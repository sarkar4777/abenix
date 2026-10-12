"""Streams from any source: HTTP push, mapping preview and suggest, the inspector, dead letters and replay."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.capabilities import require_capability
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.routers.telemetry import (
    _manage_refusal,
    forbidden,
    new_ingest_token,
    redis,
    tsdb,
)
from app.telemetry import access, pipeline, registry, sources
from app.telemetry import keys as K
from app.telemetry import mapping as M
from app.telemetry.connectors import http_push
from app.telemetry.connectors.base import Envelope
from app.telemetry.decoders.base import DecoderState, DocumentDecoder, Skipped
from models.telemetry import TelemetryConnection
from models.user import User

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

SKIP_HEADERS = {
    "authorization",
    "cookie",
    "x-abenix-signature",
    "x-api-key",
    "idempotency-key",
    "x-message-id",
    "x-forwarded-for",
    "x-real-ip",
}
PUSH_TYPES = (
    "application/json",
    "application/x-ndjson",
    "application/ndjson",
    "application/jsonl",
    "text/csv",
    "text/plain",
    "application/octet-stream",
    "application/vnd.abenix.values+json",
)


async def _conn(
    db: AsyncSession, user: User, conn_id: uuid.UUID
) -> TelemetryConnection | None:
    c = (
        await db.execute(
            select(TelemetryConnection).where(
                TelemetryConnection.id == conn_id,
                TelemetryConnection.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if c is None:
        return None
    scope = await access.scope_for(db, user)
    return c if scope.sees(str(c.id)) else None


def _payload(body: dict[str, Any]) -> bytes | None:
    if body.get("payload_base64"):
        try:
            return base64.b64decode(body["payload_base64"])
        except ValueError:
            return None
    p = body.get("payload")
    if p is None:
        return None
    if isinstance(p, (dict, list)):
        return json.dumps(p).encode()
    return str(p).encode()


# http push


async def _read_capped(request: Request, cap: int) -> bytes | None:
    """The body, or None once it passes cap. Never holds more than cap bytes."""
    stream = getattr(request, "stream", None)
    if stream is None:
        raw = await request.body()
        return None if len(raw) > cap else raw
    buf = bytearray()
    async for chunk in stream():
        buf.extend(chunk)
        if len(buf) > cap:
            return None
    return bytes(buf)


def inflate(raw: bytes, cap: int) -> bytes:
    """gzip in, at most cap bytes out. OverflowError past cap, ValueError when corrupt."""
    import zlib

    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = bytearray()
    data = raw
    try:
        while data:
            out.extend(d.decompress(data, cap + 1 - len(out)))
            if len(out) > cap:
                raise OverflowError
            data = d.unconsumed_tail
            if not data and not d.eof and d.unused_data == b"":
                break
        out.extend(d.flush(cap + 1 - len(out)))
    except zlib.error:
        raise ValueError("corrupt gzip") from None
    if len(out) > cap:
        raise OverflowError
    if not d.eof:
        raise ValueError("truncated gzip")
    return bytes(out)


@router.post("/ingest/{connection_id}", status_code=202)
async def ingest(
    connection_id: uuid.UUID,
    request: Request,
    subject: str | None = Query(None, max_length=512),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Another system sends readings here with the connection's token. 202 once queued."""
    auth = (request.headers.get("authorization") or "").strip()
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        return error(
            "Send the source's token as Authorization: Bearer tpk_...",
            401,
            error_code="UNAUTHORIZED",
        )
    c = (
        await db.execute(
            select(TelemetryConnection).where(TelemetryConnection.id == connection_id)
        )
    ).scalar_one_or_none()
    digest = hashlib.sha256(token.encode()).hexdigest()
    key = None
    if (
        c is not None
        and c.transport == "http_push"
        and token.startswith((sources.DEVICE_PREFIX, sources.GATEWAY_PREFIX))
    ):
        key = await sources.find_key(db, token, c.id)
        ok = key is not None
    else:
        ok = bool(
            c is not None
            and c.transport == "http_push"
            and c.ingest_token_hash
            and hmac.compare_digest(digest, c.ingest_token_hash)
        )
    if not ok:
        return error(
            "That key does not open this source. It may be revoked, or belong to another source. "
            "Make a new one under the source's keys.",
            401,
            error_code="UNAUTHORIZED",
        )
    if not c.enabled:
        return error(
            "This source is turned off, nothing was taken.", 409, error_code="DISABLED"
        )
    from app.core.platform_settings import get_int_setting

    cap = await get_int_setting("telemetry.max_payload_bytes", 1_048_576)
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    too_big = error(
        f"The body is more than {cap} bytes, the limit. Send smaller batches.",
        413,
        error_code="PAYLOAD_TOO_LARGE",
    )
    if declared > cap:
        return too_big
    raw = await _read_capped(request, cap)
    if raw is None:
        return too_big
    encoding = (request.headers.get("content-encoding") or "identity").strip().lower()
    if encoding in ("gzip", "x-gzip"):
        try:
            raw = inflate(raw, cap)
        except OverflowError:
            return error(
                f"The body is more than {cap} bytes after decompression, the limit. Send smaller batches.",
                413,
                error_code="PAYLOAD_TOO_LARGE",
            )
        except ValueError:
            return error(
                "The body says it is gzip but does not decompress. Check the compression.",
                400,
                error_code="BAD_ENCODING",
            )
    elif encoding not in ("identity", ""):
        return error(
            f"Content-Encoding {encoding} is not taken. Send gzip or no compression.",
            415,
            error_code="UNSUPPORTED_MEDIA_TYPE",
        )
    if not raw:
        return error("The body is empty.", 422, error_code="VALIDATION_ERROR")
    ctype = (
        (request.headers.get("content-type") or "application/json")
        .split(";")[0]
        .strip()
        .lower()
    )
    if ctype not in PUSH_TYPES:
        return error(
            f"{ctype} is not taken. Send JSON, NDJSON, CSV or plain text.",
            415,
            error_code="UNSUPPORTED_MEDIA_TYPE",
        )
    from app.core import crypto

    secret = (c.secrets or {}).get("signing_secret")
    if secret:
        signing = crypto.decrypt(c.tenant_id, secret)
        sent = (request.headers.get("x-abenix-signature") or "").strip()
        want = "sha256=" + hmac.new(signing.encode(), raw, hashlib.sha256).hexdigest()
        if not sent or not hmac.compare_digest(sent, want):
            return error(
                "The signature is missing or wrong. Send X-Abenix-Signature: sha256=<HMAC-SHA256 of the body>.",
                401,
                error_code="BAD_SIGNATURE",
            )
    msg_id = request.headers.get("idempotency-key") or request.headers.get(
        "x-message-id"
    )
    headers = {"content-type": ctype}
    for h, v in request.headers.items():
        h = h.lower()
        if h in SKIP_HEADERS or h.startswith(sources.HEADER_PREFIX):
            continue
        if h.startswith("x-") or h in ("user-agent", "ce-type", "ce-source", "ce-id"):
            headers[h] = str(v)[:200]
        if len(headers) > 30:
            break
    if key is not None:
        # the key decides who is writing, never a header the device sends
        headers.update(sources.identity_headers(key))
        headers["x-device-id"] = key.device_id
        await sources.touch(db, key)
    sub = subject or (c.config or {}).get("subject") or "push"
    backlog = await redis().xlen(K.push_stream(c.id)) if hasattr(redis(), "xlen") else 0
    if backlog >= http_push.BACKLOG_MAX:
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "5"},
            content={
                "data": None,
                "error": {
                    "message": f"{backlog} batches are waiting for this source, more than {http_push.BACKLOG_MAX}. Wait a few seconds and send again, nothing was lost.",
                    "code": 503,
                    "error_code": "BACKLOG_FULL",
                },
            },
        )
    entry = await http_push.enqueue(
        redis(),
        str(c.id),
        raw,
        subject=sub,
        headers=headers,
        msg_id=msg_id[:200] if msg_id else None,
        t_recv=time.time(),
    )
    return success({"accepted": True, "id": entry, "bytes": len(raw)}, status_code=202)


