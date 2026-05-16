"""Per-project membership grants."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.permissions import is_admin
from app.core.responses import error, success
from app.services.project_access import (
    assert_project_role,
    list_project_members,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.knowledge_project import KnowledgeProject  # noqa: E402
from models.project_member import ProjectMember, ProjectRole  # noqa: E402
from models.user import User  # noqa: E402

router = APIRouter(
    prefix="/api/knowledge-projects",
    tags=["knowledge-membership"],
)


class GrantMemberRequest(BaseModel):
    user_id: uuid.UUID
    role: ProjectRole = ProjectRole.VIEW


def _serialize(m: ProjectMember) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "project_id": str(m.project_id),
        "user_id": str(m.user_id),
        "role": m.role.value if hasattr(m.role, "value") else m.role,
        "granted_by": str(m.granted_by) if m.granted_by else None,
        "granted_at": m.granted_at.isoformat() if m.granted_at else None,
    }


@router.get("/{project_id}/members")
async def get_members(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await db.get(KnowledgeProject, project_id)
    if p is None or p.tenant_id != user.tenant_id:
        return error("Project not found", 404)
    rows = await list_project_members(db, project_id=project_id)
    return success([_serialize(m) for m in rows])


@router.post("/{project_id}/members")
async def add_member(
    project_id: uuid.UUID,
    body: GrantMemberRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await db.get(KnowledgeProject, project_id)
    if p is None or p.tenant_id != user.tenant_id:
        return error("Project not found", 404)
    if not (
        is_admin(user)
        or await assert_project_role(
            db,
            user_id=user.id,
            project_id=project_id,
            minimum_role=ProjectRole.ADMIN,
        )
    ):
        return error("Forbidden — project ADMIN required", 403)

    recipient = await db.get(User, body.user_id)
    if recipient is None or recipient.tenant_id != user.tenant_id:
        return error("User not found in this tenant", 404)

    existing = (
        await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == body.user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = ProjectMember(
            project_id=project_id,
            user_id=body.user_id,
            role=body.role,
            granted_by=user.id,
        )
        db.add(existing)
    else:
        existing.role = body.role
        existing.granted_by = user.id
    await db.commit()
    await db.refresh(existing)
    return success(_serialize(existing), status_code=201)


@router.delete("/{project_id}/members/{user_id}")
async def remove_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await db.get(KnowledgeProject, project_id)
    if p is None or p.tenant_id != user.tenant_id:
        return error("Project not found", 404)
    if not (
        is_admin(user)
        or await assert_project_role(
            db,
            user_id=user.id,
            project_id=project_id,
            minimum_role=ProjectRole.ADMIN,
        )
    ):
        return error("Forbidden — project ADMIN required", 403)

    # Refuse to remove the project creator if they're the only ADMIN —
    # otherwise the project becomes unmanageable. Tenant admins can
    # still recover, but UI should warn first.
    if p.created_by == user_id:
        admin_count = sum(
            1
            for m in await list_project_members(db, project_id=project_id)
            if m.role == ProjectRole.ADMIN
        )
        if admin_count <= 1:
            return error(
                "Cannot remove the only ADMIN — promote another member first.",
                409,
            )

    target = (
        await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        return error("Member not found", 404)
    await db.delete(target)
    await db.commit()
    return success({"removed": True})
