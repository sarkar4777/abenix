#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load the azure.env shared with deploy-azure.sh so values stay in sync.
if [ -f "${ROOT_DIR}/scripts/azure.env" ]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/scripts/azure.env"
fi
AKS_NAME="${AKS_NAME:-abenix-aks}"
AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-your-resource-group}"
NAMESPACE="${NAMESPACE:-abenix}"

# ── Services we forward ────────────────────────────────────────────────────
# Format: "<service-name>:<local-port>:<remote-port>:<health-path>:<label>"
SERVICES=(
  "abenix-web:3000:3000:/:Abenix Web"
  "abenix-api:8000:8000:/api/health:Abenix API"
  "example_app-web:3001:3001:/:the example app Web"
  "example_app-api:8001:8001:/api/health:the example app API"
  "sauditourism-web:3002:3002:/:Saudi Tourism Web"
  "sauditourism-api:8002:8002:/api/health:Saudi Tourism API"
  "industrial-iot-web:3003:3003:/:Industrial IoT Web"
  "industrial-iot-api:8003:8003:/health:Industrial IoT API"
  "resolveai-web:3004:3004:/:ResolveAI Web"
  "resolveai-api:8004:8004:/health:ResolveAI API"
  # ClaimsIQ — single Spring Boot + Vaadin container (no api/web split).
  # Health is on Spring Boot Actuator's liveness probe.
  "claimsiq:3005:3005:/actuator/health/liveness:ClaimsIQ"
)

PID_DIR="/tmp/abenix-az-portforward"
mkdir -p "${PID_DIR}"

# ── Colors ──────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; C='\033[0;36m'; B='\033[1m'; N='\033[0m'
else
  G=""; Y=""; R=""; C=""; B=""; N=""
fi
log()  { echo -e "${C}[azure]${N} $1"; }
ok()   { echo -e "${G}  [ok]${N} $1"; }
warn() { echo -e "${Y}  [warn]${N} $1"; }
err()  { echo -e "${R}  [err]${N} $1" >&2; }

# ── Prereq checks ──────────────────────────────────────────────────────────
need() { command -v "$1" >/dev/null 2>&1 || { err "$1 not installed"; exit 2; }; }
check_prereqs() {
  need kubectl
  need curl
  if ! kubectl config current-context &>/dev/null; then
    err "No kubectl context. Run: az aks get-credentials -n ${AKS_NAME} -g ${AZ_RESOURCE_GROUP}"
    exit 3
  fi
  local ctx; ctx=$(kubectl config current-context)
  if [[ "${ctx}" != *"${AKS_NAME}"* ]]; then
    warn "Current kubectl context is '${ctx}', switching to '${AKS_NAME}'..."
    kubectl config use-context "${AKS_NAME}" 2>&1 | tail -1 || {
      # Try to get the context
      need az
      az aks get-credentials -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" --overwrite-existing 2>&1 | tail -1
      kubectl config use-context "${AKS_NAME}" 2>&1 | tail -1 || { err "Cannot switch to AKS context"; exit 3; }
    }
  fi
  # Verify namespace exists
  kubectl get ns "${NAMESPACE}" &>/dev/null || { err "Namespace ${NAMESPACE} not found"; exit 3; }
}

