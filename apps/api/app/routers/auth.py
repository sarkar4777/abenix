import hashlib
import re
import uuid
from html import escape as html_escape

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.core import sessions
from app.core.security import (
    create_access_token,
    create_purpose_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.moderation_policy import ModerationAction, ModerationPolicy
from models.team_invite import InviteStatus, TeamInvite
from models.tenant import Tenant, TenantPlan
from models.user import User, UserRole

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _user_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "role": user.role.value,
        "tenant_id": str(user.tenant_id),
    }


@router.post("/register")
async def register(
    body: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    from app.routers.settings import password_problem

    if not (body.full_name or "").strip():
        return error("Full name is required", 400)
    problem = password_problem(body.password)
    if problem:
        return error(problem, 400)
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        return error("Email already registered", 409)

    # Honour caller-supplied tenant_name / plan; fall back to the legacy
    # derivation so existing {email, password, full_name}-only callers keep
    # working.
    tenant_name = (body.tenant_name or "").strip() or f"{body.full_name}'s Workspace"
    slug_seed = body.tenant_name.strip() if body.tenant_name else body.full_name
    plan_value = (body.plan or "free").strip().lower()
    try:
        tenant_plan = TenantPlan(plan_value)
    except ValueError:
        tenant_plan = TenantPlan.FREE

    tenant = Tenant(
        id=uuid.uuid4(),
        name=tenant_name,
        slug=_slugify(f"{slug_seed}-{uuid.uuid4().hex[:6]}"),
        plan=tenant_plan,
    )
    db.add(tenant)
    await db.flush()

    user = User(
        id=uuid.uuid4(),
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=UserRole.ADMIN,
        tenant_id=tenant.id,
    )
    db.add(user)
    await db.flush()

    # Seed a default moderation policy so the gate is wired the moment a
    # tenant exists. Categories with no explicit action fall back to BLOCK
    # at threshold 0.5; admins can soften per-category from /moderation.
    # Custom patterns: ship the canonical PII regex set so SSN / credit
    # card / API-key style input is blocked at execute-time without any
    # tenant configuration. Otherwise Bug #2 reproduces every fresh tenant.
    from app.core.moderation_glue import DEFAULT_PII_PATTERNS

    policy = ModerationPolicy(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Default Policy",
        description="Auto-seeded on tenant creation. Edit at /moderation.",
        is_active=True,
        pre_llm=True,
        post_llm=True,
        on_tool_output=False,
        provider="openai",
        provider_model="omni-moderation-latest",
        thresholds={},
        default_threshold=0.5,
        category_actions={},
        default_action=ModerationAction.BLOCK,
        custom_patterns=list(DEFAULT_PII_PATTERNS),
        redaction_mask="█████",
        # Not fail-closed by default. The seeded provider is OpenAI, and on a
        # deployment with no OpenAI credential every provider call errors —
        # fail_closed then escalated that to a hard block, so 100% of agent
        # requests were refused with no category to explain it. The custom
        # pattern checks (PII, secrets) need no provider and still apply.
        # Strict mode stays available as an explicit opt-in at /moderation.
        fail_closed=False,
        created_by=user.id,
    )
    db.add(policy)
    from app.core.approvers import ensure_decision_reviewers

    await ensure_decision_reviewers(db, tenant.id)
    await db.commit()
    await db.refresh(user)

    await log_action(
        db, tenant.id, user.id, "user.registered", {"email": user.email}, request
    )
    await db.commit()

    pair = await sessions.sign_in(db, user, request, "password")
    return success({**pair, "user": _user_dict(user)}, status_code=201)


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        return error("Invalid email or password", 401)

    if not user.is_active:
        return error("Account is disabled", 403)

    if user.totp_enabled_at and user.totp_secret:
        # the password was right, the code from the app comes next
        challenge = create_purpose_token(
            user.id, "2fa_challenge", TWO_FACTOR_CHALLENGE_MINUTES
        )
        return success(
            {
                "two_factor_required": True,
                "challenge": challenge,
                "email": user.email,
            }
        )

    await log_action(db, user.tenant_id, user.id, "user.login", None, request)
    await db.commit()

    pair = await sessions.sign_in(db, user, request, "password")
    return success({**pair, "user": _user_dict(user)})


TWO_FACTOR_CHALLENGE_MINUTES = 5
CHALLENGE_GONE = "This sign-in took too long. Enter your password again."


class TwoFactorLoginRequest(BaseModel):
    challenge: str
    code: str


@router.post("/login/2fa")
async def login_two_factor(
    body: TwoFactorLoginRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    from app.core import two_factor

    payload = verify_token(body.challenge)
    if payload.get("type") != "2fa_challenge" or not payload.get("sub"):
        return error(CHALLENGE_GONE, 401)
    try:
        uid = uuid.UUID(payload["sub"])
    except ValueError:
        return error(CHALLENGE_GONE, 401)
    user = (
        await db.execute(select(User).where(User.id == uid, User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None or not user.totp_enabled_at:
        return error(CHALLENGE_GONE, 401)

    how = two_factor.check_code(user, body.code)
    if how is None:
        await log_action(db, user.tenant_id, user.id, "user.2fa_failed", None, request)
        await db.commit()
        return error(
            "That code did not match. Use the newest code from your app, or a recovery code.",
            401,
        )
    await log_action(
        db, user.tenant_id, user.id, "user.login", {"second_step": how}, request
    )
    await db.commit()
    pair = await sessions.sign_in(db, user, request, "password+2fa")
    return success({**pair, "user": _user_dict(user)})


RESET_MINUTES = 30


def password_fingerprint(user: User) -> str:
    """Changes whenever the password does, so a used reset link stops working."""
    return hashlib.sha256((user.password_hash or "none").encode()).hexdigest()[:16]


def reset_email(name: str, link: str) -> tuple[str, str]:
    text = (
        f"Hi {name},\n\n"
        "Someone asked to reset the password for your Abenix account. "
        f"Open this link within {RESET_MINUTES} minutes to choose a new one:\n\n"
        f"{link}\n\n"
        "The link works once. If you did not ask for this, ignore this email "
        "and your password stays the same.\n"
    )
    html = (
        f"<p>Hi {html_escape(name)},</p><p>Someone asked to reset the password for your "
        f"Abenix account. Open this link within {RESET_MINUTES} minutes to choose a new one:</p>"
        f'<p><a href="{html_escape(link)}">Choose a new password</a></p>'
        "<p>The link works once. If you did not ask for this, ignore this email "
        "and your password stays the same.</p>"
    )
    return text, html


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    from app.core import mailer

    email = str(body.email).strip().lower()
    user = (
        await db.execute(select(User).where(func.lower(User.email) == email))
    ).scalar_one_or_none()
    if user is not None and user.is_active and mailer.available():
        token = create_purpose_token(
            user.id, "password_reset", RESET_MINUTES, pwf=password_fingerprint(user)
        )
        link = mailer.frontend_url(f"/auth/reset?token={token}")
        name = (user.full_name or "").split(" ")[0] or "there"
        text, html = reset_email(name, link)
        await mailer.send(
            to=user.email, subject="Reset your Abenix password", text=text, html=html
        )
        await log_action(
            db, user.tenant_id, user.id, "password.reset_requested", None, request
        )
        await db.commit()
    # the same answer whether or not the account exists
    return success(
        {"sent": True, "email_enabled": mailer.available(), "minutes": RESET_MINUTES}
    )


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    from app.core import principal
    from app.routers.settings import password_problem

    expired = "This reset link has expired or was already used. Ask for a new one."
    payload = verify_token(body.token)
    if payload.get("type") != "password_reset" or not payload.get("sub"):
        return error(expired, 400)
    try:
        uid = uuid.UUID(payload["sub"])
    except ValueError:
        return error(expired, 400)
    user = (
        await db.execute(select(User).where(User.id == uid, User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None or payload.get("pwf") != password_fingerprint(user):
        return error(expired, 400)
    problem = password_problem(body.new_password)
    if problem:
        return error(problem, 400)

    user.password_hash = hash_password(body.new_password)
    signed_out = await sessions.revoke(db, user.id, reason="password_reset")
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "password.reset",
        {"sessions_signed_out": signed_out},
        request,
    )
    await db.commit()
    principal.forget(user.id)
    return success({"reset": True, "email": user.email})


class AcceptInviteRequest(BaseModel):
    token: str
    full_name: str
    password: str


MIN_PASSWORD_LEN = 8


async def _load_invite(db: AsyncSession, token: str) -> TeamInvite | None:
    if not token or len(token) > 255:
        return None
    result = await db.execute(select(TeamInvite).where(TeamInvite.token == token))
    return result.scalar_one_or_none()


def _invite_problem(invite: TeamInvite | None) -> tuple[str, int] | None:
    from app.routers.team import invite_is_expired

    if invite is None:
        return "Invite not found", 404
    status = (
        invite.status.value
        if isinstance(invite.status, InviteStatus)
        else str(invite.status)
    )
    if status == InviteStatus.ACCEPTED.value:
        return "This invite has already been used", 410
    if status != InviteStatus.PENDING.value or invite_is_expired(invite):
        return "This invite has expired, ask an admin for a new one", 410
    return None


@router.get("/invite/{token}")
async def get_invite(token: str, db: AsyncSession = Depends(get_db)):
    from app.routers.team import invite_is_expired

    invite = await _load_invite(db, token)
    if invite is None:
        return error("Invite not found", 404)
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == invite.tenant_id))
    ).scalar_one_or_none()
    status = (
        invite.status.value
        if isinstance(invite.status, InviteStatus)
        else str(invite.status)
    )
    from app.routers.team import invite_sentence, role_label

    inviter = await db.get(User, invite.invited_by) if invite.invited_by else None
    approves = bool(getattr(invite, "can_approve_decisions", False))
    return success(
        {
            "email": invite.email,
            "tenant_name": tenant.name if tenant else "",
            "role": invite.role,
            "role_label": role_label(invite.role),
            "can_approve_decisions": approves,
            "message": invite_sentence(
                (inviter.full_name or inviter.email) if inviter else "An admin",
                tenant.name if tenant else "",
                invite.role,
                approves,
            ),
            "status": status,
            "expired": status == InviteStatus.EXPIRED.value
            or (status == InviteStatus.PENDING.value and invite_is_expired(invite)),
            "used": status == InviteStatus.ACCEPTED.value,
        }
    )


@router.post("/accept-invite")
async def accept_invite(
    body: AcceptInviteRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    invite = await _load_invite(db, body.token.strip())
    problem = _invite_problem(invite)
    if problem:
        return error(*problem)

    full_name = body.full_name.strip()
    if not full_name:
        return error("Full name is required", 400)
    if len(body.password) < MIN_PASSWORD_LEN:
        return error(f"Password must be at least {MIN_PASSWORD_LEN} characters", 400)

    email = invite.email.strip().lower()
    existing = await db.execute(select(User).where(func.lower(User.email) == email))
    if existing.scalar_one_or_none():
        return error("An account with this email already exists, sign in instead", 409)

    try:
        role = UserRole(str(invite.role or "user").lower())
    except ValueError:
        role = UserRole.USER

    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(body.password),
        full_name=full_name,
        role=role,
        tenant_id=invite.tenant_id,
        is_active=True,
    )
    db.add(user)
    invite.status = InviteStatus.ACCEPTED
    await db.flush()
    if getattr(invite, "can_approve_decisions", False):
        from app.core.approvers import add_decision_reviewer

        await add_decision_reviewer(db, invite.tenant_id, user.id, by=invite.invited_by)
    await db.commit()
    await db.refresh(user)

    await log_action(
        db,
        invite.tenant_id,
        user.id,
        "user.invite_accepted",
        {
            "email": user.email,
            "invite_id": str(invite.id),
            "role": role.value,
            "can_approve_decisions": bool(
                getattr(invite, "can_approve_decisions", False)
            ),
        },
        request,
    )
    await db.commit()

    pair = await sessions.sign_in(db, user, request, "invite")
    return success({**pair, "user": _user_dict(user)}, status_code=201)


async def _rt_denylist_threshold(user_id: uuid.UUID) -> int:
    try:
        import os as _os

        import redis.asyncio as aioredis

        url = _os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r = aioredis.from_url(url, decode_responses=True)
        v = await r.get(f"auth:rt_revoke_before:{user_id}")
        await r.aclose()
        return int(v) if v else 0
    except Exception:
        return 0


@router.post("/refresh")
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = verify_token(body.refresh_token)
    sub = payload.get("sub")
    if not sub or payload.get("type") != "refresh":
        return error("Invalid refresh token", 401)

    try:
        user_id = uuid.UUID(sub)
    except ValueError:
        return error("Invalid refresh token", 401)

    sid = payload.get("sid")
    if sid:
        if not await sessions.is_live(db, sid, user_id):
            return error("You were signed out. Sign in again.", 401)
    else:
        rt_iat = int(payload.get("iat", 0) or 0)
        revoke_before = await _rt_denylist_threshold(user_id)
        if rt_iat and revoke_before and rt_iat < revoke_before:
            return error("Refresh token revoked", 401)

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user:
        return error("User not found", 401)

    access = create_access_token(user.id, user.tenant_id, user.role.value, sid=sid)

    return success(
        {
            "access_token": access,
            "token_type": "bearer",
        }
    )


@router.post("/logout")
async def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import time as _time

    sid = getattr(user, "_session_id", None)
    if sid:
        from app.core import principal

        # ends this device only, its access and refresh tokens stop working now
        await sessions.revoke(db, user.id, sid=sid, reason="signed_out")
        await log_action(db, user.tenant_id, user.id, "logout", None, request)
        await db.commit()
        principal.forget(user.id)
        return success({"logged_out": True})

    try:
        import os as _os

        import redis.asyncio as aioredis

        url = _os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r = aioredis.from_url(url, decode_responses=True)
        await r.set(
            f"auth:rt_revoke_before:{user.id}",
            str(int(_time.time())),
            ex=60 * 60 * 24 * 90,
        )
        await r.aclose()
    except Exception:
        pass
    return success({"logged_out": True})


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return success({"user": _user_dict(user)})
