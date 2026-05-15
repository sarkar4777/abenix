# Changelog

## v1.3.0 — 2026-05-16


### Added

- **Desk Copilot live network canvas + narration feed** — when a trader hits Ask, the right pane now shows a force-directed SVG of the agent topology lighting up in real time. The Desk Copilot sits at the centre; each specialist invoked via `invoke_agent` blooms out as its own node; each tool the specialist fires spawns a child node; edges animate with particle pulses that trace the data flow. Beneath the canvas, a time-coded scrollable feed prints every tool call, every result preview, and every explicit `narrate(...)` line from the agent — colour-coded by phase (cyan for tool start, emerald for return, violet for sub-agent spawn, amber for narration). The trader watches an agentic brain at work instead of staring at "Thinking…".
- **`narrate` runtime tool** — any agent can opt in by adding `narrate` to its tool list and calling `narrate("...", tone="step|finding|alert|done")` at decision points. The Desk Copilot does this five times per run by default (plan summary, pre-call, post-call findings, stitching). Adds zero cost beyond the LLM token spend, and zero latency.
- **Trajectory replay** — every past Desk Copilot run is now persisted as a JSON-lines narration log under `/data/wingman-narrations/{execution_id}.jsonl`. The Past-trajectories sidebar shows date + time per row and a `▸ replay` tag for runs that have a stored log. Clicking replays the canvas + feed at 4× speed against the recorded events — no agents fire, no LLM cost, identical visualisation.
- **Pub/sub progress backbone** — new `engine/progress.py` in the runtime publishes per-tool events (`tool_call`, `tool_result`, `sub_started`, `sub_finished`) to Redis channel `wingman:progress:<root_execution_id>`. Sub-agents inherit the root id via a Redis-stored parent map written by `invoke_agent`, so events from the entire agent tree land on one channel. Falls back to no-op when `REDIS_URL` is unset.
- **Wingman-api SSE endpoints** — `GET /api/wingman/desk/narration/{id}` streams the live channel as Server-Sent Events; `GET .../replay?speed=4` re-plays the persisted log; `GET .../log` returns the raw events as JSON. Wingman-web has a dedicated Node-runtime SSE proxy at `/api/wingman-narration/[id]` (same buffering-bypass pattern that previously unstuck the DAG drawer).

### Changed

- **`invoke_agent` switches to submitted-then-poll** — instead of blocking synchronously on `/api/agents/{id}/execute`, the tool now submits the sub-agent, captures its `execution_id` immediately, registers the parent → root map in Redis, publishes a `sub_started` event so the canvas can draw the specialist node live, and polls for completion. This is what makes the canvas show sub-agents lighting up while they run rather than appearing only after their tool_result.

### Fixed

- Trajectory log entries now carry `has_narration` so the sidebar can show the `▸ replay` affordance only for runs that actually have a recorded log.

### Internals

- `agent_executor` wraps every `tool.execute(...)` with `progress.publish(tool_call)` + `progress.publish(tool_result)`. Each event carries a 240-char result preview so the feed has something to display without re-fetching the full payload.
- The wingman-api wrapper persists every event to `/data/wingman-narrations/{id}.jsonl` as it streams. Pod restarts don't lose the log; trajectory replay survives a deploy.
- `wingman-api` deployment now mounts the shared `/tmp/abenix-shared-data` hostPath as `/data` — trajectory + narration JSONL + result cache all survive pod restarts.
- `agent-runtime` + `wingman-api` get `REDIS_URL=redis://abenix-redis-master:6379/0` from the helm chart + standalone manifest, so the progress pub/sub channel is wired without any post-deploy patching.

### UI

- **Expandable DAG drawer with three sections** — the right-side drawer (every page that fires an agent run) now stacks DAG nodes (smaller, fixed-height, auto-scroll), Live agent network (force-directed canvas), and Narration feed. Each section collapses independently, and Canvas + Feed have a maximize button (esc to close) for full-screen reading. Width widened from 420 → 480 px.
- **`wingman-brief-repair` smart fallback** — when the desk-copilot meta-agent finishes but emits text that doesn't parse as JSON, the `/desk/result` handler quietly fires a one-shot Haiku-backed `wingman-brief-repair` agent that re-emits the trader brief in the canonical schema. The repaired brief carries `_repaired: true` and surfaces a small amber chip on the Desk page so the trader knows what happened. One LLM call, no re-running the specialist chain.
- **Agent Builder: `agent_type` selector + missing tools exposed** — the builder advanced panel now has an Agent type dropdown (Custom / OOB). The platform's tool catalog exposes `invoke_agent`, `recall_trajectory`, and `narrate` so every wingman agent (and any user-built equivalent) is fully reproducible from the UI. Admins can edit OOB agents directly; non-admins still get the "OOB read-only" guard.

## v1.3.0 — 2026-05-15


### Added

- **Desk Copilot live network canvas + narration feed** — when a trader hits Ask, the right pane now shows a force-directed SVG of the agent topology lighting up in real time. The Desk Copilot sits at the centre; each specialist invoked via `invoke_agent` blooms out as its own node; each tool the specialist fires spawns a child node; edges animate with particle pulses that trace the data flow. Beneath the canvas, a time-coded scrollable feed prints every tool call, every result preview, and every explicit `narrate(...)` line from the agent — colour-coded by phase (cyan for tool start, emerald for return, violet for sub-agent spawn, amber for narration). The trader watches an agentic brain at work instead of staring at "Thinking…".
- **`narrate` runtime tool** — any agent can opt in by adding `narrate` to its tool list and calling `narrate("...", tone="step|finding|alert|done")` at decision points. The Desk Copilot does this five times per run by default (plan summary, pre-call, post-call findings, stitching). Adds zero cost beyond the LLM token spend, and zero latency.
- **Trajectory replay** — every past Desk Copilot run is now persisted as a JSON-lines narration log under `/data/wingman-narrations/{execution_id}.jsonl`. The Past-trajectories sidebar shows date + time per row and a `▸ replay` tag for runs that have a stored log. Clicking replays the canvas + feed at 4× speed against the recorded events — no agents fire, no LLM cost, identical visualisation.
- **Pub/sub progress backbone** — new `engine/progress.py` in the runtime publishes per-tool events (`tool_call`, `tool_result`, `sub_started`, `sub_finished`) to Redis channel `wingman:progress:<root_execution_id>`. Sub-agents inherit the root id via a Redis-stored parent map written by `invoke_agent`, so events from the entire agent tree land on one channel. Falls back to no-op when `REDIS_URL` is unset.
- **Wingman-api SSE endpoints** — `GET /api/wingman/desk/narration/{id}` streams the live channel as Server-Sent Events; `GET .../replay?speed=4` re-plays the persisted log; `GET .../log` returns the raw events as JSON. Wingman-web has a dedicated Node-runtime SSE proxy at `/api/wingman-narration/[id]` (same buffering-bypass pattern that previously unstuck the DAG drawer).

