#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
mkdir -p "$EXPORT_DIR" "$UPLOAD_DIR" "$ML_MODELS_DIR" \
         "$CODE_ASSET_STORE" "$CODE_ASSET_BUILD_CACHE" 2>/dev/null || true
export EXPORT_DIR UPLOAD_DIR ML_MODELS_DIR CODE_ASSET_STORE CODE_ASSET_BUILD_CACHE

# ── Kill process on a port (cross-platform) ──────────────────
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

# ── Kill old processes ────────────────────────────────────────
kill_processes() {
  log "Stopping Abenix processes..."
  kill_port 8000 "API server"
  kill_port 3000 "Web server"
  kill_port 8001 "the example app API"
  kill_port 3001 "the example app Web"
  kill_port 8002 "Saudi Tourism API"
  kill_port 3002 "Saudi Tourism Web"
  kill_port 8003 "Industrial-IoT API"
  kill_port 3003 "Industrial-IoT Web"
  kill_port 8004 "ResolveAI API"
  kill_port 3004 "ResolveAI Web"

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

# ── Status check ──────────────────────────────────────────────
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

  # API
  if curl -s --max-time 3 http://localhost:8000/api/health >/dev/null 2>&1; then
    ok "API server — http://localhost:8000"
  else
    err "API server not responding on :8000"
  fi

  # Web
  if curl -s --max-time 3 http://localhost:3000 -o /dev/null 2>&1; then
    ok "Web server — http://localhost:3000"
  else
    err "Web server not responding on :3000"
  fi

  # Neo4j
  if curl -s --max-time 3 http://localhost:7474 >/dev/null 2>&1; then
    ok "Neo4j — http://localhost:7474 (Browser) / bolt://localhost:7687"
  else
    err "Neo4j not responding on :7474"
  fi

  # the example app
  if curl -s --max-time 3 http://localhost:8001/api/health >/dev/null 2>&1; then
    ok "the example app API — http://localhost:8001"
  else
    warn "the example app API not responding on :8001"
  fi
  if curl -s --max-time 3 http://localhost:3001 -o /dev/null 2>&1; then
    ok "the example app Web — http://localhost:3001"
  else
    warn "the example app Web not responding on :3001"
  fi

  # Saudi Tourism
  if curl -s --max-time 3 http://localhost:8002/api/health >/dev/null 2>&1; then
    ok "Saudi Tourism API — http://localhost:8002"
  else
    warn "Saudi Tourism API not responding on :8002"
  fi
  if curl -s --max-time 3 http://localhost:3002 -o /dev/null 2>&1; then
    ok "Saudi Tourism Web — http://localhost:3002"
  else
    warn "Saudi Tourism Web not responding on :3002"
  fi

  # Industrial IoT
  if curl -s --max-time 3 http://localhost:8003/health >/dev/null 2>&1; then
    ok "Industrial-IoT API — http://localhost:8003"
  else
    warn "Industrial-IoT API not responding on :8003"
  fi
  if curl -s --max-time 3 http://localhost:3003 -o /dev/null 2>&1; then
    ok "Industrial-IoT Web — http://localhost:3003"
  else
    warn "Industrial-IoT Web not responding on :3003"
  fi

  # ResolveAI
  if curl -s --max-time 3 http://localhost:8004/health >/dev/null 2>&1; then
    ok "ResolveAI API — http://localhost:8004"
  else
    warn "ResolveAI API not responding on :8004"
  fi
  if curl -s --max-time 3 http://localhost:3004 -o /dev/null 2>&1; then
    ok "ResolveAI Web — http://localhost:3004"
  else
    warn "ResolveAI Web not responding on :3004"
  fi

  # Celery
  if [ "$IS_WINDOWS" = true ]; then
    if tasklist 2>/dev/null | grep -qi "celery\|python" && [ -f "$ROOT_DIR/logs/celery.log" ]; then
      ok "Celery worker — logs/celery.log"
    else
      warn "Celery worker may not be running"
    fi
  else
    if pgrep -f "celery.*worker" >/dev/null 2>&1; then
      ok "Celery worker — logs/celery.log"
    else
      warn "Celery worker not running"
    fi
  fi
  echo ""
}

# ── Handle --stop and --status ────────────────────────────────
if [ "${1:-}" = "--stop" ]; then
  kill_processes
  log "All Abenix processes stopped."
  exit 0
fi

if [ "${1:-}" = "--status" ]; then
  check_status
  exit 0
fi

# STARTUP
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       Abenix Dev Environment         ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

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
docker compose ps 2>/dev/null | grep "abenix-postgres" | grep -q "healthy" && PG_HEALTHY=true
docker compose ps 2>/dev/null | grep "abenix-redis" | grep -q "healthy" && REDIS_HEALTHY=true
docker compose ps 2>/dev/null | grep "abenix-neo4j" | grep -q "healthy" && NEO4J_HEALTHY=true
docker compose ps 2>/dev/null | grep "abenix-nats" | grep -q "healthy" && NATS_HEALTHY=true

