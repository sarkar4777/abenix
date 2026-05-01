"""Per-user `me` endpoints — what the current user can see + do."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.permissions import (
    features_for,
    is_admin,
)
from app.core.responses import error, success
from models.resource_share import ResourceShare, SharePermission
from models.user import User

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("/permissions")
async def my_permissions(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Return the current user's role + per-feature flags + UI hints."""
    return success(
        {
            "user_id": str(user.id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "name": getattr(user, "name", None),
            "role": (
                user.role.value if hasattr(user.role, "value") else str(user.role)
            ).lower(),
            "is_admin": is_admin(user),
            "features": features_for(user),
        }
    )


_SHAREABLE_KINDS = {
    "agent",
    "pipeline",
    "ml_model",
    "code_asset",
    "knowledge_base",
    "saved_tool",
}


@router.post("/shares")
async def create_share(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Share any supported resource with another user in your tenant."""
    kind = (body.get("resource_type") or "").strip().lower()
    if kind not in _SHAREABLE_KINDS:
        return error(
            f"resource_type must be one of {sorted(_SHAREABLE_KINDS)}; got '{kind}'",
            400,
        )
    try:
        rid = uuid.UUID(str(body.get("resource_id") or ""))
    except (ValueError, TypeError):
        return error("resource_id must be a valid UUID", 400)

    email = (body.get("shared_with_email") or "").strip().lower()
    if not email:
        return error("shared_with_email is required", 400)

    # Accept the lower-case API surface (`view` / `use` / `edit`) and
    # map to the uppercase pg enum values (VIEW / EXECUTE / EDIT). The
    # docs + UI use lowercase since it reads better — only the DB layer
    # cares about the canonical strings.
    perm_str = (body.get("permission") or "view").strip().lower()
    perm_map = {
        "view": SharePermission.VIEW,
        "use": SharePermission.EXECUTE,
        "execute": SharePermission.EXECUTE,
        "edit": SharePermission.EDIT,
    }
    perm = perm_map.get(perm_str)
    if perm is None:
        return error(
            f"permission must be one of view/use/edit; got '{perm_str}'",
            400,
        )

    # Verify the caller owns the resource (or is admin). We do this by
    # looking up the resource via the same query helpers list endpoints
    # use — keeps semantics consistent.
    if not await _user_can_share(db, user, kind=kind, resource_id=rid):
        return error("Resource not found or you don't have permission to share it", 403)

    # Resolve recipient by email — must be in same tenant.
    recipient_q = await db.execute(
        select(User).where(User.email == email, User.tenant_id == user.tenant_id)
    )
    recipient = recipient_q.scalar_one_or_none()
    if not recipient:
        return error(
            f"No user with email '{email}' in your tenant. "
            "Invite them first via Settings → Team.",
            404,
        )
    if recipient.id == user.id:
        return error("You cannot share a resource with yourself", 400)

    # Idempotent — UniqueConstraint on (resource, recipient) → upsert.
    existing_q = await db.execute(
        select(ResourceShare).where(
            ResourceShare.resource_type == kind,
            ResourceShare.resource_id == rid,
            ResourceShare.shared_with_user_id == recipient.id,
        )
    )
    existing = existing_q.scalar_one_or_none()
    if existing:
        existing.permission = perm
        await db.commit()
        await db.refresh(existing)
        return success(_serialize_share(existing))

    share = ResourceShare(
        tenant_id=user.tenant_id,
        resource_type=kind,
        resource_id=rid,
        shared_with_user_id=recipient.id,
        shared_with_email=email,
        permission=perm,
        shared_by=user.id,
    )
    db.add(share)
    await db.commit()
    await db.refresh(share)

    # Notify the recipient via the existing notification system.
    try:
        from app.core.notifications import create_notification
        from models.notification import NotificationType

        await create_notification(
            db,
            tenant_id=user.tenant_id,
            user_id=recipient.id,
            type=(
                NotificationType.AGENT_SHARED.value
                if hasattr(NotificationType, "AGENT_SHARED")
                else "agent_shared"
            ),
            title=f"{user.email} shared a {kind} with you",
            message=f"Permission: {perm.value}. Open it from {kind}s page.",
            link=f"/{kind}s/{rid}",
            metadata={
                "resource_type": kind,
                "resource_id": str(rid),
                "permission": perm.value,
            },
        )
    except Exception:
        pass

    return success(_serialize_share(share), status_code=201)


@router.delete("/shares/{share_id}")
async def revoke_share(
    share_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Revoke a share. Only the share's creator OR the resource's owner"""
    q = await db.execute(
        select(ResourceShare).where(
            ResourceShare.id == share_id,
            ResourceShare.tenant_id == user.tenant_id,
        )
    )
    share = q.scalar_one_or_none()
    if not share:
        return error("Share not found", 404)
    # Caller must be the sharer, OR the resource owner, OR admin.
    if share.shared_by != user.id and not is_admin(user):
        # Check if user is the resource owner.
        if not await _user_can_share(
            db,
            user,
            kind=share.resource_type,
            resource_id=share.resource_id,
        ):
            return error("Not authorized to revoke this share", 403)
    await db.delete(share)
    await db.commit()
    return success({"deleted": True})


@router.get("/shares/received")
async def list_shares_received(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """All resources shared WITH the current user. Used by `My Shares`
    UI panel and the sidebar's recent-shares list."""
    q = await db.execute(
        select(ResourceShare)
        .where(ResourceShare.shared_with_user_id == user.id)
        .order_by(desc(ResourceShare.created_at))
    )
    return success([_serialize_share(s) for s in q.scalars().all()])


@router.get("/shares/sent")
async def list_shares_sent(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """All shares the current user CREATED. Lets the user audit who has
    access to their resources."""
    q = await db.execute(
        select(ResourceShare)
        .where(ResourceShare.shared_by == user.id)
        .order_by(desc(ResourceShare.created_at))
    )
    return success([_serialize_share(s) for s in q.scalars().all()])


def _serialize_share(s: ResourceShare) -> dict[str, Any]:
    # Render the API in lowercase canonical form (view/use/edit) even
    # though the DB enum is uppercase. The UI is consistent that way.
    pg_to_api = {"VIEW": "view", "EXECUTE": "use", "EDIT": "edit"}
    raw = s.permission.value if hasattr(s.permission, "value") else str(s.permission)
    return {
        "id": str(s.id),
        "resource_type": s.resource_type,
        "resource_id": str(s.resource_id),
        "shared_with_user_id": (
            str(s.shared_with_user_id) if s.shared_with_user_id else None
        ),
        "shared_with_email": s.shared_with_email,
        "permission": pg_to_api.get(raw, raw.lower()),
        "shared_by": str(s.shared_by),
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
    }


async def _user_can_share(
    db: AsyncSession,
    user: User,
    *,
    kind: str,
    resource_id: uuid.UUID,
) -> bool:
    """Look up the resource by `kind` + `resource_id` and check whether"""
    from sqlalchemy import select as _s

    if kind == "agent":
        from models.agent import Agent

        r = await db.execute(
            _s(Agent).where(Agent.id == resource_id, Agent.tenant_id == user.tenant_id)
        )
        obj = r.scalar_one_or_none()
        if not obj:
            return False
        return obj.creator_id == user.id or is_admin(user)

    if kind == "ml_model":
        from models.ml_model import MLModel

        r = await db.execute(
            _s(MLModel).where(
                MLModel.id == resource_id, MLModel.tenant_id == user.tenant_id
            )
        )
        obj = r.scalar_one_or_none()
        if not obj:
            return False
        return obj.created_by == user.id or is_admin(user)

    if kind == "code_asset":
        from models.code_asset import CodeAsset

        r = await db.execute(
            _s(CodeAsset).where(
                CodeAsset.id == resource_id, CodeAsset.tenant_id == user.tenant_id
            )
        )
        obj = r.scalar_one_or_none()
        if not obj:
            return False
        return obj.created_by == user.id or is_admin(user)

    if kind == "knowledge_base":
        from models.knowledge_base import KnowledgeBase

        r = await db.execute(
            _s(KnowledgeBase).where(
                KnowledgeBase.id == resource_id,
                KnowledgeBase.tenant_id == user.tenant_id,
            )
        )
        obj = r.scalar_one_or_none()
        if not obj:
            return False
        # KB doesn't have created_by today; anyone in tenant can share
        # (matches existing visibility), pending the migration to add it.
        return True

    if kind == "saved_tool":
        from models.saved_tool import SavedTool

        r = await db.execute(
            _s(SavedTool).where(
                SavedTool.id == resource_id, SavedTool.tenant_id == user.tenant_id
            )
        )
        obj = r.scalar_one_or_none()
        if not obj:
            return False
        return obj.created_by == user.id or is_admin(user)

    if kind == "pipeline":
        # Pipelines are stored as Agents with mode=pipeline.
        from models.agent import Agent

        r = await db.execute(
            _s(Agent).where(Agent.id == resource_id, Agent.tenant_id == user.tenant_id)
        )
        obj = r.scalar_one_or_none()
        if not obj:
            return False
        return obj.creator_id == user.id or is_admin(user)

    return False
