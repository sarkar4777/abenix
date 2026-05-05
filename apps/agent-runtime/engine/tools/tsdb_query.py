"""TSDB query — read time-series points from TimescaleDB.

Connects to TSDB_URL (postgresql://...). Supports a small set of
aggregations to keep the LLM-facing surface narrow:
  - none    → raw points
  - avg_5m  → 5-minute averages (uses time_bucket if hypertable exists, falls
              back to date_trunc otherwise so plain Postgres works too)
  - max_1h  → 1-hour maxima
  - last    → most-recent value only

Schema convention: rows live in a `metrics` table with columns
(ts timestamptz, asset_id text, metric text, value double precision).
Different schemas can be supported via the optional `table` arg.
"""

from __future__ import annotations

import json
import os
from typing import Any

from engine.tools.base import BaseTool, ToolResult

_AGGREGATIONS = ("none", "avg_5m", "max_1h", "last")


class TsdbQueryTool(BaseTool):
    name = "tsdb_query"
    description = (
        "Query the platform time-series store (TimescaleDB) for a metric over "
        "a time window. Supports raw rows or 5-min/1-hour aggregations. "
        "Connects via the TSDB_URL env var."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "metric": {
                "type": "string",
                "description": "Metric name (e.g. 'vibration_rms', 'temp_c').",
            },
            "asset_id": {
                "type": "string",
                "description": "Asset identifier — usually equipment tag.",
            },
            "since": {
                "type": "string",
                "description": "ISO-8601 lower bound, inclusive.",
            },
            "until": {
                "type": "string",
                "description": "ISO-8601 upper bound, exclusive. Defaults to now.",
            },
            "aggregation": {
                "type": "string",
                "enum": list(_AGGREGATIONS),
                "default": "none",
                "description": "Aggregation bucket — none returns raw points.",
            },
            "table": {
                "type": "string",
                "default": "metrics",
                "description": "Override target table name (defaults to 'metrics').",
            },
            "limit": {
                "type": "integer",
                "default": 1000,
                "description": "Maximum rows to return (caps at 10000).",
            },
        },
        "required": ["metric", "since"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "rows": {"type": "array"},
            "count": {"type": "integer"},
            "aggregation": {"type": "string"},
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        metric = (arguments.get("metric") or "").strip()
        if not metric:
            return ToolResult(content="metric is required", is_error=True)

        since = (arguments.get("since") or "").strip()
        if not since:
            return ToolResult(content="since is required", is_error=True)
        until = (arguments.get("until") or "").strip() or None
        asset_id = (arguments.get("asset_id") or "").strip() or None
        agg = (arguments.get("aggregation") or "none").strip()
        if agg not in _AGGREGATIONS:
            return ToolResult(
                content=f"aggregation must be one of {_AGGREGATIONS}",
                is_error=True,
            )

        table = (arguments.get("table") or "metrics").strip()
        # Cheap allow-list — only ASCII identifiers permitted to keep the
        # query string from becoming an injection surface.
        if not table.replace("_", "").isalnum():
            return ToolResult(content="invalid table name", is_error=True)

        limit = int(arguments.get("limit") or 1000)
        limit = max(1, min(limit, 10000))

        url = os.environ.get("TSDB_URL") or os.environ.get("TIMESCALE_URL") or ""
        if not url:
            return ToolResult(
                content=json.dumps(
                    {
                        "rows": [],
                        "count": 0,
                        "status": "not_configured",
                        "message": "TSDB_URL not set",
                    }
                ),
                is_error=True,
            )

        # Build SQL for each aggregation. Bind params keep user input out
        # of the query text.
        if agg == "none":
            sql = (
                f"SELECT ts, asset_id, metric, value FROM {table} "
                "WHERE metric = $1 AND ts >= $2::timestamptz "
            )
        elif agg == "last":
            sql = (
                f"SELECT ts, asset_id, metric, value FROM {table} "
                "WHERE metric = $1 AND ts >= $2::timestamptz "
            )
        elif agg == "avg_5m":
            sql = (
                "SELECT date_trunc('minute', ts) "
                "- (extract(minute from ts)::int %% 5) * INTERVAL '1 minute' AS ts, "
                "asset_id, metric, AVG(value)::float8 AS value "
                f"FROM {table} "
                "WHERE metric = $1 AND ts >= $2::timestamptz "
            )
        else:  # max_1h
            sql = (
                "SELECT date_trunc('hour', ts) AS ts, asset_id, metric, "
                "MAX(value)::float8 AS value "
                f"FROM {table} "
                "WHERE metric = $1 AND ts >= $2::timestamptz "
            )

        params: list[Any] = [metric, since]
        if until:
            sql += f"AND ts < ${len(params) + 1}::timestamptz "
            params.append(until)
        if asset_id:
            sql += f"AND asset_id = ${len(params) + 1} "
            params.append(asset_id)

        if agg in ("avg_5m", "max_1h"):
            sql += "GROUP BY 1, 2, 3 "

        if agg == "last":
            sql += "ORDER BY ts DESC LIMIT 1"
        else:
            sql += f"ORDER BY ts ASC LIMIT {limit}"

        try:
            import asyncpg
        except ImportError:
            return ToolResult(content="asyncpg not installed", is_error=True)

        # asyncpg wants a plain postgresql:// URL; strip a +asyncpg
        # suffix if a SQLAlchemy-shaped URL was provided.
        clean_url = url.replace("postgresql+asyncpg://", "postgresql://")

        try:
            conn = await asyncpg.connect(clean_url, timeout=10)
            try:
                records = await conn.fetch(sql, *params)
            finally:
                await conn.close()
        except Exception as e:
            return ToolResult(content=f"tsdb_query failed: {e}", is_error=True)

        rows: list[dict[str, Any]] = []
        for r in records:
            d = dict(r)
            ts = d.get("ts")
            if ts is not None and hasattr(ts, "isoformat"):
                d["ts"] = ts.isoformat()
            v = d.get("value")
            if v is not None:
                d["value"] = float(v)
            rows.append(d)

        return ToolResult(
            content=json.dumps({"rows": rows, "count": len(rows), "aggregation": agg}),
            metadata={"count": len(rows), "aggregation": agg, "metric": metric},
        )
