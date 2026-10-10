"""Who can sign an approval, and when the one person in a workspace may sign their own."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import ROLE_DEFAULTS, _role, holds
from models.governance import PermissionAssignment, PermissionSet
from models.tenant import Tenant
from models.user import User

# gate kinds where the requester may sign alone when nobody else can
SOLE_OPERATOR_KINDS = (
    "decision_publish",
    "decision_tier_change",
    "decision_reattest",
    "decision_retire",
    "decision_archive",
    "decision_restore",
)
DECISION_KINDS = SOLE_OPERATOR_KINDS
REVIEWERS_KEY = "decision_reviewers"
REVIEWERS_NAME = "Decision reviewers"
REVIEWERS_CAPS = ["approvals.sign", "decisions.review"]
REVIEWERS_DESC = (
    "People in this set can approve decisions: publishing a version, lowering a risk "
    "tier, a review after a raise, and retiring, archiving or restoring at high risk."
)
SOLE_OPERATOR_SETTING = "sole_operator_signoff"
MIN_REASON = 10
SYSTEM_USER_EMAIL = "system@abenix.dev"


def required_capabilities(
    policy: dict[str, Any] | None, gate_kind: str | None
) -> list[str]:
    caps = [str((policy or {}).get("capability") or "approvals.sign")]
    if gate_kind in DECISION_KINDS:
        caps.append("decisions.review")
    return caps


def can_sign(
    role: str,
    granted: frozenset[str] | set[str],
    policy: dict[str, Any] | None,
    gate_kind: str | None,
) -> bool:
    """The same test approver_denial applies, leaving out who asked."""
    if not all(holds(granted, c) for c in required_capabilities(policy, gate_kind)):
        if policy or gate_kind in DECISION_KINDS:
            return False
        # without a policy admins and creators sign by role
        return role in ("admin", "creator")
    return True


async def tenant_people(
    db: AsyncSession, tenant_id: Any
) -> list[tuple[User, frozenset[str]]]:
    """Every active user in the tenant with what they may do, in two queries."""
    users = (
        (
            await db.execute(
                select(User).where(
                    User.tenant_id == tenant_id, User.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    rows = (
        await db.execute(
            select(PermissionAssignment.user_id, PermissionSet.capabilities)
            .join(
                PermissionSet,
                PermissionAssignment.permission_set_id == PermissionSet.id,
            )
            .where(PermissionAssignment.tenant_id == tenant_id)
        )
    ).all()
    extra: dict[str, set[str]] = {}
    for uid, granted in rows:
        extra.setdefault(str(uid), set()).update(
            c for c in (granted or []) if isinstance(c, str)
        )
    out = []
    for u in users:
        # the platform's own account and erased accounts never approve anything
        if not real_person(u):
            continue
        caps = set(ROLE_DEFAULTS.get(_role(u), ROLE_DEFAULTS["user"]))
        caps |= extra.get(str(u.id), set())
        out.append((u, frozenset(caps)))
    return out


PURGED_DOMAIN = "@purged.local"


def real_person(u: Any) -> bool:
    """An account a person signs in with: not the system account, not erased under GDPR."""
    email = (getattr(u, "email", "") or "").lower()
    return email != SYSTEM_USER_EMAIL and not email.endswith(PURGED_DOMAIN)


def eligible_from(
    people: list[tuple[User, frozenset[str]]],
    policy: dict[str, Any] | None,
    gate_kind: str | None,
    requester_id: Any,
) -> list[User]:
    req = str(requester_id) if requester_id else None
    return [
        u
        for u, caps in people
        if str(u.id) != req and can_sign(_role(u), caps, policy, gate_kind)
    ]


def person_json(u: User) -> dict[str, Any]:
    return {"id": str(u.id), "name": u.full_name or u.email, "email": u.email}


async def sole_operator_enabled(db: AsyncSession, tenant_id: Any) -> bool:
    t = await db.get(Tenant, tenant_id) if isinstance(tenant_id, uuid.UUID) else None
    if t is None:
        t = (
            await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
    return setting_from((t.settings if t else None) or {})


def setting_from(settings: dict[str, Any]) -> bool:
    gov = settings.get("governance") if isinstance(settings, dict) else None
    val = (gov or {}).get(SOLE_OPERATOR_SETTING) if isinstance(gov, dict) else None
    return True if val is None else bool(val)


def people_words(n: int) -> str:
    if n == 1:
        return "1 person can approve this. Ask them."
    return f"{n} people can approve this. Ask one of them."


def sole_operator_refusal(
    *,
    gate_kind: str | None,
    decision: str,
    reason: str | None,
    is_requester: bool,
    requester_can_sign: bool,
    enabled: bool,
    eligible_count: int,
) -> tuple[int, str, str] | None:
    """Why a sole-operator sign-off is refused, as (status, error_code, message), or None when allowed."""
    if gate_kind not in SOLE_OPERATOR_KINDS:
        return (
            403,
            "SOLE_OPERATOR_NOT_ALLOWED",
            "Signing your own request alone only applies to decision approvals.",
        )
    if decision != "approve":
        return (
            400,
            "SOLE_OPERATOR_APPROVE_ONLY",
            "A sole-operator sign-off approves. To drop the request, withdraw it instead.",
        )
    if len((reason or "").strip()) < MIN_REASON:
        return (
            422,
            "REASON_REQUIRED",
            f"Say why you are approving your own request, at least {MIN_REASON} characters. It is recorded with the sign-off.",
        )
    if not is_requester:
        return (
            403,
            "SOLE_OPERATOR_NOT_REQUESTER",
            "Only the person who asked can sign it alone. Sign it the usual way instead.",
        )
    if eligible_count > 0:
        return (403, "OTHER_APPROVERS_EXIST", people_words(eligible_count))
    if not enabled:
        return (
            403,
            "SOLE_OPERATOR_OFF",
            "Nobody else can approve this and sole-operator sign-off is turned off. An admin can turn it on under Admin, Risk and Controls, or give someone the right to approve.",
        )
    if not requester_can_sign:
        return (
            403,
            "CANNOT_SIGN",
            "You do not have the right to approve this yourself. An admin can grant it under Admin, Permissions.",
        )
    return None


def mark_withdrawn(a: Any, why: str, by: Any = None) -> None:
    """Withdraw an approval and keep why and who, None when the platform did it."""
    import datetime as _dt

    from models.approval import ApprovalStatus

    a.status = ApprovalStatus.withdrawn
    a.decided_at = _dt.datetime.now(_dt.timezone.utc)
    a.payload = {
        **(a.payload or {}),
        "withdrawn": why,
        "withdrawn_by": str(by) if by else None,
    }


def is_self_approved(a: Any) -> bool:
    return any(
        s.get("decision") == "approve"
        and (s.get("sole_operator") or s.get("self_approved"))
        for s in (getattr(a, "signoffs", None) or [])
    )


async def ensure_decision_reviewers(db: AsyncSession, tenant_id: Any) -> PermissionSet:
    """The tenant's Decision reviewers set, created when missing. Flushes, never commits."""
    ps = (
        await db.execute(
            select(PermissionSet).where(
                PermissionSet.tenant_id == tenant_id,
                PermissionSet.builtin_key == REVIEWERS_KEY,
            )
        )
    ).scalar_one_or_none()
    if ps is not None:
        return ps
    ps = (
        await db.execute(
            select(PermissionSet).where(
                PermissionSet.tenant_id == tenant_id,
                PermissionSet.name == REVIEWERS_NAME,
            )
        )
    ).scalar_one_or_none()
    if ps is not None:
        ps.builtin_key = REVIEWERS_KEY
        await db.flush()
        return ps
    ps = PermissionSet(
        tenant_id=tenant_id,
        name=REVIEWERS_NAME,
        description=REVIEWERS_DESC,
        capabilities=list(REVIEWERS_CAPS),
        builtin_key=REVIEWERS_KEY,
    )
    db.add(ps)
    await db.flush()
    return ps


