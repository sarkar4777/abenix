"""Zoom MeetingAdapter stub."""

from __future__ import annotations

import os
from typing import AsyncIterator

from engine.tools.meeting_adapter import (
    AudioFrame,
    ChatMessage,
    JoinRequest,
    JoinResult,
    MeetingAdapter,
)


def _missing_creds() -> str:
    missing = [k for k in ("ZOOM_SDK_KEY", "ZOOM_SDK_SECRET") if not os.environ.get(k)]
    return ", ".join(missing) if missing else ""


class ZoomAdapter(MeetingAdapter):
    provider = "zoom"

    async def join(self, req: JoinRequest) -> JoinResult:
        missing = _missing_creds()
        return JoinResult(
            ok=False,
            error=(
                "Zoom adapter requires Zoom Meeting SDK credentials. "
                f"Missing env vars: {missing}. Zoom raw-audio also requires "
                "marketplace app review. Use provider='livekit' for the "
                "demo/dev path."
            ),
        )

    async def leave(self, reason: str = "bot_done") -> None:
        return None

    async def publish_audio(self, pcm: bytes, *, sample_rate: int = 16000) -> None:
        return None

    def subscribe_audio(self) -> AsyncIterator[AudioFrame]:
        async def _empty():
            if False:
                yield  # type: ignore[unreachable]

        return _empty()

    async def post_chat(self, text: str) -> None:
        return None

    def subscribe_chat(self) -> AsyncIterator[ChatMessage]:
        async def _empty():
            if False:
                yield  # type: ignore[unreachable]

        return _empty()

    async def list_participants(self) -> list[str]:
        return []
