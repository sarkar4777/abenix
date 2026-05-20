#!/bin/bash
# Wingman — Standalone Launch Script
#
# Starts the Wingman API (port 8006) and Web (port 3006).
# Requires Abenix to be running (default: http://localhost:8000).

set -e

WM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$WM_ROOT/.." && pwd)"

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

log "Checking Abenix API at http://localhost:8000..."
if ! curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
  warn "Abenix API is not running on port 8000"
  warn "Wingman requires Abenix for every interesting computation (corridor scans, scenarios, etc.)"
  warn "Start Abenix first: cd $ROOT_DIR && bash scripts/dev-local.sh"
  warn "Continuing anyway — agent calls will 502 until Abenix is up"
fi

# Load .env values
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

if [ -z "$WINGMAN_ABENIX_API_KEY" ]; then
  warn "WINGMAN_ABENIX_API_KEY not set — chat + scans will fail"
  warn "Create a key in Abenix with can_delegate scope and set the env var"
else
  _AF_URL="${ABENIX_API_URL:-http://localhost:8000}"
  _CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -H "X-API-Key: $WINGMAN_ABENIX_API_KEY" "${_AF_URL}/api/agents" 2>/dev/null || echo "000")
  if [ "$_CODE" = "200" ]; then
    ok "WINGMAN_ABENIX_API_KEY validates against ${_AF_URL} (200)"
  elif [ "$_CODE" = "401" ] || [ "$_CODE" = "403" ]; then
    fail "WINGMAN_ABENIX_API_KEY rejected by ${_AF_URL} (${_CODE}) — agent calls will fail"
    fail "  Run: bash scripts/seed-standalone-keys.sh wingman"
  else
    warn "Could not validate WINGMAN_ABENIX_API_KEY (got ${_CODE} from ${_AF_URL})"
  fi
fi

# Optional: AISStream key for the Operations Watch live AIS feature.
[ -z "$AISSTREAM_API_KEY" ] && warn "AISSTREAM_API_KEY not set — live AIS map disabled (non-fatal)"

mkdir -p "$WM_ROOT/logs"

# Stop any existing Wingman API on 8006
log "Stopping any existing Wingman API on port 8006..."
PID=$(netstat -ano 2>/dev/null | grep ":8006.*LISTENING" | awk '{print $5}' | head -1 || true)
if [ -n "$PID" ]; then
  taskkill //PID "$PID" //F 2>/dev/null || kill -9 "$PID" 2>/dev/null || true
  sleep 2
fi

log "Starting Wingman API on port 8006..."
cd "$WM_ROOT/api"

PORT=8006 \
ABENIX_API_URL="${ABENIX_API_URL:-http://localhost:8000}" \
$PYTHON -m uvicorn main:app --host 0.0.0.0 --port 8006 > "$WM_ROOT/logs/api.log" 2>&1 &

WM_PID=$!
sleep 5

API_OK=false
for i in 1 2 3 4 5; do
  if curl -sf http://localhost:8006/health >/dev/null 2>&1; then
    API_OK=true
    break
  fi
  sleep 2
done

if [ "$API_OK" = "true" ]; then
  ok "Wingman API is healthy on port 8006"
else
  fail "Wingman API failed to start"
  tail -20 "$WM_ROOT/logs/api.log" 2>/dev/null || true
  exit 1
fi

log "Starting Wingman Web on port 3006..."
PID=$(netstat -ano 2>/dev/null | grep ":3006.*LISTENING" | awk '{print $5}' | head -1 || true)
if [ -n "$PID" ]; then
  taskkill //PID "$PID" //F 2>/dev/null || kill -9 "$PID" 2>/dev/null || true
  sleep 2
fi

cd "$WM_ROOT/web"
if [ ! -d "node_modules" ]; then
  log "Installing web dependencies..."
  npm install > "$WM_ROOT/logs/web-install.log" 2>&1
fi

WINGMAN_API_INTERNAL_URL="http://localhost:8006" \
nohup npm run dev -- -p 3006 > "$WM_ROOT/logs/web.log" 2>&1 &
WEB_PID=$!

sleep 6
WEB_OK=false
for i in 1 2 3 4 5; do
  if curl -sf http://localhost:3006 >/dev/null 2>&1; then
    WEB_OK=true
    break
  fi
  sleep 3
done

if [ "$WEB_OK" = "true" ]; then
  ok "Wingman Web is running on port 3006"
else
  warn "Wingman Web may still be starting (check logs)"
fi

echo ""
echo -e "  ${CYAN}Wingman Web${NC}        http://localhost:3006"
echo -e "  ${CYAN}Wingman API${NC}        http://localhost:8006"
echo -e "  ${CYAN}Health Check${NC}       http://localhost:8006/health"
echo -e "  ${CYAN}API Logs${NC}           tail -f $WM_ROOT/logs/api.log"
echo -e "  ${CYAN}Web Logs${NC}           tail -f $WM_ROOT/logs/web.log"
echo ""
exit 0
