"""Realized volatility, momentum and drift estimator for price histories."""

from __future__ import annotations

import json
import math
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class RealizedVolCalcTool(BaseTool):
    name = "realized_vol_calc"
    description = (
        "Compute realized volatility (annualized), 4-week momentum and a "
        "naive drift estimate from a price history array. Inputs are daily "
        "closes. Use to calibrate Monte Carlo forward curves on illiquid hubs."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "prices": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Daily closing prices, oldest first.",
            },
            "lookback_days": {
                "type": "integer",
                "default": 60,
                "description": "Window for vol/drift. 60 ≈ 3 trading months.",
            },
            "periods_per_year": {
                "type": "integer",
                "default": 252,
                "description": "Trading periods per year for annualisation.",
            },
        },
        "required": ["prices"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        prices = arguments.get("prices") or []
        lookback = max(5, int(arguments.get("lookback_days") or 60))
        ppy = max(1, int(arguments.get("periods_per_year") or 252))

        if not isinstance(prices, list) or len(prices) < 6:
            return ToolResult(content="Need at least 6 price points", is_error=True)

        try:
            import numpy as np
        except ImportError:
            return ToolResult(content="numpy not installed", is_error=True)

        arr = np.array([float(p) for p in prices if p is not None], dtype=float)
        if (arr <= 0).any():
            return ToolResult(content="prices must all be > 0", is_error=True)

        window = arr[-lookback:] if len(arr) > lookback else arr
        log_returns = np.diff(np.log(window))
        if len(log_returns) < 2:
            return ToolResult(content="Not enough return observations", is_error=True)

        sigma_step = float(np.std(log_returns, ddof=1))
        vol_annual_raw = sigma_step * math.sqrt(ppy)
        # Clamp annualized vol to a sane band. Stale ticks, gaps, or a single
        # flash-crash bar can balloon realized vol to 3-10x; without a ceiling
        # the downstream Monte Carlo log-paths explode (E[exp(X)] grows with
        # sigma^2, so 500% vol produces $700k/bbl expected curves). Floor at
        # 10% so a quiet tape doesn't collapse the band to a flat line.
        vol_annual = max(0.10, min(1.20, vol_annual_raw))
        mean_step = float(np.mean(log_returns))
        drift_annual = mean_step * ppy

        # 4-week (20 trading-day) momentum on the full series
        mom_window = min(20, len(arr) - 1)
        momentum_4w = (
            float(arr[-1] / arr[-1 - mom_window] - 1.0) if mom_window > 0 else 0.0
        )

        return ToolResult(
            content=json.dumps(
                {
                    "vol_annual": round(vol_annual, 6),
                    "vol_annual_raw": round(vol_annual_raw, 6),
                    "vol_clamped": vol_annual_raw != vol_annual,
                    "vol_daily": round(sigma_step, 6),
                    "drift_annual": round(drift_annual, 6),
                    "momentum_4w": round(momentum_4w, 6),
                    "lookback_used": int(len(window)),
                    "returns_used": int(len(log_returns)),
                    "last_price": float(arr[-1]),
                    "mean_price_window": float(np.mean(window)),
                }
            )
        )
