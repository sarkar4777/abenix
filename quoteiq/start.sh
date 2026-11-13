#!/bin/bash
# QuoteIQ — Standalone Launch Script
#
# Starts the QuoteIQ API (port 8008) and Web (port 3008). Called from
# scripts/dev-local.sh when the app is selected; runs fine on its own too.
# Abenix must be up at http://localhost:8000 — the RFQ pipeline and the email
# drafter run there, reached through the bundled SDK.

set -e
QQ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$QQ_ROOT/.." && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log()  { echo -e "${CYAN}▸${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; }

if [ -x "$ROOT_DIR/.venv/bin/python" ]; then PYTHON="$ROOT_DIR/.venv/bin/python"
elif command -v python &>/dev/null; then PYTHON=python
elif command -v python3 &>/dev/null; then PYTHON=python3
else fail "Python not found"; exit 1; fi

# Source .env, without overriding what the caller already exported
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

_AF_URL="${ABENIX_API_URL:-http://localhost:8000}"
log "Checking Abenix API at ${_AF_URL}..."
if ! curl -sf "${_AF_URL}/api/health" >/dev/null 2>&1; then
  warn "Abenix API is not running on ${_AF_URL} — processing an email will fail until it is"
fi

# The key needs can_delegate: every run is made on behalf of the reviewer.
# dev-local.sh mints or validates it and exports it before calling this.
if [ -z "$QUOTEIQ_ABENIX_API_KEY" ]; then
  warn "QUOTEIQ_ABENIX_API_KEY not set — see quoteiq/README.md, step 3"
else
  _CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -H "X-API-Key: $QUOTEIQ_ABENIX_API_KEY" "${_AF_URL}/api/agents/by-slug/quoteiq-rfq" 2>/dev/null || echo "000")
  case "$_CODE" in
    200) ok "QUOTEIQ_ABENIX_API_KEY validates and the quoteiq-rfq pipeline is registered" ;;
    401|403) warn "QUOTEIQ_ABENIX_API_KEY rejected by ${_AF_URL} (${_CODE})" ;;
    404) warn "The quoteiq-rfq pipeline is not registered — run packages/db/seeds/seed_agents.py" ;;
    *) warn "Could not validate QUOTEIQ_ABENIX_API_KEY (got ${_CODE} from ${_AF_URL})" ;;
  esac
fi

mkdir -p "$QQ_ROOT/logs"

# The mock ERP is a code asset. dev-local.sh doesn't seed code assets, so do
# it here; the seeder is idempotent and skips assets that already exist.
log "Seeding the QuoteIQ ERP code asset (idempotent)..."
if (cd "$ROOT_DIR/packages/db" && \
    CODE_ASSET_STORE="${CODE_ASSET_STORE:-$ROOT_DIR/.data/code-assets}" \
    $PYTHON seeds/seed_code_assets.py > "$QQ_ROOT/logs/seed-code-assets.log" 2>&1); then
  ok "Code assets seeded"
else
  warn "Seeding code assets failed — tail $QQ_ROOT/logs/seed-code-assets.log"
fi

# Install API deps if missing
if ! $PYTHON -c "import fastapi, asyncpg" >/dev/null 2>&1; then
  log "Installing QuoteIQ API deps..."
  $PYTHON -m pip install -q -r "$QQ_ROOT/api/requirements.txt" 2>&1 | tail -3 || true
fi

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
kill_port 8008
kill_port 3008
sleep 1

# API. With DATABASE_URL (from .env or dev-local.sh) the inbox is kept in the
# qq_emails table and survives a restart; without it, it lives in memory.
log "Starting QuoteIQ API on :8008..."
cd "$QQ_ROOT/api"
env PORT=8008 \
  PYTHONPATH=".:sdk" \
  ABENIX_API_URL="${_AF_URL}" \
  ABENIX_WEB_URL="${ABENIX_WEB_URL:-http://localhost:3000}" \
  QUOTEIQ_ABENIX_API_KEY="$QUOTEIQ_ABENIX_API_KEY" \
  $PYTHON main.py > "$QQ_ROOT/logs/api.log" 2>&1 &
QQ_API_PID=$!
sleep 3

API_OK=false
for _ in 1 2 3 4 5; do
  curl -sf http://localhost:8008/health >/dev/null 2>&1 && { API_OK=true; break; }
  sleep 2
done
if [ "$API_OK" = "true" ]; then ok "QuoteIQ API healthy on :8008 (PID $QQ_API_PID)"
else warn "QuoteIQ API not responding — tail $QQ_ROOT/logs/api.log"; fi

# Web
log "Starting QuoteIQ Web on :3008..."
cd "$QQ_ROOT/web"
if [ ! -d "node_modules" ]; then
  log "npm install…"
  npm install --legacy-peer-deps > "$QQ_ROOT/logs/web-install.log" 2>&1
fi
QUOTEIQ_API_INTERNAL_URL="http://localhost:8008" \
nohup npx next dev --port 3008 > "$QQ_ROOT/logs/web.log" 2>&1 &
QQ_WEB_PID=$!

sleep 6
WEB_OK=false
for _ in 1 2 3 4 5; do
  curl -sf http://localhost:3008 -o /dev/null >/dev/null 2>&1 && { WEB_OK=true; break; }
  sleep 3
done
[ "$WEB_OK" = "true" ] && ok "QuoteIQ Web running on :3008 (PID $QQ_WEB_PID)" \
                        || warn "QuoteIQ Web still starting — tail $QQ_ROOT/logs/web.log"

cd "$ROOT_DIR"
