"""Knowledge base CRUD and document upload endpoints."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.core.sanitize import sanitize_input
from app.schemas.knowledge import CreateKnowledgeBaseRequest, UpdateKnowledgeBaseRequest
from app.services.kb_access import (
    accessible_collection_ids,
    user_can_access_collection,
    user_can_edit_collection,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.knowledge_base import Document, DocumentStatus, KBStatus, KnowledgeBase
from models.knowledge_project import CollectionVisibility, KnowledgeProject
from models.collection_grant import (
    CollectionPermission, UserCollectionGrant,
)
from models.user import User

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge"])

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "./data/uploads")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/csv": "csv",
    "text/markdown": "md",
    "application/json": "json",
}


def _serialize_kb(kb: KnowledgeBase, include_docs: bool = False) -> dict[str, Any]:
    docs = []
    if include_docs:
        try:
            docs = [_serialize_doc(d) for d in kb.documents]
        except Exception:
            pass
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "embedding_model": kb.embedding_model,
        "chunk_size": kb.chunk_size,
        "chunk_overlap": kb.chunk_overlap,
        "status": kb.status.value if isinstance(kb.status, KBStatus) else kb.status,
        "doc_count": kb.doc_count,
        "agent_id": str(kb.agent_id) if kb.agent_id else None,
        # v2 surface
        "project_id": str(kb.project_id) if kb.project_id else None,
        "default_visibility": (
            kb.default_visibility.value
            if hasattr(kb.default_visibility, "value")
            else kb.default_visibility
        ),
        "vector_backend": kb.vector_backend,
        "created_by": str(kb.created_by) if kb.created_by else None,
        "documents": docs,
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
        "updated_at": kb.updated_at.isoformat() if kb.updated_at else None,
    }


def _serialize_kb_summary(kb: KnowledgeBase) -> dict[str, Any]:
    total_chunks = 0
    total_size = 0
    try:
        for d in kb.documents:
            total_chunks += d.chunk_count or 0
            total_size += d.file_size or 0
    except Exception:
        pass

    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "status": kb.status.value if isinstance(kb.status, KBStatus) else kb.status,
        "doc_count": kb.doc_count,
        "chunk_count": total_chunks,
        "total_size": total_size,
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
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.get("")
async def list_knowledge_bases(
    search: str = Query("", max_length=255, description="Search by name or description"),
    status: str = Query("", description="Filter by status"),
    sort: str = Query("newest", description="Sort: newest, oldest, name"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # User-level scoping — tenant admins see the whole tenant; everyone
    # else only sees collections whose visibility lets them in (tenant /
    # project-member / explicit grant).
    allowed_ids = await accessible_collection_ids(
        db, user=user, tenant_id=user.tenant_id,
    )

    query = (
        select(KnowledgeBase)
        .options(selectinload(KnowledgeBase.documents))
        .where(KnowledgeBase.tenant_id == user.tenant_id)
    )
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
        query = query.order_by(KnowledgeBase.name.asc())
    else:  # newest (default)
        query = query.order_by(KnowledgeBase.created_at.desc())

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
    data = [_serialize_kb_summary(kb) for kb in kbs]
    return success(data, meta={"total": total, "limit": limit, "offset": offset})


async def _ensure_default_project(
    db: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID,
) -> KnowledgeProject:
    """Find-or-create the tenant's Default project."""
    p = (await db.execute(
        select(KnowledgeProject).where(
            KnowledgeProject.tenant_id == tenant_id,
            KnowledgeProject.slug == "default",
        )
    )).scalar_one_or_none()
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
            db, tenant_id=user.tenant_id, user_id=user.id,
        )
        project_uuid = proj.id

    visibility = (
        CollectionVisibility(body.default_visibility)
        if body.default_visibility else CollectionVisibility.PROJECT
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
        # Default to pgvector — self-contained, scales with Postgres, no
        # external SaaS dependency or index-provisioning step. Callers
        # can still opt into Pinecone by passing vector_backend="pinecone".
        vector_backend=body.vector_backend or "pgvector",
        status=KBStatus.READY,
        doc_count=0,
    )
    db.add(kb)
    await db.flush()

    # Auto-grant the creator ADMIN on their own collection so the share
    # query path (which reads grants) doesn't pretend they don't own it.
    db.add(UserCollectionGrant(
        user_id=user.id,
        collection_id=kb.id,
        permission=CollectionPermission.ADMIN,
        granted_by=user.id,
    ))
    await db.commit()
    await db.refresh(kb)
    return success(_serialize_kb(kb), status_code=201)


