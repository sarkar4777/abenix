"""Knowledge base CRUD and document upload endpoints."""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.core.sanitize import sanitize_input
from app.schemas.knowledge import CreateKnowledgeBaseRequest, UpdateKnowledgeBaseRequest
from app.services import kb_ingest
from app.services.collection_access import grant_agent_collection
from app.services.kb_access import (
    _is_tenant_admin,
    accessible_collection_ids,
    user_can_access_collection,
    user_can_edit_collection,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.knowledge_base import Document, DocumentStatus, KBStatus, KnowledgeBase
from models.knowledge_project import CollectionVisibility, KnowledgeProject
from models.collection_grant import (
    CollectionPermission,
    UserCollectionGrant,
)
from models.agent import Agent  # noqa: E402
from models.user import User

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge"])

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "./data/uploads")
DOCUMENT_PAGE_DEFAULT = 100
DOCUMENT_PAGE_MAX = 1000


def _kb_rollups(kb: KnowledgeBase) -> tuple[int, int, int]:
    """Aggregate (chunks, size_bytes, degraded_doc_count) over the KB's docs.

    `degraded_doc_count` is what the UI uses to draw the yellow banner —
    any non-zero value means at least one document is indexed but not
    semantically searchable.
    """
    chunks = 0
    size = 0
    degraded = 0
    try:
        for d in kb.documents:
            chunks += d.chunk_count or 0
            size += d.file_size or 0
            doc_status = (
                d.status.value if isinstance(d.status, DocumentStatus) else d.status
            )
            if doc_status == DocumentStatus.DEGRADED.value:
                degraded += 1
    except Exception:
        pass
    return chunks, size, degraded


async def _rollups_sql(db: AsyncSession, kb_id: uuid.UUID) -> tuple[int, int, int]:
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Document.chunk_count), 0),
                func.coalesce(func.sum(Document.file_size), 0),
                func.count().filter(Document.status == DocumentStatus.DEGRADED),
            ).where(Document.kb_id == kb_id)
        )
    ).one()
    return int(row[0]), int(row[1]), int(row[2])


def _visible_documents(user: User, kb_id: uuid.UUID, include_history: bool) -> list:
    """Filters for the documents this user may list, the rule runs in the database."""
    from engine.knowledge.document_acl import RESTRICTED_PREDICATE, is_admin

    clauses: list = [Document.kb_id == kb_id]
    if not include_history:
        clauses.append(Document.is_current.is_(True))
    if not is_admin(user.role):
        clauses.append(
            text("NOT " + RESTRICTED_PREDICATE.format(doc="documents")).bindparams(
                uid=user.id, aid=None
            )
        )
    return clauses


async def _document_page(
    db: AsyncSession,
    user: User,
    kb_id: uuid.UUID,
    limit: int,
    offset: int,
    include_history: bool = False,
) -> tuple[list[Document], int, int]:
    """(page, how many this user can see, how many of them are hidden)."""
    clauses = _visible_documents(user, kb_id, include_history)
    total = await db.scalar(select(func.count()).select_from(Document).where(*clauses))
    everything = [Document.kb_id == kb_id]
    if not include_history:
        everything.append(Document.is_current.is_(True))
    existing = await db.scalar(
        select(func.count()).select_from(Document).where(*everything)
    )
    rows = await db.execute(
        select(Document)
        .where(*clauses)
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    )
    return (
        list(rows.scalars().all()),
        int(total or 0),
        int(existing or 0) - int(total or 0),
    )


async def _owner_names(db: AsyncSession, ids: set[Any]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.full_name, User.email).where(User.id.in_(wanted))
        )
    ).all()
    return {r[0]: (r[1] or r[2]) for r in rows}


def _owner_fields(
    kb: KnowledgeBase,
    user: User | None,
    names: dict[uuid.UUID, str] | None,
    can_edit: bool | None,
) -> dict[str, Any]:
    owner = kb.created_by
    ownership = None
    if user is not None:
        if owner is None:
            ownership = "platform"
        else:
            ownership = "mine" if owner == user.id else "shared"
    return {
        "owner_id": str(owner) if owner else None,
        "owner_name": (names or {}).get(owner) if owner else None,
        "ownership": ownership,
        "can_edit": can_edit,
        # share is owner or admin only
        "can_manage": bool(
            user is not None
            and ((owner is not None and owner == user.id) or user.role.value == "admin")
        ),
    }


