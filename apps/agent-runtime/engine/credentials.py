"""Resolve the values a tool needs to run.

A tool declares what it needs as ``config_fields`` on its class and reads each
value through here instead of ``os.environ``. The order is

  1. an override set by a test,
  2. a ``platform_settings`` row ``tool.credential.<KEY>``, which an admin
     writes from Admin -> Tool Configuration,
  3. the process environment,
  4. ``packages/db/seeds/tool_defaults.yaml``,
  5. the default the tool declared,
  6. empty.

Reads are synchronous and only ever touch an in-memory snapshot, so a tool's
``execute`` never waits on the database. The snapshot is refreshed by
``ensure_fresh()`` at most once per TTL, single-flight, serving the previous
snapshot while a refresh is in progress. The runtime image ships asyncpg and
not psycopg2, and ``execute`` already runs on the event loop, so the refresh
uses asyncpg natively rather than a worker thread.

Without ``DATABASE_URL`` the resolver degrades to the environment and the
defaults file, and says so once.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

PREFIX = "tool.credential."
# Stored values are AES-GCM under the cluster KEK when one is set, see
# apps/api/app/core/tool_secrets.py. One fixed scope, there is no tenant.
PLATFORM_SCOPE = uuid.uuid5(uuid.NAMESPACE_URL, "abenix.platform.tool-credentials")
SOURCES = ("override", "stored", "env", "file", "default", "unset")

_ttl = 30.0
_snapshot: dict[str, str] = {}
_loaded_at = 0.0
_refreshing: asyncio.Lock | None = None
_overrides: dict[str, str] | None = None
_file_defaults: dict[str, str] | None = None
_loader: Callable[[], Awaitable[dict[str, str] | None]] | None = None
_warned_no_db = False


class ToolNeedsConfiguration(Exception):
    """Raised by ``get(..., required=True)`` when nothing provides the value.

    ``BaseTool`` turns this into one standard result for every tool, so the
    model always sees the same sentence and the same place to send an admin.
    """

    def __init__(self, key: str, *, signup_url: str = "", label: str = "") -> None:
        super().__init__(key)
        self.key = key
        self.signup_url = signup_url
        self.label = label


def configure(
    *,
    loader: Callable[[], Awaitable[dict[str, str] | None]] | None = None,
    ttl: float | None = None,
) -> None:
    """Swap the database reader, for the API process or for tests.

    The loader returns ``{KEY: value}`` without the prefix, or ``None`` when
    the store is unreachable, in which case the previous snapshot stands.
    """
    global _loader, _ttl, _refreshing
    _loader = loader
    if ttl is not None:
        _ttl = float(ttl)
    # A fresh lock, so a test that ran on a previous event loop cannot leave
    # one behind that is bound to it.
    _refreshing = None
    invalidate()


def invalidate() -> None:
    """Force the next ``ensure_fresh`` to read."""
    global _loaded_at
    _loaded_at = 0.0


def snapshot_age() -> float:
    return time.monotonic() - _loaded_at if _loaded_at else float("inf")


def _kek() -> bytes:
    raw = os.environ.get("ABENIX_DATA_KEY_KEK_BASE64", "").strip()
    if not raw:
        return b""
    try:
        import base64

        kek = base64.b64decode(raw)
        return kek if len(kek) == 32 else b""
    except Exception:  # noqa: BLE001
        return b""


def decode_stored(value: str) -> str:
    """Reverse of tool_secrets.encode_for_storage. Mirrors app.core.crypto.decrypt."""
    if not value or not value.startswith("v") or ":" not in value:
        return value
    kek = _kek()
    if not kek:
        return value
    try:
        import base64
        import hashlib
        import hmac

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        _, blob = value.split(":", 1)
        raw = base64.b64decode(blob)
        dek = hmac.new(
            kek, str(PLATFORM_SCOPE).encode("utf-8"), hashlib.sha256
        ).digest()
        return AESGCM(dek).decrypt(raw[:12], raw[12:], None).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "tool configuration: stored value could not be decrypted (%s)",
            exc.__class__.__name__,
        )
        return ""


def _db_url() -> tuple[str, str | None]:
    """DATABASE_URL in the shape asyncpg takes, plus an ssl hint it had."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return "", None
    url = url.replace("postgresql+asyncpg", "postgresql").replace("+asyncpg", "")
    ssl: str | None = None
    if "?" in url:
        base, query = url.split("?", 1)
        kept = []
        for part in query.split("&"):
            k, _, v = part.partition("=")
            if k.lower() in ("ssl", "sslmode"):
                ssl = v or "require"
            else:
                kept.append(part)
        url = base + (("?" + "&".join(kept)) if kept else "")
    return url, ssl


