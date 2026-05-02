"""Integrations status — read-only `is X configured?` for the UI.

`/settings/integrations` (in the web app) reads this endpoint to render
"configured / missing / error / unknown" badges next to each external
integration the platform supports.

The check is intentionally lightweight:
  * presence-of-env-var: a key MUST be set, non-empty, and >8 chars to
    count as "configured" (rules out copy-paste-ed empty quotes).
  * No live network probe — we don't want every page-load to ping
    20+ vendors. A future iteration could add an explicit
    "Test connection" button per integration that fires a real probe.

Tenant-scoped values (Slack webhook URL, etc.) read from the DB row
when the user hits the endpoint; everything else reads from os.environ.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.deps import get_current_user
from app.core.responses import success
from models.user import User

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _has_env(*names: str) -> bool:
    """True if at least one of the named env vars is set + non-trivial."""
    for n in names:
        v = os.environ.get(n, "").strip()
        if (
            v
            and len(v) >= 8
            and not v.lower().startswith(("change", "your-", "<", "$"))
        ):
            return True
    return False


_INTEGRATIONS: dict[str, list[str]] = {
    # LLM providers
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "gemini": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    # Search
    "tavily": ["TAVILY_API_KEY"],
    # Storage
    "pinecone": ["PINECONE_API_KEY"],
    "s3": ["AWS_ACCESS_KEY_ID"],
    # Comms
    "slack": ["SLACK_WEBHOOK_URL"],
    "smtp": ["SMTP_HOST", "SMTP_USER"],
    # Observability
    "sentry": ["SENTRY_DSN"],
    "otel": ["OTEL_ENABLED", "OTEL_ENDPOINT"],
    # Data feeds
    "yahoo_finance": ["YAHOO_FINANCE_API_KEY"],
    "ecb": [],  # public endpoint — always "configured"
    "ember": [],  # public endpoint
    "entso_e": ["ENTSO_E_TOKEN"],
    # KYC
    "opensanctions": ["OPENSANCTIONS_API_KEY", "OPENSANCTIONS_DATA_PATH"],
    "opencorporates": ["OPENCORPORATES_API_KEY"],
    # Meeting / voice
    "livekit": ["LIVEKIT_URL"],
    # Source-control
    "github": ["GITHUB_TOKEN"],
}


@router.get("/status")
async def status(user: User = Depends(get_current_user)) -> JSONResponse:
    out: dict[str, str] = {}
    for key, env_vars in _INTEGRATIONS.items():
        if not env_vars:
            out[key] = "configured"  # public endpoint, no key needed
        elif _has_env(*env_vars):
            out[key] = "configured"
        else:
            out[key] = "missing"
    return success(out)
