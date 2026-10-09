# Lessons and improvements

> How agents learn from their own mistakes without changing themselves. Every signal becomes a lesson, similar lessons are grouped, and each group suggests test cases. Proposing, proving, approving and watching a fix is the second half of the loop, in [23-governed-self-improvement](23-governed-self-improvement.md). Tables are in [04-data-model/09-self-improvement](../04-data-model/09-self-improvement.md).

---

## Where it lives

| Part | File |
|---|---|
| Runtime capture, masking and keys, fire and forget | [`engine/lessons.py`](../../apps/agent-runtime/engine/lessons.py) |
| Failed run hook in the queue consumer | [`consumer.py`](../../apps/agent-runtime/consumer.py) `_capture_failed` |
| Capture in the API, harvest, grouping, suggested cases, views, retention, erase | [`app/services/lessons.py`](../../apps/api/app/services/lessons.py) |
| Autonomy signals (reject, edit, alternative, harm, outcome outside the band) | [`app/services/autonomy.py`](../../apps/api/app/services/autonomy.py) |
| REST routes, `/api/improvements/*` capture side | [`app/routers/lessons.py`](../../apps/api/app/routers/lessons.py) |
| Grouping and retention jobs | [`app/core/scheduler.py`](../../apps/api/app/core/scheduler.py) `group_lessons`, `lesson_retention` |
| Tables | [`packages/db/models/improvement.py`](../../packages/db/models/improvement.py), migration `selfimp0001` |
| UI | `apps/web/src/app/(app)/improvements/**`, `apps/web/src/app/(app)/agents/[id]/improvements/**`, `apps/web/src/components/improvements/**` |

---

## Words

| Term | Meaning |
|---|---|
| Lesson | Something that went wrong or went well, from a run, a review, a flag or a person's note |
| Group | Lessons about the same mistake, a row in `lesson_clusters` |
| Suggested case | A test case written from a lesson. It only runs once a person accepts it |
| Good example | A thumbs up or an approved action, kept so a fix cannot break what works |

---

## Where lessons come from

| Signal | Source | How it is captured |
|---|---|---|
| Thumbs down on an answer | `thumbs` | `POST /api/improvements/feedback` |
| Thumbs down with "what should it have said" | `correction` | Same call, the text becomes `expected` |
| Thumbs up, approved action, reviewer agreed | `positive` | Feedback call, autonomy service |
| "This was wrong because" on a run | `note` | `POST /api/improvements/lessons` |
| A standalone app reporting a lesson | `sdk` | Same call with `source: "sdk"` |
| Rejected action with a note | `autonomy_reject` | `on_action_gate_resolved` |
| Edited action arguments | `autonomy_edit` | `on_action_gate_resolved`, edited arguments become `expected` |
| Reviewer did something else | `autonomy_alternative` | `review`, the alternative becomes `expected` |
| Harm flag | `harm` | `flag_harm` |
| Outcome outside the predicted band | `band_miss` | `apply_outcome` |
| Failed run | `run_failed` | The consumer at once, the harvest for inline runs |
| Pipeline step failure diff | `pipeline_failed` | Harvest from `pipeline_run_diffs` |
| Drift alert | `drift` | Harvest from `drift_alerts` |
| Failing case in a scheduled eval run | `eval_failed` | Harvest from `eval_results` |

One person's signal never changes an agent. Lessons only feed proposals, and a proposal goes through proof and approval.

---

## Capture never slows a run

- The runtime side (`engine/lessons.py`) queues the write as a background task and returns at once. A failed write pauses capture for a minute, so a database that is down costs nothing per run. More than 200 writes in flight are dropped, never queued.
- The API side inserts inside a savepoint of the caller's transaction. A failure rolls back only the savepoint and is logged.
- The harvest reads the last 30 minutes of failed runs, drift alerts, pipeline diffs and scheduled eval results every two minutes, each with a time index and a batch cap.
- `lessons` has a unique index on `(source, capture_key)`. A repeat of the same signal is a no-op, so the consumer hook and the harvest never double count.

## Masking

Secrets (API keys, bearer tokens, AWS keys) are always masked. Personal data is masked too when the tenant's DLP mode is `mask` or `block`, with its custom patterns. Masking happens before the row is written, so masked fields stay masked in the test cases made from it.

---

## Grouping

The `group_lessons` job runs every two minutes under advisory lock `LSNC` and only reads lessons with `cluster_id IS NULL`, through a partial index. It never rescans history, so its cost follows the inflow and not the archive. Feedback also asks for a grouping pass right after it lands, so the agent tab shows it within seconds.

A lesson's group is decided in two steps.

1. **Base.** Family (answer, action, failure, pipeline, drift, eval, positive), failure code, tool and decision rule. Lessons with a different base never group.
2. **Keywords.** Up to eight content words from the input, note and correction, with numbers and ids dropped. The same words give the same signature. Otherwise a group with the same base whose keywords overlap by half or more is joined.

New groups get a plain one sentence title from the tenant's cheapest connected model, at most ten calls a run. Without a model, or when the call fails, a readable fallback title is used. A fixed group that gets a new mistake opens again.

Severity is high for any harm or ten or more lessons, medium for three or more or any correction, rejection, edit, alternative or band miss, and low otherwise. Each group keeps daily counts for 14 days.

## Suggested test cases

A group earns cases when it has two lessons, or one harm, correction or alternative. Up to five cases per group, and up to ten good examples per agent.

| Lesson has | Case |
|---|---|
| A correction or alternative | `reference_output` is the right answer, and a judge checks the answer agrees with it |
| Only a note | A judge rubric from the note, tagged `needs_confirmation` for a person to check |
| A failed run | A judge that wants a complete answer, tagged `needs_confirmation` |
| A good answer | A judge that wants an answer at least as good, with the good answer as reference |

Cases land in the agent's "Improvement tests" suite with `state = suggested`. Accepting a case sets `state = accepted`. Dropped cases never run. The eval runner only runs accepted cases, and the Evaluations page lists only accepted ones. A proof runs accepted and suggested cases whatever the suite's gating.

The suite never gates by itself. These cases come from known failures, so they fail until the fix lands, and a gate would refuse the very edit that fixes the agent. The owner turns on "Require these tests to pass before changes go live" on the Improvements tab once they pass. Turning it on while tests fail, or before they have run, asks first and says how many fail. `PUT /api/improvements/agents/{agent_id}/gate` sets it.

---

## Who sees what

- Every role holds `feedback.give`, so anyone can rate an answer they can see.
- Admins see every agent's lessons. Others see the agents they built, plus agents shared with them when they hold `improvements.view`.
- Accepting, editing or dropping cases and dismissing a group needs the agent's owner or `improvements.propose`.

## Retention and erase

- `tenants.settings.improvements.retention_days` (default 180, between 7 and 3650) drops lessons and feedback older than that, and fixed or dismissed groups with nothing newer. The `lesson_retention` job runs hourly in batches under advisory lock `LSNR`.
- GDPR erase blanks the person's lessons and the suggested cases made from them, deletes their feedback, and drops proof examples from proposals on groups their lessons fed.

## Events

| Event | When |
|---|---|
| `lesson.captured` | A new lesson was stored |
| `cluster.opened` | A new group with at least one negative lesson was made |

The proposal and release events are in [23-governed-self-improvement](23-governed-self-improvement.md).
