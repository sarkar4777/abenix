#!/bin/sh
# Streams WAL into the volume through a replication slot, so a pause never loses any.
set -eu
WAL_DIR="${WAL_DIR:-/wal}"
SLOT="${WAL_SLOT:-abenix_wal}"
mkdir -p "$WAL_DIR"
pg_receivewal --slot="$SLOT" --create-slot --if-not-exists
echo "[backup] receiving WAL through slot $SLOT"
exec pg_receivewal -D "$WAL_DIR" --slot="$SLOT" --synchronous --no-password
