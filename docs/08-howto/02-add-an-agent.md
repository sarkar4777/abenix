# How to add a new agent

> Three ways, ordered by how often they are used: a YAML seed (declarative, version-controlled), the Builder UI (interactive), and the API or SDK (from code).

---

## Option 1. YAML seed (platform agents)

Every agent the platform ships, and the agents of the standalone apps, are defined this way.

### File location

- `packages/db/seeds/agents/<name>.yaml`. One directory for all of them. App agents are prefixed by app, for example `contractiq_*.yaml`, `wingman_*.yaml`, `iot_*.yaml`.

### Minimal shape

```yaml
name: "Currency Quoter"
slug: currency-quoter
description: "Quotes a currency amount in a target currency."
agent_type: oob
category: finance
version: "1.0.0"
status: active
mode: agent
system_prompt: |
  You convert currency amounts using the currency_convert tool. Always call the tool,
  never compute conversions yourself.

  ## Input
  JSON with: {amount: number, from: ISO4217, to: ISO4217}

  ## Output (STRICT JSON only, no prose, no fences)
  {"result": <number>, "rate": <number>, "as_of": "<YYYY-MM-DD>"}

model_config:
  model: claude-haiku-4-5-20251001
  temperature: 0.1
  max_iterations: 5
  max_tokens: 1024
  risk_tier: low
  tools:
    - current_time
    - currency_convert

tool_config:
  currency_convert:
    usage_instructions: "Always pass amount, from_currency, to_currency from the input."

output_schema:
  type: object
  required: [result, rate, as_of]
  properties:
    result: {type: number}
    rate: {type: number}
    as_of: {type: string}

input_variables:
  - name: message
    type: string
    description: 'JSON {amount, from, to}'
    required: true

example_prompts:
  - '{"amount": 100, "from": "USD", "to": "EUR"}'
  - '{"amount": 1, "from": "BTC", "to": "USD"}'
```

### Fields

The schema is `AgentSeedSchema` in `packages/db/seeds/agent_seed_schema.py`. Only `name` and `slug` are required. Unknown top-level keys are allowed, but `model_config` refuses keys that belong at the top level, so a mis-indented `pipeline_config` fails loudly instead of turning a pipeline into a plain agent.

| Field | Required | Purpose |
|---|---|---|
| `name` | yes | Display name in `/agents` |
| `slug` | yes | Lowercase letters, digits, `-` and `_`, starting with a letter or digit. Stable identifier used by SDK callers, the seeder and the lint |
| `description` | no | Subtitle in the UI |
| `agent_type` | no | `oob` (default), `custom` or `vertical` |
| `category` | no | Groups the `/agents` catalogue |
| `version` | no | Free text, default `1.0.0` |
| `status` | no | `active` (default), `draft`, `pending_review`, `rejected` or `archived` |
| `mode` | no | `agent` (one LLM loop) or `pipeline` (a DAG, needs a top-level `pipeline_config`) |
| `system_prompt` | no | The prompt. Include the output contract |
| `model_config.model` | no | Model id. The seeds use `claude-haiku-4-5-20251001` for fast work and `claude-sonnet-4-5-20250929` for harder reasoning |
| `model_config.temperature` | no | 0 to 2. Unset, the run uses 0.7 |
| `model_config.max_iterations` | no | 1 to 200. Unset, the platform setting `agent.max_iterations` applies, 10 by default |
| `model_config.max_tokens` | no | 1 to 200,000 |
| `model_config.tools` | no | Tool slugs, as listed on `/tools` |
| `model_config.risk_tier` | no | `low`, `medium`, `high` or `critical`, see [11-governance](11-governance.md) |
| `tool_config` | no | Per-tool `usage_instructions`, `parameter_defaults`, `max_calls`, `require_approval`. Also accepted inside `model_config` |
| `output_schema` | no | JSON Schema the final reply is checked against. A mismatch is sent back to the model once to correct |
| `input_variables` | no | Inputs the agent expects. The chat page and the SDK playground build their forms from them |
| `example_prompts` | no | Shown on the agent page |
| `requires_credentials` | no | Keys the agent's tools cannot run without. The lint fails when a tool with a required key is used and the key is missing here |
| `runtime_pool` | no | `default`, `chat`, `heavy-reasoning`, `long-running` or `inline` (runs on the API pod). Default `default`, or `inline` when the slug contains `chat`. `deploy.sh local` runs only the `default` pool, `deploy.sh local-runtime` adds `chat` and `heavy-reasoning`, and AKS runs all four |
| `min_replicas`, `max_replicas`, `concurrency_per_replica`, `rate_limit_qps`, `daily_budget_usd` | no | Per-agent scaling, surfaced at `/admin/scaling`. `daily_budget_usd` caps one tenant's spend on the agent per UTC day, see [Spend caps](../02-runtime/00-agent-execution.md#spend-caps) |

`input_variables`, `example_prompts`, `tool_config`, `output_schema` and `max_tokens` can sit at the top level, where the seeder copies them into `model_config`, or inside `model_config` directly.

### Lint it

```bash
python scripts/lint-agent-seeds.py
```

