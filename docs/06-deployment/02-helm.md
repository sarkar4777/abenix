# Helm chart structure

> One chart at `infra/helm/abenix/` deploys the platform core. Five subcharts handle the runtime pools + data stores. Standalone apps are deployed separately via `kubectl apply`.

---

## Chart tree

```
infra/helm/abenix/
├── Chart.yaml
├── values.yaml                  ← defaults
├── values-local.yaml            ← minikube/k3d overrides
├── values-azure.yaml            ← AKS overrides
├── templates/
│   ├── api-deployment.yaml      ← abenix-api Deployment + Service
│   ├── web-deployment.yaml      ← abenix-web
│   ├── worker-deployment.yaml   ← worker + celery-beat
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secrets-stub.yaml        ← shape only; values populated via helm --set
│   ├── postgres.yaml            ← Timescale StatefulSet + Service
│   ├── neo4j.yaml               ← optional
│   ├── redis.yaml
│   ├── nats.yaml
│   ├── prometheus.yaml
│   ├── grafana.yaml
│   ├── tempo.yaml
│   ├── serviceaccount.yaml      ← + ClusterRole abenix-cluster-reader
│   └── _helpers.tpl
└── charts/                      ← packaged subcharts (.tgz)
    ├── api-0.1.0.tgz
    ├── web-0.1.0.tgz
    ├── worker-0.1.0.tgz
    ├── agent-runtime-0.1.0.tgz  ← four ScaledObjects, one image
    └── neo4j-0.1.0.tgz
```

> **Trap** — the `charts/*.tgz` files are committed and updated by hand via `helm dep update`. If a sub-chart's templates change without `helm dep update`, the parent helm install picks up the **stale** tarball. The CI lint step catches this.

---

## values.yaml — top-level shape

```yaml
image:
  registry: localhost:5000     # overridden in values-azure.yaml
  pullPolicy: IfNotPresent
  tag: latest                  # overridden by --set image.tag=<sha>

api:
  replicas: 2
  image:
    repository: abenix/api
  resources:
    requests: {cpu: 200m, memory: 512Mi}
    limits:   {cpu: 1000m, memory: 2Gi}
  env:
    DATABASE_URL: ${DATABASE_URL}
    REDIS_URL: redis://redis:6379/0
    NATS_URL: nats://nats:4222
    JWT_SECRET: ${JWT_SECRET}
    ML_MODELS_DIR: /data/ml-models

web:
  replicas: 2
  env:
    NEXT_PUBLIC_API_URL: https://api.example.com
    NEXT_PUBLIC_GRAFANA_URL: https://grafana.example.com
    NEXT_PUBLIC_TEMPO_URL: https://tempo.example.com

worker:
  replicas: 2
  enabled: true

agent-runtime:
  enabled: true
  pools:
    default:       {minReplicas: 2,  maxReplicas: 20, requestCpu: 500m, requestMem: 1Gi}
    chat:          {minReplicas: 1,  maxReplicas: 10, requestCpu: 250m, requestMem: 512Mi}
    heavy:         {minReplicas: 1,  maxReplicas: 4,  requestCpu: 1000m, requestMem: 4Gi}
    longRunning:   {minReplicas: 1,  maxReplicas: 2,  requestCpu: 500m, requestMem: 2Gi}

postgres:
  enabled: true
  storageClassName: managed-premium      # AKS; gp2 on EKS
  storageSize: 100Gi
  replication: false                     # set true for HA

neo4j:
  enabled: true
  storageSize: 50Gi

ingress:
  className: nginx
  hosts:
    api: api.example.com
    web: example.com
    grafana: grafana.example.com
    tempo: tempo.example.com

observability:
  prometheus: {enabled: true, retention: 30d}
  grafana:    {enabled: true, adminPasswordSecret: grafana-admin}
  tempo:      {enabled: true, retention: 7d, storageSize: 50Gi}

secrets:
  # populated via --set on deploy; never committed
  anthropicApiKey: ""
  openaiApiKey: ""
  googleApiKey: ""
  pineconeApiKey: ""
  tavilyApiKey: ""
  ...
```

`values-local.yaml` flips:
- `postgres.replication: false`
- `postgres.storageClassName: standard`
- `agent-runtime.pools.*.minReplicas: 1` (cap costs locally)
- `ingress.hosts: localhost.*`

`values-azure.yaml` adjusts:
- `image.registry: abenixacr71a48.azurecr.io`
- `postgres.storageClassName: managed-premium`
- production hostnames

---

## ConfigMap + Secrets convention

Each service gets a ConfigMap of non-sensitive env + a Secret of sensitive env. Pods reference both via `envFrom`:

```yaml
envFrom:
  - configMapRef: {name: api-config}
  - secretRef:    {name: api-secrets}
```

Adding a new env var:
1. Add to `templates/configmap.yaml` (non-sensitive) or `templates/secrets-stub.yaml` (sensitive).
2. Plumb in `values.yaml` so it's overridable.
3. The pod inherits via envFrom on next rollout.

Secrets stub looks like:
```yaml
apiVersion: v1
kind: Secret
metadata: {name: api-secrets, namespace: abenix}
type: Opaque
stringData:
  ANTHROPIC_API_KEY: "{{ .Values.secrets.anthropicApiKey }}"
  OPENAI_API_KEY: "{{ .Values.secrets.openaiApiKey }}"
  JWT_SECRET: "{{ .Values.secrets.jwtSecret }}"
```

---

## ServiceMonitor + Prometheus scrape

Each pod exposes `/metrics` on its main HTTP port. The chart creates ServiceMonitors so Prometheus auto-scrapes:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata: {name: abenix-api}
spec:
  selector: {matchLabels: {app.kubernetes.io/name: api}}
  endpoints:
  - port: http
    path: /metrics
    interval: 30s
```

Custom metrics emitted by the app code (Prometheus `Counter`/`Histogram`) appear automatically.

---

## Standalone-app manifests (kubectl apply)

Each vertical lives in `<app>/k8s/<app>.yaml`. Shape:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: {name: wingman-api, namespace: abenix}
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: api
        image: localhost:5000/abenix/wingman-api:latest    # sed-replaced by deploy script
        envFrom:
        - secretRef:   {name: wingman-secrets}
        - configMapRef: {name: wingman-config}
        volumeMounts:
        - {name: shared-data, mountPath: /data}
        livenessProbe:  {httpGet: {path: /health, port: 8006}}
        readinessProbe: {httpGet: {path: /health, port: 8006}}
      volumes:
      - {name: shared-data, hostPath: {path: /tmp/abenix-shared-data, type: DirectoryOrCreate}}
---
apiVersion: v1
kind: Service
metadata: {name: wingman-api}
spec:
  selector: {app: wingman-api}
  ports: [{port: 8006}]
```

The deploy script `sed`-substitutes the image tag and `kubectl apply`s. Secrets are created in a separate dry-run-apply step so values aren't committed.

> **Why not helm for standalone apps** — independent release cadences. A wingman bug fix should not require a platform helm release.

---

## See also

- [00-overview](00-overview.md) — the full deploy flow
- [03-keda](03-keda.md) — autoscaling rules
- [04-observability](04-observability.md) — Prom + Grafana + Tempo
