"""Human review inbox for held content: queue, decisions, delivery, timeouts and retention."""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from engine.moderation_hold import (  # noqa: E402
    HOLD_BLOCK,
    REJECTED_STATUSES,
    RELEASED_STATUSES,
    hold_block,
    seal,
    unseal,
)
from models.moderation_policy import ModerationReview  # noqa: E402

logger = logging.getLogger(__name__)

REVIEW_CAP = "moderation.review"
PENDING = "pending"
DECIDED_STATUSES = RELEASED_STATUSES + REJECTED_STATUSES
STATUS_LABEL = {
    "pending": "Waiting for review",
    "released": "Released",
    "redacted": "Redacted and released",
    "rejected": "Rejected",
    "auto_released": "Released when the time ran out",
    "auto_rejected": "Rejected when the time ran out",
}
SOURCE_LABEL = {
    "pre_llm": "User message",
    "post_llm": "Agent reply",
    "tool_output": "Tool output",
}
PRIORITY_LABEL = {3: "High", 2: "Medium", 1: "Low"}
MAX_REASON = 1000
MAX_BULK = 100

RETENTION_KEY = "moderation_retention"
RETENTION_DEFAULTS = {
    "held_content_days": 30,
    "decision_record_days": 365,
    "event_preview_days": 30,
}
RETENTION_LIMITS = {
    "held_content_days": (0, 365),
    "decision_record_days": (30, 3650),
    "event_preview_days": (1, 365),
}
RETENTION_FIELD = {
    "held_content_days": "Full held text after a decision",
    "decision_record_days": "Decision records",
    "event_preview_days": "Event previews",
}
PURGE_BATCH = 5000


class ReviewError(Exception):
    def __init__(self, message: str, code: int = 400, error_code: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code
        self.error_code = error_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── retention settings ───────────────────────────────────────────


def retention_from(settings: dict | None) -> dict[str, Any]:
    raw = dict((settings or {}).get(RETENTION_KEY) or {})
    out: dict[str, Any] = {}
    for key, default in RETENTION_DEFAULTS.items():
        try:
            out[key] = int(raw.get(key, default))
        except (TypeError, ValueError):
            out[key] = default
    out["updated_at"] = raw.get("updated_at")
    out["updated_by"] = raw.get("updated_by")
    out["updated_by_name"] = raw.get("updated_by_name")
    return out


def validate_retention(body: dict) -> tuple[dict[str, int], dict[str, str]]:
    """Whole days within each field's range. Returns (values, errors by field)."""
    values: dict[str, int] = {}
    errors: dict[str, str] = {}
    for key, (lo, hi) in RETENTION_LIMITS.items():
        if key not in body:
            continue
        v = body.get(key)
        if isinstance(v, bool) or v is None or v == "":
            errors[key] = f"{RETENTION_FIELD[key]} needs a number of days."
            continue
        try:
            n = int(v)
            if float(v) != n:
                raise ValueError
        except (TypeError, ValueError):
            errors[key] = f"{RETENTION_FIELD[key]} must be a whole number of days."
            continue
        if n < lo or n > hi:
            errors[key] = f"{RETENTION_FIELD[key]} must be between {lo} and {hi} days."
            continue
        values[key] = n
    held = values.get("held_content_days")
    record = values.get("decision_record_days")
    if held is not None and record is not None and held > record:
        errors["held_content_days"] = (
            "Full held text cannot be kept longer than the decision record."
        )
    return values, errors


# ── who reviews ──────────────────────────────────────────────────


async def reviewer_ids(db: AsyncSession, tenant_id: uuid.UUID) -> list[uuid.UUID]:
    """Active people in the tenant who hold moderation.review, admins included."""
    from sqlalchemy import Text, cast
    from sqlalchemy.dialects.postgresql import ARRAY, array

    from models.governance import PermissionAssignment, PermissionSet
    from models.user import User, UserRole

    granted = (
        select(PermissionAssignment.user_id)
        .join(PermissionSet, PermissionSet.id == PermissionAssignment.permission_set_id)
        .where(
            PermissionAssignment.tenant_id == tenant_id,
            PermissionSet.capabilities.op("?|")(
                cast(array([REVIEW_CAP, "moderation.*", "*"]), ARRAY(Text))
            ),
        )
    )
    rows = await db.execute(
        select(User.id).where(
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            or_(User.role == UserRole.ADMIN, User.id.in_(granted)),
        )
    )
    return [r[0] for r in rows.all()]


async def _people(db: AsyncSession, ids: set[Any]) -> dict[str, dict[str, str]]:
    from models.user import User

    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await db.execute(
        select(User.id, User.full_name, User.email).where(User.id.in_(ids))
    )
    return {
        str(i): {"id": str(i), "name": (n or e or "Someone"), "email": e or ""}
        for i, n, e in rows.all()
    }


async def _agents(db: AsyncSession, ids: set[Any]) -> dict[str, str]:
    from models.agent import Agent

    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(ids)))
    return {str(i): n for i, n in rows.all()}