It validates every YAML against the schema, fails an agent that lists `knowledge_search` without a knowledge base granting it a collection in `packages/db/seeds/kb/`, and fails one that uses a tool with a required key not listed in `requires_credentials`. It also checks the agent YAMLs of any use-case app that ships `<app>/seeds/manifest.yaml`. CI and `check-before-push.sh` run it, and `deploy-azure.sh` refuses to seed when it fails.

### Seed it

`bash scripts/dev-local.sh` runs the seeders from the working tree on every start. It does not stop when a seed fails, so run the lint first. On a cluster the seeds are baked into the API image, so run `bash scripts/deploy.sh local` (or `bash scripts/deploy-azure.sh redeploy` on AKS). It rebuilds the changed images and runs every seed again.

The seeder, `packages/db/seeds/seed_agents.py`:

1. Reads every `*.yaml` in `packages/db/seeds/agents/`.
2. Validates them all first. If any fails it prints every failure, writes nothing, and exits non-zero.
3. Creates or updates each agent by `slug`, in the shared system tenant. An update overwrites the row in place. There is no version history from seeding.
4. Archives slugs listed as retired.

You should see one line per file:

```
  Creating: Currency Quoter (currency-quoter) [default]
```

or `Updating:` when the slug exists. The deploy scripts then print which seeded agents still need a tool credential.

### Test

1. Visit `/agents`, your agent is listed.
2. Press **Chat** on its card and send one of your `example_prompts`.
3. Open the run. The Flight Recorder at `/executions/<id>` shows each tool call and the final output.

To keep a good answer as a regression check, save that run as an evaluation case, see [10-evals](10-evals.md).

---

## Option 2. Builder UI

For one-off exploration and tenant-specific agents.

1. Visit `/builder`.
2. Add tools from the palette. Each lands on the canvas wired to the agent node.
3. On the agent panel set the name, description, prompt, model and risk tier.
4. **Save draft**. The URL gains `?agent=<id>`.
5. **Publish**, then pick who sees it. Publishing checks the tier policy, an output schema or an allowed model may be required, and for high and critical tiers the agent's gating evaluation suites must pass.

The builder writes the same `model_config` the YAML produces. `GET /api/agents/{id}/export` returns a builder agent in the importable form, and `POST /api/agents/import` takes it back.

---

## Option 3. API or SDK

```python
agent = await forge.agents.create({
    "name": "Currency Quoter",
    "system_prompt": "You convert currency amounts using the currency_convert tool.",
    "model_config": {"model": "claude-haiku-4-5-20251001", "tools": ["currency_convert"], "risk_tier": "low"},
})
```

`POST /api/agents` takes the same fields. `PUT /api/agents/{id}` (`forge.agents.update`) replaces `model_config` whole, so send the full object, and a `name` in the body also renames the slug.

---

## Pipelines

Switch the builder to **Pipeline** and the canvas becomes a DAG editor. Pipelines are described in [02-runtime/01-pipelines](../02-runtime/01-pipelines.md). In YAML, `pipeline_config` sits at the top level, never inside `model_config`:

```yaml
name: "Contract Triage"
slug: contract-triage
mode: pipeline
model_config:
  tools: [decision_evaluate]
input_variables:
  - {name: document_id, type: string, required: true}
pipeline_config:
  nodes:
    - id: extract
      type: agent
      agent_slug: contractiq-clause-extractor
      input: "Extract the clauses of document {{input.document_id}}"
    - id: classify
      type: agent
      agent_slug: contractiq-risk-flagger
      input: "Flag the risky clauses: {{extract.clauses}}"
    - id: route
      tool_name: decision_evaluate
      arguments:
        decision: contracts.review.route
        facts: {contract: {max_severity: "{{classify.max_severity}}"}}
    - id: summary
      type: structured
      output:
        clauses: "{{classify.clauses}}"
        reviewer: "{{route.result.reviewer}}"
```

Every node has an `id` and either a `type` (`agent`, `tool`, `structured`, `switch`, `loop`) or a `tool_name`. Dependencies are inferred from the `{{node.field}}` references, and `depends_on` adds more. Pipeline inputs are read as `{{input.<name>}}`. The pipeline's answer is the output of the last node that completed. The agent slugs above are placeholders, use your own.

---

## Tips that save hours

1. **Declare an `output_schema`** on agents called from code. The runtime checks the reply and asks the model once to correct a mismatch, which beats parsing free-form JSON. High and critical tiers require one by default.
2. **Send an `Idempotency-Key` header** on `POST /api/agents/{id}/execute` so a retried call does not start a second run.
3. **Use `max_iterations: 5` for tight agents** that should fail loud if they need more rounds.
4. **Don't anchor the model on stale example outputs.** Use `<placeholder>` values in the prompt for anything time dependent, and let the agent call `current_time`.
5. **Keep `tools` short.** An agent with twenty tools picks badly. Keep it under ten and let pipelines compose specialists.

---

## See also

- [02-runtime/00-agent-execution](../02-runtime/00-agent-execution.md), what happens when the agent runs
- [02-runtime/01-pipelines](../02-runtime/01-pipelines.md), pipeline mode in detail
- [01-add-a-tool](01-add-a-tool.md), give the agent a new tool
- [10-evals](10-evals.md), regression cases and the publish gate
- [03-sdk/00-overview](../03-sdk/00-overview.md), calling the agent from the SDK
