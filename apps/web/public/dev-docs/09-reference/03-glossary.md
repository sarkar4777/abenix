# Glossary

> Quick lookup for the terminology used across the codebase + docs.

---

**actAs** — The delegated-subject pattern. A service-account API key calls the platform with an `X-Abenix-Subject: <type>:<id>` header so RBAC + audit attribute the action to the named end-user. See [`01-architecture/01-tenants-rbac`](../01-architecture/01-tenants-rbac.md).

**Action type** — A kind of consequential action an agent can earn autonomy on, a row in `action_types`. A tool name plus an optional argument match, with its world model, outcome probe, limits decision and ladder policy. Every call is recorded in the `agent_actions` ledger. See [`02-runtime/21-earned-autonomy`](../02-runtime/21-earned-autonomy.md).

**Agent** — A definition of an LLM + tools + system prompt that can be executed. Stored in the `agents` table. The runtime executes one agent per top-level call. `model_config.mode` is `agent` (single LLM loop) or `pipeline` (DAG of multiple steps).

**agent-runtime** — The service that runs agents. Pools are listed under `scaling.pools` in the Helm values. `values-azure.yaml` ships `default`, `chat`, `heavy-reasoning` and `long-running`, each a separate Deployment scaled by KEDA on NATS queue depth. The base chart ships no pools.

**Approval gate** — A point where work waits for people. The `human_approval` tool parks a run on Redis and polls for the decision. Multi-sign-off gates, tier-driven tool approvals and decision publish gates are rows in `approvals`. See [`02-runtime/05-approvals-hitl`](../02-runtime/05-approvals-hitl.md).

**As-of / as-known** — The two times a decision evaluation can be pinned to. `as_of` picks the version whose effective dates cover that date. `known_at` evaluates as the platform knew things at that moment, ignoring versions published later and `valid_to` changes recorded later.

**Assertion** — One check on an eval case's run, stored in `eval_cases.assertions`. Types are `json_path_equals`, `json_path_contains`, `regex`, `contains`, `not_contains`, `schema_valid`, `required_tools_called`, `max_cost`, `max_duration_ms`, `cited_sources_present` and the LLM-scored `judge`.

**Atlas** — The knowledge graph canvas. Typed nodes and edges in `atlas_graphs` / `atlas_nodes` / `atlas_edges`, with Neo4j for traversal. Optional. Used by the `/atlas` page + the Cognify pipeline.

**Atlas as-of** — The `atlas_as_of` tool. Shows an Atlas graph as it stood at a past moment, from the newest row in `atlas_snapshots` saved at or before that time, or the live graph when nothing changed since.

**At-least-once delivery** — How queued agent runs reach the runtime pools. A message is acked only after the run ends, so a run cut off by a pod crash is delivered again and rerun from the start. Tool side effects can repeat. See **Queue lease**.

**Audit chain** — The per-tenant hash chain over `activity_logs`. Each row's `row_hash` covers the previous row's hash plus the row's content, so editing or removing a row breaks verification. A database trigger keeps the table append-only. See [`04-data-model/05-governance-decisions`](../04-data-model/05-governance-decisions.md#audit-chain-on-activity_logs).

