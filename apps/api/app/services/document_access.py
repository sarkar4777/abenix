"""Per-document ACL — pre-filter set the search path uses before similarity.

A user with READ on collection X may still be barred from a subset of
docs inside X. The legacy collection_grants model is too coarse for the
M&A / IP / Tax partitioning a Fortune-500 needs from a single shared KB.

`allowed_document_ids(...)` returns the set of doc_ids inside a KB that
the caller may see, taking the union of:
    1. tenant-admin scope (sees everything in their tenant)
    2. KB-level collection_grants (legacy — full KB visibility)
    3. explicit document_grants (per-doc, per-user/agent/role)

The result is cached in Redis for 60s keyed on (subject, kb_id).
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import redis.asyncio as aioredis
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))

from models.collection_grant import UserCollectionGrant
from models.document_grant import DocumentGrant
from models.knowledge_base import Document
from models.user import User, UserRole


_CACHE_TTL = 60
_CACHE_PREFIX = "doc_acl:"


def _cache_key(subject_id: uuid.UUID, kb_id: uuid.UUID) -> str:
    return f"{_CACHE_PREFIX}{subject_id}:{kb_id}"


async def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def allowed_document_ids(
    db: AsyncSession,
    user: User,
    kb_id: uuid.UUID,
    *,
    use_cache: bool = True,
) -> set[uuid.UUID] | None:
    """Returns set of doc IDs the user can read in this KB.

    None means "all documents" (admin or full-KB grant). Empty set means
    "no documents" (caller should short-circuit search to zero results).
    """
    if user.role == UserRole.ADMIN:
        return None

    if use_cache:
        r = await _redis()
        cached = await r.get(_cache_key(user.id, kb_id))
        if cached is not None:
            if cached == "*":
                return None
            try:
                return {uuid.UUID(s) for s in json.loads(cached)}
            except Exception:
                pass

    # Full-KB grant via UserCollectionGrant — caller sees every doc
    kb_grant = await db.execute(
        select(UserCollectionGrant.permission).where(
            UserCollectionGrant.collection_id == kb_id,
            UserCollectionGrant.user_id == user.id,
        )
    )
    perm = kb_grant.scalar_one_or_none()
    if perm is not None:
        if use_cache:
            r = await _redis()
            await r.set(_cache_key(user.id, kb_id), "*", ex=_CACHE_TTL)
        return None

    rows = await db.execute(
        select(Document.id)
        .join(
            DocumentGrant,
            DocumentGrant.document_id == Document.id,
        )
        .where(
            Document.kb_id == kb_id,
            Document.is_current.is_(True),
            DocumentGrant.subject_type == "user",
            DocumentGrant.subject_id == user.id,
            or_(
                DocumentGrant.permission == "read",
                DocumentGrant.permission == "write",
                DocumentGrant.permission == "admin",
            ),
        )
    )
    ids = {row[0] for row in rows.all()}
    if use_cache:
        r = await _redis()
        await r.set(
            _cache_key(user.id, kb_id),
            json.dumps([str(i) for i in ids]),
            ex=_CACHE_TTL,
        )
    return ids


async def invalidate_cache(
    subject_id: uuid.UUID, kb_id: uuid.UUID | None = None
) -> None:
    r = await _redis()
    if kb_id is not None:
        await r.delete(_cache_key(subject_id, kb_id))
        return
    pattern = f"{_CACHE_PREFIX}{subject_id}:*"
    async for key in r.scan_iter(pattern):
        await r.delete(key)


async def grant_document(
    db: AsyncSession,
    *,
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    subject_type: str,
    subject_id: uuid.UUID,
    permission: str,
    granted_by: uuid.UUID | None = None,
) -> DocumentGrant:
    grant = DocumentGrant(
        document_id=document_id,
        tenant_id=tenant_id,
        subject_type=subject_type,
        subject_id=subject_id,
        permission=permission,
        granted_by=granted_by,
    )
    db.add(grant)
    await db.commit()
    await invalidate_cache(subject_id)
    return grant


async def revoke_document(
    db: AsyncSession,
    document_id: uuid.UUID,
    subject_id: uuid.UUID,
) -> int:
    from sqlalchemy import delete as sa_delete

    result = await db.execute(
        sa_delete(DocumentGrant).where(
            DocumentGrant.document_id == document_id,
            DocumentGrant.subject_id == subject_id,
        )
    )
    await db.commit()
    await invalidate_cache(subject_id)
    return result.rowcount or 0


__all__ = [
    "allowed_document_ids",
    "invalidate_cache",
    "grant_document",
    "revoke_document",
]
