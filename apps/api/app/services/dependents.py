"""What depends on an agent, a code asset or a knowledge base.

Used before a delete so the user sees what will stop working, and after a
confirmed delete so triggers and bindings do not fire into nothing. Every
query is scoped to the tenant and capped, so a large workspace stays cheap.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import String, cast, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus  # noqa: E402
from models.agent_trigger import AgentTrigger  # noqa: E402
from models.collection_grant import AgentCollectionGrant  # noqa: E402

LIMIT = 50


def _row(a: Agent) -> dict[str, Any]:
    mc = a.model_config_ or {}
    kind = "pipeline" if mc.get("mode") == "pipeline" else "agent"
    return {"id": str(a.id), "name": a.name, "kind": kind}


async def _agents_mentioning(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    needles: list[str],
    exclude: uuid.UUID | None,
) -> list[dict[str, Any]]:
    needles = [n for n in needles if n]
    if not needles:
        return []
    conds = []
    for n in needles:
        conds.append(cast(Agent.model_config_, String).contains(n))
        conds.append(Agent.system_prompt.contains(n))
    q = select(Agent).where(
        Agent.tenant_id == tenant_id,
        Agent.status != AgentStatus.ARCHIVED,
        or_(*conds),
    )
    if exclude is not None:
        q = q.where(Agent.id != exclude)
    rows = (await db.execute(q.limit(LIMIT))).scalars().all()
    return [_row(a) for a in rows]


async def agent_dependents(
    db: AsyncSession, agent: Agent
) -> dict[str, list[dict[str, Any]]]:
    users = await _agents_mentioning(
        db, agent.tenant_id, [f'"{agent.slug}"', str(agent.id)], agent.id
    )
    # a prompt names its sub-agent by slug without quotes
    if agent.slug:
        extra = await _agents_mentioning(db, agent.tenant_id, [agent.slug], agent.id)
        seen = {u["id"] for u in users}
        users += [u for u in extra if u["id"] not in seen]
    trig = (
        (
            await db.execute(
                select(AgentTrigger)
                .where(
                    AgentTrigger.agent_id == agent.id, AgentTrigger.is_active.is_(True)
                )
                .limit(LIMIT)
            )
        )
        .scalars()
        .all()
    )
    return {
        "pipelines": [u for u in users if u["kind"] == "pipeline"],
        "agents": [u for u in users if u["kind"] == "agent"],
        "triggers": [
            {"id": str(t.id), "name": t.name, "kind": t.trigger_type} for t in trig
        ],
    }


async def disable_agent_triggers(db: AsyncSession, agent_id: uuid.UUID) -> int:
    res = await db.execute(
        update(AgentTrigger)
        .where(AgentTrigger.agent_id == agent_id, AgentTrigger.is_active.is_(True))
        .values(is_active=False, last_status="agent deleted")
    )
    return res.rowcount or 0


async def code_asset_dependents(
    db: AsyncSession, tenant_id: uuid.UUID, asset_id: uuid.UUID, name: str
) -> dict[str, list[dict[str, Any]]]:
    users = await _agents_mentioning(db, tenant_id, [str(asset_id), f'"{name}"'], None)
    return {
        "pipelines": [u for u in users if u["kind"] == "pipeline"],
        "agents": [u for u in users if u["kind"] == "agent"],
    }


async def kb_dependents(
    db: AsyncSession, tenant_id: uuid.UUID, kb_id: uuid.UUID
) -> dict[str, list[dict[str, Any]]]:
    from models.atlas import AtlasGraph

    granted = (
        (
            await db.execute(
                select(Agent)
                .join(AgentCollectionGrant, AgentCollectionGrant.agent_id == Agent.id)
                .where(
                    AgentCollectionGrant.collection_id == kb_id,
                    Agent.tenant_id == tenant_id,
                    Agent.status != AgentStatus.ARCHIVED,
                )
                .limit(LIMIT)
            )
        )
        .scalars()
        .all()
    )
    graphs = (
        (
            await db.execute(
                select(AtlasGraph)
                .where(AtlasGraph.kb_id == kb_id, AtlasGraph.tenant_id == tenant_id)
                .limit(LIMIT)
            )
        )
        .scalars()
        .all()
    )
    return {
        "agents": [_row(a) for a in granted],
        "atlas_graphs": [{"id": str(g.id), "name": g.name} for g in graphs],
    }


async def release_kb(db: AsyncSession, tenant_id: uuid.UUID, kb_id: uuid.UUID) -> None:
    """Unbind graphs and drop agent grants so nothing points at a deleted KB."""
    from sqlalchemy import delete

    from models.atlas import AtlasGraph

    await db.execute(
        update(AtlasGraph)
        .where(AtlasGraph.kb_id == kb_id, AtlasGraph.tenant_id == tenant_id)
        .values(kb_id=None)
    )
    await db.execute(
        delete(AgentCollectionGrant).where(AgentCollectionGrant.collection_id == kb_id)
    )


def count(deps: dict[str, list[Any]]) -> int:
    return sum(len(v) for v in deps.values())