**BUDGET_EXCEEDED** — The failure code and HTTP 429 error code for a run refused because the agent is over `daily_cost_limit` (its spend across all callers per UTC day) or `daily_budget_usd` (one tenant's spend on it per UTC day).

**BLPG** — Baltic LPG freight index. Three routes — BLPG1 (Ras Tanura → Chiba), BLPG2 (Houston → Flushing), BLPG3 (Houston → Chiba via Panama). The `freight_baltic_blpg` tool returns curated mids + low/high range.

**Cache (vertical-app)** — File-backed result store at `/data/<app>-cache/<page>/<key>.json`. TTL 30 min by default. Holds only agent-produced numbers — never synthesised.

**Capability** — A fine-grained permission key such as `decisions.publish` or `approvals.sign:legal`. A user holds their role's defaults plus every key in their permission sets. Routes check them with `require_capability`.

**Check / propose / publish** — The decision lifecycle calls. Check validates a draft without saving. Propose runs validation and golden tests, then moves the version to `proposed` and opens a publish approval when the tier needs approvers. Publish makes an `approved` version effective and supersedes or closes the overlapping live versions.

**Cognify** — The KB ingestion pipeline. Parse → chunk → embed → extract entities + relationships → write to Neo4j. Runs in the `cognify-worker` pod.

**Code asset** — A user-uploaded zip or git repo, analysed and exposed as a `code_asset` tool. Runs in a container, a one-off Job or a warm runner, with gVisor when the nodes have it. Each upload bumps `code_assets.version` and keeps the previous archive in `version_history`.

**Config fields** — The values a tool needs, declared on the tool class as `config_fields` (`ConfigField`: key, kind, required, group, signup URL). The Admin → Tool Configuration screen is generated from them, and `scripts/check-tool-config.py` checks that every key a tool reads is declared.

**Config hash** — SHA-256 of an agent's system prompt and `model_config`. Stamped on every run in `executions.provenance.config_hash` and on every eval run, and the key of `execution_config_snapshots`.

**Corridor** — A pair (origin port, destination port) for a commodity. Wingman's primary unit of analysis. Four active corridors: USGC-NWE, USGC-FE, MEG-FE, USGC-LATAM.

**Document grant** — A row in `document_grants` naming a user or agent who may read one document. A document with no grants is open to everyone who can read its collection. The first grant restricts it to its grantees, tenant admins, the collection creator and WRITE or ADMIN holders on the collection.

**Decision** — A named set of versioned business rules, a row in `decision_models`, evaluated by the ZEN engine from the API or the `decision_*` tools in an agent or pipeline. Callers address it by `key`.

**Decision version** — One immutable revision of a decision's rules in `decision_versions`. Carries effective dates (`valid_from` / `valid_to`), recorded times (`recorded_at`, `published_at`, `superseded_at`) and a state from `draft` through `published` to `superseded` or `retired`.

**Declared inputs** — An agent or pipeline's `model_config.input_variables`. Each has a name and an optional default that is applied under whatever the caller sends, and the pipeline validator treats the names as valid template targets.

**Earned autonomy** — Agents move between five levels per action type (Off, Watching, Asks first, Acts within limits, Acts and reports) on their scored record. Promotion needs a person who did not build the agent, demotion is automatic. See [`02-runtime/21-earned-autonomy`](../02-runtime/21-earned-autonomy.md).

**Effect** — What a tool call changes in the world, declared on the tool class as `effect = Effect(kind, label, ...)` or per call with `effect_for`. `READ_ONLY` for tools that only read. Required at medium tier and above.

**Embedding model** — The model a collection's chunks are embedded with, stored on `knowledge_collections.embedding_model` and used by ingest and search. Changed by the re-embed job, which re-reads every document and switches the collection in one step.

**Escalation** — A notification to tenant admins when a tiered approval has waited longer than the tier's `escalate_after_hours`. Sent once per approval and recorded in `approvals.escalated_at`.

**Eval case** — One input plus context and assertions inside a suite, a row in `eval_cases`. Can be captured from a real run, which fills `source_execution_id` and `reference_output`.

**Eval gate** — The publish check behind a tier policy's `require_eval_pass`. Publishing is refused with `EVAL_GATE` unless every gating suite on the agent has a completed run on the current config hash that met its threshold.

**Eval suite** — A set of eval cases scored against one agent or pipeline, a row in `eval_suites`. Has a pass threshold, an optional cron schedule, and a `gating` flag that makes it count for the eval gate.

**Event subscription** — A row in `webhooks`. Matches event types by glob and payload fields by `filter`, then delivers to a URL, or starts an agent or pipeline run.

**Execution** — One run of an agent or pipeline. The `executions` table is the source of truth for any run. Has a stable `execution_id` that flows through every log line, metric, and event.

**Failure code** — Stable string identifying *why* an execution ended in failure, stored in `executions.failure_code`. Examples: `LLM_RATE_LIMIT`, `MODERATION_BLOCKED`, `KILL_SWITCH`, `MODEL_NOT_ALLOWED`, `SANDBOX_TIMEOUT`, `STALE_SWEEP`, `TOOL_ERROR`. The mapping is in `apps/api/app/core/failure_codes.py`.

**Fair value** — In Wingman, the `wingman-mispricing-fairvalue` BayesianRidge model's prediction of where a corridor's spread should sit given the 15-feature vector. Compared to the observed spread to compute residual + verdict.

**Golden test** — A decision test in `decision_tests`. Fixed facts with the expected outcome and result. Every test runs on propose and a failure blocks the proposal.

**Hypertable** — TimescaleDB's auto-partitioned time-series table. The stack's TimescaleDB chart creates one, `metrics`, used by the `tsdb_query` tool and the pipeline `tsdb_sink`. `executions` is a plain Postgres table.

**JetStream** — NATS' persistent-stream extension. Provides at-least-once delivery + replay. The platform queues agent runs on it, one subject `agents.<pool>` per pool, and KEDA scales the pools on its consumer lag. Queued agent runs need it, Celery cannot carry them.

**KEDA** — Kubernetes Event-Driven Autoscaler. Watches external metrics (NATS depth, Redis queue, Prom queries, etc.) and scales Deployments. The platform uses it on the agent-runtime pools and the warm code runners when scaling is on.

**Kill switch** — A row in `kill_switches` that stops one kind of activity. Scope is `all`, `agent`, `pipeline`, `tool`, `model`, `trigger`, `decision` or `source`, target is one id or `*`. A NULL tenant stops it for every tenant. Runs it covers fail with `KILL_SWITCH`.

**Knowledge Base (KB)** — A collection of documents that an agent can search via the `knowledge_search` tool. Stored in `knowledge_collections`. Chunks are embedded into Pinecone or the pgvector `chunks` table, set per collection by `vector_backend`. An agent needs a grant in `agent_collection_grants`. Optionally Cognified into the Atlas graph.

**Mispricing** — Wingman's term for a corridor spread that's significantly off the fair-value model's prediction. Threshold: residual z-score > 2σ = `dislocated`, 1σ < |z| < 2σ = `stretched`, |z| < 1σ = `aligned`.

**MCP** — Model Context Protocol. The Anthropic-led spec for how LLMs talk to external tool servers. Abenix is an MCP client. See [`02-runtime/03-mcp`](../02-runtime/03-mcp.md).

**Observed spread** — The actual measured spread on a corridor today. Computed as `dest_spot - origin_spot - freight_per_mt`. The arb residual a trader actually books.

**Outbox** — The `event_outbox` table. Events are inserted in the same transaction as the change they describe, then a scheduler job fans them out to subscriptions, so an event exists exactly when its change does.

**Output schema** — Optional JSON Schema on `model_config.output_schema`. The post-processor validates and normalises the final output against it and records warnings. An agent run as a pipeline step is asked once to correct a mismatch. A tier policy with `require_output_schema` will not let the agent go live without one.

**Permission set** — A named bundle of capabilities in `permission_sets`, assigned to users through `permission_assignments`.

**Pipeline** — A DAG of nodes. Agents, tools, switches, for-each loops, parallel fan-out, human gates. Defined in `model_config.pipeline_config` as JSONB. Executed by the pipeline engine in the agent-runtime.

**Pool** — One of the agent-runtime Deployments. Each pool isolates a class of workload. An agent picks its pool with the `agents.runtime_pool` column, and `inline` keeps the run on the API pod. See [`06-deployment/03-keda`](../06-deployment/03-keda.md).

**Provenance** — What a run used, written by the `executions_provenance` trigger: `risk_tier`, `agent_revision`, `prompt_hash` and the `provenance` JSON (`config_hash`, agent version, model, temperature, tools). The prompt and config themselves go to `execution_config_snapshots` so a run can be replayed pinned.

**Provider credentials** — The LLM provider keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` and others) declared in `engine/provider_credentials.py`. They resolve like any tool credential, so a key saved under Admin → Tool Configuration reaches the router without a restart.

**Reference set** — A named, versioned list of values in `reference_sets`, such as product codes. Decision rules can test membership. The values are compiled into a decision version, and `reference_versions` records which set version was used.

**Queue lease** — The claim a runtime pod holds on a queued execution: `runner_id`, `lease_expires_at` and `delivery_attempts` on the `executions` row. Renewed while the run lives. A duplicate delivery waits while the lease is live and takes over once it expires. After `CONSUMER_MAX_ATTEMPTS` (3) pickups the run fails with `STALE_SWEEP`.

**Reranker** — The step that reorders search hits by relevance. Cohere runs when `COHERE_API_KEY` is set, the Claude Haiku scorer only with `RERANKER_PROVIDER=llm`.

**ResourceShare** — The polymorphic sharing table. One row per `(resource_type, resource_id, recipient_user_id)`. Seven resource types, three permission levels. See [`04-data-model/04-resource-shares`](../04-data-model/04-resource-shares.md).

**Return (approval)** — A sign-off with decision `return`. Sets the approval to `returned` and sends a decision version back to `draft` with the reviewer's note, instead of rejecting it.

**Risk tier** — `low`, `medium`, `high` or `critical`. Set on agents (`model_config.risk_tier`), decisions, tools and watch sources. A run starts at its agent's tier and can only rise, recorded in `executions.risk_tier` and `risk_reasons`.

**Runtime pool** — See **Pool**.

**Sandbox** — The isolation for user code. `code_executor` runs Python in-process after an AST and module check, with no network or system modules and a 30 second limit. `code_asset` runs in a container, under gVisor (`runsc`) when the cluster sets `codeRunners.runtimeClassName`.

**SDK** — The Python / TypeScript / Java client libraries. Wrap the REST + SSE surface. See [`03-sdk/00-overview`](../03-sdk/00-overview.md).

**Source change** — A row in `source_changes`. The diff between two snapshots of a watched source, with stats and a `materiality_hint` of high, medium or low.

**Source snapshot** — A row in `source_snapshots`. The raw bytes (in object storage), hashes, HTTP metadata and normalised text of one fetch. Immutable, a database trigger refuses updates.

**SSE** — Server-Sent Events. The streaming format the platform uses to push execution events to browsers. One-way, text-based, reconnect-friendly. Per run at `/api/executions/{id}/stream`, all live runs at `/api/executions/live/stream`.

**Standalone app** — A vertical app (Wingman, E&C-Copilot, etc.) that rides on top of the platform via the SDK. Owns UI + auth + caching but no business logic. See [`07-standalone-apps/00-pattern`](../07-standalone-apps/00-pattern.md).

**Subject** — Per actAs. The `(subject_type, subject_id)` pair recorded on `executions` and on audit rows. Tells RBAC + audit who the action was on behalf of.

**Tenant** — An organisation on the platform. Identified by a UUID. Every table that holds user data has a `tenant_id` column. Tenants are isolated from each other.

**Tier policy** — What a tenant requires of work at one risk tier: publish approvers and their rules, `tool_call_action` (`allow`, `approval`, `block`), allowed models, output schema, eval pass. Defaults live in `engine/risk.py`, overrides in `risk_policies`.

**Tool** — The unit of action an agent can take. Registered in the `ToolRegistry` at runtime startup. Implements the `BaseTool` interface. See [`02-runtime/02-tools`](../02-runtime/02-tools.md).

**Tool config** — Per-agent overrides on a tool. Fields: `usage_instructions`, `parameter_defaults`, `max_calls`, `require_approval`. Stored on `agents.model_config_.tool_config[tool_slug]`. Not the same as tool configuration.

**Tool configuration** — Platform and tenant values a tool needs, such as API keys, set under Admin → Tool Configuration. Resolved in order: tenant row in `tenant_tool_credentials`, platform row `tool.credential.<KEY>` in `platform_settings`, environment, seed defaults, the tool's declared default. See [`08-howto/08-tool-configuration`](../08-howto/08-tool-configuration.md).

**Trace** — In the OpenTelemetry sense. A tree of spans, one per logical operation, joined by a `trace_id`. Spans are emitted to Tempo. The W3C `traceparent` travels from the API through the NATS message to the runtime and on to child agent runs, so one trace covers a whole run. The execution detail page deep-links into Tempo Explore.

**Trace hash** — SHA-256 over the canonical JSON of a decision evaluation's facts, rules content hash, result and applied rules. Stored in `decision_evaluations.trace_hash`. Equal hashes mean the same decision for the same reason.

**Verdict** — Wingman's classification of a corridor's spread. `aligned` / `stretched` / `dislocated` based on the residual z-score against the fair-value posterior std.

**Warm runner** — A long-lived code runner Deployment per tenant and code asset version, called over NATS instead of starting a Job per call. Scales down after `codeRunners.idleSeconds` without calls, to a floor set per risk tier by `codeRunners.minWarmByTier`. See [`02-runtime/16-warm-code-runners`](../02-runtime/16-warm-code-runners.md).

**Watch source** — A row in `watch_sources`. A URL the tenant monitors on a cadence, with an optional selector, credentials key and collection to feed. Each fetch that differs creates a snapshot and a source change.

**Worker** — The `worker` pod runs Celery tasks: Cognify, document processing, KB re-embedding and Pinecone vacuum. Queued agent runs go to the runtime pools over NATS, not to the worker. Scheduled jobs such as triggers, the stale sweeper, event delivery, Source Watch checks, eval schedules and the audit chainer run in the API's APScheduler instead.

---

## See also

- [00-rest-api](00-rest-api.md) — REST surface
- [01-env-vars](01-env-vars.md) — environment variables
- [04-data-model/00-overview](../04-data-model/00-overview.md) — every table
