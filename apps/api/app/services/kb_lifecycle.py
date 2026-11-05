"""API side of collection deletes and re-embeds, state lives in Postgres."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.knowledge_base import Document, KnowledgeBase
from models.knowledge_ops import REEMBED_LIVE, KBDeleteJob, KBReembedJob

logger = logging.getLogger(__name__)

QUEUE = "documents"
DELETE_TASK = "worker.tasks.kb_delete.run"
REEMBED_TASK = "worker.tasks.kb_reembed.run"
# a worker beats at least once a batch, past this it is gone and the slice is sent again
STALE_AFTER = timedelta(minutes=int(os.environ.get("KB_JOB_STALE_MINUTES", "15")))


def send_task(name: str, kwargs: dict[str, Any]) -> None:
    from celery import Celery

    app = Celery(broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1"))
    app.send_task(name, kwargs=kwargs, queue=QUEUE)


async def _dispatch(name: str, job_id: uuid.UUID) -> bool:
    """The sweep sends it again, so a broker outage only delays the job."""
    try:
        await asyncio.to_thread(send_task, name, {"job_id": str(job_id)})
        return True
    except Exception as e:
        logger.warning("could not queue %s for %s: %s", name, job_id, e)
        return False


async def tombstone_collection(
    db: AsyncSession, kb: KnowledgeBase, user_id: uuid.UUID | None
) -> KBDeleteJob:
    """Search stops when this commits, the worker then removes the data."""
    from engine.knowledge import search_cache

    kb.deleted_at = datetime.now(timezone.utc)
    job = KBDeleteJob(
        id=uuid.uuid4(),
        tenant_id=kb.tenant_id,
        kb_id=kb.id,
        kb_name=kb.name,
        status="queued",
        phase="graph",
        requested_by=user_id,
    )
    db.add(job)
    await db.execute(
        text(
            "UPDATE kb_reembed_jobs SET status = 'cancelled', finished_at = now(), "
            "error = 'the collection was deleted' WHERE kb_id = :k "
            "AND status IN ('queued','running','pausing','paused','flipping','cleaning')"
        ),
        {"k": str(kb.id)},
    )
    await db.commit()
    await search_cache.invalidate_tenant(str(kb.tenant_id))
    await _dispatch(DELETE_TASK, job.id)
    return job


def serialize_delete_job(job: KBDeleteJob) -> dict[str, Any]:
    return {
        "job_id": str(job.id),
        "kb_id": str(job.kb_id),
        "kb_name": job.kb_name,
        "status": job.status,
        "phase": job.phase,
        "documents_deleted": job.documents_deleted,
        "chunks_deleted": job.chunks_deleted,
        "files_deleted": job.files_deleted,
        "entities_deleted": job.entities_deleted,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def serialize_reembed_job(job: KBReembedJob) -> dict[str, Any]:
    return {
        "job_id": str(job.id),
        "kb_id": str(job.kb_id),
        "status": job.status,
        "from_model": job.from_model,
        "to_model": job.to_model,
        "backend": job.backend,
        "documents_total": job.documents_total,
        "documents_done": job.documents_done,
        "chunks": job.chunks_done,
        "from_file": job.from_file,
        "from_indexed_text": job.from_indexed_text,
        "error": job.error,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "flipped_at": job.flipped_at.isoformat() if job.flipped_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


async def latest_reembed(db: AsyncSession, kb_id: uuid.UUID) -> KBReembedJob | None:
    return (
        await db.execute(
            select(KBReembedJob)
            .where(KBReembedJob.kb_id == kb_id)
            .order_by(KBReembedJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def live_reembed(db: AsyncSession, kb_id: uuid.UUID) -> KBReembedJob | None:
    return (
        await db.execute(
            select(KBReembedJob).where(
                KBReembedJob.kb_id == kb_id, KBReembedJob.status.in_(REEMBED_LIVE)
            )
        )
    ).scalar_one_or_none()


async def start_reembed(
    db: AsyncSession, kb: KnowledgeBase, new_model: str, user_id: uuid.UUID | None
) -> KBReembedJob:
    highest = (
        await db.execute(
            select(func.max(KBReembedJob.target_generation)).where(
                KBReembedJob.kb_id == kb.id
            )
        )
    ).scalar()
    total = (
        await db.execute(
            select(func.count()).select_from(Document).where(Document.kb_id == kb.id)
        )
    ).scalar()
    job = KBReembedJob(
        id=uuid.uuid4(),
        tenant_id=kb.tenant_id,
        kb_id=kb.id,
        from_model=kb.embedding_model,
        to_model=new_model,
        backend=kb.vector_backend or "pinecone",
        from_generation=kb.embedding_generation or 0,
        target_generation=max(kb.embedding_generation or 0, highest or 0) + 1,
        status="queued",
        documents_total=total or 0,
        requested_by=user_id,
    )
    db.add(job)
    await db.commit()
    await _dispatch(REEMBED_TASK, job.id)
    return job


async def request_pause(db: AsyncSession, job: KBReembedJob) -> KBReembedJob:
    """The worker stops at its next document, queued work never starts."""
    if job.status == "queued":
        job.status = "paused"
    elif job.status == "running":
        job.status = "pausing"
    await db.commit()
    return job


async def request_resume(db: AsyncSession, job: KBReembedJob) -> KBReembedJob:
    job.status = "queued"
    job.error = None
    job.finished_at = None
    await db.commit()
    await _dispatch(REEMBED_TASK, job.id)
    return job


async def request_cancel(db: AsyncSession, job: KBReembedJob) -> KBReembedJob:
    job.status = "cancelling"
    await db.commit()
    await _dispatch(REEMBED_TASK, job.id)
    return job


async def sweep_stuck_jobs(db: AsyncSession) -> dict[str, int]:
    """Send a slice again for jobs whose worker died or whose broker message was lost."""
    before = datetime.now(timezone.utc) - STALE_AFTER
    deletes = (
        (
            await db.execute(
                select(KBDeleteJob.id).where(
                    KBDeleteJob.status.in_(("queued", "running", "waiting", "failed")),
                    func.coalesce(KBDeleteJob.heartbeat_at, KBDeleteJob.created_at)
                    < before,
                )
            )
        )
        .scalars()
        .all()
    )
    reembeds = (
        (
            await db.execute(
                select(KBReembedJob.id).where(
                    KBReembedJob.status.in_(
                        ("queued", "running", "flipping", "cleaning", "cancelling")
                    ),
                    func.coalesce(KBReembedJob.heartbeat_at, KBReembedJob.created_at)
                    < before,
                )
            )
        )
        .scalars()
        .all()
    )
    # a pausing worker that died never reaches paused
    paused = await db.execute(
        text(
            "UPDATE kb_reembed_jobs SET status = 'paused', updated_at = now() "
            "WHERE status = 'pausing' AND COALESCE(heartbeat_at, created_at) < :b"
        ),
        {"b": before},
    )
    await db.commit()
    for job_id in deletes:
        await _dispatch(DELETE_TASK, job_id)
    for job_id in reembeds:
        await _dispatch(REEMBED_TASK, job_id)
    return {
        "deletes": len(deletes),
        "reembeds": len(reembeds),
        "paused": paused.rowcount or 0,
    }
