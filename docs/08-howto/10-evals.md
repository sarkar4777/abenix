# How to add an evaluation suite to an agent

> Golden cases with assertions, a scored run, a comparison against the last run, and the gate that stops a high risk version going live until its suites pass. About 20 minutes.

---

## What you are building

A suite belongs to one agent or pipeline. It holds cases. A case is one input and the checks its output must pass. A run executes every case through the agent's normal execute path, scores it, and keeps the result per case. Two runs can be compared case by case. A suite marked `gating` can block a publish.

The example below tests a surcharge agent built in [09-decisions](09-decisions.md). Any agent works.

You need `evals.manage` to create suites and cases and `evals.run` to run them. Creators and admins hold `evals.manage` by default, every role holds `evals.run`. You also need run access to the agent.

---

## Step 1. Create the suite

In the UI, **Run & Test -> Evaluations -> New suite**, pick the agent, name it, and decide whether it gates publishing.

Over REST:

```bash
curl -s -X POST "$API/api/evals/suites" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "name": "Surcharge desk regression",
    "agent_id": "<agent uuid>",
    "gating": true,
    "pass_threshold": 0.9,
    "concurrency": 4,
    "schedule_cron": "0 6 * * 1",
    "rerun_on_model_change": true
  }'
```

| Field | Default | Notes |
|---|---|---|
| `gating` | `false` | Counts toward the publish gate |
| `pass_threshold` | `0.9` | Weighted share of cases that must pass, 0 to 1 |
| `schedule_cron` | none | Read in UTC. The first tick after saving only sets the next run time |
| `rerun_on_model_change` | `false` | A run starts when the agent's model differs from the last baseline run's model |
| `concurrency` | `4` | Cases run at once, 1 to 16 |
| `judge_model` | none | Used by `judge` assertions that name no model. Falls back to `claude-haiku-4-5-20251001` |

The response carries the suite `id`. Scheduled and model-change runs start as the person who created the suite.

---

## Step 2. Add cases

```bash
curl -s -X POST "$API/api/evals/suites/$SUITE/cases" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "name": "Heavy pallet to IV27 pays the surcharge",
    "input_message": "A 120 kg pallet ships on 2026-03-14 to postcode IV27. Which surcharge applies?",
    "context": {},
    "weight": 2,
    "tags": ["remote"],
    "assertions": [
      {"type": "contains", "value": "REMOTE_AREA_SURCHARGE"},
      {"type": "required_tools_called", "tools": ["decision_evaluate"], "mode": "all"},
      {"type": "max_duration_ms", "max": 60000},
      {"type": "max_cost", "max": 0.05}
    ]
  }'
```

A suite holds up to 500 cases, a case up to 25 assertions. A bad assertion is refused with 400, code `INVALID_ASSERTION`, and `details.assertions` maps each assertion's index to what is wrong with it.

| `type` | Fields | Passes when |
|---|---|---|
| `json_path_equals` | `path`, `value`, optional `tolerance`, `ignore_case` | The output parsed as JSON, fenced or not, has that value at the path |
| `json_path_contains` | `path`, `value`, optional `ignore_case` | The field's text includes the value, its list holds it, or its object has it as a key |
| `regex` | `pattern`, optional `mode` (`match` or `no_match`), `ignore_case` | The pattern is found anywhere, or not found |
| `contains` | `value`, optional `case_sensitive` | The output includes the text |
| `not_contains` | `value`, optional `case_sensitive` | The output never mentions the text |
| `schema_valid` | `schema` | The output parses as JSON and validates against the schema |
| `required_tools_called` | `tools`, optional `mode` (`all` or `any`) | The run called those tools. Partial credit for some |
| `max_cost` | `max` (USD) | The run cost at most that |
| `max_duration_ms` | `max` | The run finished within that |
| `cited_sources_present` | optional `pattern`, `min_count`, `accept_source_tools` | The output carries citations or links, or the run used a source tool such as `knowledge_search` |
| `judge` | `rubric`, optional `min_score` (0 to 1), `model` | A model scores the output against the rubric. Not deterministic, use it alongside exact checks |

`GET /api/evals/assertion-types` returns the same list with field kinds, which is what the assertion builder renders.

### Try assertions before saving them

`POST /api/evals/assertions/check` validates assertions and runs the deterministic ones against an output. Pass `output` to test against text you paste, or `case_id` to test against the case's last result or the run it was captured from. `judge` assertions are skipped here and run only in a suite run.

```bash
curl -s -X POST "$API/api/evals/assertions/check" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"output": "{\"surcharge\": \"NONE\"}", "assertions": [{"type": "json_path_equals", "path": "surcharge", "value": "NONE"}]}'
```

### Turn a real run into a case

A run that answered well is the cheapest case to write. From an execution page use **Save as eval case**, or:

