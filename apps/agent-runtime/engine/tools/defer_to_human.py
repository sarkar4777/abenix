"""Defer-to-human tool — the single most important safety rail."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult
from engine.tools import _meeting_session as sessmod

logger = logging.getLogger(__name__)


class DeferToHumanTool(BaseTool):
    name = "defer_to_human"
    description = (
        "Route a question back to the human the agent is representing. "
        "Call this whenever: (a) the question is outside the meeting's "
        "declared topic allow-list, (b) the question asks for a new "
        "commitment, (c) the answer isn't in the persona KB with enough "
        "confidence. Blocks up to hold_seconds waiting for the user's "
        "reply; returns their answer, or a graceful 'let me get back to "
        "you' if they don't reply in time."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "string"},
            "question": {"type": "string", "minLength": 5, "maxLength": 1000},
            "context": {
                "type": "string",
                "default": "",
                "description": "Why the agent is deferring (for the user's inbox).",
            },
            "hold_seconds": {
                "type": "integer",
                "default": 30,
                "minimum": 5,
                "maximum": 180,
                "description": "How long to wait for the user's reply before returning the fallback.",
            },
            "fallback": {
                "type": "string",
                "default": "Let me check on that and come back to you.",
                "maxLength": 400,
            },
        },
        "required": ["meeting_id", "question"],
    }

    def __init__(
        self,
        *,
        execution_id: str = "",
        tenant_id: str = "",
        user_id: str = "",
    ):
        self._execution_id = execution_id
        self._tenant_id = tenant_id
        self._user_id = user_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        meeting_id = (arguments.get("meeting_id") or "").strip()
        question = (arguments.get("question") or "").strip()
        context = (arguments.get("context") or "").strip()
        hold_seconds = int(arguments.get("hold_seconds", 30))
        fallback = (
            arguments.get("fallback") or "Let me check and come back to you."
        ).strip()
        if not meeting_id or not question:
            return ToolResult(
                content="meeting_id and question are required", is_error=True
            )

        deferral_id = str(uuid.uuid4())
        entry = {
            "deferral_id": deferral_id,
            "meeting_id": meeting_id,
            "tenant_id": self._tenant_id,
            "user_id": self._user_id,
            "question": question,
            "context": context,
            "created_at_ms": int(time.time() * 1000),
            "status": "pending",
        }

        # 1. Persist to Redis + pub/sub → UI sees it immediately
        r = await _redis()
        pubsub_channel = f"deferral:{deferral_id}:answer"
        if r is None:
            return ToolResult(
                content=(
                    f"{fallback} (Note: deferral persistence unavailable — "
                    "Redis not reachable; question was not delivered.)"
                ),
                metadata={"delivered": False, "fallback_used": True},
            )
        try:
            await r.hset(f"meeting:{meeting_id}:deferral:{deferral_id}", mapping=entry)
            await r.expire(f"meeting:{meeting_id}:deferral:{deferral_id}", 86400)
            await r.rpush(f"meeting:{meeting_id}:deferrals", deferral_id)
            await r.expire(f"meeting:{meeting_id}:deferrals", 86400)
            await r.publish(
                f"meeting:{meeting_id}:events",
                json.dumps({"type": "deferral", "entry": entry}),
            )

            # 2. Fire webhook if configured (Slack / custom push)
            await _fire_webhook(entry)

            await sessmod.append_decision(
                meeting_id,
                "defer",
                f"Deferred to human: {question[:160]}",
                detail={
                    "deferral_id": deferral_id,
                    "context": context,
                    "hold_seconds": hold_seconds,
                },
            )

            # 3. Subscribe + wait for answer
            answer = await _wait_for_answer(r, pubsub_channel, hold_seconds)
        finally:
            try:
                await r.aclose()
            except Exception:
                pass

        if answer:
            return ToolResult(
                content=json.dumps(
                    {
                        "deferred": True,
                        "answer": answer,
                        "deferral_id": deferral_id,
                        "timed_out": False,
                    }
                ),
                metadata={"delivered": True, "answered": True},
            )
        return ToolResult(
            content=json.dumps(
                {
                    "deferred": True,
                    "answer": fallback,
                    "deferral_id": deferral_id,
                    "timed_out": True,
                }
            ),
            metadata={"delivered": True, "answered": False, "timed_out": True},
        )


async def _redis() -> Any:
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return None
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return None
    try:
        return aioredis.from_url(url, decode_responses=True)
    except Exception:
        return None


async def _wait_for_answer(r: Any, channel: str, hold_seconds: int) -> str | None:
    try:
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)
    except Exception:
        return None
    try:
        deadline = time.monotonic() + hold_seconds
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                msg = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=min(remaining, 1.0),
                )
            except asyncio.TimeoutError:
                continue
            if not msg:
                continue
            data = msg.get("data", "")
            if not data:
                continue
            try:
                payload = json.loads(data) if isinstance(data, str) else {}
            except Exception:
                payload = {}
            ans = (payload.get("answer") or "").strip()
            if ans:
                return ans
        return None
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
        except Exception:
            pass


async def _fire_webhook(entry: dict[str, Any]) -> None:
    url = os.environ.get("DEFER_NOTIFY_WEBHOOK_URL", "").strip()
    if not url:
        return
    # Keep payload generic — Slack webhook format as a reasonable default
    payload = {
        "text": (
            f":bell: *Abenix bot is deferring a meeting question to you*\n"
            f"*Meeting:* `{entry['meeting_id']}`\n"
            f"*Question:* {entry['question']}\n"
            f"_Context:_ {entry.get('context') or '—'}\n"
            f"Answer in the /meetings UI within the hold window."
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=payload)
    except Exception as e:
        logger.debug("defer webhook failed: %s", e)
