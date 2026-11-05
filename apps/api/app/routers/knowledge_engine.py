"""Knowledge Engine API — cognify, search, feedback, and graph stats."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.schemas.knowledge_engine import CognifyRequest, FeedbackRequest, SearchRequest
from app.services.kb_access import user_can_access_collection, user_can_edit_collection

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from models.user import User

router = APIRouter(prefix="/api/knowledge-engines", tags=["knowledge-engine"])


STALLED_PENDING_MINUTES = 15
STALLED_RUNNING_HOURS = 6


async def fail_stalled_cognify_jobs(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Close jobs no worker took or finished, so they stop blocking Run Cognify."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, update

    from models.knowledge_engine import CognifyJob, CognifyStatus

    now = datetime.now(timezone.utc)
    running = [
        CognifyStatus.EXTRACTING,
        CognifyStatus.RESOLVING,
        CognifyStatus.GRAPHING,
        CognifyStatus.EMBEDDING,
    ]
    total = 0
    for statuses, since, why in (
        (
            [CognifyStatus.PENDING],
            now - timedelta(minutes=STALLED_PENDING_MINUTES),
            "No Cognify worker picked this job up. Run Cognify again.",
        ),
        (
            running,
            now - timedelta(hours=STALLED_RUNNING_HOURS),
            "The Cognify worker stopped before finishing. Run Cognify again.",
        ),
    ):
        res = await db.execute(
            update(CognifyJob)
            .where(
                CognifyJob.tenant_id == tenant_id,
                CognifyJob.status.in_(statuses),
                func.coalesce(
                    CognifyJob.heartbeat_at,
                    CognifyJob.started_at,
                    CognifyJob.created_at,
                )
                < since,
            )
            .values(status=CognifyStatus.FAILED, error_message=why, completed_at=now)
        )
        total += res.rowcount or 0
    if total:
        await db.commit()
    return total


@router.get("/cognify/active")
async def list_active_cognify_jobs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Tenant-scoped list of cognify jobs running or completed in the last hour."""
    from datetime import datetime, timedelta, timezone

    try:
        from models.knowledge_engine import CognifyJob, CognifyStatus
        from models.knowledge_base import KnowledgeBase
    except Exception as e:
        return error(f"Failed to load cognify models: {e}", 500)

    await fail_stalled_cognify_jobs(db, user.tenant_id)
    terminal = {
        CognifyStatus.COMPLETE.value,
        CognifyStatus.FAILED.value,
        CognifyStatus.STOPPED.value,
    }
    running_statuses = [s.value for s in CognifyStatus if s.value not in terminal]

    running_q = (
        select(CognifyJob, KnowledgeBase.name)
        .join(KnowledgeBase, KnowledgeBase.id == CognifyJob.kb_id, isouter=True)
        .where(
            CognifyJob.tenant_id == user.tenant_id,
            CognifyJob.status.in_(running_statuses),
        )
        .order_by(CognifyJob.created_at.desc())
        .limit(20)
    )
    running_rows = (await db.execute(running_q)).all()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_q = (
        select(CognifyJob, KnowledgeBase.name)
        .join(KnowledgeBase, KnowledgeBase.id == CognifyJob.kb_id, isouter=True)
        .where(
            CognifyJob.tenant_id == user.tenant_id,
            CognifyJob.status.in_(list(terminal)),
            CognifyJob.completed_at >= cutoff,
        )
        .order_by(CognifyJob.completed_at.desc())
        .limit(10)
    )
    recent_rows = (await db.execute(recent_q)).all()

    def _serialize(job: "CognifyJob", kb_name: str | None) -> dict:
        return {
            **_job_summary(job),
            "kb_id": str(job.kb_id),
            "kb_name": kb_name or "Unknown KB",
        }

    return success(
        {
            "running": [_serialize(j, name) for j, name in running_rows],
            "recent": [_serialize(j, name) for j, name in recent_rows],
        }
    )


