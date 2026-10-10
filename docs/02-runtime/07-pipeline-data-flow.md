# Pipeline data flow

> How one pipeline node passes a value to another, which values are kept structured and which become text, and what a nested pipeline can see. [01-pipelines](01-pipelines.md) covers the shape. This page covers wire format and scope.

---

## Three ways to pass data between nodes

The engine is [`apps/agent-runtime/engine/pipeline.py`](../../apps/agent-runtime/engine/pipeline.py).

### 1. A template that names the node

```yaml
- id: fetch
  tool_name: http_client
  arguments: { method: GET, url: "https://api.example.com/orders" }

- id: summarise
  tool_name: llm_call
  arguments:
    prompt: "Summarise these orders: {{fetch.body}}"
```

`{{fetch}}` is the whole output of `fetch`. `{{fetch.body}}` is one field, and dot paths go deeper. A template that names another node adds that node to `depends_on` when the pipeline is parsed, so `summarise` waits for `fetch` without listing it. Listing it yourself is still easier to read.

### 2. `input_mappings`

```yaml
- id: classify
  tool_name: llm_call
  depends_on: [fetch]
  arguments:
    prompt: "Classify this order"
  input_mappings:
    payload:
      source_node: fetch
      source_field: body.line_items
```

`input_mappings` copies one field of a source node into one argument. It runs first, in `_resolve_inputs`:

```python
# pipeline.py, _resolve_inputs
def _resolve_inputs(node, node_outputs):
    resolved = dict(node.arguments)
    for arg_name, mapping in node.input_mappings.items():
        source_output = node_outputs.get(mapping.source_node)
        if source_output is None:
            continue
        value = _extract_field(source_output, mapping.source_field)
        if value is not None:
            resolved[arg_name] = value
    return resolved
```

A mapped value overrides the same key in `arguments` when the source ran.

### 3. Template strings

Templates are resolved after `input_mappings`, by `_resolve_templates`, through nested dicts and lists. There are two cases:

```python
# pipeline.py, _resolve_templates (shortened)
whole = pattern.fullmatch(value)
if whole is not None:
    # "{{plan.actions}}" keeps the extracted object, a list stays a list
    return extracted
# "prefix {{x.y}} suffix": each match becomes str(), or JSON for a list or dict
return pattern.sub(_replacer, value)
```

`payload: "{{plan.actions}}"` delivers the list `[{"id": 1}, …]`. `payload: "actions are {{plan.actions}}"` delivers the string `actions are [{"id": 1}, …]`.

A step can be named by its id or by its label in `arguments`, `context` and `input_mappings`. The builder gives steps ids like `step_1790931980212_b8m3`, so a step labelled `score` is reached with `{{score.response}}`. Labels are lowercased and every run of characters that is not a letter, digit or underscore becomes `_`, so `Exposure Check` is `{{exposure_check.response}}`. A label works only when it is unique, and an id always wins over a label with the same text. Elsewhere (`input`, `output`, `condition`, `required_if`) use ids.

Before a tool runs, the engine converts text arguments to the types the tool's input schema declares, one level deep (`_coerce_to_schema`). `"36"` reaching a `number` becomes `36`, `"true"` reaching a `boolean` becomes `true`, a JSON object in text becomes an object, and `"33.8, 34.6"` or `"[33.8, 34.6]"` reaching a list of numbers becomes `[33.8, 34.6]`. Text that does not convert cleanly is passed through so the tool reports it.

A template whose node did not run, or whose field does not exist, resolves to the string `[not available]`. The next tool sees that text, not `None`.

---

## Layers: what runs in parallel

`_topological_sort` sorts the DAG into layers. Every node in a layer runs at the same time under `asyncio.gather`, and the next layer waits for the whole layer.

- Each layer's list is sorted by node id, but the nodes run concurrently, so the order of events within a layer is not fixed.
- There is no concurrency cap within a layer. Only `for_each` limits its items with `max_concurrency`.
- A cycle fails the run before any node runs, with "Cycle detected in pipeline DAG. Nodes in cycle: {…}" on every node. The set lists every node that could not be scheduled, including nodes downstream of the cycle. `POST /api/pipelines/validate` catches cycles before a run.

---

## Conditions

