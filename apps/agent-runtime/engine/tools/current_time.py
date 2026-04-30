from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from engine.tools.base import BaseTool, ToolResult

COMMON_ZONES = {
    "UTC": "UTC",
    "EST": "America/New_York",
    "CST": "America/Chicago",
    "MST": "America/Denver",
    "PST": "America/Los_Angeles",
    "GMT": "Europe/London",
    "CET": "Europe/Berlin",
    "IST": "Asia/Kolkata",
    "JST": "Asia/Tokyo",
    "AEST": "Australia/Sydney",
}


class CurrentTimeTool(BaseTool):
    name = "current_time"
    description = (
        "Get the current date and time in UTC or a specified timezone. "
        "Supports IANA timezone names (e.g. 'America/New_York') and common "
        "abbreviations (EST, PST, GMT, CET, IST, JST, etc.)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "Timezone name (e.g. 'UTC', 'America/New_York', 'PST'). Defaults to UTC.",
                "default": "UTC",
            },
        },
        "required": [],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        tz_input = arguments.get("timezone", "UTC").strip()
        tz_name = COMMON_ZONES.get(tz_input.upper(), tz_input)

        try:
            tz = ZoneInfo(tz_name)
        except (KeyError, ValueError):
            return ToolResult(
                content=f"Unknown timezone: {tz_input}. Use IANA names like 'America/New_York' or abbreviations like 'EST', 'PST'.",
                is_error=True,
            )

        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(tz)

        lines = [
            f"Current time ({tz_name}):",
            f"  Date: {now_local.strftime('%Y-%m-%d')}",
            f"  Time: {now_local.strftime('%H:%M:%S')}",
            f"  Day: {now_local.strftime('%A')}",
            f"  ISO: {now_local.isoformat()}",
        ]
        if tz_name != "UTC":
            lines.append(f"  UTC:  {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")

        return ToolResult(
            content="\n".join(lines),
            metadata={"timezone": tz_name, "iso": now_local.isoformat()},
        )
