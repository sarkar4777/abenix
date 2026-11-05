"""Per tenant limits on knowledge, read by anyone in the tenant, set by its admins."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import success
from app.services.kb_quota import limits_of, usage_of

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

import knowledge_quota as kq
from models.user import User

router = APIRouter(tags=["knowledge-quotas"])


class QuotaBody(BaseModel):
    max_documents: int | None = Field(default=None, ge=0)
    max_chunks: int | None = Field(default=None, ge=0)
    max_storage_bytes: int | None = Field(default=None, ge=0)
    monthly_embedding_usd: float | None = Field(default=None, ge=0)
    monthly_cognify_usd: float | None = Field(default=None, ge=0)


def _ensure_admin(user: User) -> None:
    role = getattr(user, "role", None)
    r = role.value if hasattr(role, "value") else str(role or "")
    if r.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")


async def _state(db: AsyncSession, user: User) -> dict[str, Any]:
    limits = await limits_of(db, user.tenant_id) or {}
    usage = await usage_of(db, user.tenant_id)
    return {
        "limits": {
            k: (float(limits[k]) if limits.get(k) is not None else None)
            for k in kq.LIMIT_KEYS
        },
        "usage": {
            "documents": usage.documents,
            "chunks": usage.chunks,
            "storage_bytes": usage.storage_bytes,
            "embedding_usd": round(usage.embedding_usd, 4),
            "embedding_tokens": usage.embedding_tokens,
            "cognify_usd": round(usage.cognify_usd, 4),
        },
        "period_start": kq.period_start().isoformat(),
    }


@router.get("/api/knowledge-quotas")
async def get_knowledge_quota(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success(await _state(db, user))


@router.put("/api/admin/knowledge-quotas")
async def set_knowledge_quota(
    body: QuotaBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    _ensure_admin(user)
    columns = ", ".join(kq.LIMIT_KEYS)
    values = ", ".join(f":{k}" for k in kq.LIMIT_KEYS)
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in kq.LIMIT_KEYS)
    await db.execute(
        text(
            f"INSERT INTO tenant_knowledge_quotas (tenant_id, {columns}, updated_by) "
            f"VALUES (CAST(:t AS uuid), {values}, CAST(:u AS uuid)) "
            f"ON CONFLICT (tenant_id) DO UPDATE SET {updates}, "
            "updated_by = EXCLUDED.updated_by, updated_at = now()"
        ),
        {
            "t": str(user.tenant_id),
            "u": str(user.id),
            **{k: getattr(body, k) for k in kq.LIMIT_KEYS},
        },
    )
    await db.commit()
    return success(await _state(db, user))