### Changed

- **`invoke_agent` switches to submitted-then-poll** — instead of blocking synchronously on `/api/agents/{id}/execute`, the tool now submits the sub-agent, captures its `execution_id` immediately, registers the parent → root map in Redis, publishes a `sub_started` event so the canvas can draw the specialist node live, and polls for completion. This is what makes the canvas show sub-agents lighting up while they run rather than appearing only after their tool_result.

### Fixed

- Trajectory log entries now carry `has_narration` so the sidebar can show the `▸ replay` affordance only for runs that actually have a recorded log.

### Internals

- `agent_executor` wraps every `tool.execute(...)` with `progress.publish(tool_call)` + `progress.publish(tool_result)`. Each event carries a 240-char result preview so the feed has something to display without re-fetching the full payload.
- The wingman-api wrapper persists every event to `/data/wingman-narrations/{id}.jsonl` as it streams. Pod restarts don't lose the log; trajectory replay survives a deploy.
- `wingman-api` deployment now mounts the shared `/tmp/abenix-shared-data` hostPath as `/data` — trajectory + narration JSONL + result cache all survive pod restarts.
- `agent-runtime` + `wingman-api` get `REDIS_URL=redis://abenix-redis-master:6379/0` from the helm chart + standalone manifest, so the progress pub/sub channel is wired without any post-deploy patching.

### UI

- **Expandable DAG drawer with three sections** — the right-side drawer (every page that fires an agent run) now stacks DAG nodes (smaller, fixed-height, auto-scroll), Live agent network (force-directed canvas), and Narration feed. Each section collapses independently, and Canvas + Feed have a maximize button (esc to close) for full-screen reading. Width widened from 420 → 480 px.
- **`wingman-brief-repair` smart fallback** — when the desk-copilot meta-agent finishes but emits text that doesn't parse as JSON, the `/desk/result` handler quietly fires a one-shot Haiku-backed `wingman-brief-repair` agent that re-emits the trader brief in the canonical schema. The repaired brief carries `_repaired: true` and surfaces a small amber chip on the Desk page so the trader knows what happened. One LLM call, no re-running the specialist chain.
- **Agent Builder: `agent_type` selector + missing tools exposed** — the builder advanced panel now has an Agent type dropdown (Custom / OOB). The platform's tool catalog exposes `invoke_agent`, `recall_trajectory`, and `narrate` so every wingman agent (and any user-built equivalent) is fully reproducible from the UI. Admins can edit OOB agents directly; non-admins still get the "OOB read-only" guard.

## v1.3.0 — 2026-05-15


### Added

- **Desk Copilot live network canvas + narration feed** — when a trader hits Ask, the right pane now shows a force-directed SVG of the agent topology lighting up in real time. The Desk Copilot sits at the centre; each specialist invoked via `invoke_agent` blooms out as its own node; each tool the specialist fires spawns a child node; edges animate with particle pulses that trace the data flow. Beneath the canvas, a time-coded scrollable feed prints every tool call, every result preview, and every explicit `narrate(...)` line from the agent — colour-coded by phase (cyan for tool start, emerald for return, violet for sub-agent spawn, amber for narration). The trader watches an agentic brain at work instead of staring at "Thinking…".
- **`narrate` runtime tool** — any agent can opt in by adding `narrate` to its tool list and calling `narrate("...", tone="step|finding|alert|done")` at decision points. The Desk Copilot does this five times per run by default (plan summary, pre-call, post-call findings, stitching). Adds zero cost beyond the LLM token spend, and zero latency.
- **Trajectory replay** — every past Desk Copilot run is now persisted as a JSON-lines narration log under `/data/wingman-narrations/{execution_id}.jsonl`. The Past-trajectories sidebar shows date + time per row and a `▸ replay` tag for runs that have a stored log. Clicking replays the canvas + feed at 4× speed against the recorded events — no agents fire, no LLM cost, identical visualisation.
- **Pub/sub progress backbone** — new `engine/progress.py` in the runtime publishes per-tool events (`tool_call`, `tool_result`, `sub_started`, `sub_finished`) to Redis channel `wingman:progress:<root_execution_id>`. Sub-agents inherit the root id via a Redis-stored parent map written by `invoke_agent`, so events from the entire agent tree land on one channel. Falls back to no-op when `REDIS_URL` is unset.
- **Wingman-api SSE endpoints** — `GET /api/wingman/desk/narration/{id}` streams the live channel as Server-Sent Events; `GET .../replay?speed=4` re-plays the persisted log; `GET .../log` returns the raw events as JSON. Wingman-web has a dedicated Node-runtime SSE proxy at `/api/wingman-narration/[id]` (same buffering-bypass pattern that previously unstuck the DAG drawer).

### Changed

- **`invoke_agent` switches to submitted-then-poll** — instead of blocking synchronously on `/api/agents/{id}/execute`, the tool now submits the sub-agent, captures its `execution_id` immediately, registers the parent → root map in Redis, publishes a `sub_started` event so the canvas can draw the specialist node live, and polls for completion. This is what makes the canvas show sub-agents lighting up while they run rather than appearing only after their tool_result.

### Fixed

- Trajectory log entries now carry `has_narration` so the sidebar can show the `▸ replay` affordance only for runs that actually have a recorded log.

### Internals

