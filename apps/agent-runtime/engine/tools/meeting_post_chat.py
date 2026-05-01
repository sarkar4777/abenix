"""Post a text message to the meeting's chat / data channel without speaking."""

from __future__ import annotations

from typing import Any

from engine.tools.base import BaseTool, ToolResult
from engine.tools import _meeting_session as sessmod


class MeetingPostChatTool(BaseTool):
    name = "meeting_post_chat"
    description = (
        "Post a text message to the meeting chat without speaking out loud. "
        "Good for links, long-form answers, summaries, or when the user "
        "asked the bot to stay quiet but still participate in chat."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "string"},
            "text": {"type": "string", "minLength": 1, "maxLength": 4000},
        },
        "required": ["meeting_id", "text"],
    }

    def __init__(self, *, execution_id: str = ""):
        self._execution_id = execution_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        meeting_id = (arguments.get("meeting_id") or "").strip()
        text = (arguments.get("text") or "").strip()
        sess = sessmod.get(self._execution_id)
        if not sess or sess.adapter is None:
            return ToolResult(
                content="No live meeting session — call meeting_join first.",
                is_error=True,
            )
        if sess.meeting_id != meeting_id:
            return ToolResult(content="meeting_id mismatch", is_error=True)
        if await sessmod.is_killed(meeting_id):
            return ToolResult(
                content="Kill-switch active — refusing to post.",
                is_error=True,
                metadata={"killed": True},
            )
        try:
            await sess.adapter.post_chat(text)
        except Exception as e:
            return ToolResult(content=f"post_chat failed: {e}", is_error=True)
        await sessmod.append_decision(
            meeting_id,
            "answer",
            f"Chat message: {text[:140]}",
        )
        return ToolResult(content=f"ok: posted {len(text)} chars")