async def remove_decision_reviewer(
    db: AsyncSession, tenant_id: Any, user_id: Any
) -> bool:
    """Take a person out of Decision reviewers. False when they were not in it."""
    from sqlalchemy import delete

    ps = await ensure_decision_reviewers(db, tenant_id)
    res = await db.execute(
        delete(PermissionAssignment).where(
            PermissionAssignment.permission_set_id == ps.id,
            PermissionAssignment.user_id == user_id,
        )
    )
    return bool(res.rowcount)


def decision_approvers(people: list[tuple[User, frozenset[str]]]) -> list[User]:
    return [u for u, c in people if can_approve_decisions(c)]


def approver_candidates(
    people: list[tuple[User, frozenset[str]]], exclude: Any = None
) -> list[User]:
    """Teammates who could be made decision approvers: real, active, not already able to."""
    skip = {str(x) for x in (exclude or []) if x}
    return [
        u for u, c in people if not can_approve_decisions(c) and str(u.id) not in skip
    ]


async def add_decision_reviewer(
    db: AsyncSession, tenant_id: Any, user_id: Any, by: Any = None
) -> bool:
    """Put a person in Decision reviewers. False when they were already in it."""
    from app.core import capabilities as caps

    ps = await ensure_decision_reviewers(db, tenant_id)
    have = (
        await db.execute(
            select(PermissionAssignment.id).where(
                PermissionAssignment.permission_set_id == ps.id,
                PermissionAssignment.user_id == user_id,
            )
        )
    ).scalar()
    if have:
        return False
    db.add(
        PermissionAssignment(
            tenant_id=tenant_id,
            permission_set_id=ps.id,
            user_id=user_id,
            created_by=by,
        )
    )
    await db.flush()
    caps.invalidate(user_id if isinstance(user_id, uuid.UUID) else None)
    return True


