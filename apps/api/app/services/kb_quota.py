"""Tenant knowledge limits for API routes and the settings page."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

import knowledge_quota as kq

from app.core.responses import error


async def limits_of(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(kq.LIMITS_SQL.format(t="CAST(:t AS uuid)")), {"t": str(tenant_id)}
        )
    ).first()
    return dict(zip(kq.LIMIT_KEYS, row)) if row else None


async def usage_of(db: AsyncSession, tenant_id: uuid.UUID) -> kq.Usage:
    params = {"t": str(tenant_id)}
    docs, chunks, size = (
        await db.execute(text(kq.USAGE_SQL.format(t="CAST(:t AS uuid)")), params)
    ).one()
    emb, cog, tokens = (
        await db.execute(
            text(kq.SPEND_SQL.format(t="CAST(:t AS uuid)", p=":p")),
            {**params, "p": kq.period_start()},
        )
    ).one()
    return kq.Usage(
        documents=int(docs),
        chunks=int(chunks),
        storage_bytes=int(size),
        embedding_usd=float(emb),
        cognify_usd=float(cog),
        embedding_tokens=int(tokens),
    )


async def enforce(db: AsyncSession, tenant_id: uuid.UUID, **adding: Any) -> None:
    """Raises KnowledgeQuotaExceeded, for callers with no response to return."""
    limits = await limits_of(db, tenant_id)
    if limits:
        kq.check(limits, await usage_of(db, tenant_id), **adding)


async def quota_error(
    db: AsyncSession, tenant_id: uuid.UUID, **adding: Any
) -> JSONResponse | None:
    """A 429 the caller returns as it is, None when the addition fits."""
    limits = await limits_of(db, tenant_id)
    if not limits:
        return None
    try:
        kq.check(limits, await usage_of(db, tenant_id), **adding)
    except kq.KnowledgeQuotaExceeded as e:
        return error(
            e.message, 429, error_code=kq.ERROR_CODE, details={"limit": e.limit}
        )
    return None
