# Environment variables reference

> Environment variables are deploy-time and need a pod restart. Knobs an admin
> can change at runtime from the UI live in
> [04-platform-settings](04-platform-settings.md) instead.

Every variable below is read somewhere in `apps/api`, `apps/agent-runtime`,
`apps/worker`, `apps/code-runner`, `apps/web`, `packages/` or the images under
`docker/`. Defaults are the ones in code. "Chart" is what
`infra/helm/abenix/templates/configmap.yaml` and `secrets.yaml` put in
`abenix-config` and `abenix-secrets`, which every core pod loads with `envFrom`.
A chart value wins over the code default.

---

## Shared by the Python services

| Variable | Default | Read by | Notes |
|---|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://abenix:abenix@localhost:5432/abenix` (API) | api, agent-runtime, worker, seeds | Chart from `secrets.databaseUrl`. `postgresql://` URLs are rewritten to `+asyncpg` where an async engine needs it |
| `DATABASE_URL_ASYNC` | none | agent-runtime consumer, decision and source engines | Fallback when `DATABASE_URL` is unset |
| `DATABASE_URL_SYNC` | none | `packages/db/bootstrap.py` | Fallback when `DATABASE_URL` is unset |
| `ASYNC_DATABASE_URL` | none | `knowledge_search`, hybrid search | Fallback when `DATABASE_URL` is unset |
| `REDIS_URL` | `redis://localhost:6379/0` | api, agent-runtime, worker | Chart builds it from the release name and `secrets.redisPassword` |
| `QUEUE_BACKEND` | `celery` | api, agent-runtime consumer | `celery` or `nats`. Queued agent runs need `nats`. A runtime pool pod exits at startup with anything else. Chart from `scaling.queueBackend` |
| `NATS_URL` | `nats://abenix-nats:4222` (runtime), empty (API) | api event bus, agent-runtime queue, code runner gateway | Chart sets it only when `scaling.queueBackend` is `nats`. Empty on the API means events are not published to the bus |
| `NATS_USER` | `abenix` (queue), none elsewhere | api, agent-runtime, code runner gateway | Chart sets `abenix` with the NATS backend |
| `NATS_PASSWORD` | none | api, agent-runtime, code runner gateway, NATS pod | Chart generates a 32 character value on first install and keeps it on upgrade. `secrets.natsPassword` overrides it |
| `NATS_SYS_PASSWORD` | none | NATS pod config only | Generated and kept the same way. `secrets.natsSysPassword` overrides it |
| `LOG_LEVEL` | `INFO` | api, agent-runtime, code runner | Chart from `logLevel`, default `info` |
| `DEBUG` | `false` | api | `true` allows the default `SECRET_KEY`, mints throwaway JWT keys in process, logs as console text instead of JSON, and allows dev edge keys when `ENVIRONMENT` is unset. Chart sets `false` only when `environment` is `production` |
| `ENVIRONMENT` | empty | api, agent-runtime tracing | `local`, `dev` or `development` raises the rate limits. `dev`, `development`, `local`, `test` or `testing` lets the API mint a dev edge signing key. Also the Sentry environment and the trace `deployment.environment`. Chart from `environment`, default `production` |
| `PGSSLMODE` | unset | api | `disable` turns asyncpg SSL off. Anything else tries SSL without verifying the certificate. Chart sets `disable` |
| `DB_IDLE_TXN_TIMEOUT_MS` | `300000` | api, agent-runtime consumer, decision and source engines | Postgres `idle_in_transaction_session_timeout` for each connection |
| `ABENIX_DATA_KEY_KEK_BASE64` | none | api, agent-runtime | 32 bytes, base64. Encrypts tool credentials saved from Admin -> Tool Configuration, tenant Slack webhooks, approval webhook secrets and MCP connection secrets with AES-256-GCM. Unset means those values are stored as entered, with no log line. A value that is not 32 bytes logs `invalid ABENIX_DATA_KEY_KEK_BASE64` and also stores plaintext. Chart from `secrets.dataKeyKekBase64`. Setup: [06-encryption-setup](../08-howto/06-encryption-setup.md) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | none | api, agent-runtime | OTLP gRPC endpoint. Unset means no trace export. The runtime pool Deployments set `http://<release>-tempo.<ns>.svc.cluster.local:4317` |
| `OTEL_TEMPO_ENDPOINT` | none | api, agent-runtime | Fallback for the endpoint above |
| `OTEL_SERVICE_NAME` | `abenix-api` or `agent-runtime-<pool>` | api, agent-runtime | Trace `service.name` |
| `OTEL_TRACES_SAMPLER_ARG` | `0.1` | api, agent-runtime | Parent-based ratio sampler. The pool Deployments set `1.0` |
| `BUILD_VERSION` | `dev` | api, agent-runtime | Trace `service.version` |

Trace attributes holding prompts, tool arguments and outputs are always replaced
with `<redacted len=N sha256=...>` before export. There is no switch for it.

The Python SDK under `packages/sdk/python` and `packages/agent-sdk` reads the
same `OTEL_*` and `BUILD_VERSION` variables in the apps that embed it, and sets
`OTEL_PYTHON_FASTAPI_EXCLUDED_URLS` to `client/.*,server/.*,health,api/health`
when it is unset.

---

## abenix-api

### Settings class

`apps/api/app/core/config.py` reads these through pydantic, case-insensitive,
also from a `.env` at the repo root when one exists.

| Variable | Default | Notes |
|---|---|---|
| `APP_NAME` | `Abenix API` | |
| `SECRET_KEY` | `change-me-in-production` | The API refuses to start with the default unless `DEBUG=true`. The agent-runtime also signs HS* tokens with it. Chart from `secrets.jwtSecret` |
| `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` | empty | RSA PEM pair for access tokens. Required unless `DEBUG=true`. `deploy-azure.sh` generates a pair into `abenix-secrets` when missing |
| `JWT_ALGORITHM` | `RS256` | Also read by the agent-runtime when it mints short-lived tokens |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | JSON list. A `*` entry logs a warning. Chart from `corsOrigins` |
| `FRONTEND_URL` | `http://localhost:3000` | Base for links in notifications and invites. Chart from `frontendUrl` |
| `OTEL_ENABLED` / `OTEL_EXPORTER` / `OTEL_ENDPOINT` | `false` / `stdout` / `http://localhost:4317` | FastAPI auto-instrumentation in `app/core/telemetry.py` |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` | empty | A warning logs when all three are empty |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` / `STRIPE_CONNECT_CLIENT_ID` | empty | Billing |
| `MARKETPLACE_ENABLED` | `true` | Default for the marketplace switch. An admin value on Admin, Marketplace & Billing wins. Chart from `features.marketplace` |
| `MONETIZATION_ENABLED` | `false` | Default for the monetization switch. An admin value wins. Chart from `features.monetization` |
| `STRIPE_PRO_PRICE_ID` / `STRIPE_BUSINESS_PRICE_ID` | empty | Stripe price ids for the Pro and Business plans, read in `app/core/stripe.py` |
| `SCALING_EXEC_REMOTE` | `false` | `true` queues executions whose agent pool is not `inline` instead of running them in the API. Chart from `scaling.execRemote` |
| `QUEUE_BACKEND` | `celery` | See above |

