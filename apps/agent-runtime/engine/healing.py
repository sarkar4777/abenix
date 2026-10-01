"""Self-healing pipelines — failure-diff capture + surgeon-prompt builder."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
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


def _redact_text(text: str) -> str:
    """Mask PII with the shared DLP patterns, regex fallback if unavailable."""
    if not text:
        return text
    try:
        from engine.dlp import scan_text

        return scan_text(text).masked_text
    except Exception:
        pass
    out = _FALLBACK_EMAIL.sub("[EMAIL_MASKED]", text)
    out = _FALLBACK_CARD.sub("[CARD_MASKED]", out)
    return _FALLBACK_PHONE.sub("[PHONE_MASKED]", out)


_FALLBACK_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_FALLBACK_PHONE = re.compile(
    r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
)
_FALLBACK_CARD = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")


def redact_sample(value: Any, depth: int = 0) -> Any:
    """Walk a JSON-ish value and mask PII in every string leaf and key."""
    if depth > 12:
        return value
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {
            (_redact_text(k) if isinstance(k, str) else k): redact_sample(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_sample(v, depth + 1) for v in value]
    return value


async def _count_recent(
    conn: Any, pipeline_id: UUID, status: str, since: datetime
) -> int:
    # The enum column stores member names, so compare case-insensitively.
    row = await conn.fetchrow(
        "SELECT COUNT(*) AS c FROM executions "
        "WHERE agent_id = $1 AND LOWER(status::text) = LOWER($2) "
        "AND created_at >= $3",
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
    exc: BaseException | None = None,
) -> str | None:
    """Persist a `pipeline_run_diff` row and return its UUID, or None on error.

    `last_success_sample` feeds expected_shape/expected_sample. `exc` fills
    error_traceback when the caller has the exception but no formatted text.
    Samples, inputs, message and traceback are DLP-redacted before insert.
    Best-effort.  Failures are logged and swallowed.
    """
    if not db_url:
        return None
    if error_traceback is None and exc is not None:
        error_traceback = safe_traceback(exc)
    error_message = _redact_text(error_message or "")
    error_traceback = _redact_text(error_traceback) if error_traceback else None
    observed_sample = redact_sample(observed_sample)
    last_success_sample = redact_sample(last_success_sample)
    upstream_inputs = redact_sample(upstream_inputs)
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
              recent_success_count, recent_failure_count,
              -- created_at is NOT NULL. The alembic migration gives it
              -- DEFAULT now(), but a schema built by
              -- Base.metadata.create_all() does not, so omitting it made
              -- every insert fail with "null value in column created_at".
              -- fire_and_forget swallowed it, so Pipeline Surgeon silently
              -- never had a diff to diagnose. `id` is the same story: this
              -- is a raw asyncpg insert, so the ORM's UUID default never
              -- runs and create_all left the column without a server
              -- default. Set both explicitly.
              created_at, id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
                    NOW(), gen_random_uuid())
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


# Strong references to in-flight fire-and-forget tasks. asyncio keeps only a
# weak reference to a Task, so a bare `loop.create_task(coro)` whose result is
# discarded can be garbage-collected before it ever runs — which is why
# healing capture silently never wrote a row. Hold the task until it finishes.
_INFLIGHT: set[asyncio.Task[Any]] = set()


def fire_and_forget(coro: Any) -> None:
    """Schedule an awaitable on the running loop without blocking.

    Used to make healing capture truly non-blocking from the executor.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — best-effort drop on the floor.
        try:
            coro.close()
        except Exception:
            pass
        return

    task = loop.create_task(coro)
    _INFLIGHT.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _INFLIGHT.discard(t)
        # Surface failures instead of letting them vanish into a dropped task.
        if not t.cancelled():
            exc = t.exception()
            if exc is not None:
                logger.warning("fire_and_forget task failed: %s", exc)

    task.add_done_callback(_done)


# Last good output per pipeline node, so a failure diff carries an expected_sample.
_SUCCESS_TTL_SECONDS = 7 * 24 * 3600
_SUCCESS_SAMPLE_BYTES = 4_096
_SUCCESS_FALLBACK_MAX = 2_048
_success_fallback: dict[str, tuple[float, str]] = {}
_redis_pool: Any = None

# error_type carries a category for tool/timeout/validation failures, else the raising class name
_RESULT_ERROR_KINDS = frozenset(
    {"timeout", "tool_error", "llm_error", "validation", "PipelineError"}
)


