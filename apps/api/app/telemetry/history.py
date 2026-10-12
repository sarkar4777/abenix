"""Telemetry history in TimescaleDB: schema, batched COPY writes and bucketed reads."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

TABLE = "telemetry_samples"
COLUMNS = ("time", "tenant_id", "grp", "node", "device", "metric", "num", "txt")
SCHEMA_VERSION = "tel258-1"

SCHEMA_SQL = (
    "CREATE EXTENSION IF NOT EXISTS timescaledb",
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        time      timestamptz      NOT NULL,
        tenant_id uuid             NOT NULL,
        grp       text             NOT NULL,
        node      text             NOT NULL,
        device    text             NOT NULL DEFAULT '',
        metric    text             NOT NULL,
        num       double precision,
        txt       text
    )""",
    f"""SELECT create_hypertable('{TABLE}', 'time',
        chunk_time_interval => INTERVAL '6 hours', if_not_exists => TRUE)""",
    f"""CREATE INDEX IF NOT EXISTS ix_{TABLE}_series
        ON {TABLE} (tenant_id, grp, node, device, metric, time DESC)""",
)

AGGREGATES = (
    ("telemetry_samples_1m", "1 minute", "3 hours", "1 minute", "1 minute", 30),
    ("telemetry_samples_1h", "1 hour", "3 days", "1 hour", "30 minutes", 365),
)


def dsn() -> str:
    url = os.environ.get("TSDB_URL") or os.environ.get("TSDB_DSN") or ""
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def create_pool(min_size: int = 1, max_size: int = 4) -> Any:
    import asyncpg

    url = dsn()
    if not url:
        raise RuntimeError("TSDB_URL is not set")
    return await asyncpg.create_pool(
        url, min_size=min_size, max_size=max_size, command_timeout=30
    )


async def ensure_schema(pool: Any, retention_days: int) -> None:
    """Idempotent: table, hypertable, compression after a day, 1 min and 1 h aggregates, retention."""
    async with pool.acquire() as c:
        for stmt in SCHEMA_SQL:
            await c.execute(stmt)
        compressed = await c.fetchval(
            "SELECT compression_enabled FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = $1",
            TABLE,
        )
        if not compressed:
            await c.execute(
                f"""ALTER TABLE {TABLE} SET (
                    timescaledb.compress,
                    timescaledb.compress_segmentby = 'tenant_id, grp, node, device, metric',
                    timescaledb.compress_orderby = 'time DESC')"""
            )
        await c.execute(
            f"SELECT add_compression_policy('{TABLE}', INTERVAL '1 day', if_not_exists => TRUE)"
        )
        for view, bucket, start, end, every, keep_days in AGGREGATES:
            exists = await c.fetchval(
                "SELECT 1 FROM timescaledb_information.continuous_aggregates "
                "WHERE view_name = $1",
                view,
            )
            if not exists:
                await c.execute(
                    f"""CREATE MATERIALIZED VIEW {view}
                        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
                        SELECT time_bucket(INTERVAL '{bucket}', time) AS bucket,
                               tenant_id, grp, node, device, metric,
                               avg(num) AS avg, min(num) AS min, max(num) AS max,
                               count(*) AS n
                        FROM {TABLE}
                        GROUP BY bucket, tenant_id, grp, node, device, metric
                        WITH NO DATA"""
                )
            await c.execute(
                f"""SELECT add_continuous_aggregate_policy('{view}',
                    start_offset => INTERVAL '{start}', end_offset => INTERVAL '{end}',
                    schedule_interval => INTERVAL '{every}', if_not_exists => TRUE)"""
            )
            await c.execute(
                f"SELECT add_retention_policy('{view}', INTERVAL '{keep_days} days', if_not_exists => TRUE)"
            )
        await set_retention(c, retention_days)


async def set_retention(c: Any, days: int) -> None:
    """The raw table keeps the longest workspace retention, shorter ones are deleted per workspace."""
    days = max(1, int(days))
    current = await c.fetchval(
        "SELECT (config->>'drop_after') FROM timescaledb_information.jobs "
        "WHERE proc_name = 'policy_retention' AND hypertable_name = $1",
        TABLE,
    )
    want = f"{days} days"
    if current == want:
        return
    if current:
        await c.execute(f"SELECT remove_retention_policy('{TABLE}', if_exists => TRUE)")
    await c.execute(f"SELECT add_retention_policy('{TABLE}', INTERVAL '{days} days')")


async def prune_tenant(pool: Any, tenant_id: str, days: int) -> int:
    async with pool.acquire() as c:
        r = await c.execute(
            f"DELETE FROM {TABLE} WHERE tenant_id = $1 AND time < now() - make_interval(days => $2)",
            tenant_id,
            int(days),
        )
    try:
        return int(str(r).split()[-1])
    except (ValueError, IndexError):
        return 0


def to_records(rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """(ts_ms, tenant, grp, node, device, metric, num, txt) to COPY records."""
    import uuid as _uuid

    out = []
    for ts, t, g, n, d, m, num, txt in rows:
        out.append(
            (
                datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc),
                _uuid.UUID(str(t)),
                g,
                n,
                d,
                m,
                num,
                txt,
            )
        )
    return out


