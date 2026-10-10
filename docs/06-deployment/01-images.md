# Image build pipeline

## Two sets of Dockerfiles, and why that matters

There are two parallel definitions for the four core services:

| Path | Built by | Pushed to |
|---|---|---|
| `apps/<service>/Dockerfile` | GitHub Actions `build-images` job | `ghcr.io/<repo>/<service>:<sha>` |
| `docker/Dockerfile.<service>` | `scripts/deploy.sh` and `scripts/deploy-azure.sh` | minikube's Docker daemon, or ACR |

**`docker/Dockerfile.*` is what the cluster runs.** `deploy-azure.sh` maps
`api`, `web`, `worker` and `agent-runtime` to `docker/Dockerfile.<service>` in
its `DOCKERFILES` table. `deploy.sh` looks for `docker/Dockerfile.<service>`
first and falls back to `apps/<service>/Dockerfile` only when the first is
missing, which today is only the edge runtimes. The CI images are scanned and
published but no deploy script pulls them.

They are not generated from one another. A change to one does not reach the
other, and the two have drifted before: `docker/Dockerfile.api` carried
`COPY infra/use_cases_catalog.json` for months while the CI file did not, so the
published image answered "No use cases available" while a locally built one
worked.

**When you change what goes into an image, change both.** CI runs
`scripts/check-dockerfile-hardening.py`, which checks that both sets keep their
base tags unpinned and upgrade OS packages, and `scripts/check-docker-context.py`,
which fails on a `COPY` of a gitignored path. Neither compares what the two
sets copy or how they start.

The two sets already start differently:

| Image | `docker/` (cluster) | `apps/` (CI) |
|---|---|---|
| api | `uvicorn --workers ${API_WORKERS:-2} --timeout-keep-alive ${API_KEEPALIVE_SECONDS:-75}`, `PROMETHEUS_MULTIPROC_DIR=/tmp/prom-multiproc` emptied on start | 4 workers, sets `PROMETHEUS_MULTIPROC_DIR=/tmp/prom-multiproc` |
| worker | `celery ... --concurrency=2 -Q documents,cognify,agents` | `--concurrency=${CELERY_CONCURRENCY}` (8) `-Q ${CELERY_QUEUES}` (`documents`) |
| web | build arguments `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_APP_URL`, `NEXT_PUBLIC_ENABLE_MONETIZATION`, `NEXT_PUBLIC_AUDIT_NATIVE`, `NEXT_PUBLIC_GRAFANA_URL`. Empty means the code default | accepts `NEXT_PUBLIC_GRAFANA_URL` and `NEXT_PUBLIC_TEMPO_URL` |

Both API images run Prometheus multi-process mode, so each scrape of
`/api/metrics` sums all workers.

The web `NEXT_PUBLIC_*` values are fixed when the image is built. `deploy.sh`
and `deploy-azure.sh` pass each one set in `.env` or the shell as a build
argument. Changing one means rebuilding the web image, setting it on the
running Deployment does nothing.

### Code runner images

`apps/code-runner/Dockerfile.python` and `Dockerfile.node` build
`code-runner-python` and `code-runner-node`, with `apps/code-runner` as the
build context. `deploy.sh` builds one image per `Dockerfile.<lang>` it finds
there, and `deploy-azure.sh` lists both in `DOCKERFILES`. The chart's
`codeRunners.pools` maps a language family to one of these images. Only
`python-3.12` is mapped in the shipped values.

The standalone apps have a single Dockerfile each, beside their source
(`contractiq/api/Dockerfile`, `wingman/api/Dockerfile`, and so on).

---

## Shape of a service image

The four core images are multi-stage and follow the same pattern:

```dockerfile
FROM python:3.12-slim AS deps
COPY apps/api/pyproject.toml /tmp/api.toml      # dependency manifests only
RUN pip install ...                              # cached unless deps change

FROM python:3.12-slim
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY apps/api/ ./apps/api/                       # source last, changes most
```

Only the manifests go into the `deps` stage, so editing source does not
reinstall dependencies. The build context is always the repository root, which
is why every `COPY` is written as a repo-relative path.

The web image uses the Next.js standalone output, so the runtime layer carries
only `.next/standalone` plus static assets rather than `node_modules`.

