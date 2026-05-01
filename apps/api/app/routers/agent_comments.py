"""Agent Comments — threaded comments for team collaboration on agents."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.notifications import create_notification
from app.core.responses import error, success

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent
from models.agent_comment import AgentComment
from models.user import User

router = APIRouter(prefix="/api/agents", tags=["agent-comments"])


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

    # Notify agent owner
    agent_result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = agent_result.scalar_one_or_none()
    if agent and agent.creator_id != user.id:
        try:
            await create_notification(
                db,
                tenant_id=agent.tenant_id,
                user_id=agent.creator_id,
                type="agent_comment",
                title=f"New comment on {agent.name}",
                message=f"{user.full_name}: {content[:100]}",
                link=f"/agents/{agent_id}/chat",
            )
            await db.commit()
        except Exception:
            pass

    return success({"id": str(comment.id), "content": content}, status_code=201)


@router.get("/{agent_id}/comments")
async def list_comments(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(AgentComment, User.full_name, User.email)
        .join(User, AgentComment.user_id == User.id)
        .where(AgentComment.agent_id == agent_id)
        .order_by(AgentComment.created_at.asc())
    )
    rows = result.all()
    return success(
        [
            {
                "id": str(c.id),
                "content": c.content,
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
    result = await db.execute(
        select(AgentComment).where(
            AgentComment.id == comment_id, AgentComment.agent_id == agent_id
        )
    )
    comment = result.scalar_one_or_none()
    if not comment:
        return error("Comment not found", 404)

    if body.get("content"):
        comment.content = body["content"]
    if "is_resolved" in body:
        comment.is_resolved = body["is_resolved"]

    await db.commit()
    return success({"updated": True})
