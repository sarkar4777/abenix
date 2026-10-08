"""Connectors API — CRUD + test endpoint for tenant-scoped external connectors.

Connectors are stored shapes (kind, base_url, auth_type, config) that the
runtime ``connector_call`` tool resolves at execution time. Operations and
URL/body templates come from per-vendor preset YAML in
``packages/db/seeds/connector_presets/``.

A connector's secret is write-only. It is saved in the tool credentials store
(``tenant_tool_credentials``, encrypted with the cluster KEK when one is set)
under ``CONNECTOR_<id hex>_SECRET`` for the connector's tenant, and responses
only ever say ``has_secret``. The ``secret_ref`` column is legacy: it pointed
at an Abenix ApiKey whose prefix used to be sent as the credential. It is no
longer read as a credential, a connector that still has one and no stored
secret reports ``needs_secret``.

Every base URL is checked by ``engine.url_guard`` on save and again, with each
redirect hop, before the test request. ``CONNECTORS_ALLOW_PRIVATE_TARGETS``
lets a dev cluster reach in-cluster services.
"""

from __future__ import annotations

import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from urllib.parse import urlparse
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.connector_presets import get_preset, list_presets_summary
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.core.tool_secrets import TENANT_TABLE, encode_for_storage
from app.schemas.connectors import ConnectorCreate, ConnectorUpdate
from engine import credentials, url_guard
from engine.tools.connector_call import (
    LEGACY_SECRET_NOTICE,
    auth_headers,
    private_targets_allowed,
    resolve_secret,
    secret_key,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.connector import (  # noqa: E402
    Connector,
    ConnectorAuthType,
    ConnectorKind,
)
from models.user import User  # noqa: E402

router = APIRouter(prefix="/api/connectors", tags=["connectors"])

PRIVATE_HINT = (
    "Connectors may only call public addresses. A dev cluster can allow "
    "private ones with CONNECTORS_ALLOW_PRIVATE_TARGETS."
)
TEST_TIMEOUT = 5.0


def _needs_secret(c: Connector, has_secret: bool) -> bool:
    return bool(c.secret_ref) and not has_secret


def _serialize(c: Connector, has_secret: bool = False) -> dict[str, Any]:
    preset = get_preset(c.preset_key) if c.preset_key else None
    operations = list((preset or {}).get("operations", {}).keys()) if preset else []
    needs = _needs_secret(c, has_secret)
    return {
        "id": str(c.id),
        "name": c.name,
        "kind": c.kind.value if hasattr(c.kind, "value") else str(c.kind),
        "preset_key": c.preset_key,
        "base_url": c.base_url,
        "auth_type": (
            c.auth_type.value if hasattr(c.auth_type, "value") else str(c.auth_type)
        ),
        "has_secret": has_secret,
        "needs_secret": needs,
        "secret_notice": LEGACY_SECRET_NOTICE if needs else None,
        "config": c.config or {},
        "is_active": c.is_active,
        "last_test_at": c.last_test_at.isoformat() if c.last_test_at else None,
        "last_test_ok": c.last_test_ok,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "operations": operations,
    }


async def _url_problem(url: str) -> str | None:
    """Why a base URL may not be saved. A host that does not resolve yet is fine."""
    reason = await url_guard.check(
        url, allow_private=private_targets_allowed(), require_dns=False
    )
    return f"This base URL is blocked: {reason}. {PRIVATE_HINT}" if reason else None


async def _load(
    db: AsyncSession, connector_id: uuid.UUID, tenant_id: Any
) -> Connector | None:
    result = await db.execute(
        select(Connector).where(
            Connector.id == connector_id,
            Connector.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def _secret_keys(db: AsyncSession, tenant_id: Any) -> set[str]:
    """Keys of the connector secrets this tenant has stored."""
    try:
        # a savepoint, so a missing table cannot expire the caller's rows
        async with db.begin_nested():
            rows = await db.execute(
                text(
                    f"SELECT key FROM {TENANT_TABLE} "
                    "WHERE tenant_id = CAST(:tid AS uuid) AND key LIKE :pfx"
                ),
                {"tid": str(tenant_id), "pfx": "CONNECTOR%"},
            )
            return {str(r[0]) for r in rows.all()}
    except Exception:  # noqa: BLE001
        return set()


async def _write_secret(
    db: AsyncSession, tenant_id: Any, connector_id: Any, value: str, user_id: Any
) -> None:
    await db.execute(
        text(
            f"""
        INSERT INTO {TENANT_TABLE} (tenant_id, key, value, updated_by)
        VALUES (CAST(:tid AS uuid), :key, :value, :uid)
        ON CONFLICT (tenant_id, key)
        DO UPDATE SET value = :value, updated_by = :uid, updated_at = now()
        """
        ),
        {
            "tid": str(tenant_id),
            "key": secret_key(connector_id),
            "value": encode_for_storage(value),
            "uid": user_id,
        },
    )


async def _delete_secret(db: AsyncSession, tenant_id: Any, connector_id: Any) -> None:
    await db.execute(
        text(
            f"DELETE FROM {TENANT_TABLE} "
            "WHERE tenant_id = CAST(:tid AS uuid) AND key = :key"
        ),
        {"tid": str(tenant_id), "key": secret_key(connector_id)},
    )


async def _apply_secret(
    db: AsyncSession,
    c: Connector,
    secret: str | None,
    clear: bool,
    user: User,
) -> bool:
    """Write or remove the stored secret. True when anything changed."""
    if secret is not None and secret.strip():
        await _write_secret(db, c.tenant_id, c.id, secret.strip(), user.id)
        c.secret_ref = None
        return True
    if clear:
        await _delete_secret(db, c.tenant_id, c.id)
        c.secret_ref = None
        return True
    return False


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
    problem = await _url_problem(body.base_url)
    if problem:
        return error(problem, 400)

    c = Connector(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        name=body.name,
        kind=kind_enum,
        preset_key=body.preset_key,
        base_url=body.base_url,
        auth_type=auth_enum,
        config=body.config,
        is_active=body.is_active,
    )
    db.add(c)
    stored = await _apply_secret(db, c, body.secret, False, user)
    await db.commit()
    await db.refresh(c)
    if stored:
        credentials.invalidate()
    return success(_serialize(c, has_secret=stored), status_code=201)


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
    keys = await _secret_keys(db, user.tenant_id)
    return success([_serialize(c, secret_key(c.id) in keys) for c in rows])


@router.get("/{connector_id}")
async def get_connector(
    connector_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    c = await _load(db, connector_id, user.tenant_id)
    if not c:
        return error("Connector not found", 404)
    keys = await _secret_keys(db, user.tenant_id)
    return success(_serialize(c, secret_key(c.id) in keys))


@router.put("/{connector_id}")
async def update_connector(
    connector_id: uuid.UUID,
    body: ConnectorUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    c = await _load(db, connector_id, user.tenant_id)
    if not c:
        return error("Connector not found", 404)

    if body.name is not None:
        c.name = body.name
    if body.base_url is not None:
        problem = await _url_problem(body.base_url)
        if problem:
            return error(problem, 400)
        c.base_url = body.base_url
    if body.auth_type is not None:
        try:
            c.auth_type = ConnectorAuthType(body.auth_type)
        except ValueError:
            return error(f"Invalid auth_type: {body.auth_type}", 400)
    if body.config is not None:
        c.config = body.config
    if body.is_active is not None:
        c.is_active = body.is_active
    if body.preset_key is not None:
        c.preset_key = body.preset_key
    changed = await _apply_secret(db, c, body.secret, bool(body.clear_secret), user)

    await db.commit()
    await db.refresh(c)
    if changed:
        credentials.invalidate()
    keys = await _secret_keys(db, user.tenant_id)
    return success(_serialize(c, secret_key(c.id) in keys))


@router.delete("/{connector_id}")
async def delete_connector(
    connector_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    c = await _load(db, connector_id, user.tenant_id)
    if not c:
        return error("Connector not found", 404)
    await _delete_secret(db, c.tenant_id, c.id)
    await db.delete(c)
    await db.commit()
    credentials.invalidate()
    return success({"id": str(connector_id), "status": "deleted"})


def describe_status(status: int, latency_ms: int) -> tuple[bool, str]:
    """Whether a test answer counts as reachable, and what it means in words."""
    if 200 <= status < 300:
        return True, f"Reached it, HTTP {status} in {latency_ms} ms."
    if 300 <= status < 400:
        return True, f"Reached it, it answered with a redirect (HTTP {status})."
    if status in (401, 403):
        return False, (
            f"The service refused the credentials (HTTP {status}). "
            "Check the secret and the auth type."
        )
    if status == 404:
        return False, (
            "It answered HTTP 404. The host is up but nothing is at that "
            "address, check the base URL."
        )
    if status < 500:
        return False, f"It answered HTTP {status}, so it did not accept the request."
    return False, f"It answered HTTP {status}, an error on its side."


def _http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TEST_TIMEOUT, follow_redirects=False)


@router.post("/{connector_id}/test")
async def test_connector(
    connector_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """GET the base URL with the connector's auth and record whether it answered.

    The URL and every redirect hop (at most 3) are checked against the
    private-address guard first. Only a 2xx or 3xx answer counts as ok.
    """
    c = await _load(db, connector_id, user.tenant_id)
    if not c:
        return error("Connector not found", 404)

    auth_type_str = (
        c.auth_type.value if hasattr(c.auth_type, "value") else str(c.auth_type)
    )
    await credentials.ensure_fresh(force=True)
    secret = await resolve_secret(c.id, c.tenant_id)

    started = time.monotonic()
    ok = False
    blocked = False
    status_code: int | None = None
    excerpt: str | None = None
    message: str

    if not secret and _needs_secret(c, False) and auth_type_str != "none":
        message = f"{LEGACY_SECRET_NOTICE}. The test did not run."
    else:
        secret_headers = auth_headers(auth_type_str, secret, c.config)
        try:
            async with _http_client() as client:
                req = client.build_request("GET", c.base_url, headers=secret_headers)
                resp = await url_guard.send_guarded(
                    client,
                    req,
                    allow_private=private_targets_allowed(),
                    sensitive_headers=secret_headers.keys(),
                )
                status_code = resp.status_code
                latency = int((time.monotonic() - started) * 1000)
                ok, message = describe_status(resp.status_code, latency)
                excerpt = (resp.text or "")[:500]
        except url_guard.Blocked as e:
            blocked = True
            where = " after a redirect" if e.hop else ""
            message = f"Blocked{where}: {e.reason}. {PRIVATE_HINT}"
        except url_guard.TooManyRedirects as e:
            message = f"{e}, so the test stopped."
        except httpx.TimeoutException:
            message = (
                f"Could not reach it, no answer within {int(TEST_TIMEOUT)} seconds."
            )
        except httpx.ConnectError as e:
            host = urlparse(c.base_url or "").hostname or "the service"
            low = str(e).lower()
            if "name or service" in low or "getaddrinfo" in low or "nodename" in low:
                message = f"Could not reach it. This server cannot find {host}, check the address."
            elif "ssl" in low or "certificate" in low:
                message = (
                    f"Could not reach it. {host} failed the secure connection check."
                )
            else:
                message = f"Could not reach it. {host} is down or refusing connections."
        except httpx.HTTPError as e:
            # never echo the raw library error, it can carry internal detail
            message = f"Could not reach it ({e.__class__.__name__})."
        except Exception as e:  # noqa: BLE001
            message = f"The test could not run: {e.__class__.__name__}"
    latency_ms = int((time.monotonic() - started) * 1000)

    c.last_test_at = datetime.now(timezone.utc)
    c.last_test_ok = ok
    await db.commit()

    return success(
        {
            "ok": ok,
            "blocked": blocked,
            "latency_ms": latency_ms,
            "status_code": status_code,
            "sample_response_excerpt": excerpt,
            "message": message,
            "error": None if ok else message,
        }
    )
