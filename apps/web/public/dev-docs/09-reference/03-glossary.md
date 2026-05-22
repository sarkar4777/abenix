# Glossary

> Quick lookup for the terminology used across the codebase + docs.

---

**actAs** — The delegated-subject pattern. A service-account API key calls the platform with an `X-Abenix-Subject: <type>:<id>` header so RBAC + audit attribute the action to the named end-user. See [`01-architecture/01-tenants-rbac`](../01-architecture/01-tenants-rbac.md).

**Agent** — A definition of an LLM + tools + system prompt that can be executed. Stored in the `agents` table. The runtime executes one agent per top-level call. Mode can be `agent` (single LLM loop) or `pipeline` (DAG of multiple steps).

**agent-runtime** — The service that runs agents. Four pools — `default`, `chat`, `heavy-reasoning`, `long-running`. Each is a separate Kubernetes Deployment scaled by KEDA on NATS queue depth.

**Approval gate** — A tool call (or pipeline node) that pauses an execution until one or more humans sign off. The runtime persists the loop state to Postgres and exits the pod. On signoff, a fresh pod resumes from the saved state.

**Atlas** — The knowledge graph. A typed entity + relationship store backed by Neo4j. Optional. Used by the `/atlas` page + the Cognify pipeline.

**BLPG** — Baltic LPG freight index. Three routes — BLPG1 (Ras Tanura → Chiba), BLPG2 (Houston → Flushing), BLPG3 (Houston → Chiba via Panama). The `freight_baltic_blpg` tool returns curated mids + low/high range.

**Cache (vertical-app)** — File-backed result store at `/data/<app>-cache/<page>/<key>.json`. TTL 30 min by default. Holds only agent-produced numbers — never synthesised.

**Cognify** — The KB ingestion pipeline. Parse → chunk → embed → extract entities + relationships → write to Neo4j. Runs in the `cognify-worker` pod.

**Code asset** — A user-uploaded zip or git repo, analysed and exposed as a `code_asset` tool. The runtime invokes it in a sandboxed container (gVisor on AKS).

**Corridor** — A pair (origin port, destination port) for a commodity. Wingman's primary unit of analysis. Four active corridors: USGC-NWE, USGC-FE, MEG-FE, USGC-LATAM.

**Execution** — One run of an agent or pipeline. The `executions` table is the source of truth for any run. Has a stable `execution_id` that flows through every log line, metric, and event.

**Failure code** — Stable string identifying *why* an execution ended in failure. Examples: `iteration_cap`, `output_schema`, `tool_timeout`, `runtime_died_or_timeout`, `LLM_RATE_LIMIT`.

**Fair value** — In Wingman, the `wingman-mispricing-fairvalue` BayesianRidge model's prediction of where a corridor's spread should sit given the 15-feature vector. Compared to the observed spread to compute residual + verdict.

**Hypertable** — TimescaleDB's auto-partitioned time-series table. `executions` is one — partitioned by `created_at` so older rows can be compressed and moved.

**JetStream** — NATS' persistent-stream extension. Provides at-least-once delivery + replay. The platform uses it for execution events + KEDA scaling.

**KEDA** — Kubernetes Event-Driven Autoscaler. Watches external metrics (NATS depth, Redis queue, Prom queries, etc.) and scales Deployments. The platform uses it on every agent-runtime pool + the worker.

**Knowledge Base (KB)** — A collection of documents that an agent can search via the `kb_search` tool. Documents are chunked, embedded, and stored with pgvector. Optionally Cognified into the Atlas graph.

**Mispricing** — Wingman's term for a corridor spread that's significantly off the fair-value model's prediction. Threshold: residual z-score > 2σ = `dislocated`, 1σ < |z| < 2σ = `stretched`, |z| < 1σ = `aligned`.

**MCP** — Model Context Protocol. The Anthropic-led spec for how LLMs talk to external tool servers. Abenix is an MCP client. See [`02-runtime/03-mcp`](../02-runtime/03-mcp.md).

**Observed spread** — The actual measured spread on a corridor today. Computed as `dest_spot - origin_spot - freight_per_mt`. The arb residual a trader actually books.

**Output schema** — Optional JSONSchema on `model_config.output_schema`. The runtime validates the final LLM reply against it. On mismatch the runtime retries once with feedback. After one retry it gives up and writes `failure_code='output_schema'` with the raw text in `output.raw`.

**Pipeline** — A DAG of nodes. Agents, tools, switches, for-each loops, parallel fan-out, human gates. Defined in `model_config.pipeline_config` as JSONB. Executed by the pipeline engine in the agent-runtime.

**Pool** — One of the four agent-runtime Deployments. Each pool isolates a class of workload. An agent picks its pool via `model_config.runtime_pool`. See [`06-deployment/03-keda`](../06-deployment/03-keda.md).

**ResourceShare** — The polymorphic sharing table. One row per `(resource_type, resource_id, recipient_user_id)`. Six resource types, three permission levels. See [`04-data-model/04-resource-shares`](../04-data-model/04-resource-shares.md).

**Runtime pool** — See **Pool**.

**Sandbox** — The isolated container that `code_executor` and `code_asset` tools run inside. Uses gVisor (`runsc`) on AKS. No network egress unless explicitly allowed. Ephemeral overlay FS. OOM-killed at 512MB. Default 30s timeout.

**SDK** — The Python / TypeScript / Java client libraries. Wrap the REST + SSE surface. See [`03-sdk/00-overview`](../03-sdk/00-overview.md).

**SSE** — Server-Sent Events. The streaming format the platform uses to push execution events to browsers. One-way, text-based, reconnect-friendly. Connection at `/api/executions/{id}/events`.

**Standalone app** — A vertical app (Wingman, ContractIQ, etc.) that rides on top of the platform via the SDK. Owns UI + auth + caching but no business logic. See [`07-standalone-apps/00-pattern`](../07-standalone-apps/00-pattern.md).

**Subject** — Per actAs. The `(subject_type, subject_id)` tuple recorded on `executions.subject` and on every audit row. Tells RBAC + audit who the action was on behalf of.

**Tenant** — An organisation on the platform. Identified by a UUID. Every table that holds user data has a `tenant_id` column. Tenants are isolated from each other.

**Tool** — The unit of action an agent can take. Registered in the `ToolRegistry` at runtime startup. Implements the `BaseTool` interface. See [`02-runtime/02-tools`](../02-runtime/02-tools.md).

**Tool config** — Per-agent overrides on a tool. Fields: `usage_instructions`, `parameter_defaults`, `max_calls`, `require_approval`. Stored on `agents.model_config_.tool_config[tool_slug]`.

**Trace** — In the OpenTelemetry sense. A tree of spans, one per logical operation, joined by a `trace_id`. Spans are emitted to Tempo. The execution detail page deep-links into Tempo Explore.

**Verdict** — Wingman's classification of a corridor's spread. `aligned` / `stretched` / `dislocated` based on the residual z-score against the fair-value posterior std.

**Worker** — The `worker` pod runs background Celery jobs. Pipeline orchestration for long pipelines, scheduled triggers, the execution-reconcile sweeper, webhook delivery retries.

---

## See also

- [00-rest-api](00-rest-api.md) — REST surface
- [01-env-vars](01-env-vars.md) — environment variables
