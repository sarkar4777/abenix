#!/usr/bin/env bash
# Proves a backup restores: real base backup, real WAL replay, a throwaway database,
# then row counts compared with the source.
#
#   scripts/backup/restore-drill.sh docker
#     Everything in throwaway containers, nothing else on the machine is touched.
#     Writes after the base backup and without a segment switch, so WAL replay is what brings them back.
#
#   scripts/backup/restore-drill.sh minikube [--namespace abenix] [--release abenix]
#     Restores the newest backup the chart took into a throwaway pod in the cluster,
#     compares with the live primary, removes the pod. Needs backup.postgres.strategy=physical.
#
#   scripts/backup/restore-drill.sh neo4j-docker
#     The same for the Neo4j Cypher export, node and relationship counts by label and type.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
FILES="$ROOT/infra/helm/abenix/files"
MODE="${1:-docker}"
shift || true
NAMESPACE=abenix
RELEASE=abenix
DRIFT=1
while [ $# -gt 0 ]; do
  case "$1" in
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --release) RELEASE="$2"; shift 2 ;;
    --drift) DRIFT="$2"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done

ID="abenix-drill-$$-$RANDOM"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/abenix-drill.XXXXXX")"
PG_IMAGE="${DRILL_PG_IMAGE:-pgvector/pgvector:pg16}"
PY_IMAGE="${DRILL_PY_IMAGE:-python:3.12-slim}"
NEO4J_IMAGE="${DRILL_NEO4J_IMAGE:-neo4j:5-community}"
say() { printf '[drill] %s\n' "$*"; }

docker_cleanup() {
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    say "failed, last lines from the WAL receiver and shipper"
    docker logs "$ID-wal" 2>&1 | tail -8 || true
    docker logs "$ID-ship" 2>&1 | tail -8 || true
  fi
  docker rm -f "$ID-src" "$ID-wal" "$ID-ship" "$ID-up" "$ID-restored" "$ID-neo-src" "$ID-neo-restored" >/dev/null 2>&1 || true
  docker volume rm "$ID-store" "$ID-pipe" "$ID-walvol" "$ID-restore" >/dev/null 2>&1 || true
  docker network rm "$ID" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}

store() {
  docker run --rm --network "$ID" -v "$ID-store:/store" -v "$FILES:/files:ro" \
    -v "$ID-restore:/restore" -e BACKUP_STORE=dir -e BACKUP_DIR=/store "$@"
}

wait_pg() {
  local name="$1" i
  for i in $(seq 1 120); do
    if docker exec "$name" pg_isready -U postgres -q 2>/dev/null \
      && docker exec "$name" psql -U postgres -d abenix -Atc "SELECT 1" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  docker logs "$name" | tail -30
  return 1
}

seed_source() {
  docker exec -i "$ID-src" psql -v ON_ERROR_STOP=1 -q -U postgres -d abenix <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE knowledge_collections (id uuid PRIMARY KEY, name text);
CREATE TABLE documents (id uuid PRIMARY KEY, kb_id uuid REFERENCES knowledge_collections(id), filename text);
CREATE TABLE chunks (
  id uuid NOT NULL, collection_id uuid NOT NULL, document_id uuid NOT NULL,
  chunk_index int NOT NULL, content text NOT NULL, embedding vector(4),
  PRIMARY KEY (collection_id, id)
) PARTITION BY HASH (collection_id);
CREATE TABLE chunks_p0 PARTITION OF chunks FOR VALUES WITH (MODULUS 2, REMAINDER 0);
CREATE TABLE chunks_p1 PARTITION OF chunks FOR VALUES WITH (MODULUS 2, REMAINDER 1);
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
INSERT INTO knowledge_collections SELECT gen_random_uuid(), 'kb' || g FROM generate_series(1, 5) g;
INSERT INTO documents SELECT gen_random_uuid(), k.id, 'doc' || g FROM knowledge_collections k, generate_series(1, 20) g;
INSERT INTO chunks SELECT gen_random_uuid(), d.kb_id, d.id, g, 'text ' || g,
  ARRAY[random(), random(), random(), random()]::vector
FROM documents d, generate_series(1, 200) g;
SQL
}

counts() {
  docker exec -i "$1" psql -U postgres -d abenix -Atq < "$HERE/row-counts.sql"
}

