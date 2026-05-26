"""Per-document grant CRUD. Lets a KB owner share specific documents
with specific users, agents, teams, or roles without exposing the
whole KB.

  GET    /api/knowledge/{kb_id}/documents/{doc_id}/grants
  POST   /api/knowledge/{kb_id}/documents/{doc_id}/grants
  DELETE /api/knowledge/{kb_id}/documents/{doc_id}/grants/{grant_id}
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.services.document_access import (
    grant_document,
    invalidate_cache,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.document_grant import DocumentGrant
from models.knowledge_base import Document
from models.user import User

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class GrantRequest(BaseModel):
    subject_type: str = Field(pattern=r"^(user|agent|team|role)$")
    subject_id: uuid.UUID
    permission: str = Field(default="read", pattern=r"^(read|write|admin)$")
    expires_at: str | None = None


async def _verify_doc(
    db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID, user: User
) -> Document | None:
    res = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.kb_id == kb_id,
        )
    )
    return res.scalar_one_or_none()


@router.get("/{kb_id}/documents/{doc_id}/grants")
async def list_grants(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    doc = await _verify_doc(db, kb_id, doc_id, user)
    if doc is None:
        return error("Document not found", 404)
    rows = await db.execute(
        select(DocumentGrant).where(DocumentGrant.document_id == doc_id)
    )
    grants = rows.scalars().all()
    return success(
        [
            {
                "id": str(g.id),
                "subject_type": g.subject_type,
                "subject_id": str(g.subject_id),
                "permission": g.permission,
                "granted_by": str(g.granted_by) if g.granted_by else None,
                "granted_at": g.granted_at.isoformat() if g.granted_at else None,
                "expires_at": g.expires_at.isoformat() if g.expires_at else None,
            }
            for g in grants
        ]
    )


@router.post("/{kb_id}/documents/{doc_id}/grants")
async def create_grant(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    body: GrantRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    doc = await _verify_doc(db, kb_id, doc_id, user)
    if doc is None:
        return error("Document not found", 404)
    grant = await grant_document(
        db,
        document_id=doc_id,
        tenant_id=user.tenant_id,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        permission=body.permission,
        granted_by=user.id,
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
    return success(
        {
            "id": str(grant.id),
            "subject_type": grant.subject_type,
            "subject_id": str(grant.subject_id),
            "permission": grant.permission,
        },
        status_code=201,
    )


@router.delete("/{kb_id}/documents/{doc_id}/grants/{grant_id}")
async def delete_grant(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    grant_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
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
    subject_id = grant.subject_id
    await db.delete(grant)
    await db.commit()
    await invalidate_cache(subject_id)
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
