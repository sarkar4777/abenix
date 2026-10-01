"""Resolve the values a tool needs to run.

A tool declares what it needs as ``config_fields`` on its class and reads each
value through here instead of ``os.environ``. The order is

  1. an override set by a test,
  2. a ``tenant_tool_credentials`` row for the current tenant, which a tenant
     admin writes from Admin -> Tool Configuration with the scope on
     "This tenant",
  3. a ``platform_settings`` row ``tool.credential.<KEY>``, which an admin
     writes from the same screen with the scope on "Platform",
  4. the process environment,
  5. ``packages/db/seeds/tool_defaults.yaml``,
  6. the default the tool declared,
  7. empty.

The current tenant is a ``contextvars.ContextVar`` set by the executor at run
start and by the consumer before it builds executors. ``BaseTool.cfg`` passes
the instance's own ``tenant_id`` when the variable is empty.

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
import contextvars
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

PREFIX = "tool.credential."
# Stored values are AES-GCM under the cluster KEK when one is set, see
# apps/api/app/core/tool_secrets.py. One fixed scope for platform and tenant rows.
PLATFORM_SCOPE = uuid.uuid5(uuid.NAMESPACE_URL, "abenix.platform.tool-credentials")
TENANT_TABLE = "tenant_tool_credentials"
SOURCES = ("override", "tenant", "stored", "env", "file", "default", "unset")

TenantLoader = Callable[[], Awaitable["dict[tuple[str, str], str] | None"]]

_ttl = 30.0
_snapshot: dict[str, str] = {}
_tenant_snapshot: dict[tuple[str, str], str] = {}
_loaded_at = 0.0
_refreshing: asyncio.Lock | None = None
_overrides: dict[str, str] | None = None
_file_defaults: dict[str, str] | None = None
_loader: Callable[[], Awaitable[dict[str, str] | None]] | None = None
_tenant_loader: TenantLoader | None = None
_warned_no_db = False
_warned_no_tenant_table = False

_tenant_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "abenix_tool_credentials_tenant", default=""
)


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


def set_tenant(tenant_id: Any) -> contextvars.Token[str]:
    """Pin the tenant whose rows resolve first for the rest of this context."""
    return _tenant_ctx.set(str(tenant_id or "").strip())


def reset_tenant(token: contextvars.Token[str]) -> None:
    _tenant_ctx.reset(token)


def current_tenant() -> str:
    return _tenant_ctx.get()


def configure(
    *,
    loader: Callable[[], Awaitable[dict[str, str] | None]] | None = None,
    tenant_loader: TenantLoader | None = None,
    ttl: float | None = None,
) -> None:
    """Swap the database readers, for the API process or for tests.

    ``loader`` returns ``{KEY: value}`` without the prefix. ``tenant_loader``
    returns ``{(tenant_id, KEY): value}``. Either returns ``None`` when the
    store is unreachable, in which case the previous snapshot stands.
    """
    global _loader, _tenant_loader, _ttl, _refreshing
    _loader = loader
    _tenant_loader = tenant_loader
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


def _decode_tenant_rows(
    rows: dict[tuple[str, str], str] | None,
) -> dict[tuple[str, str], str] | None:
    if rows is None:
        return None
    return {(str(t), str(k)): decode_stored(v) for (t, k), v in rows.items()}


async def _read_tenant_table(conn: Any) -> dict[tuple[str, str], str]:
    """The whole tenant table, it is small. Empty until the migration is in."""
    global _warned_no_tenant_table
    try:
        rows = await conn.fetch(f"SELECT tenant_id, key, value FROM {TENANT_TABLE}")
    except Exception as exc:  # noqa: BLE001
        if "does not exist" in str(exc) or "UndefinedTable" in exc.__class__.__name__:
            if not _warned_no_tenant_table:
                logger.warning(
                    "%s is not in the schema yet, tenant tool credentials are off "
                    "until the migration runs",
                    TENANT_TABLE,
                )
                _warned_no_tenant_table = True
            return {}
        raise
    return {
        (str(r["tenant_id"]), str(r["key"])): decode_stored(str(r["value"] or ""))
        for r in rows
    }


async def _read_db() -> tuple[dict[str, str] | None, dict[tuple[str, str], str] | None]:
    global _warned_no_db
    if _loader is not None or _tenant_loader is not None:
        loaded = await _loader() if _loader is not None else None
        platform = (
            None if loaded is None else {k: decode_stored(v) for k, v in loaded.items()}
        )
        tenants = (
            _decode_tenant_rows(await _tenant_loader())
            if _tenant_loader is not None
            else None
        )
        return platform, tenants
    url, ssl = _db_url()
    if not url:
        if not _warned_no_db:
            logger.warning(
                "DATABASE_URL is not set, tool configuration reads the "
                "environment and tool_defaults.yaml only"
            )
            _warned_no_db = True
        return None, None
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
        tenants = await _read_tenant_table(conn)
    finally:
        await conn.close()
    platform = {
        str(r["key"])[len(PREFIX) :]: decode_stored(str(r["value"] or "")) for r in rows
    }
    return platform, tenants


async def ensure_fresh(force: bool = False) -> None:
    """Refresh the snapshot if it is older than the TTL. Single-flight.

    A failed read keeps the previous snapshot and still advances the clock, so
    a sick database costs one attempt per TTL rather than one per tool call.
    """
    global _snapshot, _tenant_snapshot, _loaded_at, _refreshing
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
            fresh, fresh_tenants = await _read_db()
        except (
            Exception
        ) as exc:  # noqa: BLE001 — never take a tool down on settings I/O
            logger.debug("tool configuration refresh failed: %s", exc)
            fresh, fresh_tenants = None, None
        if fresh is not None:
            _snapshot = fresh
        if fresh_tenants is not None:
            _tenant_snapshot = fresh_tenants
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


def _tenant_for(tenant_id: str | None) -> str:
    # None means whoever the context says, "" means no tenant at all
    return current_tenant() if tenant_id is None else str(tenant_id).strip()


def tenant_value(key: str, tenant_id: str | None = None) -> str:
    """The tenant row alone, empty when there is none."""
    tenant = _tenant_for(tenant_id)
    if not tenant:
        return ""
    return _tenant_snapshot.get((tenant, key), "")


def source(key: str, default: str | None = None, tenant_id: str | None = None) -> str:
    """Which layer currently provides ``key``. One of SOURCES.

    ``tenant_id`` None reads the context, "" ignores tenant rows altogether.
    """
    if _overrides is not None and key in _overrides:
        return "override"
    if tenant_value(key, tenant_id):
        return "tenant"
    if _snapshot.get(key):
        return "stored"
    if os.environ.get(key):
        return "env"
    if file_defaults().get(key):
        return "file"
    if default:
        return "default"
    return "unset"


def get(
    key: str,
    *,
    required: bool = False,
    default: str | None = None,
    tenant_id: str | None = None,
) -> str:
    """The value for ``key``, or raise when it is required and absent."""
    if _overrides is not None and key in _overrides:
        value = _overrides[key]
    else:
        value = (
            tenant_value(key, tenant_id)
            or _snapshot.get(key)
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
    """A copy of the platform layer, for the admin screen."""
    return dict(_snapshot)


def tenant_keys(tenant_id: str) -> dict[str, str]:
    """A copy of one tenant's layer, for the admin screen."""
    tenant = str(tenant_id or "").strip()
    return {k: v for (t, k), v in _tenant_snapshot.items() if t == tenant}


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