### Process and HTTP

| Variable | Default | Notes |
|---|---|---|
| `API_WORKERS` | `2` | uvicorn worker processes. Read in the `CMD` of `docker/Dockerfile.api` |
| `API_KEEPALIVE_SECONDS` | `75` | uvicorn `--timeout-keep-alive`. Keep it above the idle timeout of whatever sits in front of the API |
| `PROMETHEUS_MULTIPROC_DIR` | `/tmp/prom-multiproc` in the cluster image | When it names a directory, `/api/metrics` sums every uvicorn worker. `docker/Dockerfile.api` sets it and empties the directory on each start |
| `DEPENDENCY_PROBE_INTERVAL_SECONDS` | `30` | How often each API pod probes Postgres and Redis for `abenix_health_check`. Floor 5 |
| `DB_POOL_SIZE` | `10` | Per uvicorn worker |
| `DB_MAX_OVERFLOW` | `5` | Per uvicorn worker |
| `DB_POOL_TIMEOUT` | `20` | Seconds a request waits for a connection |
| `SQL_ECHO` | off | `1`, `true` or `yes` logs every statement |
| `IP_WHITELIST` | empty | Comma-separated IPs or CIDRs. Empty allows every client |
| `IS_LOCAL_DEV` | off | `1`, `true` or `yes` bypasses the rate limiter and raises its defaults to 5000 a minute |
| `RATE_LIMIT_USER_REQ_PER_MIN` | `300` | Authenticated requests per user per window |
| `RATE_LIMIT_ANON_REQ_PER_MIN` | `60` | Unauthenticated requests per IP per window |
| `RATE_LIMIT_AUTH_REQ_PER_MIN` | `30` | Requests to the auth endpoints per IP per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | |
| `RATE_LIMIT_BYPASS_TOKEN` | empty | A request whose `X-RateLimit-Bypass` header equals this skips the limiter |
| `SENTRY_DSN` | empty | Turns Sentry on |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | |
| `IMAGE_TAG` | `dev` | Sentry release |
| `ALLOW_DEV_CREATE_MEMBER` | `false` | `true` enables the admin-only synchronous member create endpoint |
| `KUBERNETES_NAMESPACE` | the pod's own namespace, else `abenix` | Namespace the cluster page reads |
| `HELM_RELEASE` | `abenix`, set by the chart | Release prefix the cluster page strips from service names |
| `CLUSTER_VIEW_RBAC` | `true`, set by the chart from `clusterView.rbac.enabled` | Lets the cluster page name the helm value when a read is refused |
| `GRAFANA_URL` | empty | Grafana link the cluster page returns |

Request bodies are capped at 10 MB and uploads at 50 MB in
`app/core/middleware.py`. Those are constants, not variables.

### Sign-in

| Variable | Default | Notes |
|---|---|---|
| `GOOGLE_OIDC_CLIENT_ID` / `GOOGLE_OIDC_CLIENT_SECRET` | none | Google sign-in. Both needed |
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | none | GitHub sign-in |
| `MICROSOFT_OIDC_CLIENT_ID` / `MICROSOFT_OIDC_CLIENT_SECRET` / `MICROSOFT_OIDC_TENANT` | none | Microsoft sign-in |
| `PUBLIC_API_BASE_URL` | `http://localhost:8000` | Base of the OIDC callback URL |
| `WEB_BASE_URL` | `http://localhost:3000` | Where the browser lands after sign-in. Also used for invite links |
| `JWT_SECRET_KEY` | `dev-secret-do-not-use-in-prod` | Signs the OIDC `state` parameter. Set it in production |

Details in [05-sso](05-sso.md).

### Storage and files

| Variable | Default | Notes |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `local`, `s3` or `azure`. Also read by agent-runtime. With `s3` or `azure`, uploads, model files and code assets are mirrored to object storage. Chart from `objectStorage.type` |
| `STORAGE_S3_BUCKET` | `S3_BUCKET`, else `abenix-files` | Chart from `objectStorage.bucket` |
| `STORAGE_S3_REGION` | `AWS_REGION`, else `us-east-1` | |
| `STORAGE_S3_ENDPOINT` | empty | For S3-compatible stores |
| `STORAGE_S3_ACCESS_KEY` / `STORAGE_S3_SECRET_KEY` | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Chart from `secrets.storageS3*` |
| `STORAGE_AZURE_CONNECTION_STRING` | empty | Chart from `secrets.storageAzureConnectionString` |
| `STORAGE_AZURE_CONTAINER` | `abenix-files` | |
| `STORAGE_LOCAL_DIR` | `UPLOAD_DIR`, else `./data/uploads` | agent-runtime local store |
| `OBJECT_STORAGE_LOCAL_ROOT` | `/data` | Root of the local object store |
| `UPLOAD_DIR` | `./data/uploads` | Chart `/data/uploads` |
| `EXPORT_DIR` | `/tmp/abenix_exports` | Where exports land. Chart `/data/exports` |
| `ML_MODELS_DIR` | `/tmp/ml-models` | Chart `/data/ml-models` |
| `ML_MODEL_MAX_K8S_PER_TENANT` | `10` | Concurrent on-cluster model deployments per tenant |
| `ML_MODEL_SERVING_IMAGE` | `localhost:5000/abenix/model-serving:latest` | Image for model-serving pods. Chart from `mlModels.servingImage` |
| `ARCHIVE_ROOT` | `/data/archives` | Legacy archive layout, still read for old downloads |
| `ARCHIVE_LOCAL_ROOT` | parent of `ARCHIVE_ROOT` | Local object root for archive dumps |
| `ARCHIVE_MAX_ROWS_PER_RUN` | `200000` | Rows one archive run moves |
| `USE_CASE_CATALOG_PATH` | bundled `infra/use_cases_catalog.json` | Override for the use cases catalogue |
| `USE_CASE_URLS` | empty | JSON object of catalogue id to public URL. Invalid JSON is ignored with a warning |

### Code assets and sandboxes

| Variable | Default | Read by | Notes |
|---|---|---|---|
| `CODE_ASSET_STORE` | `/data/code-assets` | api, seeds | Where uploaded repos live |
| `CODE_ASSET_GIT_ALLOWED_HOSTS` | empty | api | Comma-separated host suffixes a git import may clone from. Empty allows any public host |
| `CODE_ASSET_MAX_VERSIONS` | `20` | api | Versions kept per asset |
| `SANDBOXED_JOB_ENABLED` | off in code, `true` in chart | api, agent-runtime | Turns the `sandboxed_job` tool on |
| `SANDBOXED_JOB_ALLOW_NETWORK` | off in code, `true` in chart | api, agent-runtime | |
| `SANDBOXED_JOB_ALLOWED_IMAGES` | empty in code, chart lists Python, Node, Go, Rust, Ruby and Temurin images | api, agent-runtime | Comma-separated allow-list |
| `SANDBOXED_JOB_NAMESPACE` | pod namespace | agent-runtime | Where Jobs and one-off runners are created |

Tenants can override the three `SANDBOXED_JOB_*` switches from
`PUT /api/settings/sandbox`. Those overrides live in Redis.

