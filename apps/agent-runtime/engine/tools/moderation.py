"""Agent-callable moderation tool."""

from __future__ import annotations

import json
from typing import Any

from engine.moderation_client import evaluate
from engine.tools.base import BaseTool, ToolResult


class ModerationVetTool(BaseTool):
    name = "moderation_vet"
    description = (
        "Screen text content for policy violations (hate, harassment, violence, "
        "sexual, self-harm, illicit). Returns {outcome, action, triggered_categories, "
        "category_scores, reason}. Use before sending user-visible output or acting "
        "on user input."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Text to screen. Max 30000 characters; longer input is truncated.",
            },
            "strict": {
                "type": "boolean",
                "default": False,
                "description": (
                    "If true, use threshold 0.3 instead of 0.5 and treat any provider "
                    "flag as blocked. Use when drafting regulated communications."
                ),
            },
        },
        "required": ["content"],
    }

    def __init__(
        self,
        *,
        tenant_id: str = "",
        user_id: str = "",
        thresholds: dict | None = None,
        custom_patterns: list | None = None,
        default_action: str = "block",
    ) -> None:
        self._tenant_id = tenant_id
        self._user_id = user_id
        # Copy policy-provided defaults so the tool reflects the same
        # ruleset the gate would apply. Callers can override via
        # arguments.strict.
        self._thresholds = thresholds or {}
        self._custom_patterns = list(custom_patterns or [])
        self._default_action = default_action

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        content = (arguments.get("content") or "").strip()
        if not content:
            return ToolResult(
                content="content is required",
                is_error=True,
            )
        strict = bool(arguments.get("strict"))
        default_threshold = 0.3 if strict else 0.5
        default_action = "block" if strict else self._default_action

        decision = await evaluate(
            content,
            thresholds=self._thresholds,
            default_threshold=default_threshold,
            default_action=default_action,
            custom_patterns=self._custom_patterns,
        )

        body = {
            "outcome": decision.outcome,
            "action": decision.action,
            "flagged": decision.flagged,
            "triggered_categories": decision.triggered_categories,
            "category_scores": {
                k: round(v, 4) for k, v in (decision.category_scores or {}).items()
            },
            "reason": decision.reason,
            "latency_ms": decision.latency_ms,
            "strict": strict,
        }
        if decision.error:
            body["provider_error"] = decision.error
        if (
            decision.redacted_content is not None
            and decision.redacted_content != content
        ):
            body["redacted_content"] = decision.redacted_content

        return ToolResult(
            content=json.dumps(body),
            is_error=(decision.outcome == "blocked"),
            metadata={
                "outcome": decision.outcome,
                "action": decision.action,
                "triggered": decision.triggered_categories,
            },
        )
