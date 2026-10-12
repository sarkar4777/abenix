"""A sample message built from a source's own mapping, so a test push lands as an asset."""

from __future__ import annotations

import csv
import io
import json
import re
import time
from datetime import datetime, timezone
from typing import Any

_PATH = re.compile(r"\$(?:\.[A-Za-z0-9_\-]+|\[\d+\]|\['[^']+'\]|\[\"[^\"]+\"\])+")
_PART = re.compile(r"\.([A-Za-z0-9_\-]+)|\[(\d+)\]|\['([^']+)'\]|\[\"([^\"]+)\"\]")
TEST_VALUE = 21.5


def _set(doc: dict[str, Any], path: str, value: Any) -> None:
    parts = [
        m.group(1) or m.group(3) or m.group(4) or m.group(2)
        for m in _PART.finditer(path[1:])
    ]
    cur: Any = doc
    for i, key in enumerate(parts):
        last = i == len(parts) - 1
        if key.isdigit() and isinstance(cur, list):
            idx = int(key)
            while len(cur) <= idx:
                cur.append({})
            if last:
                cur[idx] = value
            else:
                cur = cur[idx]
            continue
        if not isinstance(cur, dict):
            return
        if last:
            cur.setdefault(key, value)
        else:
            nxt = parts[i + 1]
            cur = cur.setdefault(key, [] if nxt.isdigit() else {})


def _paths(template: Any) -> list[str]:
    if not isinstance(template, str):
        return []
    return _PATH.findall(template)


def _ts(fmt: str) -> Any:
    now = time.time()
    if fmt == "iso":
        return datetime.now(timezone.utc).isoformat()
    if fmt == "epoch_s":
        return int(now)
    if fmt == "epoch_us":
        return int(now * 1_000_000)
    if fmt == "epoch_ns":
        return int(now * 1_000_000_000)
    return int(now * 1000)


def sample_doc(mapping: dict[str, Any] | None) -> dict[str, Any]:
    """One document the mapping turns into a record on asset test-asset."""
    m = mapping or {}
    doc: dict[str, Any] = {}
    fill = {"group": "test", "node": "test-asset", "device": "test-device"}
    for key, val in fill.items():
        for p in _paths(m.get(key)):
            _set(doc, p, val)
    for p in _paths(
        (m.get("event") or {}).get("name") if isinstance(m.get("event"), dict) else None
    ):
        _set(doc, p, "test")
    flt = m.get("filter") or {}
    for p in flt.get("require") or []:
        _set(doc, p if p.startswith("$") else f"$.{p}", "test")
    for p, want in (flt.get("match") or {}).items():
        first = want[0] if isinstance(want, list) and want else want
        _set(doc, p if p.startswith("$") else f"$.{p}", first)
    ts = m.get("timestamp") or {}
    if ts.get("path"):
        _set(
            doc,
            ts["path"] if ts["path"].startswith("$") else f"$.{ts['path']}",
            _ts(ts.get("format") or "auto"),
        )
    else:
        doc.setdefault("ts", _ts("epoch_ms"))
    sig = m.get("signals") or {}
    root = sig.get("root")
    target: dict[str, Any] = doc
    if isinstance(root, str) and root not in ("", "$"):
        _set(doc, root, {})
        from app.telemetry.mapping import path_get

        found = path_get(doc, root)
        target = found if isinstance(found, dict) else doc
    names = [n for n in (sig.get("include") or []) if isinstance(n, str)]
    if not names:
        names = [n for n in (sig.get("declared") or []) if isinstance(n, str)]
    if not names:
        names = ["value"]
    for n in names[:20]:
        if n.startswith("$"):
            _set(doc, n, TEST_VALUE)
        else:
            target.setdefault(n, TEST_VALUE)
    if m.get("records"):
        wrapped: dict[str, Any] = {}
        _set(wrapped, m["records"], [doc])
        return wrapped
    return doc


def encode(doc: dict[str, Any], decoder: str) -> tuple[bytes, str]:
    """The body and content type a push of this document would carry."""
    if decoder == "csv":
        flat = {k: v for k, v in doc.items() if not isinstance(v, (dict, list))}
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(list(flat))
        w.writerow(list(flat.values()))
        return buf.getvalue().encode(), "text/csv"
    if decoder == "json_lines":
        return (json.dumps(doc) + "\n").encode(), "application/x-ndjson"
    return json.dumps(doc).encode(), "application/json"
