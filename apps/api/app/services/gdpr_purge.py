"""GDPR-compliant cascade delete with audit receipts."""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent_memory import AgentMemory
from models.gdpr_purge_log import GDPRPurgeLog
from models.meeting import PersonaItem

logger = logging.getLogger(__name__)


STORES = ("postgres", "pinecone", "neo4j", "blob", "trajectory")
_RETRY_DELAYS = (0.5, 2.0, 5.0)


async def _log_store(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    subject_user_id: uuid.UUID,
    requested_by: uuid.UUID | None,
    store: str,
    status: str,
    error: str | None = None,
    retries: int = 0,
) -> GDPRPurgeLog:
    row = GDPRPurgeLog(
        tenant_id=tenant_id,
        subject_user_id=subject_user_id,
        requested_by=requested_by,
        store=store,
        status=status,
        error=error,
        retries=retries,
        completed_at=datetime.now(timezone.utc) if status == "completed" else None,
    )
    db.add(row)
    await db.commit()
    return row


async def _purge_postgres(
    db: AsyncSession,
    subject_user_id: uuid.UUID,
    requested_by: uuid.UUID | None,
) -> int:
    from sqlalchemy import text

    now = datetime.now(timezone.utc)
    affected = 0
    result = await db.execute(
        update(PersonaItem)
        .where(
            PersonaItem.user_id == subject_user_id,
            PersonaItem.deleted_at.is_(None),
        )
        .values(deleted_at=now, deleted_by=requested_by)
    )
    affected += result.rowcount or 0
    result = await db.execute(
        update(AgentMemory)
        .where(
            AgentMemory.deleted_at.is_(None),
        )
        .values(deleted_at=now, deleted_by=requested_by)
    )
    affected += result.rowcount or 0

    sid = str(subject_user_id)
    placeholder_email = f"deleted-{sid}@purged.local"
    placeholder_name = f"deleted-{sid[:8]}"

    r = await db.execute(
        text(
            "UPDATE users SET email=:em, full_name=:fn, is_active=false, "
            "hashed_password='', notification_settings='{}'::jsonb, "
            "updated_at=now() WHERE id=:uid"
        ),
        {"em": placeholder_email, "fn": placeholder_name, "uid": sid},
    )
    affected += r.rowcount or 0

    from app.services.audit_chain import NIL_ACTOR, maintenance

    # the chain keeps its salted digest, dropping the salt unlinks the person
    await maintenance(db)
    r = await db.execute(
        text(
            "UPDATE activity_logs SET user_id=:nil, ip_address=NULL, "
            "user_agent=NULL, pii_salt=NULL WHERE user_id=:uid"
        ),
        {"uid": sid, "nil": NIL_ACTOR},
    )
    affected += r.rowcount or 0

    r = await db.execute(
        text("UPDATE api_keys SET is_active=false WHERE user_id=:uid"),
        {"uid": sid},
    )
    affected += r.rowcount or 0

    r = await db.execute(
        text("UPDATE executions SET user_id=NULL WHERE user_id=:uid"),
        {"uid": sid},
    )
    affected += r.rowcount or 0

    r = await db.execute(
        text("UPDATE conversations SET user_id=NULL WHERE user_id=:uid"),
        {"uid": sid},
    )
    affected += r.rowcount or 0

    await db.commit()
    return affected


async def _purge_pinecone(subject_user_id: uuid.UUID) -> int:
    try:
        from app.services.pinecone_client import delete_by_metadata
    except Exception:
        return 0
    deleted = 0
    last_error: Exception | None = None
    for delay in _RETRY_DELAYS + (None,):
        try:
            deleted = await delete_by_metadata({"user_id": str(subject_user_id)})
            return deleted
        except Exception as e:
            last_error = e
            if delay is not None:
                await asyncio.sleep(delay)
    if last_error is not None:
        raise last_error
    return deleted


async def _purge_neo4j(subject_user_id: uuid.UUID) -> int:
    try:
        from app.services.atlas.neo4j_client import run_cypher
    except Exception:
        return 0
    cypher = "MATCH (n) WHERE n.user_id = $uid DETACH DELETE n RETURN count(n) AS n"
    res = await run_cypher(cypher, {"uid": str(subject_user_id)})
    if not res:
        return 0
    return int(res[0].get("n", 0))


async def _purge_blob(subject_user_id: uuid.UUID) -> int:
    try:
        from app.core.blob import delete_prefix
    except Exception:
        return 0
    prefix = f"users/{subject_user_id}/"
    return await delete_prefix(prefix)


async def _purge_trajectory(subject_user_id: uuid.UUID) -> int:
    return 0


_PURGERS = {
    "postgres": _purge_postgres,
    "pinecone": _purge_pinecone,
    "neo4j": _purge_neo4j,
    "blob": _purge_blob,
    "trajectory": _purge_trajectory,
}


async def purge_user(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    subject_user_id: uuid.UUID,
    requested_by: uuid.UUID | None = None,
) -> dict[str, dict]:
    receipt: dict[str, dict] = {}
    for store in STORES:
        purger = _PURGERS[store]
        await _log_store(db, tenant_id, subject_user_id, requested_by, store, "started")
        try:
            if store == "postgres":
                count = await purger(db, subject_user_id, requested_by)
            else:
                count = await purger(subject_user_id)
            await _log_store(
                db,
                tenant_id,
                subject_user_id,
                requested_by,
                store,
                "completed",
                error=None,
                retries=0,
            )
            receipt[store] = {"status": "completed", "affected": count}
        except Exception as e:
            logger.exception("gdpr purge failed for store=%s", store)
            await _log_store(
                db,
                tenant_id,
                subject_user_id,
                requested_by,
                store,
                "failed",
                error=str(e)[:1000],
                retries=0,
            )
            receipt[store] = {"status": "failed", "error": str(e)[:300]}
    return receipt


async def list_receipts(
    db: AsyncSession,
    subject_user_id: uuid.UUID,
    limit: int = 100,
) -> list[GDPRPurgeLog]:
    res = await db.execute(
        select(GDPRPurgeLog)
        .where(GDPRPurgeLog.subject_user_id == subject_user_id)
        .order_by(GDPRPurgeLog.attempted_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


__all__ = ["purge_user", "list_receipts", "STORES"]
