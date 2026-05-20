# KEDA autoscaling

> Four agent-runtime pools, each with its own KEDA ScaledObject reading NATS JetStream depth. Plus one for the cognify-worker on Redis queue depth.

---

## What KEDA does

Native Kubernetes HPAs scale on CPU/memory. That's wrong for our workload — an agent-runtime pod can have 80% idle CPU while sitting on a 500-message NATS backlog. We want to scale on **queue depth**.

KEDA bridges. It deploys a controller that watches external metrics (NATS, Redis, Kafka, Prometheus, etc.) and adjusts the underlying HPA replica count. To the cluster it looks like a regular HPA. the magic is in how the desired replica count is computed.

---

## The four runtime pools

```mermaid
flowchart LR
  N[NATS JetStream<br/>exec.{pool}.> subject]
  N --> SO1[ScaledObject<br/>runtime-default<br/>min=2 max=20]
  N --> SO2[ScaledObject<br/>runtime-chat<br/>min=1 max=10]
  N --> SO3[ScaledObject<br/>runtime-heavy<br/>min=1 max=4]
  N --> SO4[ScaledObject<br/>runtime-long-running<br/>min=1 max=2]
  SO1 --> D1[Deployment<br/>agent-runtime-default]
  SO2 --> D2[Deployment<br/>agent-runtime-chat]
  SO3 --> D3[Deployment<br/>agent-runtime-heavy-reasoning]
  SO4 --> D4[Deployment<br/>agent-runtime-long-running]
```

Each pool is a separate Deployment because:
- They have different resource footprints (the heavy pool wants 4Gi mem. the chat pool wants 512Mi).
- They have different timeouts (chat = 30s. long-running = 30min).
- An OOM in one pool shouldn't affect the others.

Agents choose their pool via `model_config.runtime_pool`.

---

## Sample ScaledObject

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: runtime-default
  namespace: abenix
spec:
  scaleTargetRef:
    name: agent-runtime-default
  minReplicaCount: 2
  maxReplicaCount: 20
  pollingInterval: 15       # check NATS every 15s
  cooldownPeriod: 300       # wait 5min after queue is empty before scaling down
  triggers:
  - type: nats-jetstream
    metadata:
      natsServerMonitoringEndpoint: http://nats:8222
      account: $G
      stream: exec
      consumer: runtime-default
      lagThreshold: "5"     # target: 1 replica per 5 pending messages
```

Tunables that matter:
- `lagThreshold` — lower = more aggressive scaling. Default 5 = roughly 1 replica per 5 pending messages.
- `cooldownPeriod` — don't scale down too quickly. a sudden empty queue might fill again.
- `pollingInterval` — how fast KEDA reacts. 15s is a good default. faster makes the cluster more reactive but more chatty.

---

## Reading the scaling state

```bash
kubectl -n abenix get scaledobjects
# NAME                       SCALETARGETKIND   SCALETARGETNAME            MIN  MAX  TRIGGERS         READY
# runtime-default            Deployment        agent-runtime-default      2    20   nats-jetstream   True
# runtime-chat               Deployment        agent-runtime-chat         1    10   nats-jetstream   True
# runtime-heavy-reasoning    Deployment        agent-runtime-heavy        1    4    nats-jetstream   True
# runtime-long-running       Deployment        agent-runtime-long-running 1    2    nats-jetstream   True
```

```bash
kubectl -n abenix get hpa
# Shows the actual HPA KEDA manages — useful to see current replicas + target metric value
```

```bash
kubectl -n keda logs deploy/keda-operator | tail
# Decisions: "scaled runtime-default from 4 to 8 because pending messages = 47"
```

The `/admin/scaling` UI surfaces all of this without kubectl.

---

## Manual overrides

For maintenance / load tests:

```bash
# Pin to N replicas, bypass KEDA:
kubectl -n abenix annotate scaledobject runtime-default autoscaling.keda.sh/paused=true
kubectl -n abenix scale deploy agent-runtime-default --replicas=10

# Resume:
kubectl -n abenix annotate scaledobject runtime-default autoscaling.keda.sh/paused-
```

Or use the admin UI's "Override" button.

---

## Cost protection

`maxReplicaCount` caps blow-up scenarios. Worst case: 20 default + 10 chat + 4 heavy + 2 long = 36 runtime pods total at 250m-1000m CPU each = ~10-20 cores. At AKS B-series pricing that's <$10/hour even at max. Per-pool caps keep the bill bounded.

For finer cost control, set per-tenant execution caps via `tenant_settings.executions_per_day_cap`.

---

## See also

- [00-overview](00-overview.md) — overall deploy flow
- [03-services](../01-architecture/03-services.md) — what each pool is for
- [/admin/scaling page](../05-ui/03-page-catalogue.md) — UI for KEDA introspection
