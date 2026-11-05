#!/bin/sh
# Rebuilds a data directory from a fetched base backup and WAL, then replays it.
# Run as restore-postgres.sh RESTORE_DIR PGDATA [TARGET_TIME]
# RESTORE_DIR holds base.tar.gz and wal/ from backup_store.py fetch-physical.
# TARGET_TIME stops replay at that moment, empty replays everything fetched.
set -eu
RESTORE_DIR="$1"
PGDATA="$2"
TARGET_TIME="${3:-}"

mkdir -p "$PGDATA"
if [ -n "$(ls -A "$PGDATA" 2>/dev/null)" ]; then
  echo "[restore] $PGDATA is not empty, refusing to overwrite it" >&2
  exit 1
fi
tar -xzf "$RESTORE_DIR/base.tar.gz" -C "$PGDATA"
mkdir -p "$PGDATA/pg_wal"

# the last segment is still open at the source, its copy holds the newest changes
WAL="$RESTORE_DIR/wal"
for partial in "$WAL"/*.partial; do
  [ -e "$partial" ] || continue
  whole="${partial%.partial}"
  if [ -e "$whole" ]; then
    rm -f "$partial"
  else
    mv "$partial" "$whole"
    echo "[restore] using the open segment $(basename "$whole")"
  fi
done

# Bitnami keeps its config outside the data directory, a base backup may have none
[ -f "$PGDATA/postgresql.conf" ] || : > "$PGDATA/postgresql.conf"
cat > "$PGDATA/pg_hba.conf" <<HBA
local all all trust
host all all all trust
HBA
{
  echo "restore_command = 'cp $WAL/%f %p'"
  echo "recovery_target_timeline = 'latest'"
  echo "listen_addresses = '*'"
  echo "hot_standby = on"
  echo "archive_mode = off"
  echo "shared_preload_libraries = ''"
  if [ -n "$TARGET_TIME" ]; then
    echo "recovery_target_time = '$TARGET_TIME'"
    echo "recovery_target_action = 'promote'"
  fi
} >> "$PGDATA/postgresql.auto.conf"
: > "$PGDATA/recovery.signal"
rm -f "$PGDATA/postmaster.pid"
chmod 700 "$PGDATA"
echo "[restore] data directory ready at $PGDATA, starting recovery"
