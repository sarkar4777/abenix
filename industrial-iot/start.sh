#!/bin/bash
# Industrial-IoT — Standalone Launch Script
#
# Starts the Industrial-IoT API (port 8003) and Web (port 3003).
# Invoked from scripts/dev-local.sh as Step 10; can also be run on its own.
# Requires Abenix to be running at http://localhost:8000.

set -e
IOT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$IOT_ROOT/.." && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log()  { echo -e "${CYAN}▸${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; }

# Python detect
if command -v python &>/dev/null; then PYTHON=python
elif command -v python3 &>/dev/null; then PYTHON=python3
else fail "Python not found"; exit 1; fi

# Source .env (same rules as the core script)
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

# Abenix health
log "Checking Abenix API at http://localhost:8000..."
if ! curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
  warn "Abenix API is not running on :8000 — pipeline calls will fail"
fi

# Install deps on first run
if ! $PYTHON -c "import fastapi" >/dev/null 2>&1; then
  log "Installing Industrial-IoT API deps..."
  $PYTHON -m pip install -q -r "$IOT_ROOT/api/requirements.txt" 2>&1 | tail -3 || true
fi

mkdir -p "$IOT_ROOT/logs"

# Kill lingering port listeners (Windows + *nix)
kill_port() {
  local port=$1
  local pids
  if command -v netstat &>/dev/null && netstat -ano 2>/dev/null | grep -q ":${port} .*LISTENING"; then
    pids=$(netstat -ano 2>/dev/null | grep ":${port} .*LISTENING" | awk '{print $5}' | sort -u | tr -d '\r')
    for pid in $pids; do
      [ -z "$pid" ] || [ "$pid" = "0" ] && continue
      taskkill //F //PID "$pid" >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null || true
    done
  else
    pids=$(lsof -ti:"$port" 2>/dev/null || true)
    [ -n "$pids" ] && echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
}
kill_port 8003
kill_port 3003
sleep 1

# Start API
log "Starting Industrial-IoT API on :8003..."
cd "$IOT_ROOT/api"
PORT=8003 \
ABENIX_API_URL="${ABENIX_API_URL:-http://localhost:8000}" \
INDUSTRIALIOT_ABENIX_API_KEY="${INDUSTRIALIOT_ABENIX_API_KEY:-${EXAMPLE_APP_ABENIX_API_KEY:-}}" \
$PYTHON main.py > "$IOT_ROOT/logs/api.log" 2>&1 &
IOT_API_PID=$!
sleep 4

API_OK=false
for _ in 1 2 3 4 5; do
  curl -sf http://localhost:8003/health >/dev/null 2>&1 && { API_OK=true; break; }
  sleep 2
done
if [ "$API_OK" = "true" ]; then ok "Industrial-IoT API healthy on :8003 (PID $IOT_API_PID)"
else warn "Industrial-IoT API not responding — tail $IOT_ROOT/logs/api.log"; fi

# Start Web
log "Starting Industrial-IoT Web on :3003..."
cd "$IOT_ROOT/web"
if [ ! -d "node_modules" ]; then
  log "npm install…"
  npm install --legacy-peer-deps > "$IOT_ROOT/logs/web-install.log" 2>&1
fi
INDUSTRIALIOT_API_INTERNAL_URL="http://localhost:8003" \
nohup npx next dev --port 3003 > "$IOT_ROOT/logs/web.log" 2>&1 &
IOT_WEB_PID=$!

sleep 6
WEB_OK=false
for _ in 1 2 3 4 5; do
  curl -sf http://localhost:3003 -o /dev/null >/dev/null 2>&1 && { WEB_OK=true; break; }
  sleep 3
done
[ "$WEB_OK" = "true" ] && ok "Industrial-IoT Web running on :3003 (PID $IOT_WEB_PID)" \
                        || warn "Industrial-IoT Web still starting — tail $IOT_ROOT/logs/web.log"

cd "$ROOT_DIR"
