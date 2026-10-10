# Local development setup

> From `git clone` to a running platform on your laptop. Path B (processes on your machine) is up in about ten minutes once dependencies are installed. Path A (full minikube cluster) takes 30 to 40 minutes on a cold machine.

---

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Docker Desktop | 24 or later | Both paths. Path A runs minikube on the Docker driver, path B runs the data stores in docker compose |
| Node.js | 20 or later (`engines` in `package.json`, CI uses 20) | Web app and the Node use-case apps |
| Python | 3.12 (the images and CI use 3.12, `dev-local.sh` also accepts 3.13) | API, runtime, worker, seeds and lints |
| kubectl | recent | Path A |
| Helm | 3.x | Path A |
| minikube | recent | Path A. `deploy.sh local` sizes it for the apps you pick, 8 GB for the core platform up to 13.25 GB for everything. Docker needs about 1 GB more, see [06-deployment/09-local-sizing](../06-deployment/09-local-sizing.md) |
| Java | 21 | Only for the ClaimsIQ use-case app on path B |

`deploy.sh` checks for `kubectl`, `helm`, `docker` and `minikube` before it does anything.

macOS:
```bash
brew install node@20 python@3.12 kubectl helm minikube
```
Install Docker Desktop from docker.com.

Linux: use your distro's package manager plus the official installers for Docker, kubectl, Helm and minikube.

Windows: run the scripts from Git Bash or WSL2, with Docker Desktop. `dev-local.sh` detects Git Bash and uses `netstat` and `taskkill` for its port checks.

---

## Three ways to run it

| Path | Script | What runs where | Use it for |
|---|---|---|---|
| A | `bash scripts/deploy.sh local` | Everything in minikube, same chart as AKS | Anything that touches deployment, scaling or the cluster |
| B | `bash scripts/dev-local.sh` | Data stores in docker compose. API, web, Celery and the NATS consumer as local processes with reload. The consumer's health port is 8020 (`CONSUMER_HEALTH_PORT`). A seed that fails prints its last lines, keeps its output in `.local-logs/seed-<name>.log` and is listed at the end of the seed step | Fast backend and UI iteration |
| C | `npm run dev` in `apps/web` | Only the web dev server, against an API you already have | UI-only work |

### Path A: full local k8s

```bash
git clone https://github.com/sarkar4777/abenix.git
cd abenix
cp .env.example .env             # fill in at least one LLM credential
bash scripts/deploy.sh local
```

This starts minikube if it is not running, builds every image into minikube's
Docker daemon, installs the Helm chart plus the use-case apps you picked, runs
migrations and seeds, then starts port forwards. Most of the time goes on image
builds. Later runs reuse the cluster and only rebuild what changed.

`bash scripts/deploy.sh` with no argument prints every subcommand. The ones you
will use most:

| Command | What it does |
|---|---|
| `deploy.sh local` | Install or upgrade on minikube |
| `deploy.sh local-runtime` | Same, with the `default`, `chat` and `heavy-reasoning` runtime pools |
| `deploy.sh status` | Pod and service health |
| `deploy.sh reload <svc>` | Rebuild one service, for example `api` or `web`, and restart it |
| `deploy.sh forwards` | Put the port forwards back and print which ones answer |
| `deploy.sh destroy` | Tear the release down |

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
run never waits on a question nobody is there to answer. A pipe or a CI job is
not a terminal, so it skips the prompt and starts them all.

**Scripting it.** `APPS` in the environment wins over the prompt and never
asks, which is what you want in CI or a Makefile:

```bash
APPS=none bash scripts/dev-local.sh                    # core platform only
APPS=pharmavigil,wingman bash scripts/dev-local.sh     # two apps
APPS=all bash scripts/deploy.sh local                  # everything, no prompt
APP_SELECT_TIMEOUT=60 bash scripts/dev-local.sh        # longer to decide
```

`APPS` means the same thing on both `dev-local.sh` and `deploy.sh local`. An
unknown name is reported and skipped.

The registry lives in [`scripts/lib/select-apps.sh`](../../scripts/lib/select-apps.sh).
Adding an app is one line there. Both startup paths and the summary banner
read from it. `bash scripts/lib/test-select-apps.sh` covers the parsing, the
precedence rules and the prompt in about a second, with no cluster.