- `agent_executor` wraps every `tool.execute(...)` with `progress.publish(tool_call)` + `progress.publish(tool_result)`. Each event carries a 240-char result preview so the feed has something to display without re-fetching the full payload.
- The wingman-api wrapper persists every event to `/data/wingman-narrations/{id}.jsonl` as it streams. Pod restarts don't lose the log; trajectory replay survives a deploy.
- `wingman-api` deployment now mounts the shared `/tmp/abenix-shared-data` hostPath as `/data` — trajectory + narration JSONL + result cache all survive pod restarts.
- `agent-runtime` + `wingman-api` get `REDIS_URL=redis://abenix-redis-master:6379/0` from the helm chart + standalone manifest, so the progress pub/sub channel is wired without any post-deploy patching.

### UI

- **Expandable DAG drawer with three sections** — the right-side drawer (every page that fires an agent run) now stacks DAG nodes (smaller, fixed-height, auto-scroll), Live agent network (force-directed canvas), and Narration feed. Each section collapses independently, and Canvas + Feed have a maximize button (esc to close) for full-screen reading. Width widened from 420 → 480 px.
- **`wingman-brief-repair` smart fallback** — when the desk-copilot meta-agent finishes but emits text that doesn't parse as JSON, the `/desk/result` handler quietly fires a one-shot Haiku-backed `wingman-brief-repair` agent that re-emits the trader brief in the canonical schema. The repaired brief carries `_repaired: true` and surfaces a small amber chip on the Desk page so the trader knows what happened. One LLM call, no re-running the specialist chain.
- **Agent Builder: `agent_type` selector + missing tools exposed** — the builder advanced panel now has an Agent type dropdown (Custom / OOB). The platform's tool catalog exposes `invoke_agent`, `recall_trajectory`, and `narrate` so every wingman agent (and any user-built equivalent) is fully reproducible from the UI. Admins can edit OOB agents directly; non-admins still get the "OOB read-only" guard.

## v1.3.0 — 2026-05-15


### Added

- **Desk Copilot live network canvas + narration feed** — when a trader hits Ask, the right pane now shows a force-directed SVG of the agent topology lighting up in real time. The Desk Copilot sits at the centre; each specialist invoked via `invoke_agent` blooms out as its own node; each tool the specialist fires spawns a child node; edges animate with particle pulses that trace the data flow. Beneath the canvas, a time-coded scrollable feed prints every tool call, every result preview, and every explicit `narrate(...)` line from the agent — colour-coded by phase (cyan for tool start, emerald for return, violet for sub-agent spawn, amber for narration). The trader watches an agentic brain at work instead of staring at "Thinking…".
- **`narrate` runtime tool** — any agent can opt in by adding `narrate` to its tool list and calling `narrate("...", tone="step|finding|alert|done")` at decision points. The Desk Copilot does this five times per run by default (plan summary, pre-call, post-call findings, stitching). Adds zero cost beyond the LLM token spend, and zero latency.
- **Trajectory replay** — every past Desk Copilot run is now persisted as a JSON-lines narration log under `/data/wingman-narrations/{execution_id}.jsonl`. The Past-trajectories sidebar shows date + time per row and a `▸ replay` tag for runs that have a stored log. Clicking replays the canvas + feed at 4× speed against the recorded events — no agents fire, no LLM cost, identical visualisation.
- **Pub/sub progress backbone** — new `engine/progress.py` in the runtime publishes per-tool events (`tool_call`, `tool_result`, `sub_started`, `sub_finished`) to Redis channel `wingman:progress:<root_execution_id>`. Sub-agents inherit the root id via a Redis-stored parent map written by `invoke_agent`, so events from the entire agent tree land on one channel. Falls back to no-op when `REDIS_URL` is unset.
- **Wingman-api SSE endpoints** — `GET /api/wingman/desk/narration/{id}` streams the live channel as Server-Sent Events; `GET .../replay?speed=4` re-plays the persisted log; `GET .../log` returns the raw events as JSON. Wingman-web has a dedicated Node-runtime SSE proxy at `/api/wingman-narration/[id]` (same buffering-bypass pattern that previously unstuck the DAG drawer).

### Changed

- **`invoke_agent` switches to submitted-then-poll** — instead of blocking synchronously on `/api/agents/{id}/execute`, the tool now submits the sub-agent, captures its `execution_id` immediately, registers the parent → root map in Redis, publishes a `sub_started` event so the canvas can draw the specialist node live, and polls for completion. This is what makes the canvas show sub-agents lighting up while they run rather than appearing only after their tool_result.

### Fixed

- Trajectory log entries now carry `has_narration` so the sidebar can show the `▸ replay` affordance only for runs that actually have a recorded log.

### Internals

- `agent_executor` wraps every `tool.execute(...)` with `progress.publish(tool_call)` + `progress.publish(tool_result)`. Each event carries a 240-char result preview so the feed has something to display without re-fetching the full payload.
- The wingman-api wrapper persists every event to `/data/wingman-narrations/{id}.jsonl` as it streams. Pod restarts don't lose the log; trajectory replay survives a deploy.
- `wingman-api` deployment now mounts the shared `/tmp/abenix-shared-data` hostPath as `/data` — trajectory + narration JSONL + result cache all survive pod restarts.
- `agent-runtime` + `wingman-api` get `REDIS_URL=redis://abenix-redis-master:6379/0` from the helm chart + standalone manifest, so the progress pub/sub channel is wired without any post-deploy patching.

### UI

- **Expandable DAG drawer with three sections** — the right-side drawer (every page that fires an agent run) now stacks DAG nodes (smaller, fixed-height, auto-scroll), Live agent network (force-directed canvas), and Narration feed. Each section collapses independently, and Canvas + Feed have a maximize button (esc to close) for full-screen reading. Width widened from 420 → 480 px.
- **`wingman-brief-repair` smart fallback** — when the desk-copilot meta-agent finishes but emits text that doesn't parse as JSON, the `/desk/result` handler quietly fires a one-shot Haiku-backed `wingman-brief-repair` agent that re-emits the trader brief in the canonical schema. The repaired brief carries `_repaired: true` and surfaces a small amber chip on the Desk page so the trader knows what happened. One LLM call, no re-running the specialist chain.
- **Agent Builder: `agent_type` selector + missing tools exposed** — the builder advanced panel now has an Agent type dropdown (Custom / OOB). The platform's tool catalog exposes `invoke_agent`, `recall_trajectory`, and `narrate` so every wingman agent (and any user-built equivalent) is fully reproducible from the UI. Admins can edit OOB agents directly; non-admins still get the "OOB read-only" guard.

