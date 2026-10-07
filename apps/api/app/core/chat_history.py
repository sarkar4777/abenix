"""Prior turns of a chat thread, shaped as LLM conversation history."""

from __future__ import annotations

import uuid
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

HISTORY_TOKEN_BUDGET = 8000
HISTORY_MAX_ROWS = 200
CHARS_PER_TOKEN = 4


class ThreadNotFound(Exception):
    pass


def shape_history(
    rows: Iterable[tuple[str, str]], budget_tokens: int = HISTORY_TOKEN_BUDGET
) -> list[dict[str, str]]:
    """Alternating user/assistant turns, newest kept, oldest dropped past the budget."""
    merged: list[dict[str, str]] = []
    for role, content in rows:
        if role not in ("user", "assistant"):
            continue
        text = (content or "").strip()
        if not text:
            continue
        if merged and merged[-1]["role"] == role:
            merged[-1]["content"] += "\n\n" + text
        else:
            merged.append({"role": role, "content": text})
    # a trailing user turn is the message being sent now, or one that never got a reply
    if merged and merged[-1]["role"] == "user":
        merged.pop()
    budget_chars = max(0, budget_tokens) * CHARS_PER_TOKEN
    kept: list[dict[str, str]] = []
    used = 0
    for msg in reversed(merged):
        used += len(msg["content"])
        if used > budget_chars:
            break
        kept.append(msg)
    kept.reverse()
    while kept and kept[0]["role"] != "user":
        kept.pop(0)
    return kept


async def load_thread_history(
    db: AsyncSession,
    conversation_id: str,
    user: Any,
    budget_tokens: int = HISTORY_TOKEN_BUDGET,
) -> list[dict[str, str]]:
    from models.conversation import Conversation, Message

    try:
        conv_uuid = uuid.UUID(str(conversation_id))
    except ValueError as exc:
        raise ThreadNotFound() from exc
    owned = await db.execute(
        select(Conversation.id).where(
            Conversation.id == conv_uuid,
            Conversation.user_id == user.id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    if owned.scalar_one_or_none() is None:
        raise ThreadNotFound()
    res = await db.execute(
        select(Message.role, Message.content)
        .where(Message.conversation_id == conv_uuid)
        .order_by(Message.created_at.desc())
        .limit(HISTORY_MAX_ROWS)
    )
    rows = list(res.all())
    rows.reverse()
    return shape_history(((r[0], r[1]) for r in rows), budget_tokens)
