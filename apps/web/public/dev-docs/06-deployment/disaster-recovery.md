# Disaster recovery runbook

What to do when the platform is on fire. Written to be readable at 3am.

## Severity

| Sev | Symptom | Page |
|---|---|---|
| 1 | platform unreachable, all API requests 5xx, no logins | oncall right now |
| 2 | partial outage (one pool down, no execution intake, a data store degraded) | within 30 min |
| 3 | degraded — slow responses, one feature broken, rate limit on a dependency | next business hour |

## First 5 minutes — triage

```bash
# 1. Are pods healthy?
kubectl get pods -n abenix | grep -vE 'Running|Completed'

# 2. Is the API responding? (local forward or the AKS forward from portforward-azure.sh)
curl -fsS http://localhost:8000/api/health/ready

# 3. Is the DB reachable from inside the cluster?
kubectl exec -n abenix abenix-postgresql-0 -- pg_isready

# 4. Is Redis reachable? (add -a <password> when Redis auth is on)
kubectl exec -n abenix abenix-redis-master-0 -- redis-cli ping

# 5. What recent events?
kubectl get events -n abenix --sort-by='.lastTimestamp' | tail -30
```

Pod names here assume the local and Azure values, where Postgres runs with
`architecture: standalone` as `abenix-postgresql-0`. With
`architecture: replication` (base and production values) the primary is
`abenix-postgresql-primary-0`.

## Common scenarios

### A pod is `CrashLoopBackOff`

```bash
kubectl logs -n abenix <pod> --previous | tail -100
```

Most common causes:
- a variable missing or still at its default. With `DEBUG=false` the API refuses to start on the default `SECRET_KEY` or without `JWT_PRIVATE_KEY` and `JWT_PUBLIC_KEY`. Check `kubectl get secret abenix-secrets -n abenix -o yaml`
- migration mismatch, see "DB out of sync" below. On the API the `db-migrate` init container fails first, so look at its logs with `-c db-migrate`
- bad image tag, see [the --only trap](deploy-only-trap.md)

### Multiple pods in `ImagePullBackOff` after a partial deploy

You hit [the --only trap](deploy-only-trap.md). Recovery commands are in that doc.

### Postgres has stopped accepting connections

The Bitnami chart's admin user is `postgres`, with the password in
`abenix-secrets` under `postgres-password`. The pod has it as
`$POSTGRES_PASSWORD`.

```bash
# disk
kubectl exec -n abenix abenix-postgresql-0 -- df -h /bitnami/postgresql
# connections in use
kubectl exec -n abenix abenix-postgresql-0 -- bash -c \
  'PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -d abenix -c "SELECT count(*) FROM pg_stat_activity;"'
# end queries running for more than 5 minutes
kubectl exec -n abenix abenix-postgresql-0 -- bash -c \
  'PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -d abenix -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = '"'"'active'"'"' AND query_start < now() - interval '"'"'5 minutes'"'"';"'
```

Each API worker holds up to `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` connections (10 +
5), and a connection left idle inside a transaction is ended by the server after
`DB_IDLE_TXN_TIMEOUT_MS` (5 minutes).

If the volume is full, expand it when the storage class allows it:

```bash
kubectl patch pvc data-abenix-postgresql-0 -n abenix --type='json' \
  -p='[{"op":"replace","path":"/spec/resources/requests/storage","value":"100Gi"}]'
```

### Redis OOM

```bash
kubectl exec -n abenix abenix-redis-master-0 -- redis-cli info memory | grep -E 'used_memory_human|maxmemory_human'
kubectl exec -n abenix abenix-redis-master-0 -- redis-cli --bigkeys
```

Redis holds the Celery broker (DB 0) and results (DB 1), rate limit windows,
live progress channels, the tool-call stream and per-tenant overrides. Do not
flush it blindly. Clearing the Celery result keys is the safe first move.

### DB out of sync after a migration rollback

Alembic lives in `/app/packages/db` in the API image.

