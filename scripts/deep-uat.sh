#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${CYAN}[deep-uat]${NC} $*"; }
ok()   { echo -e "${GREEN}  ✓${NC} $*"; }
warn() { echo -e "${YELLOW}  !${NC} $*"; }
err()  { echo -e "${RED}  ✗${NC} $*"; }

NO_RESET=false
for arg in "$@"; do
  [ "$arg" = "--no-reset" ] && NO_RESET=true
done

if [ "$NO_RESET" != true ]; then
  log "Step 1/4 — Stopping Abenix processes & wiping docker volumes"
  bash "$ROOT_DIR/scripts/dev-local.sh" --stop >/dev/null 2>&1 || true
  docker compose down -v 2>&1 | sed 's/^/      /' || true
  ok "stack reset"
else
  log "Step 1/4 — Skipping reset (--no-reset)"
fi

log "Step 2/4 — Cold-starting the local stack via start.sh"
START_LOG="$ROOT_DIR/logs/deep-uat-start.log"
mkdir -p "$ROOT_DIR/logs"
bash "$ROOT_DIR/scripts/dev-local.sh" > "$START_LOG" 2>&1 &
START_PID=$!

log "Step 3/4 — Waiting for API (:8000) and Web (:3000) to become ready"
READY=false
for i in $(seq 1 180); do
  API_OK=false; WEB_OK=false
  curl -s --max-time 3 http://localhost:8000/api/health >/dev/null 2>&1 && API_OK=true
  curl -s --max-time 3 http://localhost:3000 -o /dev/null 2>&1 && WEB_OK=true
  if [ "$API_OK" = true ] && [ "$WEB_OK" = true ]; then READY=true; break; fi
  sleep 2
done

if [ "$READY" != true ]; then
  err "Services did not come up within 6 minutes"
  err "Tail of start.sh log:"
  tail -40 "$START_LOG" 2>/dev/null | sed 's/^/      /'
  exit 1
fi
ok "API + Web are responsive"

log "Letting Next.js warm up dev compilation for /agents, /atlas, /knowledge, /builder"
for path in /dashboard /agents /atlas /knowledge /knowledge/projects /chat /builder /settings/security; do
  curl -s --max-time 15 "http://localhost:3000${path}" -o /dev/null 2>&1 || true
done
ok "warm-up done"

log "Step 4/4 — Running scripts/deep-uat.ts via npx tsx"
export ABENIX_URL="${ABENIX_URL:-http://localhost:3000}"
export ABENIX_EMAIL="${ABENIX_EMAIL:-admin@abenix.dev}"
export ABENIX_PASSWORD="${ABENIX_PASSWORD:-Admin123456}"

set +e
npx -y tsx scripts/deep-uat.ts
EXIT=$?
set -e

if [ $EXIT -eq 0 ]; then
  ok "Deep UAT passed"
else
  err "Deep UAT failed (exit=$EXIT) — see docs/screenshots/deep-uat/report.md"
fi
exit $EXIT
