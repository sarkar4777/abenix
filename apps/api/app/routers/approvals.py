"""Approvals API — backend-enforced multi-step sign-off.

Status flips to ``approved`` once at least ``required_signoffs`` rows in the
JSONB ``signoffs`` array carry decision=``approve``. A single ``deny`` flips
status to ``denied``. The ``approval_gate`` runtime tool long-polls
``GET /api/approvals/{id}`` so it sees status transitions.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.deps import get_current_user, get_db
from app.core.hitl import (
    approver_denial,
    is_self_approval,
    get_pending_hitl,
    hitl_row_id,
    hitl_to_approval_row,
    list_pending_hitl,
    parse_hitl_id,
    write_hitl_decision,
)
from app.core.approvers import (
    DECISION_KINDS,
    SOLE_OPERATOR_KINDS,
    can_sign,
    eligible_from,
    is_self_approved,
    people_words,
    sign_check,
    sole_operator_enabled,
    sole_operator_refusal,
    tenant_people,
    visible_to,
)
from app.core.notifications import create_notification
from app.core.responses import error, success
from app.schemas.connectors import (
    ApprovalCreate,
    ApprovalSignoffRequest,
    ApprovalWebhookConfig,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.approval import Approval, ApprovalStatus  # noqa: E402
from models.execution import Execution  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.user import User  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/approvals", tags=["approvals"])
MIN_DENY_REASON = 5


def _signoff_rows(
    signoffs: list[dict[str, Any]] | None, names: dict[str, str] | None
) -> list[dict[str, Any]]:
    """Each sign-off with the signer's name, the email when no name is known."""
    out = []
    for s in signoffs or []:
        uid = str(s.get("user_id") or "")
        name = (names or {}).get(uid) or s.get("user_name") or s.get("user_email")
        out.append({**s, "user_name": name})
    return out


KIND_LABELS = {
    "human_approval": "Agent paused for a person",
    "autonomy.promote": "Autonomy promotion",
    "improvement.release": "Proven fix to release",
    "decision_publish": "Publish a rule change",
    "decision_tier_change": "Lower a risk tier",
    "decision_reattest": "Review after a tier raise",
    "decision_retire": "Retire a version",
    "decision_archive": "Archive a decision",
    "decision_restore": "Restore a decision",
}


def kind_label(kind: str | None) -> str:
    """A gate kind in plain words: gw.plan.change reads Plan change."""
    if not kind:
        return "Request"
    if kind in KIND_LABELS:
        return KIND_LABELS[kind]
    if kind.startswith("action:"):
        return "Agent action"
    parts = kind.replace("_", " ").replace("-", " ").split(".")
    words = " ".join(parts[1:] if len(parts) > 1 else parts).strip()
    return (words[:1].upper() + words[1:]) or "Request"


def _first_text(p: dict[str, Any], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = p.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list) and v and isinstance(v[0], str):
            return v[0].strip()
    return ""


def row_summary(a: Any, agent_name: str | None) -> str:
    """One plain sentence on what is being asked, whatever kind of approval it is."""
    p = a.payload if isinstance(a.payload, dict) else {}
    kind = a.gate_kind or ""
    who = agent_name or (p.get("agent") or {}).get("name") or p.get("agent_name")
    title = (a.title or "").strip()
    if kind.startswith("decision_"):
        text = fix_wording(_first_text(p, ("summary", "reason")))
        return text or title
    if kind == "human_approval":
        detail = _first_text(p, ("details",))
        head = f"{who} paused and asks a person: {title}" if who else title
        return f"{head}. {detail}".strip() if detail else head
    if kind.startswith("action:"):
        intent = _first_text(p, ("intent", "summary"))
        if who and intent:
            return f"{who} wants to act: {intent}"
        return intent or title
    if kind == "autonomy.promote":
        record = (p.get("record") or {}).get("text")
        return f"{title}. {record}." if record else title
    text = _first_text(
        p, ("summary", "why", "details", "detail", "description", "reason")
    )
    changes = p.get("changes")
    if isinstance(changes, list) and changes and isinstance(changes[0], str):
        more = f" and {len(changes) - 1} more" if len(changes) > 1 else ""
        text = (
            f"{text}. First change: {changes[0]}{more}"
            if text
            else f"{changes[0]}{more}"
        )
    head = f"{who} asks: {title}" if who else title
    return f"{head}. {text}" if text else head


def _serialize(
    a: Approval,
    names: dict[str, str] | None = None,
    agents: dict[str, str] | None = None,
) -> dict[str, Any]:
    p = a.payload if isinstance(a.payload, dict) else {}
    status = a.status.value if hasattr(a.status, "value") else str(a.status)
    withdrawn_by = p.get("withdrawn_by")
    agent_name = (agents or {}).get(str(a.agent_id)) if a.agent_id else None
    agent_name = agent_name or (p.get("agent") or {}).get("name") or p.get("agent_name")
    return {
        "kind_label": kind_label(a.gate_kind),
        "summary": row_summary(a, agent_name),
        "agent_name": agent_name,
        "run_label": (
            f"Run of {agent_name}" if a.agent_execution_id and agent_name else None
        ),
        "withdraw_reason": p.get("withdrawn") if status == "withdrawn" else None,
        "withdrawn_by_name": (
            (names or {}).get(str(withdrawn_by))
            if status == "withdrawn" and withdrawn_by
            else None
        ),
        "id": str(a.id),
        "agent_id": str(a.agent_id) if a.agent_id else None,
        "agent_execution_id": (
            str(a.agent_execution_id) if a.agent_execution_id else None
        ),
        "title": a.title or "",
        "payload": (
            {**a.payload, "summary": fix_wording(a.payload.get("summary"))}
            if isinstance(a.payload, dict) and "summary" in a.payload
            else (a.payload or {})
        ),
        "required_signoffs": a.required_signoffs,
        "signoffs": _signoff_rows(a.signoffs, names),
        "status": a.status.value if hasattr(a.status, "value") else str(a.status),
        "requested_by": str(a.requested_by) if a.requested_by else None,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "gate_kind": a.gate_kind,
        "policy": a.policy,
        "client_token": a.client_token,
        "self_approved": is_self_approved(a),
    }


