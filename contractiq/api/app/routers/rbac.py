"""RBAC — 6 personas + permission matrix + per-user assignments + audit-trail wiring."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success
from app.models.contractiq_models import (
    ContractIQAuditEvent,
    ContractIQRBACAssignment,
    ContractIQRBACRole,
    ContractIQUser,
)
from app.routers.auth import get_contractiq_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contractiq/rbac", tags=["contractiq-rbac"])


# Seeded personas from the architecture screenshot — 6 roles.
SYSTEM_ROLES: list[dict[str, Any]] = [
    {
        "name": "contract_officer",
        "description": "Owns the contract lifecycle. Captures signed contracts, maps clauses, manages document inputs.",
        "permissions": {
            "contracts": ["read", "create", "update", "delete"],
            "extraction": ["read", "trigger"],
            "clauses": ["read", "edit"],
            "whatif": ["read"],
            "risk": ["read"],
            "kyc": ["read"],
            "audit": ["read_own"],
        },
    },
    {
        "name": "trader",
        "description": "Prices, runs what-ifs, commits trades. Owns the live exposure view.",
        "permissions": {
            "contracts": ["read"],
            "whatif": ["read", "create"],
            "risk": ["read", "create"],
            "market_data": ["read"],
            "valuation": ["read", "trigger"],
            "hedge_advice": ["read", "trigger"],
            "audit": ["read_own"],
        },
    },
    {
        "name": "operations",
        "description": "Provisional vs final settlement, reconciliations, disputes.",
        "permissions": {
            "contracts": ["read"],
            "reconciliation": ["read", "create"],
            "disputes": ["read", "create", "update"],
            "settlements": ["read", "approve"],
            "audit": ["read_own"],
        },
    },
    {
        "name": "credit_risk",
        "description": "Pre-trade limits, counterparty exposure, KYC, sanctions.",
        "permissions": {
            "contracts": ["read"],
            "counterparty_risk": ["read", "create"],
            "kyc": ["read", "create", "approve"],
            "pre_trade_limits": ["read", "create", "edit"],
            "exposure": ["read"],
            "audit": ["read_own"],
        },
    },
    {
        "name": "market_risk",
        "description": "VaR, attribution, stress, sensitivities. Owns the risk engine config.",
        "permissions": {
            "risk": ["read", "create", "config"],
            "market_data": ["read", "config"],
            "stress_test": ["read", "create"],
            "valuation": ["read", "trigger"],
            "correlations": ["read"],
            "iv_surface": ["read"],
            "audit": ["read_own"],
        },
    },
    {
        "name": "sme_rule_owner",
        "description": "Authors and governs the rule library. Owns the four-eyes approval workflow.",
        "permissions": {
            "rules": ["read", "create", "edit", "approve", "retire"],
            "rule_versions": ["read"],
            "regression_corpus": ["read", "create"],
            "audit": ["read_own"],
        },
    },
    {
        "name": "admin",
        "description": "Platform admin. Manages users, roles, market-data sources, audit access.",
        "permissions": {"*": ["*"]},
    },
]


async def _seed_roles_if_missing(db: AsyncSession) -> None:
    existing = {r.name for r in (await db.execute(select(ContractIQRBACRole))).scalars().all()}
    for spec in SYSTEM_ROLES:
        if spec["name"] in existing:
            continue
        db.add(ContractIQRBACRole(
            name=spec["name"],
            description=spec["description"],
            permissions=spec["permissions"],
            is_system=True,
        ))
    await db.commit()


@router.get("/roles")
async def list_roles(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await _seed_roles_if_missing(db)
    rows = (await db.execute(select(ContractIQRBACRole))).scalars().all()
    return success([
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "permissions": r.permissions,
            "is_system": r.is_system,
        }
        for r in rows
    ])


@router.get("/me")
async def my_permissions(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await _seed_roles_if_missing(db)
    assignments = (
        await db.execute(
            select(ContractIQRBACAssignment, ContractIQRBACRole)
            .join(ContractIQRBACRole, ContractIQRBACAssignment.role_id == ContractIQRBACRole.id)
            .where(ContractIQRBACAssignment.user_id == user.id)
        )
    ).all()
    perms: dict[str, set[str]] = {}
    role_names: list[str] = []
    for _a, r in assignments:
        role_names.append(r.name)
        for k, v in (r.permissions or {}).items():
            perms.setdefault(k, set()).update(v if isinstance(v, list) else [v])
    return success({
        "user_id": str(user.id),
        "email": user.email,
        "legacy_role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "roles": role_names,
        "permissions": {k: sorted(v) for k, v in perms.items()},
    })


@router.post("/assign")
async def assign_role(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    target_user_id = body.get("user_id") or str(user.id)
    role_name = body.get("role")
    if not role_name:
        return error("`role` is required", 400)
    role = (
        await db.execute(select(ContractIQRBACRole).where(ContractIQRBACRole.name == role_name))
    ).scalar_one_or_none()
    if not role:
        return error(f"role not found: {role_name}", 404)
    existing = (
        await db.execute(
            select(ContractIQRBACAssignment).where(
                ContractIQRBACAssignment.user_id == uuid.UUID(target_user_id),
                ContractIQRBACAssignment.role_id == role.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return success({"ok": True, "already_assigned": True})
    db.add(ContractIQRBACAssignment(
        user_id=uuid.UUID(target_user_id),
        role_id=role.id,
        granted_by=user.id,
    ))
    db.add(ContractIQAuditEvent(
        user_id=user.id,
        kind="rbac",
        resource_type="role_assignment",
        resource_id=role_name,
        action="grant",
        after_state={"target_user_id": target_user_id, "role": role_name},
    ))
    await db.commit()
    return success({"ok": True})


def user_has_permission(perms: dict[str, list[str]], capability: str, action: str) -> bool:
    if "*" in perms and "*" in perms["*"]:
        return True
    actions = perms.get(capability) or []
    return action in actions or "*" in actions
