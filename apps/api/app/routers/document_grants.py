"""Per-document grant CRUD. Lets a KB owner restrict specific documents to
specific users or agents without splitting the KB.

A document with no grants is visible to everyone who can read the KB. The
first grant restricts it to its grantees (plus tenant admins, the KB creator
and holders of WRITE or ADMIN on the KB). Knowledge search drops restricted
documents before ranking.

  GET    /api/knowledge/{kb_id}/documents/{doc_id}/grants
  POST   /api/knowledge/{kb_id}/documents/{doc_id}/grants
  DELETE /api/knowledge/{kb_id}/documents/{doc_id}/grants/{grant_id}
"""

from __future__ import annotations

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
from app.services.document_access import grant_document
from app.services.kb_access import (
    user_can_access_collection,
    user_can_edit_collection,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent
from models.document_grant import DocumentGrant
from models.knowledge_base import Document, KnowledgeBase
from models.user import User

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class GrantRequest(BaseModel):
    subject_type: str = Field(pattern=r"^(user|agent)$")
    subject_id: uuid.UUID
    permission: str = Field(default="read", pattern=r"^(read|write|admin)$")
    expires_at: datetime | None = None


async def _load(
    db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID, user: User
) -> tuple[KnowledgeBase | None, Document | None]:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if kb is None:
        return None, None
    doc = (
        await db.execute(
            select(Document).where(Document.id == doc_id, Document.kb_id == kb_id)
        )
    ).scalar_one_or_none()
    return kb, doc


async def _subject_in_tenant(
    db: AsyncSession, subject_type: str, subject_id: uuid.UUID, tenant_id: uuid.UUID
) -> bool:
    model = User if subject_type == "user" else Agent
    found = await db.execute(
        select(model.id).where(model.id == subject_id, model.tenant_id == tenant_id)
    )
    return found.scalar_one_or_none() is not None


def _grant_dict(g: DocumentGrant) -> dict[str, Any]:
    return {
        "id": str(g.id),
        "subject_type": g.subject_type,
        "subject_id": str(g.subject_id),
        "permission": g.permission,
        "granted_by": str(g.granted_by) if g.granted_by else None,
        "granted_at": g.granted_at.isoformat() if g.granted_at else None,
        "expires_at": g.expires_at.isoformat() if g.expires_at else None,
    }


@router.get("/{kb_id}/documents/{doc_id}/grants")
async def list_grants(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    kb, doc = await _load(db, kb_id, doc_id, user)
    if kb is None or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    if doc is None:
        return error("Document not found", 404)
    rows = await db.execute(
        select(DocumentGrant).where(
            DocumentGrant.document_id == doc_id,
            DocumentGrant.tenant_id == user.tenant_id,
        )
    )
    return success([_grant_dict(g) for g in rows.scalars().all()])


@router.post("/{kb_id}/documents/{doc_id}/grants")
async def create_grant(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    body: GrantRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    kb, doc = await _load(db, kb_id, doc_id, user)
    if kb is None or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    if doc is None:
        return error("Document not found", 404)
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return error(
            "Only people who can edit this collection can share documents", 403
        )
    if not await _subject_in_tenant(
        db, body.subject_type, body.subject_id, user.tenant_id
    ):
        return error(f"No {body.subject_type} with that id in this workspace", 400)
    expires_at = body.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return error("expires_at must be in the future", 400)
    existing = (
        await db.execute(
            select(DocumentGrant.id).where(
                DocumentGrant.document_id == doc_id,
                DocumentGrant.subject_type == body.subject_type,
                DocumentGrant.subject_id == body.subject_id,
                DocumentGrant.permission == body.permission,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return error("That grant already exists", 409)
    grant = await grant_document(
        db,
        document_id=doc_id,
        tenant_id=user.tenant_id,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        permission=body.permission,
        granted_by=user.id,
        expires_at=expires_at,
    )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "document.granted",
        {
            "document_id": str(doc_id),
            "subject_type": body.subject_type,
            "subject_id": str(body.subject_id),
            "permission": body.permission,
        },
        request,
    )
    await db.commit()
    return success(_grant_dict(grant), status_code=201)


@router.delete("/{kb_id}/documents/{doc_id}/grants/{grant_id}")
async def delete_grant(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    grant_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    kb, doc = await _load(db, kb_id, doc_id, user)
    if kb is None or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    if doc is None:
        return error("Document not found", 404)
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return error("Only people who can edit this collection can change sharing", 403)
    res = await db.execute(
        select(DocumentGrant).where(
            DocumentGrant.id == grant_id,
            DocumentGrant.document_id == doc_id,
            DocumentGrant.tenant_id == user.tenant_id,
        )
    )
    grant = res.scalar_one_or_none()
    if grant is None:
        return error("Grant not found", 404)
    await db.delete(grant)
    await db.commit()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "document.grant_revoked",
        {"document_id": str(doc_id), "grant_id": str(grant_id)},
        request,
    )
    await db.commit()
    return success({"deleted": True})


__all__ = ["router"]
