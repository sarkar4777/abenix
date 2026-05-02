"""Helpers for tools that wrap external APIs.

Two recurring problems make wrapped-API tools confusing to end users:
  1. The vendor key is missing → tool silently returns garbage / empty
     results, and the LLM apologises politely. The user thinks the
     platform is broken when actually they need to set an env var.
  2. The vendor returns 4xx/5xx → tool returns the error text as
     `content` (not `is_error=True`), so the pipeline records
     status=completed and dashboards show no failure.

Use `require_env(...)` at the top of an external-API tool's execute()
to fail-fast with a clear message. Use `vendor_error(...)` to surface
upstream failures as `is_error=True` so the executor records them.
"""

from __future__ import annotations

import os

from engine.tools.base import ToolResult


def require_env(
    *vars_any_of: str, tool_name: str, purpose: str = ""
) -> ToolResult | None:
    """Return a ToolResult error if NONE of the named env vars is set.

    Some tools accept any of several keys (e.g. OPENAI_API_KEY OR
    ANTHROPIC_API_KEY). Pass them all — if at least one is set,
    returns None and the caller continues normally.
    """
    if any(os.environ.get(v) for v in vars_any_of):
        return None
    keys = " or ".join(f"`{v}`" for v in vars_any_of)
    msg_purpose = f" (used for {purpose})" if purpose else ""
    return ToolResult(
        content=(
            f"{tool_name} is not configured: set {keys} in the environment{msg_purpose}. "
            f"This tool wraps an external API and cannot run without that credential. "
            f"See docs/configuration#external-tools for the full list of optional integrations."
        ),
        is_error=True,
    )


def vendor_error(tool_name: str, vendor: str, detail: str) -> ToolResult:
    """Surface a vendor-side failure as an error (not silent content)."""
    return ToolResult(
        content=(
            f"{tool_name} could not reach {vendor}: {detail[:300]}. "
            f"This is an upstream issue, not a platform bug — the tool will "
            f"start working again when the vendor recovers."
        ),
        is_error=True,
    )