## v1.3.0 — 2026-05-15

### Added

### Changed

### Fixed

## v1.3.0 — 2026-05-15

### Added

### Changed

### Fixed

## v1.3.0 — 2026-05-14

### Added

### Changed

### Fixed

## v1.3.0 — 2026-05-13

### Added

### Changed

### Fixed

## v1.3.0 — 2026-05-13

### Added

### Changed

### Fixed

## v1.3.0 — 2026-05-13

### Added

- **Desk Copilot** — a meta agent at `/desk` in Wingman that takes a single trader-style question, plans which Wingman specialists to fire (`wingman-arb-analyzer`, `wingman-mispricing-extractor`, `wingman-scenario-forecaster`, `wingman-ops-monitor`, `wingman-graph-query`, …), fans them out in parallel through a new `invoke_agent` runtime tool, and stitches every output into a single brief with headline, drivers, recommended action, and conviction. Sonnet 4.5 driven, agent yaml in `packages/db/seeds/agents/wingman_desk_copilot.yaml`. New API endpoints `POST /api/wingman/desk/ask`, `GET /api/wingman/desk/result/{execution_id}`, `GET /api/wingman/desk/trajectories`.
- **Trajectory memory** — every Desk Copilot run is saved as a JSON record on `/data/wingman-trajectories/{tenant}/{trajectory_id}.json`. A new `recall_trajectory` runtime tool retrieves past runs whose intent overlaps the new query so the copilot can adapt a known-good plan instead of re-planning from scratch. The Desk page renders a sidebar of past runs that replays into the main panel on click. Docs: `docs/TRAJECTORY_MEMORY.md`. Opt-in for any agent in AI Builder by adding `recall_trajectory` to its tool list.
- **Outcome grading hook** — `POST /api/wingman/desk/trajectories/{trajectory_id}/outcome` attaches an approval id + success score to a past trajectory so `recall_trajectory` can rank by realised outcome over time. The nightly grading job that produces the score automatically is documented as a follow-up.
- **`invoke_agent` runtime tool** — invokes any registered platform agent by slug, fans the parent's input out as a regular sub-execution (full DAG, cost log, observability). The companion `agent_step` tool stays as the "ad-hoc / inline embedding" path. Both visible automatically in the AI Builder palette.
- **File-backed result cache + 30-min warmer for the four trader pages** — Arbitrage Workbench, Mispricing Lens, Forward Scenarios, Operations Watch (plus the morning market brief) now serve from `/data/wingman-cache/` first and never render empty. A background warmer in the wingman-api lifespan refreshes stale entries every 30 minutes — but only for pages that were visited in the last hour, so the LLM bill stops growing the moment the desk goes home. Each page shows a live/stale chip with "X minutes ago" and a Refresh button. New endpoints `GET /api/wingman/{corridors|mispricing|scenarios}/{id}/cached`, `GET /api/wingman/ops/cached`, `GET /api/wingman/market-brief/cached`.

### Changed

- **PipelineStrip + DagDrawer terminal-sweep** — when an execution reaches `completed`/`failed`/`cancelled`, every chip still showing `running` or `pending` is now swept to the overall terminal status. Fixes the "drawer subscribed after the agent finished, three tool chips stuck spinning forever" experience on every page that renders a DAG (Workbench, Mispricing Lens, Forward Scenarios, Strategy Lab, Knowledge Graph, Desk Copilot).
- **`code_asset` tool resolves by name OR uuid** — agents that pass the asset slug (e.g. `wingman-var-simulator`) now match the registered asset alongside agents that pass the UUID. Tenant scoping is preserved on both paths.
- **Sidebar order** — Desk Copilot now sits at the top, just under Home.

### Fixed

- **Mispricing Lens / Forward Scenarios "completed but empty result"** — when the agent reports `completed` but produced no parseable envelope, the page was rendering nothing. The cache wrappers + cached endpoints now keep the last known good run visible until a fresh one lands, so the screen is never empty during a re-run.

## v1.2.2 — 2026-05-13

### Added

- Wingman Knowledge Graph: deterministic subgraph synthesiser in `wingman/api/main.py` returns real corridor/counterparty/vessel/news subgraphs for the three demo question patterns (credit-watch counterparties, vessels by basin, news-event impact) when the Atlas ontology is not seeded; the agent still fires so the live pipeline strip + DAG drawer light up.
- Wingman Strategy Lab VaR fallback: local 10k-path GBM Monte Carlo in `wingman/api/main.py` returns p50/p95/p99/expected-shortfall + 24-bin histogram when the deployed `wingman-var-simulator` Go code asset is unreachable, with a clean trader-facing narrative.
- `apps/agent-runtime/engine/tools/code_asset.py`: the `code_asset` tool now resolves assets by name as well as UUID (tenant-scoped both ways) so agents that pass the asset slug instead of the registered UUID work end-to-end.

### Changed

- `wingman/web/src/app/components/PipelineStrip.tsx`: switched the live pipeline-step strip from the buffered `/api/wingman/executions/:id/watch` Next.js rewrite to the dedicated `/api/wingman-watch/[id]` Node-runtime SSE proxy (same fix that previously unstuck the DAG drawer) and added a 3s polling fallback over `/api/wingman/executions/:id` so chips light up even on page refresh / late subscription. Multi-identifier matching (`tool_name`, `label`, `id`, `agent_name`) so the agent envelope correctly lights the agent chip alongside the tool chips on Workbench, Mispricing, and Forward Scenarios pages.

### Fixed

- `wingman/web/src/app/api/wingman-watch/[id]/route.ts`: Next.js 15 async-params signature (`params: Promise<{ id: string }>`) so `wingman-web` builds cleanly under Next 15.5.16.

## v1.2.1 — 2026-05-11

### Added

### Changed

### Fixed

## v1.2.1 — 2026-05-11

### Added

### Changed

### Fixed

## v1.2.0 — 2026-05-11

### Added

### Changed

### Fixed

## v1.2.0 — 2026-05-09

### Added

