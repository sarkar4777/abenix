"""LLM Route tool — use an LLM to classify input and route to named branches."""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class LLMRouteTool(BaseTool):
    name = "llm_route"
    description = (
        "Use an LLM to analyze input and route to one of N named branches. "
        "Provide a classification prompt, a list of branch names, and optional context. "
        "The LLM will return a JSON object with 'route' (the chosen branch) and "
        "'confidence' (0-1 score). Use this with a Switch node for intelligent routing."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Classification instruction for the LLM (e.g., 'Classify this ticket as: billing, technical, escalation')",
            },
            "branches": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of valid branch/category names to choose from",
            },
            "context": {
                "type": "string",
                "description": "The content to classify (e.g., the ticket text, email body)",
                "default": "",
            },
            "model": {
                "type": "string",
                "description": "LLM model to use",
                "default": "claude-sonnet-4-5-20250929",
            },
        },
        "required": ["prompt", "branches"],
    }

    def __init__(self, llm_router: Any = None) -> None:
        self._llm_router = llm_router

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        prompt = arguments.get("prompt", "")
        branches = arguments.get("branches", [])
        context = arguments.get("context", "")
        model = arguments.get("model", "claude-sonnet-4-5-20250929")

        if not branches:
            return ToolResult(content="No branches provided", is_error=True)

        branch_list = ", ".join(f'"{b}"' for b in branches)
        system = (
            f"You are a classifier. Respond ONLY with valid JSON: "
            f'{{"route": "<one of: {branch_list}>", "confidence": <0.0-1.0>}}'
        )
        user_msg = f"{prompt}\n\nContent to classify:\n{context}" if context else prompt

        # Create LLM router if not injected (self-contained mode)
        llm = self._llm_router
        if llm is None:
            try:
                from engine.llm_router import LLMRouter

                llm = LLMRouter()
            except Exception:
                # Final fallback: simple keyword matching (no LLM available)
                lower_context = (context + " " + prompt).lower()
                best = branches[0]
                for b in branches:
                    if b.lower() in lower_context:
                        best = b
                        break
                return ToolResult(
                    content=json.dumps(
                        {"route": best, "confidence": 0.5, "method": "keyword_fallback"}
                    ),
                )

        try:
            response = await llm.complete(
                messages=[{"role": "user", "content": user_msg}],
                system=system,
                model=model,
                temperature=0.1,
            )
            text = response.content.strip()
            # Try to extract JSON from response (handle single quotes, markdown, etc.)
            route = None
            confidence = 0.5
            if "{" in text:
                try:
                    json_str = text[text.index("{") : text.rindex("}") + 1]
                    # Fix single quotes to double quotes
                    json_str = json_str.replace("'", '"')
                    parsed = json.loads(json_str)
                    route = parsed.get("route", None)
                    confidence = float(parsed.get("confidence", 0.5))
                except (json.JSONDecodeError, ValueError):
                    pass  # Fall through to text matching

            # If JSON parsing failed or no route, try text matching
            if route is None or route not in branches:
                lower_text = text.lower()
                for b in branches:
                    if b.lower() in lower_text:
                        route = b
                        confidence = max(confidence, 0.6)
                        break

            if route is None or route not in branches:
                route = branches[0]
                confidence = 0.3

            return ToolResult(
                content=json.dumps({"route": route, "confidence": confidence}),
            )
        except Exception as e:
            return ToolResult(content=f"LLM routing failed: {e}", is_error=True)
