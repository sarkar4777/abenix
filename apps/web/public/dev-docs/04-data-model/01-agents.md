# Agents, revisions, pipelines

Source: [`packages/db/models/agent.py`](../../packages/db/models/agent.py)

---

## `agents`

One row per agent or pipeline. Tenant-scoped through `TenantMixin`, so every query the API
issues is filtered by `tenant_id` and nothing crosses a tenant boundary by
accident.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary key. |
| `tenant_id` | uuid | Owning tenant. |
| `creator_id` | uuid | User who created it. NULL for platform-seeded agents. |
| `name` | text | Display name. |
| `slug` | text | URL-safe identifier. The SDK and pipeline `agent_slug` references resolve against this. |
| `description` | text | Shown on the agent card and info page. |
| `system_prompt` | text | The prompt. Can be long, so it is `Text` rather than a bounded string. |
| `model_config` | jsonb | Model, sampling, iteration cap, tool list, pipeline nodes, risk tier. Mapped in Python as `model_config_` because `model_config` collides with a Pydantic attribute. |
| `agent_type` | enum | `custom`, `oob`, `vertical`. `oob` are the seeded out-of-the-box agents. |
| `category` | text | Grouping for the marketplace. |
| `status` | enum | `draft`, `pending_review`, `active`, `rejected`, `archived`. |
| `rejection_reason` | text | Set when marketplace review rejects it. |
| `is_published` / `marketplace_price` | bool / numeric | Marketplace listing. |
| `version` / `version_tag` | text | Version label and canary tag, see below. |
| `parent_agent_id` | uuid | Set on a canary variant, pointing at the agent it was branched from. |
| `traffic_weight` | float | Share of traffic for a canary variant. |
| `icon_url` | text | Card icon. |

### `model_config`

The shape the runtime reads:

```yaml
model_config:
  model: claude-sonnet-4-5-20250929
  temperature: 0.0
  max_tokens: 1024
  max_iterations: 3
  risk_tier: high          # low | medium | high | critical, default low
  output_schema: {...}     # optional JSON Schema
  input_variables:
    - name: region
      default: EMEA
  tools:
    - pii_redactor
    - knowledge_search
    - moderation_vet
```

`tools` is the enabled set for this agent. A tool that exists in the registry
but is missing from this list is rejected at validation with "exists but is not
enabled on this agent" rather than silently ignored.

`model` is what the agent requests, not necessarily what runs. When subscription
mode is exclusive the router pins every call to the configured subscription
model, and the executions row records both, see
[02-executions](02-executions.md).

`risk_tier` is read by the `executions_provenance` trigger, by the activation check
(an output schema and an allowed model may be required) and by the eval gate. See
[05-governance-decisions](05-governance-decisions.md).

`input_variables` are the declared inputs. Each `default` is applied into the run
context under whatever the caller sent, and the pipeline validator treats the names
as valid template targets.

---

## Revisions

Every change to an agent writes an `agent_revisions` row, all through
`app.services.agent_revisions.record_revision`. The row joins the change's own
transaction, so when it cannot be written the change is refused with 500
`REVISION_WRITE_FAILED` and nothing is saved. The paths are a builder save
(`PUT`), publish, revert, import, duplicate, and a healing patch applied or
rolled back.

| Column | Notes |
|---|---|
| `agent_id` | The agent. |
| `revision_number` | Monotonic per agent. The provenance trigger stamps the latest one on each run as `executions.agent_revision`. |
| `changed_by` | User. |
| `change_type` | `config_update`, `publish`, `revert`, `import`, `duplicate`, `healing_patch` or `healing_rollback`. |
| `previous_state` / `new_state` | jsonb snapshots of name, description, prompt, `model_config`, category, status. |
| `diff_summary` | Short human summary of what changed. |
| `source` | Where the change came from: `edit`, `healing`, `improvement`, `revert` or `import`. Default `edit`. |
| `proposal_id` | The improvement proposal a release came from, null otherwise. The version history links it to its proof. |

The version history on the agent's info page shows each revision's source as
a badge, a "See the proof" link when `proposal_id` is set, and Restore with a
confirmation. A revert never waits on the eval gate, it is the way back.

## Canary variants

