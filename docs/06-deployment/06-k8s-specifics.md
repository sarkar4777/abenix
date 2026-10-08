# Kubernetes specifics

> What the chart and the deploy scripts create in the `abenix` namespace, how it is wired, and the gotchas. Read after [02-helm](02-helm.md).

---

## Resource inventory

With the Azure values and every standalone app selected, the namespace holds:

| Kind | Objects |
|---|---|
| Deployments from subcharts | `abenix-api`, `abenix-web`, `abenix-worker`, `abenix-agent-runtime` |
| Deployments from the umbrella chart | `abenix-agent-runtime-<pool>` per `scaling.pools` entry, `abenix-cognify-worker`, `abenix-alertmanager` |
| StatefulSets | `abenix-postgresql`, `abenix-redis-master`, `abenix-neo4j`, `abenix-nats` (NATS backend only) |
| Separate Helm releases | `abenix-mosquitto`, `abenix-timescaledb`, the edge runtime, LiveKit |
| Plain manifests | Prometheus, Grafana and Tempo from `infra/observability/`, each standalone app from `<app>/k8s/<app>.yaml` |
| Created at run time | One Deployment, Service and scaler per warm code runner, one Job per one-off sandbox run, one Pod per deployed ML model |
| ScaledObjects | One per runtime pool when `scaling.keda.enabled`, one per warm runner when `codeRunners.keda.enabled` |
| HPAs | `api`, `web`, `worker`, `agent-runtime` subcharts, plus KEDA's own |
| PodDisruptionBudgets | `minAvailable: 1` for api, web, agent-runtime and the cognify worker, each only when it runs more than one replica |
| CronJobs | `abenix-code-runner-reaper`, `abenix-pg-backup` and `abenix-neo4j-backup` when backups are on |
| PVCs | Postgres, Redis, Neo4j, NATS, `abenix-shared-data`, `ml-models-storage`, `abenix-archives` |
| Ingress | `abenix-ingress`, applied by `deploy-azure.sh` |

---

## Pod-to-pod networking

In-cluster traffic uses service DNS, `<service>.<namespace>.svc.cluster.local`.
Standalone apps reach the API at
`http://abenix-api.abenix.svc.cluster.local:8000` through `ABENIX_API_URL`.
There is no service mesh.

---

## Probes

| Workload | Probe | Path or command | Timing |
|---|---|---|---|
| api | startup, liveness, readiness | `GET /api/health` on 8000 | startup every 5s up to 30 tries, liveness from `health.initialDelaySeconds` (10) every 30s, readiness every 10s |
| web | same shape | `GET /` | |
| agent-runtime subchart | same shape | `GET /health` on 8001 | liveness delay 15s |
| runtime pools | readiness, liveness | `GET /health` on 8001 | readiness after 10s every 15s, liveness after 30s every 30s |
| worker, cognify worker | startup, liveness, readiness | `pgrep -f celery` | `celery inspect ping` was dropped because it goes through the broker and times out on a busy worker |
| NATS | readiness, liveness | `GET /healthz` on 8222 | |
| code runner gateway | readiness, liveness | `GET /healthz` on 9464 | |

`GET /api/health/ready` also exists on the API for load balancers that want a
readiness URL.

---

## Resource requests and limits

Defaults from the subchart and umbrella values. Overlays shrink them for
minikube.

| Workload | CPU req | CPU lim | Mem req | Mem lim |
|---|---|---|---|---|
| api (umbrella `values.yaml`) | 250m | 1 | 512Mi | 1Gi |
| web | 100m | 500m | 256Mi | 512Mi |
| worker | 250m | 1 | 256Mi | 1Gi |
| agent-runtime subchart | 500m | 2 | 512Mi | 2Gi |
| runtime pool (no `resources` set) | 200m | 1 | 512Mi | 1Gi |
| cognify worker | 250m | 1 | 256Mi | 1Gi |
| Postgres primary | 500m | 2 | 1Gi | 4Gi |
| Redis master | 250m | 1 | 1Gi | 4Gi |
| Neo4j | 250m | 1 | 512Mi | 2Gi |
| NATS | 100m | 500m | 256Mi | 512Mi |
| runner exec / gateway | 100m / 50m | 2 / 500m | 256Mi / 64Mi | 2Gi / 256Mi |

The Azure pools set their own, see `values-azure.yaml`.

---

## Persistent volumes