async def write(pool: Any, rows: list[tuple[Any, ...]]) -> int:
    if not rows:
        return 0
    async with pool.acquire() as c:
        await c.copy_records_to_table(TABLE, records=to_records(rows), columns=COLUMNS)
    return len(rows)


STEPS = {
    "1s": 1,
    "5s": 5,
    "10s": 10,
    "30s": 30,
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}


def parse_step(step: str | None, span_s: float) -> int:
    """A bucket size in seconds. Empty picks one that gives about 300 points."""
    if step:
        s = step.strip().lower()
        if s in STEPS:
            return STEPS[s]
        try:
            if s.endswith("ms"):
                return max(1, int(float(s[:-2]) / 1000))
            if s[-1] in "smhd":
                return max(
                    1,
                    int(
                        float(s[:-1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[s[-1]]
                    ),
                )
            return max(1, int(float(s)))
        except (ValueError, KeyError):
            raise ValueError(
                "step must look like 10s, 1m, 1h or a number of seconds"
            ) from None
    target = max(1.0, span_s / 300.0)
    for v in sorted(STEPS.values()):
        if v >= target:
            return v
    return STEPS["1d"]


def pick_source(step_s: int, span_s: float) -> str:
    """Raw rows for short ranges and fine steps, the 1 min or 1 h aggregate past that."""
    if step_s >= 3600 or span_s > 14 * 86400:
        return "telemetry_samples_1h"
    if step_s >= 60 or span_s > 6 * 3600:
        return "telemetry_samples_1m"
    return TABLE


def parse_time(v: Any, default: datetime) -> datetime:
    if v in (None, ""):
        return default
    if isinstance(v, (int, float)) or (
        isinstance(v, str) and v.strip().lstrip("-").isdigit()
    ):
        f = float(v)
        return datetime.fromtimestamp(f / 1000.0 if f > 1e11 else f, tz=timezone.utc)
    s = str(v).strip()
    if s.startswith("-") or s.startswith("now"):
        # relative, such as -15m or now-1h
        rel = s.replace("now", "").strip() or "0s"
        sign = -1 if rel.startswith("-") else 1
        rel = rel.lstrip("+-")
        secs = parse_step(rel, 0)
        return datetime.now(timezone.utc) + timedelta(seconds=sign * secs)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(
            "from and to must be ISO 8601 times, epoch milliseconds or relative like -1h"
        ) from None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def query(
    pool: Any,
    tenant_id: str,
    grp: str,
    node: str,
    device: str,
    metrics: list[str],
    frm: datetime,
    to: datetime,
    step_s: int,
) -> dict[str, Any]:
    span = max(1.0, (to - frm).total_seconds())
    source = pick_source(step_s, span)
    if source == TABLE:
        sql = f"""SELECT metric, time_bucket(make_interval(secs => $7), time) AS b,
                     avg(num) AS avg, min(num) AS min, max(num) AS max, count(*) AS n,
                     last(txt, time) AS txt
                  FROM {TABLE}
                  WHERE tenant_id = $1 AND grp = $2 AND node = $3 AND device = $4
                    AND metric = ANY($5::text[]) AND time >= $6 AND time < $8
                  GROUP BY metric, b ORDER BY metric, b"""
    else:
        sql = f"""SELECT metric, time_bucket(make_interval(secs => $7), bucket) AS b,
                     sum(avg * n) / NULLIF(sum(n) FILTER (WHERE avg IS NOT NULL), 0) AS avg,
                     min(min) AS min, max(max) AS max, sum(n)::bigint AS n,
                     NULL::text AS txt
                  FROM {source}
                  WHERE tenant_id = $1 AND grp = $2 AND node = $3 AND device = $4
                    AND metric = ANY($5::text[]) AND bucket >= $6 AND bucket < $8
                  GROUP BY metric, b ORDER BY metric, b"""
    import uuid as _uuid

    async with pool.acquire() as c:
        rows = await c.fetch(
            sql,
            _uuid.UUID(str(tenant_id)),
            grp,
            node,
            device,
            metrics,
            frm,
            float(step_s),
            to,
        )
    series: dict[str, list[dict[str, Any]]] = {m: [] for m in metrics}
    for r in rows:
        series.setdefault(r["metric"], []).append(
            {
                "t": int(r["b"].timestamp() * 1000),
                "avg": r["avg"],
                "min": r["min"],
                "max": r["max"],
                "n": int(r["n"] or 0),
                **({"txt": r["txt"]} if r["txt"] is not None else {}),
            }
        )
    return {
        "source": {
            TABLE: "raw",
            "telemetry_samples_1m": "1m",
            "telemetry_samples_1h": "1h",
        }[source],
        "step_seconds": step_s,
        "from": frm.isoformat(),
        "to": to.isoformat(),
        "series": [{"metric": m, "points": pts} for m, pts in series.items()],
    }


async def metrics_for(
    pool: Any, tenant_id: str, grp: str, node: str, device: str
) -> list[str]:
    import uuid as _uuid

    async with pool.acquire() as c:
        rows = await c.fetch(
            f"""SELECT DISTINCT metric FROM {TABLE}
                WHERE tenant_id = $1 AND grp = $2 AND node = $3 AND device = $4
                  AND time > now() - INTERVAL '1 day' AND num IS NOT NULL""",
            _uuid.UUID(str(tenant_id)),
            grp,
            node,
            device,
        )
    return sorted(r["metric"] for r in rows)
