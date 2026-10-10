from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.core.security import hash_password, verify_password
from app.schemas.settings import (
    ChangePasswordRequest,
    NotificationSettingsRequest,
    UpdateProfileRequest,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.activity_log import ActivityLog
from models.tenant import Tenant
from models.user import User, UserRole

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _user_profile(u: User) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "full_name": u.full_name,
        "avatar_url": u.avatar_url,
        "role": u.role.value,
        "tenant_id": str(u.tenant_id),
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.get("/profile")
async def get_profile(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    return success(_user_profile(user))


AVATAR_MAX_BYTES = 2 * 1024 * 1024
# Magic bytes per accepted picture type, SVG is left out on purpose
_AVATAR_TYPES = {
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "gif": ("image/gif", (b"GIF87a", b"GIF89a")),
    "webp": ("image/webp", (b"RIFF",)),
}
_AVATAR_PATH = re.compile(
    r"^/api/settings/avatars/([0-9a-f-]{36})/([0-9a-f]{32})\.(png|jpg|gif|webp)$"
)
_URL_BAD_CHARS = re.compile(r"[\s<>\"'`]")


def avatar_kind(head: bytes) -> str | None:
    for ext, (_, sigs) in _AVATAR_TYPES.items():
        if any(head.startswith(sig) for sig in sigs):
            if ext == "webp" and head[8:12] != b"WEBP":
                continue
            return ext
    return None


def check_avatar_url(raw: str | None, user_id: str) -> tuple[str | None, str | None]:
    """Returns (value to store, error). Empty means clear the picture."""
    value = (raw or "").strip()
    if not value:
        return None, None
    if len(value) > 500:
        return None, "The picture link is too long. Use one under 500 characters."
    m = _AVATAR_PATH.match(value)
    if m:
        if m.group(1) != user_id:
            return None, "That picture belongs to another account. Upload your own."
        return value, None
    parsed = urlparse(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or _URL_BAD_CHARS.search(value)
    ):
        return None, "Enter a full picture link that starts with https://"
    return value, None


async def _drop_uploaded_avatar(url: str | None) -> None:
    m = _AVATAR_PATH.match(url or "")
    if not m:
        return
    try:
        from app.core.object_storage import get_object_storage

        await get_object_storage().delete(
            f"avatars/{m.group(1)}/{m.group(2)}.{m.group(3)}"
        )
    except Exception:
        pass


@router.put("/profile")
async def update_profile(
    body: UpdateProfileRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    sent = body.model_fields_set
    details: dict = {}
    if "full_name" in sent:
        name = (body.full_name or "").strip()
        if not name:
            return error("Enter your name.", 400, details={"field": "full_name"})
        if len(name) > 255:
            return error(
                "Your name is too long. Use 255 characters or fewer.",
                400,
                details={"field": "full_name"},
            )
        user.full_name = name
        details["full_name"] = name
    old_avatar = user.avatar_url
    if "avatar_url" in sent:
        url, problem = check_avatar_url(body.avatar_url, str(user.id))
        if problem:
            return error(problem, 400, details={"field": "avatar_url"})
        user.avatar_url = url
        details["avatar_url"] = url or "(removed)"

    log = ActivityLog(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="profile.updated",
        details=details,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    await db.commit()
    await db.refresh(user)
    if old_avatar != user.avatar_url:
        await _drop_uploaded_avatar(old_avatar)

    return success(_user_profile(user))


@router.post("/avatar")
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    data = await file.read(AVATAR_MAX_BYTES + 1)
    if not data:
        return error("That file is empty. Pick a picture to upload.", 400)
    if len(data) > AVATAR_MAX_BYTES:
        return error("That picture is larger than 2 MB. Pick a smaller one.", 413)
    ext = avatar_kind(data[:16])
    if ext is None:
        return error("Only PNG, JPEG, GIF or WebP pictures can be uploaded.", 415)
    from app.core.object_storage import get_object_storage

    name = f"{uuid.uuid4().hex}.{ext}"
    try:
        await get_object_storage().put(
            f"avatars/{user.id}/{name}", data, content_type=_AVATAR_TYPES[ext][0]
        )
    except Exception:
        return error("The picture could not be stored. Try again in a minute.", 503)

    old_avatar = user.avatar_url
    user.avatar_url = f"/api/settings/avatars/{user.id}/{name}"
    db.add(
        ActivityLog(
            tenant_id=user.tenant_id,
            user_id=user.id,
            action="profile.updated",
            details={"avatar_url": "(uploaded picture)"},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    await db.commit()
    await db.refresh(user)
    if old_avatar != user.avatar_url:
        await _drop_uploaded_avatar(old_avatar)
    return success(_user_profile(user))


# Public so <img> tags can load it, the random file name is the only handle
@router.get("/avatars/{owner_id}/{filename}")
async def get_avatar(owner_id: str, filename: str) -> Response:
    m = _AVATAR_PATH.match(f"/api/settings/avatars/{owner_id}/{filename}")
    if not m:
        return Response(status_code=404)
    from app.core.object_storage import get_object_storage

    stream = get_object_storage().get_stream(f"avatars/{owner_id}/{filename}")
    try:
        first = await stream.__anext__()
    except Exception:
        return Response(status_code=404)

    async def body():
        yield first
        async for chunk in stream:
            yield chunk

    return StreamingResponse(
        body(),
        media_type=_AVATAR_TYPES[m.group(3)][0],
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )


@router.post("/password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core import sessions

    if not user.password_hash:
        return error(
            "This account signs in with single sign-on and has no password. "
            "Use Forgot password on the sign-in page to set one.",
            400,
        )
    if not verify_password(body.current_password, user.password_hash):
        return error("Current password is incorrect", 400)

    problem = password_problem(body.new_password)
    if problem:
        return error(problem, 400)
    if verify_password(body.new_password, user.password_hash):
        return error("The new password is the same as the current one", 400)

    user.password_hash = hash_password(body.new_password)
    # other devices must sign in again with the new password
    signed_out = await sessions.revoke(
        db,
        user.id,
        keep=getattr(user, "_session_id", None),
        reason="password_changed",
    )

    log = ActivityLog(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="password.changed",
        details={"other_sessions_signed_out": signed_out},
        ip_address=sessions.client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    await db.commit()

    others = (
        "No other device was signed in."
        if not signed_out
        else f"{signed_out} other {'device was' if signed_out == 1 else 'devices were'} signed out."
    )
    return success(
        {
            "message": f"Password changed. This device stays signed in. {others}",
            "other_sessions_signed_out": signed_out,
        }
    )


MIN_PASSWORD_LEN = 8


def password_problem(pw: str) -> str | None:
    if len(pw or "") < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters"
    if len(pw) > 128:
        return "Password must be at most 128 characters"
    return None


NOTIFICATION_DEFAULTS = {
    "execution_complete": True,
    "execution_failed": True,
    "billing_alerts": True,
    "team_updates": True,
    "autonomy_updates": True,
    "moderation_reviews": True,
    "improvement_updates": True,
}


async def _notification_view(user: User, db: AsyncSession) -> dict:
    from app.core.notifications import email_channel_available, tenant_slack_webhook

    prefs = user.notification_settings or {}
    out: dict = {
        k: prefs.get(k, v) is not False for k, v in NOTIFICATION_DEFAULTS.items()
    }
    channels = prefs.get("channels") or {}
    out["channels"] = {
        "slack": channels.get("slack") is not False,
        "email": channels.get("email") is not False,
    }
    slack_ready = False
    try:
        t = (
            await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        ).scalar_one_or_none()
        slack_ready = bool(tenant_slack_webhook(t))
    except Exception:
        slack_ready = False
    out["delivery"] = {
        "slack_available": slack_ready,
        "email_available": email_channel_available(),
    }
    return out


@router.get("/notifications")
async def get_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success(await _notification_view(user, db))


@router.put("/notifications")
async def update_notifications(
    body: NotificationSettingsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    prefs = dict(user.notification_settings or {})
    for key in NOTIFICATION_DEFAULTS:
        value = getattr(body, key)
        if value is not None:
            prefs[key] = value
    if body.channels is not None:
        channels = dict(prefs.get("channels") or {})
        for ch in ("slack", "email"):
            value = getattr(body.channels, ch)
            if value is not None:
                channels[ch] = value
        prefs["channels"] = channels
    # Toggles that never had a sender
    for dead in ("weekly_report", "marketing"):
        prefs.pop(dead, None)
    user.notification_settings = prefs
    await db.commit()
    return success(await _notification_view(user, db))


_AUDIT_NOISE_KEYS = {
    "integrity_hash",
    "new_value",
    "old_value",
    "tenant_id",
    "user_id",
}


def _clean_activity_details(raw: dict | None) -> dict:
    """Strip noise fields + null values so the UI doesn't render"""
    if not raw or not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k, v in raw.items():
        if k in _AUDIT_NOISE_KEYS:
            continue
        if v is None or v == "" or v == [] or v == {}:
            continue
        out[k] = v
    return out


@router.get("/activity")
async def get_activity(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(ActivityLog)
        # your own activity, the tenant-wide trail is the admin audit log
        .where(ActivityLog.tenant_id == user.tenant_id, ActivityLog.user_id == user.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(50)
    )
    logs = result.scalars().all()

    data = [
        {
            "id": str(log.id),
            "action": log.action,
            "details": _clean_activity_details(log.details),
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
    return success(data)


@router.get("/sessions")
async def get_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core import sessions

    current = str(getattr(user, "_session_id", "") or "")
    rows = await sessions.list_live(db, user.id)
    data = [
        {
            "id": str(r.id),
            "ip_address": r.ip_address,
            "user_agent": r.user_agent,
            "method": r.method,
            "action": "login",
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            "current": str(r.id) == current,
        }
        for r in rows
    ]
    # the device you are on first
    data.sort(key=lambda d: not d["current"])
    return success(data)


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core import principal, sessions

    if str(session_id) == str(getattr(user, "_session_id", "") or ""):
        return error("This is the session you are using. Sign out instead.", 400)
    n = await sessions.revoke(db, user.id, sid=session_id, reason="revoked")
    if not n:
        return error("That session is already signed out", 404)
    db.add(
        ActivityLog(
            tenant_id=user.tenant_id,
            user_id=user.id,
            action="session.revoked",
            details={"session_id": str(session_id)},
            ip_address=sessions.client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:500],
        )
    )
    await db.commit()
    principal.forget(user.id)
    return success({"revoked": n})


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core import principal, sessions

    n = await sessions.revoke(
        db, user.id, keep=getattr(user, "_session_id", None), reason="revoked"
    )
    db.add(
        ActivityLog(
            tenant_id=user.tenant_id,
            user_id=user.id,
            action="session.revoked",
            details={"count": n, "scope": "others"},
            ip_address=sessions.client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:500],
        )
    )
    await db.commit()
    principal.forget(user.id)
    return success({"revoked": n})


@router.get("/retention")
async def get_retention(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get tenant data retention settings."""
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    settings_data = (tenant.settings or {}).get("retention", {}) if tenant else {}
    from app.core.retention import parse_retention_settings

    policy = parse_retention_settings(settings_data)
    return success(
        {
            "execution_retention_days": policy.execution_retention_days,
            "message_retention_days": policy.message_retention_days,
            "audit_log_retention_days": policy.audit_log_retention_days,
        }
    )


RETENTION_MINIMUMS = {
    "execution_retention_days": 7,
    "message_retention_days": 30,
    "audit_log_retention_days": 365,
}
RETENTION_LABELS = {
    "execution_retention_days": "Run history",
    "message_retention_days": "Messages",
    "audit_log_retention_days": "Audit logs",
}


@router.put("/retention")
async def update_retention(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update tenant data retention settings."""
    # shortening retention deletes history for everyone in the workspace
    if user.role != UserRole.ADMIN:
        return error("Only workspace admins can change how long data is kept", 403)
    for key, low in RETENTION_MINIMUMS.items():
        v = body.get(key)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < low):
            return error(
                f"{RETENTION_LABELS[key]} must be a whole number of days, {low} or more",
                400,
            )
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        return error("Tenant not found", 404)
    from sqlalchemy.orm.attributes import flag_modified

    settings_obj = dict(tenant.settings or {})
    settings_obj["retention"] = {
        "execution_retention_days": max(body.get("execution_retention_days", 90), 7),
        "message_retention_days": max(body.get("message_retention_days", 365), 30),
        "audit_log_retention_days": max(body.get("audit_log_retention_days", 730), 365),
    }
    tenant.settings = settings_obj
    flag_modified(tenant, "settings")
    await db.commit()
    return success(settings_obj["retention"])


@router.get("/dlp")
async def get_dlp_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get tenant DLP (Data Loss Prevention) settings."""
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    dlp_settings = (
        (tenant.settings or {}).get("dlp", {"mode": "detect", "enabled": False})
        if tenant
        else {}
    )
    return success(dlp_settings)


@router.put("/dlp")
async def update_dlp_settings(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update tenant DLP settings. Modes: detect, mask, block."""
    if user.role != UserRole.ADMIN:
        return error("Only tenant admins can change the data protection setting", 403)
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        return error("Tenant not found", 404)
    mode = body.get("mode", "detect")
    if mode not in ("detect", "mask", "block"):
        return error("mode must be one of: detect, mask, block", 400)
    from sqlalchemy.orm.attributes import flag_modified

    settings_obj = dict(tenant.settings or {})
    settings_obj["dlp"] = {
        "mode": mode,
        "enabled": body.get("enabled", True),
        "custom_patterns": body.get("custom_patterns", {}),
    }
    tenant.settings = settings_obj
    flag_modified(tenant, "settings")
    await db.commit()
    return success(settings_obj["dlp"])


# Tenant-scoped Redis overrides for the sandboxed_job tool. Falls back to
# host env vars when not set. Keys live at sandbox:settings:<tenant_id>.


IMAGE_REF = re.compile(
    r"^(?:[a-z0-9.-]+(?::\d+)?/)?[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
    r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?(?:@sha256:[a-f0-9]{64})?$"
)


def _sandbox_key(tenant_id: str) -> str:
    return f"sandbox:settings:{tenant_id}"


@router.get("/sandbox")
async def get_sandbox_settings(user: User = Depends(get_current_user)) -> JSONResponse:
    """Effective sandbox settings: env defaults overlaid with tenant overrides."""
    import os as _os
    import redis.asyncio as aioredis
    from app.core.config import settings as app_settings

    env_enabled = _os.environ.get("SANDBOXED_JOB_ENABLED", "").lower() in (
        "1",
        "true",
        "yes",
    )
    env_network = _os.environ.get("SANDBOXED_JOB_ALLOW_NETWORK", "").lower() in (
        "1",
        "true",
        "yes",
    )
    env_images = sorted(
        {
            i.strip()
            for i in _os.environ.get("SANDBOXED_JOB_ALLOWED_IMAGES", "").split(",")
            if i.strip()
        }
    )

    overrides: dict = {}
    try:
        r = aioredis.from_url(str(app_settings.redis_url), decode_responses=True)
        raw = await r.hgetall(_sandbox_key(str(user.tenant_id)))
        await r.aclose()
        overrides = raw or {}
    except Exception:
        overrides = {}

    def _ov_bool(k: str) -> bool | None:
        v = overrides.get(k)
        if v is None or v == "":
            return None
        return v.strip().lower() in ("1", "true", "yes")

    images_override = overrides.get("allowed_images")
    # an empty override is a real choice, nothing may run, not "use the defaults"
    images_list = (
        sorted({i.strip() for i in (images_override or "").split(",") if i.strip()})
        if images_override is not None
        else None
    )

    enabled = _ov_bool("enabled")
    enabled = enabled if enabled is not None else env_enabled
    allow_n = _ov_bool("allow_network")
    allow_n = allow_n if allow_n is not None else env_network
    images = images_list if images_list is not None else env_images

    return success(
        {
            "effective": {
                "enabled": enabled,
                "allow_network": allow_n,
                "allowed_images": images,
            },
            "env_defaults": {
                "enabled": env_enabled,
                "allow_network": env_network,
                "allowed_images": env_images,
            },
            "tenant_overrides": {
                "enabled": _ov_bool("enabled"),
                "allow_network": _ov_bool("allow_network"),
                "allowed_images": images_list,
            },
        }
    )


@router.put("/sandbox")
async def set_sandbox_settings(
    body: dict,
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Set per-tenant sandbox overrides. Send `null`/omit a key to clear it"""
    import redis.asyncio as aioredis
    from app.core.config import settings as app_settings

    if user.role.value not in ("admin",):
        return error("Only tenant admins can change sandbox settings", 403)

    fields_to_set: dict[str, str] = {}
    fields_to_del: list[str] = []

    if "enabled" in body:
        v = body["enabled"]
        if v is None:
            fields_to_del.append("enabled")
        else:
            fields_to_set["enabled"] = "true" if bool(v) else "false"

    if "allow_network" in body:
        v = body["allow_network"]
        if v is None:
            fields_to_del.append("allow_network")
        else:
            fields_to_set["allow_network"] = "true" if bool(v) else "false"

    if "allowed_images" in body:
        v = body["allowed_images"]
        if v is None:
            fields_to_del.append("allowed_images")
        elif isinstance(v, list):
            cleaned = sorted({str(i).strip() for i in v if str(i).strip()})
            bad = [i for i in cleaned if not IMAGE_REF.match(i)]
            if bad:
                return error(
                    f"{bad[0]} is not a container image. Use name:tag, like python:3.12-slim",
                    400,
                )
            fields_to_set["allowed_images"] = ",".join(cleaned)
        else:
            return error("allowed_images must be a list of strings or null", 400)

    try:
        r = aioredis.from_url(str(app_settings.redis_url), decode_responses=True)
        key = _sandbox_key(str(user.tenant_id))
        if fields_to_set:
            await r.hset(key, mapping=fields_to_set)
        if fields_to_del:
            await r.hdel(key, *fields_to_del)
        await r.aclose()
    except Exception as e:
        return error(f"redis write failed: {e}", 500)

    # Echo the new effective settings
    return await get_sandbox_settings(user)


# These live on the `tenants` row. Reads are open to any tenant member
# (so the UI can show the configured values without redacting). Writes
# are admin-only because they affect outbound notifications for the
# whole tenant.


@router.get("/tenant")
async def get_tenant_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.notifications import mask_webhook, tenant_slack_webhook

    t_q = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = t_q.scalars().first()
    if tenant is None:
        return error("tenant not found", 404)
    webhook = tenant_slack_webhook(tenant)
    # Admins see a masked tail, everyone else only learns whether one is set
    masked = mask_webhook(webhook) if user.role == UserRole.ADMIN else ""
    return success(
        {
            "tenant_id": str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
            "slack_webhook_url": masked,
            "slack_webhook_is_set": bool(webhook),
            "slack_webhook_url_source": "tenant" if webhook else "unset",
        }
    )


@router.put("/tenant")
async def update_tenant_settings(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.role != UserRole.ADMIN:
        return error("only tenant admins can update tenant settings", 403)
    t_q = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = t_q.scalars().first()
    if tenant is None:
        return error("tenant not found", 404)

    if "slack_webhook_url" in body:
        from app.core import crypto

        from app.core.notifications import slack_url_problem

        url = (body.get("slack_webhook_url") or "").strip() or None
        if url is not None and "…" in url:
            url = "__keep__"  # the masked value came back unchanged
        if url is not None and url != "__keep__":
            if len(url) > 500:
                return error(
                    "The webhook link is too long, 500 characters at most", 400
                )
            # private and cluster addresses stay blocked unless an operator names the host
            problem = await slack_url_problem(url)
            if problem:
                return error(problem, 400)
        if url is None:
            tenant.slack_webhook_url = None
        elif url != "__keep__":
            tenant.slack_webhook_url = crypto.encrypt(tenant.id, url)

    db.add(
        ActivityLog(
            tenant_id=user.tenant_id,
            user_id=user.id,
            action="tenant_settings_updated",
            details={"fields": list(body.keys())},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:255],
        )
    )
    await db.commit()
    return await get_tenant_settings(user, db)
