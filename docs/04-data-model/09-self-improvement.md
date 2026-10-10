# Self-improvement tables

Feedback, lessons, lesson groups and improvement proposals, plus the columns added to eval cases and agent revisions.

Source: [`packages/db/models/improvement.py`](../../packages/db/models/improvement.py)

Migration: [`selfimp0001_governed_self_improvement`](../../packages/db/alembic/versions/selfimp0001_governed_self_improvement.py), down revision `modrev00001`. Like the autonomy migration it checks for existing tables, columns and indexes first, because `create_all` may have built them.

How they are used is in [02-runtime/22-lessons-and-improvements](../02-runtime/22-lessons-and-improvements.md). Routes are under `/api/improvements`. None of these tables has a foreign key to `executions`, `users` or messages, so a row survives what it points at.

---

## feedback

The raw thumbs, kept apart from lessons so the signal survives grouping. One row per person per answer. A second rating updates the row (enforced in code, there is no unique index).

| Column | Notes |
|---|---|
| `tenant_id`, `user_id` | Who rated |
| `execution_id`, `conversation_id`, `message_id`, `agent_id` | What was rated. A run, a saved chat message or just an agent |
| `rating` | smallint, `1` or `-1` |
| `correction` | What it should have said, thumbs down only |
| `created_at` | |

Indexes `ix_feedback_tenant_agent_created` on `(tenant_id, agent_id, created_at)`, `ix_feedback_tenant_created` on `(tenant_id, created_at)` and `ix_feedback_user` on `user_id`.

## lessons

| Column | Notes |
|---|---|
| `agent_id`, `agent_config_hash`, `execution_id` | Where it happened, the config hash when known. `agent_id` is required |
| `source` | `thumbs`, `correction`, `autonomy_reject`, `autonomy_edit`, `autonomy_alternative`, `harm`, `band_miss`, `run_failed`, `pipeline_failed`, `drift`, `eval_failed`, `note`, `sdk`, `positive` |
| `polarity` | `negative` or `positive` |
| `input_text`, `output_text` | Masked, capped at 8000 characters |
| `expected`, `note` | The right answer and why, when known. `note` is capped at 4000 characters |
| `failure_code`, `tool_name` | Used for grouping |
| `capture_key` | Unique with `source` (`uq_lessons_capture`), so a repeated capture is a no-op |
| `cluster_id`, `case_id` | The group it joined (`ON DELETE SET NULL`) and the suggested case made from it |
| `by_user`, `meta` | Who said so, source details such as `action_key`, `metric`, `node_id`, `case_name` |

A plain table, not partitioned. The API's startup `create_all` cannot build a partitioned table, so the `(tenant_id, created_at)` index plus the retention job (180 days by default) keep it bounded. Other indexes are on `(tenant_id, agent_id, created_at)`, `(cluster_id, created_at)`, `execution_id` and `by_user`. The partial index `ix_lessons_unclustered` on `created_at WHERE cluster_id IS NULL` is all the grouping job reads.

## lesson_clusters

| Column | Notes |
|---|---|
| `agent_id`, `title`, `summary` | `agent_id` is `ON DELETE CASCADE`. The title is one plain sentence |
| `signature` | Hash of the base and keywords. Unique on `(tenant_id, agent_id, signature)` (`uq_lesson_clusters_signature`) |
| `count`, `negative_count` | All lessons, and the ones that are mistakes. Groups with no negative lessons hold good examples |
| `severity` | `low`, `medium`, `high` |
| `trend` | `[{day, count}]` for the last 14 days |
| `state` | `open`, `proposing`, `proposed`, `fixed`, `dismissed` |
| `meta` | `family`, `base`, `keys`, counts per source, cases made, dismissal note |
| `last_lesson_at` | Newest lesson. Index `ix_lesson_clusters_tenant_state` on `(tenant_id, state, last_lesson_at)` |

## improvement_proposals

Written by the improver. One change per proposal.

| Column | Notes |
|---|---|
| `agent_id`, `cluster_id`, `base_config_hash` | What it fixes and the config it was drafted against. `agent_id` is `ON DELETE CASCADE`, `cluster_id` is `ON DELETE SET NULL` |
| `change_kind` | `examples`, `prompt_edit`, `tool_config`, `pipeline_patch`, `tool_set`, `model` |
| `diff`, `rationale`, `risk` | The change, why, and how risky. `risk` defaults to `low` |
| `state` | `drafting` (default), `proving`, `failed_proof`, `awaiting_approval`, `approved`, `rejected`, `released`, `kept`, `rolled_back`, `superseded` |
| `progress`, `proof` | Steps for the UI and the before and after evidence. `progress` is declared with a `[]` default but holds an object, see below |
| `approval_id`, `released_revision_id` | The sign-off and the revision it became. No foreign keys |
| `watch_until`, `watch_runs_target`, `watch_result` | The watch period after release. `watch_runs_target` is set from the improvement settings at release |
| `error`, `created_by` | |

Indexes on `(tenant_id, agent_id, created_at)`, `(tenant_id, state)` and `cluster_id`.

## Added columns

| Column | Notes |
|---|---|
| `eval_cases.state` | `accepted` (default, existing rows), `suggested`, `dropped`. Index on `(suite_id, state)` |
| `eval_cases.source_lesson_id` | The lesson a suggested case came from |
| `agent_revisions.source` | `edit` (default), `healing`, `improvement`, `revert`, `import` |
| `agent_revisions.proposal_id` | The proposal an improvement revision came from |

The migration also adds time indexes the harvest reads: `pipeline_run_diffs.created_at`, `drift_alerts.created_at`, `eval_results.created_at`, and `ix_executions_failed_completed` on `executions.completed_at WHERE status = 'FAILED'`.

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
