"""Meeting join tool."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from engine.tools.base import BaseTool, ToolResult
from engine.tools.meeting_adapter import JoinRequest, get_adapter
from engine.tools import _meeting_session as sessmod

logger = logging.getLogger(__name__)


class MeetingJoinTool(BaseTool):
    name = "meeting_join"
    description = (
        "Join a meeting on the user's behalf via LiveKit (or Teams / Zoom "
        "where enabled). The join plays a consent disclosure, records the "
        "start of the session, and returns a session_id used by other "
        "meeting_* tools. The bot will refuse to join if the meeting has "
        "not been pre-authorized by the user via the /meetings UI."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "meeting_id": {
                "type": "string",
                "description": "Abenix internal meeting id (UUID) — matches /api/meetings/<id>.",
            },
            "provider": {
                "type": "string",
                "enum": ["livekit", "teams", "zoom"],
                "default": "livekit",
            },
            "room": {"type": "string", "description": "Provider room/meeting id."},
            "url": {
                "type": "string",
                "description": "Optional override for provider URL.",
            },
            "token": {
                "type": "string",
                "description": "Optional pre-minted provider token.",
            },
            "display_name": {
                "type": "string",
                "default": "Abenix Assistant",
                "description": "Name shown in the participant list.",
            },
            "announce_consent": {
                "type": "boolean",
                "default": True,
                "description": (
                    "If true, speak a short consent disclosure immediately "
                    "after joining. Recommended for any human-facing meeting."
                ),
            },
        },
        "required": ["meeting_id", "room"],
    }

    def __init__(
        self,
        *,
        execution_id: str = "",
        tenant_id: str = "",
        user_id: str = "",
        agent_id: str = "",
    ):
        self._execution_id = execution_id
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._agent_id = agent_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        meeting_id = (arguments.get("meeting_id") or "").strip()
        if not meeting_id:
            return ToolResult(content="meeting_id is required", is_error=True)

        # Kill-switch honored even before join
        if await sessmod.is_killed(meeting_id):
            return ToolResult(
                content=(
                    f"Meeting {meeting_id} has the kill-switch active. The "
                    "user revoked bot participation — aborting join."
                ),
                is_error=True,
                metadata={"killed": True},
            )

        # Read pre-authorized scope from Redis (written by /api/meetings/{id}/authorize)
        scope_allow, scope_defer, persona_scopes, authorized, auth = (
            await _read_meeting_scope(meeting_id)
        )
        if not authorized:
            return ToolResult(
                content=(
                    f"Meeting {meeting_id} has not been authorized by the user. "
                    "The user must authorize the bot and declare a topic allow-list "
                    "in the /meetings UI before the bot can join."
                ),
                is_error=True,
                metadata={"authorized": False},
            )

        provider = (
            (auth.get("provider") or arguments.get("provider") or "livekit")
            .strip()
            .lower()
        )
        room = (auth.get("room") or arguments.get("room") or "").strip()
        display_name = (
            auth.get("display_name")
            or arguments.get("display_name")
            or "Abenix Assistant"
        ).strip()
        if not room:
            return ToolResult(
                content=(
                    f"Meeting {meeting_id} has no room set on the meeting record. "
                    "Re-create the meeting via /meetings."
                ),
                is_error=True,
            )

        try:
            adapter = get_adapter(provider)
        except ValueError as e:
            return ToolResult(content=str(e), is_error=True)

        req = JoinRequest(
            provider=provider,
            room=room,
            display_name=display_name,
            token=arguments.get("token"),
            url=arguments.get("url"),
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            meeting_id=meeting_id,
        )
        result = await adapter.join(req)
        if not result.ok:
            return ToolResult(
                content=f"Join failed: {result.error}",
                is_error=True,
                metadata={"provider": provider},
            )

        sess = sessmod.MeetingSession(
            execution_id=self._execution_id,
            meeting_id=meeting_id,
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            provider=provider,
            room=room,
            display_name=display_name,
            adapter=adapter,
            status="live",
            scope_allow=scope_allow,
            scope_defer=scope_defer,
            persona_scopes=persona_scopes,
        )
        sessmod.register(sess)
        await sessmod.publish_session(sess)
        await sessmod.append_decision(
            meeting_id,
            "join",
            f"Bot joined as '{display_name}' via {provider}",
            detail={"session_id": result.session_id, "scope_allow": scope_allow},
        )

        consent_played = False
        if arguments.get("announce_consent", True):
            consent_played = await _announce_consent(adapter, display_name, meeting_id)

        return ToolResult(
            content=json.dumps(
                {
                    "session_id": result.session_id,
                    "meeting_id": meeting_id,
                    "provider": provider,
                    "room": room,
                    "scope_allow": scope_allow,
                    "scope_defer": scope_defer,
                    "consent_announced": consent_played,
                }
            ),
            metadata={"session_id": result.session_id, "provider": provider},
        )


async def _read_meeting_scope(
    meeting_id: str,
) -> tuple[list[str], list[str], list[str], bool, dict]:
    """Load pre-authorized scope + room/provider from Redis. Written by"""
    empty = ([], [], [], False, {})
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return empty
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return empty
    try:
        r = aioredis.from_url(url, decode_responses=True)
        raw = await r.hgetall(f"meeting:{meeting_id}:scope")
        await r.aclose()
    except Exception:
        return empty
    if not raw or raw.get("authorized", "") not in ("1", "true", "yes"):
        return empty
    allow = [s.strip() for s in (raw.get("allow") or "").split("|") if s.strip()]
    defer = [s.strip() for s in (raw.get("defer") or "").split("|") if s.strip()]
    persona = [
        s.strip() for s in (raw.get("persona_scopes") or "").split("|") if s.strip()
    ]
    auth = {
        "room": (raw.get("room") or "").strip(),
        "provider": (raw.get("provider") or "").strip(),
        "display_name": (raw.get("display_name") or "").strip(),
    }
    return (allow, defer, persona, True, auth)


async def _announce_consent(adapter: Any, display_name: str, meeting_id: str) -> bool:
    """Post a text consent notice AND try to speak it. Returns True if either succeeded."""
    try:
        msg = (
            f"Hello everyone — this meeting has an AI assistant representing the user, "
            f"joined as '{display_name}'. If you'd like me to leave at any time, say "
            f"'bot leave' or ask the host to remove me. This conversation may be "
            f"transcribed to help me respond."
        )
        await adapter.post_chat(msg)
        await sessmod.append_decision(
            meeting_id, "answer", "Posted consent disclosure to meeting chat"
        )
        # Speak-side TTS is handled by meeting_speak on first call; we log here
        return True
    except Exception as e:
        logger.debug("consent announce failed: %s", e)
        return False
