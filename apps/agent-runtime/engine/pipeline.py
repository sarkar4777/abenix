"""DAG-based pipeline executor with conditional branching and data flow."""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import logging
import os
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from engine import autonomy, credentials, governance, risk
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
    node_type: str = "tool"  # "tool" | "agent" — selects dispatch path
    agent_id: str | None = None
    agent_slug: str | None = None
    # When set, this node is a pure output-assembly step: it template-
    # resolves its `arguments` against node_outputs and returns them as a
    # single dict, with no tool call. Lets pipelines declare a final
    # `final_report` shape without a dummy tool.
    structured_output: bool = False
    label: str = ""


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
    # warnings, sources_skipped and the like from the tool's ToolResult
    metadata: dict[str, Any] = field(default_factory=dict)


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
    labels: dict[str, str] = field(default_factory=dict)  # {node_id: label}
    risk_tier: str = ""
    risk_reasons: list[dict[str, Any]] = field(default_factory=list)
    failure_code: str = ""


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
            return data if field_path in ("", "response") else None

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

    # builders write {{step.response}} for every tool, so read it as the step's main output
    head, _, rest = field_path.partition(".")
    if head == "response" and isinstance(data, dict) and "response" not in data:
        main = _main_output(data)
        if not rest:
            return main
        found = _walk(data, rest)
        if found is None and main is not data:
            inner = _try_parse_json_ish(main) if isinstance(main, str) else main
            found = _walk(inner, rest) if inner is not None else None
        return found

    return None


# where a tool keeps its payload: http_client body, document_parser text, ...
_MAIN_OUTPUT_KEYS = ("body", "text", "result", "output", "content", "data")


def _main_output(data: dict[str, Any]) -> Any:
    for key in _MAIN_OUTPUT_KEYS:
        if data.get(key) is not None:
            return data[key]
    return data


def _answer_with_saved_file(
    final_output: Any, execution_path: list[str], results: dict[str, Any]
) -> Any:
    """A run that ends by saving a file still answers with the text it wrote.

    The export keys stay, a "response" is added from the latest written answer
    so chat shows the summary and where the file went, not the file metadata.
    """
    if not isinstance(final_output, dict) or "response" in final_output:
        return final_output
    if not (final_output.get("download_url") or final_output.get("file_path")):
        return final_output
    text = None
    for nid in reversed(execution_path[:-1]):
        r = results.get(nid)
        if r is None or r.status != "completed":
            continue
        out = r.output
        if isinstance(out, dict) and isinstance(out.get("response"), str):
            text = out["response"].strip()
        elif isinstance(out, str) and r.tool_name in ("llm_call", "agent_step"):
            text = out.strip()
        if text:
            break
    if not text:
        return final_output
    where = final_output.get("download_url") or final_output.get("file_path")
    name = final_output.get("filename") or str(where).rsplit("/", 1)[-1]
    return {**final_output, "response": f"{text}\n\nSaved {name}: {where}"}


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
    """Replace {{node_id.field}} template variables in arguments.

    Walks nested dicts and lists. A node's `context:` block arrives as a dict,
    so a string-only pass shipped every `{{input.x}}` inside it to the agent
    verbatim.
    """
    import re as _re

    pattern = _re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")

    def _lookup(path: str) -> Any:
        parts = path.split(".", 1)
        source = node_outputs.get(parts[0])
        if source is None:
            return None
        return _extract_field(source, parts[1] if len(parts) > 1 else "__all__")

    def _resolve(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_resolve(v) for v in value]
        if not isinstance(value, str) or "{{" not in value:
            return value

        # Whole-value template ({{plan.actions}}) — keep the extracted object
        # as-is so downstream nodes / structured outputs get a list/dict, not
        # its Python repr. Embedded templates in a longer string fall back to
        # str() coercion.
        whole = pattern.fullmatch(value)
        if whole is not None:
            extracted = _lookup(whole.group(1))
            return "[not available]" if extracted is None else extracted

        def _replacer(match: _re.Match) -> str:
            extracted = _lookup(match.group(1))
            if extracted is None:
                return "[not available]"  # skipped, not run, or no such field
            # Inline inside a larger string: use JSON so lists/dicts don't show
            # up as Python repr (single-quoted keys).
            if isinstance(extracted, (dict, list)):
                try:
                    return json.dumps(extracted, default=str)
                except (TypeError, ValueError):
                    return str(extracted)
            return str(extracted)

        return pattern.sub(_replacer, value)

    return {key: _resolve(value) for key, value in arguments.items()}


