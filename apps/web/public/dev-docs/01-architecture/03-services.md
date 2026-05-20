# Service inventory

> A complete catalogue of every Deployment / StatefulSet in the platform, what it does, how it scales, and how to find its source.

This is a reference doc — skim the table, deep-read only the entries relevant to your task.

---

## Bird's-eye topology

```mermaid
flowchart TB
  subgraph PUBLIC["Public / ingress"]
    ING[ingress-nginx Service<br/>type=LoadBalancer]
  end

  subgraph WEB_TIER["Web tier · Next.js"]
    AW[abenix-web]
    WW[wingman-web]
    CW[example_app-web]
    SW[sauditourism-web]
    RW[resolveai-web]
    IW[industrial-iot-web]
    CIW[claimsiq-web]
  end

  subgraph API_TIER["API tier · FastAPI"]
    AAPI[abenix-api]
    WAPI[wingman-api]
    CAPI[example_app-api]
    SAPI[sauditourism-api]
    RAPI[resolveai-api]
    IAPI[industrial-iot-api]
    CIAPI[claimsiq-api]
  end

  subgraph RUNTIME["Agent runtime · 4 pools"]
    AR1[runtime-default<br/>HPA 2-20]
    AR2[runtime-chat<br/>HPA 1-10]
    AR3[runtime-heavy<br/>HPA 1-4]
    AR4[runtime-long<br/>HPA 1-2]
  end

  subgraph WORKERS["Workers · Celery"]
    W[worker]
    CW2[cognify-worker]
    BEAT[celery-beat]
  end

  subgraph STORES["Stores"]
    PG[(postgres)]
    NEO[(neo4j)]
    R[(redis)]
    NATS[(nats)]
    S3[s3 / azure-files]
  end

  subgraph EDGE["Edge runtimes (optional)"]
    ERPY[edge-runtime · Python]
    ERRS[edge-runtime-rust]
    ERC[edge-runtime-c]
  end

  ING --> AW
  ING --> WW
  ING --> CW
  ING --> SW
  ING --> RW
  ING --> IW
  ING --> CIW

  AW --> AAPI
  WW --> WAPI
  CW --> CAPI
  WAPI --> AAPI
  CAPI --> AAPI
  SAPI --> AAPI
  RAPI --> AAPI
  IAPI --> AAPI
  CIAPI --> AAPI

  AAPI --> PG
  AAPI --> NEO
  AAPI --> R
  AAPI --> NATS

  NATS <--> AR1
  NATS <--> AR2
  NATS <--> AR3
  NATS <--> AR4

  AR1 --> PG
  AR1 --> S3
  AR2 --> PG
  AR3 --> PG
  AR4 --> PG

  AAPI --> S3
  W --> PG
  W --> R
  W --> NATS
  CW2 --> PG
  CW2 --> NEO
  CW2 --> S3
  BEAT --> R

  EDGE -.-> AAPI
```

---

## Core platform services

### `abenix-api` — the REST + SSE surface
- **Language**: Python 3.12 / FastAPI
- **Source**: [`apps/api/`](../../apps/api/)
- **Image**: `Dockerfile.api`
- **Replicas**: 2-8 (HPA on CPU). ALWAYS ≥2 for rolling deploys.
- **Responsibility**: Every REST endpoint the browser hits. CRUD for agents, pipelines, knowledge bases, ML models, code assets, executions. auth + RBAC. SSE event streams. webhooks.
- **Reads from**: Postgres, Neo4j (via knowledge router), Redis (cache + rate-limit), NATS (publish + consume for SSE).
- **Writes to**: Postgres, S3 (file uploads), NATS (exec.start, exec.signoff, exec.resume).
- **Key envs**: `DATABASE_URL`, `REDIS_URL`, `NATS_URL`, `JWT_SECRET`, `ML_MODELS_DIR`, `OTEL_EXPORTER_OTLP_ENDPOINT`.
- **Where to look first**: [`apps/api/app/main.py`](../../apps/api/app/main.py) for router wiring.

