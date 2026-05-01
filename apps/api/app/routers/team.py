from __future__ import annotations

import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_role
from app.core.responses import error, success
from app.schemas.settings import InviteMemberRequest, UpdateMemberRoleRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.team_invite import InviteStatus, TeamInvite
from models.user import User, UserRole

router = APIRouter(prefix="/api/team", tags=["team"])


def _serialize_member(u: User) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "full_name": u.full_name,
        "avatar_url": u.avatar_url,
        "role": u.role.value,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _serialize_invite(inv: TeamInvite) -> dict:
    return {
        "id": str(inv.id),
        "email": inv.email,
        "role": inv.role,
        "status": (
            inv.status.value
            if isinstance(inv.status, InviteStatus)
            else str(inv.status)
        ),
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
    }


@router.get("/members")
async def list_members(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(User).where(User.tenant_id == user.tenant_id).order_by(User.created_at)
    )
    members = result.scalars().all()

    inv_result = await db.execute(
        select(TeamInvite).where(
            TeamInvite.tenant_id == user.tenant_id,
            TeamInvite.status == InviteStatus.PENDING,
        )
    )
    invites = inv_result.scalars().all()

    return success(
        {
            "members": [_serialize_member(m) for m in members],
            "pending_invites": [_serialize_invite(i) for i in invites],
        }
    )


@router.post("/dev-create-member")
async def dev_create_member(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Admin-only: synchronously create a member in the caller's tenant."""
    import os

    if os.environ.get("ALLOW_DEV_CREATE_MEMBER", "true").lower() != "true":
        return error("dev-create-member is disabled in this environment", 403)
    if user.role not in (UserRole.ADMIN,):
        return error("Only admins can create members", 403)

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    role_str = (body.get("role") or "user").strip().lower()
    if not email or not password:
        return error("email and password are required", 400)
    if role_str not in ("admin", "creator", "user"):
        return error("role must be admin, creator, or user", 400)

    # Idempotent — return 409 if the member already exists in this
    # tenant so callers don't accidentally double-create.
    existing = await db.execute(
        select(User).where(User.email == email, User.tenant_id == user.tenant_id)
    )
    if existing.scalar_one_or_none():
        return error("member already exists", 409)

    from app.core.security import hash_password

    new_user = User(
        tenant_id=user.tenant_id,
        email=email,
        password_hash=hash_password(password),
        full_name=email.split("@")[0],
        role=UserRole(role_str),
        is_active=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return success(_serialize_member(new_user), status_code=201)


@router.post("/invite")
async def invite_member(
    body: InviteMemberRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.role not in (UserRole.ADMIN,):
        return error("Only admins can invite members", 403)

    if body.role not in ("admin", "creator", "user"):
        return error("Invalid role. Must be admin, creator, or user", 400)

    existing = await db.execute(
        select(User).where(User.email == body.email, User.tenant_id == user.tenant_id)
    )
    if existing.scalar_one_or_none():
        return error("User already a member of this workspace", 409)

    pending = await db.execute(
        select(TeamInvite).where(
            TeamInvite.email == body.email,
            TeamInvite.tenant_id == user.tenant_id,
            TeamInvite.status == InviteStatus.PENDING,
        )
    )
    if pending.scalar_one_or_none():
        return error("Invite already pending for this email", 409)

    invite = TeamInvite(
        tenant_id=user.tenant_id,
        invited_by=user.id,
        email=body.email,
        role=body.role,
        token=secrets.token_urlsafe(32),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    return success(_serialize_invite(invite), status_code=201)


@router.put("/members/{member_id}/role")
async def update_member_role(
    member_id: uuid.UUID,
    body: UpdateMemberRoleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.role not in (UserRole.ADMIN,):
        return error("Only admins can change roles", 403)

    if body.role not in ("admin", "creator", "user"):
        return error("Invalid role", 400)

    if member_id == user.id:
        return error("Cannot change your own role", 400)

    result = await db.execute(
        select(User).where(
            User.id == member_id,
            User.tenant_id == user.tenant_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        return error("Member not found", 404)

    member.role = UserRole(body.role)
    await db.commit()
    await db.refresh(member)

    return success(_serialize_member(member))


@router.delete("/members/{member_id}")
async def remove_member(
    member_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.role not in (UserRole.ADMIN,):
        return error("Only admins can remove members", 403)

    if member_id == user.id:
        return error("Cannot remove yourself", 400)

    result = await db.execute(
        select(User).where(
            User.id == member_id,
            User.tenant_id == user.tenant_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        return error("Member not found", 404)

    member.is_active = False
    await db.commit()

    return success({"id": str(member.id), "status": "removed"})


@router.delete("/invites/{invite_id}")
async def cancel_invite(
    invite_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(TeamInvite).where(
            TeamInvite.id == invite_id,
            TeamInvite.tenant_id == user.tenant_id,
            TeamInvite.status == InviteStatus.PENDING,
        )
    )
    invite = result.scalar_one_or_none()
    if not invite:
        return error("Invite not found", 404)

    invite.status = InviteStatus.EXPIRED
    await db.commit()

    return success({"id": str(invite.id), "status": "cancelled"})


@router.put("/members/{member_id}/quota")
async def set_member_quota(
    member_id: uuid.UUID,
    body: dict,
    request: Request,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Admin-only: set token and cost quotas for a team member."""
    result = await db.execute(
        select(User).where(User.id == member_id, User.tenant_id == user.tenant_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        return error("Member not found", 404)

    if "token_monthly_allowance" in body:
        val = body["token_monthly_allowance"]
        member.token_monthly_allowance = int(val) if val is not None else None
    if "cost_monthly_limit" in body:
        val = body["cost_monthly_limit"]
        member.cost_monthly_limit = float(val) if val is not None else None

    await db.commit()

    return success(
        {
            "id": str(member.id),
            "email": member.email,
            "token_monthly_allowance": member.token_monthly_allowance,
            "cost_monthly_limit": (
                float(member.cost_monthly_limit) if member.cost_monthly_limit else None
            ),
            "tokens_used": member.tokens_used_this_month or 0,
            "cost_used": float(member.cost_used_this_month or 0),
        }
    )
