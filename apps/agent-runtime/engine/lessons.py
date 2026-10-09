"""Lesson capture from the runtime: fire and forget, a lesson store that is down never touches a run.

Shared helpers here (masking, keys, caps) are used by the API's lessons service too,
so a lesson reads the same whichever side captured it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

TEXT_CAP = 8000
NOTE_CAP = 4000
KEY_CAP = 200
# beyond this many writes in flight new captures are dropped, never queued behind a slow database
MAX_IN_FLIGHT = 200
DLP_TTL = 60.0
OFF_SECONDS = 60.0

SECRET_PATTERNS = (
    "aws_access_key",
    "aws_secret_key",
    "generic_api_key",
    "bearer_token",
)

_tasks: set[asyncio.Task] = set()
_pools: dict[int, Any] = {}
_dlp_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_off_until = 0.0
_warned: set[str] = set()
_writer: Callable[[dict[str, Any]], Awaitable[None]] | None = None
dropped = 0


def configure(*, writer: Callable[[dict[str, Any]], Awaitable[None]] | None) -> None:
    """Swap the database writer, for tests."""
    global _writer, _off_until, dropped
    _writer = writer
    _off_until = 0.0
    dropped = 0


def _warn_once(key: str, msg: str, *args: Any) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(msg, *args)


def clip(text: Any, cap: int = TEXT_CAP) -> str:
    s = "" if text is None else str(text)
    return s if len(s) <= cap else s[: cap - 1] + "…"


def mask_text(text: Any, dlp: dict[str, Any] | None = None) -> str:
    """Secrets are always masked. Personal data too when the tenant's DLP mode masks or blocks."""
    s = "" if text is None else str(text)
    if not s:
        return s
    try:
        from engine.dlp import PII_PATTERNS, DLPPolicy, scan_text
    except Exception:  # noqa: BLE001
        return s
    dlp = dlp or {}
    full = bool(dlp.get("enabled", True)) and dlp.get("mode") in ("mask", "block")
    if full:
        patterns = list(PII_PATTERNS)
        custom = dlp.get("custom_patterns") or {}
    else:
        patterns = list(SECRET_PATTERNS)
        custom = {}
    try:
        return scan_text(
            s,
            DLPPolicy(
                mode="mask",
                enabled_patterns=patterns,
                custom_patterns=custom if isinstance(custom, dict) else {},
            ),
        ).masked_text
    except Exception:  # noqa: BLE001
        return s


def capture_key(*parts: Any) -> str:
    return ":".join(str(p) for p in parts if p not in (None, ""))[:KEY_CAP]


def polarity_for(source: str) -> str:
    return "positive" if source == "positive" else "negative"