# ── reading ──────────────────────────────────────────────────────


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def serialize(
    r: ModerationReview,
    people: dict[str, dict[str, str]],
    agents: dict[str, str],
    *,
    me: uuid.UUID | None = None,
    full: bool = False,
) -> dict[str, Any]:
    def person(pid: Any) -> dict[str, str] | None:
        return people.get(str(pid)) if pid else None

    out: dict[str, Any] = {
        "id": str(r.id),
        "status": r.status,
        "status_label": STATUS_LABEL.get(r.status, r.status),
        "source": r.source,
        "source_label": SOURCE_LABEL.get(r.source, r.source),
        "priority": int(r.priority or 1),
        "priority_label": PRIORITY_LABEL.get(int(r.priority or 1), "Low"),
        "categories": list(r.categories or []),
        "category_scores": dict(r.category_scores or {}),
        "preview": (r.masked_content or "")[:400],
        "content_length": int(r.content_length or 0),
        "created_at": _iso(r.created_at),
        "expires_at": _iso(r.expires_at),
        "timeout_action": r.timeout_action,
        "assigned_to": person(r.assigned_to),
        "assigned_to_me": bool(me and r.assigned_to == me),
        "decided_by": person(r.decided_by),
        "decided_at": _iso(r.decided_at),
        "decision_reason": r.decision_reason,
        "delivered": r.delivered_at is not None,
        "author": person(r.user_id),
        "agent": (
            {"id": str(r.agent_id), "name": agents.get(str(r.agent_id), "an agent")}
            if r.agent_id
            else None
        ),
        "execution_id": str(r.execution_id) if r.execution_id else None,
        "conversation_id": str(r.conversation_id) if r.conversation_id else None,
        "policy_id": str(r.policy_id) if r.policy_id else None,
        "content_available": r.held_content is not None,
        "redaction_mask": r.redaction_mask or "█████",
    }
    if full:
        out["content"] = unseal(r.tenant_id, r.held_content)
        out["masked_content"] = r.masked_content
        out["spans"] = list(r.spans or [])
        out["released_content"] = unseal(r.tenant_id, r.released_content)
        out["history"] = [
            {
                **h,
                "by_name": (
                    (person(h.get("by")) or {}).get("name") if h.get("by") else None
                ),
            }
            for h in (r.history or [])
        ]
    return out


async def serialize_many(
    db: AsyncSession,
    rows: list[ModerationReview],
    me: uuid.UUID | None,
    *,
    full: bool = False,
) -> list[dict[str, Any]]:
    pids: set[Any] = set()
    for r in rows:
        pids.update({r.user_id, r.assigned_to, r.decided_by})
        if full:
            pids.update(h.get("by") for h in (r.history or []))
    people = await _people(db, pids)
    agents = await _agents(db, {r.agent_id for r in rows})
    return [serialize(r, people, agents, me=me, full=full) for r in rows]


