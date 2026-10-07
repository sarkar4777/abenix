"""Turns an uploaded spreadsheet into a pf_ table plus a portfolio schema that queries it."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 50_000
MAX_COLUMNS = 100
PREVIEW_ROWS = 20
MAX_SKIP_REASONS = 100
INSERT_CHUNK = 1000
MAX_NAME = 59
TABLE_MARKER = "abenix:portfolio-import"
SYSTEM_COLUMNS = {"id", "owner_id", "created_at"}
TYPES = ("text", "number", "date", "boolean")
TABLE_RE = re.compile(r"^pf_[0-9a-f]{8}_[a-z0-9_]+$")
IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
SAMPLE_PATH = (
    Path(__file__).resolve().parent / "portfolio_templates" / "energy_trades_sample.csv"
)

# postgres reserved words, the runtime splices identifiers unquoted so these break queries
SQL_RESERVED = frozenset(
    """
    all analyse analyze and any array as asc asymmetric authorization binary both case cast
    check collate collation column concurrently constraint create cross current_catalog
    current_date current_role current_schema current_time current_timestamp current_user
    default deferrable desc distinct do else end except false fetch for foreign freeze from
    full grant group having ilike in initially inner intersect into is isnull join lateral
    leading left like limit localtime localtimestamp natural not notnull null offset on only
    or order outer overlaps placing primary references returning right select session_user
    similar some symmetric system_user table tablesample then to trailing true union unique
    user using variadic verbose when where window with
    """.split()
)

BOOL_TRUE = {"true", "yes", "y", "t"}
BOOL_FALSE = {"false", "no", "n", "f"}
NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")
LEADING_ZERO_RE = re.compile(r"^[+-]?0\d")
ISO_DATE_RE = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$")
ISO_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$"
)
DMY_RE = re.compile(r"^(\d{1,2})([./-])(\d{1,2})\2(\d{4})$")


class SpreadsheetError(ValueError):
    """A problem the user can fix, with a status code and optional details."""

    def __init__(
        self,
        message: str,
        status: int = 422,
        code: str = "SPREADSHEET_INVALID",
        details: dict | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details or {}


@dataclass
class Sheet:
    headers: list[str]
    rows: list[tuple[int, list[str]]]
    skipped: list[tuple[int, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def xlsx_supported() -> bool:
    return importlib.util.find_spec("openpyxl") is not None


def accepted_formats() -> list[str]:
    return ["csv", "xlsx"] if xlsx_supported() else ["csv"]


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def snake_case(raw: Any, fallback: str = "column", limit: int = MAX_NAME) -> str:
    s = unicodedata.normalize("NFKD", str(raw or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if not s:
        s = fallback
    if s[0].isdigit():
        s = f"c_{s}"
    return s[:limit].rstrip("_")


def safe_column_name(raw: Any, taken: set[str], fallback: str = "column") -> str:
    """snake_case, steer clear of system and reserved words, then make unique."""
    base = snake_case(raw, fallback)
    if base in SYSTEM_COLUMNS:
        base = f"source_{base}"
    elif base in SQL_RESERVED:
        base = f"{base}_value"
    name, n = base, 2
    while name in taken:
        suffix = f"_{n}"
        name = base[: MAX_NAME - len(suffix)] + suffix
        n += 1
    taken.add(name)
    return name


def table_name_for(tenant_id: Any, domain: str) -> str:
    hex8 = uuid.UUID(str(tenant_id)).hex[:8]
    d = snake_case(domain, "data", limit=200)
    name = f"pf_{hex8}_{d}"
    if len(name) > 63:
        digest = hashlib.sha1(d.encode()).hexdigest()[:8]
        name = f"{name[:54].rstrip('_')}_{digest}"
    return name


def is_import_table(name: Any, tenant_id: Any, domain: str) -> bool:
    return (
        isinstance(name, str)
        and bool(TABLE_RE.match(name))
        and name == table_name_for(tenant_id, domain)
    )


def humanize(name: str) -> str:
    s = name.replace("_", " ").strip()
    return s[:1].upper() + s[1:] if s else name


# reading


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _too_many_rows(n: int) -> SpreadsheetError:
    return SpreadsheetError(
        f"The file has more than {MAX_ROWS:,} rows, which is the limit for one upload. "
        "Split it into smaller files, create the schema from the first one and append the rest.",
        413,
        "SPREADSHEET_TOO_MANY_ROWS",
    )


def _finish(
    header: list[str], body: list[tuple[int, list[str]]], warnings: list[str]
) -> Sheet:
    if not header or not any(h.strip() for h in header):
        raise SpreadsheetError(
            "The first row should hold column names, but it is empty."
        )
    while (
        header
        and not header[-1].strip()
        and all(len(c) < len(header) or not c[len(header) - 1].strip() for _, c in body)
    ):
        header = header[:-1]
    if len(header) > MAX_COLUMNS:
        raise SpreadsheetError(
            f"The file has {len(header)} columns. The limit is {MAX_COLUMNS}. Remove the columns you don't need and try again."
        )
    sheet = Sheet(headers=[h.strip() for h in header], rows=[], warnings=warnings)
    width = len(header)
    for line, cells in body:
        if not any((c or "").strip() for c in cells):
            continue
        if len(cells) > width and any((c or "").strip() for c in cells[width:]):
            sheet.skipped.append(
                (line, f"has {len(cells)} values but the header has {width} columns")
            )
            continue
        cells = (cells + [""] * width)[:width]
        sheet.rows.append((line, cells))
        if len(sheet.rows) > MAX_ROWS:
            raise _too_many_rows(len(sheet.rows))
    if not sheet.rows:
        raise SpreadsheetError("The file has column names but no rows of data.")
    return sheet


def _guess_delimiter(content: str) -> str:
    # the header line is the most reliable signal, csv.Sniffer trips on ragged rows
    first = next((line for line in content.splitlines() if line.strip()), "")
    counts = {d: first.count(d) for d in (",", ";", "\t", "|")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] else ","


def _read_csv(data: bytes, delimiter: str | None) -> Sheet:
    content = _decode(data)
    if delimiter is None:
        delimiter = _guess_delimiter(content)
    reader = csv.reader(io.StringIO(content, newline=""), delimiter=delimiter)
    header: list[str] | None = None
    body: list[tuple[int, list[str]]] = []
    try:
        for row in reader:
            line = reader.line_num
            if header is None:
                if any(c.strip() for c in row):
                    header = row
                continue
            body.append((line, row))
            if len(body) > MAX_ROWS + 1000:
                raise _too_many_rows(len(body))
    except csv.Error as e:
        raise SpreadsheetError(
            f"The file could not be read as CSV near line {reader.line_num}: {e}"
        ) from e
    return _finish(header or [], body, [])


def _cell_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime):
        return (
            v.date().isoformat()
            if v.time() == time(0) and v.tzinfo is None
            else v.isoformat()
        )
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    return str(v)


def _read_xlsx(data: bytes) -> Sheet:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise SpreadsheetError(f"The Excel file could not be opened: {e}") from e
    try:
        ws = wb.worksheets[0]
        warnings = []
        if len(wb.worksheets) > 1:
            warnings.append(
                f"Only the first sheet, {ws.title}, was read. Upload the other sheets as separate files."
            )
        header: list[str] | None = None
        body: list[tuple[int, list[str]]] = []
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            cells = [_cell_text(v) for v in row]
            if header is None:
                if any(c.strip() for c in cells):
                    header = cells
                continue
            body.append((i, cells))
            if len(body) > MAX_ROWS + 1000:
                raise _too_many_rows(len(body))
    finally:
        wb.close()
    return _finish(header or [], body, warnings)


def read_sheet(filename: str, data: bytes) -> Sheet:
    if len(data) > MAX_BYTES:
        raise SpreadsheetError(
            f"The file is {_mb(len(data))}. The limit is {_mb(MAX_BYTES)}. "
            "Split it into smaller files, create the schema from the first one and append the rest.",
            413,
            "SPREADSHEET_TOO_LARGE",
        )
    if not data.strip():
        raise SpreadsheetError("The file is empty.")
    ext = Path(filename or "").suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        if not xlsx_supported():
            raise SpreadsheetError(
                "Excel files can't be read on this server yet. In Excel choose File, Save As, "
                "CSV (comma delimited) and upload the CSV.",
                415,
                "SPREADSHEET_FORMAT",
            )
        return _read_xlsx(data)
    if ext in (".xls", ".numbers", ".ods"):
        raise SpreadsheetError(
            f"{ext} files are not supported. Save the sheet as CSV"
            + (" or .xlsx" if xlsx_supported() else "")
            + " and upload that.",
            415,
            "SPREADSHEET_FORMAT",
        )
    if ext in ("", ".csv", ".txt", ".tsv"):
        return _read_csv(data, "\t" if ext == ".tsv" else None)
    raise SpreadsheetError(
        "Upload a .csv file" + (" or an .xlsx file" if xlsx_supported() else "") + ".",
        415,
        "SPREADSHEET_FORMAT",
    )


# types


def parse_number(s: str) -> float | None:
    v = s.strip()
    if THOUSANDS_RE.match(v):
        v = v.replace(",", "")
    if not NUM_RE.match(v):
        return None
    return float(v)


def parse_bool(s: str) -> bool | None:
    v = s.strip().lower()
    if v in BOOL_TRUE or v == "1":
        return True
    if v in BOOL_FALSE or v == "0":
        return False
    return None


def _date_order(values: list[str]) -> tuple[str | None, bool]:
    """Return (order, has_time) when every value is a date, order is iso, dmy or mdy."""
    has_time = False
    firsts, seconds = [], []
    for v in values:
        if ISO_DT_RE.match(v):
            try:
                datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                return None, False
            has_time = True
            continue
        m = ISO_DATE_RE.match(v)
        if m:
            try:
                date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None, False
            continue
        m = DMY_RE.match(v)
        if not m:
            return None, False
        firsts.append(int(m.group(1)))
        seconds.append(int(m.group(3)))
    if not firsts:
        return "iso", has_time
    day_first = any(a > 12 for a in firsts)
    month_first = any(b > 12 for b in seconds)
    if day_first and month_first:
        return None, False
    order = "mdy" if month_first else "dmy"
    for v in values:
        if (
            not ISO_DT_RE.match(v)
            and not ISO_DATE_RE.match(v)
            and parse_date(v, order) is None
        ):
            return None, False
    return order, has_time


def parse_date(s: str, order: str = "iso") -> date | datetime | None:
    v = s.strip()
    if ISO_DT_RE.match(v):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    m = ISO_DATE_RE.match(v)
    try:
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = DMY_RE.match(v)
        if m:
            a, b, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
            return date(y, b, a) if order != "mdy" else date(y, a, b)
    except ValueError:
        return None
    return None


def infer_column(values: list[str]) -> dict:
    """Pick number, date, boolean or text for a column from all its non-empty values."""
    vals = [v.strip() for v in values if v and v.strip()]
    out = {
        "type": "text",
        "date_order": None,
        "has_time": False,
        "empty": len(values) - len(vals),
    }
    if not vals:
        return out
    lowered = {v.lower() for v in vals}
    if lowered <= (BOOL_TRUE | BOOL_FALSE):
        out["type"] = "boolean"
        return out
    if all(parse_number(v) is not None for v in vals) and not any(
        LEADING_ZERO_RE.match(v) and "." not in v for v in vals
    ):
        out["type"] = "number"
        return out
    order, has_time = _date_order(vals)
    if order:
        out.update(type="date", date_order=order, has_time=has_time)
    return out


def sql_type(col: dict) -> str:
    t = col["type"]
    if t == "number":
        return "double precision"
    if t == "boolean":
        return "boolean"
    if t == "date":
        return "timestamptz" if col.get("has_time") else "date"
    return "text"


def type_from_pg(data_type: str) -> tuple[str, bool]:
    d = (data_type or "").lower()
    if d in ("double precision", "real", "numeric", "integer", "bigint", "smallint"):
        return "number", False
    if d == "boolean":
        return "boolean", False
    if d == "date":
        return "date", False
    if d.startswith("timestamp"):
        return "date", True
    return "text", False


def convert(raw: str, col: dict) -> Any:
    """Cell text to the python value for the column, ValueError says why it doesn't fit."""
    v = (raw or "").strip()
    if not v:
        return None
    t = col["type"]
    if t == "number":
        n = parse_number(v)
        if n is None:
            raise ValueError("is not a number")
        return n
    if t == "boolean":
        b = parse_bool(v)
        if b is None:
            raise ValueError("is not yes/no or true/false")
        return b
    if t == "date":
        d = parse_date(v, col.get("date_order") or "iso")
        if d is None:
            raise ValueError("is not a date like 2026-03-31")
        if col.get("has_time"):
            if not isinstance(d, datetime):
                d = datetime.combine(d, time(0), tzinfo=timezone.utc)
            return d
        return d.date() if isinstance(d, datetime) else d
    return v