if [ "$PG_HEALTHY" = true ] && [ "$REDIS_HEALTHY" = true ] && [ "$NEO4J_HEALTHY" = true ] && [ "$NATS_HEALTHY" = true ]; then
  ok "Postgres, Redis, Neo4j, and NATS already running and healthy"
else
  docker compose up -d 2>&1 | sed 's/^/      /'
  log "Waiting for containers to be healthy..."
  for i in $(seq 1 45); do
    PG_OK=false
    RD_OK=false
    N4_OK=false
    NA_OK=false
    docker compose ps 2>/dev/null | grep "abenix-postgres" | grep -q "healthy" && PG_OK=true
    docker compose ps 2>/dev/null | grep "abenix-redis" | grep -q "healthy" && RD_OK=true
    docker compose ps 2>/dev/null | grep "abenix-neo4j" | grep -q "healthy" && N4_OK=true
    docker compose ps 2>/dev/null | grep "abenix-nats" | grep -q "healthy" && NA_OK=true

    if [ "$PG_OK" = true ] && [ "$RD_OK" = true ] && [ "$N4_OK" = true ] && [ "$NA_OK" = true ]; then
      ok "Postgres, Redis, Neo4j, and NATS are healthy"
      break
    fi
    if [ "$i" -eq 45 ]; then
      if [ "$PG_OK" = true ] && [ "$RD_OK" = true ] && [ "$NA_OK" = true ]; then
        warn "Neo4j is still starting — Knowledge Engine features may be delayed"
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

# Run alembic to head — applies the catchup migration if needed.
MIGRATION_OUT=$(PYTHONPATH="." $PYTHON -m alembic upgrade head 2>&1) || true
echo "$MIGRATION_OUT" | grep "Running upgrade" | sed 's/^/      /' || true

# Sentinel column list — small, load-bearing, updated whenever a
# schema-changing migration lands. If ALL of these are present,
# the schema is considered current.
_CANONICAL_COLUMNS=(
  "executions.node_results"
  "executions.execution_trace"
  "executions.failure_code"
  "agent_shares.shared_with_user_id"
  "moderation_policies.default_action"
  "agent_memories.importance"
)

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

mkdir -p "$ROOT_DIR/logs"

# Start API server (DEBUG=true for local dev — allows default secrets)
cd "$ROOT_DIR/apps/api"
DEBUG=true PGSSLMODE=disable PYTHONPATH=".:../../packages/db:../../apps/agent-runtime" $PYTHON -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 \
  > "$ROOT_DIR/logs/api.log" 2>&1 &
API_PID=$!
cd "$ROOT_DIR"
ok "API server starting (PID $API_PID) — port 8000"

# Start Web server
cd "$ROOT_DIR/apps/web"
npx next dev --port 3000 \
  > "$ROOT_DIR/logs/web.log" 2>&1 &
WEB_PID=$!
cd "$ROOT_DIR"
ok "Web server starting (PID $WEB_PID) — port 3000"

# Start Celery worker (handles document processing, cognify, and memify)
# On Python 3.13 the prefork pool's `fast_trace_task` crashes with
# `ValueError: not enough values to unpack (expected 3, got 0)` because of a
# Celery 5.x billiard incompatibility. Use `--pool=solo` on dev to dodge it.
cd "$ROOT_DIR/apps/worker"
PYTHONPATH=".:../../packages/db:../agent-runtime" $PYTHON -m celery \
  -A worker.celery_app worker \
  -Q documents,cognify,agents \
  -l info --pool=solo \
  > "$ROOT_DIR/logs/celery.log" 2>&1 &
CELERY_PID=$!
cd "$ROOT_DIR"
ok "Celery worker starting (PID $CELERY_PID, pool=solo) — queues: documents, cognify, agents"

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
    > "$ROOT_DIR/logs/consumer.log" 2>&1 &
  CONSUMER_PID=$!
  cd "$ROOT_DIR"
  ok "NATS consumer starting (PID $CONSUMER_PID) — pool=default, backend=nats"
fi

# ── Wait for services to be ready ─────────────────────────────
log "Waiting for services to be ready..."
READY=false
for i in $(seq 1 60); do
  API_OK=false
  WEB_OK=false

  curl -s --max-time 2 http://localhost:8000/api/health >/dev/null 2>&1 && API_OK=true
  curl -s --max-time 2 http://localhost:3000 -o /dev/null 2>&1 && WEB_OK=true

  if [ "$API_OK" = true ] && [ "$WEB_OK" = true ]; then
    READY=true
    break
  fi
  sleep 1