```bash
curl -s -X POST "$API/api/evals/suites/$SUITE/cases/from-execution" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"execution_id": "<execution uuid>"}'
```

The case gets the run's input, its output as `reference_output`, the tag `from-run`, and suggested assertions that all hold for that run. Up to three top-level fields and a schema when the output is a JSON object, otherwise a `contains` on a word from the first line. Then the tools it called, a citation check if it cited, and cost and duration ceilings at about three times what it took. Review them before relying on them. `same_agent` in the response says whether the run came from the suite's agent.

---

## Step 3. Run it

```bash
curl -s -X POST "$API/api/evals/suites/$SUITE/run" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}'
```

The answer is 202 with the run in `queued`. Poll it:

```bash
curl -s "$API/api/evals/runs/$RUN" -H "Authorization: Bearer $TOKEN"
```

`status` goes `queued`, `running`, then `completed`, `failed` or `cancelled`. A finished run carries `score`, `threshold_met`, `passed`, `failed`, `errored`, `cost`, `config_hash`, and `results` with one row per case: `passed`, `score`, `assertion_results` (each with a `reason`), `output_excerpt`, `execution_id`. A case that could not run counts as failed. `POST /api/evals/runs/{id}/cancel` stops a run.

The run executes inside the API pod. If that pod restarts mid-run the run is marked failed with a message saying so. Run it again.

To try another model without changing the agent, pass `{"model": "<model id>"}`. That run is flagged `model_override` and never counts toward the gate. It is refused for pipelines, whose steps pick their own models, and for a model not on the allowed list of the agent's risk tier.

Every finished run writes an `eval.completed` event with the score and `threshold_met`, so a webhook can post it to a channel. See [12-source-watch-and-events](12-source-watch-and-events.md).

---

## Step 4. Compare runs

`GET /api/evals/runs/{id}` already compares against the previous baseline run of the same suite under `comparison`. To compare any two runs, for example two models:

```bash
curl -s "$API/api/evals/runs/$BASE_RUN/compare/$OTHER_RUN" -H "Authorization: Bearer $TOKEN"
```

The answer lists `regressions` (passed before, fails now), `improvements`, `still_failing`, `still_passing`, `added` and `removed`, with `counts`, plus `rows` pairing each case's result from both runs. On a suite's page, tick two runs and compare them for the same view.

---

## Step 5. Gate publishing

The gate applies when the tenant's policy for the agent's risk tier has `require_eval_pass: true`. By default that is the high and critical tiers. Set the tier on the agent (`model_config.risk_tier`, or the tier picker in the builder) and the policy on **Admin -> Risk & Controls**, see [11-governance](11-governance.md).

When it applies, publishing the agent or setting it active looks at every suite of that agent with `gating: true`. For each it takes the latest completed run with no model override, and that run must

- have run against the agent's current configuration. The `config_hash` is a SHA-256 of the system prompt and `model_config`, so any edit to either needs a fresh run, and
- meet the suite's `pass_threshold`.

Otherwise the publish is refused with 409, code `EVAL_GATE`, and a message naming each suite, its score against the threshold and the failing cases. An agent with no gating suites is not blocked.

Check where you stand before publishing:

```bash
curl -s "$API/api/evals/gate/$AGENT" -H "Authorization: Bearer $TOKEN"
```

It returns `allowed`, `required`, `message`, `current_config_hash` and per suite a `state` of `passed`, `failed` or `not_run`.

---

## From the SDK

The SDKs have no evals client yet. Use the authenticated client the Python SDK exposes, which carries the API key:

```python
forge = Abenix(api_key=os.environ["ABENIX_API_KEY"], base_url="http://localhost:8000")
run = (await forge.http.post(f"/api/evals/suites/{suite_id}/run", json={})).json()["data"]
gate = (await forge.http.get(f"/api/evals/gate/{agent_id}")).json()["data"]
```

---

## See also

- [02-runtime/18-evaluation-suites](../02-runtime/18-evaluation-suites.md), the reference for every field, the scoring and the gate
- [11-governance](11-governance.md), risk tiers and the `require_eval_pass` policy
- [05-testing](05-testing.md), `e2e/uat_evals.spec.ts` drives all of this through the UI

---

## Source map

| What | Where |
|---|---|
| Endpoints | [`apps/api/app/routers/evals.py`](../../apps/api/app/routers/evals.py), prefix `/api/evals` |
| Assertion types and checks | [`apps/api/app/services/eval_assertions.py`](../../apps/api/app/services/eval_assertions.py) |
| Runner, schedules, gate lookup | [`apps/api/app/services/eval_runner.py`](../../apps/api/app/services/eval_runner.py) |
| Scoring, comparison, gate decision | [`apps/api/app/services/eval_scoring.py`](../../apps/api/app/services/eval_scoring.py) |
| Unit tests | `tests/unit/test_eval_assertions.py`, `tests/unit/test_evals_api.py` |