async def queue_counts(
    db: AsyncSession, tenant_id: uuid.UUID, me: uuid.UUID | None
) -> dict[str, int]:
    soon = _now() + timedelta(minutes=10)
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(ModerationReview.assigned_to == me),
                func.count().filter(ModerationReview.assigned_to.is_(None)),
                func.count().filter(ModerationReview.expires_at <= soon),
                func.count().filter(ModerationReview.priority >= 3),
            ).where(
                ModerationReview.tenant_id == tenant_id,
                ModerationReview.status == PENDING,
            )
        )
    ).one()
    return {
        "pending": int(row[0] or 0),
        "mine": int(row[1] or 0),
        "unassigned": int(row[2] or 0),
        "due_soon": int(row[3] or 0),
        "high": int(row[4] or 0),
    }


async def list_reviews(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    me: uuid.UUID,
    *,
    status: str = "pending",
    assigned: str = "any",
    priority: int | None = None,
    page: int = 1,
    limit: int = 25,
) -> tuple[list[dict[str, Any]], int]:
    conds = [ModerationReview.tenant_id == tenant_id]
    if status == "pending":
        conds.append(ModerationReview.status == PENDING)
    elif status == "decided":
        conds.append(ModerationReview.status != PENDING)
    elif status in STATUS_LABEL:
        conds.append(ModerationReview.status == status)
    if assigned == "me":
        conds.append(ModerationReview.assigned_to == me)
    elif assigned == "unassigned":
        conds.append(ModerationReview.assigned_to.is_(None))
    if priority in (1, 2, 3):
        conds.append(ModerationReview.priority == priority)
    where = and_(*conds)
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(ModerationReview).where(where)
            )
        ).scalar()
        or 0
    )
    q = select(ModerationReview).where(where)
    if status == "pending":
        # most severe first, then the one closest to timing out
        q = q.order_by(
            ModerationReview.priority.desc(),
            ModerationReview.expires_at.asc(),
            ModerationReview.created_at.asc(),
        )
    else:
        q = q.order_by(ModerationReview.decided_at.desc().nullslast())
    q = q.offset((max(1, page) - 1) * limit).limit(limit)
    rows = list((await db.execute(q)).scalars().all())
    return await serialize_many(db, rows, me), total


async def get_review(
    db: AsyncSession, tenant_id: uuid.UUID, review_id: Any, *, lock: bool = False
) -> ModerationReview:
    try:
        rid = uuid.UUID(str(review_id))
    except ValueError as exc:
        raise ReviewError("That review link is not valid.", 400) from exc
    q = select(ModerationReview).where(
        ModerationReview.id == rid, ModerationReview.tenant_id == tenant_id
    )
    if lock:
        q = q.with_for_update()
    r = (await db.execute(q)).scalar_one_or_none()
    if r is None:
        raise ReviewError(
            "This review is not here. It may have been removed when its retention period ended.",
            404,
            "REVIEW_NOT_FOUND",
        )
    return r


def owner_view(r: ModerationReview) -> dict[str, Any]:
    """What the author of held content sees about it."""
    out: dict[str, Any] = {
        "id": str(r.id),
        "status": r.status,
        "status_label": STATUS_LABEL.get(r.status, r.status),
        "source": r.source,
        "expires_at": _iso(r.expires_at),
        "timeout_action": r.timeout_action,
        "decided_at": _iso(r.decided_at),
        "reason": r.decision_reason if r.status in REJECTED_STATUSES else None,
        "delivered": r.delivered_at is not None,
        "conversation_id": str(r.conversation_id) if r.conversation_id else None,
        "content": None,
    }
    if r.status in RELEASED_STATUSES:
        out["content"] = unseal(r.tenant_id, r.released_content)
    elif r.status == PENDING and r.source == "pre_llm":
        # their own words, shown back while they wait
        out["content"] = unseal(r.tenant_id, r.held_content)
    return out


# ── acting ───────────────────────────────────────────────────────


