# Agents, revisions, pipelines

Source: [`packages/db/models/agent.py`](../../packages/db/models/agent.py)

---

## `agents`

One row per agent. Tenant-scoped through `TenantMixin`, so every query the API
issues is filtered by `tenant_id` and nothing crosses a tenant boundary by
accident.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary key. |
| `tenant_id` | uuid | Owning tenant. |
| `creator_id` | uuid | User who created it. |
| `name` | text | Display name. |
| `slug` | text | URL-safe identifier. The SDK and pipeline `agent_slug` references resolve against this. |
| `description` | text | Shown on the agent card and info page. |
| `system_prompt` | text | The prompt. Can be long, so it is `Text` rather than a bounded string. |
| `model_config` | jsonb | Model, sampling, iteration cap and tool list. Mapped in Python as `model_config_` because `model_config` collides with a Pydantic attribute. |
| `agent_type` | enum | `custom`, `oob`, `vertical`. `oob` are the seeded out-of-the-box agents. |
| `category` | text | Grouping for the marketplace. |
| `status` | enum | `draft`, `pending_review`, `active`, `rejected`, `archived`. |
| `is_published` | bool | Visible in the marketplace. |
| `version` / `version_tag` | text | Revision identity, see below. |
| `parent_agent_id` | uuid | Set on a revision, pointing at the agent it was branched from. |
| `traffic_weight` | float | Share of traffic for a canary revision. |

### `model_config`

The shape the runtime reads:

```yaml
model_config:
  model: claude-sonnet-4-5-20250929
  temperature: 0.0
  max_tokens: 1024
  max_iterations: 3
  tools:
    - pii_redactor
    - text_analyzer
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

---

## Revisions and canary

A revision is another `agents` row with `parent_agent_id` pointing at the
original and its own `version_tag`. `traffic_weight` splits traffic between
them, which is how a new prompt is tried against a slice of real load before it
replaces the incumbent.

There is no separate revisions table. Listing revisions means selecting rows
that share a `parent_agent_id`.

---

## Cost and scaling columns

These sit on the agent rather than in a side table because the dispatcher reads
them on every run and a join would be on the hot path.

| Column | Effect |
|---|---|
| `per_execution_cost_limit` | A single run that exceeds this is stopped. |
| `daily_cost_limit` / `daily_budget_usd` | Tenant-day budget. The alert webhook archives the agent when a P4 budget alert fires. |
| `runtime_pool` | Which agent-runtime pool executes it. |
| `min_replicas` / `max_replicas` / `concurrency_per_replica` | Per-pool KEDA bounds. |
| `rate_limit_qps` | Per-agent throttle. |
| `dedicated_mode` | Gives the agent its own pod instead of sharing a pool. |

See [02-runtime/08-queue-scaling](../02-runtime/08-queue-scaling.md) for how the
pool values become a `ScaledObject`.

---

## Pipelines

A pipeline is an agent whose `agent_type` is a pipeline and whose
`model_config` carries a `pipeline_config` with a node list. It is not a
separate table. That is why a pipeline run shows up in `executions` with
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

---

## Related tables

| Table | Relationship |
|---|---|
| `executions` | One per run. See [02-executions](02-executions.md). |
| `knowledge_bases` | Many-to-many. Which KBs the agent can search. |
| `agent_mcp_tools` | MCP tools attached beyond the built-in registry. |
| `reviews` | Marketplace ratings. |
| `resource_shares` | Per-user access. See [04-resource-shares](04-resource-shares.md). |

---

## See also

- [00-overview](00-overview.md) — the data model as a whole
- [02-runtime/00-agent-execution](../02-runtime/00-agent-execution.md) — what happens on a run
- [08-howto/02-add-an-agent](../08-howto/02-add-an-agent.md) — adding one
