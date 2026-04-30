from __future__ import annotations

import logging
import os
import secrets
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, or_, and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.schemas.conversations import (
    CreateConversationRequest,
    SaveMessageRequest,
    UpdateConversationRequest,
)

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent
from models.conversation import Conversation, Message
from models.user import User

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _serialize_conversation(c: Conversation, include_messages: bool = False) -> dict:
    data = {
        "id": str(c.id),
        "user_id": str(c.user_id),
        "agent_id": str(c.agent_id) if c.agent_id else None,
        "agent_slug": getattr(c, "agent_slug", None),
        "app_slug": getattr(c, "app_slug", None),
        "subject_type": getattr(c, "subject_type", None),
        "subject_id": getattr(c, "subject_id", None),
        "title": c.title,
        "model_used": c.model_used,
        "is_archived": c.is_archived,
        "is_shared": c.is_shared,
        "share_token": c.share_token,
        "total_tokens": c.total_tokens,
        "total_cost": float(c.total_cost),
        "message_count": c.message_count,
        "last_message_preview": getattr(c, "last_message_preview", None),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }
    if include_messages:
        data["messages"] = [_serialize_message(m) for m in (c.messages or [])]
    return data


def _resolve_subject(request: Request, user: User) -> tuple[str, str]:
    """Standalone-app user identity if delegated, else Abenix user."""
    acting = getattr(request.state, "acting_subject", None)
    if acting:
        return (acting.subject_type, str(acting.subject_id))
    return ("user", str(user.id))


def _derive_title(text: str) -> str:
    s = (text or "").strip().splitlines()[0] if text else "New Chat"
    s = s.strip()
    return (s[:80] + "…") if len(s) > 80 else (s or "New Chat")


async def _resolve_agent_by_slug(db: AsyncSession, slug: str) -> Agent | None:
    if not slug:
        return None
    row = await db.execute(select(Agent).where(Agent.slug == slug))
    return row.scalar_one_or_none()