def _success_key(pipeline_id: str, node_id: str) -> str:
    return f"healing:last_success:{pipeline_id}:{node_id}"


async def _get_redis() -> Any:
    global _redis_pool
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return None
    if _redis_pool is None:
        try:
            import redis.asyncio as aioredis

            _redis_pool = aioredis.from_url(
                url, decode_responses=True, socket_connect_timeout=2.0
            )
        except Exception as e:
            logger.debug("healing: redis unavailable: %s", e)
            return None
    return _redis_pool


def _fallback_get(key: str) -> str | None:
    hit = _success_fallback.get(key)
    if hit is None:
        return None
    expires_at, payload = hit
    if expires_at < time.monotonic():
        _success_fallback.pop(key, None)
        return None
    return payload


def _fallback_set(key: str, payload: str) -> None:
    now = time.monotonic()
    if len(_success_fallback) >= _SUCCESS_FALLBACK_MAX:
        for k in [k for k, (exp, _) in _success_fallback.items() if exp < now]:
            _success_fallback.pop(k, None)
        while len(_success_fallback) >= _SUCCESS_FALLBACK_MAX:
            _success_fallback.pop(next(iter(_success_fallback)), None)
    _success_fallback[key] = (now + _SUCCESS_TTL_SECONDS, payload)


def success_sample(output: Any) -> Any:
    """Redacted copy of a node output, capped at 4 KB."""
    return _truncate_json(redact_sample(output), _SUCCESS_SAMPLE_BYTES)


async def remember_success(pipeline_id: str, node_id: str, output: Any) -> None:
    """Store a node's latest good output for 7 days. Redis first, process dict otherwise."""
    if not pipeline_id or not node_id or output is None:
        return
    key = _success_key(pipeline_id, node_id)
    try:
        payload = json.dumps(success_sample(output), default=str)
    except Exception as e:
        logger.debug("healing: sample not serialisable: %s", e)
        return
    r = await _get_redis()
    if r is not None:
        try:
            await r.set(key, payload, ex=_SUCCESS_TTL_SECONDS)
            return
        except Exception as e:
            logger.debug("healing: redis set failed, using process store: %s", e)
    _fallback_set(key, payload)


async def last_success(pipeline_id: str, node_id: str) -> Any | None:
    if not pipeline_id or not node_id:
        return None
    key = _success_key(pipeline_id, node_id)
    payload: str | None = None
    r = await _get_redis()
    if r is not None:
        try:
            payload = await r.get(key)
        except Exception as e:
            logger.debug("healing: redis get failed, using process store: %s", e)
    if payload is None:
        payload = _fallback_get(key)
    if payload is None:
        return None
    try:
        return json.loads(payload)
    except Exception:
        return None


def exception_from_result(
    error_type: str | None, error_message: str | None
) -> BaseException | None:
    """Rebuild the node's exception from the class name the executor kept.

    The executor swallows the original object, so this is only ever
    formatted into a traceback header, never raised.
    """
    if not error_type or error_type in _RESULT_ERROR_KINDS:
        return None
    import builtins

    cls = getattr(builtins, error_type, None)
    if not (isinstance(cls, type) and issubclass(cls, BaseException)):
        cls = type(error_type, (Exception,), {"__module__": "builtins"})
    try:
        return cls(error_message or "")
    except Exception:
        return Exception(error_message or "")


async def capture_node_failure(
    *,
    pipeline_id: str,
    node_id: str,
    error_type: str | None,
    error_message: str,
    **kwargs: Any,
) -> str | None:
    """capture_failure fed with the node's last good output and a traceback.

    A raised exception is rebuilt and passed as `exc`, a tool-reported
    error goes in as the traceback text.
    """
    sample = await last_success(pipeline_id, node_id)
    # a real traceback from the executor beats a rebuilt exception
    real_tb = kwargs.pop("error_traceback", None)
    exc = None if real_tb else exception_from_result(error_type, error_message)
    return await capture_failure(
        pipeline_id=pipeline_id,
        node_id=node_id,
        error_class=error_type or "PipelineError",
        error_message=error_message,
        error_traceback=real_tb
        or (None if exc is not None else (error_message or None)),
        last_success_sample=sample,
        exc=exc,
        **kwargs,
    )
