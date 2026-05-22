"""Market data cache — wraps energy market tools with TTL caching."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, Any]] = {}  # key -> (expiry_timestamp, data)


def _get_cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and entry[0] > time.time():
        return entry[1]
    return None


def _set_cached(key: str, data: Any, ttl_seconds: int) -> None:
    _cache[key] = (time.time() + ttl_seconds, data)


async def fetch_power_prices() -> dict[str, Any]:
    """Fetch EU power prices from ENTSO-E (cached 5 min)."""
    cached = _get_cached("power_prices")
    if cached:
        return cached

    try:
        import sys
        from pathlib import Path
        runtime_path = str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime")
        if runtime_path not in sys.path:
            sys.path.insert(0, runtime_path)

        from engine.tools.entso_e_tool import EntsoETool
        tool = EntsoETool()
        result = await tool.execute({"data_type": "day_ahead_price", "area": "DE_LU"})
        data = {"available": not result.is_error, "content": result.content[:2000], "metadata": result.metadata}
    except Exception as e:
        logger.warning("Power price fetch failed: %s", e)
        data = {"available": False, "content": str(e), "metadata": {}}

    _set_cached("power_prices", data, 300)  # 5 min TTL
    return data


async def fetch_carbon_prices() -> dict[str, Any]:
    """Fetch carbon/UK power prices from Ember (cached 30 min)."""
    cached = _get_cached("carbon_prices")
    if cached:
        return cached

    try:
        import sys
        from pathlib import Path
        runtime_path = str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime")
        if runtime_path not in sys.path:
            sys.path.insert(0, runtime_path)

        from engine.tools.ember_tool import EmberClimateTool
        tool = EmberClimateTool()
        result = await tool.execute({"data_type": "carbon_price", "country": "GBR"})
        data = {"available": not result.is_error, "content": result.content[:2000], "metadata": result.metadata}
    except Exception as e:
        logger.warning("Carbon price fetch failed: %s", e)
        data = {"available": False, "content": str(e), "metadata": {}}

    _set_cached("carbon_prices", data, 1800)  # 30 min TTL
    return data


async def fetch_fx_rates() -> dict[str, Any]:
    """Fetch FX rates from ECB (cached 30 min)."""
    cached = _get_cached("fx_rates")
    if cached:
        return cached

    try:
        import sys
        from pathlib import Path
        runtime_path = str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime")
        if runtime_path not in sys.path:
            sys.path.insert(0, runtime_path)

        from engine.tools.ecb_rates_tool import ECBRatesTool
        tool = ECBRatesTool()
        result = await tool.execute({"data_type": "fx_rate", "currency_pair": "EUR/USD"})
        data = {"available": not result.is_error, "content": result.content[:2000], "metadata": result.metadata}
    except Exception as e:
        logger.warning("FX rate fetch failed: %s", e)
        data = {"available": False, "content": str(e), "metadata": {}}

    _set_cached("fx_rates", data, 1800)  # 30 min TTL
    return data


async def fetch_all_market_data() -> dict[str, Any]:
    """Fetch all market data sources in parallel."""
    power, carbon, fx = await asyncio.gather(
        fetch_power_prices(),
        fetch_carbon_prices(),
        fetch_fx_rates(),
        return_exceptions=True,
    )

    return {
        "power": power if not isinstance(power, Exception) else {"available": False},
        "carbon": carbon if not isinstance(carbon, Exception) else {"available": False},
        "fx": fx if not isinstance(fx, Exception) else {"available": False},
    }
