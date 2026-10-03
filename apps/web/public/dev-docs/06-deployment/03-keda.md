# KEDA autoscaling

> Each agent-runtime pool gets its own ScaledObject that scales on its queue backlog, with an optional latency trigger. Warm code runners get one ScaledObject each, scaling on runner load. Everything else uses plain HPAs.

---

## Why queue depth

A CPU HPA is the wrong signal for agent runs. A runtime pod can sit at 80% idle
CPU while hundreds of runs wait in its queue, because most of a run is spent
waiting on an LLM. KEDA reads the backlog and drives the HPA replica count from
that.

KEDA is installed by the deploy scripts. `deploy-azure.sh provision` and
`deploy` both run `ensure_keda`. `deploy.sh local` installs it when
`scaling.keda.enabled` is true in `values-local.yaml`, or when `KEDA_ENABLED=true`.
Both install the `kedacore/keda` chart into the `keda` namespace and skip it
when the CRDs already exist.

---

## Runtime pools

`templates/agent-runtime-pools.yaml` renders, for every entry in
`scaling.pools`, a Deployment and a Service named
`<release>-agent-runtime-<key>`, and a ScaledObject of the same name when
`scaling.keda.enabled` is true. Pods run `python3 consumer.py` with
`RUNTIME_POOL=<key>` and drain that pool's queue.

| Pool (Azure values) | min | max | Runs per replica | Queue trigger |
|---|---|---|---|---|
| `default` | 1 | 5 | 3 | 3 |
| `chat` | 0 | 3 | 6 | 3 |
| `heavy-reasoning` | 0 | 4 | 2 | 3 |
| `long-running` | 0 | 3 | 1 | 1 |

`values-local.yaml` ships only `default`, min 1, max 2.
`values-local-runtime.yaml` adds the other pools on minikube.

Agents pick a pool with `model_config.runtime_pool`. With
`scaling.execRemote` on, an agent whose pool is `inline` still runs in the API
process.

### The ScaledObject

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: abenix-agent-runtime-default
spec:
  scaleTargetRef:
    name: abenix-agent-runtime-default
  minReplicaCount: 1            # pool min_replicas, default 1
  maxReplicaCount: 5            # pool max_replicas, default 10
  pollingInterval: 15
  cooldownPeriod: 300
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown: {stabilizationWindowSeconds: 600, selectPolicy: Min, policies: [{type: Percent, value: 50, periodSeconds: 60}, {type: Pods, value: 1, periodSeconds: 60}]}
        scaleUp:   {stabilizationWindowSeconds: 0,   selectPolicy: Max, policies: [{type: Percent, value: 100, periodSeconds: 15}, {type: Pods, value: 4, periodSeconds: 15}]}
  triggers:
    - type: nats-jetstream
      metadata:
        natsServerMonitoringEndpoint: "abenix-nats.abenix.svc.cluster.local:8222"
        account: "A"
        stream: "agents"
        consumer: "abenix-default-consumer"
        lagThreshold: "3"       # pool keda_queue_trigger, default 3
    - type: prometheus           # only when scaling.keda.prometheusUrl is set
      metadata:
        serverAddress: http://abenix-prometheus.abenix.svc.cluster.local:9090
        metricName: abenix_execution_p95_ms
        query: histogram_quantile(0.95, sum by(le) (rate(abenix_execution_duration_seconds_bucket{pool="default"}[5m]))) * 1000
        threshold: "90000"
```

Pools need `scaling.queueBackend: nats`. The chart refuses to render them with
`celery`, since nothing consumes queued agent runs from Celery.

Tunables that matter:

- `keda_queue_trigger` per pool. Lower scales sooner. `long-running` uses 1 so a single queued job brings a pod up from zero.
- `min_replicas`. 0 saves money and costs a cold start on the first run.
- `concurrency_per_replica` becomes `AGENT_CONCURRENCY`, the runs one pod takes at once.

---

## Warm code runners

The agent-runtime creates one Deployment per tenant and asset version when an
asset is first called. With `codeRunners.keda.enabled` and a Prometheus URL it
also creates a ScaledObject:

| Field | Value |
|---|---|
| Trigger | `prometheus`, `sum(abenix_coderunner_load{runner="<name>"}) or vector(0)` |
| Threshold | `CODE_RUNNER_CONCURRENCY`, activation 0 |
| Min replicas | the warm floor, the larger of the tier floor, the asset's own `min_warm` and 1 while the asset is hot, capped at max |
| Max replicas | `CODE_RUNNER_MAX_REPLICAS` |
| Polling, cooldown | 10s, `CODE_RUNNER_IDLE_SECONDS` |

Without KEDA the runtime creates a CPU HPA at 70% instead, min 1. The
`<release>-code-runner-reaper` CronJob scales idle runners to zero and removes
old versions. Details in [02-runtime/16-warm-code-runners](../02-runtime/16-warm-code-runners.md).

---

## Everything else

The `api`, `web`, `worker` and `agent-runtime` subcharts each render a CPU HPA
from their `autoscaling` values. The cognify worker gets one when
`cognifyWorker.autoscaling.enabled` is true, off by default.

---

## Reading the scaling state

```bash
kubectl -n abenix get scaledobjects
kubectl -n abenix get hpa          # KEDA manages one HPA per ScaledObject
kubectl -n keda logs deploy/keda-operator --tail=50
```

The `/admin/scaling` page shows pool state without kubectl.

---

## Manual overrides

```bash
# pin a pool, KEDA paused
kubectl -n abenix annotate scaledobject abenix-agent-runtime-default autoscaling.keda.sh/paused=true
kubectl -n abenix scale deploy abenix-agent-runtime-default --replicas=4

# resume
kubectl -n abenix annotate scaledobject abenix-agent-runtime-default autoscaling.keda.sh/paused-
```

---

## Cost protection

`max_replicas` per pool caps the worst case. With the Azure values that is
5 + 3 + 4 + 3 = 15 runtime pods, plus `codeRunners.maxReplicas` per active
runner. Pools at min 0 cost nothing while idle.

---

## See also

- [00-overview](00-overview.md) — overall deploy flow
- [02-helm](02-helm.md) — the `scaling` and `codeRunners` values
- [02-runtime/08-queue-scaling](../02-runtime/08-queue-scaling.md) — how runs are queued
