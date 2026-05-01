"""Workspace CRUD — sub-tenant isolation boundaries.

Endpoints: POST/GET/PUT/DELETE /api/workspaces
"""

from __future__ import annotations

import re
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

from models.user import User
from models.workspace import Workspace

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


@router.get("")
async def list_workspaces(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(Workspace).where(Workspace.tenant_id == user.tenant_id)
    )
    workspaces = result.scalars().all()
    return success(
        [
            {
                "id": str(ws.id),
                "name": ws.name,
                "slug": ws.slug,
                "description": ws.description,
                "is_default": ws.is_default,
                "settings": ws.settings,
                "created_at": ws.created_at.isoformat() if ws.created_at else None,
            }
            for ws in workspaces
        ]
    )


@router.post("")
async def create_workspace(
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    name = body.get("name", "").strip()
    if not name:
        return error("Workspace name is required", 400)

    ws = Workspace(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        name=name,
        slug=_slugify(name) + "-" + uuid.uuid4().hex[:6],
        description=body.get("description"),
        settings=body.get("settings"),
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)

    return success(
        {
            "id": str(ws.id),
            "name": ws.name,
            "slug": ws.slug,
            "description": ws.description,
            "is_default": ws.is_default,
        },
        status_code=201,
    )


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == user.tenant_id,
        )
    )
    ws = result.scalar_one_or_none()
    if not ws:
        return error("Workspace not found", 404)

    return success(
        {
            "id": str(ws.id),
            "name": ws.name,
            "slug": ws.slug,
            "description": ws.description,
            "is_default": ws.is_default,
            "settings": ws.settings,
        }
    )


@router.put("/{workspace_id}")
async def update_workspace(
    workspace_id: uuid.UUID,
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == user.tenant_id,
        )
    )
    ws = result.scalar_one_or_none()
    if not ws:
        return error("Workspace not found", 404)

    if body.get("name"):
        ws.name = body["name"]
    if body.get("description") is not None:
        ws.description = body["description"]
    if body.get("settings") is not None:
        ws.settings = body["settings"]

    await db.commit()
    return success({"id": str(ws.id), "name": ws.name, "updated": True})


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == user.tenant_id,
        )
    )
    ws = result.scalar_one_or_none()
    if not ws:
        return error("Workspace not found", 404)
    if ws.is_default:
        return error("Cannot delete the default workspace", 400)

    await db.delete(ws)
    await db.commit()
    return success({"deleted": True})
