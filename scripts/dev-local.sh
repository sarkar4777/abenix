#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Which use-case apps to start. APPS env wins, otherwise it prompts.
# shellcheck source=scripts/lib/select-apps.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/select-apps.sh"
cd "$ROOT_DIR"

# ── Colors ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[Abenix]${NC} $1"; }
ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  !${NC} $1"; }
err()  { echo -e "${RED}  ✗${NC} $1"; }

# ── Detect OS ─────────────────────────────────────────────────
IS_WINDOWS=false
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=true ;;
esac

# ── Detect Python ─────────────────────────────────────────────
find_python() {
  for cmd in python3.12 python3.13 python3 python; do
    if command -v "$cmd" &>/dev/null; then
      echo "$cmd"
      return
    fi
  done
  if command -v py &>/dev/null; then
    echo "py"
    return
  fi
  err "No Python found. Install Python 3.12+."
  exit 1
}

PYTHON=$(find_python)
log "Using Python: $PYTHON ($($PYTHON --version 2>&1))"

# ── Normalise AZURE_OPENAI_* in .env BEFORE we source it ──────
# The Azure OpenAI Python SDK builds URLs as
# `{azure_endpoint}/openai/deployments/{deployment}/{action}`. If the
# endpoint already ends in `/openai/deployments` (or `/openai`), the
# resulting URL doubles up and Azure 404s. Human-edited .env files keep
# drifting back to the bad shape, so we sanity-check and fix in place
# the same way scripts/deploy-azure.sh does for cluster secrets.
#
# Idempotent: re-running this is a no-op unless something actually
# changed. No duplicate keys, no spurious WARN.
_normalize_env_azure_endpoints() {
  local env_file="$ROOT_DIR/.env"
  [ -f "$env_file" ] || return 0

  local tmp="$env_file.tmp"
  local changed=false
  local has_base=false
  local base_value=""
  local has_endpoint=false
  local endpoint_value=""

  # First pass: rewrite any AZURE_OPENAI_API_BASE / AZURE_OPENAI_ENDPOINT
  # line that has the bad suffix, leave every other line untouched.
  : > "$tmp"
  while IFS= read -r line || [ -n "$line" ]; do
    local key="${line%%=*}"
    local value="${line#*=}"
    # Only touch our two keys; pass everything else through verbatim.
    if [ "$key" = "AZURE_OPENAI_API_BASE" ] || [ "$key" = "AZURE_OPENAI_ENDPOINT" ]; then
      local raw="$value"
      local cleaned="${raw%$'\r'}"
      cleaned="${cleaned%/}"
      cleaned="${cleaned%/openai/deployments}"
      cleaned="${cleaned%/openai}"
      cleaned="${cleaned%/}"
      if [ "$cleaned" != "${raw%$'\r'}" ]; then
        changed=true
        line="$key=$cleaned"
      fi
      if [ "$key" = "AZURE_OPENAI_API_BASE" ]; then
        has_base=true
        base_value="$cleaned"
      else
        has_endpoint=true
        endpoint_value="$cleaned"
      fi
    fi
    printf '%s\n' "$line" >> "$tmp"
  done < "$env_file"

  # Second consideration: if BASE is set + non-empty and ENDPOINT is
  # missing/empty, mirror BASE → ENDPOINT (matches deploy-azure.sh).
  # Both vars are read by the embedder code; aliasing makes the next
  # dev's env match .env.example.
  if [ "$has_base" = true ] && [ -n "$base_value" ]; then
    if [ "$has_endpoint" = false ]; then
      printf '%s\n' "AZURE_OPENAI_ENDPOINT=$base_value" >> "$tmp"
      changed=true
    elif [ -z "$endpoint_value" ]; then
      # Rewrite the empty ENDPOINT line in place with BASE's value.
      local tmp2="$tmp.2"
      while IFS= read -r line || [ -n "$line" ]; do
        if [ "${line%%=*}" = "AZURE_OPENAI_ENDPOINT" ] && [ -z "${line#*=}" ]; then
          printf '%s\n' "AZURE_OPENAI_ENDPOINT=$base_value" >> "$tmp2"
        else
          printf '%s\n' "$line" >> "$tmp2"
        fi
      done < "$tmp"
      mv "$tmp2" "$tmp"
      changed=true
    fi
  fi

  if [ "$changed" = true ]; then
    mv "$tmp" "$env_file"
    warn "Normalized AZURE_* endpoint in .env (stripped /openai/deployments)"
  else
    rm -f "$tmp"
  fi
}

_normalize_env_azure_endpoints

# ── Tear down any active kubectl port-forwards ────────────────
# Local probes against http://localhost:8000 etc are silently routed
# to whichever Azure pod the dev forgot to disconnect. The user's
# rule: dev-local owns the local stack, so if any port-forward is
# active when we start, force-stop it before launching local processes.
# We try the canonical script first (portforward-azure.sh stop), then
# pkill as a fallback for stray `kubectl port-forward` left running
# from `kubectl port-forward` invocations not tracked by the script.
_force_stop_azure_portforwards() {
  local any=false
  if pgrep -fa "kubectl.*port-forward" >/dev/null 2>&1; then
    any=true
  elif command -v powershell.exe >/dev/null 2>&1; then
    if powershell.exe -NoProfile -Command 'Get-Process kubectl -ErrorAction SilentlyContinue | Select-Object -First 1' 2>/dev/null | grep -q kubectl; then
      any=true
    fi
  fi
  [ "$any" = false ] && return 0
  warn "Detected active kubectl port-forward(s) — tearing down before local boot"
  if [ -x "$ROOT_DIR/scripts/portforward-azure.sh" ]; then
    bash "$ROOT_DIR/scripts/portforward-azure.sh" stop >/dev/null 2>&1 || true
  fi
  pkill -f "kubectl.*port-forward" 2>/dev/null || true
  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command "Get-Process kubectl -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue" >/dev/null 2>&1 || true
  fi
  sleep 1
  ok "kubectl port-forwards stopped"
}
_force_stop_azure_portforwards

