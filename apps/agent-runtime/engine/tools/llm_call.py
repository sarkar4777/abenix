"""LLM call tool for making sub-agent LLM requests within a pipeline."""

from __future__ import annotations

import json
from typing import Any

from engine.provider_credentials import PROVIDER_CONFIG_FIELDS
from engine.tools.base import BaseTool, ToolResult


class LLMCallTool(BaseTool):
    # The LLM provider keys, declared here so they sit on the admin screen.
    config_fields = PROVIDER_CONFIG_FIELDS
    name = "llm_call"

    @classmethod
    async def config_test(
        cls, values: dict[str, str], key: str | None = None
    ) -> tuple[bool, str] | None:
        from engine.tools._config_probe import probe

        if key == "ANTHROPIC_API_KEY":
            return await probe(
                "GET",
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": values.get(key, ""),
                    "anthropic-version": "2023-06-01",
                },
                accepted="Anthropic accepted the key",
            )
        if key == "OPENAI_API_KEY":
            return await probe(
                "GET",
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {values.get(key, '')}"},
                accepted="OpenAI accepted the key",
            )
        if key in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
            return await probe(
                "GET",
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": values.get(key, ""), "pageSize": 1},
                accepted="Google AI accepted the key",
            )
        if key and key.startswith("AZURE_OPENAI_"):
            base = (values.get("AZURE_OPENAI_API_BASE") or "").rstrip("/")
            if not base:
                return False, "AZURE_OPENAI_API_BASE is needed to test the key"
            return await probe(
                "GET",
                f"{base}/openai/models",
                params={
                    "api-version": values.get("AZURE_OPENAI_API_VERSION")
                    or "2024-10-01-preview"
                },
                headers={"api-key": values.get("AZURE_OPENAI_API_KEY", "")},
                accepted="Azure OpenAI accepted the key",
            )
        return None

    description = (
        "Make a sub-call to a large language model within a pipeline. Supports multiple "
        "providers and models including Claude, GPT-4o, and Gemini. Useful for "
        "summarization, classification, extraction, rewriting, translation, and any "
        "other LLM-powered transformation step within an agent workflow."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The user prompt to send to the LLM",
            },
            "system_prompt": {
                "type": "string",
                "description": "Optional system prompt to set LLM behavior and context",
                "default": "",
            },
            "model": {
                "type": "string",
                "enum": [
                    "claude-sonnet-4-5-20250929",
                    "claude-haiku-3-5-20241022",
                    "gpt-4o",
                    "gpt-4o-mini",
                    "gemini-2.0-flash",
                ],
                "description": "Model to use for the completion",
                "default": "claude-sonnet-4-5-20250929",
            },
            "temperature": {
                "type": "number",
                "description": "Sampling temperature (0-2). Lower is more deterministic.",
                "default": 0.7,
                "minimum": 0,
                "maximum": 2,
            },
            "max_tokens": {
                "type": "integer",
                "description": "Maximum number of tokens to generate",
                "default": 4096,
            },
        },
        "required": ["prompt"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        prompt = arguments.get("prompt", "")
        system_prompt = arguments.get("system_prompt", "")
        model = arguments.get("model", "claude-sonnet-4-5-20250929")
        temperature = arguments.get("temperature", 0.7)
        arguments.get("max_tokens", 4096)

        # Coerce non-string prompts (dicts/lists from upstream node outputs)
        # into a JSON string so the LLM can still reason over the data.
        if not isinstance(prompt, str):
            import json as _j

            prompt = _j.dumps(prompt, default=str, indent=2)
        if not isinstance(system_prompt, str):
            import json as _j

            system_prompt = _j.dumps(system_prompt, default=str, indent=2)

        if not prompt.strip():
            return ToolResult(content="Error: prompt is required", is_error=True)

        try:
            from engine.llm_router import LLMRouter

            router = LLMRouter()
            response = await router.complete(
                messages=[{"role": "user", "content": prompt}],
                system=system_prompt or None,
                model=model,
                temperature=temperature,
                stream=False,
            )

            result = {
                "response": response.content,
                "model": response.model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost": response.cost,
                "latency_ms": response.latency_ms,
            }
            return ToolResult(
                content=json.dumps(result, indent=2, default=str),
                metadata={
                    "model": response.model,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "cost": response.cost,
                },
            )
        except Exception as e:
            return ToolResult(content=f"LLM call failed: {e}", is_error=True)
