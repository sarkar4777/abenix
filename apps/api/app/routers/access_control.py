"""Access Control API — manage RBAC delegation policies for acting subjects."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.user import User
from models.api_key import ApiKey
from models.subject_policy import SubjectPolicy

router = APIRouter(prefix="/api/access-control", tags=["access-control"])


class PolicyRules(BaseModel):
    """Subject policy rules schema."""
    agents: dict | None = None
    knowledge_bases: list[dict] | None = None
    tools: dict | None = None
    data_scopes: dict | None = None
    denied_actions: list[str] | None = None


class CreatePolicyRequest(BaseModel):
    api_key_id: str
    subject_type: str = Field(..., max_length=50)
    subject_id: str = Field(..., max_length=255)
    display_name: str | None = None
    description: str | None = None
    rules: dict = Field(default_factory=dict)


class UpdatePolicyRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    rules: dict | None = None
    is_active: bool | None = None


def _serialize_policy(p: SubjectPolicy) -> dict:
    return {
        "id": str(p.id),
        "api_key_id": str(p.api_key_id),
        "subject_type": p.subject_type,
        "subject_id": p.subject_id,
        "display_name": p.display_name,
        "description": p.description,
        "rules": p.rules or {},
        "is_active": p.is_active,
        "last_used_at": p.last_used_at.isoformat() if p.last_used_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/policies")
async def list_policies(
    api_key_id: str = Query("", description="Filter by API key"),
    subject_type: str = Query(""),
    search: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List subject policies under the user's API keys."""
    # Get user's API keys
    keys_result = await db.execute(
        select(ApiKey.id).where(ApiKey.tenant_id == user.tenant_id, ApiKey.is_active.is_(True))
    )
    user_key_ids = [r[0] for r in keys_result.all()]

    if not user_key_ids:
        return JSONResponse(content={"data": [], "error": None, "meta": {"total": 0, "limit": limit, "offset": offset}})

    query = select(SubjectPolicy).where(SubjectPolicy.api_key_id.in_(user_key_ids))

    if api_key_id:
        try:
            query = query.where(SubjectPolicy.api_key_id == uuid.UUID(api_key_id))
        except ValueError:
            return error("Invalid api_key_id", 400)
    if subject_type:
        query = query.where(SubjectPolicy.subject_type == subject_type)
    if search:
        from sqlalchemy import or_
        query = query.where(or_(
            SubjectPolicy.subject_id.ilike(f"%{search}%"),
            SubjectPolicy.display_name.ilike(f"%{search}%"),
        ))

    count_q = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_q) or 0

    query = query.order_by(SubjectPolicy.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    policies = result.scalars().all()

    return JSONResponse(content={
        "data": [_serialize_policy(p) for p in policies],
        "error": None,
        "meta": {"total": total, "limit": limit, "offset": offset},
    })


@router.post("/policies")
async def create_policy(
    body: CreatePolicyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create a new subject policy."""
    try:
        api_key_uuid = uuid.UUID(body.api_key_id)
    except ValueError:
        return error("Invalid api_key_id", 400)

    # Verify the API key belongs to the user's tenant
    key_result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == api_key_uuid,
            ApiKey.tenant_id == user.tenant_id,
        )
    )
    api_key = key_result.scalar_one_or_none()
    if not api_key:
        return error("API key not found or access denied", 404)

    policy = SubjectPolicy(
        id=uuid.uuid4(),
        api_key_id=api_key_uuid,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        display_name=body.display_name,
        description=body.description,
        rules=body.rules,
        is_active=True,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)

    return success(_serialize_policy(policy), status_code=201)


@router.get("/policies/{policy_id}")
async def get_policy(
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get a single policy."""
    result = await db.execute(
        select(SubjectPolicy)
        .join(ApiKey, SubjectPolicy.api_key_id == ApiKey.id)
        .where(SubjectPolicy.id == policy_id, ApiKey.tenant_id == user.tenant_id)
    )
    policy = result.scalar_one_or_none()
    if not policy:
        return error("Policy not found", 404)
    return success(_serialize_policy(policy))


@router.put("/policies/{policy_id}")
async def update_policy(
    policy_id: uuid.UUID,
    body: UpdatePolicyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update a policy."""
    result = await db.execute(
        select(SubjectPolicy)
        .join(ApiKey, SubjectPolicy.api_key_id == ApiKey.id)
        .where(SubjectPolicy.id == policy_id, ApiKey.tenant_id == user.tenant_id)
    )
    policy = result.scalar_one_or_none()
    if not policy:
        return error("Policy not found", 404)

    if body.display_name is not None:
        policy.display_name = body.display_name
    if body.description is not None:
        policy.description = body.description
    if body.rules is not None:
        policy.rules = body.rules
    if body.is_active is not None:
        policy.is_active = body.is_active

    await db.commit()
    await db.refresh(policy)
    return success(_serialize_policy(policy))


@router.delete("/policies/{policy_id}")
async def delete_policy(
    policy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Delete a policy."""
    result = await db.execute(
        select(SubjectPolicy)
        .join(ApiKey, SubjectPolicy.api_key_id == ApiKey.id)
        .where(SubjectPolicy.id == policy_id, ApiKey.tenant_id == user.tenant_id)
    )
    policy = result.scalar_one_or_none()
    if not policy:
        return error("Policy not found", 404)

    await db.delete(policy)
    await db.commit()
    return success({"deleted": True})


@router.get("/api-keys")
async def list_delegation_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List API keys with delegation enabled."""
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.tenant_id == user.tenant_id,
            ApiKey.is_active.is_(True),
        ).order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()

    data = []
    for k in keys:
        scopes = k.scopes or {}
        can_delegate = scopes.get("can_delegate", False) if isinstance(scopes, dict) else False
        data.append({
            "id": str(k.id),
            "name": k.name,
            "key_prefix": k.key_prefix,
            "can_delegate": can_delegate,
            "subject_types_allowed": scopes.get("subject_types_allowed", []) if isinstance(scopes, dict) else [],
            "created_at": k.created_at.isoformat() if k.created_at else None,
        })

    return success(data)


@router.get("/templates")
async def list_policy_templates() -> JSONResponse:
    """Return common policy templates that admins can apply."""
    templates = [
        {
            "id": "example_app_user_isolated",
            "name": "the example app User-Isolated",
            "description": "Each the example app user can only access their own contracts and KB namespace",
            "subject_type": "example_app",
            "rules": {
                "agents": {
                    "mode": "allowlist",
                    "slugs": ["example_app-chat", "example_app-pipeline"],
                },
                "knowledge_bases": [{
                    "kb_id": "*",
                    "access_mode": "namespace",
                    "namespace_pattern": "example_app-{subject_id}",
                    "allowed_actions": ["read", "search"],
                }],
                "data_scopes": {
                    "example_app.contracts.user_id": "{subject_id}",
                },
                "denied_actions": ["delete", "admin"],
            },
        },
        {
            "id": "team_lead_cross_user",
            "name": "Team Lead (Cross-User Read)",
            "description": "Team lead can read contracts from team members",
            "subject_type": "example_app",
            "rules": {
                "agents": {"mode": "allowlist", "slugs": ["example_app-chat"]},
                "knowledge_bases": [{
                    "kb_id": "*",
                    "access_mode": "namespace",
                    "namespace_pattern": "example_app-team-{subject_id}",
                    "allowed_actions": ["read", "search"],
                }],
                "denied_actions": ["delete"],
            },
        },
        {
            "id": "read_only",
            "name": "Read-Only Subject",
            "description": "Subject can search and read but not execute writes",
            "subject_type": "external",
            "rules": {
                "agents": {"mode": "denylist", "slugs": []},
                "knowledge_bases": [{
                    "kb_id": "*",
                    "access_mode": "full",
                    "allowed_actions": ["read", "search"],
                }],
                "denied_actions": ["delete", "admin", "write"],
            },
        },
        {
            "id": "department_filtered",
            "name": "Department-Filtered KB Access",
            "description": "Subject can only see KB documents tagged with their department",
            "subject_type": "external",
            "rules": {
                "knowledge_bases": [{
                    "kb_id": "*",
                    "access_mode": "document_filter",
                    "document_filters": {"department": "{subject_metadata.department}"},
                    "allowed_actions": ["read", "search"],
                }],
            },
        },
    ]
    return success(templates)


@router.post("/test")
async def test_policy(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Test what a subject can/cannot access by simulating a query."""
    subject_type = body.get("subject_type", "")
    subject_id = body.get("subject_id", "")
    api_key_id = body.get("api_key_id", "")
    test_resource = body.get("test_resource", "")  # e.g., "agent:example_app-chat"

    if not all([subject_type, subject_id, api_key_id, test_resource]):
        return error("Missing required fields", 400)

    # Find the policy
    try:
        api_key_uuid = uuid.UUID(api_key_id)
    except ValueError:
        return error("Invalid api_key_id", 400)

    result = await db.execute(
        select(SubjectPolicy).where(
            SubjectPolicy.api_key_id == api_key_uuid,
            SubjectPolicy.subject_type == subject_type,
            SubjectPolicy.subject_id.in_([subject_id, "*"]),
            SubjectPolicy.is_active.is_(True),
        )
    )
    policies = result.scalars().all()

    if not policies:
        return success({
            "allowed": False,
            "reason": "No policy found for this subject",
            "matched_policy": None,
        })

    # Use the most specific policy (subject_id over wildcard)
    policy = sorted(policies, key=lambda p: 0 if p.subject_id == subject_id else 1)[0]
    rules = policy.rules or {}

    # Resolve the test resource
    resource_type, _, resource_id = test_resource.partition(":")
    allowed = False
    reason = "Default deny"

    if resource_type == "agent":
        agent_rules = rules.get("agents", {})
        mode = agent_rules.get("mode", "all")
        slugs = agent_rules.get("slugs", [])
        ids = agent_rules.get("ids", [])
        if mode == "all":
            allowed, reason = True, "All agents allowed"
        elif mode == "allowlist":
            allowed = resource_id in slugs or resource_id in ids
            reason = f"Allowlist {'matched' if allowed else 'no match'}"
        elif mode == "denylist":
            denied = resource_id in slugs or resource_id in ids
            allowed = not denied
            reason = f"Denylist {'blocked' if denied else 'allowed'}"
    elif resource_type == "kb":
        kbs = rules.get("knowledge_bases", [])
        for kb_rule in kbs:
            if kb_rule.get("kb_id") in (resource_id, "*"):
                if kb_rule.get("access_mode") != "none":
                    allowed = True
                    reason = f"KB access mode: {kb_rule.get('access_mode')}"
                    break

    return success({
        "allowed": allowed,
        "reason": reason,
        "matched_policy": _serialize_policy(policy),
    })
