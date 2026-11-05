from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus, AgentType  # noqa: E402


async def find_agent_by_slug(
    db: AsyncSession,
    slug: str,
    tenant_id: uuid.UUID | str | None,
    *,
    active_only: bool = False,
) -> Any:
    """The caller's own agent with this slug, else the shipped one, never another tenant's."""
    query = (
        select(Agent)
        .where(
            Agent.slug == slug,
            or_(Agent.tenant_id == tenant_id, Agent.agent_type == AgentType.OOB),
        )
        .order_by((Agent.tenant_id == tenant_id).desc())
        .limit(1)
    )
    if active_only:
        query = query.where(Agent.status == AgentStatus.ACTIVE)
    return (await db.execute(query)).scalars().first()
