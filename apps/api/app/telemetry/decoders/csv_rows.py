"""CSV with a header row, each row a document. Numbers are read as numbers."""

from __future__ import annotations

import csv
import io
from typing import Any

from app.telemetry.connectors.base import ConfigField
from app.telemetry.decoders.base import DecodeError, DocumentDecoder


def _cell(v: str) -> Any:
    s = v.strip()
    if s == "":
        return None
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        f = float(s)
        return int(f) if f.is_integer() and "." not in s and "e" not in low else f
    except ValueError:
        return s


class CsvDecoder(DocumentDecoder):
    name = "csv"
    label = "CSV"
    description = (
        "Comma or other separated rows with a header row. Each row is one reading."
    )
    config_fields = (
        ConfigField(
            key="delimiter",
            label="Separator",
            kind="string",
            required=False,
            default=",",
        ),
        ConfigField(
            key="columns",
            label="Column names",
            kind="string",
            required=False,
            description="Comma separated, for data without a header row.",
        ),
    )

    def parse(self, payload: bytes, config: dict[str, Any]) -> list[Any]:
        text = payload.decode("utf-8-sig", "replace")
        delim = str(config.get("delimiter") or ",")
        if delim in ("\t", "tab"):
            delim = "\t"
        cols = [
            c.strip() for c in str(config.get("columns") or "").split(",") if c.strip()
        ]
        reader = csv.reader(io.StringIO(text), delimiter=delim[0])
        rows = [r for r in reader if any(c.strip() for c in r)]
        if not rows:
            raise DecodeError("The CSV has no rows")
        if not cols:
            cols, rows = [c.strip() for c in rows[0]], rows[1:]
        out = []
        for i, r in enumerate(rows, 1):
            if len(r) != len(cols):
                raise DecodeError(
                    f"Row {i} has {len(r)} values but there are {len(cols)} columns"
                )
            out.append({c: _cell(v) for c, v in zip(cols, r)})
        return out
