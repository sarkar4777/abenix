# Environment variables reference

> Environment variables are deploy-time and need a pod restart. Knobs an admin
> can change at runtime from the UI live in
> [04-platform-settings](04-platform-settings.md) instead.

> Every env var the platform reads. Grouped by service. Defaults + notes.

---

## Cross-service (read by most pods)

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | yes | — | `postgresql+asyncpg://abenix:****@postgres:5432/abenix` |
| `REDIS_URL` | yes | — | `redis://redis:6379/0` |
| `NATS_URL` | yes | — | `nats://nats:4222` |
| `JWT_SECRET` | yes | — | HMAC secret. Rotate quarterly |
| `JWT_ALGORITHM` | no | `RS256` | Currently RS only. HS not supported |
| `LOG_LEVEL` | no | `INFO` | DEBUG / INFO / WARNING / ERROR |
| `LOG_FORMAT` | no | `json` | `json` for prod. `text` for local dev |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | — | gRPC `tempo:4317`. set empty to disable export |
| `OTEL_SERVICE_NAME` | no | per-service | Auto-set by deploy |
| `OTEL_TRACES_SAMPLER_ARG` | no | `1.0` | Reduce in high-traffic prod |
| `OTEL_PII_REDACT` | no | `true` | Set `false` for local debugging only |
| `ABENIX_DATA_KEY_KEK_BASE64` | **prod yes**, dev no | — | 32-byte base64 cluster KEK for AES-256-GCM at-rest encryption of sensitive PersonaItem + AgentMemory fields. Generate via `openssl rand -base64 32`. Source from a real KMS (Azure Key Vault / AWS KMS / Vault) — never put in source / configmap. **Missing → encryption is a silent no-op + one warning logs.** Per-tenant DEK derives deterministically as `HMAC-SHA256(KEK, tenant_id)` so pods don't need a shared cache. Setup recipe: [`08-howto/06-encryption-setup.md`](../08-howto/06-encryption-setup.md) |

---

## abenix-api specific

| Variable | Required | Default | Notes |
|---|---|---|---|
| `CORS_ORIGINS` | no | `*` | Comma-separated. **set to specific domains in prod** |
| `RATE_LIMIT_REDIS_DB` | no | `1` | Redis logical DB for the rate-limit counters |
| `BODY_SIZE_LIMIT_MB` | no | `500` | Cap per request. ML uploads override |
| `ML_MODELS_DIR` | no | `/data/ml-models` | Where uploaded model pkls land |
| `ML_MODEL_MAX_K8S_PER_TENANT` | no | `10` | Per-tenant cap on concurrent k8s model deployments |
| `ML_MODEL_SERVING_IMAGE` | no | — | Image for the on-cluster model-serving pods |
| `ALLOWED_IPS` | no | `""` | Comma-separated CIDR. empty = no restriction |
| `EMAIL_SMTP_HOST` / `_PORT` / `_USER` / `_PASSWORD` | no | — | Outbound email for notifications |
| `SLACK_DEFAULT_WEBHOOK_URL` | no | — | Default Slack webhook (per-tenant overrides exist) |

---

## agent-runtime specific

| Variable | Required | Default | Notes |
|---|---|---|---|
| `RUNTIME_POOL` | yes | — | Pool name — `default`, `chat`, `heavy-reasoning`, `long-running` |
| `RUNTIME_MAX_CONCURRENT_EXECS` | no | `8` | In-pod concurrency cap |
| `MAX_ITERATION_DEFAULT` | no | `10` | Override if agent doesn't set it |
| `TOOL_TIMEOUT_DEFAULT` | no | `60` | Per-tool timeout in seconds |
| `LLM_RETRY_COUNT` | no | `3` | Retries on 5xx from LLM provider |
| `LLM_RETRY_BACKOFF_MAX` | no | `30` | Max seconds between retries |
| `BLPG_CURATED_PATH` | no | `/data/blpg_curated.json` | Operator override for the freight_baltic_blpg tool's curated mids |

### LLM provider keys