async def _read_db() -> dict[str, str] | None:
    global _warned_no_db
    if _loader is not None:
        loaded = await _loader()
        return (
            None if loaded is None else {k: decode_stored(v) for k, v in loaded.items()}
        )
    url, ssl = _db_url()
    if not url:
        if not _warned_no_db:
            logger.warning(
                "DATABASE_URL is not set, tool configuration reads the "
                "environment and tool_defaults.yaml only"
            )
            _warned_no_db = True
        return None
    import asyncpg  # the runtime and the API both ship it

    kwargs: dict[str, Any] = {"timeout": 2}
    if ssl:
        kwargs["ssl"] = "require" if ssl in ("true", "1", "require") else ssl
    conn = await asyncpg.connect(url, **kwargs)
    try:
        rows = await conn.fetch(
            "SELECT key, value FROM platform_settings WHERE key LIKE $1",
            PREFIX + "%",
        )
    finally:
        await conn.close()
    return {
        str(r["key"])[len(PREFIX) :]: decode_stored(str(r["value"] or "")) for r in rows
    }


async def ensure_fresh(force: bool = False) -> None:
    """Refresh the snapshot if it is older than the TTL. Single-flight.

    A failed read keeps the previous snapshot and still advances the clock, so
    a sick database costs one attempt per TTL rather than one per tool call.
    """
    global _snapshot, _loaded_at, _refreshing
    if not force and snapshot_age() < _ttl:
        return
    if _refreshing is None:
        _refreshing = asyncio.Lock()
    if _refreshing.locked() and not force:
        return  # someone else is on it, serve the stale snapshot
    async with _refreshing:
        if not force and snapshot_age() < _ttl:
            return
        try:
            fresh = await _read_db()
        except (
            Exception
        ) as exc:  # noqa: BLE001 — never take a tool down on settings I/O
            logger.debug("tool configuration refresh failed: %s", exc)
            fresh = None
        if fresh is not None:
            _snapshot = fresh
        _loaded_at = time.monotonic()


def _defaults_file() -> Path:
    here = Path(__file__).resolve()
    # apps/agent-runtime/engine/credentials.py -> repo root is parents[3]
    candidates = [
        here.parents[3] / "packages" / "db" / "seeds" / "tool_defaults.yaml",
        Path("/app/packages/db/seeds/tool_defaults.yaml"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def file_defaults() -> dict[str, str]:
    """Values from tool_defaults.yaml, read once per process."""
    global _file_defaults
    if _file_defaults is not None:
        return _file_defaults
    out: dict[str, str] = {}
    fp = _defaults_file()
    if fp.exists():
        try:
            import yaml

            data = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                out = {str(k): "" if v is None else str(v) for k, v in data.items()}
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not read %s: %s", fp, exc)
    _file_defaults = out
    return out


def reset_file_defaults() -> None:
    global _file_defaults
    _file_defaults = None


def source(key: str, default: str | None = None) -> str:
    """Which layer currently provides ``key``. One of SOURCES."""
    if _overrides is not None and key in _overrides:
        return "override"
    if _snapshot.get(key):
        return "stored"
    if os.environ.get(key):
        return "env"
    if file_defaults().get(key):
        return "file"
    if default:
        return "default"
    return "unset"


def get(key: str, *, required: bool = False, default: str | None = None) -> str:
    """The value for ``key``, or raise when it is required and absent."""
    if _overrides is not None and key in _overrides:
        value = _overrides[key]
    else:
        value = (
            _snapshot.get(key)
            or os.environ.get(key, "")
            or file_defaults().get(key, "")
        )
        if not value and default is not None:
            value = default
    value = (value or "").strip()
    if required and not value:
        raise ToolNeedsConfiguration(key)
    return value


def stored_keys() -> dict[str, str]:
    """A copy of the stored layer, for the admin screen."""
    return dict(_snapshot)


@contextlib.contextmanager
def override(values: dict[str, str]):
    """Pin values for the duration of a test, above every other layer."""
    global _overrides
    previous = _overrides
    _overrides = {**(previous or {}), **values}
    try:
        yield
    finally:
        _overrides = previous
