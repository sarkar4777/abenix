"""Saudi Tourism Chat — natural language Q&A via Abenix st-chat agent."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_utils import get_forge
from app.core.deps import get_db
from app.core.responses import error, success
from app.models.tourism_models import STChatMessage, STDataset, STUser
from app.routers.auth import get_st_user

logger = logging.getLogger("sauditourism.chat")
router = APIRouter(prefix="/api/st/chat", tags=["st-chat"])


def _build_data_context(datasets: list[STDataset], max_chars: int = 40000) -> str:
    parts = []
    char_count = 0
    for d in datasets:
        if not d.raw_text:
            continue
        header = f"\n=== DATASET: {d.title} (type={d.dataset_type.value if d.dataset_type else 'general'}, file={d.filename}) ===\n"
        if d.summary:
            header += f"Summary: {d.summary}\n"
        if d.columns:
            header += f"Columns: {', '.join(d.columns)}\n"
        section = header + d.raw_text[:20000]
        if char_count + len(section) > max_chars:
            break
        parts.append(section)
        char_count += len(section)
    return "".join(parts) if parts else "NO DATA UPLOADED — tell the user to upload tourism datasets first."


def _build_chat_history(messages: list[STChatMessage], max_turns: int = 10) -> str:
    recent = messages[-max_turns * 2:] if len(messages) > max_turns * 2 else messages
    parts = []
    for m in recent:
        role = "User" if m.role == "user" else "Assistant"
        parts.append(f"{role}: {m.content}")
    return "\n\n".join(parts) if parts else "No prior conversation."


@router.post("/message")
async def send_message(
    body: dict,
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    message = body.get("message", "").strip()
    if not message:
        return error("Message is required", 400)

    # Save user message
    user_msg = STChatMessage(id=uuid.uuid4(), user_id=user.id, role="user", content=message)
    db.add(user_msg)
    await db.flush()

    # Gather datasets
    datasets = (await db.execute(
        select(STDataset).where(STDataset.user_id == user.id)
    )).scalars().all()
    data_context = _build_data_context(datasets)

    # Gather chat history
    history_result = await db.execute(
        select(STChatMessage)
        .where(STChatMessage.user_id == user.id)
        .order_by(STChatMessage.created_at.asc())
        .limit(20)
    )
    history = _build_chat_history(history_result.scalars().all())

    forge, subject = get_forge(user)

    prompt = f"""You are the Saudi Arabia Ministry of Tourism analytics assistant.
Answer questions about KSA tourism using the datasets and tools available to you.

AVAILABLE DATA:
{data_context}

CONVERSATION HISTORY:
{history}

CURRENT QUESTION: {message}

INSTRUCTIONS:
- Use financial_calculator for any numerical computations
- Use csv_analyzer for data aggregation and trend analysis
- Be specific — cite numbers, regions, time periods
- Format with markdown (tables, bold, bullets)
- If data is insufficient, say exactly what datasets are needed"""

    result = await forge.execute("st-chat", prompt, act_as=subject)
    answer = result.output

    # Save assistant message
    asst_msg = STChatMessage(id=uuid.uuid4(), user_id=user.id, role="assistant", content=answer)
    db.add(asst_msg)
    await db.commit()

    return success({
        "message": answer,
        "sources": len(datasets),
        "agent_cost": result.cost,
        "agent_tokens": result.input_tokens + result.output_tokens,
    })


@router.get("/history")
async def chat_history(
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(STChatMessage)
        .where(STChatMessage.user_id == user.id)
        .order_by(STChatMessage.created_at.asc())
        .limit(100)
    )
    messages = result.scalars().all()
    return success([
        {"id": str(m.id), "role": m.role, "content": m.content, "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in messages
    ])


@router.delete("/history")
async def clear_history(
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(STChatMessage).where(STChatMessage.user_id == user.id))
    for m in result.scalars().all():
        await db.delete(m)
    await db.commit()
    return success({"cleared": True})