A canary is another `agents` row with `parent_agent_id` pointing at the
original and its own `version_tag`. `traffic_weight` splits traffic between
them, which is how a new prompt is tried against a slice of real load before it
replaces the incumbent.

---

## Cost and scaling columns

The pool columns sit on the agent rather than in a side table because the dispatcher reads
them on every run and a join would be on the hot path.

| Column | Effect |
|---|---|
| `per_execution_cost_limit` / `daily_cost_limit` / `daily_budget_usd` | Spend caps, 0 or less means none. `daily_cost_limit` caps the agent's spend across all callers per UTC day, `daily_budget_usd` caps one tenant's spend on it per UTC day. A run over either is refused with 429 `BUDGET_EXCEEDED`. `per_execution_cost_limit` caps one run: an agent stops with `BUDGET_EXCEEDED` when it wants another step after reaching it, a pipeline fails its next node. The builder and `/admin/scaling` both edit `daily_budget_usd`. See [Spend caps](../02-runtime/00-agent-execution.md#spend-caps). Pausing an agent from `/admin/scaling` sets `status = archived`. |
| `runtime_pool` | Which agent-runtime pool executes it, default `default`. `inline` keeps the run on the API pod. |
| `min_replicas` / `max_replicas` / `concurrency_per_replica` | Per-pool KEDA bounds. |
| `rate_limit_qps` | Per-agent throttle. |
| `dedicated_mode` | Gives the agent its own pod instead of sharing a pool. |

The scaling columns and `daily_budget_usd` are added by idempotent `ALTER TABLE`
statements in the API startup hook rather than by a migration. See
[02-runtime/08-queue-scaling](../02-runtime/08-queue-scaling.md) for how the
pool values become a `ScaledObject`.

---

## Pipelines

A pipeline is an `agents` row whose `model_config.mode` is `pipeline` and whose
`model_config.pipeline_config` carries a node list. It is not a separate table.
That is why a pipeline run shows up in `executions` with
`model_used = "pipeline"` rather than a model id.

Nodes are either a tool step or a nested agent step:

```json
{
  "id": "score",
  "type": "tool",
  "tool": "time_series_analyzer",
  "input": { "data": "{fetch}" },
  "depends_on": ["fetch"]
}
```

`type: "agent"` requires `agent_id` or `agent_slug` instead of `tool`, and the
engine routes it through the `agent_step` tool. Nodes with no `depends_on` run
in parallel.

Full node grammar and the templating rules are in
[02-runtime/01-pipelines](../02-runtime/01-pipelines.md) and
[02-runtime/07-pipeline-data-flow](../02-runtime/07-pipeline-data-flow.md).

### `pipeline_states`

A key/value store scoped to one pipeline (`agent_id`, `key`, jsonb `value`), so a
pipeline can carry data from one run to the next.

---

## Related tables

| Table | Relationship |
|---|---|
| `executions` | One per run. See [02-executions](02-executions.md). |
| `agent_comments` | Threaded comments (`parent_id`), optionally tied to a `revision_id`, with `is_resolved`. |
| `agent_favorites` | A user's starred agents, grouped by an optional `collection` name. |
| `agent_triggers` | `trigger_type` `webhook` (with `webhook_token`) or `schedule` (with `cron_expression`, `next_run_at`). Holds `default_message`, `default_context`, `run_count`, `last_status`. |
| `knowledge_collections` | A collection can name an owning `agent_id`. Read access for agents is granted through `agent_collection_grants`. See [03-knowledge](03-knowledge.md). |
| `agent_mcp_tools` | MCP tools attached beyond the built-in registry. See [07-tools-and-operations](07-tools-and-operations.md). |
| `eval_suites` | Suites that test this agent or pipeline. See [06-evals-sources-events](06-evals-sources-events.md). |
| `reviews` / `subscriptions` | Marketplace ratings and subscriptions. |
| `resource_shares` | Per-user access. See [04-resource-shares](04-resource-shares.md). |

---

## See also

- [00-overview](00-overview.md) — the data model as a whole
- [02-runtime/00-agent-execution](../02-runtime/00-agent-execution.md) — what happens on a run
- [08-howto/02-add-an-agent](../08-howto/02-add-an-agent.md) — adding one
