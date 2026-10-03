# Evaluation suites

> Golden cases with assertions, scored runs against an agent or pipeline, comparisons across versions and models, and the gate that stops a high-risk version going live until its suites pass.

---

## Suites and cases

A suite belongs to one agent or pipeline. It holds cases and the settings for running them.

| Suite field | Default | Meaning |
|---|---|---|
| `name` | | 1 to 255 characters |
| `description` | empty | |
| `agent_id` | | The agent or pipeline under test. You need run access to it |
| `gating` | `false` | Counts toward the publish gate |
| `pass_threshold` | `0.9` | Score from 0 to 1 a run needs |
| `schedule_cron` | none | Cron expression, read in UTC |
| `rerun_on_model_change` | `false` | Run again when the agent's model changes |
| `concurrency` | `4` | Cases run at once, 1 to 16 |
| `judge_model` | none | Model for judged assertions that name none |

A case is one input and the checks its output must pass.

| Case field | Default | Meaning |
|---|---|---|
| `name` | | 1 to 255 characters |
| `input_message` | empty | Sent as the run's message |
| `context` | `{}` | Sent as the run's context |
| `assertions` | `[]` | Up to 25 |
| `weight` | `1.0` | 0 to 100, used in the run score |
| `tags` | `[]` | Free labels |
| `reference_output` | none | What a captured run answered, for previews |

A suite holds up to 500 cases. Assertions are validated on save. A bad one is refused with 400, code `INVALID_ASSERTION`, and `details.assertions` maps each assertion's index to its problems.

## Assertion types

Every assertion is an object with a `type` and the fields below. An optional `label` replaces the default name in results. The output is scanned up to its first 200,000 characters.

| Type | Fields | Passes when |
|---|---|---|
| `json_path_equals` | `path`, `value`, `tolerance`, `ignore_case` | The field at `path` equals `value` |
| `json_path_contains` | `path`, `value`, `ignore_case` | The field's text includes `value`, its list holds it, or its object has it as a key |
| `regex` | `pattern`, `mode` (`match` or `no_match`), `ignore_case` | The pattern is found anywhere in the output, or not found for `no_match` |
| `contains` | `value`, `case_sensitive` | The output includes the text. Case is ignored unless `case_sensitive` |
| `not_contains` | `value`, `case_sensitive` | The output never includes the text |
| `schema_valid` | `schema` | The output parses as JSON and validates against the JSON schema |
| `required_tools_called` | `tools`, `mode` (`all` or `any`) | The run called every listed tool, or at least one for `any` |
| `max_cost` | `max` | The run cost in USD is at most `max` |
| `max_duration_ms` | `max` | The run's wall-clock time is at most `max`. Above zero |
| `cited_sources_present` | `pattern`, `min_count`, `accept_source_tools` | The output has at least `min_count` citations, or the run used a source tool |
| `judge` | `rubric`, `min_score`, `model` | A model scores the output 0 to 1 against the rubric at or above `min_score` |

Details:

- **JSON reading.** The output is read as JSON whether it is bare, inside a code fence, or wrapped in prose. Paths take `a.b[0].c`, `$.a.b`, `items[*].name` and `['odd key']`. A wildcard checks every value it reaches and passes if any one matches. A missing field fails.
- **Equality.** Numbers compare as numbers, including numeric strings, within `tolerance` when given. Two strings compare trimmed, and ignore case when asked. Booleans must match exactly.
- **Tools.** `required_tools_called` in `all` mode scores the share of tools that were called, so a partial hit gives partial credit while still failing.
- **Citations.** The default pattern matches URLs, `[1]` style markers, `[source ...]` and `source:` or `sources:`. `min_count` defaults to 1. `accept_source_tools` defaults to true, and the source tools are `knowledge_search`, `vector_search`, `web_search`, `tavily_search`, `academic_search`, `persona_rag`, `news_feed`, `edgar_filings` and `ferc_elibrary`.
- **Judge.** Not deterministic, so use it alongside exact checks. `min_score` defaults to 0.7. The model is the assertion's own, then the suite's `judge_model`, then `claude-haiku-4-5-20251001`. The judge sees the rubric, the input (first 6,000 characters) and the output (first 20,000), runs at temperature 0, and must answer with a JSON score. A judge error fails the assertion. Judge cost is added to the case cost.