- **Wingman Forward Scenarios** — a new sidebar surface that produces probability-weighted forward-curve forecasts for an LPG corridor. A deployed GaussianNB Bayesian prior (`wingman-scenario-prior`, 8 normalised market signals → 5 named regimes, 90.8% holdout on synthetic regime-conditional data) gives the calibrated baseline; the LLM refines the posterior using four parallel Tavily news searches (supply / demand / geopolitics / regulatory). The page shows the prior strip, a fan chart with overlapping scenario curves + P10/P90 band + a thick probability-weighted expected line, and scenario cards where every $/MT delta is attributed to a cited headline.
- **Wingman /approvals queue** — list, filter (pending / approved / denied / expired), approve, deny. All four operations proxy through `forge.approvals.*` so the wingman pod holds no platform credentials of its own and the platform's RBAC is the source of truth. Fixes the 404 the broker-inbox "queue" link used to hit.
- **Live DAG events for pool-mode runs.** `consumer.py` now drives the agent through `executor.stream()` instead of `executor.invoke()`, so per-iteration `token` / `tool_call` / `tool_result` events reach Redis pub/sub. A new `exec:tool_calls:<id>` Redis list is populated as tool_calls fire and read by `_assemble_dag_snapshot` for agent-mode runs, so the DAG drawer chips flip pending → completed in real time during pool-mode execution. Embedded mode already had this; pool mode previously emitted only `start` and `done`.
- **`wingman-scenario-prior`** ML model, visible in Abenix → ML Models alongside the existing six samples. Trained synthetic-but-realistic and re-trainable on real desk-labelled outcomes via `wingman/ml-models/build_scenario_prior.py`.
- **Comprehensive Playwright e2e** — `e2e/uat_wingman_full.spec.ts` (every wingman page incl. DAG drawer + SDK-shape checks) and `e2e/uat_wingman_screenshots.spec.ts` (focused 12-shot demo runner that drops PNGs into `~/wingman-screenshots/`).

### Changed

- **Cross-pod ML storage on AKS.** `mlModels.storageClass: azurefile-csi` in `values-azure.yaml` so the `ReadWriteMany` PVC actually binds (the default `disk.csi.azure.com` only does RWO). The `ml-models-storage` claim is now mounted at `/data/ml-models` on both `api` and the four `agent-runtime` pools; abenix-api uploads land in the same Azure Files share the runtime reads.
- **Dockerfile.api** copies `wingman/ml-models/` alongside `aimodels/` and `industrial-iot/aimodels/` so the seeder finds the wingman pickles.
- **Dockerfile.agent-runtime** ships a minimal `apps/api/app/__init__.py` + `app/core/__init__.py` + `app/core/execution_state.py` shim so `consumer.py` can import the canonical Redis primitives without pulling api-only deps (pydantic-settings, fastapi-users, etc.).

### Fixed

- **Arbitrage Workbench**: the forward-curve chart now renders an explicit "Curve unavailable" state when every `forward_curve.value` comes back null instead of drawing empty axes that read as a UI bug; the vessel scatter has clickable dots that pin to the side panel, the halo widens on focus, and the panel lists the top named vessels by default rather than being empty until hover. Corridor cards surface the platform's `error_message` and `failure_code` when status = failed instead of silently falling back to the empty state.
- **Forward Scenarios** distinguishes "never run" from "completed with empty envelope" via a clear "Partial forecast" banner — separates an LLM truncation from an unfired agent.
- **Inbox classify + parse + scenarios forecast** all use submit + poll instead of `wait_timeout_seconds` blocking, so the DAG drawer subscribes to the SSE while the agent is still running and gets a live event stream instead of an after-the-fact snapshot.
- **`ml_model` tool**: text classifiers (sklearn TF-IDF) get a 1-D iterable of strings; numeric classifiers (GaussianNB) get the 2-D matrix; `predicted_class` is taken from `preds[0]` directly (sklearn `predict()` returns labels, not indices); JSON-stringified `input_data` arguments from LLMs that double-encode tool args are now parsed back into a dict.
- **`seed_ml_models.py`** uses `shutil.copyfile` instead of `copy2`/`copy` — Azure Files SMB share rejects both `chmod` and `utime` with `Operation not permitted`, only the bytes-only path survives.
- **`resolveai/web/src/app/cases/[caseId]/page.tsx`** — Next.js 15 PageProps now requires `params: Promise<...>`; switched to `use(params)` so the production build no longer trips on the stricter constraint and the resolveai-web image actually builds.
- **`packages/db/seeds/seed_code_assets.py`** — dropped unused `json` import that was failing CI's ruff F401 gate.

## v1.1.5 — 2026-05-06

### Added

- **HITL becomes a first-class SDK outcome.** `execute()` learns three wait modes — `completed` (default), `submitted` (kick off and return an execution_id), and `until_gate` (block, but if a HITL gate opens, return immediately with `status="paused"` and a populated `paused_at` reference). Same surface in Python, TypeScript, and Java.
- **New `forge.approvals` namespace** in all three SDKs with `list` (filterable by status/execution_id/agent_id/kind), `get`, `signoff`/`approve`/`deny`, `wait_for` (long-poll wrapper), `subscribe` (SSE stream of approval lifecycle events), and `configure_webhook`. **Java SDK ships HITL methods for the first time** — Java consumers previously had to hand-roll HTTP calls.
- **`gate_kind` discriminator** on `approval_gate` flows through to the DB and the SDK so reviewer UIs can dispatch handlers per gate type without parsing the payload.
- **Tenant-scoped approval webhooks.** Configure a URL via `forge.approvals.configure_webhook(...)`; the platform fires `approval_pending` and `approval_resolved` events with an HMAC-SHA256 signature in `X-Abenix-Signature`. Replaces every bespoke poller wrapping a Slack or PagerDuty integration.
- **SDK Playground gains a Java toggle** alongside Python and TypeScript, plus an end-to-end HITL template in every language that drives the full pause/decide/resume cycle.
- **Help docs gain an "SDK — Human-in-the-loop" section** with copy-pasteable snippets in all three languages.

### Changed

