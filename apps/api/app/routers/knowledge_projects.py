"""Knowledge Projects — CRUD for the v2 governance container."""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.permissions import is_admin
from app.core.responses import error, success
from app.core.sanitize import sanitize_input
from app.services.project_access import visible_project_ids

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.knowledge_base import KnowledgeBase  # noqa: E402
from models.knowledge_project import KnowledgeProject  # noqa: E402
from models.project_member import ProjectMember, ProjectRole  # noqa: E402
from models.user import User  # noqa: E402

router = APIRouter(prefix="/api/knowledge-projects", tags=["knowledge"])


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str | None = Field(None, max_length=120)
    description: str = Field("", max_length=2000)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)


_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(text: str) -> str:
    """Conservative slug — lowercase, dashes only."""
    s = text.lower().strip()
    s = _SLUG_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:120] or "project"


def _serialize_project(
    p: KnowledgeProject, collection_count: int = 0
) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "tenant_id": str(p.tenant_id),
        "name": p.name,
        "slug": p.slug,
        "description": p.description,
        "ontology_schema_id": (
            str(p.ontology_schema_id) if p.ontology_schema_id else None
        ),
        "collection_count": collection_count,
        "created_by": str(p.created_by) if p.created_by else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("")
async def list_projects(
    search: str = Query("", max_length=255),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return projects the caller can see."""
    q = select(KnowledgeProject).where(
        KnowledgeProject.tenant_id == user.tenant_id,
    )
    if not is_admin(user):
        ids = await visible_project_ids(
            db,
            user_id=user.id,
            tenant_id=user.tenant_id,
        )
        if not ids:
            # Empty set short-circuit so the IN () doesn't generate
            # a parse error and we still return the user's slice.
            q = q.where(KnowledgeProject.id == uuid.UUID(int=0))
        else:
            q = q.where(KnowledgeProject.id.in_(ids))
    if search:
        q = q.where(KnowledgeProject.name.ilike(f"%{search}%"))
    q = q.order_by(KnowledgeProject.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()

    # Cheap collection counts in one round-trip.
    counts: dict[uuid.UUID, int] = {}
    if rows:
        cnt_q = (
            select(KnowledgeBase.project_id, func.count(KnowledgeBase.id))
            .where(KnowledgeBase.project_id.in_([p.id for p in rows]))
            .group_by(KnowledgeBase.project_id)
        )
        for pid, c in (await db.execute(cnt_q)).all():
            counts[pid] = c

    data = [_serialize_project(p, counts.get(p.id, 0)) for p in rows]

    total = (
        await db.scalar(
            select(func.count(KnowledgeProject.id)).where(
                KnowledgeProject.tenant_id == user.tenant_id,
            )
        )
        or 0
    )
    return success(data, meta={"total": total, "limit": limit, "offset": offset})


@router.post("")
async def create_project(
    body: CreateProjectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    name = sanitize_input(body.name)
    slug = _slugify(body.slug) if body.slug else _slugify(name)

    # Reject slug collisions explicitly so the API has a clean 400 path
    # instead of a UniqueConstraint 500 from the DB.
    existing = await db.execute(
        select(KnowledgeProject.id).where(
            KnowledgeProject.tenant_id == user.tenant_id,
            KnowledgeProject.slug == slug,
        )
    )
    if existing.first() is not None:
        return error(f"Project with slug '{slug}' already exists in this tenant", 409)

    p = KnowledgeProject(
        tenant_id=user.tenant_id,
        name=name,
        slug=slug,
        description=sanitize_input(body.description or ""),
        created_by=user.id,
    )
    db.add(p)
    await db.flush()

    # Auto-grant creator ADMIN on the new project. Mirror of the
    # collection-creation flow; ensures the creator can manage
    # membership without depending on the migration backfill.
    db.add(
        ProjectMember(
            project_id=p.id,
            user_id=user.id,
            role=ProjectRole.ADMIN,
            granted_by=user.id,
        )
    )
    await db.commit()
    await db.refresh(p)
    return success(_serialize_project(p), status_code=201)


@router.get("/{project_id}")
async def get_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await db.get(KnowledgeProject, project_id)
    if p is None or p.tenant_id != user.tenant_id:
        return error("Project not found", 404)

    cnt = (
        await db.scalar(
            select(func.count(KnowledgeBase.id)).where(
                KnowledgeBase.project_id == p.id,
            )
        )
        or 0
    )
    return success(_serialize_project(p, cnt))


@router.patch("/{project_id}")
async def update_project(
    project_id: uuid.UUID,
    body: UpdateProjectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await db.get(KnowledgeProject, project_id)
    if p is None or p.tenant_id != user.tenant_id:
        return error("Project not found", 404)
    if not (is_admin(user) or p.created_by == user.id):
        return error("Forbidden", 403)
    if body.name is not None:
        p.name = sanitize_input(body.name)
    if body.description is not None:
        p.description = sanitize_input(body.description)
    await db.commit()
    await db.refresh(p)
    return success(_serialize_project(p))


@router.delete("/{project_id}")
async def delete_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await db.get(KnowledgeProject, project_id)
    if p is None or p.tenant_id != user.tenant_id:
        return error("Project not found", 404)
    if not (is_admin(user) or p.created_by == user.id):
        return error("Forbidden", 403)

    # Refuse if the project still holds collections — protects from
    # accidental cascading deletes of working corpora. UI can surface
    # this as "move or delete the collections first".
    cnt = (
        await db.scalar(
            select(func.count(KnowledgeBase.id)).where(
                KnowledgeBase.project_id == p.id,
            )
        )
        or 0
    )
    if cnt > 0:
        return error(
            f"Project has {cnt} collection(s); delete or move them first",
            409,
        )
    await db.delete(p)
    await db.commit()
    return success({"deleted": True})


@router.get("/{project_id}/collections")
async def list_project_collections(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Collections inside a project, scoped to the tenant."""
    p = await db.get(KnowledgeProject, project_id)
    if p is None or p.tenant_id != user.tenant_id:
        return error("Project not found", 404)

    rows = (
        (
            await db.execute(
                select(KnowledgeBase)
                .where(
                    KnowledgeBase.project_id == project_id,
                )
                .order_by(KnowledgeBase.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    data = [
        {
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description,
            "status": kb.status.value if hasattr(kb.status, "value") else kb.status,
            "doc_count": kb.doc_count,
            "default_visibility": (
                kb.default_visibility.value
                if hasattr(kb.default_visibility, "value")
                else kb.default_visibility
            ),
            "vector_backend": kb.vector_backend,
            "created_by": str(kb.created_by) if kb.created_by else None,
            "created_at": kb.created_at.isoformat() if kb.created_at else None,
        }
        for kb in rows
    ]
    return success(data)
