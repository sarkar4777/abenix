"""Tier 3 LLM critic — coherence check for pipelines and agents."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)

_CRITIC_SYSTEM_PROMPT = """\
You are a senior AI engineer reviewing an Abenix configuration before it
ships to production. You are terse, specific, and honest. Never hedge.

You will be given EITHER:
  - A pipeline (list of tool nodes with a DAG), OR
  - An agent (system_prompt + tools + input_variables)

Your job: read the config and answer FOUR questions.

  1. coherence_score  — integer 1..10 for how likely the config is to achieve
                        its stated purpose. 10 = clearly correct, 1 = clearly
                        broken.
  2. missing_steps    — list of concrete steps the config is missing, if any
                        (empty list if none). Be specific: "validate input",
                        "handle empty search results", etc.
  3. suspect_nodes    — list of {node_id, reason} for nodes that look wrong
                        or suspicious. Use the literal node id. Empty list
                        for agents (they don't have nodes).
  4. suggestions      — list of concrete improvements. Be specific and small;
                        do not rewrite the whole thing. Example:
                        "Add a code_executor after `predict` to bucket
                        probability into HIGH/MEDIUM/LOW risk tiers."

Respond with ONLY a JSON object of this exact shape. No preamble, no fences:

{
  "coherence_score": 1..10,
  "missing_steps": ["..."],
  "suspect_nodes": [{"node_id": "...", "reason": "..."}],
  "suggestions": ["..."],
  "summary": "one sentence overall verdict"
}
"""


@dataclass
class LLMCriticReport:
    coherence_score: int = 0
    missing_steps: list[str] = field(default_factory=list)
    suspect_nodes: list[dict[str, str]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    summary: str = ""
    model: str = ""
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "coherence_score": self.coherence_score,
            "missing_steps": self.missing_steps,
            "suspect_nodes": self.suspect_nodes,
            "suggestions": self.suggestions,
            "summary": self.summary,
            "model": self.model,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


def _build_user_prompt(kind: str, config: dict[str, Any], purpose: str) -> str:
    """Build the user turn. Keep the config faithful but trim huge strings."""
    # Clip system prompts so we don't blow the context window.
    trimmed = json.loads(json.dumps(config, default=str))
    if isinstance(trimmed, dict):
        if (
            isinstance(trimmed.get("system_prompt"), str)
            and len(trimmed["system_prompt"]) > 4000
        ):
            trimmed["system_prompt"] = (
                trimmed["system_prompt"][:4000] + "...[truncated]"
            )
        nodes = (
            trimmed.get("pipeline_config", {}).get("nodes")
            or trimmed.get("nodes")
            or []
        )
        for n in nodes if isinstance(nodes, list) else []:
            args = n.get("arguments", {}) if isinstance(n, dict) else {}
            for k, v in list(args.items()) if isinstance(args, dict) else []:
                if isinstance(v, str) and len(v) > 1500:
                    args[k] = v[:1500] + "...[truncated]"

    return (
        f"Kind: {kind}\n"
        f"Stated purpose: {purpose or '(not provided)'}\n\n"
        f"Config:\n```json\n{json.dumps(trimmed, indent=2)}\n```\n"
    )


async def critique(
    kind: str,
    config: dict[str, Any],
    purpose: str = "",
    model: str = "claude-sonnet-4-5-20250929",
) -> LLMCriticReport:
    """Run the Tier 3 critic. `kind` is 'pipeline' or 'agent'."""
    import time as _time

    report = LLMCriticReport(model=model)
    user_prompt = _build_user_prompt(kind, config, purpose)
    start = _time.monotonic()

    # Resolve against subscription mode before branching, else an exclusive
    # subscription still sent critique to ai_builder.validation.model's provider.
    try:
        from engine import claude_subscription as _sub

        _resolved = _sub.effective_model(model)
        if _resolved and _resolved != model:
            logger.info(
                "critic model %s remapped to %s by subscription", model, _resolved
            )
            model = _resolved
            report.model = model
    except Exception as e:  # noqa: BLE001 — never block critique on this
        logger.debug("subscription remap unavailable for critic: %s", e)

    # Non-Anthropic models (azure/openai/google) route through the unified
    # LLMRouter. Anthropic stays on the direct client so we keep the cheaper
    # path and the existing cost calc.
    is_anthropic = model.startswith("claude-")
    text = ""
    if is_anthropic:
        try:
            from engine import claude_subscription

            # Honour subscription credentials — on a subscription-only
            # install there is no ANTHROPIC_API_KEY for a bare client.
            client, _ = claude_subscription.build_async_client()
            model = claude_subscription.effective_model(model)
        except Exception as e:
            report.error = f"No Anthropic client available: {e}"
            return report
        try:
            _kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": 1400,
                "system": _CRITIC_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            try:
                from engine.llm_router import _anthropic_accepts_sampling

                if _anthropic_accepts_sampling():
                    _kwargs["temperature"] = 0.0
            except Exception:
                pass
            resp = await client.messages.create(**_kwargs)
        except Exception as e:
            report.error = f"LLM call failed: {e}"
            return report
        report.latency_ms = int((_time.monotonic() - start) * 1000)
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text += block.text
        # Rough cost estimate (claude-sonnet-4-5 pricing).
        report.cost_usd = (
            resp.usage.input_tokens * 3.0 + resp.usage.output_tokens * 15.0
        ) / 1_000_000
    else:
        try:
            from engine.llm_router import LLMRouter  # type: ignore

            router = LLMRouter()
        except Exception as e:
            report.error = f"LLMRouter unavailable for model {model}: {e}"
            return report
        try:
            resp = await router.complete(  # type: ignore[attr-defined]
                messages=[{"role": "user", "content": user_prompt}],
                system=_CRITIC_SYSTEM_PROMPT,
                model=model,
                temperature=0.0,
                max_tokens=1400,
            )
        except Exception as e:
            report.error = f"LLM call failed: {e}"
            return report
        report.latency_ms = int((_time.monotonic() - start) * 1000)
        text = getattr(resp, "content", "") or ""
        report.cost_usd = float(getattr(resp, "cost", 0.0) or 0.0)

    # Parse JSON — handle fence fallback.
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        data = json.loads(raw)
    except Exception as e:
        report.error = f"Critic returned non-JSON: {e}. Raw: {text[:200]}"
        return report

    report.coherence_score = int(data.get("coherence_score", 0))
    report.missing_steps = [str(s) for s in data.get("missing_steps", [])]
    report.suspect_nodes = [
        {"node_id": str(x.get("node_id", "")), "reason": str(x.get("reason", ""))}
        for x in data.get("suspect_nodes", [])
        if isinstance(x, dict)
    ]
    report.suggestions = [str(s) for s in data.get("suggestions", [])]
    report.summary = str(data.get("summary", ""))
    return report