def _continued_after_error(output: Any) -> bool:
    return isinstance(output, dict) and bool(output.get("__error_continue"))


def _skipped_by_failure(result: Any) -> bool:
    err = getattr(result, "error", None) or ""
    return err.startswith("Dependency '") and err.endswith("' failed")


_NUM_RE = __import__("re").compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")


def _coerce_scalar(v: str, kind: str) -> Any:
    t = v.strip()
    if kind in ("number", "integer") and _NUM_RE.match(t):
        n = float(t)
        if kind == "integer":
            return int(n) if n.is_integer() else v
        return n
    if kind == "boolean" and t.lower() in ("true", "false"):
        return t.lower() == "true"
    return v


def _coerce_to_schema(args: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Turn text that templates produced into the types the tool declares.

    Pipeline inputs and step outputs often arrive as text, so "36" reaches a
    number field and "33.8, 34.6" reaches a list of numbers. Only top-level
    string values whose declared type differs are touched, anything that does
    not convert cleanly is passed through for the tool to report.
    """
    props = (schema or {}).get("properties") or {}
    out = dict(args)
    for key, value in args.items():
        spec = props.get(key)
        if not isinstance(spec, dict) or not isinstance(value, str):
            continue
        kind = spec.get("type")
        if isinstance(kind, list):
            kind = next((k for k in kind if k != "null"), None)
        if kind in ("number", "integer", "boolean"):
            out[key] = _coerce_scalar(value, kind)
        elif kind == "array":
            text = value.strip()
            items: Any = None
            if text.startswith("["):
                try:
                    items = json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    items = None
            elif text and "{{" not in text:
                items = [p.strip() for p in text.split(",") if p.strip()]
            if isinstance(items, list):
                item_kind = (spec.get("items") or {}).get("type")
                if item_kind in ("number", "integer", "boolean"):
                    items = [
                        _coerce_scalar(i, item_kind) if isinstance(i, str) else i
                        for i in items
                    ]
                out[key] = items
        elif kind == "object":
            text = value.strip()
            if text.startswith("{"):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        out[key] = parsed
                except (json.JSONDecodeError, TypeError):
                    pass
    return out


def _resolve_from_node_args(
    arguments: dict[str, Any],
    node_outputs: dict[str, Any],
) -> dict[str, Any]:
    """Resolve `<x>_from_node` + `<x>_field` indirection pairs.

    A DSL node can pass `{asset_id_from_node: "validate_input",
    asset_id_field: "alarm.asset.turbine"}` and have the runtime swap that
    pair for `asset_id: <resolved value>` before the tool sees the args.
    Used by IoT seeds (windowed_state, mqtt_publish, approval_gate, …) so
    they don't have to template the value through a string.
    """
    resolved = dict(arguments)
    pairs: list[tuple[str, str, str]] = []
    for key in list(resolved.keys()):
        if key.endswith("_from_node"):
            base = key[: -len("_from_node")]
            field_key = f"{base}_field"
            if field_key in resolved:
                pairs.append((base, key, field_key))
    for base, from_key, field_key in pairs:
        src_node = resolved.pop(from_key, None)
        src_field = resolved.pop(field_key, None)
        if base in resolved and resolved[base] not in (None, "", "[not available]"):
            # Caller already supplied a direct value — leave it alone.
            continue
        if not src_node:
            continue
        src = node_outputs.get(str(src_node))
        if src is None:
            continue
        value = _extract_field(src, str(src_field)) if src_field else src
        if value is None:
            continue
        resolved[base] = value
    return resolved


_engine_cache: dict[str, Any] = {}
_engine_cache_lock: asyncio.Lock | None = None


def _get_engine_lock() -> asyncio.Lock:
    global _engine_cache_lock
    if _engine_cache_lock is None:
        _engine_cache_lock = asyncio.Lock()
    return _engine_cache_lock


async def _get_pipeline_engine(db_url: str) -> Any:
    if not db_url:
        return None
    cached = _engine_cache.get(db_url)
    if cached is not None:
        return cached
    async with _get_engine_lock():
        cached = _engine_cache.get(db_url)
        if cached is not None:
            return cached
        from sqlalchemy.ext.asyncio import create_async_engine

        pool_size = int(os.environ.get("PIPELINE_DB_POOL_SIZE", "10"))
        max_overflow = int(os.environ.get("PIPELINE_DB_MAX_OVERFLOW", "5"))
        engine = create_async_engine(
            db_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=3600,
        )
        _engine_cache[db_url] = engine
        return engine


# Whole-pipeline wall-clock budget. 120s was hardcoded at every call site and
# is not enough for a multi-node LLM pipeline: ClaimsIQ's seven nodes were cut
# off at 134s with "Pipeline timeout exceeded" on the last two. OracleNet had
# already worked around it with its own 600s. Override with
# PIPELINE_TIMEOUT_SECONDS.
DEFAULT_PIPELINE_TIMEOUT_SECONDS = int(
    os.environ.get("PIPELINE_TIMEOUT_SECONDS", "300")
)


# names seed pipelines use for the run message, all filled the same way on every path
_MESSAGE_ALIASES = (
    "user_message",
    "message",
    "prompt",
    "content",
    "text",
    "ticket_content",
    "query",
    "request",
)


def build_run_context(
    message: str,
    execution_id: str = "",
    defaults: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The context every execute path hands to PipelineExecutor.execute.

    Declared input defaults sit under what the caller sent, and the execution
    id rides along so healing can attach a failure diff to the run.
    """
    out: dict[str, Any] = {k: message for k in _MESSAGE_ALIASES} if message else {}
    out.update(defaults or {})
    out.update(context or {})
    if execution_id:
        out["__execution_id"] = str(execution_id)
    return out


def pipeline_timed_out(
    limit_seconds: int, node_statuses: dict[str, str] | None = None
) -> "PipelineResult":
    """The failed result a caller records when a run overruns its time limit."""
    msg = (
        f"The pipeline ran out of time. It stopped after {int(limit_seconds)}s, "
        "the limit set in pipeline.timeout_seconds."
    )
    unfinished = [
        nid for nid, st in (node_statuses or {}).items() if st in ("pending", "running")
    ]
    errors = {"pipeline": msg, **{nid: msg for nid in unfinished}}
    return PipelineResult(
        status="failed",
        failed_nodes=unfinished,
        total_duration_ms=int(limit_seconds) * 1000,
        final_output={"error": msg},
        node_errors=errors,
        failure_code="RUNTIME_TIMEOUT",
    )


class PipelineExecutor:
    """Execute a DAG of tool calls with conditions and data piping."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        timeout_seconds: int | None = None,
        on_node_start: Callable[..., Any] | None = None,
        on_node_complete: Callable[..., Any] | None = None,
        cost_limit: float | None = None,
        db_url: str = "",
        agent_id: str = "",
        tenant_id: str = "",
    ) -> None:
        self.tool_registry = tool_registry
        self.timeout_seconds = timeout_seconds or DEFAULT_PIPELINE_TIMEOUT_SECONDS
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
        # Callbacks written before error_message/error_type existed take fewer args
        try:
            kinds = [p.kind for p in inspect.signature(callback).parameters.values()]
        except (TypeError, ValueError):
            kinds = None
        if kinds is not None and inspect.Parameter.VAR_POSITIONAL not in kinds:
            positional = (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
            args = args[: sum(1 for k in kinds if k in positional)]
        try:
            if inspect.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception:
            logger.warning("Streaming callback raised an exception", exc_info=True)

    async def execute(
        self,
        nodes: list[PipelineNode],
        context: dict[str, Any] | None = None,
    ) -> PipelineResult:
        await governance.ensure_fresh(max_age=1.0)
        await autonomy.ensure_fresh()
        parent = governance.current()
        base = risk.highest(
            [governance.agent_tier(self._agent_id), parent.tier if parent else "low"]
        )
        ctx = governance.RunContext(
            tenant_id=str(self._tenant_id or ""),
            execution_id=str((context or {}).get("__execution_id") or ""),
            agent_name=f"pipeline {self._agent_id}",
            base_tier=base,
            tier=base,
            scope="pipeline",
            subject_id=str(self._agent_id or ""),
            parent=parent,
            agent_id=str(self._agent_id or ""),
            user_id=str(
                getattr(self.tool_registry, "run_user_id", "")
                or (parent.user_id if parent else "")
                or ""
            ),
            agent_config_hash=autonomy.config_hash(self._agent_id),
        )
        if base != "low":
            ctx.reasons.append({"tier": base, "source": "pipeline", "detail": ""})
        token = governance.begin_run(ctx)
        try:
            try:
                governance.check(self._tenant_id, "pipeline", self._agent_id or "*")
            except governance.Stopped as s:
                result = PipelineResult(
                    status="failed",
                    node_errors={"pipeline": s.message()},
                    final_output={"error": s.message()},
                    failure_code="KILL_SWITCH",
                )
            else:
                result = await self._execute_governed(nodes, context)
        finally:
            governance.end_run(token)
            if parent is not None:
                parent.raise_to(ctx.tier, f"pipeline:{self._agent_id}")
        result.risk_tier = ctx.tier
        result.risk_reasons = list(ctx.reasons)
        return result

    async def _execute_governed(
        self,
        nodes: list[PipelineNode],
        context: dict[str, Any] | None = None,
    ) -> PipelineResult:
        start = time.monotonic()
        credentials.set_tenant(self._tenant_id)
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
        # a plain-text "input" in the context must not replace the alias, or {{input.x}} breaks
        if not isinstance(context.get("input"), dict):
            if isinstance(context.get("input"), str):
                input_alias.pop("input", None)
                input_alias.setdefault("message", context["input"])
            node_outputs["input"] = input_alias
        results: dict[str, NodeResult] = {}
        execution_path: list[str] = []
        skipped_nodes: list[str] = []
        failed_nodes: list[str] = []

        # Validate dependencies BEFORE topo sort so callers get a precise
        # "unknown dependency" error per offending node instead of a generic
        # cycle/missing message. Returns a failed PipelineResult — never raises.
        known_ids = {n.id for n in nodes}
        dep_errors: dict[str, str] = {}
        for n in nodes:
            for dep in n.depends_on:
                if dep not in known_ids:
                    dep_errors[n.id] = f"unknown dependency: {dep}"
                    break
        if dep_errors:
            return PipelineResult(
                status="failed",
                total_duration_ms=int((time.monotonic() - start) * 1000),
                final_output={"error": "unknown_dependency", "details": dep_errors},
                node_errors=dep_errors,
                failed_nodes=list(dep_errors.keys()),
            )

        try:
            layers = _topological_sort(nodes)
        except ValueError as e:
            return PipelineResult(
                status="failed",
                total_duration_ms=int((time.monotonic() - start) * 1000),
                final_output={"error": str(e)},
                node_errors={n.id: str(e) for n in nodes},
            )

        timed_out = False
        for layer in layers:
            elapsed = time.monotonic() - start
            if elapsed > self.timeout_seconds:
                timed_out = True
                for nid in layer:
                    results[nid] = NodeResult(
                        node_id=nid,
                        status="failed",
                        error="Pipeline timeout exceeded",
                        error_message=(
                            f"The pipeline ran out of time after {int(elapsed)}s "
                            f"(limit {self.timeout_seconds}s), so this step did not run."
                        ),
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

                    # Keep the last good output so a later failure diff has an expected_sample
                    if self._agent_id:
                        try:
                            from engine.healing import fire_and_forget, remember_success

                            fire_and_forget(
                                remember_success(self._agent_id, nid, result.output)
                            )
                        except Exception as _he:
                            logger.debug("healing success sample skipped: %s", _he)

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
                            "error": result.error_message or result.error,
                            "error_type": result.error_type,
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
                        # no execution id means no row to attach to, the insert would only fail on the FK
                        if (
                            self._db_url
                            and self._tenant_id
                            and self._agent_id
                            and context.get("__execution_id")
                        ):
                            try:
                                from engine.healing import (
                                    capture_node_failure,
                                    fire_and_forget,
                                )

                                # healing rebuilds the exception from error_type and reads the last good sample
                                fire_and_forget(
                                    capture_node_failure(
                                        error_traceback=(result.metadata or {}).get(
                                            "traceback"
                                        ),
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
                                        error_type=result.error_type,
                                        error_message=(
                                            result.error_message or result.error or ""
                                        ),
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
        final_output = _answer_with_saved_file(final_output, execution_path, results)

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
            labels={n.id: n.label for n in nodes if n.label},
            failure_code="RUNTIME_TIMEOUT" if timed_out else "",
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
        earlier = {"cost": 0.0, "input_tokens": 0, "output_tokens": 0}

        for attempt in range(max_attempts):
            result = await self._execute_node_once(node, node_outputs, prior_results)
            result.attempt = attempt + 1

            # Only retry on "failed" status -- NOT on "skipped"
            if result.status != "failed" or attempt >= max_attempts - 1:
                break
            for k, v in node_usage(result).items():
                earlier[k] += v

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

        assert result is not None
        if any(earlier.values()):
            last = node_usage(result)
            result.metadata = {
                **(result.metadata or {}),
                **{k: last[k] + earlier[k] for k in earlier},
                "earlier_attempts_cost": round(earlier["cost"], 6),
            }

        # Fire on_node_complete callback
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
                # on_error: continue leaves an error marker in node_outputs, dependents run with it
                if _continued_after_error(node_outputs.get(dep_id)):
                    continue
                return NodeResult(
                    node_id=node.id,
                    status="skipped",
                    error=f"Dependency '{dep_id}' failed",
                    tool_name=node.tool_name,
                    duration_ms=int((time.monotonic() - node_start) * 1000),
                )
            # skipped because something upstream failed, so this has no input either
            if dep_result.status == "skipped" and _skipped_by_failure(dep_result):
                return NodeResult(
                    node_id=node.id,
                    status="skipped",
                    error=dep_result.error,
                    tool_name=node.tool_name,
                    duration_ms=int((time.monotonic() - node_start) * 1000),
                )

        for dep_id in node.depends_on:
            dep_result = prior_results.get(dep_id)
            if dep_result is None or dep_result.tool_name != "__switch__":
                continue
            if not node_outputs.get(f"__switch_activated_{node.id}"):
                return NodeResult(
                    node_id=node.id,
                    status="skipped",
                    tool_name=node.tool_name,
                    duration_ms=int((time.monotonic() - node_start) * 1000),
                )

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
        # Generic <x>_from_node + <x>_field indirection (IoT seeds use this)
        resolved_args = _resolve_from_node_args(resolved_args, node_outputs)

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
        # Also catches DSL nodes that drop `agent_slug` inside `arguments`
        # rather than at node level (tool_name: agent_step + agent_slug arg).
        effective_slug = node.agent_slug or (
            resolved_args.pop("agent_slug", None)
            if node.tool_name == "agent_step"
            else None
        )
        if effective_slug:
            agent_row = await self._resolve_agent_by_slug(effective_slug)
            if agent_row is not None and agent_row.get("archived"):
                msg = (
                    f"agent '{effective_slug}' was deleted. Pick another agent for "
                    f"step '{node.label or node.id}'."
                )
                return NodeResult(
                    node_id=node.id,
                    status="failed",
                    error=msg,
                    error_message=msg,
                    error_type="validation",
                    tool_name=node.tool_name,
                    resolved_arguments=resolved_args,
                    duration_ms=int((time.monotonic() - node_start) * 1000),
                )
            if agent_row is None:
                return NodeResult(
                    node_id=node.id,
                    status="failed",
                    error=f"agent_slug '{effective_slug}' not found in DB",
                    error_message=f"agent_slug '{effective_slug}' not found in DB",
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
            # Execution context the sub-agent's tool registry needs. Without
            # these its knowledge_search and every db-backed tool go missing.
            # No db_url here — it carries a password and these arguments are
            # recorded on the node result. agent_step reads DATABASE_URL itself.
            resolved_args.setdefault("__kb_ids__", agent_row.get("kb_ids") or [])
            resolved_args.setdefault("__agent_id__", agent_row.get("agent_id") or "")
            resolved_args.setdefault("__tenant_id__", self._tenant_id or "")
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
            node_timeout = node.timeout_seconds or self.timeout_seconds
            try:
                await asyncio.wait_for(asyncio.sleep(seconds), timeout=node_timeout)
            except asyncio.TimeoutError:
                return NodeResult(
                    node_id=node.id,
                    status="timeout",
                    error=f"wait timeout after {node_timeout}s",
                    tool_name="wait",
                    duration_ms=int(node_timeout * 1000),
                )
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

        # Find and execute the tool. An unknown name fails the node, no code is synthesized for it.
        tool = self.tool_registry.get(node.tool_name)
        if tool is None:
            return NodeResult(
                node_id=node.id,
                status="failed",
                error=f"Unknown tool '{node.tool_name}'",
                error_message=f"Unknown tool '{node.tool_name}'",
                error_type="tool_error",
                tool_name=node.tool_name,
                resolved_arguments=resolved_args,
                duration_ms=int((time.monotonic() - node_start) * 1000),
            )

        resolved_args = _coerce_to_schema(
            resolved_args, getattr(tool, "input_schema", None) or {}
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
                    metadata=dict(getattr(result, "metadata", None) or {}),
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

            # A downstream llm_call only sees the node output, so a warning
            # kept in metadata alone would never reach it.
            md = dict(getattr(result, "metadata", None) or {})
            notes = list(md.get("warnings") or [])
            if md.get("sources_skipped"):
                notes.append(
                    "sources not queried: "
                    + ", ".join(str(x) for x in md["sources_skipped"])
                )
            if notes and isinstance(parsed, dict):
                parsed.setdefault("_warnings", notes)
            # a watching action did not run, downstream reads it like an approval status
            auto = md.get("autonomy")
            if isinstance(auto, dict) and auto.get("status") == "watching":
                parsed = {"status": "watching", "proposed": auto.get("proposed") or {}}

            return NodeResult(
                node_id=node.id,
                status="completed",
                output=parsed,
                metadata=md,
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
                metadata={"traceback": traceback.format_exc()[-4000:]},
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
            from sqlalchemy.ext.asyncio import AsyncSession
            from sqlalchemy import text as _t

            engine = await _get_pipeline_engine(self._db_url)
            if engine is None:
                return None
            async with AsyncSession(engine) as session:
                res = await session.execute(
                    _t(
                        "SELECT id, system_prompt, model_config, status::text FROM agents "
                        "WHERE slug = :slug ORDER BY (status::text = 'archived') LIMIT 1"
                    ).bindparams(slug=slug)
                )
                row = res.first()
                if row is None:
                    cache[slug] = None
                    return None
                aid, sp, mcfg = row[0], row[1], row[2]
                if str(row[3] or "").lower() == "archived":
                    cache[slug] = {"archived": True}
                    return cache[slug]
                if isinstance(mcfg, str):
                    try:
                        mcfg = json.loads(mcfg)
                    except Exception:
                        mcfg = {}
                # Without its granted collections the sub-agent's registry has
                # no knowledge_search, and the agent answers that it cannot
                # look anything up. Direct invocation resolves these in the
                # API layer, so a pipeline node has to do it here.
                kb = await session.execute(
                    _t(
                        "SELECT collection_id FROM agent_collection_grants "
                        "WHERE agent_id = :aid"
                    ).bindparams(aid=aid)
                )
                cache[slug] = {
                    "agent_id": str(aid),
                    "system_prompt": sp or "",
                    "model_config": mcfg or {},
                    "kb_ids": [str(r[0]) for r in kb.fetchall()],
                }
                return cache[slug]
        except Exception as e:
            logger.warning("_resolve_agent_by_slug(%s) failed: %s", slug, e)
            return None

    async def _state_get(self, key: str) -> Any:
        """Read a value from persistent pipeline state (database)."""
        if not self._db_url or not self._agent_id:
            return None
        try:
            from sqlalchemy.ext.asyncio import AsyncSession
            from sqlalchemy import select

            engine = await _get_pipeline_engine(self._db_url)
            if engine is None:
                return None
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
            from sqlalchemy.ext.asyncio import AsyncSession
            from sqlalchemy import select

            engine = await _get_pipeline_engine(self._db_url)
            if engine is None:
                return
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


def _label_key(label: Any) -> str:
    import re as _re

    return _re.sub(r"\W+", "_", str(label or "").strip().lower()).strip("_")


def alias_labels_to_ids(raw_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rewrite {{label.x}} to {{id.x}} when a step is referenced by its unique label.

    The builder gives steps generated ids, and people write the label they
    typed. An id always wins over a label of the same name.
    """
    ids = {raw.get("id") for raw in raw_nodes if raw.get("id")}
    seen: dict[str, list[str]] = {}
    for raw in raw_nodes:
        key = _label_key(raw.get("label"))
        if key and raw.get("id"):
            seen.setdefault(key, []).append(raw["id"])
    alias = {k: v[0] for k, v in seen.items() if len(v) == 1 and k not in ids}
    if not alias:
        return raw_nodes

    def _sub(m: Any) -> str:
        root, _, rest = m.group(1).partition(".")
        target = alias.get(root.lower()) if root not in ids else None
        if not target:
            return m.group(0)
        return "{{" + target + ("." + rest if rest else "") + "}}"

    def _walk(v: Any) -> Any:
        if isinstance(v, str):
            return _TEMPLATE_REF_RE.sub(_sub, v) if "{{" in v else v
        if isinstance(v, dict):
            return {k: _walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_walk(x) for x in v]
        return v

    out = []
    for raw in raw_nodes:
        r = dict(raw)
        for k in ("arguments", "context", "input_mappings"):
            if k in r:
                r[k] = _walk(r[k])
        out.append(r)
    return out


def parse_pipeline_nodes(raw_nodes: list[dict[str, Any]]) -> list[PipelineNode]:
    """Parse raw JSON/dict pipeline node definitions into PipelineNode objects."""
    raw_nodes = alias_labels_to_ids(raw_nodes)
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
        agent_id = raw.get("agent_id")
        structured_output = False
        required_if = raw.get("required_if")

        if node_type == "agent" and (agent_slug or agent_id):
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
                node_type=(node_type or "tool"),
                agent_id=agent_id,
                agent_slug=agent_slug,
                structured_output=structured_output,
                label=str(raw.get("label") or ""),
            )
        )

    return nodes


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def node_usage(nr: NodeResult) -> dict[str, Any]:
    """Spend of one node whatever its status, from its metadata or else its output."""
    src: dict[str, Any] | None = None
    md = nr.metadata or {}
    if _is_num(md.get("cost")):
        src = md
    else:
        out = nr.output
        if isinstance(out, str):
            try:
                out = json.loads(out)
            except (TypeError, ValueError):
                out = None
        if isinstance(out, dict) and _is_num(out.get("cost")):
            src = out
    if src is None:
        return {"cost": 0.0, "input_tokens": 0, "output_tokens": 0}
    return {
        "cost": float(src.get("cost") or 0),
        "input_tokens": int(src.get("input_tokens") or 0),
        "output_tokens": int(src.get("output_tokens") or 0),
    }


