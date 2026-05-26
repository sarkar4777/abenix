# Architecture

A map of the repo so a new contributor knows where to land.

## What ships

Five things ship from this monorepo:

1. **Abenix platform** — the core product. API, web, agent-runtime workers, background worker, edge runtimes.
2. **Standalone apps** — domain-specific UIs that proxy through the platform: `wingman/`, `industrial-iot/`, `sauditourism/`, `contractiq/`, `resolveai/`, `claimsiq/`.
3. **SDKs** — `packages/sdk/python/` is canonical, copied into every standalone app's `api/sdk/` so they can talk to the platform without a vendored HTTP client.
4. **Helm chart** — `infra/helm/abenix/` deploys the whole platform plus selected standalones to k8s.
5. **The public mirror** — `scripts/publish-public.sh` strips sensitive pieces and rewrites history to the public repo on every release.

## Top-level layout

```
.
├── apps/                      # platform services
│   ├── api/                   # FastAPI — every HTTP route, RBAC, persistence
│   ├── agent-runtime/         # the workers that execute agents (pooled)
│   ├── worker/                # background jobs (cron, webhooks, sweepers)
│   ├── web/                   # Next.js SPA (Tailwind, framer-motion)
│   ├── edge/                  # Python edge runtime (offline agent execution)
│   ├── edge-c/                # C edge runtime (constrained devices)
│   └── edge-rust/             # Rust edge runtime (medium-resource devices)
├── packages/
│   ├── db/                    # SQLAlchemy models + alembic migrations
│   ├── agent-sdk/             # Python SDK consumers import
│   └── sdk/python/abenix_sdk/ # canonical SDK source (synced to consumers)
├── contractiq/                # standalone ETRM/contracts app
├── wingman/                   # standalone commodities trading copilot
├── industrial-iot/            # standalone IoT/predictive maintenance app
├── sauditourism/              # standalone Saudi Tourism app
├── resolveai/                 # standalone customer-support app
├── claimsiq/                  # standalone insurance-claims app
├── infra/helm/abenix/         # the Helm chart that deploys everything
├── docker/                    # Dockerfiles for non-app images
├── scripts/                   # ops scripts (deploy, build, e2e, publish)
├── e2e/                       # Playwright E2E suites
├── tests/unit/                # pure-python unit tests (CI gate)
└── docs/                      # architecture, ops, release guides
```

## Request flow — agent execution

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser / SDK
  participant API as apps/api
  participant DB as Postgres
  participant Q as Redis Streams
  participant R as apps/agent-runtime
  participant T as External tools<br/>(Anthropic, Tavily, ...)

  B->>API: POST /api/agents/{id}/execute
  API->>DB: insert Execution row
  API->>Q: enqueue on exec_q:<pool>
  API-->>B: 202 { execution_id }
  B->>API: GET /api/executions/{id}/watch (SSE)
  R->>Q: consume
  R->>T: tool invocations
  T-->>R: tool results
  R-->>API: status + events (pub/sub)
  API-->>B: stream events
  R->>DB: update Execution + ToolInvocation rows
```

Agent code lives in `apps/agent-runtime/engine/`. Tools register themselves in `engine/tools/__init__.py`. The agent runtime pulls work from one of four Redis Streams pools (`chat`, `default`, `heavy-reasoning`, `long-running`) — pool choice is per-agent config and lets KEDA scale each pool independently.

## Data model — where things live

Everything is tenant-scoped via `tenant_id`. The model lives in [packages/db/models/](packages/db/models/). The notable tables:

| Table | What it holds |
|---|---|
| `tenants` | top of the isolation tree; tenant-level settings (DLP, retention) live in the JSONB `settings` column, which is `MutableDict`-wrapped |
| `users` | password-auth or SSO; `auth_provider` + `external_id` identifies SSO users |
| `agents` | agent definitions (system prompt, tools, model config, optional DSL) |
| `executions` | one row per run; node-result trace + token + cost accounting |
| `tool_invocations` | one row per tool call inside an execution; the source of audit data |
| `webhooks` | tenant-owned outbound HTTP endpoints; HMAC-signed deliveries logged in `webhook_deliveries` |
| `api_keys` | `af_*` keys for SDK callers; raw key shown once on create |
| `approvals` | HITL gates with signoff |
| `mcp_connections` | per-user MCP servers wired into agents at runtime |
| `code_assets`, `knowledge_bases`, `ml_models` | uploadable artifacts |
| `activity_log` | append-only audit trail |

## SSO (Google / GitHub / Microsoft)

Both auth paths share `users.id` — the JWT issued at the end is identical. The difference is only how we resolved the user.

Password flow (existing): `/api/auth/register` and `/api/auth/login` in [auth.py](apps/api/app/routers/auth.py). Stores a bcrypt hash in `users.password_hash`.

SSO flow (new in v1.11): three endpoints in [sso.py](apps/api/app/routers/sso.py):

1. `GET /api/auth/oidc/providers` — returns the list of providers the SPA should show buttons for (only those with creds in env).
2. `GET /api/auth/oidc/{provider}/start?return_to=/dashboard` — signs a short-lived state JWT (return_to + nonce + provider, 10-min expiry) and 302s to the provider's authorize endpoint.
3. `GET /api/auth/oidc/{provider}/callback?code=...&state=...` — verifies state, exchanges code, fetches userinfo, upserts the user (match by `(auth_provider, external_id)` then by email then new), issues access + refresh tokens, 302s to `${WEB_BASE_URL}/auth/callback#access_token=...&refresh_token=...&return_to=...`. The SPA's [/auth/callback page](apps/web/src/app/auth/callback/page.tsx) stashes the tokens in localStorage and forwards.

