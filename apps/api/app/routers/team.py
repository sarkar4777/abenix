from __future__ import annotations

import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_capability
from app.core.deps import get_current_user, get_db, require_role
from app.core.responses import error, success
from app.schemas.settings import InviteMemberRequest, UpdateMemberRoleRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.team_invite import InviteStatus, TeamInvite
from models.user import User, UserRole

router = APIRouter(prefix="/api/team", tags=["team"])

# the names Team, the invite email and the accept page all use
ROLE_LABELS = {"admin": "Admin", "creator": "Creator", "user": "Member"}


def role_label(role: str | None) -> str:
    return ROLE_LABELS.get(str(role or "user").lower(), str(role or "Member").title())


def invite_sentence(who: str, workspace: str, role: str, approves: bool) -> str:
    """One plain line for the email and the accept page, without "Abenix on Abenix"."""
    place = (
        "Abenix"
        if not workspace or workspace.strip().lower() == "abenix"
        else f"the {workspace} workspace on Abenix"
    )
    article = "an" if role_label(role)[0] in "AEIOU" else "a"
    out = f"{who} invited you to join {place} as {article} {role_label(role)}."
    if approves:
        out += " You will also be able to approve decisions."
    return out


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


def web_base_url(request: Request | None) -> str:
    import os

    base = os.environ.get("WEB_BASE_URL", "").strip()
    if not base and request is not None:
        base = (request.headers.get("origin") or "").strip()
    if not base:
        from app.core.config import settings

        base = os.environ.get("FRONTEND_URL", "") or settings.frontend_url
    return base.rstrip("/")


def invite_is_expired(inv: TeamInvite, now: datetime | None = None) -> bool:
    exp = inv.expires_at
    if exp is None:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp <= (now or datetime.now(timezone.utc))


def invite_url(request: Request | None, token: str) -> str:
    return f"{web_base_url(request)}/auth/accept-invite?token={token}"


def _serialize_invite(inv: TeamInvite, request: Request | None = None) -> dict:
    data = {
        "id": str(inv.id),
        "email": inv.email,
        "role": inv.role,
        "role_label": role_label(inv.role),
        "can_approve_decisions": bool(getattr(inv, "can_approve_decisions", False)),
        "status": (
            inv.status.value
            if isinstance(inv.status, InviteStatus)
            else str(inv.status)
        ),
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
        "expired": invite_is_expired(inv),
    }
    # the token is a credential, only callers that pass a request see the link
    if request is not None and inv.token:
        data["invite_url"] = invite_url(request, inv.token)
    return data


