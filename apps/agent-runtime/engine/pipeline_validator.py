"""Pipeline validation — catch configuration errors before execution."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from engine.tools.base import ToolRegistry


@dataclass
class ValidationError:
    """A single pipeline configuration error."""

    node_id: str
    field: str
    message: str
    severity: str = "error"  # "error" | "warning"
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
            "suggestion": self.suggestion,
        }


@dataclass
class ValidationResult:
    """Full result of validating a pipeline."""

    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }


# Common context variables that the executor auto-injects
_AUTO_INJECTED_CONTEXT_KEYS = {
    "user_message", "message", "input", "prompt", "content",
    "text", "ticket_content", "query", "request",
}

# Pipeline node tool names that don't have to appear in the agent's
# `tools: [...]` declaration — the executor resolves them directly.
# Exposed for the AI builder so both the normalizer and the judge agree
# on what "declared" means.
BUILTIN_TOOLS: set[str] = {
    "wait", "state_get", "state_set", "for_each", "while_loop",
    "switch", "parallel", "merge", "conditional", "data_merger",
    "loop", "branch", "__switch__", "__merge__",
    # Engine DSL — `type: structured` parses to this tool_name. Pure
    # output-assembly node, no registry lookup. Validator must treat
    # it as a known tool or it reports "Unknown tool '__structured__'"
    # for every pipeline that uses a final_report block.
    "__structured__",
}

# Template pattern: {{node_id.field}} or {{context.var}}
_TEMPLATE_PATTERN = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")


def _normalise_dsl_node(n: dict[str, Any]) -> dict[str, Any]:
    """Mirror parse_pipeline_nodes' DSL → low-level translation."""
    if not isinstance(n, dict):
        return n
    node_type = str(n.get("type") or "").strip().lower()
    if not node_type:
        return n
    normalised = dict(n)
    args = dict(n.get("arguments") or {})
    if node_type == "agent":
        normalised["tool_name"] = n.get("tool_name") or "agent_step"
        if "input" in n and "input_message" not in args:
            args["input_message"] = n["input"]
        ctx = n.get("context")
        if ctx and "__context__" not in args:
            args["__context__"] = ctx
    elif node_type == "structured":
        normalised["tool_name"] = "__structured__"
        out = n.get("output") or n.get("fields") or {}
        if isinstance(out, dict):
            args.update(out)
    elif node_type == "tool":
        if "tool_name" not in normalised and n.get("tool"):
            normalised["tool_name"] = n["tool"]
        ipt = n.get("input")
        if isinstance(ipt, dict):
            args.update(ipt)
        elif ipt is not None and "input" not in args:
            args["input"] = ipt
    normalised["arguments"] = args
    return normalised


def _extract_template_refs(value: Any) -> list[str]:
    """Extract all {{node.field}} references from a value (recursive)."""
    refs: list[str] = []
    if isinstance(value, str):
        refs.extend(_TEMPLATE_PATTERN.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            refs.extend(_extract_template_refs(v))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_extract_template_refs(item))
    return refs


