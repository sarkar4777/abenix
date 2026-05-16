"""DAG-based pipeline executor with conditional branching and data flow."""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from engine.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class NodeCondition:
    """Gate a node's execution on a previous node's output."""

    source_node: str
    field: str
    operator: str  # eq, neq, gt, lt, gte, lte, contains, not_contains, in, not_in
    value: Any

    def evaluate(self, node_outputs: dict[str, Any]) -> bool:
        source = node_outputs.get(self.source_node)
        if source is None:
            return False

        actual = _extract_field(source, self.field)
        if actual is None and self.operator not in ("eq", "neq"):
            return False

        ops = {
            "eq": lambda a, b: a == b,
            "neq": lambda a, b: a != b,
            "gt": lambda a, b: float(a) > float(b),
            "lt": lambda a, b: float(a) < float(b),
            "gte": lambda a, b: float(a) >= float(b),
            "lte": lambda a, b: float(a) <= float(b),
            "contains": lambda a, b: str(b) in str(a),
            "not_contains": lambda a, b: str(b) not in str(a),
            "in": lambda a, b: a in b,
            "not_in": lambda a, b: a not in b,
        }
        fn = ops.get(self.operator)
        if fn is None:
            logger.warning("Unknown condition operator: %s", self.operator)
            return False

        try:
            return fn(actual, self.value)
        except (TypeError, ValueError):
            return False


@dataclass
class InputMapping:
    """Pipe a field from a previous node's output into this node's arguments."""

    source_node: str
    source_field: str  # dot-path key, or "__all__" for entire output


@dataclass
class ForEachConfig:
    """Configure iteration over a list from an upstream node's output."""

    source_node: str
    source_field: str
    item_variable: str = "current_item"
    max_concurrency: int = 10


@dataclass
class WhileLoopConfig:
    """Loop a set of body nodes while a condition is true."""

    condition: NodeCondition
    body_nodes: list[str]  # node IDs to re-execute each iteration
    max_iterations: int = 50


@dataclass
class SwitchCase:
    """A single case in a switch routing decision."""

    operator: str
    value: Any
    target_node: str  # node ID to activate when this case matches


@dataclass
class SwitchConfig:
    """Route to one of N branches based on an upstream value."""

    source_node: str
    field: str
    cases: list[SwitchCase] = field(default_factory=list)
    default_node: str | None = None


@dataclass
class MergeConfig:
    """Recombine outputs from multiple upstream branches."""

    mode: str = "append"  # "append" | "zip" | "join"
    join_field: str | None = None  # for "join" mode
    source_nodes: list[str] = field(default_factory=list)


@dataclass
class PipelineNode:
    """A single node in the pipeline DAG."""

    id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    condition: NodeCondition | None = None
    input_mappings: dict[str, InputMapping] = field(default_factory=dict)
    max_retries: int = 0
    retry_delay_ms: int = 1000
    for_each: ForEachConfig | None = None
    while_loop: WhileLoopConfig | None = None
    timeout_seconds: int | None = None  # per-node timeout (None = use pipeline default)
    on_error: str = "stop"  # "stop" | "continue" | "error_branch"
    error_branch_node: str | None = None  # node ID to route to on failure
    switch: SwitchConfig | None = None
    merge: MergeConfig | None = None
    agent_slug: str | None = None
    # When set, this node is a pure output-assembly step: it template-
    # resolves its `arguments` against node_outputs and returns them as a
    # single dict, with no tool call. Lets pipelines declare a final
    # `final_report` shape without a dummy tool.
    structured_output: bool = False


@dataclass
class NodeResult:
    """Outcome of a single pipeline node."""

    node_id: str
    status: str  # completed, skipped, failed, timeout
    output: Any = None
    duration_ms: int = 0
    error: str | None = None
    error_message: str | None = None  # Detailed error text
    error_type: str | None = (
        None  # "timeout" | "tool_error" | "llm_error" | "validation" | exception class name
    )
    condition_evaluated: bool = False
    condition_met: bool | None = None
    tool_name: str = ""
    resolved_arguments: dict[str, Any] = field(default_factory=dict)
    attempt: int = 1


@dataclass
class PipelineResult:
    """Outcome of the full pipeline."""

    status: str  # completed, partial, failed
    node_results: dict[str, NodeResult] = field(default_factory=dict)
    execution_path: list[str] = field(default_factory=list)
    skipped_nodes: list[str] = field(default_factory=list)
    failed_nodes: list[str] = field(default_factory=list)
    total_duration_ms: int = 0
    final_output: Any = None
    node_errors: dict[str, str] = field(default_factory=dict)  # {node_id: error_msg}


