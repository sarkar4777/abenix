"""Warnings for an agent saved with a model or tool that a run cannot use."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)

# built per tenant or per run, so no fixed list can hold them
DYNAMIC_TOOL_PREFIXES = ("portfolio_", "atlas_", "pipeline:", "mcp")


def find_problems(
    model: str,
    tools: list[str],
    listed_models: set[str],
    known_tools: set[str],
) -> list[str]:
    out: list[str] = []
    if model and listed_models and model not in listed_models:
        out.append(
            f"Model {model} is not in this deployment's model list. A run may fail "
            "or use a different model."
        )
    unknown = [
        t
        for t in tools
        if t not in known_tools and not t.startswith(DYNAMIC_TOOL_PREFIXES)
    ]
    if unknown:
        out.append(
            "These tools do not exist and a run will not have them. "
            + ", ".join(sorted(unknown))
        )
    return out


async def config_warnings(cfg: dict[str, Any], tenant_id: Any) -> list[str]:
    """Never blocks a save, a failed check gives no warnings."""
    try:
        from app.core.deps import fresh_session
        from app.routers.tools import TOOL_CATALOG, _load_runtime_schemas
        from engine.llm_router import MODEL_TO_PROVIDER, PRICING
        from models.llm_pricing import LLMModelPricing
        from models.saved_tool import SavedTool

        tools = [str(t) for t in (cfg.get("tools") or [])]
        model = str(cfg.get("model") or "").strip()
        async with fresh_session() as db:
            rows = await db.execute(
                select(LLMModelPricing.model).where(LLMModelPricing.is_active.is_(True))
            )
            catalogue = {r[0] for r in rows.all()}
            saved = await db.execute(
                select(SavedTool.name).where(
                    SavedTool.tenant_id == tenant_id,
                    SavedTool.name.in_(tools),
                    SavedTool.status == "approved",
                )
            )
            saved_names = {r[0] for r in saved.all()}
        # an empty catalogue means an unseeded table, which says nothing about the model
        listed = (
            catalogue | set(MODEL_TO_PROVIDER) | set(PRICING) if catalogue else set()
        )
        known = set(_load_runtime_schemas())
        known |= {t["id"] for t in TOOL_CATALOG} | saved_names
        return find_problems(model, tools, listed, known)
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent config check skipped %s", exc)
        return []