# ── Start / stop ───────────────────────────────────────────────────────────
stop_all() {
  log "Stopping all Abenix port-forwards..."
  # Kill our auto-reconnect wrappers
  if command -v pkill &>/dev/null; then
    pkill -f "start-azure.sh-keeper" 2>/dev/null || true
  fi
  # Kill stray kubectl port-forwards targeting our namespace
  if command -v pkill &>/dev/null; then
    pkill -f "kubectl port-forward.*${NAMESPACE}" 2>/dev/null || true
  fi
  # Best-effort Windows fallback — kill anything listening on our local ports
  for spec in "${SERVICES[@]}"; do
    local lp; lp=$(echo "$spec" | cut -d: -f2)
    if command -v netstat &>/dev/null; then
      local pids
      pids=$(netstat -ano 2>/dev/null | awk -v port=":${lp}" '$2 ~ port && /LISTENING/ {print $NF}' | sort -u)
      for pid in ${pids}; do
        taskkill //F //PID "${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
      done
    fi
  done
  rm -f "${PID_DIR}"/*.pid 2>/dev/null || true
  ok "All forwards stopped"
}

start_one() {
  local spec="$1"
  local svc local_port remote_port health_path label
  svc=$(echo "$spec"       | cut -d: -f1)
  local_port=$(echo "$spec"| cut -d: -f2)
  remote_port=$(echo "$spec"|cut -d: -f3)
  health_path=$(echo "$spec"|cut -d: -f4)
  label=$(echo "$spec"     | cut -d: -f5)

  local log_file="${PID_DIR}/${svc}.log"
  local pid_file="${PID_DIR}/${svc}.pid"

  # `$0` is start-azure.sh itself. We name the wrapper process identifiably
  # via a `start-azure.sh-keeper` marker so `stop_all` finds it with pkill.
  (
    exec -a "start-azure.sh-keeper:${svc}" bash -c "
      while true; do
        kubectl port-forward -n '${NAMESPACE}' 'svc/${svc}' ${local_port}:${remote_port} 2>/dev/null
        sleep 2
      done
    "
  ) >"${log_file}" 2>&1 &
  echo $! >"${pid_file}"
}

start_all() {
  local open_browser="${1:-true}"
  check_prereqs
  stop_all
  log "Starting 6 port-forwards to ${AKS_NAME} (namespace: ${NAMESPACE})..."
  for spec in "${SERVICES[@]}"; do
    start_one "${spec}"
    local svc; svc=$(echo "$spec" | cut -d: -f1)
    local label; label=$(echo "$spec" | cut -d: -f5)
    ok "${label} (${svc})"
  done

  log "Waiting for all endpoints to respond..."
  local all_ok="false"
  for i in $(seq 1 30); do
    all_ok="true"
    for spec in "${SERVICES[@]}"; do
      local lp path
      lp=$(echo "$spec"   | cut -d: -f2)
      path=$(echo "$spec" | cut -d: -f4)
      local code
      code=$(curl -sS --max-time 3 -o /dev/null -w "%{http_code}" "http://localhost:${lp}${path}" 2>/dev/null || echo "000")
      if [ "${code}" = "000" ] || [ "${code}" -ge "500" ]; then all_ok="false"; fi
    done
    if [ "${all_ok}" = "true" ]; then break; fi
    sleep 2
  done

  print_urls

  # Auto-open the primary app in the default browser. Opt-out with
  # --no-browser if you're on a headless box or just want the forwards.
  if [ "${open_browser}" = "true" ]; then
    log "Opening http://localhost:3000 in your default browser..."
    open_url "http://localhost:3000"
  fi
}

# ── Status / URL printer ───────────────────────────────────────────────────
probe_one() {
  local spec="$1"
  local lp path code
  lp=$(echo "$spec"   | cut -d: -f2)
  path=$(echo "$spec" | cut -d: -f4)
  # -w prints "000" on failure already; capture stdout, strip newlines.
  code=$(curl -sS --max-time 3 -o /dev/null -w "%{http_code}" "http://localhost:${lp}${path}" 2>/dev/null)
  # Fallback only if curl printed nothing (very rare)
  [ -z "${code}" ] && code="000"
  echo "${code}"
}

print_urls() {
  echo ""
  echo -e "${B}═══════════════════════════════════════════════════════════════${N}"
  echo -e "${B}  Abenix on Azure AKS — live on your laptop${N}"
  echo -e "${B}═══════════════════════════════════════════════════════════════${N}"
  echo ""
  echo -e "${B}Services${N} (each auto-reconnects if the pod restarts):"
  echo ""
  for spec in "${SERVICES[@]}"; do
    local svc lp label code
    svc=$(echo "$spec"   | cut -d: -f1)
    lp=$(echo "$spec"    | cut -d: -f2)
    label=$(echo "$spec" | cut -d: -f5)
    code=$(probe_one "${spec}")
    local dot
    if [ "${code}" = "200" ] || [ "${code}" = "301" ] || [ "${code}" = "307" ]; then
      dot="${G}●${N}"
    elif [ "${code}" = "000" ]; then
      dot="${R}●${N}"
    else
      dot="${Y}●${N}"
    fi
    printf "  ${dot} %-22s ${C}http://localhost:%s${N}  (%s)\n" "${label}" "${lp}" "${code}"
  done
  echo ""
  echo -e "${B}Featured pages${N}"
  cat <<URLS
  Abenix
    Dashboard           http://localhost:3000/dashboard
    AI Builder          http://localhost:3000/builder
    Agents (80 seeded)  http://localhost:3000/agents
    Chat                http://localhost:3000/chat
    Knowledge Base      http://localhost:3000/knowledge
    SDK Playground      http://localhost:3000/sdk-playground
    ML Models           http://localhost:3000/ml-models
    Marketplace         http://localhost:3000/marketplace
    Code Runner         http://localhost:3000/code-runner
    Executions          http://localhost:3000/executions
    Triggers            http://localhost:3000/triggers
    Analytics           http://localhost:3000/analytics
    MCP Connections     http://localhost:3000/mcp
    Meetings            http://localhost:3000/meetings
    Alerts              http://localhost:3000/alerts
    OracleNet           http://localhost:3000/oraclenet
    API docs (Swagger)  http://localhost:8000/docs

  the example app
    Dashboard           http://localhost:3001/dashboard
    Contracts           http://localhost:3001/contracts
    Upload              http://localhost:3001/upload
    Deal Clusters       http://localhost:3001/deal-clusters
    Valuation           http://localhost:3001/valuation
    Insights Hub        http://localhost:3001/insights
    Clause Benchmarking http://localhost:3001/insights/benchmark
    KYC                 http://localhost:3001/credit-risk/kyc
    Chat                http://localhost:3001/chat
    Agent Atlas (help)  http://localhost:3001/help

  Saudi Tourism
    Dashboard           http://localhost:3002/dashboard
    Upload              http://localhost:3002/upload
    Regional Analytics  http://localhost:3002/analytics/regional
    Deep Analytics      http://localhost:3002/analytics/deep
    Simulations         http://localhost:3002/simulations
    Chat                http://localhost:3002/chat
    Reports             http://localhost:3002/reports

  Industrial IoT
    Dashboard           http://localhost:3003/
    API pipelines       http://localhost:8003/api/industrial-iot/pipelines

  ResolveAI
    Dashboard           http://localhost:3004/
    Cases queue         http://localhost:3004/cases
    SLA Board           http://localhost:3004/sla
    QA & CSAT           http://localhost:3004/qa
    Trends / VoC        http://localhost:3004/trends
    Admin               http://localhost:3004/admin

  ClaimsIQ (Java + Vaadin)
    Dashboard           http://localhost:3005/
    New FNOL            http://localhost:3005/fnol
    Claims queue        http://localhost:3005/claims
    Walkthrough         http://localhost:3005/help
    Health              http://localhost:3005/actuator/health
URLS
  echo ""
  echo -e "${B}Credentials${N}"
  echo -e "  Abenix      ${Y}admin@abenix.dev${N} / ${Y}Admin123456${N}  (or demo@abenix.dev / Demo123456)"
  echo -e "  the example app      ${Y}test@example_app.com${N} / ${Y}TestPass123!${N}"
  echo -e "  Saudi Tourism   use the 'demo credentials' button on the sign-in modal"
  echo ""
  echo -e "${B}Controls${N}"
  echo "  bash scripts/portforward-azure.sh status   # health check"
  echo "  bash scripts/portforward-azure.sh stop     # tear down port-forwards"
  echo "  bash scripts/portforward-azure.sh restart  # stop + start"
  echo ""
  echo -e "${C}Note${N} — port-forwards tunnel kubectl's session. If kubectl loses"
  echo -e "auth, forwards will start failing; just run ${Y}bash scripts/portforward-azure.sh restart${N}."
  echo ""
}

status_cmd() {
  check_prereqs
  echo -e "${B}Port-forward processes:${N}"
  if command -v pgrep &>/dev/null; then
    pgrep -fa "start-azure.sh-keeper" 2>/dev/null || echo "  (none)"
  fi
  print_urls
}

# ── Pods — show everything running in the namespace ────────────────────────
pods_cmd() {
  check_prereqs
  local extra="${1:-}"
  if [ "${extra}" = "-w" ] || [ "${extra}" = "--watch" ]; then
    log "Watching pods in namespace ${NAMESPACE} (Ctrl-C to exit)..."
    kubectl get pods -n "${NAMESPACE}" -o wide --watch
    return
  fi
  log "Pods in namespace ${NAMESPACE} (AKS: ${AKS_NAME})"
  echo ""
  kubectl get pods -n "${NAMESPACE}" -o wide 2>&1
  echo ""
  # Quick summary: running / total + restart pressure
  local total running ready restarts_high
  total=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | wc -l | tr -d ' ')
  running=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | awk '$3=="Running"' | wc -l | tr -d ' ')
  ready=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | awk '{split($2,a,"/"); if (a[1]==a[2]) print}' | wc -l | tr -d ' ')
  restarts_high=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | awk '$4+0 > 5' | wc -l | tr -d ' ')
  echo -e "${B}Summary${N}  ${G}${running}${N} running / ${B}${total}${N} total   ·   ${ready} fully-ready   ·   ${Y}${restarts_high}${N} with >5 restarts"
  echo ""
  echo -e "${B}Useful follow-ups${N}"
  echo "  kubectl logs -n ${NAMESPACE} <pod-name> --tail=100"
  echo "  kubectl logs -n ${NAMESPACE} deploy/abenix-api --tail=200 -f"
  echo "  kubectl describe pod -n ${NAMESPACE} <pod-name>"
  echo "  kubectl exec -n ${NAMESPACE} -it <pod-name> -- bash"
  echo "  bash scripts/portforward-azure.sh pods -w        # watch live"
  echo ""
}

# ── Browser opener — cross-platform ────────────────────────────────────────
open_url() {
  local url="$1"
  local os; os=$(uname -s 2>/dev/null || echo unknown)
  case "${os}" in
    Darwin*)
      open "${url}" &>/dev/null &
      ;;
    Linux*)
      if command -v xdg-open &>/dev/null; then
        xdg-open "${url}" &>/dev/null &
      elif command -v sensible-browser &>/dev/null; then
        sensible-browser "${url}" &>/dev/null &
      else
        warn "No xdg-open / sensible-browser — open ${url} manually"
      fi
      ;;
    MINGW*|CYGWIN*|MSYS*|Windows*)
      # On Git-Bash / WSL-to-Windows, `start` is a cmd builtin. Use cmd.exe /c.
      cmd.exe /c start "" "${url}" &>/dev/null || start "${url}" &>/dev/null &
      ;;
    *)
      warn "Unknown OS '${os}' — open ${url} manually"
      ;;
  esac
}

open_app_cmd() {
  local app="${1:-af}"
  case "${app}" in
    af|abenix)    open_url "http://localhost:3000" ;;
    ciq|example_app)   open_url "http://localhost:3001" ;;
    st|sauditourism|tourism) open_url "http://localhost:3002" ;;
    iot|industrial-iot) open_url "http://localhost:3003" ;;
    care|resolveai)   open_url "http://localhost:3004" ;;
    cq|claims|claimsiq) open_url "http://localhost:3005" ;;
    docs|swagger|api) open_url "http://localhost:8000/docs" ;;
    all)
      open_url "http://localhost:3000"
      open_url "http://localhost:3001"
      open_url "http://localhost:3002"
      open_url "http://localhost:3003"
      open_url "http://localhost:3004"
      open_url "http://localhost:3005"
      ;;
    *)
      err "Unknown app '${app}'. Try: af | ciq | st | iot | care | cq | docs | all"
      return 1
      ;;
  esac
}

# ── Main ────────────────────────────────────────────────────────────────────
# Accept a --no-browser flag anywhere in argv (scrub it before we dispatch).
OPEN_BROWSER="true"
ARGS=()
for a in "$@"; do
  case "$a" in
    --no-browser|--headless) OPEN_BROWSER="false" ;;
    *)                       ARGS+=("$a") ;;
  esac
done
set -- "${ARGS[@]}"

cmd="${1:-start}"
shift || true
case "${cmd}" in
  start|up|"")     start_all "${OPEN_BROWSER}" ;;
  stop|down)       stop_all ;;
  status|ps)       status_cmd ;;
  pods|kubectl)    pods_cmd "$@" ;;
  open|browse)     open_app_cmd "${1:-af}" ;;
  urls|links)      print_urls ;;
  restart)         stop_all; sleep 2; start_all "${OPEN_BROWSER}" ;;
  -h|--help|help)  sed -n '1,34p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
  *)               err "Unknown command: ${cmd}"; sed -n '10,34p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
