"""Per-agent deterministic post-processors.

A post-processor runs after the agent finishes and gets a chance to
rewrite the structured output before it lands in the DB. The agent_slug
is the lookup key — each agent that wants one registers a callable here.

The contract is intentionally tiny: callable receives the parsed forecast
dict, the list of (tool_name, arguments, output_summary) tuples gathered
during the run, plus the raw output string for diagnostic logging, and
returns the rewritten forecast dict.

These run AFTER the generic output_schema validator in post_process.py.
That ordering matters — the schema walker normalizes enums first, then a
domain post-processor can override numeric content with knowledge the
schema can't express.

Discovery: this module knows NOTHING about specific commodities, apps,
or tenants. Hook modules are loaded via two mechanisms, both opt-in:

1. POST_PROCESSOR_MODULES env var: comma-separated import paths. Each
   module is imported at startup; import-time side effects call
   register(slug, fn).
2. importlib.metadata entry-points under group
   'agentforge.post_processors'. Same contract — import triggers
   registration.

If neither is set the registry stays empty and run() is a no-op.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)

# Signature: (forecast_dict, tool_runs, raw_output) -> rewritten forecast_dict
# tool_runs is a list of {"tool": str, "input": dict, "output_summary": dict}.
PostProcessor = Callable[[dict, list[dict], str], dict]


_REGISTRY: dict[str, PostProcessor] = {}
_DISCOVERED = False


def register(slug: str, fn: PostProcessor) -> None:
    """Register a per-agent post-processor by slug."""
    _REGISTRY[slug] = fn


def get(slug: str) -> PostProcessor | None:
    try:
        _ensure_discovered()
    except Exception as e:
        logger.warning("post_processors.get: discovery raised: %s", e)
    return _REGISTRY.get(slug)


def run(slug: str, forecast: dict, tool_runs: list[dict], raw: str) -> dict:
    """Run the registered post-processor for `slug`. No-op if none registered."""
    try:
        _ensure_discovered()
    except Exception as e:
        logger.warning("post_processors.run: discovery raised: %s", e)
        return forecast
    fn = _REGISTRY.get(slug)
    if fn is None:
        return forecast
    try:
        return fn(forecast, tool_runs, raw)
    except Exception as e:
        logger.warning("post_processor[%s] raised — passing through: %s", slug, e)
        return forecast


def _ensure_discovered() -> None:
    """Import any modules listed in POST_PROCESSOR_MODULES + entry-points once.

    Belt-and-braces: every step is wrapped so a malformed env value or a
    broken hook module can never bubble up to the caller. The runtime
    must stay alive even if every post-processor is busted — agents are
    still useful without their domain rewrite.
    """
    global _DISCOVERED
    if _DISCOVERED:
        return
    # Flip the flag FIRST so a re-entrant call during a failing import
    # (e.g. the hook module itself doing a `from engine.post_processors
    # import register`) doesn't loop forever.
    _DISCOVERED = True

    try:
        raw = os.environ.get("POST_PROCESSOR_MODULES", "")
        mods = [m.strip() for m in raw.split(",") if m.strip()]
        if mods:
            logger.info("post_processors: discovering modules=%s", mods)
        for mod_name in mods:
            try:
                importlib.import_module(mod_name)
            except Exception as e:
                logger.warning("post_processors: failed to import %s: %s", mod_name, e)
    except Exception as e:
        logger.warning("post_processors: env-driven discovery skipped: %s", e)

    try:
        from importlib import metadata as _md

        for ep in _md.entry_points(group="agentforge.post_processors"):
            try:
                ep.load()
            except Exception as e:
                logger.warning("post_processors: entry-point %s failed: %s", ep.name, e)
    except Exception as e:
        logger.debug("post_processors: entry-point discovery skipped: %s", e)

    logger.info("post_processors: discovery complete (%d registered)", len(_REGISTRY))
