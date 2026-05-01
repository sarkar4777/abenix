"""Admin CRUD for LLM model pricing."""

from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))
from models.llm_pricing import LLMModelPricing  # type: ignore  # noqa: E402
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
            "providers": ["anthropic", "openai", "google", "other"],
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
    if not model or provider not in {"anthropic", "openai", "google", "other"}:
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
        if prov not in {"anthropic", "openai", "google", "other"}:
            return error("provider must be anthropic/openai/google/other", 400)
        row.provider = prov

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
    """Re-seed the table from the hardcoded PRICING baseline."""
    _ensure_admin(user)

    # The canonical baseline — matches the router's code constant.
    baseline = [
        ("claude-opus-4-6-20250106", "anthropic", 15.0, 75.0, 1.5, 7.5, 37.5),
        ("claude-opus-4-6", "anthropic", 15.0, 75.0, 1.5, 7.5, 37.5),
        ("claude-sonnet-4-6-20250106", "anthropic", 3.0, 15.0, 0.3, 1.5, 7.5),
        ("claude-sonnet-4-6", "anthropic", 3.0, 15.0, 0.3, 1.5, 7.5),
        ("claude-sonnet-4-5-20250929", "anthropic", 3.0, 15.0, 0.3, 1.5, 7.5),
        ("claude-sonnet-4-20250514", "anthropic", 3.0, 15.0, 0.3, 1.5, 7.5),
        ("claude-haiku-4-5-20251001", "anthropic", 1.0, 5.0, 0.1, 0.5, 2.5),
        ("claude-haiku-4-5", "anthropic", 1.0, 5.0, 0.1, 0.5, 2.5),
        ("claude-haiku-3-5-20241022", "anthropic", 0.80, 4.0, 0.08, 0.4, 2.0),
        ("gpt-4o", "openai", 2.50, 10.0, 1.25, 1.25, 5.0),
        ("gpt-4o-mini", "openai", 0.15, 0.60, 0.075, 0.075, 0.30),
        ("gemini-2.0-flash", "google", 0.10, 0.40, None, None, None),
        ("gemini-2.5-flash", "google", 0.30, 2.50, None, None, None),
        ("gemini-2.5-pro", "google", 1.25, 10.0, None, None, None),
        ("gemini-1.5-pro", "google", 1.25, 5.00, None, None, None),
    ]

    existing = {
        r[0]
        for r in (await db.execute(text("SELECT model FROM llm_model_pricing"))).all()
    }
    added = 0
    for model, provider, inp, out, cached, b_in, b_out in baseline:
        if model in existing:
            continue
        db.add(
            LLMModelPricing(
                model=model,
                provider=provider,
                input_per_m=inp,
                output_per_m=out,
                cached_input_per_m=cached,
                batch_input_per_m=b_in,
                batch_output_per_m=b_out,
            )
        )
        added += 1
    await db.commit()
    return success({"seeded": added, "skipped_existing": len(existing)})
