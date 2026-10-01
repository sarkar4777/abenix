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

from engine import credentials
from engine.tools.base import ToolResult


def require_env(
    *vars_any_of: str, tool_name: str, purpose: str = ""
) -> ToolResult | None:
    """Return a ToolResult error if NONE of the named values is configured.

    Some tools accept any of several keys (e.g. OPENAI_API_KEY OR
    ANTHROPIC_API_KEY). Pass them all — if at least one is set,
    returns None and the caller continues normally. Values come through
    the resolver, so a key an admin saved counts the same as one in the
    environment, and the message sends the user to the admin screen rather
    than to a shell.
    """
    if any(credentials.get(v) for v in vars_any_of):
        return None
    keys = " or ".join(vars_any_of)
    msg_purpose = f" (used for {purpose})" if purpose else ""
    return ToolResult(
        content=(
            f"{keys} is not configured{msg_purpose}. "
            "An admin can add it under Admin -> Tool Configuration."
        ),
        is_error=True,
        metadata={
            "needs_configuration": vars_any_of[0] if vars_any_of else "",
            "tool": tool_name,
        },
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