_WORDING = (
    (r"\b1 golden test pass\b", "1 golden test passes"),
    (r"\b1 of (\d+) golden tests fail\b", r"1 of \1 golden tests fails"),
    (r"\b1 pair of rules disagree\b", "1 pair of rules disagrees"),
    (r"\b1 result change compared\b", "1 result changes compared"),
)


def fix_wording(text: Any) -> Any:
    """Older summaries said "1 golden test pass", they read right now."""
    import re

    if not isinstance(text, str):
        return text
    for pat, rep in _WORDING:
        text = re.sub(pat, rep, text)
    return text


def _check_row(viewer: Any, granted: frozenset[str], a: Approval) -> Any:
    p = a.payload or {}
    return sign_check(
        viewer,
        granted,
        requested_by=a.requested_by,
        policy=a.policy,
        gate_kind=a.gate_kind,
        signoffs=a.signoffs,
        agent_creator_id=p.get("agent_creator_id"),
        self_approval=p.get("self_approval"),
    )


def _with_viewer(
    row: dict[str, Any], a: Approval, check: Any, sole: bool
) -> dict[str, Any]:
    pending = a.status == ApprovalStatus.pending
    mine = sole and check is not None and check[0] in ("OWN_REQUEST", "NOT_SIGNER")
    row["can_sign"] = bool(pending and (check is None or sole))
    if row["can_sign"]:
        row["cannot_sign_reason"] = None
    elif not pending:
        status = a.status.value if hasattr(a.status, "value") else str(a.status)
        row["cannot_sign_reason"] = f"This is already {status}."
    else:
        row["cannot_sign_reason"] = check[1] if check else None
    row["sign_alone"] = bool(pending and mine)
    return row


async def _serialize_many(
    db: AsyncSession, rows: list[Approval], viewer: Any = None
) -> list[dict[str, Any]]:
    """Rows with who could sign each one, whether the requester may sign alone, and what the viewer can do."""
    if not rows:
        return []
    from app.core.capabilities import _role, capabilities_for

    tenant_id = rows[0].tenant_id
    try:
        people = await tenant_people(db, tenant_id)
        enabled = await sole_operator_enabled(db, tenant_id)
        granted = await capabilities_for(db, viewer) if viewer is not None else None
    except Exception as e:  # noqa: BLE001
        # the counts help the reader, a failure to work them out must not hide the approval
        logger.warning("approver counts unavailable: %s", e)
        return [
            {
                **_serialize(a),
                "eligible_approver_count": None,
                "sole_operator_available": False,
            }
            for a in rows
        ]
    caps_of = {str(u.id): (u, c) for u, c in people}
    names = await _requester_names(db, rows, caps_of)
    details = await _decision_details(db, rows)
    agents = await _agent_names(db, rows)
    out = []
    for a in rows:
        row = _serialize(a, names, agents)
        row["requested_by_name"] = (
            names.get(str(a.requested_by)) if a.requested_by else None
        )
        extra = details.get(str(a.id)) or {}
        row["change_note"] = extra.get(
            "change_note", (a.payload or {}).get("change_note")
        )
        row["changes"] = extra.get("changes", (a.payload or {}).get("changes"))
        if "changes" in extra and isinstance(row.get("payload"), dict):
            # proposals saved before the count was fixed said 0 for a first version
            row["payload"] = {**row["payload"], "changes": row["changes"]}
        eligible = eligible_from(people, a.policy, a.gate_kind, a.requested_by)
        req = caps_of.get(str(a.requested_by)) if a.requested_by else None
        row["eligible_approver_count"] = len(eligible)
        if a.gate_kind in SOLE_OPERATOR_KINDS and a.status == ApprovalStatus.pending:
            # every decision card can say who can approve it, by name
            row["eligible_approvers"] = [
                {"id": str(u.id), "name": u.full_name or u.email} for u in eligible[:25]
            ]
        row["sole_operator_available"] = bool(
            a.status == ApprovalStatus.pending
            and a.gate_kind in SOLE_OPERATOR_KINDS
            and enabled
            and not eligible
            and req is not None
            and can_sign(_role(req[0]), req[1], a.policy, a.gate_kind)
        )
        if viewer is not None:
            check = _check_row(viewer, granted, a)
            own = a.requested_by is not None and str(a.requested_by) == str(viewer.id)
            row = _with_viewer(
                row, a, check, bool(own and row["sole_operator_available"])
            )
            row["visible"] = _visible_row(viewer, a, check)
        out.append(row)
    return out


def _visible_row(viewer: Any, a: Approval, check: Any) -> bool:
    """Pending: what you can sign or asked for. Settled: what you asked for, signed, or could have signed then."""
    me = str(viewer.id)
    if a.requested_by is not None and str(a.requested_by) == me:
        return True
    if any(str(s.get("user_id")) == me for s in a.signoffs or []):
        return True
    if not visible_to(viewer, check, a.requested_by):
        return False
    if a.status == ApprovalStatus.pending:
        return True
    # a request settled before you joined was never yours to sign
    joined = getattr(viewer, "created_at", None)
    return joined is None or a.created_at is None or a.created_at >= joined


async def _requester_names(
    db: AsyncSession, rows: list[Approval], known: dict[str, Any]
) -> dict[str, str]:
    out = {k: (u.full_name or u.email) for k, (u, _) in known.items()}
    missing = {
        a.requested_by
        for a in rows
        if a.requested_by and str(a.requested_by) not in out
    }
    for a in rows:
        wb = (
            (a.payload or {}).get("withdrawn_by")
            if isinstance(a.payload, dict)
            else None
        )
        if wb and str(wb) not in out:
            try:
                missing.add(uuid.UUID(str(wb)))
            except ValueError:
                pass
        for so in a.signoffs or []:
            uid = so.get("user_id")
            if uid and str(uid) not in out:
                try:
                    missing.add(uuid.UUID(str(uid)))
                except ValueError:
                    pass
    if missing:
        try:
            for uid, name, email in (
                await db.execute(
                    select(User.id, User.full_name, User.email).where(
                        User.id.in_(missing)
                    )
                )
            ).all():
                out[str(uid)] = name or email
        except Exception as e:  # noqa: BLE001
            logger.debug("requester names unavailable: %s", e)
    return out


