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

## Three ways to run it

| Path | Script | What runs where | Use it for |
|---|---|---|---|
| A | `bash scripts/deploy.sh local` | Everything in minikube, same chart as AKS | Anything that touches deployment, scaling or the cluster |
| B | `bash scripts/dev-local.sh` | Data stores in docker compose, API, web, Celery and the NATS consumer as local processes with reload | Fast backend and UI iteration |
| C | `npm run dev` in `apps/web` | Only the web dev server, against an API you already have | UI-only work |

### Path A — full local k8s

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

### Path B — processes on your machine

```bash
bash scripts/dev-local.sh             # start, self-heals anything left on its ports
bash scripts/dev-local.sh --status    # PID, port and health per service, exit 1 if any is down
bash scripts/dev-local.sh --restart
bash scripts/dev-local.sh --stop
```

It starts `docker compose` for Postgres (5432), Redis (6379), NATS (4222),
mosquitto (1883), TimescaleDB (5433), Neo4j, MinIO, pgAdmin and the three edge
runtimes from `docker-compose.yml`, installs npm and pip
dependencies when missing, runs migrations, then launches:

| Process | Port | Notes |
|---|---|---|
| API, `uvicorn --reload` | 8000 | `DEBUG=true`, `IS_LOCAL_DEV=1`, `ENVIRONMENT=local`, `PGSSLMODE=disable` |
| Web, `next dev` | 3000 | |
| Celery worker | | `--pool=solo`, queues `documents,cognify,agents` |
| NATS consumer, `consumer.py` | health on 8002 | `RUNTIME_MODE=remote`, pool `default` |

It exports `QUEUE_BACKEND=nats`, `SCALING_EXEC_REMOTE=true`, `NATS_USER=abenix`,
`NATS_PASSWORD=abenix-dev`, `MQTT_URL` and `TSDB_URL` unless you set them, and
reads the rest from `.env`. Logs go to `logs/<service>.log`. Before it starts it
stops any `kubectl port-forward` it finds, so a forward to a cluster cannot
shadow the local ports.

### Path C — frontend against a running backend

```bash
# backend in minikube
bash scripts/deploy.sh forwards
# or backend on AKS
bash scripts/portforward-azure.sh

cd apps/web
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Both forward the API to `localhost:8000`. Start forwards only through these
scripts so they can be listed and stopped as a set. You get Next.js hot reload
with real platform data. Any backend change needs path A or B.

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

```

`deploy.sh` reads `.env` and passes the provider and tool keys it knows into
`abenix-secrets` with `--set`. The database URL, Redis password and
`SECRET_KEY` for a local cluster come from `values-local.yaml`, not from
`.env`. `dev-local.sh` runs the API with `DEBUG=true`, which accepts the
default `SECRET_KEY` and mints throwaway JWT keys in process, so a restart logs
everyone out. Set `JWT_PRIVATE_KEY` and `JWT_PUBLIC_KEY` in `.env` if that
bothers you. `.env.example` lists the rest.

Anything missing degrades the corresponding tool — `tavily_search` returns "tool not configured" instead of crashing.

### Knowledge bases without an embedding key

With `OPENAI_API_KEY`, or `AZURE_OPENAI_API_KEY` with `AZURE_OPENAI_ENDPOINT`
or `AZURE_OPENAI_API_BASE`, documents are embedded with that provider. Without
one, the worker and the runtime fall back to a built-in hashed embedder in
`packages/db/local_embeddings.py`. It is lexical, not semantic. It finds the
chunk that contains the words you searched for, but will not connect synonyms.
`ABENIX_LOCAL_EMBEDDINGS=1` forces it even with a key, which gives an offline,
repeatable test run.

`seed_kb.py` creates the collections and grants, then chunks and embeds the
sample documents itself, so a seeded collection is searchable as soon as the
deploy finishes. A collection embedded one way has to be re-embedded before it
answers queries embedded the other way.

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
k logs -l app.kubernetes.io/name=api -f
k logs -l abenix.io/pool=default -f            # one runtime pool
k exec -it deploy/abenix-api -- python -c "import app.main; print('ok')"
```

Grafana is already forwarded to http://localhost:3030 by `deploy.sh`. For any
forward that dropped, run `bash scripts/deploy.sh forwards` rather than
starting one by hand.

---

## Resetting

```bash
# Nuke the cluster, keep the code
FRESH=true bash scripts/deploy.sh local

# Or just reset the database, then let the deploy rebuild schema and seeds
k exec abenix-postgresql-0 -- bash -c \
  'PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -d abenix -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
bash scripts/deploy.sh local
```

The API pod's `db-migrate` init container runs `python -m bootstrap` and
`alembic upgrade heads` from `/app/packages/db` on every start, and the deploy
runs every seed again. For path B, `dev-local.sh` runs the migrations itself.

---

## See also

- [01-add-a-tool](01-add-a-tool.md) — first thing to try once running
- [03-add-a-page](03-add-a-page.md) — first UI change
- [04-debugging](04-debugging.md) — when things don't work

---

## Source map

| What | Where |
|---|---|
| **Local dev launcher (docker compose + uvicorn + Celery + NATS consumer + Next.js)** | [`scripts/dev-local.sh`](../../scripts/dev-local.sh) |
| **Minikube deploy (full Helm chart on local k8s)** | [`scripts/deploy.sh`](../../scripts/deploy.sh) |
| **Quick restart of an existing minikube demo** | [`scripts/dev-minikube.sh`](../../scripts/dev-minikube.sh) |
| **docker-compose data plane** | [`docker-compose.yml`](../../docker-compose.yml) |
| **Helm chart (full deploy)** | [`infra/helm/abenix/`](../../infra/helm/abenix/) |
| **Alembic migrations** | [`packages/db/alembic/versions/`](../../packages/db/alembic/versions/) |
| **Seed scripts** | [`packages/db/seeds/`](../../packages/db/seeds/) (agents, atlas, tool presets) |
| **Pre-push CI gate (run locally)** | [`scripts/check-before-push.sh`](../../scripts/check-before-push.sh) |
| **30-minute end-to-end onboarding** | [`ONBOARDING.md`](../../ONBOARDING.md) (top-level) |
