from __future__ import annotations

import logging
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import has_capability, need_words
from app.core.platform_features import is_platform_operator
from app.core.responses import error

logger = logging.getLogger(__name__)

TOOLS_EXECUTE = "tools.execute"

# These reach the platform database, the platform Redis, local files or run code in the API process.
OPERATOR_ONLY_TOOLS = frozenset(
    {
        "agent_step",
        "browser_automation",
        "cloud_storage",
        "code_executor",
        "csv_analyzer",
        "data_exporter",
        "database_query",
        "database_writer",
        "document_extractor",
        "document_parser",
        "file_reader",
        "file_system",
        "image_analyzer",
        "invoke_agent",
        "kafka_consumer",
        "kyc_met_pdf_extractor",
        "presentation_analyzer",
        "redis_stream_consumer",
        "redis_stream_publisher",
        "sandboxed_job",
        "speech_to_text",
        "spreadsheet_analyzer",
        "sub_pipeline",
        "tsdb_query",
    }
)

CALLER_CONFIG_KEYS = frozenset(
    {"thresholds", "custom_patterns", "default_action", "timeout_seconds"}
)


def caller_config(config: Any, tool_slug: str) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    dropped = sorted(k for k in config if k not in CALLER_CONFIG_KEYS)
    if dropped:
        logger.warning("tool %s ignored config keys %s", tool_slug, dropped)
    return {k: v for k, v in config.items() if k in CALLER_CONFIG_KEYS}


async def tool_denial(
    db: AsyncSession, user: Any, tool_slug: str
) -> JSONResponse | None:
    if not await has_capability(db, user, TOOLS_EXECUTE):
        return error(need_words(TOOLS_EXECUTE), 403, "MISSING_PERMISSION")
    if tool_slug in OPERATOR_ONLY_TOOLS and not await is_platform_operator(db, user):
        return error(
            f"{tool_slug} reaches shared platform resources, so only a platform "
            "operator can run it directly. Add it to an agent instead.",
            403,
            "PLATFORM_OPERATOR_REQUIRED",
        )
    return None
