"""Agent Sharing — granular sharing with view/execute/edit permissions."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.notifications import create_notification
from app.core.responses import error, success

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent
from models.agent_share import AgentShare, SharePermission
from models.user import User

router = APIRouter(prefix="/api/agents", tags=["agent-sharing"])


@router.post("/{agent_id}/share")
async def share_agent(
    agent_id: uuid.UUID,
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Share an agent with another user."""
    # Verify ownership
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user.tenant_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    email = body.get("email", "").strip()
    permission = body.get("permission", "view")
    if permission not in ("view", "execute", "edit"):
        return error("permission must be view, execute, or edit", 400)
    if not email:
        return error("email is required", 400)

    # Find target user
    target_result = await db.execute(select(User).where(User.email == email))
    target_user = target_result.scalar_one_or_none()

    # Check for existing share
    if target_user:
        existing = await db.execute(
            select(AgentShare).where(
                AgentShare.agent_id == agent_id,
                AgentShare.shared_with_user_id == target_user.id,
            )
        )
        if existing.scalar_one_or_none():
            return error("Agent already shared with this user", 409)

    share = AgentShare(
        id=uuid.uuid4(),
        agent_id=agent_id,
        shared_with_user_id=target_user.id if target_user else None,
        shared_with_email=email,
        permission=SharePermission(permission),
        shared_by=user.id,
    )
    db.add(share)
    await db.commit()

    # Notify recipient
    if target_user:
        try:
            await create_notification(
                db,
                tenant_id=target_user.tenant_id,
                user_id=target_user.id,
                type="agent_shared",
                title=f"Agent shared with you",
                message=f"{user.full_name} shared '{agent.name}' with you ({permission} permission)",
                link=f"/agents/{agent_id}/chat",
                metadata={"agent_id": str(agent_id), "permission": permission, "shared_by": user.full_name},
            )
            await db.commit()
        except Exception:
            pass

    return success({
        "id": str(share.id),
        "agent_id": str(agent_id),
        "shared_with": email,
        "permission": permission,
    }, status_code=201)


@router.get("/{agent_id}/shares")
async def list_shares(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all users this agent is shared with."""
    result = await db.execute(
        select(AgentShare).where(AgentShare.agent_id == agent_id)
    )
    shares = result.scalars().all()
    return success([
        {
            "id": str(s.id),
            "email": s.shared_with_email,
            "user_id": str(s.shared_with_user_id) if s.shared_with_user_id else None,
            "permission": s.permission.value,
            "shared_by": str(s.shared_by),
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in shares
    ])


@router.delete("/{agent_id}/shares/{share_id}")
async def revoke_share(
    agent_id: uuid.UUID,
    share_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Revoke a user's access to a shared agent."""
    result = await db.execute(
        select(AgentShare).where(AgentShare.id == share_id, AgentShare.agent_id == agent_id)
    )
    share = result.scalar_one_or_none()
    if not share:
        return error("Share not found", 404)

    # Notify the user whose access is being revoked
    if share.shared_with_user_id:
        try:
            agent_result = await db.execute(select(Agent.name).where(Agent.id == agent_id))
            agent_name = agent_result.scalar() or "Agent"
            await create_notification(
                db,
                tenant_id=user.tenant_id,
                user_id=share.shared_with_user_id,
                type="share_revoked",
                title="Access revoked",
                message=f"Your access to '{agent_name}' has been revoked",
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
        select(AgentShare, Agent).join(Agent, AgentShare.agent_id == Agent.id).where(
            AgentShare.shared_with_user_id == user.id,
        )
    )
    rows = result.all()
    return success([
        {
            "share_id": str(share.id),
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            "agent_slug": agent.slug,
            "description": agent.description,
            "permission": share.permission.value,
            "shared_by": str(share.shared_by),
            "category": agent.category,
        }
        for share, agent in rows
    ])
