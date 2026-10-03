# Executions, invocations, traces

Source: [`packages/db/models/execution.py`](../../packages/db/models/execution.py)

---

## `executions`

One row per agent or pipeline run. Written when the run starts, updated when it
reaches a terminal state. It is an ordinary Postgres table. The TimescaleDB
hypertable in the stack is `metrics`, used by `tsdb_query`, not this one.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary key. Surfaced to clients so they can poll or stream. |
| `tenant_id` / `agent_id` / `user_id` | uuid | Scope and ownership. |
| `subject_id` / `subject_type` | text | The acting subject when a call is delegated (`actAs`). Lets a standalone app run as one of its own users while authenticating with its platform key. Added by `e2f3a4b5c6d7`. |
| `input_message` | text | What was asked. |
| `output_message` | text | The answer, or the moderation or grounding refusal. |
| `status` | enum | `running`, `completed`, `failed`, `cancelled`. Stored uppercase in Postgres. |
| `parent_execution_id` | uuid | Set when one agent invokes another, and on a replay, so a fan-out is reconstructable. |
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
| `cost` | Total in USD. For a pipeline, the sum over every step, failed and retried ones included. |
| `anthropic_cost` / `openai_cost` / `google_cost` / `other_cost` | Per-provider split, so a run that fell back mid-way shows where the spend went. These are `NOT NULL` and default to 0. |
| `model_requested` | What the agent's `model_config` asked for. Added by `a8b9c0d1e2f3`. |
| `model_used` | What actually served the run. `pipeline` for a pipeline run. |
| `model_fallback_reason` | Why they differ, when they do. |

`model_requested` and `model_used` differ whenever the router swaps provider, and
always under exclusive subscription mode, which pins every call to the
configured subscription model regardless of what the agent asked for.

`cost` is nullable, and zero is a real value rather than a missing one. A
subscription-served run genuinely costs nothing and stores `0.000000`. NULL
means the cost was never recorded, which is a different thing. Dashboards that
treat NULL and zero the same will misreport.

---

## Provenance and risk tier

Added by `c1d2e3f4a5b6_governance_core`. These answer "exactly what ran, and how risky was it".

| Column | Type | Notes |
|---|---|---|
| `risk_tier` | varchar(16) | `low`, `medium`, `high` or `critical`. Starts at the agent's tier and can only go up during the run. Indexed. |
| `risk_reasons` | jsonb | Why the run reached its tier, one entry per escalation. |
| `agent_revision` | int | Latest `agent_revisions.revision_number` for the agent at insert time. |
| `prompt_hash` | varchar(64) | SHA-256 of the system prompt. |
| `provenance` | jsonb | `config_hash`, `agent_version`, `model`, `temperature`, `tools`, `risk_tier`. A pinned replay adds `replay_of` and `replay_mode`. |

None of this depends on the insert path remembering it. A `BEFORE INSERT`
trigger, `executions_provenance`, fills the columns from the `agents` row when
`provenance` is NULL. It hashes `system_prompt || '|' || model_config` into
`config_hash` and writes the pair into `execution_config_snapshots`.

### `execution_config_snapshots`

| Column | Notes |
|---|---|
| `config_hash` | Primary key. SHA-256 hex. |
| `agent_id` | Indexed, no foreign key, so the snapshot outlives the agent. |
| `system_prompt` / `model_config` | Exactly what the run used. |
| `created_at` | First time this config was seen. `ON CONFLICT DO NOTHING` keeps one row per hash. |

`GET /api/governance/runs/{id}/provenance` compares the snapshot with the
current agent and lists the keys that changed since. A pinned replay rebuilds
the run from the snapshot. Eval runs record the same `config_hash`, which is how
the eval gate knows a suite passed on this exact config.

### Events

A second trigger, `executions_emit_event` (`AFTER UPDATE OF status`, added by
`fe18a43f0be1`), writes an `execution.completed` or `execution.failed` row into
`event_outbox` whenever status changes to completed or failed. See
[06-evals-sources-events](06-evals-sources-events.md).

---

## Timing

`created_at`, `started_at` and `completed_at` are separate because a queued run
waits before it starts, and queue latency is worth seeing on its own.
`duration_ms` is computed at the terminal transition rather than derived at read
time.

## Queue lease

Added by `09519dee709f`. A runtime pool consumer claims the row before it runs a
queued execution, so a redelivered message never runs it twice at once.

