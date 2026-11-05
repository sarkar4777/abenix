#!/bin/bash
# ContractIQ — Standalone Launch Script
#
# Starts the ContractIQ API (port 8001) and Web (port 3001).
# Requires Abenix to be running (default: http://localhost:8000).

set -e

CIQ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$CIQ_ROOT/.." && pwd)"

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
  warn "ContractIQ requires Abenix to be running for AI features"
  warn "Start Abenix first: cd $ROOT_DIR && bash scripts/dev-local.sh"
  warn "Continuing anyway — the chat feature will fail until Abenix is up"
fi

if [ -f "$ROOT_DIR/.env" ]; then
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [[ -z "$key" ]] && continue
    key="${key%$'\r'}"
    key="$(echo "$key" | xargs)"
    # Skip anything that isn't a valid shell identifier (avoids failing
    # the indirect expansion `${!key}` below with "invalid variable name").
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    case "$value" in
      \[*|\{*) continue ;;   # skip JSON arrays/objects
    esac
    # Strip trailing CR — .env may have CRLF endings, which would leave
    # e.g. DATABASE_URL=...abenix\r and asyncpg fails to find the DB.
    value="${value%$'\r'}"
    # Only set if not already in environment so caller overrides win.
    if [ -z "${!key}" ]; then
      export "$key=$value" 2>/dev/null || true
    fi
  done < "$ROOT_DIR/.env"
fi

if [ -z "$CONTRACTIQ_ABENIX_API_KEY" ]; then
  warn "CONTRACTIQ_ABENIX_API_KEY not set — chat will fail"
  warn "Create a key in Abenix with can_delegate scope and set the env var"
else
  # Startup probe — validate the key against Abenix /api/agents. Surfaces
  # 401s loudly in the launch log so a bad/stale key doesn't masquerade
  # as a runtime bug 30 minutes into a chat session.
  _AF_URL="${ABENIX_API_URL:-http://localhost:8000}"
  _CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -H "X-API-Key: $CONTRACTIQ_ABENIX_API_KEY" "${_AF_URL}/api/agents" 2>/dev/null || echo "000")
  if [ "$_CODE" = "200" ]; then
    ok "CONTRACTIQ_ABENIX_API_KEY validates against ${_AF_URL} (200)"
  elif [ "$_CODE" = "401" ] || [ "$_CODE" = "403" ]; then
    fail "CONTRACTIQ_ABENIX_API_KEY rejected by ${_AF_URL} (${_CODE}) — chat will fail"
    fail "  Run: bash scripts/seed-standalone-keys.sh contractiq"
  else
    warn "Could not validate CONTRACTIQ_ABENIX_API_KEY (got ${_CODE} from ${_AF_URL})"
  fi
fi

# asyncpg rejects any sslmode value other than disable/allow/prefer/require/
# verify-ca/verify-full. The local-dev Postgres runs plaintext, so default to
# disable unless the caller set PGSSLMODE explicitly.
if [ -z "$PGSSLMODE" ]; then
  export PGSSLMODE=disable
fi

# Create logs dir
mkdir -p "$CIQ_ROOT/logs"

# Kill any existing ContractIQ API
log "Stopping any existing ContractIQ API on port 8001..."
PID=$(netstat -ano 2>/dev/null | grep ":8001.*LISTENING" | awk '{print $5}' | head -1 || true)
if [ -n "$PID" ]; then
  taskkill //PID "$PID" //F 2>/dev/null || kill -9 "$PID" 2>/dev/null || true
  sleep 2
fi

# Start the API
log "Starting ContractIQ API on port 8001..."
cd "$CIQ_ROOT/api"

# The subprocess inherits the shell's env (we sourced .env above). Only
# explicitly override values that differ from .env — port, AF URL, and
# a couple of overrides that must win regardless of .env contents.
#
# --reload is required for local dev: without it, edits to engine/ or
# translator code don't take effect until a manual restart (was a real
# UAT trap — the api ran stale bytecode for 4 minutes post-edit).
PORT=8001 \
ABENIX_API_URL="${ABENIX_API_URL:-http://localhost:8000}" \
IS_LOCAL_DEV=1 ENVIRONMENT=local \
$PYTHON -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload \
  --reload-dir . --reload-dir "$ROOT_DIR/apps/agent-runtime" \
  > "$CIQ_ROOT/logs/api.log" 2>&1 &

CIQ_PID=$!
sleep 5

# API health check
API_OK=false
for i in 1 2 3 4 5; do
  if curl -sf http://localhost:8001/api/health >/dev/null 2>&1; then
    API_OK=true
    break
  fi
  sleep 2
done

if [ "$API_OK" = "true" ]; then
  ok "ContractIQ API is healthy on port 8001"
else
  fail "ContractIQ API failed to start"
  tail -20 "$CIQ_ROOT/logs/api.log" 2>/dev/null || true
  exit 1
fi

# Start the web frontend
log "Starting ContractIQ Web on port 3001..."
PID=$(netstat -ano 2>/dev/null | grep ":3001.*LISTENING" | awk '{print $5}' | head -1 || true)
if [ -n "$PID" ]; then
  taskkill //PID "$PID" //F 2>/dev/null || kill -9 "$PID" 2>/dev/null || true
  sleep 2
fi

cd "$CIQ_ROOT/web"
if [ ! -d "node_modules" ]; then
  log "Installing web dependencies..."
  npm install > "$CIQ_ROOT/logs/web-install.log" 2>&1
fi

NEXT_PUBLIC_API_URL="http://localhost:8001" \
nohup npm run dev > "$CIQ_ROOT/logs/web.log" 2>&1 &
WEB_PID=$!

# Web health check
sleep 6
WEB_OK=false
for i in 1 2 3 4 5; do
  if curl -sf http://localhost:3001 >/dev/null 2>&1; then
    WEB_OK=true
    break
  fi
  sleep 3
done

if [ "$WEB_OK" = "true" ]; then
  ok "ContractIQ Web is running on port 3001"
else
  warn "ContractIQ Web may still be starting (check logs)"
fi

echo ""
echo -e "  ${CYAN}ContractIQ Web${NC}       http://localhost:3001"
echo -e "  ${CYAN}ContractIQ API${NC}       http://localhost:8001"
echo -e "  ${CYAN}Health Check${NC}         http://localhost:8001/api/health"
echo -e "  ${CYAN}API Logs${NC}             tail -f $CIQ_ROOT/logs/api.log"
echo -e "  ${CYAN}Web Logs${NC}             tail -f $CIQ_ROOT/logs/web.log"
echo ""
exit 0
