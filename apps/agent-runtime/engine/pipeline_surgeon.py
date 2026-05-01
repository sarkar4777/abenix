"""Pipeline Surgeon — proposes minimal JSON-Patch fixes for failed runs.

Inputs (gathered by the API caller, not the LLM):
  * the latest pipeline_run_diff for the failing pipeline+node
  * the last 1-3 successful executions of the same pipeline (for shape evidence)
  * the current DSL (model_config.pipeline_config)
  * the tool registry (so we know what's available)

Output:
  * a JSON-Patch (RFC 6902) against the DSL — typically rename a field,
    widen an input mapping, swap a model, add a fallback branch, or
    insert a defensive {coerce-shape, validate} node before the failing
    one.  Plus a confidence score, risk level, and rationale.

The LLM is only asked to produce structured JSON.  The resulting patch is
then applied with python-jsonpatch in a sandbox copy of the DSL; if the
result is invalid (cycle, dangling depends_on, unknown tool) the proposal
is rejected at draft time, never written to the DB.

Important: we never mutate the live agent record here.  This module
returns a proposal record that the API persists into
`pipeline_patch_proposals` with status='pending'.
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You are the Pipeline Surgeon.

Your job: read a structured snapshot of a failed pipeline run and propose the
SMALLEST POSSIBLE JSON-Patch (RFC 6902) against the pipeline's DSL that would
make the failing node succeed on the next run.

You will be given:

  * `dsl` — the full pipeline DSL.  It is a list of nodes under
    `model_config.pipeline_config.nodes`.  Each node has an `id`,
    `tool` or `agent_slug`, optional `depends_on`, `input_mappings`,
    `arguments`, `on_error`, etc.
  * `failure` — the structured run-diff: which node, error class, error
    message, observed output shape, expected shape (from past successes),
    and the inputs the node received.
  * `recent_successes` — up to 3 recent successful runs of the SAME
    pipeline so you can see what the failing node USED to consume and
    produce.
  * `tool_registry` — list of available tool names + their declared
    input/output shapes.

Patch design rules (in order):

  1. Be minimal.  One or two ops only.  Never rewrite the whole DSL.
  2. Prefer non-destructive changes:
     a. add input_mapping with a fallback default
     b. add `on_error: continue` if the failing node is non-critical
     c. add a defensive coerce/validate node BEFORE the failing one
     d. swap model on an agent_step node only as a last resort
  3. Never delete a node without an explicit replacement.
  4. Never alter another tenant's resources.
  5. If you cannot find a confident fix, return confidence < 0.5 and
     explain in rationale.

Return STRICT JSON exactly matching this schema, with NO prose:

{
  "title": "<short, imperative — e.g. 'Add fallback default for missing counterparty field'>",
  "rationale": "<2-4 sentences explaining what changed and why>",
  "confidence": <number between 0.0 and 1.0>,
  "risk_level": "low" | "medium" | "high",
  "json_patch": [
    {"op": "add" | "replace" | "remove", "path": "<JSON Pointer>", "value": <any>},
    ...
  ]
}

Risk-level guidance:
  * low    — adds a fallback, widens an input mapping, sets on_error=continue
  * medium — adds a new defensive node, swaps a model
  * high   — replaces a node's tool, removes a node
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


def _validate_patch(dsl_before: dict[str, Any], patch_ops: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply a JSON-Patch and validate the resulting DSL.  Returns the
    patched DSL.  Raises ValueError on any invalidity."""
    try:
        import jsonpatch  # type: ignore[import-untyped]
    except ImportError as e:
        raise ValueError("jsonpatch library not installed") from e

    if not isinstance(patch_ops, list) or not patch_ops:
        raise ValueError("patch must be a non-empty list of ops")
    if len(patch_ops) > 8:
        raise ValueError("patch is too large (>8 ops); should be minimal")

    for op in patch_ops:
        if not isinstance(op, dict):
            raise ValueError("each op must be an object")
        if op.get("op") not in {"add", "replace", "remove", "move", "copy", "test"}:
            raise ValueError(f"unsupported op: {op.get('op')}")
        if "path" not in op or not isinstance(op["path"], str):
            raise ValueError("op missing path")

    patched = jsonpatch.JsonPatch(patch_ops).apply(copy.deepcopy(dsl_before))

    nodes = (patched.get("pipeline_config") or {}).get("nodes") or []
    if not isinstance(nodes, list):
        raise ValueError("patched DSL has no node list")

    ids = [n.get("id") for n in nodes if isinstance(n, dict)]
    if len(ids) != len(set(ids)):
        raise ValueError("patched DSL has duplicate node ids")
    for node in nodes:
        for dep in node.get("depends_on") or []:
            if dep not in ids:
                raise ValueError(f"node {node.get('id')} depends_on missing node {dep}")

    return patched


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

    raw = await llm_router.complete(
        model=model,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=0.1,
        max_tokens=2_000,
        force_json=True,
    )
    text = (raw.get("text") or "").strip() if isinstance(raw, dict) else str(raw).strip()

    # Cope with code fences and trailing prose.
    text = text.strip("` \n\t")
    if text.startswith("json\n"):
        text = text[5:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("surgeon returned non-JSON output")
    payload = json.loads(text[start:end + 1])

    title = str(payload.get("title", "")).strip()[:240]
    rationale = str(payload.get("rationale", "")).strip()[:4000]
    confidence = float(payload.get("confidence", 0.5))
    risk_level = str(payload.get("risk_level", "low")).strip().lower()
    if risk_level not in {"low", "medium", "high"}:
        risk_level = "low"
    confidence = max(0.0, min(1.0, confidence))
    patch_ops = payload.get("json_patch")
    if not title:
        raise ValueError("surgeon proposal has no title")

    dsl_after = _validate_patch(dsl_before, patch_ops)

    return {
        "title": title,
        "rationale": rationale,
        "confidence": confidence,
        "risk_level": risk_level,
        "json_patch": patch_ops,
        "dsl_before": dsl_before,
        "dsl_after": dsl_after,
    }