**No API key?** If you have a Claude Pro or Max subscription and are signed in
with Claude Code on this machine, run `bash scripts/sync-claude-subscription.sh`
instead of filling in a key. Every feature then routes through the subscription
and records tokens at zero cost. The credential rotates, so run the script again
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
| Grafana | http://localhost:3030 (`admin` and the password in secret `abenix-grafana-admin`, `abenix-admin` unless `GRAFANA_ADMIN_PASSWORD` was set when it was created) |
| Prometheus | http://localhost:9090 |

`deploy.sh local` installs Grafana and Prometheus by default.
`OBSERVABILITY=false` skips them and saves about 600 MB of memory.

### Default logins

`packages/db/seeds/seed_users.py` creates two accounts on every deploy and on
every `dev-local.sh` start:

| Email | Password | Role |
|---|---|---|
| `admin@abenix.dev` | `Admin123456` | admin |
| `demo@abenix.dev` | `Demo123456` | user |

Change them before anyone else can reach the instance.

If port 3000 is already taken, deploy with `WEB_PORT=3100 bash scripts/deploy.sh local`.
`API_PORT` moves the API forward the same way. The deploy passes the web port
through as the API's allowed CORS origin. A port already in use is named rather
than skipped, so you find out from the deploy rather than from a page that will
not load. Forwards drop whenever a pod restarts, so `bash scripts/deploy.sh forwards`
puts them all back and prints which ones answer.

### Path B: processes on your machine

```bash
bash scripts/dev-local.sh             # start, cleans up anything left on its ports first
bash scripts/dev-local.sh --status    # PID, port and health per service, exit 1 if any is down
bash scripts/dev-local.sh --restart
bash scripts/dev-local.sh --stop
```

It runs `docker compose up -d`, which starts every service in
`docker-compose.yml`: Postgres (5432), Redis (6379), NATS (4222), mosquitto
(1883), TimescaleDB (5433), Neo4j (7474 and 7687), MinIO (9000), pgAdmin (5050)
and the three edge runtimes (8088 to 8090). It then installs npm and pip
dependencies when they are missing, runs migrations, seeds agents, accounts,
portfolio schemas and sample ML models, and launches:

| Process | Port | Notes |
|---|---|---|
| API, `uvicorn --reload` | 8000 | `DEBUG=true`, `IS_LOCAL_DEV=1`, `ENVIRONMENT=local`, `PGSSLMODE=disable` |
| Web, `next dev` | 3000 | `apps/web/.env.local` is created with `NEXT_PUBLIC_API_URL=http://localhost:8000` if missing |
| Celery worker | | `--pool=solo`, queues `documents,cognify` |
| NATS consumer, `consumer.py` | health on 8002 | `RUNTIME_MODE=remote`, pool `default` |

It exports `QUEUE_BACKEND=nats`, `SCALING_EXEC_REMOTE=true`, `NATS_USER=abenix`,
`NATS_PASSWORD=abenix-dev`, `MQTT_URL` and `TSDB_URL` unless you set them, and
reads the rest from `.env`. File-writing tools get data directories under
`.data/`. Logs go to `.local-logs/<service>.log` (`abenix-api.log`,
`abenix-web.log`, `celery.log`, `consumer.log`), or to `$LOG_DIR` if you set it.
Before it starts it stops any `kubectl port-forward` it finds, so a forward to a
cluster cannot shadow the local ports.

The start fails early, with the fix printed, when Docker is not running, when
the vendored SDK copies have drifted (`bash scripts/sync-sdks.sh` fixes that), or
when the schema is still missing columns after migrations.

### Path C: frontend against a running backend

```bash
# backend in minikube
bash scripts/deploy.sh forwards
# or backend on AKS
bash scripts/portforward-azure.sh

cd apps/web
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Both scripts forward the API to `localhost:8000`. Start forwards only through
these scripts so they can be listed and stopped as a set. You get Next.js hot
reload with real platform data. Any backend change needs path A or B.

---

## Required env vars

`.env` at repo root, copied from `.env.example`:

```bash
# LLM provider keys (at least one)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...

# Tool integrations (optional, the tools that need them say so when they are missing)
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
everyone out. Set `JWT_PRIVATE_KEY` and `JWT_PUBLIC_KEY` in `.env` to avoid
that, see [09-reference/06-signing-keys](../09-reference/06-signing-keys.md) for
how to make a pair. `.env.example` lists the rest.

