# Pipeline data flow

> How does one pipeline node send a value to another, when does an upstream output get materialised vs templated, and what exactly is in scope when a child pipeline runs inside a parent. The pipelines doc covers shape. This page covers wire format and scoping.

---

## Three ways to pass data between nodes

The engine in [`apps/agent-runtime/engine/pipeline.py`](../../apps/agent-runtime/engine/pipeline.py) supports three communication shapes. Each has a different scope rule.

### 1. Implicit upstream — via `depends_on` only

```yaml
- id: fetch
  tool: http_get
  arguments: { url: "https://api.example.com/orders" }

- id: count
  tool: jq
  depends_on: [fetch]
  arguments:
    expression: "length"
    data: "{{fetch}}"
```

`{{fetch}}` resolves to the full output of the `fetch` node — its tool result object, structured. `{{fetch.body}}` would resolve to just the body. Dot-paths drill into nested JSON.

`depends_on` is the **only** edge that affects scheduling. The template engine doesn't add an implicit dependency just because you used `{{some_node.x}}` — if `some_node` isn't in `depends_on`, the template fires before it has run and resolves to `[not available]`. Always pair the template with the dependency.

### 2. Explicit `input_mappings`

```yaml
- id: classify
  tool: llm_complete
  depends_on: [fetch]
  arguments:
    model: "claude-haiku-4-5"
    prompt: "Classify this order: {payload}"
  input_mappings:
    payload:
      source_node: fetch
      source_field: body.line_items
```

`input_mappings` pipes a specific field from a source node into a specific argument key. Internally:

```python
# pipeline.py:339-389
def _resolve_inputs(node, node_outputs):
    resolved = dict(node.arguments)
    for arg_name, mapping in node.input_mappings.items():
        source_output = node_outputs.get(mapping.source_node)
        if source_output is None:
            continue                                 # source not run yet — skip
        value = _extract_field(source_output, mapping.source_field)
        if value is not None:
            resolved[arg_name] = value
    return resolved
```

The mapped value **overrides** the default in `arguments`. If you wrote `arguments: { payload: "fallback" }` and a mapping for `payload`, the mapping wins when the source ran.

### 3. Template strings — `{{node.field}}` substitution

This is the most-used form. Template substitution runs *after* input_mappings and merges into the same `resolved` dict. The implementation has two important branches.

```python
# pipeline.py:339-389 (paraphrased)
whole = pattern.fullmatch(value)
if whole is not None:
    # "{{plan.actions}}" — whole-value template
    # Returns the extracted object unchanged (list/dict stays structured)
    resolved[key] = _extract_field(node_outputs[whole_node], whole_field)
else:
    # "prefix {{x.y}} suffix" — embedded template
    # Each match is replaced by str() or json.dumps() depending on type
    resolved[key] = pattern.sub(_replacer, value)
```

The whole-value vs embedded distinction matters. **`arguments.payload: "{{plan.actions}}"`** delivers the structured list `[{"id": 1}, …]` to the next tool. **`arguments.payload: "actions are {{plan.actions}}"`** delivers the *string* `"actions are [{\"id\": 1}, ...]"` because it has to interpolate inside a wider string.

If a template references a node that has not run (skipped by a condition, or upstream failed), the value resolves to the literal string `[not available]`. Downstream tools see a string, not `None`. This is intentional — it surfaces the gap as a visible value the LLM can reason about rather than failing silently with a null.

---

## Topological scheduling — what runs in parallel

The engine sorts the DAG into layers. Every node in a layer runs concurrently. The next layer waits for the current one to finish.

```python
# pipeline.py:286-318
def _topological_sort(nodes):
    in_degree = {n.id: 0 for n in nodes}
    adjacency = {n.id: [] for n in nodes}
    for node in nodes:
        for dep in node.depends_on:
            adjacency[dep].append(node.id)
            in_degree[node.id] += 1
    layers = []
    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    while queue:
        layers.append(sorted(queue))    # sort for determinism
        next_queue = []
        for nid in queue:
            for child in adjacency[nid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    next_queue.append(child)
        queue = next_queue
    return layers
```

Two important consequences.

- Cycles are caught here, not at runtime — the engine raises `ValueError("Cycle detected in pipeline DAG")` before any node runs.
- Within a layer, execution order is sorted by node ID for determinism. This is a debugging convenience — re-running a deterministic pipeline twice gives byte-identical SSE traces, so a regression can be diffed.

