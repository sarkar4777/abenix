#!/bin/sh
# Replays a Cypher export into a Neo4j that holds nothing yet.
# Run as restore-neo4j.sh FILE.cypher.gz, with NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD set.
set -eu
FILE="$1"
EXISTING=$(cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" --format plain \
  "MATCH (n) RETURN count(n)" | tail -1)
if [ "$EXISTING" != "0" ]; then
  echo "[restore] this database already holds $EXISTING nodes, refusing to add to them" >&2
  exit 1
fi
gunzip -c "$FILE" | cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" --fail-fast
echo "[restore] replayed $FILE"