`POST /api/evals/assertions/check` tries assertions without a run. It uses the output you send, or the case's last completed result, or the run the case was captured from, or its `reference_output`. Judged assertions are skipped there, since a model judges them only during a suite run.

## Scoring

**A case** passes when its run finished with status `completed` and every assertion passed. Its score is the mean of its assertion scores. Exact checks score 1 or 0, `judge` scores what the model gave, `required_tools_called` scores its share. A case with no assertions passes with score 1. A run that did not complete fails the case with a single "Run finished" result.

**A run** scores the weighted share of passing cases: the sum of passing weights over the sum of all weights. If every weight is 0 it falls back to passed cases over total. A case that errored counts as failed. The run meets its threshold when the score is at or above `pass_threshold`, which is copied onto the run when it starts. A run that failed or was cancelled never meets its threshold.

## Runs

**Run** on the suite page, or `POST /api/evals/suites/{suite_id}/run`, queues a run and returns it with 202. The suite needs at least one case and you need run access to the agent. If an identical run, same model and same override flag, is already queued or running, that run is returned instead of a new one.

How a run executes:

1. It runs as a background task in the API process. Cases start in creation order, up to the suite's `concurrency` at a time, and up to `EVAL_MAX_PARALLEL_CASES` across all runs in one API process.
2. Each case goes through the same handler as `POST /api/agents/{id}/execute`, with `wait: true`, as the user who started the run. Scheduled and model-change runs act as the suite's creator. Every case is a real execution, listed under Executions.
3. The case waits up to `EVAL_CASE_TIMEOUT_SECONDS`, held between 5 and 1,800 seconds, then the execution row is read once it is no longer running.
4. Assertions are scored and an `eval_results` row is stored with the execution id, the assertion results, the first 4,000 characters of output, duration, cost and any error.
5. When every case is done the run is scored. Its `config_hash` becomes the most common hash stamped on the case executions by run provenance, and `agent_revision` the highest revision seen.
6. An `eval.completed` event is emitted with the suite, run, agent, status, score, threshold, counts, model and trigger.

| Run status | Meaning |
|---|---|
| `queued` | Created, not started |
| `running` | Cases executing |
| `completed` | Every case ran and was scored |
| `failed` | The run could not finish, for example no cases, no user to run as, or a crash. `error` says why |
| `cancelled` | Stopped by `POST /api/evals/runs/{run_id}/cancel` |

Each result is `completed` or `error`. Cancelling stops cases that have not started. Cases already running finish and are scored. Cancelling a finished run returns 409.

A run left `queued` or `running` longer than `EVAL_STALE_MINUTES` is marked `failed` by the scheduler, with a message that its API pod most likely restarted.

`triggered_by` is `manual`, `schedule` or `model_change`.

## Comparing runs

`GET /api/evals/runs/{run_id}` returns the run, every result and, once the run is completed or cancelled, a comparison with the previous completed run of the same suite that used the agent's own model.

`GET /api/evals/runs/{run_id}/compare/{other_id}` puts any two runs side by side. The first is the base. Cases are matched by case id, or by name when the case was deleted. The page is `/evals/compare?a=...&b=...`.

Both group cases into:

| Group | Meaning |
|---|---|
| `regressions` | Passed before, fails now |
| `improvements` | Failed before, passes now |
| `still_failing` | Failed in both |
| `still_passing` | Passed in both |
| `added` | Only in the newer run |
| `removed` | Only in the base run |

Each row carries `before`, `after` and `score_delta`. `counts` gives the size of each group. The compare endpoint also returns `rows` with both results per case and `same_suite`.

## Model override

**Try another model** on the suite page runs every case on a different model for that run only. The agent's configuration is not changed. The API passes the model to the execute handler in-process, so nothing outside the run can set it.

