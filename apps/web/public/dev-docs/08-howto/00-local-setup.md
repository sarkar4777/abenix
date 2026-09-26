# Local development setup

> From `git clone` to a running cluster on your laptop in ~10 minutes.

---

## Prerequisites

| Tool | Min version | Why |
|---|---|---|
| Docker Desktop | 24.x | Container runtime |
| Node.js | 20.x | Next.js web build |
| Python | 3.12 | Backend services |
| kubectl | 1.27 | k8s CLI |
| Helm | 3.13 | chart installs |
| minikube **or** k3d | latest | local k8s |
| jq | latest | scripts |

macOS:
```bash
brew install docker node@20 python@3.12 kubectl helm minikube jq
```

Linux:
```bash
# Use your distro's package manager + the official installers for kubectl/helm/minikube
```

Windows: WSL2 + Docker Desktop + the Linux toolchain inside WSL.

---

## Two paths

### Path A — full local k8s (recommended for backend work)

```bash
git clone https://github.com/sarkar4777/abenix.git
cd abenix
cp .env.example .env             # fill in at least one LLM credential
bash scripts/deploy.sh local
```

This creates the minikube cluster, builds every image into minikube's Docker
daemon, installs the Helm chart plus the standalone apps, runs migrations and
seeds, then starts port forwards. Budget 30 to 40 minutes on a cold machine.
Most of that is image builds.

### Choosing which use-case apps to start

Both startup paths ask which use-case apps you want before they do anything
slow. Seven ship in the repo and you rarely need all of them.

```
  Which use-case apps should start alongside the platform?

    1  ContractIQ         3001/8001  energy contract intelligence
    2  Mideast Tourism    3002/8002  tourism analytics
    3  Industrial IoT     3003/8003  predictive maintenance + edge
    4  ResolveAI          3004/8004  customer-service resolution
    5  ClaimsIQ           3005       insurance FNOL (Java + Vaadin)
    6  Wingman            3006/8006  energy commodity trading
    7  PharmaVigil        3007/8007  drug safety + signal detection

    Numbers or names, comma separated — e.g. "1,3" or "pharmavigil,claimsiq".
    "all" for everything, "none" for the core platform only.
    Enter starts them all. (20s, then all)
```

| You want | Answer |
|---|---|
| Everything | press Enter, or `all` |
| Core platform only | `none` |
| Two of them | `pharmavigil,claimsiq` or `7,5` |

The prompt times out after 20 seconds and starts everything, so an unattended
run never wedges on a question nobody is there to answer. A pipe or a CI job
is not a terminal, so it skips the prompt entirely and starts them all.

**Scripting it.** `APPS` in the environment wins over the prompt and never
asks, which is what you want in CI or a Makefile:

```bash
APPS=none bash scripts/dev-local.sh                    # core platform only
APPS=pharmavigil,wingman bash scripts/dev-local.sh     # two apps
APPS=all bash scripts/deploy.sh local                  # everything, no prompt
APP_SELECT_TIMEOUT=60 bash scripts/dev-local.sh        # longer to decide
```

`APPS` means the same thing on both `dev-local.sh` and `deploy.sh local`. An
unrecognised name is reported and skipped rather than silently ignored.

The registry lives in [`scripts/lib/select-apps.sh`](../../scripts/lib/select-apps.sh).
Adding an app is one line there — both startup paths and the summary banner
read from it. `bash scripts/lib/test-select-apps.sh` covers the parsing, the
precedence rules and the prompt in about a second, with no cluster.

**No API key?** If you have a Claude Pro or Max subscription and are signed in
with Claude Code on this machine, run `bash scripts/sync-claude-subscription.sh`
instead of filling in a key. Every feature then routes through the subscription
and records tokens at zero cost. The credential rotates, so re-run the script
when agent runs start failing with `OAuth access token has been revoked`.

Ingress is off for local deploys (`ingress.enabled: false` in
`values-local.yaml`), so everything is reached over port forwards rather than
hostnames. Nothing needs to go in `/etc/hosts`.

| Service | URL |
|---|---|
| Abenix web | http://localhost:3000 |
| Abenix API | http://localhost:8000/docs |
| ContractIQ | http://localhost:3001 |
| Mideast Tourism | http://localhost:3002 |
| Industrial IoT | http://localhost:3003 |
| ResolveAI | http://localhost:3004 |
| ClaimsIQ | http://localhost:3005 |
| Wingman | http://localhost:3006 |
| PharmaVigil | http://localhost:3007 |
| Grafana | http://localhost:3030 (`admin` / `abenix-admin`) |
| Prometheus | http://localhost:9090 |

Sign in as `admin@abenix.dev` / `Admin123456`.