def preview(sheet: Sheet) -> dict:
    taken: set[str] = set()
    columns = []
    for i, header in enumerate(sheet.headers):
        values = [cells[i] for _, cells in sheet.rows]
        info = infer_column(values)
        name = safe_column_name(header, taken, f"column_{i + 1}")
        samples = []
        for v in values:
            v = v.strip()
            if v and v not in samples:
                samples.append(v)
            if len(samples) == 3:
                break
        columns.append(
            {
                "index": i,
                "source": header,
                "name": name,
                "label": header.strip() or humanize(name),
                "type": info["type"],
                "empty": info["empty"],
                "samples": samples,
                "note": (
                    "Read as day/month/year"
                    if info["date_order"] == "dmy"
                    else (
                        "Read as month/day/year"
                        if info["date_order"] == "mdy"
                        else None
                    )
                ),
            }
        )
    title = next(
        (c["name"] for c in columns if c["type"] == "text"),
        columns[0]["name"] if columns else None,
    )
    return {
        "columns": columns,
        "rows": [cells for _, cells in sheet.rows[:PREVIEW_ROWS]],
        "total_rows": len(sheet.rows),
        "skipped_on_read": [
            {"row": r, "reason": why} for r, why in sheet.skipped[:MAX_SKIP_REASONS]
        ],
        "skipped_on_read_count": len(sheet.skipped),
        "warnings": sheet.warnings,
        "suggested_title_column": title,
        "limits": {
            "max_rows": MAX_ROWS,
            "max_bytes": MAX_BYTES,
            "max_columns": MAX_COLUMNS,
        },
    }