if [ -f "$ROOT_DIR/.env" ]; then
  while IFS='=' read -r key value; do
    # Skip comments and empty lines
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [[ -z "$key" ]] && continue
    key="${key%$'\r'}"
    key="$(echo "$key" | xargs)"
    # Only accept valid shell identifiers as env-var names.
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    # Skip JSON arrays/objects (brackets break bash)
    case "$value" in
      \[*|\{*) continue ;;
    esac
    # Strip a single trailing CR if the file has CRLF endings.
    value="${value%$'\r'}"
    export "$key=$value" 2>/dev/null || true
  done < "$ROOT_DIR/.env"
  ok "Loaded environment from .env"
fi

# ── Sandboxed-job runner is on by default in dev ──────────────
# These two vars must always be set or the sandboxed_job tool returns
# "disabled". Don't override what the developer put in .env.
: "${SANDBOXED_JOB_ENABLED:=true}"
: "${SANDBOXED_JOB_ALLOWED_IMAGES:=alpine:3.20,busybox:1.36,python:3.12-slim,gcc:13,golang:1.22-alpine,rust:1.80-slim,eclipse-temurin:21-jdk,node:20-alpine,sbtscala/scala-sbt:eclipse-temurin-jammy-21.0.2_13_1.10.0_3.4.2,zenika/kotlin:1.9.24-jdk-jre-alpine-slim,mcr.microsoft.com/dotnet/sdk:8.0,ruby:3.3-alpine}"
export SANDBOXED_JOB_ENABLED SANDBOXED_JOB_ALLOWED_IMAGES

# ── Local data directories (k8s parity) ──────────────────────
# In k8s these point to the /data PVC. Locally we use $ROOT_DIR/.data
# so file-writing tools (code_executor, data_exporter, ml_model,
# code_asset, sandboxed_job) work without the developer setting
# anything. Each var is overridable via .env if a developer prefers
# a different location.
: "${EXPORT_DIR:=$ROOT_DIR/.data/exports}"
: "${UPLOAD_DIR:=$ROOT_DIR/.data/uploads}"
: "${ML_MODELS_DIR:=$ROOT_DIR/.data/ml-models}"
: "${CODE_ASSET_STORE:=$ROOT_DIR/.data/code-assets}"
: "${CODE_ASSET_BUILD_CACHE:=$ROOT_DIR/.data/code-asset-cache}"
# object keys for durable copies are paths under this root
: "${OBJECT_STORAGE_LOCAL_ROOT:=$ROOT_DIR/.data}"
mkdir -p "$EXPORT_DIR" "$UPLOAD_DIR" "$ML_MODELS_DIR" \
         "$CODE_ASSET_STORE" "$CODE_ASSET_BUILD_CACHE" 2>/dev/null || true
export EXPORT_DIR UPLOAD_DIR ML_MODELS_DIR CODE_ASSET_STORE CODE_ASSET_BUILD_CACHE OBJECT_STORAGE_LOCAL_ROOT

# ── Per-process log directory (must exist before any helper runs) ─────
LOG_DIR="${LOG_DIR:-$ROOT_DIR/.local-logs}"
mkdir -p "$LOG_DIR" 2>/dev/null || true

# ── Canonical port + label registry (single source of truth) ──────────
# Every entry: "<port>|<label>|<log-basename>". Used by kill_port loop,
# wait_port_listening, --status, and self-heal-at-start. Add new apps
# here ONCE and they participate in every lifecycle path.
ALL_PORTS=(
  "8000|API server|abenix-api"
  "3000|Web server|abenix-web"
  "8001|ContractIQ API|contractiq-api"
  "3001|ContractIQ Web|contractiq-web"
  "8002|Mideast Tourism API|mideasttourism-api"
  "3002|Mideast Tourism Web|mideasttourism-web"
  "8003|Industrial-IoT API|industrial-iot-api"
  "3003|Industrial-IoT Web|industrial-iot-web"
  "8004|ResolveAI API|resolveai-api"
  "3004|ResolveAI Web|resolveai-web"
  "3005|ClaimsIQ|claimsiq"
  "8006|Wingman API|wingman-api"
  "3006|Wingman Web|wingman-web"
)

# ── Detect if a port is currently LISTENING ───────────────────────────
port_listening() {
  local port=$1
  if [ "$IS_WINDOWS" = true ]; then
    netstat -ano 2>/dev/null | grep -q ":${port} .*LISTENING"
  else
    if command -v lsof >/dev/null 2>&1; then
      lsof -ti:"$port" >/dev/null 2>&1
    else
      ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":${port}$"
    fi
  fi
}

# ── Find the PID listening on a port (cross-platform) ─────────────────
pid_on_port() {
  local port=$1
  if [ "$IS_WINDOWS" = true ]; then
    netstat -ano 2>/dev/null | grep ":${port} .*LISTENING" | awk '{print $5}' | sort -u | tr -d '\r' | head -1
  else
    if command -v lsof >/dev/null 2>&1; then
      lsof -ti:"$port" 2>/dev/null | head -1
    else
      ss -ltnp 2>/dev/null | awk -v p=":${port}" '$4 ~ p {print $NF}' | sed 's/.*pid=\([0-9]*\).*/\1/' | head -1
    fi
  fi
}

# ── Kill process on a port (cross-platform) ──────────────────
# Idempotent. Returns 0 whether or not anything was running.
kill_port() {
  local port=$1
  local label=$2

  for attempt in 1 2 3; do
    if [ "$IS_WINDOWS" = true ]; then
      local pids
      pids=$(netstat -ano 2>/dev/null | grep ":${port} .*LISTENING" | awk '{print $5}' | sort -u | tr -d '\r')
      local killed=false
      for pid in $pids; do
        [ -z "$pid" ] || [ "$pid" = "0" ] && continue
        taskkill //F //PID "$pid" >/dev/null 2>&1 && killed=true
      done
      if [ "$killed" = true ]; then
        ok "Killed $label on port $port (attempt $attempt)"
        sleep 1
      else
        ok "$label not running (port $port free)"
        return 0
      fi
    else
      local pids
      pids=$(lsof -ti:"$port" 2>/dev/null)
      if [ -n "$pids" ]; then
        echo "$pids" | xargs kill -9 2>/dev/null
        ok "Killed $label on port $port (attempt $attempt)"
        sleep 1
      else
        ok "$label not running (port $port free)"
        return 0
      fi
    fi
  done
  return 0
}

# ── Wait for a port to start listening, with a hard cap ───────────────
# Usage: wait_port_listening <port> <label> <timeout_sec> [<log_basename>] [<pid>]
# On timeout, kills the started PID (if given), tails the log file,
# prints a clear remediation hint, then exits 1. No silent hangs.
wait_port_listening() {
  local port=$1
  local label=$2
  local timeout=${3:-30}
  local log_base="${4:-}"
  local pid="${5:-}"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if port_listening "$port"; then
      ok "$label is listening on :$port (after ${elapsed}s)"
      return 0
    fi
    # Bail early if the launched PID already died — no point waiting the full window.
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      err "$label process (PID $pid) exited before opening port $port"
      if [ -n "$log_base" ] && [ -f "$LOG_DIR/${log_base}.log" ]; then
        err "Last 30 log lines from $LOG_DIR/${log_base}.log:"
        tail -30 "$LOG_DIR/${log_base}.log" 2>/dev/null | sed 's/^/      /'
      fi
      err "Hint: bash scripts/dev-local.sh --restart   (clears stale state and retries)"
      return 1
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  err "$label did not start listening on :$port within ${timeout}s"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    err "  Killing stuck PID $pid"
    if [ "$IS_WINDOWS" = true ]; then
      taskkill //F //PID "$pid" >/dev/null 2>&1 || true
    else
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  fi
  if [ -n "$log_base" ] && [ -f "$LOG_DIR/${log_base}.log" ]; then
    err "Last 30 log lines from $LOG_DIR/${log_base}.log:"
    tail -30 "$LOG_DIR/${log_base}.log" 2>/dev/null | sed 's/^/      /'
  fi
  err "Hint: tail -f $LOG_DIR/${log_base}.log   (full log)"
  err "      bash scripts/dev-local.sh --restart   (clears stale state and retries)"
  return 1
}

# ── Reap every port in ALL_PORTS in one pass ──────────────────────────
reap_all_ports() {
  for entry in "${ALL_PORTS[@]}"; do
    local port="${entry%%|*}"
    local rest="${entry#*|}"
    local label="${rest%%|*}"
    kill_port "$port" "$label"
  done
}

# ── Clean stale Python bytecode ───────────────────────────────
clean_pycache() {
  for dir in \
    "$ROOT_DIR/apps/api/app/__pycache__" \
    "$ROOT_DIR/apps/api/app/schemas/__pycache__" \
    "$ROOT_DIR/apps/api/app/routers/__pycache__" \
    "$ROOT_DIR/apps/api/app/core/__pycache__" \
    "$ROOT_DIR/apps/agent-runtime/engine/__pycache__" \
    "$ROOT_DIR/apps/agent-runtime/engine/tools/__pycache__" \
    "$ROOT_DIR/apps/agent-runtime/engine/knowledge/__pycache__" \
    "$ROOT_DIR/apps/worker/worker/__pycache__" \
    "$ROOT_DIR/apps/worker/worker/tasks/__pycache__" \
    "$ROOT_DIR/packages/db/models/__pycache__"; do
    [ -d "$dir" ] && rm -rf "$dir"
  done
  ok "Bytecode caches cleaned"
}

# ── Kill old processes (idempotent — second call is a no-op) ──────────
kill_processes() {
  log "Stopping Abenix processes..."
  # Quick precheck — if nothing's listening on any tracked port AND no
  # Celery/uvicorn/consumer processes are running, this is the second
  # invocation of --stop. Say so and return 0.
  local anything=false
  for entry in "${ALL_PORTS[@]}"; do
    local port="${entry%%|*}"
    if port_listening "$port"; then anything=true; break; fi
  done
  if [ "$anything" = false ]; then
    if [ "$IS_WINDOWS" = true ]; then
      if ! tasklist 2>/dev/null | grep -qi "celery.exe"; then
        ok "Already stopped (no tracked ports listening, no celery/uvicorn)"
        return 0
      fi
    else
      if ! pgrep -f "celery.*worker\|uvicorn.*app.main\|python.*consumer\.py" >/dev/null 2>&1; then
        ok "Already stopped (no tracked ports listening, no celery/uvicorn)"
        return 0
      fi
    fi
  fi

  reap_all_ports

  # Kill celery and orphaned python processes (including the Wave-2
  # NATS consumer we launched as `python consumer.py`).
  if [ "$IS_WINDOWS" = true ]; then
    taskkill //F //IM "celery.exe" >/dev/null 2>&1 && ok "Killed Celery worker" || ok "Celery worker not running"
    tasklist 2>/dev/null | grep -i python | awk '{print $2}' | while read pid; do
      cmd=$(wmic process where "ProcessId=$pid" get CommandLine 2>/dev/null)
      echo "$cmd" | grep -qi "celery\|consumer\.py" && taskkill //F //PID "$pid" >/dev/null 2>&1
    done 2>/dev/null || true
  else
    pkill -f "celery.*worker" 2>/dev/null && ok "Killed Celery worker" || ok "Celery worker not running"
    pkill -f "uvicorn.*app.main" 2>/dev/null && ok "Killed orphaned uvicorn" || true
    pkill -f "python.*consumer\.py" 2>/dev/null && ok "Killed NATS consumer" || true
  fi

  sleep 3
  clean_pycache
}

# ── Resolve health-check URL for a port (per-app) ─────────────────────
_health_url_for_port() {
  case "$1" in
    8000) echo "http://localhost:8000/api/health" ;;
    8001) echo "http://localhost:8001/api/health" ;;
    8002) echo "http://localhost:8002/api/health" ;;
    8003) echo "http://localhost:8003/health" ;;
    8004) echo "http://localhost:8004/health" ;;
    8006) echo "http://localhost:8006/health" ;;
    3005) echo "http://localhost:3005/actuator/health/liveness" ;;
    *)    echo "http://localhost:$1" ;;
  esac
}