- Send `{"model": "<id>"}` to the run endpoint.
- Agents only. A pipeline's steps choose their own models, so a pipeline returns 400.
- The model must be on the allowed list of the agent's risk tier, or the request returns 400.
- Picking the agent's own model makes a regular run.

Override runs are stored with `model_override: true`. They never count for the publish gate, never serve as the comparison baseline, and are left out of the suite trend.

## Schedules and model-change reruns

A scheduler job runs every 60 seconds, on one replica at a time through a Postgres advisory lock. Each tick:

1. Fails stale runs, as above.
2. Starts a run for each suite whose `schedule_cron` is due. The next time is computed from the cron in UTC. A suite with no `next_run_at` yet only has it set on that tick. Suites whose creator was deleted are skipped.
3. For each suite with `rerun_on_model_change`, compares the model of its latest non-override run with the agent's current model, ignoring case. If they differ it starts a run with `triggered_by: model_change`. Pipelines are never rerun this way, and a suite with no earlier run is left alone.

An invalid cron is refused with 400 when the suite is saved.

## Publish gate

Each tier policy has `require_eval_pass`. Platform defaults:

| Tier | `require_eval_pass` |
|---|---|
| Low | false |
| Medium | false |
| High | true |
| Critical | true |

A tenant changes it under **Admin -> Risk & Controls -> Tier policies**.

