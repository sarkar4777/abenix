# Helm chart structure

> One umbrella chart at `infra/helm/abenix/` deploys the platform core. Five local subcharts plus Bitnami Postgres and Redis come in as dependencies. Prometheus, Grafana and Tempo are plain manifests under `infra/observability/`, and the standalone apps are separate `kubectl apply` manifests.

---

## Chart tree

```
infra/helm/
├── abenix/                         ← umbrella chart, version 0.2.0
│   ├── Chart.yaml                  ← dependencies below
│   ├── values.yaml                 ← defaults
│   ├── values-local.yaml           ← minikube, used by deploy.sh local
│   ├── values-local-runtime.yaml   ← layered on values-local by deploy.sh local-runtime
│   ├── values-azure.yaml           ← AKS, used by deploy-azure.sh
│   ├── values-production.yaml      ← used by deploy.sh cloud
│   ├── templates/
│   │   ├── configmap.yaml          ← abenix-config, non-secret env
│   │   ├── secrets.yaml            ← abenix-secrets, secret env + generated passwords
│   │   ├── agent-runtime-pools.yaml← one Deployment + Service (+ ScaledObject) per scaling pool
│   │   ├── nats-jetstream.yaml     ← NATS StatefulSet when queueBackend is nats
│   │   ├── code-runners.yaml       ← runner NATS login, network policies, reaper CronJob
│   │   ├── cognify-worker-deployment.yaml
│   │   ├── alertmanager-*.yaml     ← Alertmanager Deployment, Service, ConfigMap
│   │   ├── prometheus-rules.yaml   ← alert rules as a ConfigMap
│   │   ├── scaling-alerts.yaml     ← pool scaling alerts as a ConfigMap
│   │   ├── slo-configmap.yaml
│   │   ├── shared-data-pvc.yaml    ← abenix-shared-data when sharedData.usePVC
│   │   ├── ml-models-pvc.yaml      ← ml-models-storage when mlModels.enabled
│   │   ├── archives-pvc.yaml
│   │   ├── sandboxed-job-rbac.yaml ← Role + RoleBinding for Jobs and runner Deployments
│   │   ├── cluster-view-rbac.yaml  ← read-only roles for the /admin/cluster page
│   │   ├── improvements-proof-pool.yaml ← proof worker Deployment (+ ScaledObject) when improvements.proofPool.enabled
│   │   ├── backup-cronjob.yaml
│   │   ├── backup-pvc.yaml
│   │   ├── networkpolicy.yaml
│   │   ├── pdb.yaml
│   │   ├── ingress.yaml
│   │   ├── servicemonitor.yaml
│   │   ├── api-deployment.yaml     ← empty, the api subchart owns the Deployment
│   │   └── _helpers.tpl
│   └── charts/                     ← packaged dependencies (.tgz)
├── api/  web/  worker/  agent-runtime/  neo4j/   ← subchart sources
├── mosquitto/  timescaledb/                      ← installed as their own releases
└── edge-runtime/  edge-runtime-rust/  edge-runtime-c/
```

| Dependency | Source | Notes |
|---|---|---|
| `api`, `web`, `worker`, `agent-runtime`, `neo4j` | `file://../<name>` | Deployment (StatefulSet for Neo4j), Service and HPA templates. `worker` has no Service. `agent-runtime` renders nothing when `agent-runtime.enabled` is `false`, as in the local and Azure values |
| `postgresql` 15.5.38 | Bitnami | Image is the pgvector build from `infra/docker/Dockerfile.postgres-pgvector` |
| `redis` 19.6.4 | Bitnami | |

Both deploy scripts run `helm dependency update` before every install, which
repacks `charts/*.tgz` from the subchart sources. That is why the tarballs show
as modified after a deploy. A plain `helm upgrade` without that step installs
whatever tarball is committed, so run `helm dependency update infra/helm/abenix`
first if you changed a subchart.

---

## values.yaml, the parts you will change

Image repositories and tags are per subchart. The deploy scripts pass them with
`--set`, for example `api.image.repository`, `api.image.tag` and
`api.image.pullPolicy`, and the same for `web`, `worker`, `agent-runtime` and
`cognifyWorker`.

