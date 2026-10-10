"""Platform-settings helper."""

from __future__ import annotations

import time
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from engine.claude_subscription import DEFAULT_SUBSCRIPTION_MODEL

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[str, float]] = {}
_TTL = 30.0  # seconds


_engine = None
_SessionLocal = None


def _get_session_factory():
    global _engine, _SessionLocal
    if _SessionLocal is None:
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
    return _SessionLocal


# The keys an admin sees in the UI. Edit here to surface new knobs.
DEFAULTS: dict[str, dict[str, Any]] = {
    "ai_builder.model": {
        "value": "claude-sonnet-4-5-20250929",
        "category": "ai_builder",
        "description": "Model used by the AI Builder to generate agent + pipeline YAMLs.",
    },
    "ai_builder.critic.model": {
        "value": "claude-sonnet-4-5-20250929",
        "category": "ai_builder",
        "description": "Model used by the Builder's critic + adversarial-safety gates.",
    },
    "ai_builder.validation.model": {
        "value": "azure-gpt-4o",
        "category": "ai_builder",
        "description": "Model used to preview/validate agents and pipelines from the AI Builder (Tier-3 LLM critic + draft preview calls).",
    },
    "moderation.model": {
        "value": "claude-sonnet-4-5-20250929",
        "category": "moderation",
        "description": "Model used by the pre-LLM moderation gate.",
    },
    "knowledge_engine.summarizer.model": {
        "value": "gemini-2.0-flash",
        "category": "knowledge_engine",
        "description": "Model used to summarise ingested documents in Cognify.",
    },
    "sdk_playground.default.model": {
        "value": "claude-sonnet-4-5-20250929",
        "category": "sdk_playground",
        "description": "Default model pre-selected in the SDK Playground.",
    },
    "triggers.default.model": {
        "value": "gemini-2.0-flash",
        "category": "triggers",
        "description": "Default model attached to scheduled triggers.",
    },
    "pipeline_surgeon.model": {
        "value": "claude-sonnet-4-5-20250929",
        "category": "pipeline_healing",
        "description": "Model used by the Pipeline Surgeon to propose JSON-Patch fixes for failed pipeline runs. Surgeon output must be deterministic JSON, so prefer a strong reasoning model.",
    },
    "workflow_shell.model": {
        "value": "claude-sonnet-4-5-20250929",
        "category": "workflow_shell",
        "description": "Model used by the Talk-to-Workflow shell to translate natural-language verbs and explain failures. Lower latency models work well here.",
    },
    # ── Claude subscription ──────────────────────────────────────────────
    # An alternative to per-provider API keys: authenticate with a Claude
    # Pro/Max subscription OAuth token. When enabled the runtime routes
    # through it first and falls back to whatever API keys exist.
    # ── Execution limits ────────────────────────────────────────────────
    # These were hardcoded in the engine. A seven-node LLM pipeline does not
    # fit in 120s, which is how ClaimsIQ's adjudication kept dying with
    # "Pipeline timeout exceeded" on its last two nodes.
    "pipeline.timeout_seconds": {
        "value": "300",
        "category": "execution",
        "description": "Wall-clock budget for a whole pipeline run, in seconds. Raise it for pipelines with many LLM nodes. 60-3600.",
        "kind": "int",
        "min": 60,
        "max": 3600,
    },
    "agent.max_iterations": {
        "value": "10",
        "category": "execution",
        "description": "Default tool-calling loop cap for an agent. An agent can ask for more in its own model_config. 1-50.",
        "kind": "int",
        "min": 1,
        "max": 50,
    },
    "sandbox.timeout_seconds": {
        "value": "300",
        "category": "execution",
        "description": "Wall-clock budget for one sandboxed code execution, in seconds. 30-1800.",
        "kind": "int",
        "min": 30,
        "max": 1800,
    },
    "llm.subscription.enabled": {
        "value": "false",
        "category": "claude_subscription",
        "description": "Route LLM traffic through a Claude Pro/Max subscription instead of per-call API billing.",
    },
    "llm.subscription.token": {
        "value": "",
        "category": "claude_subscription",
        "description": "Subscription OAuth token. Generate with `claude setup-token` and paste it here. Stored server-side and never returned to the browser.",
    },
    "llm.subscription.default_model": {
        # same constant the runtime falls back to
        "value": DEFAULT_SUBSCRIPTION_MODEL,
        "category": "claude_subscription",
        "description": "Claude model the subscription serves, and the target for requests that name a non-Claude model while exclusive mode is on. Defaults to Haiku for rate-limit headroom under fan-out.",
    },
    "llm.subscription.exclusive": {
        "value": "true",
        "category": "claude_subscription",
        "description": "Send every feature through the subscription, remapping non-Claude requests onto the model above. Turn off to use it for Claude models only.",
    },
}

# Never echoed back to a client or written to a log line.
SECRET_KEYS: set[str] = {"llm.subscription.token"}


def is_secret(key: str) -> bool:
    """Settings whose value must never be echoed. Tool credentials are stored
    under tool.credential.<KEY> and are treated as secret here regardless of
    kind, the tool-config router masks by declared kind itself."""
    return key in SECRET_KEYS or key.startswith("tool.credential.")


def mask(key: str, value: str | None) -> str:
    """Redact a secret setting for display, keeping a recognisable tail."""
    if not is_secret(key):
        return value or ""
    v = (value or "").strip()
    if not v:
        return ""
    return f"{'*' * 8}{v[-4:]}" if len(v) > 4 else "*" * 8


async def get_setting(key: str, default: str | None = None) -> str:
    """Read a platform setting with a 30-second read-through cache."""
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached and now - cached[1] < _TTL:
        return cached[0]

    fallback = default
    if fallback is None and key in DEFAULTS:
        fallback = str(DEFAULTS[key]["value"])
    try:
        Session = _get_session_factory()
        async with Session() as db:
            r = await db.execute(
                text("SELECT value FROM platform_settings WHERE key = :k"), {"k": key}
            )
            row = r.first()
            if row and row[0]:
                _CACHE[key] = (row[0], now)
                return row[0]
    except Exception as e:
        logger.warning("platform_settings read failed for %s: %s", key, e)

    if fallback is not None:
        _CACHE[key] = (fallback, now)
        return fallback
    return ""


def invalidate(key: str | None = None) -> None:
    """Drop cached value(s) after a write. Called from the admin
    settings router when a value changes."""
    if key:
        _CACHE.pop(key, None)
    else:
        _CACHE.clear()


async def get_int_setting(key: str, fallback: int) -> int:
    """Read an int setting, clamped to the bounds declared in DEFAULTS.

    Any bad or missing value falls back rather than raising, because these are
    read on the execution hot path and a typo in the admin UI must not take
    agent runs down.
    """
    meta = DEFAULTS.get(key) or {}
    try:
        raw = await get_setting(key)
    except Exception as e:  # noqa: BLE001 — never block a run on settings I/O
        logger.warning("get_int_setting(%s) failed: %s", key, e)
        return fallback
    try:
        val = int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    lo, hi = meta.get("min"), meta.get("max")
    if isinstance(lo, int) and val < lo:
        return lo
    if isinstance(hi, int) and val > hi:
        return hi
    return val