@router.get("/members")
async def list_members(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.approvers import can_approve_decisions, tenant_people

    result = await db.execute(
        select(User).where(User.tenant_id == user.tenant_id).order_by(User.created_at)
    )
    members = result.scalars().all()
    try:
        approvers = {
            str(u.id)
            for u, c in await tenant_people(db, user.tenant_id)
            if can_approve_decisions(c)
        }
    except Exception:  # noqa: BLE001
        approvers = set()

    inv_result = await db.execute(
        select(TeamInvite).where(
            TeamInvite.tenant_id == user.tenant_id,
            TeamInvite.status == InviteStatus.PENDING,
        )
    )
    invites = inv_result.scalars().all()

    return success(
        {
            "members": [
                {
                    **_serialize_member(m),
                    "can_approve_decisions": str(m.id) in approvers,
                }
                for m in members
            ],
            "pending_invites": [
                _serialize_invite(i, request if user.role == UserRole.ADMIN else None)
                for i in invites
            ],
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

    if os.environ.get("ALLOW_DEV_CREATE_MEMBER", "false").lower() != "true":
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
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.role not in (UserRole.ADMIN,):
        return error("Only admins can invite members", 403)

    if body.role not in ("admin", "creator", "user"):
        return error("Invalid role. Must be admin, creator, or user", 400)

    email = str(body.email).strip().lower()
    existing = await db.execute(select(User).where(func.lower(User.email) == email))
    found = existing.scalar_one_or_none()
    if found is not None:
        if found.tenant_id == user.tenant_id:
            return error("User already a member of this workspace", 409)
        # one account belongs to one workspace, the invite could never be accepted
        return error("This email already has an account in another workspace", 409)

    pending = await db.execute(
        select(TeamInvite).where(
            TeamInvite.email == email,
            TeamInvite.tenant_id == user.tenant_id,
            TeamInvite.status == InviteStatus.PENDING,
        )
    )
    prior = pending.scalar_one_or_none()
    if prior is not None:
        if not invite_is_expired(prior):
            return error("Invite already pending for this email", 409)
        prior.status = InviteStatus.EXPIRED

    invite = TeamInvite(
        tenant_id=user.tenant_id,
        invited_by=user.id,
        email=email,
        role=body.role,
        can_approve_decisions=bool(body.can_approve_decisions),
        token=secrets.token_urlsafe(32),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    data = _serialize_invite(invite, request)
    data["emailed"] = await _email_invite(db, invite, user, data.get("invite_url", ""))
    return success(data, status_code=201)


async def _email_invite(
    db: AsyncSession, invite: TeamInvite, inviter: User, link: str
) -> bool:
    from html import escape

    from app.core import mailer
    from models.tenant import Tenant

    if not link or not mailer.available():
        return False
    tenant = await db.get(Tenant, invite.tenant_id)
    workspace = tenant.name if tenant else ""
    who = inviter.full_name or inviter.email
    line = invite_sentence(
        who,
        workspace,
        invite.role,
        bool(getattr(invite, "can_approve_decisions", False)),
    )
    text = (
        f"{line}\n\n"
        f"Accept the invite and choose your password here:\n\n{link}\n\n"
        "The link works for 7 days.\n"
    )
    html = (
        f"<p>{escape(line)}</p>"
        f'<p><a href="{escape(link)}">Accept the invite</a></p>'
        "<p>The link works for 7 days.</p>"
    )
    place = (
        "Abenix"
        if not workspace or workspace.strip().lower() == "abenix"
        else f"{workspace} on Abenix"
    )
    return await mailer.send(
        to=invite.email,
        subject=f"{who} invited you to {place}",
        text=text,
        html=html,
    )


class ApproverRequest(BaseModel):
    can_approve_decisions: bool


@router.put("/{member_id}/approver")
async def set_approver(
    member_id: uuid.UUID,
    body: ApproverRequest,
    request: Request,
    user: User = Depends(require_capability("permissions.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Add someone to Decision reviewers, or take them out, from the Team page."""
    from app.core import capabilities as caps
    from app.core.approvers import (
        REVIEWERS_NAME,
        add_decision_reviewer,
        can_approve_decisions,
        decision_approvers,
        real_person,
        remove_decision_reviewer,
        tenant_people,
    )
    from app.core.audit import log_action

    member = await db.get(User, member_id)
    if member is None or member.tenant_id != user.tenant_id:
        return error("Member not found", 404)
    if body.can_approve_decisions and (not member.is_active or not real_person(member)):
        return error(
            "Only an active member of this workspace can approve decisions.", 400
        )
    if body.can_approve_decisions:
        changed = await add_decision_reviewer(db, user.tenant_id, member.id, by=user.id)
        action = "permission_set.member_added"
    else:
        changed = await remove_decision_reviewer(db, user.tenant_id, member.id)
        action = "permission_set.member_removed"
    if changed:
        await log_action(
            db,
            user.tenant_id,
            user.id,
            action,
            {"set": REVIEWERS_NAME, "member": member.email, "from": "team"},
            request,
            resource_type="permission_set",
            resource_id=REVIEWERS_NAME,
        )
    await db.commit()
    caps.invalidate(member.id)
    people = await tenant_people(db, user.tenant_id)
    mine = next((c for u, c in people if u.id == member.id), frozenset())
    approvers = decision_approvers(people)
    out: dict[str, Any] = {
        "user_id": str(member.id),
        "changed": changed,
        "can_approve_decisions": can_approve_decisions(mine),
        "approver_count": len(approvers),
        "warning": None,
    }
    if not body.can_approve_decisions and out["can_approve_decisions"]:
        out["warning"] = (
            f"{member.full_name or member.email} can still approve decisions through their role "
            "or another permission set."
        )
    elif not body.can_approve_decisions and len(approvers) <= 1:
        who = "Nobody" if not approvers else "Only one person"
        out["warning"] = (
            f"{who} in this workspace can approve decisions now. High-risk changes will need "
            "a sole-operator sign-off or a new approver."
        )
    return success(out)


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
    from app.core import capabilities as caps

    caps.invalidate(member.id)
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
    from app.core import capabilities as caps

    caps.invalidate(member.id)

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


def quota_value(
    body: dict, key: str, *, whole: bool
) -> tuple[float | int | None, str | None]:
    """The limit to store, None for no limit, or why the value is unusable."""
    label = "The token limit" if whole else "The cost limit"
    raw = body.get(key)
    if raw is None or raw == "":
        return None, None
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return None, f"{label} must be a number, or blank for no limit"
    if num != num or num < 0:
        return None, f"{label} cannot be negative"
    if whole:
        if num != int(num):
            return None, f"{label} must be a whole number of tokens"
        return int(num), None
    return round(num, 2), None


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

    tokens, problem = quota_value(body, "token_monthly_allowance", whole=True)
    if problem:
        return error(problem, 400)
    cost, problem = quota_value(body, "cost_monthly_limit", whole=False)
    if problem:
        return error(problem, 400)
    if "token_monthly_allowance" in body:
        member.token_monthly_allowance = tokens
    if "cost_monthly_limit" in body:
        member.cost_monthly_limit = cost

    await db.commit()

    return success(
        {
            "id": str(member.id),
            "email": member.email,
            "token_monthly_allowance": member.token_monthly_allowance,
            "cost_monthly_limit": (
                float(member.cost_monthly_limit)
                if member.cost_monthly_limit is not None
                else None
            ),
            "tokens_used": member.tokens_used_this_month or 0,
            "cost_used": float(member.cost_used_this_month or 0),
        }
    )
