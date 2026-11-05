"""Per-document ACL pre-filter for knowledge search.

A document with no document_grants rows is visible to anyone who can read its
collection. Once a document has any grant it is restricted to holders of a live
grant, tenant admins, the collection's creator and users holding WRITE or ADMIN
on the collection. An expired grant keeps the document restricted. The
search path drops restricted documents before similarity ranking, so the top-k
a caller gets is drawn only from what it may read.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from typing import Any, Iterable

# the one statement of the rule, for a documents row called `doc` that holds id and kb_id
RESTRICTED_PREDICATE = """(
  EXISTS (
      SELECT 1 FROM document_grants g
      WHERE g.document_id = {doc}.id)
  AND (CAST(:uid AS uuid) IS NULL
       OR (SELECT kc.created_by FROM knowledge_collections kc WHERE kc.id = {doc}.kb_id)
          IS DISTINCT FROM CAST(:uid AS uuid))
  AND NOT EXISTS (
      SELECT 1 FROM user_collection_grants ucg
      WHERE ucg.collection_id = {doc}.kb_id
        AND ucg.user_id = CAST(:uid AS uuid)
        AND ucg.permission::text IN ('WRITE', 'ADMIN')
        AND (ucg.expires_at IS NULL OR ucg.expires_at > now()))
  AND NOT EXISTS (
      SELECT 1 FROM document_grants g
      WHERE g.document_id = {doc}.id
        AND (g.expires_at IS NULL OR g.expires_at > now())
        AND ((g.subject_type = 'user' AND g.subject_id = CAST(:uid AS uuid))
          OR (g.subject_type = 'agent' AND g.subject_id = CAST(:aid AS uuid))))
)"""

_HIDDEN_SQL = f"""
SELECT d.id::text
FROM documents d
WHERE d.kb_id = ANY(:kb_ids)
  AND {RESTRICTED_PREDICATE.format(doc="d")}
"""

# a fixed size answer however many documents match, the database does the counting
_BOUNDED_SQL = """
WITH h AS ({inner})
SELECT count(*),
       COALESCE(sum(hashtextextended(id, 0)), 0)::text,
       ARRAY(SELECT id FROM h LIMIT :cap)
FROM h
"""


def inline_limit() -> int:
    return int(os.environ.get("KB_HIDDEN_INLINE_MAX", "1000"))


class HiddenIds(set):
    """At most a bounded number of hidden ids, plus how many there really are."""

    total: int = 0
    digest: str = ""
    # true when ids were left out, the caller must filter in SQL instead
    overflow: bool = False
    uid: Any = None
    aid: Any = None
    restricted_overflow: bool = False


def merge_hidden(restricted: set[str], superseded: set[str]) -> set[str]:
    out = HiddenIds(set(restricted) | set(superseded))
    out.total = getattr(restricted, "total", len(restricted)) + getattr(
        superseded, "total", len(superseded)
    )
    parts = [getattr(x, "digest", "") for x in (restricted, superseded)]
    out.digest = (
        hashlib.sha256("|".join(parts).encode()).hexdigest()[:16] if any(parts) else ""
    )
    out.restricted_overflow = bool(getattr(restricted, "overflow", False))
    out.overflow = out.restricted_overflow or bool(
        getattr(superseded, "overflow", False)
    )
    out.uid = getattr(restricted, "uid", None)
    out.aid = getattr(restricted, "aid", None)
    if not out.digest and not out.overflow:
        return set(out)
    return out


async def _bounded(session: Any, inner: str, **params: Any) -> HiddenIds:
    from sqlalchemy import text

    cap = inline_limit()
    row = (
        await session.execute(
            text(_BOUNDED_SQL.format(inner=inner)).bindparams(cap=cap, **params)
        )
    ).first()
    total = int(row[0] if row else 0)
    out = HiddenIds(str(i) for i in (row[2] or [])) if row else HiddenIds()
    out.total = total
    out.digest = f"{total}:{row[1]}" if row and total else ""
    out.overflow = total > cap
    return out


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

    ids = [u for u in (_uuid_or_none(k) for k in kb_ids) if u]
    uid, aid = _uuid_or_none(user_id), _uuid_or_none(agent_id)
    async with AsyncSession(shared_engine(db_url)) as session:
        out = await _bounded(session, _HIDDEN_SQL, kb_ids=ids, uid=uid, aid=aid)
    out.uid, out.aid = uid, aid
    return out


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

    ids = [u for u in (_uuid_or_none(k) for k in kb_ids) if u]
    async with AsyncSession(shared_engine(db_url)) as session:
        return await _bounded(session, _SUPERSEDED_SQL, kb_ids=ids)


async def hidden_among(
    doc_ids: Iterable[str], hidden: Any, kb_ids: Iterable[str]
) -> set[str]:
    """Which of these returned documents the caller may not see, sized by the results."""
    candidates = [u for u in (_uuid_or_none(d) for d in doc_ids) if u]
    if not candidates:
        return set()
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("ASYNC_DATABASE_URL")
    if not db_url:
        # no way to check, so nothing unverified may pass
        return {str(c) for c in candidates}
    if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    from engine.db_pool import shared_engine

    sql = (
        "SELECT d.id::text FROM documents d WHERE d.id = ANY(:docs) AND (d.is_current IS FALSE"
        + (
            f" OR {RESTRICTED_PREDICATE.format(doc='d')}"
            if getattr(hidden, "restricted_overflow", False)
            else ""
        )
        + ")"
    )
    params: dict[str, Any] = {"docs": candidates}
    if getattr(hidden, "restricted_overflow", False):
        params.update(
            uid=getattr(hidden, "uid", None), aid=getattr(hidden, "aid", None)
        )
    async with AsyncSession(shared_engine(db_url)) as session:
        rows = await session.execute(text(sql).bindparams(**params))
        return {str(r[0]) for r in rows.all()}


__all__ = [
    "RESTRICTED_PREDICATE",
    "HiddenIds",
    "hidden_among",
    "hidden_document_ids",
    "hidden_for_search",
    "is_admin",
    "merge_hidden",
    "superseded_document_ids",
    "superseded_for_search",
]
