"""Manage agent + user grants on a collection (a.k.a. KnowledgeBase row)."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.permissions import is_admin
from app.core.responses import error, success
from app.services.collection_access import assert_collection_access

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent  # noqa: E402
from models.collection_grant import (  # noqa: E402
    AgentCollectionGrant,
    CollectionPermission,
    UserCollectionGrant,
)
from models.knowledge_base import KnowledgeBase  # noqa: E402
from models.user import User  # noqa: E402

router = APIRouter(
    prefix="/api/knowledge-collections", tags=["knowledge-grants"],
)


class GrantAgentRequest(BaseModel):
    agent_id: uuid.UUID
    permission: CollectionPermission = Field(default=CollectionPermission.READ)


class GrantUserRequest(BaseModel):
    user_id: uuid.UUID
    permission: CollectionPermission = Field(default=CollectionPermission.READ)


async def _require_admin_on(
    db: AsyncSession, *, user: User, collection_id: uuid.UUID,
) -> KnowledgeBase | None:
    """Return the collection if user has ADMIN on it; else None."""
    kb = await db.get(KnowledgeBase, collection_id)
    if kb is None or kb.tenant_id != user.tenant_id:
        return None
    if is_admin(user) or kb.created_by == user.id:
        return kb
    ok = await assert_collection_access(
        db,
        user_id=user.id,
        tenant_id=user.tenant_id,
        collection_id=collection_id,
        minimum_permission=CollectionPermission.ADMIN,
    )
    return kb if ok else None


def _serialize_agent_grant(g: AgentCollectionGrant) -> dict[str, Any]:
    return {
        "id": str(g.id),
        "agent_id": str(g.agent_id),
        "collection_id": str(g.collection_id),
        "permission": g.permission.value if hasattr(g.permission, "value") else g.permission,
        "granted_by": str(g.granted_by) if g.granted_by else None,
        "granted_at": g.granted_at.isoformat() if g.granted_at else None,
    }


def _serialize_user_grant(g: UserCollectionGrant) -> dict[str, Any]:
    return {
        "id": str(g.id),
        "user_id": str(g.user_id),
        "collection_id": str(g.collection_id),
        "permission": g.permission.value if hasattr(g.permission, "value") else g.permission,
        "granted_by": str(g.granted_by) if g.granted_by else None,
        "granted_at": g.granted_at.isoformat() if g.granted_at else None,
        "expires_at": g.expires_at.isoformat() if g.expires_at else None,
    }


@router.get("/{collection_id}/agents")
async def list_agent_grants(
    collection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    kb = await db.get(KnowledgeBase, collection_id)
    if kb is None or kb.tenant_id != user.tenant_id:
        return error("Collection not found", 404)
    rows = (await db.execute(
        select(AgentCollectionGrant).where(
            AgentCollectionGrant.collection_id == collection_id,
        )
    )).scalars().all()
    return success([_serialize_agent_grant(g) for g in rows])


@router.post("/{collection_id}/agents")
async def grant_agent(
    collection_id: uuid.UUID,
    body: GrantAgentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    kb = await _require_admin_on(db, user=user, collection_id=collection_id)
    if kb is None:
        return error("Forbidden", 403)

    # The agent must live in the same tenant. Cross-tenant grants are
    # never allowed; the boundary is non-negotiable.
    agent = await db.get(Agent, body.agent_id)
    if agent is None or agent.tenant_id != user.tenant_id:
        return error("Agent not found in this tenant", 404)

    # Upsert: if a grant already exists, UPDATE its permission rather
    # than 409. The UI's natural action is "set permission to X" not
    # "create grant"; idempotent upsert matches that.
    existing = await db.execute(
        select(AgentCollectionGrant).where(
            AgentCollectionGrant.agent_id == body.agent_id,
            AgentCollectionGrant.collection_id == collection_id,
        )
    )
    grant = existing.scalar_one_or_none()
    if grant is None:
        grant = AgentCollectionGrant(
            agent_id=body.agent_id,
            collection_id=collection_id,
            permission=body.permission,
            granted_by=user.id,
        )
        db.add(grant)
    else:
        grant.permission = body.permission
        grant.granted_by = user.id

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return error("Failed to grant — concurrent write", 409)
    await db.refresh(grant)
    return success(_serialize_agent_grant(grant), status_code=201)


@router.delete("/{collection_id}/agents/{agent_id}")
async def revoke_agent(
    collection_id: uuid.UUID,
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    kb = await _require_admin_on(db, user=user, collection_id=collection_id)
    if kb is None:
        return error("Forbidden", 403)

    grant = (await db.execute(
        select(AgentCollectionGrant).where(
            AgentCollectionGrant.agent_id == agent_id,
            AgentCollectionGrant.collection_id == collection_id,
        )
    )).scalar_one_or_none()
    if grant is None:
        return error("Grant not found", 404)
    await db.delete(grant)
    await db.commit()
    return success({"revoked": True})


@router.get("/{collection_id}/users")
async def list_user_grants(
    collection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    kb = await db.get(KnowledgeBase, collection_id)
    if kb is None or kb.tenant_id != user.tenant_id:
        return error("Collection not found", 404)
    rows = (await db.execute(
        select(UserCollectionGrant).where(
            UserCollectionGrant.collection_id == collection_id,
        )
    )).scalars().all()
    return success([_serialize_user_grant(g) for g in rows])


@router.post("/{collection_id}/users")
async def grant_user(
    collection_id: uuid.UUID,
    body: GrantUserRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    kb = await _require_admin_on(db, user=user, collection_id=collection_id)
    if kb is None:
        return error("Forbidden", 403)

    # Recipient must exist and be in the same tenant. We don't expose
    # invite-by-email here — that's a separate flow on ResourceShare.
    recipient = await db.get(User, body.user_id)
    if recipient is None or recipient.tenant_id != user.tenant_id:
        return error("User not found in this tenant", 404)

    existing = await db.execute(
        select(UserCollectionGrant).where(
            UserCollectionGrant.user_id == body.user_id,
            UserCollectionGrant.collection_id == collection_id,
        )
    )
    grant = existing.scalar_one_or_none()
    if grant is None:
        grant = UserCollectionGrant(
            user_id=body.user_id,
            collection_id=collection_id,
            permission=body.permission,
            granted_by=user.id,
        )
        db.add(grant)
    else:
        grant.permission = body.permission
        grant.granted_by = user.id

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return error("Failed to grant — concurrent write", 409)
    await db.refresh(grant)
    return success(_serialize_user_grant(grant), status_code=201)


@router.delete("/{collection_id}/users/{user_id}")
async def revoke_user(
    collection_id: uuid.UUID,
    user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    kb = await _require_admin_on(db, user=user, collection_id=collection_id)
    if kb is None:
        return error("Forbidden", 403)

    grant = (await db.execute(
        select(UserCollectionGrant).where(
            UserCollectionGrant.user_id == user_id,
            UserCollectionGrant.collection_id == collection_id,
        )
    )).scalar_one_or_none()
    if grant is None:
        return error("Grant not found", 404)
    await db.delete(grant)
    await db.commit()
    return success({"revoked": True})
