"""The telemetry testbed: whether it is installed, and one click to add its sources as connections."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Awaitable, Callable

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_capability
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.routers import telemetry as T
from app.routers import telemetry_streams as TS
from app.telemetry import access
from models.user import User

router = APIRouter(prefix="/api/telemetry/testbed", tags=["telemetry"])

PREFIX = "Testbed · "
# name shown, transport, service, port
SERVICES = (
    ("Kafka (Redpanda)", "kafka", "redpanda", 9092),
    ("RabbitMQ", "amqp", "rabbitmq", 5672),
    ("NATS JetStream", "nats", "nats", 4222),
    ("OPC UA PLC", "opcua", "opc-plc", 50000),
    ("Modbus energy meter", "modbus_tcp", "meter", 502),
    ("WebSocket prices", "websocket", "prices", 8765),
    ("HTTP pusher", "http_push", "testbed-info", 8080),
)
NOT_INSTALLED = (
    "The testbed is not installed, or Abenix cannot reach it. "
    "Run bash scripts/deploy.sh testbed, then try again."
)


def namespace() -> str:
    return os.environ.get("TELEMETRY_TESTBED_NAMESPACE", "abenix-testbed")


def host(service: str) -> str:
    return f"{service}.{namespace()}.svc.cluster.local"


def info_url() -> str:
    return (
        os.environ.get("TELEMETRY_TESTBED_INFO_URL")
        or f"http://{host('testbed-info')}:8080"
    )


async def reachable(h: str, port: int, timeout: float = 1.0) -> bool:
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(h, port), timeout)
    except Exception:  # noqa: BLE001
        return False
    w.close()
    try:
        await w.wait_closed()
    except Exception:  # noqa: BLE001
        pass
    return True


async def probe() -> list[dict[str, Any]]:
    """Every testbed service with whether it answers, no Kubernetes calls."""
    oks = await asyncio.gather(
        *(reachable(host(svc), port) for _, _, svc, port in SERVICES)
    )
    return [
        {
            "name": name,
            "transport": t,
            "address": f"{host(svc)}:{port}",
            "reachable": ok,
        }
        for (name, t, svc, port), ok in zip(SERVICES, oks)
    ]


async def fetch_sources() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=5) as http:
        r = await http.get(f"{info_url()}/sources")
        r.raise_for_status()
        return list(r.json().get("sources") or [])


async def pusher_target() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            r = await http.get(f"{info_url()}/pusher")
            return r.json() if r.status_code == 200 else {}
    except Exception:  # noqa: BLE001
        return {}


async def set_pusher(connection_id: str, token: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            r = await http.post(
                f"{info_url()}/pusher",
                json={"connection_id": connection_id, "token": token},
            )
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def body_of(resp: JSONResponse) -> dict[str, Any]:
    try:
        return json.loads(resp.body)
    except (TypeError, ValueError):
        return {}


def message_of(resp: JSONResponse) -> str:
    b = body_of(resp)
    err = b.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return str(
        err or b.get("detail") or b.get("message") or f"status {resp.status_code}"
    )


Call = Callable[..., Awaitable[JSONResponse]]


async def connect_all(
    sources: list[dict[str, Any]],
    existing: dict[str, str],
    create: Call,
    update: Call,
    rotate: Call,
    target: dict[str, Any],
    point_pusher: Callable[[str, str], Awaitable[bool]],
) -> dict[str, Any]:
    """Adds each source, or brings an existing one up to date. The same calls the Connections page makes."""
    rows: list[dict[str, Any]] = []
    problems: list[dict[str, str]] = []
    pusher = "not needed"
    for src in sources:
        name = str(src.get("name") or "")
        if not name.startswith(PREFIX):
            continue
        body = {**src, "enabled": True}
        cid = existing.get(name)
        if cid is None:
            resp = await create(body)
            verb = "added"
        else:
            body.pop("transport", None)
            resp = await update(cid, body)
            verb = "updated"
        if resp.status_code >= 300:
            problems.append({"name": name, "error": message_of(resp)})
            continue
        row = body_of(resp).get("data") or {}
        token = row.pop("ingest_token", None)
        rows.append({**row, "action": verb})
        if src.get("transport") != "http_push":
            continue
        rid = str(row.get("id") or cid)
        if token is None and str(target.get("connection_id") or "") != rid:
            # the pusher lost its target, a fresh token is the only way to give it one
            rot = await rotate(rid)
            token = (
                (body_of(rot).get("data") or {}).get("ingest_token")
                if rot.status_code < 300
                else None
            )
        if token is None:
            pusher = "kept"
        elif await point_pusher(rid, token):
            pusher = "set"
        else:
            pusher = "failed"
            problems.append(
                {
                    "name": name,
                    "error": "The HTTP pusher in the testbed did not take its new target. Try again in a minute.",
                }
            )
    return {"connections": rows, "errors": problems, "pusher": pusher}


async def _testbed_rows(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    scope = await access.scope_for(db, user, fresh=True)
    conns = [
        c
        for c in scope.connections
        if scope.sees(str(c.id)) and c.name.startswith(PREFIX)
    ]
    if not conns:
        return []
    rows = await T._serialize(db, user, conns, scope)
    keep = (
        "id",
        "name",
        "transport",
        "status",
        "last_error",
        "messages_per_second",
        "last_message_at",
    )
    return [{k: r.get(k) for k in keep} for r in rows]


def with_details(
    services: list[dict[str, Any]], sources: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Each service with the settings and sign-in of its first testbed source, for an admin to copy."""
    first: dict[str, dict[str, Any]] = {}
    for src in sources:
        first.setdefault(str(src.get("transport") or ""), src)
    out = []
    for svc in services:
        src = first.get(svc["transport"]) or {}
        row = {
            **svc,
            "config": dict(src.get("config") or {}),
            "secrets": dict(src.get("secrets") or {}),
        }
        for k in ("subjects", "decoder"):
            if src.get(k) is not None:
                row[k] = src[k]
        out.append(row)
    return out


def _is_admin(user: User) -> bool:
    role = getattr(getattr(user, "role", None), "value", getattr(user, "role", None))
    return bool(getattr(user, "is_admin", False) or role == "admin")


@router.get("")
async def testbed_status(
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    services = await probe()
    if _is_admin(user) and any(s["reachable"] for s in services):
        # testbed sign-ins only, never a real source's
        try:
            services = with_details(services, await fetch_sources())
        except Exception:  # noqa: BLE001
            pass
    return success(
        {
            "installed": any(s["reachable"] for s in services),
            "namespace": namespace(),
            "services": services,
            "connections": await _testbed_rows(db, user),
            "can_connect": await access.has(db, user, "telemetry.manage"),
        }
    )


@router.post("/connect")
async def testbed_connect(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return T.forbidden(T._manage_refusal())
    try:
        sources = await fetch_sources()
    except Exception:  # noqa: BLE001
        return error(NOT_INSTALLED, 502, error_code="TESTBED_NOT_INSTALLED")
    scope = await access.scope_for(db, user, fresh=True)
    existing = {
        c.name: str(c.id) for c in scope.connections if c.name.startswith(PREFIX)
    }
    out = await connect_all(
        sources,
        existing,
        create=lambda body: T.create_connection(request, body, user, db),
        update=lambda cid, body: T.update_connection(
            uuid.UUID(cid), request, body, user, db
        ),
        rotate=lambda cid: TS.rotate_token(uuid.UUID(cid), request, user, db),
        target=await pusher_target(),
        point_pusher=set_pusher,
    )
    return success(out)
