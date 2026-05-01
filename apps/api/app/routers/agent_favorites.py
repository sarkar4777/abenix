"""Agent Favorites — star agents and organize into collections."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent
from models.agent_favorite import AgentFavorite
from models.user import User

router = APIRouter(prefix="/api/agents", tags=["agent-favorites"])


@router.post("/{agent_id}/favorite")
async def add_favorite(
    agent_id: uuid.UUID,
    body: dict[str, Any] | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    body = body or {}
    # Check if already favorited
    existing = await db.execute(
        select(AgentFavorite).where(
            AgentFavorite.user_id == user.id,
            AgentFavorite.agent_id == agent_id,
        )
    )
    if existing.scalar_one_or_none():
        return error("Already favorited", 409)

    fav = AgentFavorite(
        id=uuid.uuid4(),
        user_id=user.id,
        agent_id=agent_id,
        collection=body.get("collection"),
    )
    db.add(fav)
    await db.commit()
    return success(
        {"id": str(fav.id), "agent_id": str(agent_id), "collection": fav.collection},
        status_code=201,
    )


@router.delete("/{agent_id}/favorite")
async def remove_favorite(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(AgentFavorite).where(
            AgentFavorite.user_id == user.id,
            AgentFavorite.agent_id == agent_id,
        )
    )
    fav = result.scalar_one_or_none()
    if not fav:
        return error("Not favorited", 404)
    await db.delete(fav)
    await db.commit()
    return success({"removed": True})


@router.get("/favorites")
async def list_favorites(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(AgentFavorite, Agent)
        .join(Agent, AgentFavorite.agent_id == Agent.id)
        .where(AgentFavorite.user_id == user.id)
        .order_by(AgentFavorite.created_at.desc())
    )
    rows = result.all()
    return success(
        [
            {
                "favorite_id": str(fav.id),
                "agent_id": str(agent.id),
                "agent_name": agent.name,
                "agent_slug": agent.slug,
                "description": agent.description,
                "category": agent.category,
                "collection": fav.collection,
                "created_at": fav.created_at.isoformat() if fav.created_at else None,
            }
            for fav, agent in rows
        ]
    )


@router.put("/{agent_id}/favorite")
async def update_favorite(
    agent_id: uuid.UUID,
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(AgentFavorite).where(
            AgentFavorite.user_id == user.id,
            AgentFavorite.agent_id == agent_id,
        )
    )
    fav = result.scalar_one_or_none()
    if not fav:
        return error("Not favorited", 404)
    fav.collection = body.get("collection")
    await db.commit()
    return success({"updated": True, "collection": fav.collection})
