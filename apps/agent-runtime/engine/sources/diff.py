"""Change detection between two normalised snapshots: a line diff for text, a row diff for tables."""

from __future__ import annotations

import difflib
import hashlib
import re
from collections import Counter
from typing import Any

MAX_DIFF_LINES = 4000
MAX_TABLE_ROWS = 2000
_SIGNAL = re.compile(
    r"\b(shall|must|required?|prohibit\w*|deadline|penalt\w*|effective|repeal\w*|amend\w*|"
    r"obligation\w*|exempt\w*|threshold|rate|fee|fine|sanction\w*|in force|apply|applies)\b",
    re.I,
)
_NUMBER = re.compile(r"\d")


def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def text_diff(old: str, new: str, context: int = 3) -> dict[str, Any]:
    a = old.split("\n") if old else []
    b = new.split("\n") if new else []
    sm = difflib.SequenceMatcher(None, a, b, autojunk=len(a) + len(b) > 40_000)
    hunks: list[dict[str, Any]] = []
    added: list[str] = []
    removed: list[str] = []
    emitted = 0
    truncated = False
    for group in sm.get_grouped_opcodes(context):
        first, last = group[0], group[-1]
        lines: list[dict[str, Any]] = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for k in range(i2 - i1):
                    lines.append(
                        {
                            "op": " ",
                            "text": a[i1 + k],
                            "old": i1 + k + 1,
                            "new": j1 + k + 1,
                        }
                    )
                continue
            if tag in ("replace", "delete"):
                for k in range(i1, i2):
                    removed.append(a[k])
                    lines.append({"op": "-", "text": a[k], "old": k + 1, "new": None})
            if tag in ("replace", "insert"):
                for k in range(j1, j2):
                    added.append(b[k])
                    lines.append({"op": "+", "text": b[k], "old": None, "new": k + 1})
        if emitted + len(lines) > MAX_DIFF_LINES:
            truncated = True
            continue
        emitted += len(lines)
        hunks.append(
            {
                "old_start": first[1] + 1,
                "old_len": last[2] - first[1],
                "new_start": first[3] + 1,
                "new_len": last[4] - first[3],
                "lines": lines,
            }
        )
    stats = {
        "added": len(added),
        "removed": len(removed),
        "old_lines": len(a),
        "new_lines": len(b),
        "hunks": len(hunks),
    }
    return {
        "kind": "text",
        "hunks": hunks,
        "added": added[:MAX_DIFF_LINES],
        "removed": removed[:MAX_DIFF_LINES],
        "truncated": truncated,
        "stats": stats,
    }


def _key_column(header: list[str], old: list[list[str]], new: list[list[str]]) -> bool:
    """The first column works as a key when it is filled and unique on both sides."""
    for rows in (old, new):
        keys = [r[0] if r else "" for r in rows]
        if not keys or any(k == "" for k in keys) or len(set(keys)) != len(keys):
            return False
    return bool(header)


def _sheet_diff(
    name: str, old: list[list[str]], new: list[list[str]]
) -> dict[str, Any]:
    header = new[0] if new else (old[0] if old else [])
    same_header = bool(old) and bool(new) and old[0] == new[0]
    body_old = old[1:] if same_header else old
    body_new = new[1:] if same_header else new
    out: dict[str, Any] = {
        "name": name,
        "header": header if same_header else [],
        "header_changed": bool(old) and bool(new) and not same_header,
        "added": [],
        "removed": [],
        "changed": [],
        "key_column": None,
    }
    if same_header and _key_column(header, body_old, body_new):
        out["key_column"] = header[0]
        before = {r[0]: r for r in body_old}
        after = {r[0]: r for r in body_new}
        out["added"] = [after[k] for k in after if k not in before]
        out["removed"] = [before[k] for k in before if k not in after]
        for k in after:
            if k in before and before[k] != after[k]:
                b, a = before[k], after[k]
                width = max(len(a), len(b))
                cols = [
                    i
                    for i in range(width)
                    if (b[i] if i < len(b) else "") != (a[i] if i < len(a) else "")
                ]
                out["changed"].append(
                    {
                        "key": k,
                        "before": b,
                        "after": a,
                        "columns": [
                            header[i] if i < len(header) else f"#{i + 1}" for i in cols
                        ],
                        "indexes": cols,
                    }
                )
    else:
        co, cn = Counter(map(tuple, body_old)), Counter(map(tuple, body_new))
        out["added"] = _dedupe_extra(body_new, cn, co)
        out["removed"] = _dedupe_extra(body_old, co, cn)
    out["rows_old"] = len(body_old)
    out["rows_new"] = len(body_new)
    truncated = False
    for k in ("added", "removed", "changed"):
        if len(out[k]) > MAX_TABLE_ROWS:
            out[k + "_total"] = len(out[k])
            out[k] = out[k][:MAX_TABLE_ROWS]
            truncated = True
    out["truncated"] = truncated
    return out