@router.post("/connections/{conn_id}/token")
async def rotate_token(
    conn_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """A new push token. The old one stops working at once. Shown this once."""
    if not await access.has(db, user, "telemetry.manage"):
        return forbidden(_manage_refusal())
    c = await _conn(db, user, conn_id)
    if c is None:
        return error("Connection not found", 404, error_code="NOT_FOUND")
    if c.transport != "http_push":
        return error(
            "Only HTTP push sources have a token.", 422, error_code="VALIDATION_ERROR"
        )
    token, c.ingest_token_hash = new_ingest_token()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.connection.token_rotated",
        {"name": c.name},
        request,
        resource_type=access.KIND,
        resource_id=str(c.id),
    )
    await db.commit()
    return success(
        {
            "ingest_token": token,
            "ingest_url": f"/api/telemetry/ingest/{c.id}",
            "rotated": True,
        }
    )


# mapping preview and suggest


async def _lookup(kind: str, t: str, g: str, n: str, d: str = "") -> Any:
    from app.telemetry.writer import Writer

    return await Writer(redis()).lookup(kind, t, g, n, d)


async def _decode(
    row: dict[str, Any],
    env: Envelope,
    decoder_name: str | None,
    decoder_config: dict[str, Any] | None,
    mapping: dict[str, Any] | None,
) -> dict[str, Any]:
    name = decoder_name or row["decoder"]
    try:
        dec = registry.decoder(name)
    except KeyError as exc:
        return {"records": [], "errors": [str(exc).strip("'\"")], "decoder": name}
    for b in row["bindings"]:
        if not decoder_name and any(
            pipeline.subject_matches(p, env.subject) for p in b.get("subjects") or []
        ):
            dec = registry.decoder(b.get("decoder") or "json")
            decoder_config = (
                decoder_config
                if decoder_config is not None
                else b.get("decoder_config")
            )
            name = dec.name
            break
    st = DecoderState(
        config=dict(
            decoder_config if decoder_config is not None else row["decoder_config"]
        ),
        lookup=_lookup,
    )
    m = dict(mapping if mapping is not None else row["mapping"])
    if row["strict"]:
        m["strict"] = True
    try:
        recs = await pipeline.run_decode(dec, env, st, m)
        if env.headers:
            recs = sources.enforce(env.headers, recs)
    except Skipped as exc:
        return {
            "records": [],
            "errors": [],
            "decoder": name,
            "skipped": True,
            "skip_reason": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "records": [],
            "errors": [pipeline.plain_decode_error(exc)],
            "decoder": name,
        }
    return {
        "records": [pipeline.record_json(r) for r in recs],
        "errors": [],
        "decoder": name,
    }


