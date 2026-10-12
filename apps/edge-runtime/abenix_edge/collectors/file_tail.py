"""Follows a CSV or JSON lines file that a machine, a logger or another program appends to.

The offset is kept on disk, so a restart carries on where it stopped. A file
that is rotated or truncated is read again from the start.
"""

from __future__ import annotations

import asyncio
import csv
import glob
import io
import json
import os
from pathlib import Path
from typing import Any

from abenix_edge.buffer import now_ms
from abenix_edge.collectors.base import Collector
from abenix_edge.collectors.mqtt_bridge import flatten, ts_of


def coerce(v: Any) -> Any:
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return None
        try:
            f = float(s)
            return (
                int(f)
                if f.is_integer() and "." not in s and "e" not in s.lower()
                else f
            )
        except ValueError:
            if s.lower() in ("true", "false"):
                return s.lower() == "true"
            return s
    return v


class FileTailCollector(Collector):
    type = "file_tail"
    label = "File or CSV tail"

    def __init__(self, spec: dict[str, Any], sink: Any, gateway_id: str) -> None:
        super().__init__(spec, sink, gateway_id)
        self.pattern = str(spec.get("path") or "")
        self.fmt = spec.get("format") or "csv"
        self.ts_col = str(spec.get("timestamp_column") or "").strip()
        self.from_start = bool(spec.get("from_start"))
        state_dir = Path(
            spec.get("_data_dir")
            or os.environ.get("ABENIX_EDGE_DATA", "/var/lib/abenix-edge")
        )
        self.state_path = state_dir / f"tail-{self.id}.json"
        self.offsets: dict[str, dict[str, int]] = {}
        self.headers: dict[str, list[str]] = {}
        try:
            self.offsets = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            self.offsets = {}

    def _save(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(self.offsets))
        except OSError:
            pass

    def rows(self, path: str, text: str) -> list[tuple[dict[str, Any], int | None]]:
        out = []
        if self.fmt == "jsonl":
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except ValueError:
                    self.extra["bad_lines"] = self.extra.get("bad_lines", 0) + 1
                    continue
                if not isinstance(doc, dict):
                    continue
                ts = ts_of(doc.pop(self.ts_col, None)) if self.ts_col else None
                if ts is None:
                    for k in ("ts", "timestamp", "time", "t"):
                        if k in doc:
                            ts = ts_of(doc.pop(k))
                            break
                out.append((flatten(doc), ts))
            return out
        lines = text.splitlines()
        if path not in self.headers:
            if not lines:
                return out
            self.headers[path] = next(csv.reader([lines[0]]))
            lines = lines[1:]
        hdr = self.headers[path]
        for rec in csv.reader(io.StringIO("\n".join(lines))):
            if not rec or rec == hdr:
                continue
            doc = {k.strip(): coerce(v) for k, v in zip(hdr, rec)}
            ts = None
            key = self.ts_col or next(
                (k for k in ("ts", "timestamp", "time") if k in doc), ""
            )
            if key:
                ts = ts_of(doc.pop(key, None))
            out.append((doc, ts))
        return out

    def read_new(self) -> int:
        files = sorted(glob.glob(self.pattern))
        if not files:
            self.fail(
                f"No file matches {self.pattern} yet. Check the path, and in Docker mount the folder with -v.",
                "running",
            )
            return 0
        n = 0
        for path in files:
            st = os.stat(path)
            pos = self.offsets.get(path)
            if pos is None:
                pos = {"ino": st.st_ino, "off": 0 if self.from_start else st.st_size}
                if not self.from_start and self.fmt == "csv":
                    with open(path, encoding="utf-8", errors="replace") as f:
                        self.headers[path] = next(csv.reader([f.readline()]), [])
            if pos["ino"] != st.st_ino or st.st_size < pos["off"]:
                pos = {"ino": st.st_ino, "off": 0}
                self.headers.pop(path, None)
            if st.st_size > pos["off"]:
                with open(path, "rb") as f:
                    f.seek(pos["off"])
                    data = f.read(4 * 1024 * 1024)
                cut = data.rfind(b"\n")
                if cut >= 0:
                    data = data[: cut + 1]
                    if (
                        path not in self.headers
                        and pos["off"] > 0
                        and self.fmt == "csv"
                    ):
                        with open(path, encoding="utf-8", errors="replace") as f:
                            self.headers[path] = next(csv.reader([f.readline()]), [])
                    for doc, ts in self.rows(path, data.decode("utf-8", "replace")):
                        rows = [
                            (k, v, None, "good")
                            for k, v in doc.items()
                            if v is not None
                        ]
                        self.emit_many(rows, ts=ts or now_ms())
                        n += len(rows)
                    pos["off"] += len(data)
            self.offsets[path] = pos
        self._save()
        self.ok()
        return n

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.to_thread(self.read_new)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"Could not read {self.pattern}: {exc}")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