def _dedupe_extra(
    rows: list[list[str]], mine: Counter, other: Counter
) -> list[list[str]]:
    left = {k: mine[k] - other.get(k, 0) for k in mine}
    out = []
    # rows that only moved are not changes, and a duplicate counts once per extra copy
    for r in rows:
        t = tuple(r)
        if left.get(t, 0) > 0:
            out.append(r)
            left[t] -= 1
    return out


def table_diff(
    old: dict[str, list[list[str]]], new: dict[str, list[list[str]]]
) -> dict[str, Any]:
    sheets = []
    for name in list(new) + [n for n in old if n not in new]:
        if old.get(name) == new.get(name):
            continue
        sheets.append(_sheet_diff(name, old.get(name) or [], new.get(name) or []))
    stats = {
        "rows_added": sum(len(s["added"]) for s in sheets),
        "rows_removed": sum(len(s["removed"]) for s in sheets),
        "rows_changed": sum(len(s["changed"]) for s in sheets),
        "sheets_added": [n for n in new if n not in old],
        "sheets_removed": [n for n in old if n not in new],
        "rows_old": sum(max(0, len(r) - 1) for r in old.values()),
        "rows_new": sum(max(0, len(r) - 1) for r in new.values()),
    }
    stats["added"] = stats["rows_added"] + stats["rows_changed"]
    stats["removed"] = stats["rows_removed"] + stats["rows_changed"]
    return {
        "kind": "table",
        "sheets": sheets,
        "truncated": any(s["truncated"] for s in sheets),
        "stats": stats,
    }


def _clip(s: str, n: int = 160) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def summarize(diff: dict[str, Any]) -> str:
    st = diff.get("stats") or {}
    if diff.get("kind") == "table":
        parts = []
        for label, k in (
            ("added", "rows_added"),
            ("removed", "rows_removed"),
            ("changed", "rows_changed"),
        ):
            n = st.get(k) or 0
            if n:
                parts.append(f"{n} row{'s' if n != 1 else ''} {label}")
        where = [s["name"] for s in diff.get("sheets") or [] if s.get("name")]
        text = ", ".join(parts) or "The table layout changed"
        if st.get("sheets_added"):
            text += f". New sheet {', '.join(st['sheets_added'])}"
        if st.get("sheets_removed"):
            text += f". Sheet removed: {', '.join(st['sheets_removed'])}"
        if where and len(where) <= 3:
            text += f" in {', '.join(where)}"
        first = next(
            (s["changed"][0] for s in diff.get("sheets") or [] if s.get("changed")),
            None,
        )
        if first:
            text += (
                f". First change: {first['key']} ({', '.join(first['columns'][:3])})"
            )
        return text + "."
    a, r, h = st.get("added", 0), st.get("removed", 0), st.get("hunks", 0)
    text = f"{a} line{'s' if a != 1 else ''} added and {r} removed"
    if h > 1:
        text += f" in {h} places"
    sample = next((x for x in diff.get("added") or [] if x.strip()), "") or next(
        (x for x in diff.get("removed") or [] if x.strip()), ""
    )
    if sample:
        verb = "Now reads" if diff.get("added") else "Removed"
        line = _clip(sample.strip())
        # a line that already opens with a quote reads badly wrapped in another
        text += f". {verb}: {line}" if line.startswith('"') else f'. {verb}: "{line}"'
    return text + "."


def materiality_hint(diff: dict[str, Any]) -> str:
    """A rough first sort for reviewers: high, medium or low. Never a verdict."""
    st = diff.get("stats") or {}
    if diff.get("kind") == "table":
        total = max(1, st.get("rows_old", 0) + st.get("rows_new", 0))
        moved = (
            st.get("rows_added", 0)
            + st.get("rows_removed", 0)
            + 2 * st.get("rows_changed", 0)
        )
        if (
            st.get("sheets_added")
            or st.get("sheets_removed")
            or (moved >= 6 and moved / total > 0.25)
        ):
            return "high"
        if st.get("rows_changed") or st.get("rows_removed"):
            return "medium"
        return "low" if moved <= 1 else "medium"
    changed = (diff.get("added") or []) + (diff.get("removed") or [])
    total = max(1, st.get("old_lines", 0) + st.get("new_lines", 0))
    if len(changed) > 200 or (len(changed) >= 6 and len(changed) / total > 0.25):
        return "high"
    if any(_SIGNAL.search(x) or _NUMBER.search(x) for x in changed):
        return "medium"
    return "low"


def compare(
    kind: str,
    old_text: str,
    new_text: str,
    old_tables: dict[str, list[list[str]]] | None = None,
    new_tables: dict[str, list[list[str]]] | None = None,
) -> dict[str, Any] | None:
    """The diff between two snapshots, or None when nothing changed."""
    if old_tables is not None and new_tables is not None:
        if old_tables == new_tables:
            return None
        d = table_diff(old_tables, new_tables)
    else:
        if old_text == new_text:
            return None
        d = text_diff(old_text, new_text)
    d["summary"] = summarize(d)
    d["materiality_hint"] = materiality_hint(d)
    return d
