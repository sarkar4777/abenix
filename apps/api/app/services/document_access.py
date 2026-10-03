"""Per-document ACL for the API.

The rule and its SQL live in engine.knowledge.document_acl so the API and the
agent runtime decide visibility the same way. A document with no grants is
open to everyone who can read its collection. One with grants is restricted
to its grantees, tenant admins, the collection creator and holders of WRITE or
ADMIN on the collection.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from engine.knowledge.document_acl import hidden_document_ids as _hidden
from models.document_grant import DocumentGrant
from models.user import User


async def hidden_document_ids(
    db: AsyncSession,
    user: User,
    kb_ids: list[uuid.UUID],
) -> set[uuid.UUID]:
    """Documents in these collections this user may not read."""
    ids = await _hidden(
        db,
        [str(k) for k in kb_ids],
        user_id=user.id,
        user_role=user.role,
    )
    return {uuid.UUID(i) for i in ids}


async def grant_document(
    db: AsyncSession,
    *,
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    subject_type: str,
    subject_id: uuid.UUID,
    permission: str,
    granted_by: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> DocumentGrant:
    grant = DocumentGrant(
        document_id=document_id,
        tenant_id=tenant_id,
        subject_type=subject_type,
        subject_id=subject_id,
        permission=permission,
        granted_by=granted_by,
        expires_at=expires_at,
    )
    db.add(grant)
    await db.commit()
    return grant


async def revoke_document(
    db: AsyncSession,
    document_id: uuid.UUID,
    subject_id: uuid.UUID,
) -> int:
    result = await db.execute(
        sa_delete(DocumentGrant).where(
            DocumentGrant.document_id == document_id,
            DocumentGrant.subject_id == subject_id,
        )
    )
    await db.commit()
    return result.rowcount or 0


__all__ = ["hidden_document_ids", "grant_document", "revoke_document"]
