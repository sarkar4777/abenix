#!/usr/bin/env bash
# Verify the live database schema matches what alembic head produces.
#
# Use cases:
#   * `bash scripts/verify-schema.sh`              — verify only, exit 1 on drift
#   * `bash scripts/verify-schema.sh --reset`      — drop + recreate + re-migrate (DESTROYS ALL DATA)
#   * `bash scripts/verify-schema.sh --pod=NAME`   — verify against a k8s pod via kubectl exec
#
# Run automatically by:
#   * `dev-local.sh` Step 4/7 (auto-resets on drift in local mode)
#   * CI on every deploy (verify only — never auto-destroy prod)
#   * The CD pipeline before flipping traffic
#
# The canonical columns list below is the sentinel — keep it small,
# load-bearing, and updated whenever a meaningful migration lands.

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESET=false
POD_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset) RESET=true ;;
    --pod=*) POD_NAME="${1#*=}" ;;
    --pod)   POD_NAME="$2"; shift ;;
    -h|--help)
      grep '^#' "$0" | head -25
      exit 0
      ;;
  esac
  shift
done

CANONICAL_COLUMNS=(
  "executions.node_results"
  "executions.execution_trace"
  "executions.failure_code"
  "agent_shares.shared_with_user_id"
  "moderation_policies.default_action"
  "agent_memories.importance"
)

_psql() {
  if [ -n "$POD_NAME" ]; then
    kubectl exec "$POD_NAME" -- psql "$DATABASE_URL_SYNC" -tAc "$1"
  elif command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -q '^abenix-postgres$'; then
    docker exec abenix-postgres psql -U "${POSTGRES_USER:-abenix}" -d "${POSTGRES_DB:-abenix}" -tAc "$1"
  else
    psql "$DATABASE_URL_SYNC" -tAc "$1"
  fi
}

check_drift() {
  local missing=""
  for entry in "${CANONICAL_COLUMNS[@]}"; do
    local table="${entry%.*}"
    local column="${entry#*.}"
    local exists
    exists=$(_psql "SELECT 1 FROM information_schema.columns WHERE table_name='$table' AND column_name='$column'" 2>/dev/null || echo "")
    if [ -z "$exists" ]; then
      missing="$missing $entry"
    fi
  done
  echo "$missing"
}

reset_database() {
  echo "DESTRUCTIVE: Dropping + recreating abenix database to fix schema drift"
  docker exec abenix-postgres psql -U abenix -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='abenix' AND pid <> pg_backend_pid()" >/dev/null 2>&1 || true
  docker exec abenix-postgres psql -U abenix -d postgres -c "DROP DATABASE IF EXISTS abenix" >/dev/null 2>&1
  docker exec abenix-postgres psql -U abenix -d postgres -c "CREATE DATABASE abenix" >/dev/null 2>&1
  cd "$ROOT_DIR/packages/db"
  PYTHONPATH="." python -m alembic upgrade head
  cd "$ROOT_DIR"
}

DRIFT=$(check_drift)
if [ -n "$DRIFT" ]; then
  echo "ERROR: Schema drift detected. Missing columns:$DRIFT" >&2
  if [ "$RESET" = true ]; then
    reset_database
    DRIFT=$(check_drift)
    if [ -n "$DRIFT" ]; then
      echo "FATAL: Drift persists after reset:$DRIFT" >&2
      exit 5
    fi
    echo "OK: Schema repaired after reset"
    exit 0
  fi
  echo "Run again with --reset to drop + recreate (DESTROYS DATA)" >&2
  exit 1
fi

echo "OK: Schema verified — all canonical columns present"
exit 0
