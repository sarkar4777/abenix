"""Platform-settings helper."""
from __future__ import annotations

import time
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[str, float]] = {}
_TTL = 30.0  # seconds


_engine = None
_SessionLocal = None


def _get_session_factory():
    global _engine, _SessionLocal
    if _SessionLocal is None:
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
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
}


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
