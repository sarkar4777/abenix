"""Agent sharing on ResourceShare, plus the per-request access check."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from app.core.permissions import (  # noqa: E402
    accessible_resource_ids,
    can_access_agent,
    is_admin,
    is_platform_agent,
)
from models.agent import Agent, AgentStatus, AgentType  # noqa: E402
from models.marketplace import Subscription  # noqa: E402
from models.resource_share import ResourceShare, SharePermission  # noqa: E402
from models.user import User  # noqa: E402

AGENT_KIND = "agent"

PERMISSION_FROM_API = {
    "view": SharePermission.VIEW,
    "execute": SharePermission.EXECUTE,
    "use": SharePermission.EXECUTE,
    "edit": SharePermission.EDIT,
}
PERMISSION_TO_API = {"VIEW": "view", "EXECUTE": "execute", "EDIT": "edit"}

# What a marketplace listing may reveal about an agent's config.
PUBLIC_CONFIG_KEYS = ("model", "tools", "mode", "example_prompts", "input_variables")


def public_model_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    cfg = cfg or {}
    out: dict[str, Any] = {}
    for k in PUBLIC_CONFIG_KEYS:
        if k in cfg:
            out[k] = cfg[k]
    tools = out.get("tools")
    if isinstance(tools, list):
        out["tools"] = [
            t if isinstance(t, str) else (t or {}).get("name") for t in tools
        ]
        out["tools"] = [t for t in out["tools"] if t]
    vars_ = out.get("input_variables")
    if isinstance(vars_, list):
        out["input_variables"] = [
            (
                {
                    k: v
                    for k, v in item.items()
                    if k in ("name", "description", "required", "type")
                }
                if isinstance(item, dict)
                else item
            )
            for item in vars_
        ]
    return out


def visible_agent_clause(user: User):
    """Rows a user may even look up: own tenant, OOB, or marketplace-published."""
    return or_(
        Agent.tenant_id == user.tenant_id,
        Agent.agent_type == AgentType.OOB,
        Agent.is_published.is_(True),
    )


async def resolve_agent_access(
    db: AsyncSession,
    user: User,
    agent: Agent,
    *,
    permission_required: SharePermission = SharePermission.VIEW,
) -> bool:
    if is_platform_agent(agent):
        return True
    if agent.tenant_id == user.tenant_id and (
        agent.creator_id == user.id or is_admin(user)
    ):
        return True
    shared: set[uuid.UUID] = set()
    if agent.tenant_id == user.tenant_id:
        shared = await accessible_resource_ids(
            db, user, kind=AGENT_KIND, minimum_permission=permission_required
        )
    subscribed = False
    if agent.is_published and agent.status == AgentStatus.ACTIVE:
        sub = await db.execute(
            select(Subscription.id).where(
                Subscription.agent_id == agent.id,
                Subscription.user_id == user.id,
                Subscription.status == "active",
            )
        )
        subscribed = sub.first() is not None
    return can_access_agent(
        agent,
        user,
        accessible_ids=shared,
        permission_required=permission_required,
        subscribed=subscribed,
    )


async def accessible_agent_ids(
    db: AsyncSession,
    user: User,
    *,
    permission_required: SharePermission = SharePermission.VIEW,
) -> set[uuid.UUID]:
    """Tenant agents the user created or holds a share on. Platform agents are left out, everyone has those."""
    own = await db.execute(
        select(Agent.id).where(
            Agent.tenant_id == user.tenant_id, Agent.creator_id == user.id
        )
    )
    ids = {row[0] for row in own.all()}
    ids |= await accessible_resource_ids(
        db, user, kind=AGENT_KIND, minimum_permission=permission_required
    )
    return ids


def can_manage_shares(agent: Agent, user: User) -> bool:
    return agent.tenant_id == user.tenant_id and (
        agent.creator_id == user.id or is_admin(user)
    )


async def get_agent_share(
    db: AsyncSession, agent_id: uuid.UUID, target_user_id: uuid.UUID
) -> ResourceShare | None:
    q = await db.execute(
        select(ResourceShare).where(
            ResourceShare.resource_type == AGENT_KIND,
            ResourceShare.resource_id == agent_id,
            ResourceShare.shared_with_user_id == target_user_id,
        )
    )
    return q.scalar_one_or_none()


async def upsert_agent_share(
    db: AsyncSession,
    *,
    agent: Agent,
    target: User,
    permission: SharePermission,
    shared_by: User,
) -> tuple[ResourceShare, bool]:
    existing = await get_agent_share(db, agent.id, target.id)
    if existing:
        existing.permission = permission
        await db.commit()
        await db.refresh(existing)
        return existing, False
    share = ResourceShare(
        tenant_id=agent.tenant_id,
        resource_type=AGENT_KIND,
        resource_id=agent.id,
        shared_with_user_id=target.id,
        shared_with_email=target.email,
        permission=permission,
        shared_by=shared_by.id,
    )
    db.add(share)
    await db.commit()
    await db.refresh(share)
    return share, True


async def list_agent_shares(
    db: AsyncSession, agent_id: uuid.UUID
) -> list[ResourceShare]:
    q = await db.execute(
        select(ResourceShare)
        .where(
            ResourceShare.resource_type == AGENT_KIND,
            ResourceShare.resource_id == agent_id,
        )
        .order_by(ResourceShare.created_at)
    )
    return list(q.scalars().all())


def serialize_agent_share(s: ResourceShare) -> dict[str, Any]:
    raw = s.permission.value if hasattr(s.permission, "value") else str(s.permission)
    return {
        "id": str(s.id),
        "agent_id": str(s.resource_id),
        "email": s.shared_with_email,
        "shared_with_email": s.shared_with_email,
        "user_id": str(s.shared_with_user_id) if s.shared_with_user_id else None,
        "permission": PERMISSION_TO_API.get(raw, raw.lower()),
        "shared_by": str(s.shared_by),
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