| Column | Type | What it holds |
|---|---|---|
| `runner_id` | varchar(128) | Pod, process and a random suffix of the consumer that holds the run |
| `lease_expires_at` | timestamptz | When the lease runs out. Renewed while the run lives. A later time means the owner is alive, so duplicates wait and the stale sweeper skips the row |
| `delivery_attempts` | int, default 0 | Times a consumer has picked the run up. At `CONSUMER_MAX_ATTEMPTS` (3) the run fails with `STALE_SWEEP` |

Inline runs in the API leave all three empty. See
[02-runtime/08-queue-scaling](../02-runtime/08-queue-scaling.md#at-least-once-delivery).

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
| `trace_id` | varchar(32). Correlates with OpenTelemetry spans and the Grafana dashboards. Partial index where not NULL. |

---

## Invocation side tables

`executions` records the run. These record what the run reached into, each with
its own latency and outcome, so a slow agent can be attributed to a slow
dependency:

| Table | Records |
|---|---|
| `tool_invocations` | Direct tool execute calls from the SDK or REST, outside an agent loop. Tool calls inside a run live in `executions.tool_calls`. Columns include `tool_slug`, `via`, `arguments`, `status` (`ok` / `error` / `timeout`), `acting_subject`, `api_key_id`, `trace_id`. |
| `ml_model_invocations` | Predictions against a deployed ML model, with `predicted_class`, `confidence`, `deployment_type`. |
| `code_asset_invocations` | Code asset runs with `stdout`, `stderr`, `exit_code`, `image_tag`, `schema_validated`. |
| `kb_query_invocations` | Knowledge searches, with `search_mode`, `top_k` and `hit_count`. |

---

## Idempotency, batches, DLQ, drift

| Table | Key columns | Notes |
|---|---|---|
| `execution_idempotency` | `key`, `agent_id`, `execution_id`, `status`, `cached_response`, `expires_at` | Caches the execute response per `Idempotency-Key` header. Added by `1100_c_idempotency`. |
| `batch_jobs` | `agent_id`, `user_id`, `status`, `total_inputs`, `completed_count`, `failed_count`, `results` | One row per batch execute request. |
| `dead_letter_executions` | `execution_id`, `agent_id`, `failure_code`, `error_message`, `original_input`, `replay_count`, `last_replay_at`, `resolved`, `replay_execution_id` | Added by `1100_d_dead_letter`. `f2a3b4c5d6e7` makes `execution_id` unique, so one failed run has one row, and adds `replay_execution_id` (`ON DELETE SET NULL`) pointing at the latest run spawned by replay. |
| `drift_alerts` | `agent_id`, `execution_id`, `severity`, `metric`, `baseline_value`, `current_value`, `deviation_pct`, `acknowledged` | Written by the drift detector. |

---

## Self-healing tables

`pipeline_run_diffs` captures a failing node's shape and a sample of its inputs
and outputs so Pipeline Surgeon has something concrete to diagnose. It is
written best-effort from the runtime and keyed on `execution_id`, so a row with
no valid execution id is dropped on the foreign key.

`pipeline_patch_proposals` holds the drafted fix: `dsl_before`, `json_patch`,
`dsl_after`, `confidence`, `risk_level`, `status`, who decided and when, and
rollback columns. `1100_f_patch_cas` added `dsl_before_sha256` and
`applied_snapshot`. Applying a patch compares the live pipeline against
`dsl_before_sha256` first, so a patch drafted against an older version cannot
overwrite a newer edit. See
[02-runtime/10-pipeline-healing-drift](../02-runtime/10-pipeline-healing-drift.md).

---

## Retention

Executions accumulate quickly. A stale-execution sweeper marks runs abandoned
past their timeout, and the archiver moves old rows out per tenant. Both take an
advisory lock so only one pod does the work. The archive tables are covered in
[07-tools-and-operations](07-tools-and-operations.md).

---

## See also

- [01-agents](01-agents.md) — the agent side of the relationship
- [05-governance-decisions](05-governance-decisions.md) — risk tiers and policies
- [02-runtime/04-streaming-tracing](../02-runtime/04-streaming-tracing.md) — how a run streams while it writes this row
- [02-runtime/09-state-machines](../02-runtime/09-state-machines.md) — the legal status transitions
