"""HTTP push: other systems POST to /api/telemetry/ingest/{connection_id}.

The API checks the source's token (and signature when one is set), puts the
body on a Redis stream and answers 202. Every ingest replica reads that stream
as one consumer group and acknowledges an entry once its records are stored,
so a replica that dies leaves its entries for another to claim.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any

from app.telemetry import keys as K
from app.telemetry.connectors.base import (
    ConfigField,
    Envelope,
    RunContext,
    SourceConnector,
    backoff,
)

logger = logging.getLogger(__name__)

GROUP = "ingest"
STREAM_MAXLEN = 50_000
# the API answers 503 BACKLOG_FULL past this, so a stopped ingest cannot fill Redis
BACKLOG_MAX = 10_000
CLAIM_IDLE_MS = 60_000


class HttpPushConnector(SourceConnector):
    transport = "http_push"
    label = "HTTP push"
    description = (
        "Another system POSTs JSON, NDJSON, CSV or text to this connection's address with its "
        "token. Answers 202 once the batch is safely queued."
    )
    config_fields = (
        ConfigField(
            key="subject",
            label="Subject",
            kind="string",
            required=False,
            default="push",
            description="Used for the group and asset when a request names none with ?subject=, e.g. fleet/vans or payments.orders.",
        ),
        ConfigField(
            key="signing_secret",
            label="Signing secret",
            kind="secret",
            required=False,
            description="When set, every request needs X-Abenix-Signature: sha256=<HMAC-SHA256 of the body>, e.g. a long random string shared with the sender.",
        ),
    )
    capabilities = {"receive": "push", "write": False}
    scale_mode = "shared"
    default_decoder = "json"

    def __init__(self) -> None:
        self._r: Any = None
        self._stream = ""

    async def _redis(self) -> Any:
        if self._r is None:
            import redis.asyncio as aioredis

            from app.core.config import settings

            self._r = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._r

    async def run(self, ctx: RunContext) -> None:
        r = await self._redis()
        self._stream = K.push_stream(ctx.connection_id)
        try:
            await r.xgroup_create(self._stream, GROUP, id="0", mkstream=True)
        except Exception as exc:  # noqa: BLE001
            if "BUSYGROUP" not in str(exc):
                ctx.set_status("error", f"Could not open the push queue: {exc}")
        ctx.set_status("connected")
        attempt = 0
        last_claim = 0.0
        loop = asyncio.get_running_loop()
        while not ctx.stopping.is_set():
            try:
                if loop.time() - last_claim > 30:
                    last_claim = loop.time()
                    await self._claim(r, ctx)
                res = await r.xreadgroup(
                    GROUP, ctx.replica, {self._stream: ">"}, count=500, block=1000
                )
                attempt = 0
                for _stream, entries in res or []:
                    for entry_id, fields in entries:
                        await ctx.emit(self._envelope(ctx, entry_id, fields))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                ctx.set_status("connecting", f"The push queue is not answering: {exc}")
                attempt += 1
                await asyncio.sleep(backoff(attempt))
                ctx.set_status("connected")

    async def _claim(self, r: Any, ctx: RunContext) -> None:
        """Take over entries a dead replica read but never acknowledged."""
        try:
            res = await r.xautoclaim(
                self._stream, GROUP, ctx.replica, CLAIM_IDLE_MS, "0-0", count=500
            )
        except Exception:  # noqa: BLE001
            return
        entries = res[1] if isinstance(res, (list, tuple)) and len(res) > 1 else []
        for entry_id, fields in entries or []:
            if fields:
                await ctx.emit(self._envelope(ctx, entry_id, fields))

    def _envelope(
        self, ctx: RunContext, entry_id: str, fields: dict[str, str]
    ) -> Envelope:
        try:
            headers = json.loads(fields.get("headers") or "{}")
        except ValueError:
            headers = {}
        return Envelope(
            connection_id=ctx.connection_id,
            tenant=ctx.tenant,
            subject=fields.get("subject") or ctx.config.get("subject") or "push",
            payload=base64.b64decode(fields.get("payload") or ""),
            headers=headers,
            t_recv=float(fields.get("t") or 0) or time.time(),
            msg_id=fields.get("msg_id") or None,
            offset_token=entry_id,
        )

    async def commit(self, tokens: list[Any]) -> None:
        if not tokens or self._r is None:
            return
        await self._r.xack(self._stream, GROUP, *tokens)
        await self._r.xdel(self._stream, *tokens)


async def enqueue(
    r: Any,
    conn_id: str,
    payload: bytes,
    *,
    subject: str,
    headers: dict[str, str],
    msg_id: str | None,
    t_recv: float,
) -> str:
    """What the API does with an accepted POST."""
    fields = {
        "payload": base64.b64encode(payload).decode(),
        "subject": subject,
        "headers": json.dumps(headers),
        "t": str(t_recv),
    }
    if msg_id:
        fields["msg_id"] = msg_id
    return await r.xadd(
        K.push_stream(conn_id), fields, maxlen=STREAM_MAXLEN, approximate=True
    )
