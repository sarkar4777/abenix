#!/bin/bash
# PharmaVigil — Standalone Launch Script
#
# Starts the PharmaVigil API (port 8007) and Web (port 3007). Called from
# scripts/dev-local.sh when the app is selected; runs fine on its own too.
# Abenix must be up at http://localhost:8000 — every reasoning step delegates to it
# via the bundled SDK.

set -e
PV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$PV_ROOT/.." && pwd)"

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

if [ -z "$PHARMAVIGIL_ABENIX_API_KEY" ]; then
  # Fall back to the ContractIQ / Mideast Tourism key (same tenant, same AF).
  : "${PHARMAVIGIL_ABENIX_API_KEY:=${CONTRACTIQ_ABENIX_API_KEY:-${MIDEASTTOURISM_ABENIX_API_KEY:-}}}"
  export PHARMAVIGIL_ABENIX_API_KEY
  [ -z "$PHARMAVIGIL_ABENIX_API_KEY" ] && warn "PHARMAVIGIL_ABENIX_API_KEY not set — pipeline calls will 503"
fi

# Probe — validate the key against Abenix /api/agents so a stale 401 surfaces in pod logs.
if [ -n "$PHARMAVIGIL_ABENIX_API_KEY" ]; then
  _AF_URL="${ABENIX_API_URL:-http://localhost:8000}"
  _CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -H "X-API-Key: $PHARMAVIGIL_ABENIX_API_KEY" "${_AF_URL}/api/agents" 2>/dev/null || echo "000")
  if [ "$_CODE" = "200" ]; then
    ok "PHARMAVIGIL_ABENIX_API_KEY validates against ${_AF_URL} (200)"
  elif [ "$_CODE" = "401" ] || [ "$_CODE" = "403" ]; then
    warn "PHARMAVIGIL_ABENIX_API_KEY rejected by ${_AF_URL} (${_CODE}) — pipeline calls will fail"
    warn "  Run: bash scripts/seed-standalone-keys.sh pharmavigil"
  else
    warn "Could not validate PHARMAVIGIL_ABENIX_API_KEY (got ${_CODE} from ${_AF_URL})"
  fi
fi

# Install API deps if missing
if ! $PYTHON -c "import fastapi" >/dev/null 2>&1; then
  log "Installing PharmaVigil API deps..."
  $PYTHON -m pip install -q -r "$PV_ROOT/api/requirements.txt" 2>&1 | tail -3 || true
fi

mkdir -p "$PV_ROOT/logs"

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
kill_port 8007
kill_port 3007
sleep 1

# API
log "Starting PharmaVigil API on :8007..."
cd "$PV_ROOT/api"
PORT=8007 \
ABENIX_API_URL="${ABENIX_API_URL:-http://localhost:8000}" \
PHARMAVIGIL_ABENIX_API_KEY="$PHARMAVIGIL_ABENIX_API_KEY" \
$PYTHON main.py > "$PV_ROOT/logs/api.log" 2>&1 &
PV_API_PID=$!
sleep 4

API_OK=false
for _ in 1 2 3 4 5; do
  curl -sf http://localhost:8007/health >/dev/null 2>&1 && { API_OK=true; break; }
  sleep 2
done
if [ "$API_OK" = "true" ]; then ok "PharmaVigil API healthy on :8007 (PID $PV_API_PID)"
else warn "PharmaVigil API not responding — tail $PV_ROOT/logs/api.log"; fi

# Web
log "Starting PharmaVigil Web on :3007..."
cd "$PV_ROOT/web"
if [ ! -d "node_modules" ]; then
  log "npm install…"
  npm install --legacy-peer-deps > "$PV_ROOT/logs/web-install.log" 2>&1
fi
PHARMAVIGIL_API_INTERNAL_URL="http://localhost:8007" \
nohup npx next dev --port 3007 > "$PV_ROOT/logs/web.log" 2>&1 &
PV_WEB_PID=$!

sleep 6
WEB_OK=false
for _ in 1 2 3 4 5; do
  curl -sf http://localhost:3007 -o /dev/null >/dev/null 2>&1 && { WEB_OK=true; break; }
  sleep 3
done
[ "$WEB_OK" = "true" ] && ok "PharmaVigil Web running on :3007 (PID $PV_WEB_PID)" \
                        || warn "PharmaVigil Web still starting — tail $PV_ROOT/logs/web.log"

cd "$ROOT_DIR"