### Alerts and notifications

| Variable | Default | Notes |
|---|---|---|
| `PROMETHEUS_URL` | `http://abenix-prometheus.abenix.svc.cluster.local:9090` | Fallback source for `/api/admin/alerts` and the `/rules` proxy. Chart from `alerting.prometheusUrl` |
| `ALERTMANAGER_URL` | empty | Primary source for `/api/admin/alerts`. Chart sets `http://<release>-alertmanager.<ns>.svc.cluster.local:9093` when `alerting.alertmanager.enabled` |
| `ALERT_WEBHOOK_TOKEN` | empty | Bearer token Alertmanager presents on `POST /api/admin/alerts/webhook`. Unset means the webhook answers 503. Chart generates one and keeps it |
| `PLATFORM_ALERT_DEDUPE_MINUTES` | `30` | Same fingerprint is not re-notified inside this window. Chart from `alerting.dedupeMinutes` |
| `ABENIX_SLACK_WEBHOOK_URL` | empty | Operator Slack channel for platform alerts, in addition to per-tenant hooks |
| `SMTP_HOST` | empty | Outbound email for notifications. Empty disables email |
| `SMTP_PORT` | `587` | STARTTLS |
| `SMTP_USER` / `SMTP_PASS` | none | |
| `SMTP_FROM` | `no-reply@abenix.dev` | |
| `STALE_EXECUTION_MAX_MINUTES` | `10` | A run still `running` after this long is marked failed by the sweeper, which runs every 5 minutes. Runs with a live queue lease are skipped |
| `DRIFT_DETECTION_ENABLED` | `true` | Platform default for drift scoring. An agent's `model_config.drift_detection` and the tenant toggle win |
| `DRIFT_SCAN_INTERVAL_SECONDS` | `300` | Floor 30 |
| `DRIFT_SCAN_BATCH` | `500` | Executions scored per backlog pass |
| `DRIFT_RECORDED_TTL_SECONDS` | `86400` | How long an execution stays marked as scored |

The chart also writes `PLATFORM_ALERTS_ENABLED`, `DATABASE_HOST`,
`DATABASE_PORT` and `DATABASE_NAME` into `abenix-config`. No platform code reads
them.

### MCP servers

| Variable | Default | Notes |
|---|---|---|
| `MCP_ALLOWED_HOSTS` | empty in code, the UAT fixture host in the chart | Comma-separated host suffixes an MCP server may be registered from |

`POST /api/mcp/connections` checks the host of `server_url` before it connects,
and answers `400` with `host '<yours>' not in MCP_ALLOWED_HOSTS` when the host
is not listed. The chart sets the variable from `mcpAllowedHosts` in the Helm
values, and when that is empty it falls back to the UAT fixture host alone. So
a freshly deployed cluster will refuse every MCP server except that one until
you say otherwise.

Entries are matched as suffixes, so a host is allowed when it equals an entry
or ends with a dot plus that entry.

```yaml
# infra/helm/abenix/values-local.yaml
mcpAllowedHosts: "uat-mcp.abenix.svc.cluster.local,custom-mcp.abenix.svc.cluster.local"
```

Leaving the variable empty in production is the safer setting rather than an
oversight. The connector then falls through to a block-list that refuses
localhost, cluster-internal names and cloud metadata endpoints, which is what
stops a tenant pointing an MCP connection at your instance metadata.

### Outbound events

Read by abenix-api. Details in [outbound events](../02-runtime/19-outbound-events.md).

| Variable | Default | Notes |
|---|---|---|
| `EVENTS_ALLOWED_INTERNAL_HOSTS` | empty | Comma-separated host names a webhook may be saved with and call even though they are cluster-internal or resolve to private addresses. Exact match only, no suffixes, so a lookalike host cannot slip through. Chart from `eventsAllowedInternalHosts` |
| `EVENTS_ALLOW_PRIVATE_TARGETS` | empty | `1`, `true` or `yes` lets every webhook call private and loopback addresses. Local dev only |

### Connectors

Read by abenix-api and agent-runtime. Details in [connectors](../02-runtime/14-connectors-and-triggers.md).

| Variable | Default | Notes |
|---|---|---|
| `CONNECTORS_ALLOW_PRIVATE_TARGETS` | empty | `1`, `true` or `yes` lets connectors save and call private, loopback and cluster-internal addresses. For dev clusters that point a connector at an in-cluster service. Set it on both pods |

Events also go to NATS when `NATS_URL` is set, logging in with `NATS_USER` and
`NATS_PASSWORD`.

### Source Watch

Read by abenix-api unless noted. Details in [02-runtime/17-source-watch](../02-runtime/17-source-watch.md).

| Variable | Default | Notes |
|---|---|---|
| `SOURCE_WATCH_MAX_BYTES` | `26214400` (25 MB) | Largest response kept. Floor 1024 |
| `SOURCE_WATCH_TIMEOUT_SECONDS` | `30` | Fetch timeout |
| `SOURCE_WATCH_HOST_INTERVAL_SECONDS` | `2` | Minimum gap between fetches to one host |
| `SOURCE_WATCH_PAUSE_AFTER` | `5` | Default number of failures in a row before a source is paused. A tenant can set its own from 1 to 100 |
| `SOURCE_WATCH_CONCURRENCY` | `8` | Sources fetched at once |
| `SOURCE_WATCH_ALLOW_PRIVATE_TARGETS` | empty | `1`, `true` or `yes` allows private and loopback addresses. Local dev only |
| `SOURCE_WATCH_LOCAL_ROOT` | `OBJECT_STORAGE_LOCAL_ROOT` | Where snapshots go when object storage is the local disk |
| `SOURCE_DB_POOL` | `3` | Pool size of the database engine the source tools use in agent-runtime |
| `SOURCE_DB_OVERFLOW` | `3` | Extra connections past that pool size |

Credentials for a source are stored as tool credentials under the keys `SOURCE_AUTH_1` to `SOURCE_AUTH_5`, not as environment variables.

### Evaluation suites

Read by abenix-api. Details in [02-runtime/18-evaluation-suites](../02-runtime/18-evaluation-suites.md).

| Variable | Default | Notes |
|---|---|---|
| `EVAL_CASE_TIMEOUT_SECONDS` | `300` | Time one case may run. Held between 5 and 1800 |
| `EVAL_STALE_MINUTES` | `180` | A run still queued or running after this long is marked failed, most likely its API pod restarted |
| `EVAL_MAX_PARALLEL_CASES` | `8` | Cases running at once in one API process |

### Decisions

Read by the agent-runtime engine, which also runs inside the API.

| Variable | Default | Notes |
|---|---|---|
| `DECISION_DB_POOL` | `5` | Pool size of the decisions database engine |
| `DECISION_DB_OVERFLOW` | `5` | Extra connections past the pool size |
| `DECISION_CACHE_SIZE` | `512` | Compiled decisions kept in memory, least recently used dropped first |
| `DECISION_RESOLVE_TTL` | `30` | Seconds a resolved decision version is reused. A publish clears it sooner through the `abenix:decisions:changed` Redis channel |

Governance, approval escalation and tool configuration read no variables of
their own. They use the database, Redis and the settings tables.

