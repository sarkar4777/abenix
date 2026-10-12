"""Store-and-forward: readings wait on disk until Abenix has taken them.

Readings are staged in memory for a second, then written to SQLite as
compressed chunks, one subject (group/node/device) per chunk. The sender
takes the oldest chunk first and gathers more chunks of the same subject
into one batch. The batch's chunk list is written down before it is sent,
so a retry after a crash or a timeout sends exactly the same readings under
the same Idempotency-Key and Abenix drops the copy.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CHUNK_MAX_VALUES = 2000
SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    first_ts INTEGER NOT NULL,
    last_ts INTEGER NOT NULL,
    n INTEGER NOT NULL,
    bytes INTEGER NOT NULL,
    body BLOB NOT NULL,
    ord REAL
);
CREATE INDEX IF NOT EXISTS ix_chunks_subject ON chunks(subject, ord);
CREATE INDEX IF NOT EXISTS ix_chunks_ord ON chunks(ord);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Reading:
    subject: str
    name: str
    value: Any
    ts: int
    unit: str | None = None
    quality: str = "good"

    def doc(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "value": self.value,
            "ts": self.ts,
            "quality": self.quality,
        }
        if self.unit:
            d["unit"] = self.unit
        return d


@dataclass
class Batch:
    key: str
    subject: str
    seqs: list[int]
    values: list[dict[str, Any]] = field(default_factory=list)

    @property
    def first_ts(self) -> int:
        return min((v["ts"] for v in self.values), default=0)

    def body(self) -> bytes:
        return json.dumps(
            {"ts": self.first_ts, "values": self.values}, separators=(",", ":")
        ).encode()


class Buffer:
    def __init__(
        self,
        path: str | Path,
        *,
        gateway_id: str,
        max_bytes: int = 1024 * 1024 * 1024,
        max_age_s: int = 72 * 3600,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.gateway_id = gateway_id
        self.max_bytes = max_bytes
        self.max_age_s = max_age_s
        self._lock = threading.RLock()
        self._staged: dict[str, list[Reading]] = {}
        self._staged_n = 0
        self.db = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None
        )
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.epoch = self._meta("epoch") or self._new_epoch()
        self.counters = {
            k: int(self._meta(k) or 0)
            for k in ("written", "sent", "dropped_age", "dropped_size", "rejected")
        }
        self._bytes = self._sum_bytes()

    def _new_epoch(self) -> str:
        # a new file restarts seq at 1, the epoch keeps its batch keys apart from the old file's
        e = secrets.token_hex(4)
        self._set_meta("epoch", e)
        return e

    def _meta(self, k: str) -> str | None:
        row = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, k: str, v: str) -> None:
        self.db.execute(
            "INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (k, v),
        )

    def _sum_bytes(self) -> int:
        return int(
            self.db.execute("SELECT COALESCE(SUM(bytes),0) FROM chunks").fetchone()[0]
        )

    def _count(self, k: str, n: int) -> None:
        self.counters[k] = self.counters.get(k, 0) + n
        self._set_meta(k, str(self.counters[k]))

    def configure(
        self, *, max_bytes: int | None = None, max_age_s: int | None = None
    ) -> None:
        with self._lock:
            if max_bytes:
                self.max_bytes = int(max_bytes)
            if max_age_s:
                self.max_age_s = int(max_age_s)

    # writing

    def add(self, r: Reading) -> None:
        with self._lock:
            self._staged.setdefault(r.subject, []).append(r)
            self._staged_n += 1

    def add_many(self, rs: list[Reading]) -> None:
        with self._lock:
            for r in rs:
                self._staged.setdefault(r.subject, []).append(r)
            self._staged_n += len(rs)

    def flush(self) -> int:
        """Write what is staged as chunks. Returns the number of readings written."""
        with self._lock:
            staged, self._staged, self._staged_n = self._staged, {}, 0
            if not staged:
                return 0
            n = 0
            self.db.execute("BEGIN")
            try:
                for subject, rs in staged.items():
                    rs.sort(key=lambda r: r.ts)
                    for i in range(0, len(rs), CHUNK_MAX_VALUES):
                        part = rs[i : i + CHUNK_MAX_VALUES]
                        raw = json.dumps(
                            [r.doc() for r in part], separators=(",", ":"), default=str
                        ).encode()
                        body = zlib.compress(raw, 6)
                        self.db.execute(
                            "INSERT INTO chunks(subject, first_ts, last_ts, n, bytes, body) "
                            "VALUES(?,?,?,?,?,?)",
                            (
                                subject,
                                part[0].ts,
                                part[-1].ts,
                                len(part),
                                len(body),
                                body,
                            ),
                        )
                        self._bytes += len(body)
                        n += len(part)
                self.db.execute("UPDATE chunks SET ord=seq WHERE ord IS NULL")
                self._count("written", n)
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            self._enforce_locked()
            return n

    def _enforce_locked(self) -> None:
        cutoff = now_ms() - self.max_age_s * 1000
        old = self.db.execute(
            "SELECT COALESCE(SUM(n),0), COALESCE(SUM(bytes),0) FROM chunks WHERE last_ts < ?",
            (cutoff,),
        ).fetchone()
        if old[0]:
            self.db.execute("DELETE FROM chunks WHERE last_ts < ?", (cutoff,))
            self._bytes -= int(old[1])
            self._count("dropped_age", int(old[0]))
        while self._bytes > self.max_bytes:
            rows = self.db.execute(
                "SELECT seq, n, bytes FROM chunks ORDER BY ord LIMIT 200"
            ).fetchall()
            if not rows:
                self._bytes = 0
                break
            drop, nvals = [], 0
            for seq, n, b in rows:
                drop.append(seq)
                nvals += n
                self._bytes -= b
                if self._bytes <= self.max_bytes:
                    break
            self.db.execute(
                f"DELETE FROM chunks WHERE seq IN ({','.join('?' * len(drop))})", drop
            )
            self._count("dropped_size", nvals)
        if old[0] or self._bytes < 0:
            self._bytes = self._sum_bytes()

    def enforce_limits(self) -> None:
        with self._lock:
            self._enforce_locked()

    # sending

    def next_batch(
        self, max_values: int = 5000, max_bytes: int = 900_000
    ) -> Batch | None:
        """The batch to send now: the one in flight, else the oldest subject's oldest chunks."""
        with self._lock:
            pending = self._meta("inflight")
            if pending:
                b = self._load(json.loads(pending))
                if b is not None:
                    return b
                self.db.execute("DELETE FROM meta WHERE k='inflight'")
            first = self.db.execute(
                "SELECT seq, subject FROM chunks ORDER BY ord LIMIT 1"
            ).fetchone()
            if first is None:
                return None
            subject = first[1]
            rows = self.db.execute(
                "SELECT seq, n, body FROM chunks WHERE subject=? ORDER BY ord LIMIT 500",
                (subject,),
            ).fetchall()
            seqs: list[int] = []
            values: list[dict[str, Any]] = []
            size = 0
            for seq, n, body in rows:
                vals = json.loads(zlib.decompress(body))
                est = len(json.dumps(vals, separators=(",", ":"), default=str))
                if seqs and (len(values) + n > max_values or size + est > max_bytes):
                    break
                seqs.append(seq)
                values.extend(vals)
                size += est
            key = f"{self.gateway_id}:{self.epoch}:{seqs[0]}-{seqs[-1]}-{len(seqs)}"
            self._set_meta(
                "inflight", json.dumps({"key": key, "subject": subject, "seqs": seqs})
            )
            return Batch(key=key, subject=subject, seqs=seqs, values=values)

    def _load(self, p: dict[str, Any]) -> Batch | None:
        seqs = [int(s) for s in p.get("seqs") or []]
        if not seqs:
            return None
        rows = self.db.execute(
            f"SELECT seq, body FROM chunks WHERE seq IN ({','.join('?' * len(seqs))}) ORDER BY ord",
            seqs,
        ).fetchall()
        if len(rows) != len(seqs):
            # some chunks aged out while the batch waited, send what is left under a new key
            return None
        values: list[dict[str, Any]] = []
        for _, body in rows:
            values.extend(json.loads(zlib.decompress(body)))
        return Batch(key=p["key"], subject=p["subject"], seqs=seqs, values=values)

    def ack(self, batch: Batch) -> None:
        """Abenix has the batch, drop it from disk."""
        with self._lock:
            self._drop(batch)
            self._count("sent", len(batch.values))

    def reject(self, batch: Batch) -> None:
        """Abenix will never take this batch, such as a payload it cannot read."""
        with self._lock:
            self._drop(batch)
            self._count("rejected", len(batch.values))

    def _drop(self, batch: Batch) -> None:
        q = ",".join("?" * len(batch.seqs))
        b = self.db.execute(
            f"SELECT COALESCE(SUM(bytes),0) FROM chunks WHERE seq IN ({q})", batch.seqs
        ).fetchone()[0]
        self.db.execute(f"DELETE FROM chunks WHERE seq IN ({q})", batch.seqs)
        self.db.execute("DELETE FROM meta WHERE k='inflight'")
        self._bytes -= int(b)

    def split(self, batch: Batch) -> bool:
        """Abenix said the batch is too large: send its chunks one by one, or halve a single chunk."""
        with self._lock:
            self.db.execute("DELETE FROM meta WHERE k='inflight'")
            if len(batch.seqs) > 1:
                key = (
                    f"{self.gateway_id}:{self.epoch}:{batch.seqs[0]}-{batch.seqs[0]}-1"
                )
                self._set_meta(
                    "inflight",
                    json.dumps(
                        {"key": key, "subject": batch.subject, "seqs": batch.seqs[:1]}
                    ),
                )
                return True
            if len(batch.values) < 2:
                return False
            row = self.db.execute(
                "SELECT subject, ord FROM chunks WHERE seq=?", (batch.seqs[0],)
            ).fetchone()
            if row is None:
                return False
            subject, ord_ = row
            nxt = self.db.execute(
                "SELECT MIN(ord) FROM chunks WHERE ord > ?", (ord_,)
            ).fetchone()[0]
            # the second half sits between this chunk and the next, so order holds
            mid = (ord_ + nxt) / 2 if nxt is not None else ord_ + 0.5
            half = len(batch.values) // 2
            parts = [(batch.values[:half], ord_), (batch.values[half:], mid)]
            self.db.execute("BEGIN")
            self.db.execute("DELETE FROM chunks WHERE seq=?", (batch.seqs[0],))
            first_seq = None
            for part, o in parts:
                body = zlib.compress(
                    json.dumps(part, separators=(",", ":")).encode(), 6
                )
                cur = self.db.execute(
                    "INSERT INTO chunks(subject, first_ts, last_ts, n, bytes, body, ord) VALUES(?,?,?,?,?,?,?)",
                    (
                        subject,
                        part[0]["ts"],
                        part[-1]["ts"],
                        len(part),
                        len(body),
                        body,
                        o,
                    ),
                )
                first_seq = first_seq or cur.lastrowid
            key = f"{self.gateway_id}:{self.epoch}:{first_seq}-{first_seq}-1"
            self._set_meta(
                "inflight",
                json.dumps({"key": key, "subject": subject, "seqs": [first_seq]}),
            )
            self.db.execute("COMMIT")
            self._bytes = self._sum_bytes()
            return True

    # health

    def stats(self) -> dict[str, Any]:
        with self._lock:
            n, chunks, oldest = self.db.execute(
                "SELECT COALESCE(SUM(n),0), COUNT(*), MIN(first_ts) FROM chunks"
            ).fetchone()
            try:
                disk = os.path.getsize(self.path)
            except OSError:
                disk = 0
            return {
                "depth": int(n) + self._staged_n,
                "chunks": int(chunks),
                "bytes": int(self._bytes),
                "file_bytes": disk,
                "oldest_ts": oldest,
                "oldest_age_s": round((now_ms() - oldest) / 1000, 1) if oldest else 0,
                "max_bytes": self.max_bytes,
                "max_age_s": self.max_age_s,
                **self.counters,
            }

    def close(self) -> None:
        with self._lock:
            self.db.close()
