"""Rehearsal adapter: a meeting with no room, fed typed turns through Redis."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

from engine.tools.meeting_adapter import (
    AudioFrame,
    ChatMessage,
    JoinRequest,
    JoinResult,
    MeetingAdapter,
    _BoundedQueue,
)
from engine.tools import _meeting_session as sessmod

logger = logging.getLogger(__name__)


def turns_key(meeting_id: str) -> str:
    return f"meeting:{meeting_id}:rehearsal:turns"


class RehearsalAdapter(MeetingAdapter):
    provider = "rehearsal"
    simulated = True

    def __init__(self) -> None:
        self._chat_q = _BoundedQueue(maxsize=200)
        self._closed = asyncio.Event()
        self._pump: asyncio.Task | None = None
        self._meeting_id = ""
        self.chat_out: list[str] = []

    async def join(self, req: JoinRequest) -> JoinResult:
        self._meeting_id = req.meeting_id
        self._pump = asyncio.create_task(self._pump_turns())
        return JoinResult(ok=True, session_id=f"rehearsal-{req.meeting_id}")

    async def _pump_turns(self) -> None:
        key = turns_key(self._meeting_id)
        while not self._closed.is_set():
            r = await sessmod._redis()
            if r is None:
                await asyncio.sleep(1.0)
                continue
            try:
                item = await r.blpop(key, timeout=1)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug("rehearsal pump: %s", e)
                await asyncio.sleep(1.0)
                continue
            if not item:
                if await sessmod.is_killed(self._meeting_id):
                    break
                continue
            try:
                turn = json.loads(item[1])
            except Exception:
                continue
            text = str(turn.get("text") or "").strip()
            if text:
                await self._chat_q.put(
                    ChatMessage(
                        sender=str(turn.get("speaker") or "participant")[:80],
                        text=text,
                        timestamp_ms=int(turn.get("ts_ms") or time.time() * 1000),
                    )
                )

    async def leave(self, reason: str = "bot_done") -> None:
        self._closed.set()
        self._chat_q.close()
        if self._pump and not self._pump.done():
            self._pump.cancel()

    async def publish_audio(self, pcm: bytes, *, sample_rate: int = 16000) -> None:
        return None

    async def subscribe_audio(self) -> AsyncIterator[AudioFrame]:  # type: ignore[override]
        # nobody speaks audio here, block until the rehearsal ends
        await self._closed.wait()
        return
        yield  # pragma: no cover

    async def post_chat(self, text: str) -> None:
        self.chat_out.append(text)

    async def subscribe_chat(self) -> AsyncIterator[ChatMessage]:  # type: ignore[override]
        while not self._closed.is_set():
            item = await self._chat_q.get()
            if item is None:
                break
            yield item

    async def list_participants(self) -> list[str]:
        return ["rehearsal"]
