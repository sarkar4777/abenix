"""A small simulated plant for trying earned autonomy with no external system.

Pressure settles to setpoint times demand with a first order lag and a little
noise, so a read tells the agent enough to predict the next one. Demand swings
slowly through the hour with a small random wander on top, so pressure moves a
few tenths of a bar every few minutes and leaves the normal 4.0 to 5.0 bar band
when nobody acts.
"""

from __future__ import annotations

import json
import math
import os
import random
import time
from typing import Any

from engine import credentials, governance
from engine.tools.base import READ_ONLY, BaseTool, Effect, ToolResult

LOW_BAR = 4.0
HIGH_BAR = 5.0
MAX_SETPOINT = 10.0
TAU_S = 8.0
NOISE_BAR = 0.02
# an hourly swing of 0.2 moves demand at most about 0.01 in 30 seconds
DEMAND_SWING = 0.2
DEMAND_PERIOD_S = 3600.0
# per square root second, on top of the swing
DEMAND_DRIFT = 0.001
DEMAND_PULL_S = 1800.0
DEMAND_MIN, DEMAND_MAX = 0.75, 1.25
SETTLE_S = 30
SETTLE_TOLERANCE_BAR = 0.1
RESPONSE_NOTE = (
    f"Pressure settles to about setpoint_bar x demand within {SETTLE_S} seconds, "
    f"give or take {SETTLE_TOLERANCE_BAR:g} bar. Demand drifts slowly on its own."
)
STATE_TTL_S = 30 * 24 * 3600

_memory: dict[str, dict[str, Any]] = {}
_redis: Any = None
_redis_failed_at = 0.0


def settles_to(state: dict[str, Any]) -> float:
    """Where pressure ends up for the current setpoint and demand."""
    return float(state["setpoint_bar"]) * float(state["demand"])


def swing(state: dict[str, Any], t: float) -> float:
    phase = float(state.get("phase_s") or 0.0)
    return 1.0 + DEMAND_SWING * math.sin(2 * math.pi * (t + phase) / DEMAND_PERIOD_S)


def _new_state(now: float) -> dict[str, Any]:
    setpoint = 4.5
    s = {
        "setpoint_bar": setpoint,
        "phase_s": round(random.uniform(0, DEMAND_PERIOD_S), 1),
        "wander": 0.0,
        "updated_at": now,
    }
    s["demand"] = round(swing(s, now), 4)
    s["pressure_bar"] = round(setpoint * s["demand"], 3)
    return s


def advance(
    state: dict[str, Any], now: float, rng: random.Random | None = None
) -> dict[str, Any]:
    """Move the plant forward to ``now``."""
    rng = rng or random
    last = state.get("updated_at")
    dt = max(0.0, min(now - float(now if last is None else last), 24 * 3600.0))
    s = dict(state)
    if "phase_s" not in s:
        # a plant saved before the swing existed keeps its demand
        s["phase_s"] = round(rng.uniform(0, DEMAND_PERIOD_S), 1)
        then = float(now if last is None else last)
        s["wander"] = float(s["demand"]) - swing(s, then)
    if dt > 0:
        # the wander is a random walk pulled back towards the swing
        wander = float(s.get("wander") or 0.0)
        wander -= wander * (1 - math.exp(-dt / DEMAND_PULL_S))
        wander += rng.gauss(0.0, DEMAND_DRIFT * math.sqrt(dt))
        demand = min(DEMAND_MAX, max(DEMAND_MIN, swing(s, now) + wander))
        s["wander"] = round(demand - swing(s, now), 5)
        target = float(s["setpoint_bar"]) * demand
        p = float(s["pressure_bar"])
        p += (target - p) * (1 - math.exp(-dt / TAU_S))
        p += rng.gauss(0.0, NOISE_BAR)
        s["demand"] = round(demand, 4)
        s["pressure_bar"] = round(max(0.0, p), 3)
    s["updated_at"] = now
    return s


def alarm(pressure: float) -> str | None:
    if pressure < LOW_BAR:
        return f"Low pressure: {pressure:.2f} bar is under {LOW_BAR:.1f} bar"
    if pressure > HIGH_BAR:
        return f"High pressure: {pressure:.2f} bar is over {HIGH_BAR:.1f} bar"
    return None