def can_approve_decisions(granted: frozenset[str] | set[str]) -> bool:
    return holds(granted, "approvals.sign") and holds(granted, "decisions.review")


# why a row cannot be signed: these hide it from people who never could
HIDDEN_CODES = ("NOT_REVIEWER", "MISSING_PERMISSION", "NOT_SIGNER")


def sign_check(
    user: Any,
    granted: frozenset[str] | set[str],
    *,
    requested_by: Any,
    policy: dict[str, Any] | None,
    gate_kind: str | None,
    signoffs: list[dict[str, Any]] | None,
    agent_creator_id: str | None = None,
    self_approval: str | None = None,
) -> tuple[str, str] | None:
    """Why this person cannot sign the approval, as (code, plain words), or None. No database."""
    from app.core.capabilities import REVIEWER_REFUSAL, need_words

    me = str(user.id)
    decision = gate_kind in DECISION_KINDS
    if any(str(s.get("user_id")) == me for s in signoffs or []):
        return ("ALREADY_SIGNED", "You have already signed this.")
    if decision and not holds(granted, "decisions.review"):
        return ("NOT_REVIEWER", REVIEWER_REFUSAL)
    if (
        gate_kind in ("autonomy.promote", "improvement.release")
        and agent_creator_id == me
        and not self_approval
    ):
        return ("BUILT_IT", "You built this agent, so someone else has to approve it.")
    if policy:
        cap = str(policy.get("capability") or "approvals.sign")
        if not holds(granted, cap):
            if decision and cap == "approvals.sign":
                return ("NOT_REVIEWER", REVIEWER_REFUSAL)
            return (
                "MISSING_PERMISSION",
                need_words(cap).replace("This needs", "Approving this needs"),
            )
        if policy.get("exclude_requester") and str(requested_by) == me:
            return (
                "OWN_REQUEST",
                "You asked for this, so someone else has to approve it.",
            )
        return None
    if _role(user) not in ("admin", "creator") and not holds(granted, "approvals.sign"):
        return (
            "NOT_SIGNER",
            "Only admins, creators and people who can sign approvals can approve this.",
        )
    return None


def visible_to(user: Any, check: tuple[str, str] | None, requested_by: Any) -> bool:
    """A person sees rows they can sign, rows they asked for, and rows they already signed."""
    if check is None or check[0] not in HIDDEN_CODES:
        return True
    return requested_by is not None and str(requested_by) == str(user.id)
