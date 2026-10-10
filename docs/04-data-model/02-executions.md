# Executions, invocations, traces

Source: [`packages/db/models/execution.py`](../../packages/db/models/execution.py)

---

## `executions`

One row per agent or pipeline run. Written when the run starts, updated when it
reaches a terminal state. It is an ordinary Postgres table. TimescaleDB is a
separate database (`TSDB_URL`) that the `tsdb_query` tool reads, not this one.
The table has `created_at` but no `updated_at`.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary key. Surfaced to clients so they can poll or stream. |
| `tenant_id` / `agent_id` / `user_id` | uuid | Scope and ownership. Each is a foreign key and indexed. |
| `subject_id` / `subject_type` | varchar(128) / varchar(64) | The acting subject when a call is delegated (`actAs`). Lets a standalone app run as one of its own users while authenticating with its platform key. `subject_id` is indexed. Added by `e2f3a4b5c6d7`. |
| `input_message` | text | What was asked. |
| `output_message` | text | The answer, or the moderation or grounding refusal. |
| `status` | enum `execution_status` | `running` (default), `completed`, `failed`, `cancelled`. Stored as the uppercase member names in Postgres. |
| `parent_execution_id` | uuid | Self foreign key. Set when one agent invokes another, and on a replay, so a fan-out is reconstructable. |
| `retry_count` | int | Default 0. Incremented on replay. |
| `trigger_id` | uuid | The `agent_triggers` row that started the run. `ON DELETE SET NULL`, so the run outlives its trigger. Indexed. Added by `trig0prov01`. |
| `trigger_kind` | varchar(32) | What started the run. See [Started by](#started-by). Indexed. NULL on runs older than `trig0prov01`. |
| `trigger_name` | varchar(255) | The trigger, subscription, source or parent agent name at the time of the run. Kept when the trigger is deleted. |

### Started by

Every path that writes an `executions` row sets `trigger_kind`. The helper is
[`apps/api/app/core/run_origin.py`](../../apps/api/app/core/run_origin.py).

| `trigger_kind` | Set by | `trigger_id` | `trigger_name` |
|---|---|---|---|
| `schedule` | the scheduler, `check_due_triggers` | the trigger | the trigger name |
| `webhook` | `POST /api/triggers/webhook/{token}` | the trigger | the trigger name |
| `manual` | Run now on a trigger, or a signed-in person running an agent outside chat | the trigger on Run now | the trigger name on Run now |
| `event` | an event subscription with a run target | none | the subscription name |
| `source_watch` | a `source.changed` event delivered to a run target | none | the source name |
| `chat` | the chat pages, which send `source: "chat"` | none | none |
| `api` | any call with an API key, SDK included | none | none |
| `playground` / `builder` | the SDK playground, the pipeline builder and the BPM analyzer test | none | none |
| `pipeline` / `agent` | a child run started by `invoke_agent`, by the parent's mode | none | the parent agent name |
| `autonomy_sample` | Run sample on the earned autonomy page | none | `Earned autonomy sample` |
| `eval` | an evaluation suite case | none | none |
| `replay` | a replay from the run page, the governance replay or the dead letter queue | none | how it was replayed |
| `a2a` / `batch` / `meeting` | the A2A endpoint, batch execute and the meeting bot | none | none |

A browser may only claim `chat`, `playground` or `builder` through `source` on
`POST /api/agents/{id}/execute`. Every other kind is decided on the server.

### Status is not the same as success

A pipeline execute returns HTTP 200 with `status = failed` rather than a 5xx.
The caller needs the `execution_id` to inspect what went wrong, and a 5xx body
would not carry one. Check `status`, never just the HTTP code.

---

## Tokens, cost and which model actually ran

| Column | Notes |
|---|---|
| `input_tokens` / `output_tokens` | int, nullable. Aggregated across every turn of the run. |
| `cost` | numeric(10,6), nullable. Total in USD. |
| `anthropic_cost` / `openai_cost` / `google_cost` / `other_cost` | numeric(10,6). Per-provider split, so a run that fell back mid-way shows where the spend went. `NOT NULL`, default 0. Written on every terminal update, see `provider_cost_values()` in `models/execution.py`. |
| `model_requested` | varchar(100). What the agent's `model_config` asked for. Added by `a8b9c0d1e2f3`. |
| `model_used` | varchar(100). What actually served the run. `pipeline` for a pipeline run. |
| `model_fallback_reason` | varchar(64). Why they differ, when they do. |

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
`config_hash` and writes the pair into `execution_config_snapshots`. A row
inserted with `provenance` already set, or with no `agent_id`, is left alone.

### `execution_config_snapshots`

| Column | Notes |
|---|---|
| `config_hash` | Primary key. SHA-256 hex. |
| `agent_id` | Nullable, indexed, no foreign key, so the snapshot outlives the agent. |
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
waits before it starts. `duration_ms` (int) is stored, not derived at read time.

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
| `confidence_score` | numeric(3,2). Heuristic over tool-call count, failures and output length. |
| `error_message` | Free text. |
| `failure_code` | varchar(64), indexed. Stable identifier such as `MODERATION_BLOCKED` or `GROUNDING_REQUIRED_VIOLATION`. Group alerts on this, not on the message. |
| `trace_id` | varchar(32), indexed. Correlates with OpenTelemetry spans and the Grafana dashboards. |

Composite indexes: `ix_executions_agent_status` on `(agent_id, status)`,
`ix_executions_user_agent` on `(user_id, agent_id)`, `ix_executions_tenant_created`
on `(tenant_id, created_at)`. `selfimp0001` adds `ix_executions_failed_completed`
on `completed_at` where status is `FAILED`.

---

## Invocation side tables

`executions` records the run. These record what the run reached into, each with
its own `duration_ms`, `is_error` and `error_message`.

| Table | Records |
|---|---|
| `tool_invocations` | Direct tool execute calls from the SDK or REST, outside an agent loop. Tool calls inside a run live in `executions.tool_calls`. Columns include `tool_slug`, `via` (`direct`, `agent` or `pipeline`), `parent_execution_id`, `arguments`, `status` (`ok` / `error` / `timeout`), `acting_subject`, `api_key_id`, `trace_id`. Only `created_at`. |
| `ml_model_invocations` | Predictions against a deployed ML model, with `ml_model_id`, `execution_id`, `predicted_class`, `confidence`, `deployment_type`, `caller_source`. |
| `code_asset_invocations` | Code asset runs with `code_asset_id`, `execution_id`, `stdout`, `stderr`, `exit_code`, `image_tag`, `schema_validated`, `caller_source`. |
| `kb_query_invocations` | Knowledge searches, with `kb_collection_id`, `execution_id`, `search_mode`, `top_k`, `hit_count`, `caller_source`. |

---

## Idempotency, batches, DLQ, drift

| Table | Key columns | Notes |
|---|---|---|
| `execution_idempotency` | `key`, `agent_id`, `execution_id`, `status`, `cached_response`, `expires_at` | Caches the execute response per `Idempotency-Key` header. Unique on `(tenant_id, key)`. Added by `1100_c_idempotency`. |
| `batch_jobs` | `agent_id`, `user_id`, `status`, `total_inputs`, `completed_count`, `failed_count`, `results` | One row per batch execute request. |
| `dead_letter_executions` | `execution_id`, `agent_id`, `failure_code`, `error_message`, `original_input`, `replay_count`, `last_replay_at`, `resolved`, `replay_execution_id` | Added by `1100_d_dead_letter`. `f2a3b4c5d6e7` makes `execution_id` unique, so one failed run has one row, and adds `replay_execution_id` pointing at the latest run spawned by replay. |
| `drift_alerts` | `agent_id`, `execution_id`, `severity`, `metric`, `baseline_value`, `current_value`, `deviation_pct`, `acknowledged` | Written by the drift detector. `agent_id` cascades on delete, `execution_id` is set to NULL. |

---

## Self-healing tables

`pipeline_run_diffs` captures a failing node's shape and a sample of its inputs
and outputs so Pipeline Surgeon has something concrete to diagnose. `pipeline_id`
and `execution_id` are foreign keys with `ON DELETE CASCADE`, so a row with no
valid execution id cannot be written.

`pipeline_patch_proposals` holds the drafted fix. Columns are `dsl_before`, `json_patch`,
`dsl_after`, `confidence`, `risk_level`, `status` (`pending`, `accepted`,
`rejected`, `superseded`), who decided and when, and rollback columns. `1100_f_patch_cas` added `dsl_before_sha256` and
`applied_snapshot`. Applying a patch compares the live pipeline against
`dsl_before_sha256` first, so a patch drafted against an older version cannot
overwrite a newer edit. See
[02-runtime/10-pipeline-healing-drift](../02-runtime/10-pipeline-healing-drift.md).

---

## Retention

A stale-execution sweeper fails runs left `running` past their timeout, and the
archiver moves old rows out per tenant. The archive tables are covered in
[07-tools-and-operations](07-tools-and-operations.md).

---

## See also

- [01-agents](01-agents.md): the agent side of the relationship
- [05-governance-decisions](05-governance-decisions.md): risk tiers and policies
- [02-runtime/04-streaming-tracing](../02-runtime/04-streaming-tracing.md): how a run streams while it writes this row
- [02-runtime/09-state-machines](../02-runtime/09-state-machines.md): the legal status transitions