async def _agent_names(db: AsyncSession, rows: list[Approval]) -> dict[str, str]:
    ids = {a.agent_id for a in rows if a.agent_id}
    if not ids:
        return {}
    try:
        from models.agent import Agent

        return {
            str(i): n
            for i, n in (
                await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(ids)))
            ).all()
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("agent names unavailable: %s", e)
        return {}


async def _decision_details(
    db: AsyncSession, rows: list[Approval]
) -> dict[str, dict[str, Any]]:
    """The change note and rule change count of each decision version waiting to publish."""
    wanted = [
        a
        for a in rows
        if a.gate_kind == "decision_publish"
        and (a.payload or {}).get("decision_key")
        and (a.payload or {}).get("version") is not None
    ]
    if not wanted:
        return {}
    from models.decision import DecisionModel, DecisionVersion

    from app.routers.decisions import rule_changes

    out: dict[str, dict[str, Any]] = {}
    try:
        keys = {(a.payload or {})["decision_key"] for a in wanted}
        found = (
            await db.execute(
                select(DecisionModel.key, DecisionVersion)
                .join(DecisionVersion, DecisionVersion.model_id == DecisionModel.id)
                .where(
                    DecisionModel.tenant_id == wanted[0].tenant_id,
                    DecisionModel.key.in_(keys),
                )
            )
        ).all()
        by = {(k, v.version): v for k, v in found}
        by_id = {str(v.id): v for _, v in found}
        for a in wanted:
            p = a.payload or {}
            v = by.get((p["decision_key"], p["version"]))
            if v is None:
                continue
            base = by_id.get(str(v.base_version_id)) if v.base_version_id else None
            n = rule_changes(v, base)
            out[str(a.id)] = {
                "change_note": p.get("change_note") or v.change_note or "",
                "changes": n if n is not None else p.get("changes"),
            }
    except Exception as e:  # noqa: BLE001
        logger.debug("decision details unavailable: %s", e)
    return out


