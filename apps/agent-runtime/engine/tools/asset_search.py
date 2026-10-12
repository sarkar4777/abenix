"""asset_search: find streaming assets by name, type, tag, team, group or online state.

Returns keys and display names the other telemetry tools take. The search runs as the
person the agent runs for, so it only finds what their teams may see.
"""

from __future__ import annotations

import json
from typing import Any

from engine.tools import _telemetry_api as api
from engine.tools.base import READ_ONLY, BaseTool, ConfigField, ToolResult


def _int(v: Any, default: int) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


class AssetSearchTool(BaseTool):
    name = "asset_search"
    risk_tier = "low"
    effect = READ_ONLY
    description = (
        "Find assets that stream telemetry: vehicles, machines, sensors, devices and systems. "
        "Search by name, type, tag, team, group, or whether they are online, and get each asset's "
        "key (group/asset/part), display name, tags and a few latest readings. Pass the keys or "
        "names to device_state, signal_history and device_command. Example: type 'vehicle' and "
        "tag 'haul' for every haul truck."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "q": {
                "type": "string",
                "description": "Words in the name, key, tags or details, like 'EX1' or 'north pit'.",
            },
            "type": {
                "type": "string",
                "enum": ["vehicle", "machine", "sensor", "device", "system"],
                "description": "Only assets of this type.",
            },
            "tag": {"type": "string", "description": "Only assets with this tag."},
            "group": {
                "type": "string",
                "description": "Only assets in this group, like groundwork.",
            },
            "team": {"type": "string", "description": "Only assets of this team."},
            "online": {
                "type": "boolean",
                "description": "true for assets streaming now, false for ones that went quiet.",
            },
            "parts": {
                "type": "boolean",
                "description": "Also list parts (devices on an asset) as their own rows.",
            },
            "signals": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Signal names or prefixes to show as the latest readings, like ['Engine/Speed_rpm', 'GNSS/'].",
            },
            "limit": {
                "type": "integer",
                "description": "Most assets to return, default 25, at most 200.",
            },
        },
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"assets": {"type": "array"}, "total": {"type": "integer"}},
    }
    config_fields = (
        ConfigField(
            key="TELEMETRY_SEARCH_LIMIT",
            label="Default number of assets",
            kind="int",
            required=False,
            group="Telemetry",
            description="How many assets a search returns when the agent does not say.",
            default="25",
        ),
    )

    def __init__(self, tenant_id: str | None = None) -> None:
        self.tenant_id = tenant_id or ""

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        limit = _int(
            arguments.get("limit"), _int(self.cfg("TELEMETRY_SEARCH_LIMIT"), 25)
        )
        limit = max(1, min(200, limit))
        sigs = arguments.get("signals") or []
        if isinstance(sigs, str):
            sigs = [s.strip() for s in sigs.split(",") if s.strip()]
        online = arguments.get("online")
        params = {
            "q": str(arguments.get("q") or "").strip(),
            "type": str(arguments.get("type") or "").strip().lower(),
            "tag": str(arguments.get("tag") or "").strip(),
            "group": str(arguments.get("group") or "").strip(),
            "team": str(arguments.get("team") or "").strip(),
            "online": "" if online is None else ("yes" if online else "no"),
            "parts": "true" if arguments.get("parts") else "",
            "headline_signals": ",".join(str(s) for s in sigs[:20]),
            "limit": limit,
        }
        status, data, err = await api.call(
            "GET", "/api/telemetry/loop/assets", params=params
        )
        if status == 0 or status >= 300:
            return ToolResult(content=err, is_error=True, metadata={"status": status})
        rows = data or []
        out = {
            "assets": [
                {
                    k: r.get(k)
                    for k in (
                        "key",
                        "name",
                        "type",
                        "tags",
                        "team",
                        "online",
                        "last_seen",
                        "parts",
                        "readings",
                        "fields",
                    )
                    if r.get(k) not in (None, [], {})
                }
                for r in rows
            ],
            "count": len(rows),
        }
        if not rows:
            out["message"] = (
                "No assets match. Try fewer filters, or a word from the name. "
                "Assets appear when their source sends data."
            )
        return ToolResult(
            content=json.dumps(out, default=str), metadata={"count": len(rows)}
        )