### Meetings and persona

| Variable | Default | Notes |
|---|---|---|
| `LIVEKIT_URL` | empty | LiveKit server, also read by the `meeting_join` tool. Chart from `meeting.livekit.url`. The pool Deployments set `ws://<release>-livekit-server.<ns>.svc.cluster.local:7880` |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | empty | Without all three the join endpoint answers 400 |
| `LIVEKIT_PUBLIC_URL` | derived from `LIVEKIT_URL` | URL the browser uses. Dev host names are translated when unset |
| `LIVEKIT_MEET_URL` | empty in code, `https://meet.livekit.io` in chart | Builds the "join as human" link |
| `ELEVENLABS_API_KEY` | empty | Voice clone for persona |

### Embedded engine callbacks

The API process runs the agent engine in embedded mode, so a few calls go back
to the API over HTTP.

| Variable | Default | Notes |
|---|---|---|
| `ABENIX_PLATFORM_API_KEY` | empty | Platform key the conversation endpoints use with the SDK. `ABENIX_API_KEY` is the fallback. The BPM analyzer no longer needs it, its smoke test runs in process |
| `ABENIX_INTERNAL_URL` | `http://localhost:8000` | API base for those SDK calls |
| `PLAYGROUND_INTERNAL_API_URL` | `http://localhost:8000` | API base the SDK Playground runs snippets against |
| `CODE_ASSET_DOWNLOAD_TOKEN` | set by the API at run time | Bearer the `code_asset` tool sends when it downloads an archive. Not for operators |

---

## agent-runtime

Also read by the API in embedded mode, since it imports the same engine.

| Variable | Default | Notes |
|---|---|---|
| `RUNTIME_MODE` | `embedded` | `embedded` runs agents in the API process, `remote` hands them to the runtime. Chart from `runtimeMode`. The pool Deployments set `remote` |
| `RUNTIME_URL` | `http://abenix-agent-runtime:8001` | Runtime the API calls in remote mode. Chart sets it from the release name |
| `RUNTIME_TIMEOUT` | `300` | Seconds the API waits on a remote run |
| `RUNTIME_POOL` | `default` | Pool a consumer drains. Set per pool Deployment |
| `AGENT_CONCURRENCY` | `8` | Runs one consumer handles at once. Pool Deployments set it from `concurrency_per_replica`, default 3. `CONSUMER_MAX_CONCURRENCY` is the older name |
| `HEALTH_PORT` | `8001` | Consumer health and `/metrics` port |
| `CONSUMER_LEASE_SECONDS` | `25` | Length of a run's lease on its execution row. Renewed every third of that while the run lives. Floor 6 |
| `CONSUMER_MAX_ATTEMPTS` | `3` | Pickups of one run before it is failed with `STALE_SWEEP` instead of rerun |
| `CONSUMER_DB_POOL_SIZE` / `CONSUMER_DB_MAX_OVERFLOW` | `10` / `5` | Consumer database engine |
| `RUNTIME_DB_POOL_SIZE` / `RUNTIME_DB_MAX_OVERFLOW` | `5` / `5` | Shared engine tools use, one per event loop and URL |
| `PIPELINE_DB_POOL_SIZE` / `PIPELINE_DB_MAX_OVERFLOW` | `10` / `5` | Pipeline engine database pool |
| `PIPELINE_TIMEOUT_SECONDS` | `300` | Engine fallback when the `pipeline.timeout_seconds` setting cannot be read |
| `SANDBOX_TIMEOUT_SECONDS` | `300` | Engine fallback when the `sandbox.timeout_seconds` setting cannot be read |
| `TOOL_WORKER_ENABLED` | `1` | `1` starts the Redis-stream tool worker inside the consumer |
| `TOOL_WORKER_CONCURRENCY` | `10` | Tool calls that worker runs at once |
| `HOSTNAME` | set by Kubernetes | Consumer name of the tool worker in its Redis stream group. Also names the code runner NATS connection |
| `TOOL_RESULT_PERSIST_CHARS` | `8000` | Characters of each tool result kept on the execution row |
| `LLM_DEFAULT_PRICING_INPUT_PER_M` / `LLM_DEFAULT_PRICING_OUTPUT_PER_M` | `3.0` / `15.0` | Dollars per million tokens for a model with no price row |
| `PROGRESS_CHANNEL_PREFIX` | `progress:` | Redis channel prefix for live progress. Chart from `progress.channelPrefix` |
| `PROGRESS_PARENT_KEY_PREFIX` | `parent:` | Chart from `progress.parentKeyPrefix` |
| `PROGRESS_PARENT_TTL` | `1800` | Chart from `progress.parentTtl` |
| `PROGRESS_LEGACY_CHANNEL_PREFIX` | empty | Mirrors each publish onto an older prefix. Empty turns it off |
| `POST_PROCESSOR_MODULES` | empty | Comma-separated modules imported at start so they register output post-processors. Chart from `postProcessorModules` |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | empty | Langfuse tracing turns on when both keys are set |
| `ABENIX_LOCAL_EMBEDDINGS` | auto | `1` forces the built-in hashed embedder, `0` forbids it. Auto uses it when neither OpenAI nor Azure OpenAI is configured. Also read by the worker |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Also read by the worker |
| `AZURE_EMBEDDING_DEPLOYMENT` | the OpenAI model name | Azure deployment for embeddings. Chart from `azureEmbeddingDeployment` |
| `AZURE_OPENAI_ENDPOINT` | empty | Accepted beside `AZURE_OPENAI_API_BASE` for embeddings |
| `PINECONE_API_KEY` / `PINECONE_INDEX_NAME` | empty / `agentforge-knowledge` | Also read by the API and worker. Chart sets the index from `pinecone.indexName` |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` / `NEO4J_DATABASE` | `bolt://localhost:7687` / `neo4j` / `abenix` / `neo4j` | Also read by the API. Chart sets URI and database, password from `secrets.neo4jPassword` |

### Tool settings that are not credentials