async def _sweep_archived(db: AsyncSession, tenant_id: Any) -> None:
    """Withdraw approvals left open on decisions that were archived since."""
    try:
        from app.routers.decisions import sweep_archived

        await sweep_archived(db, tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("archived decision sweep failed: %s", e)
        await db.rollback()


async def _serialize_one(
    db: AsyncSession, a: Approval, viewer: Any = None
) -> dict[str, Any]:
    row = (await _serialize_many(db, [a], viewer))[0]
    row.pop("visible", None)
    return row


def _evaluate_status(a: Approval) -> ApprovalStatus:
    """Walk the signoffs array and return the new status. Pure function."""
    signoffs = a.signoffs or []
    approve_count = sum(1 for s in signoffs if s.get("decision") == "approve")
    deny_count = sum(1 for s in signoffs if s.get("decision") == "deny")
    if deny_count > 0:
        return ApprovalStatus.denied
    if any(s.get("decision") == "return" for s in signoffs):
        return ApprovalStatus.returned
    if approve_count >= a.required_signoffs:
        return ApprovalStatus.approved
    if a.expires_at and a.expires_at < datetime.now(timezone.utc):
        return ApprovalStatus.expired
    return ApprovalStatus.pending


async def _tier_floor(
    db: AsyncSession, user: User, body: Any
) -> tuple[int, dict | None]:
    """Sign-offs and signing rules for a new approval: what was asked, raised to the tier's policy."""
    from engine import governance, risk

    tier = body.risk_tier
    if not tier and body.agent_execution_id:
        from models.execution import Execution

        tier = (
            await db.execute(
                select(Execution.risk_tier).where(
                    Execution.id == body.agent_execution_id,
                    Execution.tenant_id == user.tenant_id,
                )
            )
        ).scalar()
    if not tier or risk.normalize(tier) == "low":
        return body.required_signoffs, None
    await governance.ensure_fresh()
    pol = (
        governance.policy(str(user.tenant_id), risk.normalize(tier)).get(
            "publish_approvals"
        )
        or {}
    )
    floor = int(pol.get("min_approvers") or 0)
    policy = {
        "exclude_requester": bool(pol.get("exclude_author")),
        "capability": pol.get("capability") or "approvals.sign",
        "risk_tier": risk.normalize(tier),
        "escalate_after_hours": int(pol.get("escalate_after_hours") or 0),
        "escalate_after_minutes": risk.escalate_minutes(pol),
    }
    return max(body.required_signoffs, floor), policy


async def escalate_overdue(db: AsyncSession) -> int:
    """Tell a tenant's admins once about each tiered approval nobody has acted on in time."""
    now = datetime.now(timezone.utc)
    rows = (
        (
            await db.execute(
                select(Approval).where(
                    Approval.status == ApprovalStatus.pending,
                    Approval.escalated_at.is_(None),
                    Approval.policy.isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )
    from engine.risk import escalate_minutes, wait_words

    sent = 0
    for a in rows:
        minutes = escalate_minutes(a.policy)
        if minutes <= 0 or a.created_at + timedelta(minutes=minutes) > now:
            continue
        admins = (
            (
                await db.execute(
                    select(User.id).where(
                        User.tenant_id == a.tenant_id,
                        User.role == "admin",
                        User.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        got = len(a.signoffs or [])
        for uid in admins:
            await create_notification(
                db,
                tenant_id=a.tenant_id,
                user_id=uid,
                type="system_alert",
                title=f"Approval waiting over {wait_words(minutes)}: {a.title or 'untitled'}",
                message=f"{got} of {a.required_signoffs} sign-offs so far. It is {a.policy.get('risk_tier', 'tiered')} risk, so it needs someone to act.",
                link="/approvals",
                metadata={"approval_id": str(a.id)},
            )
        a.escalated_at = now
        sent += 1
    await db.commit()
    return sent


async def _expire_stale(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Sweep pending rows past their deadline. Cheap inline call from list/get."""
    from app.services.events import emit

    now = datetime.now(timezone.utc)
    expired = (
        await db.execute(
            update(Approval)
            .where(
                Approval.tenant_id == tenant_id,
                Approval.status == ApprovalStatus.pending,
                Approval.expires_at.isnot(None),
                Approval.expires_at < now,
            )
            .values(status=ApprovalStatus.expired, decided_at=now)
            .returning(Approval.id, Approval.title, Approval.gate_kind)
        )
    ).all()
    for aid, title, gate_kind in expired:
        await emit(
            db,
            tenant_id,
            "approval.resolved",
            {
                "approval_id": str(aid),
                "status": ApprovalStatus.expired.value,
                "gate_kind": gate_kind,
                "title": title,
            },
        )
    await db.commit()
    for aid, _, gate_kind in expired:
        if gate_kind in DECISION_KINDS:
            from app.routers.decisions import on_approval_resolved

            row = await db.get(Approval, aid)
            if row is not None:
                await on_approval_resolved(db, row)
        elif gate_kind and (
            gate_kind.startswith("action:")
            or gate_kind in ("autonomy.promote", "improvement.release")
        ):
            row = await db.get(Approval, aid)
            if row is not None:
                await _autonomy_resolved(db, row, None)


@router.post("")
async def create_approval(
    body: ApprovalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if body.client_token:
        existing = await db.execute(
            select(Approval).where(
                Approval.tenant_id == user.tenant_id,
                Approval.client_token == body.client_token,
            )
        )
        prior = existing.scalar_one_or_none()
        if prior is not None:
            return success(_serialize(prior), status_code=200)

    expires_at = None
    if body.expires_seconds:
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=body.expires_seconds
        )
    required, policy = await _tier_floor(db, user, body)
    a = Approval(
        tenant_id=user.tenant_id,
        agent_id=body.agent_id,
        agent_execution_id=body.agent_execution_id,
        title=body.title,
        payload=body.payload,
        required_signoffs=required,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=user.id,
        expires_at=expires_at,
        gate_kind=body.gate_kind,
        client_token=body.client_token,
        policy=policy,
    )
    db.add(a)
    await db.flush()
    from app.services.events import emit

    await emit(
        db,
        user.tenant_id,
        "approval.requested",
        {
            "approval_id": str(a.id),
            "title": a.title,
            "gate_kind": a.gate_kind,
            "required_signoffs": a.required_signoffs,
        },
    )
    await db.commit()
    await db.refresh(a)
    await _notify_pending(db, a, requester=user)
    return success(_serialize(a), status_code=201)


@router.get("")
async def list_approvals(
    mine: int = Query(
        0,
        description="If 1, restrict to approvals the caller has rights to act on (tenant scope today)",
    ),
    status: str | None = Query(
        None,
        description="pending | approved | denied | expired | returned | withdrawn, or resolved for every settled row, paged with offset",
    ),
    execution_id: uuid.UUID | None = Query(
        None, description="Filter to approvals linked to a specific execution"
    ),
    agent_id: uuid.UUID | None = Query(
        None, description="Filter to approvals raised by a specific agent"
    ),
    kind: str | None = Query(None, description="Filter by gate_kind discriminator"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0, description="Rows to skip, with status=resolved"),
    resolved_offset: int | None = Query(
        None, ge=0, description="Same as status=resolved with this offset"
    ),
    all: int = Query(
        0,
        ge=0,
        le=1,
        description="Admins only: every row, not just what you can sign and your own requests",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # called directly, the Query defaults are not values
    offset = offset if isinstance(offset, int) else 0
    resolved_offset = resolved_offset if isinstance(resolved_offset, int) else None
    all = all if isinstance(all, int) else 0
    await _expire_stale(db, user.tenant_id)
    await _sweep_archived(db, user.tenant_id)
    if resolved_offset is not None:
        status, offset = "resolved", resolved_offset
    stmt = select(Approval).where(Approval.tenant_id == user.tenant_id)
    if status == "resolved":
        return await _resolved_page(
            db, user, stmt, execution_id, agent_id, kind, limit, offset, all
        )
    if status:
        try:
            stmt = stmt.where(Approval.status == ApprovalStatus(status))
        except ValueError:
            return error(f"Invalid status: {status}", 400)
    if execution_id is not None:
        stmt = stmt.where(Approval.agent_execution_id == execution_id)
    if agent_id is not None:
        stmt = stmt.where(Approval.agent_id == agent_id)
    if kind:
        stmt = stmt.where(Approval.gate_kind == kind)
    from app.core.permissions import is_admin

    everything = bool(all) and is_admin(user)
    # rows the viewer cannot see are dropped after the read, so read past the page
    stmt = stmt.order_by(Approval.created_at.desc()).limit(
        limit if everything else min(limit * 4, 2000)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    _ = mine  # the default view is already what you can act on
    items = await _serialize_many(db, list(rows), user)
    if not everything:
        items = [r for r in items if r.get("visible", True)]
    for r in items:
        r.pop("visible", None)
    found = len(items)
    scanned_all = len(rows) < (limit if everything else min(limit * 4, 2000))
    items = items[:limit]
    meta = {
        "total": found if scanned_all else None,
        "has_more": found > limit or not scanned_all,
        "limit": limit,
    }

    # Runtime human_approval gates live in Redis, not in the approvals table
    include_hitl = (
        (status is None or status == "pending")
        and (kind is None or kind == "human_approval")
        and agent_id is None
    )
    if include_hitl:
        from app.core.capabilities import capabilities_for

        hitl_caps = await capabilities_for(db, user)
        try:
            gates = await list_pending_hitl(str(user.tenant_id))
        except Exception as e:
            logger.warning("hitl pending list unavailable: %s", e)
            gates = []
        for g in gates:
            if execution_id is not None and str(g.get("execution_id")) != str(
                execution_id
            ):
                continue
            row = hitl_to_approval_row(g)
            row.setdefault("self_approved", False)
            row.setdefault("sole_operator_available", False)
            row.setdefault("eligible_approver_count", None)
            gate_agent = (row.get("payload") or {}).get("agent_name") or g.get(
                "agent_name"
            )
            row.setdefault("kind_label", kind_label("human_approval"))
            row.setdefault("agent_name", gate_agent)
            row.setdefault(
                "summary",
                row_summary(
                    SimpleNamespace(
                        payload=row.get("payload") or {},
                        gate_kind="human_approval",
                        title=row.get("title") or "",
                    ),
                    gate_agent,
                ),
            )
            row.setdefault("withdraw_reason", None)
            row.setdefault("withdrawn_by_name", None)
            check = sign_check(
                user,
                hitl_caps,
                requested_by=row.get("requested_by"),
                policy=None,
                gate_kind="human_approval",
                signoffs=[],
            )
            if not everything and not visible_to(user, check, row.get("requested_by")):
                continue
            row["can_sign"] = check is None
            row["cannot_sign_reason"] = check[1] if check else None
            row["sign_alone"] = False
            items.append(row)
        items.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        items = items[:limit]
    return success(items, meta=meta)


RESOLVED_SCAN = 5000


async def _resolved_page(
    db: AsyncSession,
    user: User,
    stmt: Any,
    execution_id: Any,
    agent_id: Any,
    kind: str | None,
    limit: int,
    offset: int,
    everything_asked: int,
) -> JSONResponse:
    """Settled approvals the viewer may see, a page at a time with the total."""
    from app.core.capabilities import capabilities_for
    from app.core.permissions import is_admin

    stmt = stmt.where(Approval.status != ApprovalStatus.pending)
    if execution_id is not None:
        stmt = stmt.where(Approval.agent_execution_id == execution_id)
    if agent_id is not None:
        stmt = stmt.where(Approval.agent_id == agent_id)
    if kind:
        stmt = stmt.where(Approval.gate_kind == kind)
    rows = list(
        (
            await db.execute(
                stmt.order_by(
                    Approval.decided_at.desc().nullslast(), Approval.created_at.desc()
                ).limit(RESOLVED_SCAN)
            )
        )
        .scalars()
        .all()
    )
    if not (bool(everything_asked) and is_admin(user)):
        granted = await capabilities_for(db, user)
        rows = [a for a in rows if _visible_row(user, a, _check_row(user, granted, a))]
    page = rows[offset : offset + limit]
    items = await _serialize_many(db, page, user)
    for r in items:
        r.pop("visible", None)
    return success(
        items,
        meta={
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < len(rows),
            "capped": len(rows) >= RESOLVED_SCAN,
        },
    )


async def _hitl_execution(
    db: AsyncSession, user: User, execution_id: str
) -> Execution | None:
    try:
        ex_uuid = uuid.UUID(execution_id)
    except ValueError:
        return None
    res = await db.execute(
        select(Execution).where(
            Execution.id == ex_uuid, Execution.tenant_id == user.tenant_id
        )
    )
    return res.scalar_one_or_none()


async def _hitl_history_row(
    db: AsyncSession, tenant_id: uuid.UUID, execution_id: str, gate_id: str
) -> Approval | None:
    res = await db.execute(
        select(Approval).where(
            Approval.tenant_id == tenant_id,
            Approval.client_token == hitl_row_id(execution_id, gate_id),
        )
    )
    return res.scalar_one_or_none()


async def _hitl_snapshot(
    db: AsyncSession, user: User, execution_id: str, gate_id: str
) -> dict[str, Any] | None:
    """Pending gate as a row, the recorded decision row, or None."""
    exec_row = await _hitl_execution(db, user, execution_id)
    if exec_row is None:
        return None
    pending = await get_pending_hitl(str(user.tenant_id), execution_id, gate_id)
    if pending is not None:
        row = hitl_to_approval_row(pending)
        row["requested_by"] = str(exec_row.user_id) if exec_row.user_id else None
        return row
    history = await _hitl_history_row(db, user.tenant_id, execution_id, gate_id)
    if history is not None:
        return _serialize(history)
    return None


@router.get("/webhooks")
async def get_webhook(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    settings = await _tenant_settings(db, user.tenant_id)
    return success(
        {
            "url": settings.get("approval_webhook_url"),
            "has_secret": bool(settings.get("approval_webhook_secret")),
        }
    )


@router.put("/webhooks")
async def set_webhook(
    body: ApprovalWebhookConfig,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.role.value not in ("admin", "owner"):
        return error("Only tenant admins can configure approval webhooks", 403)
    res = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = res.scalar_one_or_none()
    if not tenant:
        return error("Tenant not found", 404)
    settings = dict(tenant.settings or {})
    if body.url is None:
        settings.pop("approval_webhook_url", None)
    else:
        settings["approval_webhook_url"] = body.url.strip() or None
    if body.secret is not None:
        if body.secret == "":
            settings.pop("approval_webhook_secret", None)
        else:
            settings["approval_webhook_secret"] = crypto.encrypt(tenant.id, body.secret)
    from sqlalchemy.orm.attributes import flag_modified

    tenant.settings = settings
    flag_modified(tenant, "settings")
    await db.commit()
    return success(
        {
            "url": settings.get("approval_webhook_url"),
            "has_secret": bool(settings.get("approval_webhook_secret")),
        }
    )


def _parse_approval_id(approval_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(approval_id)
    except (ValueError, TypeError):
        return None


@router.get("/{approval_id}")
async def get_approval(
    approval_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    hitl = parse_hitl_id(approval_id)
    if hitl:
        row = await _hitl_snapshot(db, user, *hitl)
        return success(row) if row else error("Approval not found", 404)
    approval_uuid = _parse_approval_id(approval_id)
    if approval_uuid is None:
        return error("Approval not found", 404)
    result = await db.execute(
        select(Approval).where(
            Approval.id == approval_uuid, Approval.tenant_id == user.tenant_id
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        return error("Approval not found", 404)
    if (
        a.status == ApprovalStatus.pending
        and a.expires_at
        and a.expires_at < datetime.now(timezone.utc)
    ):
        a.status = ApprovalStatus.expired
        a.decided_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(a)
    return success(await _serialize_one(db, a, user))


@router.get("/{approval_id}/wait")
async def wait_for_approval(
    approval_id: str,
    timeout_seconds: int = Query(30, ge=1, le=120),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Long-poll a single approval until status leaves pending or timeout fires.

    SDK consumers call this from a worker that picked up an `approval_id`
    out-of-band (queue, webhook, scheduled job) and want the resolved row
    without burning CPU on a 2-second loop.
    """
    deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    hitl = parse_hitl_id(approval_id)
    if hitl:
        while True:
            row = await _hitl_snapshot(db, user, *hitl)
            if row is None:
                return error("Approval not found", 404)
            if row.get("status") != "pending" or datetime.now(timezone.utc) >= deadline:
                return success(row)
            # hand the connection back while sleeping, a 120 s wait must not hold one of the pool
            await db.close()
            await asyncio.sleep(1.0)
    approval_uuid = _parse_approval_id(approval_id)
    if approval_uuid is None:
        return error("Approval not found", 404)
    while True:
        result = await db.execute(
            select(Approval).where(
                Approval.id == approval_uuid, Approval.tenant_id == user.tenant_id
            )
        )
        a = result.scalar_one_or_none()
        if not a:
            return error("Approval not found", 404)
        if (
            a.status == ApprovalStatus.pending
            and a.expires_at
            and a.expires_at < datetime.now(timezone.utc)
        ):
            a.status = ApprovalStatus.expired
            a.decided_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(a)
        if a.status != ApprovalStatus.pending:
            return success(_serialize(a))
        if datetime.now(timezone.utc) >= deadline:
            return success(_serialize(a))
        # closing returns the connection and drops the loaded row, so the next read sees the sign-off
        await db.close()
        await asyncio.sleep(1.0)


async def _sign_off_hitl(
    db: AsyncSession,
    user: User,
    execution_id: str,
    gate_id: str,
    body: ApprovalSignoffRequest,
) -> JSONResponse:
    exec_row = await _hitl_execution(db, user, execution_id)
    if exec_row is None:
        return error("Approval not found", 404)
    history = await _hitl_history_row(db, user.tenant_id, execution_id, gate_id)
    if history is not None:
        return error(f"Approval is already {history.status.value}", 409)
    pending = await get_pending_hitl(str(user.tenant_id), execution_id, gate_id)
    if pending is None:
        return error(
            "This run is no longer waiting for an answer, it ended or the request expired.",
            409,
            error_code="GATE_CLOSED",
        )
    status = getattr(
        getattr(exec_row, "status", None), "value", getattr(exec_row, "status", None)
    )
    if str(status).lower() in ("completed", "failed", "cancelled", "canceled"):
        return error(
            f"This run already {str(status).lower()}, so nothing is waiting for this answer.",
            409,
            error_code="GATE_CLOSED",
        )
    denial = await approver_denial(db, user, exec_row.user_id)
    if denial:
        return error(denial, 403)

    decision = "approved" if body.decision == "approve" else "rejected"
    written = await write_hitl_decision(
        execution_id=execution_id,
        gate_id=gate_id,
        decision=decision,
        reviewer=user.full_name or user.email,
        reviewer_id=str(user.id),
        tenant_id=str(user.tenant_id),
        comment=body.reason or "",
    )
    if not written:
        return error("Approval is already decided", 409)

    now = datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "user_id": str(user.id),
        "user_email": user.email,
        "decision": body.decision,
        "reason": body.reason or "",
        "at": now.isoformat(),
    }
    if body.client_token:
        record["client_token"] = body.client_token
    # History row so the decision shows under recent decisions and notifies the requester
    a = Approval(
        tenant_id=user.tenant_id,
        agent_id=exec_row.agent_id,
        agent_execution_id=exec_row.id,
        title=pending.get("action") or "Approval requested",
        payload={
            "details": pending.get("details") or "",
            "risk_level": pending.get("risk_level") or "medium",
            "agent_name": pending.get("agent_name") or "",
            "gate_id": gate_id,
        },
        required_signoffs=1,
        signoffs=[record],
        status=(
            ApprovalStatus.approved if decision == "approved" else ApprovalStatus.denied
        ),
        requested_by=exec_row.user_id,
        expires_at=None,
        decided_at=now,
        gate_kind="human_approval",
        client_token=hitl_row_id(execution_id, gate_id),
    )
    requested_at = pending.get("requested_at")
    if requested_at:
        a.created_at = datetime.fromtimestamp(float(requested_at), tz=timezone.utc)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    await _notify_resolved(db, a, decider=user)
    return success(_serialize(a))


@router.post("/{approval_id}/signoff")
async def sign_off(
    approval_id: str,
    body: ApprovalSignoffRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if body.decision not in ("approve", "deny", "return"):
        return error("decision must be approve, deny or return", 400)
    if body.decision == "return" and not (body.reason or "").strip():
        return error("Say what needs to change, so the requester can correct it.", 400)
    if body.decision == "deny" and len((body.reason or "").strip()) < MIN_DENY_REASON:
        return error(
            f"Say why you are denying it, at least {MIN_DENY_REASON} characters. The requester is told.",
            422,
            error_code="REASON_REQUIRED",
        )
    hitl = parse_hitl_id(approval_id)
    if hitl:
        return await _sign_off_hitl(db, user, hitl[0], hitl[1], body)
    approval_uuid = _parse_approval_id(approval_id)
    if approval_uuid is None:
        return error("Approval not found", 404)
    result = await db.execute(
        select(Approval).where(
            Approval.id == approval_uuid, Approval.tenant_id == user.tenant_id
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        return error("Approval not found", 404)

    if body.client_token:
        for s in a.signoffs or []:
            if s.get("client_token") == body.client_token:
                return success(_serialize(a))

    if a.status != ApprovalStatus.pending:
        return error(f"Approval is already {a.status.value}", 409)

    if a.gate_kind in DECISION_KINDS and a.gate_kind != "decision_restore":
        from app.routers import decisions as decisions_router

        key = (a.payload or {}).get("decision_key")
        if await decisions_router.archived_key(db, a.tenant_id, key):
            await decisions_router.sweep_archived(db, a.tenant_id)
            return error(
                decisions_router.ARCHIVED_REFUSAL, 409, error_code="DECISION_ARCHIVED"
            )

    edited = body.edited_arguments
    if edited is not None:
        if not (a.gate_kind or "").startswith("action:"):
            return error("Only action approvals take edited arguments.", 400)
        if body.decision != "approve":
            return error("Edited arguments go with an approval, not a rejection.", 400)
    if a.gate_kind == "autonomy.promote":
        from app.services.autonomy import promotion_denial

        refused = await promotion_denial(db, user, a)
        if refused:
            return error(refused, 403, error_code="AUTHOR_CANNOT_GRANT")
    if a.gate_kind == "improvement.release" and body.decision == "approve":
        from app.services.improvements import release_denial

        refused = await release_denial(db, user, a)
        if refused:
            return error(refused, 403, error_code="AUTHOR_CANNOT_APPROVE")

    sole = bool(body.sole_operator)
    if sole:
        from app.core.capabilities import _role, capabilities_for

        people = await tenant_people(db, a.tenant_id)
        eligible = eligible_from(people, a.policy, a.gate_kind, a.requested_by)
        refused = sole_operator_refusal(
            gate_kind=a.gate_kind,
            decision=body.decision,
            reason=body.reason,
            is_requester=is_self_approval(user, a.requested_by),
            requester_can_sign=can_sign(
                _role(user), await capabilities_for(db, user), a.policy, a.gate_kind
            ),
            enabled=await sole_operator_enabled(db, a.tenant_id),
            eligible_count=len(eligible),
        )
        if refused:
            status_code, code, message = refused
            return error(message, status_code, error_code=code)
    else:
        denial = await approver_denial(db, user, a.requested_by, a.policy, a.gate_kind)
        if denial:
            cap = getattr(denial, "capability", None)
            if a.gate_kind in SOLE_OPERATOR_KINDS and is_self_approval(
                user, a.requested_by
            ):
                denial = await _sole_hint(db, a, denial)
            return error(
                str(denial),
                403,
                error_code="CANNOT_SIGN" if cap else None,
                details={"capability": cap} if cap else None,
            )

    if edited is not None:
        from app.services.autonomy import validate_edited_arguments

        merged, problem = validate_edited_arguments(a.payload or {}, edited)
        if problem:
            return error(problem, 400, error_code="BAD_EDITED_ARGUMENTS")
        # the runtime reads payload.edited_arguments when the gate opens
        a.payload = {**(a.payload or {}), "edited_arguments": merged}

    signoffs = list(a.signoffs or [])
    if any(s.get("user_id") == str(user.id) for s in signoffs):
        return error("User has already signed off on this approval", 409)
    record: dict[str, Any] = {
        "user_id": str(user.id),
        "user_email": user.email,
        "user_name": user.full_name or user.email,
        "decision": body.decision,
        "reason": body.reason or "",
        "at": datetime.now(timezone.utc).isoformat(),
        "self_approved": is_self_approval(user, a.requested_by),
        "sole_operator": sole,
    }
    if body.client_token:
        record["client_token"] = body.client_token
    signoffs.append(record)
    a.signoffs = signoffs
    prev_status = a.status
    # nobody else can sign, so the one recorded sign-off settles it whatever the count
    new_status = ApprovalStatus.approved if sole else _evaluate_status(a)
    a.status = new_status
    if new_status != ApprovalStatus.pending:
        a.decided_at = datetime.now(timezone.utc)
    if sole:
        from app.core.audit import log_action

        await log_action(
            db,
            a.tenant_id,
            user.id,
            "approval.self_approved",
            {
                "approval_id": str(a.id),
                "gate_kind": a.gate_kind,
                "title": a.title,
                "reason": (body.reason or "").strip(),
                "eligible_approvers": 0,
                "required_signoffs": a.required_signoffs,
            },
            resource_type="approval",
            resource_id=str(a.id),
        )
    await db.commit()
    await db.refresh(a)
    if sole:
        await _notify_self_approved(db, a, user, (body.reason or "").strip())
    if prev_status == ApprovalStatus.pending and new_status != ApprovalStatus.pending:
        from app.services.events import emit

        await emit(
            db,
            a.tenant_id,
            "approval.resolved",
            {
                "approval_id": str(a.id),
                "status": new_status.value,
                "gate_kind": a.gate_kind,
                "title": a.title,
            },
        )
        await db.commit()
        if a.gate_kind in DECISION_KINDS:
            from app.routers.decisions import on_approval_resolved

            await on_approval_resolved(db, a)
        await _autonomy_resolved(db, a, user)
        await _notify_resolved(db, a, decider=user)
    return success(await _serialize_one(db, a, user))


async def _sole_hint(db: AsyncSession, a: Approval, denial: str) -> str:
    """Tell the requester who else can sign, or that they may sign alone."""
    people = await tenant_people(db, a.tenant_id)
    n = len(eligible_from(people, a.policy, a.gate_kind, a.requested_by))
    if n:
        return f"{denial} {people_words(n)}"
    if await sole_operator_enabled(db, a.tenant_id):
        return f"{denial} Nobody else in this workspace can, so you can sign it alone with a written reason."
    return denial


async def _notify_self_approved(
    db: AsyncSession, a: Approval, user: User, reason: str
) -> None:
    admins = (
        (
            await db.execute(
                select(User.id).where(
                    User.tenant_id == a.tenant_id,
                    User.role == "admin",
                    User.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    who = user.full_name or user.email
    for uid in admins:
        # you know you signed it, the other admins are the ones to tell
        if uid == user.id:
            continue
        try:
            await create_notification(
                db,
                tenant_id=a.tenant_id,
                user_id=uid,
                type="system_alert",
                title=f"Self-approved: {(a.title or 'an approval')[:80]}",
                message=f"{who} approved their own request because nobody else in the workspace can. Reason: {reason}",
                link="/approvals",
                metadata={
                    "approval_id": str(a.id),
                    "gate_kind": a.gate_kind,
                    "self_approved": True,
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("self-approval notice failed: %s", e)
    await db.commit()


async def _autonomy_resolved(db: AsyncSession, a: Approval, decider: Any) -> None:
    """Promotions change the level, action gates update their ledger row, fixes get released."""
    kind = a.gate_kind or ""
    if kind == "improvement.release":
        from app.services import improvements as improvements_svc

        try:
            await improvements_svc.on_release_resolved(db, a, decider)
        except Exception:
            logger.exception("improvement follow-up for approval %s failed", a.id)
            await db.rollback()
        return
    if not (kind.startswith("action:") or kind == "autonomy.promote"):
        return
    from app.services import autonomy as autonomy_svc

    try:
        if kind == "autonomy.promote":
            await autonomy_svc.on_promotion_resolved(db, a, decider)
        else:
            await autonomy_svc.on_action_gate_resolved(db, a, decider)
    except Exception:
        logger.exception("autonomy follow-up for approval %s failed", a.id)
        await db.rollback()


async def _tenant_settings(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    res = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = res.scalar_one_or_none()
    return dict(tenant.settings or {}) if tenant else {}


async def _post_webhook(
    settings: dict[str, Any],
    event: str,
    payload: dict[str, Any],
    tenant_id: uuid.UUID | str | None = None,
) -> None:
    url = (settings.get("approval_webhook_url") or "").strip()
    if not url:
        return
    secret = settings.get("approval_webhook_secret") or ""
    if secret and tenant_id is not None:
        secret = crypto.decrypt(tenant_id, secret)
    body = {"event": event, "data": payload}
    headers = {"Content-Type": "application/json"}
    if secret:
        import hashlib
        import hmac
        import json as _json

        raw = _json.dumps(body, separators=(",", ":")).encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        headers["X-Abenix-Signature"] = f"sha256={sig}"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=body, headers=headers)
    except Exception as e:
        logger.warning("approval webhook to %s failed: %s", url, e)


async def _notify_pending(
    db: AsyncSession, approval: Approval, *, requester: User
) -> None:
    """Tell every other user in the tenant a new approval needs their attention."""
    res = await db.execute(
        select(User).where(
            User.tenant_id == approval.tenant_id,
            User.is_active.is_(True),
            User.id != requester.id,
        )
    )
    targets = res.scalars().all()
    title = approval.title or "Approval requested"
    truncated_title = title if len(title) <= 80 else title[:77] + "..."
    requester_name = requester.full_name or requester.email or "An agent"
    message = f"{requester_name} requested approval — open the queue to review."
    metadata = {
        "approval_id": str(approval.id),
        "agent_id": str(approval.agent_id) if approval.agent_id else None,
        "agent_execution_id": (
            str(approval.agent_execution_id) if approval.agent_execution_id else None
        ),
        "required_signoffs": approval.required_signoffs,
        "expires_at": (
            approval.expires_at.isoformat() if approval.expires_at else None
        ),
        "gate_kind": approval.gate_kind,
    }
    for target in targets:
        await create_notification(
            db,
            tenant_id=approval.tenant_id,
            user_id=target.id,
            type="approval_pending",
            title=truncated_title,
            message=message,
            link="/approvals",
            metadata=metadata,
            slack=False,
        )
    await db.commit()
    # one post for the shared channel, not one per member
    if targets:
        from app.core.notifications import post_once_to_tenant_slack

        await post_once_to_tenant_slack(
            db,
            approval.tenant_id,
            title=f"Approval requested: {truncated_title}",
            message=message,
            link="/approvals",
        )
    settings = await _tenant_settings(db, approval.tenant_id)
    await _post_webhook(
        settings, "approval_pending", _serialize(approval), approval.tenant_id
    )


async def _notify_resolved(
    db: AsyncSession, approval: Approval, *, decider: User
) -> None:
    """Tell the requester (and any prior signers) that the approval landed."""
    if not approval.requested_by:
        return
    status_value = (
        approval.status.value
        if hasattr(approval.status, "value")
        else str(approval.status)
    )
    title = approval.title or "Approval resolved"
    truncated_title = title if len(title) <= 80 else title[:77] + "..."
    decider_name = decider.full_name or decider.email or "A reviewer"
    message = f"{decider_name} {status_value} this request."
    why = next(
        (
            (s.get("reason") or "").strip()
            for s in reversed(approval.signoffs or [])
            if s.get("decision") in ("deny", "return")
            and (s.get("reason") or "").strip()
        ),
        "",
    )
    if why and status_value in ("denied", "returned"):
        message = f"{message} Reason: {why}"
    targets: set[uuid.UUID] = {approval.requested_by}
    for s in approval.signoffs or []:
        sid = s.get("user_id")
        if sid:
            try:
                targets.add(uuid.UUID(sid))
            except (ValueError, TypeError):
                continue
    targets.discard(decider.id)
    metadata = {
        "approval_id": str(approval.id),
        "status": status_value,
        "agent_id": str(approval.agent_id) if approval.agent_id else None,
        "gate_kind": approval.gate_kind,
    }
    decision_gate = approval.gate_kind in DECISION_KINDS
    link = "/approvals"
    if decision_gate and isinstance((approval.payload or {}).get("link"), str):
        link = approval.payload["link"]
    for target_id in targets:
        await create_notification(
            db,
            tenant_id=approval.tenant_id,
            user_id=target_id,
            type="approval_resolved",
            title=truncated_title,
            message=message,
            link=link,
            metadata=metadata,
            # the person who asked always hears the outcome, by email too when it is on
            email=decision_gate and target_id == approval.requested_by,
        )
    if targets:
        await db.commit()
    settings = await _tenant_settings(db, approval.tenant_id)
    await _post_webhook(
        settings, "approval_resolved", _serialize(approval), approval.tenant_id
    )
