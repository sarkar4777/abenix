"""Large and bulk uploads, and the build mode vector index for a bulk loaded collection."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.routers.knowledge import (
    _answer_duplicate,
    _delete_file,
    _deferred_refusal,
    _serialize_doc,
    ingest_upload,
    invalidate_search_cache,
    queue_document,
)
from app.services import kb_ingest
from app.services.kb_access import user_can_access_collection, user_can_edit_collection

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.knowledge_base import KnowledgeBase
from models.user import User

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge"])


class UploadFilePlan(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    size: int = Field(gt=0)
    content_type: str | None = None
    sha256: str | None = None


class StartUploads(BaseModel):
    files: list[UploadFilePlan] = Field(min_length=1, max_length=500)


class CompleteUpload(BaseModel):
    parts: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)


async def _writable_kb(
    db: AsyncSession, user: User, kb_id: uuid.UUID
) -> tuple[KnowledgeBase | None, JSONResponse | None]:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return None, error("Knowledge base not found", 404)
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return None, error(
            "You don't have permission to upload to this collection", 403
        )
    return kb, None


@router.post("/{kb_id}/upload-bulk")
async def upload_bulk(
    kb_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Many files in one request, each with its own answer so one bad file costs only itself."""
    kb, refused = await _writable_kb(db, user, kb_id)
    if refused:
        return refused
    if len(files) > kb_ingest.bulk_max_files():
        return error(
            f"Too many files. Send at most {kb_ingest.bulk_max_files()} in one "
            "request, or use POST uploads for a large batch.",
            400,
        )
    results: list[dict[str, Any]] = []
    for file in files:
        try:
            outcome, code = await ingest_upload(db, kb, user, file)
        except Exception as exc:
            await db.rollback()
            outcome, code = {"error": f"Could not store this file. {exc}"[:300]}, 500
        if "error" in outcome:
            results.append(
                {"filename": file.filename, "status": code, "error": outcome["error"]}
            )
        else:
            results.append(
                {
                    "filename": file.filename,
                    "status": code,
                    "document": outcome["document"],
                }
            )
    return success(
        results,
        meta={
            "total": len(results),
            "created": sum(1 for r in results if r["status"] == 201),
            "duplicates": sum(1 for r in results if r["status"] == 200),
            "failed": sum(1 for r in results if r["status"] >= 400),
        },
    )


