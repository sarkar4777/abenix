"""Tier 2 semantic validation — deterministic checks beyond the structural pass."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from engine.pipeline_validator import (
    ValidationError,
    ValidationResult,
    _extract_template_refs,
)
from engine.tools.base import ToolRegistry


# Rough per-call cost hints (USD). These are heuristics for budgeting, not billing.
_TOOL_COST_HINTS: dict[str, float] = {
    "llm_call": 0.02,
    "llm_route": 0.005,
    "agent_step": 0.10,
    "sub_pipeline": 0.05,
    "knowledge_search": 0.002,
    "vector_search": 0.002,
    "web_search": 0.0,
    "tavily_search": 0.004,
    "web_scrape": 0.001,
    "http_client": 0.0,
    "ml_model": 0.0,
    "code_executor": 0.0,
    "calculator": 0.0,
    "current_time": 0.0,
}


@dataclass
class SemanticReport:
    """Output of the Tier 2 pass, layered on top of Tier 1."""
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    suggestions: list[ValidationError] = field(default_factory=list)
    cost_estimate_usd: float = 0.0
    node_cost_breakdown: dict[str, float] = field(default_factory=dict)
    unused_nodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "suggestions": [s.to_dict() for s in self.suggestions],
            "cost_estimate_usd": round(self.cost_estimate_usd, 4),
            "node_cost_breakdown": {k: round(v, 4) for k, v in self.node_cost_breakdown.items()},
            "unused_nodes": self.unused_nodes,
        }


def _argtype(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int) or isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    if v is None:
        return "null"
    return "unknown"


def _is_template(v: Any) -> bool:
    return isinstance(v, str) and "{{" in v and "}}" in v


def _schema_expected(schema: dict[str, Any], field_name: str) -> str | None:
    """Return the JSON-schema type declared for an argument, if any."""
    props = schema.get("properties", {}) or {}
    spec = props.get(field_name)
    if isinstance(spec, dict):
        t = spec.get("type")
        if isinstance(t, str):
            return t
        if isinstance(t, list) and t:
            return t[0]
    return None


def validate_semantic(
    nodes: list[dict[str, Any]],
    tool_registry: ToolRegistry,
    tier1: ValidationResult | None = None,
) -> SemanticReport:
    """Run the Tier 2 checks. Tier 1 is assumed to have already run."""
    report = SemanticReport()
    node_by_id: dict[str, dict[str, Any]] = {n.get("id", ""): n for n in nodes if n.get("id")}

    for n in nodes:
        nid = n.get("id", "")
        tool_name = n.get("tool") or n.get("tool_name") or ""
        args = n.get("arguments", {}) or {}

        tool = tool_registry.get(tool_name)
        if tool is not None:
            schema = getattr(tool, "input_schema", {}) or {}
            for k, v in args.items():
                if _is_template(v):
                    continue  # Can't type-check until runtime substitution.
                expected = _schema_expected(schema, k)
                if expected is None:
                    continue
                actual = _argtype(v)
                # JSON-schema "integer" subsumes "number" for our purpose.
                if expected == "integer":
                    expected = "number"
                if expected == "number" and actual == "number":
                    continue
                if expected != actual:
                    report.errors.append(ValidationError(
                        node_id=nid, field=f"arguments.{k}",
                        message=f"Argument '{k}' should be {expected} but got {actual}",
                        suggestion=f"Update the value so its JSON type matches the tool schema.",
                    ))

        # A string like "Run for {{parse.response.features}}" that expects a
        # literal but references an object — flag it as a likely bug.
        for k, v in args.items():
            if not isinstance(v, str):
                continue
            refs = _extract_template_refs(v)
            if len(refs) == 1 and v.strip() == "{{" + refs[0] + "}}":
                # Whole-value template — OK for any type.
                continue
            # Embedded template inside a larger string — warn if the reference
            # is likely to be an object/array (ends in common container paths).
            for ref in refs:
                tail = ref.split(".")[-1]
                if tail in {"features", "items", "messages", "probabilities", "nodes"}:
                    report.warnings.append(ValidationError(
                        node_id=nid, field=f"arguments.{k}",
                        severity="warning",
                        message=f"Template {{{{{ref}}}}} is interpolated into a string but likely references a container",
                        suggestion=f"If '{tail}' is a list/object, use it as the whole value "
                                   f"(e.g. {k}: \"{{{{{ref}}}}}\") or serialize it via a code_executor step first.",
                    ))

        cost = _TOOL_COST_HINTS.get(tool_name)
        if cost is None:
            cost = 0.01  # Unknown custom tool — budget a small default.
        if tool_name == "agent_step":
            # Sub-agents burn more budget.
            cost = float(cost) * float(n.get("arguments", {}).get("max_iterations", 5)) / 5.0
        report.node_cost_breakdown[nid] = cost
        report.cost_estimate_usd += cost

    referenced: set[str] = set()
    for n in nodes:
        for dep in (n.get("depends_on") or []):
            referenced.add(dep)
        refs = _extract_template_refs(n.get("arguments", {}))
        for r in refs:
            head = r.split(".")[0]
            if head in node_by_id:
                referenced.add(head)
    # Treat the last non-referenced node as "output" — don't flag it.
    all_ids = list(node_by_id.keys())
    if all_ids:
        referenced.add(all_ids[-1])
    for nid in all_ids:
        if nid not in referenced:
            report.warnings.append(ValidationError(
                node_id=nid, field="",
                severity="warning",
                message=f"Node '{nid}' output is never consumed by any downstream node",
                suggestion="Either wire this node into a downstream node via depends_on or a template, or remove it.",
            ))
            report.unused_nodes.append(nid)

    for n in nodes:
        nid = n.get("id", "")
        tool_name = n.get("tool") or n.get("tool_name") or ""
        if tool_name in {"http_client", "web_request"}:
            url = (n.get("arguments", {}) or {}).get("url", "")
            if isinstance(url, str) and url and not url.startswith(("http://", "https://", "{{")):
                report.errors.append(ValidationError(
                    node_id=nid, field="arguments.url",
                    message=f"URL '{url}' does not use http(s) — likely a typo or SSRF risk",
                    suggestion="URLs must start with http:// or https://. Templates are allowed: {{node.url}}.",
                ))
            if isinstance(url, str) and url.startswith("http://localhost"):
                report.warnings.append(ValidationError(
                    node_id=nid, field="arguments.url",
                    severity="warning",
                    message="URL points at localhost — fine for dev but will break in production",
                    suggestion="Use a configurable env var or the gateway URL so the pipeline is portable.",
                ))

    if report.cost_estimate_usd > 0.5:
        report.warnings.append(ValidationError(
            node_id="", field="__pipeline__",
            severity="warning",
            message=f"Estimated cost per run: ${report.cost_estimate_usd:.2f}",
            suggestion="Consider consolidating LLM calls, caching results, or using smaller models.",
        ))

    return report
