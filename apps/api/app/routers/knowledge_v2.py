"""v2 enterprise endpoints on top of the existing /api/knowledge surface.

Admin verbs for the enterprise ingest workflow:

  POST   /api/knowledge/{kb_id}/documents/{doc_id}/replace   versioning
  GET    /api/knowledge/{kb_id}/reembed                      model + job progress
  POST   /api/knowledge/{kb_id}/reembed                      embed-model swap
  GET    /api/knowledge/cognify-config                       per-tenant config
  PUT    /api/knowledge/cognify-config                       update threshold etc.
  GET    /api/knowledge/cognify-conflicts                    list open conflicts
  POST   /api/knowledge/cognify-conflicts/{id}/resolve       human resolution
"""

from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

import embedding_models
from models.cognify_config import CognifyConfig, CognifyConflict
from models.knowledge_base import Document, KnowledgeBase
from models.user import User, UserRole

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)


def _is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


class ReplaceDocumentRequest(BaseModel):
    new_filename: str = Field(min_length=1, max_length=500)
    new_storage_url: str = Field(min_length=1, max_length=1000)
    new_file_type: str = Field(min_length=1, max_length=50)
    new_file_size: int = Field(ge=0)


@router.post("/{kb_id}/documents/{doc_id}/replace")
async def replace_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    body: ReplaceDocumentRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    res = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.kb_id == kb_id,
        )
    )
    old = res.scalar_one_or_none()
    if old is None:
        return error("Document not found", 404)
    if not old.is_current:
        return error(
            "Cannot replace a superseded version; replace the current head", 400
        )

    new = Document(
        id=uuid.uuid4(),
        kb_id=kb_id,
        filename=body.new_filename,
        file_type=body.new_file_type,
        file_size=body.new_file_size,
        storage_url=body.new_storage_url,
        parent_document_id=old.parent_document_id or old.id,
        version_number=(old.version_number or 1) + 1,
        is_current=True,
    )
    db.add(new)
    old.is_current = False
    old.superseded_by = new.id
    await db.commit()
    await db.refresh(new)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "document.replaced",
        {"old_id": str(old.id), "new_id": str(new.id), "version": new.version_number},
        request,
    )
    await db.commit()
    return success(
        {
            "id": str(new.id),
            "version_number": new.version_number,
            "parent_document_id": (
                str(new.parent_document_id) if new.parent_document_id else None
            ),
            "supersedes": str(old.id),
        },
        status_code=201,
    )


class ReembedRequest(BaseModel):
    embedding_model: str = Field(min_length=1, max_length=120)
    dry_run: bool = Field(default=False)


def _job_is_live(state: dict | None) -> bool:
    """A queued or running job that has not outlived the worker's time limit."""
    from app.workers.kb_reembed import ACTIVE

    if not state or state.get("status") not in ACTIVE:
        return False
    stamp = state.get("started_at") or state.get("queued_at")
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return False
    limit = 6 * 3600 if state.get("status") == "running" else 3600
    return age.total_seconds() < limit


async def _reembed_kb_or_error(
    db: AsyncSession, kb_id: uuid.UUID, user: User
) -> KnowledgeBase | None:
    res = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    return res.scalar_one_or_none()


