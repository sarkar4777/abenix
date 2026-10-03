"""Admin settings for the runtime pod, which lacks the API settings module and its pydantic-settings dependency."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_TTL = 30.0
_cache: dict[str, tuple[str | None, float]] = {}


async def _read_row(key: str) -> str | None:
    from sqlalchemy import text

    from engine.decisions.db import session

    async with session() as db:
        row = (
            await db.execute(
                text("SELECT value FROM platform_settings WHERE key = :k"), {"k": key}
            )
        ).first()
    return None if row is None else row[0]


async def get_int_setting(key: str, fallback: int) -> int:
    try:
        from app.core.platform_settings import get_int_setting as api_get

        return await api_get(key, fallback)
    except ImportError:
        pass
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[1] < _TTL:
        raw = hit[0]
    else:
        try:
            raw = await _read_row(key)
        except Exception as e:
            logger.warning("runtime_setting_read_failed key=%s err=%s", key, e)
            return fallback
        _cache[key] = (raw, now)
    try:
        return int(str(raw).strip()) if raw not in (None, "") else fallback
    except ValueError:
        return fallback
