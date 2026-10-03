"""Turn a fetched document into stable text, plus rows for tabular kinds, so only real changes show up."""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from xml.etree import ElementTree as ET

PARSER_VERSION = "sw-1"
KINDS = ("html", "pdf", "xlsx", "csv", "json", "rss")
TABLE_KINDS = ("csv", "xlsx", "rss")
MAX_ROWS = 50_000


class NormalizeError(ValueError):
    pass


@dataclass
class Normalized:
    text: str
    title: str = ""
    # sheet or feed name -> rows, for kinds diffed row by row
    tables: dict[str, list[list[str]]] | None = None
    notes: list[str] = field(default_factory=list)


_WS = re.compile(r"[ \t  -​　]+")


def _clean_line(s: str) -> str:
    return _WS.sub(" ", s).strip()


def tidy(text: str) -> str:
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _clean_line(raw)
        if not line and (not out or not out[-1]):
            continue
        out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def decode(body: bytes, content_type: str = "") -> str:
    m = re.search(r"charset=([\w.-]+)", content_type or "", re.I)
    enc = m.group(1) if m else None
    if body.startswith(b"\xef\xbb\xbf"):
        body, enc = body[3:], "utf-8"
    if not enc:
        head = body[:2048].decode("ascii", "ignore")
        mm = re.search(r"<meta[^>]+charset=[\"']?([\w.-]+)", head, re.I)
        enc = mm.group(1) if mm else None
    for candidate in (enc, "utf-8"):
        if not candidate:
            continue
        try:
            return body.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


# HTML

_SKIP = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "nav",
    "footer",
    "aside",
    "form",
    "iframe",
    "button",
    "select",
    "canvas",
    "object",
    "head",
}
_SKIP_ROLES = {"navigation", "banner", "contentinfo", "search", "menu", "menubar"}
_VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_BLOCK = {
    "p",
    "div",
    "section",
    "article",
    "main",
    "header",
    "ul",
    "ol",
    "dl",
    "dt",
    "dd",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "blockquote",
    "pre",
    "figure",
    "figcaption",
    "address",
    "details",
    "summary",
    "caption",
    "body",
    "html",
}
_HEADING = re.compile(r"h[1-6]")


@dataclass
class _Compound:
    tag: str = ""
    id: str = ""
    classes: tuple[str, ...] = ()
    attrs: tuple[tuple[str, str | None], ...] = ()

    def matches(self, tag: str, attrs: dict[str, str]) -> bool:
        if self.tag and self.tag != "*" and self.tag != tag:
            return False
        if self.id and attrs.get("id") != self.id:
            return False
        if self.classes:
            have = set((attrs.get("class") or "").split())
            if not set(self.classes) <= have:
                return False
        for k, v in self.attrs:
            if k not in attrs or (v is not None and attrs[k] != v):
                return False
        return True


_COMPOUND = re.compile(
    r"^(?P<tag>[a-zA-Z][\w-]*|\*)?(?P<rest>(?:[#.][\w-]+|\[[\w-]+(?:=[\"']?[^\]\"']*[\"']?)?\])*)$"
)


def parse_css(selector: str) -> list[list[_Compound]]:
    """A CSS subset: tag, #id, .class, [attr] and [attr=value], descendants, and comma lists."""
    groups: list[list[_Compound]] = []
    for part in (selector or "").split(","):
        chain: list[_Compound] = []
        for token in part.replace(">", " ").split():
            m = _COMPOUND.match(token)
            if not m:
                raise NormalizeError(
                    f"The selector part {token!r} is not supported. Use tag, #id, .class "
                    "or [attr=value], separated by spaces."
                )
            rest = m.group("rest") or ""
            ids = re.findall(r"#([\w-]+)", rest)
            attrs = tuple(
                (a, v if eq else None)
                for a, eq, v in re.findall(
                    r"\[([\w-]+)(=)?[\"']?([^\]\"']*)[\"']?\]", rest
                )
            )
            chain.append(
                _Compound(
                    tag=(m.group("tag") or "").lower(),
                    id=ids[0] if ids else "",
                    classes=tuple(re.findall(r"\.([\w-]+)", rest)),
                    attrs=tuple((a.lower(), v) for a, v in attrs),
                )
            )
        if chain:
            groups.append(chain)
    if not groups:
        raise NormalizeError("The selector is empty.")
    return groups


