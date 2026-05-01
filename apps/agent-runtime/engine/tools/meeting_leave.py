"""Leave the meeting cleanly: post farewell, disconnect, drop session."""

from __future__ import annotations

from typing import Any

from engine.tools.base import BaseTool, ToolResult
from engine.tools import _meeting_session as sessmod


class MeetingLeaveTool(BaseTool):
    name = "meeting_leave"
    description = (
        "Leave the joined meeting. Optionally posts a short farewell to "
        "the meeting chat before disconnecting, and logs a final decision "
        "summarising what the bot did."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "string"},
            "farewell": {
                "type": "string",
                "default": "Thanks everyone — I'll send a summary afterwards.",
                "maxLength": 400,
            },
            "post_farewell": {"type": "boolean", "default": True},
            "summary": {
                "type": "string",
                "default": "",
                "description": "Optional one-paragraph summary persisted to the decision log.",
            },
        },
        "required": ["meeting_id"],
    }

    def __init__(self, *, execution_id: str = ""):
        self._execution_id = execution_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        meeting_id = (arguments.get("meeting_id") or "").strip()
        sess = sessmod.get(self._execution_id)
        if not sess or sess.adapter is None:
            return ToolResult(
                content="No active meeting session — nothing to leave.",
                is_error=False,  # not an error — bot may have been kicked already
            )
        if sess.meeting_id != meeting_id:
            return ToolResult(content="meeting_id mismatch", is_error=True)

        if arguments.get("post_farewell", True):
            try:
                await sess.adapter.post_chat((arguments.get("farewell") or "").strip())
            except Exception:
                pass

        try:
            await sess.adapter.leave(reason="bot_done")
        except Exception:
            pass

        sess.status = "closed"
        await sessmod.publish_session(sess)
        await sessmod.append_decision(
            meeting_id,
            "leave",
            f"Bot left meeting — {(arguments.get('summary') or 'no summary provided')[:200]}",
            detail={"summary": arguments.get("summary") or ""},
        )
        sessmod.drop(sess.execution_id)
        return ToolResult(content=f"ok: left meeting {meeting_id}")
