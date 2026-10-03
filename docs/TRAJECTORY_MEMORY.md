# Trajectory memory — how the Desk Copilot learns from past runs

The Wingman Desk Copilot is a meta agent. When a trader asks a question, the
copilot does not start from a blank page — it first checks whether anyone
has asked something similar before, and if so, adapts that past plan
instead of re-discovering it.

This document explains how that works, where the data lives, and how to
turn it on for an agent you build yourself in the Abenix AI Builder.

## Three things happen on every Desk Copilot run

1. The copilot calls `recall_trajectory(query=<the question>)`. The tool
   walks the trajectory store and returns up to K past runs whose intent
   text overlaps the new query. Each past run carries the agents that
   were invoked, the synthesised brief, and (if available) the approval
   id and outcome score that came out the other side.

2. The copilot fans out to the specialists it decides are needed — most
   often two to five of `wingman-arb-analyzer`, `wingman-mispricing-extractor`,
   `wingman-scenario-forecaster`, `wingman-ops-monitor`, `wingman-graph-query`.
   The fan-out uses the `invoke_agent` tool, so every sub-agent runs as a
   first-class platform execution with its own DAG + cost record.

3. When the run completes, the copilot writes a new trajectory record:
   the question, the plan, every specialist's structured output, the
   final brief, the recommended action, and the cost. That record is
   the source for the next `recall_trajectory` call.

## Where trajectories live

Trajectories are JSON files on the shared `/data` PVC:

```
/data/wingman-trajectories/{tenant}/{trajectory_id}.json
```

Each record is small (a few KB at most) so a year of desk activity is a
few hundred MB. No DB migration is required to run trajectory memory.

The platform's `recall_trajectory` tool reads `TRAJECTORY_DIR`
(`/data/trajectories`) under the tenant's folder and `shared`. Wingman writes
to `WINGMAN_TRAJECTORY_DIR` (`/data/wingman-trajectories`), folder
`WINGMAN_TRAJECTORY_TENANT` (`shared` by default).

## Erasure

Each record carries the `execution_id` of the run it came from. A GDPR purge
(`POST /api/gdpr/users/{id}/purge`) looks up the person's runs and deletes
every record whose `execution_id` is one of them, or whose `user_id` is the
person, from the tenant's folder and `shared` under both directories. The
trajectory receipt counts the records deleted.

## Outcome grading (phase 3)

When a trade card produced by a trajectory routes through `/approvals`
and gets signed off, the approval id is attached to the trajectory via
`POST /api/wingman/desk/trajectories/{trajectory_id}/outcome`. A
follow-on (cron-driven) job grades the trajectory against realised
spread movement N days later and updates `success_signal`.
`recall_trajectory` weights past runs by `success_signal` so good
trajectories get preferred and bad ones get retired.

## Turning trajectory memory on for your own agent

Trajectory memory is opt-in per agent. To enable it for an agent built
in AI Builder, give the agent these tools:

- `recall_trajectory` — read past runs that look like the new task.
- (optional) `invoke_agent` — only useful if your agent acts as a
  planner that delegates to other registered agents.

In the agent's system prompt, instruct the model to call
`recall_trajectory` before planning, e.g.:

> Before deciding what to do, call `recall_trajectory(query=<the user
> question>)`. If a past trajectory has term_overlap >= 3 with the new
> query, adapt that plan instead of starting fresh.

Trajectories are tenant-scoped — your agent will only see runs from
its own tenant.

## Inspecting and replaying past runs

The Desk page (`/desk` in Wingman) shows the trajectories sidebar. Each
row is clickable — clicking it replays the past brief into the main
panel without re-firing the agents.

For raw JSON access:

```
GET  /api/wingman/desk/trajectories?q=<query>&limit=25
GET  /api/wingman/desk/trajectories/{trajectory_id}
POST /api/wingman/desk/trajectories/{trajectory_id}/outcome
```