# ── Status check — PID + port + health per app, table-of-record ───────
check_status() {
  log "Service status:"
  echo ""

  # Docker
  if docker compose ps 2>/dev/null | grep -q "abenix"; then
    ok "Docker containers"
    docker compose ps 2>/dev/null | grep abenix | sed 's/^/      /'
  else
    err "Docker containers not running"
  fi
  echo ""

  printf "  %-22s %-6s %-8s %-7s %s\n" "Service" "Port" "PID" "Health" "Log"
  printf "  %-22s %-6s %-8s %-7s %s\n" "──────" "────" "───" "──────" "───"

  local green=0 red=0
  for entry in "${ALL_PORTS[@]}"; do
    local port="${entry%%|*}"
    local rest="${entry#*|}"
    local label="${rest%%|*}"
    local log_base="${rest##*|}"
    local pid health verdict url log_path

    pid=$(pid_on_port "$port" 2>/dev/null)
    [ -z "$pid" ] && pid="-"
    url=$(_health_url_for_port "$port")
    log_path="$LOG_DIR/${log_base}.log"

    if curl -s --max-time 3 -o /dev/null "$url" 2>/dev/null; then
      health="OK"
      verdict="${GREEN}${health}${NC}"
      green=$((green+1))
    else
      health="DOWN"
      verdict="${RED}${health}${NC}"
      red=$((red+1))
    fi
    printf "  %-22s %-6s %-8s " "$label" "$port" "$pid"
    echo -e "${verdict}\t$log_path"
  done

  echo ""

  # Neo4j (infra — not in ALL_PORTS)
  if curl -s --max-time 3 http://localhost:7474 >/dev/null 2>&1; then
    ok "Neo4j — http://localhost:7474 (Browser) / bolt://localhost:7687"
  else
    err "Neo4j not responding on :7474"
  fi

  # Celery
  if [ "$IS_WINDOWS" = true ]; then
    if tasklist 2>/dev/null | grep -qi "celery\|python" && [ -f "$LOG_DIR/celery.log" ]; then
      ok "Celery worker — $LOG_DIR/celery.log"
    else
      warn "Celery worker may not be running"
    fi
  else
    if pgrep -f "celery.*worker" >/dev/null 2>&1; then
      ok "Celery worker — $LOG_DIR/celery.log"
    else
      warn "Celery worker not running"
    fi
  fi

  echo ""
  echo -e "  Summary: ${GREEN}${green} green${NC} / ${RED}${red} down${NC} (of ${#ALL_PORTS[@]} tracked services)"
  echo ""
  # Exit code conveys aggregate health — callers/scripts can branch on it.
  if [ "$red" -gt 0 ]; then return 1; fi
  return 0
}