| Variable | Required if you use | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude models | `sk-ant-...` |
| `OPENAI_API_KEY` | GPT models | `sk-...` |
| `GOOGLE_API_KEY` | Gemini models | service account JSON or API key |
| `CLAUDE_SUBSCRIPTION_TOKEN` | A Claude Pro or Max subscription instead of per-call API billing | Mint with `claude setup-token`, or let `scripts/sync-claude-subscription.sh` copy the one Claude Code already holds. A value stored in Admin -> LLM Settings takes precedence over this variable. The token rotates, see [02-runtime/00-agent-execution](../02-runtime/00-agent-execution.md#claude-subscription-mode). |

### Tool API keys (most tools degrade gracefully if missing)

| Variable | Tool that uses it |
|---|---|
| `TAVILY_API_KEY` | `tavily_search` |
| `BRAVE_SEARCH_API_KEY` | `brave_search` |
| `SERPAPI_API_KEY` | `serpapi_search` |
| `SERPER_API_KEY` | `serper_search` |
| `NEWS_API_KEY` | `news_api` |
| `EIA_API_KEY` | `eia_open_data` |
| `FRED_API_KEY` | `fred_data` |
| `ALPHA_VANTAGE_API_KEY` | `alpha_vantage` |
| `MEDIASTACK_API_KEY` | `mediastack_news` |
| `ENTSOE_API_KEY` | `entsoe_power` |
| `BALTIC_API_KEY` + `BALTIC_API_URL` | `freight_baltic_blpg` (live subscription) |
| `AISSTREAM_API_KEY` | `ais_stream` |
| `PINECONE_API_KEY` | optional: `pinecone_kb_search` (we default to pgvector) |

---

## worker specific

| Variable | Required | Default | Notes |
|---|---|---|---|
| `CELERY_BROKER_URL` | yes | inherits REDIS_URL DB 0 | broker for jobs |
| `CELERY_QUEUE` | yes | `default` | `default` or `cognify` |
| `CELERY_CONCURRENCY` | no | `4` | Workers per pod |
| `BEAT_SCHEDULE_FILE` | no | `/data/celerybeat-schedule` | Beat's persistence file |

---

## abenix-web specific (build-time)

These must be set at `npm run build` time — they're inlined into the client bundle. Changing them requires rebuilding the image.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | yes | — | `https://api.example.com` |
| `NEXT_PUBLIC_GRAFANA_URL` | no | unset | Used by /admin/cluster's Open-Grafana link |
| `NEXT_PUBLIC_TEMPO_URL` | no | unset | Used by /executions/{id}'s View-Trace link |
| `NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT` | no | unset | Browser OTel. rarely used |
| `NEXT_PUBLIC_ENABLE_MONETIZATION` | no | `false` | Show billing pages |
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | no | — | When monetization enabled |

> **Trap** — `NEXT_PUBLIC_*` are inlined at build. Changing them via the helm values without rebuilding does nothing.

---

## Standalone-app specific

Each app has:

| Variable | Required | Notes |
|---|---|---|
| `ABENIX_API_URL` | yes | Cluster-internal: `http://abenix-api.abenix.svc.cluster.local:8000` |
| `<APP>_ABENIX_API_KEY` | yes | Long-lived service-account key. Generated at first deploy by `seed-standalone-keys.sh` |
| `<APP>_DATABASE_URL` | depends | Separate DB if the app has its own tables. otherwise shares platform DB |
| `<APP>_CACHE_DIR` | no | Path to the file cache. defaults to `/data/<app>-cache` |
| `<APP>_CACHE_TTL_SECONDS` | no | `1800` |
| `<APP>_VISIT_WINDOW_SECONDS` | no | `3600` |
| `<APP>_WARMER_INTERVAL_SECONDS` | no | `1800` |

Wingman-specific:

| Variable | Notes |
|---|---|
| `WINGMAN_ACTING_SUBJECT_TYPE` | Default `wingman` |
| `AISSTREAM_API_KEY` | Required for Operations Watch live AIS |

E&C-Copilot-specific:

| Variable | Notes |
|---|---|
| `CONTRACTIQ_OCR_PROVIDER` | `tesseract` (default) or `azure` |
| `CONTRACTIQ_AZURE_FORM_RECOGNIZER_KEY` | When provider=azure |

ResolveAI-specific:

| Variable | Notes |
|---|---|
| `RESOLVEAI_INBOX_SOURCE` | `helpscout` / `zendesk` / `intercom` / `gmail` |
| `RESOLVEAI_<SOURCE>_API_KEY` | Per-source |

---

## Edge runtime specific

| Variable | Required | Notes |
|---|---|---|
| `EDGE_REGISTRATION_TOKEN` | yes | One-time token from `/admin/edge` |
| `EDGE_NODE_ID` | yes | Stable per-node identifier |
| `EDGE_LOCATION` | no | Free-form (city, plant ID) |
| `LOCAL_LLM_URL` | no | If set, route `local/*` and `ollama/*` models here |
| `ALLOWED_AGENTS` | no | Comma-separated whitelist. empty = all assigned agents |
| `EDGE_CACHE_DIR` | no | Local SQLite path. default `/var/lib/abenix-edge` |

---

## Test / CI env

| Variable | Notes |
|---|---|
| `USE_K8S` | When `true`, Playwright skips its built-in webServer (don't auto-start the dev server) |
| `BASE` | Playwright base URL — default `http://localhost:3000` |
| `API` | Playwright API base URL — default `http://localhost:8000` |
| `AF_EMAIL` / `AF_PASSWORD` | Test user creds — default `admin@abenix.dev / Admin123456` |
| `CI` | When set, retries=2 and other CI-only behaviour |

---

## See also

- [06-deployment/02-helm](../06-deployment/02-helm.md) — how these are templated into ConfigMaps + Secrets
- [03-glossary](03-glossary.md) — terminology
