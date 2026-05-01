"""Tool Library — Save, browse, approve, and manage custom AI-generated tools."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from models.saved_tool import SavedTool
from models.user import User, UserRole

router = APIRouter(prefix="/api/tools", tags=["tool-library"])


class SaveToolRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: str = Field(..., min_length=5, max_length=2000)
    code: str = Field(..., min_length=10, max_length=50000)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: dict[str, Any] = Field(default_factory=lambda: {
        "network": False, "filesystem_read": False,
        "filesystem_write": False, "third_party": [], "env_vars": [],
    })
    review_score: float | None = None


class ApproveRejectRequest(BaseModel):
    notes: str = ""


@router.post("/save")
async def save_tool(
    body: SaveToolRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Save an AI-generated tool to the library (status: pending approval)."""
    from engine.tools.dynamic_tool import validate_code

    # Validate code safety
    errors = validate_code(body.code)
    if errors:
        return error(f"Code validation failed: {'; '.join(errors)}", 400)

    # Check for duplicate name
    existing = await db.execute(
        select(SavedTool).where(
            SavedTool.tenant_id == user.tenant_id,
            SavedTool.name == body.name,
        )
    )
    if existing.scalar_one_or_none():
        return error(f"Tool '{body.name}' already exists in your library", 409)

    tool = SavedTool(
        tenant_id=user.tenant_id,
        name=body.name,
        description=body.description,
        code=body.code,
        input_schema=body.input_schema,
        created_by=user.id,
        status="pending",
        permissions=body.permissions,
        review_score=body.review_score,
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)

    return success({
        "id": str(tool.id),
        "name": tool.name,
        "status": tool.status,
    })


@router.get("/library")
async def list_tools(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> JSONResponse:
    """List saved tools in the library."""
    query = select(SavedTool).where(SavedTool.tenant_id == user.tenant_id)
    if status:
        query = query.where(SavedTool.status == status)
    if search:
        query = query.where(
            or_(
                SavedTool.name.ilike(f"%{search}%"),
                SavedTool.description.ilike(f"%{search}%"),
            )
        )
    query = query.order_by(SavedTool.created_at.desc()).limit(limit)

    result = await db.execute(query)
    tools = result.scalars().all()

    return success([{
        "id": str(t.id),
        "name": t.name,
        "description": t.description,
        "status": t.status,
        "is_public": t.is_public,
        "usage_count": t.usage_count,
        "review_score": t.review_score,
        "permissions": t.permissions,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    } for t in tools])


@router.get("/library/{tool_id}")
async def get_tool(
    tool_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get full tool detail including code."""
    result = await db.execute(
        select(SavedTool).where(
            SavedTool.id == tool_id,
            SavedTool.tenant_id == user.tenant_id,
        )
    )
    tool = result.scalar_one_or_none()
    if not tool:
        return error("Tool not found", 404)

    return success({
        "id": str(tool.id),
        "name": tool.name,
        "description": tool.description,
        "code": tool.code,
        "input_schema": tool.input_schema,
        "status": tool.status,
        "is_public": tool.is_public,
        "usage_count": tool.usage_count,
        "review_score": tool.review_score,
        "review_notes": tool.review_notes,
        "permissions": tool.permissions,
        "created_by": str(tool.created_by),
        "approved_by": str(tool.approved_by) if tool.approved_by else None,
        "created_at": tool.created_at.isoformat() if tool.created_at else None,
    })


@router.post("/library/{tool_id}/approve")
async def approve_tool(
    tool_id: str,
    body: ApproveRejectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Admin approves a pending tool — makes it available in the tool registry."""
    if user.role != UserRole.ADMIN:
        return error("Only admins can approve tools", 403)

    result = await db.execute(
        select(SavedTool).where(
            SavedTool.id == tool_id,
            SavedTool.tenant_id == user.tenant_id,
        )
    )
    tool = result.scalar_one_or_none()
    if not tool:
        return error("Tool not found", 404)

    tool.status = "approved"
    tool.approved_by = user.id
    tool.review_notes = body.notes or "Approved by admin"
    await db.commit()

    return success({"approved": True, "tool_id": str(tool.id)})


@router.post("/library/{tool_id}/reject")
async def reject_tool(
    tool_id: str,
    body: ApproveRejectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Admin rejects a pending tool with reason."""
    if user.role != UserRole.ADMIN:
        return error("Only admins can reject tools", 403)

    result = await db.execute(
        select(SavedTool).where(
            SavedTool.id == tool_id,
            SavedTool.tenant_id == user.tenant_id,
        )
    )
    tool = result.scalar_one_or_none()
    if not tool:
        return error("Tool not found", 404)

    tool.status = "rejected"
    tool.review_notes = body.notes or "Rejected by admin"
    await db.commit()

    return success({"rejected": True, "tool_id": str(tool.id)})


@router.delete("/library/{tool_id}")
async def delete_tool(
    tool_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Delete a saved tool."""
    result = await db.execute(
        select(SavedTool).where(
            SavedTool.id == tool_id,
            SavedTool.tenant_id == user.tenant_id,
        )
    )
    tool = result.scalar_one_or_none()
    if not tool:
        return error("Tool not found", 404)

    await db.delete(tool)
    await db.commit()

    return success({"deleted": True})