@router.post("/{kb_id}/uploads")
async def start_uploads(
    kb_id: uuid.UUID,
    body: StartUploads,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """A plan per file, straight to object storage when it can, a raw stream through here if not."""
    kb, refused = await _writable_kb(db, user, kb_id)
    if refused:
        return refused
    storage = kb_ingest._storage()
    plans: list[dict[str, Any]] = []
    for item in body.files:
        file_type = kb_ingest.file_type_for(item.content_type, item.filename)
        problem = kb_ingest.size_error(item.size)
        if not file_type:
            problem = f"Accepted types are {kb_ingest.ALLOWED_LABEL}"
        sha256 = kb_ingest.clean_sha256(item.sha256)
        if item.sha256 and not sha256:
            problem = "sha256 must be 64 hex characters"
        if problem:
            plans.append(
                {"filename": item.filename, "mode": "rejected", "error": problem}
            )
            continue
        if sha256:
            twin = await kb_ingest.existing_document(db, kb.id, sha256)
            if twin is not None:
                document = (await _answer_duplicate(db, kb, twin))["document"]
                plans.append(
                    {
                        "filename": item.filename,
                        "mode": "resumed" if document.get("resumed") else "duplicate",
                        "document": document,
                    }
                )
                continue
        from app.services.kb_quota import quota_error

        over = await quota_error(
            db, user.tenant_id, add_documents=1, add_bytes=item.size
        )
        if over is not None:
            return over
        doc_id = uuid.uuid4()
        claims: dict[str, Any] = {
            "tenant": str(user.tenant_id),
            "kb": str(kb_id),
            "doc": str(doc_id),
            "filename": item.filename,
            "type": file_type,
            "size": item.size,
            "sha256": sha256,
            "content_type": item.content_type,
        }
        direct = (
            storage.supports_direct_upload()
            and item.size >= kb_ingest.direct_upload_min_bytes()
        )
        if direct:
            plan = await storage.start_direct_upload(
                str(user.tenant_id),
                f"kb/{kb_id}/{doc_id}.{file_type}",
                item.size,
                item.content_type or "application/octet-stream",
            )
            public = {k: v for k, v in plan.items() if k != "upload_id"}
            claims["plan"] = {k: plan[k] for k in ("kind", "uri")}
            if "upload_id" in plan:
                claims["plan"]["upload_id"] = plan["upload_id"]
            token = kb_ingest.sign_upload(claims)
            plans.append(
                {
                    "filename": item.filename,
                    "mode": "direct",
                    "upload": public,
                    "complete_url": f"/api/knowledge-bases/{kb_id}/uploads/{token}/complete",
                    "abort_url": f"/api/knowledge-bases/{kb_id}/uploads/{token}",
                }
            )
        else:
            token = kb_ingest.sign_upload(claims)
            plans.append(
                {
                    "filename": item.filename,
                    "mode": "stream",
                    "method": "PUT",
                    "url": f"/api/knowledge-bases/{kb_id}/uploads/{token}/content",
                }
            )
    return success(plans)


def _claims_for(token: str, user: User, kb_id: uuid.UUID) -> dict[str, Any] | None:
    claims = kb_ingest.read_upload(token)
    if not claims:
        return None
    if claims.get("tenant") != str(user.tenant_id) or claims.get("kb") != str(kb_id):
        return None
    return claims


@router.put("/{kb_id}/uploads/{token}/content")
async def stream_upload(
    kb_id: uuid.UUID,
    token: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """The body goes straight to storage, nothing of it stays in memory or on the API's disk."""
    claims = _claims_for(token, user, kb_id)
    if not claims:
        return error(
            "This upload link is not valid any more. Start the upload again.", 400
        )
    kb, refused = await _writable_kb(db, user, kb_id)
    if refused:
        return refused
    doc_id = uuid.UUID(claims["doc"])
    file_type = claims["type"]
    # release the connection, a slow upload must not hold one from the pool
    await db.commit()
    body = kb_ingest.HashingStream(request.stream(), kb_ingest.max_upload_bytes())
    storage = kb_ingest._storage()
    try:
        storage_url = await storage.upload_stream(
            str(user.tenant_id),
            f"kb/{kb_id}/{doc_id}.{file_type}",
            body.chunks(),
            claims.get("content_type") or "application/octet-stream",
        )
    except kb_ingest.TooLarge:
        return error(kb_ingest.size_error(body.size) or "File too large", 413)
    except ClientDisconnect:
        return error("The upload was cut off. Nothing was stored.", 400)
    sha256 = body.digest.hexdigest()
    problem = None
    if body.size != claims["size"]:
        problem = f"Expected {claims['size']} bytes and received {body.size}."
    elif claims.get("sha256") and claims["sha256"] != sha256:
        problem = f"The file has hash {sha256}, not the declared {claims['sha256']}."
    if problem:
        await _delete_file(storage_url)
        return error(problem, 400)
    return await _finish(db, kb, user, claims, storage_url, sha256)


@router.post("/{kb_id}/uploads/{token}/complete")
async def complete_upload(
    kb_id: uuid.UUID,
    token: str,
    body: CompleteUpload,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    claims = _claims_for(token, user, kb_id)
    if not claims or not claims.get("plan"):
        return error(
            "This upload link is not valid any more. Start the upload again.", 400
        )
    kb, refused = await _writable_kb(db, user, kb_id)
    if refused:
        return refused
    storage = kb_ingest._storage()
    plan = claims["plan"]
    try:
        uri = await storage.finish_direct_upload(plan, body.parts)
        size = await storage.size_of(uri)
    except Exception as exc:
        return error(f"Object storage refused the upload. {exc}"[:300], 400)
    if size != claims["size"]:
        await _delete_file(uri)
        return error(f"Expected {claims['size']} bytes and storage holds {size}.", 400)
    # the worker hashes it, this process never saw the bytes
    return await _finish(db, kb, user, claims, uri, claims.get("sha256"), verify=True)


@router.delete("/{kb_id}/uploads/{token}")
async def abort_upload(
    kb_id: uuid.UUID,
    token: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    claims = _claims_for(token, user, kb_id)
    if not claims or not claims.get("plan"):
        return error("This upload link is not valid any more.", 400)
    _kb, refused = await _writable_kb(db, user, kb_id)
    if refused:
        return refused
    await kb_ingest._storage().abort_direct_upload(claims["plan"])
    return success({"aborted": True})


async def _finish(
    db: AsyncSession,
    kb: KnowledgeBase,
    user: User,
    claims: dict[str, Any],
    storage_url: str,
    sha256: str | None,
    verify: bool = False,
) -> JSONResponse:
    if sha256:
        twin = await kb_ingest.existing_document(db, kb.id, sha256)
        if twin is not None and str(twin.id) != claims["doc"]:
            await _delete_file(storage_url)
            answer = await _answer_duplicate(db, kb, twin)
            return success(answer["document"], status_code=200)
    doc, created = await kb_ingest.register_document(
        db,
        kb,
        doc_id=uuid.UUID(claims["doc"]),
        filename=claims["filename"],
        file_type=claims["type"],
        file_size=claims["size"],
        storage_url=storage_url,
        sha256=sha256,
        uploaded_by=user.id,
    )
    if not created:
        await _delete_file(storage_url)
        return success({**_serialize_doc(doc), "duplicate": True}, status_code=200)
    await queue_document(db, kb, doc, verify_content=verify)
    await invalidate_search_cache(user.tenant_id)
    return success({**_serialize_doc(doc), "duplicate": False}, status_code=201)


@router.post("/{kb_id}/index/build")
async def build_index(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Build the vector index a bulk load deferred. Search keeps working, exact, meanwhile."""
    kb, refused = await _writable_kb(db, user, kb_id)
    if refused:
        return refused
    if kb.index_mode not in ("deferred", "building"):
        return error(
            f"This collection's index mode is {kb.index_mode}, nothing to build.", 409
        )
    kb.index_mode = "building"
    await db.commit()
    from celery import Celery

    broker = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
    Celery(broker=broker).send_task(
        "worker.tasks.kb_index.build", args=[str(kb_id)], queue="documents"
    )
    return success({"id": str(kb_id), "index_mode": "building"}, status_code=202)


@router.get("/{kb_id}/index")
async def index_state(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    from chunks_store import STATE_SQL

    row = (await db.execute(text(STATE_SQL))).first()
    return success(
        {
            "id": str(kb_id),
            "index_mode": kb.index_mode,
            "can_defer": (await _deferred_refusal(db, kb)) is None,
            "partitioned": bool(row and row[0] == "p"),
            "storage": row[1] if row else None,
            "pgvector": row[2] if row else None,
        }
    )