@router.get("/{kb_id}/reembed")
async def reembed_status(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    from app.services.kb_access import user_can_access_collection
    from app.workers.kb_reembed import get_status

    kb = await _reembed_kb_or_error(db, kb_id, user)
    if kb is None or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    return success(
        {
            "kb_id": str(kb_id),
            "embedding_model": kb.embedding_model,
            "supported_models": list(embedding_models.SUPPORTED),
            "job": await get_status(kb_id),
        }
    )


@router.post("/{kb_id}/reembed")
async def reembed_kb(
    kb_id: uuid.UUID,
    body: ReembedRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not _is_admin(user):
        return error("Only admins can re-embed a KB", 403)
    kb = await _reembed_kb_or_error(db, kb_id, user)
    if kb is None:
        return error("Knowledge base not found", 404)
    if not embedding_models.is_supported(body.embedding_model):
        return error(
            f"Unsupported embedding model {body.embedding_model}. "
            f"Choose one of: {', '.join(embedding_models.SUPPORTED)}",
            400,
        )

    old_model = kb.embedding_model
    chunks = await db.execute(
        select(Document.chunk_count).where(Document.kb_id == kb_id)
    )
    total = sum(c or 0 for (c,) in chunks.all())
    if body.dry_run:
        # rough, about 250 tokens a chunk at the small-model rate
        local = embedding_models.is_local(body.embedding_model)
        estimated_usd = 0.0 if local else round(total * 250 / 1_000_000 * 0.02, 4)
        return success(
            {
                "kb_id": str(kb_id),
                "from_model": old_model,
                "to_model": body.embedding_model,
                "chunks_to_reembed": total,
                "estimated_usd": estimated_usd,
                "estimated_seconds": max(60, total // 50),
                "supported_models": list(embedding_models.SUPPORTED),
            }
        )

    from app.workers.kb_reembed import enqueue_reembed, get_status

    current = await get_status(kb_id)
    if _job_is_live(current):
        return error(
            f"A re-embed of this collection is already {current['status']}", 409
        )
    try:
        job_id = await enqueue_reembed(
            kb_id=kb_id, new_model=body.embedding_model, from_model=old_model
        )
    except Exception as e:
        return error(f"Could not queue the re-embed job: {e}", 503)

    await log_action(
        db,
        user.tenant_id,
        user.id,
        "kb.reembed_started",
        {
            "kb_id": str(kb_id),
            "job_id": str(job_id),
            "from_model": old_model,
            "to_model": body.embedding_model,
        },
        request,
    )
    await db.commit()
    return success(
        {
            "kb_id": str(kb_id),
            "job_id": str(job_id),
            "from_model": old_model,
            "to_model": body.embedding_model,
            "chunks_to_reembed": total,
            "status": "queued",
        },
        status_code=202,
    )


@router.get("/cognify-config")
async def get_cognify_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    res = await db.execute(
        select(CognifyConfig).where(CognifyConfig.tenant_id == user.tenant_id)
    )
    cfg = res.scalar_one_or_none()
    if cfg is None:
        return success(
            {
                "auto_accept_threshold": 0.85,
                "conflict_action": "flag",
                "max_parallel_docs": 8,
                "daily_budget_usd": None,
                "is_default": True,
            }
        )
    return success(
        {
            "auto_accept_threshold": float(cfg.auto_accept_threshold),
            "conflict_action": cfg.conflict_action,
            "max_parallel_docs": cfg.max_parallel_docs,
            "daily_budget_usd": (
                float(cfg.daily_budget_usd) if cfg.daily_budget_usd else None
            ),
            "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        }
    )


class CognifyConfigRequest(BaseModel):
    auto_accept_threshold: float = Field(ge=0.0, le=1.0, default=0.85)
    conflict_action: str = Field(
        default="flag", pattern=r"^(flag|split|lower_conf_wins|higher_conf_wins)$"
    )
    max_parallel_docs: int = Field(ge=1, le=64, default=8)
    daily_budget_usd: float | None = Field(default=None, ge=0.0)


@router.put("/cognify-config")
async def put_cognify_config(
    body: CognifyConfigRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not _is_admin(user):
        return error("Only admins can edit cognify config", 403)
    res = await db.execute(
        select(CognifyConfig).where(CognifyConfig.tenant_id == user.tenant_id)
    )
    cfg = res.scalar_one_or_none()
    if cfg is None:
        cfg = CognifyConfig(
            tenant_id=user.tenant_id,
            auto_accept_threshold=body.auto_accept_threshold,
            conflict_action=body.conflict_action,
            max_parallel_docs=body.max_parallel_docs,
            daily_budget_usd=body.daily_budget_usd,
        )
        db.add(cfg)
    else:
        cfg.auto_accept_threshold = body.auto_accept_threshold
        cfg.conflict_action = body.conflict_action
        cfg.max_parallel_docs = body.max_parallel_docs
        cfg.daily_budget_usd = body.daily_budget_usd
        cfg.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "cognify.config_updated",
        body.model_dump(),
        request,
    )
    await db.commit()
    return success({"saved": True})


@router.get("/cognify-conflicts")
async def list_conflicts(
    status: str = "open",
    limit: int = 50,
    cursor: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    limit = max(1, min(limit, 200))
    q = select(CognifyConflict).where(
        CognifyConflict.tenant_id == user.tenant_id,
        CognifyConflict.status == status,
    )
    if cursor is not None:
        try:
            cursor_id = uuid.UUID(cursor)
            q = q.where(CognifyConflict.id < cursor_id)
        except Exception:
            return error("Invalid cursor", 400)
    q = q.order_by(CognifyConflict.created_at.desc()).limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()
    next_cursor = str(rows[limit].id) if len(rows) > limit else None
    rows = rows[:limit]
    return success(
        {
            "items": [
                {
                    "id": str(c.id),
                    "entity": c.entity_canonical_name,
                    "property": c.property_name,
                    "source_a": {
                        "doc_id": str(c.source_a_doc_id),
                        "value": c.source_a_value,
                        "confidence": float(c.source_a_confidence),
                    },
                    "source_b": {
                        "doc_id": str(c.source_b_doc_id),
                        "value": c.source_b_value,
                        "confidence": float(c.source_b_confidence),
                    },
                    "status": c.status,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in rows
            ],
            "next_cursor": next_cursor,
        }
    )


class ResolveConflictRequest(BaseModel):
    resolved_value: str = Field(min_length=1, max_length=100)


async def _apply_entity_type(
    db: AsyncSession, kb_id: uuid.UUID, entity: str, value: str
) -> bool:
    """Write the chosen type to the graph, Postgres mirror first, then Neo4j."""
    from sqlalchemy import text

    r = await db.execute(
        text(
            "UPDATE graph_entities SET entity_type = :v, updated_at = now() "
            "WHERE kb_id = :kb AND canonical_name = :name"
        ),
        {"v": value, "kb": kb_id, "name": entity},
    )
    try:
        sys.path.insert(
            0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime")
        )
        from engine.knowledge.neo4j_client import get_neo4j_session, is_neo4j_available

        if await is_neo4j_available():
            session = await get_neo4j_session()
            async with session:
                await session.run(
                    "MATCH (e:Entity {kb_id: $kb, canonical_name: $name}) "
                    "SET e.entity_type = $v, e.updated_at = datetime()",
                    kb=str(kb_id),
                    name=entity,
                    v=value,
                )
            return True
    except Exception:
        logger.exception("could not apply conflict resolution to Neo4j")
    return bool(r.rowcount)


@router.post("/cognify-conflicts/{conflict_id}/resolve")
async def resolve_conflict(
    conflict_id: uuid.UUID,
    body: ResolveConflictRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not _is_admin(user):
        return error("Only admins can resolve conflicts", 403)
    res = await db.execute(
        select(CognifyConflict).where(
            CognifyConflict.id == conflict_id,
            CognifyConflict.tenant_id == user.tenant_id,
        )
    )
    c = res.scalar_one_or_none()
    if c is None:
        return error("Conflict not found", 404)
    if c.status != "open":
        return error(f"Conflict already {c.status}", 409)
    if c.property_name == "entity_type" and body.resolved_value not in (
        c.source_a_value,
        c.source_b_value,
    ):
        return error("Pick one of the two values the sources gave", 400)
    c.resolved_value = body.resolved_value
    c.resolved_by = user.id
    c.resolved_at = datetime.now(timezone.utc)
    c.status = "resolved"
    applied = False
    if c.property_name == "entity_type":
        applied = await _apply_entity_type(
            db, c.knowledge_base_id, c.entity_canonical_name, body.resolved_value
        )
    await db.commit()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "cognify.conflict_resolved",
        {"conflict_id": str(conflict_id), "value": body.resolved_value[:200]},
        request,
    )
    await db.commit()
    return success({"resolved": True, "applied_to_graph": applied})


__all__ = ["router"]
