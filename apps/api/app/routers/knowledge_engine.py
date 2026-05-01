"""Knowledge Engine API — cognify, search, feedback, and graph stats."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.schemas.knowledge_engine import CognifyRequest, FeedbackRequest, SearchRequest
from app.services.kb_access import user_can_access_collection

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from models.user import User

router = APIRouter(prefix="/api/knowledge-engines", tags=["knowledge-engine"])


@router.post("/{kb_id}/cognify")
async def trigger_cognify(
    kb_id: uuid.UUID,
    body: CognifyRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Trigger cognify — build knowledge graph from documents."""
    from models.knowledge_base import KnowledgeBase, Document, DocumentStatus

    # Verify KB exists, belongs to tenant, and the user can access it.
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)

    # Get documents to process
    doc_query = select(Document).where(
        Document.kb_id == kb_id,
        Document.status == DocumentStatus.READY,
    )
    if body and body.doc_ids:
        doc_query = doc_query.where(Document.id.in_([uuid.UUID(d) for d in body.doc_ids]))

    doc_result = await db.execute(doc_query)
    documents = doc_result.scalars().all()

    if not documents:
        return error("No ready documents to cognify", 400)

    # Create cognify job
    try:
        from models.knowledge_engine import CognifyJob
        job = CognifyJob(
            tenant_id=user.tenant_id,
            kb_id=kb_id,
            status="pending",
            config={
                "model": body.model if body else "claude-sonnet-4-5-20250929",
                "chunk_size": body.chunk_size if body else 1000,
                "chunk_overlap": body.chunk_overlap if body else 200,
            },
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
    except Exception as e:
        return error(f"Failed to create cognify job: {e}", 500)

    import logging as _log
    _logger = _log.getLogger(__name__)
    try:
        import os
        from celery import Celery
        broker = os.environ.get(
            "CELERY_BROKER_URL", "redis://localhost:6379/0",
        )
        backend = os.environ.get(
            "CELERY_RESULT_BACKEND", "redis://localhost:6379/1",
        )
        client = Celery("api_dispatcher", broker=broker, backend=backend)
        client.send_task(
            "worker.tasks.cognify_task.run_cognify_job",
            kwargs={
                "job_id": str(job.id),
                "kb_id": str(kb_id),
                "tenant_id": str(user.tenant_id),
                "doc_ids": [str(d.id) for d in documents],
                "config": job.config,
            },
            queue="cognify",
        )
        _logger.info("Dispatched cognify job %s to queue 'cognify'", job.id)
    except Exception as e:
        # Hard-log the failure so this never silently regresses again.
        _logger.error("Failed to dispatch cognify job %s: %s", job.id, e)

    return success({
        "job_id": str(job.id),
        "status": "pending",
        "documents": len(documents),
        "message": f"Cognify job created. Processing {len(documents)} documents.",
    })


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
            select(func.count()).select_from(GraphEntity).where(GraphEntity.kb_id == kb_id)
        )
        entity_count = entity_count_result.scalar() or 0

        rel_count_result = await db.execute(
            select(func.count()).select_from(GraphRelationship).where(GraphRelationship.kb_id == kb_id)
        )
        relationship_count = rel_count_result.scalar() or 0

        # Entity type breakdown
        type_result = await db.execute(
            select(GraphEntity.entity_type, func.count()).where(
                GraphEntity.kb_id == kb_id,
            ).group_by(GraphEntity.entity_type)
        )
        entities_by_type = {row[0]: row[1] for row in type_result.all()}

        # Top entities
        top_result = await db.execute(
            select(
                GraphEntity.canonical_name,
                GraphEntity.entity_type,
                GraphEntity.mention_count,
                GraphEntity.description,
            ).where(
                GraphEntity.kb_id == kb_id,
            ).order_by(GraphEntity.mention_count.desc()).limit(10)
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
    return success({
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
    })


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
        subgraph = await get_subgraph(str(kb_id), limit=limit)
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
        from engine.knowledge.hybrid_search import hybrid_search, SearchMode
        response = await hybrid_search(
            query=body.query,
            kb_ids=[str(kb_id)],
            mode=SearchMode(body.mode),
            top_k=body.top_k,
            graph_depth=body.graph_depth,
        )
        return success({
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
            "vector_count": response.vector_results_count,
            "graph_count": response.graph_results_count,
            "entities_found": response.entities_found,
            "graph_hops": response.graph_hops,
            "latency_ms": response.latency_ms,
        })
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
                    feedback_data=[{
                        "entity_ids": body.result_entity_ids,
                        "rating": body.rating,
                        "query": body.query,
                    }],
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
    kb_row = (await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )).scalar_one_or_none()
    if not kb_row or not await user_can_access_collection(db, user=user, kb=kb_row):
        return error("Knowledge base not found", 404)

    try:
        from models.knowledge_engine import CognifyJob

        result = await db.execute(
            select(CognifyJob).where(
                CognifyJob.kb_id == kb_id,
                CognifyJob.tenant_id == user.tenant_id,
            ).order_by(CognifyJob.created_at.desc()).limit(20)
        )
        jobs = result.scalars().all()
        return success([
            {
                "id": str(j.id),
                "status": j.status if isinstance(j.status, str) else j.status.value,
                "entities_extracted": j.entities_extracted,
                "relationships_extracted": j.relationships_extracted,
                "documents_processed": j.documents_processed,
                "tokens_used": j.tokens_used,
                "cost_usd": float(j.cost_usd) if j.cost_usd else 0,
                "duration_seconds": float(j.duration_seconds) if j.duration_seconds else None,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "error_message": j.error_message,
            }
            for j in jobs
        ])
    except Exception as e:
        return error(f"Failed to list jobs: {e}", 500)