def _log(r: ModerationReview, by: Any, action: str, note: str = "") -> None:
    entry = {
        "at": _now().isoformat(),
        "by": str(by) if by else None,
        "action": action,
        "note": note[:300],
    }
    r.history = list(r.history or []) + [entry]


def _guard_pending(r: ModerationReview) -> None:
    if r.status != PENDING:
        raise ReviewError(
            f"This was already decided: {STATUS_LABEL.get(r.status, r.status).lower()}.",
            409,
            "REVIEW_ALREADY_DECIDED",
        )


async def claim(
    db: AsyncSession, r: ModerationReview, me: uuid.UUID, is_admin: bool = False
) -> None:
    _guard_pending(r)
    if r.assigned_to and r.assigned_to != me and is_admin:
        _log(r, me, "claimed", "taken over by an admin")
        r.assigned_to = me
        r.assigned_at = _now()
        return
    if r.assigned_to and r.assigned_to != me:
        who = (await _people(db, {r.assigned_to})).get(str(r.assigned_to), {})
        raise ReviewError(
            f"{who.get('name', 'Another reviewer')} has already claimed this. "
            "An admin can unassign it if they are away.",
            409,
            "REVIEW_CLAIMED",
        )
    if r.assigned_to == me:
        return
    r.assigned_to = me
    r.assigned_at = _now()
    _log(r, me, "claimed")


async def unassign(
    db: AsyncSession, r: ModerationReview, me: uuid.UUID, is_admin: bool
) -> None:
    _guard_pending(r)
    if r.assigned_to is None:
        return
    if r.assigned_to != me and not is_admin:
        raise ReviewError(
            "Only the reviewer who claimed this, or an admin, can unassign it.",
            403,
            "REVIEW_NOT_YOURS",
        )
    _log(r, me, "unassigned")
    r.assigned_to = None
    r.assigned_at = None


