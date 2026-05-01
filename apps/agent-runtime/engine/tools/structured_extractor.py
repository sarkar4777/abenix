"""Universal structured data extraction tool."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_MAX_INPUT_CHARS = 100_000

_SYSTEM_PROMPT = (
    "You are a structured data extraction specialist. "
    "Given source text and a target schema, extract ALL matching data from "
    "the text into the exact schema format. Return ONLY valid JSON matching "
    "the schema -- no markdown fences, no commentary, no explanations. "
    "If a field cannot be determined from the text, use null. "
    "For arrays, include every matching item found in the text, not just "
    "the first few."
)


def _strip_json_fences(text: str) -> str:
    """Remove optional ```json ... ``` fences that LLMs sometimes add."""
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (with optional language tag)
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    if text.endswith("```"):
        text = text[: -3].rstrip()
    return text.strip()


def _schema_to_description(schema: dict[str, Any], indent: int = 0) -> str:
    """Convert a user-provided schema hint into a readable description"""
    lines: list[str] = []
    prefix = "  " * indent

    for key, value in schema.items():
        if isinstance(value, str):
            lines.append(f"{prefix}\"{key}\": <{value}>")
        elif isinstance(value, list):
            if value and isinstance(value[0], dict):
                lines.append(f"{prefix}\"{key}\": [")
                lines.append(_schema_to_description(value[0], indent + 1))
                lines.append(f"{prefix}]")
            elif value and isinstance(value[0], str):
                lines.append(f"{prefix}\"{key}\": [<{value[0]}>]")
            else:
                lines.append(f"{prefix}\"{key}\": [...]")
        elif isinstance(value, dict):
            lines.append(f"{prefix}\"{key}\": {{")
            lines.append(_schema_to_description(value, indent + 1))
            lines.append(f"{prefix}}}")
        else:
            lines.append(f"{prefix}\"{key}\": <{type(value).__name__}>")

    return "\n".join(lines)


def _validate_structure(
    extracted: Any, schema: dict[str, Any]
) -> list[str]:
    """Light structural validation: check top-level keys exist."""
    warnings: list[str] = []
    if not isinstance(extracted, dict):
        warnings.append(
            f"Expected a JSON object at the top level but got {type(extracted).__name__}"
        )
        return warnings

    expected_keys = set(schema.keys())
    actual_keys = set(extracted.keys())
    missing = expected_keys - actual_keys
    if missing:
        warnings.append(f"Schema keys missing from output: {', '.join(sorted(missing))}")
    return warnings


class StructuredExtractorTool(BaseTool):
    name = "structured_extractor"
    description = (
        "Extract structured data from unstructured text using a provided JSON "
        "schema. The tool calls an LLM to analyze the text and produce output "
        "matching your schema. Use for contract analysis, invoice processing, "
        "resume parsing, medical record extraction, or any document-to-data "
        "conversion."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "The source text to extract from (up to 100K characters)"
                ),
            },
            "schema": {
                "type": "object",
                "description": (
                    "A JSON object describing the output structure. Example: "
                    '{\"company_name\": \"string\", \"revenue\": \"number\", '
                    '\"employees\": [{\"name\": \"string\", \"role\": \"string\"}]}'
                ),
            },
            "instructions": {
                "type": "string",
                "description": (
                    "Additional extraction guidelines, e.g. 'Focus on financial "
                    "terms. Use ISO dates. Extract ALL clauses, not just the first few.'"
                ),
            },
            "model": {
                "type": "string",
                "description": "LLM model to use for extraction",
                "default": "claude-sonnet-4-5-20250929",
            },
            "max_tokens": {
                "type": "integer",
                "description": "Maximum output tokens for the LLM response",
                "default": 8000,
            },
        },
        "required": ["text", "schema"],
    }

    # execute

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        text = arguments.get("text", "")
        schema = arguments.get("schema")
        instructions = arguments.get("instructions", "")
        model = arguments.get("model", "claude-sonnet-4-5-20250929")
        max_tokens = int(arguments.get("max_tokens", 8000))

        if not text:
            return ToolResult(
                content="Error: 'text' is required", is_error=True
            )
        if not schema or not isinstance(schema, dict):
            return ToolResult(
                content="Error: 'schema' is required and must be a JSON object",
                is_error=True,
            )

        warnings: list[str] = []

        # Enforce character ceiling
        if len(text) > _MAX_INPUT_CHARS:
            text = text[:_MAX_INPUT_CHARS]
            warnings.append(
                f"Input text truncated to {_MAX_INPUT_CHARS} characters"
            )

        schema_desc = _schema_to_description(schema)
        user_prompt_parts = [
            "Extract structured data from the following text.",
            "",
            "TARGET SCHEMA:",
            "```",
            schema_desc,
            "```",
            "",
        ]

        if instructions:
            user_prompt_parts += [
                "ADDITIONAL INSTRUCTIONS:",
                instructions,
                "",
            ]

        user_prompt_parts += [
            "SOURCE TEXT:",
            "```",
            text,
            "```",
            "",
            "Return ONLY the JSON object matching the schema above.",
        ]
        user_prompt = "\n".join(user_prompt_parts)

        try:
            from engine.llm_router import LLMRouter

            router = LLMRouter()
            response = await router.complete(
                messages=[{"role": "user", "content": user_prompt}],
                system=_SYSTEM_PROMPT,
                model=model,
                temperature=0.0,  # deterministic extraction
                max_tokens=max_tokens,
                stream=False,
            )
        except Exception as exc:
            logger.exception("structured_extractor LLM call failed")
            return ToolResult(
                content=f"Error: LLM call failed: {exc}", is_error=True
            )

        raw_content = response.content
        cleaned = _strip_json_fences(raw_content)

        try:
            extracted = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            # Try to salvage: find the first { ... } block
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                try:
                    extracted = json.loads(match.group(0))
                except json.JSONDecodeError:
                    return ToolResult(
                        content=json.dumps({
                            "error": "LLM returned invalid JSON",
                            "parse_error": str(exc),
                            "raw_response": raw_content[:2000],
                            "model": model,
                        }),
                        is_error=True,
                    )
            else:
                return ToolResult(
                    content=json.dumps({
                        "error": "LLM returned invalid JSON",
                        "parse_error": str(exc),
                        "raw_response": raw_content[:2000],
                        "model": model,
                    }),
                    is_error=True,
                )

        # Structural check
        validation_warnings = _validate_structure(extracted, schema)
        warnings.extend(validation_warnings)

        # Simple heuristic: ratio of non-null populated schema keys.
        confidence = self._estimate_confidence(extracted, schema)

        tokens_used = response.input_tokens + response.output_tokens

        result = {
            "extracted": extracted,
            "confidence": round(confidence, 2),
            "warnings": warnings,
            "model": response.model,
            "tokens_used": tokens_used,
        }

        return ToolResult(
            content=json.dumps(result, default=str),
            metadata={
                "model": response.model,
                "tokens_used": tokens_used,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost": response.cost,
                "confidence": round(confidence, 2),
            },
        )

    # helpers

    @staticmethod
    def _estimate_confidence(
        extracted: Any, schema: dict[str, Any]
    ) -> float:
        """Return a 0-1 confidence score based on how many schema keys"""
        if not isinstance(extracted, dict):
            return 0.0

        total = 0
        populated = 0

        for key in schema:
            total += 1
            value = extracted.get(key)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, list) and len(value) == 0:
                continue
            if isinstance(value, dict) and not value:
                continue
            populated += 1

        return populated / total if total > 0 else 0.0