def row(
    *,
    tenant_id: Any,
    agent_id: Any,
    source: str,
    input_text: Any = "",
    output_text: Any = "",
    expected: Any = None,
    note: Any = None,
    execution_id: Any = None,
    failure_code: str | None = None,
    tool_name: str | None = None,
    key: str | None = None,
    by_user: Any = None,
    agent_config_hash: str | None = None,
    meta: dict[str, Any] | None = None,
    dlp: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The lesson row, masked and capped. Pure, so both sides build the same thing."""
    return {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "agent_config_hash": agent_config_hash,
        "execution_id": execution_id,
        "source": source,
        "polarity": polarity_for(source),
        "input_text": clip(mask_text(input_text, dlp)),
        "output_text": clip(mask_text(output_text, dlp)),
        "expected": clip(mask_text(expected, dlp)) if expected else None,
        "note": clip(mask_text(note, dlp), NOTE_CAP) if note else None,
        "failure_code": (failure_code or None) and str(failure_code)[:64],
        "tool_name": (tool_name or None) and str(tool_name)[:160],
        "capture_key": key[:KEY_CAP] if key else None,
        "by_user": by_user,
        "meta": meta or {},
    }


def _uuid(v: Any) -> uuid.UUID | None:
    if not v:
        return None
    try:
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    except (ValueError, AttributeError, TypeError):
        return None


def _connect_kwargs() -> tuple[str, dict[str, Any]]:
    from engine.credentials import _db_url

    url, ssl = _db_url()
    kwargs: dict[str, Any] = {}
    if ssl:
        kwargs["ssl"] = "require" if ssl in ("true", "1", "require") else ssl
    return url, kwargs


async def _pool() -> Any:
    loop_id = id(asyncio.get_running_loop())
    pool = _pools.get(loop_id)
    if pool is None:
        url, kwargs = _connect_kwargs()
        if not url:
            return None
        import asyncpg

        pool = await asyncpg.create_pool(
            url, min_size=0, max_size=2, timeout=3, **kwargs
        )
        _pools[loop_id] = pool
    return pool


async def _tenant_dlp(conn: Any, tenant_id: Any) -> dict[str, Any] | None:
    key = str(tenant_id)
    hit = _dlp_cache.get(key)
    if hit and time.monotonic() - hit[0] < DLP_TTL:
        return hit[1]
    raw = await conn.fetchval(
        "SELECT settings->'dlp' FROM tenants WHERE id = $1", _uuid(tenant_id)
    )
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    dlp = raw if isinstance(raw, dict) else None
    _dlp_cache[key] = (time.monotonic(), dlp)
    return dlp


INSERT_SQL = (
    "INSERT INTO lessons (id, tenant_id, agent_id, agent_config_hash, execution_id, "
    "source, polarity, input_text, output_text, expected, note, failure_code, tool_name, "
    "capture_key, by_user, meta, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, "
    "$10, $11, $12, $13, $14, $15, $16::jsonb, now()) "
    "ON CONFLICT (source, capture_key) DO NOTHING RETURNING id"
)


async def _db_write(fields: dict[str, Any]) -> None:
    pool = await _pool()
    if pool is None:
        _warn_once("no_db", "DATABASE_URL is not set, lessons are not captured")
        return
    async with pool.acquire() as conn:
        dlp = await _tenant_dlp(conn, fields["tenant_id"])
        r = row(**fields, dlp=dlp)
        async with conn.transaction():
            new_id = await conn.fetchval(
                INSERT_SQL,
                r["id"],
                _uuid(r["tenant_id"]),
                _uuid(r["agent_id"]),
                r["agent_config_hash"],
                _uuid(r["execution_id"]),
                r["source"],
                r["polarity"],
                r["input_text"],
                r["output_text"],
                r["expected"],
                r["note"],
                r["failure_code"],
                r["tool_name"],
                r["capture_key"],
                _uuid(r["by_user"]),
                json.dumps(r["meta"], default=str),
            )
            if new_id is not None:
                _count(r["source"])
                await conn.execute(
                    "INSERT INTO event_outbox (tenant_id, event_type, payload) "
                    "VALUES ($1, 'lesson.captured', $2::jsonb)",
                    _uuid(r["tenant_id"]),
                    json.dumps(
                        {
                            "lesson_id": str(new_id),
                            "agent_id": str(r["agent_id"]),
                            "source": r["source"],
                            "polarity": r["polarity"],
                            "execution_id": (
                                str(r["execution_id"]) if r["execution_id"] else None
                            ),
                        }
                    ),
                )


def _count(source: str) -> None:
    # the API's counter, absent in the slim runtime image
    try:
        from app.core import telemetry

        telemetry.improvement_lessons_captured_total.labels(source=source).inc()
    except Exception:  # noqa: BLE001
        pass


async def _write(fields: dict[str, Any]) -> None:
    global _off_until
    try:
        if _writer is not None:
            await _writer(fields)
        else:
            await asyncio.wait_for(_db_write(fields), 10)
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if "does not exist" in text:
            _warn_once(
                "missing",
                "lessons table is not ready (%s), capture is skipped for now",
                text[:200],
            )
        else:
            _warn_once(
                f"write:{type(exc).__name__}", "lesson capture failed: %s", text[:300]
            )
        # one failure pauses capture briefly so a dead database costs nothing per run
        _off_until = time.monotonic() + OFF_SECONDS


def capture(**fields: Any) -> asyncio.Task | None:
    """Queue a lesson write behind the caller. Returns at once and never raises."""
    global dropped
    try:
        if time.monotonic() < _off_until:
            return None
        if not fields.get("tenant_id") or not fields.get("agent_id"):
            return None
        if len(_tasks) >= MAX_IN_FLIGHT:
            dropped += 1
            return None
        task = asyncio.get_running_loop().create_task(_write(fields))
    except Exception:  # noqa: BLE001
        return None
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def capture_run_failed(
    *,
    tenant_id: Any,
    agent_id: Any,
    execution_id: Any,
    input_text: Any = "",
    output_text: Any = "",
    error: Any = None,
    failure_code: str | None = None,
) -> asyncio.Task | None:
    return capture(
        tenant_id=tenant_id,
        agent_id=agent_id,
        source="run_failed",
        execution_id=execution_id,
        input_text=input_text,
        output_text=output_text or error or "",
        note=error,
        failure_code=failure_code,
        key=capture_key(execution_id),
    )


async def flush() -> None:
    """Wait for pending writes. For tests and shutdown."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
