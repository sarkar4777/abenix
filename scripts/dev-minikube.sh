#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Abenix — Fast Demo Startup
#
# Ensures minikube is up, required pods are running, port-forwards are active,
# and standalone apps (ContractIQ + Mideast Tourism) are started.
#
#   bash scripts/dev-minikube.sh            Start everything
#   bash scripts/dev-minikube.sh --status   Just show what's running
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS="abenix"

G='\033[0;32m' Y='\033[1;33m' R='\033[0;31m' C='\033[0;36m' B='\033[1m' N='\033[0m'
ok()  { echo -e "  ${G}✓${N} $1"; }
warn(){ echo -e "  ${Y}⚠${N} $1"; }
err() { echo -e "  ${R}✗${N} $1"; }
log() { echo -e "  ${C}▸${N} $1"; }

# Load .env
[ -f "$ROOT/.env" ] && {
  while IFS='=' read -r k v; do
    [[ "$k" =~ ^[[:space:]]*#|^$ ]] && continue
    k="${k%$'\r'}"; k="$(echo "$k"|xargs)"
    [[ "$k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    case "$v" in \[*|\{*) continue;; esac
    v="${v%$'\r'}"
    [ -z "${!k:-}" ] && export "$k=$v" 2>/dev/null || true
  done < "$ROOT/.env"
}
export PGSSLMODE="${PGSSLMODE:-disable}"

PYTHON=$(command -v python || command -v python3) || { err "Python not found"; exit 1; }

# ── Helpers ──────────────────────────────────────────────────────────────────

listening() { netstat -ano 2>/dev/null | grep -q ":${1}.*LISTENING"; }

pf() {
  local svc=$1 lp=$2 rp=$3
  if listening "$lp"; then
    # Verify it's actually working, not a stale socket
    if timeout 2 bash -c "echo > /dev/tcp/localhost/$lp" 2>/dev/null; then
      ok "$svc → :$lp (active)"
      return 0
    fi
    # Stale — kill it
    local pid; pid=$(netstat -ano 2>/dev/null | grep ":${lp}.*LISTENING" | awk '{print $5}' | head -1)
    [ -n "$pid" ] && (taskkill //PID "$pid" //F 2>/dev/null || kill -9 "$pid" 2>/dev/null) || true
    sleep 1
  fi
  nohup bash -c "while true; do kubectl port-forward -n $NS svc/$svc $lp:$rp 2>/dev/null; sleep 2; done" &>/dev/null &
  ok "$svc → :$lp (started)"
}

pod_ok() {
  kubectl get pod -l "$1" -n "$NS" --no-headers 2>/dev/null | grep -q "Running"
}

get_db_url() {
  local pw
  pw=$(kubectl get secret abenix-secrets -n "$NS" -o jsonpath='{.data.postgres-password}' 2>/dev/null | base64 -d 2>/dev/null || echo "localpass")
  echo "postgresql+asyncpg://postgres:${pw}@localhost:5432/abenix"
}

# ── Status ───────────────────────────────────────────────────────────────────

show_status() {
  echo -e "\n${B}Services:${N}"
  for e in "8000:Abenix API" "3000:Abenix Web" "5432:PostgreSQL" "6379:Redis" \
           "8001:ContractIQ API" "3001:ContractIQ Web" "8002:Mideast Tourism API" "3002:Mideast Tourism Web"; do
    local p="${e%%:*}" l="${e##*:}"
    if listening "$p"; then
      echo -e "    ${G}●${N} ${l}  → localhost:${p}"
    else
      echo -e "    ${R}○${N} ${l}  → localhost:${p}"
    fi
  done
  echo -e "\n${B}Links:${N}"
  echo -e "    Abenix:     ${C}http://localhost:3000${N}"
  echo -e "    ContractIQ:     ${C}http://localhost:3001${N}  (test@contractiq.com / TestPass123!)"
  echo -e "    Mideast Tourism:  ${C}http://localhost:3002${N}  (test@mideasttourism.gov.sa / TestPass123!)"
  echo -e "    Industrial IoT: ${C}http://localhost:3003${N}"
  echo -e "    ResolveAI:      ${C}http://localhost:3004${N}  — Customer-service agents"
  echo -e "    ClaimsIQ:       ${C}http://localhost:3005${N}  — Insurance FNOL (Java + Vaadin)"
  echo ""
}

# ══════════════════════════════════════════════════════════════════════════════

if [ "${1:-}" = "--status" ]; then show_status; exit 0; fi

echo -e "\n${G}Abenix — Demo Startup${N}\n"

# 1. Minikube
echo -e "${B}1. Minikube${N}"
if minikube status --format='{{.APIServer}}' 2>/dev/null | grep -q Running; then
  ok "Already running"
else
  log "Starting minikube..."
  minikube start 2>&1 | tail -2
  minikube update-context &>/dev/null || true
  ok "Started"
fi

# 2. Check required pods (by name prefix, not labels)
echo -e "\n${B}2. Required pods${N}"
for pod in abenix-api abenix-postgresql abenix-redis-master; do
  if kubectl get pods -n "$NS" --no-headers 2>/dev/null | grep "^${pod}" | grep -q Running; then
    ok "$pod running"
  else
    warn "$pod not running — waiting 30s..."
    for i in $(seq 1 6); do
      kubectl get pods -n "$NS" --no-headers 2>/dev/null | grep "^${pod}" | grep -q Running && break
      sleep 5
    done
    kubectl get pods -n "$NS" --no-headers 2>/dev/null | grep "^${pod}" | grep -q Running \
      && ok "$pod running" || err "$pod still not ready"
  fi
done

# 3. Port-forward (only if not already listening)
echo -e "\n${B}3. Port forwards${N}"
pf abenix-postgresql    5432 5432
pf abenix-api           8000 8000
pf abenix-web           3000 3000
pf abenix-redis-master  6379 6379

# Standalone apps + extras (only if services exist in k8s)
kubectl -n "$NS" get svc contractiq-api      &>/dev/null 2>&1 && pf contractiq-api      8001 8001
kubectl -n "$NS" get svc contractiq-web      &>/dev/null 2>&1 && pf contractiq-web      3001 3001
kubectl -n "$NS" get svc mideasttourism-api    &>/dev/null 2>&1 && pf mideasttourism-api    8002 8002
kubectl -n "$NS" get svc mideasttourism-web    &>/dev/null 2>&1 && pf mideasttourism-web    3002 3002
kubectl -n "$NS" get svc industrial-iot-api  &>/dev/null 2>&1 && pf industrial-iot-api  8003 8003
kubectl -n "$NS" get svc industrial-iot-web  &>/dev/null 2>&1 && pf industrial-iot-web  3003 3003
kubectl -n "$NS" get svc resolveai-api       &>/dev/null 2>&1 && pf resolveai-api       8004 8004
kubectl -n "$NS" get svc resolveai-web       &>/dev/null 2>&1 && pf resolveai-web       3004 3004
kubectl -n "$NS" get svc claimsiq            &>/dev/null 2>&1 && pf claimsiq            3005 3005
kubectl -n "$NS" get svc livekit-server      &>/dev/null 2>&1 && pf livekit-server      7880 7880
kubectl -n "$NS" get svc abenix-neo4j &>/dev/null 2>&1 && pf abenix-neo4j 7474 7474
kubectl -n "$NS" get svc abenix-prometheus &>/dev/null 2>&1 && pf abenix-prometheus 9090 9090
kubectl -n "$NS" get svc abenix-grafana &>/dev/null 2>&1 && pf abenix-grafana 3030 3000

# v1.1 production tooling — MQTT broker, TimescaleDB, edge-runtime gateway
kubectl -n "$NS" get svc abenix-mosquitto &>/dev/null 2>&1 && pf abenix-mosquitto 1883 1883
kubectl -n "$NS" get svc abenix-timescaledb &>/dev/null 2>&1 && pf abenix-timescaledb 5433 5432
kubectl -n "$NS" get svc abenix-edge &>/dev/null 2>&1 && pf abenix-edge 8088 8080
kubectl -n "$NS" get svc abenix-edge-rust &>/dev/null 2>&1 && pf abenix-edge-rust 8089 8080
kubectl -n "$NS" get svc abenix-edge-c &>/dev/null 2>&1 && pf abenix-edge-c 8090 8080

sleep 2

# Helper: read a key from .env reliably
env_val() { grep "^${1}=" "$ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r'; }

_start_st_api() {
  mkdir -p "$ROOT/mideasttourism/logs"
  cd "$ROOT/mideasttourism/api"
  local st_key; st_key=$(env_val MIDEASTTOURISM_ABENIX_API_KEY)
  DATABASE_URL="$DB_URL" PORT=8002 ABENIX_API_URL="http://localhost:8000" \
    MIDEASTTOURISM_ABENIX_API_KEY="$st_key" \
    PGSSLMODE=disable \
    $PYTHON main.py > "$ROOT/mideasttourism/logs/api.log" 2>&1 &
  ok "Mideast Tourism API (starting on :8002, SDK key ${st_key:+set}${st_key:-MISSING})"
}

_start_ciq_api() {
  mkdir -p "$ROOT/contractiq/logs"
  cd "$ROOT/contractiq/api"
  local ciq_key; ciq_key=$(env_val CONTRACTIQ_ABENIX_API_KEY)
  DATABASE_URL="$DB_URL" PORT=8001 ABENIX_API_URL="http://localhost:8000" \
    CONTRACTIQ_ABENIX_API_KEY="$ciq_key" \
    PGSSLMODE=disable \
    $PYTHON main.py > "$ROOT/contractiq/logs/api.log" 2>&1 &
  ok "ContractIQ API (starting on :8001)"
}

# 4. Standalone apps
echo -e "\n${B}4. Standalone apps${N}"
DB_URL=$(get_db_url)

# ContractIQ API
if curl -sf http://localhost:8001/api/health &>/dev/null; then
  ok "ContractIQ API (already running)"
else
  _start_ciq_api
fi

# ContractIQ Web
if listening 3001 && ! kubectl -n "$NS" get svc contractiq-web &>/dev/null 2>&1; then
  ok "ContractIQ Web (already running)"
elif ! listening 3001; then
  cd "$ROOT/contractiq/web"
  [ ! -d node_modules ] && npm install --silent &>/dev/null
  NEXT_PUBLIC_API_URL="http://localhost:8001" nohup npm run dev > "$ROOT/contractiq/logs/web.log" 2>&1 &
  ok "ContractIQ Web (starting on :3001)"
fi

# Mideast Tourism API
if curl -sf http://localhost:8002/api/health &>/dev/null; then
  # Verify SDK key is configured
  local sdk_ok
  sdk_ok=$(curl -sf http://localhost:8002/api/health 2>/dev/null | grep -o '"abenix_sdk_configured":true' || true)
  if [ -n "$sdk_ok" ]; then
    ok "Mideast Tourism API (running, SDK configured)"
  else
    warn "Mideast Tourism API running but SDK key missing — restarting"
    local pid; pid=$(netstat -ano 2>/dev/null | grep ":8002.*LISTENING" | awk '{print $5}' | head -1)
    [ -n "$pid" ] && (taskkill //PID "$pid" //F 2>/dev/null || kill -9 "$pid" 2>/dev/null) || true
    sleep 1
    _start_st_api
  fi
else
  _start_st_api
fi

# Mideast Tourism Web
if listening 3002; then
  ok "Mideast Tourism Web (already running)"
else
  cd "$ROOT/mideasttourism/web"
  [ ! -d node_modules ] && npm install --silent &>/dev/null
  NEXT_PUBLIC_API_URL="http://localhost:8002" nohup npm run dev > "$ROOT/mideasttourism/logs/web.log" 2>&1 &
  ok "Mideast Tourism Web (starting on :3002)"
fi

# 5. Done
echo ""
show_status