# plan


def _values(sheet: Sheet, idx: int) -> list[str]:
    return [cells[idx].strip() for _, cells in sheet.rows if cells[idx].strip()]


def date_order_of(sheet: Sheet, idx: int) -> str:
    return _date_order(_values(sheet, idx))[0] or "iso"


def resolve_plan(
    sheet: Sheet, plan_columns: list[dict], title_column: str | None
) -> tuple[list[dict], str]:
    """Check the user's column choices against the file and return the final columns and title."""
    if not isinstance(plan_columns, list) or not plan_columns:
        raise SpreadsheetError("Pick at least one column to import.")
    taken: set[str] = set()
    final: list[dict] = []
    by_requested: dict[str, str] = {}
    for pc in plan_columns:
        if not isinstance(pc, dict):
            raise SpreadsheetError("Each column choice must be an object.")
        if not pc.get("include", True):
            continue
        idx = pc.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(sheet.headers):
            raise SpreadsheetError(
                "The column choices don't match this file. Preview the file again."
            )
        if (
            pc.get("source") is not None
            and str(pc["source"]).strip() != sheet.headers[idx]
        ):
            raise SpreadsheetError(
                "The column choices don't match this file. Preview the file again."
            )
        typ = pc.get("type") or "text"
        if typ not in TYPES:
            raise SpreadsheetError(
                f"Column {sheet.headers[idx]!r} has type {typ!r}. Use one of: {', '.join(TYPES)}."
            )
        requested = str(pc.get("name") or sheet.headers[idx])
        name = safe_column_name(requested, taken, f"column_{idx + 1}")
        by_requested[requested] = name
        label = (
            str(pc.get("label") or "").strip() or sheet.headers[idx] or humanize(name)
        )
        col = {
            "index": idx,
            "name": name,
            "label": label[:120],
            "type": typ,
            "date_order": None,
            "has_time": False,
        }
        if typ == "date":
            col["date_order"] = date_order_of(sheet, idx)
            col["has_time"] = _date_order(_values(sheet, idx))[1]
        final.append(col)
    if not final:
        raise SpreadsheetError("Pick at least one column to import.")
    names = [c["name"] for c in final]
    title = by_requested.get(title_column or "", title_column)
    if title not in names:
        title = next((c["name"] for c in final if c["type"] == "text"), names[0])
    return final, title