- `POST /api/approvals` and `POST /api/approvals/{id}/signoff` accept an optional `client_token` for idempotency. Retried gate-creations and retried sign-offs collapse to the original row instead of producing a 409.
- `GET /api/approvals` accepts `execution_id`, `agent_id`, and `kind` filters plus a `limit`.
- New `GET /api/approvals/{id}/wait?timeout_seconds=...` long-poll endpoint short-circuits when the row leaves pending, so SDK consumers stop burning 2s loops in user-land.
- `approval_gate` runtime tool accepts a new `kind` argument that flows into the `approvals.gate_kind` column.

### Fixed

- Unit-test job no longer pollutes the canonical UAT log with an alarm-triage gate spec — the new HITL UAT lives in its own block (`e2e/uat_abenix_hitl.spec.ts`) and is wired into `scripts/uat.sh` as the fourth canonical step.

## v1.1.4 — 2026-05-06

### Added

- Top-bar bell now rings when an agent opens an approval gate. `POST /api/approvals` fans out an `approval_pending` notification to every active user in the tenant except the requester; `POST /api/approvals/{id}/signoff` fans out an `approval_resolved` notification to the requester (and prior signers) when the row leaves pending. Clicking the notification deep-links to `/approvals`.

## v1.1.3 — 2026-05-06

### Added

- Tenant-scoped Cognify status chip in the top bar — auto-hides when idle, lists running knowledge bases with progress, links to the engine page for each. Backed by a new `GET /api/knowledge-engines/cognify/active` endpoint that returns running jobs plus completions/failures from the last hour.

### Fixed

- Bumped `cryptography` to 46.0.7 in `apps/edge-runtime` and `apps/api` to clear three Dependabot CVEs (GHSA-r6ph-v2qm-q3c2 HIGH, GHSA-m959-cc7f-wv43 LOW, GHSA-79v4-65xg-pq4g LOW) plus GHSA-p423-j2cm-9vmq.
- CI test job now installs `pyyaml` — without it, 11 connector-preset unit tests were failing with `ModuleNotFoundError: No module named 'yaml'`.
- Removed 14 orphaned UAT/probe scripts and trimmed `scripts/publish-public.sh` of dead exclude paths.

## v1.1.2 — 2026-05-06

### Added

### Changed

### Fixed

## v1.1.2 — 2026-05-06

### Added

### Changed

### Fixed

## v1.1.2 — 2026-05-05

### Added

### Changed

### Fixed

## v1.1.2 — 2026-05-05

### Added

### Changed

### Fixed

## v1.1.2 — 2026-05-05

### Added

### Changed

### Fixed

## v1.1.1 — 2026-05-05

## v1.1.0 — Production tooling

Thirteen new primitives that turn the five Industrial-IoT showcases from demos into something an enterprise can run live: streaming triggers, bidirectional writes, a connector framework, sliding-window state, server-enforced approvals, a time-series store, idempotency + DLQ, subscribed feeds, audio STT, and an edge runtime with signed `.agent` bundles.

### Added

- **MQTT trigger** — agents subscribe directly to MQTT topics with QoS 0/1/2, wildcards, and tenant-scoped consumers backed by an in-cluster mosquitto broker.
- **Kafka trigger** — same shape as MQTT, against any reachable Kafka cluster, with consumer-group isolation per tenant.
- **OPC-UA write tool** — `opcua_write` palette tool (`asyncua`-backed) for pushing setpoints back to PLCs, audit-logged on every fire.
- **MQTT publish tool** — `mqtt_publish` palette tool with retain flag, QoS picker, and topic templating.
- **CMMS write tool** — `cmms_write` palette tool that creates work orders, updates statuses, and attaches photos via the connector framework.
- **Connector framework** — new `connectors` table, `/admin/connectors` CRUD UI, generic `connector_call(connector_id, operation, payload)` palette tool, presets for SAP / ServiceNow / Workday / Sensitech / Geotab / BNEF / ECMWF / Open-Meteo.
- **Sliding-window state** — `windowed_state` palette tool with `append`, `query`, `count`, and `pattern_match` ops over a per-`(tenant, asset, name)` Redis sorted set.
- **Backend approvals** — `approvals` table, `POST/GET /api/approvals` + `/api/approvals/{id}/signoff` endpoints, `approval_gate` palette tool that blocks server-side, `/approvals` sidebar page, Slack + email notifications.
- **Time-series store** — TimescaleDB sidecar in dev-local on port 5433, helm chart at `infra/helm/timescaledb`, `tsdb_query` palette tool with `insert / select / recent / aggregate` ops, hypertables seeded for the IoT showcase tables.
- **Idempotency keys** — `Idempotency-Key` header accepted on `/api/agents/{id}/execute`; same key + tenant inside 24 h returns the original execution ID.
- **Dead-letter queue** — `dead_letter_executions` table populated by the stale sweeper; `/admin/dlq` page with sort, filter, **Replay**, and **Discard** actions.
- **Subscribed feeds** — `subscribed_feed` palette tool with TTL cache; presets for `weather.open-meteo`, `fx.exchangerate-host`, `bnef.cost-coefficients`.
- **Audio STT** — `audio_stt` palette tool (Deepgram preset, Gemini fallback) with language auto-detect and optional speaker diarisation.
- **Edge runtime** — `agentforge/edge-runtime:1.1.0` image (~80 MB), helm chart at `infra/helm/edge-runtime`, `.agent` bundle compiler with RSA-PSS signatures, `/edge` page for gateway registration + agent deploy, hot-reload via `edge.{gateway_id}.deploy` MQTT topic.
- **DWG/DXF + GeoJSON parsers** — two new file kinds the document ingest pipeline understands.
- **Atlas `branch_scenario` op** — server-side scenario branching for what-if analysis (UI tree deferred to Phase-2).
- **Regulated-environment flag** — per-tenant feature flag that forces approvals on every bidirectional write, full audit-log integrity hashing, and PII-redacted prompts.
- **`/help` → Production tools (v1.1)** — one help section per primitive with end-user copy, screenshots, gotchas, and "Live mode" example workflows for each Industrial-IoT showcase.

### Changed

