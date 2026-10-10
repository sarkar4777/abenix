"""Agent Sharing — view/execute/edit grants, stored on ResourceShare."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.notifications import create_notification
from app.core.permissions import parse_share_expiry
from app.core.responses import error, success
from app.services.agent_share import (
    AGENT_KIND,
    PERMISSION_FROM_API,
    can_manage_shares,
    list_agent_shares,
    serialize_agent_share,
    upsert_agent_share,
)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus
from models.resource_share import ResourceShare
from models.user import User

router = APIRouter(prefix="/api/agents", tags=["agent-sharing"])


async def _load_managed_agent(
    db: AsyncSession, agent_id: uuid.UUID, user: User
) -> tuple[Agent | None, Any]:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user.tenant_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return None, error("Agent not found", 404)
    if not can_manage_shares(agent, user):
        return None, error("Only the agent creator or an admin can manage shares", 403)
    return agent, None


@router.post("/{agent_id}/share")
async def share_agent(
    agent_id: uuid.UUID,
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Share an agent with another user in the same tenant."""
    agent, err = await _load_managed_agent(db, agent_id, user)
    if err:
        return err

    email = (body.get("email") or "").strip().lower()
    permission_str = str(body.get("permission") or "view").lower()
    permission = PERMISSION_FROM_API.get(permission_str)
    if permission is None:
        return error("permission must be view, execute, or edit", 400)
    if not email:
        return error("email is required", 400)
    expires_at, exp_err = parse_share_expiry(body.get("expires_at"))
    if exp_err:
        return error(exp_err, 400)

    target_result = await db.execute(
        select(User).where(
            User.email == email,
            User.tenant_id == user.tenant_id,
        )
    )
    target_user = target_result.scalar_one_or_none()
    if not target_user:
        return error("User not found in this tenant", 404)
    if target_user.id == user.id:
        return error("You cannot share an agent with yourself", 400)

    share, created = await upsert_agent_share(
        db,
        agent=agent,
        target=target_user,
        permission=permission,
        shared_by=user,
        expires_at=expires_at,
    )

    if created:
        try:
            await create_notification(
                db,
                tenant_id=target_user.tenant_id,
                user_id=target_user.id,
                type="agent_shared",
                title="Agent shared with you",
                message=f"{user.full_name} shared '{agent.name}' with you ({permission_str} permission)",
                link=f"/agents/{agent_id}/chat",
                metadata={
                    "agent_id": str(agent_id),
                    "permission": permission_str,
                    "shared_by": user.full_name,
                },
            )
            await db.commit()
        except Exception:
            pass

    data = serialize_agent_share(share)
    data["shared_with"] = email
    return success(data, status_code=201 if created else 200)


@router.get("/{agent_id}/shares")
async def list_shares(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all users this agent is shared with."""
    _agent, err = await _load_managed_agent(db, agent_id, user)
    if err:
        return err
    shares = await list_agent_shares(db, agent_id)
    return success([serialize_agent_share(s) for s in shares])


@router.delete("/{agent_id}/shares/{share_id}")
async def revoke_share(
    agent_id: uuid.UUID,
    share_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Revoke a user's access to a shared agent."""
    agent, err = await _load_managed_agent(db, agent_id, user)
    if err:
        return err
    result = await db.execute(
        select(ResourceShare).where(
            ResourceShare.id == share_id,
            ResourceShare.resource_type == AGENT_KIND,
            ResourceShare.resource_id == agent_id,
        )
    )
    share = result.scalar_one_or_none()
    if not share:
        return error("Share not found", 404)

    if share.shared_with_user_id:
        try:
            await create_notification(
                db,
                tenant_id=user.tenant_id,
                user_id=share.shared_with_user_id,
                type="share_revoked",
                title="Access revoked",
                message=f"Your access to '{agent.name}' has been revoked",
            )
        except Exception:
            pass

    await db.delete(share)
    await db.commit()
    return success({"revoked": True})


@router.get("/shared-with-me")
async def shared_with_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all agents shared with the current user."""
    result = await db.execute(
        select(ResourceShare, Agent)
        .join(Agent, ResourceShare.resource_id == Agent.id)
        .where(
            ResourceShare.resource_type == AGENT_KIND,
            ResourceShare.shared_with_user_id == user.id,
            ResourceShare.live(),
            Agent.tenant_id == user.tenant_id,
            Agent.status != AgentStatus.ARCHIVED,
        )
    )
    rows = result.all()
    return success(
        [
            {
                "share_id": str(share.id),
                "agent_id": str(agent.id),
                "agent_name": agent.name,
                "agent_slug": agent.slug,
                "description": agent.description,
                "permission": serialize_agent_share(share)["permission"],
                "shared_by": str(share.shared_by),
                "category": agent.category,
            }
            for share, agent in rows
        ]
    )