def validate_pipeline(
    nodes: list[dict[str, Any]],
    tool_registry: ToolRegistry,
    available_context_keys: set[str] | None = None,
) -> ValidationResult:
    """Validate a pipeline node graph."""
    errors: list[ValidationError] = []
    warnings: list[ValidationError] = []

    if not nodes:
        errors.append(ValidationError(
            node_id="", field="nodes",
            message="Pipeline has no nodes",
            suggestion="Add at least one node to the pipeline.",
        ))
        return ValidationResult(valid=False, errors=errors, warnings=warnings)

    nodes = [_normalise_dsl_node(n) for n in nodes]

    node_ids: set[str] = set()
    for idx, n in enumerate(nodes):
        nid = n.get("id") or ""
        if not nid:
            errors.append(ValidationError(
                node_id=f"node_{idx}", field="id",
                message=f"Node at index {idx} is missing 'id'",
                suggestion="Add a unique 'id' field like 'classify' or 'step_1'.",
            ))
            continue
        if nid in node_ids:
            errors.append(ValidationError(
                node_id=nid, field="id",
                message=f"Duplicate node id '{nid}'",
                suggestion="Every node must have a unique id.",
            ))
        node_ids.add(nid)

        tool_name = n.get("tool") or n.get("tool_name")
        if not tool_name:
            errors.append(ValidationError(
                node_id=nid, field="tool",
                message="Node is missing 'tool' field",
                suggestion="Specify which tool this node should use, e.g. 'tool: llm_call'.",
            ))
            continue

        # Built-ins live in the module-level BUILTIN_TOOLS constant so the
        # AI builder's normalizer + judge can import the same set.
        if tool_name not in BUILTIN_TOOLS and tool_registry.get(tool_name) is None:
            errors.append(ValidationError(
                node_id=nid, field="tool",
                message=f"Unknown tool '{tool_name}'",
                suggestion=f"Check spelling. Available tools: {', '.join(sorted(tool_registry.names())[:10])}...",
            ))
            continue

        tool = tool_registry.get(tool_name)
        if tool is not None:
            schema = getattr(tool, "input_schema", {}) or {}
            required_fields = schema.get("required", [])
            args = n.get("arguments", {}) or {}
            input_mappings = n.get("input_mappings", {}) or {}

            has_agent_slug = bool(n.get("agent_slug"))
            has_node_input = n.get("input") is not None

            for req_field in required_fields:
                has_arg = req_field in args or req_field in input_mappings
                auto_injected = req_field in _AUTO_INJECTED_CONTEXT_KEYS
                # agent_step required fields (system_prompt, input_message)
                # are satisfied by agent_slug lookup / node-level input.
                if tool_name == "agent_step" and req_field in ("system_prompt", "input_message"):
                    if has_agent_slug or has_node_input:
                        continue
                if not has_arg and not auto_injected:
                    errors.append(ValidationError(
                        node_id=nid, field=f"arguments.{req_field}",
                        message=f"Missing required argument '{req_field}' for tool '{tool_name}'",
                        suggestion=f"Add '{req_field}: <value>' to this node's arguments. "
                                   f"You can reference other nodes with {{{{node_id.field}}}} "
                                   f"or context with {{{{context.var}}}}.",
                    ))

    for n in nodes:
        nid = n.get("id", "")
        depends = n.get("depends_on", []) or []
        for dep in depends:
            if dep not in node_ids:
                errors.append(ValidationError(
                    node_id=nid, field="depends_on",
                    message=f"Node depends on '{dep}' which does not exist",
                    suggestion=f"Check the node ID. Existing nodes: {', '.join(sorted(node_ids))}",
                ))

    def _has_cycle() -> tuple[bool, list[str]]:
        color = {nid: "white" for nid in node_ids}
        path: list[str] = []

        def _visit(nid: str) -> bool:
            if color.get(nid) == "gray":
                return True  # Cycle found
            if color.get(nid) == "black":
                return False
            color[nid] = "gray"
            path.append(nid)
            node = next((x for x in nodes if x.get("id") == nid), None)
            if node:
                for dep in (node.get("depends_on") or []):
                    if _visit(dep):
                        return True
            path.pop()
            color[nid] = "black"
            return False

        for nid in list(node_ids):
            if color[nid] == "white" and _visit(nid):
                return True, path
        return False, []

    cycle, cycle_path = _has_cycle()
    if cycle:
        errors.append(ValidationError(
            node_id=cycle_path[-1] if cycle_path else "",
            field="depends_on",
            message=f"Circular dependency detected: {' -> '.join(cycle_path)}",
            suggestion="Remove the dependency that creates the cycle. Pipelines must be acyclic (DAG).",
        ))

    ctx_keys = _AUTO_INJECTED_CONTEXT_KEYS | (available_context_keys or set())
    for n in nodes:
        nid = n.get("id", "")
        refs = _extract_template_refs(n.get("arguments", {}))
        for ref in refs:
            parts = ref.split(".", 1)
            target = parts[0]
            if target == "context":
                # {{context.var}} — check the var name
                if len(parts) > 1 and parts[1].split(".")[0] not in ctx_keys:
                    warnings.append(ValidationError(
                        node_id=nid, field="arguments",
                        severity="warning",
                        message=f"Template {{{{{ref}}}}} references unknown context variable '{parts[1].split('.')[0]}'",
                        suggestion=f"Available context: {', '.join(sorted(ctx_keys))}. "
                                   f"Define this variable in agent.input_variables or pass it at execution time.",
                    ))
            elif target in node_ids:
                pass  # references a real node — OK
            elif target in ctx_keys:
                pass  # flat context var (e.g. {{message}}) — OK, executor resolves these
            else:
                errors.append(ValidationError(
                    node_id=nid, field="arguments",
                    message=f"Template {{{{{ref}}}}} references unknown node or context variable '{target}'",
                    suggestion=(
                        f"Known nodes: {', '.join(sorted(node_ids)) or '(none)'}. "
                        f"Known context vars: {', '.join(sorted(ctx_keys))}. "
                        f"If '{target}' is an input variable, add it to the agent's input_variables."
                    ),
                ))

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)