When the agent's tier requires it, publishing checks every suite of that agent with `gating: true`. For each one it takes the latest `completed` run without a model override whose `config_hash` matches the agent's current hash, a SHA-256 of the system prompt and the model config. It is the same hash [run provenance](00-agent-execution.md#provenance) stamps on every execution.

| Suite state | When |
|---|---|
| `passed` | That run met its threshold |
| `failed` | That run scored below the threshold. The message lists up to 8 failing cases |
| `not_run` | No such run exists for the current version |

Any suite not `passed` blocks the publish with 409, `error_code: "EVAL_GATE"`. `details` holds `agent_id` and the per-suite rows. The message names the tier, each blocking suite and what to do next.

The gate is checked on `POST /api/agents/{id}/publish`, and on `PUT /api/agents/{id}` when the update moves the agent to active from another status. An agent with no gating suites, or whose tier does not require a pass, publishes as before.

Editing the system prompt or the model config changes the hash, so the gating suites must run again on the new version before it can go live. `GET /api/evals/gate/{agent_id}` returns the gate decision now, without publishing.

## Save as eval case

The execution detail page, `/executions/{id}`, has a **Save as eval case** button for people with `evals.manage`. It picks an existing suite of that agent or creates a new one, then calls `POST /api/evals/suites/{suite_id}/cases/from-execution`.

The case gets the run's input, `reference_output` set to the first 20,000 characters of its output, weight 1 and the tag `from-run`. Without a name it takes the first line of the input, cut to 80 characters, or `Run <first 8 of the id>`. The response includes `same_agent`, false when the execution came from a different agent than the suite's.

Suggested assertions are added only when the execution completed. Each holds for that run:

| Suggestion | When |
|---|---|
| `json_path_equals` for up to 3 top-level fields | The output is a JSON object. Only text up to 80 characters, numbers and booleans |
| `schema_valid` with a schema inferred from the output | The output is a JSON object. Types and non-null keys as required, two levels deep |
| `contains` with one word | The output is not JSON. The first word of 6 or more characters from the first line of at least 12 |
| `required_tools_called`, mode `all` | The run called tools. Up to 5 distinct names |
| `cited_sources_present`, `min_count: 1` | The run used a source tool or the output matches the citation pattern |
| `max_cost` | The run had a cost. 3x the cost, at least 0.01, rounded to 4 places |
| `max_duration_ms` | The run recorded a duration. The largest of 3x the duration, the duration plus 10,000 ms, and 5,000 ms |

The limits are loose on purpose, so normal latency and token variance do not fail the case. Tighten or remove them on the suite page.

## Access

| Capability | Lets you | Default roles |
|---|---|---|
| `evals.run` | See suites and runs, run, cancel, compare, check assertions, read the gate | user, creator, admin |
| `evals.manage` | Create, edit and delete suites and cases, save runs as cases | creator, admin |

Everything is scoped to the caller's tenant. Creating a suite and starting a run also need run access to the agent. Suite create, update and delete, and run start, are written to the audit log as `eval.suite_created`, `eval.suite_updated`, `eval.suite_deleted` and `eval.run_started`.

## REST endpoints

All under `/api/evals`.

| Method | Path | Does |
|---|---|---|
| GET | `/assertion-types` | Assertion types with their fields, the default judge model and the source tools |
| GET | `/suites` | Suites, optionally `?agent_id=`, with case count, last run, active run, trend of the last 12 runs and whether the current version was evaluated |
| POST | `/suites` | Create a suite. 201 |
| GET | `/suites/{suite_id}` | Suite with cases and each case's last result, the last 50 runs, the current config hash and the gate |
| PATCH | `/suites/{suite_id}` | Update suite fields |
| DELETE | `/suites/{suite_id}` | Delete the suite, its cases and runs |
| POST | `/suites/{suite_id}/cases` | Add a case. 201 |
| POST | `/suites/{suite_id}/cases/from-execution` | Add a case from a past execution. 201 |
| PATCH | `/cases/{case_id}` | Update a case |
| DELETE | `/cases/{case_id}` | Delete a case |
| POST | `/assertions/check` | Validate assertions and try them on an output |
| POST | `/suites/{suite_id}/run` | Start a run, optional `{"model": ...}`. 202 |
| GET | `/suites/{suite_id}/runs` | Runs, newest first, `?limit=` 1 to 200, default 50 |
| GET | `/runs/{run_id}` | Run with results and comparison to the previous baseline |
| POST | `/runs/{run_id}/cancel` | Cancel a queued or running run |
| GET | `/runs/{run_id}/compare/{other_id}` | Two runs side by side |
| GET | `/gate/{agent_id}` | Whether publishing the agent now would pass the gate |

## Environment

| Variable | Default | Effect |
|---|---|---|
| `EVAL_CASE_TIMEOUT_SECONDS` | `300` | How long one case waits for its execution, held between 5 and 1,800 |
| `EVAL_MAX_PARALLEL_CASES` | `8` | Cases running at once across all runs in one API process |
| `EVAL_STALE_MINUTES` | `180` | Age after which a queued or running run is marked failed |

## Source map

| What | Where |
|---|---|
| **REST router** | [`apps/api/app/routers/evals.py`](../../apps/api/app/routers/evals.py) |
| **Run execution, gate lookup, scheduler tick** | [`apps/api/app/services/eval_runner.py`](../../apps/api/app/services/eval_runner.py) |
| **Assertions, judge scoring, suggestions** | [`apps/api/app/services/eval_assertions.py`](../../apps/api/app/services/eval_assertions.py) |
| **Run score, comparison, gate decision, model-change check** | [`apps/api/app/services/eval_scoring.py`](../../apps/api/app/services/eval_scoring.py) |
| **Models** | [`packages/db/models/evals.py`](../../packages/db/models/evals.py) — `EvalSuite`, `EvalCase`, `EvalRun`, `EvalResult` |
| **Publish gate hook** | [`apps/api/app/routers/agents.py`](../../apps/api/app/routers/agents.py) — `_eval_gate_problem` |
| **Tier policy defaults** | [`apps/agent-runtime/engine/risk.py`](../../apps/agent-runtime/engine/risk.py) — `require_eval_pass` |
| **Scheduler job** | [`apps/api/app/core/scheduler.py`](../../apps/api/app/core/scheduler.py) — `eval_schedules` |
| **Evaluations pages** | [`apps/web/src/app/(app)/evals/`](../../apps/web/src/app/(app)/evals/) |
| **Save as eval case** | [`apps/web/src/components/evals/SaveAsEvalCase.tsx`](../../apps/web/src/components/evals/SaveAsEvalCase.tsx), on `/executions/{id}` |
| **Assertion builder** | [`apps/web/src/components/evals/AssertionBuilder.tsx`](../../apps/web/src/components/evals/AssertionBuilder.tsx) |