drill_docker() {
  trap docker_cleanup EXIT
  docker network create "$ID" >/dev/null
  docker volume create "$ID-store" >/dev/null
  docker volume create "$ID-pipe" >/dev/null
  docker volume create "$ID-walvol" >/dev/null
  docker volume create "$ID-restore" >/dev/null

  say "starting the source database"
  docker run -d --name "$ID-src" --network "$ID" --network-alias source \
    -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=abenix "$PG_IMAGE" \
    -c wal_level=replica -c max_wal_senders=10 -c max_replication_slots=10 >/dev/null
  wait_pg "$ID-src"
  # the chart sets the same line through postgresql.primary.pgHbaConfiguration
  docker exec "$ID-src" sh -c 'echo "host replication all all scram-sha-256" >> "$PGDATA/pg_hba.conf"'
  docker exec "$ID-src" psql -U postgres -Atqc "SELECT pg_reload_conf()" >/dev/null
  seed_source

  say "starting the WAL receiver and shipper"
  docker run --rm -v "$ID-walvol:/wal" "$PG_IMAGE" chmod 777 /wal
  docker run -d --name "$ID-wal" --network "$ID" -v "$ID-walvol:/wal" -v "$FILES:/files:ro" \
    -e PGHOST=source -e PGUSER=postgres -e PGPASSWORD=drill -e WAL_DIR=/wal \
    --user postgres --entrypoint sh "$PG_IMAGE" /files/pg-wal-receive.sh >/dev/null
  docker run -d --name "$ID-ship" --network "$ID" -v "$ID-walvol:/wal" -v "$ID-store:/store" -v "$FILES:/files:ro" \
    -e BACKUP_STORE=dir -e BACKUP_DIR=/store "$PY_IMAGE" \
    python /files/backup_store.py ship-wal /wal pg/wal --interval 1 >/dev/null
  sleep 3

  say "taking a base backup through a pipe, no local copy"
  docker run --rm --network "$ID" -v "$ID-pipe:/work" "$PG_IMAGE" sh -c 'mkfifo /work/base.fifo; chmod 666 /work/base.fifo'
  docker run -d --name "$ID-up" --network "$ID" -v "$ID-pipe:/work" -v "$ID-store:/store" -v "$FILES:/files:ro" \
    -e BACKUP_STORE=dir -e BACKUP_DIR=/store "$PY_IMAGE" \
    python /files/backup_store.py stream-base /work/base.fifo pg/base pg/wal --status /work/status >/dev/null
  docker run --rm --network "$ID" -v "$ID-pipe:/work" -v "$FILES:/files:ro" \
    -e PGHOST=source -e PGUSER=postgres -e PGPASSWORD=drill -e WORK=/work \
    "$PG_IMAGE" sh /files/pg-basebackup.sh
  docker wait "$ID-up" >/dev/null
  docker logs "$ID-up" | tail -2
  docker rm -f "$ID-up" >/dev/null

  say "writing after the base backup, only WAL replay can bring these back"
  docker exec -i "$ID-src" psql -v ON_ERROR_STOP=1 -q -U postgres -d abenix <<'SQL'
INSERT INTO documents SELECT gen_random_uuid(), k.id, 'late' FROM knowledge_collections k;
DELETE FROM chunks WHERE chunk_index = 200;
CREATE TABLE made_after_the_backup AS SELECT generate_series(1, 777) AS n;
SQL
  counts "$ID-src" > "$WORK/source.txt"
  sleep 4

  say "stopping the source, the drill must not need it"
  docker stop -t 5 "$ID-src" >/dev/null
  sleep 3
  docker stop "$ID-ship" >/dev/null

  say "fetching and restoring into a throwaway database"
  store "$PY_IMAGE" python /files/backup_store.py fetch-physical pg/base pg/wal /restore
  docker run --rm -v "$ID-restore:/restore" -v "$FILES:/files:ro" --entrypoint sh "$PG_IMAGE" \
    -c 'chown -R postgres /restore && su postgres -c "sh /files/restore-postgres.sh /restore /restore/data"'
  docker run -d --name "$ID-restored" --network "$ID" -v "$ID-restore:/restore" \
    -e PGDATA=/restore/data "$PG_IMAGE" >/dev/null
  wait_recovery "$ID-restored"
  counts "$ID-restored" > "$WORK/restored.txt"

  say "comparing row counts"
  python3 "$HERE/compare-counts.py" "$WORK/source.txt" "$WORK/restored.txt" 0
  docker exec "$ID-restored" psql -U postgres -d abenix -Atc \
    "SET enable_seqscan = off; SELECT count(*) FROM (SELECT 1 FROM chunks ORDER BY embedding <=> '[1,0,0,0]' LIMIT 5) x" | grep -q '^5$' \
    && say "vector search works on the restored index"
  grep -q 'made_after_the_backup|777' "$WORK/restored.txt" && say "changes after the base backup were replayed"
  say "PASSED"
}

