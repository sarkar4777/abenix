# Background jobs

Every API replica starts an APScheduler instance (`apps/api/app/core/scheduler.py`). It runs the jobs that make things happen without anyone pressing a button: scheduled triggers, evaluation schedules, approval escalation, Source Watch checks, retention purges, the quota reset and more.

Admins see all of them at **Admin, Background jobs** (`/admin/jobs`).

## What the page shows

For each job:

- a plain name, what it does in one line and why it matters
- the schedule, last run and next run
- the last outcome (Worked, Failed, Late, Running now, Not run yet) and how long it took
- what the last run did, for example `2 triggers started` or `Nothing was past its retention.`
- the last error in plain words, with the technical detail one click away
- the run count, failures, Run now count and skipped ticks
- recent runs that did something or failed (quiet ticks are counted but not listed)
- a link to where the job's settings live

`?job=<id>` opens the page on one job. The retention cards on Moderation and Improvements link there.

## How runs are recorded

`app/core/job_runs.py` wraps every scheduled function. Each run writes to Redis:

| Key | What |
|---|---|
| `abenix:jobs:<id>` | last run fields and counters |
| `abenix:jobs:<id>:history` | last 20 runs worth listing |
| `abenix:jobs:<id>:running` | set while a run is in progress, 15 minute expiry |
| `abenix:jobs:<id>:next` | next run time per replica |
| `abenix:jobs:replicas` | last time each replica ran any job |

No table and no migration. Jobs swallow their own exceptions, so the wrapper also collects anything logged at ERROR while the job runs and treats it as a failure.

## Several replicas

Singleton jobs take a transaction-scoped pg advisory lock. A replica that does not get the lock records a skip, not a run, so the last run on the page is always the replica that did the work. Claim-based jobs (triggers, Source Watch, event delivery) run everywhere and claim rows with `SKIP LOCKED`. The next run shown is the earliest across replicas that reported in the last minute.

## Run now

`POST /api/admin/jobs/{id}/run` runs the job once on the replica that took the request, under the same lock as the schedule. If another replica holds the lock at that moment the answer is "skipped" and nothing runs twice. Jobs that remove or change data (retention purges, the archive, the quota reset, the stuck run sweep, the released fix watch, the vector clean-up) need `{confirm: true}` and the page asks first. The request waits up to 45 seconds (`JOB_RUN_NOW_WAIT_SECONDS`), longer runs carry on in the background. Every Run now is in the audit log as `job.run_now`.

The quota reset clears usage for every tenant, not just the admin's own.

## Shortest windows

| Job | Setting | Shortest |
|---|---|---|
| Approval escalation | Risk & Controls, per tier | 1 minute (job runs every minute) |
| Source Watch | check interval | 5 minutes |
| Scheduled triggers and evaluations | cron | every minute |
| Moderation retention | held text after a decision | 0 days |
| Lesson retention | Improvements, lesson retention | 7 days |
| Archive | per table policy | 1 day |
| Event clean-up | fixed | 30 days delivered, 7 days sent |

## When a job fails

Open the card, read the plain error and the technical detail, fix the cause, then press Run now to confirm. A job shows Late when it is well past its next run and nothing was recorded, which usually means the API pods are restarting or Redis is down. The summary strip says when Redis is unreachable.
