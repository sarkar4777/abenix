# How to add a new agent

> Three options ordered by effort + flexibility: YAML seed (declarative, version-controlled), Builder UI (interactive), and direct DB insert (rare).

---

## Option 1 — YAML seed (recommended for platform agents)

The most-used path. Every platform-shipped agent + every standalone-app agent is defined this way.

### File location
- Platform agents → `packages/db/seeds/agents/<slug>.yaml`
- Vertical-app agents → same directory. convention `<app>_<purpose>.yaml`

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
  You convert currency amounts using the currency_convert tool. Always call the tool;
  never compute conversions yourself.

  ## Input
  JSON with: {amount: number, from: ISO4217, to: ISO4217}

  ## Output (STRICT JSON only — no prose, no fences)
  ```json
  {"result": <number>, "rate": <number>, "as_of": "<YYYY-MM-DD>"}
  ```

model_config:
  model: claude-haiku-4-5-20251001
  temperature: 0.1
  max_iterations: 5
  max_tokens: 1024
  tools:
    - current_time
    - currency_convert
  tool_config:
    currency_convert:
      usage_instructions: "Always pass amount, from_currency, to_currency from the input."

input_variables:
  - name: message
    type: string
    description: 'JSON {amount, from, to}'
    required: true

example_prompts:
  - '{"amount": 100, "from": "USD", "to": "EUR"}'
  - '{"amount": 1, "from": "BTC", "to": "USD"}'
```

### Fields in detail

| Field | Required | Purpose |
|---|---|---|
| `name` | yes | Display name in /agents |
| `slug` | yes | Stable identifier — used by SDK callers + tool catalogues |
| `description` | yes | Sub-title in the UI |
| `agent_type` | yes | `oob` (out-of-the-box, shipped with the platform) or `custom` (user-created) |
| `category` | no | Groups in the /agents catalogue |
| `version` | yes | Semver. Re-seeding bumps the version row. older versions stay accessible by ID |
| `status` | yes | `active` / `paused` / `draft` / `archived` |
| `mode` | yes | `agent` (single LLM loop) or `pipeline` (DAG) |
| `system_prompt` | yes | The prompt. Include the JSON-output contract |
| `model_config.model` | yes | LLM model ID. Use `claude-haiku-4-5-20251001` for fast/cheap, `claude-sonnet-4-6-20251215` for harder reasoning |
| `model_config.temperature` | no | 0.0–1.0. Default 0.2 |
| `model_config.max_iterations` | no | Default 10 |
| `model_config.tools` | no | List of tool slugs |
| `model_config.tool_config` | no | Per-tool overrides |
| `model_config.output_schema` | no | JSONSchema the final reply must match |
| `model_config.runtime_pool` | no | `default` / `chat` / `heavy-reasoning` / `long-running`. Default `default` |
| `input_variables` | no | Inputs the agent expects. Documented for callers |
| `example_prompts` | no | Shown in the /agents UI. used by the test runner |

### Seed it

```bash
# Inside the api pod
python /app/packages/db/seeds/seed_agents.py
```

The script:
1. Reads every `*.yaml` in `packages/db/seeds/agents/`.
2. Validates each against an internal schema.
3. Inserts or updates by `slug`. New versions are appended. older versions stay.
4. Re-seeds the agent's `agent_revisions` history so the UI's version dropdown is populated.

You should see:
```
+ Seeded Currency Quoter (currency-quoter) v1.0.0 [default]
```

### Test
1. Visit `/agents` — your agent shows up.
2. Click into it → click **Test** → use one of your `example_prompts`.
3. Open the resulting execution → trace shows tool calls + final output.

---

## Option 2 — Builder UI (interactive)

For one-off exploration / customer-specific agents.

1. Visit `/builder`. Empty canvas.
2. Drag a tool from the palette onto the canvas (wires automatically to the centre agent node).
3. Click the agent node → fill in name, model, system prompt in the right panel.
4. Click **Test** in the top bar to dry-run.
5. Click **Save**. The agent is created as a `draft`.
6. Click **Publish** to make it `active`.

The Builder serialises to the same `model_config_` JSONB the YAML produces. The two paths are interchangeable — you can export a Builder-created agent to YAML via `GET /api/agents/{id}/export`.

---

## Option 3 — Pipeline mode

Switch the Builder's mode toggle to **Pipeline**. The canvas becomes a DAG editor.

Pipelines are described in [`02-runtime/01-pipelines`](../02-runtime/01-pipelines.md). The YAML form for a pipeline:

```yaml
name: "Contract Triage"
slug: contract-triage
agent_type: oob
mode: pipeline
model_config:
  mode: pipeline
  pipeline_config:
    nodes:
      - id: extract
        type: agent
        agent_slug: contractiq-clause-extractor
        inputs: {document_id: "{{context.document_id}}"}
      - id: classify
        type: agent
        agent_slug: contractiq-risk-flagger
        inputs: {clauses: "{{extract.clauses}}"}
      - id: gate
        type: human
        title: "Review high-risk contract"
        required_signoffs: 2
        when: "{{classify.max_severity}} == 'high'"
    edges:
      - {from: extract, to: classify}
      - {from: classify, to: gate}
    output:
      from: classify
      field: clauses
```

---

## Tips that save hours

1. **Always declare an `output_schema`** on agents called from production code. The runtime auto-retries on schema mismatch — much more reliable than parsing free-form JSON.
2. **Pin a `client_token`** on every SDK execute call so retries are idempotent.
3. **Use `max_iterations: 5` for tight agents** that should fail loud if they need more rounds. Default 10 is generous but lets bugs hide.
4. **Don't anchor the LLM on stale example outputs.** Use `<placeholder>` syntax in your example block for any time-dependent value — see the [`feedback_no_pinned_dates`](../) memory.
5. **Group related tools.** An agent with 20 tools confuses the LLM. Keep `tools` under 10. let pipelines compose specialists.

---

## See also

- [02-runtime/00-agent-execution](../02-runtime/00-agent-execution.md) — what happens when the agent runs
- [02-runtime/01-pipelines](../02-runtime/01-pipelines.md) — pipeline mode details
- [03-sdk/00-overview](../03-sdk/00-overview.md) — calling your new agent from the SDK