wait_recovery() {
  local name="$1" i
  wait_pg "$name"
  for i in $(seq 1 120); do
    if [ "$(docker exec "$name" psql -U postgres -d abenix -Atc 'SELECT pg_is_in_recovery()')" = "f" ]; then
      return 0
    fi
    sleep 1
  done
  docker logs "$name" | tail -30
  return 1
}

neo_shell() {
  local name="$1"
  shift
  docker exec -i "$name" cypher-shell -u neo4j -p drillpassword --format plain "$@"
}

neo_counts() {
  {
    neo_shell "$1" "MATCH (n) UNWIND labels(n) AS l WITH l, count(*) AS c WHERE l <> 'UNIQUE IMPORT LABEL' RETURN 'label ' + l + '|' + toString(c) AS line ORDER BY line" | tail -n +2
    neo_shell "$1" "MATCH ()-[r]->() WITH type(r) AS t, count(r) AS c RETURN 'rel ' + t + '|' + toString(c) AS line ORDER BY line" | tail -n +2
  } | tr -d '"'
}

wait_neo() {
  local name="$1" i
  for i in $(seq 1 180); do
    neo_shell "$name" "RETURN 1" >/dev/null 2>&1 && return 0
    sleep 1
  done
  docker logs "$name" | tail -30
  return 1
}

drill_neo4j_docker() {
  trap docker_cleanup EXIT
  docker network create "$ID" >/dev/null
  say "starting a Neo4j source with APOC, it downloads the plugin on first start"
  docker run -d --name "$ID-neo-src" --network "$ID" --network-alias neosource \
    -e NEO4J_AUTH=neo4j/drillpassword -e 'NEO4J_PLUGINS=["apoc"]' \
    -e NEO4J_dbms_security_procedures_unrestricted='apoc.*' \
    -e NEO4J_dbms_security_procedures_allowlist='apoc.*' "$NEO4J_IMAGE" >/dev/null
  wait_neo "$ID-neo-src"
  neo_shell "$ID-neo-src" <<'CYPHER'
UNWIND range(1, 1200) AS i CREATE (:Entity {kb_id: 'kb' + (i % 3), canonical_name: 'e' + i, source_doc_ids: ['d' + (i % 7)]});
MATCH (a:Entity), (b:Entity) WHERE a.canonical_name = 'e' + 1 AND b.canonical_name IN ['e2', 'e3', 'e4'] CREATE (a)-[:RELATED_TO {source_doc_ids: ['d1']}]->(b);
MATCH (a:Entity) WHERE a.kb_id = 'kb1' WITH a LIMIT 100 MATCH (b:Entity {canonical_name: 'e2'}) CREATE (a)-[:MENTIONS]->(b);
CREATE CONSTRAINT drill_unique IF NOT EXISTS FOR (e:Entity) REQUIRE (e.kb_id, e.canonical_name) IS UNIQUE;
CYPHER
  neo_counts "$ID-neo-src" | sort > "$WORK/source.txt"

  say "running the chart's export script"
  docker run --rm --network "$ID" -v "$WORK:/out" -v "$FILES:/files:ro" \
    -e NEO4J_URI=bolt://neosource:7687 -e NEO4J_USER=neo4j -e NEO4J_PASSWORD=drillpassword \
    -e NEO4J_DATABASE=neo4j -e BACKUP_LOCAL_DIR=/out -e KEEP=2 "$PY_IMAGE" \
    sh -c 'pip install --quiet --disable-pip-version-check --root-user-action=ignore "neo4j>=5" && python /files/neo4j_backup.py'
  FILE="$(ls "$WORK"/abenix-neo4j-*.cypher.gz)"
  docker stop -t 5 "$ID-neo-src" >/dev/null

  say "restoring into a throwaway Neo4j"
  docker run -d --name "$ID-neo-restored" --network "$ID" -v "$FILES:/files:ro" -v "$WORK:/out:ro" \
    -e NEO4J_AUTH=neo4j/drillpassword "$NEO4J_IMAGE" >/dev/null
  wait_neo "$ID-neo-restored"
  docker exec -e NEO4J_URI=bolt://localhost:7687 -e NEO4J_USER=neo4j -e NEO4J_PASSWORD=drillpassword \
    "$ID-neo-restored" sh /files/restore-neo4j.sh "/out/$(basename "$FILE")"
  neo_counts "$ID-neo-restored" | sort > "$WORK/restored.txt"
  say "comparing node and relationship counts"
  python3 "$HERE/compare-counts.py" "$WORK/source.txt" "$WORK/restored.txt" 0
  neo_shell "$ID-neo-restored" "SHOW CONSTRAINTS YIELD name RETURN count(name)" | tail -1 | grep -qv '^0$' \
    && say "constraints came back"
  say "PASSED"
}