async def decide(
    db: AsyncSession,
    r: ModerationReview,
    *,
    actor: uuid.UUID | None,
    action: str,
    content: str | None = None,
    reason: str | None = None,
    is_admin: bool = False,
    request: Any = None,
) -> None:
    """Release, redact and release, or reject. actor None means the timeout decided."""
    _guard_pending(r)
    reason = (reason or "").strip()
    if actor is not None:
        if r.assigned_to and r.assigned_to != actor and not is_admin:
            who = (await _people(db, {r.assigned_to})).get(str(r.assigned_to), {})
            raise ReviewError(
                f"{who.get('name', 'Another reviewer')} has claimed this. Ask them, or an admin, to unassign it first.",
                409,
                "REVIEW_CLAIMED",
            )
    if action not in ("release", "redact", "reject"):
        raise ReviewError("Choose release, redact or reject.", 400, "BAD_ACTION")
    if len(reason) > MAX_REASON:
        raise ReviewError(
            f"Keep the reason under {MAX_REASON} characters.", 400, "REASON_TOO_LONG"
        )
    original = unseal(r.tenant_id, r.held_content)
    released: str | None = None
    if action == "reject":
        if actor is not None and not reason:
            raise ReviewError(
                "Say why you are rejecting it. The person who wrote it sees this reason.",
                400,
                "REASON_REQUIRED",
            )
    elif action == "redact":
        released = (content or "").strip()
        if not released:
            raise ReviewError(
                "The redacted text is empty. Mask the parts that should not go out and keep the rest.",
                400,
                "REDACTION_EMPTY",
            )
        if len(released) > max(2 * (r.content_length or 0), 2000):
            raise ReviewError(
                "The redacted text is much longer than the original. Only remove or mask parts of it.",
                400,
                "REDACTION_TOO_LONG",
            )
    else:
        if original is None:
            raise ReviewError(
                "The full text is no longer stored, so it cannot be released as it was. Redact and release the masked text, or reject it.",
                409,
                "CONTENT_GONE",
            )
        released = original

    now = _now()
    if actor is None:
        status = "auto_released" if action == "release" else "auto_rejected"
    else:
        status = {"release": "released", "redact": "redacted", "reject": "rejected"}[
            action
        ]
    r.status = status
    r.decided_by = actor
    r.decided_at = now
    r.decision_reason = reason or (
        f"Nobody decided within the time limit, so it was {'released' if action == 'release' else 'rejected'} automatically."
        if actor is None
        else None
    )
    if released is not None:
        r.released_content = seal(r.tenant_id, released)
    _log(r, actor, status, reason)

    retention = retention_from(await _tenant_settings(db, r.tenant_id))
    if retention["held_content_days"] == 0:
        r.held_content = None
        if r.source != "pre_llm":
            r.released_content = None
        r.content_purged_at = now

    await _deliver(db, r, released)
    await _audit(db, r, actor, request)
    try:
        from app.services.events import emit

        await emit(
            db,
            r.tenant_id,
            "moderation.decided",
            {
                "review_id": str(r.id),
                "status": status,
                "source": r.source,
                "execution_id": str(r.execution_id) if r.execution_id else None,
                "automatic": actor is None,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("moderation.decided not emitted: %s", exc)


async def _tenant_settings(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    from models.tenant import Tenant

    row = await db.execute(select(Tenant.settings).where(Tenant.id == tenant_id))
    return dict(row.scalar_one_or_none() or {})


async def _deliver(db: AsyncSession, r: ModerationReview, released: str | None) -> None:
    """Put the outcome where the content was held, the chat message and the run record."""
    from models.conversation import Message
    from models.execution import Execution, ExecutionStatus

    ok = r.status in RELEASED_STATUSES
    if r.message_id is not None:
        msg = (
            await db.execute(select(Message).where(Message.id == r.message_id))
        ).scalar_one_or_none()
        if msg is not None:
            if ok:
                msg.content = released or ""
            else:
                msg.content = (
                    "[Message withheld after review]"
                    if r.source == "pre_llm"
                    else "[Reply withheld after review]"
                )
            msg.blocks = [hold_block(r.id, r.source)]
    if r.execution_id is None:
        return
    values: dict[str, Any]
    if ok and r.source == "post_llm":
        values = {
            "status": ExecutionStatus.COMPLETED,
            "failure_code": None,
            "error_message": None,
            "output_message": released,
        }
    elif ok:
        values = {
            "failure_code": "MODERATION_RELEASED",
            "error_message": "A reviewer released this message. Send it again to run it.",
        }
    else:
        values = {
            "failure_code": "MODERATION_REJECTED",
            "error_message": (
                f"Held for review and rejected. {r.decision_reason or ''}"
            ).strip()[:2000],
        }
    await db.execute(
        update(Execution).where(Execution.id == r.execution_id).values(**values)
    )


async def _audit(
    db: AsyncSession, r: ModerationReview, actor: uuid.UUID | None, request: Any
) -> None:
    from app.core.audit import log_action
    from app.services.audit_chain import NIL_ACTOR

    await log_action(
        db,
        r.tenant_id,
        actor or NIL_ACTOR,
        action=f"moderation_review_{r.status}",
        details={
            "source": r.source,
            "categories": list(r.categories or [])[:10],
            # the reason is the reviewer's words, never the held text
            "reason": (r.decision_reason or "")[:300],
            "automatic": actor is None,
        },
        request=request,
        resource_type="moderation_review",
        resource_id=str(r.id),
    )


async def after_decision(db: AsyncSession, r: ModerationReview) -> None:
    """Tell the author and refresh reviewers' queues, after the commit."""
    from app.core.ws_manager import ws_manager

    ok = r.status in RELEASED_STATUSES
    what = "Your message" if r.source == "pre_llm" else "A reply to you"
    if ok:
        title = f"{what} was released after review"
        body = (
            "A reviewer released it. Open the chat to continue."
            if r.status != "auto_released"
            else "Nobody reviewed it in time, so it was released automatically."
        )
    else:
        title = f"{what} was not sent"
        body = r.decision_reason or "A reviewer rejected it."
    if r.user_id:
        try:
            from app.core.notifications import (
                _serialize_notification,
                create_notification,
            )

            link = f"/chat?id={r.conversation_id}" if r.conversation_id else None
            n = await create_notification(
                db,
                tenant_id=r.tenant_id,
                user_id=r.user_id,
                type="moderation_hold_decided",
                title=title,
                message=body[:500],
                link=link,
                metadata={"review_id": str(r.id), "status": r.status},
                push=False,
            )
            await db.commit()
            if n is not None:
                await ws_manager.send_to_user(
                    r.user_id, "notification", _serialize_notification(n)
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("author notification failed: %s", exc)
        try:
            await ws_manager.send_to_user(
                r.user_id, "moderation_review", {"id": str(r.id), "status": r.status}
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("author push failed: %s", exc)
    await push_queue(db, r.tenant_id)


async def push_queue(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Reviewers' sidebars and open inboxes refresh from this, nothing polls."""
    from app.core.ws_manager import ws_manager

    try:
        counts = await queue_counts(db, tenant_id, None)
        for uid in await reviewer_ids(db, tenant_id):
            await ws_manager.send_to_user(
                uid, "moderation_queue", {"pending": counts["pending"]}
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("queue push failed: %s", exc)


# ── background jobs ──────────────────────────────────────────────

_BACKGROUND: set = set()


def announce_soon(tenant_id: Any) -> None:
    """Tell reviewers right after an inline run held something, the sweep is the backstop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _go() -> None:
        # the caller's transaction commits first
        await asyncio.sleep(1.0)
        from app.core.deps import async_session

        try:
            async with async_session() as db:
                await announce_pending(db, tenant_id=uuid.UUID(str(tenant_id)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("review announce failed: %s", exc)

    task = loop.create_task(_go())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def announce_pending(
    db: AsyncSession, tenant_id: uuid.UUID | None = None, limit: int = 200
) -> int:
    """Notify reviewers of new held content once. Safe to run from every replica."""
    from app.core.notifications import create_notification

    q = (
        select(ModerationReview)
        .where(
            ModerationReview.status == PENDING,
            ModerationReview.notified_at.is_(None),
        )
        .order_by(ModerationReview.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    if tenant_id is not None:
        q = q.where(ModerationReview.tenant_id == tenant_id)
    rows = list((await db.execute(q)).scalars().all())
    if not rows:
        return 0
    by_tenant: dict[uuid.UUID, list[ModerationReview]] = {}
    for r in rows:
        by_tenant.setdefault(r.tenant_id, []).append(r)
        r.notified_at = _now()
    for tid, items in by_tenant.items():
        reviewers = await reviewer_ids(db, tid)
        top = max(items, key=lambda x: int(x.priority or 1))
        cats = ", ".join(_plain_category(c) for c in (top.categories or [])[:3])
        if len(items) == 1:
            title = f"{SOURCE_LABEL.get(top.source, 'Content')} held for review"
            message = (
                f"{PRIORITY_LABEL.get(int(top.priority or 1), 'Low')} priority"
                + (f", matched {cats}" if cats else "")
                + ". Open the review inbox to release, redact or reject it."
            )
        else:
            title = f"{len(items)} items held for review"
            message = "Open the review inbox to work through them, the most severe come first."
        for uid in reviewers:
            try:
                await create_notification(
                    db,
                    tenant_id=tid,
                    user_id=uid,
                    type="moderation_review_requested",
                    title=title,
                    message=message,
                    link="/review-queue?tab=held",
                    metadata={"review_ids": [str(x.id) for x in items[:20]]},
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("reviewer notification failed: %s", exc)
        try:
            from app.services.events import emit

            for x in items:
                await emit(
                    db,
                    tid,
                    "moderation.held",
                    {
                        "review_id": str(x.id),
                        "source": x.source,
                        "priority": int(x.priority or 1),
                        "categories": list(x.categories or []),
                        "expires_at": _iso(x.expires_at),
                    },
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("moderation.held not emitted: %s", exc)
    await db.commit()
    for tid in by_tenant:
        await push_queue(db, tid)
    return len(rows)


def _plain_category(cat: str) -> str:
    if cat.startswith("custom:") and cat.split(":", 1)[1].isdigit():
        return f"custom pattern {int(cat.split(':', 1)[1]) + 1}"
    return cat


async def expire_due(db: AsyncSession, limit: int = 200) -> int:
    """Apply each policy's timeout to held content nobody decided on."""
    rows = list(
        (
            await db.execute(
                select(ModerationReview)
                .where(
                    ModerationReview.status == PENDING,
                    ModerationReview.expires_at <= _now(),
                )
                .order_by(ModerationReview.expires_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    done: list[ModerationReview] = []
    for r in rows:
        action = "release" if r.timeout_action == "release" else "reject"
        if action == "release" and r.held_content is None:
            action = "reject"
        try:
            await decide(db, r, actor=None, action=action)
            done.append(r)
        except ReviewError as exc:
            logger.warning("timeout decision skipped for %s: %s", r.id, exc.message)
    await db.commit()
    for r in done:
        await after_decision(db, r)
    return len(done)


_PURGE_HELD = text(
    """
    UPDATE moderation_reviews r
       SET held_content = NULL,
           released_content = NULL,
           content_purged_at = now()
     WHERE r.id IN (
           SELECT r2.id FROM moderation_reviews r2
             JOIN tenants t2 ON t2.id = r2.tenant_id
            WHERE r2.status <> 'pending'
              AND r2.content_purged_at IS NULL
              AND r2.decided_at < now() - make_interval(days =>
                  COALESCE((t2.settings->'moderation_retention'->>'held_content_days')::int, 30))
            LIMIT :batch)
    """
)
_DROP_RECORDS = text(
    """
    DELETE FROM moderation_reviews r
     WHERE r.id IN (
           SELECT r2.id FROM moderation_reviews r2
             JOIN tenants t2 ON t2.id = r2.tenant_id
            WHERE r2.status <> 'pending'
              AND r2.decided_at < now() - make_interval(days =>
                  COALESCE((t2.settings->'moderation_retention'->>'decision_record_days')::int, 365))
            LIMIT :batch)
    """
)
_EXPIRE_PREVIEWS = text(
    """
    UPDATE moderation_events e
       SET content_preview = NULL
     WHERE e.id IN (
           SELECT e2.id FROM moderation_events e2
             JOIN tenants t2 ON t2.id = e2.tenant_id
            WHERE e2.content_preview IS NOT NULL
              AND e2.created_at < now() - make_interval(days =>
                  COALESCE((t2.settings->'moderation_retention'->>'event_preview_days')::int, 30))
            LIMIT :batch)
    """
)


async def purge_retention(db: AsyncSession, batch: int = PURGE_BATCH) -> dict[str, int]:
    """Drop what each tenant's retention settings say is past keeping, in bounded batches."""
    out = {"held_text": 0, "records": 0, "previews": 0}
    for key, sql in (
        ("held_text", _PURGE_HELD),
        ("records", _DROP_RECORDS),
        ("previews", _EXPIRE_PREVIEWS),
    ):
        # loop the batches so a backlog clears in one run without one giant statement
        for _ in range(50):
            n = (await db.execute(sql, {"batch": batch})).rowcount or 0
            await db.commit()
            out[key] += n
            if n < batch:
                break
    return out


__all__ = [
    "HOLD_BLOCK",
    "REVIEW_CAP",
    "ReviewError",
    "announce_pending",
    "announce_soon",
    "claim",
    "decide",
    "expire_due",
    "list_reviews",
    "purge_retention",
    "queue_counts",
    "retention_from",
    "unassign",
    "validate_retention",
]
