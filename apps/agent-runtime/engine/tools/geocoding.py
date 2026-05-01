"""Forward + reverse geocoding via Nominatim (OpenStreetMap)."""

from __future__ import annotations

from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_BASE = "https://nominatim.openstreetmap.org"
_UA = "Abenix/1.0 (geocoding tool)"


class GeocodingTool(BaseTool):
    name = "geocoding"
    description = (
        "Convert addresses to coordinates (forward) or coordinates to "
        "addresses (reverse) using OpenStreetMap Nominatim. Free, no "
        "API key. For batch / commercial use, swap to a paid provider."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["forward", "reverse"],
                "default": "forward",
                "description": "forward = address -> coords, reverse = coords -> address",
            },
            "query": {
                "type": "string",
                "description": "Address (forward) or 'lat,lon' (reverse).",
            },
            "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation", "forward")
        query = (arguments.get("query") or "").strip()
        limit = int(arguments.get("limit", 5))
        if not query:
            return ToolResult(content="Error: query is required", is_error=True)

        try:
            async with httpx.AsyncClient(
                timeout=15, headers={"User-Agent": _UA, "Accept": "application/json"}
            ) as client:
                if op == "reverse":
                    parts = [p.strip() for p in query.split(",")]
                    if len(parts) != 2:
                        return ToolResult(
                            content="reverse requires 'lat,lon'", is_error=True
                        )
                    try:
                        lat, lon = float(parts[0]), float(parts[1])
                    except ValueError:
                        return ToolResult(
                            content="lat/lon must be numbers", is_error=True
                        )
                    r = await client.get(
                        f"{_BASE}/reverse",
                        params={"format": "jsonv2", "lat": lat, "lon": lon},
                    )
                    r.raise_for_status()
                    data = r.json()
                    return ToolResult(
                        content=(
                            f"Reverse — {lat}, {lon}\n"
                            f"Display: {data.get('display_name', '(no result)')}\n"
                            f"Type: {data.get('type', '?')} ({data.get('class', '?')})"
                        ),
                        metadata=data,
                    )
                # forward
                r = await client.get(
                    f"{_BASE}/search",
                    params={
                        "format": "jsonv2",
                        "q": query,
                        "limit": limit,
                        "addressdetails": 1,
                    },
                )
                r.raise_for_status()
                results = r.json() or []
        except httpx.HTTPStatusError as e:
            return ToolResult(
                content=f"Nominatim HTTP {e.response.status_code}", is_error=True
            )
        except Exception as e:
            return ToolResult(content=f"Geocoding failed: {e}", is_error=True)

        if not results:
            return ToolResult(content=f"No results for '{query}'.")

        lines = [
            f"Forward — '{query}' ({len(results)} match{'es' if len(results) != 1 else ''}):"
        ]
        compact = []
        for i, r in enumerate(results):
            try:
                lat = float(r.get("lat", 0))
                lon = float(r.get("lon", 0))
            except (TypeError, ValueError):
                continue
            lines.append(
                f"  {i+1}. ({lat:.5f}, {lon:.5f}) — {r.get('display_name', '')}"
            )
            compact.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "display_name": r.get("display_name"),
                    "type": r.get("type"),
                    "class": r.get("class"),
                }
            )
        return ToolResult(content="\n".join(lines), metadata={"results": compact})