drill_minikube() {
  local kc=(kubectl -n "$NAMESPACE") pod="$ID" primary
  primary="$("${kc[@]}" get pods -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/name=postgresql,app.kubernetes.io/component=primary" -o jsonpath='{.items[0].metadata.name}')"
  [ -n "$primary" ] || { echo "no Postgres primary found for release $RELEASE" >&2; exit 1; }
  local job="$RELEASE-pg-basebackup"
  "${kc[@]}" get cronjob "$job" >/dev/null || {
    echo "$job is missing, install with backup.postgres.strategy=physical" >&2
    exit 1
  }
  trap '"${kc[@]}" delete pod "$pod" --ignore-not-found --wait=false >/dev/null; rm -rf "$WORK"' EXIT

  say "taking a fresh base backup with the chart's job"
  "${kc[@]}" delete job "$ID-base" --ignore-not-found >/dev/null
  "${kc[@]}" create job "$ID-base" --from="cronjob/$job" >/dev/null
  "${kc[@]}" wait --for=condition=complete --timeout=30m "job/$ID-base"
  "${kc[@]}" delete job "$ID-base" --wait=false >/dev/null

  say "reading row counts from the live primary"
  local password
  password="$("${kc[@]}" get secret abenix-secrets -o jsonpath='{.data.postgres-password}' | base64 -d)"
  "${kc[@]}" exec -i "$primary" -- env PGPASSWORD="$password" \
    psql -h 127.0.0.1 -U postgres -d "${DRILL_DB:-abenix}" -Atq < "$HERE/row-counts.sql" > "$WORK/source.txt"
  "${kc[@]}" exec "$primary" -- env PGPASSWORD="$password" \
    psql -h 127.0.0.1 -U postgres -d postgres -Atc "SELECT pg_switch_wal()" >/dev/null
  sleep "${DRILL_SHIP_WAIT:-45}"

  say "restoring into a throwaway pod"
  "${kc[@]}" get configmap "$RELEASE-backup-drill" -o jsonpath='{.data.pod\.json}' \
    | sed "s/__POD__/$pod/g" | "${kc[@]}" apply -f - >/dev/null
  "${kc[@]}" wait --for=condition=Ready --timeout=45m "pod/$pod"
  local i
  for i in $(seq 1 300); do
    if [ "$("${kc[@]}" exec "$pod" -c postgres -- psql -U postgres -d "${DRILL_DB:-abenix}" -Atc 'SELECT pg_is_in_recovery()' 2>/dev/null)" = "f" ]; then
      break
    fi
    sleep 5
  done
  "${kc[@]}" exec -i "$pod" -c postgres -- psql -U postgres -d "${DRILL_DB:-abenix}" -Atq \
    < "$HERE/row-counts.sql" > "$WORK/restored.txt"
  say "comparing row counts, a live source may move by $DRILL_PERCENT percent"
  python3 "$HERE/compare-counts.py" "$WORK/source.txt" "$WORK/restored.txt" "$DRIFT"
  say "PASSED"
}

DRILL_PERCENT="$DRIFT"
case "$MODE" in
  docker) drill_docker ;;
  neo4j-docker) drill_neo4j_docker ;;
  minikube) drill_minikube ;;
  *) echo "usage: restore-drill.sh docker | neo4j-docker | minikube" >&2; exit 2 ;;
esac
