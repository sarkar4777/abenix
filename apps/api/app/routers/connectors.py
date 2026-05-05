"""Connectors API — CRUD + test endpoint for tenant-scoped external connectors.

Connectors are stored shapes (kind, base_url, auth_type, secret_ref, config) that
the runtime ``connector_call`` tool resolves at execution time. Operations and
URL/body templates come from per-vendor preset YAML in
``packages/db/seeds/connector_presets/``.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.connector_presets import get_preset, list_presets_summary
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.schemas.connectors import ConnectorCreate, ConnectorUpdate

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.api_key import ApiKey  # noqa: E402
from models.connector import (  # noqa: E402
    Connector,
    ConnectorAuthType,
    ConnectorKind,
)
from models.user import User  # noqa: E402

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


def _serialize(c: Connector) -> dict[str, Any]:
    preset = get_preset(c.preset_key) if c.preset_key else None
    operations = list((preset or {}).get("operations", {}).keys()) if preset else []
    return {
        "id": str(c.id),
        "name": c.name,
        "kind": c.kind.value if hasattr(c.kind, "value") else str(c.kind),
        "preset_key": c.preset_key,
        "base_url": c.base_url,
        "auth_type": (
            c.auth_type.value if hasattr(c.auth_type, "value") else str(c.auth_type)
        ),
        "secret_ref": str(c.secret_ref) if c.secret_ref else None,
        "config": c.config or {},
        "is_active": c.is_active,
        "last_test_at": c.last_test_at.isoformat() if c.last_test_at else None,
        "last_test_ok": c.last_test_ok,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "operations": operations,
    }


@router.get("/presets")
async def list_presets(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Return all available presets — used by the create-connector UI dropdown."""
    return success(list_presets_summary())


@router.post("")
async def create_connector(
    body: ConnectorCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        kind_enum = ConnectorKind(body.kind)
        auth_enum = ConnectorAuthType(body.auth_type)
    except ValueError as e:
        return error(f"Invalid kind/auth_type: {e}", 400)

    c = Connector(
        tenant_id=user.tenant_id,
        name=body.name,
        kind=kind_enum,
        preset_key=body.preset_key,
        base_url=body.base_url,
        auth_type=auth_enum,
        secret_ref=body.secret_ref,
        config=body.config,
        is_active=body.is_active,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return success(_serialize(c), status_code=201)


@router.get("")
async def list_connectors(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Connector)
        .where(Connector.tenant_id == user.tenant_id)
        .order_by(Connector.created_at.desc())
    )
    rows = result.scalars().all()
    return success([_serialize(c) for c in rows])


@router.get("/{connector_id}")
async def get_connector(
    connector_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Connector).where(
            Connector.id == connector_id,
            Connector.tenant_id == user.tenant_id,
        )
    )
    c = result.scalar_one_or_none()
    if not c:
        return error("Connector not found", 404)
    return success(_serialize(c))


@router.put("/{connector_id}")
async def update_connector(
    connector_id: uuid.UUID,
    body: ConnectorUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Connector).where(
            Connector.id == connector_id,
            Connector.tenant_id == user.tenant_id,
        )
    )
    c = result.scalar_one_or_none()
    if not c:
        return error("Connector not found", 404)

    if body.name is not None:
        c.name = body.name
    if body.base_url is not None:
        c.base_url = body.base_url
    if body.auth_type is not None:
        try:
            c.auth_type = ConnectorAuthType(body.auth_type)
        except ValueError:
            return error(f"Invalid auth_type: {body.auth_type}", 400)
    if body.secret_ref is not None:
        c.secret_ref = body.secret_ref
    if body.config is not None:
        c.config = body.config
    if body.is_active is not None:
        c.is_active = body.is_active
    if body.preset_key is not None:
        c.preset_key = body.preset_key

    await db.commit()
    await db.refresh(c)
    return success(_serialize(c))


@router.delete("/{connector_id}")
async def delete_connector(
    connector_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Connector).where(
            Connector.id == connector_id,
            Connector.tenant_id == user.tenant_id,
        )
    )
    c = result.scalar_one_or_none()
    if not c:
        return error("Connector not found", 404)
    await db.delete(c)
    await db.commit()
    return success({"id": str(connector_id), "status": "deleted"})


async def _resolve_secret(secret_ref: uuid.UUID | None, db: AsyncSession) -> str | None:
    """Look up an ApiKey row by id — the prefix doubles as a redaction-safe handle.

    The full raw key is never persisted, so for tests + local dev we use the
    prefix as the bearer token. In production the secret store wires real
    secrets; presets ship as placeholders.
    """
    if not secret_ref:
        return None
    result = await db.execute(select(ApiKey).where(ApiKey.id == secret_ref))
    key = result.scalar_one_or_none()
    if not key:
        return None
    # The runtime resolves the actual secret via the platform secret-store;
    # for now we surface the prefix as a stable handle so test endpoints
    # round-trip without leaking the hash.
    return key.key_prefix


def _build_auth_headers(
    auth_type: str, secret: str | None, config: dict[str, Any] | None
) -> dict[str, str]:
    headers: dict[str, str] = {}
    config = config or {}
    if not secret:
        return headers
    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {secret}"
    elif auth_type == "api_key":
        header_name = config.get("auth_header_name", "X-API-Key")
        headers[header_name] = secret
    elif auth_type == "basic":
        import base64

        username = config.get("username", "")
        creds = base64.b64encode(f"{username}:{secret}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"
    elif auth_type == "oauth2":
        headers["Authorization"] = f"Bearer {secret}"
    return headers


@router.post("/{connector_id}/test")
async def test_connector(
    connector_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Ping the configured base_url with the connector's auth and capture timing.

    Strategy: GET base_url, follow up to 1 redirect, hard 5s timeout. Records
    the result on the connector row so the list view can show health.
    """
    result = await db.execute(
        select(Connector).where(
            Connector.id == connector_id,
            Connector.tenant_id == user.tenant_id,
        )
    )
    c = result.scalar_one_or_none()
    if not c:
        return error("Connector not found", 404)

    secret = await _resolve_secret(c.secret_ref, db)
    auth_type_str = (
        c.auth_type.value if hasattr(c.auth_type, "value") else str(c.auth_type)
    )
    headers = _build_auth_headers(auth_type_str, secret, c.config)

    started = time.monotonic()
    ok = False
    status_code: int | None = None
    excerpt: str | None = None
    error_msg: str | None = None
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.get(c.base_url, headers=headers)
            status_code = resp.status_code
            ok = 200 <= resp.status_code < 500
            text = resp.text or ""
            excerpt = text[:500]
    except httpx.HTTPError as e:
        error_msg = str(e)
    except Exception as e:
        error_msg = f"connector test failed: {e}"
    latency_ms = int((time.monotonic() - started) * 1000)

    from datetime import datetime, timezone

    c.last_test_at = datetime.now(timezone.utc)
    c.last_test_ok = ok
    await db.commit()

    return success(
        {
            "ok": ok,
            "latency_ms": latency_ms,
            "status_code": status_code,
            "sample_response_excerpt": excerpt,
            "error": error_msg,
        }
    )
