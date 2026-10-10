"""Agent Comments — threaded comments for team collaboration on agents."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.permissions import is_admin
from app.core.notifications import create_notification
from app.core.responses import error, success

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent
from models.agent_comment import AgentComment
from models.user import User

router = APIRouter(prefix="/api/agents", tags=["agent-comments"])


async def _load_agent_for_caller(
    db: AsyncSession, agent_id: uuid.UUID, user: User
) -> Agent | None:
    """The agent, when the caller may see it. Comments follow the agent's access."""
    from app.services.agent_share import resolve_agent_access, visible_agent_clause

    agent = (
        await db.execute(
            select(Agent).where(Agent.id == agent_id, visible_agent_clause(user))
        )
    ).scalar_one_or_none()
    if agent is None or not await resolve_agent_access(db, user, agent):
        return None
    return agent


def _can_moderate(agent: Agent, user: User) -> bool:
    return is_admin(user) or (
        agent.creator_id is not None and agent.creator_id == user.id
    )


@router.post("/{agent_id}/comments")
async def add_comment(
    agent_id: uuid.UUID,
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    content = body.get("content", "").strip()
    if not content:
        return error("Comment content is required", 400)

    agent = await _load_agent_for_caller(db, agent_id, user)
    if not agent:
        return error("Agent not found", 404)

    comment = AgentComment(
        id=uuid.uuid4(),
        agent_id=agent_id,
        user_id=user.id,
        revision_id=uuid.UUID(body["revision_id"]) if body.get("revision_id") else None,
        parent_id=uuid.UUID(body["parent_id"]) if body.get("parent_id") else None,
        content=content,
    )
    db.add(comment)
    await db.commit()

    if agent.creator_id and agent.creator_id != user.id:
        try:
            await create_notification(
                db,
                tenant_id=agent.tenant_id,
                user_id=agent.creator_id,
                type="agent_comment",
                title=f"New comment on {agent.name}",
                message=f"{user.full_name}: {content[:100]}",
                link=f"/agents/{agent_id}/info#comments",
            )
            await db.commit()
        except Exception:
            pass

    return success(
        {
            "id": str(comment.id),
            "content": content,
            "user_id": str(user.id),
            "user_name": user.full_name,
            "user_email": user.email,
            "is_resolved": False,
            "parent_id": str(comment.parent_id) if comment.parent_id else None,
            "created_at": (
                comment.created_at.isoformat() if comment.created_at else None
            ),
        },
        status_code=201,
    )


@router.get("/{agent_id}/comments")
async def list_comments(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not await _load_agent_for_caller(db, agent_id, user):
        return error("Agent not found", 404)
    result = await db.execute(
        select(AgentComment, User.full_name, User.email)
        .join(User, AgentComment.user_id == User.id)
        .where(AgentComment.agent_id == agent_id, User.tenant_id == user.tenant_id)
        .order_by(AgentComment.created_at.asc())
    )
    rows = result.all()
    return success(
        [
            {
                "id": str(c.id),
                "content": c.content,
                "user_id": str(c.user_id),
                "user_name": name,
                "user_email": email,
                "is_resolved": c.is_resolved,
                "parent_id": str(c.parent_id) if c.parent_id else None,
                "revision_id": str(c.revision_id) if c.revision_id else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c, name, email in rows
        ]
    )


@router.put("/{agent_id}/comments/{comment_id}")
async def update_comment(
    agent_id: uuid.UUID,
    comment_id: uuid.UUID,
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    agent = await _load_agent_for_caller(db, agent_id, user)
    if not agent:
        return error("Agent not found", 404)
    result = await db.execute(
        select(AgentComment).where(
            AgentComment.id == comment_id, AgentComment.agent_id == agent_id
        )
    )
    comment = result.scalar_one_or_none()
    if not comment:
        return error("Comment not found", 404)
    mine = comment.user_id == user.id

    content = (body.get("content") or "").strip()
    if content:
        if not mine:
            return error("Only the author can edit a comment", 403)
        comment.content = content
    if "is_resolved" in body:
        if not (mine or _can_moderate(agent, user)):
            return error("Only the author or the agent owner can resolve it", 403)
        comment.is_resolved = bool(body["is_resolved"])

    await db.commit()
    return success({"updated": True})


@router.delete("/{agent_id}/comments/{comment_id}")
async def delete_comment(
    agent_id: uuid.UUID,
    comment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    agent = await _load_agent_for_caller(db, agent_id, user)
    if not agent:
        return error("Agent not found", 404)
    comment = (
        await db.execute(
            select(AgentComment).where(
                AgentComment.id == comment_id, AgentComment.agent_id == agent_id
            )
        )
    ).scalar_one_or_none()
    if not comment:
        return error("Comment not found", 404)
    if comment.user_id != user.id and not _can_moderate(agent, user):
        return error("Only the author or the agent owner can delete it", 403)
    await db.delete(comment)
    await db.commit()
    return success({"deleted": True})
