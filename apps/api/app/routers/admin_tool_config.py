"""Admin -> Tool Configuration.

Generated from the tools' own declarations, see app.services.tool_config. An
admin saves a value here and every pod reads it within the resolver's TTL,
with no redeploy.

Two scopes. ``tenant`` (the default) writes tenant_tool_credentials for the
caller's tenant and wins for that tenant only. ``platform`` writes
platform_settings under tool.credential.<KEY>, beside the subscription token,
and is the fallback for every tenant. There is no separate platform-admin
role, so any admin may write either scope and platform writes are audited.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_role
from app.core.platform_settings import invalidate
from app.core.responses import error, success
from app.core.tool_secrets import TENANT_TABLE, encode_for_storage
from app.services import tool_config
from engine import credentials
from models.user import User

logger = logging.getLogger(__name__)
audit = logging.getLogger("abenix.audit.tool_config")

router = APIRouter(prefix="/api/admin/tool-config", tags=["admin-tool-config"])

_admin = require_role(["admin"])


class ValueBody(BaseModel):
    value: str = Field(default="", max_length=8000)
    scope: str | None = Field(default=None, max_length=16)


class ScopeBody(BaseModel):
    scope: str | None = Field(default=None, max_length=16)


def _scope(*candidates: str | None) -> str | None:
    """First scope given, tenant by default, None when it is not one we know."""
    for c in candidates:
        if c:
            s = c.strip().lower()
            return s if s in tool_config.SCOPES else None
    return "tenant"


def _validate(decl: tool_config.KeyDecl, value: str) -> str | None:
    v = value.strip()
    if not v:
        return None
    if decl.kind == "int":
        try:
            int(v)
        except ValueError:
            return f"{decl.key} must be a whole number"
    if decl.kind == "bool" and v.lower() not in (
        "true",
        "false",
        "1",
        "0",
        "yes",
        "no",
    ):
        return f"{decl.key} must be true or false"
    if decl.kind == "url" and not (v.startswith("http://") or v.startswith("https://")):
        return f"{decl.key} must start with http:// or https://"
    if decl.kind == "select" and decl.options and v not in decl.options:
        return f"{decl.key} must be one of {', '.join(decl.options)}"
    return None


async def _row_state(key: str, tenant_id: Any, scope: str) -> dict[str, Any]:
    await tool_config.refresh(force=True)
    return tool_config.key_state(
        tool_config.declarations()[key],
        include_value=True,
        tenant_id=tenant_id,
        scope=scope,
    )


def _audit(user: User, verb: str, key: str, scope: str) -> None:
    audit.info(
        "[admin.tool-config] %s %s %s scope=%s tenant=%s",
        user.email,
        verb,
        key,
        scope,
        user.tenant_id,
    )


@router.get("")
async def list_tool_config(
    scope: str | None = Query(default=None),
    user: User = Depends(_admin),
) -> JSONResponse:
    """Every declared key, grouped by provider, with where its value comes from.

    ``scope=tenant`` (default) shows what this tenant's agents run with,
    ``scope=platform`` shows the platform fallback with tenant rows ignored.
    Every row carries both ``tenant_source`` and ``platform_source``.
    """
    s = _scope(scope)
    if s is None:
        return error("scope must be tenant or platform", 400)
    return success(
        await tool_config.catalogue(
            include_values=True, force=True, tenant_id=user.tenant_id, scope=s
        )
    )


@router.patch("/{key}")
async def set_value(
    key: str,
    body: ValueBody,
    scope: str | None = Query(default=None),
    user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    decls = tool_config.declarations()
    decl = decls.get(key)
    if decl is None:
        return error(f"No tool declares {key}", 404)
    s = _scope(body.scope, scope)
    if s is None:
        return error("scope must be tenant or platform", 400)
    problem = _validate(decl, body.value)
    if problem:
        return error(problem, 400)
    if not body.value.strip():
        return error("Use DELETE to remove a stored value", 400)
    stored = encode_for_storage(body.value.strip())
    if s == "tenant":
        await db.execute(
            text(
                f"""
            INSERT INTO {TENANT_TABLE} (tenant_id, key, value, updated_by)
            VALUES (CAST(:tid AS uuid), :key, :value, :uid)
            ON CONFLICT (tenant_id, key)
            DO UPDATE SET value = :value, updated_by = :uid, updated_at = now()
            """
            ),
            {"tid": str(user.tenant_id), "key": key, "value": stored, "uid": user.id},
        )
    else:
        await db.execute(
            text(
                """
            INSERT INTO platform_settings (key, value, category, description, updated_by)
            VALUES (:key, :value, :cat, :desc, :uid)
            ON CONFLICT (key)
            DO UPDATE SET value = :value, category = :cat, description = :desc,
                          updated_by = :uid, updated_at = now()
            """
            ),
            {
                "key": credentials.PREFIX + key,
                "value": stored,
                "cat": "tool_credential",
                "desc": decl.label or key,
                "uid": user.id,
            },
        )
        invalidate(credentials.PREFIX + key)
    await db.commit()
    credentials.invalidate()
    _audit(user, "set", key, s)
    return success(await _row_state(key, user.tenant_id, s))


@router.delete("/{key}")
async def clear_value(
    key: str,
    scope: str | None = Query(default=None),
    body: ScopeBody | None = None,
    user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Remove the saved value in one scope so the next source applies again."""
    if key not in tool_config.declarations():
        return error(f"No tool declares {key}", 404)
    s = _scope(body.scope if body else None, scope)
    if s is None:
        return error("scope must be tenant or platform", 400)
    if s == "tenant":
        await db.execute(
            text(
                f"DELETE FROM {TENANT_TABLE} "
                "WHERE tenant_id = CAST(:tid AS uuid) AND key = :k"
            ),
            {"tid": str(user.tenant_id), "k": key},
        )
    else:
        await db.execute(
            text("DELETE FROM platform_settings WHERE key = :k"),
            {"k": credentials.PREFIX + key},
        )
        invalidate(credentials.PREFIX + key)
    await db.commit()
    credentials.invalidate()
    _audit(user, "cleared", key, s)
    return success(await _row_state(key, user.tenant_id, s))


@router.post("/{key}/test")
async def test_value(
    key: str, body: ValueBody, user: User = Depends(_admin)
) -> JSONResponse:
    """Run the declaring tool's own check, if it has one."""
    decls = tool_config.declarations()
    decl = decls.get(key)
    if decl is None:
        return error(f"No tool declares {key}", 404)
    if decl.test_tool is None:
        return error(f"No tool that uses {key} offers a test", 404)
    cls = None
    for slug, c in tool_config._iter_tool_classes():
        if slug == decl.test_tool:
            cls = c
            break
    if cls is None:
        return error("Test tool not found", 404)
    await tool_config.refresh(force=True)
    # a platform test ignores tenant rows, a tenant test runs with what the tenant's agents see
    tid = "" if _scope(body.scope) == "platform" else str(user.tenant_id or "")
    values = {
        k: credentials.get(k, default=decls[k].default, tenant_id=tid)
        for k in tool_config.keys_for_tool(decl.test_tool)
    }
    if body.value.strip():
        values[key] = body.value.strip()
    try:
        outcome = cls.config_test(values, key=key)
        if inspect.isawaitable(outcome):
            outcome = await outcome
        if outcome is None:
            return error("The tool declined to test", 404)
        ok, message = outcome
    except Exception as e:  # noqa: BLE001
        ok, message = False, f"{e.__class__.__name__}: {str(e)[:200]}"
    return success(
        {"key": key, "tool": decl.test_tool, "ok": bool(ok), "message": message}
    )
