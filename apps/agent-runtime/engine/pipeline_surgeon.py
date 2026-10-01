"""Pipeline Surgeon — proposes minimal JSON-Patch fixes for failed runs.

Inputs (gathered by the API caller, not the LLM):
  * the latest pipeline_run_diff for the failing pipeline+node
  * the last 1-3 successful executions of the same pipeline (for shape evidence)
  * the current DSL as {"pipeline_config": agent.model_config.pipeline_config}
  * the tool registry (name + description for every registered tool)

Output:
  * a JSON-Patch (RFC 6902) against the DSL — typically rename a field,
    widen an input mapping, swap a model, add a fallback branch, or
    insert a defensive {coerce-shape, validate} node before the failing
    one.  Plus a confidence score, risk level, and rationale.

The LLM is only asked to produce structured JSON.  The patch is applied with
python-jsonpatch to a copy of the DSL and the result goes through the
allow-list validator below.  Anything it rejects never reaches the DB.

Important: we never mutate the live agent record here.  This module
returns a proposal record that the API persists into
`pipeline_patch_proposals` with status='pending'.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Ops the validator accepts. "test" is harmless and lets the model guard a
# replace. Nothing that moves or removes data.
ALLOWED_OPS = frozenset({"add", "replace", "test"})
MAX_PATCH_OPS = 8
NODES_PREFIX = "/pipeline_config/nodes"

# Node targets that are dispatched by the engine itself, not the registry.
INTERNAL_TOOL_NAMES = frozenset(
    {"agent_step", "wait", "state_get", "state_set", "__structured__"}
)
NODE_KINDS_WITHOUT_TOOL = frozenset({"agent", "structured"})

_POINTER_INDEX = re.compile(r"^/pipeline_config/nodes/(\d+|-)(/.*)?$")


_SYSTEM_PROMPT = """You are the Pipeline Surgeon.

Your job: read a structured snapshot of a failed pipeline run and propose the
SMALLEST POSSIBLE JSON-Patch (RFC 6902) against the pipeline's DSL that would
make the failing node succeed on the next run.

You will be given:

  * `dsl` — the pipeline DSL, an object of the shape
    {"pipeline_config": {"nodes": [...], ...}}.  Nodes live at
    `pipeline_config.nodes`, so every JSON Pointer in your patch starts
    with `/pipeline_config/nodes/<index>`.  Each node has an `id`, a
    `type` ("tool", "agent" or "structured"), `tool` (or `tool_name`) or
    `agent_slug`, optional `depends_on`, `input`, `input_mappings`,
    `arguments`, `on_error`, `max_retries`, `timeout_seconds`.
  * `failure` — the structured run-diff: which node, error class, error
    message, observed output shape, expected shape (from past successes),
    and the inputs the node received.
  * `recent_successes` — up to 3 recent successful runs of the SAME
    pipeline so you can see what the failing node USED to consume and
    produce.
  * `tool_registry` — the only tool names a node may use, with their
    descriptions.

Patch design rules (in order):

  1. Be minimal.  One or two ops only.  Never rewrite the whole DSL.
  2. Only `add` and `replace` ops, and only under `/pipeline_config/nodes`.
     No `remove`, `move` or `copy`.  Anything else is rejected.
  3. Never remove a node, never change a node's `id`, never add or drop
     the pipeline's entry nodes (no `depends_on`) or exit nodes (nothing
     depends on them).  You may add a node in the middle of the graph.
  4. Every `tool` / `tool_name` you set must be in `tool_registry`.
  5. The result must stay a DAG: no `depends_on` cycles, no dangling ids.
  6. Prefer non-destructive changes:
     a. add input_mapping with a fallback default
     b. add `on_error: continue` if the failing node is non-critical
     c. add a defensive coerce/validate node BEFORE the failing one
     d. swap model on an agent_step node only as a last resort
  7. Never alter another tenant's resources.
  8. If you cannot find a confident fix, return confidence < 0.5 and
     explain in rationale.

Return STRICT JSON exactly matching this schema, with NO prose:

{
  "title": "<short, imperative — e.g. 'Add fallback default for missing counterparty field'>",
  "rationale": "<2-4 sentences explaining what changed and why>",
  "confidence": <number between 0.0 and 1.0>,
  "risk_level": "low" | "medium" | "high",
  "json_patch": [
    {"op": "add" | "replace", "path": "/pipeline_config/nodes/<index>/...", "value": <any>},
    ...
  ]
}

