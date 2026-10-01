"""Admin CRUD for LLM model pricing."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any


def _json_dumps(v: Any) -> str:
    return json.dumps(v)


from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))
from models.llm_pricing import LLMModelPricing
from pricing_baseline import seed_pricing  # noqa: E402  # type: ignore  # noqa: E402
from models.user import User  # type: ignore  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/llm-pricing", tags=["admin-pricing"])


def _ensure_admin(user: User) -> None:
    role = getattr(user, "role", None)
    r = role.value if hasattr(role, "value") else str(role or "")
    if r.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")


def _serialize(row: LLMModelPricing) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "model": row.model,
        "provider": row.provider,
        "input_per_m": float(row.input_per_m),
        "output_per_m": float(row.output_per_m),
        "cached_input_per_m": (
            float(row.cached_input_per_m)
            if row.cached_input_per_m is not None
            else None
        ),
        "batch_input_per_m": (
            float(row.batch_input_per_m) if row.batch_input_per_m is not None else None
        ),
        "batch_output_per_m": (
            float(row.batch_output_per_m)
            if row.batch_output_per_m is not None
            else None
        ),
        "effective_from": (
            row.effective_from.isoformat() if row.effective_from else None
        ),
        "is_active": bool(row.is_active),
        "notes": row.notes,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "capabilities": row.capabilities or {},
        "fallback_to": list(row.fallback_to or []),
        "provider_endpoint": row.provider_endpoint,
        "display_name": row.display_name,
        "is_deprecated": bool(row.is_deprecated),
        "deprecated_at": row.deprecated_at.isoformat() if row.deprecated_at else None,
        "migration_hint": row.migration_hint,
    }


@router.get("")
async def list_pricing(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _ensure_admin(user)
    rows = (
        (
            await db.execute(
                select(LLMModelPricing).order_by(
                    LLMModelPricing.provider.asc(),
                    LLMModelPricing.model.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return success(
        {
            "rows": [_serialize(r) for r in rows],
            "providers": ["anthropic", "openai", "google", "azure", "other"],
        }
    )


@router.post("")
async def create_pricing(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _ensure_admin(user)
    model = (body.get("model") or "").strip()
    provider = (body.get("provider") or "").strip().lower()
    if not model or provider not in {"anthropic", "openai", "google", "azure", "other"}:
        return error(
            "model and provider (anthropic/openai/google/other) are required", 400
        )

    try:
        input_per_m = float(body["input_per_m"])
        output_per_m = float(body["output_per_m"])
    except (KeyError, TypeError, ValueError):
        return error(
            "input_per_m and output_per_m must be numbers ($ per 1M tokens)", 400
        )

    row = LLMModelPricing(
        model=model,
        provider=provider,
        input_per_m=input_per_m,
        output_per_m=output_per_m,
        cached_input_per_m=body.get("cached_input_per_m"),
        batch_input_per_m=body.get("batch_input_per_m"),
        batch_output_per_m=body.get("batch_output_per_m"),
        is_active=bool(body.get("is_active", True)),
        notes=(body.get("notes") or None),
        capabilities=body.get("capabilities") or {},
        fallback_to=body.get("fallback_to") or [],
        provider_endpoint=body.get("provider_endpoint") or None,
        display_name=body.get("display_name") or None,
        is_deprecated=bool(body.get("is_deprecated", False)),
        migration_hint=body.get("migration_hint") or None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return success(_serialize(row), status_code=201)


@router.patch("/{row_id}")
async def update_pricing(
    row_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _ensure_admin(user)
    row = await db.get(LLMModelPricing, row_id)
    if row is None:
        return error("Pricing row not found", 404)

    # Only mutate fields actually present in the body — PATCH semantics.
    for field in (
        "input_per_m",
        "output_per_m",
        "cached_input_per_m",
        "batch_input_per_m",
        "batch_output_per_m",
    ):
        if field in body:
            try:
                setattr(
                    row, field, float(body[field]) if body[field] is not None else None
                )
            except (TypeError, ValueError):
                return error(f"{field} must be a number or null", 400)
    if "is_active" in body:
        row.is_active = bool(body["is_active"])
    if "notes" in body:
        row.notes = body["notes"] or None
    if "provider" in body:
        prov = (body["provider"] or "").strip().lower()
        if prov not in {"anthropic", "openai", "google", "azure", "other"}:
            return error("provider must be anthropic/openai/google/azure/other", 400)
        row.provider = prov
    if "capabilities" in body:
        row.capabilities = body["capabilities"] or {}
    if "fallback_to" in body:
        row.fallback_to = list(body["fallback_to"] or [])
    if "provider_endpoint" in body:
        row.provider_endpoint = body["provider_endpoint"] or None
    if "display_name" in body:
        row.display_name = body["display_name"] or None
    if "migration_hint" in body:
        row.migration_hint = body["migration_hint"] or None
    if "is_deprecated" in body:
        from datetime import datetime as _dt, timezone as _tz

        row.is_deprecated = bool(body["is_deprecated"])
        if row.is_deprecated and row.deprecated_at is None:
            row.deprecated_at = _dt.now(_tz.utc)
        if not row.is_deprecated:
            row.deprecated_at = None

    await db.commit()
    await db.refresh(row)
    return success(_serialize(row))


@router.delete("/{row_id}")
async def delete_pricing(
    row_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _ensure_admin(user)
    row = await db.get(LLMModelPricing, row_id)
    if row is None:
        return error("Pricing row not found", 404)
    await db.delete(row)
    await db.commit()
    # The router's hardcoded PRICING dict still covers the 14 baked-in
    # models, so deleting an admin-added row is always safe.
    return success({"deleted": True, "id": str(row_id)})


@router.post("/seed")
async def seed_from_defaults(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Re-seed pricing + capabilities + fallback chains from the baseline.

    Inserts missing rows and backfills NULL capabilities/fallback_to/is_active
    on existing rows. Idempotent — safe to re-run after schema upgrades."""
    _ensure_admin(user)

    # The baseline and the insert logic live in packages/db/pricing_baseline.py so
    # the deploy seed and this endpoint cannot drift apart.
    return success(await seed_pricing(db))