@router.post("/connections/{conn_id}/preview")
async def preview(
    conn_id: uuid.UUID,
    body: dict[str, Any] = Body(...),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run a sample, or with capture the next live message, through a mapping. Nothing is stored."""
    c = await _conn(db, user, conn_id)
    if c is None:
        return error("Connection not found", 404, error_code="NOT_FOUND")
    row = pipeline.connection_row(c)
    await db.close()
    if body.get("capture"):
        r = redis()
        since = int(time.time() * 1000)
        doc = None
        for _ in range(40):
            head = await r.lrange(K.inspector(row["tenant"], row["id"]), 0, 0)
            if head:
                cand = json.loads(head[0])
                if cand.get("t", 0) >= since:
                    doc = cand
                    break
            await asyncio.sleep(0.25)
        if doc is None:
            return error(
                "Nothing arrived in 10 seconds. Check the connection is connected and its source is sending.",
                408,
                error_code="NOTHING_ARRIVED",
            )
        raw = (
            base64.b64decode(doc["payload"])
            if doc.get("encoding") == "base64"
            else str(doc.get("payload") or "").encode()
        )
        env = Envelope(
            row["id"],
            row["tenant"],
            doc.get("subject") or "",
            raw,
            headers=doc.get("headers") or {},
        )
    else:
        raw = _payload(body)
        if raw is None:
            return error(
                "Give a payload (text or JSON) or payload_base64, or capture: true for the next live message.",
                422,
                error_code="VALIDATION_ERROR",
            )
        env = Envelope(
            row["id"],
            row["tenant"],
            str(
                body.get("subject") or (row["config"].get("subjects") or [""])[0] or ""
            ),
            raw,
            headers=dict(body.get("headers") or {}),
        )
    out = await _decode(
        row, env, body.get("decoder"), body.get("decoder_config"), body.get("mapping")
    )
    text, enc = pipeline.payload_preview(env.payload)
    used = body.get("mapping") if body.get("mapping") is not None else row["mapping"]
    pinned = (used or {}).get("subject_separator")
    out["sample"] = {
        "subject": env.subject,
        "subject_segments": M.segments(env.subject, used),
        "subject_separator": pinned or ("/" if "/" in env.subject else "."),
        "payload": text,
        "encoding": enc,
        "size": len(env.payload),
    }
    return success(out)


@router.post("/mapping/suggest")
async def suggest(
    body: dict[str, Any] = Body(...),
    user: User = Depends(require_capability("telemetry.view")),
) -> JSONResponse:
    """A first mapping from one sample message, with the records it gives."""
    raw = _payload(body)
    if raw is None:
        return error("Give a sample payload.", 422, error_code="VALIDATION_ERROR")
    name = body.get("decoder") or "json"
    try:
        dec = registry.decoder(name)
    except KeyError as exc:
        return error(str(exc).strip("'\""), 422, error_code="VALIDATION_ERROR")
    subject = str(body.get("subject") or "")
    cfg = dict(body.get("decoder_config") or {})
    sample: Any = None
    try:
        if isinstance(dec, DocumentDecoder):
            docs = dec.parse(raw, cfg)
            sample = docs[0] if len(docs) == 1 else docs
        else:
            recs = await pipeline.run_decode(
                dec, Envelope("", "", subject, raw), DecoderState(config=cfg), {}
            )
            return success(
                {
                    "mapping": {},
                    "note": f"{dec.label} sets the asset and signals itself, a mapping is optional.",
                    "records": [pipeline.record_json(r) for r in recs],
                    "errors": [],
                }
            )
    except Exception as exc:  # noqa: BLE001
        return success(
            {"mapping": {}, "records": [], "errors": [pipeline.plain_decode_error(exc)]}
        )
    proposal = M.suggest(sample, subject)
    env = Envelope("", "", subject, raw)
    try:
        recs = await pipeline.run_decode(dec, env, DecoderState(config=cfg), proposal)
        return success(
            {
                "mapping": proposal,
                "records": [pipeline.record_json(r) for r in recs],
                "errors": [],
            }
        )
    except Exception as exc:  # noqa: BLE001
        return success(
            {
                "mapping": proposal,
                "records": [],
                "errors": [pipeline.plain_decode_error(exc)],
            }
        )


# inspector, dead letters and the signal registry


@router.get("/connections/{conn_id}/inspector")
async def inspector(
    conn_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    errors_only: bool = False,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """The newest raw messages of a connection with what each decoded to, or why it failed."""
    c = await _conn(db, user, conn_id)
    if c is None:
        return error("Connection not found", 404, error_code="NOT_FOUND")
    raw = await redis().lrange(
        K.inspector(c.tenant_id, c.id), 0, 499 if errors_only else limit - 1
    )
    rows = [json.loads(x) for x in raw]
    if errors_only:
        rows = [x for x in rows if not x.get("ok")][:limit]
    return success(rows, meta={"count": len(rows)})


@router.get("/connections/{conn_id}/dlq")
async def dead_letters(
    conn_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=1000),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    c = await _conn(db, user, conn_id)
    if c is None:
        return error("Connection not found", 404, error_code="NOT_FOUND")
    r = redis()
    key = K.dlq(c.tenant_id, c.id)
    raw = await r.lrange(key, 0, limit - 1)
    total = await r.llen(key) if hasattr(r, "llen") else len(raw)
    rows = []
    for x in raw:
        doc = json.loads(x)
        text, enc = pipeline.payload_preview(
            base64.b64decode(doc.get("payload_b64") or "")
        )
        doc["payload"], doc["encoding"] = text, enc
        doc.pop("payload_b64", None)
        rows.append(doc)
    return success(rows, meta={"total": total})


@router.delete("/connections/{conn_id}/dlq")
async def clear_dead_letters(
    conn_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return forbidden(_manage_refusal())
    c = await _conn(db, user, conn_id)
    if c is None:
        return error("Connection not found", 404, error_code="NOT_FOUND")
    await redis().delete(K.dlq(c.tenant_id, c.id))
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.dlq.cleared",
        {"name": c.name},
        request,
        resource_type=access.KIND,
        resource_id=str(c.id),
    )
    await db.commit()
    return success({"cleared": True})


@router.post("/connections/{conn_id}/dlq/replay")
async def replay(
    conn_id: uuid.UUID,
    request: Request,
    body: dict[str, Any] = Body(default={}),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run dead letters through the connection's current decoder and mapping, and store what now works."""
    if not await access.has(db, user, "telemetry.manage"):
        return forbidden(_manage_refusal())
    c = await _conn(db, user, conn_id)
    if c is None:
        return error("Connection not found", 404, error_code="NOT_FOUND")
    from app.telemetry.store import Batch, ConnInfo, Store
    from app.telemetry.writer import Writer

    row = pipeline.connection_row(c)
    r = redis()
    key = K.dlq(c.tenant_id, c.id)
    raw = await r.lrange(key, 0, pipeline.DLQ_RING - 1)
    ids = set(body.get("ids") or [])
    picked = [(x, json.loads(x)) for x in raw]
    if ids:
        picked = [(x, d) for x, d in picked if d.get("id") in ids]
    writer = Writer(r)
    store = Store(writer.lookup, history_interval_ms=0)
    info = ConnInfo(
        id=row["id"],
        tenant=row["tenant"],
        name=row["name"],
        team_id=row["team_id"],
        transport=row["transport"],
    )
    replayed, failing, history_rows = 0, [], []
    from app.services import events as E

    for raw_entry, doc in picked:
        if doc.get("truncated"):
            failing.append(
                {
                    "id": doc.get("id"),
                    "reason": f"This message was {doc.get('size')} bytes, only the first {pipeline.DLQ_PAYLOAD_MAX} were kept, so it cannot be replayed. Ask the source to send it again.",
                }
            )
            continue
        env = pipeline.envelope_from_dlq(doc, row["id"], row["tenant"])
        out = await _decode(row, env, None, None, None)
        if out["errors"]:
            failing.append({"id": doc.get("id"), "reason": out["errors"][0]})
            continue
        from app.telemetry.decoders.base import Metric, Record

        recs = []
        for rd in out["records"]:
            rd = dict(rd)
            rd["metrics"] = [Metric(**m) for m in rd.get("metrics") or []]
            recs.append(Record(**rd))
        b = Batch()
        store.admit(info, env.t_recv, b)
        await store.apply(info, recs, env.t_recv, b)
        await writer.flush(b)
        history_rows.extend(b.history)
        for t, kind, payload in b.events:
            await E.emit(db, t, kind, payload)
        await r.lrem(key, 1, raw_entry)
        replayed += 1
    if history_rows:
        try:
            from app.telemetry import history

            await history.write(await tsdb(), history_rows)
        except Exception:  # noqa: BLE001
            pass
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.dlq.replayed",
        {"name": c.name, "replayed": replayed, "still_failing": len(failing)},
        request,
        resource_type=access.KIND,
        resource_id=str(c.id),
    )
    await db.commit()
    return success(
        {
            "replayed": replayed,
            "still_failing": failing,
            "remaining": len(raw) - replayed,
        }
    )


