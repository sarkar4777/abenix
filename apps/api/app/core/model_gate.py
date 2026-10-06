"""Refuse an agent run before it starts when no model provider has a credential."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from app.core.responses import error

NO_MODEL_CONFIGURED = "NO_MODEL_CONFIGURED"
NO_MODEL_MESSAGE = (
    "No AI model is connected, so this agent cannot run. An admin can add an "
    "Anthropic, OpenAI, Google or Azure key under Admin, Tool Configuration, or "
    "connect a Claude subscription under Admin, LLM Settings."
)


def _is_pipeline(agent: Any) -> bool:
    # a pipeline of tool steps needs no model, its llm steps fail on their own
    cfg = getattr(agent, "model_config_", None) or {}
    return (
        bool(cfg.get("pipeline_config")) or getattr(agent, "mode", None) == "pipeline"
    )


async def model_unavailable_error(db: Any, agent: Any) -> JSONResponse | None:
    if _is_pipeline(agent):
        return None
    from app.routers.llm_models import _probe_providers

    try:
        providers = await _probe_providers(db)
    except Exception:
        return None  # never block a run because the check itself broke
    if any((p or {}).get("configured") for p in providers.values()):
        return None
    return error(NO_MODEL_MESSAGE, 503, error_code=NO_MODEL_CONFIGURED)