```bash
POD=$(kubectl get pods -n abenix -l app.kubernetes.io/name=api -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n abenix $POD -- bash -c 'cd /app/packages/db && alembic current'
kubectl exec -n abenix $POD -- bash -c 'cd /app/packages/db && alembic stamp <revision>'
kubectl exec -n abenix $POD -- bash -c 'cd /app/packages/db && alembic upgrade heads'
```

Never blow away the `alembic_version` table unless you have a backup and accept
reseeding.

### Webhook deliveries stuck

Outbound events are delivered from the API scheduler, not the worker. A
delivery that ran out of retries is marked `dead`.

```bash
# list dead deliveries for one subscription
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/webhooks/<webhook_id>/deliveries?status=dead"
# queue one again, full retry budget
curl -X POST -H "Authorization: Bearer <token>" "http://localhost:8000/api/webhooks/deliveries/<delivery_id>/redeliver"
```

Details in [outbound events](../02-runtime/19-outbound-events.md).

### A failed execution needs to run again

`GET /api/admin/dlq` lists dead-lettered executions. `POST /api/admin/dlq/<id>/replay`
runs one again from its captured input. The `/admin/dlq` page does the same.

### Agent executions piling up

With the NATS backend every pool has a JetStream consumer
`abenix-<pool>-consumer` on the `agents` stream. Pending counts are on the NATS
monitor port, 8222. Read it from inside the API pod, so no extra forward is
needed:

```bash
kubectl exec -n abenix deploy/abenix-api -c api -- python3 -c   "import urllib.request; print(urllib.request.urlopen('http://abenix-nats:8222/jsz?consumers=true').read().decode())"   | grep -E '"name"|num_pending'
```

`num_ack_pending` counts runs in flight. A message stays unacked until its run ends.

If a pool is backed up, KEDA should be scaling it:

```bash
kubectl get scaledobject -n abenix
kubectl get hpa -n abenix
```