def pipeline_usage(result: PipelineResult) -> dict[str, Any]:
    """What the whole run spent, failed and retried steps included."""
    total = {"cost": 0.0, "input_tokens": 0, "output_tokens": 0}
    for nr in (result.node_results or {}).values():
        for k, v in node_usage(nr).items():
            total[k] += v
    total["cost"] = round(total["cost"], 6)
    return total


def pipeline_provider_costs(result: PipelineResult) -> dict[str, float]:
    """Run spend split by LLM provider, from each step's model."""
    from engine.agent_executor import _provider_key

    out: dict[str, float] = {}
    for nr in (result.node_results or {}).values():
        cost = node_usage(nr)["cost"]
        if not cost:
            continue
        md = nr.metadata or {}
        out_val = nr.output if isinstance(nr.output, dict) else {}
        model = md.get("model") or out_val.get("model") or ""
        key = _provider_key(str(model))
        out[key] = round(out.get(key, 0.0) + cost, 6)
    return out


def serialize_pipeline_result(result: PipelineResult) -> dict[str, Any]:
    """Convert a PipelineResult into a JSON-serializable dict."""
    node_results = {}
    for nid, nr in result.node_results.items():
        node_results[nid] = {
            "node_id": nr.node_id,
            "label": result.labels.get(nid, ""),
            "status": nr.status,
            "tool_name": nr.tool_name,
            "duration_ms": nr.duration_ms,
            "condition_evaluated": nr.condition_evaluated,
            "condition_met": nr.condition_met,
            "error": nr.error,
            "attempt": nr.attempt,
            "metadata": nr.metadata,
        }
        if nr.resolved_arguments:
            try:
                if len(json.dumps(nr.resolved_arguments, default=str)) <= 16_000:
                    node_results[nid]["resolved_arguments"] = nr.resolved_arguments
            except (TypeError, ValueError):
                pass
        # Include output for completed nodes (truncate large outputs).
        # Bumped from 10K→128K to keep multi-stage briefs (synthesiser,
        # executive briefing, etc.) intact when the
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

    # one row per node in run order, what the Flight Recorder and replay read
    steps: list[dict[str, Any]] = []
    order = list(result.execution_path or []) + [
        n for n in result.node_results if n not in (result.execution_path or [])
    ]
    for nid in order:
        nr = result.node_results.get(nid)
        if nr is None:
            continue
        preview = node_results.get(nid, {}).get("output")
        if not isinstance(preview, str):
            try:
                preview = json.dumps(preview, default=str)
            except (TypeError, ValueError):
                preview = str(preview)
        steps.append(
            {
                "node_type": "pipeline_node",
                "node_id": nid,
                "label": result.labels.get(nid, ""),
                "tool": nr.tool_name,
                "status": nr.status,
                "duration_ms": nr.duration_ms,
                "input": nr.resolved_arguments,
                "output_preview": (preview or "")[:500],
                "is_error": nr.status == "failed",
                "error": nr.error,
                "metadata": nr.metadata,
                "attempt": nr.attempt,
            }
        )

    return {
        "status": result.status,
        "node_results": node_results,
        "steps": steps,
        "execution_path": result.execution_path,
        "skipped_nodes": result.skipped_nodes,
        "failed_nodes": result.failed_nodes,
        "total_duration_ms": result.total_duration_ms,
        "final_output": result.final_output,
        "risk_tier": result.risk_tier,
        "risk_reasons": result.risk_reasons,
        "failure_code": result.failure_code,
        **pipeline_usage(result),
    }
