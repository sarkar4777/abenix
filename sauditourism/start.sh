#!/bin/bash
# Saudi Tourism Analytics — Standalone Launch Script
#
# Starts the Saudi Tourism API (port 8002) and Web (port 3002).
# Requires Abenix to be running (default: http://localhost:8000).

set -e

ST_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$ST_ROOT/.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()    { echo -e "${GREEN}✓${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠${NC} $1"; }
log()   { echo -e "${CYAN}▸${NC} $1"; }
fail()  { echo -e "${RED}✗${NC} $1"; }

# Detect Python
if command -v python &>/dev/null; then
  PYTHON=python
elif command -v python3 &>/dev/null; then
  PYTHON=python3
else
  fail "Python not found"
  exit 1
fi

# Check Abenix is running
log "Checking Abenix API at http://localhost:8000..."
if ! curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
  warn "Abenix API is not running on port 8000"
  warn "Saudi Tourism requires Abenix for ALL analytics features"
  warn "Start Abenix first: cd $ROOT_DIR && bash scripts/dev-local.sh"
  warn "Continuing anyway — all agent-powered features will fail"
fi

# Source ALL vars from main .env
if [ -f "$ROOT_DIR/.env" ]; then
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [[ -z "$key" ]] && continue
    key="${key%$'\r'}"
    key="$(echo "$key" | xargs)"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    case "$value" in
      \[*|\{*) continue ;;
    esac
    value="${value%$'\r'}"
    if [ -z "${!key}" ]; then
      export "$key=$value" 2>/dev/null || true
    fi
  done < "$ROOT_DIR/.env"
fi

if [ -z "$SAUDITOURISM_ABENIX_API_KEY" ]; then
  warn "SAUDITOURISM_ABENIX_API_KEY not set — all agent features will fail"
  warn "Create a key in Abenix with can_delegate scope and set the env var"
else
  _AF_URL="${ABENIX_API_URL:-http://localhost:8000}"
  _CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -H "X-API-Key: $SAUDITOURISM_ABENIX_API_KEY" "${_AF_URL}/api/agents" 2>/dev/null || echo "000")
  if [ "$_CODE" = "200" ]; then
    ok "SAUDITOURISM_ABENIX_API_KEY validates against ${_AF_URL} (200)"
  elif [ "$_CODE" = "401" ] || [ "$_CODE" = "403" ]; then
    fail "SAUDITOURISM_ABENIX_API_KEY rejected by ${_AF_URL} (${_CODE}) — agent calls will fail"
    fail "  Run: bash scripts/seed-standalone-keys.sh sauditourism"
  else
    warn "Could not validate SAUDITOURISM_ABENIX_API_KEY (got ${_CODE} from ${_AF_URL})"
  fi
fi

if [ -z "$PGSSLMODE" ]; then
  export PGSSLMODE=disable
fi

# Create logs dir
mkdir -p "$ST_ROOT/logs"

# Kill any existing Saudi Tourism API
log "Stopping any existing Saudi Tourism API on port 8002..."
PID=$(netstat -ano 2>/dev/null | grep ":8002.*LISTENING" | awk '{print $5}' | head -1 || true)
if [ -n "$PID" ]; then
  taskkill //PID "$PID" //F 2>/dev/null || kill -9 "$PID" 2>/dev/null || true
  sleep 2
fi

# Start the API
log "Starting Saudi Tourism API on port 8002..."
cd "$ST_ROOT/api"

PORT=8002 \
ABENIX_API_URL="${ABENIX_API_URL:-http://localhost:8000}" \
$PYTHON main.py > "$ST_ROOT/logs/api.log" 2>&1 &

ST_PID=$!
sleep 5

# API health check
API_OK=false
for i in 1 2 3 4 5; do
  if curl -sf http://localhost:8002/api/health >/dev/null 2>&1; then
    API_OK=true
    break
  fi
  sleep 2
done

if [ "$API_OK" = "true" ]; then
  ok "Saudi Tourism API is healthy on port 8002"
else
  fail "Saudi Tourism API failed to start"
  tail -20 "$ST_ROOT/logs/api.log" 2>/dev/null || true
  exit 1
fi

# Start the web frontend
log "Starting Saudi Tourism Web on port 3002..."
PID=$(netstat -ano 2>/dev/null | grep ":3002.*LISTENING" | awk '{print $5}' | head -1 || true)
if [ -n "$PID" ]; then
  taskkill //PID "$PID" //F 2>/dev/null || kill -9 "$PID" 2>/dev/null || true
  sleep 2
fi

cd "$ST_ROOT/web"
if [ ! -d "node_modules" ]; then
  log "Installing web dependencies..."
  npm install > "$ST_ROOT/logs/web-install.log" 2>&1
fi

NEXT_PUBLIC_API_URL="http://localhost:8002" \
nohup npm run dev > "$ST_ROOT/logs/web.log" 2>&1 &
WEB_PID=$!

# Web health check
sleep 6
WEB_OK=false
for i in 1 2 3 4 5; do
  if curl -sf http://localhost:3002 >/dev/null 2>&1; then
    WEB_OK=true
    break
  fi
  sleep 3
done

if [ "$WEB_OK" = "true" ]; then
  ok "Saudi Tourism Web is running on port 3002"
else
  warn "Saudi Tourism Web may still be starting (check logs)"
fi

echo ""
echo -e "  ${GREEN}Saudi Tourism Web${NC}     http://localhost:3002"
echo -e "  ${GREEN}Saudi Tourism API${NC}     http://localhost:8002"
echo -e "  ${GREEN}Health Check${NC}          http://localhost:8002/api/health"
echo -e "  ${GREEN}API Logs${NC}              tail -f $ST_ROOT/logs/api.log"
echo -e "  ${GREEN}Web Logs${NC}              tail -f $ST_ROOT/logs/web.log"
echo ""
echo -e "  Demo credentials: ${CYAN}test@sauditourism.gov.sa${NC} / ${CYAN}TestPass123!${NC}"
echo ""
exit 0
