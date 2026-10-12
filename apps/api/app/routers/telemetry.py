"""Machine telemetry: broker connections, live device state, history, raw frames, live stream and commands."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.audit import log_action
from app.core.capabilities import cap_words, require_capability
from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.permissions import is_admin
from app.core.responses import error, success
from app.telemetry import access, brokers, history, lifecycle, reads
from app.telemetry import keys as K
from app.telemetry import quota as Q
from app.telemetry import sparkplug as sp
from app.telemetry import stream as S
from models.governance import PermissionSet
from models.telemetry import DEFAULT_TOPICS, TelemetryConnection
from models.tenant import Tenant
from models.user import User

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

MASK = "********"
COMMAND_LIMIT_PER_SEC = 20
_redis: Any = None
_pool: Any = None
_pool_lock = asyncio.Lock()
_health_cache: dict[Any, tuple[float, dict[str, Any]]] = {}


def redis() -> Any:
    global _redis
    if _redis is None:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(
            settings.redis_url, decode_responses=True, max_connections=200
        )
    return _redis


async def tsdb() -> Any:
    global _pool
    async with _pool_lock:
        if _pool is None:
            _pool = await history.create_pool(min_size=1, max_size=4)
    return _pool


def _iso(v: Any) -> str | None:
    return v.isoformat() if v is not None else None


def new_ingest_token() -> tuple[str, str]:
    import hashlib
    import secrets as _secrets

    raw = "tpk_" + _secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def forbidden(message: str) -> JSONResponse:
    return error(message, 403, error_code="FORBIDDEN")


def _forget_refusal() -> str:
    return (
        f"Forgetting devices needs {cap_words('telemetry.manage')}. "
        "An admin can grant it under Admin, Permissions."
    )


def _manage_refusal() -> str:
    return (
        f"Changing brokers needs {cap_words('telemetry.manage')}. "
        "An admin can grant it under Admin, Permissions."
    )


def _command_refusal() -> str:
    return (
        f"Sending commands needs {cap_words('telemetry.command')}. "
        "An admin can add you to Machine operators under Admin, Permissions."
    )


async def _changed() -> None:
    access.forget()
    try:
        await redis().publish(K.CHANGED, str(time.time()))
    except Exception:  # noqa: BLE001
        pass


# connections


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # MQTT only, every other transport takes its address in config
    broker_url: str | None = Field(default=None, max_length=1000)
    topics: list[str] | None = None
    raw_topics: list[str] | None = None
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=1000)
    protocol: str = "sparkplug_b"
    enabled: bool = True
    shared_subscription: bool = False
    team_id: uuid.UUID | None = None


class ConnectionTestIn(BaseModel):
    transport: str | None = None
    broker_url: str | None = Field(default=None, max_length=1000)
    config: dict[str, Any] | None = None
    secrets: dict[str, Any] | None = None
    subjects: list[str] | None = None
    topics: list[str] | None = None
    raw_topics: list[str] | None = None
    username: str | None = None
    password: str | None = None


def _row(
    c: TelemetryConnection,
    status: dict[str, Any] | None,
    teams: dict[str, str],
    shares: dict[str, int],
    can_edit: bool,
) -> dict[str, Any]:
    st = status or {}
    tid = str(c.team_id) if c.team_id else None
    return {
        "id": str(c.id),
        "name": c.name,
        "broker_url": c.broker_url,
        "topics": list(c.topics or []),
        "raw_topics": list(c.raw_topics or []),
        "username": c.username or "",
        "password": MASK if c.password else "",
        "has_password": bool(c.password),
        "protocol": c.protocol,
        "enabled": bool(c.enabled),
        "shared_subscription": bool(c.shared_subscription),
        "team_id": tid,
        "team_name": teams.get(tid) if tid else None,
        "share_count": shares.get(str(c.id), 0),
        "created_by": str(c.created_by) if c.created_by else None,
        "created_at": _iso(c.created_at),
        "updated_at": _iso(c.updated_at),
        "status": st.get("status") or ("disabled" if not c.enabled else "connecting"),
        "last_error": st.get("last_error"),
        "messages_per_second": st.get("messages_per_second", 0),
        "last_message_at": st.get("last_message_at"),
        "dropped": st.get("dropped", 0),
        "pool": st.get("pool"),
        "can_edit": can_edit,
        "transport": getattr(c, "transport", None) or "mqtt",
        "subjects": list(c.topics or []),
        "config": {k: v for k, v in (getattr(c, "config", None) or {}).items()},
        "secrets": {k: MASK for k in (getattr(c, "secrets", None) or {})},
        "decoder": getattr(c, "decoder", None) or "sparkplug_b",
        "decoder_config": dict(getattr(c, "decoder_config", None) or {}),
        "mapping": dict(getattr(c, "mapping", None) or {}),
        "strict": bool(getattr(c, "strict", False)),
        "has_ingest_token": bool(getattr(c, "ingest_token_hash", None)),
        "ingest_url": (
            f"/api/telemetry/ingest/{c.id}"
            if (getattr(c, "transport", None) or "mqtt") == "http_push"
            else None
        ),
        "clock_skew_ms": st.get("clock_skew_ms"),
        "clock_skew_flagged": abs(st.get("clock_skew_ms") or 0) > 5000,
        "decode_errors": st.get("decode_errors", 0),
        "pipeline": st.get("pipeline") or {},
        "last_reasons": st.get("last_reasons") or {},
        "diagnosis": reads.diagnose(bool(c.enabled), st, list(c.topics or [])),
    }


async def _validate(
    db: AsyncSession,
    user: User,
    body: dict[str, Any],
    current: TelemetryConnection | None,
) -> tuple[dict[str, Any] | None, str | None]:
    out: dict[str, Any] = {}
    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            return None, "Give the broker a name, for example Site broker"
        out["name"] = name[:255]
    transport = (
        body.get("transport") or (current.transport if current else None) or "mqtt"
    )
    if "broker_url" in body and (transport == "mqtt" or body.get("broker_url")):
        if transport == "mqtt":
            try:
                brokers.parse_url(body.get("broker_url") or "")
            except ValueError as exc:
                return None, str(exc)
        out["broker_url"] = (body.get("broker_url") or "").strip()
    try:
        if "topics" in body:
            out["topics"] = brokers.clean_topics(
                body.get("topics"), default=DEFAULT_TOPICS
            )
            if not out["topics"]:
                out["topics"] = list(DEFAULT_TOPICS)
        if "raw_topics" in body:
            out["raw_topics"] = brokers.clean_topics(body.get("raw_topics"))
    except ValueError as exc:
        return None, str(exc)
    if "protocol" in body:
        if (body.get("protocol") or "sparkplug_b") != "sparkplug_b":
            return None, "Only Sparkplug B (sparkplug_b) is supported for now"
        out["protocol"] = "sparkplug_b"
    if "username" in body:
        out["username"] = (body.get("username") or "").strip() or None
    if "password" in body:
        pw = body.get("password")
        if pw != MASK:
            out["password"] = crypto.encrypt(user.tenant_id, pw) if pw else None
    for flag in ("enabled", "shared_subscription"):
        if flag in body and body[flag] is not None:
            out[flag] = bool(body[flag])
    if "team_id" in body:
        tid = body.get("team_id")
        if tid in (None, ""):
            out["team_id"] = None
        else:
            try:
                tid = uuid.UUID(str(tid))
            except ValueError:
                return None, "team_id must be the id of a team"
            ps = (
                await db.execute(
                    select(PermissionSet.id).where(
                        PermissionSet.id == tid,
                        PermissionSet.tenant_id == user.tenant_id,
                    )
                )
            ).scalar()
            if ps is None:
                return None, "That team does not exist in this workspace"
            out["team_id"] = tid
    problem = _validate_streams(user, body, current, out)
    if problem:
        return None, problem
    return out, None


def _validate_streams(
    user: User,
    body: dict[str, Any],
    current: TelemetryConnection | None,
    out: dict[str, Any],
) -> str | None:
    """Transport, its settings and secrets, decoder, mapping and strict mode."""
    from app.telemetry import registry

    transport = (
        body.get("transport") or (current.transport if current else None) or "mqtt"
    )
    conns = registry.connectors()
    if transport not in conns:
        return (
            f"There is no {transport} transport. Pick one of {', '.join(sorted(conns))}"
        )
    if "transport" in body or current is None:
        out["transport"] = transport
    cls = conns[transport]
    if (
        "subjects" not in body
        and isinstance(body.get("config"), dict)
        and body["config"].get("subjects")
    ):
        # the transport's own subjects field, lifted to the topics column
        body["subjects"] = body["config"]["subjects"]
    if "subjects" in body:
        try:
            if transport == "mqtt":
                out["topics"] = brokers.clean_topics(
                    body.get("subjects"), default=DEFAULT_TOPICS
                ) or list(DEFAULT_TOPICS)
            else:
                subj = body.get("subjects")
                if isinstance(subj, str):
                    subj = subj.replace("\n", ",").split(",")
                out["topics"] = [
                    str(x).strip() for x in (subj or []) if str(x).strip()
                ][:200]
        except ValueError as exc:
            return str(exc)
    elif current is None and transport != "mqtt" and "topics" not in body:
        out["topics"] = []
    secret_keys = {f.key for f in cls.config_fields if f.kind == "secret"}
    cfg = dict(current.config or {}) if current is not None else {}
    if "config" in body:
        if not isinstance(body["config"], dict):
            return "config must be an object of the transport's settings"
        cfg = {}
        for k, v in body["config"].items():
            if k in secret_keys:
                body.setdefault("secrets", {})
                if isinstance(body["secrets"], dict):
                    body["secrets"].setdefault(k, v)
                continue
            cfg[k] = v
        if transport == "mqtt" and cfg.get("broker_url") and "broker_url" not in out:
            try:
                brokers.parse_url(cfg["broker_url"])
            except ValueError as exc:
                return str(exc)
            out["broker_url"] = cfg["broker_url"].strip()
        out["config"] = cfg
    secrets = dict(current.secrets or {}) if current is not None else {}
    if isinstance(body.get("secrets"), dict):
        for k, v in body["secrets"].items():
            if v == MASK:
                continue
            if v in (None, ""):
                secrets.pop(k, None)
            else:
                secrets[k] = crypto.encrypt(user.tenant_id, str(v))
        out["secrets"] = secrets
    if transport == "mqtt" and "password" in out:
        # the T1 password field and the mqtt secret are one value
        if out["password"]:
            secrets["password"] = out["password"]
        else:
            secrets.pop("password", None)
        out["secrets"] = secrets
    if (
        transport == "mqtt"
        and isinstance(body.get("secrets"), dict)
        and "password" in out.get("secrets", {})
    ):
        out["password"] = out["secrets"]["password"]
    if "config" in out:
        from app.telemetry.connectors.base import clean_config

        out["config"], problems = clean_config(cls.config_fields, out["config"])
        if problems:
            return ". ".join(problems)
        cfg = out["config"]
    have = {**cfg, **{k: 1 for k in secrets}}
    if transport == "mqtt":
        have["broker_url"] = out.get("broker_url") or (
            current.broker_url if current else ""
        )
    missing = [
        f.label or f.key
        for f in cls.config_fields
        if f.required and not have.get(f.key) and f.key != "subjects"
    ]
    if missing:
        return f"{cls.label} needs {', '.join(missing)}"
    if "decoder" in body or current is None:
        dec = (
            body.get("decoder")
            or (current.decoder if current else None)
            or cls.default_decoder
            or "json"
        )
        decs = registry.decoders()
        if dec not in decs:
            return f"There is no {dec} decoder. Pick one of {', '.join(sorted(decs))}"
        out["decoder"] = dec
    for key in ("decoder_config", "mapping"):
        if key in body:
            if body[key] is not None and not isinstance(body[key], dict):
                return f"{key} must be an object"
            out[key] = dict(body[key] or {})
    if "mapping" in out:
        for tkey in ("group", "node", "device", "records"):
            v = out["mapping"].get(tkey)
            if v is not None and not isinstance(v, str):
                return f"mapping.{tkey} must be text, such as {{subject.0}} or $.machine.id"
    if "strict" in body and body["strict"] is not None:
        out["strict"] = bool(body["strict"])
    return None


async def _serialize(
    db: AsyncSession, user: User, conns: list[TelemetryConnection], scope: access.Scope
) -> list[dict[str, Any]]:
    statuses = await reads.connection_status(redis(), conns)
    shares = await access.share_counts(db, [c.id for c in conns])
    teams = dict(scope.teams)
    manage = scope.everything
    return [
        _row(
            c,
            statuses.get(str(c.id)),
            teams,
            shares,
            manage or c.created_by == user.id,
        )
        for c in conns
    ]


@router.get("/connections")
async def list_connections(
    q: str = "",
    team: str = "",
    status: str = "",
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    scope = await access.scope_for(db, user)
    conns = [c for c in scope.connections if scope.sees(str(c.id))]
    if q:
        ql = q.strip().lower()
        conns = [c for c in conns if ql in c.name.lower() or ql in c.broker_url.lower()]
    if team:
        if team in ("none", "workspace"):
            conns = [c for c in conns if not c.team_id]
        else:
            conns = [
                c
                for c in conns
                if c.team_id
                and (str(c.team_id) == team or scope.teams.get(str(c.team_id)) == team)
            ]
    rows = await _serialize(db, user, conns, scope)
    if status:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    return success(
        rows[offset : offset + limit],
        meta={
            "total": total,
            "limit": limit,
            "offset": offset,
            "can_manage": scope.everything,
            "example": brokers.EXAMPLE,
        },
    )


@router.post("/connections")
async def create_connection(
    request: Request,
    body: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return forbidden(_manage_refusal())
    try:
        ConnectionIn(
            **{k: v for k, v in body.items() if k in ConnectionIn.model_fields}
        )
    except Exception as exc:  # noqa: BLE001
        return error(
            f"Check the broker details: {exc}", 422, error_code="VALIDATION_ERROR"
        )
    transport = body.get("transport") or "mqtt"
    cfg_url = (
        (body.get("config") or {}).get("broker_url")
        if isinstance(body.get("config"), dict)
        else None
    )
    if transport == "mqtt" and not body.get("broker_url") and cfg_url:
        body["broker_url"] = cfg_url
    if not str(body.get("name") or "").strip() or (
        transport == "mqtt" and not str(body.get("broker_url") or "").strip()
    ):
        return error(
            "Give the connection a name"
            + (
                f" and an address, for example Site broker at {brokers.EXAMPLE}"
                if transport == "mqtt"
                else ""
            ),
            422,
            error_code="VALIDATION_ERROR",
        )
    if transport == "mqtt":
        if "subjects" not in body:
            body.setdefault("topics", list(DEFAULT_TOPICS))
        body.setdefault("raw_topics", [])
    else:
        body.setdefault("broker_url", "")
    fields, problem = await _validate(db, user, body, None)
    if problem:
        return error(problem, 422, error_code="VALIDATION_ERROR")
    quota = await Q.for_tenant(db, user.tenant_id)
    have = (
        await db.execute(
            select(func.count())
            .select_from(TelemetryConnection)
            .where(TelemetryConnection.tenant_id == user.tenant_id)
        )
    ).scalar() or 0
    if have >= quota["max_connections"]:
        return error(
            f"This workspace already has {have} brokers, its limit is "
            f"{quota['max_connections']}. Remove one or ask an admin to raise the limit "
            "under Admin, Settings, Telemetry.",
            429,
            error_code="QUOTA_EXCEEDED",
            details={"limit": quota["max_connections"], "used": have},
        )
    fields.setdefault("broker_url", body.get("broker_url") or "")
    conn = TelemetryConnection(
        tenant_id=user.tenant_id,
        created_by=user.id,
        **{
            "topics": list(DEFAULT_TOPICS) if transport == "mqtt" else [],
            "raw_topics": [],
            "enabled": True,
            "shared_subscription": False,
            "config": {},
            "secrets": {},
            "decoder_config": {},
            "mapping": {},
            "strict": False,
            **fields,
        },
    )
    conn.protocol = conn.decoder or "sparkplug_b"
    token = None
    if conn.transport == "http_push":
        token, conn.ingest_token_hash = new_ingest_token()
    db.add(conn)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return error(
            f"There is already a broker called {fields.get('name')}. Pick another name.",
            409,
            error_code="DUPLICATE_NAME",
        )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.connection.created",
        {"name": conn.name, "broker_url": conn.broker_url},
        request,
        resource_type=access.KIND,
        resource_id=str(conn.id),
    )
    await db.commit()
    await _changed()
    scope = await access.scope_for(db, user, fresh=True)
    rows = await _serialize(db, user, [conn], scope)
    if token:
        # shown this once, only its hash is kept
        rows[0]["ingest_token"] = token
    return success(rows[0], status_code=201)


async def _get_visible(
    db: AsyncSession, user: User, conn_id: uuid.UUID
) -> tuple[TelemetryConnection | None, access.Scope]:
    scope = await access.scope_for(db, user)
    for c in scope.connections:
        if c.id == conn_id:
            return (c if scope.sees(str(c.id)) else None), scope
    # made a moment ago in another worker
    scope = await access.scope_for(db, user, fresh=True)
    for c in scope.connections:
        if c.id == conn_id and scope.sees(str(c.id)):
            return c, scope
    return None, scope


@router.get("/connections/{conn_id}")
async def get_connection(
    conn_id: uuid.UUID,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    c, scope = await _get_visible(db, user, conn_id)
    if c is None:
        return error("Broker not found", 404, error_code="NOT_FOUND")
    rows = await _serialize(db, user, [c], scope)
    return success(rows[0])


async def _load_for_write(
    db: AsyncSession, user: User, conn_id: uuid.UUID
) -> TelemetryConnection | None:
    return (
        await db.execute(
            select(TelemetryConnection).where(
                TelemetryConnection.id == conn_id,
                TelemetryConnection.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()


@router.patch("/connections/{conn_id}")
async def update_connection(
    conn_id: uuid.UUID,
    request: Request,
    body: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return forbidden(_manage_refusal())
    c = await _load_for_write(db, user, conn_id)
    if c is None:
        return error("Broker not found", 404, error_code="NOT_FOUND")
    fields, problem = await _validate(db, user, body, c)
    if problem:
        return error(problem, 422, error_code="VALIDATION_ERROR")
    before = {"name": c.name, "broker_url": c.broker_url, "enabled": c.enabled}
    for k, v in (fields or {}).items():
        setattr(c, k, v)
    c.updated_at = datetime.now(timezone.utc)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return error(
            f"There is already a broker called {fields.get('name')}. Pick another name.",
            409,
            error_code="DUPLICATE_NAME",
        )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.connection.updated",
        {"changed": sorted((fields or {}).keys())},
        request,
        resource_type=access.KIND,
        resource_id=str(c.id),
        old_value=before,
        new_value={"name": c.name, "broker_url": c.broker_url, "enabled": c.enabled},
    )
    await db.commit()
    brokers.publisher.forget(str(c.id))
    await _changed()
    scope = await access.scope_for(db, user, fresh=True)
    rows = await _serialize(db, user, [c], scope)
    return success(rows[0])


@router.delete("/connections/{conn_id}")
async def delete_connection(
    conn_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return forbidden(_manage_refusal())
    c = await _load_for_write(db, user, conn_id)
    if c is None:
        return error("Broker not found", 404, error_code="NOT_FOUND")
    from models.resource_share import ResourceShare
    from sqlalchemy import delete

    await db.execute(
        delete(ResourceShare).where(
            ResourceShare.resource_type == access.KIND,
            ResourceShare.resource_id == c.id,
        )
    )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.connection.deleted",
        {"name": c.name, "broker_url": c.broker_url},
        request,
        resource_type=access.KIND,
        resource_id=str(c.id),
    )
    await db.delete(c)
    await db.commit()
    brokers.publisher.forget(str(conn_id))
    await _changed()
    return success({"deleted": True, "id": str(conn_id)})


@router.post("/connections/test")
async def test_unsaved_connection(
    body: ConnectionTestIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return forbidden(_manage_refusal())
    transport = body.transport or "mqtt"
    cfg = dict(body.config or {})
    secrets = dict(body.secrets or {})
    if transport == "mqtt":
        try:
            topics = brokers.clean_topics(
                body.subjects or body.topics, default=DEFAULT_TOPICS
            ) + brokers.clean_topics(body.raw_topics)
        except ValueError as exc:
            return error(str(exc), 422, error_code="VALIDATION_ERROR")
        cfg.setdefault("broker_url", body.broker_url or "")
        cfg["subjects"] = topics
        if body.username:
            cfg["username"] = body.username
        if body.password:
            secrets["password"] = body.password
    elif body.subjects is not None:
        cfg["subjects"] = body.subjects
    return success(await _run_test(transport, cfg, secrets))


@router.post("/connections/{conn_id}/test")
async def test_connection(
    conn_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return forbidden(_manage_refusal())
    c = await _load_for_write(db, user, conn_id)
    if c is None:
        return error("Broker not found", 404, error_code="NOT_FOUND")
    from app.telemetry import pipeline

    row = pipeline.connection_row(c)
    return success(await _run_test(row["transport"], row["config"], row["secrets"]))


async def _run_test(
    transport: str, cfg: dict[str, Any], secrets: dict[str, Any]
) -> dict[str, Any]:
    from app.telemetry import registry

    blank = {
        "ok": False,
        "connected": False,
        "messages": 0,
        "subjects_seen": [],
        "sample": None,
    }
    try:
        connector = registry.connector(transport)
        out = await asyncio.wait_for(connector.test(cfg, secrets), timeout=12)
    except KeyError as exc:
        out = {**blank, "error": str(exc).strip("'\"")}
    except asyncio.TimeoutError:
        out = {
            **blank,
            "error": "The test took longer than 12 seconds and was stopped. Check the address and the network.",
        }
    except Exception as exc:  # noqa: BLE001
        out = {**blank, "error": str(exc)}
    out.setdefault("subjects_seen", out.get("topics_seen") or [])
    out.setdefault("topics_seen", out.get("subjects_seen") or [])
    out.setdefault("sample", None)
    return out


@router.get("/transports")
async def list_transports(
    user: User = Depends(require_capability("telemetry.view")),
) -> JSONResponse:
    """Every transport the platform can read from, with the fields its form needs."""
    from app.telemetry import registry

    cat = registry.catalogue()
    return success(cat["transports"], meta={"unavailable": cat["unavailable"]})


@router.get("/decoders")
async def list_decoders(
    user: User = Depends(require_capability("telemetry.view")),
) -> JSONResponse:
    """Every payload format the platform can decode, with the fields its form needs."""
    from app.telemetry import registry

    cat = registry.catalogue()
    return success(cat["decoders"], meta={"unavailable": cat["unavailable"]})


@router.get("/diagnose")
async def diagnose_asset(
    group: str,
    node: str,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Why an asset's data is or is not showing for this person."""
    scope = await access.scope_for(db, user)
    raw = await redis().hget(K.index(user.tenant_id), K.index_field(group, node, ""))
    if raw is None:
        return success(
            {
                "state": "unknown_asset",
                "message": f"Nothing called {node} in group {group} has reported yet.",
                "fix": "Check the source sends with this group and asset, or preview its messages on the connection.",
            }
        )
    doc = json.loads(raw)
    cid = doc.get("connection_id")
    if not scope.sees(cid):
        return success(
            {
                "state": "not_shared",
                "message": f"{node} reports through a connection that belongs to a team you are not in.",
                "fix": "Ask an admin or the connection's owner to share it with you, or to add you to its team.",
            }
        )
    conn = next((c for c in scope.connections if str(c.id) == cid), None)
    if conn is None:
        return success(
            {
                "state": "connection_removed",
                "message": "The connection this asset reported through was removed.",
                "fix": None,
            }
        )
    st = (await reads.connection_status(redis(), [conn])).get(str(conn.id))
    d = reads.diagnose(bool(conn.enabled), st, list(conn.topics or []))
    d.update(
        {
            "connection_id": str(conn.id),
            "connection": conn.name,
            "online": bool(doc.get("online")),
        }
    )
    if d["state"] == "ok" and not doc.get("online"):
        d.update(
            {
                "state": "offline",
                "message": f"{node} is offline. It comes back when it reports again.",
                "fix": None,
            }
        )
    return success(d)


