# Governed self-improvement

> The second half of the loop in [22-lessons-and-improvements](22-lessons-and-improvements.md). A group of lessons gets one proposed fix, the fix is proven offline against the agent's own tests and history, a person approves it, it is released as a revision and watched against the old version. Worse means an automatic rollback with the reason. Tables are in [04-data-model/09-self-improvement](../04-data-model/09-self-improvement.md).

## In short

1. **Propose.** A group of lessons gets one small change: examples, a prompt edit, a tool setting, a read-only tool, a model, or a pipeline patch. A person can ask for it, or it is proposed on its own once the group has 5 lessons or turns high severity.
2. **Prove.** The change runs offline against the agent's tests and a replay of recent real inputs. Tools that act are never executed during a proof. Only a proposal that fixes something, breaks nothing and stays within cost and speed margins goes on.
3. **Approve.** A person with `improvements.approve` who did not build the agent signs it on `/approvals`. A rejection becomes a lesson for the next draft.
4. **Watch.** The change is released as a new revision and compared with the old one for 7 days or 200 runs. Anything worse rolls it back at once, with the reason.

Find it on `/improvements` (sidebar **Improvements**, needs `improvements.view`) and on each agent's Improvements tab at `/agents/{id}/improvements`. The step-by-step guide is [08-howto/16-self-improvement](../08-howto/16-self-improvement.md).

---

## Where it lives

| Part | File |
|---|---|
| Improver, proof, bar, release, watch, rollback, budget, sample | [`app/services/improvements.py`](../../apps/api/app/services/improvements.py) |
| Allow list, proof bar and watch rules, pure and unit tested | [`app/services/improvement_rules.py`](../../apps/api/app/services/improvement_rules.py) |
| REST routes, proposal side | [`app/routers/improvements_proposals.py`](../../apps/api/app/routers/improvements_proposals.py) |
| Approval hook | [`app/routers/approvals.py`](../../apps/api/app/routers/approvals.py) `_autonomy_resolved` calls `on_release_resolved` |
| Replay hold in the autonomy gate | [`engine/autonomy.py`](../../apps/agent-runtime/engine/autonomy.py) `replay_hold`, flag on [`engine/governance.py`](../../apps/agent-runtime/engine/governance.py) `RunContext.replay` |
| Jobs | [`app/core/scheduler.py`](../../apps/api/app/core/scheduler.py) `improvements_tick` (lock `IMPP`), `improvements_watch` (lock `IMPW`) |
| Proof worker for the dedicated pool | [`app/workers/improvements_proof.py`](../../apps/api/app/workers/improvements_proof.py), chart template `improvements-proof-pool.yaml` |
| UI | `apps/web/src/components/improvements/proposals/**`, the Approvals page for gate kind `improvement.release` |

---

## The flow

```
cluster ──propose──▶ drafting ──improver──▶ proving ──proof──▶ awaiting_approval ──approve──▶ released ──watch──▶ kept
                         │                      │                     │                           │
                         ▼                      ▼                     ▼                           ▼
                    failed_proof           failed_proof           rejected (lesson)           rolled_back
```

`superseded` means the agent changed under the proposal: someone edited it after the proof, or during the watch.

## Propose