# ── Handle --stop, --status, --restart, --help ────────────────
case "${1:-}" in
  --stop)
    kill_processes
    log "All Abenix processes stopped."
    exit 0
    ;;
  --status)
    # check_status returns non-zero if anything's down; surface that exit
    # code to the caller so scripts (CI, /loop, etc.) can branch on it.
    if check_status; then exit 0; else exit 1; fi
    ;;
  --restart)
    log "Restart requested — running --stop then a clean start..."
    kill_processes
    log "All Abenix processes stopped. Re-launching..."
    # Fall through to the normal start path below.
    ;;
  --help|-h)
    cat <<EOF
Usage: bash scripts/dev-local.sh [flag]

Flags:
  (no flag)   Start every service (idempotent — self-heals stale ports).
  --stop      Stop every tracked service. Re-running is a clean no-op.
  --status    Print PID + port + health table. Exit 0 if all green, 1 otherwise.
  --restart   Stop everything, then run a clean start.
  --help      This message.

Logs:        $LOG_DIR/<service>.log
EOF
    exit 0
    ;;
esac

# ── Self-heal preamble (no-flag start path) ───────────────────
# If any tracked port is already listening when we enter the start path,
# the previous run left state behind. Per the operating contract this
# script self-heals — we run the --stop branch implicitly to reach a
# clean baseline, then continue. No silent EADDRINUSE.
if [ "${1:-}" != "--restart" ]; then
  _busy_ports=""
  for entry in "${ALL_PORTS[@]}"; do
    port="${entry%%|*}"
    if port_listening "$port"; then
      _busy_ports="${_busy_ports} ${port}"
    fi
  done
  if [ -n "$_busy_ports" ]; then
    warn "Detected existing listeners on:${_busy_ports} — self-healing (auto --stop + continue)"
    kill_processes
  fi
fi

# ── Pre-flight: SDK drift gate ────────────────────────────────
# Bail early if any of the 5 vendored Abenix SDK copies has drifted
# from the canonical packages/sdk/python source. A drifted SDK in dev
# silently breaks every standalone app's agent.execute() call (the
# wait=True default that polls async-mode executions lives in the SDK).
# Set SKIP_SDK_SYNC_CHECK=1 to bypass.
if [ "${SKIP_SDK_SYNC_CHECK:-0}" != "1" ] && [ -f "$ROOT_DIR/scripts/sync-sdks.sh" ]; then
  if ! bash "$ROOT_DIR/scripts/sync-sdks.sh" --check >/dev/null 2>&1; then
    err "Abenix SDK copies are out of sync with canonical."
    err "Run: bash scripts/sync-sdks.sh   (or SKIP_SDK_SYNC_CHECK=1 to bypass)"
    bash "$ROOT_DIR/scripts/sync-sdks.sh" --check || true
    exit 1
  fi
  ok "SDK copies in sync"
fi

# STARTUP
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       Abenix Dev Environment         ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Ask before doing anything slow ────────────────────────────
# Up front, so nobody waits through five minutes of infrastructure only to be
# asked a question at the end. APPS in the environment skips the prompt.
select_apps
log "Use-case apps: $(describe_selection)"

# ── Step 1: Kill old processes ────────────────────────────────
kill_processes

# ── Step 2: Docker Compose ────────────────────────────────────
log "Step 1/7 — Docker infrastructure (Postgres + Redis + Neo4j + NATS JetStream)..."

if ! docker info >/dev/null 2>&1; then
  err "Docker is not running. Please start Docker Desktop first."
  exit 1
fi

PG_HEALTHY=false
REDIS_HEALTHY=false
NEO4J_HEALTHY=false
NATS_HEALTHY=false
TSDB_HEALTHY=false
docker compose ps 2>/dev/null | grep "abenix-postgres" | grep -q "healthy" && PG_HEALTHY=true
docker compose ps 2>/dev/null | grep "abenix-redis" | grep -q "healthy" && REDIS_HEALTHY=true
docker compose ps 2>/dev/null | grep "abenix-neo4j" | grep -q "healthy" && NEO4J_HEALTHY=true
docker compose ps 2>/dev/null | grep "abenix-nats" | grep -q "healthy" && NATS_HEALTHY=true
docker compose ps 2>/dev/null | grep "abenix-timescaledb" | grep -q "healthy" && TSDB_HEALTHY=true