def build_rows(
    sheet: Sheet, columns: list[dict]
) -> tuple[list[list[Any]], list[tuple[int, str]]]:
    rows: list[list[Any]] = []
    skipped: list[tuple[int, str]] = list(sheet.skipped)
    for line, cells in sheet.rows:
        values = []
        for col in columns:
            raw = cells[col["index"]]
            try:
                values.append(convert(raw, col))
            except ValueError as e:
                shown = raw.strip()
                shown = shown if len(shown) <= 40 else shown[:37] + "..."
                skipped.append((line, f'"{shown}" in {col["label"]} {e}'))
                break
        else:
            rows.append(values)
    return rows, skipped


def schema_type(col: dict) -> str:
    if col["type"] == "number":
        return "number"
    if col["type"] == "date":
        return "datetime" if col.get("has_time") else "date"
    if col["type"] == "boolean":
        return "boolean"
    return "string"


def build_schema_json(
    *,
    domain: str,
    label: str,
    description: str | None,
    record_noun: str,
    record_noun_plural: str,
    table: str,
    columns: list[dict],
    title_column: str,
) -> dict:
    ordered = sorted(columns, key=lambda c: c["name"] != title_column)
    text_cols = [c["name"] for c in ordered if c["type"] == "text"]
    num_cols = [c for c in ordered if c["type"] == "number"]
    aggs: dict[str, dict] = {
        "record_count": {"sql": "count(*)", "label": f"Number of {record_noun_plural}"},
    }
    for c in num_cols[:10]:
        aggs[f"total_{c['name']}"[:63]] = {
            "sql": f"sum({c['name']})",
            "label": f"Total {c['label']}",
            "format": "{:,.2f}",
        }
        aggs[f"avg_{c['name']}"[:63]] = {
            "sql": f"avg({c['name']})",
            "label": f"Average {c['label']}",
            "format": "{:,.2f}",
        }
    main: dict[str, Any] = {
        "name": table,
        "primary_key": "id",
        "user_scope_column": "owner_id",
        "title_column": title_column,
        "created_at_column": "created_at",
        "list_columns": ["id"] + [c["name"] for c in ordered[:30]],
        "columns": {"id": {"type": "uuid", "label": "ID"}}
        | {c["name"]: {"type": schema_type(c), "label": c["label"]} for c in ordered},
        "summary_aggregations": aggs,
    }
    if text_cols:
        main["search_columns"] = text_cols[:10]
    domain_block = {
        "name": domain,
        "label": label,
        "record_noun": record_noun,
        "record_noun_plural": record_noun_plural,
    }
    if description:
        domain_block["description"] = description
    return {
        "domain": domain_block,
        "main_table": main,
        "related_tables": [],
        "source": {"kind": "spreadsheet", "table": table},
    }