async def _owner_context(
    db: AsyncSession, kb: KnowledgeBase, user: User
) -> dict[str, Any]:
    return {
        "user": user,
        "names": await _owner_names(db, {kb.created_by}),
        "can_edit": await user_can_edit_collection(db, user=user, kb=kb),
    }


def _serialize_kb(
    kb: KnowledgeBase,
    include_docs: bool = False,
    user: User | None = None,
    names: dict[uuid.UUID, str] | None = None,
    can_edit: bool | None = None,
    hidden_doc_ids: set[uuid.UUID] | None = None,
    rollups: tuple[int, int, int] | None = None,
    page: list[Document] | None = None,
) -> dict[str, Any]:
    chunk_count, total_size, degraded_doc_count = rollups or _kb_rollups(kb)
    docs: list[dict[str, Any]] = []
    if page is not None:
        docs = [_serialize_doc(d) for d in page]
    elif include_docs:
        hidden = hidden_doc_ids or set()
        try:
            docs = [
                _serialize_doc(d)
                for d in kb.documents
                if d.is_current is not False and d.id not in hidden
            ]
        except Exception:
            pass
    raw_status = kb.status.value if isinstance(kb.status, KBStatus) else kb.status
    # Belt-and-braces: even if the worker rollup missed the DEGRADED flip
    # (older worker version, race condition), the API answer is the
    # source of truth and must reflect what the user is actually seeing.
    if degraded_doc_count > 0 and raw_status == KBStatus.READY.value:
        raw_status = KBStatus.DEGRADED.value
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "embedding_model": kb.embedding_model,
        "chunk_size": kb.chunk_size,
        "chunk_overlap": kb.chunk_overlap,
        "status": raw_status,
        "doc_count": kb.doc_count,
        "chunk_count": chunk_count,
        "total_size": total_size,
        "degraded_doc_count": degraded_doc_count,
        "agent_id": str(kb.agent_id) if kb.agent_id else None,
        "project_id": str(kb.project_id) if kb.project_id else None,
        "default_visibility": (
            kb.default_visibility.value
            if hasattr(kb.default_visibility, "value")
            else kb.default_visibility
        ),
        "vector_backend": kb.vector_backend,
        **_scale_settings(kb),
        "created_by": str(kb.created_by) if kb.created_by else None,
        **_owner_fields(kb, user, names, can_edit),
        "documents": docs,
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
        "updated_at": kb.updated_at.isoformat() if kb.updated_at else None,
    }


def _scale_settings(kb: KnowledgeBase) -> dict[str, Any]:
    return {
        "search_language": getattr(kb, "search_language", None) or "simple",
        "rerank_mode": getattr(kb, "rerank_mode", None) or "auto",
        "index_mode": getattr(kb, "index_mode", None) or "shared",
    }


def _serialize_kb_summary(kb: KnowledgeBase) -> dict[str, Any]:
    full = _serialize_kb(kb, include_docs=False)
    full.pop("documents", None)
    return full


def _serialize_kb_summary_lite(
    kb: KnowledgeBase,
    user: User | None = None,
    names: dict[uuid.UUID, str] | None = None,
    can_edit: bool | None = None,
) -> dict[str, Any]:
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "embedding_model": kb.embedding_model,
        "chunk_size": kb.chunk_size,
        "chunk_overlap": kb.chunk_overlap,
        "status": kb.status.value if isinstance(kb.status, KBStatus) else kb.status,
        "doc_count": kb.doc_count,
        "chunk_count": 0,
        "total_size": 0,
        # Filled in by the list endpoint after the GROUP BY rollup.
        "degraded_doc_count": 0,
        "agent_id": str(kb.agent_id) if kb.agent_id else None,
        "project_id": str(kb.project_id) if kb.project_id else None,
        "default_visibility": (
            kb.default_visibility.value
            if hasattr(kb.default_visibility, "value")
            else kb.default_visibility
        ),
        "vector_backend": kb.vector_backend,
        **_scale_settings(kb),
        "created_by": str(kb.created_by) if kb.created_by else None,
        **_owner_fields(kb, user, names, can_edit),
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
        "updated_at": kb.updated_at.isoformat() if kb.updated_at else None,
    }