`POST /api/improvements/clusters/{id}/propose` creates a proposal in `drafting` and returns at once. The work is queued, see [The queue](#the-queue). A cluster gets a proposal on its own when it reaches `auto_propose_min_count` lessons (default 5) or turns high severity, worst first by severity times count, up to 20 a tick. A cluster that already has a proposal in flight returns that one.

## The improver

One model call on the tenant's own credentials. The model is the tenant's cheapest connected one when the agent's risk tier allows it, otherwise the agent's own model. Input: the cluster, up to 12 lessons, the test cases written from them, the current instructions, tools, tool settings and model, the read-only tools it could add and five recent results. It answers with one change.

| Kind | Diff | Rules |
|---|---|---|
| `examples` | `{"examples": [{"input", "output"}]}` | 1 to 5, appended under one header, at most 8 kept, a repeated input replaces the old one |
| `prompt_edit` | `{"edits": [{"find", "replace"}]}` or `{"append": "..."}` | Each `find` must match exactly once, at most 5 edits, never more than 60% of the instructions |
| `tool_config` | `{"tool", "set": {...}}` | Only a tool the agent uses, only `parameter_defaults`, `locked_defaults`, `max_calls`, `require_approval`. Never removes an approval step or frees a locked value |
| `tool_set` | `{"add": [..]}` or `{"remove": [..]}` | One tool. Only read-only tools are added, tools that act need a person |
| `model` | `{"model": "..."}` | Must be on the tier's allowed list |
| `pipeline_patch` | `{"patch": [JSON-Patch]}` | Pipelines only, drafted by the [Pipeline Surgeon](10-pipeline-healing-drift.md) and checked by its validator |

After applying a change, `guard` compares the candidate with the current agent. Anything outside the kind's own field fails: limits, risk tier, max iterations, autonomy, credentials, sharing. A refused draft is retried once with the reason. A second refusal ends in `failed_proof` with the reason in plain words.

## Prove

The proof runs every case of the agent's suites that is accepted, the suggested cases written from the cluster's lessons, and a judge case for each target lesson that has no case yet. Then it replays a sample of recent real inputs.

- **Offline.** Runs go through `AgentExecutor` (or `PipelineExecutor`) in-process with the candidate's prompt, model and tool config. No execution row is written, so proofs never show in run history, metrics or the watch.
- **Replay never acts.** Every proof run starts under a `RunContext` with `replay=True`. The autonomy gate checks the run's chain first, so nested agents are covered too. Any effect tool, at any autonomy level or with no grant, returns "Recorded during a proof replay, not executed" and the tool never runs. A short list of tools that change state without declaring an effect (`memory_store`, `human_approval`, `invoke_agent` and a few more) is held the same way. Nothing reaches the action ledger. Read tools run for real.
- **Before side.** For replays it is the stored answer of the real run. For cases it is the current revision's answer, cached in Redis for 7 days by config hash and input, so only the candidate side costs tokens when a proof runs again.
- **Sample.** Up to `replay_sample` inputs (default 50) from completed runs of the last 30 days, distinct, round robin over input length and first word.
- **Progress.** Steps `draft`, `test_set`, `replay`, `comparing`, `done`, each with done and total. Saved at most once a second. People can leave and come back.

Proof JSON: `fixed`, `broken`, `still_failing`, `target_lessons`, `cases_run`, `scores.before` and `scores.after` (`pass_rate`, `quality`, `cost_usd`, `latency_ms` median, `timed_latency_ms` and `timed_runs` for the runs timed side by side, `tool_calls`), `replay` (`sampled`, `changed`, `watching_effects`), `gating`, `examples` (three), `passed_bar`, `bar_reasons`, `tokens`.

## The bar

A person only ever sees a proposal that meets all of these.

1. Fixes at least one lesson in the target cluster.
2. Breaks nothing that passed before, cases and replays. A replay that worked before and fails now counts as broken.
3. Cost per run at most `cost_margin` worse (default 20%).
4. Speed at most `latency_margin` worse (default 20%). Judged only on runs timed side by side in this proof, 10 or more on each side. Cached answers of the current version and replayed history ran at another time under another load, so they show on the Speed bar but are not judged, and the proof says so.
5. Passes the agent's gating suites at their thresholds.

A proposal below the bar stays as `failed_proof` with its proof, so people can see what was tried. `request-approval` refuses it with 409 `NOT_PROVEN`.

## Approve

A passing proof opens an approval with gate kind `improvement.release`, policy capability `improvements.approve`, expiring in 7 days. The payload is the ProposalRow plus `agent_creator_id`, `is_sample`, `self_approval` and a link to the proof.

- **Separation of duties.** The agent's author is refused with 403 `AUTHOR_CANNOT_APPROVE` and a pointer to invite a teammate. Two exceptions match Earned Autonomy, both labelled in the payload: the sample agent, and a solo builder when no other active user holds `improvements.approve`. The check runs again at signing.
- **Edit and approve.** The approver edits the diff, the proof runs again (`POST /proposals/{id}/rerun`), the open approval is withdrawn and a new one opens when the edited fix passes.
- **Reject.** A deny or return with a reason closes the proposal as `rejected`, reopens the cluster and adds a `note` lesson with the reason and the rejected diff, so the next draft knows.

## Release

The approved diff is applied again to the agent as it is now, through `agent_revisions.record_revision`, with `source=improvement` and `proposal_id`. If the agent's config hash moved since the proof, nothing is applied and the proposal becomes `superseded`. Then:

- the gating suites start on the new revision, the eval gate on a live change
- Earned Autonomy sees a new config hash, so every grant on the agent drops to Asks first until it proves itself again
- `watch_until` is now plus `watch_days` (default 7), `watch_runs_target` is `watch_runs` (default 200)
- `improvement.released` is emitted and written to the audit log

## Watch

`improvements_watch` runs every 5 minutes under lock `IMPW`. People can also press Check now (`POST /proposals/{id}/watch-check`). It compares the new config hash since the release with the old hash over the same length of time before it, on live runs only (eval runs are left out).

| Measure | Worse when |
|---|---|
| Failed runs | 10 points higher, with `watch_min_runs` runs and 2 failures |
| Thumbs down | 15 points higher, with 3 ratings and 2 thumbs down |
| Cost per run | over `cost_margin` higher, with `watch_min_runs` runs |
| Drift | any drift alert on the agent since the release |
| Autonomy accuracy | 15 points lower, with 3 scored actions on each side |
| The target cluster | 2 or more new lessons, at a higher rate than before |

Any worse measure rolls back at once. The reason lists every measure that got worse, it goes on the proposal, in the audit log, on `improvement.rolled_back` and in a notification to the approver and the owner. A clean watch that reaches its end or its run target is `kept`, the cluster is `fixed` and the same people are told.

## Rollback

`POST /proposals/{id}/rollback` and the automatic path do the same thing, with no approval. The agent goes back to the `previous_state` of the release revision through `record_revision` with `source=revert`. If the agent was edited after the release, a manual rollback is refused (it would undo that edit) and the automatic watch stops with `superseded`.

## The queue

Proposals in `drafting` or `proving` are the queue. A worker claims rows with `SELECT ... FOR UPDATE SKIP LOCKED` and writes a lease into `progress.claimed_until`, renewed on every progress save. A worker that dies leaves its proposal to be claimed again after 20 minutes. `IMPROVEMENTS_PROOF_CONCURRENCY` (default 2) proofs run at once per process.

- By default API pods drain the queue, the scheduler tick every 15 s and right after a propose.
- With `improvements.proofPool.enabled` the chart adds a `improvements-proof` Deployment running `python -m app.workers.improvements_proof`, and sets `IMPROVEMENTS_PROOF_DRAIN=pool` so API pods stop proving. With `improvements.proofPool.keda.enabled` a ScaledObject scales it from `minReplicas` (0) to `maxReplicas` on `max(abenix_improvement_proof_queue_depth)`.

## Budget and kill switch

Tenant settings under `improvements`, each overridable per agent under `improvements.agents.<agent_id>`:

| Key | Default |
|---|---|
| `tokens_per_day` | 400000 |
| `proofs_per_day` | 20 |
| `replay_sample` | 50 |
| `cost_margin`, `latency_margin` | 0.2 |
| `watch_days`, `watch_runs`, `watch_min_runs` | 7, 200, 10 |
| `auto_propose`, `auto_propose_min_count` | true, 5 |

A proof counts toward the day when it is first claimed. Automatic proposals may use at most half of the day's proofs and tokens, so a fix a person asks for can still run, and a person's proposal is claimed ahead of automatic ones. A running proof checks the budget each time it saves progress and stops with a plain reason once the day is spent. When the budget is spent, queued proposals stay in line with `progress.waiting` saying so in plain words, and start the next day. `GET /api/improvements/budget` feeds the meter on the Improvements page, with `tokens_left` and `proofs_left` for what a person's fix can still use.

The kill switch scope `improvements` stops all proposing and proving for the tenant. Proposing returns 409 `KILL_SWITCH`, queued proposals wait with the reason. Releases already in their watch keep being watched, so a rollback can still happen.

## The sample

`POST /api/improvements/sample` installs "Temperature helper (sample)". Its instructions say "Always give the answer in degrees Fahrenheit, whatever unit the user asks for". Four corrected lessons sit in one cluster ("Answers in Fahrenheit when the user asks for Kelvin") with suggested contains-cases, plus two accepted good cases. The sample gets a short watch (3 runs minimum, 20 runs or a day). Running it again after a loop finished puts the planted mistake back, as an `edit` revision.

## Metrics

| Metric | Labels |
|---|---|
| `abenix_improvement_lessons_captured_total` | `source` |
| `abenix_improvement_clusters_open` | |
| `abenix_improvement_proofs_total` | `result` passed or failed |
| `abenix_improvement_proof_tokens_total` | |
| `abenix_improvement_proof_queue_depth` | |
| `abenix_improvement_releases_total` | `outcome` released, kept, rolled_back |

Two panels on the Abenix overview dashboard show them.