def merge_new_columns(schema_json: dict, new_cols: list[dict]) -> dict:
    """Append columns added on re-upload without touching what the user already edited."""
    main = schema_json.setdefault("main_table", {})
    cols = main.setdefault("columns", {})
    lists = main.setdefault("list_columns", ["id"])
    aggs = main.setdefault("summary_aggregations", {})
    for c in new_cols:
        cols.setdefault(c["name"], {"type": schema_type(c), "label": c["label"]})
        if c["name"] not in lists and len(lists) < 31:
            lists.append(c["name"])
        if c["type"] == "text":
            search = main.setdefault("search_columns", [])
            if c["name"] not in search and len(search) < 10:
                search.append(c["name"])
        if c["type"] == "number":
            aggs.setdefault(
                f"total_{c['name']}"[:63],
                {
                    "sql": f"sum({c['name']})",
                    "label": f"Total {c['label']}",
                    "format": "{:,.2f}",
                },
            )
            aggs.setdefault(
                f"avg_{c['name']}"[:63],
                {
                    "sql": f"avg({c['name']})",
                    "label": f"Average {c['label']}",
                    "format": "{:,.2f}",
                },
            )
    return schema_json


def schema_source_table(schema_json: Any) -> str | None:
    if not isinstance(schema_json, dict):
        return None
    src = schema_json.get("source")
    if (
        isinstance(src, dict)
        and src.get("kind") == "spreadsheet"
        and isinstance(src.get("table"), str)
    ):
        return src["table"]
    return None