def _serialize_doc(d: Document) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "filename": d.filename,
        "file_type": d.file_type,
        "file_size": d.file_size,
        "chunk_count": d.chunk_count,
        "status": d.status.value if isinstance(d.status, DocumentStatus) else d.status,
        # Populated for FAILED + DEGRADED — UI tooltip on the yellow/red
        # icon. None for healthy docs.
        "error_message": getattr(d, "error_message", None),
        "content_sha256": getattr(d, "content_sha256", None),
        "ingest_checkpoint": getattr(d, "ingest_checkpoint", None) or 0,
        "version_number": getattr(d, "version_number", None) or 1,
        "is_current": getattr(d, "is_current", True) is not False,
        "parent_document_id": (
            str(d.parent_document_id)
            if getattr(d, "parent_document_id", None)
            else None
        ),
        "superseded_by": (
            str(d.superseded_by) if getattr(d, "superseded_by", None) else None
        ),
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.get("")
async def list_knowledge_bases(
    search: str = Query(
        "", max_length=255, description="Search by name or description"
    ),
    status: str = Query("", description="Filter by status"),
    sort: str = Query("newest", description="Sort: newest, oldest, name"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # User-level scoping â€” tenant admins see the whole tenant; everyone
    # else only sees collections whose visibility lets them in (tenant /
    # project-member / explicit grant).
    allowed_ids = await accessible_collection_ids(
        db,
        user=user,
        tenant_id=user.tenant_id,
    )

    query = select(KnowledgeBase).where(KnowledgeBase.tenant_id == user.tenant_id)
    if allowed_ids is not None:
        if not allowed_ids:
            return success([], meta={"total": 0, "limit": limit, "offset": offset})
        query = query.where(KnowledgeBase.id.in_(allowed_ids))

    if search:
        from sqlalchemy import or_

        query = query.where(
            or_(
                KnowledgeBase.name.ilike(f"%{search}%"),
                KnowledgeBase.description.ilike(f"%{search}%"),
            )
        )
    if status:
        query = query.where(KnowledgeBase.status == status)

    # Sort
    if sort == "oldest":
        query = query.order_by(KnowledgeBase.created_at.asc())
    elif sort == "name":
        query = query.order_by(KnowledgeBase.name.asc(), KnowledgeBase.id)
    else:  # newest (default)
        query = query.order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id)

    # Count total before pagination
    count_base = select(KnowledgeBase).where(KnowledgeBase.tenant_id == user.tenant_id)
    if allowed_ids is not None:
        count_base = count_base.where(KnowledgeBase.id.in_(allowed_ids))
    if search:
        from sqlalchemy import or_

        count_base = count_base.where(
            or_(
                KnowledgeBase.name.ilike(f"%{search}%"),
                KnowledgeBase.description.ilike(f"%{search}%"),
            )
        )
    if status:
        count_base = count_base.where(KnowledgeBase.status == status)
    count_query = select(func.count()).select_from(count_base.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    kbs = result.scalars().all()
    kb_ids = [kb.id for kb in kbs]
    rollups: dict[uuid.UUID, tuple[int, int]] = {}
    degraded_counts: dict[uuid.UUID, int] = {}
    if kb_ids:
        rollup_rows = (
            await db.execute(
                select(
                    Document.kb_id,
                    func.coalesce(func.sum(Document.chunk_count), 0),
                    func.coalesce(func.sum(Document.file_size), 0),
                )
                .where(Document.kb_id.in_(kb_ids))
                .group_by(Document.kb_id)
            )
        ).all()
        for cid, ck, sz in rollup_rows:
            rollups[cid] = (int(ck or 0), int(sz or 0))
        # Separate pass for degraded counts — cheaper than dragging a
        # CASE WHEN through the SUM rollup, and keeps the column list
        # honest if more statuses get surfaced later.
        degraded_rows = (
            await db.execute(
                select(Document.kb_id, func.count())
                .where(
                    Document.kb_id.in_(kb_ids),
                    Document.status == DocumentStatus.DEGRADED,
                )
                .group_by(Document.kb_id)
            )
        ).all()
        for cid, cnt in degraded_rows:
            degraded_counts[cid] = int(cnt or 0)
    names = await _owner_names(db, {kb.created_by for kb in kbs})
    admin = _is_tenant_admin(user)
    writable: set[uuid.UUID] = set()
    if kb_ids and not admin:
        grant_rows = (
            await db.execute(
                select(
                    UserCollectionGrant.collection_id, UserCollectionGrant.permission
                ).where(
                    UserCollectionGrant.collection_id.in_(kb_ids),
                    UserCollectionGrant.user_id == user.id,
                    UserCollectionGrant.live(),
                )
            )
        ).all()
        for cid, perm in grant_rows:
            pv = perm.value if hasattr(perm, "value") else str(perm)
            if pv.lower() in ("edit", "admin"):
                writable.add(cid)
    data = []
    for kb in kbs:
        can_edit = admin or kb.created_by == user.id or kb.id in writable
        d = _serialize_kb_summary_lite(kb, user, names, can_edit)
        ck, sz = rollups.get(kb.id, (0, 0))
        d["chunk_count"] = ck
        d["total_size"] = sz
        deg = degraded_counts.get(kb.id, 0)
        d["degraded_doc_count"] = deg
        # Mirror the same belt-and-braces rule the detail serializer
        # uses — never let a green "ready" leak out when there are
        # known degraded docs underneath.
        if deg > 0 and d["status"] == KBStatus.READY.value:
            d["status"] = KBStatus.DEGRADED.value
        data.append(d)
    return success(data, meta={"total": total, "limit": limit, "offset": offset})


async def _deferred_refusal(db: AsyncSession, kb: KnowledgeBase) -> str | None:
    """Why this collection can not bulk load with its index deferred, if it can not."""
    from chunks_store import STATE_SQL

    if (kb.vector_backend or "pgvector") != "pgvector":
        return "Deferring the index needs vector_backend pgvector."
    row = (await db.execute(text(STATE_SQL))).first()
    if row is None or not row[3]:
        return (
            "Rows here would still go through the shared index, so deferring saves "
            "nothing. Run scripts/kb-chunks-partition.py first."
        )
    if kb.id is not None:
        has_rows = await db.scalar(
            text("SELECT EXISTS (SELECT 1 FROM chunks WHERE collection_id = :id)"),
            {"id": kb.id},
        )
        if has_rows:
            return "The index can only be deferred while a collection is empty."
    return None


async def _ensure_default_project(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> KnowledgeProject:
    """Find-or-create the tenant's Default project."""
    p = (
        await db.execute(
            select(KnowledgeProject).where(
                KnowledgeProject.tenant_id == tenant_id,
                KnowledgeProject.slug == "default",
            )
        )
    ).scalar_one_or_none()
    if p is not None:
        return p
    p = KnowledgeProject(
        tenant_id=tenant_id,
        name="Default",
        slug="default",
        description="Auto-created container for collections that pre-date project assignment.",
        created_by=user_id,
    )
    db.add(p)
    await db.flush()
    return p


@router.post("")
async def create_knowledge_base(
    body: CreateKnowledgeBaseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    agent_uuid = None
    if body.agent_id:
        try:
            agent_uuid = uuid.UUID(body.agent_id)
        except ValueError:
            return error("Invalid agent_id", 400)
        if not (
            await db.execute(
                select(Agent).where(
                    Agent.id == agent_uuid, Agent.tenant_id == user.tenant_id
                )
            )
        ).scalar_one_or_none():
            return error("Agent not found", 404)

    # v2: collections live in a project. If the caller didn't supply
    # one, find-or-create the tenant's Default. Validate that any
    # supplied project belongs to this tenant.
    project_uuid: uuid.UUID
    if body.project_id:
        try:
            project_uuid = uuid.UUID(body.project_id)
        except ValueError:
            return error("Invalid project_id", 400)
        proj = await db.get(KnowledgeProject, project_uuid)
        if proj is None or proj.tenant_id != user.tenant_id:
            return error("Project not found", 404)
    else:
        proj = await _ensure_default_project(
            db,
            tenant_id=user.tenant_id,
            user_id=user.id,
        )
        project_uuid = proj.id

    visibility = (
        CollectionVisibility(body.default_visibility)
        if body.default_visibility
        else CollectionVisibility.PROJECT
    )

    kb = KnowledgeBase(
        tenant_id=user.tenant_id,
        project_id=project_uuid,
        default_visibility=visibility,
        created_by=user.id,
        name=sanitize_input(body.name),
        description=sanitize_input(body.description),
        agent_id=agent_uuid,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        # Default to pgvector â€” self-contained, scales with Postgres, no
        # external SaaS dependency or index-provisioning step. Callers
        # can still opt into Pinecone by passing vector_backend="pinecone".
        vector_backend=body.vector_backend or "pgvector",
        status=KBStatus.READY,
        doc_count=0,
        search_language=body.search_language or "simple",
        rerank_mode=body.rerank_mode or "auto",
    )
    if body.index_mode == "deferred":
        refused = await _deferred_refusal(db, kb)
        if refused:
            return error(refused, 409)
        kb.index_mode = "deferred"
    db.add(kb)
    await db.flush()

    # Auto-grant the creator ADMIN on their own collection so the share
    # query path (which reads grants) doesn't pretend they don't own it.
    db.add(
        UserCollectionGrant(
            user_id=user.id,
            collection_id=kb.id,
            permission=CollectionPermission.ADMIN,
            granted_by=user.id,
        )
    )
    # Binding an agent here used to set kb.agent_id and nothing else. The
    # runtime registers knowledge_search from the grant table only, so the
    # agent answered that it had no search tool. Write the grant too.
    if agent_uuid is not None:
        await grant_agent_collection(
            db,
            agent_id=agent_uuid,
            collection_id=kb.id,
            permission=CollectionPermission.READ,
            granted_by=user.id,
        )
    await db.commit()
    await db.refresh(kb)
    return success(
        _serialize_kb(kb, **(await _owner_context(db, kb, user))), status_code=201
    )


@router.get("/{kb_id}")
async def get_knowledge_base(
    kb_id: uuid.UUID,
    doc_limit: int = Query(DOCUMENT_PAGE_DEFAULT, ge=0, le=DOCUMENT_PAGE_MAX),
    doc_offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    page, total, hidden = await _document_page(db, user, kb_id, doc_limit, doc_offset)
    data = _serialize_kb(
        kb,
        rollups=await _rollups_sql(db, kb_id),
        page=page,
        **(await _owner_context(db, kb, user)),
    )
    data["documents_total"] = total
    data["documents_hidden"] = hidden
    return success(data)


@router.put("/{kb_id}")
async def update_knowledge_base(
    kb_id: uuid.UUID,
    body: UpdateKnowledgeBaseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return error("You don't have permission to edit this collection", 403)

    if body.name is not None:
        kb.name = sanitize_input(body.name)
    if body.description is not None:
        kb.description = sanitize_input(body.description)
    if body.agent_id is not None:
        try:
            kb.agent_id = uuid.UUID(body.agent_id)
        except ValueError:
            return error("Invalid agent_id", 400)
        if not (
            await db.execute(
                select(Agent).where(
                    Agent.id == kb.agent_id, Agent.tenant_id == user.tenant_id
                )
            )
        ).scalar_one_or_none():
            return error("Agent not found", 404)
        await grant_agent_collection(
            db,
            agent_id=kb.agent_id,
            collection_id=kb.id,
            permission=CollectionPermission.READ,
            granted_by=user.id,
        )

    if body.search_language is not None:
        kb.search_language = body.search_language
    if body.rerank_mode is not None:
        kb.rerank_mode = body.rerank_mode
    if body.index_mode is not None and body.index_mode != kb.index_mode:
        refused = await _deferred_refusal(db, kb)
        if refused:
            return error(refused, 409)
        kb.index_mode = "deferred"

    await db.commit()
    await db.refresh(kb)
    return success(
        _serialize_kb(
            kb,
            rollups=await _rollups_sql(db, kb_id),
            **(await _owner_context(db, kb, user)),
        )
    )


@router.get("/{kb_id}/dependents")
async def get_kb_dependents(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Agents granted this knowledge base and Atlas graphs bound to it."""
    from app.services.dependents import kb_dependents

    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    return success(await kb_dependents(db, user.tenant_id, kb_id))


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: uuid.UUID,
    force: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return error("You don't have permission to delete this collection", 403)

    from app.services.dependents import count, kb_dependents, release_kb
    from app.services.kb_lifecycle import tombstone_collection

    deps = await kb_dependents(db, user.tenant_id, kb_id)
    if count(deps) and not force:
        return error(
            f"{kb.name} is used by {count(deps)} agent(s) or Atlas graph(s). They lose these documents if it is deleted.",
            409,
            error_code="IN_USE",
            details={"dependents": deps},
        )
    await release_kb(db, user.tenant_id, kb_id)
    job = await tombstone_collection(db, kb, user.id)
    return success(
        {
            "id": str(kb_id),
            "deleted": True,
            "status": "deleting",
            "job_id": str(job.id),
        }
    )


@router.get("/{kb_id}/delete-status")
async def delete_status(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """The receipt of a delete, readable after the collection itself is gone."""
    from app.services.kb_lifecycle import serialize_delete_job
    from models.knowledge_ops import KBDeleteJob

    job = (
        await db.execute(
            select(KBDeleteJob)
            .where(
                KBDeleteJob.kb_id == kb_id,
                KBDeleteJob.tenant_id == user.tenant_id,
            )
            .order_by(KBDeleteJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        return error("No delete was asked for on this collection", 404)
    return success(serialize_delete_job(job))


@router.post("/{kb_id}/upload")
async def upload_document(
    kb_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return error("You don't have permission to upload to this collection", 403)

    outcome, status_code = await ingest_upload(db, kb, user, file)
    if "error" in outcome:
        return error(
            outcome["error"],
            status_code,
            error_code=outcome.get("code"),
            details=outcome.get("details"),
        )
    return success(outcome["document"], status_code=status_code)


async def ingest_upload(
    db: AsyncSession, kb: KnowledgeBase, user: User, file: UploadFile
) -> tuple[dict[str, Any], int]:
    """One file of a request, already spooled to disk by the parser, into the collection."""
    file_type = kb_ingest.file_type_for(file.content_type, file.filename)
    if not file_type:
        return {
            "error": f"Files of type {file.content_type} are not accepted. "
            f"Accepted types are {kb_ingest.ALLOWED_LABEL}"
        }, 400
    sha256, file_size = await kb_ingest.hash_spooled(file.file)
    problem = kb_ingest.size_error(file_size)
    if problem:
        return {"error": problem}, 400 if file_size == 0 else 413

    twin = await kb_ingest.existing_document(db, kb.id, sha256)
    if twin is not None:
        return await _answer_duplicate(db, kb, twin), 200

    from app.services.kb_quota import quota_error

    refused = await quota_error(
        db, user.tenant_id, add_documents=1, add_bytes=file_size
    )
    if refused is not None:
        body = json.loads(refused.body).get("error") or {}
        return {
            "error": body.get("message", "Quota exceeded"),
            "code": body.get("error_code"),
            "details": body.get("details"),
        }, refused.status_code

    doc_id = uuid.uuid4()
    storage_url = await kb_ingest.store_fileobj(
        user.tenant_id, kb.id, f"{doc_id}.{file_type}", file.file, file.content_type
    )
    doc, created = await kb_ingest.register_document(
        db,
        kb,
        doc_id=doc_id,
        filename=file.filename or f"{doc_id}.{file_type}",
        file_type=file_type,
        file_size=file_size,
        storage_url=storage_url,
        sha256=sha256,
        uploaded_by=user.id,
    )
    if not created:
        await _delete_file(storage_url)
        return await _answer_duplicate(db, kb, doc), 200
    await queue_document(db, kb, doc)
    await invalidate_search_cache(user.tenant_id)
    return {"document": {**_serialize_doc(doc), "duplicate": False}}, 201


async def _answer_duplicate(
    db: AsyncSession, kb: KnowledgeBase, doc: Document
) -> dict[str, Any]:
    if kb_ingest.can_resume(doc):
        await kb_ingest.resume_failed(db, kb, doc)
        await queue_document(db, kb, doc)
        return {
            "document": {**_serialize_doc(doc), "duplicate": False, "resumed": True}
        }
    return {"document": {**_serialize_doc(doc), "duplicate": True}}


async def queue_document(
    db: AsyncSession, kb: KnowledgeBase, doc: Document, verify_content: bool = False
) -> None:
    """A document nothing will ever process must not sit in PROCESSING forever."""
    queued = _dispatch_processing(
        doc_id=str(doc.id),
        kb_id=str(kb.id),
        file_path=doc.storage_url,
        filename=doc.filename,
        file_type=doc.file_type,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
        verify_content=verify_content,
    )
    if queued is False:
        doc.status = DocumentStatus.FAILED
        doc.error_message = (
            "The ingest queue could not be reached. Upload the file again to retry."
        )
        await db.commit()
        await db.refresh(doc)


async def invalidate_search_cache(tenant_id: uuid.UUID) -> None:
    # a new doc could change top results within the 5 minute cache window
    try:
        from app.services.kb_cache import invalidate_tenant_search_cache

        await invalidate_tenant_search_cache(str(tenant_id))
    except Exception:
        pass


@router.get("/{kb_id}/documents")
async def list_documents(
    kb_id: uuid.UUID,
    include_history: bool = False,
    limit: int = Query(DOCUMENT_PAGE_DEFAULT, ge=1, le=DOCUMENT_PAGE_MAX),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = kb_result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)

    # superseded versions stay out of the list, editors can ask for history
    if include_history and not await user_can_edit_collection(db, user=user, kb=kb):
        return error("Only people who can edit this collection can view history", 403)
    page, total, hidden = await _document_page(
        db, user, kb_id, limit, offset, include_history
    )
    data = [_serialize_doc(d) for d in page]
    return success(
        data,
        meta={
            "count": len(data),
            "total": total,
            "hidden": hidden,
            "limit": limit,
            "offset": offset,
        },
    )


@router.delete("/{kb_id}/documents/{doc_id}")
async def delete_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = kb_result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return error(
            "You don't have permission to delete documents in this collection", 403
        )

    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.kb_id == kb_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return error("Document not found", 404)

    await _delete_file(doc.storage_url)
    from models.knowledge_ops import KBReembedJob

    targets = (
        (
            await db.execute(
                select(KBReembedJob.target_generation).where(
                    KBReembedJob.kb_id == kb_id, KBReembedJob.finished_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    # a running re-embed staged it too, and that namespace is about to go live
    for generation in {kb.embedding_generation or 0, *targets}:
        _delete_pinecone_vectors(
            str(kb_id), str(doc_id), doc.chunk_count or 0, generation=generation
        )

    await db.delete(doc)

    kb.doc_count = (
        await db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.kb_id == kb_id, Document.id != doc_id)
        )
        or 0
    )

    await db.commit()

    return success({"id": str(doc_id), "deleted": True})


def _dispatch_processing(
    doc_id: str,
    kb_id: str,
    file_path: str,
    filename: str,
    file_type: str,
    chunk_size: int,
    chunk_overlap: int,
    verify_content: bool = False,
) -> bool:
    try:
        from celery import Celery

        broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
        app = Celery(broker=broker_url)
        app.send_task(
            "worker.tasks.document_processor.process_document",
            args=[
                doc_id,
                kb_id,
                file_path,
                filename,
                file_type,
                chunk_size,
                chunk_overlap,
            ],
            kwargs={"verify_content": True} if verify_content else {},
            queue="documents",
        )
        return True
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "Celery not available, document %s will need manual processing", doc_id
        )
        return False


async def _delete_file(storage_url: str) -> None:
    """Handles plain paths and file://, s3:// and az:// URIs, a failure leaves the row to go."""
    if not storage_url or storage_url.startswith("agent://"):
        return
    try:
        from engine.storage import get_storage

        await get_storage().delete(storage_url)
    except Exception:
        logging.getLogger(__name__).warning(
            "could not delete stored file %s", storage_url, exc_info=True
        )


def _delete_pinecone_vectors(
    kb_id: str, doc_id: str, chunk_count: int = 0, generation: int = 0
) -> None:
    from engine.knowledge.kb_state import pinecone_namespace

    namespace = pinecone_namespace(kb_id, generation)
    api_key = os.environ.get("PINECONE_API_KEY", "")
    index_name = os.environ.get("PINECONE_INDEX_NAME", "agentforge-knowledge")
    if not api_key:
        return
    try:
        from pinecone import Pinecone

        pc = Pinecone(api_key=api_key)
        index = pc.Index(index_name)
    except Exception:
        return
    # serverless indexes refuse delete-by-filter, ids work everywhere
    ids = [f"{doc_id}_{i}" for i in range(chunk_count)]
    try:
        for page in index.list(prefix=f"{doc_id}_", namespace=namespace):
            ids.extend(page if isinstance(page, (list, tuple)) else [page])
    except Exception:
        pass
    ids = sorted(set(ids))
    try:
        for i in range(0, len(ids), 1000):
            index.delete(ids=ids[i : i + 1000], namespace=namespace)
        if not ids:
            index.delete(filter={"doc_id": {"$eq": doc_id}}, namespace=namespace)
    except Exception:
        pass