A missing tool key does not crash anything. The tool answers that it is not
configured and names the key, and an admin can add it later under
**Admin -> Tool Configuration**, see [01-add-a-tool](01-add-a-tool.md).

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

The quickest way to run what CI runs, before you push:

```bash
bash scripts/check-before-push.sh           # everything
bash scripts/check-before-push.sh --fast    # skip the web build
bash scripts/check-before-push.sh --python  # Python gates only
```

The pieces on their own, from the repo root:

```bash
python -m pytest tests/unit/ -q                    # unit tests, no services needed
python -m pytest -q apps/agent-runtime/tests       # runtime tests
npm run test --workspace=apps/web                  # web unit tests (vitest)
```

`apps/api/tests` talks to a real Postgres through the API's `DATABASE_URL`, so
run it with path B up.

End-to-end (Playwright), against a running stack:

```bash
# BASE and API default to localhost:3000 and localhost:8000 in this spec,
# so pass them only if you moved the ports
USE_K8S=true npx playwright test e2e/uat_audit_fixes.spec.ts

# Same spec against a deploy that moved the web port
USE_K8S=true BASE=http://localhost:3100 npx playwright test e2e/uat_audit_fixes.spec.ts
```

`USE_K8S=true` stops Playwright from starting its own web server. Defaults
differ between specs, so read the header of the one you run. See
[05-testing](05-testing.md) for the full catalogue.

---

## Useful kubectl shortcuts

```bash
alias k="kubectl -n abenix"

k get all
k logs -l app.kubernetes.io/name=api -f
k logs -l abenix.io/pool=default -f            # one runtime pool
k exec -it deploy/abenix-api -- python -c "import app.main; print('ok')"
```

Grafana is forwarded to http://localhost:3030 by `deploy.sh`. For any forward
that dropped, run
`bash scripts/deploy.sh forwards` rather than starting one by hand.

---

## Resetting

```bash
# Delete the cluster and build it again, keeps your working tree
FRESH=true bash scripts/deploy.sh local

# Or reset only the database, then let the deploy rebuild schema and seeds
k exec abenix-postgresql-0 -- bash -c \
  'PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -d abenix -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
bash scripts/deploy.sh local
```

The API pod's `db-migrate` init container runs `python -m bootstrap`,
`alembic upgrade heads` and `python -m bootstrap verify` from `/app/packages/db`
on every start, and the deploy runs every seed again. For path B,
`dev-local.sh` runs the migrations itself. If its schema check fails on a fresh
local database, `bash scripts/verify-schema.sh --reset` drops and rebuilds it,
which deletes all data.

---

## See also

- [07-finding-your-way-around](07-finding-your-way-around.md), a tour of the console once you are signed in
- [01-add-a-tool](01-add-a-tool.md), the first thing to try once running
- [03-add-a-page](03-add-a-page.md), the first UI change
- [04-debugging](04-debugging.md), when things do not work

---

## Source map

| What | Where |
|---|---|
| **Local dev launcher (docker compose + uvicorn + Celery + NATS consumer + Next.js)** | [`scripts/dev-local.sh`](../../scripts/dev-local.sh) |
| **Minikube deploy (full Helm chart on local k8s)** | [`scripts/deploy.sh`](../../scripts/deploy.sh) |
| **Quick restart of an existing minikube demo** | [`scripts/dev-minikube.sh`](../../scripts/dev-minikube.sh) |
| **Use-case app registry and prompt** | [`scripts/lib/select-apps.sh`](../../scripts/lib/select-apps.sh) |
| **docker-compose data plane** | [`docker-compose.yml`](../../docker-compose.yml) |
| **Helm chart (full deploy)** | [`infra/helm/abenix/`](../../infra/helm/abenix/) |
| **Alembic migrations** | [`packages/db/alembic/versions/`](../../packages/db/alembic/versions/) |
| **Seed scripts** | [`packages/db/seeds/`](../../packages/db/seeds/) (agents, users, knowledge bases, atlas, tool defaults) |
| **Default accounts** | [`packages/db/seeds/seed_users.py`](../../packages/db/seeds/seed_users.py) |
| **Pre-push CI gate (run locally)** | [`scripts/check-before-push.sh`](../../scripts/check-before-push.sh) |
| **30-minute end-to-end onboarding** | [`ONBOARDING.md`](../../ONBOARDING.md) (top-level) |