def _job_summary(job: Any) -> dict:
    status = job.status if isinstance(job.status, str) else job.status.value
    details = job.details or {}
    return {
        "id": str(job.id),
        "status": status,
        "documents_total": job.documents_total or 0,
        "documents_processed": job.documents_processed or 0,
        "chunks_total": job.chunks_total or 0,
        "chunks_processed": job.chunks_processed or 0,
        "chunks_skipped": job.chunks_skipped or 0,
        "chunks_failed": job.chunks_failed or 0,
        "entities_extracted": job.entities_extracted or 0,
        "entities_written": job.entities_written or 0,
        "entities_failed": job.entities_failed or 0,
        "relationships_extracted": job.relationships_extracted or 0,
        "relationships_written": job.relationships_written or 0,
        "relationships_failed": job.relationships_failed or 0,
        "off_ontology_dropped": job.off_ontology_dropped or 0,
        "tokens_used": job.tokens_used or 0,
        "cost_usd": float(job.cost_usd) if job.cost_usd else 0.0,
        "budget_usd": float(job.budget_usd) if job.budget_usd is not None else None,
        "stop_reason": job.stop_reason,
        "stop_requested": bool(job.stop_requested),
        "duration_seconds": (
            float(job.duration_seconds) if job.duration_seconds else None
        ),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
        "entities_held_back": details.get("entities_held_back"),
        "relationships_held_back": details.get("relationships_held_back"),
        "conflicts_recorded": details.get("conflicts_recorded"),
    }


def _cognify_defaults() -> tuple[str, float]:
    from engine.knowledge.cognify_pipeline import (
        DEFAULT_COGNIFY_MODEL,
        DEFAULT_JOB_BUDGET_USD,
    )

    return DEFAULT_COGNIFY_MODEL, DEFAULT_JOB_BUDGET_USD


def _dispatcher() -> Any:
    import os

    from celery import Celery

    # same defaults as the worker's celery_app, or a bare install never meets its queue
    broker = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
    backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
    return Celery("api_dispatcher", broker=broker, backend=backend)


async def _load_visible_kb(
    db: AsyncSession, kb_id: uuid.UUID, user: User
) -> Any | None:
    from models.knowledge_base import KnowledgeBase

    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return None
    return kb