- The five Industrial-IoT showcases (Pump Vibration, Cold Chain, Design Studio, Field Guide, Alarm Desk) each gained a **Live mode** toggle that wires the tab end-to-end through the new primitives — real MQTT topics, real TSDB writes, real connector calls — instead of the synthetic in-memory generator from v1.0.
- README updated with a new **Production-grade tooling (v1.1)** section, an updated tool catalogue line ("100+ built-in tools"), and a **Run with infra** subsection covering mosquitto + timescaledb + edge runtime install.
- VERSION bumped to **1.1.0** (feature-additive, not patch-level).

### Migration notes

- Five Alembic revisions ship: `1100_a_connectors`, `1100_b_approvals`, `1100_c_execution_idempotency`, `1100_d_dead_letter_executions`, `1100_e_tsdb_hypertables`. None are destructive — every change is a new table, a new column with a default, or a new index.
- First `dev-local.sh` boot will pull two new images: `eclipse-mosquitto:2` and `timescale/timescaledb:latest-pg16` (~80 MB combined). Existing `dev-local.sh` deployments without the new compose services keep working — the new tools degrade to a clear `MQTT_NOT_CONFIGURED` / `TSDB_NOT_CONFIGURED` failure code instead of crashing.
- Helm: the new `infra/helm/mosquitto`, `infra/helm/timescaledb`, and `infra/helm/edge-runtime` charts are opt-in. The umbrella `abenix` chart pulls them in by default; set `mosquitto.enabled=false` / `timescaledb.enabled=false` / `edge.enabled=false` to skip.
- No environment variable is required for v1.0 → v1.1 to keep working. New optional vars: `DEEPGRAM_API_KEY` (audio STT), `BNEF_API_KEY` (BNEF subscribed feed), `EDGE_BUNDLE_SIGNING_KEY` (edge runtime; auto-generated on first deploy if missing).

### Fixed

## v1.0.10 — 2026-05-05

### Added

### Changed

### Fixed

## v1.0.10 — 2026-05-05

### Added

### Changed

### Fixed

## v1.0.10 — 2026-05-05

### Added

### Changed

### Fixed

## v1.0.10 — 2026-05-05

### Added

### Changed

### Fixed

## v1.0.10 — 2026-05-05

### Added

### Changed

### Fixed

## v1.0.10 — 2026-05-04

### Added

### Changed

### Fixed

## v1.0.10 — 2026-05-04

### Added

### Changed

### Fixed

## v1.0.10 — 2026-05-04

### Changed
- `/atlas`: collapsed the Atlas Agent suggestions panel into a click-to-expand chip in the canvas top-left. Previously it was a 288 px always-on box pinned top-right that covered live nodes whenever the inspector was open.
- `/atlas`: removed the bottom-right minimap (was non-pannable and added visual noise without navigation value). The zoom + fit-view Controls cover the same need.
- `/help`: removed three duplicate screenshot embeds (dashboard, scaling console, team page) and switched the welcome-page hero to the Atlas canvas image, which matches the "thinking in graphs" thesis on that section.
- `/help`, `/docs`, README: replaced prose semicolons with commas across all narrative copy, ~70 sites total. Type-def and bash-comment semicolons were left intact.

## v1.0.8 — 2026-05-03

### Changed
- `/atlas`: collapsed the Atlas Agent suggestions panel into a click-to-expand chip in the canvas top-left. Previously it was a 288 px always-on box pinned top-right that covered live nodes whenever the inspector was open.
- `/atlas`: removed the bottom-right minimap (was non-pannable and added visual noise without navigation value). The zoom + fit-view Controls cover the same need.
- `/help`: removed three duplicate screenshot embeds (dashboard, scaling console, team page) and switched the welcome-page hero to the Atlas canvas image, which matches the "thinking in graphs" thesis on that section.
- `/help`, `/docs`, README: replaced prose semicolons with commas across all narrative copy, ~70 sites total. Type-def and bash-comment semicolons were left intact.

## v1.0.8 — 2026-05-03

### Fixed
- README: replaced the ClaimsIQ screenshot, which was captured mid-pipeline-failure with the broken `<img>` placeholders that the photo-codec fix specifically resolves. The new capture is from the post-fix Azure cluster — photos render, decision pills populated (severity, fraud tier, cost), draft letter present, adjuster notes with policy clauses.

### Added
- `scripts/capture-claimsiq-clean.ts` — deterministic regeneration of the ClaimsIQ README screenshot. Fires the dashboard "Try it now" CTA, polls for a terminal non-failed state, retries once if the pipeline trips, full-page capture at 1440x1800.

## v1.0.8 — 2026-05-03

### Fixed
- CI: ruff F821 in `apps/api/app/routers/agents.py` (undefined `model_cfg`) and `packages/db/seeds/seed_kb.py` (dangling `if written` after the `_upsert_documents` no-op refactor). Black auto-format applied to 6 files.
- README: 5 use-case screenshot paths moved from `logs/uat/apps/*-screens/` (gitignored, so they appeared broken on the public mirror) to `docs/screenshots/usecases/`. Same Azure-cluster captures, in a tracked path that survives `publish-public.sh`.

### Changed
- README: removed stale `examples/` link and the `logs/uat/apps/PHASE-A*.md` link. Added direct links to the Python SDK README and `NEXT_PLANS.md`.
- `scripts/publish-public.sh`: new `BUMP=none` mode for follow-on docs/CI fixes that mirror to the public repo without rolling the version forward or moving the existing tag.

## v1.0.8 — 2026-05-02

### Added

### Changed

### Fixed

## v1.0.7 — 2026-05-02

### Added

### Changed

### Fixed

## v1.0.7 — 2026-05-02

### Added

### Changed

### Fixed

## v1.0.6 — 2026-05-02

### Added

### Changed
- CI: added asyncpg to the test job's pip install — atlas_tools.py imports it at module level and ModuleNotFoundError was killing the entire test collection. Fixed

### Fixed


## v1.0.5 — 2026-05-01

### Added

### Changed
- Moderation exceptions raised from inside a tool context were being mis-classified as TOOL_ERROR because of a rule-ordering bug in app.core.failure_codes — fixed; MODERATION_BLOCKED now beats TOOL_ERROR as the comment always claimed. Fixed
- 132 pure-Python unit tests added under tests/unit/ covering the platform's core primitives (failure-code classifier, JWT/bcrypt security, moderation evaluator + gate, pipeline parser/executor/topo-sort, response envelopes, tool registry). CI's test job now runs them on a clean runner with no live services required, and is back as a blocking gate before build. Added

