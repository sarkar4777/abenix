"""Per-document ACL pre-filter for knowledge search.

A document with no document_grants rows is visible to anyone who can read its
collection. Once a document has any grant it is restricted to holders of a live
grant, tenant admins, the collection's creator and users holding WRITE or ADMIN
on the collection. An expired grant keeps the document restricted. The
search path drops restricted documents before similarity ranking, so the top-k
a caller gets is drawn only from what it may read.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable

_HIDDEN_SQL = """
SELECT d.id::text
FROM documents d
JOIN knowledge_collections kc ON kc.id = d.kb_id
WHERE d.kb_id = ANY(:kb_ids)
  AND EXISTS (
      SELECT 1 FROM document_grants g
      WHERE g.document_id = d.id)
  AND (CAST(:uid AS uuid) IS NULL
       OR kc.created_by IS DISTINCT FROM CAST(:uid AS uuid))
  AND NOT EXISTS (
      SELECT 1 FROM user_collection_grants ucg
      WHERE ucg.collection_id = d.kb_id
        AND ucg.user_id = CAST(:uid AS uuid)
        AND ucg.permission::text IN ('WRITE', 'ADMIN')
        AND (ucg.expires_at IS NULL OR ucg.expires_at > now()))
  AND NOT EXISTS (
      SELECT 1 FROM document_grants g
      WHERE g.document_id = d.id
        AND (g.expires_at IS NULL OR g.expires_at > now())
        AND ((g.subject_type = 'user' AND g.subject_id = CAST(:uid AS uuid))
          OR (g.subject_type = 'agent' AND g.subject_id = CAST(:aid AS uuid))))
"""


def _uuid_or_none(v: Any) -> uuid.UUID | None:
    if not v:
        return None
    try:
        return uuid.UUID(str(v))
    except (TypeError, ValueError):
        return None


def is_admin(role: Any) -> bool:
    r = role.value if hasattr(role, "value") else str(role or "")
    return r.lower() == "admin"


async def hidden_document_ids(
    session: Any,
    kb_ids: Iterable[str],
    *,
    user_id: Any = None,
    user_role: Any = None,
    agent_id: Any = None,
) -> set[str]:
    """Ids of documents in these collections the caller may not read."""
    if is_admin(user_role):
        return set()
    ids = [u for u in (_uuid_or_none(k) for k in kb_ids) if u]
    if not ids:
        return set()
    from sqlalchemy import text

    rows = await session.execute(
        text(_HIDDEN_SQL).bindparams(
            kb_ids=ids,
            uid=_uuid_or_none(user_id),
            aid=_uuid_or_none(agent_id),
        )
    )
    return {str(r[0]) for r in rows.all()}


async def hidden_for_search(
    kb_ids: list[str],
    *,
    user_id: Any = None,
    user_role: Any = None,
    agent_id: Any = None,
) -> set[str]:
    """Same, on the runtime's shared engine."""
    import os

    if is_admin(user_role) or not any(_uuid_or_none(k) for k in kb_ids):
        return set()
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("ASYNC_DATABASE_URL")
    if not db_url:
        return set()
    if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    from sqlalchemy.ext.asyncio import AsyncSession

    from engine.db_pool import shared_engine

    async with AsyncSession(shared_engine(db_url)) as session:
        return await hidden_document_ids(
            session, kb_ids, user_id=user_id, user_role=user_role, agent_id=agent_id
        )


_SUPERSEDED_SQL = """
SELECT d.id::text
FROM documents d
WHERE d.kb_id = ANY(:kb_ids)
  AND d.is_current IS FALSE
"""


async def superseded_document_ids(session: Any, kb_ids: Iterable[str]) -> set[str]:
    """Old versions replaced by a newer upload. Search must never return them."""
    ids = [u for u in (_uuid_or_none(k) for k in kb_ids) if u]
    if not ids:
        return set()
    from sqlalchemy import text

    rows = await session.execute(text(_SUPERSEDED_SQL).bindparams(kb_ids=ids))
    return {str(r[0]) for r in rows.all()}


async def superseded_for_search(kb_ids: list[str]) -> set[str]:
    """Same, on the runtime's shared engine."""
    import os

    if not any(_uuid_or_none(k) for k in kb_ids):
        return set()
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("ASYNC_DATABASE_URL")
    if not db_url:
        return set()
    if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    from sqlalchemy.ext.asyncio import AsyncSession

    from engine.db_pool import shared_engine

    async with AsyncSession(shared_engine(db_url)) as session:
        return await superseded_document_ids(session, kb_ids)


__all__ = [
    "hidden_document_ids",
    "hidden_for_search",
    "is_admin",
    "superseded_document_ids",
    "superseded_for_search",
]
