"""Who may reach the platform database and which folders a tenant's tools may read."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from engine import credentials, url_guard

logger = logging.getLogger(__name__)

SYSTEM_USER_EMAIL = "system@abenix.dev"
TENANT_DB_KEY = "TENANT_DATABASE_URL"
ALLOW_CONNECTION_ARG_KEY = "TOOL_ALLOW_CONNECTION_STRINGS"
PLATFORM_FILE_ROOTS_ENV = "TOOL_PLATFORM_FILE_ROOTS"
_CACHE_SECONDS = 60.0
_cache: dict[str, tuple[float, str]] = {}


def _dsn() -> str:
    from engine.tools._db_url import resolve_async_db_url

    url = resolve_async_db_url(os.environ.get("DATABASE_URL", ""))
    return (url or "").replace("postgresql+asyncpg://", "postgresql://", 1)


async def _lookup(cache_key: str, sql: str, *args: Any) -> str:
    hit = _cache.get(cache_key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    dsn = _dsn()
    if not dsn:
        return ""
    try:
        import asyncpg

        conn = await asyncpg.connect(dsn, timeout=10)
        try:
            value = str(await conn.fetchval(sql, *args) or "")
        finally:
            await conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("tenant access lookup failed (%s)", type(e).__name__)
        return ""
    _cache[cache_key] = (time.monotonic() + _CACHE_SECONDS, value)
    return value


async def platform_tenant_id() -> str:
    return await _lookup(
        "platform",
        "SELECT tenant_id::text FROM users WHERE lower(email) = $1",
        SYSTEM_USER_EMAIL,
    )


def current_tenant(tool: Any = None) -> str:
    return str(getattr(tool, "tenant_id", "") or credentials.current_tenant() or "")


async def may_use_platform_db(tenant_id: str, agent_id: str = "") -> bool:
    """Only runs in the platform tenant, a seeded agent run by another tenant could read everyone."""
    platform = await platform_tenant_id()
    return bool(platform) and platform == str(tenant_id or "")


def _same_as_platform_db(url: str) -> bool:
    try:
        wanted, ours = urlparse(url), urlparse(_dsn())
        return (wanted.hostname, wanted.port or 5432, wanted.path) == (
            ours.hostname,
            ours.port or 5432,
            ours.path,
        )
    except ValueError:
        return True


async def connection_host_refusal(url: str) -> str | None:
    """The private target guard http_client uses, applied to a database address."""
    try:
        parsed = urlparse(url)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        return "That connection string is not valid."
    if not parsed.scheme.startswith("postgresql") or not host:
        return "A connection string must start with postgresql:// and name a host."
    reason = await url_guard.check(
        f"https://{host}:{port or 5432}/",
        allow_private=url_guard.env_flag("CONNECTORS_ALLOW_PRIVATE_TARGETS"),
        require_dns=False,
    )
    return f"This connection was refused. {reason}." if reason else None


async def resolve_connection(tool: Any, requested: str) -> tuple[str, str | None]:
    """The address a database tool may use, or the reason it may not."""
    tenant = current_tenant(tool)
    agent = str(getattr(tool, "agent_id", "") or "")
    await credentials.ensure_fresh()
    platform_ok = await may_use_platform_db(tenant, agent)
    if requested:
        allowed = str(tool.cfg(ALLOW_CONNECTION_ARG_KEY) or "").strip().lower()
        if allowed not in ("1", "true", "yes", "on"):
            return "", (
                "This tool cannot take a connection_string here. Ask an admin to set "
                f"{ALLOW_CONNECTION_ARG_KEY} under Admin, Tool Configuration, or to save "
                f"{TENANT_DB_KEY} for this tenant."
            )
        refused = await connection_host_refusal(requested)
        if refused:
            return "", refused
        if not platform_ok and _same_as_platform_db(requested):
            return "", "This tenant cannot connect to the platform database."
        return requested, None
    configured = getattr(tool, "_default_conn", "") or credentials.tenant_value(
        TENANT_DB_KEY, tenant or None
    )
    if configured:
        refused = await connection_host_refusal(configured)
        if refused and not getattr(tool, "_default_conn", ""):
            return "", refused
        return configured, None
    if platform_ok:
        return _dsn(), None
    return "", (
        "No database is configured for this tenant. An admin can save its address as "
        f"{TENANT_DB_KEY} under Admin, Tool Configuration. The platform database is not "
        "available to tenant agents."
    )


def _bases() -> list[str]:
    from engine.storage import service

    return [
        service.STORAGE_LOCAL_DIR,
        os.environ.get("UPLOAD_DIR", "") or service.STORAGE_LOCAL_DIR,
        export_base(),
    ]


def export_base() -> str:
    from engine.tools.code_executor import EXPORT_DIR

    return os.environ.get("EXPORT_DIR") or EXPORT_DIR


def export_dir_for(tenant: str) -> str:
    base = export_base()
    return os.path.join(base, tenant) if tenant else base


def tenant_file_roots(tenant: str) -> list[str]:
    if not tenant:
        return []
    roots = {os.path.realpath(os.path.join(b, tenant)) for b in _bases() if b}
    return sorted(roots)


async def path_refusal(path: Any, tool: Any = None) -> str | None:
    """Why this tool may not touch the path. Symlinks count as where they lead."""
    tenant = current_tenant(tool)
    if not tenant:
        return "File access needs a tenant, and this run has none."
    real = Path(os.path.realpath(str(path)))
    roots = tenant_file_roots(tenant)
    extra = os.environ.get(PLATFORM_FILE_ROOTS_ENV, "")
    kyc = os.environ.get("KYC_UPLOAD_DIR", "")
    shared = [r.strip() for r in [*extra.split(","), kyc] if r.strip()]
    if any(real.is_relative_to(r) for r in roots):
        return None
    if shared and tenant == await platform_tenant_id():
        if any(real.is_relative_to(os.path.realpath(r)) for r in shared):
            return None
    return f"{path} is outside this tenant's files, so it cannot be read."
