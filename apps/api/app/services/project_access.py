"""Project membership resolver helpers."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))

from models.knowledge_project import KnowledgeProject  # noqa: E402
from models.project_member import (  # noqa: E402
    PROJECT_ROLE_RANK,
    ProjectMember,
    ProjectRole,
)


async def list_project_members(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
) -> list[ProjectMember]:
    rows = (
        (
            await db.execute(
                select(ProjectMember)
                .where(
                    ProjectMember.project_id == project_id,
                )
                .order_by(ProjectMember.granted_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def get_membership_role(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ProjectRole | None:
    row = (
        await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    return row


async def assert_project_role(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    minimum_role: ProjectRole = ProjectRole.VIEW,
) -> bool:
    """True if the user is a project member at >= minimum_role."""
    role = await get_membership_role(db, user_id=user_id, project_id=project_id)
    if role is None:
        return False
    return PROJECT_ROLE_RANK[role] >= PROJECT_ROLE_RANK[minimum_role]


async def visible_project_ids(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> set[uuid.UUID]:
    """Project ids a user can see: created OR member."""
    rows = (
        await db.execute(
            select(KnowledgeProject.id).where(
                KnowledgeProject.tenant_id == tenant_id,
                (KnowledgeProject.created_by == user_id)
                | (
                    KnowledgeProject.id.in_(
                        select(ProjectMember.project_id).where(
                            ProjectMember.user_id == user_id,
                        )
                    )
                ),
            )
        )
    ).all()
    return {r[0] for r in rows}
