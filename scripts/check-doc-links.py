#!/usr/bin/env python3
"""Every internal link in the README, the docs and the Help page must resolve.

Checks:
  - relative links and images in the top-level docs and docs/**.md point at a file
  - #anchors point at a heading that exists in the target markdown file
  - docs/manifest.json lists every doc and every slug in it has a file
  - app routes and /docs?slug= links in the Help page and the docs viewer exist

Run: python scripts/check-doc-links.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
APP = ROOT / "apps" / "web" / "src" / "app"
TOP = ["README.md", "ONBOARDING.md", "ARCHITECTURE.md", "CONTRIBUTING.md"]
# working notes and capture reports, not reader-facing docs
NOT_IN_MANIFEST = {"TRAJECTORY_MEMORY.md", "screenshots/README.md", "screenshots/atlas-e2e/report.md"}
TSX = [APP / "(app)" / "help" / "page.tsx", APP / "docs" / "DocsContent.tsx"]

LINK_OPEN = re.compile(r"\]\(")
HTML_LINK = re.compile(r'<(?:a|img)\b[^>]*\s(?:href|src)="([^"]+)"', re.I)
REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(\S+)", re.M)
FENCE = re.compile(r"^(```|~~~).*?^\1\s*$", re.M | re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$", re.M)
EXPLICIT_ANCHOR = re.compile(r'<a\s+(?:name|id)="([^"]+)"', re.I)
WEB_SRC = ROOT / "apps" / "web" / "src"
# PageHeader docSlug props, docHref() calls and literal /docs?slug= links anywhere in the web app
DOC_REF = re.compile(r"""(?:docSlug=\{?\s*["']|docHref\(\s*["']|/docs\?(?:slug|doc)=)([0-9A-Za-z_%./-]+)""")
TSX_HREF = re.compile(r"""(?:href|to)\s*[:=]\s*\{?\s*['"`](/[^'"`$]*)['"`]""")


def strip_code(text: str) -> str:
    text = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return INLINE_CODE.sub("", text)


def md_links(text: str) -> list[str]:
    # destinations may hold balanced parens, as in apps/web/src/app/(app)/...
    out = []
    for m in LINK_OPEN.finditer(text):
        i, depth, buf = m.end(), 1, []
        while i < len(text) and text[i] != "\n":
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            buf.append(c)
            i += 1
        if depth == 0:
            dest = "".join(buf).strip()
            if dest.startswith("<") and ">" in dest:
                dest = dest[1:dest.index(">")]
            dest = dest.split()[0] if dest else ""
            if dest:
                out.append(dest)
    return out


def gh_slug(heading: str) -> str:
    h = re.sub(r"<[^>]+>", "", heading)
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h)
    h = h.replace("`", "").strip().lower()
    h = re.sub(r"[^\w\- ]", "", h, flags=re.UNICODE)
    return h.replace(" ", "-")


_anchor_cache: dict[Path, set[str]] = {}


def anchors(path: Path) -> set[str]:
    if path not in _anchor_cache:
        text = FENCE.sub("", path.read_text(encoding="utf-8"))
        seen: dict[str, int] = {}
        out: set[str] = set()
        for _, title in HEADING.findall(text):
            s = gh_slug(title)
            n = seen.get(s, 0)
            out.add(s if n == 0 else f"{s}-{n}")
            seen[s] = n + 1
        out.update(a.lower() for a in EXPLICIT_ANCHOR.findall(text))
        _anchor_cache[path] = out
    return _anchor_cache[path]


def check_md(path: Path, problems: list[str]) -> int:
    text = strip_code(path.read_text(encoding="utf-8"))
    refs = md_links(text) + HTML_LINK.findall(text) + REF_DEF.findall(text)
    rel_name = path.relative_to(ROOT).as_posix()
    n = 0
    for ref in refs:
        if re.match(r"^[a-z][a-z0-9+.-]*:", ref, re.I):
            continue
        n += 1
        target_s, _, frag = ref.partition("#")
        target_s = unquote(target_s.split("?")[0])
        if not target_s:
            target = path
        elif target_s.startswith("/"):
            target = ROOT / target_s.lstrip("/")
        else:
            target = (path.parent / target_s).resolve()
        if not target.exists():
            problems.append(f"{rel_name}: broken link -> {ref}")
            continue
        if frag and target.is_file() and target.suffix == ".md":
            if frag.lower() not in anchors(target):
                problems.append(f"{rel_name}: missing anchor -> {ref}")
    return n


def app_routes() -> list[re.Pattern[str]]:
    pats = []
    for page in APP.rglob("page.tsx"):
        parts = [p for p in page.parent.relative_to(APP).parts if not (p.startswith("(") and p.endswith(")"))]
        rx = "/" + "/".join(
            "[^/]+" if p.startswith("[") and not p.startswith("[[...") else re.escape(p) for p in parts
        )
        pats.append(re.compile("^" + (rx if parts else "/") + "/?$"))
    return pats


def doc_slugs() -> set[str]:
    return {p.relative_to(DOCS).with_suffix("").as_posix() for p in DOCS.rglob("*.md")}


def check_tsx(path: Path, routes: list[re.Pattern[str]], slugs: set[str], problems: list[str]) -> int:
    text = path.read_text(encoding="utf-8")
    rel_name = path.relative_to(ROOT).as_posix()
    n = 0
    # in-page links on the Help page jump to a topic or category id
    ids = set(re.findall(r"id:\s*'([^']+)'", text)) | set(re.findall(r'id="([^"]+)"', text))
    for frag in re.findall(r"""href=["']#([^"']+)""", text):
        n += 1
        if frag not in ids:
            problems.append(f"{rel_name}: no topic with id -> #{frag}")
    for href in TSX_HREF.findall(text):
        if href.startswith("/api/") or href.startswith("//"):
            continue
        n += 1
        route, _, query = href.partition("?")
        route = route.split("#")[0]
        if route.startswith("/dev-docs/"):
            if not (DOCS / route[len("/dev-docs/"):]).exists():
                problems.append(f"{rel_name}: missing doc file -> {href}")
            continue
        if not any(r.match(route) for r in routes):
            problems.append(f"{rel_name}: no such app route -> {href}")
            continue
        m = re.search(r"(?:^|&)(?:slug|doc)=([^&#]+)", query)
        if route.rstrip("/") in ("/docs", "/dev-docs") and m and unquote(m.group(1)) not in slugs:
            problems.append(f"{rel_name}: no such doc slug -> {href}")
    return n


def check_web_slugs(slugs: set[str], problems: list[str]) -> int:
    n = 0
    for f in sorted(WEB_SRC.rglob("*.ts*")):
        if "__tests__" in f.parts:
            continue
        for raw in DOC_REF.findall(f.read_text(encoding="utf-8")):
            n += 1
            slug = unquote(raw).split("#")[0]
            if slug not in slugs:
                problems.append(f"{f.relative_to(ROOT).as_posix()}: no such doc slug -> {raw}")
    return n


def check_manifest(slugs: set[str], problems: list[str]) -> int:
    manifest = json.loads((DOCS / "manifest.json").read_text(encoding="utf-8"))
    listed: list[str] = [d["slug"] for s in manifest["sections"] for d in s["docs"]]
    for s in listed:
        if s not in slugs:
            problems.append(f"docs/manifest.json: slug has no file -> {s}")
    dupes = {s for s in listed if listed.count(s) > 1}
    for s in sorted(dupes):
        problems.append(f"docs/manifest.json: slug listed twice -> {s}")
    skip = {Path(p).with_suffix("").as_posix() for p in NOT_IN_MANIFEST}
    for s in sorted(slugs - set(listed) - skip):
        problems.append(f"docs/manifest.json: orphan doc not listed -> docs/{s}.md")
    return len(listed)


def main() -> int:
    problems: list[str] = []
    files = [ROOT / f for f in TOP if (ROOT / f).exists()] + sorted(DOCS.rglob("*.md"))
    links = sum(check_md(f, problems) for f in files)
    routes, slugs = app_routes(), doc_slugs()
    app_links = sum(check_tsx(f, routes, slugs, problems) for f in TSX if f.exists())
    app_links += check_web_slugs(slugs, problems)
    listed = check_manifest(slugs, problems)

    if problems:
        print(f"[check-doc-links] FAIL: {len(problems)} problems across {links} doc links, {app_links} app links, {listed} manifest entries")
        for line in problems:
            print(f"  - {line}")
        return 1
    print(f"[check-doc-links] OK: {links} links in {len(files)} docs and {app_links} app links and doc slugs in the web app resolve, "
          f"{listed} manifest entries match docs/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
