"""Account management — GDPR data export, account deletion, privacy settings."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import success
from app.core.audit import log_action

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.user import User
from models.agent import Agent
from models.execution import Execution
from models.conversation import Conversation, Message
from models.api_key import ApiKey

router = APIRouter(prefix="/api/account", tags=["account"])

EXPORT_MESSAGE_LIMIT = 20_000


def uuid_of(raw: str) -> uuid.UUID:
    return uuid.UUID(raw)


@router.post("/export")
async def export_user_data(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """GDPR Article 20 — Right to data portability.

    Returns all user data in a machine-readable JSON format.
    """
    # Collect user profile
    profile = {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role.value,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "notification_settings": user.notification_settings,
    }

    # Collect agents
    result = await db.execute(
        select(Agent).where(Agent.creator_id == user.id).limit(1000)
    )
    agents = [
        {
            "id": str(a.id),
            "name": a.name,
            "description": a.description,
            "type": a.type,
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in result.scalars().all()
    ]

    # Collect executions (last 1000)
    result = await db.execute(
        select(Execution)
        .where(Execution.user_id == user.id)
        .order_by(Execution.created_at.desc())
        .limit(1000)
    )
    executions = [
        {
            "id": str(e.id),
            "agent_id": str(e.agent_id),
            "input_message": e.input_message,
            "output_message": e.output_message,
            "status": e.status.value if e.status else None,
            "cost": float(e.cost) if e.cost else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in result.scalars().all()
    ]

    # Collect conversations (last 500)
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.created_at.desc())
        .limit(500)
    )
    conversations = [
        {
            "id": str(c.id),
            "title": c.title,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in result.scalars().all()
    ]

    # what was said in those conversations, not just their titles
    conv_ids = [uuid_of(c["id"]) for c in conversations]
    messages = []
    if conv_ids:
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id.in_(conv_ids))
            .order_by(Message.created_at.asc())
            .limit(EXPORT_MESSAGE_LIMIT)
        )
        messages = [
            {
                "id": str(m.id),
                "conversation_id": str(m.conversation_id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in result.scalars().all()
        ]

    from models.activity_log import ActivityLog
    from models.user_session import UserSession

    result = await db.execute(
        select(UserSession)
        .where(UserSession.user_id == user.id)
        .order_by(UserSession.created_at.desc())
        .limit(200)
    )
    sessions = [
        {
            "id": str(s.id),
            "method": s.method,
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
            "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
        }
        for s in result.scalars().all()
    ]
    result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.user_id == user.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(1000)
    )
    activity = [
        {
            "action": a.action,
            "ip_address": a.ip_address,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in result.scalars().all()
    ]

    # Collect API keys metadata (never export the hash)
    result = await db.execute(select(ApiKey).where(ApiKey.user_id == user.id))
    api_keys = [
        {
            "id": str(k.id),
            "name": k.name,
            "key_prefix": k.key_prefix,
            "scopes": k.scopes,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        }
        for k in result.scalars().all()
    ]

    await log_action(
        db,
        user.tenant_id,
        user.id,
        "account.data_export",
        request=request,
        resource_type="user",
        resource_id=str(user.id),
    )
    await db.commit()

    export_data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "format_version": "1.1",
        "profile": profile,
        "agents": agents,
        "executions": executions,
        "conversations": conversations,
        "messages": messages,
        "api_keys": api_keys,
        "sessions": sessions,
        "activity": activity,
    }

    return success(export_data)


@router.delete("")
async def delete_account(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """GDPR Article 17 — Right to erasure (right to be forgotten)."""
    user_id = user.id
    tenant_id = user.tenant_id

    # Revoke all API keys
    await db.execute(
        update(ApiKey).where(ApiKey.user_id == user_id).values(is_active=False)
    )

    # every device it is signed in on stops working now
    from app.core import sessions

    await sessions.revoke(db, user_id, reason="account_deleted")

    # Anonymize executions (keep for analytics, remove PII)
    await db.execute(
        update(Execution)
        .where(Execution.user_id == user_id)
        .values(
            input_message="[deleted]",
            output_message="[deleted]",
        )
    )

    # Delete conversations
    await db.execute(delete(Conversation).where(Conversation.user_id == user_id))

    # Log the deletion before deactivating
    await log_action(
        db,
        tenant_id,
        user_id,
        "account.deleted",
        request=request,
        resource_type="user",
        resource_id=str(user_id),
    )

    # Soft-delete user (anonymize PII)
    user.is_active = False
    user.email = f"deleted-{user_id}@deleted.abenix.dev"
    user.full_name = "Deleted User"
    user.avatar_url = None
    user.notification_settings = None

    await db.commit()

    return success(
        {"message": "Account deleted successfully. This action cannot be undone."}
    )


@router.get("/privacy")
async def get_privacy_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get privacy and data processing configuration for audit purposes."""
    from models.tenant import Tenant

    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()

    settings_data = tenant.settings or {} if tenant else {}
    retention = settings_data.get("retention", {})
    dlp = settings_data.get("dlp", {})

    return success(
        {
            "data_processing": {
                "encryption_at_rest": "AES-256 (database-level)",
                "encryption_in_transit": "TLS 1.2+",
                "data_location": "tenant-scoped isolation",
                "password_hashing": "bcrypt",
                "api_key_hashing": "SHA-256",
            },
            "retention_policy": retention,
            "dlp_policy": dlp,
            "gdpr_endpoints": {
                "data_export": "POST /api/account/export",
                "account_deletion": "DELETE /api/account",
                "privacy_settings": "GET /api/account/privacy",
            },
        }
    )
