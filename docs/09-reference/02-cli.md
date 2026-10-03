# CLI cheatsheet

There is no packaged `abenix` command. The CLI is the set of scripts in
`scripts/`, run with `bash scripts/<name>.sh` or `python scripts/<name>.py`.
They are idempotent unless the table says otherwise, so re-running after a
failure is the normal recovery path.

---

## Running the platform

### `deploy.sh` — Kubernetes (minikube or any cluster)

| Command | What it does |
|---|---|
| `deploy.sh local` | Full Helm chart on minikube, embedded execution. Builds every image into minikube's Docker daemon, installs KEDA when the chart enables it, runs migrations and seeds, then sets up port forwards. |
| `deploy.sh local-runtime` | Same, but agents run in separate runtime pods instead of inside the API pod. Use this to reproduce production architecture. |
| `deploy.sh cloud` | Deploys to whatever `kubectl` context is current. |
| `deploy.sh build` | Builds the images only. No cluster changes. |
| `deploy.sh reload <service>` | Rebuilds one service and restarts just its deployment. Accepts `api`, `web`, `worker`, `agent-runtime`, `edge-runtime`, `<app>-api` and `<app>-web` for the standalone apps, and `claimsiq`. The rollout drops that service's forward, run `forwards` after. |
| `deploy.sh forwards` | Re-establishes every port forward and prints which ones answer. Forwards die whenever a pod restarts, so reach for this before assuming something is broken. Needs minikube running. |
| `deploy.sh observability` | Installs only the Prometheus and Grafana stack from `infra/observability/`. |
| `deploy.sh status` | Pod and service health. |
| `deploy.sh destroy` | Tears the deployment down. |

Any other argument prints the usage.

Environment overrides:

| Variable | Default | Why you would set it |
|---|---|---|
| `APPS` | prompts, or all apps when there is no terminal | Comma-separated app keys or 1-based numbers, or `all` or `none`. Shared with `dev-local.sh`. |
| `WEB_PORT` | `3000` | Something else already owns 3000 on your machine. |
| `API_PORT` | `8000` | Same, for the API. |
| `FRESH` | `false` | `FRESH=true` destroys and recreates the minikube VM. Wipes all cluster data. |
| `NAMESPACE` | `abenix` | Deploy into a different namespace. |
| `RELEASE_NAME` | `abenix` | Helm release name. |
| `OBSERVABILITY` | `true` | Set `false` to skip Prometheus and Grafana and save about 600MB of RAM. |
| `KEDA_ENABLED` | the `keda.enabled` value in `values-local.yaml` | Force KEDA on or off. |
| `IMAGE_TAG` | current short git SHA | Pin a specific tag. |

