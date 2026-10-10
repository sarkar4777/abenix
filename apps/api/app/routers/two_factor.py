"""Two-step sign-in: turn it on with an authenticator app, sign in with a code, turn it off."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import totp, two_factor
from app.core.audit import log_action
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.core.security import verify_password

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.user import User

router = APIRouter(prefix="/api/settings/2fa", tags=["settings"])


class SetupRequest(BaseModel):
    password: str = ""


class CodeRequest(BaseModel):
    code: str


class DisableRequest(BaseModel):
    password: str = ""
    code: str


def _status(user: User) -> dict:
    return {
        "enabled": bool(user.totp_enabled_at),
        "enabled_at": (
            user.totp_enabled_at.isoformat() if user.totp_enabled_at else None
        ),
        "recovery_codes_left": len(user.totp_recovery_codes or []),
        "has_password": bool(user.password_hash),
    }


def _password_ok(user: User, password: str) -> bool:
    # SSO-only accounts have nothing to re-enter
    return not user.password_hash or verify_password(password, user.password_hash)


@router.get("")
async def get_status(user: User = Depends(get_current_user)) -> JSONResponse:
    return success(_status(user))


@router.post("/setup")
async def setup(
    body: SetupRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.totp_enabled_at:
        return error(
            "Two-step sign-in is already on. Turn it off first to move it to a new app.",
            409,
        )
    if not _password_ok(user, body.password):
        return error("Your password is not right", 400)
    secret = totp.new_secret()
    two_factor.store_secret(user, secret)
    user.totp_last_step = None
    await db.commit()
    uri = totp.otpauth_uri(secret, user.email)
    return success(
        {
            "secret": secret,
            "otpauth_uri": uri,
            "qr_svg": two_factor.qr_svg_data_uri(uri),
        }
    )


@router.post("/enable")
async def enable(
    body: CodeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.totp_enabled_at:
        return error("Two-step sign-in is already on", 409)
    secret = two_factor.secret_of(user)
    if not secret:
        return error("Start again: press Set up two-step sign-in first", 400)
    step = totp.verify(secret, body.code)
    if step is None:
        return error(
            "That code did not match. Check the clock on your phone and type the newest code.",
            400,
        )
    user.totp_last_step = step
    user.totp_enabled_at = datetime.now(timezone.utc)
    codes = two_factor.issue_recovery_codes(user)
    await log_action(db, user.tenant_id, user.id, "2fa.enabled", None, request)
    await db.commit()
    return success({**_status(user), "recovery_codes": codes})


@router.post("/disable")
async def disable(
    body: DisableRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not user.totp_enabled_at:
        return error("Two-step sign-in is already off", 409)
    if not _password_ok(user, body.password):
        return error("Your password is not right", 400)
    if two_factor.check_code(user, body.code) is None:
        return error("That code did not match", 400)
    user.totp_enabled_at = None
    user.totp_secret = None
    user.totp_last_step = None
    user.totp_recovery_codes = None
    await log_action(db, user.tenant_id, user.id, "2fa.disabled", None, request)
    await db.commit()
    return success(_status(user))


@router.post("/recovery-codes")
async def new_recovery_codes(
    body: CodeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not user.totp_enabled_at:
        return error("Turn on two-step sign-in first", 409)
    if two_factor.check_code(user, body.code) is None:
        return error("That code did not match", 400)
    codes = two_factor.issue_recovery_codes(user)
    await log_action(db, user.tenant_id, user.id, "2fa.recovery_codes", None, request)
    await db.commit()
    return success({**_status(user), "recovery_codes": codes})