| Variable | Default | Notes |
|---|---|---|
| `CODE_ASSET_BUILD_CACHE` | `/data/code-asset-cache` | Compiled artifact cache |
| `CODE_ASSET_CACHE_SECONDS` | `2` | How long `code_asset` reuses the asset row it read |
| `CODE_ASSET_DOWNLOAD_BASE_URL` | `http://abenix-api.abenix.svc.cluster.local:8000` | API base a one-off Job fetches archives from |
| `CODE_ASSET_MAX_INLINE_BYTES` | `400000` | Archives up to this size are passed inline instead of downloaded |
| `CODE_ASSET_SECRETS_KEY` | empty | Hex AES key that decrypts secrets stored for a code asset. Unset means stored secrets are skipped with a warning |
| `BLPG_CURATED_PATH` | `/data/blpg_curated.json` | Curated mids file for `freight_baltic_blpg` |
| `BROWSER_AUTOMATION_ALLOWED_HOSTS` | `*` | Hosts `browser_automation` may open |
| `SEARCH_PROVIDER` | `tavily` | Search order for `tavily_search`. Chart from `secrets.searchProvider` |
| `SENTIMENT_LEXICON_OVERRIDE_PATH` | empty | JSON lexicon merged into `sentiment_analyzer` |
| `TRAJECTORY_DIR` | `/data/trajectories` | Read by `recall_trajectory` |
| `DEFER_NOTIFY_WEBHOOK_URL` | empty | `defer_to_human` posts here. Chart from `meeting.deferNotifyWebhookUrl` |
| `OPENAI_TTS_VOICE` | `alloy` | `meeting_speak` voice. Chart from `meeting.ttsVoice` |
| `MQTT_URL` | `mqtt://abenix-mosquitto:1883` | `mqtt_publish`, and the API's edge bundle push. `MQTT_BROKER_URL` is the older name. Chart builds it from the release |
| `TSDB_URL` | empty | `tsdb_query` connection string. `TIMESCALE_URL` is the older name. Chart builds it from `streaming.*` |
| `KAFKA_BOOTSTRAP_SERVERS` | empty | `event_stream` answers "not configured" without it |
| `TENANT_ID` | `default` | Fallback tenant for `subscribed_feed` and `windowed_state` |
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `localhost` / `5432` / `abenix` / `abenix` / `abenix` | `schema_portfolio_tool` when it has no database URL |
| `INTERNAL_API_URL` | `API_BASE_URL`, then `ABENIX_API_URL`, then `http://localhost:8000` | API base for `approval_gate` |
| `INTERNAL_API_TOKEN` | empty | Bearer for `approval_gate` and `invoke_agent` |
| `ABENIX_API_URL` / `ABENIX_INTERNAL_URL` | `http://abenix-api:8000` | API base for `invoke_agent` and `ml_model` |
| `ABENIX_INTERNAL_API_KEY` / `PLATFORM_API_KEY` | empty | Further fallbacks for the `invoke_agent` key, after `ABENIX_PLATFORM_API_KEY` and `INTERNAL_API_TOKEN` |

### LLM provider keys