@router.get("/connections/{conn_id}/diagnose")
async def diagnose_connection(
    conn_id: uuid.UUID,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    c, scope = await _get_visible(db, user, conn_id)
    if c is None:
        return error(
            "Connection not found, or it belongs to a team you are not in. Ask an admin to share it with you.",
            404,
            error_code="NOT_FOUND",
        )
    st = (await reads.connection_status(redis(), [c])).get(str(c.id))
    return success(reads.diagnose(bool(c.enabled), st, list(c.topics or [])))


@router.get("/teams")
async def list_teams(
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Teams a broker can belong to. A team is a permission set, managed under Admin, Permissions."""
    scope = await access.scope_for(db, user)
    if scope.everything:
        rows = (
            await db.execute(
                select(PermissionSet.id, PermissionSet.name)
                .where(PermissionSet.tenant_id == user.tenant_id)
                .order_by(PermissionSet.name)
            )
        ).all()
        teams = [{"id": str(i), "name": n} for i, n in rows]
    else:
        teams = [
            {"id": i, "name": n}
            for i, n in sorted(scope.teams.items(), key=lambda x: x[1])
        ]
    return success(teams)


@router.get("/quota")
async def get_quota(
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    base = await Q.defaults()
    st = (
        await db.execute(select(Tenant.settings).where(Tenant.id == user.tenant_id))
    ).scalar()
    return success(
        {
            "effective": Q.merge(base, st),
            "defaults": base,
            "override": (st or {}).get(Q.OVERRIDE_KEY) or {},
        }
    )


@router.put("/quota")
async def set_quota(
    request: Request,
    body: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not is_admin(user):
        return forbidden("Only an admin can change this workspace's telemetry limits.")
    clean: dict[str, int] = {}
    for k in Q.FIELDS:
        if body.get(k) in (None, ""):
            continue
        try:
            v = int(body[k])
        except (TypeError, ValueError):
            return error(
                f"{k} must be a whole number", 422, error_code="VALIDATION_ERROR"
            )
        if v < 1:
            return error(f"{k} must be at least 1", 422, error_code="VALIDATION_ERROR")
        clean[k] = v
    t = (
        await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    ).scalar_one()
    st = dict(t.settings or {})
    st[Q.OVERRIDE_KEY] = clean
    t.settings = st
    await log_action(
        db, user.tenant_id, user.id, "telemetry.quota.updated", clean, request
    )
    await db.commit()
    return success({"effective": Q.merge(await Q.defaults(), st), "override": clean})


# devices and readings


@router.get("/devices")
async def list_devices(
    q: str = "",
    group: str = "",
    node: str = "",
    status: str = "",
    team: str = "",
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if status and status not in ("online", "offline"):
        return error(
            "status must be online or offline", 422, error_code="VALIDATION_ERROR"
        )
    scope = await access.scope_for(db, user)
    rows = await reads.all_devices(redis(), user.tenant_id)
    rows = reads.filter_devices(
        rows,
        scope,
        q=q,
        group=group,
        node=node,
        status=status,
        team=team,
        teams=scope.teams,
    )
    total = len(rows)
    return success(
        rows[offset : offset + limit],
        meta={
            "total": total,
            "limit": limit,
            "offset": offset,
            "online": sum(1 for r in rows if r["online"]),
        },
    )


async def _node_conn(tenant: Any, g: str, n: str) -> str | None:
    return await redis().hget(K.device(tenant, g, n, ""), "_conn")


class ForgetIn(BaseModel):
    offline_for_s: int = Field(..., ge=60)
    group: str = ""
    node_glob: str = ""
    connection_id: str = ""
    dry_run: bool = False
    limit: int = Field(lifecycle.BULK_MAX, ge=1, le=lifecycle.BULK_MAX)


@router.post("/devices/forget")
async def forget_devices(
    body: ForgetIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Forgets offline devices in bulk, a dry run counts them first. History stays."""
    if not await access.has(db, user, "telemetry.manage"):
        return forbidden(_forget_refusal())
    scope = await access.scope_for(db, user)
    out = await lifecycle.forget_matching(
        redis(),
        user.tenant_id,
        scope,
        offline_for_s=body.offline_for_s,
        group=body.group.strip(),
        node_glob=body.node_glob.strip(),
        connection_id=body.connection_id.strip(),
        limit=body.limit,
        dry_run=body.dry_run,
    )
    if not body.dry_run and out["forgotten"]:
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "telemetry.devices.forgotten",
            {
                "count": out["forgotten"],
                "offline_for_s": body.offline_for_s,
                "group": body.group,
                "node_glob": body.node_glob,
                "connection_id": body.connection_id,
            },
            request,
            resource_type="telemetry_device",
        )
        await db.commit()
    return success(out)


@router.delete("/devices/{group}/{node}")
async def forget_device(
    group: str,
    node: str,
    request: Request,
    device: str = "",
    force: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Forgets one device, or a whole asset with its parts when device is left out."""
    if not await access.has(db, user, "telemetry.manage"):
        return forbidden(_forget_refusal())
    scope = await access.scope_for(db, user)
    r = redis()
    raw = await r.hget(K.index(user.tenant_id), K.index_field(group, node, device))
    doc = json.loads(raw) if raw else None
    name = f"{group}/{node}" + (f"/{device}" if device else "")
    if doc is None or not scope.sees(doc.get("connection_id")):
        return error(f"No machine or device {name} here.", 404, error_code="NOT_FOUND")
    if doc.get("online") and not force:
        return error(
            f"{device or node} is online and still sending, so it would come straight back. "
            "Forget it anyway with force, or stop its source first.",
            409,
            error_code="DEVICE_ONLINE",
        )
    done = await lifecycle.forget(r, user.tenant_id, [(group, node, device)])
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.devices.forgotten",
        {"count": len(done), "asset": name, "force": force},
        request,
        resource_type="telemetry_device",
        resource_id=name,
    )
    await db.commit()
    return success({"forgotten": len(done), "devices": done, "history_kept": True})


@router.get("/devices/{group}/{node}")
async def get_node(
    group: str,
    node: str,
    device: str | None = None,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    scope = await access.scope_for(db, user)
    doc = await reads.node_detail(redis(), user.tenant_id, group, node, device)
    if doc is None or not scope.sees(doc.get("connection_id")):
        return error(
            f"No machine called {node} in group {group}. Machines appear when they send their birth message.",
            404,
            error_code="NOT_FOUND",
        )
    if device is not None and device and not doc["devices"]:
        return error(
            f"{node} has no device called {device}", 404, error_code="NOT_FOUND"
        )
    tid = None
    for c in scope.connections:
        if str(c.id) == doc.get("connection_id"):
            tid = str(c.team_id) if c.team_id else None
            doc["connection_name"] = c.name
    doc["team_id"] = tid
    doc["team_name"] = scope.teams.get(tid) if tid else None
    doc["can_command"] = scope.may_command(
        doc.get("connection_id")
    ) and await access.has(db, user, "telemetry.command")
    return success(doc)


@router.get("/history")
async def get_history(
    group: str,
    node: str,
    device: str = "",
    metric: str = "",
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    step: str | None = None,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    scope = await access.scope_for(db, user)
    conn_id = await _node_conn(user.tenant_id, group, node)
    if conn_id is None or not scope.sees(conn_id):
        return error(
            f"No machine called {node} in group {group}", 404, error_code="NOT_FOUND"
        )
    now = datetime.now(timezone.utc)
    try:
        t_to = history.parse_time(to, now)
        t_from = history.parse_time(from_, t_to - timedelta(hours=1))
        if t_from >= t_to:
            return error("from must be before to", 422, error_code="VALIDATION_ERROR")
        span = (t_to - t_from).total_seconds()
        step_s = history.parse_step(step, span)
    except ValueError as exc:
        return error(str(exc), 422, error_code="VALIDATION_ERROR")
    if span / step_s > 5000:
        return error(
            "That range and step give more than 5000 points. Use a longer step.",
            422,
            error_code="VALIDATION_ERROR",
        )
    try:
        pool = await tsdb()
        metrics = [m.strip() for m in metric.split(",") if m.strip()] if metric else []
        if not metrics:
            metrics = await history.metrics_for(
                pool, str(user.tenant_id), group, node, device
            )
        doc = await history.query(
            pool,
            str(user.tenant_id),
            group,
            node,
            device,
            metrics[:20],
            t_from,
            t_to,
            step_s,
        )
    except Exception as exc:  # noqa: BLE001
        return error(
            f"History is not available right now: {exc}",
            503,
            error_code="HISTORY_UNAVAILABLE",
        )
    doc.update({"group": group, "node": node, "device": device})
    return success(doc)


@router.get("/frames/{group}/{node}")
async def get_frames(
    group: str,
    node: str,
    limit: int = Query(200, ge=1, le=2000),
    since: int | None = None,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    scope = await access.scope_for(db, user)
    if not scope.everything:
        conn_id = await _node_conn(user.tenant_id, group, node)
        if not scope.sees(conn_id):
            return error(
                f"No machine called {node} in group {group}",
                404,
                error_code="NOT_FOUND",
            )
    rows = await reads.frames(redis(), user.tenant_id, group, node, limit, since)
    return success(
        rows, meta={"count": len(rows), "newest": rows[0]["t"] if rows else None}
    )


async def _health(
    tenant: Any, scope: access.Scope, quota: dict[str, int]
) -> dict[str, Any]:
    key = (str(tenant), scope.everything, frozenset(scope.visible))
    hit = _health_cache.get(key)
    if hit and time.monotonic() - hit[0] < 1.0:
        return hit[1]
    doc = await reads.health(redis(), tenant, scope, quota)
    _health_cache[key] = (time.monotonic(), doc)
    if len(_health_cache) > 2000:
        _health_cache.clear()
    return doc


@router.get("/health")
async def get_health(
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    scope = await access.scope_for(db, user)
    quota = await Q.for_tenant(db, user.tenant_id)
    return success(await _health(user.tenant_id, scope, quota))


@router.get("/stream")
async def stream(
    request: Request,
    group: str | None = None,
    node: str | None = None,
    device: str | None = None,
    nodes: str | None = None,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
):
    """Server-sent events: device, metrics (at most 10 a second per device), health each second, ping."""
    try:
        node_set = S.parse_nodes(nodes, group, node)
    except ValueError as exc:
        await db.close()
        return error(str(exc), 422, error_code="VALIDATION_ERROR")
    scope = await access.scope_for(db, user)
    quota = await Q.for_tenant(db, user.tenant_id)
    from app.core.platform_settings import get_int_setting

    cap = await get_int_setting("telemetry.sse.max_per_user", 8)
    tenant = str(user.tenant_id)
    uid = str(user.id)
    await db.close()

    r = redis()
    vkey = K.sse_viewers(uid)
    sid = uuid.uuid4().hex
    now = time.time()
    await r.zremrangebyscore(vkey, 0, now - 30)
    if await r.zcard(vkey) >= cap:
        return error(
            f"You already have {cap} live telemetry views open. Close one and try again.",
            429,
            error_code="RATE_LIMITED",
        )
    await r.zadd(vkey, {sid: now})
    await r.expire(vkey, 60)
    viewer = S.Viewer(
        tenant=tenant,
        scope=scope,
        nodes=node_set,
        device=device if device is not None and node_set else None,
        group=group if group and not node else None,
    )

    async def events():
        await S.hub.add(viewer)
        co = S.Coalescer()
        last_health = last_ping = last_mark = 0.0
        try:
            yield "retry: 3000\n\n"
            rows = await reads.all_devices(r, tenant)
            for row in rows:
                if node_set is not None and (row["group"], row["node"]) not in node_set:
                    continue
                if viewer.device is not None and row["device"] != viewer.device:
                    continue
                if viewer.group is not None and row["group"] != viewer.group:
                    continue
                if not scope.sees(row.get("connection_id")):
                    continue
                yield S.sse("device", {k: row.get(k) for k in reads.DEVICE_FIELDS})
            if node_set is not None and len(node_set) <= 20:
                for g, n in sorted(node_set):
                    doc = await reads.node_detail(r, tenant, g, n, viewer.device)
                    if doc is None or not scope.sees(doc.get("connection_id")):
                        continue
                    if doc["metrics"] and viewer.device in (None, ""):
                        yield S.sse(
                            "metrics",
                            {
                                "group": g,
                                "node": n,
                                "device": "",
                                "metrics": doc["metrics"],
                            },
                        )
                    for d in doc["devices"]:
                        yield S.sse(
                            "metrics",
                            {
                                "group": g,
                                "node": n,
                                "device": d["device"],
                                "metrics": d["metrics"],
                            },
                        )
            while True:
                try:
                    kind, doc = await asyncio.wait_for(viewer.queue.get(), timeout=0.1)
                    batch = [(kind, doc)]
                    while len(batch) < 500:
                        try:
                            batch.append(viewer.queue.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                    for kind, doc in batch:
                        if kind == "metrics":
                            co.add(doc)
                        else:
                            yield S.sse(kind, doc)
                except asyncio.TimeoutError:
                    pass
                for doc in co.due():
                    yield S.sse("metrics", doc)
                t = time.time()
                if t - last_health >= 1.0:
                    last_health = t
                    try:
                        yield S.sse("health", await _health(tenant, scope, quota))
                    except Exception:  # noqa: BLE001
                        pass
                if t - last_ping >= 15.0:
                    last_ping = t
                    yield ": ping\n\n"
                if t - last_mark >= 10.0:
                    last_mark = t
                    await r.zadd(vkey, {sid: t})
                    await r.expire(vkey, 60)
                    if await request.is_disconnected():
                        break
        finally:
            await S.hub.remove(viewer)
            try:
                await r.zrem(vkey, sid)
            except Exception:  # noqa: BLE001
                pass

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# commands


class CommandIn(BaseModel):
    group: str = Field(min_length=1, max_length=255)
    node: str = Field(min_length=1, max_length=255)
    device: str = Field(default="", max_length=255)
    signal: str | None = Field(default=None, max_length=512)
    # the 2.5.8 T4 name, still taken
    metric: str | None = Field(default=None, max_length=512)
    value: Any = None
    reason: str = Field(default="", max_length=2000)
    dry_run: bool = False
    # wait this long for the device to report the value back, 0 answers at publish
    confirm_timeout_ms: int = Field(default=0, ge=0, le=10000)
    # the reading that shows it took, such as Safety/Mode, and the value it should show
    confirm_signal: str | None = Field(default=None, max_length=512)
    confirm_value: Any = None


def _when(ms: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    except (TypeError, ValueError):
        return "an unknown time"


@router.post("/command")
async def send_command(
    body: CommandIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Write one signal back through the source: a Sparkplug DCMD or NCMD, or the target
    the mapping declares for any other transport. Never waits for an approval."""
    if not await access.has(db, user, "telemetry.command"):
        return forbidden(_command_refusal())
    received_ms = int(time.time() * 1000)
    name = (body.signal or body.metric or "").strip()
    if not name:
        return error("Name the signal to set.", 422, error_code="VALIDATION_ERROR")
    reason = (body.reason or "").strip()
    if len(reason) < 3 and not body.dry_run:
        return error(
            "Say why you are sending this command, it is kept in the audit log.",
            422,
            error_code="VALIDATION_ERROR",
        )
    r = redis()
    t = user.tenant_id
    g, n, d = body.group, body.node, body.device or ""
    pipe = r.pipeline(transaction=False)
    pipe.hmget(K.device(t, g, n, ""), "_online", "_conn", "_offline_at")
    pipe.hmget(K.device(t, g, n, d), "_online", "_offline_at", K.metric_field(name))
    node_h, dev_h = await pipe.execute()
    online, conn_id, offline_at = node_h
    if conn_id is None:
        return error(
            f"No machine called {n} in group {g}. Machines appear when they send their birth message.",
            404,
            error_code="NOT_FOUND",
        )
    scope = await access.scope_for(db, user)
    if not scope.sees(conn_id):
        return error(
            f"No machine called {n} in group {g}.", 404, error_code="NOT_FOUND"
        )
    if not scope.may_command(conn_id):
        return forbidden(
            f"You can see {n} but not command it. Its broker belongs to a team you are not in, "
            "ask its owner to share it with you with use rights."
        )
    if online != "1":
        return error(
            f"{n} is offline since {_when(offline_at)}, so the command was not sent.",
            409,
            error_code="NODE_OFFLINE",
            details={"group": g, "node": n, "offline_at": K.as_int(offline_at) or None},
        )
    if d and dev_h[0] != "1":
        return error(
            f"Device {d} on {n} is offline"
            + (f" since {_when(dev_h[1])}" if dev_h[1] else "")
            + ", so the command was not sent.",
            409,
            error_code="NODE_OFFLINE",
            details={"group": g, "node": n, "device": d},
        )
    conn = None
    for c in scope.connections:
        if str(c.id) == conn_id:
            conn = c
    if conn is None:
        return error(
            "The connection for this asset was removed.", 404, error_code="NOT_FOUND"
        )
    from app.telemetry import pipeline, registry

    row = pipeline.connection_row(conn)
    now_ms = int(time.time() * 1000)
    spec = None
    if row["decoder"] == "sparkplug_b":
        hint = None
        if dev_h[2]:
            try:
                hint = json.loads(dev_h[2]).get("t")
            except (TypeError, ValueError):
                hint = None
        dtype = sp.datatype_for(
            body.value,
            hint if hint and hint in sp.TYPE_IDS and hint != "Unknown" else None,
        )
        try:
            value = sp.coerce(body.value, dtype)
        except (TypeError, ValueError):
            return error(
                f"{name} takes a {sp.TYPE_NAMES.get(dtype, 'value')}, {body.value!r} does not fit.",
                422,
                error_code="VALIDATION_ERROR",
            )
        topic = sp.command_topic(g, n, d)
        payload = sp.encode(
            [{"name": name, "value": value, "datatype": dtype, "timestamp": now_ms}],
            timestamp=now_ms,
        )
        target = {"topic": topic, "payload": payload}
        preview = {"topic": topic, "payload": sp.to_json(sp.decode(payload))}
        datatype = sp.TYPE_NAMES.get(dtype)
    else:
        spec = _writable(row["mapping"], name, g, n, d)
        if spec is None:
            return error(
                f"{name} is not a writable signal of this source. Declare it in the mapping under writable, with its target.",
                422,
                error_code="NOT_WRITABLE",
            )
        value = body.value
        target = _render_target(spec.get("target") or {}, value, name, g, n, d)
        preview = {
            "target": target,
            "topic": target.get("topic"),
            "payload": target.get("payload"),
        }
        datatype = None
    if body.dry_run:
        return success({"published": False, "dry_run": True, **preview})
    sec = int(time.time())
    rk = K.command_rate(t, g, n, sec)
    pipe = r.pipeline(transaction=False)
    pipe.incr(rk)
    pipe.expire(rk, 3)
    used, _ = await pipe.execute()
    if int(used) > COMMAND_LIMIT_PER_SEC:
        return error(
            f"More than {COMMAND_LIMIT_PER_SEC} commands a second to {n}. Wait a moment and send it again.",
            429,
            error_code="RATE_LIMITED",
        )
    try:
        connector = registry.connector(row["transport"])
        if not connector.capabilities.get("write"):
            return error(
                f"{connector.label} sources cannot take commands.",
                422,
                error_code="NOT_WRITABLE",
            )
        cfg = {**row["config"], "_connection_id": row["id"]}
        target["connection_id"] = row["id"]
        published_ms = int(time.time() * 1000)
        if row["decoder"] == "sparkplug_b":
            # the payload carries the moment it goes out, not when the request came in
            target["payload"] = sp.encode(
                [
                    {
                        "name": name,
                        "value": value,
                        "datatype": dtype,
                        "timestamp": published_ms,
                    }
                ],
                timestamp=published_ms,
            )
            preview["payload"] = sp.to_json(sp.decode(target["payload"]))
        await connector.write(cfg, row["secrets"], target, value)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 502, error_code="BROKER_UNREACHABLE")
    target.pop("connection_id", None)
    at = datetime.fromtimestamp(published_ms / 1000.0, tz=timezone.utc).isoformat()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.command",
        {
            "group": g,
            "node": n,
            "device": d,
            "signal": name,
            "metric": name,
            "value": value if not isinstance(value, bytes) else value.hex(),
            "datatype": datatype,
            "reason": reason,
            "topic": preview.get("topic"),
            "transport": row["transport"],
            "connection_id": conn_id,
            "api_key_id": str(getattr(user, "_api_key_id", "") or "") or None,
        },
        request,
        resource_type=access.KIND,
        resource_id=conn_id,
    )
    await db.commit()
    result: dict[str, Any] = {
        "published": True,
        "at": at,
        **preview,
        "confirmed": None,
        "received_at": received_ms,
        "checks_ms": published_ms - received_ms,
        "published_at": published_ms,
    }
    if body.confirm_timeout_ms:
        csig = body.confirm_signal or (spec or {}).get("confirm_signal") or name
        if body.confirm_value is not None:
            cval = body.confirm_value
        elif body.confirm_signal:
            # a named signal with no value to wait for waits for the value sent
            cval = value
        else:
            cval = (spec or {}).get("confirm_value", value)
        result.update(
            await _confirm(t, g, n, d, csig, cval, now_ms, body.confirm_timeout_ms)
        )
    return success(result)


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        truthy = ("1", "true", "yes", "on")
        return (str(a).strip().lower() in truthy) == (str(b).strip().lower() in truthy)
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