The maximum width of any layer is bounded by `pipeline.max_concurrency` (default unlimited, but capped at 20 in practice by the runtime's own semaphore on `asyncio.gather`).

---

## Conditions — gating downstream nodes

A node can carry a condition that gates whether it runs.

```yaml
- id: classify
  tool: llm_complete
  depends_on: [fetch]
  arguments: { ... }

- id: notify_slack
  tool: slack_send
  depends_on: [classify]
  condition:
    source_node: classify
    field: priority
    operator: eq
    value: "high"
```

Operators (defined in `NodeCondition`, [pipeline.py:21-59](../../apps/agent-runtime/engine/pipeline.py)): `eq`, `neq`, `gt`, `lt`, `gte`, `lte`, `contains`, `not_contains`, `in`, `not_in`.

A condition that evaluates to false skips the node. Skipped nodes propagate — every downstream node that depended on a skipped node also skips, unless it depends on a sibling that succeeded.

This makes "branch and merge" possible without a special node type — just connect two siblings to a downstream merge node, both gated by complementary conditions, and the merge sees exactly one of them with the other resolving to `[not available]`.

---

## Switch — explicit N-way branching

When a node should route to *one of many* downstream nodes by value, use a switch.

```yaml
- id: router
  tool: noop
  switch:
    source_node: classify
    field: category
    cases:
      - { operator: eq, value: "refund",  target_node: refund_path }
      - { operator: eq, value: "complaint", target_node: complaint_path }
      - { operator: contains, value: "urgent", target_node: escalate_path }
    default_node: ack_path
```

Only the target node activates. Other case targets are auto-skipped *with their entire downstream subgraph*. This is one of the few places the engine walks the DAG twice — once to mark deactivated branches, once to schedule the active ones.

---

## forEach — iterating over an upstream list

```yaml
- id: process_each_order
  for_each:
    source_node: fetch
    source_field: body.orders
    item_variable: order
    max_concurrency: 5
  body:
    - id: enrich
      tool: db_lookup
      arguments: { id: "{{order.id}}" }
    - id: score
      tool: ml_predict
      depends_on: [enrich]
      arguments: { features: "{{enrich.features}}" }
```

The body is a *sub-pipeline*. Every iteration runs an independent execution of the body with `order` bound to the current item. `max_concurrency` is per-iteration (default 10). The iteration outputs are collected as a list at `{{process_each_order.results}}` for downstream consumers.

Scope inside the body — every node *in the body* sees `{{order.*}}`. Nodes *outside* the body do not. The body's outputs (the `results` list) are scoped to the parent. There is no leak in either direction.

---

## while — repeat a body until a flag flips

```yaml
- id: poll_until_ready
  while_loop:
    condition: { source_node: status_check, field: ready, operator: eq, value: false }
    body_nodes: [status_check, sleep]
    max_iterations: 50
```

Re-executes the named body nodes until the condition becomes false or `max_iterations` is hit (hard cap of 50). Each iteration's outputs replace the previous iteration's outputs — only the last iteration is visible downstream.

This is useful for polling, retries with state, and "wait for an external resource". For anything more complex (multi-step state machine) you usually want a pipeline of pipelines instead.

---

## Error handling — `on_error`

Every node has an `on_error` setting.

| Value | Effect |
|---|---|
| `stop` (default) | Pipeline fails. Failed node's error is on the result. Skipped downstream nodes are listed. |
| `continue` | Node is marked failed, but the pipeline keeps going. Downstream nodes that depended on this node see `[not available]` for its outputs. |
| `error_branch` | Re-routes to a named `error_branch_node`. Useful for self-healing flows that try a recovery agent on failure. |

```yaml
- id: external_fetch
  tool: http_get
  arguments: { url: "https://flaky.example.com/data" }
  max_retries: 3
  retry_delay_ms: 2000
  on_error: error_branch
  error_branch_node: fallback_fetch
```

Retry logic is per-node. `max_retries: 3` means up to 3 *additional* attempts after the first, so 4 total. Backoff is `retry_delay_ms` linear by default. The adaptive-retry strategy in [`apps/agent-runtime/engine/adaptive_retry.py`](../../apps/agent-runtime/engine/adaptive_retry.py) is opt-in per-node (`retry_strategy: "adaptive"`) and switches the delay to exponential with jitter on tool-class errors.

---

## Merge — recombining branches

When two upstream branches need to feed one downstream node, you can merge them explicitly.

```yaml
- id: combine
  merge:
    mode: append           # or "zip" or "join"
    join_field: order_id   # required when mode == "join"
    source_nodes: [path_a, path_b]
```

| Mode | Semantics |
|---|---|
| `append` | Output is the list `[output_a, output_b]`. |
| `zip` | If both outputs are lists of equal length, output is the list of pairs. |
| `join` | Both outputs are lists of objects. Output is the inner-join keyed on `join_field`. |

For simple combines, a downstream node that just references `{{path_a.x}}` and `{{path_b.y}}` in its arguments is usually cleaner than a merge node.

---

## Agent steps — calling an LLM as a node

A node with `type: agent` and `agent_slug` runs an `agent_step` — a thin wrapper that:

1. Looks up the agent's system prompt, tools, model from `agents` table.
2. Builds an `ExecutionContext` from the resolved arguments.
3. Runs one full ReAct loop in-process.
4. Returns the agent's structured output as the node output.

```yaml
- id: classify_intent
  type: agent
  agent_slug: contractiq-intent-classifier
  arguments:
    text: "{{fetch.body.content}}"
```

The `agent_step` invocation produces an output of shape `{"response": "<json>", "cost": <float>, "model": "<str>"}`. The engine auto-unwraps `response` so downstream nodes see the parsed JSON directly without having to do `{{classify_intent.response.priority}}`. They write `{{classify_intent.priority}}`.

This is one of two ways to compose agents (the other is `invoke_agent` from inside another agent — see [06-agent-to-agent](06-agent-to-agent.md)).

---

## Structured-output nodes — assemble without a tool

The `structured_output: true` flag turns a node into a pure assembly step.

```yaml
- id: final_report
  structured_output: true
  depends_on: [enrich, score, flag]
  arguments:
    customer_id: "{{enrich.customer_id}}"
    risk_score: "{{score.value}}"
    flags: "{{flag.results}}"
    timestamp: "{{ now }}"
```

No tool call. The node template-resolves its `arguments` and returns the dict. This lets a pipeline declare its final shape without a dummy `noop` tool. The engine returns this node's output as `pipeline.final_output` if it has no children.

---

## Nested pipelines and scope

A pipeline node can itself be `type: pipeline` and point at another pipeline by slug. The semantics:

- The child pipeline runs its own topological sort.
- The child's `{{context.*}}` namespace includes the *parent's* node outputs that were explicitly passed as inputs. Nothing else from the parent is visible.
- The child's outputs are returned as a single dict, available to parent downstream nodes as `{{<child_node_id>.*}}`.

There is no auto-inheritance of variables across nesting levels. If a deeply nested grandchild needs a value from the root, every layer in between has to forward it explicitly. This is verbose but unambiguous — the alternative (variable bleed through scopes) is the source of most pipeline-debugging pain in other engines.

Recursion is allowed but has no automatic depth cap. The runtime's per-execution iteration budget bounds it indirectly. A pipeline that calls itself without a base case will burn the budget and fail with an iteration-limit error.

---

## How a pipeline communicates with the world

The pipeline executor itself does not own I/O. Every external interaction is a tool call. The full inventory of "talks to the outside world" tools at the time of writing:

- `http_get` / `http_post` — generic HTTP, used for almost everything
- `kb_search` — vector search against a knowledge base
- `db_query` — Postgres read (tenant-scoped, no writes from here)
- `slack_send`, `email_send` — outbound notifications
- `code_runner` — sandboxed multi-language script
- `invoke_agent` — call another agent (see [06-agent-to-agent](06-agent-to-agent.md))
- the ~120 first-party data tools (eia, yahoo_finance, opensanctions, …)

Every tool call goes through the same registry and the same sandbox. Whether a node calls `eia_open_data` directly or asks an agent to call it, the call ends up at the same Python implementation. The pipeline DAG just lets you skip the LLM when you do not need its judgement.

---

## Common pipeline mistakes

1. **Template without dependency.** `{{x.y}}` does not auto-add `x` to `depends_on`. The engine will not warn — your value will be `[not available]` at runtime.
2. **Whole-value vs embedded confusion.** `"{{plan}}"` and `" {{plan}}"` (note leading space) deliver different types. If you wanted a structured value, do not pad it.
3. **Cycles.** Caught by the topological sort *at load time*. The error message lists the nodes in the cycle.
4. **forEach concurrency leaks.** Setting `max_concurrency: 100` will not actually parallelise that much — the runtime pod's HTTP client pool is the next bottleneck. Tune both together.
5. **Mutating arguments inside a tool.** The `resolved` dict is passed by reference to the tool implementation. A tool that mutates it has changed the recorded `resolved_arguments` on the node result. Treat the dict as read-only.

---

## See also

- [01-pipelines](01-pipelines.md) — the high-level shape, lifecycle, and node types
- [02-tools](02-tools.md) — the tool framework that pipeline nodes call
- [06-agent-to-agent](06-agent-to-agent.md) — when to fan out from inside an agent instead
- [04-streaming-tracing](04-streaming-tracing.md) — events that pipelines emit

---

## Source map

| What | Where |
|---|---|
| **Pipeline executor + topo sort** | [`apps/agent-runtime/engine/pipeline.py`](../../apps/agent-runtime/engine/pipeline.py) — `_topological_sort` at line 286, `_resolve_inputs` around line 339, main `execute_pipeline` loop at line 466 |
| **NodeCondition operators** | same file — search for `class NodeCondition` |
| **Adaptive retry** | [`apps/agent-runtime/engine/adaptive_retry.py`](../../apps/agent-runtime/engine/adaptive_retry.py) |
| **Pipeline schema (validation)** | [`apps/api/app/schemas/pipelines.py`](../../apps/api/app/schemas/pipelines.py) |
| **Tests** | [`apps/agent-runtime/tests/test_pipeline.py`](../../apps/agent-runtime/tests/test_pipeline.py), [`test_tool_chaining.py`](../../apps/agent-runtime/tests/test_tool_chaining.py) |
| **Builder canvas (visual editor)** | [`apps/web/src/app/(app)/builder/page.tsx`](../../apps/web/src/app/(app)/builder/page.tsx) — see [05-ui/01-builder-canvas](../05-ui/01-builder-canvas.md) |
| **Healing + drift on pipeline runs** | [10-pipeline-healing-drift](10-pipeline-healing-drift.md) |