if [ "$PG_HEALTHY" = true ] && [ "$REDIS_HEALTHY" = true ] && [ "$NEO4J_HEALTHY" = true ] && [ "$NATS_HEALTHY" = true ] && [ "$TSDB_HEALTHY" = true ]; then
  ok "Postgres, Redis, Neo4j, NATS, Mosquitto, and TimescaleDB already running and healthy"
else
  docker compose up -d 2>&1 | sed 's/^/      /'
  log "Waiting for containers to be healthy..."
  for i in $(seq 1 45); do
    PG_OK=false
    RD_OK=false
    N4_OK=false
    NA_OK=false
    TS_OK=false
    docker compose ps 2>/dev/null | grep "abenix-postgres" | grep -q "healthy" && PG_OK=true
    docker compose ps 2>/dev/null | grep "abenix-redis" | grep -q "healthy" && RD_OK=true
    docker compose ps 2>/dev/null | grep "abenix-neo4j" | grep -q "healthy" && N4_OK=true
    docker compose ps 2>/dev/null | grep "abenix-nats" | grep -q "healthy" && NA_OK=true
    docker compose ps 2>/dev/null | grep "abenix-timescaledb" | grep -q "healthy" && TS_OK=true

    if [ "$PG_OK" = true ] && [ "$RD_OK" = true ] && [ "$N4_OK" = true ] && [ "$NA_OK" = true ] && [ "$TS_OK" = true ]; then
      ok "Postgres, Redis, Neo4j, NATS, Mosquitto, and TimescaleDB are healthy"
      break
    fi
    if [ "$i" -eq 45 ]; then
      if [ "$PG_OK" = true ] && [ "$RD_OK" = true ] && [ "$NA_OK" = true ]; then
        warn "Neo4j/TimescaleDB still starting — knowledge or tsdb features may be delayed"
      elif [ "$PG_OK" = true ] && [ "$RD_OK" = true ]; then
        warn "NATS is still starting — agent execution will fall back to inline"
      else
        err "Containers failed to become healthy after 45s"
        docker compose ps 2>/dev/null
        exit 1
      fi
    fi
    sleep 1
  done
fi

