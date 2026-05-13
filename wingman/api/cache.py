"""File-backed result cache for the trader pages. Entries live in /data/wingman-cache/{page}/{key}.json."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

CACHE_ROOT = Path(os.environ.get("WINGMAN_CACHE_DIR", "/data/wingman-cache"))
DEFAULT_TTL_SECONDS = int(os.environ.get("WINGMAN_CACHE_TTL_SECONDS", "1800"))
RECENT_VISIT_WINDOW_SECONDS = int(os.environ.get("WINGMAN_VISIT_WINDOW_SECONDS", "3600"))

# Per-page TTL overrides (seconds). Ops AIS refreshes hourly; the rest 30 min.
_TTL_BY_PAGE: dict[str, int] = {
    "mispricing": 1800,
    "analyze": 1800,
    "scenarios": 1800,
    "ops": 3600,
    "market-brief": 300,
}

_SAFE_KEY_RX = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe(key: str) -> str:
    return _SAFE_KEY_RX.sub("_", (key or "").strip()) or "default"


def _entry_path(page: str, key: str) -> Path:
    return CACHE_ROOT / _safe(page) / f"{_safe(key)}.json"


def _visit_path(page: str) -> Path:
    return CACHE_ROOT / "_visits" / f"{_safe(page)}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _safe_read_json(path: Path) -> Any | None:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("cache read failed for %s: %s", path, e)
        return None


def write(page: str, key: str, payload: dict[str, Any]) -> None:
    entry = {"written_at": _now_iso(), "payload": payload}
    _atomic_write_json(_entry_path(page, key), entry)


def read(page: str, key: str) -> dict[str, Any] | None:
    entry = _safe_read_json(_entry_path(page, key))
    if not isinstance(entry, dict) or "payload" not in entry:
        return None
    written_at = _parse_iso(str(entry.get("written_at", "")))
    age = None
    if written_at is not None:
        age = max(0.0, (datetime.now(timezone.utc) - written_at).total_seconds())
    return {
        "payload": entry["payload"],
        "written_at": entry.get("written_at"),
        "age_seconds": age,
        "ttl_seconds": _TTL_BY_PAGE.get(page, DEFAULT_TTL_SECONDS),
        "fresh": (age is not None and age < _TTL_BY_PAGE.get(page, DEFAULT_TTL_SECONDS)),
    }


def list_keys(page: str) -> list[str]:
    p = CACHE_ROOT / _safe(page)
    if not p.exists():
        return []
    return sorted(
        f.stem
        for f in p.iterdir()
        if f.is_file() and f.suffix == ".json" and not f.name.startswith(".")
    )


def is_stale(page: str, key: str) -> bool:
    entry = read(page, key)
    if entry is None:
        return True
    return not entry["fresh"]


def mark_visit(page: str) -> None:
    _atomic_write_json(_visit_path(page), {"last_visit": _now_iso()})


def last_visit(page: str) -> datetime | None:
    obj = _safe_read_json(_visit_path(page))
    if not isinstance(obj, dict):
        return None
    return _parse_iso(str(obj.get("last_visit", "")))


def visited_recently(page: str) -> bool:
    lv = last_visit(page)
    if lv is None:
        return False
    age = (datetime.now(timezone.utc) - lv).total_seconds()
    return age < RECENT_VISIT_WINDOW_SECONDS


async def warm(
    page: str,
    keys: list[str],
    run: Callable[[str], Awaitable[dict[str, Any]]],
    *,
    require_recent_visit: bool = True,
    concurrency: int = 1,
) -> int:
    if require_recent_visit and not visited_recently(page):
        return 0

    stale = [k for k in keys if is_stale(page, k)]
    if not stale:
        return 0

    sem = asyncio.Semaphore(max(1, concurrency))
    refreshed = 0

    async def _one(k: str) -> None:
        nonlocal refreshed
        async with sem:
            try:
                payload = await run(k)
                write(page, k, payload)
                refreshed += 1
                logger.info("cache.warm %s/%s refreshed", page, k)
            except Exception as e:
                logger.warning("cache.warm %s/%s failed: %s", page, k, e)

    await asyncio.gather(*(_one(k) for k in stale))
    return refreshed
