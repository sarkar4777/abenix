# Disaster recovery runbook

What to do when the platform is on fire. Written to be readable at 3am.

## Severity

| Sev | Symptom | Page |
|---|---|---|
| 1 | platform unreachable, all API requests 5xx, no logins | oncall right now |
| 2 | partial outage (one pool down, one DB read replica down, no execution intake) | within 30 min |
| 3 | degraded — slow responses, one feature broken, rate limit on a dep | next business hour |

## First 5 minutes — triage

```bash
# 1. Are pods healthy?
kubectl get pods -n abenix | grep -vE 'Running|Completed'

# 2. Is the API responding?
curl -fsS http://<api-host>/api/health/ready

# 3. Is the DB reachable from inside the cluster?
kubectl exec -n abenix abenix-postgresql-0 -- pg_isready

# 4. Is Redis reachable?
kubectl exec -n abenix abenix-redis-master-0 -- redis-cli ping

# 5. What recent events?
kubectl get events -n abenix --sort-by='.lastTimestamp' | tail -30
```

## Common scenarios

### A pod is `CrashLoopBackOff`

```bash
kubectl logs -n abenix <pod> --previous | tail -100
```

Most common causes:
- env var missing (check `kubectl get secret abenix-secrets -n abenix -o yaml`)
- migration mismatch (api expects newer schema than DB has — see "DB out of sync" below)
- bad image tag (see `docs/06-deployment/deploy-only-trap.md`)

### Multiple pods in `ImagePullBackOff` after a partial deploy

You hit [the --only trap](deploy-only-trap.md). Recovery commands are in that doc.

### Postgres has stopped accepting connections

```bash
# Check disk
kubectl exec -n abenix abenix-postgresql-0 -- df -h /bitnami/postgresql
# Check connections in use
kubectl exec -n abenix abenix-postgresql-0 -- \
  psql -U abenix -c "SELECT count(*) FROM pg_stat_activity;"
# Kill long-running queries
kubectl exec -n abenix abenix-postgresql-0 -- \
  psql -U abenix -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state='active' AND query_start < now() - interval '5 minutes';"
```

If the StatefulSet PVC is full, scale up the volume:

```bash
kubectl patch pvc data-abenix-postgresql-0 -n abenix --type='json' \
  -p='[{"op":"replace","path":"/spec/resources/requests/storage","value":"100Gi"}]'
```

Most managed Kubernetes (AKS / EKS / GKE) supports online expansion.

### Redis OOM

```bash
kubectl exec -n abenix abenix-redis-master-0 -- redis-cli info memory | grep -E 'used_memory_human|maxmemory_human'
# Look for the offender:
kubectl exec -n abenix abenix-redis-master-0 -- redis-cli --bigkeys
# Burn the cache safely (does NOT touch queues used by agent-runtime):
kubectl exec -n abenix abenix-redis-master-0 -- redis-cli --scan --pattern 'cache:*' | xargs -L 100 kubectl exec -n abenix abenix-redis-master-0 -- redis-cli del
```

### DB out of sync after a migration rollback

If `alembic upgrade head` fails on a server that was downgraded:

```bash
# 1. Find the current revision
kubectl exec -n abenix abenix-api-<pod> -- alembic -c packages/db/alembic.ini current
# 2. Stamp to the correct one
kubectl exec -n abenix abenix-api-<pod> -- alembic -c packages/db/alembic.ini stamp <revision>
# 3. Upgrade
kubectl exec -n abenix abenix-api-<pod> -- alembic -c packages/db/alembic.ini upgrade head
```

Never blow away the alembic_version table unless you've already backed up the DB and accept reseeding.

### Webhook deliveries stuck

Check the worker pool:

```bash
kubectl logs -n abenix -l app=abenix-worker --tail=200 | grep -i webhook
```

Replay a stuck delivery:

```bash
kubectl exec -n abenix abenix-api-<pod> -- \
  python -c "from app.workers.webhook_redrive import redrive_id; redrive_id('<delivery_id>')"
```

### Agent executions piling up

Check pool depth:

```bash
kubectl exec -n abenix abenix-redis-master-0 -- redis-cli xlen exec_q:default
kubectl exec -n abenix abenix-redis-master-0 -- redis-cli xlen exec_q:chat
kubectl exec -n abenix abenix-redis-master-0 -- redis-cli xlen exec_q:heavy-reasoning
kubectl exec -n abenix abenix-redis-master-0 -- redis-cli xlen exec_q:long-running
```

If a pool is backed up, KEDA should be scaling. Confirm:

```bash
kubectl get hpa -n abenix
kubectl get scaledobject -n abenix
```

If KEDA isn't scaling, scale manually:

```bash
kubectl scale deploy abenix-agent-runtime-default --replicas=5 -n abenix
```

## Backups

### Postgres

The Helm chart enables a daily logical dump via a CronJob (`abenix-pg-backup`). Restore:

```bash
# 1. Get the backup
kubectl cp abenix/<backup-pod>:/backups/abenix-2026-05-25.sql.gz /tmp/restore.sql.gz
gunzip /tmp/restore.sql.gz

# 2. Stop the API to prevent writes
kubectl scale deploy abenix-api --replicas=0 -n abenix

# 3. Restore (CAUTION: drops the existing DB)
kubectl exec -i -n abenix abenix-postgresql-0 -- \
  psql -U postgres -c "DROP DATABASE abenix; CREATE DATABASE abenix OWNER abenix;"
kubectl exec -i -n abenix abenix-postgresql-0 -- psql -U abenix -d abenix < /tmp/restore.sql

# 4. Bring the API back
kubectl scale deploy abenix-api --replicas=2 -n abenix
```

### Object storage (`/data`)

Knowledge bases, ML models, and code assets persist to a shared `/data` mount (azurefile-csi RWX on AKS, NFS in BYO). The chart enables a daily `restic` snapshot to your configured S3-compatible store via the `abenix-data-backup` CronJob.

Restore from a known snapshot:

```bash
kubectl exec -n abenix abenix-data-backup-<jobpod> -- \
  restic restore <snapshot-id> --target /data
```

### Neo4j (atlas graphs)

Neo4j ships `neo4j-admin database backup` in its image. The CronJob is `abenix-neo4j-backup`. Restore is a stop / restore / start cycle — see Neo4j's docs (graph data is reseedable from source artifacts so this is rarely the critical path).

## Tested restore path

Do this once a quarter:

1. Take a fresh backup.
2. Stand up a temporary namespace `abenix-dr-test`.
3. Apply the same Helm chart with empty PVCs.
4. Run the Postgres restore + `/data` restore commands above.
5. Smoke-test login + one agent execution.
6. Tear down the temporary namespace.

If step 5 fails, the production restore would also fail — fix it now, not at 3am.

## Escalation

- **API maintainer**: sarkar4777 (GitHub) — primary
- **Infra**: see internal oncall rotation
- **Provider escalation**:
  - Azure AKS: <https://portal.azure.com> support → AKS
  - Anthropic outage: <https://status.anthropic.com>
  - OpenAI outage: <https://status.openai.com>