If port 3000 is already taken, deploy with `WEB_PORT=3100 bash scripts/deploy.sh local`.
Any port works — the deploy passes it through as the API's allowed CORS origin.
A port already in use is named rather than skipped, so you find out from the
deploy rather than from a page that will not load.
Forwards drop whenever a pod restarts, so `bash scripts/deploy.sh forwards` puts
them all back and prints which ones answer.

### Path B — partial — frontend dev against deployed backend

For UI-only work, faster turnaround:

```bash
# In one terminal: port-forward the cloud cluster's api
kubectl -n abenix port-forward svc/abenix-api 8000:8000

# In another: run web dev server pointing at it
cd apps/web
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

You get Next.js hot-reload but with real platform data. Caveat: any backend change requires path A.

---

## Required env vars

`.env` at repo root:

```bash
# LLM provider keys (at least one)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...

# Tool integrations (optional — without these, related tools degrade gracefully)
TAVILY_API_KEY=tvly-...
EIA_API_KEY=...
BRAVE_SEARCH_API_KEY=...
SERPAPI_API_KEY=...
NEWS_API_KEY=...
FRED_API_KEY=...
ALPHA_VANTAGE_API_KEY=...
MEDIASTACK_API_KEY=...
ENTSOE_API_KEY=...
AISSTREAM_API_KEY=...

# Postgres (auto-populated by deploy.sh local)
JWT_SECRET=local-dev-secret-change-in-prod
```

Anything missing degrades the corresponding tool — `tavily_search` returns "tool not configured" instead of crashing.

### Knowledge bases need an embedding key

`OPENAI_API_KEY` (or `AZURE_OPENAI_API_KEY` with `AZURE_OPENAI_ENDPOINT`) is the
one key that is not optional if you want knowledge search to work. Embeddings
have no fallback provider, so without it nothing can be ingested and nothing can
be searched.

`seed_kb.py` creates the collections and the agent grants but does **not** ingest
the documents — it prints a warning naming every collection it left empty. Until
you upload content through the Knowledge UI, or POST it to
`/api/knowledge/collections/{id}/documents`, an agent that calls
`knowledge_search` gets nothing back and says so in its answer. That affects
ClaimsIQ's policy matcher, ResolveAI, Industrial IoT and Wingman.

---

## Running tests

Unit (Python):
```bash
cd apps/api && pytest
cd apps/agent-runtime && pytest
```

Unit (TS):
```bash
cd apps/web && npm run test
```

End-to-end (Playwright):
```bash
# Run the audit-fixes spec against your local deployment.
# BASE and API default to localhost:3000 and localhost:8000, so pass them
# only if you deployed with WEB_PORT or API_PORT set.
USE_K8S=true npx playwright test e2e/uat_audit_fixes.spec.ts

# Same spec against a deploy that moved the web port
USE_K8S=true BASE=http://localhost:3100 npx playwright test e2e/uat_audit_fixes.spec.ts
```

See [05-testing](05-testing.md) for the full test catalogue.

---

## Useful kubectl shortcuts

```bash
alias k="kubectl -n abenix"

k get all
k logs -l app=abenix-api -f
k exec -it deploy/abenix-api -- python -c "import app.main; print('ok')"
k port-forward svc/grafana 3010:3000        # then visit localhost:3010
k port-forward svc/abenix-api 8000:8000
```

---

## Resetting

```bash
# Nuke the cluster, keep the code
minikube delete && bash scripts/deploy.sh local

# Or just reset DB
k exec -it sts/postgres -- psql -U abenix -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
k exec deploy/abenix-api -- alembic upgrade head
k exec deploy/abenix-api -- python /app/packages/db/seeds/seed_agents.py
```

---

## See also

- [01-add-a-tool](01-add-a-tool.md) — first thing to try once running
- [03-add-a-page](03-add-a-page.md) — first UI change
- [04-debugging](04-debugging.md) — when things don't work

---

## Source map

| What | Where |
|---|---|
| **Local dev launcher (docker-compose + uvicorn + agent-runtime + Next.js)** | [`scripts/dev-local.sh`](../../scripts/dev-local.sh) |
| **Minikube path (full helm chart on local k8s)** | [`scripts/dev-minikube.sh`](../../scripts/dev-minikube.sh) |
| **docker-compose data plane** | [`docker-compose.yml`](../../docker-compose.yml) |
| **Helm chart (full deploy)** | [`infra/helm/abenix/`](../../infra/helm/abenix/) |
| **Alembic migrations** | [`packages/db/alembic/versions/`](../../packages/db/alembic/versions/) |
| **Seed scripts** | [`packages/db/seeds/`](../../packages/db/seeds/) (agents, atlas, tool presets) |
| **Pre-push CI gate (run locally)** | [`scripts/check-before-push.sh`](../../scripts/check-before-push.sh) |
| **30-minute end-to-end onboarding** | [`ONBOARDING.md`](../../ONBOARDING.md) (top-level) |
