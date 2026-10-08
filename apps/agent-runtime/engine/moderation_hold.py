"""Persist content a HOLD policy stopped, shared by the API and the queue consumer."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from engine.moderation_client import content_hash, mask_spans, merge_spans

logger = logging.getLogger(__name__)

HOLD_BLOCK = "moderation_hold"
USER_PLACEHOLDER = "[Message held for review]"
REPLY_PLACEHOLDER = "[Reply held for review]"
RELEASED_STATUSES = ("released", "redacted", "auto_released")
REJECTED_STATUSES = ("rejected", "auto_rejected")
# a released message has a day to go on to the agent before it needs a new review
RELEASE_GRACE = timedelta(hours=24)

# provider categories a person should see first
HIGH_RISK = frozenset(
    {
        "sexual/minors",
        "self-harm",
        "self-harm/intent",
        "self-harm/instructions",
        "violence/graphic",
        "hate/threatening",
        "harassment/threatening",
        "illicit/violent",
    }
)


def priority_for(categories: list[str], scores: dict[str, float] | None) -> int:
    """3 high, 2 medium, 1 low, from what matched and how sure the provider was."""
    scores = scores or {}
    cats = [c for c in categories or [] if c]
    top = max([float(scores.get(c, 0.0)) for c in cats] or [0.0])
    if any(c in HIGH_RISK for c in cats) or top >= 0.85:
        return 3
    if any(c.startswith("custom:") for c in cats) or top >= 0.6:
        return 2
    return 1


def _kek_set() -> bool:
    return bool(os.environ.get("ABENIX_DATA_KEY_KEK_BASE64", "").strip())


def seal(tenant_id: Any, plaintext: str | None) -> str | None:
    """Encrypt held text when a KEK is set. Without the crypto module it is not kept at all."""
    if plaintext is None:
        return None
    try:
        from app.core.crypto import encrypt
    except Exception:  # noqa: BLE001
        if _kek_set():
            logger.warning("crypto module missing, held content not stored")
            return None
        return plaintext
    return encrypt(tenant_id, plaintext)


def unseal(tenant_id: Any, stored: str | None) -> str | None:
    if stored is None:
        return None
    try:
        from app.core.crypto import decrypt
    except Exception:  # noqa: BLE001
        return stored
    return decrypt(tenant_id, stored)


def _uuid(v: Any) -> uuid.UUID | None:
    if not v:
        return None
    if isinstance(v, uuid.UUID):
        return v
    try:
        return uuid.UUID(str(v))
    except ValueError:
        return None


def hold_block(review_id: Any, source: str) -> dict[str, Any]:
    return {"type": HOLD_BLOCK, "review_id": str(review_id), "source": source}


async def record_hold(
    db: Any,
    *,
    tenant_id: Any,
    user_id: Any,
    policy_id: Any,
    event_id: Any,
    execution_id: Any,
    source: str,
    categories: list[str],
    scores: dict[str, float] | None,
    hold: dict[str, Any],
    redaction_mask: str,
    custom_spans: list[dict[str, Any]] | None = None,
) -> Any:
    """Add the review row and take the raw text out of the chat and the run record."""
    from models.moderation_policy import ModerationReview

    content = str(hold.get("content") or "")
    spans = merge_spans(list(hold.get("spans") or []) + list(custom_spans or []))
    masked = mask_spans(content, spans, redaction_mask)
    now = datetime.now(timezone.utc)
    minutes = max(1, int(hold.get("timeout_minutes") or 60))
    review = ModerationReview(
        id=_uuid(hold.get("review_id")) or uuid.uuid4(),
        tenant_id=_uuid(tenant_id),
        policy_id=_uuid(policy_id),
        event_id=_uuid(event_id),
        user_id=_uuid(user_id),
        execution_id=_uuid(execution_id),
        agent_id=_uuid(hold.get("agent_id")),
        conversation_id=_uuid(hold.get("conversation_id")),
        source=source or "pre_llm",
        status="pending",
        priority=priority_for(categories, scores),
        categories=list(categories or []),
        category_scores={
            k: round(float(v), 4) for k, v in (scores or {}).items() if k in categories
        },
        spans=spans,
        held_content=seal(tenant_id, content),
        content_sha256=content_hash(content),
        content_length=len(content),
        masked_content=masked,
        redaction_mask=redaction_mask or "█████",
        timeout_action=(
            "release" if hold.get("timeout_action") == "release" else "reject"
        ),
        expires_at=now + timedelta(minutes=minutes),
        history=[{"at": now.isoformat(), "by": None, "action": "held", "note": ""}],
    )
    db.add(review)
    try:
        await _stand_in(db, review, content, masked)
    except Exception as exc:  # noqa: BLE001
        logger.warning("held content stand-in not written: %s", type(exc).__name__)
    return review


async def _stand_in(db: Any, review: Any, content: str, masked: str) -> None:
    """The chat shows a hold card where the content was, the run record keeps the masked text."""
    from sqlalchemy import select, update

    from models.conversation import Conversation, Message
    from models.execution import Execution

    if review.execution_id is not None and review.source == "pre_llm":
        await db.execute(
            update(Execution)
            .where(Execution.id == review.execution_id)
            .values(input_message=masked)
        )
    if review.conversation_id is None:
        return
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == review.conversation_id,
                Conversation.tenant_id == review.tenant_id,
                Conversation.user_id == review.user_id,
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        return
    block = [hold_block(review.id, review.source)]
    if review.source == "pre_llm":
        rows = (
            (
                await db.execute(
                    select(Message)
                    .where(
                        Message.conversation_id == conv.id,
                        Message.role == "user",
                    )
                    .order_by(Message.created_at.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        msg = next((m for m in rows if (m.content or "") == content), None)
        if msg is None and rows:
            created = rows[0].created_at
            recent = created is not None and (
                datetime.now(timezone.utc) - created < timedelta(minutes=3)
            )
            msg = rows[0] if recent else None
        if msg is not None:
            msg.content = USER_PLACEHOLDER
            msg.blocks = block
            msg.attachments = None
            review.message_id = msg.id
        # the chat titles a new thread with its first message
        if conv.title and content.startswith(conv.title.rstrip("…")[:60]):
            conv.title = "Message held for review"
        if conv.last_message_preview and conv.last_message_preview in content:
            conv.last_message_preview = USER_PLACEHOLDER
    else:
        msg = Message(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            role="assistant",
            content=REPLY_PLACEHOLDER,
            blocks=block,
        )
        db.add(msg)
        conv.message_count = (conv.message_count or 0) + 1
        review.message_id = msg.id


async def mark_consumed(db: Any, review_id: Any) -> None:
    from sqlalchemy import update

    from models.moderation_policy import ModerationReview

    rid = _uuid(review_id)
    if rid is None:
        return
    await db.execute(
        update(ModerationReview)
        .where(ModerationReview.id == rid, ModerationReview.delivered_at.is_(None))
        .values(delivered_at=datetime.now(timezone.utc))
    )


async def load_released(db: Any, tenant_id: Any, user_id: Any) -> dict[str, str]:
    """Hash of each released message the person has not sent on yet, to its review id."""
    from sqlalchemy import select

    from models.moderation_policy import ModerationReview

    uid, tid = _uuid(user_id), _uuid(tenant_id)
    if uid is None or tid is None:
        return {}
    since = datetime.now(timezone.utc) - RELEASE_GRACE
    rows = (
        await db.execute(
            select(ModerationReview.id, ModerationReview.released_content)
            .where(
                ModerationReview.user_id == uid,
                ModerationReview.tenant_id == tid,
                ModerationReview.source == "pre_llm",
                ModerationReview.status.in_(RELEASED_STATUSES),
                ModerationReview.delivered_at.is_(None),
                ModerationReview.decided_at >= since,
            )
            .limit(20)
        )
    ).all()
    out: dict[str, str] = {}
    for rid, stored in rows:
        text = unseal(tid, stored)
        if text:
            out[content_hash(text)] = str(rid)
    return out


async def persist_gate_event(
    db: Any,
    *,
    event: Any,
    payload: dict[str, Any],
    tenant_id: Any,
    user_id: Any,
    policy_id: Any,
    execution_id: Any,
    redaction_mask: str,
) -> Any:
    """Hold and consume side effects for one captured gate event. Returns the review or None."""
    consumed = payload.get("consumed_review_id")
    if consumed:
        await mark_consumed(db, consumed)
    hold = payload.get("hold")
    if not hold:
        return None
    return await record_hold(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        policy_id=policy_id,
        event_id=getattr(event, "id", None),
        execution_id=execution_id,
        source=payload.get("source") or "pre_llm",
        categories=list(payload.get("acted_categories") or []),
        scores=payload.get("category_scores") or {},
        hold=hold,
        redaction_mask=redaction_mask,
    )
