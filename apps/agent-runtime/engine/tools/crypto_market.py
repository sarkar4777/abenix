"""Crypto / digital-asset market data via CoinGecko (free public tier)."""

from __future__ import annotations

import os
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_BASE = "https://api.coingecko.com/api/v3"


def _headers() -> dict[str, str]:
    h = {"Accept": "application/json"}
    key = os.environ.get("COINGECKO_API_KEY", "").strip()
    if key:
        h["x-cg-pro-api-key"] = key
    return h


class CryptoMarketTool(BaseTool):
    name = "crypto_market"
    description = (
        "Crypto market data from CoinGecko: spot price, 24h change, market "
        "cap, and OHLC history for any coin. Free tier (~30 req/min). "
        "Set COINGECKO_API_KEY for the pro tier."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["price", "ohlc", "trending", "search"],
                "default": "price",
            },
            "coin_id": {
                "type": "string",
                "description": "CoinGecko coin id ('bitcoin', 'ethereum', 'solana'). Use operation=search to discover ids.",
            },
            "vs_currency": {"type": "string", "default": "usd"},
            "days": {
                "type": "integer",
                "default": 7,
                "minimum": 1,
                "maximum": 365,
                "description": "Lookback for ohlc operation.",
            },
            "query": {
                "type": "string",
                "description": "Free-text search for operation=search",
            },
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation", "price")
        try:
            async with httpx.AsyncClient(timeout=20, headers=_headers()) as client:
                if op == "trending":
                    r = await client.get(f"{_BASE}/search/trending")
                    r.raise_for_status()
                    coins = r.json().get("coins", [])
                    if not coins:
                        return ToolResult(content="No trending coins returned.")
                    lines = ["Trending coins (CoinGecko):"]
                    for c in coins[:10]:
                        item = c.get("item", {})
                        lines.append(
                            f"  {item.get('market_cap_rank') or '-':>3}. "
                            f"{item.get('name')} ({item.get('symbol', '').upper()}) — "
                            f"id: {item.get('id')}"
                        )
                    return ToolResult(
                        content="\n".join(lines), metadata={"trending": coins}
                    )

                if op == "search":
                    q = (arguments.get("query") or "").strip()
                    if not q:
                        return ToolResult(
                            content="search requires 'query'", is_error=True
                        )
                    r = await client.get(f"{_BASE}/search", params={"query": q})
                    r.raise_for_status()
                    found = r.json().get("coins", [])[:10]
                    if not found:
                        return ToolResult(content=f"No coin matched '{q}'.")
                    lines = [f"Search '{q}':"]
                    for c in found:
                        lines.append(
                            f"  {c.get('name')} ({c.get('symbol', '').upper()}) — id: {c.get('id')}"
                        )
                    return ToolResult(
                        content="\n".join(lines), metadata={"results": found}
                    )

                # price + ohlc both need coin_id
                coin = (arguments.get("coin_id") or "").strip().lower()
                if not coin:
                    return ToolResult(
                        content="coin_id is required for this operation", is_error=True
                    )
                vs = arguments.get("vs_currency", "usd").lower()

                if op == "price":
                    r = await client.get(
                        f"{_BASE}/coins/markets",
                        params={"vs_currency": vs, "ids": coin},
                    )
                    r.raise_for_status()
                    rows = r.json() or []
                    if not rows:
                        return ToolResult(
                            content=f"No market data for {coin}", is_error=True
                        )
                    m = rows[0]
                    return ToolResult(
                        content=(
                            f"{m.get('name')} ({m.get('symbol', '').upper()}) — {vs.upper()}\n"
                            f"  Price:        {m.get('current_price'):,}\n"
                            f"  24h change:   {m.get('price_change_percentage_24h', 0):+.2f}%\n"
                            f"  Market cap:   {m.get('market_cap'):,}\n"
                            f"  24h volume:   {m.get('total_volume'):,}\n"
                            f"  Rank:         {m.get('market_cap_rank')}\n"
                            f"  ATH:          {m.get('ath'):,} ({m.get('ath_change_percentage', 0):+.1f}% from ATH)"
                        ),
                        metadata=m,
                    )

                if op == "ohlc":
                    days = int(arguments.get("days", 7))
                    r = await client.get(
                        f"{_BASE}/coins/{coin}/ohlc",
                        params={"vs_currency": vs, "days": days},
                    )
                    r.raise_for_status()
                    points = r.json() or []
                    if not points:
                        return ToolResult(
                            content=f"No OHLC for {coin}/{vs} over {days}d",
                            is_error=True,
                        )
                    lines = [
                        f"OHLC — {coin} / {vs.upper()} — last {days}d ({len(points)} candles)",
                        "  ts                  open       high       low        close",
                    ]
                    import datetime as _dt

                    for ts, o, h, lo, c in points[-12:]:
                        d = _dt.datetime.fromtimestamp(ts / 1000, tz=_dt.timezone.utc)
                        lines.append(
                            f"  {d:%Y-%m-%d %H:%M}  {o:>9.4f}  {h:>9.4f}  {lo:>9.4f}  {c:>9.4f}"
                        )
                    return ToolResult(
                        content="\n".join(lines),
                        metadata={
                            "coin": coin,
                            "vs": vs,
                            "days": days,
                            "candles": points,
                        },
                    )

            return ToolResult(content=f"Unknown operation: {op}", is_error=True)
        except httpx.HTTPStatusError as e:
            body = e.response.text[:200]
            return ToolResult(
                content=f"CoinGecko HTTP {e.response.status_code}: {body}",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(content=f"CoinGecko error: {e}", is_error=True)