```yaml
- id: classify
  tool_name: llm_call
  arguments: { prompt: "Rate the priority of: {{context.message}}" }

- id: notify
  tool_name: email_sender
  depends_on: [classify]
  condition:
    source_node: classify
    field: priority
    operator: eq
    value: "high"
  arguments: { to: "ops@example.com", subject: "High priority", body: "{{context.message}}" }
```

Operators are `eq`, `neq`, `gt`, `lt`, `gte`, `lte`, `contains`, `not_contains`, `in` and `not_in` (`NodeCondition`). A false condition skips the node.

A node skipped by its condition does not skip its dependents. They still run and see `[not available]` for its fields. Only a skip caused by an upstream failure is passed on. That lets two siblings with opposite conditions feed one downstream node, which sees one real value and one `[not available]`.

---

## Switch

```yaml
- id: router
  tool_name: "__switch__"
  depends_on: [classify]
  switch:
    source_node: classify
    field: category
    cases:
      - { operator: eq, value: "refund", target_node: refund_path }
      - { operator: eq, value: "complaint", target_node: complaint_path }
    default_node: ack_path
- id: refund_path
  tool_name: llm_call
  depends_on: [router]
  arguments: { prompt: "Draft a refund reply" }
```

The switch must use `tool_name: "__switch__"`. Targets must `depends_on` the switch. A target that was not activated is skipped, but its own dependents still run and see `[not available]`. See [Switch and merge](01-pipelines.md#switch-and-merge).

---

## for_each

```yaml
- id: score_each
  tool_name: agent_step
  arguments:
    agent_slug: clause-risk-analyzer
  for_each:
    source_node: extract
    source_field: clauses
    item_variable: input_message
    max_concurrency: 5
```

`for_each` reruns this one node once per item of `source_node.source_field`. The item goes into the argument named by `item_variable` and is not visible to templates. `max_concurrency` (default 10) is how many items run at once. The output is the plain list of item outputs, read as `{{score_each}}`. A node where some items failed ends `partial`.

---

## while_loop

```yaml
- id: poll_until_ready
  while_loop:
    condition: { source_node: status_check, field: ready, operator: eq, value: false }
    body_nodes: [status_check, pause]
    max_iterations: 20
```

While the condition holds, the body nodes run in order, one after another. The loop stops when the condition turns false or after `max_iterations` (default 50). Each pass overwrites the body nodes' outputs, so later nodes see the last pass. The loop node's own output is `{iterations, last_output}`.

---

## Errors and retries

| `on_error` | Effect |
|---|---|
| `stop` (default) | The node fails and its dependents are skipped. Other branches keep running. The run ends `partial`, or `failed` if nothing completed |
| `continue` | The node goes on the execution path and not into `failed_nodes`. Its dependents are still skipped with "Dependency '<id>' failed" today |
| `error_branch` | The node named in `error_branch_node` runs after the layer and can read `__error_from_<id>` |

```yaml
- id: external_fetch
  tool_name: http_client
  arguments: { method: GET, url: "https://flaky.example.com/data" }
  max_retries: 3
  retry_delay_ms: 2000
  on_error: error_branch
  error_branch_node: fallback_fetch
```

`max_retries: 3` means up to 3 more attempts after the first. Backoff is exponential, `retry_delay_ms × 2^attempt`. [`engine/adaptive_retry.py`](../../apps/agent-runtime/engine/adaptive_retry.py) exists but the pipeline engine does not use it.

---

## Merge

```yaml
- id: combine
  tool_name: "__merge__"
  depends_on: [path_a, path_b]
  merge:
    mode: append
    source_nodes: [path_a, path_b]
```

| Mode | Output |
|---|---|
| `append` | One flat list. A list output is spread in, skipped sources are dropped |
| `zip` | When every source is a list, `[{0: a0, 1: b0}, …]` up to the shortest list. Otherwise the list of source outputs |
| `join` | Lists of objects joined on `join_field`, keeping only items whose key appears in every source |

For a simple combine, one node that references `{{path_a.x}}` and `{{path_b.y}}` is often clearer than a merge node.

---

## Agent nodes

```yaml
- id: classify_intent
  type: agent
  agent_slug: contractiq-intent-classifier
  input: "{{fetch.body.content}}"
```

The engine looks up the agent by slug and passes its system prompt, model, tools, `max_iterations` and temperature to `agent_step`, which runs a full agent loop in-process. `input` becomes the message. With no message set, the run's own message is used.

`agent_step` returns `{response, model, input_tokens, output_tokens, cost, duration_ms, tool_calls_count, iterations}`. Templates look through the `response` wrapper, so `{{classify_intent.priority}}` reads a field of the agent's JSON answer.

The other way to compose agents is `invoke_agent` from inside an agent, see [06-agent-to-agent](06-agent-to-agent.md).

---

## Structured nodes

```yaml
- id: final_report
  type: structured
  depends_on: [enrich, score]
  output:
    customer_id: "{{enrich.customer_id}}"
    risk_score: "{{score.value}}"
```

`type: structured` with an `output` (or `fields`) map, or `tool_name: "__structured__"` with `arguments`, makes a node that calls no tool. It resolves the templates and returns the dict, parsing values that look like JSON. Like any node, it is the run's final output only if it is the last node to complete.

---

## Nested pipelines

There is no `type: pipeline`. Nest with the `sub_pipeline` tool:

```yaml
- id: child
  tool_name: sub_pipeline
  arguments:
    nodes:
      - { id: a, tool_name: current_time }
    context: { region: "{{context.region}}" }
    timeout_seconds: 60
```

The child sees only the `context` you pass. `timeout_seconds` defaults to 60, range 5 to 300. The node's output is the child's serialized result (`status`, `final_output`, `node_results`, …).

---

## Talking to the outside world

The engine owns no I/O. Every external call is a tool call through the same registry an agent uses. Common ones in pipelines: `http_client`, `knowledge_search`, `database_query` and `database_writer`, `email_sender`, `code_executor` and `sandboxed_job`, `invoke_agent`, and data tools such as `eia_open_data`, `yahoo_finance` and `pep_screening`. The full list is in [02-tools](02-tools.md).

---

## Common mistakes

1. **Whole-value vs embedded.** `"{{plan}}"` and `" {{plan}}"` (leading space) deliver different types. Do not pad a template that should stay structured.
2. **A label the engine does not alias.** Labels work in `arguments`, `context` and `input_mappings` only. In `input` or a condition, use the id.
3. **`for_each` concurrency.** The ad-hoc execute schema caps `max_concurrency` at 50, and a high value moves the bottleneck to the tool or the provider behind it.
4. **Tool names.** A node that names a tool not in `model_config.tools` fails with "Unknown tool", or the `/api/pipelines` routes refuse the run.

---

## See also

- [01-pipelines](01-pipelines.md) for node types, fields and run records
- [02-tools](02-tools.md) for the tool framework that nodes call
- [06-agent-to-agent](06-agent-to-agent.md) for fanning out from inside an agent
- [04-streaming-tracing](04-streaming-tracing.md) for the events a pipeline emits

---

## Source map

| What | Where |
|---|---|
| **Pipeline executor** | [`apps/agent-runtime/engine/pipeline.py`](../../apps/agent-runtime/engine/pipeline.py) — `_topological_sort`, `_resolve_inputs`, `_resolve_templates`, `_coerce_to_schema`, `PipelineExecutor._execute_governed`, `alias_labels_to_ids` |
| **Conditions** | same file, `NodeCondition` |
| **Nested pipelines** | [`apps/agent-runtime/engine/tools/sub_pipeline.py`](../../apps/agent-runtime/engine/tools/sub_pipeline.py) |
| **Pipeline schema** | [`apps/api/app/schemas/pipelines.py`](../../apps/api/app/schemas/pipelines.py) |
| **Tests** | [`apps/agent-runtime/tests/test_pipeline.py`](../../apps/agent-runtime/tests/test_pipeline.py), [`test_tool_chaining.py`](../../apps/agent-runtime/tests/test_tool_chaining.py) |
| **Builder canvas** | [`apps/web/src/app/(app)/builder/page.tsx`](../../apps/web/src/app/(app)/builder/page.tsx), see [05-ui/01-builder-canvas](../05-ui/01-builder-canvas.md) |
| **Healing and drift** | [10-pipeline-healing-drift](10-pipeline-healing-drift.md) |
