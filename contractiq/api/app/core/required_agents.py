"""Agent slugs ContractIQ depends on at runtime.

Every endpoint that calls ``_execute_agent("ciq-...")`` should list the
slug here. The startup health check resolves each one against the
configured Abenix instance and logs a loud warning per missing slug, so
seeder drift is caught at boot instead of surfaced as a runtime
"agent slug not found" failure to a user clicking the UI.
"""

from __future__ import annotations

import logging
import os

REQUIRED_ABENIX_AGENT_SLUGS: list[str] = [
    "ciq-recommendation-engine",
    "ciq-price-engine",
    "ciq-offtake-forecaster",
    "ciq-financial-extractor",
    "ciq-rating-fetcher",
    "ciq-permit-checker",
    "ciq-counterparty-refresher",
]


async def warn_if_required_agents_missing(logger: logging.Logger | None = None) -> list[str]:
    """Resolve each required slug against Abenix. Returns the missing list.

    Non-fatal: a warning is logged per missing slug so the operator sees
    them on boot, but the API still serves. Misconfigured ABENIX_API_URL
    or API key is logged once at INFO so the cause is visible.
    """
    log = logger or logging.getLogger("contractiq.startup")
    base_url = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    if not api_key:
        log.info(
            "Skipping required-agents check: CONTRACTIQ_ABENIX_API_KEY not set"
        )
        return list(REQUIRED_ABENIX_AGENT_SLUGS)

    missing: list[str] = []
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))
        from abenix_sdk import Abenix
        async with Abenix(api_key=api_key, base_url=base_url, timeout=15.0) as forge:
            for slug in REQUIRED_ABENIX_AGENT_SLUGS:
                try:
                    found = await forge.agents.find_by_slug(slug)
                except Exception as e:  # noqa: BLE001
                    log.warning("required-agent check %s errored: %r", slug, e)
                    missing.append(slug)
                    continue
                if not found or not found.get("id"):
                    missing.append(slug)
    except Exception as e:  # noqa: BLE001
        log.warning("required-agents check could not run: %r", e)
        return list(REQUIRED_ABENIX_AGENT_SLUGS)

    if missing:
        log.warning(
            "REQUIRED ABENIX AGENTS MISSING (%d): %s — run "
            "`python packages/db/seeds/seed_agents.py` against the configured "
            "Abenix DB to seed them.",
            len(missing),
            ", ".join(missing),
        )
    else:
        log.info(
            "Abenix required-agents check: all %d agents present",
            len(REQUIRED_ABENIX_AGENT_SLUGS),
        )
    return missing
