"""Provider-agnostic meeting adapter interface."""

from __future__ import annotations

import abc
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)


@dataclass
class JoinRequest:
    """All the parameters needed to join a meeting across providers."""

    provider: str  # "livekit" | "teams" | "zoom"
    room: str  # provider-native room/meeting id
    display_name: str  # what participants see
    token: Optional[str] = None  # livekit-signed token / teams bot token
    url: Optional[str] = None  # livekit server url / teams join url
    tenant_id: str = ""
    user_id: str = ""
    meeting_id: str = ""  # our internal meeting id (foreign key to meetings table)


@dataclass
class AudioFrame:
    """Raw PCM audio from the meeting, ready to feed STT."""

    pcm: bytes  # 16-bit LE, mono, 16kHz by convention
    sample_rate: int = 16000
    channels: int = 1
    participant: str = ""  # participant identity that produced the frame
    timestamp_ms: int = 0


@dataclass
class ChatMessage:
    """Meeting chat message (data channel on LiveKit, chat API on Teams/Zoom)."""

    sender: str
    text: str
    timestamp_ms: int = 0


@dataclass
class JoinResult:
    ok: bool
    session_id: str = ""
    error: str = ""
    provider_room_sid: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class MeetingAdapter(abc.ABC):
    """One instance per meeting session. Hold live state internally."""

    provider: str

    @abc.abstractmethod
    async def join(self, req: JoinRequest) -> JoinResult:
        """Connect, authenticate, announce presence."""

    @abc.abstractmethod
    async def leave(self, reason: str = "bot_done") -> None:
        """Clean shutdown — publish leave event to subscribers before closing."""

    @abc.abstractmethod
    async def publish_audio(self, pcm: bytes, *, sample_rate: int = 16000) -> None:
        """Send audio into the meeting's shared audio channel (bot speaking)."""

    @abc.abstractmethod
    def subscribe_audio(self) -> AsyncIterator[AudioFrame]:
        """Async iterator yielding PCM frames from other participants."""

    @abc.abstractmethod
    async def post_chat(self, text: str) -> None:
        """Post a message to the meeting's chat/data channel."""

    @abc.abstractmethod
    def subscribe_chat(self) -> AsyncIterator[ChatMessage]:
        """Async iterator yielding chat messages from other participants."""

    @abc.abstractmethod
    async def list_participants(self) -> list[str]:
        """Current participant identities, excluding the bot itself."""

    # Default: no-op unless adapter overrides
    async def set_muted(self, muted: bool) -> None:
        return None


def get_adapter(provider: str) -> MeetingAdapter:
    """Return a fresh adapter for the provider."""
    p = (provider or "").strip().lower()
    if p == "livekit":
        from engine.tools._livekit_adapter import LiveKitAdapter

        return LiveKitAdapter()
    if p == "teams":
        from engine.tools._teams_adapter import TeamsAdapter

        return TeamsAdapter()
    if p == "zoom":
        from engine.tools._zoom_adapter import ZoomAdapter

        return ZoomAdapter()
    raise ValueError(
        f"Unknown meeting provider '{provider}'. "
        "Expected one of: livekit, teams, zoom."
    )


class _BoundedQueue:
    """Async queue with a drop-oldest policy. Adapters use this for audio"""

    def __init__(self, maxsize: int = 200) -> None:
        self._q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)

    async def put(self, item: Any) -> None:
        if self._q.full():
            try:
                self._q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        await self._q.put(item)

    async def get(self) -> Any:
        return await self._q.get()

    def close(self) -> None:
        # Sentinel: None ends the iterator
        try:
            self._q.put_nowait(None)
        except asyncio.QueueFull:
            pass