| Volume | Source | Default size | Notes |
|---|---|---|---|
| Postgres data | Bitnami chart | 50Gi (`values.yaml`), 5Gi local | `managed-premium` in the base values |
| Redis data | Bitnami chart | 10Gi | |
| Neo4j data | neo4j subchart | 10Gi | |
| NATS data | `volumeClaimTemplates` in `nats-jetstream.yaml` | `nats.jetstream.fileStorage.size`, 5Gi when unset | |
| `abenix-shared-data` | `sharedData.usePVC` | 20Gi | RWX. `azurefile-csi` in the Azure values |
| `ml-models-storage` | `mlModels.enabled` | 5Gi | |
| `abenix-archives` | `archives.pvc.enabled` | 10Gi | Local storage mode only |
| `<release>-backup` | `backup.enabled` and `backup.persistentVolume.enabled` ([`backup-pvc.yaml`](../../infra/helm/abenix/templates/backup-pvc.yaml)) | `backup.persistentVolume.size`, 20Gi | Kept on uninstall. `accessMode` defaults to RWO, use RWX on multi-node clusters. Azure sets `azurefile-csi`, RWX, 50Gi |

### `sharedData.usePVC` — single-node vs multi-node `/data`

The api, worker and agent-runtime pods all read and write `/data` for uploads,
exports, code assets, the build cache and ML model files.

| Mode | Set with | When to use | Failure mode if wrong |
|---|---|---|---|
| hostPath | `sharedData.usePVC: false`, the default | Single node: minikube, k3d, one-box k3s | On several nodes each pod sees its own `/var/lib/abenix/data` and uploads vanish from the others |
| RWX PVC | `sharedData.usePVC: true` and an RWX `sharedData.storageClass` | AKS and any other multi-node cluster | The class has to be RWX. `azurefile-csi` is. `managed-premium` is RWO and fails to mount on the second pod |

Every pod that mounts the host path uses `sharedDataHostPath`
(`/var/lib/abenix/data`). An older pool template used a different path, so the
API wrote code assets where the runtime could not see them.

### Azure Files and `/data`

Azure Files is RWX but mounted over SMB, where `chmod` and `utime` fail.
`shutil.copy` and `shutil.copy2` call both. When writing under `/data` use
`shutil.copyfile` or plain `open(...).write(...)`. The seed scripts already do.

### Resizing a running PVC

Expansion works when the storage class allows it. Raise the size value and
`helm upgrade`. RWO volumes such as Postgres and Neo4j need the pod restarted
before the filesystem grows. Take a backup first.

---

## RBAC

| Object | Scope | Grants | Created by |
|---|---|---|---|
| `<release>-<namespace>-cluster-view` ClusterRole + binding | cluster | get, list, watch on nodes and namespaces, plus get and list on `metrics.k8s.io` nodes when metrics-server is there | The chart, when `clusterView.rbac.enabled` (default on) |
| `<release>-cluster-view` Role + binding | release namespace | get, list, watch on pods, events, PVCs, Deployments, ReplicaSets, StatefulSets, DaemonSets, HPAs and KEDA ScaledObjects, get on `pods/log`, and pod metrics. No secrets, no writes | The chart, when `clusterView.rbac.enabled` (default on) |
| `abenix-cluster-reader` ClusterRole + binding | cluster | get, list, watch on nodes, pods and PVCs for the `default` ServiceAccount in `abenix` | `deploy-azure.sh` applies `infra/k8s/abenix-cluster-reader.yaml`. The chart's cluster view role now covers it |
| `<release>-sandboxed-job-runner` Role + binding | `sandboxedJob.namespace` or the release namespace | Jobs, pods and logs, Deployments, Services, Secrets, HPAs and ScaledObjects for the `default` ServiceAccount | The chart, when `sandboxedJob.enabled` |

The cluster view roles feed the `/admin/cluster` page. Both bind
`clusterView.rbac.serviceAccount`, `default` unless the API runs as another
account. The metrics and KEDA rules render when helm sees those APIs at install
time. Set `clusterView.rbac.metrics` or `clusterView.rbac.keda` to `"true"` to
force them, for example under `helm template` or when KEDA lands after the
platform. With the roles off the page still loads, lists what it cannot read and
names the value to turn back on. The namespaced Role is what
lets the API and runtime create sandbox Jobs, warm runners and their scalers.

---

## Ingress

The chart's own `ingress.yaml` serves one host with `/api` to the API and `/`
to web, `proxy-body-size: 50m`, `proxy-read-timeout: 120`. Local values turn it
off.

