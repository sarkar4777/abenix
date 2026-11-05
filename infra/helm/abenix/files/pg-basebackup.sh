#!/bin/sh
# Streams a base backup into a pipe the uploader reads, so no local disk has to hold it.
# PGHOST, PGUSER and PGPASSWORD come from the environment.
set -u
WORK="${WORK:-/work}"
FIFO="$WORK/base.fifo"
rm -f "$WORK/status" "$WORK/start_wal"
[ -p "$FIFO" ] || mkfifo "$FIFO"
chmod 666 "$FIFO"

START_WAL=$(psql -d postgres -Atc "SELECT pg_walfile_name(pg_current_wal_lsn())")
echo "$START_WAL" > "$WORK/start_wal"

echo "[backup] base backup starting at $(date), WAL $START_WAL"
# -X none because the WAL archive already holds what replay needs
pg_basebackup -D - -Ft -z -Z "${BASE_COMPRESS:-1}" -X none --no-manifest \
  --checkpoint=fast --label="abenix-$(date +%Y%m%d-%H%M%S)" > "$FIFO"
STATUS=$?
echo "$STATUS" > "$WORK/status"
echo "[backup] pg_basebackup exited with $STATUS"
exit "$STATUS"