async def _confirm(
    t: Any,
    g: str,
    n: str,
    d: str,
    signal: str,
    want: Any,
    sent_ms: int,
    timeout_ms: int,
) -> dict[str, Any]:
    """Watch the device's own report until it shows the value, or the time runs out."""
    r = redis()
    deadline = time.monotonic() + timeout_ms / 1000.0
    last = None
    while True:
        raw = await r.hget(K.device(t, g, n, d), K.metric_field(signal))
        if raw:
            try:
                last = json.loads(raw)
            except ValueError:
                last = None
            if (
                last
                and K.as_int(last.get("ts")) >= sent_ms - 50
                and _same(last.get("v"), want)
            ):
                return {
                    "confirmed": True,
                    "confirm_ms": max(0, int(time.time() * 1000) - sent_ms),
                    "confirmed_by": {
                        "signal": signal,
                        "value": last.get("v"),
                        "ts": last.get("ts"),
                    },
                }
        if time.monotonic() >= deadline:
            seen = f" It last reported {signal} = {last.get('v')!r}." if last else ""
            return {
                "confirmed": False,
                "confirm_ms": None,
                "confirm_note": (
                    f"Published, but {n} did not report {signal} = {want!r} within {timeout_ms} ms.{seen} "
                    "The command may still take effect, check the device."
                ),
            }
        await asyncio.sleep(0.02)


def _writable(
    mapping: dict[str, Any], name: str, g: str, n: str, d: str
) -> dict[str, Any] | None:
    for spec in (mapping or {}).get("writable") or []:
        if not isinstance(spec, dict) or spec.get("signal") != name:
            continue
        if any(
            spec.get(k) not in (None, "", v)
            for k, v in (("group", g), ("node", n), ("device", d))
        ):
            continue
        return spec
    return None


def _render_target(
    target: dict[str, Any], value: Any, name: str, g: str, n: str, d: str
) -> dict[str, Any]:
    """{value} is the value as JSON, {raw} as plain text, {group}, {node}, {device} and {signal} as they are."""
    subs = {
        "{value}": json.dumps(value, default=str),
        "{raw}": "" if value is None else str(value),
        "{group}": g,
        "{node}": n,
        "{device}": d,
        "{signal}": name,
    }

    def fill(v: Any) -> Any:
        if isinstance(v, str):
            for k, rep in subs.items():
                v = v.replace(k, rep)
            return v
        if isinstance(v, dict):
            return {k: fill(x) for k, x in v.items()}
        if isinstance(v, list):
            return [fill(x) for x in v]
        return v

    return fill(dict(target))