def _serialize_message(m: Message) -> dict:
    return {
        "id": str(m.id),
        "conversation_id": str(m.conversation_id),
        "role": m.role,
        "content": m.content,
        "blocks": m.blocks,
        "tool_calls": m.tool_calls,
        "input_tokens": m.input_tokens,
        "output_tokens": m.output_tokens,
        "cost": float(m.cost),
        "model_used": m.model_used,
        "duration_ms": m.duration_ms,
        "attachments": m.attachments,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("")
async def list_conversations(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    archived: bool = Query(default=False),
    app_slug: str = Query(default=""),
    agent_slug: str = Query(default=""),
) -> JSONResponse:
    """List threads visible to the current user / acting subject."""
    subject_type, subject_id = _resolve_subject(request, user)
    filters = [
        Conversation.tenant_id == user.tenant_id,
        Conversation.is_archived == archived,
        or_(
            and_(
                Conversation.subject_type == subject_type,
                Conversation.subject_id == subject_id,
            ),
            # Legacy threads predate subject scoping — show ours too
            and_(
                Conversation.subject_type.is_(None),
                Conversation.user_id == user.id,
            ),
        ),
    ]
    if app_slug:
        filters.append(Conversation.app_slug == app_slug)
    if agent_slug:
        filters.append(Conversation.agent_slug == agent_slug)

    base = select(Conversation).where(*filters)
    count_result = await db.execute(select(func.count(Conversation.id)).where(*filters))
    total = count_result.scalar() or 0

    result = await db.execute(
        base.order_by(Conversation.updated_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    conversations = result.scalars().all()

    return success(
        [_serialize_conversation(c) for c in conversations],
        meta={"total": total, "page": page, "per_page": per_page},
    )


@router.post("")
async def create_conversation(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create a new chat thread."""
    subject_type, subject_id = _resolve_subject(request, user)
    agent_uuid = None
    agent_slug = body.get("agent_slug")
    if body.get("agent_id"):
        try:
            agent_uuid = uuid.UUID(body["agent_id"])
        except (ValueError, TypeError):
            return error("Invalid agent_id", 400)
        agent_row = (await db.execute(select(Agent).where(Agent.id == agent_uuid))).scalar_one_or_none()
        if not agent_row:
            return error("Agent not found", 404)
        agent_slug = agent_slug or agent_row.slug
    elif agent_slug:
        agent_row = await _resolve_agent_by_slug(db, agent_slug)
        if agent_row:
            agent_uuid = agent_row.id

    conv = Conversation(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        agent_id=agent_uuid,
        agent_slug=agent_slug,
        app_slug=body.get("app_slug"),
        subject_type=subject_type,
        subject_id=subject_id,
        title=str(body.get("title") or "New Chat")[:255],
        model_used=body.get("model_used"),
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return success(_serialize_conversation(conv), status_code=201)


def _check_thread_access(conv: Conversation, request: Request, user: User) -> str | None:
    """Return error string if access denied, None if OK."""
    if conv.tenant_id != user.tenant_id:
        return "Forbidden"
    subject_type, subject_id = _resolve_subject(request, user)
    if conv.subject_type and (conv.subject_type, conv.subject_id) != (subject_type, subject_id):
        if user.role.value != "admin":
            return "Forbidden"
    elif not conv.subject_type and conv.user_id != user.id and user.role.value != "admin":
        return "Forbidden"
    return None


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        return error("Invalid conversation ID", 400)

    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(
            Conversation.id == conv_uuid,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        return error("Conversation not found", 404)
    if (denied := _check_thread_access(conv, request, user)):
        return error(denied, 403)

    return success(_serialize_conversation(conv, include_messages=True))



@router.post("/{conversation_id}/turn")
async def send_turn(
    conversation_id: str,
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Append a user message, run the agent with full history, persist."""
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        return error("Invalid conversation ID", 400)
    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_uuid))).scalar_one_or_none()
    if not conv:
        return error("Conversation not found", 404)
    if (denied := _check_thread_access(conv, request, user)):
        return error(denied, 403)

    content = (body.get("content") or "").strip()
    if not content:
        return error("Message content is required", 400)

    agent_slug = body.get("agent_slug") or conv.agent_slug
    if not agent_slug:
        return error("Thread has no bound agent and no agent_slug provided", 400)

    # Refresh agent_id when the slug was re-seeded
    if not conv.agent_id or body.get("agent_slug"):
        agent_row = await _resolve_agent_by_slug(db, agent_slug)
        if agent_row:
            conv.agent_id = agent_row.id
            conv.agent_slug = agent_row.slug

    now = datetime.now(timezone.utc)
    user_msg = Message(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        role="user",
        content=content,
        attachments=body.get("attachments"),
    )
    db.add(user_msg)
    if (not conv.title or conv.title == "New Chat") and (conv.message_count or 0) == 0:
        conv.title = _derive_title(content)
    conv.message_count = (conv.message_count or 0) + 1
    conv.last_message_preview = content[:200]
    conv.updated_at = now
    await db.commit()
    await db.refresh(conv)

    history = (await db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )).scalars().all()
    history_text = "\n\n".join(f"[{m.role.upper()}] {m.content}" for m in history[-20:])
    composed = ""
    if (ctx := (body.get("context") or "").strip()):
        composed += f"=== CONTEXT (fresh, this turn) ===\n{ctx}\n\n"
    if history_text:
        composed += f"=== CONVERSATION SO FAR ===\n{history_text}\n\n"
    composed += "=== ASSISTANT, RESPOND TO THE LATEST USER MESSAGE ==="

    try:
        from abenix_sdk import Abenix, ActingSubject  # type: ignore
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "sdk" / "python"))
        from abenix_sdk import Abenix, ActingSubject  # type: ignore

    api_key = os.environ.get("ABENIX_PLATFORM_API_KEY") or os.environ.get("ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_INTERNAL_URL", "http://localhost:8000")
    subject_type, subject_id = _resolve_subject(request, user)
    subject = ActingSubject(
        subject_type=subject_type, subject_id=subject_id,
        email=user.email, display_name=getattr(user, "full_name", None),
    ) if subject_type != "user" else None

    started = datetime.now(timezone.utc)
    try:
        async with Abenix(api_key=api_key, base_url=api_base, act_as=subject, timeout=300.0) as forge:
            result = await forge.execute(agent_slug, composed)
        assistant = Message(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            role="assistant",
            content=result.output or "",
            tool_calls=[
                {"name": t.get("name"), "duration_ms": t.get("duration_ms")}
                for t in (result.tool_calls or [])
            ] if result.tool_calls else None,
            input_tokens=int(getattr(result, "input_tokens", 0) or 0),
            output_tokens=int(getattr(result, "output_tokens", 0) or 0),
            cost=float(result.cost or 0.0),
            model_used=result.model,
            duration_ms=int(result.duration_ms or 0),
        )
        db.add(assistant)
        conv.model_used = result.model
        conv.message_count += 1
        conv.last_message_preview = (result.output or "")[:200]
        conv.total_tokens = (conv.total_tokens or 0) + assistant.input_tokens + assistant.output_tokens
        conv.total_cost = float(conv.total_cost or 0.0) + float(result.cost or 0.0)
        conv.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(conv)
        await db.refresh(assistant)
        return success({
            "thread": _serialize_conversation(conv),
            "user_message": _serialize_message(user_msg),
            "assistant_message": _serialize_message(assistant),
        })
    except Exception as exc:
        logger.exception("conversations.turn: agent execution failed")
        # Persist a failure marker so the UI can show what happened
        err_msg = Message(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            role="assistant",
            content=f"[error] {exc}",
            duration_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
        )
        db.add(err_msg)
        conv.message_count += 1
        conv.last_message_preview = "[error]"
        await db.commit()
        return error(f"Agent call failed: {exc}", 502)


