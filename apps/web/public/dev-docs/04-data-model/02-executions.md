# Executions, invocations, traces

Source: [`packages/db/models/execution.py`](../../packages/db/models/execution.py)

---

## `executions`

One row per agent or pipeline run. Written when the run starts, updated when it
reaches a terminal state.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary key. Surfaced to clients so they can poll or stream. |
| `tenant_id` / `agent_id` / `user_id` | uuid | Scope and ownership. |
| `subject_id` / `subject_type` | text | The acting subject when a call is delegated (`actAs`). Lets a standalone app run as one of its own users while authenticating with its platform key. |
| `input_message` | text | What was asked. |
| `output_message` | text | The answer, or the moderation or grounding refusal. |
| `status` | enum | `running`, `completed`, `failed`, `cancelled`. Stored uppercase in Postgres. |
| `parent_execution_id` | uuid | Set when one agent invokes another, so a fan-out is reconstructable. |
| `retry_count` | int | Incremented on replay. |

### Status is not the same as success

A pipeline execute returns HTTP 200 with `status = failed` rather than a 5xx.
That is deliberate: the caller needs the `execution_id` to inspect what went
wrong, and a 5xx body would not carry one. Check `status`, never just the HTTP
code.

---

## Tokens, cost and which model actually ran

| Column | Notes |
|---|---|
| `input_tokens` / `output_tokens` | Aggregated across every turn of the run. |
| `cost` | Total in USD. |
| `anthropic_cost` / `openai_cost` / `google_cost` / `other_cost` | Per-provider split, so a run that fell back mid-way shows where the spend went. These are `NOT NULL` and default to 0. |
| `model_requested` | What the agent's `model_config` asked for. |
| `model_used` | What actually served the run. |
| `model_fallback_reason` | Why they differ, when they do. |

`model_requested` and `model_used` differ whenever the router swaps provider, and
always under exclusive subscription mode, which pins every call to the
configured subscription model regardless of what the agent asked for.

`cost` is nullable, and zero is a real value rather than a missing one. A
subscription-served run genuinely costs nothing and stores `0.000000`. NULL
means the cost was never recorded, which is a different thing. Dashboards that
treat NULL and zero the same will misreport.

---

## Timing

`created_at`, `started_at` and `completed_at` are separate because a queued run
waits before it starts, and queue latency is worth seeing on its own.
`duration_ms` is computed at the terminal transition rather than derived at read
time.

---

## Diagnostics

| Column | Contents |
|---|---|
| `tool_calls` | jsonb. Every tool invoked, its arguments and whether it errored. |
| `node_results` | jsonb. Per-node outcome for a pipeline run. |
| `execution_trace` | jsonb. Node traces plus the tool-call summary, used by the flight recorder in the UI. |
| `confidence_score` | Heuristic over tool-call count, failures and output length. |
| `error_message` | Free text. |
| `failure_code` | Stable identifier such as `MODERATION_BLOCKED` or `GROUNDING_REQUIRED_VIOLATION`. Group alerts on this, not on the message. |
| `trace_id` | Correlates with OpenTelemetry spans and the Grafana dashboards. |

---

## Invocation side tables

`executions` records the run. These record what the run reached into, each with
its own latency and outcome, so a slow agent can be attributed to a slow
dependency:

| Table | Records |
|---|---|
| `tool_invocations` | Built-in and MCP tool calls. |
| `ml_model_invocations` | Predictions against a deployed ML model. |
| `code_asset_invocations` | Sandboxed code runs. |
| `kb_query_invocations` | Knowledge-base searches, with the retrieval mode used. |

---

## Self-healing diffs

`pipeline_run_diffs` captures a failing node's shape and a sample of its inputs
and outputs so Pipeline Surgeon has something concrete to diagnose. It is
written best-effort from the runtime and keyed on `execution_id`, so a row with
no valid execution id is dropped on the foreign key. See
[02-runtime/10-pipeline-healing-drift](../02-runtime/10-pipeline-healing-drift.md).

---

## Retention

Executions accumulate quickly. A stale-execution sweeper marks runs abandoned
past their timeout, and the archiver moves old rows out. Both take an advisory
lock so only one pod does the work.

---

## See also

- [01-agents](01-agents.md) — the agent side of the relationship
- [02-runtime/04-streaming-tracing](../02-runtime/04-streaming-tracing.md) — how a run streams while it writes this row
- [02-runtime/09-state-machines](../02-runtime/09-state-machines.md) — the legal status transitions