done

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

  # ── Step 8: Start the example app standalone application ──────────
  if [ -f "$ROOT_DIR/example_app/start.sh" ]; then
    echo ""
    log "Step 8/11 — Starting the example app standalone application..."
    bash "$ROOT_DIR/example_app/start.sh" || warn "the example app failed to start (non-fatal)"
  fi

  # ── Step 9: Start Saudi Tourism standalone application ──────
  if [ -f "$ROOT_DIR/sauditourism/start.sh" ]; then
    echo ""
    log "Step 9/11 — Starting Saudi Tourism standalone application..."
    bash "$ROOT_DIR/sauditourism/start.sh" || warn "Saudi Tourism failed to start (non-fatal)"
  fi

  # ── Step 10: Start Industrial-IoT standalone application ────
  if [ -f "$ROOT_DIR/industrial-iot/start.sh" ]; then
    echo ""
    log "Step 10/11 — Starting Industrial-IoT standalone application..."
    bash "$ROOT_DIR/industrial-iot/start.sh" || warn "Industrial-IoT failed to start (non-fatal)"
  fi

  # ── Step 11: Start ResolveAI standalone application ─────────
  if [ -f "$ROOT_DIR/resolveai/start.sh" ]; then
    echo ""
    log "Step 11/12 — Starting ResolveAI standalone application..."
    bash "$ROOT_DIR/resolveai/start.sh" || warn "ResolveAI failed to start (non-fatal)"
  fi

  # ── Step 12: Start ClaimsIQ standalone application (Java) ───
  if [ -f "$ROOT_DIR/claimsiq/start.sh" ]; then
    echo ""
    log "Step 12/12 — Starting ClaimsIQ (Spring Boot + Vaadin, Java)…"
    bash "$ROOT_DIR/claimsiq/start.sh" || warn "ClaimsIQ failed to start (non-fatal — needs Java 21 + Gradle)"
  fi

  echo ""
  echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"
  echo -e "${GREEN}  All apps running: core + 5 standalones${NC}"
  echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"
  echo ""
  echo -e "  ${CYAN}Abenix App${NC}     http://localhost:3000"
  echo -e "  ${CYAN}the example app App${NC}     http://localhost:3001"
  echo -e "  ${CYAN}Saudi Tourism${NC}      http://localhost:3002"
  echo -e "  ${CYAN}Industrial IoT${NC}     http://localhost:3003"
  echo -e "  ${CYAN}ResolveAI${NC}          http://localhost:3004  (customer-service agents)"
  echo -e "  ${CYAN}ClaimsIQ${NC}           http://localhost:3005  (insurance FNOL, Java + Vaadin)"
  echo -e "  ${CYAN}Abenix API${NC}     http://localhost:8000"
  echo -e "  ${CYAN}the example app API${NC}     http://localhost:8001"
  echo -e "  ${CYAN}Saudi Tourism API${NC}  http://localhost:8002"
  echo -e "  ${CYAN}Industrial-IoT API${NC} http://localhost:8003"
  echo -e "  ${CYAN}ResolveAI API${NC}      http://localhost:8004"
  echo -e "  ${CYAN}API Docs${NC}           http://localhost:8000/docs"
  echo -e "  ${CYAN}Neo4j Browser${NC}      http://localhost:7474"
  echo ""
  echo -e "  ${YELLOW}Services:${NC}"
  echo -e "    API:     PID $API_PID — port 8000"
  echo -e "    Web:     PID $WEB_PID — port 3000"
  echo -e "    Celery:  PID $CELERY_PID — queues: documents, cognify, agents"
  echo -e "    Neo4j:   bolt://localhost:7687 (user: neo4j, pass: abenix)"
  echo ""
  echo -e "  ${YELLOW}Logs:${NC}"
  echo -e "    API:     tail -f logs/api.log"
  echo -e "    Web:     tail -f logs/web.log"
  echo -e "    Celery:  tail -f logs/celery.log"
  echo ""
  echo -e "  ${YELLOW}Stop:${NC}  bash scripts/dev-local.sh --stop"
  echo -e "  ${YELLOW}Tests:${NC} npx playwright test --headed"
  echo ""
else
  warn "Services did not become ready within 60s."
  warn "Check logs:"
  warn "  API: tail -f $ROOT_DIR/logs/api.log"
  warn "  Web: tail -f $ROOT_DIR/logs/web.log"
  echo ""
  # Show last few lines of logs for debugging
  if [ -f "$ROOT_DIR/logs/api.log" ]; then
    log "Last API log lines:"
    tail -5 "$ROOT_DIR/logs/api.log" 2>/dev/null | sed 's/^/      /'
  fi
  if [ -f "$ROOT_DIR/logs/web.log" ]; then
    log "Last Web log lines:"
    tail -5 "$ROOT_DIR/logs/web.log" 2>/dev/null | sed 's/^/      /'
  fi
fi

echo ""
echo -e "  ${CYAN}For Kubernetes deployment:${NC} bash scripts/deploy.sh local"
echo ""