@router.get("/connections/{conn_id}/signals")
async def signals(
    conn_id: uuid.UUID,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Every signal this source has sent, with when it was first and last seen."""
    c = await _conn(db, user, conn_id)
    if c is None:
        return error("Connection not found", 404, error_code="NOT_FOUND")
    raw = await redis().hgetall(K.signals(c.tenant_id, c.id))
    retired: dict[str, list[dict[str, Any]]] = {}
    for path, at in (await redis().hgetall(K.retired(c.tenant_id, c.id))).items():
        g, n, d, name = (path.split("/", 3) + ["", "", "", ""])[:4]
        retired.setdefault(name, []).append(
            {"group": g, "node": n, "device": d, "retired_at": int(at)}
        )
    rows = []
    for name, v in raw.items():
        try:
            doc = json.loads(v)
        except ValueError:
            continue
        row = {"name": name, **doc}
        if name in retired:
            # a later birth no longer declared it on these assets, history is kept
            row["retired"] = retired[name]
        rows.append(row)
    rows.sort(key=lambda x: x["name"])
    return success(rows, meta={"total": len(rows)})


@router.get("/events/{group}/{node}")
async def app_events(
    group: str,
    node: str,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Newest messages kept whole as events, such as order.created from a payments stream."""
    scope = await access.scope_for(db, user)
    r = redis()
    raw = await r.lrange(K.events(user.tenant_id, group, node), 0, limit - 1)
    rows = [json.loads(x) for x in raw]
    rows = [x for x in rows if scope.sees(x.get("connection_id"))]
    return success(rows, meta={"count": len(rows)})


# keys on HTTP push sources


async def _push_source(db: AsyncSession, user: User, conn_id: uuid.UUID) -> Any:
    if not await access.has(db, user, "telemetry.manage"):
        return forbidden(_manage_refusal())
    c = await _conn(db, user, conn_id)
    if c is None:
        return error("Connection not found", 404, error_code="NOT_FOUND")
    if c.transport != "http_push":
        return error(
            "Device keys are for HTTP push sources. Other transports use their own credentials.",
            422,
            error_code="VALIDATION_ERROR",
        )
    return c


@router.get("/connections/{conn_id}/keys")
async def list_keys(
    conn_id: uuid.UUID,
    include_revoked: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    c = await _push_source(db, user, conn_id)
    if isinstance(c, JSONResponse):
        return c
    from models.telemetry import TelemetryDeviceKey

    q = select(TelemetryDeviceKey).where(TelemetryDeviceKey.connection_id == c.id)
    if not include_revoked:
        q = q.where(TelemetryDeviceKey.revoked_at.is_(None))
    rows = (await db.execute(q.order_by(TelemetryDeviceKey.device_id))).scalars().all()
    return success([sources.key_json(k) for k in rows], meta={"total": len(rows)})


@router.post("/connections/{conn_id}/keys")
async def create_key(
    conn_id: uuid.UUID,
    request: Request,
    body: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """A key for one device, or a gateway, shown once."""
    c = await _push_source(db, user, conn_id)
    if isinstance(c, JSONResponse):
        return c
    try:
        k, raw = await sources.create_key(
            db,
            c,
            device_id=body.get("device_id"),
            kind=body.get("kind") or "device",
            group=body.get("group"),
            allowed_nodes=body.get("allowed_nodes"),
            label=body.get("label") or "",
            created_by=user.id,
        )
    except ValueError as exc:
        return error(str(exc), 422, error_code="VALIDATION_ERROR")
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.key.created",
        {"connection": c.name, "device_id": k.device_id, "kind": k.kind},
        request,
        resource_type=access.KIND,
        resource_id=str(c.id),
    )
    await db.commit()
    return success({**sources.key_json(k), "key": raw}, status_code=201)


@router.post("/connections/{conn_id}/keys/bulk")
async def create_keys_bulk(
    conn_id: uuid.UUID,
    request: Request,
    body: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Keys for many devices from CSV (device_id, optional label and group). Each shown once."""
    c = await _push_source(db, user, conn_id)
    if isinstance(c, JSONResponse):
        return c
    try:
        rows = sources.parse_csv(str(body.get("csv") or ""))
    except ValueError as exc:
        return error(str(exc), 422, error_code="VALIDATION_ERROR")
    out = []
    for r in rows:
        k, raw = await sources.create_key(
            db,
            c,
            device_id=r["device_id"],
            label=r["label"],
            group=r["group"] or None,
            created_by=user.id,
        )
        out.append({**sources.key_json(k), "key": raw})
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.key.bulk_created",
        {"connection": c.name, "count": len(out)},
        request,
        resource_type=access.KIND,
        resource_id=str(c.id),
    )
    await db.commit()
    csv_out = "device_id,key\n" + "".join(f"{x['device_id']},{x['key']}\n" for x in out)
    return success(out, meta={"count": len(out), "csv": csv_out}, status_code=201)


@router.delete("/connections/{conn_id}/keys/{key_id}")
async def revoke_key(
    conn_id: uuid.UUID,
    key_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    c = await _push_source(db, user, conn_id)
    if isinstance(c, JSONResponse):
        return c
    from datetime import datetime, timezone

    from models.telemetry import TelemetryDeviceKey

    k = (
        await db.execute(
            select(TelemetryDeviceKey).where(
                TelemetryDeviceKey.id == key_id,
                TelemetryDeviceKey.connection_id == c.id,
            )
        )
    ).scalar_one_or_none()
    if k is None:
        return error("Key not found", 404, error_code="NOT_FOUND")
    if k.revoked_at is None:
        k.revoked_at = datetime.now(timezone.utc)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.key.revoked",
        {"connection": c.name, "device_id": k.device_id},
        request,
        resource_type=access.KIND,
        resource_id=str(c.id),
    )
    await db.commit()
    return success(sources.key_json(k))
