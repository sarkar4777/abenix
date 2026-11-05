"""v2 enterprise endpoints on top of the existing /api/knowledge surface.

Admin verbs for the enterprise ingest workflow:

  POST   /api/knowledge/{kb_id}/documents/{doc_id}/replace   versioning
  GET    /api/knowledge/{kb_id}/documents/{doc_id}/versions  history, editors only
  GET    /api/knowledge/{kb_id}/reembed                      model + job progress
  POST   /api/knowledge/{kb_id}/reembed                      embed-model swap
  GET    /api/knowledge/cognify-config                       per-tenant config
  PUT    /api/knowledge/cognify-config                       update threshold etc.
  GET    /api/knowledge/cognify-conflicts                    list open conflicts
  POST   /api/knowledge/cognify-conflicts/{id}/resolve       human resolution
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
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
    # the id an upload returned, or the older form that names the stored file
    new_document_id: uuid.UUID | None = None
    new_filename: str | None = Field(default=None, min_length=1, max_length=500)
    new_storage_url: str | None = Field(default=None, min_length=1, max_length=1000)
    new_file_type: str | None = Field(default=None, min_length=1, max_length=50)
    new_file_size: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _one_form(self) -> "ReplaceDocumentRequest":
        stored = (
            self.new_filename,
            self.new_storage_url,
            self.new_file_type,
            self.new_file_size,
        )
        if self.new_document_id is not None:
            if any(v is not None for v in stored):
                raise ValueError("Send new_document_id or the file fields, not both.")
        elif any(v is None for v in stored):
            raise ValueError("Send new_document_id, the id your upload returned.")
        return self


def _owned_storage_url(url: str, tenant_id: Any, kb_id: Any) -> bool:
    """The new file must sit under this tenant's and this collection's own prefix."""
    norm = url.replace("\\", "/")
    if ".." in norm.split("/"):
        return False
    # object storage keys are {tenant}/kb/{kb}/..., the dev fallback is {upload_dir}/{tenant}/{kb}/...
    return (
        f"/{tenant_id}/kb/{kb_id}/" in f"/{norm}"
        or f"/{tenant_id}/{kb_id}/" in f"/{norm}"
    )


async def _document_in(
    db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID
) -> Document | None:
    return (
        await db.execute(
            select(Document).where(Document.id == doc_id, Document.kb_id == kb_id)
        )
    ).scalar_one_or_none()


COPY_GRANTS_SQL = """
INSERT INTO document_grants
    (id, document_id, tenant_id, subject_type, subject_id, permission,
     granted_by, granted_at, expires_at)
SELECT gen_random_uuid(), CAST(:new_id AS uuid), tenant_id, subject_type, subject_id,
       permission, granted_by, granted_at, expires_at
FROM document_grants WHERE document_id = CAST(:old_id AS uuid)
ON CONFLICT DO NOTHING
"""


async def _copy_grants(db: AsyncSession, old_id: uuid.UUID, new_id: uuid.UUID) -> None:
    # without this a restricted document's new version would be open to everyone
    from sqlalchemy import text

    await db.execute(text(COPY_GRANTS_SQL), {"old_id": old_id, "new_id": new_id})


def _stamp_superseded(kb: KnowledgeBase, old: Document) -> None:
    try:
        from celery import Celery

        broker = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
        Celery(broker=broker).send_task(
            "worker.tasks.pinecone_vacuum.stamp_superseded",
            args=[
                str(kb.id),
                str(old.id),
                old.chunk_count,
                kb.embedding_generation or 0,
            ],
            queue="documents",
        )
    except Exception as exc:
        # search still checks each hit against Postgres, this only keeps the filter short
        logger.warning("could not stamp superseded document %s: %s", old.id, exc)


@router.post("/{kb_id}/documents/{doc_id}/replace")
async def replace_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    body: ReplaceDocumentRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    from app.services.kb_access import (
        user_can_access_collection,
        user_can_edit_collection,
    )

    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if kb is None or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Document not found", 404)
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return error("You don't have permission to edit this collection", 403)
    if body.new_document_id is None and not _owned_storage_url(
        body.new_storage_url, user.tenant_id, kb_id
    ):
        return error(
            "The new file must be uploaded to this collection first. Upload it, then replace with that file.",
            400,
        )
    old = await _document_in(db, kb_id, doc_id)
    if old is None:
        return error("Document not found", 404)
    if not old.is_current:
        return error(
            "Cannot replace a superseded version; replace the current head", 400
        )

    parent = old.parent_document_id or old.id
    version = (old.version_number or 1) + 1
    if body.new_document_id is not None:
        new = await _document_in(db, kb_id, body.new_document_id)
        if new is None:
            return error("The new document was not found in this collection", 404)
        if new.id == old.id:
            return error(
                "That file is already the current version, there is nothing to replace.",
                409,
            )
        if not new.is_current or new.parent_document_id is not None:
            return error("That document is already part of a version history", 409)
        new.parent_document_id = parent
        new.version_number = version
    else:
        new = Document(
            id=uuid.uuid4(),
            kb_id=kb_id,
            filename=body.new_filename,
            file_type=body.new_file_type,
            file_size=body.new_file_size,
            storage_url=body.new_storage_url,
            parent_document_id=parent,
            version_number=version,
            is_current=True,
            uploaded_by=user.id,
        )
    db.add(new)
    await db.flush()
    await _copy_grants(db, old.id, new.id)
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
    # the new version is processed like any upload, otherwise it never gets chunks
    from app.routers.knowledge import _dispatch_processing

    if body.new_document_id is None:
        _dispatch_processing(
            doc_id=str(new.id),
            kb_id=str(kb_id),
            file_path=new.storage_url,
            filename=new.filename,
            file_type=new.file_type,
            chunk_size=kb.chunk_size,
            chunk_overlap=kb.chunk_overlap,
        )
    if kb.vector_backend == "pinecone" and old.chunk_count:
        _stamp_superseded(kb, old)
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


@router.get("/{kb_id}/documents/{doc_id}/versions")
async def document_versions(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Full version history of one document, oldest first. Editors only."""
    from app.routers.knowledge import _serialize_doc
    from app.services.kb_access import (
        user_can_access_collection,
        user_can_edit_collection,
    )

    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if kb is None or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Document not found", 404)
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return error("Only people who can edit this collection can view history", 403)
    doc = (
        await db.execute(
            select(Document).where(Document.id == doc_id, Document.kb_id == kb_id)
        )
    ).scalar_one_or_none()
    if doc is None:
        return error("Document not found", 404)
    root = doc.parent_document_id or doc.id
    rows = (
        (
            await db.execute(
                select(Document)
                .where(
                    Document.kb_id == kb_id,
                    (Document.id == root) | (Document.parent_document_id == root),
                )
                .order_by(Document.version_number.asc())
            )
        )
        .scalars()
        .all()
    )
    return success([_serialize_doc(d) for d in rows])


