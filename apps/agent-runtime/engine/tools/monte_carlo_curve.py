"""Monte Carlo forward-curve simulator for commodity hubs."""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class MonteCarloCurveTool(BaseTool):
    name = "monte_carlo_curve"
    description = (
        "Simulate a forward curve via mean-reverting GBM with optional "
        "seasonal overlay. Returns the expected curve plus P10/P90 band "
        "points at monthly tenors. Use for natural gas / power / refined "
        "products where realised vol is observable but the forward is illiquid."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "spot": {
                "type": "number",
                "description": "Current spot price (e.g. TTF M+1 in EUR/MWh).",
            },
            "vol": {
                "type": "number",
                "description": "Annualised realized volatility as a decimal (0.45 = 45%).",
            },
            "mean_reversion": {
                "type": "number",
                "default": 0.15,
                "description": "Mean-reversion strength toward long-run mean. 0 disables.",
            },
            "long_run_mean": {
                "type": "number",
                "description": "Long-run mean price. Defaults to spot if omitted.",
            },
            "seasonality_amplitude": {
                "type": "number",
                "default": 0.0,
                "description": "Peak-to-trough seasonal swing as a fraction of spot (0.2 = 20%).",
            },
            "seasonality_peak_month": {
                "type": "integer",
                "default": 1,
                "description": "Calendar month of the seasonal peak (1=Jan). Gas peaks in winter.",
            },
            "tenor_months": {
                "type": "integer",
                "default": 24,
                "description": "Number of monthly tenor points to simulate.",
            },
            "paths": {
                "type": "integer",
                "default": 1000,
                "description": "Number of MC paths. Capped at 10000.",
            },
            "drift": {
                "type": "number",
                "default": 0.0,
                "description": "Annualised drift (decimal). Use sparingly.",
            },
            "start_month": {
                "type": "integer",
                "default": 1,
                "description": "Calendar month of the first tenor point (1-12).",
            },
        },
        "required": ["spot", "vol"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            import numpy as np
        except ImportError:
            return ToolResult(content="numpy not installed", is_error=True)

        spot = float(arguments.get("spot") or 0.0)
        if spot <= 0:
            return ToolResult(content="spot must be > 0", is_error=True)
        vol = max(0.0, float(arguments.get("vol") or 0.0))
        kappa = max(0.0, float(arguments.get("mean_reversion") or 0.15))
        lr_mean = float(arguments.get("long_run_mean") or spot)
        amp = max(0.0, float(arguments.get("seasonality_amplitude") or 0.0))
        peak_month = int(arguments.get("seasonality_peak_month") or 1)
        tenor = max(1, min(int(arguments.get("tenor_months") or 24), 120))
        paths = max(100, min(int(arguments.get("paths") or 1000), 10000))
        drift = float(arguments.get("drift") or 0.0)
        start_month = int(arguments.get("start_month") or 1)

        dt = 1.0 / 12.0
        sigma_step = vol * math.sqrt(dt)
        # Itô correction for geometric Brownian motion: without subtracting
        # 0.5 * sigma^2 * dt the expected level grows like exp(0.5*sigma^2*t),
        # which produced the 700k/bbl Brent blow-up. Keep it on every step so
        # E[exp(log_path)] tracks the deterministic drift, not the variance.
        ito_step = 0.5 * vol * vol * dt

        rng = np.random.default_rng(seed=42)
        log_paths = np.zeros((paths, tenor))
        log_spot = math.log(spot)
        log_lr = math.log(max(lr_mean, 1e-6))
        prev = np.full(paths, log_spot)
        for t in range(tenor):
            shock = rng.standard_normal(paths) * sigma_step
            reversion = kappa * (log_lr - prev) * dt
            # simulated_price = spot * exp((mu - 0.5*sigma^2)*t + sigma*sqrt(t)*Z)
            prev = prev + reversion + drift * dt - ito_step + shock
            log_paths[:, t] = prev

        levels = np.exp(log_paths)

        def _seasonal(month_idx: int) -> float:
            if amp <= 0:
                return 1.0
            phase = 2 * math.pi * ((month_idx - peak_month) / 12.0)
            return 1.0 + (amp / 2.0) * math.cos(phase)

        season_mult = np.array(
            [_seasonal(((start_month - 1 + t) % 12) + 1) for t in range(tenor)]
        )
        levels = levels * season_mult[None, :]

        expected = levels.mean(axis=0)
        p10 = np.percentile(levels, 10, axis=0)
        p50 = np.percentile(levels, 50, axis=0)
        p90 = np.percentile(levels, 90, axis=0)

        # Server-side post-condition: if the simulated curve has wandered more
        # than an order of magnitude away from spot, the calibration is wrong
        # (un-clamped vol upstream, bad anchor, exploded seed). Suppress the
        # numbers and return a degraded shape so the UI shows "data unavailable"
        # instead of a fabricated $700k/bbl print.
        curve_max = float(expected.max())
        curve_min = float(expected.min())
        if curve_max > 10.0 * spot or curve_min < spot / 10.0:
            logger.warning(
                "monte_carlo_curve degraded: spot=%s expected_max=%s expected_min=%s vol=%s",
                spot,
                curve_max,
                curve_min,
                vol,
            )
            return ToolResult(
                content=json.dumps(
                    {
                        "spot": spot,
                        "vol": vol,
                        "tenor_months": tenor,
                        "paths": paths,
                        "seasonality_amplitude": amp,
                        "long_run_mean": lr_mean,
                        "points": [],
                        "data_quality": "degraded",
                        "degraded_reason": (
                            f"expected curve out of band: max={curve_max:.2f} "
                            f"min={curve_min:.2f} vs spot={spot:.2f} "
                            "(>10x or <0.1x). likely uncalibrated vol upstream."
                        ),
                    }
                )
            )

        points = []
        for t in range(tenor):
            month_idx = ((start_month - 1 + t) % 12) + 1
            points.append(
                {
                    "tenor": f"M+{t + 1}",
                    "month": month_idx,
                    "expected": round(float(expected[t]), 4),
                    "p10": round(float(p10[t]), 4),
                    "p50": round(float(p50[t]), 4),
                    "p90": round(float(p90[t]), 4),
                }
            )

        return ToolResult(
            content=json.dumps(
                {
                    "spot": spot,
                    "vol": vol,
                    "tenor_months": tenor,
                    "paths": paths,
                    "seasonality_amplitude": amp,
                    "long_run_mean": lr_mean,
                    "points": points,
                }
            )
        )
