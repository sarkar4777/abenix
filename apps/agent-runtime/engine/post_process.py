"""Generic agent-output post-processor.

Validates an agent's structured output against the `output_schema` declared
in its seed YAML (or model_config), normalizes obvious enum drift
(sentiment="mixed" → "neutral", severity="extreme" → "critical"), and
returns both the cleaned payload and a list of validation warnings so the
caller can persist them alongside the result.

This is intentionally a tiny dependency-free walker rather than a full
JSON-schema validator (jsonschema is heavy and we only need a subset:
type=object/array/string/number, enum, required). If a stricter schema
language becomes necessary, swap this for `jsonschema` in one place.

Wired in:
- apps/agent-runtime/engine/pipeline.py — after each llm_call/agent_step
  node where the producing agent has output_schema set.
- apps/agent-runtime/consumer.py — after AgentExecutor.invoke() for
  single-agent runs.

The "validation_warnings" list is published on the SSE bus and persisted
in the Execution row's `output_message` (as a JSON sidecar) so the UI's
provenance tab can render real lineage.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Known enum normalizations the LLM repeatedly drifts on. Keep this list
# tight — if it grows past ~20 entries, the right answer is a corrective
# retry (which is what the engine does for output_schema-declared agents).
_SENTIMENT_NORMALIZE = {
    "": "neutral",
    "mixed": "neutral",
    "ambiguous": "neutral",
    "neutral/positive": "neutral",
    "neutral/negative": "neutral",
    "slightly positive": "positive",
    "slightly negative": "negative",
    "very positive": "positive",
    "very negative": "negative",
    "strongly positive": "positive",
    "strongly negative": "negative",
}

_SEVERITY_NORMALIZE = {
    "extreme": "critical",
    "severe": "critical",
    "med": "medium",
    "moderate": "medium",
    "minor": "low",
    "negligible": "low",
}


def _coerce_enum(
    value: Any, allowed: list[str], normalize_map: dict[str, str]
) -> tuple[Any, str | None]:
    """Try to coerce `value` into one of `allowed`. Returns (new_value, warning_or_None)."""
    if value is None:
        return None, None
    s = str(value).strip().lower()
    if s in allowed:
        return s, None
    mapped = normalize_map.get(s)
    if mapped and mapped in allowed:
        return mapped, f"normalized {value!r} → {mapped!r}"
    # Last resort: keep value but flag it. The UI's defensive normalizers
    # (Phase A2) will catch it client-side.
    return value, f"value {value!r} not in {allowed}"


def _looks_like_sentiment(field_name: str) -> bool:
    return field_name.lower() in {"sentiment", "tone", "stance"}


def _looks_like_severity(field_name: str) -> bool:
    return field_name.lower() in {
        "severity",
        "risk_severity",
        "criticality",
        "impact_level",
    }


def _walk(
    value: Any,
    schema: dict[str, Any] | None,
    path: str,
    warnings: list[str],
) -> Any:
    """Recursively validate + normalize `value` against `schema`."""
    if not isinstance(schema, dict):
        return value

    expected_type = schema.get("type")

    if expected_type == "object" and isinstance(value, dict):
        props = schema.get("properties") or {}
        for k, v in list(value.items()):
            sub_schema = props.get(k)
            if sub_schema is not None:
                value[k] = _walk(v, sub_schema, f"{path}.{k}", warnings)
            elif _looks_like_sentiment(k):
                new_v, w = _coerce_enum(
                    v, ["positive", "negative", "neutral"], _SENTIMENT_NORMALIZE
                )
                value[k] = new_v
                if w:
                    warnings.append(f"{path}.{k}: {w}")
            elif _looks_like_severity(k):
                new_v, w = _coerce_enum(
                    v, ["low", "medium", "high", "critical"], _SEVERITY_NORMALIZE
                )
                value[k] = new_v
                if w:
                    warnings.append(f"{path}.{k}: {w}")
        for required in schema.get("required") or []:
            if required not in value:
                warnings.append(f"{path}: missing required field {required!r}")

    elif expected_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        for i, item in enumerate(value):
            value[i] = _walk(item, item_schema, f"{path}[{i}]", warnings)

    elif expected_type == "string":
        enum_vals = schema.get("enum")
        if enum_vals:
            normalize_map: dict[str, str] = {}
            if set(enum_vals) >= {"positive", "negative", "neutral"}:
                normalize_map = _SENTIMENT_NORMALIZE
            elif set(enum_vals) >= {"low", "medium", "high"}:
                normalize_map = _SEVERITY_NORMALIZE
            new_v, w = _coerce_enum(value, list(enum_vals), normalize_map)
            if w:
                warnings.append(f"{path}: {w}")
            return new_v

    elif expected_type == "number":
        try:
            num = float(value)
            lo = schema.get("minimum")
            hi = schema.get("maximum")
            if lo is not None and num < lo:
                warnings.append(f"{path}: {num} < minimum {lo}; clamping")
                num = float(lo)
            if hi is not None and num > hi:
                warnings.append(f"{path}: {num} > maximum {hi}; clamping")
                num = float(hi)
            return num
        except (TypeError, ValueError):
            warnings.append(f"{path}: not a number ({value!r})")

    return value


_FENCE_RE = re.compile(r"```(?:json)?\s*\n?([\s\S]*?)(?:```|$)", re.MULTILINE)


def _extract_json(text: str) -> Any | None:
    """Best-effort: pull a JSON object out of fenced markdown / prose."""
    if not text:
        return None
    candidate = text.strip()
    m = _FENCE_RE.search(candidate)
    if m:
        candidate = m.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # Find outermost { ... } region
    first = candidate.find("{")
    last = candidate.rfind("}")
    if first >= 0 and last > first:
        try:
            return json.loads(candidate[first : last + 1])
        except json.JSONDecodeError:
            return None
    return None


def post_process(
    raw_output: Any,
    output_schema: dict[str, Any] | None,
) -> tuple[Any, list[str]]:
    """Validate + normalize `raw_output` against `output_schema`.

    Returns (normalized_output, validation_warnings). If `output_schema`
    is None or the output isn't structured, returns the input unchanged
    with no warnings — this is a no-op for legacy agents.

    Callers (pipeline executor, consumer) should:
      1. Call post_process() on the producer's structured output.
      2. If warnings list is non-empty, attach to the SSE node_complete
         event and persist as `validation_warnings` on the Execution row.
      3. Render warnings in the OracleNet provenance tab.
    """
    if not output_schema:
        return raw_output, []

    payload = raw_output
    if isinstance(raw_output, str):
        extracted = _extract_json(raw_output)
        if extracted is not None:
            payload = extracted
        else:
            return raw_output, ["output is string but no JSON could be extracted"]

    warnings: list[str] = []
    try:
        normalized = _walk(payload, output_schema, "$", warnings)
    except Exception as e:
        logger.warning("post_process: walker failed: %s", e)
        return raw_output, [f"validator error: {e}"]

    return normalized, warnings