# database


def _check_ident(name: str) -> str:
    if not IDENT.match(name) or len(name) > 63:
        raise SpreadsheetError(f"Unsafe name {name!r}", 400)
    return name


def marker_for(tenant_id: Any) -> str:
    return f"{TABLE_MARKER}:{uuid.UUID(str(tenant_id))}"


async def table_state(db: Any, table: str, tenant_id: Any) -> dict:
    """exists, ours (carries this tenant's import marker) and {column: (type, has_time)} for a table."""
    _check_ident(table)
    row = (
        await db.execute(
            text(
                "SELECT to_regclass(:t) IS NOT NULL AS present, obj_description(to_regclass(:t), 'pg_class') AS note"
            ),
            {"t": table},
        )
    ).first()
    present = bool(row and row[0])
    if not present:
        return {"exists": False, "ours": False, "columns": {}}
    cols = (
        await db.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = ANY(current_schemas(false)) AND table_name = :t ORDER BY ordinal_position"
            ),
            {"t": table},
        )
    ).all()
    return {
        "exists": True,
        "ours": row[1] == marker_for(tenant_id),
        "columns": {c: type_from_pg(dt) for c, dt in cols},
    }


async def create_table(
    db: Any, table: str, columns: list[dict], tenant_id: Any
) -> None:
    _check_ident(table)
    defs = ",\n  ".join(f"{_check_ident(c['name'])} {sql_type(c)}" for c in columns)
    await db.execute(
        text(
            f"CREATE TABLE {table} (\n"
            "  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),\n"
            "  owner_id uuid NOT NULL,\n"
            "  created_at timestamptz NOT NULL DEFAULT now(),\n"
            f"  {defs}\n)"
        )
    )
    idx = "ix_" + hashlib.sha1(table.encode()).hexdigest()[:16] + "_owner"
    await db.execute(text(f"CREATE INDEX {idx} ON {table} (owner_id)"))
    await db.execute(text(f"COMMENT ON TABLE {table} IS '{marker_for(tenant_id)}'"))


async def add_columns(db: Any, table: str, columns: list[dict]) -> None:
    _check_ident(table)
    for c in columns:
        await db.execute(
            text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {_check_ident(c['name'])} {sql_type(c)}"
            )
        )


async def delete_owner_rows(db: Any, table: str, owner_id: Any) -> int:
    _check_ident(table)
    res = await db.execute(
        text(f"DELETE FROM {table} WHERE owner_id = :owner"), {"owner": owner_id}
    )
    return int(getattr(res, "rowcount", 0) or 0)


async def insert_rows(
    db: Any, table: str, columns: list[dict], rows: list[list[Any]], owner_id: Any
) -> int:
    _check_ident(table)
    names = ", ".join(_check_ident(c["name"]) for c in columns)
    binds = ", ".join(f":c{i}" for i in range(len(columns)))
    stmt = text(f"INSERT INTO {table} (owner_id, {names}) VALUES (:owner, {binds})")
    for start in range(0, len(rows), INSERT_CHUNK):
        chunk = rows[start : start + INSERT_CHUNK]
        await db.execute(
            stmt,
            [
                {"owner": owner_id} | {f"c{i}": v for i, v in enumerate(r)}
                for r in chunk
            ],
        )
    return len(rows)


async def count_owner_rows(db: Any, table: str, owner_id: Any) -> int:
    _check_ident(table)
    return int(
        (
            await db.execute(
                text(f"SELECT count(*) FROM {table} WHERE owner_id = :owner"),
                {"owner": owner_id},
            )
        ).scalar()
        or 0
    )


async def drop_table(db: Any, table: str) -> None:
    _check_ident(table)
    if not TABLE_RE.match(table):
        raise SpreadsheetError(
            "Only tables created from a spreadsheet can be dropped here.", 400
        )
    await db.execute(text(f"DROP TABLE IF EXISTS {table}"))


def sample_bytes() -> bytes:
    return SAMPLE_PATH.read_bytes()
