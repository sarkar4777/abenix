"""Per-user permissions + resource-scope helpers."""
from __future__ import annotations

import uuid
from typing import Any, Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User, UserRole
from models.resource_share import ResourceShare, SharePermission


# What every role can DO. The frontend reads this to decide which
# sidebar items to render and which buttons to enable. Server-side
# authority still lives in the route handlers — the frontend descriptor
# is for UX, not security.
ROLE_FEATURES: dict[str, dict[str, bool]] = {
    "user": {
        "view_dashboard": True,
        "create_agents": True,
        "use_builder": True,
        "create_pipelines": True,
        "use_chat": True,
        "use_kb": True,
        "use_persona": True,
        "use_ml_models": True,
        "use_code_runner": True,
        "use_meetings": True,
        "use_triggers": True,
        "view_executions": True,
        "view_analytics": True,
        "view_alerts": True,
        "use_marketplace": True,
        "use_sdk_playground": True,
        "use_load_playground": True,
        # Admin-only by default below
        "review_queue": False,
        "manage_team": False,
        "manage_settings": False,
        "manage_api_keys": True,    # users manage their own keys
        "manage_mcp": True,         # users manage their own MCP connections
        # KB v2: ontology authoring is admin-only by default. End users
        # get it by being granted ADMIN on a project (Phase 3 wires the
        # per-project check into the schema editor route handler), but
        # the global flag here decides who sees the editor button at all.
        "manage_ontology": False,
        "publish_to_marketplace": False,
        "see_other_users_resources": False,
    },
    "creator": {
        # Creator gets everything user has + can publish + monetize
        "review_queue": False,
        "manage_team": False,
        "manage_ontology": True,    # creators frequently author schemas
        "publish_to_marketplace": True,
        "see_other_users_resources": False,
    },
    "admin": {
        # Admin sees everything in the tenant + manages users/settings
        "review_queue": True,
        "manage_team": True,
        "manage_settings": True,
        "manage_ontology": True,
        "publish_to_marketplace": True,
        "see_other_users_resources": True,
    },
}


def features_for(user: User) -> dict[str, bool]:
    """Merge the base 'user' feature flags with role-specific overrides."""
    role_str = (
        user.role.value if hasattr(user.role, "value") else str(user.role)
    ).lower()
    base = dict(ROLE_FEATURES.get("user", {}))
    overrides = ROLE_FEATURES.get(role_str, {})
    base.update(overrides)
    return base


def is_admin(user: User) -> bool:
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return role.lower() == "admin"


async def accessible_resource_ids(
    db: AsyncSession, user: User, *, kind: str,
    minimum_permission: SharePermission = SharePermission.VIEW,
) -> set[uuid.UUID]:
    """Return resource IDs of `kind` that have been shared with `user`"""
    perm_rank = {
        SharePermission.VIEW: 0,
        SharePermission.EXECUTE: 1,
        SharePermission.EDIT: 2,
    }
    min_rank = perm_rank[minimum_permission]
    allowed_perms = [p for p, r in perm_rank.items() if r >= min_rank]

    q = await db.execute(
        select(ResourceShare.resource_id).where(
            ResourceShare.shared_with_user_id == user.id,
            ResourceShare.resource_type == kind,
            ResourceShare.permission.in_(allowed_perms),
        )
    )
    return {row[0] for row in q.all()}


def apply_resource_scope(
    query: Any, model: Any, user: User, *,
    kind: str,
    scope: str = "all",
    accessible_ids: Iterable[uuid.UUID] | None = None,
    creator_field: str = "created_by",
    tenant_field: str = "tenant_id",
):
    """Add the right WHERE clause to a SQLAlchemy `select(model)` based"""
    creator_col = getattr(model, creator_field, None)
    tenant_col = getattr(model, tenant_field, None)
    role_str = (user.role.value if hasattr(user.role, "value") else str(user.role)).lower()
    is_admin_user = role_str == "admin"

    # Always tenant-scoped — never leak across tenants.
    base = [tenant_col == user.tenant_id] if tenant_col is not None else []

    if scope == "tenant" or (scope == "all" and is_admin_user):
        # Admin sees everything in the tenant; explicit tenant scope
        # is admin-only (members get rejected before this gets called
        # in the router).
        return query.where(*base)

    if scope == "mine":
        if creator_col is None:
            return query.where(*base)  # no ownership column → tenant-only
        return query.where(*base, creator_col == user.id)

    if scope == "shared":
        ids = list(accessible_ids or [])
        if not ids:
            return query.where(*base, model.id.in_([uuid.UUID(int=0)]))  # empty set
        return query.where(*base, model.id.in_(ids))

    # Default `scope == "all"` for non-admin: mine OR shared
    ids = list(accessible_ids or [])
    if creator_col is None:
        # Resource has no ownership concept — treat as tenant-wide.
        # (Knowledge bases historically; can add `created_by` later.)
        return query.where(*base)
    if not ids:
        return query.where(*base, creator_col == user.id)
    return query.where(*base, or_(creator_col == user.id, model.id.in_(ids)))


def assert_can_access(
    resource: Any, user: User, *,
    creator_field: str = "created_by",
    accessible_ids: Iterable[uuid.UUID] | None = None,
    permission_required: SharePermission = SharePermission.VIEW,
) -> bool:
    """Return True if `user` is allowed to access `resource` at the"""
    creator_id = getattr(resource, creator_field, None)
    if creator_id is not None and creator_id == user.id:
        return True
    if is_admin(user):
        return True
    if permission_required != SharePermission.VIEW:
        # Edit/use checks are stricter — require explicit share at that
        # level. The accessible_ids set was filtered by min permission
        # before being passed in.
        pass
    return resource.id in set(accessible_ids or [])


def assert_can_edit(
    resource: Any, user: User, *, creator_field: str = "created_by",
) -> bool:
    """True if user can mutate the resource (rename, change config).
    Stricter than view: tenant admin OR creator OR explicit edit share."""
    creator_id = getattr(resource, creator_field, None)
    if creator_id is not None and creator_id == user.id:
        return True
    if is_admin(user):
        return True
    return False  # explicit edit shares can extend this; checked at API


def assert_can_delete(
    resource: Any, user: User, *, creator_field: str = "created_by",
) -> bool:
    """Stricter than edit: ONLY creator OR tenant admin can delete."""
    creator_id = getattr(resource, creator_field, None)
    if creator_id is not None and creator_id == user.id:
        return True
    return is_admin(user)
