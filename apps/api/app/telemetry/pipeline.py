"""One connection's pipeline on one replica: its connector, its decoders and mapping, and the helpers
the API shares for previews and replays."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import fnmatch
import functools
import hashlib
import inspect
import json
import logging
import re
import time
from typing import Any

from app.telemetry import keys as K
from app.telemetry import registry
from app.telemetry.connectors.base import Envelope, RunContext, backoff
from app.telemetry.decoders.base import DecodeError, Decoder, DecoderState, Record
from app.telemetry.store import ConnInfo

logger = logging.getLogger("telemetry.pipeline")

INSPECTOR_RING = 500
DLQ_RING = 500
# a dead letter keeps at most this much payload, a bigger one is kept as a preview only
DLQ_PAYLOAD_MAX = 16384
INSPECT_OK_PER_SEC = 5
PREVIEW_BYTES = 4096


@functools.lru_cache(maxsize=4096)
def _pattern(pattern: str) -> re.Pattern:
    """An MQTT filter (+ one level, # the rest) or a glob, compiled once."""
    if "+" in pattern or "#" in pattern:
        parts = pattern.split("/")
        out = []
        for i, p in enumerate(parts):
            if p == "#" and i == len(parts) - 1:
                # a/# also matches a itself
                if out:
                    out[-1] = out[-1] + "(?:/.*)?"
                    return re.compile("^" + "/".join(out) + "$")
                return re.compile("^.*$")
            out.append("[^/]+" if p == "+" else re.escape(p))
        return re.compile("^" + "/".join(out) + "$")
    return re.compile(fnmatch.translate(pattern))


def subject_matches(pattern: str, subject: str) -> bool:
    return bool(_pattern(pattern).match(subject))


def connection_row(c: Any) -> dict[str, Any]:
    """The effective settings of a connection, secrets decrypted. Used by the ingest and the API."""
    from app.core import crypto

    tenant = str(c.tenant_id)
    transport = getattr(c, "transport", None) or "mqtt"
    cfg = dict(getattr(c, "config", None) or {})
    secrets = {}
    for k, v in (getattr(c, "secrets", None) or {}).items():
        secrets[k] = crypto.decrypt(tenant, v) if isinstance(v, str) else v
    topics = list(c.topics or [])
    raw = list(c.raw_topics or [])
    if transport == "mqtt":
        cfg["broker_url"] = c.broker_url or cfg.get("broker_url") or ""
        if c.username:
            cfg["username"] = c.username
        if c.password and not secrets.get("password"):
            secrets["password"] = crypto.decrypt(tenant, c.password)
        cfg["subjects"] = topics + [t for t in raw if t not in topics]
    elif topics or not cfg.get("subjects"):
        cfg["subjects"] = topics
    bindings = [b for b in (cfg.get("bindings") or []) if isinstance(b, dict)]
    if raw:
        bindings.insert(
            0,
            {
                "subjects": raw,
                "decoder": "can_frames",
                "decoder_config": cfg.get("can_frames") or {},
            },
        )
    mapping = dict(getattr(c, "mapping", None) or {})
    row = {
        "id": str(c.id),
        "tenant": tenant,
        "name": c.name,
        "transport": transport,
        "config": cfg,
        "secrets": secrets,
        "decoder": getattr(c, "decoder", None)
        or ("sparkplug_b" if transport == "mqtt" else "json"),
        "decoder_config": dict(getattr(c, "decoder_config", None) or {}),
        "mapping": mapping,
        "bindings": bindings,
        "strict": bool(getattr(c, "strict", False)),
        "enabled": bool(c.enabled),
        "shared": bool(c.shared_subscription),
        "team_id": str(c.team_id) if c.team_id else None,
    }
    if row["strict"]:
        row["mapping"]["strict"] = True
    row["sig"] = hashlib.sha1(
        json.dumps(row, sort_keys=True, default=str).encode()
    ).hexdigest()
    return row


async def run_decode(
    decoder: Decoder, env: Envelope, state: DecoderState, mapping: dict[str, Any] | None
) -> list[Record]:
    res = decoder.decode(env, state, mapping)
    if inspect.isawaitable(res):
        res = await res
    return list(res or [])


def record_json(r: Record) -> dict[str, Any]:
    return dataclasses.asdict(r)


def payload_preview(payload: bytes) -> tuple[str, str]:
    head = payload[:PREVIEW_BYTES]
    try:
        return head.decode("utf-8"), "utf8"
    except UnicodeDecodeError:
        return base64.b64encode(head).decode(), "base64"


def conn_info(row: dict[str, Any], shared: bool | None = None) -> ConnInfo:
    return ConnInfo(
        id=row["id"],
        tenant=row["tenant"],
        name=row["name"],
        shared=bool(row.get("shared")) if shared is None else shared,
        team_id=row.get("team_id"),
        transport=row.get("transport") or "mqtt",
        offline_after_s=int((row.get("mapping") or {}).get("offline_after_s") or 0),
    )


class Runtime:
    """A connection running on this replica."""

    def __init__(
        self,
        row: dict[str, Any],
        replica: str,
        loop: asyncio.AbstractEventLoop,
        on_enqueue: Any,
        lookup: Any,
        queue_max: int,
    ) -> None:
        self.row = row
        self.sig = row["sig"]
        self.connector = registry.connector(row["transport"])
        shared = row["shared"] or self.connector.scale_mode == "shared"
        self.info = conn_info(row, shared)
        cfg = dict(row["config"])
        cfg["_connection_id"] = row["id"]
        self.ctx = RunContext(
            connection_id=row["id"],
            tenant=row["tenant"],
            name=row["name"],
            config=cfg,
            secrets=row["secrets"],
            replica=replica,
            shared=shared,
            queue_max=queue_max,
            on_enqueue=on_enqueue,
            loop=loop,
        )
        self.mapping = row["mapping"]
        self.bindings: list[tuple[list[str], Decoder, DecoderState]] = []
        for bnd in row["bindings"]:
            self.bindings.append(
                (
                    list(bnd.get("subjects") or []),
                    registry.decoder(bnd.get("decoder") or "json"),
                    DecoderState(
                        config=dict(bnd.get("decoder_config") or {}),
                        lookup=lookup,
                        shared=shared,
                    ),
                )
            )
        self.primary = (
            registry.decoder(row["decoder"]),
            DecoderState(
                config=dict(row["decoder_config"]), lookup=lookup, shared=shared
            ),
        )
        self.task: asyncio.Task | None = None
        self._picked: dict[str, tuple[Decoder, DecoderState]] = {}
        self.rate_window: list[tuple[float, int]] = []
        self.inspect_sec = 0
        self.inspect_count = 0
        self.decode_errors = 0
        # what happened to each message, for "why is my data not showing"
        self.counts: dict[str, int] = {}
        self.reasons: dict[str, dict[str, Any]] = {}

    def bump(self, kind: str, reason: str | None = None, n: int = 1) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + n
        if reason:
            self.reasons[kind] = {"reason": reason, "at": int(time.time() * 1000)}

    def pick(self, subject: str) -> tuple[Decoder, DecoderState]:
        hit = self._picked.get(subject)
        if hit is not None:
            return hit
        found = self.primary
        for subjects, dec, st in self.bindings:
            if any(subject_matches(p, subject) for p in subjects):
                found = (dec, st)
                break
        if len(self._picked) > 4096:
            self._picked.clear()
        self._picked[subject] = found
        return found

    def states(self) -> list[DecoderState]:
        return [st for _, _, st in self.bindings] + [self.primary[1]]

    async def decode(self, env: Envelope) -> list[Record]:
        dec, st = self.pick(env.subject)
        return await run_decode(dec, env, st, self.mapping)

    def start(self) -> None:
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        attempt = 0
        while not self.ctx.stopping.is_set():
            try:
                await self.connector.run(self.ctx)
                if self.ctx.stopping.is_set():
                    return
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                logger.warning("connection %s failed: %s", self.row["name"], exc)
                self.ctx.set_status("error", str(exc) or type(exc).__name__)
            try:
                await asyncio.wait_for(
                    self.ctx.stopping.wait(), timeout=backoff(attempt, cap=30)
                )
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self.ctx.stopping.set()
        self.ctx._room.set()
        if self.task is not None:
            try:
                await asyncio.wait_for(self.task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.task.cancel()
            except Exception:  # noqa: BLE001
                pass

    def mps(self) -> float:
        now = time.time()
        self.rate_window.append((now, self.ctx.received))
        while self.rate_window and now - self.rate_window[0][0] > 5.0:
            self.rate_window.pop(0)
        if len(self.rate_window) < 2:
            return 0.0
        (t0, c0), (t1, c1) = self.rate_window[0], self.rate_window[-1]
        return round((c1 - c0) / max(0.001, t1 - t0), 1)

    def inspect_ok(self, now: float) -> bool:
        """At most a few successful messages a second go to the inspector, every failure does."""
        sec = int(now)
        if sec != self.inspect_sec:
            self.inspect_sec, self.inspect_count = sec, 0
        self.inspect_count += 1
        return self.inspect_count <= INSPECT_OK_PER_SEC


def inspector_entry(
    env: Envelope,
    records: list[Record] | None,
    error: str | None,
    skipped: str | None = None,
) -> str:
    text, enc = payload_preview(env.payload)
    doc = {
        "t": int(env.t_recv * 1000),
        "subject": env.subject,
        "size": len(env.payload),
        "headers": env.headers,
        "payload": text,
        "encoding": enc,
        "msg_id": env.msg_id,
        "ok": error is None,
        "error": error,
    }
    if skipped:
        doc["skipped"] = True
        doc["skip_reason"] = skipped
    if records is not None:
        doc["records"] = len(records)
        doc["result"] = [
            {
                "kind": r.kind,
                "group": r.group,
                "node": r.node,
                "device": r.device,
                "metrics": [m.name for m in r.metrics][:20],
                "frames": len(r.frames),
                "event": r.event_name,
            }
            for r in records[:5]
        ]
    return json.dumps(doc, default=str)


def dlq_entry(env: Envelope, reason: str) -> str:
    import uuid

    return json.dumps(
        {
            "id": uuid.uuid4().hex,
            "t": int(env.t_recv * 1000),
            "subject": env.subject,
            "headers": env.headers,
            "payload_b64": base64.b64encode(env.payload[:DLQ_PAYLOAD_MAX]).decode(),
            "size": len(env.payload),
            "truncated": len(env.payload) > DLQ_PAYLOAD_MAX,
            "reason": reason,
            "msg_id": env.msg_id,
        },
        default=str,
    )


def envelope_from_dlq(doc: dict[str, Any], conn_id: str, tenant: str) -> Envelope:
    return Envelope(
        connection_id=conn_id,
        tenant=tenant,
        subject=doc.get("subject") or "",
        payload=base64.b64decode(doc.get("payload_b64") or ""),
        headers=doc.get("headers") or {},
        t_recv=(doc.get("t") or time.time() * 1000) / 1000.0,
        msg_id=None,
    )


def plain_decode_error(exc: BaseException) -> str:
    if isinstance(exc, DecodeError):
        return str(exc)
    return f"Could not decode this message: {type(exc).__name__}: {exc}"


__all__ = [
    "K",
    "Runtime",
    "connection_row",
    "dlq_entry",
    "envelope_from_dlq",
    "inspector_entry",
    "plain_decode_error",
    "record_json",
    "run_decode",
    "subject_matches",
]