| Variable | Required if you use | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude models | The LLM reranker uses it when `RERANKER_PROVIDER=llm`. Vision OCR in the worker needs it |
| `OPENAI_API_KEY` | GPT models, OpenAI embeddings, moderation | |
| `GOOGLE_API_KEY` | Gemini models | `GEMINI_API_KEY` is accepted too |
| `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_API_BASE` / `AZURE_OPENAI_API_VERSION` | Azure OpenAI models and embeddings | Version default `2024-10-01-preview` |
| `CLAUDE_SUBSCRIPTION_TOKEN` | A Claude Pro or Max subscription instead of per-call API billing | `ANTHROPIC_AUTH_TOKEN` is accepted too. Mint with `claude setup-token`, or let `scripts/sync-claude-subscription.sh` copy the one Claude Code already holds. A value stored in Admin -> LLM Settings takes precedence over this variable. The token rotates, see [02-runtime/00-agent-execution](../02-runtime/00-agent-execution.md#claude-subscription-mode). |
| `COHERE_API_KEY` | Cohere reranking | |
| `RERANKER_PROVIDER` | | `cohere`, `llm` or `none`. Unset picks Cohere when its key exists, else no reranking. The Haiku scorer runs only with `llm` |

### Tool credentials

The environment is one of four sources for these, and the lowest-effort one for a first deploy. An admin can also set any of them at run time under **Admin -> Tool Configuration**, which wins over the environment, and the screen shows which source is in effect. The list below is generated from the tools' own `config_fields` declarations, so it is complete by construction. `python scripts/check-tool-config.py` fails CI when a tool reads the environment without declaring the key, and `--report` lists every read by file.

A tool listed under *Required by* returns a standard "not configured" answer without the key. Every other tool runs in a degraded mode and says so in its result.

| Variable | Provider | Read by | Required by |
|---|---|---|---|
| `AIRTABLE_API_KEY` | Airtable | `api_connector`, `integration_hub` | nobody, optional |
| `AISSTREAM_API_KEY` | AISStream | `ais_stream` | `ais_stream` |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage | `market_data` | nobody, optional |
| `ANTHROPIC_API_KEY` | Anthropic | `agent_step`, `image_analyzer`, `kyc_met_pdf_extractor`, `llm_call`, `llm_route` | nobody, optional |
| `ASANA_TOKEN` | Asana | `integration_hub` | nobody, optional |
| `AWS_ACCESS_KEY_ID` | AWS | `cloud_cost`, `cloud_storage`, `data_exporter`, `integration_hub` | nobody, optional |
| `AWS_REGION` | AWS | `cloud_cost`, `cloud_storage`, `data_exporter` | nobody, optional |
| `AWS_SECRET_ACCESS_KEY` | AWS | `cloud_cost`, `cloud_storage`, `data_exporter` | nobody, optional |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure | `cloud_storage` | nobody, optional |
| `AZURE_SUBSCRIPTION_ID` | Azure | `cloud_cost` | nobody, optional |
| `AZURE_OPENAI_API_BASE` | Azure OpenAI | `agent_step`, `llm_call`, `llm_route` | nobody, optional |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI | `agent_step`, `llm_call`, `llm_route` | nobody, optional |
| `AZURE_OPENAI_API_VERSION` | Azure OpenAI | `agent_step`, `llm_call`, `llm_route` | nobody, optional |
| `BALTIC_API_KEY` | Baltic Exchange | `freight_baltic_blpg` | nobody, optional |
| `BALTIC_API_URL` | Baltic Exchange | `freight_baltic_blpg` | nobody, optional |
| `BRAVE_SEARCH_API_KEY` | Brave | `tavily_search` | nobody, optional |
| `COINGECKO_API_KEY` | CoinGecko | `crypto_market` | nobody, optional |
| `COMPANIES_HOUSE_API_KEY` | Companies House | `companies_house`, `legal_existence_verifier`, `ubo_discovery` | `companies_house` |
| `DEEPL_API_KEY` | DeepL | `translation` | nobody, optional |
| `EIA_API_KEY` | EIA | `eia_open_data`, `market_data` | `eia_open_data` |
| `ELEVENLABS_API_KEY` | ElevenLabs | `meeting_speak` | nobody, optional |
| `SMTP_FROM` | Email (SMTP) | `data_exporter`, `email_sender` | nobody, optional |
| `SMTP_HOST` | Email (SMTP) | `data_exporter`, `email_sender` | nobody, optional |
| `SMTP_PASS` | Email (SMTP) | `data_exporter`, `email_sender` | nobody, optional |
| `SMTP_PORT` | Email (SMTP) | `data_exporter`, `email_sender` | nobody, optional |
| `SMTP_USER` | Email (SMTP) | `data_exporter`, `email_sender` | nobody, optional |
| `EMBER_API_KEY` | Ember | `ember_climate` | nobody, optional |
| `ENTSOE_API_KEY` | ENTSO-E | `entso_e` | `entso_e` |
| `FMP_API_KEY` | Financial Modeling Prep | `credit_risk` | `credit_risk` |
| `FITCH_CONNECT_API_KEY` | Fitch Connect | `fitch_connect` | `fitch_connect` |
| `FITCH_CONNECT_API_URL` | Fitch Connect | `fitch_connect` | `fitch_connect` |
| `FRED_API_KEY` | FRED | `fred_economic`, `yahoo_finance` | nobody, optional |
| `GITHUB_TOKEN` | GitHub | `github_tool` | nobody, optional |
| `GMAIL_API_KEY` | Gmail | `integration_hub` | nobody, optional |
| `GEMINI_API_KEY` | Google AI | `agent_step`, `llm_call`, `llm_route` | nobody, optional |
| `GOOGLE_API_KEY` | Google AI | `agent_step`, `kyc_met_pdf_extractor`, `llm_call`, `llm_route` | nobody, optional |
| `GCP_BILLING_BQ_DATASET` | Google Cloud | `cloud_cost` | nobody, optional |
| `GCP_BILLING_PROJECT` | Google Cloud | `cloud_cost` | nobody, optional |
| `GOOGLE_SHEETS_CREDENTIALS` | Google Sheets | `api_connector` | nobody, optional |
| `GOOGLE_SHEETS_KEY` | Google Sheets | `integration_hub` | nobody, optional |
| `HUBSPOT_API_KEY` | Hubspot | `integration_hub` | nobody, optional |
| `INTERCOM_TOKEN` | Intercom | `integration_hub` | nobody, optional |
| `JIRA_EMAIL` | Jira | `api_connector`, `integration_hub` | nobody, optional |
| `JIRA_TOKEN` | Jira | `api_connector`, `integration_hub` | nobody, optional |
| `JIRA_URL` | Jira | `api_connector`, `integration_hub` | nobody, optional |
| `LIBRETRANSLATE_API_KEY` | LibreTranslate | `translation` | nobody, optional |
| `LIBRETRANSLATE_URL` | LibreTranslate | `translation` | nobody, optional |
| `LINEAR_API_KEY` | Linear | `integration_hub` | nobody, optional |
| `LIVEKIT_API_KEY` | LiveKit | `meeting_join` | `meeting_join` |
| `LIVEKIT_API_SECRET` | LiveKit | `meeting_join` | `meeting_join` |
| `LIVEKIT_URL` | LiveKit | `meeting_join` | `meeting_join` |
| `MEDIASTACK_API_KEY` | MediaStack | `news_feed` | nobody, optional |
| `TEAMS_BOT_CERT_PATH` | Microsoft Teams | `meeting_join` | nobody, optional |
| `TEAMS_GRAPH_CLIENT_ID` | Microsoft Teams | `meeting_join` | nobody, optional |
| `TEAMS_GRAPH_CLIENT_SECRET` | Microsoft Teams | `meeting_join` | nobody, optional |
| `TEAMS_GRAPH_TENANT_ID` | Microsoft Teams | `meeting_join` | nobody, optional |
| `MOODYS_API_KEY` | Moody's | `moodys_api` | `moodys_api` |
| `MOODYS_API_URL` | Moody's | `moodys_api` | `moodys_api` |
| `NEWS_API_KEY` | NewsAPI | `news_feed` | nobody, optional |
| `NOTION_API_KEY` | Notion | `api_connector`, `integration_hub` | nobody, optional |
| `OPENAI_API_KEY` | OpenAI | `agent_step`, `image_analyzer`, `knowledge_store`, `llm_call`, `llm_route`, `meeting_listen`, `meeting_speak`, `persona_rag`, `speech_to_text`, `text_to_speech`, `vector_search` | nobody, optional |
| `OPENCORPORATES_API_KEY` | OpenCorporates | `legal_existence_verifier`, `ubo_discovery` | nobody, optional |
| `OPENSANCTIONS_API_KEY` | OpenSanctions | `pep_screening` | nobody, optional |
| `PAGERDUTY_TOKEN` | Pagerduty | `integration_hub` | nobody, optional |
| `PINECONE_API_KEY` | Pinecone | `knowledge_store`, `vector_search` | nobody, optional |
| `PINECONE_INDEX_NAME` | Pinecone | `knowledge_store`, `vector_search` | nobody, optional |
| `SPG_RATINGS_API_KEY` | S&P Global Ratings | `spg_ratings_api` | `spg_ratings_api` |
| `SPG_RATINGS_API_URL` | S&P Global Ratings | `spg_ratings_api` | nobody, optional |
| `SALESFORCE_INSTANCE_URL` | Salesforce | `integration_hub` | nobody, optional |
| `SALESFORCE_TOKEN` | Salesforce | `integration_hub` | nobody, optional |
| `SENDGRID_API_KEY` | Sendgrid | `integration_hub` | nobody, optional |
| `SERPAPI_API_KEY` | Serpapi | `tavily_search` | nobody, optional |
| `SERPER_API_KEY` | Serper | `tavily_search` | nobody, optional |
| `SLACK_WEBHOOK_URL` | Slack | `api_connector`, `integration_hub` | nobody, optional |
| `SNOWFLAKE_ACCOUNT` | Snowflake | `integration_hub` | nobody, optional |
| `STRIPE_SECRET_KEY` | Stripe | `integration_hub` | nobody, optional |
| `TAVILY_API_KEY` | Tavily | `adverse_media`, `tavily_search` | nobody, optional |
| `TEAMS_WEBHOOK_URL` | Teams | `integration_hub` | nobody, optional |
| `TWILIO_ACCOUNT_SID` | Twilio | `twilio_sms` | `twilio_sms` |
| `TWILIO_AUTH_TOKEN` | Twilio | `integration_hub`, `twilio_sms` | `twilio_sms` |
| `TWILIO_FROM_NUMBER` | Twilio | `twilio_sms` | `twilio_sms` |
| `TWILIO_WHATSAPP_FROM` | Twilio | `twilio_sms` | nobody, optional |
| `ZAPIER_NLA_KEY` | Zapier | `zapier_pass_through` | `zapier_pass_through` |
| `ZENDESK_TOKEN` | Zendesk | `integration_hub` | nobody, optional |
| `ZOOM_SDK_KEY` | Zoom | `meeting_join` | nobody, optional |
| `ZOOM_SDK_SECRET` | Zoom | `meeting_join` | nobody, optional |

`ABENIX_DATA_KEY_KEK_BASE64` encrypts values saved from the admin screen. The chart sets it from `secrets.dataKeyKekBase64`.

The older `GET /api/integrations/status` probe also checks `SENTRY_DSN`,
`OTEL_ENABLED`, `OTEL_ENDPOINT`, `YAHOO_FINANCE_API_KEY`, `ENTSO_E_TOKEN` and
`OPENSANCTIONS_DATA_PATH`. Only the first three are read anywhere else.

---

## Warm code runners

Read by agent-runtime. Details in [02-runtime/16-warm-code-runners](../02-runtime/16-warm-code-runners.md). With `codeRunners.enabled` off the chart sets only `CODE_RUNNER_MODE=job`.

| Variable | Default | Notes |
|---|---|---|
| `CODE_RUNNER_MODE` | `auto` | `auto`, `warm` or `job`. Anything else is read as `auto`. Chart from `codeRunners.mode` |
| `CODE_RUNNER_IMAGES` | `{}` | JSON map of language to runner image. Empty means warm runners are not configured. Chart builds it from `codeRunners.registry`, `pools` and `imageTag` |
| `CODE_RUNNER_PULL_POLICY` | `IfNotPresent` | Image pull policy for runner pods |
| `CODE_RUNNER_PULL_SECRET` | `""` | Image pull secret name. The chart does not set it |
| `CODE_RUNNER_NAMESPACE` | `""` | Namespace runners are created in. Empty means the pod's own. The chart does not set it |
| `CODE_RUNNER_CONCURRENCY` | `4` | Calls one runner pod handles at once |
| `CODE_RUNNER_MAX_REPLICAS` | `5` | Upper bound on replicas per runner |
| `CODE_RUNNER_EXEC_RESOURCES` | requests `100m`/`256Mi`, limits `2`/`2Gi` | JSON resources for the exec container |
| `CODE_RUNNER_GATEWAY_RESOURCES` | requests `50m`/`64Mi`, limits `500m`/`256Mi` | JSON resources for the gateway container |
| `CODE_RUNNER_RUNTIME_CLASS` | `""` | `runtimeClassName` for runner pods, for example gVisor |
| `CODE_RUNNER_KEDA` | off | `1`, `true` or `yes` adds a KEDA scaler per runner. Needs `CODE_RUNNER_PROMETHEUS_URL`, otherwise a CPU HPA is created |
| `CODE_RUNNER_PROMETHEUS_URL` | `""` | Prometheus the KEDA scaler queries for `abenix_coderunner_load` |
| `CODE_RUNNER_IDLE_SECONDS` | `900` | Idle time before a runner with no warm floor scales to zero. Also the KEDA cooldown |
| `CODE_RUNNER_DRAIN_SECONDS` | `120` | Idle time before an old version's runner is deleted |
| `CODE_RUNNER_MIN_WARM` | `low=0,medium=0,high=1,critical=1` | Replicas kept warm per risk tier. Comma-separated `tier=n`, merged over the defaults |
| `CODE_RUNNER_HOT_CALLS_PER_HOUR` | `30` | Calls in the last hour that keep one replica warm. 0 turns it off |
| `CODE_RUNNER_DEFAULT_TIER` | `medium` | Tier used when the asset does not say |
| `CODE_RUNNER_NATS_URL` | `NATS_URL` | NATS address handed to runner pods |
| `CODE_RUNNER_NATS_SECRET` | `""` | Secret with `user` and `password` keys that runner pods log in with. Chart sets `<release>-code-runner-nats` |
| `CODE_RUNNER_FETCH_TTL` | `21600` | Lifetime in seconds of the token a runner uses to fetch its archive |
| `CODE_RUNNER_API_URL` | `CODE_ASSET_DOWNLOAD_BASE_URL`, else `http://abenix-api.abenix.svc.cluster.local:8000` | Where runners fetch archives from |
| `CODE_RUNNER_MAX_PAYLOAD` | `900000` | Largest request in bytes sent over NATS. The chart does not set it |
| `CODE_RUNNER_GRACE_SECONDS` | `930` | Pod termination grace period |
| `CODE_RUNNER_WS_SIZE` | `2Gi` | Size limit of the workspace volume |
| `CODE_RUNNER_SCRATCH_SIZE` | `1Gi` | Size limit of the scratch volume |

The runner NATS login is its own user, `coderun` by default, allowed only to
subscribe to `code.>` and answer on `_INBOX.>`. Its password is generated on
first install and kept, unless `codeRunners.nats.password` is set. The NATS pod
reads it as `CODERUN_NATS_PASSWORD`.

### Runner image

`apps/code-runner/runner.py` reads these. The agent-runtime sets them on the
pods it creates, so you only touch them when running the image by hand.

| Variable | Default | Container | Notes |
|---|---|---|---|
| `CODERUN_NAME` / `CODERUN_REVISION` / `CODERUN_TENANT` / `CODERUN_ASSET` / `CODERUN_IMAGE` | `coderun` / none | gateway | Identity in metrics and logs |
| `CODERUN_NETWORK` | `false` | gateway | Whether the asset was granted network |
| `CODERUN_CONCURRENCY` | `4` | both | Concurrent calls |
| `CODERUN_MAX_PENDING` | `0` | gateway | Queued calls before new ones are refused. 0 means no cap |
| `CODERUN_SOCKET` | `/run/coderun/exec.sock` | both | Socket between gateway and exec |
| `CODERUN_METRICS_PORT` | `9464` | gateway | `/metrics` and `/healthz` |
| `CODERUN_DRAIN_SECONDS` | `900` | gateway | Time to finish in-flight calls on shutdown. The runtime sets grace minus 15 |
| `NATS_URL` / `NATS_USER` / `NATS_PASSWORD` | `nats://abenix-nats:4222` | gateway | |
| `POD_NAME` | `CODERUN_NAME` | gateway | |
| `CODERUN_WS` / `CODERUN_TMP` / `CODERUN_SCRATCH` | `/ws` / `/tmp` / `/scratch` | exec | Mount points |
| `CODERUN_RUN_CMD` | none | exec | Command a call runs |
| `CODERUN_MAX_STDOUT` | `1000000` | exec | Bytes of output kept |
| `CODERUN_AS_MULTIPLIER` | `1` | exec | Address space limit as a multiple of the memory limit |
| `CODERUN_MAX_PROCS` | `512` | exec | Process limit |
| `CODERUN_MAX_FILE_MB` | `256` | exec | Largest file a run may write |
| `CODERUN_PATH` | the image `PATH` | exec | |
| `CODERUN_FETCH_URL` / `CODERUN_BUILD_CMD` / `CODERUN_BUILD_ROOT` / `CODERUN_BUILD_TIMEOUT` / `CODERUN_MAX_ZIP_MB` | none / `true` / `/tmp` / `900` / `200` | init | Archive fetch and build step |

---

## worker

| Variable | Default | Notes |
|---|---|---|
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Chart sets DB 0 on the release Redis. The API also reads it to enqueue |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Chart sets DB 1 |
| `CELERY_PREFETCH_MULTIPLIER` | `1` | |
| `CELERY_TASK_ACKS_LATE` | `true` | The worker Deployments set it explicitly |
| `CELERY_TASK_REJECT_ON_WORKER_LOST` | `true` | |
| `CELERY_VISIBILITY_TIMEOUT` | `21600` | Redis broker visibility timeout in seconds |
| `CELERY_RESULT_EXPIRES` | `86400` | |
| `CELERY_TASK_SOFT_TIME_LIMIT` / `CELERY_TASK_TIME_LIMIT` | `1500` / `1800` | |

`docker/Dockerfile.worker`, the image the cluster runs, starts Celery with
`--concurrency=2 -Q documents,cognify,agents` written into its `CMD`. The CI
image `apps/worker/Dockerfile` reads `CELERY_CONCURRENCY` (default 8),
`CELERY_QUEUES` (default `documents,agents`) and `CELERY_LOGLEVEL` instead.
The cognify worker Deployment passes its own `-Q` and `--concurrency` from
`cognifyWorker.queue` and `cognifyWorker.concurrency`.

---

## abenix-web

`NEXT_PUBLIC_*` values are inlined into the client bundle at `npm run build`.
Changing them on a running pod does nothing.

| Variable | Default | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | API base the browser calls |
| `NEXT_PUBLIC_APP_URL` | `http://localhost:3000` | `metadataBase` for page metadata |
| `NEXT_PUBLIC_GRAFANA_URL` | `http://localhost:3010` (alerts, observability, execution trace link), empty (cluster page) | |
| `NEXT_PUBLIC_ENABLE_MONETIZATION` | ignored | No longer read. The web asks `GET /api/platform/features` at runtime, see `MARKETPLACE_ENABLED` and `MONETIZATION_ENABLED` |
| `NEXT_PUBLIC_AUDIT_NATIVE` | off | `true` makes the audit page try `/api/admin/audit-log` first |
| `NEXT_PUBLIC_ORACLENET_API_KEY` | empty | Key the public OracleNet page sends |

`docker/Dockerfile.web`, the cluster image, takes `NEXT_PUBLIC_API_URL`,
`NEXT_PUBLIC_APP_URL`, `NEXT_PUBLIC_ENABLE_MONETIZATION`,
`NEXT_PUBLIC_AUDIT_NATIVE` and `NEXT_PUBLIC_GRAFANA_URL` as build arguments.
An empty one falls back to the default in the table. `deploy.sh` and
`deploy-azure.sh` pass each one that is set in `.env` or the shell when they
build the web image. Changing one means rebuilding the web image.
`apps/web/Dockerfile` (CI) accepts `NEXT_PUBLIC_GRAFANA_URL` and
`NEXT_PUBLIC_TEMPO_URL`. No page reads `NEXT_PUBLIC_TEMPO_URL`.
When `NEXT_PUBLIC_GRAFANA_URL` is not set, `deploy-azure.sh` builds the web
image with `http://grafana.<host>`, taking the host from `.azure-endpoint` or
the ingress load balancer of the last deploy. On a first deploy the host is not
known yet, so set the variable or redeploy once the ingress is up. Setting a
`NEXT_PUBLIC_*` value with `kubectl set env` on a running web Deployment has no
effect, the bundle is already built.

---

## Images

| Variable | Image | Value | Notes |
|---|---|---|---|
| `PYTHONDONTWRITEBYTECODE` | api, agent-runtime, worker | `1` | |
| `PYTHONPATH` | api | `/app/packages/db:/app/packages/sdk/python:/app/apps/agent-runtime` | The API imports the engine |
| `PYTHONPATH` | agent-runtime | `/app/packages/db:/app/apps/agent-runtime:/app/apps/api` | The runtime imports API settings helpers |
| `PYTHONPATH` | worker | `/app/packages/db:/app/apps/agent-runtime` | |
| `NODE_ENV` / `PORT` | web | `production` / `3000` | |
| `NEXT_TELEMETRY_DISABLED` | web, CI image only | `1` | |
| `MODEL_URI` / `MODEL_FRAMEWORK` / `PORT` | model-serving | empty / `sklearn` / `8080` | `MODEL_URI` may be a path or an HTTP URL |
| `PYTHONUNBUFFERED` | code-runner | `1` | |

---

## Edge runtimes

Read by `apps/edge-runtime/runtime.py`, `apps/edge-runtime-rust` and
`apps/edge-runtime-c`, all three the same contract unless noted.

| Variable | Default | Notes |
|---|---|---|
| `GATEWAY_ID` | `edge-local` | Stable id the gateway registers under |
| `GATEWAY_NAME` | `GATEWAY_ID` | |
| `PLATFORM_URL` | `http://host.docker.internal:8000` | API base |
| `PLATFORM_TOKEN` | empty | `af_*` key from `POST /api/edge/tokens/mint`. Empty skips registration |
| `MQTT_URL` | empty | Broker for `edge.<gateway_id>.deploy`. Empty means bundles arrive over HTTP only |
| `SIGNING_PUBKEY_PEM` | empty | Bundle verification key. Python and Rust only |
| `SIGNING_PUBKEY_PATH` | `/etc/edge/signing_pub.pem` | Used when the PEM variable is empty |
| `EDGE_ALLOW_UNSIGNED` | off | Only the literal `true` accepts unsigned bundles. Python only. Local development |
| `TENANT_ID` | empty | Refuses bundles signed for another tenant. Python only |
| `BUNDLE_DIR` | `/var/edge/agents` | |
| `ENDPOINT_URL` | empty | URL the platform can push bundles to. Sent on register |
| `ANTHROPIC_API_KEY` | empty | Without it execute returns a stub answer |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | |
| `PORT` | `8080` | |

On the API side, `EDGE_SIGNING_KEY_PEM`, `EDGE_SIGNING_KEY_PATH`,
`EDGE_SIGNING_KEY_DIR` and `EDGE_ALLOW_UNSIGNED` control bundle signing. See
[06-deployment/05-edge-runtime](../06-deployment/05-edge-runtime.md).

---

## Standalone apps

Each app reads `ABENIX_API_URL` and its own key, for example
`CONTRACTIQ_ABENIX_API_KEY`, `WINGMAN_ABENIX_API_KEY`,
`INDUSTRIALIOT_ABENIX_API_KEY`, `MIDEASTTOURISM_ABENIX_API_KEY`,
`RESOLVEAI_ABENIX_API_KEY` and `PHARMAVIGIL_ABENIX_API_KEY`.
`scripts/seed-standalone-keys.sh` mints them and patches each app's Secret.

Wingman also reads `WINGMAN_CACHE_DIR` (`/data/wingman-cache`),
`WINGMAN_CACHE_TTL_SECONDS` (`1800`), `WINGMAN_VISIT_WINDOW_SECONDS` (`3600`),
`WINGMAN_WARMER_INTERVAL_SECONDS` (`1800`) and `WINGMAN_ACTING_SUBJECT_TYPE`
(`wingman`). App-specific settings live with each app.

---

## Read in code but not for operators

The SDK Playground and Load Playground generate sample code that reads
`ABENIX_API_KEY`, `ABENIX_API_URL`, `ABENIX_BASE_URL` and `MYAPP_ABENIX_API_KEY`.
Those reads run on your machine when you paste the snippet, not in the
platform.

---

## Test and CI

| Variable | Read by | Notes |
|---|---|---|
| `USE_K8S` | `playwright.config.ts`, `scripts/run-e2e.sh` | Set means Playwright does not start its own web server |
| `BASE_URL` | `playwright.config.ts` | Default `http://localhost:3000` |
| `BASE` / `API` | specs, `scripts/uat.sh`, `scripts/load/baseline.js` | Web and API bases, default `localhost:3000` and `localhost:8000` (`baseline.js` uses `BASE` for the API) |
| `AF_EMAIL` / `AF_PASSWORD` | specs, `scripts/uat.sh`, decision load setup | Default `admin@abenix.dev` / `Admin123456` |
| `AF_VIEWER_EMAIL` / `AF_VIEWER_PASSWORD` | `scripts/uat.sh` | Low-privilege user for the RBAC spec |
| `CI` | `playwright.config.ts` | Retries 2, `forbidOnly`, video on first retry |

---

## See also

- [06-deployment/02-helm](../06-deployment/02-helm.md) — how these are templated into ConfigMaps + Secrets
- [03-glossary](03-glossary.md) — terminology
