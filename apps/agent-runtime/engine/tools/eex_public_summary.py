"""EEX public TTF Natural Gas Future settlement reader (degraded).

Honest provenance note up-front: free, public, machine-readable end-of-day
TTF settle prices are not actually available. EEX serves its market-data
pages through a JavaScript shell behind Cloudflare; the gvsi back-end is
not part of the public contract and the few queries that used to work
without an API key are now gated. Heren / Argus / ICE TTF settle files
all sit behind paid subscriptions.

Rather than ship a "live" tool that returns nothing and a guessed URL,
this tool always returns ``status='unavailable'`` with a documented
explanation. The agent is wired to fall back to ``monte_carlo_curve`` +
``realized_vol_calc`` against a free TTF proxy (Yahoo NG=F front-month
or EIA Henry Hub) so the simulated path is always the live path.

If a future free TTF feed appears (or the team buys an Argus/Heren
subscription) the live path can come back — replace the body of
``execute`` with the new fetcher and keep the same envelope.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from engine.tools.base import BaseTool, ToolResult


EEX_TTF_PUBLIC_URL = "https://www.eex.com/en/market-data/natural-gas/futures"

_UNAVAILABLE_NOTE = (
    "Real live TTF settle prices require an ICE/Argus/Heren subscription. "
    "The EEX public web page is JavaScript-rendered behind Cloudflare and "
    "is not machine-readable. Fall back to monte_carlo_curve calibrated "
    "against a free TTF proxy (yahoo_finance NG=F or eia_open_data HH_NATGAS)."
)


class EexPublicSummaryTool(BaseTool):
    name = "eex_public_summary"
    risk_tier = "low"
    description = (
        "Documented-degraded TTF data fetcher. Always returns "
        "status='unavailable' because no free machine-readable TTF settle "
        "feed exists today. The agent must fall back to monte_carlo_curve "
        "+ realized_vol_calc against a TTF proxy (yahoo_finance NG=F or "
        "eia_open_data HH_NATGAS). Kept in the toolchain so the agent "
        "honestly records 'live-data not available' provenance."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "hub": {
                "type": "string",
                "description": "Hub code. Ignored (no hub is live).",
                "default": "TTF",
            },
            "lookback_days": {
                "type": "integer",
                "default": 30,
                "description": "Unused — kept for signature stability.",
            },
            "tenor_months": {
                "type": "integer",
                "default": 12,
                "description": "Unused — kept for signature stability.",
            },
        },
        "required": [],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        hub = (arguments.get("hub") or "TTF").upper().strip()
        fetched_at = datetime.now(timezone.utc).isoformat()
        return ToolResult(
            content=json.dumps(
                {
                    "status": "unavailable",
                    "hub": hub,
                    "error": (
                        f"No free machine-readable TTF settle feed is "
                        f"available today. hub={hub} unavailable by design."
                    ),
                    "note": _UNAVAILABLE_NOTE,
                    "source": EEX_TTF_PUBLIC_URL,
                    "fetched_at": fetched_at,
                }
            )
        )