class _HTMLText(HTMLParser):
    def __init__(self, selector: list[list[_Compound]] | None) -> None:
        super().__init__(convert_charrefs=True)
        self.selector = selector
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.skip_depth: int | None = None
        self.capture_depth: int | None = None
        self.matched = False
        self.cells_in_row = 0

    def _selected(self, tag: str, attrs: dict[str, str]) -> bool:
        for chain in self.selector or ():
            if not chain[-1].matches(tag, attrs):
                continue
            i = len(chain) - 2
            for t, a in reversed(self.stack):
                if i < 0:
                    break
                if chain[i].matches(t, a):
                    i -= 1
            if i < 0:
                return True
        return False

    def _emitting(self) -> bool:
        if self.skip_depth is not None:
            return False
        return self.selector is None or self.capture_depth is not None

    def _out(self, s: str) -> None:
        if self._emitting():
            self.parts.append(s)

    def handle_starttag(self, tag: str, attrs_list: list) -> None:
        attrs = {k.lower(): (v or "") for k, v in attrs_list}
        if tag == "title" and not any(t == "body" for t, _ in self.stack):
            self.in_title = True
        if tag in _VOID:
            if tag == "br":
                self._out("\n")
            elif tag == "hr":
                self._out("\n\n")
            elif tag == "img" and attrs.get("alt", "").strip():
                self._out(f" {attrs['alt'].strip()} ")
            return
        hidden = (
            tag in _SKIP
            or attrs.get("role", "").lower() in _SKIP_ROLES
            or attrs.get("aria-hidden", "").lower() == "true"
            or "hidden" in attrs
        )
        depth = len(self.stack)
        if (
            self.selector is not None
            and self.capture_depth is None
            and self.skip_depth is None
            and self._selected(tag, attrs)
        ):
            self.capture_depth = depth
            self.matched = True
            self.parts.append("\n\n")
        self.stack.append((tag, attrs))
        if self.skip_depth is None and hidden:
            self.skip_depth = depth
        if _HEADING.fullmatch(tag):
            self._out("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self._out("\n- ")
        elif tag == "tr":
            self._out("\n")
            self.cells_in_row = 0
        elif tag in ("td", "th"):
            if self.cells_in_row:
                self._out(" | ")
            self.cells_in_row += 1
        elif tag in _BLOCK:
            self._out("\n\n" if tag == "p" else "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag in _VOID:
            return
        idx = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                idx = i
                break
        if idx is None:
            return
        if _HEADING.fullmatch(tag) or tag == "p":
            self._out("\n\n")
        elif tag in _BLOCK:
            self._out("\n")
        del self.stack[idx:]
        if self.skip_depth is not None and len(self.stack) <= self.skip_depth:
            self.skip_depth = None
        if self.capture_depth is not None and len(self.stack) <= self.capture_depth:
            self.capture_depth = None
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
            return
        self._out(data.replace("\n", " "))


def html_text(body: bytes, content_type: str = "", selector: str = "") -> Normalized:
    sel = parse_css(selector) if selector and selector.strip() else None
    p = _HTMLText(sel)
    p.feed(decode(body, content_type))
    p.close()
    notes = []
    if sel is not None and not p.matched:
        notes.append(f"The selector {selector!r} matched nothing on the page.")
    return Normalized(
        text=tidy("".join(p.parts)),
        title=_clean_line("".join(p.title_parts))[:500],
        notes=notes,
    )


# PDF


def pdf_text(body: bytes) -> Normalized:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise NormalizeError("PDF support needs pypdf installed.") from e
    try:
        reader = PdfReader(io.BytesIO(body))
        pages = [
            f"[page {i}]\n{tidy(page.extract_text() or '')}"
            for i, page in enumerate(reader.pages, 1)
        ]
        try:
            title = str((reader.metadata or {}).get("/Title") or "")
        except Exception:  # noqa: BLE001
            title = ""
    except Exception as e:  # noqa: BLE001
        raise NormalizeError(f"The PDF could not be read: {e}") from e
    return Normalized(text="\n\n".join(pages), title=_clean_line(title)[:500])


# Tables


def _cell(v: Any) -> str:
    s = "" if v is None else str(v)
    if re.fullmatch(r"-?\d+\.0+", s):
        s = s.split(".")[0]
    return _clean_line(s)


def _trim_rows(rows: list[list[str]]) -> list[list[str]]:
    out = []
    for r in rows:
        while r and r[-1] == "":
            r = r[:-1]
        if r:
            out.append(r)
    return out[:MAX_ROWS]


def _rows_text(tables: dict[str, list[list[str]]]) -> str:
    blocks = []
    for name, rows in tables.items():
        lines = "\n".join(" | ".join(r) for r in rows)
        blocks.append(f"## {name}\n{lines}" if name else lines)
    return "\n\n".join(blocks)


def csv_rows(body: bytes, content_type: str = "") -> Normalized:
    text = decode(body, content_type)
    try:
        dialect: Any = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = _trim_rows(
        [[_cell(c) for c in r] for r in csv.reader(io.StringIO(text), dialect)]
    )
    tables = {"": rows}
    return Normalized(text=_rows_text(tables), tables=tables)


_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS = {"m": _M}
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _col_index(ref: str) -> int:
    m = re.match(r"[A-Z]+", ref)
    n = 0
    for ch in m.group(0) if m else "A":
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def xlsx_rows(body: bytes, selector: str = "") -> Normalized:
    """Read cell values straight from the workbook XML, so the result never depends on an optional library."""
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as e:
        raise NormalizeError("This is not an xlsx workbook.") from e
    names = set(z.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_M}}}t")))
    rels: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
            target = (rel.get("Target") or "").lstrip("/")
            rels[rel.get("Id") or ""] = (
                target if target.startswith("xl/") else f"xl/{target}"
            )
    sheets: list[tuple[str, str]] = []
    if "xl/workbook.xml" in names:
        for s in ET.fromstring(z.read("xl/workbook.xml")).iter(f"{{{_M}}}sheet"):
            path = rels.get(s.get(_REL) or "", "")
            if path in names:
                sheets.append((s.get("name") or path, path))
    if not sheets:
        sheets = [
            (n.rsplit("/", 1)[-1].removesuffix(".xml"), n)
            for n in sorted(names)
            if n.startswith("xl/worksheets/sheet")
        ]
    wanted = (selector or "").strip()
    if wanted:
        sheets = [s for s in sheets if s[0] == wanted]
        if not sheets:
            raise NormalizeError(f"The workbook has no sheet named {wanted!r}.")
    tables: dict[str, list[list[str]]] = {}
    for name, path in sheets:
        rows: list[list[str]] = []
        for row in ET.fromstring(z.read(path)).iter(f"{{{_M}}}row"):
            cells: dict[int, str] = {}
            for i, c in enumerate(row.findall("m:c", _NS)):
                ref = c.get("r") or ""
                col = _col_index(ref) if ref else i
                t = c.get("t")
                v = c.find("m:v", _NS)
                if t == "s" and v is not None and v.text is not None:
                    idx = int(v.text)
                    val = shared[idx] if idx < len(shared) else ""
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{{{_M}}}t"))
                elif t == "b":
                    val = "TRUE" if (v is not None and v.text == "1") else "FALSE"
                else:
                    val = v.text if v is not None and v.text is not None else ""
                cells[col] = _cell(val)
            if cells:
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        tables[name] = _trim_rows(rows)
    return Normalized(text=_rows_text(tables), tables=tables)