LLM and data provider keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` and the rest) are read from `.env` at the repo root and passed to Helm as secrets.

### `dev-local.sh` — no Kubernetes

Runs `docker compose up -d` for the backing services in `docker-compose.yml`
(Postgres, Redis, Neo4j, NATS, MinIO and the rest), then the API, web, the
Celery worker, the consumer and the selected standalone apps as local
processes. `APPS` picks the apps, as for `deploy.sh`. Faster to iterate than
the Helm path.

| Command | What it does |
|---|---|
| `dev-local.sh` | Starts everything. If tracked ports are already in use it stops the old processes first. Logs land in `.local-logs/` (`LOG_DIR` overrides). |
| `dev-local.sh --status` | Table of PID, port, health and log path per process. Exits 1 if anything is down. |
| `dev-local.sh --restart` | Stops and starts cleanly. |
| `dev-local.sh --stop` | Stops everything it started. |
| `dev-local.sh --help` | Usage. |

Before starting it runs `sync-sdks.sh --check` and refuses to go on when a vendored SDK copy has drifted. `SKIP_SDK_SYNC_CHECK=1` skips that.

### `dev-minikube.sh`

Makes sure minikube is up, the pods are running and the port forwards are
active. `--status` only reports what is running.

### `livekit-dev.sh`

Local LiveKit server for meeting work, from `scripts/livekit-dev.yaml`. Subcommands `up`, `down`, `status` and `env` (prints the exports, use `eval "$(bash scripts/livekit-dev.sh env)"`).

---

## Credentials and seeds

| Command | What it does |
|---|---|
| `sync-claude-subscription.sh` | Copies the Claude Code OAuth credential from `~/.claude/.credentials.json` into the platform, turns on subscription mode and calls the verify endpoint. Re-run when agent runs start failing with `OAuth access token has been revoked`, because that token rotates. The value is never printed. `API_URL` points it at another API. |
| `seed-standalone-keys.sh [app]` | For each standalone app, keeps its platform API key if it is still active, otherwise mints a `can_delegate` key, patches `<app>-secrets` and restarts the deployment. Pass one app name to do just that one. Run it after the apps are deployed, not before, or their manifests overwrite what you just minted. |
| `sync-sdks.sh` | Copies the canonical Python SDK in `packages/sdk/python/abenix_sdk/` over every vendored copy. `--check` only reports drift and exits 1. |

---

## Testing

| Command | What it does |
|---|---|
| `check-before-push.sh` | Runs the gates CI runs. `--fast` skips the web build, `--python` and `--web` narrow it further. Use this before pushing rather than waiting for CI to go red. |
| `uat.sh` | The canonical browser UAT: sanity, deep and industrial specs in that order. Stops on the first failing spec. Needs forwards on 3000 and 8000. `BASE` and `API` override the URLs. |
| `run-e2e.sh [--k8s] [--headed] [sanity\|deep\|industrial\|all] [extra args]` | Playwright UAT specs. Checks `API_URL` and `BASE_URL` answer first. Anything else on the line goes to Playwright. |
| `edge-smoke.sh` | Edge runtime smoke test on minikube. Installs the chart, deploys a sample agent to the gateway and calls it. Needs `PLATFORM_URL` and `PLATFORM_TOKEN`. |
| `python scripts/test_all_agents.py` | Runs every OOB agent through the API on `localhost:8000` and reports which ones work. |

Playwright specs can also be run directly:

```bash
USE_K8S=true BASE_URL=http://localhost:3100 npx playwright test e2e/uat_abenix_browser.spec.ts
```

### Load

| Command | What it does |
|---|---|
| `python scripts/load/decision_load.py --base URL --token JWT --key KEY --concurrency N --seconds S [--publish-at T --publish-version V]` | Concurrent decision evaluations, with an optional publish in the middle of the run. `decision_load_setup.py` prepares the decision. |
| `python scripts/load/code_runner_bench.py --asset ID --api URL --token T --scenario all` | Cold versus warm code asset latency. Run it inside an agent-runtime pod. Scenarios are `cold`, `warm`, `zero`, `version` and `concurrency`. |
| `python scripts/load/middleware_bench.py [--requests 5000] [--concurrency 200]` | In-process benchmark of the API middleware stack. |

---

## Schema

| Command | What it does |
|---|---|
| `verify-alembic-graph.sh` | Fails if migrations declare duplicate revision IDs or leave more than one head. Runs in the Azure deploy as a pre-flight. |
| `verify-schema.sh` | Checks the live database has every sentinel column listed in `scripts/_schema-sentinels.sh`. Exits 1 on drift. `--pod=NAME` checks through `kubectl exec`. `--reset` drops, recreates and re-migrates the database and destroys all data. |
| `test-migration-locally.sh` | Starts a throwaway `pgvector/pgvector:pg15` container on port 55434, builds the schema from the ORM, stamps alembic to the parent of one migration and runs only that migration. The revision is hard-coded in the script (`a8b9c0d1e2f3`), so edit it for a new one. The container is removed on exit. |

---

## Code checks and generators

All exit non-zero on a problem, so they fit CI or a pre-commit hook.

| Command | What it does |
|---|---|
| `python scripts/lint-agent-seeds.py` | Validates every YAML under `packages/db/seeds/agents/` against the agent seed schema. |
| `python scripts/check-tool-config.py` | Fails when a tool reads the environment directly or reads a config key it does not declare in `config_fields`. |
| `python scripts/gen-tool-docs.py` | Regenerates `TOOL_DOCS` in `apps/web/src/lib/tool-docs.ts` from the runtime tools. `--check` exits 1 when the file is stale. |
| `python scripts/check-api-requirements.py` | Fails when `apps/api/requirements.txt` lacks a dependency `pyproject.toml` declares. |
| `python scripts/check-dockerfile-hardening.py` | Asserts every shipped Dockerfile patches its base image. |
| `python scripts/check-readme-images.py` | Every local image the README embeds must exist and be tracked by git. |
| `node scripts/validate-mermaid.mjs` | Parses every Mermaid block under `docs/` with the real mermaid library. |
| `sync-dev-docs.sh` | Copies `docs/` into `apps/web/public/dev-docs/` for the in-app viewer. Run it after editing docs. |

---

## Azure

`deploy-azure.sh <command> [flags]`. Settings come from `scripts/azure.env` and the environment.

| Command | What it does |
|---|---|
| `deploy-azure.sh provision` | Creates the resource group, ACR and AKS cluster, attaches ACR and fetches kubectl credentials. |
| `deploy-azure.sh build` | Runs `provision`, then builds and pushes images to ACR. |
| `deploy-azure.sh deploy` | Builds (unless `--skip-build`) and Helm-installs the platform and standalone apps. Safe to re-run. |
| `deploy-azure.sh redeploy` | Builds and deploys against an existing cluster. Run it whole. A partial `--only=X` still rewrites the image tag on every pod, which cascades into `ImagePullBackOff`. See [deploy-only-trap](../06-deployment/deploy-only-trap.md). |
| `deploy-azure.sh seed` / `seed-keys` | Agent, portfolio and ML model seeds plus the standalone API keys, or just the keys. |
| `deploy-azure.sh test` | Playwright suites against the AKS endpoints. `E2E_PROJECT` and `E2E_ONLY` narrow it. |
| `deploy-azure.sh status` | Cluster, pods, services, ingress and health endpoints. |
| `deploy-azure.sh destroy` | Removes the Helm release and namespace, then the cluster and resource group. `--keep-cluster` stops after the namespace. |
| `deploy-azure.sh all` | provision, build, deploy, seed, test. |
| `acr-build-all.sh` | Builds every image remotely in ACR, for when local BuildKit is wedged. |

`portforward-azure.sh` brings the AKS deployment to `localhost:*` and warns when the ingress LoadBalancer IP has drifted since the last start. Subcommands: `start` (default), `stop`, `restart`, `status`, `pods`, `open <app>`, `urls`. `--no-browser` stops it opening a browser.

---

## Release

| Command | What it does |
|---|---|
| `changelog-add.sh [--added\|--changed\|--fixed\|--removed\|--security] "message"` | Appends a bullet to `RELEASE_NOTES_PENDING.md` under that section, `Changed` by default. |
| `publish-public.sh` | Bumps `VERSION`, folds the pending notes into the public `CHANGELOG.md`, syncs a scrubbed copy of the tree to the public mirror, runs leak scans, commits, tags and pushes. Always pass `PUBLIC_REPO_URL`, and run with `DRY_RUN=1` first. `BUMP` takes `major`, `minor`, `patch` (default) or `none`. |
| `python scripts/merge-changelog.py CHANGELOG.md vX.Y.Z DATE notes.md` | Folds notes into an existing version's section. `publish-public.sh` uses it for a `BUMP=none` publish. |
| `python scripts/log-fixed-issues.py open --title T --problem P [--area A] [--label L]` | Opens an issue on the public repo for a bug. `close NUMBER --fix F --fixed-in COMMIT` closes it with how it was fixed. Passing a JSON file backfills a batch. |
| `python scripts/open-issue.py FILE.json --title T --problem P` | Opens one issue and records it in an issues file. |

---

## See also

- [08-howto/00-local-setup](../08-howto/00-local-setup.md) — first run, step by step
- [09-reference/01-env-vars](01-env-vars.md) — every environment variable
- [06-deployment/00-overview](../06-deployment/00-overview.md) — how the deploy paths differ
