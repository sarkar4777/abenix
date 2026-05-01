"""Self-healing pipelines — failure-diff capture + surgeon-prompt builder."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback as _tb
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse
from uuid import UUID

logger = logging.getLogger(__name__)

# Limits to keep stored payloads sane
_MAX_SAMPLE_BYTES = 8_192
_MAX_TRACEBACK_BYTES = 4_096
_MAX_INPUTS_BYTES = 4_096


def _to_asyncpg_dsn(url: str) -> tuple[str, dict[str, Any]]:
    """Strip ?sslmode= / ?ssl= query params and lift to asyncpg kwargs."""
    if not url:
        return url, {}
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://") :]
    parsed = urlparse(url)
    qs = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
    kwargs: dict[str, Any] = {}
    sslmode = qs.pop("sslmode", None) or qs.pop("ssl", None)
    if sslmode:
        kwargs["ssl"] = sslmode != "disable"
    clean = urlunparse(parsed._replace(query=""))
    return clean, kwargs


def _truncate_json(value: Any, limit: int) -> Any:
    """Round-trip through JSON, truncate stringified form, then return as
    either the original (if small enough) or a trimmed string."""
    if value is None:
        return None
    try:
        s = json.dumps(value, default=str)
    except Exception:
        s = repr(value)
    if len(s) <= limit:
        return value
    return {"_truncated": True, "_preview": s[:limit] + "...", "_orig_size": len(s)}


def _infer_shape(value: Any, depth: int = 0) -> Any:
    """Cheap, recursive shape signature.  Returns nested dicts/lists of
    type names so two outputs can be diff'd structurally."""
    if depth > 4:
        return "..."
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        if not value:
            return ["empty-list"]
        return [_infer_shape(value[0], depth + 1), f"len={len(value)}"]
    if isinstance(value, dict):
        return {k: _infer_shape(v, depth + 1) for k, v in list(value.items())[:24]}
    return type(value).__name__


async def _count_recent(
    conn: Any, pipeline_id: UUID, status: str, since: datetime
) -> int:
    row = await conn.fetchrow(
        "SELECT COUNT(*) AS c FROM executions "
        "WHERE agent_id = $1 AND status = $2 AND created_at >= $3",
        pipeline_id,
        status,
        since,
    )
    return int(row["c"]) if row else 0


async def capture_failure(
    *,
    db_url: str,
    tenant_id: str,
    pipeline_id: str,
    execution_id: str,
    node_id: str,
    node_kind: str,
    node_target: str | None,
    error_class: str,
    error_message: str,
    error_traceback: str | None,
    upstream_inputs: dict[str, Any] | None,
    observed_sample: Any | None,
    last_success_sample: Any | None = None,
) -> str | None:
    """Persist a `pipeline_run_diff` row and return its UUID, or None on error.

    Best-effort.  Failures are logged and swallowed.
    """
    if not db_url:
        return None
    try:
        import asyncpg
    except ImportError:
        logger.warning("asyncpg not available; skipping failure diff capture")
        return None

    try:
        clean, kwargs = _to_asyncpg_dsn(db_url)
        conn = await asyncpg.connect(clean, **kwargs)
    except Exception as e:
        logger.warning("healing.capture_failure: cannot connect: %s", e)
        return None

    try:
        # Telemetry over the past 24h
        since = datetime.now(timezone.utc) - timedelta(days=1)
        try:
            success_count = await _count_recent(
                conn, UUID(pipeline_id), "completed", since
            )
            failure_count = await _count_recent(
                conn, UUID(pipeline_id), "failed", since
            )
        except Exception:
            success_count = 0
            failure_count = 0

        observed_shape = (
            _infer_shape(observed_sample) if observed_sample is not None else None
        )
        expected_shape = (
            _infer_shape(last_success_sample)
            if last_success_sample is not None
            else None
        )

        row = await conn.fetchrow(
            """
            INSERT INTO pipeline_run_diffs (
              tenant_id, pipeline_id, execution_id,
              node_id, node_kind, node_target,
              error_class, error_message, error_traceback,
              expected_shape, observed_shape,
              expected_sample, observed_sample, upstream_inputs,
              recent_success_count, recent_failure_count
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            RETURNING id::text
            """,
            UUID(tenant_id),
            UUID(pipeline_id),
            UUID(execution_id),
            node_id[:255],
            node_kind[:64],
            (node_target or "")[:255] or None,
            (error_class or "Unknown")[:128],
            (error_message or "")[:8000],
            (error_traceback or "")[:_MAX_TRACEBACK_BYTES] if error_traceback else None,
            json.dumps(expected_shape) if expected_shape is not None else None,
            json.dumps(observed_shape) if observed_shape is not None else None,
            (
                json.dumps(_truncate_json(last_success_sample, _MAX_SAMPLE_BYTES))
                if last_success_sample is not None
                else None
            ),
            (
                json.dumps(_truncate_json(observed_sample, _MAX_SAMPLE_BYTES))
                if observed_sample is not None
                else None
            ),
            (
                json.dumps(_truncate_json(upstream_inputs, _MAX_INPUTS_BYTES))
                if upstream_inputs is not None
                else None
            ),
            success_count,
            failure_count,
        )
        return row["id"] if row else None
    except Exception as e:
        logger.warning("healing.capture_failure: insert failed: %s", e)
        return None
    finally:
        try:
            await conn.close()
        except Exception:
            pass


def safe_traceback(exc: BaseException | None) -> str | None:
    if exc is None:
        return None
    try:
        return "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        return None


def fire_and_forget(coro: Any) -> None:
    """Schedule an awaitable on the running loop without blocking.

    Used to make healing capture truly non-blocking from the executor.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        # No running loop — best-effort drop on the floor.
        try:
            coro.close()
        except Exception:
            pass
