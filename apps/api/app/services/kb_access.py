"""Collection (KnowledgeBase) access resolution."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.project_access import visible_project_ids

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))

from models.collection_grant import UserCollectionGrant  # noqa: E402
from models.knowledge_base import KnowledgeBase  # noqa: E402
from models.knowledge_project import CollectionVisibility  # noqa: E402


def _is_tenant_admin(user) -> bool:
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return role.lower() == "admin"


_WRITE_PERMS = {"edit", "admin"}


async def user_can_edit_collection(
    db: AsyncSession,
    *,
    user,
    kb: KnowledgeBase,
) -> bool:
    """Can this user mutate this collection (update / delete / upload)?"""
    if kb.tenant_id != user.tenant_id:
        return False
    if _is_tenant_admin(user):
        return True
    if getattr(kb, "created_by", None) == user.id:
        return True

    grant = (
        await db.execute(
            select(UserCollectionGrant.permission)
            .where(
                UserCollectionGrant.collection_id == kb.id,
                UserCollectionGrant.user_id == user.id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if grant is None:
        return False
    perm = grant.value if hasattr(grant, "value") else str(grant)
    return perm.lower() in _WRITE_PERMS


async def user_can_access_collection(
    db: AsyncSession,
    *,
    user,
    kb: KnowledgeBase,
) -> bool:
    """Authoritative check: can this user read this collection?"""
    if kb.tenant_id != user.tenant_id:
        return False
    if _is_tenant_admin(user):
        return True

    visibility = kb.default_visibility
    if hasattr(visibility, "value"):
        visibility = visibility.value

    if visibility == CollectionVisibility.TENANT.value:
        return True

    if visibility == CollectionVisibility.PROJECT.value:
        if kb.project_id is None:
            return True  # legacy: no project → tenant-wide
        proj_ids = await visible_project_ids(
            db,
            user_id=user.id,
            tenant_id=user.tenant_id,
        )
        if kb.project_id in proj_ids:
            return True

    # private OR project-member-missing → require explicit grant
    grant = (
        await db.execute(
            select(UserCollectionGrant.id)
            .where(
                UserCollectionGrant.collection_id == kb.id,
                UserCollectionGrant.user_id == user.id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return grant is not None


async def accessible_collection_ids(
    db: AsyncSession,
    *,
    user,
    tenant_id: uuid.UUID,
) -> set[uuid.UUID] | None:
    """Return the set of KB ids this user can read within the tenant."""
    if _is_tenant_admin(user):
        return None

    # Collect project ids visible to the user (membership + creator).
    proj_ids = await visible_project_ids(
        db,
        user_id=user.id,
        tenant_id=tenant_id,
    )

    # Direct grants (covers private collections explicitly shared).
    grant_rows: Iterable[uuid.UUID] = (
        await db.execute(
            select(UserCollectionGrant.collection_id).where(
                UserCollectionGrant.user_id == user.id,
            )
        )
    ).scalars()
    grant_ids = set(grant_rows)

    # Collections visible via tenant/project visibility OR direct grant.
    rows = (
        await db.execute(
            select(
                KnowledgeBase.id,
                KnowledgeBase.default_visibility,
                KnowledgeBase.project_id,
            ).where(
                KnowledgeBase.tenant_id == tenant_id,
            )
        )
    ).all()

    visible: set[uuid.UUID] = set()
    for kb_id, visibility, project_id in rows:
        v = visibility.value if hasattr(visibility, "value") else visibility
        if v == CollectionVisibility.TENANT.value:
            visible.add(kb_id)
        elif v == CollectionVisibility.PROJECT.value:
            if project_id is None or project_id in proj_ids:
                visible.add(kb_id)
        # private → only if explicit grant (added below)
        if kb_id in grant_ids:
            visible.add(kb_id)
    return visible
