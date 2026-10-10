"""Claude subscription credentials for the runtime.

A Claude Pro/Max subscription authenticates with an OAuth token instead of
an API key: `Authorization: Bearer <token>` plus the `oauth-2025-04-20`
beta header. The token is minted out-of-band (`claude setup-token`) and
pasted into Admin -> LLM Settings, which stores it in `platform_settings`.

The runtime cannot import the API's async settings helper, so config is
read straight from Postgres with psycopg2 — the same pattern
`model_resolver` and `_load_db_pricing` already use.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_CACHE: SubscriptionConfig | None = None
_CACHE_AT: float = 0.0
_CACHE_TTL = 30.0

# Keys mirrored in apps/api/app/core/platform_settings.py DEFAULTS.
_KEY_ENABLED = "llm.subscription.enabled"
_KEY_TOKEN = "llm.subscription.token"
_KEY_MODEL = "llm.subscription.default_model"
_KEY_EXCLUSIVE = "llm.subscription.exclusive"

# Env fallbacks so a headless install can run without touching the UI.
_ENV_TOKEN = ("CLAUDE_SUBSCRIPTION_TOKEN", "ANTHROPIC_AUTH_TOKEN")

# The one default for the runtime, the admin page and the model pickers. Haiku
# because exclusive mode pins every call to it and one pipeline can fan out to a
# dozen sub-agents, so the tightest-limited model 429s a fresh install.
DEFAULT_SUBSCRIPTION_MODEL = "claude-haiku-4-5"

# Requests naming a non-Claude model get remapped onto a Claude tier of
# roughly comparable standing so an exclusive subscription can serve them.
_TIER_REMAP: dict[str, str] = {
    "gpt-4o": "claude-opus-5",
    "gpt-4o-mini": "claude-haiku-4-5",
    "gpt-5": "claude-opus-5",
    "azure-gpt-4o": "claude-opus-5",
    "azure-gpt-4o-mini": "claude-haiku-4-5",
    "gemini-2.5-pro": "claude-opus-5",
    "gemini-2.0-flash": "claude-haiku-4-5",
    "gemini-2.5-flash": "claude-haiku-4-5",
    "gemini-1.5-pro": "claude-sonnet-5",
}

_PLACEHOLDERS = {"", "placeholder", "dev", "changeme", "none", "null"}


@dataclass(frozen=True)
class SubscriptionConfig:
    enabled: bool
    token: str
    default_model: str
    exclusive: bool

    @property
    def usable(self) -> bool:
        return self.enabled and _is_real_token(self.token)


def _is_real_token(val: str | None) -> bool:
    return bool(val) and val.strip().lower() not in _PLACEHOLDERS


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def _sync_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return ""
    url = url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
    if "?" in url:
        base, query = url.split("?", 1)
        kept = [p for p in query.split("&") if not p.lower().startswith("ssl=")]
        url = base + (("?" + "&".join(kept)) if kept else "")
    return url


_SQL = "SELECT key, value FROM platform_settings WHERE key LIKE 'llm.subscription.%'"


def _read_via_psycopg2(url: str) -> dict[str, str] | None:
    try:
        import psycopg2
    except Exception:
        return None
    conn = psycopg2.connect(url, connect_timeout=2)
    try:
        with conn.cursor() as cur:
            cur.execute(_SQL)
            return {str(k): str(v or "") for k, v in cur.fetchall()}
    finally:
        conn.close()


def _read_via_asyncpg(url: str) -> dict[str, str] | None:
    """asyncpg fallback — the agent-runtime image ships no psycopg2.

    Without this the settings read failed with "No module named 'psycopg2'",
    get_config() silently fell back to the (empty) environment, and the
    subscription never entered the routing chain even when an admin had
    enabled it. Mirrors model_resolver's two-driver approach.
    """
    try:
        import asyncio as _asyncio

        import asyncpg
    except Exception:
        return None

    async def _query():
        c = await asyncpg.connect(url, timeout=2)
        try:
            return await c.fetch(_SQL)
        finally:
            await c.close()

    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                rows = ex.submit(lambda: _asyncio.run(_query())).result(timeout=5)
        else:
            rows = loop.run_until_complete(_query())
    except RuntimeError:
        rows = _asyncio.run(_query())
    return {str(r["key"]): str(r["value"] or "") for r in rows}


def _read_settings() -> dict[str, str]:
    url = _sync_db_url()
    if not url:
        return {}
    for reader in (_read_via_psycopg2, _read_via_asyncpg):
        try:
            out = reader(url)
        except Exception as exc:
            logger.debug("%s failed: %s", reader.__name__, exc)
            continue
        if out is not None:
            return out
    logger.warning(
        "no usable Postgres driver for subscription settings — "
        "subscription mode cannot be read from the database"
    )
    return {}


def _env_token() -> str:
    for name in _ENV_TOKEN:
        val = os.environ.get(name, "")
        if _is_real_token(val):
            return val.strip()
    return ""


def subscription_state(rows: dict[str, str], token: str) -> dict[str, object]:
    """enabled, default_model and exclusive from the stored rows.

    The API's admin page and model pickers call this too, so what they show is
    what the runtime does.
    """
    # An env-only install has no settings row, so a bare env token is opt-in. A stored row wins.
    if _KEY_ENABLED in rows:
        enabled = _truthy(rows[_KEY_ENABLED])
    else:
        enabled = _is_real_token(token)
    return {
        "enabled": enabled,
        "default_model": str(rows.get(_KEY_MODEL) or "").strip()
        or DEFAULT_SUBSCRIPTION_MODEL,
        "exclusive": _truthy(rows[_KEY_EXCLUSIVE]) if _KEY_EXCLUSIVE in rows else True,
    }


def get_config(refresh: bool = False) -> SubscriptionConfig:
    """Current subscription config, cached for 30s."""
    global _CACHE, _CACHE_AT
    now = time.monotonic()
    if not refresh and _CACHE is not None and (now - _CACHE_AT) < _CACHE_TTL:
        return _CACHE

    rows = _read_settings()
    token = rows.get(_KEY_TOKEN, "").strip() or _env_token()
    cfg = SubscriptionConfig(token=token, **subscription_state(rows, token))
    _CACHE = cfg
    _CACHE_AT = now
    return cfg


def invalidate() -> None:
    global _CACHE, _CACHE_AT
    _CACHE = None
    _CACHE_AT = 0.0


OAUTH_BETA = "oauth-2025-04-20"


def build_async_client(api_key: str | None = None):
    """An `AsyncAnthropic` using whichever credential this install has.

    Subscription first when it is configured, else the supplied API key,
    else whatever the SDK resolves from the environment. Every feature that
    talks to Anthropic outside `LLMRouter` should go through this so
    subscription mode really does cover the whole platform rather than just
    agent execution.

    Returns `(client, used_subscription)`.
    """
    import anthropic

    cfg = get_config()
    if cfg.usable:
        return (
            anthropic.AsyncAnthropic(
                auth_token=cfg.token,
                default_headers={"anthropic-beta": OAUTH_BETA},
            ),
            True,
        )
    if api_key:
        return anthropic.AsyncAnthropic(api_key=api_key), False
    return anthropic.AsyncAnthropic(), False


def build_sync_client(api_key: str | None = None):
    """Sync counterpart of `build_async_client`."""
    import anthropic

    cfg = get_config()
    if cfg.usable:
        return (
            anthropic.Anthropic(
                auth_token=cfg.token,
                default_headers={"anthropic-beta": OAUTH_BETA},
            ),
            True,
        )
    if api_key:
        return anthropic.Anthropic(api_key=api_key), False
    return anthropic.Anthropic(), False


def effective_model(model: str) -> str:
    """Model a call should actually use, accounting for exclusive remapping."""
    cfg = get_config()
    if not cfg.usable:
        return model
    if cfg.exclusive or (model or "").lower().startswith("claude"):
        return map_model(model, cfg)
    return model


def map_model(model: str, cfg: SubscriptionConfig | None = None) -> str:
    """Claude model this request should run on under the subscription.

    In exclusive mode the configured model wins for *every* request,
    including ones that already name a Claude model. That is the whole
    point of the setting — "use the subscription for every feature" — and
    it also keeps behaviour predictable against per-tier rate limits: a
    plan with headroom on Haiku shouldn't 429 just because a seeded agent
    happens to request Sonnet.

    Outside exclusive mode a Claude request passes through untouched and a
    non-Claude one maps onto a comparable tier.
    """
    cfg = cfg or get_config()
    m = (model or "").strip()
    if cfg.exclusive:
        return cfg.default_model
    if m.lower().startswith("claude"):
        return m
    return _TIER_REMAP.get(m.lower(), cfg.default_model)
