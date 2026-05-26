"""Tool presets — per-tenant labelled (tool, default_args) bundles.

One generic tool (e.g. yahoo_finance) can be configured into many
purpose-built presets ("LBMA gold fix" / "TTF settlement" / "VIX")
without writing per-instrument tool classes. Presets are visible
across agents, pipelines, and direct SDK calls.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

from models.tool_preset import ToolPreset
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tool-presets", tags=["tool-presets"])


def _serialize(p: ToolPreset) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "slug": p.slug,
        "label": p.label,
        "description": p.description,
        "tool_slug": p.tool_slug,
        "default_args": p.default_args or {},
        "config": p.config or {},
        "category": p.category,
        "ui_group": p.ui_group,
        "asset_class": p.asset_class,
        "enabled": p.enabled,
        "is_system": p.is_system,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("")
async def list_presets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    tool_slug: str | None = None,
    ui_group: str | None = None,
    asset_class: str | None = None,
) -> JSONResponse:
    q = select(ToolPreset).where(ToolPreset.tenant_id == user.tenant_id)
    if tool_slug:
        q = q.where(ToolPreset.tool_slug == tool_slug)
    if ui_group:
        q = q.where(ToolPreset.ui_group == ui_group)
    if asset_class:
        q = q.where(ToolPreset.asset_class == asset_class)
    q = q.order_by(ToolPreset.ui_group.asc().nulls_last(), ToolPreset.label.asc())
    rows = (await db.execute(q)).scalars().all()
    return success([_serialize(r) for r in rows], meta={"count": len(rows)})


@router.get("/{preset_slug}")
async def get_preset(
    preset_slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    q = select(ToolPreset).where(
        ToolPreset.tenant_id == user.tenant_id,
        ToolPreset.slug == preset_slug,
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        return error(f"unknown preset: {preset_slug}", 404)
    return success(_serialize(row))


@router.post("")
async def upsert_preset(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    slug = (body or {}).get("slug")
    tool_slug = (body or {}).get("tool_slug")
    label = (body or {}).get("label")
    if not slug or not tool_slug or not label:
        return error("slug, tool_slug, label required", 400)
    q = select(ToolPreset).where(
        ToolPreset.tenant_id == user.tenant_id,
        ToolPreset.slug == slug,
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        row = ToolPreset(
            tenant_id=user.tenant_id,
            slug=slug,
            tool_slug=tool_slug,
            label=label,
            description=body.get("description"),
            default_args=body.get("default_args") or {},
            config=body.get("config") or {},
            category=body.get("category"),
            ui_group=body.get("ui_group"),
            asset_class=body.get("asset_class"),
            enabled=body.get("enabled", True),
            is_system=False,
            created_by=user.id,
        )
        db.add(row)
    else:
        row.tool_slug = tool_slug
        row.label = label
        row.description = body.get("description", row.description)
        row.default_args = body.get("default_args") or row.default_args or {}
        row.config = body.get("config") or row.config or {}
        row.category = body.get("category", row.category)
        row.ui_group = body.get("ui_group", row.ui_group)
        row.asset_class = body.get("asset_class", row.asset_class)
        row.enabled = body.get("enabled", row.enabled)
    await db.commit()
    await db.refresh(row)
    return success(_serialize(row))


@router.delete("/{preset_slug}")
async def delete_preset(
    preset_slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    q = select(ToolPreset).where(
        ToolPreset.tenant_id == user.tenant_id,
        ToolPreset.slug == preset_slug,
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        return error(f"unknown preset: {preset_slug}", 404)
    if row.is_system:
        return error("system presets cannot be deleted", 400)
    await db.delete(row)
    await db.commit()
    return success({"deleted": preset_slug})


@router.post("/{preset_slug}/run")
async def run_preset(
    preset_slug: str,
    body: dict | None = None,
    request: Request = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Execute a preset. Merges preset.default_args with caller overrides
    and dispatches to the underlying tool, logging in tool_invocations."""

    q = select(ToolPreset).where(
        ToolPreset.tenant_id == user.tenant_id,
        ToolPreset.slug == preset_slug,
    )
    preset = (await db.execute(q)).scalar_one_or_none()
    if preset is None:
        return error(f"unknown preset: {preset_slug}", 404)
    if not preset.enabled:
        return error(f"preset disabled: {preset_slug}", 400)

    from app.core import tool_gate

    overrides = (body or {}).get("arguments") or {}
    merged_args = {**(preset.default_args or {}), **overrides}
    config = {**(preset.config or {}), **((body or {}).get("config") or {})}

    started = time.time()
    tenant_id = str(user.tenant_id)

    decision = await tool_gate.acquire(preset.tool_slug, tenant_id, merged_args, db)
    if not decision.allowed:
        return error(f"{preset.tool_slug}: {decision.reason}", 429)
    if decision.cached and decision.cached_value:
        return success(
            {
                "preset_slug": preset_slug,
                "tool_slug": preset.tool_slug,
                "arguments": merged_args,
                "content": decision.cached_value.get("content"),
                "metadata": {
                    **(decision.cached_value.get("metadata") or {}),
                    "cache_hit": True,
                },
                "is_error": False,
            }
        )

    try:
        from engine.agent_executor import get_tool_class

        cls = get_tool_class(preset.tool_slug)
    except Exception as e:
        await tool_gate.release(decision, preset.tool_slug, tenant_id, ok=False)
        return error(f"registry lookup failed: {e}", 500)
    if cls is None:
        await tool_gate.release(decision, preset.tool_slug, tenant_id, ok=False)
        return error(f"underlying tool unknown: {preset.tool_slug}", 404)

    import inspect
    import os as _os

    try:
        sig = inspect.signature(cls.__init__)
        accepted = set(sig.parameters.keys()) - {"self"}
    except (TypeError, ValueError):
        accepted = set()
    base_kwargs = {
        "tenant_id": tenant_id,
        "execution_id": "",
        "agent_id": "",
        "api_key": "",
        "api_base": "",
        "db_url": _os.environ.get("DATABASE_URL", ""),
    }
    init_kwargs = {
        k: v for k, v in base_kwargs.items() if not accepted or k in accepted
    }
    init_kwargs.update(
        {k: v for k, v in (config or {}).items() if not accepted or k in accepted}
    )
    try:
        tool = cls(**init_kwargs)
    except TypeError:
        try:
            tool = cls(tenant_id=tenant_id)
        except TypeError:
            tool = cls()

    try:
        result = await tool.execute(merged_args)
    except Exception as e:
        await tool_gate.release(decision, preset.tool_slug, tenant_id, ok=False)
        logger.exception("preset run failed: %s", preset_slug)
        await _log_preset_invocation(
            db,
            user,
            preset,
            merged_args,
            None,
            started,
            status="error",
            error_message=str(e),
        )
        return error(f"preset {preset_slug} failed: {e}", 500)

    is_error = getattr(result, "is_error", False)
    payload = {
        "content": getattr(result, "content", None),
        "metadata": getattr(result, "metadata", None),
    }
    await tool_gate.release(
        decision, preset.tool_slug, tenant_id, ok=not is_error, result_payload=payload
    )
    await _log_preset_invocation(
        db,
        user,
        preset,
        merged_args,
        result,
        started,
        status="ok" if not is_error else "error",
    )

    return success(
        {
            "preset_slug": preset_slug,
            "tool_slug": preset.tool_slug,
            "arguments": merged_args,
            **payload,
            "is_error": is_error,
        }
    )


async def _log_preset_invocation(
    db, user, preset, merged_args, result, started_at, *, status, error_message=None
):
    try:
        from models.tool_invocation import ToolInvocation, ToolInvocationStatus

        row = ToolInvocation(
            tenant_id=user.tenant_id,
            user_id=user.id,
            via="direct",
            tool_slug=preset.tool_slug,
            arguments=merged_args,
            config={"preset_slug": preset.slug},
            status=ToolInvocationStatus(
                status if status in {"ok", "error", "timeout"} else "error"
            ),
            output=getattr(result, "content", None) if result else None,
            output_metadata=getattr(result, "metadata", None) if result else None,
            is_error=getattr(result, "is_error", False) if result else True,
            error_message=error_message,
            duration_ms=int((time.time() - started_at) * 1000),
            requested_via="preset",
        )
        db.add(row)
        await db.commit()
    except Exception as e:
        logger.warning("could not log preset invocation: %s", e)
