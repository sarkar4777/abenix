# CLI cheatsheet

Every script lives in `scripts/` and is run with `bash scripts/<name>.sh`. They
are idempotent unless the table says otherwise, so re-running after a failure is
the normal recovery path.

---

## Running the platform

### `deploy.sh` — Kubernetes (minikube or any cluster)

| Command | What it does |
|---|---|
| `deploy.sh local` | Full Helm chart on minikube, embedded execution. Builds every image into minikube's Docker daemon, installs KEDA when enabled, runs migrations and seeds, then sets up port forwards. |
| `deploy.sh local-runtime` | Same, but agents run in separate runtime pods instead of inside the API pod. Use this to reproduce production architecture. |
| `deploy.sh cloud` | Deploys to whatever `kubectl` context is current. |
| `deploy.sh build` | Builds the images only. No cluster changes. |
| `deploy.sh reload <service>` | Rebuilds one service and restarts just its deployment. Accepts `api`, `web`, `worker`, `agent-runtime`, `edge-runtime`, and `{contractiq,industrial-iot,resolveai,wingman,mideasttourism}-{api,web}`. Much faster than a full redeploy when iterating. |
| `deploy.sh forwards` | Re-establishes every port forward and prints which ones answer. Forwards die whenever a pod restarts, so reach for this before assuming something is broken. |
| `deploy.sh status` | Pod and service health. |
| `deploy.sh destroy` | Tears the deployment down. |

Environment overrides:

| Variable | Default | Why you would set it |
|---|---|---|
| `WEB_PORT` | `3000` | Something else already owns 3000 on your machine. |
| `API_PORT` | `8000` | Same, for the API. |
| `FRESH` | `false` | `FRESH=true` destroys and recreates the minikube VM. Wipes all cluster data. |
| `NAMESPACE` | `abenix` | Deploy into a different namespace. |
| `OBSERVABILITY` | `true` | Set `false` to skip Prometheus and Grafana and save about 600MB of RAM. |
| `IMAGE_TAG` | current git SHA | Pin a specific tag. |

### `dev-local.sh` — no Kubernetes

Runs Postgres and Redis in docker-compose, then the API, web and the five
standalone apps as local processes. Faster to iterate than the Helm path.

| Command | What it does |
|---|---|
| `dev-local.sh` | Starts everything. Logs land in `.local-logs/`. |
| `dev-local.sh --status` | Table of PID, port, health and log path per process. |
| `dev-local.sh --restart` | Stops and starts cleanly. |
| `dev-local.sh --stop` | Stops everything it started. |

### `dev-minikube.sh`

Wrapper around the minikube path that also keeps port forwards alive.

---

## Credentials and seeds

| Command | What it does |
|---|---|
| `sync-claude-subscription.sh` | Copies the Claude Code OAuth credential from `~/.claude/.credentials.json` into the platform, enables subscription mode and verifies it. Re-run when agent runs start failing with `OAuth access token has been revoked` — that token rotates. The value is never printed. |
| `seed-standalone-keys.sh` | Mints and patches each standalone app's platform API key, then restarts the affected deployments. Reuses a key that is still valid. Run it after the apps are deployed, not before, or their manifests overwrite what you just minted. |

---

## Testing

| Command | What it does |
|---|---|
| `check-before-push.sh` | Runs the exact gates CI runs. `--fast` skips the web build, `--python` and `--web` narrow it further. Use this before pushing rather than waiting for CI to go red. |
| `uat.sh` | The canonical browser UAT, in the order deploy-gating expects. |
| `run-e2e.sh --k8s <suite>` | Playwright suites against a deployed cluster. |
| `edge-smoke.sh` | Smoke test for the edge runtime. |

Playwright specs can also be run directly:

```bash
USE_K8S=true BASE_URL=http://localhost:3100 npx playwright test e2e/uat_abenix_browser.spec.ts
```

---

## Schema

| Command | What it does |
|---|---|
| `verify-alembic-graph.sh` | Fails if migrations declare duplicate revision IDs or leave more than one head. Runs in the Azure deploy as a pre-flight. |
| `verify-schema.sh` | Compares the live database against the ORM models. |
| `test-migration-locally.sh` | Exercises a migration against a scratch database before it reaches a real one. |

---

## Azure

| Command | What it does |
|---|---|
| `deploy-azure.sh provision` | Creates the resource group, ACR and AKS cluster. |
| `deploy-azure.sh build` | Builds and pushes images to ACR. |
| `deploy-azure.sh deploy` | Full path: provision, build, helm install, migrate, seed, smoke. |
| `deploy-azure.sh redeploy` | Re-runs the deploy against an existing cluster. Run it whole. A partial `--only=X` still rewrites the image tag on every pod, which cascades into `ImagePullBackOff`. See [deploy-only-trap](../06-deployment/deploy-only-trap.md). |
| `deploy-azure.sh seed` / `seed-keys` | Agent and knowledge seeds, or just the standalone API keys. |
| `deploy-azure.sh status` / `test` / `destroy` | Health, smoke test, teardown. |
| `portforward-azure.sh` | Brings the AKS deployment to `localhost:*`. Detects LoadBalancer IP drift. `restart` re-establishes them. |

---

## Release

| Command | What it does |
|---|---|
| `changelog-add.sh "message"` | Appends a line to `RELEASE_NOTES_PENDING.md`. |
| `publish-public.sh` | Bumps `VERSION`, folds the pending notes into the public `CHANGELOG.md`, syncs a scrubbed copy of the tree to the public mirror, commits, tags and pushes. Always pass `PUBLIC_REPO_URL`, and run with `DRY_RUN=1` first — the secret scan is the last gate before commit. `BUMP` takes `major`, `minor`, `patch` or `none`. |

---

## See also

- [08-howto/00-local-setup](../08-howto/00-local-setup.md) — first run, step by step
- [09-reference/01-env-vars](01-env-vars.md) — every environment variable
- [06-deployment/00-overview](../06-deployment/00-overview.md) — how the deploy paths differ
