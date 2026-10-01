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
| `MCP_ALLOWED_HOSTS` | no | the UAT fixture host | Comma-separated host suffixes an MCP server may be registered from. See below |
| `EMAIL_SMTP_HOST` / `_PORT` / `_USER` / `_PASSWORD` | no | — | Outbound email for notifications |
| `SLACK_DEFAULT_WEBHOOK_URL` | no | — | Default Slack webhook (per-tenant overrides exist) |

### Registering your own MCP server

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

### Tool credentials

The environment is one of four sources for these, and the lowest-effort one for a first deploy. An admin can also set any of them at run time under **Admin -> Tool Configuration**, which wins over the environment, and the screen shows which source is in effect. The list below is generated from the tools' own `config_fields` declarations, so it is complete by construction. Regenerate it with `python scripts/check-tool-config.py --report` after adding a tool.

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
| `PINECONE_API_KEY` | Pinecone | `knowledge_store`, `persona_rag`, `vector_search` | nobody, optional |
| `PINECONE_INDEX_NAME` | Pinecone | `knowledge_store`, `persona_rag`, `vector_search` | nobody, optional |
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