_MD_JSON_FENCE = __import__("re").compile(
    r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```",
    __import__("re").DOTALL,
)


def _strip_markdown_fence(text: str) -> str:
    """Unwrap ```...``` code fences that LLMs wrap JSON outputs in."""
    m = _MD_JSON_FENCE.search(text)
    return m.group(1) if m else text


def _try_parse_json_ish(text: str) -> Any:
    """Best-effort JSON parse for LLM output."""
    candidate = _strip_markdown_fence(text).strip()
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: scan for the first balanced {...} / [...] block.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(candidate)):
            ch = candidate[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(candidate[start : i + 1])
                    except (json.JSONDecodeError, TypeError):
                        break
    return None


def _extract_field(data: Any, field_path: str) -> Any:
    """Extract a value from nested dict/str using dot-notation path."""
    if field_path == "__all__":
        if isinstance(data, dict) and isinstance(
            data.get("response"), (str, dict, list)
        ):
            resp = data["response"]
            if isinstance(resp, str):
                parsed = _try_parse_json_ish(resp)
                if parsed is not None:
                    return parsed
            else:
                return resp
        return data

    # If data is a string, try to parse it as JSON (tolerating markdown
    # fences + trailing prose that LLMs love to append).
    if isinstance(data, str):
        parsed = _try_parse_json_ish(data)
        if parsed is not None:
            data = parsed
        else:
            return data if not field_path else None

    # Path-walk helper kept inline so we can re-try on a nested response.
    def _walk(obj: Any, path: str) -> Any:
        parts = path.split(".")
        current = obj
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, (list, tuple)) and part.isdigit():
                idx = int(part)
                current = current[idx] if idx < len(current) else None
            else:
                return None
            if current is None:
                return None
        return current

    direct = _walk(data, field_path)
    if direct is not None:
        return direct

    # agent_step wrapper: {"response": "<json>", "cost": …, "model": …}.
    # When the top-level dict doesn't carry the field, fall through to
    # the `response` payload. Works for both JSON-string responses and
    # already-parsed dicts.
    if isinstance(data, dict) and isinstance(data.get("response"), (str, dict, list)):
        resp = data["response"]
        if isinstance(resp, str):
            resp = _try_parse_json_ish(resp)
        if resp is not None:
            return _walk(resp, field_path)

    return None


def _topological_sort(nodes: list[PipelineNode]) -> list[list[str]]:
    """Return layers of node IDs that can be executed in parallel."""
    {n.id: n for n in nodes}
    in_degree: dict[str, int] = {n.id: 0 for n in nodes}
    adjacency: dict[str, list[str]] = {n.id: [] for n in nodes}

    for node in nodes:
        for dep in node.depends_on:
            if dep in adjacency:
                adjacency[dep].append(node.id)
                in_degree[node.id] += 1

    layers: list[list[str]] = []
    queue = [nid for nid, deg in in_degree.items() if deg == 0]

    while queue:
        layers.append(sorted(queue))  # sort for determinism
        next_queue: list[str] = []
        for nid in queue:
            for child in adjacency[nid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    next_queue.append(child)
        queue = next_queue

    executed = sum(len(layer) for layer in layers)
    if executed != len(nodes):
        missing = set(n.id for n in nodes) - set(
            nid for layer in layers for nid in layer
        )
        raise ValueError(f"Cycle detected in pipeline DAG. Nodes in cycle: {missing}")

    return layers


def _resolve_inputs(
    node: PipelineNode,
    node_outputs: dict[str, Any],
) -> dict[str, Any]:
    """Merge input_mappings into the node's base arguments."""
    resolved = dict(node.arguments)

    for arg_name, mapping in node.input_mappings.items():
        source_output = node_outputs.get(mapping.source_node)
        if source_output is None:
            continue
        value = _extract_field(source_output, mapping.source_field)
        if value is not None:
            resolved[arg_name] = value

    return resolved


def _resolve_templates(
    arguments: dict[str, Any],
    node_outputs: dict[str, Any],
) -> dict[str, Any]:
    """Replace {{node_id.field}} template variables in string arguments."""
    import re as _re

    pattern = _re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")
    resolved = {}

    for key, value in arguments.items():
        if isinstance(value, str) and "{{" in value:
            # Whole-value template ({{plan.actions}}) — keep the extracted
            # object as-is so downstream nodes / structured outputs get a
            # list/dict, not its Python repr. Embedded templates in a
            # longer string fall back to str() coercion.
            whole = pattern.fullmatch(value)
            if whole is not None:
                path = whole.group(1)
                parts = path.split(".", 1)
                node_id = parts[0]
                field = parts[1] if len(parts) > 1 else "__all__"
                source = node_outputs.get(node_id)
                extracted = None if source is None else _extract_field(source, field)
                resolved[key] = "[not available]" if extracted is None else extracted
                continue

            def _replacer(match: _re.Match) -> str:
                path = match.group(1)
                parts = path.split(".", 1)
                node_id = parts[0]
                field = parts[1] if len(parts) > 1 else "__all__"
                source = node_outputs.get(node_id)
                if source is None:
                    return "[not available]"  # Node was skipped or hasn't run
                extracted = _extract_field(source, field)
                if extracted is None:
                    return "[not available]"
                # Inline inside a larger string: use JSON so lists/dicts
                # don't show up as Python repr (single-quoted keys).
                if isinstance(extracted, (dict, list)):
                    try:
                        return json.dumps(extracted, default=str)
                    except (TypeError, ValueError):
                        return str(extracted)
                return str(extracted)

            resolved[key] = pattern.sub(_replacer, value)
        else:
            resolved[key] = value

    return resolved


class PipelineExecutor:
    """Execute a DAG of tool calls with conditions and data piping."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        timeout_seconds: int = 120,
        on_node_start: Callable[..., Any] | None = None,
        on_node_complete: Callable[..., Any] | None = None,
        cost_limit: float | None = None,
        db_url: str = "",
        agent_id: str = "",
        tenant_id: str = "",
    ) -> None:
        self.tool_registry = tool_registry
        self.timeout_seconds = timeout_seconds
        self.on_node_start = on_node_start
        self.on_node_complete = on_node_complete
        self.cost_limit = cost_limit
        self.accumulated_cost: float = 0.0
        self._db_url = db_url
        self._agent_id = agent_id
        self._tenant_id = tenant_id

    async def _fire_callback(
        self,
        callback: Callable[..., Any] | None,
        *args: Any,
    ) -> None:
        """Safely invoke a callback, awaiting it if it is a coroutine function."""
        if callback is None:
            return
        try:
            if inspect.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception:
            logger.debug("Streaming callback raised an exception", exc_info=True)

    async def execute(
        self,
        nodes: list[PipelineNode],
        context: dict[str, Any] | None = None,
    ) -> PipelineResult:
        start = time.monotonic()
        context = context or {}

        node_map = {n.id: n for n in nodes}
        node_outputs: dict[str, Any] = {}
        # Store context under "context" key so templates like {{context.message}} resolve
        node_outputs["context"] = context
        # `input` alias — lets pipeline yaml reference the initial payload
        # the same way it references upstream node outputs ({{input.message}},
        # {{input.customer_tier}}). Mirrors what the DSL-style pipelines
        # (type:agent, agent_slug, input) expect.
        input_alias = dict(context)
        # common fallbacks: expose the user message under .message even
        # when callers supplied it under user_message / prompt / body.
        if "message" not in input_alias:
            for k in ("user_message", "prompt", "body", "ticket_content", "content"):
                if k in input_alias:
                    input_alias["message"] = input_alias[k]
                    break
        node_outputs["input"] = input_alias
        # Also store flat for backward compatibility ({{user_message}}, etc.)
        node_outputs.update(context)
        results: dict[str, NodeResult] = {}
        execution_path: list[str] = []
        skipped_nodes: list[str] = []
        failed_nodes: list[str] = []

        try:
            layers = _topological_sort(nodes)
        except ValueError as e:
            return PipelineResult(
                status="failed",
                total_duration_ms=int((time.monotonic() - start) * 1000),
                final_output={"error": str(e)},
            )

        for layer in layers:
            elapsed = time.monotonic() - start
            if elapsed > self.timeout_seconds:
                for nid in layer:
                    results[nid] = NodeResult(
                        node_id=nid,
                        status="failed",
                        error="Pipeline timeout exceeded",
                        error_message=f"Pipeline timeout exceeded after {int(elapsed)}s (limit: {self.timeout_seconds}s)",
                        error_type="timeout",
                        tool_name=node_map[nid].tool_name,
                    )
                    failed_nodes.append(nid)
                break

            # Separate for_each / while_loop nodes from regular nodes
            regular_tasks: list[tuple[str, asyncio.Task[NodeResult]]] = []
            for_each_tasks: list[tuple[str, asyncio.Task[NodeResult]]] = []

            for nid in layer:
                node = node_map[nid]
                if node.for_each is not None:
                    task = asyncio.create_task(
                        self._execute_for_each_node(node, node_outputs, results)
                    )
                    for_each_tasks.append((nid, task))
                elif node.while_loop is not None:
                    task = asyncio.create_task(
                        self._execute_while_loop_node(
                            node, node_outputs, node_map, results
                        )
                    )
                    regular_tasks.append((nid, task))
                else:
                    task = asyncio.create_task(
                        self._execute_node(node, node_outputs, results)
                    )
                    regular_tasks.append((nid, task))

            # Await all tasks together
            all_tasks = regular_tasks + for_each_tasks
            all_coros = [t for _, t in all_tasks]
            layer_results = await asyncio.gather(*all_coros)

            # Dynamic nodes to add to the next layer (e.g., error branches)
            dynamic_next: list[str] = []

            for (nid, _), result in zip(all_tasks, layer_results):
                results[nid] = result
                node = node_map[nid]

                if result.status == "completed":
                    execution_path.append(nid)
                    node_outputs[nid] = result.output

                    # Handle switch routing: mark target nodes for activation
                    if node.switch and isinstance(result.output, dict):
                        matched_targets = result.output.get("__switch_targets", [])
                        for target_id in matched_targets:
                            node_outputs[f"__switch_activated_{target_id}"] = True

                elif result.status == "skipped":
                    skipped_nodes.append(nid)
                    node_outputs[nid] = None
                else:
                    # Node failed
                    if node.on_error == "continue":
                        # Treat as completed with error info so dependents can proceed
                        execution_path.append(nid)
                        node_outputs[nid] = {
                            "__error_continue": True,
                            "error": result.error,
                            "status": "failed",
                        }
                    elif node.on_error == "error_branch" and node.error_branch_node:
                        failed_nodes.append(nid)
                        # Inject error context for the error branch node
                        node_outputs[f"__error_from_{nid}"] = {
                            "error": result.error,
                            "failed_node": nid,
                            "tool_name": result.tool_name,
                        }
                        # Schedule error branch node for next layer if not already scheduled
                        if (
                            node.error_branch_node in node_map
                            and node.error_branch_node not in results
                        ):
                            dynamic_next.append(node.error_branch_node)
                    else:
                        failed_nodes.append(nid)
                        # Self-healing capture — best-effort, fire-and-forget
                        # so a slow DB never delays the user-visible error.
                        if self._db_url and self._tenant_id and self._agent_id:
                            try:
                                from engine.healing import (
                                    capture_failure,
                                    fire_and_forget,
                                )

                                fire_and_forget(
                                    capture_failure(
                                        db_url=self._db_url,
                                        tenant_id=self._tenant_id,
                                        pipeline_id=self._agent_id,
                                        execution_id=context.get(
                                            "__execution_id",
                                            "00000000-0000-0000-0000-000000000000",
                                        ),
                                        node_id=nid,
                                        node_kind=(
                                            "agent" if node.agent_slug else "tool"
                                        ),
                                        node_target=(node.agent_slug or node.tool_name),
                                        error_class=(
                                            result.error_type or "PipelineError"
                                        ),
                                        error_message=(
                                            result.error_message or result.error or ""
                                        ),
                                        error_traceback=None,
                                        upstream_inputs={
                                            k: node_outputs.get(k)
                                            for k in node.depends_on
                                            if k in node_outputs
                                        },
                                        observed_sample=result.output,
                                    )
                                )
                            except Exception as _he:
                                logger.debug("healing capture skipped: %s", _he)

            # Process any dynamically activated error branch nodes
            if dynamic_next:
                for eb_nid in dynamic_next:
                    eb_node = node_map[eb_nid]
                    eb_result = await self._execute_node(eb_node, node_outputs, results)
                    results[eb_nid] = eb_result
                    if eb_result.status == "completed":
                        execution_path.append(eb_nid)
                        node_outputs[eb_nid] = eb_result.output
                    elif eb_result.status == "skipped":
                        skipped_nodes.append(eb_nid)
                    else:
                        failed_nodes.append(eb_nid)

        total_ms = int((time.monotonic() - start) * 1000)

        # Determine final output: last completed node's output
        final_output = None
        for nid in reversed(execution_path):
            if results[nid].status == "completed":
                final_output = results[nid].output
                break

        status = "completed"
        if failed_nodes:
            status = "failed" if not execution_path else "partial"

        # Aggregate error messages from failed nodes
        node_errors = {
            nid: r.error_message or r.error or "Unknown error"
            for nid, r in results.items()
            if r.status == "failed" and (r.error_message or r.error)
        }

        return PipelineResult(
            status=status,
            node_results=results,
            execution_path=execution_path,
            skipped_nodes=skipped_nodes,
            failed_nodes=failed_nodes,
            total_duration_ms=total_ms,
            final_output=final_output,
            node_errors=node_errors,
        )

    async def _execute_node(
        self,
        node: PipelineNode,
        node_outputs: dict[str, Any],
        prior_results: dict[str, NodeResult],
    ) -> NodeResult:
        """Execute a node with retry logic and streaming callbacks."""
        # Fire on_node_start callback
        await self._fire_callback(self.on_node_start, node.id, node.tool_name)

        result: NodeResult | None = None
        max_attempts = node.max_retries + 1

        for attempt in range(max_attempts):
            result = await self._execute_node_once(node, node_outputs, prior_results)
            result.attempt = attempt + 1

            # Only retry on "failed" status -- NOT on "skipped"
            if result.status != "failed" or attempt >= max_attempts - 1:
                break

            # Wait with exponential backoff before retrying
            delay_s = (node.retry_delay_ms / 1000) * (2**attempt)
            logger.debug(
                "Retrying node %s (attempt %d/%d) after %.2fs",
                node.id,
                attempt + 2,
                max_attempts,
                delay_s,
            )
            await asyncio.sleep(delay_s)

        # Fire on_node_complete callback
        assert result is not None
        await self._fire_callback(
            self.on_node_complete,
            result.node_id,
            result.status,
            result.duration_ms,
            result.output,
            result.error_message,
            result.error_type,
        )

        return result

    async def _execute_node_once(
        self,
        node: PipelineNode,
        node_outputs: dict[str, Any],
        prior_results: dict[str, NodeResult],
    ) -> NodeResult:
        node_start = time.monotonic()

        # Check if dependencies that were required actually completed
        for dep_id in node.depends_on:
            dep_result = prior_results.get(dep_id)
            if dep_result is None:
                continue
            if dep_result.status == "failed":
                for n in [n for n in prior_results]:
                    pass  # node_map not available here, check via depends_on
                # If the failed dependency has on_error="continue", propagate error info instead of skipping
                # We check the original node config via the id match in prior_results
                # For simplicity, we use a convention: if the failed dep's output contains
                # {"__error_continue": True}, it means on_error=continue was set
                if (
                    dep_result.output
                    and isinstance(dep_result.output, dict)
                    and dep_result.output.get("__error_continue")
                ):
                    continue  # Allow this node to proceed with error info available
                return NodeResult(
                    node_id=node.id,
                    status="skipped",
                    error=f"Dependency '{dep_id}' failed",
                    tool_name=node.tool_name,
                    duration_ms=int((time.monotonic() - node_start) * 1000),
                )

        # Evaluate condition
        if node.condition is not None:
            met = node.condition.evaluate(node_outputs)
            if not met:
                return NodeResult(
                    node_id=node.id,
                    status="skipped",
                    tool_name=node.tool_name,
                    condition_evaluated=True,
                    condition_met=False,
                    duration_ms=int((time.monotonic() - node_start) * 1000),
                )

        # Resolve input mappings, then substitute {{template}} variables
        resolved_args = _resolve_inputs(node, node_outputs)
        resolved_args = _resolve_templates(resolved_args, node_outputs)

        # Fallback: if common input args are missing or unresolved, pull from
        # the initial user_message in node_outputs (merged from context).
        # Handles seed pipelines that didn't explicitly map the user message.
        user_msg = (
            node_outputs.get("user_message")
            or node_outputs.get("ticket_content")
            or node_outputs.get("message")
            or node_outputs.get("input")
            or ""
        )
        if user_msg and isinstance(user_msg, str):
            _INPUT_KEYS = {
                "input_message",
                "input",
                "message",
                "prompt",
                "text",
                "content",
                "user_message",
            }
            for k, v in list(resolved_args.items()):
                if (
                    k in _INPUT_KEYS
                    and isinstance(v, str)
                    and v.strip()
                    in (
                        "",
                        "[not available]",
                    )
                ):
                    resolved_args[k] = user_msg
            # Inject content/text if not present and first node of the pipeline
            if "content" not in resolved_args and node.tool_name in (
                "structured_analyzer",
                "text_analyzer",
                "document_analyzer",
            ):
                resolved_args["content"] = user_msg

        req_if = resolved_args.pop("__required_if__", None)
        if req_if is not None:
            val = str(req_if).strip().lower()
            is_false = val in (
                "",
                "false",
                "0",
                "none",
                "null",
                "[]",
                "[not available]",
            )
            if is_false:
                return NodeResult(
                    node_id=node.id,
                    status="skipped",
                    tool_name=node.tool_name,
                    condition_evaluated=True,
                    condition_met=False,
                    duration_ms=int((time.monotonic() - node_start) * 1000),
                    resolved_arguments={"__required_if__": req_if},
                )

        # Built-in "__structured__" node — pure output assembly. Returns
        # the (already template-resolved) arguments as a dict, JSON-
        # parsing string values that look like JSON so downstream
        # consumers get typed data instead of serialised strings.
        if node.tool_name == "__structured__" or node.structured_output:
            out: dict[str, Any] = {}
            for k, v in resolved_args.items():
                if isinstance(v, str):
                    stripped = _strip_markdown_fence(v).strip()
                    # Try to parse JSON so e.g. citations=[...] stays a list
                    if (
                        stripped
                        and stripped[:1] in ("{", "[")
                        and stripped[-1:] in ("}", "]")
                    ):
                        try:
                            out[k] = json.loads(stripped)
                            continue
                        except (json.JSONDecodeError, TypeError):
                            pass
                    out[k] = v
                else:
                    out[k] = v
            return NodeResult(
                node_id=node.id,
                status="completed",
                output=out,
                duration_ms=int((time.monotonic() - node_start) * 1000),
                tool_name="__structured__",
                resolved_arguments=resolved_args,
            )

        # If this node was declared as `type: agent`, resolve the seeded
        # agent row and inline its system_prompt / tools / model into the
        # agent_step arguments. This lets pipeline YAMLs reference agents
        # by slug rather than duplicating the prompt.
        if node.agent_slug:
            agent_row = await self._resolve_agent_by_slug(node.agent_slug)
            if agent_row is None:
                return NodeResult(
                    node_id=node.id,
                    status="failed",
                    error=f"agent_slug '{node.agent_slug}' not found in DB",
                    error_message=f"agent_slug '{node.agent_slug}' not found in DB",
                    error_type="validation",
                    tool_name=node.tool_name,
                    resolved_arguments=resolved_args,
                    duration_ms=int((time.monotonic() - node_start) * 1000),
                )
            mcfg = agent_row.get("model_config") or {}
            # Agent's own system_prompt + model config beat pipeline-local
            # overrides so the agent behaves identically in pipeline or
            # direct-invoke mode.
            resolved_args.setdefault(
                "system_prompt", agent_row.get("system_prompt") or ""
            )
            resolved_args.setdefault(
                "model", mcfg.get("model") or "claude-sonnet-4-5-20250929"
            )
            if mcfg.get("tools") and "tools" not in resolved_args:
                resolved_args["tools"] = mcfg["tools"]
            if (
                mcfg.get("max_iterations") is not None
                and "max_iterations" not in resolved_args
            ):
                resolved_args["max_iterations"] = mcfg["max_iterations"]
            if (
                mcfg.get("temperature") is not None
                and "temperature" not in resolved_args
            ):
                resolved_args["temperature"] = mcfg["temperature"]
            # Fold node-level `context: {...}` into the input_message so
            # the agent sees upstream fields it was promised. agent_step's
            # schema doesn't take a context arg, so we append it.
            node_ctx = resolved_args.pop("__context__", None)
            if node_ctx:
                ctx_block = json.dumps(node_ctx, default=str, indent=2)
                im = resolved_args.get("input_message", "")
                resolved_args["input_message"] = (
                    f"{im}\n\n[Pipeline context]\n{ctx_block}"
                    if im
                    else f"[Pipeline context]\n{ctx_block}"
                )
            # Default input_message from the first user_msg if the pipeline
            # didn't declare one explicitly.
            if not resolved_args.get("input_message") and user_msg:
                resolved_args["input_message"] = user_msg

        # Built-in "wait" tool — no registry lookup needed
        if node.tool_name == "wait":
            seconds = min(float(resolved_args.get("seconds", 1)), 300)
            await asyncio.sleep(seconds)
            return NodeResult(
                node_id=node.id,
                status="completed",
                output={"waited_seconds": seconds},
                duration_ms=int(seconds * 1000),
                tool_name="wait",
            )

        # Built-in "state_get" — read persistent pipeline state
        if node.tool_name == "state_get":
            state_key = str(resolved_args.get("key", ""))
            state_val = await self._state_get(state_key)
            return NodeResult(
                node_id=node.id,
                status="completed",
                output=state_val,
                duration_ms=int((time.monotonic() - node_start) * 1000),
                tool_name="state_get",
                resolved_arguments=resolved_args,
            )

        # Built-in "state_set" — write persistent pipeline state
        if node.tool_name == "state_set":
            state_key = str(resolved_args.get("key", ""))
            state_value = resolved_args.get("value")
            await self._state_set(state_key, state_value)
            return NodeResult(
                node_id=node.id,
                status="completed",
                output={"key": state_key, "stored": True},
                duration_ms=int((time.monotonic() - node_start) * 1000),
                tool_name="state_set",
                resolved_arguments=resolved_args,
            )

        # Built-in "__merge__" node — combine outputs from upstream branches
        if node.tool_name == "__merge__" and node.merge is not None:
            merge_output = self._execute_merge(node.merge, node_outputs)
            return NodeResult(
                node_id=node.id,
                status="completed",
                output=merge_output,
                duration_ms=int((time.monotonic() - node_start) * 1000),
                tool_name="__merge__",
                resolved_arguments=resolved_args,
            )

        # Built-in "__switch__" node — route to one of N target nodes
        if node.tool_name == "__switch__" and node.switch is not None:
            switch_result = self._execute_switch(node.switch, node_outputs)
            return NodeResult(
                node_id=node.id,
                status="completed",
                output=switch_result,
                duration_ms=int((time.monotonic() - node_start) * 1000),
                tool_name="__switch__",
                resolved_arguments=resolved_args,
            )

        # Find and execute the tool
        tool = self.tool_registry.get(node.tool_name)
        if tool is None:
            # Try dynamic tool generation as last resort
            try:
                from engine.tools.dynamic_tool import generate_dynamic_tool

                dyn = await generate_dynamic_tool(
                    f"A tool called '{node.tool_name}' that performs: {node.tool_name.replace('_', ' ')}",
                    node.tool_name,
                )
                if dyn:
                    self.tool_registry.register(dyn)
                    tool = dyn
                    logger.info("Generated dynamic tool: %s", node.tool_name)
            except Exception:
                pass

        if tool is None:
            return NodeResult(
                node_id=node.id,
                status="failed",
                error=f"Unknown tool: {node.tool_name}",
                error_message=f"Unknown tool: {node.tool_name}",
                error_type="validation",
                tool_name=node.tool_name,
                resolved_arguments=resolved_args,
                duration_ms=int((time.monotonic() - node_start) * 1000),
            )

        # Inject pipeline context for code_executor nodes
        if node.tool_name == "code_executor":
            resolved_args["__pipeline_context__"] = {
                k: v
                for k, v in node_outputs.items()
                if not k.startswith("__") and k != "context"
            }

        try:
            # Check cost budget before executing
            if self.cost_limit and self.accumulated_cost >= self.cost_limit:
                return NodeResult(
                    node_id=node.id,
                    status="failed",
                    error=f"Cost budget exceeded (${self.accumulated_cost:.4f} >= ${self.cost_limit:.4f})",
                    error_message=f"Cost budget exceeded (${self.accumulated_cost:.4f} >= ${self.cost_limit:.4f})",
                    error_type="validation",
                    tool_name=node.tool_name,
                    resolved_arguments=resolved_args,
                    duration_ms=int((time.monotonic() - node_start) * 1000),
                )

            if node.timeout_seconds:
                result = await asyncio.wait_for(
                    tool.execute(resolved_args), timeout=node.timeout_seconds
                )
            else:
                result = await tool.execute(resolved_args)
            duration = int((time.monotonic() - node_start) * 1000)

            # Normalize result — some tools return raw dicts instead of ToolResult
            if isinstance(result, dict):
                from engine.tools.base import ToolResult

                is_err = "error" in result and result.get("error")
                result = ToolResult(
                    content=json.dumps(result, default=str),
                    is_error=bool(is_err),
                )

            # Track cost from tool execution metadata
            if hasattr(result, "metadata") and result.metadata.get("cost"):
                self.accumulated_cost += float(result.metadata["cost"])

            if result.is_error:
                return NodeResult(
                    node_id=node.id,
                    status="failed",
                    output=result.content,
                    error=result.content,
                    error_message=(
                        str(result.content)[:2000]
                        if result.content
                        else "Tool returned error"
                    ),
                    error_type="tool_error",
                    tool_name=node.tool_name,
                    resolved_arguments=resolved_args,
                    duration_ms=duration,
                    condition_evaluated=node.condition is not None,
                    condition_met=True if node.condition is not None else None,
                )

            # Try to parse output as JSON for downstream consumption
            try:
                parsed = json.loads(result.content)
            except (json.JSONDecodeError, TypeError):
                parsed = result.content

            return NodeResult(
                node_id=node.id,
                status="completed",
                output=parsed,
                tool_name=node.tool_name,
                resolved_arguments=resolved_args,
                duration_ms=duration,
                condition_evaluated=node.condition is not None,
                condition_met=True if node.condition is not None else None,
            )

        except asyncio.TimeoutError:
            return NodeResult(
                node_id=node.id,
                status="failed",
                error=f"Node timed out after {node.timeout_seconds}s",
                error_message=f"Node '{node.id}' timed out after {node.timeout_seconds}s",
                error_type="timeout",
                tool_name=node.tool_name,
                resolved_arguments=resolved_args,
                duration_ms=int((time.monotonic() - node_start) * 1000),
            )
        except Exception as e:
            return NodeResult(
                node_id=node.id,
                status="failed",
                error=str(e),
                error_message=str(e),
                error_type=type(e).__name__,
                tool_name=node.tool_name,
                resolved_arguments=resolved_args,
                duration_ms=int((time.monotonic() - node_start) * 1000),
            )

    async def _resolve_agent_by_slug(self, slug: str) -> dict[str, Any] | None:
        """Look up a seeded agent by slug and return its system_prompt +"""
        if not self._db_url:
            logger.warning(
                "_resolve_agent_by_slug: no DATABASE_URL set — cannot resolve '%s'",
                slug,
            )
            return None
        cache = getattr(self, "_agent_slug_cache", None)
        if cache is None:
            cache = {}
            self._agent_slug_cache = cache
        if slug in cache:
            return cache[slug]
        try:
            from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
            from sqlalchemy import text as _t

            engine = create_async_engine(self._db_url, echo=False)
            async with AsyncSession(engine) as session:
                res = await session.execute(
                    _t(
                        "SELECT system_prompt, model_config FROM agents WHERE slug = :slug LIMIT 1"
                    ).bindparams(slug=slug)
                )
                row = res.first()
                if row is None:
                    cache[slug] = None
                    return None
                sp, mcfg = row[0], row[1]
                if isinstance(mcfg, str):
                    try:
                        mcfg = json.loads(mcfg)
                    except Exception:
                        mcfg = {}
                cache[slug] = {"system_prompt": sp or "", "model_config": mcfg or {}}
                return cache[slug]
        except Exception as e:
            logger.warning("_resolve_agent_by_slug(%s) failed: %s", slug, e)
            return None

    async def _state_get(self, key: str) -> Any:
        """Read a value from persistent pipeline state (database)."""
        if not self._db_url or not self._agent_id:
            return None
        try:
            from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
            from sqlalchemy import select

            engine = create_async_engine(self._db_url, echo=False)
            async with AsyncSession(engine) as session:
                # Import here to avoid circular deps
                import sys
                from pathlib import Path

                sys.path.insert(
                    0, str(Path(__file__).resolve().parents[2] / "packages" / "db")
                )
                from models.pipeline_state import PipelineState

                result = await session.execute(
                    select(PipelineState.value).where(
                        PipelineState.agent_id == self._agent_id,
                        PipelineState.key == key,
                    )
                )
                row = result.scalar_one_or_none()
                return row if row else None
        except Exception as e:
            logger.warning("state_get failed for key=%s: %s", key, e)
            return None

    async def _state_set(self, key: str, value: Any) -> None:
        """Write a value to persistent pipeline state (database)."""
        if not self._db_url or not self._agent_id:
            return
        try:
            from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
            from sqlalchemy import select

            engine = create_async_engine(self._db_url, echo=False)
            async with AsyncSession(engine) as session:
                import sys
                from pathlib import Path

                sys.path.insert(
                    0, str(Path(__file__).resolve().parents[2] / "packages" / "db")
                )
                from models.pipeline_state import PipelineState

                result = await session.execute(
                    select(PipelineState).where(
                        PipelineState.agent_id == self._agent_id,
                        PipelineState.key == key,
                    )
                )
                existing = result.scalar_one_or_none()
                if existing:
                    existing.value = value
                else:
                    session.add(
                        PipelineState(
                            agent_id=self._agent_id,
                            tenant_id=self._tenant_id,
                            key=key,
                            value=value,
                        )
                    )
                await session.commit()
        except Exception as e:
            logger.warning("state_set failed for key=%s: %s", key, e)

    def _execute_merge(self, merge: MergeConfig, node_outputs: dict[str, Any]) -> Any:
        """Execute a merge operation combining outputs from multiple source nodes."""
        sources = [
            node_outputs.get(src) for src in merge.source_nodes if src in node_outputs
        ]
        # Filter out None (skipped nodes)
        sources = [s for s in sources if s is not None]

        if merge.mode == "append":
            # Concatenate all outputs into a flat list
            merged: list[Any] = []
            for s in sources:
                if isinstance(s, list):
                    merged.extend(s)
                else:
                    merged.append(s)
            return merged

        elif merge.mode == "zip":
            # Pair outputs positionally
            if all(isinstance(s, list) for s in sources):
                return [dict(enumerate(pair)) for pair in zip(*sources)]
            return sources

        elif merge.mode == "join" and merge.join_field:
            # Inner join by matching field
            if len(sources) < 2:
                return sources[0] if sources else []
            base = sources[0] if isinstance(sources[0], list) else [sources[0]]
            for other_source in sources[1:]:
                other_list = (
                    other_source if isinstance(other_source, list) else [other_source]
                )
                other_map: dict[Any, Any] = {}
                for item in other_list:
                    if isinstance(item, dict):
                        key = item.get(merge.join_field)
                        if key is not None:
                            other_map[key] = item
                joined: list[Any] = []
                for item in base:
                    if isinstance(item, dict):
                        key = item.get(merge.join_field)
                        if key in other_map:
                            joined.append({**item, **other_map[key]})
                base = joined
            return base

        return sources

    def _execute_switch(
        self, switch: SwitchConfig, node_outputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Evaluate switch cases and return routing decision."""
        source_output = node_outputs.get(switch.source_node)
        actual = _extract_field(source_output, switch.field)

        matched_targets: list[str] = []
        matched_target: str | None = None
        matched_value: Any = None

        condition_proxy = NodeCondition(
            source_node=switch.source_node,
            field=switch.field,
            operator="eq",
            value=None,
        )

        for case in switch.cases:
            condition_proxy.operator = case.operator
            condition_proxy.value = case.value
            if condition_proxy.evaluate(node_outputs):
                matched_targets.append(case.target_node)
                if matched_target is None:
                    matched_target = case.target_node
                    matched_value = case.value
                break  # First match wins

        if not matched_targets and switch.default_node:
            matched_targets.append(switch.default_node)
            matched_target = switch.default_node
            matched_value = "default"

        return {
            "route": matched_value,  # The value that matched (e.g., "billing"), not the target node
            "target_node": matched_target,  # Which node was activated
            "actual_value": actual,
            "__switch_targets": matched_targets,
        }

    async def _execute_for_each_node(
        self,
        node: PipelineNode,
        node_outputs: dict[str, Any],
        prior_results: dict[str, NodeResult],
    ) -> NodeResult:
        """Execute a node once per item in a list from an upstream node."""
        assert node.for_each is not None
        fe = node.for_each
        node_start = time.monotonic()

        # Extract the source list
        source_data = node_outputs.get(fe.source_node)
        items = _extract_field(source_data, fe.source_field)

        if not isinstance(items, list):
            err_msg = (
                f"for_each source '{fe.source_node}.{fe.source_field}' "
                f"is not a list (got {type(items).__name__})"
            )
            return NodeResult(
                node_id=node.id,
                status="failed",
                error=err_msg,
                error_message=err_msg,
                error_type="validation",
                tool_name=node.tool_name,
                duration_ms=int((time.monotonic() - node_start) * 1000),
            )

        if len(items) == 0:
            return NodeResult(
                node_id=node.id,
                status="completed",
                output=[],
                tool_name=node.tool_name,
                duration_ms=int((time.monotonic() - node_start) * 1000),
            )

        semaphore = asyncio.Semaphore(fe.max_concurrency)

        async def _run_item(item: Any, index: int) -> NodeResult:
            async with semaphore:
                # Create a copy of the node with the item injected
                item_node = copy.deepcopy(node)
                item_node.id = f"{node.id}[{index}]"
                item_node.arguments[fe.item_variable] = item
                # Clear for_each on the copy to avoid infinite recursion
                item_node.for_each = None
                return await self._execute_node(item_node, node_outputs, prior_results)

        item_results = await asyncio.gather(
            *[_run_item(item, idx) for idx, item in enumerate(items)]
        )

        duration = int((time.monotonic() - node_start) * 1000)
        outputs = [r.output for r in item_results]
        any_failed = any(r.status == "failed" for r in item_results)

        return NodeResult(
            node_id=node.id,
            status="partial" if any_failed else "completed",
            output=outputs,
            tool_name=node.tool_name,
            duration_ms=duration,
        )

    async def _execute_while_loop_node(
        self,
        node: PipelineNode,
        node_outputs: dict[str, Any],
        all_nodes: dict[str, PipelineNode],
        prior_results: dict[str, NodeResult],
    ) -> NodeResult:
        """Execute body nodes in a loop while condition is true."""
        wl = node.while_loop
        assert wl is not None
        start = time.monotonic()
        iteration = 0
        last_output = None

        while iteration < wl.max_iterations:
            # Evaluate condition
            if not wl.condition.evaluate(node_outputs):
                break

            iteration += 1
            logger.info("WhileLoop %s iteration %d", node.id, iteration)

            # Execute each body node in sequence
            for body_id in wl.body_nodes:
                body_node = all_nodes.get(body_id)
                if body_node is None:
                    continue
                body_result = await self._execute_node_once(
                    body_node, node_outputs, prior_results
                )
                if body_result.status == "completed":
                    node_outputs[body_id] = body_result.output
                    last_output = body_result.output
                prior_results[body_id] = body_result

        duration = int((time.monotonic() - start) * 1000)
        return NodeResult(
            node_id=node.id,
            status="completed",
            output={"iterations": iteration, "last_output": last_output},
            duration_ms=duration,
            tool_name="while_loop",
        )


_TEMPLATE_REF_RE = __import__("re").compile(r"\{\{(\w+(?:\.\w+)*)\}\}")


def _infer_template_deps(obj: Any, known_ids: set[str]) -> set[str]:
    """Walk a JSON-ish payload, returning every top-level identifier"""
    deps: set[str] = set()

    def _walk(v: Any) -> None:
        if isinstance(v, str):
            for m in _TEMPLATE_REF_RE.finditer(v):
                first = m.group(1).split(".", 1)[0]
                if first in known_ids:
                    deps.add(first)
        elif isinstance(v, dict):
            for sub in v.values():
                _walk(sub)
        elif isinstance(v, (list, tuple)):
            for sub in v:
                _walk(sub)

    _walk(obj)
    return deps


def parse_pipeline_nodes(raw_nodes: list[dict[str, Any]]) -> list[PipelineNode]:
    """Parse raw JSON/dict pipeline node definitions into PipelineNode objects."""
    nodes: list[PipelineNode] = []
    # Build the set of sibling ids up-front so template refs like
    # {{triage.intent}} can be traced back to a node called 'triage'.
    known_ids = {raw["id"] for raw in raw_nodes if "id" in raw}

    for raw in raw_nodes:
        condition = None
        if raw.get("condition"):
            c = raw["condition"]
            condition = NodeCondition(
                source_node=c["source_node"],
                field=c["field"],
                operator=c.get("operator", "eq"),
                value=c["value"],
            )

        input_mappings: dict[str, InputMapping] = {}
        for arg_name, mapping in raw.get("input_mappings", {}).items():
            input_mappings[arg_name] = InputMapping(
                source_node=mapping["source_node"],
                source_field=mapping.get("source_field", "__all__"),
            )

        for_each_config = None
        if raw.get("for_each"):
            fe = raw["for_each"]
            for_each_config = ForEachConfig(
                source_node=fe["source_node"],
                source_field=fe["source_field"],
                item_variable=fe.get("item_variable", "current_item"),
                max_concurrency=fe.get("max_concurrency", 10),
            )

        while_loop_config = None
        if raw.get("while_loop"):
            wl = raw["while_loop"]
            wl_cond = wl["condition"]
            while_loop_config = WhileLoopConfig(
                condition=NodeCondition(
                    source_node=wl_cond["source_node"],
                    field=wl_cond["field"],
                    operator=wl_cond.get("operator", "eq"),
                    value=wl_cond["value"],
                ),
                body_nodes=wl["body_nodes"],
                max_iterations=wl.get("max_iterations", 50),
            )

        # Parse switch config
        switch_config = None
        if raw.get("switch"):
            sw = raw["switch"]
            cases = []
            for case_raw in sw.get("cases", []):
                cases.append(
                    SwitchCase(
                        operator=case_raw.get("operator", "eq"),
                        value=case_raw["value"],
                        target_node=case_raw["target_node"],
                    )
                )
            switch_config = SwitchConfig(
                source_node=sw["source_node"],
                field=sw["field"],
                cases=cases,
                default_node=sw.get("default_node"),
            )

        # Parse merge config
        merge_config = None
        if raw.get("merge"):
            mg = raw["merge"]
            merge_config = MergeConfig(
                mode=mg.get("mode", "append"),
                join_field=mg.get("join_field"),
                source_nodes=mg.get("source_nodes", []),
            )

        node_type = (raw.get("type") or "").strip().lower()
        tool_name = raw.get("tool_name") or raw.get("tool") or ""
        arguments = dict(raw.get("arguments") or {})
        agent_slug = raw.get("agent_slug")
        structured_output = False
        required_if = raw.get("required_if")

        if node_type == "agent" and agent_slug:
            # Will be executed via agent_step, with prompt/tools pulled
            # from the seeded agent row at exec time.
            tool_name = "agent_step"
            if "input" in raw and "input_message" not in arguments:
                arguments["input_message"] = raw["input"]
            ctx = raw.get("context")
            if ctx and "__context__" not in arguments:
                arguments["__context__"] = ctx
        elif node_type == "tool":
            if not tool_name:
                tool_name = raw.get("tool") or ""
            ipt = raw.get("input")
            if isinstance(ipt, dict):
                arguments.update(ipt)
            elif ipt is not None and "input" not in arguments:
                arguments["input"] = ipt
        elif node_type == "structured":
            tool_name = "__structured__"
            structured_output = True
            ipt = raw.get("output") or raw.get("fields") or {}
            if isinstance(ipt, dict):
                arguments.update(ipt)

        if required_if:
            arguments["__required_if__"] = required_if

        declared_deps = list(raw.get("depends_on") or [])
        inferred = _infer_template_deps(
            {
                "args": arguments,
                "input": raw.get("input"),
                "output": raw.get("output"),
                "context": raw.get("context"),
                "required_if": required_if,
                "condition": raw.get("condition"),
                "input_mappings": raw.get("input_mappings"),
            },
            known_ids,
        )
        inferred.discard(raw["id"])
        for dep in sorted(inferred):
            if dep not in declared_deps:
                declared_deps.append(dep)

        nodes.append(
            PipelineNode(
                id=raw["id"],
                tool_name=tool_name,
                arguments=arguments,
                depends_on=declared_deps,
                condition=condition,
                input_mappings=input_mappings,
                max_retries=raw.get("max_retries", 0),
                retry_delay_ms=raw.get("retry_delay_ms", 1000),
                for_each=for_each_config,
                while_loop=while_loop_config,
                timeout_seconds=raw.get("timeout_seconds"),
                on_error=raw.get("on_error", "stop"),
                error_branch_node=raw.get("error_branch_node"),
                switch=switch_config,
                merge=merge_config,
                agent_slug=agent_slug,
                structured_output=structured_output,
            )
        )

    return nodes


def serialize_pipeline_result(result: PipelineResult) -> dict[str, Any]:
    """Convert a PipelineResult into a JSON-serializable dict."""
    node_results = {}
    for nid, nr in result.node_results.items():
        node_results[nid] = {
            "node_id": nr.node_id,
            "status": nr.status,
            "tool_name": nr.tool_name,
            "duration_ms": nr.duration_ms,
            "condition_evaluated": nr.condition_evaluated,
            "condition_met": nr.condition_met,
            "error": nr.error,
            "attempt": nr.attempt,
        }
        # Include output for completed nodes (truncate large outputs).
        # Bumped from 10K→128K to keep multi-stage briefs (OracleNet
        # synthesizer, the example app executive briefing, etc.) intact when the
        # client renders them. JSON loads can't round-trip a sliced string,
        # so on truncation we emit the raw string + an "output_truncated"
        # flag so the UI can show a "view raw" affordance.
        _NODE_OUTPUT_CAP = 128_000
        _NODE_FALLBACK_CAP = 32_000
        if nr.status == "completed" and nr.output is not None:
            try:
                output_str = json.dumps(nr.output, default=str)
                if len(output_str) > _NODE_OUTPUT_CAP:
                    # Don't try to re-parse a truncated slice — that almost
                    # always raises and falls into the str() branch anyway.
                    node_results[nid]["output"] = output_str[:_NODE_OUTPUT_CAP]
                    node_results[nid]["output_truncated"] = True
                else:
                    node_results[nid]["output"] = nr.output
            except (TypeError, json.JSONDecodeError):
                node_results[nid]["output"] = str(nr.output)[:_NODE_FALLBACK_CAP]
        elif nr.status == "skipped":
            node_results[nid]["output"] = None

    return {
        "status": result.status,
        "node_results": node_results,
        "execution_path": result.execution_path,
        "skipped_nodes": result.skipped_nodes,
        "failed_nodes": result.failed_nodes,
        "total_duration_ms": result.total_duration_ms,
        "final_output": result.final_output,
    }