On AKS, `deploy-azure.sh` installs ingress-nginx and applies `abenix-ingress`
with one host per surface under `<lb-ip>.nip.io`, `proxy-body-size: 100m` and
read and send timeouts of 600 seconds. There is no TLS or cert-manager in that
path. See [00-overview](00-overview.md#aks) for the host list.

---

## Network policies

Off by default, on in the production values. `networkPolicy.enabled: true`
renders the policies in
[`networkpolicy.yaml`](../../infra/helm/abenix/templates/networkpolicy.yaml).
"Platform egress" below means Postgres 5432, Redis 6379, Neo4j 7687, NATS 4222,
the API on 8000, agent-runtime on 8001, Tempo on 4317 and 4318, DNS, and outside
addresses on `networkPolicy.externalEgressPorts` with private ranges closed.

| Policy | Allows in | Allows out |
|---|---|---|
| api | ingress-nginx, and any pod in the namespace, on 8000 | Platform egress, the Kubernetes API, Prometheus 9090, Alertmanager 9093 |
| agent-runtime | api, agent-runtime, worker, cognify-worker and Prometheus on 8001 | Platform egress, the Kubernetes API |
| workers, cognify-worker | not restricted | Platform egress |
| web | ingress-nginx on 80 and 3000 | The API on 8000, DNS |
| postgresql-clients | Platform pods, the code runner reaper, backup jobs, pgpool, other Postgres pods, on 5432 | not restricted |
| redis-clients | Platform pods, the code runner reaper, other Redis pods, on 6379 | not restricted |
| neo4j | Platform pods and the Neo4j backup job on 7687 and 7474 | not restricted |
| nats | Platform pods and code runners on 4222, Prometheus on 8222. Rendered only when `scaling.queueBackend` is `nats` | not restricted |

| Value | Default | Notes |
|---|---|---|
| `networkPolicy.externalEgressPorts` | `[443]` | Outside ports platform pods may call. Add one only when a provider needs it |
| `networkPolicy.kubeApiServer.cidrs` | empty | API server addresses the api and runtime pods may call, for sandboxed jobs, code runners and model deployments. Empty adds no rule |
| `networkPolicy.kubeApiServer.ports` | `[443, 6443, 8443]` | |

The production values turn off the Bitnami Postgres and Redis subcharts' own
policies (`postgresql.primary.networkPolicy`, `postgresql.readReplicas.networkPolicy`,
`redis.networkPolicy`), since those admit every pod. The chart's
`*-clients` policies decide instead.

`codeRunners.networkPolicy` (on by default) adds separate policies for runner
pods: DNS, the API on 8000 and NATS on 4222 for all, outside addresses except
private ranges only for runners labelled `abenix.io/network: open`, and inbound
scrapes from Prometheus and KEDA on 9464. With `networkPolicy.enabled` the
chart also lets runners reach the API.

---

## Image pulls on AKS

`provision` runs `az aks update --attach-acr`. Without Owner rights that fails,
and the script creates a docker-registry Secret `acr-pull-secret` and patches
the default ServiceAccount to use it. The Bitnami Postgres ServiceAccount lists
`acr-pull-secret` too.

> **Trap** — swap ACRs and the attach has to run again.

---

## Common kubectl recipes

```bash
kubectl -n abenix get all

# logs from every api replica
kubectl -n abenix logs -l app.kubernetes.io/name=api -f --tail=100

# logs from one runtime pool
kubectl -n abenix logs -l abenix.io/pool=default --tail=200

kubectl -n abenix rollout status deploy/abenix-web
kubectl -n abenix rollout restart deploy/abenix-agent-runtime-default

kubectl -n abenix describe pod <pod>
kubectl -n abenix logs <pod> --previous
```

For port forwards use `scripts/deploy.sh forwards` locally and
`scripts/portforward-azure.sh` on AKS, so they can be listed and stopped as a
set.

---

## Node placement

Subcharts accept `nodeSelector` and `tolerations`. A pool entry with
`nodeAffinity: <name>` gets `nodeSelector: abenix.io/node-pool: <name>`. The
shipped values set none of these, so everything schedules anywhere.

---

## See also

- [00-overview](00-overview.md) — overall deploy flow
- [02-helm](02-helm.md) — chart structure
- [03-keda](03-keda.md) — autoscaling
- [05-edge-runtime](05-edge-runtime.md) — edge deployment
- [disaster-recovery](disaster-recovery.md) — backups and restores