# JSON


def json_pointer(doc: Any, pointer: str) -> Any:
    if pointer in ("", "/"):
        return doc
    if not pointer.startswith("/"):
        raise NormalizeError("A JSON selector is a JSON pointer such as /data/items.")
    cur = doc
    for raw in pointer.split("/")[1:]:
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            try:
                cur = cur[int(key)]
            except (ValueError, IndexError) as e:
                raise NormalizeError(f"The pointer {pointer} has no item {key}.") from e
        elif isinstance(cur, dict):
            if key not in cur:
                raise NormalizeError(f"The pointer {pointer} has no field {key!r}.")
            cur = cur[key]
        else:
            raise NormalizeError(f"The pointer {pointer} goes past a plain value.")
    return cur


def json_text(body: bytes, content_type: str = "", selector: str = "") -> Normalized:
    try:
        doc = json.loads(decode(body, content_type))
    except ValueError as e:
        raise NormalizeError(f"This is not valid JSON: {e}") from e
    if selector and selector.strip():
        doc = json_pointer(doc, selector.strip())
    return Normalized(
        text=json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False)
    )


# RSS and Atom


def _local(tag: Any) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def _child(el: ET.Element, name: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _child_text(el: ET.Element, *names: str) -> str:
    for n in names:
        c = _child(el, n)
        if c is None:
            continue
        if n == "link" and c.get("href"):
            return c.get("href") or ""
        txt = "".join(c.itertext())
        if txt.strip():
            return txt
    return ""


def _strip_html(s: str) -> str:
    if "<" not in s:
        return _clean_line(s)
    return _clean_line(
        html_text(s.encode("utf-8"), "text/html; charset=utf-8").text.replace("\n", " ")
    )


def rss_rows(body: bytes) -> Normalized:
    if b"<!ENTITY" in body[:8192]:
        raise NormalizeError("Feeds that declare XML entities are refused.")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise NormalizeError(f"This is not a valid RSS or Atom feed: {e}") from e
    channel = _child(root, "channel") if _local(root.tag) == "rss" else root
    if channel is None:
        channel = root
    title = _clean_line(_child_text(channel, "title"))
    rows = [["id", "title", "published", "link", "summary"]]
    for it in (c for c in channel.iter() if _local(c.tag) in ("item", "entry")):
        link = _clean_line(_child_text(it, "link"))
        rows.append(
            [
                _clean_line(_child_text(it, "guid", "id")) or link,
                _strip_html(_child_text(it, "title")),
                _clean_line(_child_text(it, "pubdate", "published", "updated", "date")),
                link,
                _strip_html(_child_text(it, "description", "summary", "content"))[
                    :1000
                ],
            ]
        )
    text = "\n\n".join(
        "\n".join(x for x in (f"## {r[1]}", r[2], r[3], r[4]) if x) for r in rows[1:]
    )
    return Normalized(
        text=text, title=title[:500], tables={title or "feed": rows[:MAX_ROWS]}
    )


def normalize(
    kind: str, body: bytes, content_type: str = "", selector: str = ""
) -> Normalized:
    n = _normalize(kind, body, content_type, selector)
    # Postgres text and jsonb refuse NUL characters
    n.text = n.text.replace("\x00", "")
    n.title = n.title.replace("\x00", "")
    if n.tables is not None:
        n.tables = {
            k.replace("\x00", ""): [[c.replace("\x00", "") for c in r] for r in rows]
            for k, rows in n.tables.items()
        }
    return n


def _normalize(kind: str, body: bytes, content_type: str, selector: str) -> Normalized:
    kind = (kind or "").lower()
    if kind == "html":
        return html_text(body, content_type, selector)
    if kind == "pdf":
        return pdf_text(body)
    if kind == "csv":
        return csv_rows(body, content_type)
    if kind == "xlsx":
        return xlsx_rows(body, selector)
    if kind == "json":
        return json_text(body, content_type, selector)
    if kind == "rss":
        return rss_rows(body)
    raise NormalizeError(
        f"Unknown source kind {kind!r}. Use one of {', '.join(KINDS)}."
    )


def guess_kind(content_type: str, url: str = "", body: bytes = b"") -> str:
    ct = (content_type or "").lower()
    u = (url or "").lower().split("?", 1)[0]
    if "pdf" in ct or u.endswith(".pdf") or body[:5] == b"%PDF-":
        return "pdf"
    if "spreadsheetml" in ct or u.endswith(".xlsx"):
        return "xlsx"
    if "csv" in ct or u.endswith(".csv"):
        return "csv"
    if "rss" in ct or "atom" in ct or u.endswith((".rss", ".atom")):
        return "rss"
    if "json" in ct or u.endswith(".json"):
        return "json"
    head = body[:512].lstrip().lower()
    if head.startswith(b"<?xml") and (b"<rss" in head or b"<feed" in head):
        return "rss"
    if head[:1] in (b"{", b"["):
        return "json"
    return "html"