Risk-level guidance:
  * low    — adds a fallback, widens an input mapping, sets on_error=continue
  * medium — adds a new defensive node, swaps a model
  * high   — replaces a node's tool
"""


_USER_PROMPT_TEMPLATE = """Please propose a fix for this pipeline failure.

## DSL (current)

```json
{dsl}
```

## Failure snapshot

```json
{failure}
```

## Recent successful runs (newest first)

```json
{recent_successes}
```

## Available tool registry

```json
{tool_registry}
```

Remember: return ONLY the JSON object as specified in the system prompt.
The patch MUST be valid against the DSL above.
"""


def _nodes_of(dsl: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = (dsl.get("pipeline_config") or {}).get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("DSL has no pipeline_config.nodes list")
    for n in nodes:
        if not isinstance(n, dict) or not isinstance(n.get("id"), str):
            raise ValueError("every node must be an object with a string id")
    return nodes


def _node_tool(node: dict[str, Any]) -> str | None:
    kind = str(node.get("type") or "tool").strip().lower()
    if (
        kind in NODE_KINDS_WITHOUT_TOOL
        or node.get("agent_slug")
        or node.get("agent_id")
    ):
        return None
    return node.get("tool_name") or node.get("tool") or None


def _entry_exit(nodes: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    ids = {n["id"] for n in nodes}
    depended = {d for n in nodes for d in (n.get("depends_on") or []) if d in ids}
    entry = {n["id"] for n in nodes if not (n.get("depends_on") or [])}
    exit_ = ids - depended
    return entry, exit_


def _has_cycle(nodes: list[dict[str, Any]]) -> bool:
    deps = {n["id"]: list(n.get("depends_on") or []) for n in nodes}
    indeg = {nid: 0 for nid in deps}
    for nid, ds in deps.items():
        for d in ds:
            if d in indeg:
                indeg[nid] += 1
    ready = [nid for nid, c in indeg.items() if c == 0]
    seen = 0
    while ready:
        cur = ready.pop()
        seen += 1
        for nid, ds in deps.items():
            if cur in ds:
                indeg[nid] -= 1
                if indeg[nid] == 0:
                    ready.append(nid)
    return seen != len(deps)


def registry_names(tool_registry: list[dict[str, Any]] | None) -> set[str]:
    names: set[str] = set()
    for entry in tool_registry or []:
        if isinstance(entry, dict) and entry.get("name"):
            names.add(str(entry["name"]))
        elif isinstance(entry, str):
            names.add(entry)
    return names


def validate_patch(
    dsl_before: dict[str, Any],
    patch_ops: list[dict[str, Any]],
    tool_registry: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply a JSON-Patch and validate the result against the allow-list.

    Returns the patched DSL. Raises ValueError with a reason otherwise.
    Allowed: add/replace under /pipeline_config/nodes. Rejected: any other
    op or path, node removal or id change, entry/exit node changes, a tool
    not in the registry, a cycle, a dangling depends_on.
    """
    try:
        import jsonpatch  # type: ignore[import-untyped]
    except ImportError as e:
        raise ValueError("jsonpatch library not installed") from e

    if not isinstance(patch_ops, list) or not patch_ops:
        raise ValueError("patch must be a non-empty list of ops")
    if len(patch_ops) > MAX_PATCH_OPS:
        raise ValueError(
            f"patch is too large (>{MAX_PATCH_OPS} ops); should be minimal"
        )

    for op in patch_ops:
        if not isinstance(op, dict):
            raise ValueError("each op must be an object")
        if op.get("op") not in ALLOWED_OPS:
            raise ValueError(
                f"op '{op.get('op')}' not allowed; only add/replace of node fields"
            )
        path = op.get("path")
        if not isinstance(path, str) or not _POINTER_INDEX.match(path):
            raise ValueError(
                f"path '{path}' must target /pipeline_config/nodes/<index>[/field]"
            )
        if "from" in op:
            raise ValueError("ops with 'from' are not allowed")
        m = _POINTER_INDEX.match(path)
        if m and m.group(2) == "/id":
            raise ValueError("changing a node id is not allowed")

    before_nodes = _nodes_of(dsl_before)
    try:
        patched = jsonpatch.JsonPatch(patch_ops).apply(copy.deepcopy(dsl_before))
    except Exception as e:
        raise ValueError(f"patch does not apply: {e}") from e

    nodes = _nodes_of(patched)
    ids = [n["id"] for n in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("patched DSL has duplicate node ids")

    before_ids = {n["id"] for n in before_nodes}
    missing = before_ids - set(ids)
    if missing:
        raise ValueError(f"patch removes node(s): {sorted(missing)}")
    for b in before_nodes:
        after = next(n for n in nodes if n["id"] == b["id"])
        if _node_kind(after) != _node_kind(b):
            raise ValueError(f"patch changes the kind of node {b['id']}")

    for node in nodes:
        for dep in node.get("depends_on") or []:
            if dep not in ids:
                raise ValueError(f"node {node['id']} depends_on missing node {dep}")
            if dep == node["id"]:
                raise ValueError(f"node {node['id']} depends on itself")
    if _has_cycle(nodes):
        raise ValueError("patched DSL has a depends_on cycle")

    entry_b, exit_b = _entry_exit(before_nodes)
    entry_a, exit_a = _entry_exit(nodes)
    if entry_a != entry_b:
        raise ValueError("patch changes the pipeline's entry nodes")
    if exit_a != exit_b:
        raise ValueError("patch changes the pipeline's exit nodes")

    if tool_registry is not None:
        allowed = registry_names(tool_registry) | INTERNAL_TOOL_NAMES
        for node in nodes:
            tool = _node_tool(node)
            if tool and tool not in allowed:
                raise ValueError(f"node {node['id']} uses unknown tool '{tool}'")
        for node in nodes:
            if _node_tool(node) is None and not (
                node.get("agent_slug")
                or node.get("agent_id")
                or _node_kind(node) == "structured"
            ):
                raise ValueError(f"node {node['id']} has no tool or agent_slug")

    return patched


def _node_kind(node: dict[str, Any]) -> str:
    kind = str(node.get("type") or "").strip().lower()
    if kind:
        return kind
    return "agent" if (node.get("agent_slug") or node.get("agent_id")) else "tool"


# Older name, kept for callers that imported the private helper.
_validate_patch = validate_patch


def normalize_risk_level(value: Any) -> str:
    """Unknown or missing risk reads as high. The reviewer can lower it."""
    level = str(value or "").strip().lower()
    return level if level in {"low", "medium", "high"} else "high"


async def propose_patch(
    *,
    llm_router: Any,
    model: str,
    dsl_before: dict[str, Any],
    failure: dict[str, Any],
    recent_successes: list[dict[str, Any]],
    tool_registry: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run the Pipeline Surgeon LLM call and return a validated proposal."""
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        dsl=json.dumps(dsl_before, default=str)[:24_000],
        failure=json.dumps(failure, default=str)[:8_000],
        recent_successes=json.dumps(recent_successes, default=str)[:8_000],
        tool_registry=json.dumps(tool_registry, default=str)[:6_000],
    )

    # LLMRouter.complete() returns an LLMResponse, JSON is enforced by the
    # system prompt plus the fence tolerant parsing below.
    raw = await llm_router.complete(
        model=model,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=0.1,
        max_tokens=2_000,
    )
    if isinstance(raw, dict):
        text = (raw.get("text") or raw.get("content") or "").strip()
    else:
        text = str(getattr(raw, "content", raw) or "").strip()

    text = text.strip("` \n\t")
    if text.startswith("json\n"):
        text = text[5:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("surgeon returned non-JSON output")
    payload = json.loads(text[start : end + 1])

    title = str(payload.get("title", "")).strip()[:240]
    rationale = str(payload.get("rationale", "")).strip()[:4000]
    try:
        confidence = float(payload.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    risk_level = normalize_risk_level(payload.get("risk_level"))
    confidence = max(0.0, min(1.0, confidence))
    patch_ops = payload.get("json_patch")
    if not title:
        raise ValueError("surgeon proposal has no title")

    dsl_after = validate_patch(dsl_before, patch_ops, tool_registry)

    return {
        "title": title,
        "rationale": rationale,
        "confidence": confidence,
        "risk_level": risk_level,
        "json_patch": patch_ops,
        "dsl_before": dsl_before,
        "dsl_after": dsl_after,
    }