| Key | Default | What it does |
|---|---|---|
| `environment` | `production` | `ENVIRONMENT`. `DEBUG` is `false` only when this is `production` |
| `agent-runtime.enabled` | unset (on) | `false` drops the single `abenix-agent-runtime` Deployment and Service. The runtime pools replace it |
| `web.service.port` / `web.containerPort` | `3000` / `3000` (subchart) | Service port, and the port the Next.js image listens on. The container port is named `http` and the probes and the Service `targetPort` use the name, so changing `service.port` alone cannot break the pod. The chart ingress sends `/` to `web.service.port` |
| `cognifyWorker.enabled` / `queue` / `concurrency` | `true` / `cognify` / `2` | The `abenix-cognify-worker` Deployment, on the `worker` image |
| `features.marketplace` / `monetization` | `true` / `false` | `MARKETPLACE_ENABLED` / `MONETIZATION_ENABLED` defaults. The value an admin stores wins |
| `logLevel` | `info` | `LOG_LEVEL` |
| `runtimeMode` | `embedded` | `RUNTIME_MODE`. `remote` hands runs to the runtime pods |
| `frontendUrl` | `http://localhost:3000` | `FRONTEND_URL` |
| `corsOrigins` | `["http://localhost:3000"]` | `CORS_ORIGINS` |
| `databaseName` | `abenix` | Backup target database |
| `objectStorage.type` | `local` | `STORAGE_BACKEND`. `s3` or `azure` adds the bucket or container env and secrets |
| `objectStorage.uploadDir` / `exportDir` / `mlModelsDir` / `codeAssetStore` / `codeAssetBuildCache` / `trajectoryDir` | under `/data` | The matching path variables |
| `sharedData.usePVC` / `storageClass` / `storageSize` | `false` / empty / `20Gi` | `true` mounts the RWX claim `abenix-shared-data` at `/data` instead of the host path |
| `sharedDataHostPath` | `/var/lib/abenix/data` | Host path behind `/data` on single-node clusters |
| `mlModels.enabled` | `false` | Creates `ml-models-storage` and mounts it on the runtime pools |
| `mlModels.servingImage` | `""` | `ML_MODEL_SERVING_IMAGE`, falls back to the local registry image |
| `archives.pvc.enabled` | `false` | Archive claim, local storage mode only. Pair with `api.archivesPVC.enabled` |
| `clusterView.rbac.enabled` / `serviceAccount` / `metrics` / `keda` | `true` / `default` / `""` / `""` | Read-only ClusterRole and Role for the `/admin/cluster` page, see [06-k8s-specifics](06-k8s-specifics.md#rbac). `metrics` and `keda` set to `"true"` force those rules when helm cannot see the APIs |
| `sandboxedJob.enabled` / `allowNetwork` / `allowedImages` / `namespace` | `"true"` / unset / list / `""` | `SANDBOXED_JOB_*`. `enabled` also renders the RBAC |
| `meeting.livekit.url` / `meetUrl`, `meeting.ttsVoice`, `meeting.deferNotifyWebhookUrl` | | LiveKit and meeting tool env |
| `progress.channelPrefix` / `parentKeyPrefix` / `parentTtl` | `progress:` / `parent:` / `1800` | `PROGRESS_*` |
| `postProcessorModules` | `""` | `POST_PROCESSOR_MODULES` |
| `secrets.sso.*` | `""` | SSO provider ids, secrets and the Microsoft tenant, written to `abenix-secrets` only when set. See [05-sso](../09-reference/05-sso.md#kubernetes) |
| `mcpAllowedHosts` | `""` | `MCP_ALLOWED_HOSTS`. Empty falls back to `uat-mcp.<namespace>.svc.cluster.local` |
| `eventsAllowedInternalHosts` | `""` | `EVENTS_ALLOWED_INTERNAL_HOSTS`. Exact host names outbound webhooks may save and call although they are cluster-internal or resolve to private addresses |
| `pinecone.indexName` | `abenix` | `PINECONE_INDEX_NAME`. The template falls back to `agentforge-knowledge` only when this is empty |
| `azureEmbeddingDeployment` | `text-embedding-3-small` | `AZURE_EMBEDDING_DEPLOYMENT` |
| `streaming.*` | release hosts, `abenix` / `abenix` / `abenix_tsdb` | Builds `MQTT_URL` and `TSDB_URL` |
| `edge.allowUnsigned` | `false` | `EDGE_ALLOW_UNSIGNED` on the API |
| `ingress.enabled` / `className` / `host` / `tls.*` | `true` / `nginx` / `app.abenix.io` | One host, `/api` to the API, `/` to web. Local values turn it off. `deploy-azure.sh` applies its own `abenix-ingress` instead |
| `networkPolicy.enabled` | `false` | Per-service allow lists, see [06-k8s-specifics](06-k8s-specifics.md#network-policies). On in the production values |
| `networkPolicy.externalEgressPorts` | `[443]` | Outside ports platform pods may call |
| `networkPolicy.kubeApiServer.cidrs` / `ports` | empty / `[443, 6443, 8443]` | Kubernetes API server addresses the api and runtime pods may reach. Empty adds no rule |
| `backup.enabled` | `false` | Daily `pg_dump` CronJob, plus the Neo4j APOC export with `backup.neo4j.enabled` |
| `backup.persistentVolume.enabled` / `storageClass` / `accessMode` / `size` | `false` / empty / `ReadWriteOnce` / `20Gi` | Creates the `<release>-backup` PVC, kept on uninstall. Without it backups land in an `emptyDir`. See [disaster-recovery](disaster-recovery.md#backups) |
| `backup.s3Bucket` / `uploaderImage` | empty / agent-runtime image | With `objectStorage.type: s3`, the bucket the dump is uploaded to (empty uses `objectStorage.bucket`) and the `boto3` image that uploads it. Credentials come from `STORAGE_S3_ACCESS_KEY` / `STORAGE_S3_SECRET_KEY` in `abenix-secrets`, or the pod's cloud role when empty |
| `backup.neo4j.keep` / `image` | `7` / agent-runtime image | Neo4j exports kept, and the image the export runs in |
| `monitoring.enabled` | `false` | ServiceMonitors for clusters running the Prometheus operator |
| `alerting.*` | | Alertmanager and webhook settings, see [04-observability](04-observability.md) |

### Scaling and NATS

| Key | Default | What it does |
|---|---|---|
| `scaling.enabled` | `false` | Renders one runtime Deployment per entry in `scaling.pools` |
| `scaling.execRemote` | `false` | `SCALING_EXEC_REMOTE`. Needs `queueBackend: nats`, the render fails otherwise |
| `scaling.queueBackend` | `celery` | `QUEUE_BACKEND`. `nats` also renders the NATS StatefulSet and sets `NATS_URL` and `NATS_USER`. Queued agent runs only work on `nats`. `celery` still runs document, cognify and KB jobs |
| `scaling.agentRuntimeImage` | `{}` | Image for the pools and the runner reaper. Empty uses `agent-runtime.image` |
| `scaling.keda.enabled` | `false` | Adds a ScaledObject per pool. KEDA has to be installed |
| `scaling.keda.prometheusUrl` | unset | Adds a p95 latency trigger to each pool's ScaledObject |
| `scaling.alerts.enabled` | `false` | Renders `scaling-alerts.yaml` |
| `scaling.pools[]` | `[]` | `key`, `min_replicas`, `max_replicas`, `concurrency_per_replica`, `keda_queue_trigger`, `resources`, `nodeAffinity`. With `scaling.enabled` the render fails unless `queueBackend` is `nats` |
| `nats.cluster.replicas` | `1` | NATS StatefulSet replicas |
| `nats.jetstream.fileStorage.size` | `1Gi` | NATS volume size. The template falls back to `5Gi` when unset |

The keys `nats.enabled`, `nats.cluster.enabled` and `nats.jetstream.enabled`
exist in the values files but no template reads them. NATS is on exactly when
`scaling.queueBackend` is `nats`.

### Self-improvement proof pool

| Key | Default | What it does |
|---|---|---|
| `improvements.proofPool.enabled` | `false` | Renders `<release>-improvements-proof`, the API image running `python -m app.workers.improvements_proof`, and sets `IMPROVEMENTS_PROOF_DRAIN=pool`. Off, API pods prove fixes themselves (`api`) |
| `improvements.proofPool.minReplicas` / `maxReplicas` / `concurrency` | `0` / `4` / `2` | `concurrency` becomes `IMPROVEMENTS_PROOF_CONCURRENCY`. Without KEDA the Deployment runs at least one replica |
| `improvements.proofPool.keda.enabled` / `prometheusUrl` / `queueTrigger` | `false` / release Prometheus / `"3"` | ScaledObject on `max(abenix_improvement_proof_queue_depth)` |

No shipped overlay turns it on.

### Warm code runners

| Key | Default | What it does |
|---|---|---|
| `codeRunners.enabled` | `false` | Turns warm runners on. Fails the render unless `scaling.queueBackend` is `nats`. Off sets only `CODE_RUNNER_MODE=job` |
| `codeRunners.mode` | `auto` | `CODE_RUNNER_MODE` |
| `codeRunners.registry` / `imageTag` / `pullPolicy` | `""` (falls back to `localhost:5000/abenix`) / `latest` / `IfNotPresent` | `deploy-azure.sh` sets registry and tag to the ACR build |
| `codeRunners.pools[]` | `python-3.12` -> `code-runner-python` | Builds `CODE_RUNNER_IMAGES` |
| `codeRunners.concurrency` / `maxReplicas` / `idleSeconds` / `drainSeconds` / `graceSeconds` | `4` / `5` / `900` / `120` / `930` | |
| `codeRunners.minWarmByTier` / `hotCallsPerHour` / `defaultTier` | `low=0,medium=0,high=1,critical=1` / `30` / `medium` | |
| `codeRunners.fetchTokenTtl` / `apiUrl` | `21600` / `""` (release API service) | |
| `codeRunners.runtimeClassName` / `workspaceSize` / `scratchSize` | `""` / `2Gi` / `1Gi` | |
| `codeRunners.resources.exec` / `.gateway` | see values | JSON resources for the two containers |
| `codeRunners.networkPolicy` | `true` | Renders the `none` and `open` runner policies |
| `codeRunners.keda.enabled` / `prometheusUrl` | `false` / `""` | `CODE_RUNNER_KEDA` and `CODE_RUNNER_PROMETHEUS_URL` |
| `codeRunners.nats.user` / `password` | `coderun` / `""` | Runner NATS login. Empty password is generated on install and kept |
| `codeRunners.reaper.schedule` | `*/2 * * * *` | CronJob that drains old versions and scales idle runners to zero |

### Secrets

`secrets.*` feed `abenix-secrets`. The deploy scripts fill them with `--set`
from `.env`. Never commit real values.

| Key | Becomes | Notes |
|---|---|---|
| `databaseUrl` | `DATABASE_URL` | |
| `redisPassword` | part of `REDIS_URL` and `CELERY_*` | |
| `postgresPassword` | `POSTGRES_PASSWORD` | Bitnami admin password |
| `jwtSecret` | `SECRET_KEY` | Default `change-me` |
| `anthropicApiKey`, `openaiApiKey`, `googleApiKey`, `azureOpenaiApiKey`, `azureOpenaiApiBase`, `azureOpenaiApiVersion` | provider keys | |
| `claudeSubscriptionToken` | `CLAUDE_SUBSCRIPTION_TOKEN` | |
| `neo4jPassword` | `NEO4J_PASSWORD` | Default `abenix-neo4j-pass` |
| `pineconeApiKey`, `tavilyApiKey`, `braveSearchApiKey`, `serpapiApiKey`, `serperApiKey`, `searchProvider`, `newsApiKey`, `fredApiKey`, `alphaVantageApiKey`, `mediastackApiKey`, `entsoeApiKey`, `eiaApiKey`, `stripeSecretKey` | the matching variables | |
| `alertWebhookToken` | `ALERT_WEBHOOK_TOKEN` | Empty means generated once and kept |
| `natsPassword` / `natsSysPassword` | `NATS_PASSWORD` / `NATS_SYS_PASSWORD` | Empty means generated per install and kept on upgrade |
| `dataKeyKekBase64` | `ABENIX_DATA_KEY_KEK_BASE64` | Rendered only when set |
| `edgeSigningKeyPem` / `edgeSigningPubkeyPem` | `EDGE_SIGNING_KEY_PEM` / `EDGE_SIGNING_PUBKEY_PEM` | Rendered only when set. Scripts pass them with `--set-file` |
| `storageS3AccessKey` / `storageS3SecretKey` / `storageAzureConnectionString` | storage credentials | Rendered for the matching `objectStorage.type` |

### Generated passwords

`ALERT_WEBHOOK_TOKEN`, `NATS_PASSWORD`, `NATS_SYS_PASSWORD` and the runner
password in `<release>-code-runner-nats` are generated with `randAlphaNum` the
first time the chart renders. On later upgrades the template `lookup`s the live
Secret and reuses the value, so pods and NATS keep agreeing. Two consequences:

- `helm template` and `--dry-run` cannot see the live Secret, so they print a
  fresh random value each time. That output is not what the cluster holds.
- Deleting `abenix-secrets` by hand rotates all three on the next upgrade.
  Roll the API, runtime pools and NATS afterwards so they pick up the new
  values together.

---

## What the overlays change

`values-local.yaml`, used by `deploy.sh local`:

- `environment: development`, `logLevel: debug`, `runtimeMode: remote`
- images from `localhost:5000/abenix/*` with `pullPolicy: Never`, Postgres from the locally built pgvector image
- standalone Postgres and Redis, small resources, ingress off
- `agent-runtime.enabled: false`, so the runtime pools are the only runtime pods
- `scaling.enabled`, `execRemote`, `queueBackend: nats`, one `default` pool, KEDA on with the local Prometheus
- `codeRunners.enabled` with `maxReplicas: 2`, KEDA off so runners scale on CPU
- `mlModels.enabled`, `edge.allowUnsigned: true`, local secrets including `jwtSecret`

`values-local-runtime.yaml` is layered on top by `deploy.sh local-runtime`. It
adds the `chat` and `heavy-reasoning` pools, turns KEDA off and gives NATS a
2Gi volume.

`values-azure.yaml`, used by `deploy-azure.sh`:

- `environment: staging`, `runtimeMode: embedded`, but `scaling.execRemote: true` with `queueBackend: nats`, so agent runs go to the pools
- one replica each for api, web and worker, subchart HPAs off, `agent-runtime.enabled: false`, chart ingress off
- four pools `default` (min 1), `chat`, `heavy-reasoning` and `long-running` (min 0), KEDA and scaling alerts on
- `codeRunners.enabled` with KEDA on runner load, `pullPolicy: Always`
- `sharedData.usePVC` and `archives.pvc` on `azurefile-csi`, `backup.enabled`
- progress prefixes and post-processor modules for the standalone apps

`values-production.yaml` is what `deploy.sh cloud` uses against the current
kubectl context:

- `runtimeMode: remote` against the `agent-runtime` subchart (5 replicas), scaling pools off
- subchart HPAs on, Postgres `architecture: replication`, network policies and backups on
- chart ingress for `app.abenix.io` with TLS. Its `ingress.annotations` block is not read, the template hard-codes its own annotations
- `web.service.port` at the subchart's `3000`, the same as every other values file

---

## ConfigMap and Secret convention

Every core pod loads both with `envFrom`:

```yaml
envFrom:
  - secretRef:    {name: abenix-secrets}
  - configMapRef: {name: abenix-config}
```

The pool Deployments add a few explicit `env` entries on top, which win over
`envFrom`: `RUNTIME_POOL`, `RUNTIME_MODE=remote`, `QUEUE_BACKEND`,
`AGENT_CONCURRENCY`, the NATS login, `LIVEKIT_URL`, the `/data` paths,
`OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_TRACES_SAMPLER_ARG=1.0`. They do not
set `REDIS_URL`, so the authenticated one from the Secret is used.

Adding a variable:

1. Add it to `templates/configmap.yaml`, or to `templates/secrets.yaml` if it is sensitive.
2. Plumb it from a value in `values.yaml` so it can be overridden.
3. Pods pick it up on their next rollout. A ConfigMap change alone does not restart anything.

---

## Prometheus scraping

The cluster runs the plain Prometheus from `infra/observability/prometheus.yaml`,
not the operator. It scrapes the API at `/api/metrics`, every agent-runtime
service on port `http` at `/metrics`, and runner pods on their `metrics` port.
`monitoring.enabled` renders ServiceMonitors instead, for clusters that do run
the operator. Details in [04-observability](04-observability.md).

---

## Standalone-app manifests

Each app lives in `<app>/k8s/<app>.yaml` and is applied with `kubectl`, not
Helm. The deploy scripts substitute the image and tag before applying, and
create each app's Secret separately so values are never committed.

> **Why not Helm for the apps** — independent release cadences. An app fix should not require a platform Helm release.

---

## See also

- [00-overview](00-overview.md) — the deploy flow
- [03-keda](03-keda.md) — autoscaling
- [04-observability](04-observability.md) — Prometheus, Grafana, Tempo, Alertmanager
- [09-reference/01-env-vars](../09-reference/01-env-vars.md) — every variable the chart sets