class ReembedRequest(BaseModel):
    embedding_model: str = Field(min_length=1, max_length=120)
    dry_run: bool = Field(default=False)


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
    from app.services.kb_lifecycle import latest_reembed, serialize_reembed_job

    kb = await _reembed_kb_or_error(db, kb_id, user)
    if kb is None or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    job = await latest_reembed(db, kb_id)
    return success(
        {
            "kb_id": str(kb_id),
            "embedding_model": kb.embedding_model,
            "supported_models": list(embedding_models.SUPPORTED),
            "job": serialize_reembed_job(job) if job else None,
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
    total = (
        await db.execute(
            select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                Document.kb_id == kb_id
            )
        )
    ).scalar() or 0
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

    from app.services.kb_lifecycle import live_reembed, start_reembed
    from app.services.kb_quota import quota_error

    current = await live_reembed(db, kb_id)
    if current is not None:
        return error(
            f"A re-embed of this collection is already {current.status}. "
            "Resume or cancel it first.",
            409,
        )
    refused = await quota_error(db, kb.tenant_id, add_embedding_usd=0.000001)
    if refused is not None:
        return refused
    job = await start_reembed(db, kb, body.embedding_model, user.id)
    job_id = job.id

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


async def _reembed_action(
    db: AsyncSession, kb_id: uuid.UUID, user: User, allowed: tuple[str, ...], act: Any
) -> Any:
    from app.services.kb_lifecycle import latest_reembed, serialize_reembed_job

    if not _is_admin(user):
        return error("Only admins can change a re-embed", 403)
    kb = await _reembed_kb_or_error(db, kb_id, user)
    if kb is None:
        return error("Knowledge base not found", 404)
    job = await latest_reembed(db, kb_id)
    if job is None:
        return error("This collection has no re-embed job", 404)
    if job.status not in allowed:
        return error(f"The re-embed is {job.status}, so this does not apply", 409)
    return success(serialize_reembed_job(await act(db, job)))


@router.post("/{kb_id}/reembed/pause")
async def pause_reembed(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    from app.services.kb_lifecycle import request_pause

    return await _reembed_action(db, kb_id, user, ("queued", "running"), request_pause)


@router.post("/{kb_id}/reembed/resume")
async def resume_reembed(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    from app.services.kb_lifecycle import request_resume

    return await _reembed_action(db, kb_id, user, ("paused", "failed"), request_resume)


@router.post("/{kb_id}/reembed/cancel")
async def cancel_reembed(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    from app.services.kb_lifecycle import request_cancel

    return await _reembed_action(
        db,
        kb_id,
        user,
        ("queued", "running", "pausing", "paused", "failed"),
        request_cancel,
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
                float(cfg.daily_budget_usd)
                if cfg.daily_budget_usd is not None
                else None
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