---

## What each image needs beyond its own source

The API image is the awkward one. Its `PYTHONPATH` is
`/app/packages/db:/app/packages/sdk/python:/app/apps/agent-runtime`. It carries
the agent-runtime engine (agents execute in-process in embedded mode), the
shared DB package, the Python SDK, the
use-cases catalogue the UI reads at runtime, and the sample ML models and code
assets (`aimodels/` plus each app's `aimodels/`, `ml-models/` and
`code-assets/`) so `seed_ml_models.py` and `seed_code_assets.py` find them at
boot.
Leave one out and the symptom is a runtime "not found", not a build failure.

`agent-runtime` and `worker` both copy all of `apps/agent-runtime/`, so anything
new under `engine/` is picked up automatically. The `agent-runtime` image also
copies a few API modules (`execution_state.py`, `failure_codes.py`,
`telemetry.py`, `connector_presets.py`, `crypto.py`) and the ContractIQ,
Wingman and Industrial IoT code assets. A new import from `apps/api` in the
consumer needs a matching `COPY`.

---

## The .dockerignore negation

`.dockerignore` excludes `infra` wholesale, then negates one file:

```
infra
!infra/use_cases_catalog.json
```

Order matters. The negation has to come after the directory exclude or the
catalogue never reaches the build context and the `COPY` fails. `.env*` is
excluded with no exception, so no env file reaches an image.

---

## Tagging

Both scripts tag with the short git SHA (`IMAGE_TAG`, overridable) and also
apply `:latest`. `deploy-azure.sh` builds with `docker buildx --platform=linux/amd64 --push`.

The SHA is the same for uncommitted edits, so rebuilding after a code change
produces a new image under a tag Kubernetes already believes it has. With
`pullPolicy: Never` on minikube the new image is used only after the pod
restarts. `deploy.sh reload <service>` rebuilds, points the Deployment and any
init container built from the same image (the API's `db-migrate`) at the new
image, and restarts it. A plain `helm upgrade` with an unchanged tag will not
restart anything.

---

## Edge runtime images

`apps/edge-runtime/`, `edge-runtime-rust/` and `edge-runtime-c/` each carry a
self-contained Dockerfile, built with their own directory as the context.

- **Local.** `deploy.sh` builds `edge-runtime` on every deploy, plus the Rust or
  C image when `EDGE_RUNTIME_VARIANT` or `EDGE_RUNTIME_ALL_VARIANTS` asks for
  it, tags it with the SHA and installs the gateway from
  `localhost:5000/abenix/<variant>`.
- **AKS.** `deploy-azure.sh` never builds them. Its edge releases pull
  `<acr>/abenix/<variant>` at the version pinned in each chart's `values.yaml`,
  currently `1.1.0`. Push a new image to ACR by hand, then set
  `EDGE_IMAGE_TAG`. Passing the git SHA instead leaves the pods in
  `ImagePullBackOff`, because no such image was ever pushed.

---

## Supporting images

| Image | Source | Purpose |
|---|---|---|
| `postgresql-pgvector` | `infra/docker/Dockerfile.postgres-pgvector` | Postgres with the `vector` extension. `deploy.sh` builds it locally as `localhost:5000/abenix/postgresql-pgvector:16` because the chart default points at a private registry. |
| `model-serving` | `docker/Dockerfile.model-serving` | One pod per deployed ML model. |
| MCP fixtures | `e2e/fixtures/mcp_server/Dockerfile` and `Dockerfile.custom` | The in-cluster MCP servers `uat-mcp` and `custom-mcp` that `scripts/uat.sh` brings up. |

---

## Scanning

The CI `build-images` job runs Trivy after each push, once as a readable table
and once as SARIF uploaded to GitHub code scanning. Both are informational and
`exit-code: 0`, so a CVE does not fail the build. The gate that does block is
`pip-audit` in `python-lint`, which reads `.pip-audit-ignore`. Every entry there
needs a written justification.

---

## See also

- [00-overview](00-overview.md) — the deployment paths
- [02-helm](02-helm.md) — the chart and its values
- [09-reference/02-cli](../09-reference/02-cli.md) — build and reload commands
