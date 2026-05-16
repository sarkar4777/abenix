"""Resolve which collections an agent (or acting subject) can read."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))

from models.collection_grant import (  # noqa: E402
    AgentCollectionGrant,
    CollectionPermission,
    PERMISSION_RANK,
    UserCollectionGrant,
)
from models.knowledge_base import KBStatus, KnowledgeBase  # noqa: E402


async def resolve_agent_collections(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID,
    minimum_permission: CollectionPermission = CollectionPermission.READ,
    acting_subject: dict[str, Any] | None = None,
) -> list[uuid.UUID]:
    """Return the collection ids an agent is allowed to query."""
    min_rank = PERMISSION_RANK[minimum_permission]
    allowed_perms = [p for p, r in PERMISSION_RANK.items() if r >= min_rank]

    # Legacy FK + v2 grants, deduped, tenant-scoped, status filter.
    grant_subq = (
        select(AgentCollectionGrant.collection_id)
        .where(
            AgentCollectionGrant.agent_id == agent_id,
            AgentCollectionGrant.permission.in_(allowed_perms),
        )
        .scalar_subquery()
    )
    q = select(KnowledgeBase.id).where(
        KnowledgeBase.tenant_id == tenant_id,
        KnowledgeBase.status == KBStatus.READY,
        or_(
            KnowledgeBase.agent_id == agent_id,
            KnowledgeBase.id.in_(grant_subq),
        ),
    )
    rows = (await db.execute(q)).all()
    ids = {row[0] for row in rows}

    # Acting-subject collection — when an integration passes `actAs`,
    # we include the collection slug-named `<subject_type>-<subject_id>`
    # if one exists in this tenant. Phase 2 standalone-app cutover
    # creates these collections on demand.
    if acting_subject:
        subj_type = acting_subject.get("subject_type")
        subj_id = acting_subject.get("subject_id")
        if subj_type and subj_id:
            slug = f"{subj_type}-{subj_id}"
            subj_row = await db.execute(
                select(KnowledgeBase.id).where(
                    KnowledgeBase.tenant_id == tenant_id,
                    KnowledgeBase.name == slug,
                    KnowledgeBase.status == KBStatus.READY,
                )
            )
            for row in subj_row.all():
                ids.add(row[0])

    return list(ids)


async def resolve_user_collections(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    minimum_permission: CollectionPermission = CollectionPermission.READ,
) -> list[uuid.UUID]:
    """Collections a user can see at >= the given permission."""
    min_rank = PERMISSION_RANK[minimum_permission]
    allowed_perms = [p for p, r in PERMISSION_RANK.items() if r >= min_rank]

    grant_subq = (
        select(UserCollectionGrant.collection_id)
        .where(
            UserCollectionGrant.user_id == user_id,
            UserCollectionGrant.permission.in_(allowed_perms),
        )
        .scalar_subquery()
    )
    q = select(KnowledgeBase.id).where(
        KnowledgeBase.tenant_id == tenant_id,
        or_(
            KnowledgeBase.created_by == user_id,
            KnowledgeBase.id.in_(grant_subq),
        ),
    )
    rows = (await db.execute(q)).all()
    return [row[0] for row in rows]


async def assert_collection_access(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
    minimum_permission: CollectionPermission = CollectionPermission.READ,
    is_admin: bool = False,
) -> bool:
    """True if the user can act on this collection at the given level."""
    kb = await db.get(KnowledgeBase, collection_id)
    if kb is None or kb.tenant_id != tenant_id:
        return False
    if is_admin:
        return True
    if kb.created_by == user_id:
        return True

    min_rank = PERMISSION_RANK[minimum_permission]
    allowed_perms = [p for p, r in PERMISSION_RANK.items() if r >= min_rank]
    grant = await db.execute(
        select(UserCollectionGrant).where(
            UserCollectionGrant.user_id == user_id,
            UserCollectionGrant.collection_id == collection_id,
            UserCollectionGrant.permission.in_(allowed_perms),
        )
    )
    return grant.first() is not None