If it is not, scale by hand after pausing the ScaledObject, see
[03-keda](03-keda.md#manual-overrides).

When a pool pod dies mid-run, JetStream redelivers its messages and another pod
reruns each agent from the start once the run's lease (25 s) has expired. Tool
side effects can repeat. A run picked up 3 times without finishing is failed
with `STALE_SWEEP`. Inline runs stuck in `running` after an API pod died are
marked failed by the stale sweeper after `STALE_EXECUTION_MAX_MINUTES` (10).

## Backups

Pick a Postgres strategy with `backup.postgres.strategy`.

| Strategy | What it does | Use it when |
|---|---|---|
| `dump` | Nightly `pg_dump`, the section below | A small install. The whole dump has to fit `backup.activeDeadlineSeconds` and `backup.scratchSize` |
| `physical` | Streamed base backup plus a continuous WAL archive, point in time restore | A large corpus, the production values default to it |
| `external` | The chart renders no Postgres backup | CloudNativePG or a managed Postgres owns it, see below |

Run a restore drill before you need one, see [the drill](#restore-drill).

### Physical backups

`<release>-pg-basebackup` streams `pg_basebackup` through a pipe into the uploader, so neither side holds the backup on disk and its size is only limited by `backup.postgres.physical.activeDeadlineSeconds`. `<release>-pg-wal-archiver` runs `pg_receivewal` through the replication slot `abenix_wal` and ships each finished segment, plus a copy of the open one every `shipIntervalSeconds`, so at most that much is lost.

Targets are S3 compatible storage, Azure Blob with `backup.target.type: azure` and `STORAGE_AZURE_CONNECTION_STRING` in `abenix-secrets`, or the backup PVC when `objectStorage.type` is local. Everything sits under `backups/pg/`. Only a backup with a `COMPLETE` marker is ever restored. `keep` base backups stay, and WAL older than the oldest of them is pruned.

The primary needs a `host replication` line. Replicated installs have it. For a standalone install layer `values-backup-physical.yaml`, which also bounds the slot.

Keep `max_slot_wal_keep_size` set. A stopped archiver makes the primary retain WAL through its slot, and without that bound it fills the disk. With it the archive gets a gap once the limit passes, so take a new base backup after a long archiver outage. `walVolumeSize` only has to hold WAL until it ships. Nothing alerts on archiver lag yet, watch the shipper's log or the volume.

Restore a real outage the same way the drill does, into a new data directory, then point the release at it.

```bash
# on a pod with the backup scripts mounted and the store variables set
python3 /scripts/backup_store.py fetch-physical backups/pg/base backups/pg/wal /restore
sh /scripts/restore-postgres.sh /restore /restore/data "2026-11-05 09:00:00+00"
postgres -D /restore/data
```

The third argument is the moment to stop at, leave it out to replay everything. The script refuses a data directory that is not empty.

### CloudNativePG or a managed Postgres

Set `backup.postgres.strategy: external` and point `DATABASE_URL` at your cluster. The chart still installs its own Postgres subchart, so scale that StatefulSet to zero. Configure base backups and WAL archiving there, with CloudNativePG's `backup.barmanObjectStore` and a `ScheduledBackup`, or your provider's point in time recovery. Abenix needs the `vector` extension and a role that can create it. The drill's row count check still applies, restore into a scratch database and run `scripts/backup/row-counts.sql` on both sides, then compare with `scripts/backup/compare-counts.py`. The chart path has not been run against CloudNativePG.

### Restore drill

```bash
scripts/backup/restore-drill.sh docker        # throwaway containers, needs only Docker
scripts/backup/restore-drill.sh neo4j-docker  # the same for the Neo4j export
scripts/backup/restore-drill.sh minikube      # with the chart installed, strategy physical
```

The Docker drill seeds a source with a partitioned `chunks` table and an HNSW index, takes a base backup with the chart's scripts, writes more with no segment switch, stops the source, restores into a new container, then compares exact row counts for every table and runs a vector query. It fails on any difference.

The minikube drill runs the CronJob once, reads counts from the live primary, starts a throwaway pod from the ConfigMap `<release>-backup-drill` that restores the newest backup, compares, and deletes the pod. A live source moves, so `--drift 1` allows that percent per table. Set `DRILL_DB` if your database is not `abenix`.

### Dump backups

Backups need both `backup.enabled` and `backup.persistentVolume.enabled`. With
the volume on, the chart creates the PVC `<release>-backup` and keeps it on
`helm uninstall`. Without it the jobs write to an `emptyDir` that is gone when
the pod ends. Both jobs share the claim and run an hour apart, so
`ReadWriteOnce` works on one node. On a multi-node cluster use a
`ReadWriteMany` class, as the Azure values do with `azurefile-csi`.

| Value | Default | Notes |
|---|---|---|
| `backup.persistentVolume.enabled` | `false` | Creates the `<release>-backup` claim |
| `backup.persistentVolume.storageClass` | empty | Empty uses the cluster default class |
| `backup.persistentVolume.accessMode` | `ReadWriteOnce` | `ReadWriteMany` on multi-node clusters |
| `backup.persistentVolume.size` | `20Gi` | |
| `backup.neo4j.keep` | `7` | Neo4j exports kept |
| `backup.neo4j.image` | the agent-runtime image | Needs Python and the `neo4j` driver |

### Postgres

With `backup.enabled` and the `dump` strategy the chart adds the CronJob
`abenix-pg-backup`, daily at 02:00 by default. It runs `pg_dump` as `postgres`
in custom format (`--format=custom`, `--compress` from `backup.compress`) into
`/backup/abenix-pg-<timestamp>.dump` and keeps the newest 7 there. Without S3,
Sunday dumps are also copied to `/backup/weekly`, which keeps 4.

With `objectStorage.type: s3` the dump runs in an init container and a second
container, `s3-upload`, uploads it with `boto3` to
`s3://BUCKET/backups/daily/`, plus `s3://BUCKET/backups/weekly/` on Sundays (UTC).
It keeps the newest 7 daily and 4 weekly objects and deletes older ones.

| Value | Default | Notes |
|---|---|---|
| `backup.s3Bucket` | empty | The bucket. Empty uses `objectStorage.bucket`. With neither set the upload fails |
| `backup.uploaderImage` | the agent-runtime image | Image for the upload container, needs `python3` and `boto3` |
| `STORAGE_S3_ACCESS_KEY` / `STORAGE_S3_SECRET_KEY` in `abenix-secrets` | unset | Upload credentials. When empty the pod's cloud role is used (IRSA, workload identity, instance profile) |

`objectStorage.region` and `objectStorage.endpoint` pass through, so S3-compatible
stores work too.

The files are custom-format dumps. Restore them with `pg_restore`, not `psql`.

Restore:

```bash
# 1. stop writers, pausing KEDA first so it does not scale the pools back up
kubectl annotate scaledobject --all -n abenix autoscaling.keda.sh/paused=true
kubectl scale deploy abenix-api --replicas=0 -n abenix
kubectl scale deploy -l app.kubernetes.io/name=agent-runtime --replicas=0 -n abenix

# 2. copy the dump into the Postgres pod
kubectl cp ./abenix-pg-<timestamp>.dump abenix/abenix-postgresql-0:/tmp/restore.dump

# 3. restore over the existing database
kubectl exec -n abenix abenix-postgresql-0 -- bash -c \
  'PGPASSWORD=$POSTGRES_PASSWORD pg_restore -U postgres -d abenix --clean --if-exists --no-owner /tmp/restore.dump'

# 4. bring things back
kubectl scale deploy abenix-api --replicas=2 -n abenix
kubectl annotate scaledobject --all -n abenix autoscaling.keda.sh/paused-
```

### Neo4j

With `backup.neo4j.enabled` the CronJob `abenix-neo4j-backup` runs daily at
03:00. The chart runs Neo4j Community, which has no online backup, so the job
streams an APOC Cypher export (`apoc.export.cypher.all`) over Bolt into
`/backup/neo4j/abenix-neo4j-<timestamp>.cypher.gz`. It needs no access to the
Neo4j data volume and no downtime. It keeps the newest `backup.neo4j.keep` (7).
With an S3 or Azure target each export is also uploaded to `backups/neo4j/`. `backup.neo4j.activeDeadlineSeconds`, `scratchSize` and `resources` size it. Restore with `files/restore-neo4j.sh`, it refuses a database that already has nodes.

Restore by piping the file into `cypher-shell` against an empty database:

```bash
gunzip -c abenix-neo4j-<timestamp>.cypher.gz |   cypher-shell -a bolt://abenix-neo4j:7687 -u neo4j -p "$NEO4J_PASSWORD" -d neo4j
```

Graph data can also be rebuilt from the knowledge sources, so this is rarely
the critical path.

### `/data`

Uploads, ML models and code assets live on `/data`. There is no backup job for
it. With `objectStorage.type` set to `s3` or `azure`, every file is mirrored to
object storage and an API replica restores a missing file on demand, so the
bucket is the durable copy. With local storage, back up the volume yourself.

## Tested restore path

Do this once a quarter:

1. Take a fresh backup.
2. Stand up a temporary namespace `abenix-dr-test`.
3. Install the same chart into it with empty volumes.
4. Run the Postgres restore above.
5. Smoke-test login and one agent run.
6. Tear down the namespace.

If step 5 fails, the production restore would also fail — fix it now, not at 3am.

## Escalation

- **API maintainer**: sarkar4777 (GitHub) — primary
- **Infra**: see internal oncall rotation
- **Provider escalation**:
  - Azure AKS: <https://portal.azure.com> support → AKS
  - Anthropic outage: <https://status.anthropic.com>
  - OpenAI outage: <https://status.openai.com>