@router.get("/{kb_id}")
async def get_knowledge_base(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(KnowledgeBase)
        .options(selectinload(KnowledgeBase.documents))
        .where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    return success(_serialize_kb(kb, include_docs=True))


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

    await db.commit()
    await db.refresh(kb)
    return success(_serialize_kb(kb))


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(KnowledgeBase)
        .options(selectinload(KnowledgeBase.documents))
        .where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return error("You don't have permission to delete this collection", 403)

    for doc in kb.documents:
        _delete_file(doc.storage_url)
        await db.delete(doc)

    _delete_pinecone_namespace(str(kb_id))

    await db.delete(kb)
    await db.commit()
    return success({"id": str(kb_id), "deleted": True})


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

    content_type = file.content_type or ""
    file_ext = ALLOWED_TYPES.get(content_type)
    if not file_ext:
        filename = file.filename or ""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in ("pdf", "docx", "txt", "csv", "md", "json"):
            file_ext = ext
        else:
            return error(
                f"Unsupported file type: {content_type}. Allowed: PDF, DOCX, TXT, CSV, MD, JSON",
                400,
            )

    content = await file.read()
    file_size = len(content)

    if file_size > MAX_FILE_SIZE:
        return error(f"File too large. Max size: {MAX_FILE_SIZE // (1024*1024)} MB", 400)

    if file_size == 0:
        return error("Empty file", 400)

    doc_id = uuid.uuid4()
    safe_filename = f"{doc_id}.{file_ext}"

    # Store via StorageService (S3 in K8s, local filesystem in dev)
    storage_url = ""
    try:
        from engine.storage import get_storage
        storage = get_storage()
        storage_url = await storage.upload(
            tenant_id=str(user.tenant_id),
            path=f"kb/{kb_id}/{safe_filename}",
            data=content,
            content_type=file.content_type or "application/octet-stream",
        )
    except ImportError:
        # Fallback to direct filesystem if storage module not available
        upload_dir = Path(UPLOAD_DIR) / str(user.tenant_id) / str(kb_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / safe_filename
        file_path.write_bytes(content)
        storage_url = str(file_path)

    doc = Document(
        id=doc_id,
        kb_id=kb_id,
        filename=file.filename or safe_filename,
        file_type=file_ext,
        file_size=file_size,
        chunk_count=0,
        status=DocumentStatus.PROCESSING,
        storage_url=storage_url,
    )
    db.add(doc)

    kb.status = KBStatus.PROCESSING
    await db.commit()
    await db.refresh(doc)

    _dispatch_processing(
        doc_id=str(doc_id),
        kb_id=str(kb_id),
        file_path=storage_url,
        filename=file.filename or safe_filename,
        file_type=file_ext,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
    )

    # KB v2: invalidate the search cache for this tenant — a new doc
    # could change top results within the 5-min cache window. Cheap
    # SCAN + DEL; failure is silent (cache layer is best-effort).
    try:
        from app.services.kb_cache import invalidate_tenant_search_cache
        await invalidate_tenant_search_cache(str(user.tenant_id))
    except Exception:
        pass

    return success(_serialize_doc(doc), status_code=201)


@router.get("/{kb_id}/documents")
async def list_documents(
    kb_id: uuid.UUID,
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

    result = await db.execute(
        select(Document)
        .where(Document.kb_id == kb_id)
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    data = [_serialize_doc(d) for d in docs]
    return success(data, meta={"count": len(data)})


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
        return error("You don't have permission to delete documents in this collection", 403)

    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.kb_id == kb_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return error("Document not found", 404)

    _delete_file(doc.storage_url)
    _delete_pinecone_vectors(str(kb_id), str(doc_id))

    await db.delete(doc)

    remaining = await db.execute(
        select(Document).where(Document.kb_id == kb_id, Document.id != doc_id)
    )
    remaining_count = len(remaining.scalars().all())
    kb.doc_count = remaining_count

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
) -> None:
    try:
        from celery import Celery

        broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
        app = Celery(broker=broker_url)
        app.send_task(
            "worker.tasks.document_processor.process_document",
            args=[doc_id, kb_id, file_path, filename, file_type, chunk_size, chunk_overlap],
            queue="documents",
        )
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Celery not available, document %s will need manual processing", doc_id
        )


def _delete_file(storage_url: str) -> None:
    try:
        path = Path(storage_url)
        if path.exists():
            path.unlink()
    except Exception:
        pass


def _delete_pinecone_vectors(kb_id: str, doc_id: str) -> None:
    api_key = os.environ.get("PINECONE_API_KEY", "")
    index_name = os.environ.get("PINECONE_INDEX_NAME", "abenix-knowledge")
    if not api_key:
        return
    try:
        from pinecone import Pinecone

        pc = Pinecone(api_key=api_key)
        index = pc.Index(index_name)
        index.delete(
            filter={"doc_id": {"$eq": doc_id}},
            namespace=kb_id,
        )
    except Exception:
        pass


def _delete_pinecone_namespace(kb_id: str) -> None:
    api_key = os.environ.get("PINECONE_API_KEY", "")
    index_name = os.environ.get("PINECONE_INDEX_NAME", "abenix-knowledge")
    if not api_key:
        return
    try:
        from pinecone import Pinecone

        pc = Pinecone(api_key=api_key)
        index = pc.Index(index_name)
        index.delete(delete_all=True, namespace=kb_id)
    except Exception:
        pass