State is a signed JWT (HS256, same secret as access tokens) — no Redis needed. The `users.auth_provider` + `users.external_id` columns (added in migration `a7b8c9d0e1f2`) carry the SSO link; the pair is unique-indexed so callback resolves in one query.

End-user docs in [docs/sso.md](docs/sso.md). Per-provider setup, env vars, and the kubectl one-liner are there.

## Routers — where each feature lives

| Feature | File |
|---|---|
| Email+password auth | [apps/api/app/routers/auth.py](apps/api/app/routers/auth.py) |
| SSO (Google/GitHub/Microsoft) | [apps/api/app/routers/sso.py](apps/api/app/routers/sso.py) |
| Agent CRUD + execute | [apps/api/app/routers/agents.py](apps/api/app/routers/agents.py) |
| Pipeline DSL run | [apps/api/app/routers/pipelines.py](apps/api/app/routers/pipelines.py) |
| Knowledge bases | [apps/api/app/routers/knowledge.py](apps/api/app/routers/knowledge.py) |
| ML models | [apps/api/app/routers/ml_models.py](apps/api/app/routers/ml_models.py) |
| Code assets | [apps/api/app/routers/code_assets.py](apps/api/app/routers/code_assets.py) |
| MCP connect + install | [apps/api/app/routers/mcp.py](apps/api/app/routers/mcp.py) |
| Webhooks | [apps/api/app/routers/webhook_config.py](apps/api/app/routers/webhook_config.py) |
| Approvals (HITL) | [apps/api/app/routers/approvals.py](apps/api/app/routers/approvals.py) |
| Edge | [apps/api/app/routers/edge.py](apps/api/app/routers/edge.py) |
| Tools registry | [apps/api/app/routers/tools.py](apps/api/app/routers/tools.py) |
| Tool runtime invoke | [apps/api/app/routers/tool_runtime.py](apps/api/app/routers/tool_runtime.py) |
| Tenant settings (DLP, retention, sandbox) | [apps/api/app/routers/settings.py](apps/api/app/routers/settings.py) |

## How to add a new...

**A new tool**: drop a single Python file under `apps/agent-runtime/engine/tools/`. Inherit from `BaseTool`, register in `engine/tools/__init__.py`. The tool will surface in the registry, the agent picker, the Builder palette, and `/api/tools` automatically.

**A new LLM provider**: mirror `_run_anthropic` / `_run_gemini` / `_run_openai` in [apps/api/app/routers/bpm_analyzer.py](apps/api/app/routers/bpm_analyzer.py). Provider keys go in env, surfaced via `/settings/integrations`.

**A new endpoint**: create the router under `apps/api/app/routers/`, register it in `apps/api/app/main.py`. Always return `success()` / `error()` from `app.core.responses` so the envelope is consistent. Add at least one happy-path test in `tests/unit/`.

**A new standalone app**: copy an existing standalone (`wingman/` is the cleanest reference), update `api/main.py` to set `app.title` and `app.routes`, point its SDK at the platform via `ABENIX_BASE_URL` + `ABENIX_API_KEY`, add a helm sub-chart under `infra/helm/`.

## Build + deploy — the part that bites new contributors

- **Image tags are derived from the git commit SHA** — `your-acr.azurecr.io/api:<sha>`. The Helm chart pins a single tag per image across all deployments using that image.
- **`scripts/deploy-azure.sh build --only=<service>` rewrites the helm template** to the latest SHA for ALL deployments — not just the one you built. This is the [`--only` trap](docs/06-deployment/deploy-only-trap.md): if you build only `api`, helm still rewrites `agent-runtime` and `worker` deployments to a tag that doesn't exist, and those pods go ImagePullBackOff while the old replicas keep serving.
- **Recovery**: rebuild the missing services with the current SHA, or `kubectl set image deploy/X ...` back to the last known good tag, or `helm rollback`.
- **The safe pattern**: do `bash scripts/deploy-azure.sh build` (no `--only`) on any change that touches Dockerfiles or shared code. Use `--only` only when you're certain the helm template won't fan out.

## Tests

- `tests/unit/` — pure-Python primitives (failure-code classifier, pipeline parser, response envelopes, security, moderation, tool registry). Runs in CI. **No live services.**
- `e2e/` — Playwright suites. Run against a deployed cluster (or a local dev stack). Three headline files:
  - `uat_enterprise_edge.spec.ts` — settings, JSONB persistence, RBAC edges
  - `uat_critical_paths.spec.ts` — auth, agents, pipelines, KBs, ML, webhooks, approvals, observability
  - `uat_ui_journeys.spec.ts` — browser-driven user journeys across the SPA
- `apps/*/tests/` — older live-DB suites, kept for future revival.

## Where to start as a new contributor

1. Read this file.
2. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution mechanics.
3. Read [ONBOARDING.md](ONBOARDING.md) for the 30-minute local setup.
4. Look at a recent PR that touched code near what you want to change — git blame is the cheapest way to learn local conventions.
5. Open a draft PR early and ask in the description what feedback you want.