### `abenix-web` — the browser UI
- **Language**: TypeScript / Next.js 15 (App Router)
- **Source**: [`apps/web/`](../../apps/web/)
- **Image**: `Dockerfile.web`
- **Replicas**: 2-4 (HPA on CPU).
- **Responsibility**: Renders every UI page. The (app)/ folder is the authenticated app. the / route is the marketing landing.
- **Talks to**: `abenix-api` only. Never queries the DB directly.
- **Key envs**: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_GRAFANA_URL`, `NEXT_PUBLIC_TEMPO_URL`.
- **Build-time inlining**: `NEXT_PUBLIC_*` env vars are baked into the client bundle at `npm run build`. To change them you must rebuild the image.

### `agent-runtime-{default,chat,heavy-reasoning,long-running}` — the 4 runtime pools
- **Language**: Python 3.12 / FastAPI + Celery-style consumer
- **Source**: [`apps/agent-runtime/`](../../apps/agent-runtime/)
- **Image**: `Dockerfile.agent-runtime`
- **Replicas**: KEDA-managed per pool — see [06-deployment/03-keda](../06-deployment/03-keda.md).
- **Responsibility**: The agent execution loop. Consumes from NATS, runs LLM + tool calls, emits events.
- **Pool selection**: an agent's `model_config.runtime_pool` field. Default = `default`.
- **Why four pools**: isolate the 30-minute reasoning agent from the 200-ms chat agent. Each pool has different replica caps, request limits, and timeouts.

### `worker` — background jobs
- **Language**: Python / Celery
- **Source**: [`apps/worker/`](../../apps/worker/)
- **Image**: `Dockerfile.worker`
- **Replicas**: 1-4 (KEDA on Redis queue depth).
- **Responsibility**: Scheduled triggers (cron), webhook delivery retries, pipeline orchestration for long pipelines, execution reconciliation sweeper (the straggler-cleaner from [02-request-lifecycle](02-request-lifecycle.md)).
- **Two consumer queues**: `default` (worker pod) and `cognify` (separate cognify-worker pod).

### `cognify-worker` — knowledge ingestion
- **Language**: Python / Celery (reuses the worker image, different queue)
- **Source**: same image, different `CELERY_QUEUE` env.
- **Responsibility**: When a KB document is uploaded, this worker parses (PDF/DOCX/etc.), chunks, embeds, and (optionally) Cognifies — i.e. extracts entities and relationships into the Neo4j graph.
- **Why separate**: a 500-page PDF can pin a worker for 10 minutes. Isolating cognify jobs keeps the default queue responsive for short tasks.

### `celery-beat` — scheduler
- **Source**: same image as worker.
- **Responsibility**: Cron-style triggers. Runs the execution-reconcile sweeper, KB re-index jobs, billing-rollup jobs.
- **Replicas**: 1 (singleton — Redlock for ownership).

---

## Standalone vertical apps

Each vertical app deploys two services: `*-api` (FastAPI) and `*-web` (Next.js). They follow the **thin-app pattern** — see [07-standalone-apps/00-pattern](../07-standalone-apps/00-pattern.md).

| App | Domain | Image-tag-pair | Default port (web/api) |
|---|---|---|---|
| **Wingman** | Energy commodity trading | `wingman-web`, `wingman-api` | 3006 / 8006 |
| **the example app** | Contract intelligence | `example_app-web`, `example_app-api` | 3007 / 8007 |
| **Saudi Tourism** | Tourism analytics | `sauditourism-web`, `sauditourism-api` | 3002 / 8002 |
| **ResolveAI** | Customer-support automation | `resolveai-web`, `resolveai-api` | 3008 / 8008 |
| **Industrial-IoT** | Equipment health + alarm desk | `industrial-iot-web`, `industrial-iot-api` | 3009 / 8009 |
| **ClaimsIQ** | Insurance claims triage | `claimsiq-web`, `claimsiq-api` | 3010 / 8010 |

All vertical APIs hold a delegated platform API key (`<APP>_ABENIX_API_KEY`) and call `abenix-api` via the SDK with `X-Abenix-Subject: <app>:<user>`.

---

## Edge runtimes (optional)

The edge runtimes are for low-latency / on-prem deployments where round-trips to the cloud would be too slow. They're not part of a standard deployment.

| Edge runtime | Language | Use case |
|---|---|---|
| `edge-runtime` | Python | Default — same agent loop as the cloud runtime, but runs locally on a factory floor / branch office. |
| `edge-runtime-rust` | Rust | Sub-100ms inference for streaming use cases (telemetry, AIS feed scoring). |
| `edge-runtime-c` | C | Embedded targets (ARM SoCs in industrial gateways). |

Edge runtimes register with the cloud `abenix-api` and pull their agent + tool config on a heartbeat. See [06-deployment/00-overview](../06-deployment/00-overview.md#edge-runtimes).

---

## Data services

These run as their own Deployments / StatefulSets but are infrastructure, not application logic.

| Service | Type | Replicas | Notes |
|---|---|---|---|
| `postgres` (TimescaleDB) | StatefulSet | 1 primary + 2 replicas in HA mode | Primary database. TimescaleDB for the executions time-series. |
| `neo4j` | StatefulSet | 1 | Atlas knowledge graph. Optional but used by KB Cognify + Atlas page. |
| `redis` | StatefulSet | 1 (1+2 in HA mode) | Celery broker, rate-limit counters, hot cache. |
| `nats` JetStream | StatefulSet | 3 (raft cluster) | Execution events, pipeline messaging. |
| `prometheus` | StatefulSet | 1 | Metrics scraper. |
| `grafana` | Deployment | 1 | Dashboards. |
| `tempo` | StatefulSet | 1 | Distributed tracing backend. |

S3-compatible storage is external (AWS S3 / Azure Blob / on-prem MinIO). Not a Pod.

---

## How services find each other

In-cluster service discovery is by Kubernetes DNS: `<service>.<namespace>.svc.cluster.local`. The platform default namespace is `abenix`.

Common envs the vertical apps + workers use:

```
ABENIX_API_URL=http://abenix-api.abenix.svc.cluster.local:8000
DATABASE_URL=postgresql+asyncpg://abenix:****@postgres.abenix.svc.cluster.local:5432/abenix
REDIS_URL=redis://redis.abenix.svc.cluster.local:6379/0
NATS_URL=nats://nats.abenix.svc.cluster.local:4222
NEO4J_URL=bolt://neo4j.abenix.svc.cluster.local:7687
```

The helm chart wires these in [`infra/helm/abenix/templates/configmap.yaml`](../../infra/helm/abenix/templates/configmap.yaml).

---

## Per-service request rate, typical p50, capacity guidance

These are observed numbers from a 4-node AKS deployment under demo load. Use as ballparks. benchmark for your workload.

| Service | rps observed | p50 latency | p99 latency | Bottleneck |
|---|---|---|---|---|
| `abenix-api` | 50-200 rps | 30-80ms | 600ms | Postgres pool exhaustion |
| `abenix-web` | dependent on api | 200ms ssr | 1.5s ssr | Cold-start ssr cost on heavy pages (e.g. /agents with 200 cards) |
| `agent-runtime-default` | 0.5-5 exec/s | 2-8s | 30s | LLM latency dominates |
| `agent-runtime-heavy` | 0.05-0.5 exec/s | 30-180s | 600s | LLM latency dominates |
| `worker` | 5-20 jobs/s | varies | varies | Job-specific |
| `postgres` | 500-2000 qps | 1-5ms | 50ms | Disk IOPS on writes |
| `nats` | thousands of msg/s | <1ms | 5ms | Network |

> **Trap** — Postgres connection pool is shared between `abenix-api`, `worker`, and `agent-runtime`. The default pool size is 10 per pod. with HPA-scaled replicas this can saturate Postgres' max_connections (200) before any service feels CPU pressure. Tune `DB_POOL_SIZE` env if you see "connection limit exceeded" errors.

---

## See also

- [04-data-stores](04-data-stores.md) — per-store schema overview + tuning
- [06-deployment/02-helm](../06-deployment/02-helm.md) — how these are templated
- [06-deployment/03-keda](../06-deployment/03-keda.md) — autoscaling rules per pool
