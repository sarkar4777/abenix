"""ais_stream — sample real-time global vessel positions from AISStream.io.

AISStream.io ships a free WebSocket feed of every AIS-broadcasting vessel on
earth (registration only, no paid tier needed for the demo). For each call
this tool opens a short subscription, collects N position reports inside an
optional bounding box and ship-type filter, then closes the connection and
returns a structured snapshot.

AISSTREAM_API_KEY is set under Admin -> Tool Configuration. Free key:
https://aisstream.io.

Common ship-type codes:
  70-79   Cargo
  80-89   Tanker (89 = Hazardous Category A — typical for crude/product)
  84-89   LNG, LPG, chemical tankers (84 = LPG, 85 = LNG, 86-89 = others)

Bounding-box reference (lat,lon corners) for the major shipping corridors:
  USGC->NWE   : [[-100, 18], [-3, 60]]      Gulf + Atlantic + NWE approaches
  USGC->FE    : [[-180, -10], [180, 50]]    Worldwide eastbound
  ME->FE      : [[40, -10], [140, 40]]      Indian Ocean + Western Pacific
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from engine.tools.base import BaseTool, ConfigField, ToolResult

_WS_URL = "wss://stream.aisstream.io/v0/stream"


class AisStreamTool(BaseTool):
    name = "ais_stream"
    risk_tier = "low"
    config_fields = (
        ConfigField(
            "AISSTREAM_API_KEY",
            label="API key",
            kind="secret",
            required=True,
            group="AISStream",
            signup_url="https://aisstream.io",
        ),
    )
    description = (
        "Sample live vessel positions from the global AIS feed (AISStream.io). "
        "Returns up to N most-recent PositionReport / ShipStaticData messages "
        "within an optional bounding box and ship-type filter. Real, identifiable "
        "MMSIs and ship names — every vessel in the response can be looked up on "
        "VesselFinder for verification. Use ship_types=[80,84] for LPG/tanker "
        "traffic, [70,71,72,73,74,75,76,77,78,79] for cargo. The call opens a "
        "short subscription (default 8s) and closes — it does NOT keep streaming. "
        "An admin sets AISSTREAM_API_KEY under Admin -> Tool Configuration."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "bounding_boxes": {
                "type": "array",
                "description": (
                    "List of bounding boxes, each [[sw_lat, sw_lon], [ne_lat, ne_lon]]. "
                    "Default: worldwide. Smaller boxes = denser sampling for the "
                    "subscription window."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
            },
            "ship_types": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "AIS ship type codes (e.g. [80,84] for tankers + LPG). Empty = all."
                ),
            },
            "max_messages": {
                "type": "integer",
                "default": 30,
                "minimum": 1,
                "maximum": 200,
                "description": "Stop after this many messages collected.",
            },
            "duration_seconds": {
                "type": "number",
                "default": 8.0,
                "minimum": 1.0,
                "maximum": 30.0,
                "description": "Max subscription window in seconds.",
            },
        },
        "required": [],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        api_key = (self.cfg("AISSTREAM_API_KEY", required=True) or "").strip()
        try:
            import websockets  # local import — only needed when this tool runs
        except ImportError:
            return ToolResult(
                content="The 'websockets' package isn't installed in the runtime image.",
                is_error=True,
            )

        bboxes = arguments.get("bounding_boxes") or [[[-90.0, -180.0], [90.0, 180.0]]]
        ship_types = arguments.get("ship_types") or []
        max_messages = int(arguments.get("max_messages") or 30)
        duration = float(arguments.get("duration_seconds") or 8.0)

        sub: dict[str, Any] = {
            "APIKey": api_key,
            "BoundingBoxes": bboxes,
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }
        if ship_types:
            sub["FiltersShipMMSI"] = []
            sub["FilterShipType"] = ship_types

        collected: list[dict[str, Any]] = []
        ship_names: dict[int, str] = {}
        ship_types_seen: dict[int, int] = {}

        async def _run() -> None:
            async with websockets.connect(_WS_URL, ping_interval=20) as ws:
                await ws.send(json.dumps(sub))
                while len(collected) < max_messages:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    except asyncio.TimeoutError:
                        continue
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    mtype = msg.get("MessageType") or msg.get("Type")
                    meta = msg.get("MetaData") or {}
                    mmsi = meta.get("MMSI") or msg.get("MMSI")
                    payload = msg.get("Message") or {}
                    if mtype == "ShipStaticData":
                        sd = payload.get("ShipStaticData") or {}
                        if mmsi and sd.get("Name"):
                            ship_names[int(mmsi)] = str(sd["Name"]).strip()
                        if mmsi and sd.get("Type") is not None:
                            ship_types_seen[int(mmsi)] = int(sd["Type"])
                    if mtype == "PositionReport":
                        pr = payload.get("PositionReport") or {}
                        lat = pr.get("Latitude") or meta.get("latitude")
                        lon = pr.get("Longitude") or meta.get("longitude")
                        sog = pr.get("Sog")
                        cog = pr.get("Cog")
                        if mmsi is None or lat is None or lon is None:
                            continue
                        collected.append(
                            {
                                "mmsi": int(mmsi),
                                "name": meta.get("ShipName")
                                or ship_names.get(int(mmsi))
                                or "(unknown)",
                                "lat": round(float(lat), 5),
                                "lon": round(float(lon), 5),
                                "speed_knots": (
                                    round(float(sog), 2) if sog is not None else None
                                ),
                                "course_deg": (
                                    round(float(cog), 1) if cog is not None else None
                                ),
                                "time_utc": meta.get("time_utc"),
                                "ship_type": ship_types_seen.get(int(mmsi)),
                            }
                        )

        try:
            await asyncio.wait_for(_run(), timeout=duration + 4.0)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            return ToolResult(content=f"AIS subscription failed: {e}", is_error=True)

        if not collected:
            return ToolResult(
                content=(
                    "AIS subscription opened cleanly but no PositionReport messages "
                    "arrived in the window. Try a wider bounding box, fewer ship_type "
                    "filters, or a longer duration_seconds."
                ),
                metadata={"data_points": 0, "source": "https://aisstream.io"},
            )

        # De-duplicate by MMSI keeping the latest position for each vessel.
        latest_by_mmsi: dict[int, dict[str, Any]] = {}
        for v in collected:
            latest_by_mmsi[v["mmsi"]] = v
        unique = list(latest_by_mmsi.values())

        lines = [
            f"AIS live snapshot — {len(unique)} unique vessels in {len(collected)} messages",
            f"Bounding box(es): {bboxes}",
            f"Ship-type filter: {ship_types or 'all'}",
            "",
        ]
        for v in unique[:30]:
            line = (
                f"  MMSI {v['mmsi']}  {v['name']:<24}  "
                f"({v['lat']:.4f}, {v['lon']:.4f})  "
                f"sog {v['speed_knots']} kt  cog {v['course_deg']}°"
            )
            if v.get("ship_type") is not None:
                line += f"  type {v['ship_type']}"
            lines.append(line)

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "data_points": len(unique),
                "bounding_boxes": bboxes,
                "ship_types": ship_types,
                "vessels": unique,
                "source": "https://aisstream.io",
            },
        )
