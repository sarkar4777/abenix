#!/bin/bash
# ResolveAI — Standalone Launch Script
#
# Starts the ResolveAI API (port 8004) and Web (port 3004). Called from
# scripts/dev-local.sh as Step 11; runs fine on its own too. Abenix must
# be up at http://localhost:8000 — every reasoning step delegates to it
# via the bundled SDK.

set -e
RA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$RA_ROOT/.." && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log()  { echo -e "${CYAN}▸${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; }

if command -v python &>/dev/null; then PYTHON=python
elif command -v python3 &>/dev/null; then PYTHON=python3
else fail "Python not found"; exit 1; fi

# Source .env
if [ -f "$ROOT_DIR/.env" ]; then
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [[ -z "$key" ]] && continue
    key="${key%$'\r'}"; key="$(echo "$key" | xargs)"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    case "$value" in \[*|\{*) continue ;; esac
    value="${value%$'\r'}"
    [ -z "${!key}" ] && export "$key=$value" 2>/dev/null || true
  done < "$ROOT_DIR/.env"
fi

# Need Abenix
log "Checking Abenix API at http://localhost:8000..."
if ! curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
  warn "Abenix API is not running on :8000 — pipeline calls will 503"
fi

if [ -z "$RESOLVEAI_ABENIX_API_KEY" ]; then
  # Fall back to the the example app / Saudi Tourism key (same tenant, same AF).
  : "${RESOLVEAI_ABENIX_API_KEY:=${EXAMPLE_APP_ABENIX_API_KEY:-${SAUDITOURISM_ABENIX_API_KEY:-}}}"
  export RESOLVEAI_ABENIX_API_KEY
  [ -z "$RESOLVEAI_ABENIX_API_KEY" ] && warn "RESOLVEAI_ABENIX_API_KEY not set — pipeline calls will 503"
fi

# Probe — validate the key against Abenix /api/agents so a stale 401 surfaces in pod logs.
if [ -n "$RESOLVEAI_ABENIX_API_KEY" ]; then
  _AF_URL="${ABENIX_API_URL:-http://localhost:8000}"
  _CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -H "X-API-Key: $RESOLVEAI_ABENIX_API_KEY" "${_AF_URL}/api/agents" 2>/dev/null || echo "000")
  if [ "$_CODE" = "200" ]; then
    ok "RESOLVEAI_ABENIX_API_KEY validates against ${_AF_URL} (200)"
  elif [ "$_CODE" = "401" ] || [ "$_CODE" = "403" ]; then
    warn "RESOLVEAI_ABENIX_API_KEY rejected by ${_AF_URL} (${_CODE}) — pipeline calls will fail"
    warn "  Run: bash scripts/seed-standalone-keys.sh resolveai"
  else
    warn "Could not validate RESOLVEAI_ABENIX_API_KEY (got ${_CODE} from ${_AF_URL})"
  fi
fi

# Install API deps if missing
if ! $PYTHON -c "import fastapi" >/dev/null 2>&1; then
  log "Installing ResolveAI API deps..."
  $PYTHON -m pip install -q -r "$RA_ROOT/api/requirements.txt" 2>&1 | tail -3 || true
fi

mkdir -p "$RA_ROOT/logs"

kill_port() {
  local port=$1
  if command -v netstat &>/dev/null && netstat -ano 2>/dev/null | grep -q ":${port} .*LISTENING"; then
    local pids; pids=$(netstat -ano 2>/dev/null | grep ":${port} .*LISTENING" | awk '{print $5}' | sort -u | tr -d '\r')
    for pid in $pids; do
      [ -z "$pid" ] || [ "$pid" = "0" ] && continue
      taskkill //F //PID "$pid" >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null || true
    done
  else
    local pids; pids=$(lsof -ti:"$port" 2>/dev/null || true)
    [ -n "$pids" ] && echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
}
kill_port 8004
kill_port 3004
sleep 1

# API
log "Starting ResolveAI API on :8004..."
cd "$RA_ROOT/api"
PORT=8004 \
ABENIX_API_URL="${ABENIX_API_URL:-http://localhost:8000}" \
RESOLVEAI_ABENIX_API_KEY="$RESOLVEAI_ABENIX_API_KEY" \
$PYTHON main.py > "$RA_ROOT/logs/api.log" 2>&1 &
RA_API_PID=$!
sleep 4

API_OK=false
for _ in 1 2 3 4 5; do
  curl -sf http://localhost:8004/health >/dev/null 2>&1 && { API_OK=true; break; }
  sleep 2
done
if [ "$API_OK" = "true" ]; then ok "ResolveAI API healthy on :8004 (PID $RA_API_PID)"
else warn "ResolveAI API not responding — tail $RA_ROOT/logs/api.log"; fi

# Web
log "Starting ResolveAI Web on :3004..."
cd "$RA_ROOT/web"
if [ ! -d "node_modules" ]; then
  log "npm install…"
  npm install --legacy-peer-deps > "$RA_ROOT/logs/web-install.log" 2>&1
fi
RESOLVEAI_API_INTERNAL_URL="http://localhost:8004" \
nohup npx next dev --port 3004 > "$RA_ROOT/logs/web.log" 2>&1 &
RA_WEB_PID=$!

sleep 6
WEB_OK=false
for _ in 1 2 3 4 5; do
  curl -sf http://localhost:3004 -o /dev/null >/dev/null 2>&1 && { WEB_OK=true; break; }
  sleep 3
done
[ "$WEB_OK" = "true" ] && ok "ResolveAI Web running on :3004 (PID $RA_WEB_PID)" \
                        || warn "ResolveAI Web still starting — tail $RA_ROOT/logs/web.log"

cd "$ROOT_DIR"
