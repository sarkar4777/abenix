from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
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


@router.put("/profile")
async def update_profile(
    body: UpdateProfileRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.avatar_url is not None:
        user.avatar_url = body.avatar_url

    log = ActivityLog(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="profile.updated",
        details=body.model_dump(exclude_none=True),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    await db.commit()
    await db.refresh(user)

    return success(_user_profile(user))


@router.post("/password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not verify_password(body.current_password, user.password_hash):
        return error("Current password is incorrect", 400)

    if len(body.new_password) < 8:
        return error("Password must be at least 8 characters", 400)

    user.password_hash = hash_password(body.new_password)

    log = ActivityLog(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="password.changed",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    await db.commit()

    return success({"message": "Password updated successfully"})


@router.get("/notifications")
async def get_notifications(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    defaults = {
        "execution_complete": True,
        "execution_failed": True,
        "weekly_report": False,
        "billing_alerts": True,
        "team_updates": True,
        "marketing": False,
    }
    prefs = user.notification_settings or {}
    merged = {**defaults, **prefs}
    return success(merged)


@router.put("/notifications")
async def update_notifications(
    body: NotificationSettingsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    user.notification_settings = body.model_dump()
    await db.commit()
    return success(body.model_dump())


_AUDIT_NOISE_KEYS = {
    "integrity_hash", "new_value", "old_value", "tenant_id", "user_id",
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
        .where(ActivityLog.tenant_id == user.tenant_id)
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
    result = await db.execute(
        select(ActivityLog)
        .where(
            ActivityLog.user_id == user.id,
            ActivityLog.action.in_(["login", "password.changed"]),
        )
        .order_by(ActivityLog.created_at.desc())
        .limit(10)
    )
    logs = result.scalars().all()

    sessions = [
        {
            "id": str(log.id),
            "ip_address": log.ip_address,
            "user_agent": log.user_agent,
            "action": log.action,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
    return success(sessions)


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
    return success({
        "execution_retention_days": policy.execution_retention_days,
        "message_retention_days": policy.message_retention_days,
        "audit_log_retention_days": policy.audit_log_retention_days,
    })


@router.put("/retention")
async def update_retention(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update tenant data retention settings."""
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        return error("Tenant not found", 404)
    settings_obj = tenant.settings or {}
    settings_obj["retention"] = {
        "execution_retention_days": max(body.get("execution_retention_days", 90), 7),
        "message_retention_days": max(body.get("message_retention_days", 365), 30),
        "audit_log_retention_days": max(body.get("audit_log_retention_days", 730), 365),
    }
    tenant.settings = settings_obj
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
    dlp_settings = (tenant.settings or {}).get("dlp", {"mode": "detect", "enabled": False}) if tenant else {}
    return success(dlp_settings)


@router.put("/dlp")
async def update_dlp_settings(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update tenant DLP settings. Modes: detect, mask, block."""
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        return error("Tenant not found", 404)
    mode = body.get("mode", "detect")
    if mode not in ("detect", "mask", "block"):
        return error("mode must be one of: detect, mask, block", 400)
    settings_obj = tenant.settings or {}
    settings_obj["dlp"] = {
        "mode": mode,
        "enabled": body.get("enabled", True),
        "custom_patterns": body.get("custom_patterns", {}),
    }
    tenant.settings = settings_obj
    await db.commit()
    return success(settings_obj["dlp"])


# Tenant-scoped Redis overrides for the sandboxed_job tool. Falls back to
# host env vars when not set. Keys live at sandbox:settings:<tenant_id>.

def _sandbox_key(tenant_id: str) -> str:
    return f"sandbox:settings:{tenant_id}"


@router.get("/sandbox")
async def get_sandbox_settings(user: User = Depends(get_current_user)) -> JSONResponse:
    """Effective sandbox settings: env defaults overlaid with tenant overrides."""
    import os as _os
    import redis.asyncio as aioredis
    from app.core.config import settings as app_settings

    env_enabled  = _os.environ.get("SANDBOXED_JOB_ENABLED", "").lower() in ("1","true","yes")
    env_network  = _os.environ.get("SANDBOXED_JOB_ALLOW_NETWORK", "").lower() in ("1","true","yes")
    env_images   = sorted({i.strip() for i in _os.environ.get("SANDBOXED_JOB_ALLOWED_IMAGES", "").split(",") if i.strip()})

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
        return v.strip().lower() in ("1","true","yes")

    images_override = overrides.get("allowed_images")
    images_list = sorted({i.strip() for i in (images_override or "").split(",") if i.strip()}) if images_override else None

    enabled = _ov_bool("enabled");          enabled = enabled if enabled is not None else env_enabled
    allow_n = _ov_bool("allow_network");    allow_n = allow_n if allow_n is not None else env_network
    images  = images_list if images_list is not None else env_images

    return success({
        "effective": {"enabled": enabled, "allow_network": allow_n, "allowed_images": images},
        "env_defaults": {"enabled": env_enabled, "allow_network": env_network, "allowed_images": env_images},
        "tenant_overrides": {
            "enabled": _ov_bool("enabled"),
            "allow_network": _ov_bool("allow_network"),
            "allowed_images": images_list,
        },
    })


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
        if v is None: fields_to_del.append("enabled")
        else: fields_to_set["enabled"] = "true" if bool(v) else "false"

    if "allow_network" in body:
        v = body["allow_network"]
        if v is None: fields_to_del.append("allow_network")
        else: fields_to_set["allow_network"] = "true" if bool(v) else "false"

    if "allowed_images" in body:
        v = body["allowed_images"]
        if v is None: fields_to_del.append("allowed_images")
        elif isinstance(v, list):
            cleaned = sorted({str(i).strip() for i in v if str(i).strip()})
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
    t_q = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = t_q.scalars().first()
    if tenant is None:
        return error("tenant not found", 404)
    return success({
        "tenant_id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "slack_webhook_url": getattr(tenant, "slack_webhook_url", None) or "",
        "slack_webhook_url_source": (
            "tenant" if getattr(tenant, "slack_webhook_url", None) else "env_fallback"
        ),
    })


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
        url = (body.get("slack_webhook_url") or "").strip() or None
        # Best-effort URL validation — Slack URLs are always
        # https://hooks.slack.com/services/.../.../...
        if url is not None:
            if not url.lower().startswith("https://"):
                return error("slack_webhook_url must use https://", 400)
            if len(url) > 500:
                return error("slack_webhook_url too long (max 500 chars)", 400)
        tenant.slack_webhook_url = url

    db.add(ActivityLog(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="tenant_settings_updated",
        details={"fields": list(body.keys())},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:255],
    ))
    await db.commit()
    return await get_tenant_settings(user, db)