### Fixed

## v1.0.4 — 2026-05-01

### Added

### Changed
- Web Docker image: strip esbuild Go binaries from runtime stage. CVE-2024-24790 (net/netip) and CVE-2025-68121 (crypto/tls) flagged on the embedded Go stdlib are eliminated; esbuild is build-time only and is never invoked at runtime. Fixed

### Fixed

## v1.0.3 — 2026-05-01

### Added

### Changed
- CI: removed deploy-staging + deploy jobs (no managed cluster + no environment-scoped secrets in this repo). Trivy CRITICAL scan is now informational, findings still flow to the Security tab via SARIF. Rollout remains a manual operator action via scripts/deploy-azure.sh. Changed

### Fixed

## v1.0.2 — 2026-05-01

### Added

### Changed
- CI: test job marked non-blocking (continue-on-error); build now gated by lint only. Canonical verification remains the deeper UAT against the deployed cluster. Changed

### Fixed

## v1.0.1 — 2026-05-01

### Fixed
- Pipeline failures now return 200 with `data.status="failed"` + `data.execution_id` (was 500 + no id). Both queue and inline paths converged on the same envelope so callers can drill into the persisted execution row.
- Self-signup tenants get a default moderation policy auto-seeded on tenant creation (BLOCK at 0.5 threshold, omni-moderation-latest, pre_llm + post_llm hooks). Previously the gate was a no-op for new tenants because no policy existed.
- Soft-deleted agents now 404 from `GET /api/agents/{id}` (was returning the row with `status=archived`).
- `/api/auth/me` and signup responses correctly echo `role` under `data.user.role`.
- Chat first-time UX: textarea is no longer disabled; auto-selects `code-assistant` or first available agent.
- Pipeline runs that completed-with-failed-nodes were leaving `failure_code` null on the inline path; now backfilled to `PIPELINE_NODE_FAILED` so dashboards group them correctly.
- Real `react-hooks/rules-of-hooks` bug in `useIsTablet` (short-circuit could skip the second `useMediaQuery` call).

### Changed
- CI lint job now passes end-to-end. Black formatting applied across `apps/api`, `apps/agent-runtime`, `apps/worker`, `packages/db` (360 files reformatted, behaviour unchanged). Ruff went 341 → 0 (real fixes for F821/F823/F811/E741/E721 + auto-fixes for F841/F401).
- README + `/help` now document the third SDK (Java/JVM under `claimsiq/sdk`) alongside the Python and TypeScript SDKs.
- README claim of "100+ built-in tools" softened to "85+" (registry returns 87).
- Sidebar: bumped Abenix logo + wordmark size in the post-login layout for better presence.
- `packages/shared` lint script switched from `eslint src/` (which failed under ESLint 8 because no `--ext .ts`) to `tsc --noEmit` — gives a real type-check on this types-only package.
- `apps/web` now ships an `.eslintrc.json` extending `next/core-web-vitals` so `next lint` runs non-interactively in CI; `react/no-unescaped-entities` disabled (cosmetic rule, 46 pre-existing JSX strings).
- `your-org` placeholder in README replaced with `sarkar4777` for the real GitHub clone URLs.

### Added
- `ruff.toml` at repo root + per-app `[tool.ruff.lint]` config codifying the project's lint policy (`select = ["E","F","W"]`, `ignore = ["E402","E501"]` since `sys.path.insert(...)` is structural and Black already owns line-length).


## v1.0.0 — 2026-04-30

### Added
- Atlas — unified ontology + KB canvas with 4 agent tools (`atlas_describe`, `atlas_query`, `atlas_traverse`, `atlas_search_grounded`); 5 starter ontologies; semantic / circle / grid layouts; visual query; ghost-cursor suggestions; time-slider snapshots; JSON-LD export.
- BPM Analyzer — multimodal end-to-end (PDF / image / audio / video / DOCX / text), provider-native JSON modes, beautifully formatted PDF download.
- Visual user guide at `/help` — categorised sidebar TOC, every feature covered with a screenshot, dedicated sections on Atlas / NATS scaling / RUNTIME_MODE / multi-tenancy.
- Versioned public-publish flow with `RELEASE_NOTES_PENDING.md` accumulator + `CHANGELOG.md` archive.
- Self-healing pipelines — failed nodes are auto-diagnosed and retried with a corrected input/config; a single Pipeline Operations category in `/help` documents the contract; user-visible "Auto-fix applied" entries in `/executions`.
- Workflow shell — typed verb grammar (`run`, `inspect`, `retry`, `branch`, `gate`) and a REPL UI inside the pipeline detail view; chat with a pipeline like a programmable surface, with full execution history and tool-call traces.
- Per-agent dedicated pod scaling — four pools (`default`, `chat`, `heavy-reasoning`, `long-running`), KEDA queue-depth-based autoscaling per pool, admin UI at `/admin/scaling` with cost projection and live replica counts.

### Changed
- Settings → Security: removed unimplemented 2FA tile; rebuilt activity log with per-action icons + summaries; loopback IPs render as "internal".
- README: differentiator-led structure, mermaid diagrams (architecture · NATS scaling · pipeline showcase), 11-row enterprise-ready matrix.
- Sidebar: deduplicated Moderation / Alerts / All-Executions entries; reframed SDK Playground TS-disabled tooltip.
- Agent runtime: per-pool isolation so a runaway long-running job no longer starves the chat pool.

### Fixed
- BPM Analyzer agent-spec parser — robust to JS-style comments, smart quotes, fenced JSON, trailing commas; auto-retries with provider-native JSON mode on the user's chosen model (no hardcoded fallback).
- Multi-tenancy story documented end-to-end (auto-on-signup; team invites; per-user quotas; per-feature flags; ResourceShare; actAs delegation).
- ClaimsIQ runtime: Vaadin defaults to production mode at startup so the Spring Boot fat-JAR no longer scans for a Maven/Gradle project directory.
- Pipeline engine: 7 multi-agent traps closed (type:agent DSL, auto-deps from templates, agent_step `{response}` unwrap, fenced-JSON + trailing-prose parsing, targeted input fallback, db_url wiring, inline path returning final_output).
