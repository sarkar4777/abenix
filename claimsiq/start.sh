#!/bin/bash

set -e

CQ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$CQ_ROOT/.." && pwd)"

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

# Detect Gradle — prefer wrapper, fall back to system gradle.
if [ -x "$CQ_ROOT/gradlew" ]; then
  GRADLE="$CQ_ROOT/gradlew"
elif command -v gradle &>/dev/null; then
  GRADLE="gradle"
else
  fail "Gradle not found. Install Gradle 8.x (sdk install gradle) or add a wrapper."
  exit 1
fi

# Check Java 21
if ! command -v java &>/dev/null; then
  fail "Java 21 not found on PATH."
  exit 1
fi
JAVA_MAJOR=$(java -version 2>&1 | awk -F'"' '/version/{print $2}' | cut -d. -f1)
if [ "$JAVA_MAJOR" -lt 21 ] 2>/dev/null; then
  warn "ClaimsIQ targets Java 21; detected Java $JAVA_MAJOR. Gradle may download a 21 toolchain but startup can be slow."
fi

# Check Abenix
log "Checking Abenix API at http://localhost:8000…"
if ! curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
  warn "Abenix API is not running on port 8000."
  warn "Start it first: cd $ROOT_DIR && bash scripts/dev-local.sh"
  warn "Continuing — the pipeline will fail until Abenix is up."
fi

# Source ALL vars from main .env, same rules as the other start.sh
# scripts (skip comments, JSON-ish values, CRLF line endings).
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

if [ -z "$CLAIMSIQ_ABENIX_API_KEY" ]; then
  warn "CLAIMSIQ_ABENIX_API_KEY not set — pipeline dispatch will 401."
  warn "Create a key in Abenix with can_delegate scope and export the env var."
else
  _AF_URL="${ABENIX_API_URL:-http://localhost:8000}"
  _CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -H "X-API-Key: $CLAIMSIQ_ABENIX_API_KEY" "${_AF_URL}/api/agents" 2>/dev/null || echo "000")
  if [ "$_CODE" = "200" ]; then
    ok "CLAIMSIQ_ABENIX_API_KEY validates against ${_AF_URL} (200)"
  elif [ "$_CODE" = "401" ] || [ "$_CODE" = "403" ]; then
    fail "CLAIMSIQ_ABENIX_API_KEY rejected by ${_AF_URL} (${_CODE}) — pipeline dispatch will fail"
    fail "  Run: bash scripts/seed-standalone-keys.sh claimsiq"
  else
    warn "Could not validate CLAIMSIQ_ABENIX_API_KEY (got ${_CODE} from ${_AF_URL})"
  fi
fi

# logs dir
mkdir -p "$CQ_ROOT/logs"

# Kill any existing ClaimsIQ on 3005
log "Stopping any existing ClaimsIQ on port 3005…"
PID=$(netstat -ano 2>/dev/null | grep ":3005.*LISTENING" | awk '{print $5}' | head -1 || true)
if [ -n "$PID" ]; then
  taskkill //PID "$PID" //F 2>/dev/null || kill -9 "$PID" 2>/dev/null || true
  sleep 2
fi

# Build if needed
if [ ! -f "$CQ_ROOT/app/build/libs"/*.jar ] 2>/dev/null; then
  log "Building ClaimsIQ jar (first run — takes a minute)…"
  ( cd "$CQ_ROOT" && "$GRADLE" --no-daemon :app:bootJar -Pvaadin.productionMode=true ) \
    > "$CQ_ROOT/logs/build.log" 2>&1
  if [ $? -ne 0 ]; then
    fail "Build failed — see $CQ_ROOT/logs/build.log"
    tail -30 "$CQ_ROOT/logs/build.log"
    exit 1
  fi
  ok "Built."
fi

JAR=$(ls "$CQ_ROOT/app/build/libs/"*.jar 2>/dev/null | head -1)
if [ -z "$JAR" ]; then
  fail "No jar found in $CQ_ROOT/app/build/libs — Gradle build didn't produce output."
  exit 1
fi

log "Starting ClaimsIQ on port 3005…"
PORT=3005 \
ABENIX_API_URL="${ABENIX_API_URL:-http://localhost:8000}" \
CLAIMSIQ_ABENIX_API_KEY="${CLAIMSIQ_ABENIX_API_KEY:-}" \
nohup java -jar "$JAR" > "$CQ_ROOT/logs/app.log" 2>&1 &

CQ_PID=$!
sleep 6

# Health check
APP_OK=false
for i in 1 2 3 4 5 6 7 8; do
  if curl -sf http://localhost:3005/actuator/health/liveness >/dev/null 2>&1; then
    APP_OK=true
    break
  fi
  sleep 3
done

if [ "$APP_OK" = "true" ]; then
  ok "ClaimsIQ is healthy on port 3005 (pid $CQ_PID)"
else
  warn "ClaimsIQ may still be starting — JVM cold-start is 30-40s. Watch the log."
fi

echo ""
echo -e "  ${CYAN}ClaimsIQ UI${NC}          http://localhost:3005"
echo -e "  ${CYAN}New FNOL${NC}             http://localhost:3005/fnol"
echo -e "  ${CYAN}Claims queue${NC}         http://localhost:3005/claims"
echo -e "  ${CYAN}Health${NC}               http://localhost:3005/actuator/health"
echo -e "  ${CYAN}Logs${NC}                 tail -f $CQ_ROOT/logs/app.log"
echo ""
exit 0
