# Self-improvement tables

> Feedback, lessons, lesson groups and improvement proposals, plus the columns added to eval cases and agent revisions. Migration `selfimp0001`, models in [`packages/db/models/improvement.py`](../../packages/db/models/improvement.py). How they are used is in [02-runtime/22-lessons-and-improvements](../02-runtime/22-lessons-and-improvements.md).

---

## feedback

The raw thumbs, kept apart from lessons so the signal survives grouping. One row per person per answer, a second rating updates it.

| Column | Notes |
|---|---|
| `tenant_id`, `user_id` | Who rated |
| `execution_id`, `conversation_id`, `message_id`, `agent_id` | What was rated. A run, a saved chat message or just an agent |
| `rating` | `1` or `-1` |
| `correction` | What it should have said, thumbs down only |

Index `(tenant_id, agent_id, created_at)`.

## lessons

| Column | Notes |
|---|---|
| `agent_id`, `agent_config_hash`, `execution_id` | Where it happened, the config hash when known |
| `source` | `thumbs`, `correction`, `autonomy_reject`, `autonomy_edit`, `autonomy_alternative`, `harm`, `band_miss`, `run_failed`, `pipeline_failed`, `drift`, `eval_failed`, `note`, `sdk`, `positive` |
| `polarity` | `negative` or `positive` |
| `input_text`, `output_text` | Masked, capped at 8000 characters |
| `expected`, `note` | The right answer and why, when known |
| `failure_code`, `tool_name` | Used for grouping |
| `capture_key` | With `source`, unique, so a repeated capture is a no-op |
| `cluster_id`, `case_id` | The group it joined and the suggested case made from it |
| `by_user`, `meta` | Who said so, source details such as `action_key`, `metric`, `node_id`, `case_name` |

A plain table, not partitioned. The API's startup `create_all` cannot build a partitioned table, so `(tenant_id, created_at)` plus the retention job keep it bounded. The partial index `ix_lessons_unclustered` on `created_at WHERE cluster_id IS NULL` is all the grouping job reads.

## lesson_clusters

| Column | Notes |
|---|---|
| `agent_id`, `title`, `summary` | The title is one plain sentence |
| `signature` | Hash of the base and keywords. Unique per agent |
| `count`, `negative_count` | All lessons, and the ones that are mistakes. Groups with no negative lessons hold good examples |
| `severity` | `low`, `medium`, `high` |
| `trend` | `[{day, count}]` for the last 14 days |
| `state` | `open`, `proposing`, `proposed`, `fixed`, `dismissed` |
| `meta` | `family`, `base`, `keys`, counts per source, cases made, dismissal note |
| `last_lesson_at` | Newest lesson |

## improvement_proposals

Written by the improver. One change per proposal.

| Column | Notes |
|---|---|
| `agent_id`, `cluster_id`, `base_config_hash` | What it fixes and the config it was drafted against |
| `change_kind` | `examples`, `prompt_edit`, `tool_config`, `pipeline_patch`, `tool_set`, `model` |
| `diff`, `rationale`, `risk` | The change, why, and how risky |
| `state` | `drafting`, `proving`, `failed_proof`, `awaiting_approval`, `approved`, `rejected`, `released`, `kept`, `rolled_back`, `superseded` |
| `progress`, `proof` | Steps for the UI and the before and after evidence |
| `approval_id`, `released_revision_id` | The sign-off and the revision it became |
| `watch_until`, `watch_runs_target`, `watch_result` | The watch period after release |
| `error`, `created_by` | |

## Added columns

| Column | Notes |
|---|---|
| `eval_cases.state` | `accepted` (default, existing rows), `suggested`, `dropped` |
| `eval_cases.source_lesson_id` | The lesson a suggested case came from |
| `agent_revisions.source` | `edit` (default), `healing`, `improvement`, `revert`, `import` |
| `agent_revisions.proposal_id` | The proposal an improvement revision came from |

The migration also adds time indexes the harvest reads: `pipeline_run_diffs.created_at`, `drift_alerts.created_at`, `eval_results.created_at`, and `executions.completed_at WHERE status = 'FAILED'`.

## Proposal JSON

The proposal side writes these shapes, see [02-runtime/23-governed-self-improvement](../02-runtime/23-governed-self-improvement.md).

| Field | Shape |
|---|---|
| `change_kind` | Empty until the improver has drafted the change |
| `diff` | The change for its kind, plus `preview: {what, lines: [{op: add or remove or same, text}]}` for display |
| `progress` | `{phase, steps: [{key, label, state, done, total}], message, waiting, tokens, started_on, started_at, finished_at, claimed_until, runner}`. `started_on` counts the proof toward the day's budget, `claimed_until` is the worker's lease |
| `proof` | `{fixed, broken, still_failing, target_lessons, cases_run, scores: {before, after}, replay: {sampled, changed, watching_effects}, gating, examples, passed_bar, bar_reasons, tokens, finished_at}` |
| `watch_result` | `{outcome, started_at, base_hash, new_hash, approved_by, approved_by_name, old, new, worse, points, checked_at, reason, automatic, rolled_back_by_name, ended_at}` |

`old` and `new` hold `runs`, `failures`, `cost_avg`, `thumbs_total`, `thumbs_down`, `scored`, `accurate`, `cluster_lessons` and, for `new`, `drift`. `points` keeps the last 50 checks for the timeline.
