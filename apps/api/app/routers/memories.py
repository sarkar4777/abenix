"""Agent Memory Management — browse, inspect, and delete stored memories."""

from __future__ import annotations

import sys
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.permissions import is_admin
from app.core.responses import error, success

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent
from models.agent_memory import AgentMemory
from models.resource_share import SharePermission
from models.user import User

router = APIRouter(prefix="/api/agents", tags=["memories"])


async def _memory_agent(
    db: AsyncSession, agent_id: uuid.UUID, user: User, *, manage: bool = False
) -> JSONResponse | None:
    """None when the caller may read (or with manage, delete) this agent's memories."""
    from app.services.agent_share import (
        resolve_agent_access,
        visible_agent_clause,
    )

    agent = (
        await db.execute(
            select(Agent).where(Agent.id == agent_id, visible_agent_clause(user))
        )
    ).scalar_one_or_none()
    if agent is None or not await resolve_agent_access(db, user, agent):
        return error("Agent not found", 404)
    if not manage:
        return None
    if is_admin(user) or (
        agent.creator_id is not None
        and agent.tenant_id == user.tenant_id
        and agent.creator_id == user.id
    ):
        return None
    if agent.creator_id is not None and await resolve_agent_access(
        db, user, agent, permission_required=SharePermission.EDIT
    ):
        return None
    return error(
        "Only the agent owner, an editor or an admin can delete its memories", 403
    )


@router.get("/{agent_id}/memories")
async def list_memories(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    memory_type: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    """List stored memories for an agent, in the caller's tenant only."""
    denied = await _memory_agent(db, agent_id, user)
    if denied is not None:
        return denied

    query = select(AgentMemory).where(
        AgentMemory.agent_id == agent_id,
        AgentMemory.tenant_id == user.tenant_id,
        AgentMemory.deleted_at.is_(None),
    )
    if memory_type:
        query = query.where(AgentMemory.memory_type == memory_type)
    if search:
        query = query.where(
            or_(
                AgentMemory.key.ilike(f"%{search}%"),
                AgentMemory.value.ilike(f"%{search}%"),
            )
        )

    query = (
        query.order_by(desc(AgentMemory.updated_at), AgentMemory.id)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    memories = result.scalars().all()

    return success(
        [
            {
                "id": str(m.id),
                "key": m.key,
                "value": str(m.value)[:500] if m.value else None,
                "memory_type": (
                    m.memory_type.value
                    if hasattr(m.memory_type, "value")
                    else str(m.memory_type)
                ),
                "importance": float(m.importance) if m.importance else None,
                "access_count": m.access_count,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            }
            for m in memories
        ]
    )


@router.delete("/{agent_id}/memories/{memory_id}")
async def delete_memory(
    agent_id: uuid.UUID,
    memory_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Delete a specific memory."""
    denied = await _memory_agent(db, agent_id, user, manage=True)
    if denied is not None:
        return denied
    result = await db.execute(
        select(AgentMemory).where(
            AgentMemory.id == memory_id,
            AgentMemory.agent_id == agent_id,
            AgentMemory.tenant_id == user.tenant_id,
        )
    )
    memory = result.scalar_one_or_none()
    if not memory:
        return error("Memory not found", 404)

    await db.delete(memory)
    await db.commit()
    return success({"deleted": True})


@router.delete("/{agent_id}/memories")
async def bulk_delete_memories(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    all: bool = Query(False),
) -> JSONResponse:
    """Delete all of this tenant's memories for an agent."""
    if not all:
        return error("Set all=true to confirm bulk deletion", 400)
    denied = await _memory_agent(db, agent_id, user, manage=True)
    if denied is not None:
        return denied

    from sqlalchemy import delete

    result = await db.execute(
        delete(AgentMemory).where(
            AgentMemory.agent_id == agent_id,
            AgentMemory.tenant_id == user.tenant_id,
        )
    )
    await db.commit()
    return success({"deleted_count": result.rowcount})