def view(state: dict[str, Any]) -> dict[str, Any]:
    p = float(state["pressure_bar"])
    return {
        "pressure_bar": round(p, 2),
        "setpoint_bar": round(float(state["setpoint_bar"]), 2),
        "demand": round(float(state["demand"]), 3),
        "alarm": alarm(p),
        "normal_band_bar": [LOW_BAR, HIGH_BAR],
        "note": RESPONSE_NOTE,
    }


async def _client() -> Any:
    global _redis, _redis_failed_at
    url = os.environ.get("REDIS_URL", "")
    if not url or time.monotonic() - _redis_failed_at < 60:
        return None
    if _redis is None:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
    return _redis


def _key(tenant: str) -> str:
    return f"abenix:sample_plant:{tenant or 'default'}"


async def load(tenant: str) -> dict[str, Any] | None:
    global _redis_failed_at
    try:
        r = await _client()
        if r is not None:
            raw = await r.get(_key(tenant))
            return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        _redis_failed_at = time.monotonic()
    got = _memory.get(tenant)
    return dict(got) if got else None


async def save(tenant: str, state: dict[str, Any]) -> None:
    global _redis_failed_at
    _memory[tenant] = dict(state)
    try:
        r = await _client()
        if r is not None:
            await r.set(_key(tenant), json.dumps(state), ex=STATE_TTL_S)
    except Exception:  # noqa: BLE001
        _redis_failed_at = time.monotonic()


class SamplePlantTool(BaseTool):
    name = "sample_plant"
    risk_tier = "low"
    effect = Effect(
        kind="control",
        label="Change the plant pressure setpoint",
        magnitude_param="setpoint_bar",
        reversible=True,
    )
    description = (
        "A simulated plant for trying autonomy. 'read' returns pressure_bar, setpoint_bar, "
        "demand, any alarm and a note on how it responds. 'set_setpoint' sets setpoint_bar. "
        "Pressure settles to about setpoint_bar x demand within 30 seconds, give or take "
        "0.1 bar, and demand drifts slowly on its own. Normal pressure is 4.0 to 5.0 bar."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "set_setpoint"],
                "description": "read the plant, or set a new pressure setpoint",
            },
            "setpoint_bar": {
                "type": "number",
                "description": "New pressure setpoint in bar, for set_setpoint",
            },
        },
        "required": ["operation"],
    }

    def __init__(self, tenant_id: str = "") -> None:
        self.tenant_id = tenant_id

    @classmethod
    def effect_for(cls, arguments: dict[str, Any]) -> Effect | None:
        return cls.effect if arguments.get("operation") == "set_setpoint" else READ_ONLY

    def _tenant(self) -> str:
        run = governance.current()
        return (
            credentials.current_tenant()
            or (run.tenant_id if run else "")
            or str(self.tenant_id or "")
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = str(arguments.get("operation") or "read")
        if op not in ("read", "set_setpoint"):
            return ToolResult(
                content=f"Unknown operation {op}. Use read or set_setpoint.",
                is_error=True,
            )
        tenant = self._tenant()
        now = time.time()
        state = await load(tenant)
        state = advance(state, now) if state else _new_state(now)
        if op == "set_setpoint":
            raw = arguments.get("setpoint_bar")
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return ToolResult(
                    content="setpoint_bar must be a number of bar, for example 4.5.",
                    is_error=True,
                )
            if not (0.0 < value <= MAX_SETPOINT) or value != value:
                return ToolResult(
                    content=f"setpoint_bar must be above 0 and at most {MAX_SETPOINT:g} bar.",
                    is_error=True,
                )
            state["setpoint_bar"] = round(value, 3)
        await save(tenant, state)
        out = view(state)
        if op == "set_setpoint":
            out["message"] = (
                f"Setpoint is now {value:g} bar. Pressure settles to about "
                f"{settles_to(state):.2f} bar within {SETTLE_S} seconds."
            )
        return ToolResult(content=json.dumps(out), metadata={"sample_plant": out})