@router.post("/{kb_id}/cognify")
async def trigger_cognify(
    kb_id: uuid.UUID,
    body: CognifyRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Trigger cognify, or with dry_run report what it would cost."""
    from models.knowledge_base import Document, DocumentStatus
    from models.knowledge_engine import CognifyJob, CognifyStatus

    body = body or CognifyRequest()
    kb = await _load_visible_kb(db, kb_id, user)
    if not kb:
        return error("Knowledge base not found", 404)

    default_model, default_budget = _cognify_defaults()
    model = body.model or default_model

    doc_ids = [uuid.UUID(d) for d in body.doc_ids] if body.doc_ids else None
    scope = [
        Document.kb_id == kb_id,
        Document.status == DocumentStatus.READY,
        Document.is_current.is_(True),
    ]
    if doc_ids:
        scope.append(Document.id.in_(doc_ids))
    ready = (
        await db.execute(select(func.count()).select_from(Document).where(*scope))
    ).scalar() or 0
    if not ready:
        return error("No ready documents to cognify", 400)

    wanted = list(scope)
    if not doc_ids and not body.force:
        wanted.append(Document.cognified_at.is_(None))
    documents, chunks = (
        await db.execute(
            select(
                func.count(), func.coalesce(func.sum(Document.chunk_count), 0)
            ).where(*wanted)
        )
    ).one()

    if body.dry_run:
        from engine.knowledge.cognify_pipeline import estimate_cost

        share = body.sample_rate if body.selection != "all" else 1.0
        planned = int(chunks * share)
        if body.max_chunks_per_doc:
            planned = min(planned, documents * body.max_chunks_per_doc)
        return success(
            {
                "documents": documents,
                "chunks": planned,
                "chunks_total": int(chunks),
                "model": model,
                "estimated_usd": round(estimate_cost(planned, model), 4),
                "max_cost_usd": (
                    body.max_cost_usd
                    if body.max_cost_usd is not None
                    else default_budget
                ),
                "note": "Chunks already in the ledger are skipped, so a rerun costs less than this.",
            }
        )

    active = (
        await db.execute(
            select(CognifyJob.id).where(
                CognifyJob.kb_id == kb_id,
                CognifyJob.status.in_(
                    [
                        CognifyStatus.PENDING,
                        CognifyStatus.EXTRACTING,
                        CognifyStatus.RESOLVING,
                        CognifyStatus.GRAPHING,
                        CognifyStatus.EMBEDDING,
                    ]
                ),
            )
        )
    ).first()
    if active:
        await fail_stalled_cognify_jobs(db, user.tenant_id)
        still = (
            await db.execute(
                select(CognifyJob.status).where(CognifyJob.id == active[0])
            )
        ).scalar_one()
        if still not in (CognifyStatus.COMPLETE, CognifyStatus.FAILED):
            return error(
                "Cognify is already running on this collection. "
                "Stop it or wait for it to finish.",
                409,
            )

    config = {
        "model": model,
        "chunk_size": body.chunk_size,
        "chunk_overlap": body.chunk_overlap,
        "force": body.force,
        "selection": body.selection,
        "sample_rate": body.sample_rate,
        "max_chunks_per_doc": body.max_chunks_per_doc,
        "max_cost_usd": body.max_cost_usd,
        "max_parallel_chunks": body.max_parallel_chunks,
        "requests_per_minute": body.requests_per_minute,
        "tokens_per_minute": body.tokens_per_minute,
        "llm_resolution": body.llm_resolution,
    }
    try:
        job = CognifyJob(
            tenant_id=user.tenant_id,
            kb_id=kb_id,
            status=CognifyStatus.PENDING,
            config=config,
            budget_usd=(
                body.max_cost_usd if body.max_cost_usd is not None else default_budget
            ),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
    except Exception as e:
        return error(f"Failed to create cognify job: {e}", 500)

    import logging as _log

    _logger = _log.getLogger(__name__)
    try:
        _dispatcher().send_task(
            "worker.tasks.cognify_task.run_cognify_job",
            kwargs={
                "job_id": str(job.id),
                "kb_id": str(kb_id),
                "tenant_id": str(user.tenant_id),
                "doc_ids": [str(d) for d in doc_ids] if doc_ids else None,
                "config": config,
            },
            queue="cognify",
        )
        _logger.info("Dispatched cognify job %s to queue 'cognify'", job.id)
    except Exception as e:
        _logger.error("Failed to dispatch cognify job %s: %s", job.id, e)
        job.status = CognifyStatus.FAILED
        job.error_message = "The Cognify queue is not reachable. Check the worker and Redis, then run it again."
        await db.commit()
        return error(job.error_message, 503)

    return success(
        {
            "job_id": str(job.id),
            "status": "pending",
            "documents": documents,
            "chunks_estimated": int(chunks),
            "model": model,
            "max_cost_usd": float(job.budget_usd),
            "message": (
                f"Cognify job created. Processing {documents} documents."
                if documents
                else "Cognify job created. Every document is already in the graph."
            ),
        }
    )


@router.post("/{kb_id}/cognify/{job_id}/stop")
async def stop_cognify(
    kb_id: uuid.UUID,
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Ask a running job to stop after its current batch. Its work so far is kept."""
    from models.knowledge_engine import CognifyJob

    if not await _load_visible_kb(db, kb_id, user):
        return error("Knowledge base not found", 404)
    job = (
        await db.execute(
            select(CognifyJob).where(
                CognifyJob.id == job_id,
                CognifyJob.kb_id == kb_id,
                CognifyJob.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not job:
        return error("Job not found", 404)
    job.stop_requested = True
    job.stop_reason = job.stop_reason or "user_requested"
    await db.commit()
    return success({"id": str(job.id), "stop_requested": True})


@router.delete("/{kb_id}/graph")
async def delete_graph(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Remove this KB's graph from Neo4j, its Postgres mirror and the chunk ledger."""
    from sqlalchemy import delete as sa_delete, update

    from models.knowledge_base import Document, KnowledgeBase
    from models.knowledge_engine import CognifyChunk, GraphEntity, GraphRelationship

    kb = await _load_visible_kb(db, kb_id, user)
    if not kb:
        return error("Knowledge base not found", 404)
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return error("You don't have permission to change this collection", 403)
    try:
        await enqueue_graph_delete(str(kb_id))
    except Exception as e:
        return error(f"Could not delete the graph: {e}", 503)
    await db.execute(
        sa_delete(GraphRelationship).where(GraphRelationship.kb_id == kb_id)
    )
    await db.execute(sa_delete(GraphEntity).where(GraphEntity.kb_id == kb_id))
    await db.execute(sa_delete(CognifyChunk).where(CognifyChunk.kb_id == kb_id))
    await db.execute(
        update(Document)
        .where(Document.kb_id == kb_id)
        .values(cognified_at=None, last_cognify_job_id=None)
    )
    await db.execute(
        update(KnowledgeBase)
        .where(KnowledgeBase.id == kb_id)
        .values(
            entity_count=0,
            relationship_count=0,
            graph_enabled=False,
            last_cognified_at=None,
        )
    )
    await db.commit()
    return success({"kb_id": str(kb_id), "deleted": True})


async def enqueue_graph_delete(kb_id: str) -> None:
    """Queue the Neo4j delete. A KB's graph can be millions of nodes, so never in a request."""
    _dispatcher().send_task(
        "worker.tasks.cognify_task.delete_kb_graph",
        kwargs={"kb_id": kb_id},
        queue="cognify",
    )


@router.get("/{kb_id}/graph-stats")
async def get_graph_stats(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get knowledge graph statistics for a KB."""
    from models.knowledge_base import KnowledgeBase

    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)

    # Get entity/relationship counts from PostgreSQL
    try:
        from models.knowledge_engine import GraphEntity, GraphRelationship

        entity_count_result = await db.execute(
            select(func.count())
            .select_from(GraphEntity)
            .where(GraphEntity.kb_id == kb_id)
        )
        entity_count = entity_count_result.scalar() or 0

        rel_count_result = await db.execute(
            select(func.count())
            .select_from(GraphRelationship)
            .where(GraphRelationship.kb_id == kb_id)
        )
        relationship_count = rel_count_result.scalar() or 0

        # Entity type breakdown
        type_result = await db.execute(
            select(GraphEntity.entity_type, func.count())
            .where(
                GraphEntity.kb_id == kb_id,
            )
            .group_by(GraphEntity.entity_type)
        )
        entities_by_type = {row[0]: row[1] for row in type_result.all()}

        # Top entities
        top_result = await db.execute(
            select(
                GraphEntity.canonical_name,
                GraphEntity.entity_type,
                GraphEntity.mention_count,
                GraphEntity.description,
            )
            .where(
                GraphEntity.kb_id == kb_id,
            )
            .order_by(GraphEntity.mention_count.desc())
            .limit(10)
        )
        top_entities = [
            {"name": row[0], "type": row[1], "mentions": row[2], "description": row[3]}
            for row in top_result.all()
        ]

    except Exception:
        entity_count = getattr(kb, "entity_count", 0) or 0
        relationship_count = getattr(kb, "relationship_count", 0) or 0
        entities_by_type = {}
        top_entities = []

    # Check Neo4j health
    neo4j_available = False
    try:
        from engine.knowledge.neo4j_client import is_neo4j_available

        neo4j_available = await is_neo4j_available()
    except Exception:
        pass

    last_cognified = getattr(kb, "last_cognified_at", None)
    return success(
        {
            "kb_id": str(kb_id),
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "entities_by_type": entities_by_type,
            "top_entities": top_entities,
            "graph_enabled": getattr(kb, "graph_enabled", False),
            # ISO-format the datetime so the JSONResponse serialiser
            # doesn't blow up with 'Object of type datetime is not JSON
            # serializable' (silent 500 with empty body to the caller).
            "last_cognified_at": last_cognified.isoformat() if last_cognified else None,
            "neo4j_available": neo4j_available,
            "doc_count": kb.doc_count,
        }
    )


@router.get("/{kb_id}/graph")
async def get_graph_visualization(
    kb_id: uuid.UUID,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get a subgraph for visualization — nodes and edges."""
    from models.knowledge_base import KnowledgeBase

    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)

    try:
        from engine.knowledge.neo4j_client import get_subgraph

        subgraph = await get_subgraph(
            str(kb_id), limit=limit, tenant_id=str(user.tenant_id)
        )
        return success(subgraph)
    except Exception as e:
        return error(f"Could not retrieve graph: {e}", 500)


@router.post("/{kb_id}/search")
async def search_knowledge(
    kb_id: uuid.UUID,
    body: SearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Execute hybrid search across knowledge graph and vector store."""
    from models.knowledge_base import KnowledgeBase

    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)

    try:
        from engine.knowledge.hybrid_search import (
            EmbeddingProviderError,
            hybrid_search,
            SearchMode,
        )

        try:
            response = await hybrid_search(
                query=body.query,
                kb_ids=[str(kb_id)],
                mode=SearchMode(body.mode),
                top_k=body.top_k,
                graph_depth=body.graph_depth,
                tenant_id=str(user.tenant_id),
                user_id=str(user.id),
                user_role=getattr(user.role, "value", str(user.role)),
            )
        except EmbeddingProviderError as e:
            # Surface provider outage as 503 so callers can distinguish
            # "no match" from "retrieval is broken right now".
            raise HTTPException(
                status_code=503,
                detail={
                    "error_code": "embedding_provider_unavailable",
                    "message": (
                        "Knowledge search temporarily unavailable: "
                        "embedding provider did not respond"
                    ),
                },
            ) from e
        return success(
            {
                "results": [
                    {
                        "content": r.content,
                        "score": r.score,
                        "source": r.source,
                        "source_type": r.source_type,
                        "metadata": r.metadata,
                    }
                    for r in response.results
                ],
                "mode_used": response.mode_used,
                "degraded": response.degraded or None,
                "vector_count": response.vector_results_count,
                "graph_count": response.graph_results_count,
                "entities_found": response.entities_found,
                "graph_hops": response.graph_hops,
                "latency_ms": response.latency_ms,
                "hidden_documents": response.hidden_documents,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        return error(f"Search failed: {e}", 500)


@router.post("/{kb_id}/feedback")
async def submit_feedback(
    kb_id: uuid.UUID,
    body: FeedbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Submit feedback on search results to improve graph quality."""
    from models.knowledge_base import KnowledgeBase

    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)

    try:
        from models.knowledge_engine import RetrievalFeedback

        feedback = RetrievalFeedback(
            tenant_id=user.tenant_id,
            kb_id=kb_id,
            execution_id=uuid.UUID(body.execution_id) if body.execution_id else None,
            query=body.query,
            search_mode=body.search_mode,
            result_entity_ids=body.result_entity_ids,
            result_chunk_ids=body.result_chunk_ids,
            rating=body.rating,
            comment=body.comment,
        )
        db.add(feedback)
        await db.commit()

        # Trigger async memify if enough negative feedback accumulated
        if body.rating < 0:
            try:
                from engine.knowledge.memify_pipeline import run_memify

                # Run memify with this feedback (async, fire-and-forget is fine)
                await run_memify(
                    kb_id=str(kb_id),
                    trigger="feedback",
                    feedback_data=[
                        {
                            "entity_ids": body.result_entity_ids,
                            "rating": body.rating,
                            "query": body.query,
                        }
                    ],
                )
            except Exception:
                pass  # Memify is best-effort

        return success({"message": "Feedback recorded", "rating": body.rating})
    except Exception as e:
        return error(f"Failed to submit feedback: {e}", 500)


@router.get("/{kb_id}/cognify-jobs")
async def list_cognify_jobs(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List cognify job history for a KB."""
    from models.knowledge_base import KnowledgeBase

    # Enforce the same access semantics as the other KB endpoints so
    # tenant B cross-querying tenant A's kb_id gets 404 — not a 200
    # with an empty list, which would leak that the id exists elsewhere.
    kb_row = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not kb_row or not await user_can_access_collection(db, user=user, kb=kb_row):
        return error("Knowledge base not found", 404)

    try:
        from models.knowledge_engine import CognifyJob, CognifyReport

        await fail_stalled_cognify_jobs(db, user.tenant_id)
        result = await db.execute(
            select(CognifyJob)
            .where(
                CognifyJob.kb_id == kb_id,
                CognifyJob.tenant_id == user.tenant_id,
            )
            .order_by(CognifyJob.created_at.desc())
            .limit(20)
        )
        jobs = result.scalars().all()
        details: dict = {}
        if jobs:
            reports = await db.execute(
                select(CognifyReport.job_id, CognifyReport.processing_details).where(
                    CognifyReport.job_id.in_([j.id for j in jobs])
                )
            )
            details = {jid: d or {} for jid, d in reports.all()}
        rows = []
        for j in jobs:
            row = _job_summary(j)
            d = details.get(j.id, {})
            for key in (
                "entities_held_back",
                "relationships_held_back",
                "conflicts_recorded",
            ):
                if d.get(key) is not None:
                    row[key] = d.get(key)
            rows.append(row)
        return success(rows)
    except Exception as e:
        return error(f"Failed to list jobs: {e}", 500)