@router.put("/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    body: UpdateConversationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        return error("Invalid conversation ID", 400)

    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_uuid,
            Conversation.user_id == user.id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        return error("Conversation not found", 404)

    if body.title is not None:
        conv.title = body.title
    if body.is_archived is not None:
        conv.is_archived = body.is_archived

    await db.commit()
    await db.refresh(conv)

    return success(_serialize_conversation(conv))


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        return error("Invalid conversation ID", 400)

    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_uuid,
            Conversation.user_id == user.id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        return error("Conversation not found", 404)

    await db.execute(delete(Message).where(Message.conversation_id == conv_uuid))
    await db.delete(conv)
    await db.commit()

    return success({"deleted": True})


@router.post("/{conversation_id}/messages")
async def save_message(
    conversation_id: str,
    body: SaveMessageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        return error("Invalid conversation ID", 400)

    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_uuid,
            Conversation.user_id == user.id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        return error("Conversation not found", 404)

    msg = Message(
        id=uuid.uuid4(),
        conversation_id=conv_uuid,
        role=body.role,
        content=body.content,
        blocks=body.blocks,
        tool_calls=body.tool_calls,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        cost=body.cost,
        model_used=body.model_used,
        duration_ms=body.duration_ms,
        attachments=body.attachments,
    )
    db.add(msg)

    conv.message_count = (conv.message_count or 0) + 1
    conv.total_tokens = (conv.total_tokens or 0) + body.input_tokens + body.output_tokens
    conv.total_cost = float(conv.total_cost or 0) + body.cost
    if body.model_used:
        conv.model_used = body.model_used

    await db.commit()
    await db.refresh(msg)

    return success(_serialize_message(msg), status_code=201)


@router.post("/{conversation_id}/share")
async def share_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        return error("Invalid conversation ID", 400)

    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_uuid,
            Conversation.user_id == user.id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        return error("Conversation not found", 404)

    if not conv.share_token:
        conv.share_token = secrets.token_urlsafe(32)
    conv.is_shared = True

    await db.commit()
    await db.refresh(conv)

    return success({
        "share_token": conv.share_token,
        "share_url": f"/chat/shared/{conv.share_token}",
    })


@router.delete("/{conversation_id}/share")
async def unshare_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        return error("Invalid conversation ID", 400)

    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_uuid,
            Conversation.user_id == user.id,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        return error("Conversation not found", 404)

    conv.is_shared = False
    conv.share_token = None

    await db.commit()

    return success({"unshared": True})


@router.get("/shared/{share_token}")
async def get_shared_conversation(
    share_token: str,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(
            Conversation.share_token == share_token,
            Conversation.is_shared.is_(True),
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        return error("Shared conversation not found", 404)

    return success(_serialize_conversation(conv, include_messages=True))
