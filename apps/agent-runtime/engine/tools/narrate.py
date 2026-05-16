from __future__ import annotations

import logging
from typing import Any

from engine import progress
from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class NarrateTool(BaseTool):
    name = "narrate"
    description = (
        "Emit a single short progress line so the trader watching the live "
        "Desk Copilot canvas can see what you are doing right now. Use this at "
        "decision points: 'planning to fan out to mispricing + scenarios', "
        "'pulling EIA Mont Belvieu propane history', 'fair value is $28.40 / MT, "
        "residual is 1.7 sigma rich'. Keep each call under 140 characters. "
        "Calling this does NOT count against your tool budget for actual work."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "One short human-readable line for the live narration feed.",
                "maxLength": 240,
            },
            "tone": {
                "type": "string",
                "enum": ["info", "step", "finding", "alert", "done"],
                "default": "step",
                "description": "Visual category. 'finding' = numeric result, 'alert' = warning, 'done' = wrap-up.",
            },
        },
        "required": ["message"],
    }

    def __init__(
        self, *, execution_id: str = "", agent_name: str = "", agent_slug: str = ""
    ) -> None:
        self._execution_id = execution_id
        self._agent_name = agent_name
        self._agent_slug = agent_slug

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        message = (arguments.get("message") or "").strip()
        tone = (arguments.get("tone") or "step").strip()
        if not message:
            return ToolResult(content="narrate: message is required", is_error=True)
        await progress.publish(
            self._execution_id,
            {
                "phase": "narration",
                "tone": tone,
                "message": message[:240],
                "agent_slug": self._agent_slug,
                "agent_name": self._agent_name,
            },
        )
        return ToolResult(content="ok")