# ── Streaming + TSDB env vars (parity with the helm chart in AKS) ──
# Tools (mqtt_publish, tsdb_query, subscribed_feed) read these at execute
# time. Defaults match docker-compose.yml so agents work out-of-the-box.
export MQTT_URL=${MQTT_URL:-mqtt://localhost:1883}
export TSDB_URL=${TSDB_URL:-postgresql://abenix:abenix@localhost:5433/abenix_tsdb}
ok "Streaming/TSDB env: MQTT_URL=$MQTT_URL, TSDB_URL=postgresql://abenix:***@localhost:5433/abenix_tsdb"

# Export NATS env for the API + the consumer process start.sh launches.
# These match what the Helm chart injects into AKS pods, so dev/prod
# behaviour is identical.
export QUEUE_BACKEND=${QUEUE_BACKEND:-nats}
export SCALING_EXEC_REMOTE=${SCALING_EXEC_REMOTE:-true}
export NATS_URL=${NATS_URL:-nats://127.0.0.1:4222}
export NATS_USER=${NATS_USER:-abenix}
export NATS_PASSWORD=${NATS_PASSWORD:-abenix-dev}
export RUNTIME_POOL=${RUNTIME_POOL:-default}
ok "Queue backend: $QUEUE_BACKEND (exec_remote=$SCALING_EXEC_REMOTE)"

# Progress pub/sub + per-app post-processors — parity with the helm
# chart's configmap so the runtime publishes on the same Redis channel
# that contractiq/wingman web subscribe to and contractiq's
# deterministic guardrails register at startup. Without this, chat SSE
# narration in the standalone apps comes through the legacy "wingman:"
# alias only (kept alive in progress.py for back-compat).
export PROGRESS_CHANNEL_PREFIX=${PROGRESS_CHANNEL_PREFIX:-progress:}
export PROGRESS_PARENT_KEY_PREFIX=${PROGRESS_PARENT_KEY_PREFIX:-parent:}
export POST_PROCESSOR_MODULES=${POST_PROCESSOR_MODULES:-contractiq.runtime.post_processors}
ok "Progress channel: ${PROGRESS_CHANNEL_PREFIX}<id> | post-processors: ${POST_PROCESSOR_MODULES}"

# ── Step 3: Install npm dependencies if needed ────────────────
log "Step 2/7 — Node.js dependencies..."
if [ ! -d "node_modules" ] || [ ! -d "apps/web/node_modules" ]; then
  npm install 2>&1 | tail -3 | sed 's/^/      /'
  ok "npm packages installed"
else
  ok "npm packages already installed"
fi

# ── Step 4: Install Python dependencies if needed ─────────────
log "Step 3/7 — Python dependencies..."
if $PYTHON -c "import fastapi" >/dev/null 2>&1; then
  ok "Python packages already installed"
else
  $PYTHON -m pip install -r requirements.txt 2>&1 | tail -3 | sed 's/^/      /'
  ok "Python packages installed"
fi

# ── Step 5: Run migrations + verify schema is current ──────────
# Robust startup: `alembic upgrade head` is the source of truth in BOTH
# local and k8s prod. The catchup migration `x4y5z6a7b8c9` adds any
# columns that drifted between the ORM and the database — it's
# idempotent (information_schema-guarded) so re-running it is always
# safe in production.
#
# Verification step: AFTER alembic, check a small set of canonical
# columns. If any are STILL missing the catchup migration is
# incomplete and we exit non-zero so the developer notices and fixes
# the migration rather than papering over the gap with a destructive
# drop.
log "Step 4/7 — Database migrations + schema verification..."
cd "$ROOT_DIR/packages/db"

# Clean Python cache to avoid stale bytecode
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Bootstrap fast-path for a brand-new database — Base.metadata.create_all
# in one shot, then alembic stamp heads. No-ops if alembic_version
# already exists. See packages/db/bootstrap.py.
PYTHONPATH="." $PYTHON -m bootstrap 2>&1 | sed 's/^/      /' || true

# Run alembic to heads — applies every independent migration chain (we
# have multiple heads in the repo, e.g. the dead_letter branch + the
# approvals additions branch). The singular `head` form errors with
# "Multiple head revisions are present" and the swallow below would
# hide it; the sentinel check at the bottom is what catches drift.
MIGRATION_OUT=$(PYTHONPATH="." $PYTHON -m alembic upgrade heads 2>&1) || true
echo "$MIGRATION_OUT" | grep "Running upgrade" | sed 's/^/      /' || true

# Sentinel column list lives in scripts/_schema-sentinels.sh — single
# source of truth shared with verify-schema.sh and deploy-azure.sh.
# When you add a schema-changing migration, append the load-bearing
# columns to that file (one place, three consumers).
# shellcheck source=_schema-sentinels.sh
source "$ROOT_DIR/scripts/_schema-sentinels.sh"
_CANONICAL_COLUMNS=("${SCHEMA_CANONICAL_COLUMNS[@]}")

_missing=""
for entry in "${_CANONICAL_COLUMNS[@]}"; do
  table="${entry%.*}"
  column="${entry#*.}"
  exists=$(docker exec abenix-postgres psql -U abenix -d abenix -tAc \
    "SELECT 1 FROM information_schema.columns WHERE table_name='$table' AND column_name='$column'" 2>/dev/null || echo "")
  [ -z "$exists" ] && _missing="$_missing $entry"
done

if [ -n "$_missing" ]; then
  err "Schema drift after alembic upgrade head — missing:$_missing"
  err "The catchup migration didn't fully apply. Inspect:"
  err "  packages/db/alembic/versions/x4y5z6a7b8c9_schema_drift_catchup.py"
  err "If this is a fresh install you can recover with:"
  err "  bash scripts/verify-schema.sh --reset"
  exit 5
fi
ok "Migrations complete; schema verified current ($((${#_CANONICAL_COLUMNS[@]})) sentinel columns present)"
cd "$ROOT_DIR"

# ── Step 6: Seed agents ──────────────────────────────────────
log "Step 5/7 — Seeding OOB agents..."
cd "$ROOT_DIR/packages/db"
SEED_OUTPUT=$(PYTHONPATH="." $PYTHON seeds/seed_agents.py 2>&1) || true
SEED_COUNT=$(echo "$SEED_OUTPUT" | grep -c "Creating:" 2>/dev/null || echo "0")
if [ "$SEED_COUNT" -gt 0 ] 2>/dev/null; then
  ok "Seeded $SEED_COUNT agents"
else
  ok "Agents already seeded"
fi

log "Step 6/7 — Seeding default accounts..."
USERS_OUTPUT=$(PYTHONPATH="." $PYTHON seeds/seed_users.py 2>&1) || true

log "       Seeding subject policies (RBAC delegation)..."
POLICIES_OUTPUT=$(PYTHONPATH="." $PYTHON seeds/seed_subject_policies.py 2>&1) || true
echo "$POLICIES_OUTPUT" | grep -E "Seeded|Updated|Ensured" | sed 's/^/      /' || true
echo "$USERS_OUTPUT" | grep -E "Created:|Exists:" | sed 's/^/  /' || true
ok "Default accounts ready"

log "       Seeding portfolio_schemas (energy_contracts for CIQ chat)..."
PORTFOLIO_SEED_OUT=$(PYTHONPATH="." $PYTHON seeds/seed_portfolio_schemas.py 2>&1) || true
echo "$PORTFOLIO_SEED_OUT" | grep -E "Seeded|No tenants|template" | sed 's/^/      /' || true

log "       Seeding sample ML models (from aimodels/)..."
# If the .pkl files don't exist yet, build them first.
if [ ! -f "$ROOT_DIR/aimodels/churn_predictor.pkl" ] || \
   [ ! -f "$ROOT_DIR/aimodels/iris_species_classifier.pkl" ] || \
   [ ! -f "$ROOT_DIR/aimodels/housing_price_predictor.pkl" ]; then
  log "       Building sample .pkl files (one-time)..."
  (cd "$ROOT_DIR" && $PYTHON aimodels/build_samples.py 2>&1) | tail -5 | sed 's/^/      /' || true
fi
ML_SEED_OUTPUT=$(PYTHONPATH="." $PYTHON seeds/seed_ml_models.py 2>&1) || true
echo "$ML_SEED_OUTPUT" | grep -E "Seeded|Found|No " | sed 's/^/      /' || true
ok "Sample ML models ready"

# Seed sample IoT data into Redis streams for demo
log "Seeding IoT demo data into Redis streams..."
$PYTHON -c "
import redis, json, time, random
import os; r = redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379/0'))
for stream in ['equipment:telemetry', 'sensor:temperature', 'transactions:incoming']:
    try:
        r.xinfo_stream(stream)
    except:
        # Seed 20 sample messages
        for i in range(20):
            ts = int(time.time() * 1000) - (20 - i) * 60000
            if stream == 'equipment:telemetry':
                data = {'equipment_id': 'PUMP-001', 'temperature': round(70 + random.gauss(0, 3), 1), 'vibration': round(0.12 + random.gauss(0, 0.05), 3), 'pressure': round(14.7 + random.gauss(0, 0.3), 1), 'timestamp': str(ts)}
            elif stream == 'sensor:temperature':
                data = {'sensor_id': 'TEMP-001', 'value': round(22 + random.gauss(0, 2), 1), 'unit': 'C', 'timestamp': str(ts)}
            else:
                data = {'account_id': 'ACC-12345', 'amount': round(random.uniform(10, 500), 2), 'merchant': random.choice(['Amazon', 'Starbucks', 'Shell', 'Netflix']), 'timestamp': str(ts)}
            r.xadd(stream, data)
        print(f'  Seeded {stream}: 20 messages')
" 2>/dev/null || true
ok "IoT demo data ready"
cd "$ROOT_DIR"

# ── Ensure web app has env vars ───────────────────────────────
if [ ! -f "$ROOT_DIR/apps/web/.env.local" ]; then
  log "Creating apps/web/.env.local..."
  cat > "$ROOT_DIR/apps/web/.env.local" <<ENVEOF
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_ENABLE_MONETIZATION=false
ENVEOF
  ok "Web env vars configured"
else
  ok "Web env vars already configured"
fi

# ── Step 7: Start services ───────────────────────────────────
log "Step 7/7 — Starting services..."

mkdir -p "$LOG_DIR" "$ROOT_DIR/logs"

# Belt-and-braces: reap 8000/3000 right before we spawn. The standalone
# start.sh files do the same for their own ports — but the core API/Web
# launch had no such guard, which is why a half-stuck previous run could
# hit EADDRINUSE and silently exit. With the self-heal preamble + this
# guard, that path is now closed.
kill_port 8000 "API server"
kill_port 3000 "Web server"

# Start API server (DEBUG=true for local dev — allows default secrets).
# --reload picks up engine/translator/router edits without a manual kill.
cd "$ROOT_DIR/apps/api"
DEBUG=true PGSSLMODE=disable IS_LOCAL_DEV=1 ENVIRONMENT=local \
  PYTHONPATH=".:../../packages/db:../../apps/agent-runtime" $PYTHON -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 --reload \
  --reload-dir . --reload-dir ../../packages/db --reload-dir ../../apps/agent-runtime \
  > "$LOG_DIR/abenix-api.log" 2>&1 &
API_PID=$!
cd "$ROOT_DIR"
ok "API server starting (PID $API_PID) — port 8000 — log: $LOG_DIR/abenix-api.log"

# Hard-cap wait for the API to actually open the port. If it doesn't,
# wait_port_listening kills the PID and bails with a tailed log.
wait_port_listening 8000 "API server" 45 "abenix-api" "$API_PID" || exit 1

# Start Web server
cd "$ROOT_DIR/apps/web"
npx next dev --port 3000 \
  > "$LOG_DIR/abenix-web.log" 2>&1 &
WEB_PID=$!
cd "$ROOT_DIR"
ok "Web server starting (PID $WEB_PID) — port 3000 — log: $LOG_DIR/abenix-web.log"

wait_port_listening 3000 "Web server" 60 "abenix-web" "$WEB_PID" || exit 1

# Start Celery worker (handles document processing, cognify, and memify)
# On Python 3.13 the prefork pool's `fast_trace_task` crashes with
# `ValueError: not enough values to unpack (expected 3, got 0)` because of a
# Celery 5.x billiard incompatibility. Use `--pool=solo` on dev to dodge it.
cd "$ROOT_DIR/apps/worker"
PYTHONPATH=".:../../packages/db:../agent-runtime" $PYTHON -m celery \
  -A worker.celery_app worker \
  -Q documents,cognify \
  -l info --pool=solo \
  > "$LOG_DIR/celery.log" 2>&1 &
CELERY_PID=$!
cd "$ROOT_DIR"
ok "Celery worker starting (PID $CELERY_PID, pool=solo) — queues: documents, cognify — log: $LOG_DIR/celery.log"

# Start the Wave-2 per-pool consumer — this is what drains NATS agent
# jobs locally. Same binary the AKS per-pool Deployment runs, so the
# local execution path is byte-for-byte identical to production.
if [ "$QUEUE_BACKEND" = "nats" ]; then
  cd "$ROOT_DIR/apps/agent-runtime"
  # HEALTH_PORT 8002 so it doesn't fight with the API on 8000 / api-runtime on 8001
  RUNTIME_MODE=remote HEALTH_PORT=8002 \
    PYTHONPATH=".:../../packages/db:../api" \
    DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://abenix:abenix@localhost:5432/abenix}" \
    REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}" \
    $PYTHON consumer.py \
    > "$LOG_DIR/consumer.log" 2>&1 &
  CONSUMER_PID=$!
  cd "$ROOT_DIR"
  ok "NATS consumer starting (PID $CONSUMER_PID) — pool=default, backend=nats — log: $LOG_DIR/consumer.log"
fi

# Both API + Web are already verified-listening by wait_port_listening
# above. No need for the legacy second curl loop. Mark READY for the
# downstream branches that print the standalone-app launch banner.
READY=true

if [ "$READY" = true ]; then
  # Sync MCP registry and tool catalog after API is ready
  log "Syncing MCP registry and tool catalog..."
  TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"email":"admin@abenix.dev","password":"Admin123456"}' 2>/dev/null | \
    $PYTHON -c "import sys,json; print(json.load(sys.stdin).get('data',{}).get('access_token',''))" 2>/dev/null)
  if [ -n "$TOKEN" ]; then
    curl -s -X POST http://localhost:8000/api/mcp/registry/sync \
      -H "Authorization: Bearer $TOKEN" >/dev/null 2>&1
    ok "MCP registry synced"
  else
    warn "Could not sync MCP registry (auth failed)"
  fi

  # ── Mint / validate standalone ABENIX_API_KEYs before launching apps ─
  # Run a small helper that hits the local platform API and ensures each
  # standalone has an active can_delegate-scoped key. Same logic as the
  # in-cluster scripts/seed-standalone-keys.sh, just talking to localhost.
  log "Reconciling standalone ABENIX_API_KEYs (idempotent)..."
  STANDALONE_KEYS_JSON=$(DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://abenix:abenix@localhost:5432/abenix}" \
    PYTHONPATH="$ROOT_DIR/packages/db" \
    $PYTHON -c "
import asyncio, hashlib, json, os, secrets, sys
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from models.api_key import ApiKey
from models.user import User

WANT = {
    'CONTRACTIQ_ABENIX_API_KEY':   'standalone-contractiq',
    'MIDEASTTOURISM_ABENIX_API_KEY': 'standalone-mideasttourism',
    'INDUSTRIALIOT_ABENIX_API_KEY':'standalone-industrial-iot',
    'RESOLVEAI_ABENIX_API_KEY':    'standalone-resolveai',
    'CLAIMSIQ_ABENIX_API_KEY':     'standalone-claimsiq',
    'WINGMAN_ABENIX_API_KEY':      'standalone-wingman',
    'PHARMAVIGIL_ABENIX_API_KEY':  'standalone-pharmavigil',
}

async def run():
    eng = create_async_engine(os.environ['DATABASE_URL'], echo=False)
    sf = async_sessionmaker(eng, expire_on_commit=False)
    out = {}
    async with sf() as db:
        u = (await db.execute(
            select(User).where(User.email == 'admin@abenix.dev')
        )).scalar_one_or_none()
        if u is None:
            print(json.dumps({}))
            return
        for env_var, name in WANT.items():
            current = os.environ.get(env_var, '').strip()
            valid = False
            if current.startswith('af_'):
                h = hashlib.sha256(current.encode()).hexdigest()
                row = (await db.execute(
                    select(ApiKey).where(ApiKey.key_hash == h, ApiKey.is_active.is_(True))
                )).scalar_one_or_none()
                if row is not None:
                    valid = True
                    out[env_var] = current
            if not valid:
                old = (await db.execute(
                    select(ApiKey).where(ApiKey.name == name, ApiKey.is_active.is_(True))
                )).scalars().all()
                for k in old:
                    k.is_active = False
                raw = 'af_' + secrets.token_urlsafe(40)
                ak = ApiKey(
                    user_id=u.id, tenant_id=u.tenant_id, name=name,
                    key_prefix=raw[:8] + '****' + raw[-4:],
                    key_hash=hashlib.sha256(raw.encode()).hexdigest(),
                    scopes={'allowed_actions': ['can_delegate', 'execute', 'list', 'read']},
                    is_active=True,
                )
                db.add(ak)
                await db.commit()
                out[env_var] = raw
    print(json.dumps(out))
    await eng.dispose()

asyncio.run(run())
" 2>/dev/null || echo "{}")

  # Export each minted/validated key so the start.sh files inherit it.
  if [ -n "$STANDALONE_KEYS_JSON" ] && [ "$STANDALONE_KEYS_JSON" != "{}" ]; then
    while IFS='=' read -r k v; do
      [ -n "$k" ] && export "$k=$v"
    done < <(echo "$STANDALONE_KEYS_JSON" | $PYTHON -c "
import sys,json
for k,v in json.load(sys.stdin).items(): print(f'{k}={v}')
" 2>/dev/null)
    ok "Standalone keys reconciled: $(echo "$STANDALONE_KEYS_JSON" | $PYTHON -c 'import sys,json; d=json.load(sys.stdin); print(len(d), "key(s) active")' 2>/dev/null)"
  else
    warn "Could not reconcile standalone keys — chat in ContractIQ/Mideast Tourism/etc. may 401"
  fi

  # ── Use-case apps ─────────────────────────────────────────────
  # One loop over APP_REGISTRY rather than a block per app. The previous
  # version hand-numbered its steps and the numbering had already drifted
  # ("Step 11/12" followed by "Step 12/13").
  if [ "${#SELECTED_APPS[@]}" -eq 0 ]; then
    echo ""
    log "No use-case apps selected — core platform only."
  else
    _pv_total="${#SELECTED_APPS[@]}"
    _pv_n=0
    for _app_i in "${!APP_REGISTRY[@]}"; do
      _key="$(app_key "${_app_i}")"
      app_selected "${_key}" || continue
      _dir="$(app_dir "${_app_i}")"
      _label="$(app_label "${_app_i}")"
      _pv_n=$((_pv_n + 1))
      if [ ! -f "$ROOT_DIR/${_dir}/start.sh" ]; then
        warn "${_label}: no start.sh at ${_dir}/ — skipped"
        continue
      fi
      echo ""
      log "App ${_pv_n}/${_pv_total} — starting ${_label} ($(app_ports "${_app_i}"))..."
      bash "$ROOT_DIR/${_dir}/start.sh" || warn "${_label} failed to start (non-fatal)"
    done
  fi

  echo ""
  echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"
  echo -e "${GREEN}  Running: core platform + $(describe_selection)${NC}"
  echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"
  echo ""
  echo -e "  ${CYAN}Abenix App${NC}     http://localhost:3000"
  for _app_i in "${!APP_REGISTRY[@]}"; do
    _key="$(app_key "${_app_i}")"
    app_selected "${_key}" || continue
    printf "  \033[0;36m%-18s\033[0m http://localhost:%s  (%s)\n" \
      "$(app_label "${_app_i}")" \
      "$(app_ports "${_app_i}" | cut -d/ -f1)" \
      "$(app_blurb "${_app_i}")"
  done
  echo -e "  ${CYAN}Abenix API${NC}     http://localhost:8000"
  echo -e "  ${CYAN}ContractIQ API${NC}     http://localhost:8001"
  echo -e "  ${CYAN}Mideast Tourism API${NC}  http://localhost:8002"
  echo -e "  ${CYAN}Industrial-IoT API${NC} http://localhost:8003"
  echo -e "  ${CYAN}ResolveAI API${NC}      http://localhost:8004"
  echo -e "  ${CYAN}Wingman API${NC}        http://localhost:8006"
  echo -e "  ${CYAN}API Docs${NC}           http://localhost:8000/docs"
  echo -e "  ${CYAN}Neo4j Browser${NC}      http://localhost:7474"
  echo ""
  echo -e "  ${YELLOW}Services:${NC}"
  echo -e "    API:     PID $API_PID — port 8000"
  echo -e "    Web:     PID $WEB_PID — port 3000"
  echo -e "    Celery:  PID $CELERY_PID — queues: documents, cognify"
  echo -e "    Neo4j:   bolt://localhost:7687 (user: neo4j, pass: abenix)"
  echo ""
  echo -e "  ${YELLOW}Logs:${NC} (per-process — $LOG_DIR/)"
  echo -e "    API:     tail -f $LOG_DIR/abenix-api.log"
  echo -e "    Web:     tail -f $LOG_DIR/abenix-web.log"
  echo -e "    Celery:  tail -f $LOG_DIR/celery.log"
  echo -e "    Consumer:tail -f $LOG_DIR/consumer.log"
  echo ""
  echo -e "  ${YELLOW}Stop:${NC}     bash scripts/dev-local.sh --stop"
  echo -e "  ${YELLOW}Restart:${NC}  bash scripts/dev-local.sh --restart"
  echo -e "  ${YELLOW}Status:${NC}   bash scripts/dev-local.sh --status"
  echo -e "  ${YELLOW}Tests:${NC}    npx playwright test --headed"
  echo ""
else
  warn "Services did not become ready."
  warn "Check logs:"
  warn "  API: tail -f $LOG_DIR/abenix-api.log"
  warn "  Web: tail -f $LOG_DIR/abenix-web.log"
  echo ""
  # Show last few lines of logs for debugging
  if [ -f "$LOG_DIR/abenix-api.log" ]; then
    log "Last API log lines:"
    tail -5 "$LOG_DIR/abenix-api.log" 2>/dev/null | sed 's/^/      /'
  fi
  if [ -f "$LOG_DIR/abenix-web.log" ]; then
    log "Last Web log lines:"
    tail -5 "$LOG_DIR/abenix-web.log" 2>/dev/null | sed 's/^/      /'
  fi
fi

echo ""
echo -e "  ${CYAN}For Kubernetes deployment:${NC} bash scripts/deploy.sh local"
echo ""
