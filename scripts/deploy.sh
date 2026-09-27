#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Which use-case apps to deploy. APPS env wins, otherwise it prompts.
# shellcheck source=scripts/lib/select-apps.sh
source "${ROOT_DIR}/scripts/lib/select-apps.sh"
HELM_DIR="${ROOT_DIR}/infra/helm/abenix"
NAMESPACE="${NAMESPACE:-abenix}"
RELEASE_NAME="${RELEASE_NAME:-abenix}"
IMAGE_TAG="${IMAGE_TAG:-$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || echo latest)}"
FRESH="${FRESH:-false}"
# Local ports the browser uses. Override when something else already owns
# 3000/8000 on the host.
WEB_PORT="${WEB_PORT:-3000}"
API_PORT="${API_PORT:-8000}"
# Where the self-restarting port-forward wrappers record their PIDs, so
# they can be stopped without relying on pattern matching.
FORWARD_PIDFILE="${FORWARD_PIDFILE:-${TMPDIR:-/tmp}/abenix-forwards-${NAMESPACE}.pids}"

# ── Load .env for API keys (LLM providers need these for agent execution) ───
if [ -f "${ROOT_DIR}/.env" ]; then
  set -a
  source "${ROOT_DIR}/.env"
  set +a
fi

# Build --set flags for secrets from environment variables
_build_secrets_flags() {
  local flags=""
  [ -n "${ANTHROPIC_API_KEY:-}" ]  && flags="${flags} --set secrets.anthropicApiKey=${ANTHROPIC_API_KEY}"
  [ -n "${CLAUDE_SUBSCRIPTION_TOKEN:-}" ] && flags="${flags} --set secrets.claudeSubscriptionToken=${CLAUDE_SUBSCRIPTION_TOKEN}"
  [ -n "${OPENAI_API_KEY:-}" ]     && flags="${flags} --set secrets.openaiApiKey=${OPENAI_API_KEY}"
  [ -n "${GOOGLE_API_KEY:-}" ]     && flags="${flags} --set secrets.googleApiKey=${GOOGLE_API_KEY}"
  [ -n "${PINECONE_API_KEY:-}" ]   && flags="${flags} --set secrets.pineconeApiKey=${PINECONE_API_KEY}"
  # OracleNet search & data API keys
  [ -n "${TAVILY_API_KEY:-}" ]         && flags="${flags} --set secrets.tavilyApiKey=${TAVILY_API_KEY}"
  [ -n "${BRAVE_SEARCH_API_KEY:-}" ]   && flags="${flags} --set secrets.braveSearchApiKey=${BRAVE_SEARCH_API_KEY}"
  [ -n "${SERPAPI_API_KEY:-}" ]        && flags="${flags} --set secrets.serpapiApiKey=${SERPAPI_API_KEY}"
  [ -n "${SERPER_API_KEY:-}" ]         && flags="${flags} --set secrets.serperApiKey=${SERPER_API_KEY}"
  [ -n "${NEWS_API_KEY:-}" ]           && flags="${flags} --set secrets.newsApiKey=${NEWS_API_KEY}"
  [ -n "${FRED_API_KEY:-}" ]           && flags="${flags} --set secrets.fredApiKey=${FRED_API_KEY}"
  [ -n "${ALPHA_VANTAGE_API_KEY:-}" ]  && flags="${flags} --set secrets.alphaVantageApiKey=${ALPHA_VANTAGE_API_KEY}"
  [ -n "${MEDIASTACK_API_KEY:-}" ]     && flags="${flags} --set secrets.mediastackApiKey=${MEDIASTACK_API_KEY}"
  [ -n "${ENTSOE_API_KEY:-}" ]           && flags="${flags} --set secrets.entsoeApiKey=${ENTSOE_API_KEY}"
  [ -n "${EIA_API_KEY:-}" ]              && flags="${flags} --set secrets.eiaApiKey=${EIA_API_KEY}"
  [ -n "${CONTRACTIQ_JWT_SECRET:-}" ]    && flags="${flags} --set secrets.contractiqJwtSecret=${CONTRACTIQ_JWT_SECRET}"
  echo "${flags}"
}

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${CYAN}[deploy]${NC} $1"; }
ok()   { echo -e "${GREEN}  [ok]${NC} $1"; }
warn() { echo -e "${YELLOW}  [warn]${NC} $1"; }
err()  { echo -e "${RED}  [err]${NC} $1"; }
step() { echo -e "\n${BOLD}${CYAN}>> $1${NC}"; }

usage() {
  echo "Usage: $0 {local|local-runtime|cloud|status|destroy|build|reload <svc>|forwards}"
  echo ""
  echo "Commands:"
  echo "  local          Deploy to minikube — embedded execution (no runtime pod)"
  echo "  local-runtime  Deploy to minikube — separate runtime pod (test prod architecture)"
  echo "  cloud          Deploy to current kubectl context (production, remote runtime)"
  echo "  status         Check deployment health"
  echo "  destroy        Tear down the deployment"
  echo "  build          Build Docker images only"
  echo "  reload <svc>   Rebuild one service and restart it"
  echo "                 core: api web worker agent-runtime edge-runtime"
  echo "                 apps: {contractiq,industrial-iot,resolveai,wingman,mideasttourism,pharmavigil}-{api,web}, claimsiq"
  echo "  forwards       Re-establish and verify all local port forwards"
  echo ""
  echo "Flags:"
  echo "  FRESH=true     Force destroy + recreate minikube from scratch"
  echo "  WEB_PORT=3100  Host port for the web UI (default 3000)"
  echo ""
  echo "The script is incremental — reuses running minikube, only rebuilds changed images."
  exit 1
}

# ── Prereqs ──────────────────────────────────────────────────────────────────
check_command() {
  command -v "$1" &>/dev/null || { err "$1 is required but not found. Install it first."; exit 1; }
}

check_prereqs() {
  check_command kubectl
  check_command helm
  check_command docker
}

# ── Docker health check ─────────────────────────────────────────────────────
wait_for_docker() {
  log "Checking Docker..."
  for i in $(seq 1 30); do
    if docker info &>/dev/null; then
      ok "Docker is ready"
      return 0
    fi
    [ "$i" -eq 1 ] && log "Waiting for Docker to respond..."
    sleep 2
  done
  err "Docker not responding after 60s. Start Docker Desktop and retry."
  exit 1
}

# ── Ensure minikube is running (start only if needed) ────────────────────────
ensure_minikube() {
  local host_status api_status
  host_status=$(minikube status --format='{{.Host}}' 2>/dev/null || echo "Stopped")
  api_status=$(minikube status --format='{{.APIServer}}' 2>/dev/null || echo "Stopped")

  if [ "${host_status}" = "Running" ] && [ "${api_status}" = "Running" ]; then
    ok "Minikube already running (host + apiserver healthy)"
  else
    # If host is running but apiserver is dead, the cluster is broken — delete it
    if [ "${host_status}" = "Running" ] && [ "${api_status}" != "Running" ]; then
      warn "Minikube host is running but apiserver is ${api_status} — cluster is broken"
      log "Deleting broken minikube cluster..."
      minikube delete 2>/dev/null || true
      sleep 3
    fi

    log "Starting minikube (4 CPUs, 8GB RAM, 30GB disk)..."
    wait_for_docker

    local start_log
    start_log=$(mktemp)
    set +e
    minikube start --driver=docker --cpus=4 --memory=8192 --disk-size=30g >"${start_log}" 2>&1
    local rc=$?
    set -e
    tail -5 "${start_log}"
    if [ "${rc}" -ne 0 ]; then
      err "minikube start failed (exit code ${rc}). Full output:"
      sed 's/^/      /' "${start_log}"
      rm -f "${start_log}"
      exit 1
    fi
    rm -f "${start_log}"

    # Verify apiserver came up
    api_status=$(minikube status --format='{{.APIServer}}' 2>/dev/null || echo "Stopped")
    if [ "${api_status}" != "Running" ]; then
      err "Minikube started but apiserver is ${api_status}."
      err "Try: FRESH=true bash scripts/deploy.sh ${1:-local}"
      exit 1
    fi
    ok "Minikube started (apiserver verified)"
  fi

  # Ensure addons (idempotent)
  minikube addons enable ingress &>/dev/null || true
  minikube addons enable metrics-server &>/dev/null || true
  minikube addons enable storage-provisioner &>/dev/null || true
}

# ── KEDA ─────────────────────────────────────────────────────────────────────
# values-local.yaml's `scaling.keda.enabled` comment has always claimed
# "deploy.sh installs it when enabled=true", but no such code existed — so
# flipping that flag produced ScaledObjects with no CRD to satisfy them.
# Mirrors ensure_keda() in scripts/deploy-azure.sh.
ensure_keda() {
  if kubectl get crd scaledobjects.keda.sh &>/dev/null; then
    ok "KEDA CRDs already installed"
    return 0
  fi
  log "Installing KEDA (event-driven autoscaler)..."
  helm repo add kedacore https://kedacore.github.io/charts &>/dev/null || true
  helm repo update &>/dev/null || true
  if helm install keda kedacore/keda \
      --namespace keda --create-namespace \
      --timeout 5m --wait 2>&1 | tail -3; then
    ok "KEDA installed"
  else
    warn "KEDA install failed — ScaledObjects will not be created"
    return 0
  fi
}

# Whether the chart wants KEDA for this deploy.
_keda_requested() {
  local v
  v=$(grep -A3 '^\s*keda:' "${HELM_DIR}/values-local.yaml" 2>/dev/null \
      | grep -m1 'enabled:' | awk '{print $2}' | tr -d '"')
  [ "${KEDA_ENABLED:-${v:-false}}" = "true" ]
}

# ── Pull + tag Bitnami images if not already present ─────────────────────────
ensure_infra_images() {
  eval "$(minikube docker-env)"

  # Only pull if not already present
  # `docker pull ... 2>/dev/null` used to hide auth/not-found failures and the
  # unconditional "ready" below then lied about it. Report per-image instead.
  if ! docker image inspect bitnami/redis:7.2 &>/dev/null; then
    log "Pulling Redis image..."
    if docker pull bitnami/redis:latest 2>&1 | tail -1; then
      docker tag bitnami/redis:latest bitnami/redis:7.2
    else
      warn "bitnami/redis pull failed — Redis will not start"
    fi
  fi
  if ! docker image inspect neo4j:5-community &>/dev/null; then
    log "Pulling Neo4j image..."
    docker pull neo4j:5-community 2>&1 | tail -1 \
      || warn "neo4j:5-community pull failed — Atlas/graph features will be down"
  fi

  # Postgres + pgvector. values.yaml points this at a private ACR, which a
  # laptop cannot pull — local deploys used to sit in ContainerCreating on
  # `your-acr.azurecr.io/postgresql-pgvector` forever. Build the same image
  # locally from the same Dockerfile so minikube gets pgvector too, instead
  # of silently dropping to a vanilla postgres without the extension.
  local pgv="localhost:5000/abenix/postgresql-pgvector:16"
  if ! docker image inspect "${pgv}" &>/dev/null; then
    if [ -f "${ROOT_DIR}/infra/docker/Dockerfile.postgres-pgvector" ]; then
      log "Building postgres+pgvector image (first run only, a few minutes)..."
      # Every COPY in that Dockerfile is --from another stage, so the build
      # context is unused — point it at the small infra/docker dir rather
      # than shipping the whole repo to the daemon.
      if docker build -t "${pgv}" \
          -f "${ROOT_DIR}/infra/docker/Dockerfile.postgres-pgvector" \
          "${ROOT_DIR}/infra/docker" 2>&1 | tail -3; then
        ok "postgresql-pgvector built"
      else
        warn "postgresql-pgvector build failed — KB collections cannot use pgvector locally"
      fi
    else
      warn "infra/docker/Dockerfile.postgres-pgvector missing — skipping pgvector build"
    fi
  fi
  ok "Infrastructure images ready"
}

# ── Build app images (only if code changed) ──────────────────────────────────
# Build one core service image. Shared by build_images and `reload`, so a
# single-service rebuild resolves its Dockerfile and build context exactly
# the same way a full build does.
build_core_service() {
  local svc="$1"
  local registry="${2:-localhost:5000/abenix}"
  local push="${3:-false}"

  local image="${registry}/${svc}:${IMAGE_TAG}"
  local dockerfile="docker/Dockerfile.${svc}"

  [ ! -f "${ROOT_DIR}/${dockerfile}" ] && dockerfile="apps/${svc}/Dockerfile"
  if [ ! -f "${ROOT_DIR}/${dockerfile}" ]; then
    warn "No Dockerfile for ${svc}, skipping"
    return 0
  fi

  # Core images COPY from the repo root. The edge runtimes ship a
  # self-contained Dockerfile that COPYs from its own directory.
  local ctx="${ROOT_DIR}"
  case "${svc}" in
    edge-runtime|edge-runtime-rust|edge-runtime-c) ctx="${ROOT_DIR}/apps/${svc}" ;;
  esac

  log "Building ${svc}..."
  docker build -t "${image}" -t "${registry}/${svc}:latest" \
    -f "${ROOT_DIR}/${dockerfile}" "${ctx}" 2>&1 | tail -3
  ok "${svc}: built"

  if [ "${push}" = "true" ]; then
    docker push "${image}" 2>&1 | tail -1
    ok "${svc}: pushed"
  fi
  return 0
}

build_images() {
  local registry="${1:-localhost:5000/abenix}"
  local push="${2:-false}"

  step "Building Docker images (tag: ${IMAGE_TAG})"
  eval "$(minikube docker-env)" 2>/dev/null || true

  # NOTE: We always rebuild — Docker layer cache makes incremental builds fast,
  # and "skip if exists" caused stale images to ship without new seed YAMLs etc.
  # edge-runtime is included because deploy_local installs its helm chart by
  # default (EDGE_RUNTIME_ENABLED=true). Without building it the chart pulls
  # `agentforge/edge-runtime` from Docker Hub, which does not exist, leaving a
  # permanent ImagePullBackOff pod that also makes wait_for_pods burn its full
  # timeout on every deploy. The loop below falls back to apps/<svc>/Dockerfile.
  local services=("api" "web" "worker" "agent-runtime" "edge-runtime")
  for svc in "${services[@]}"; do
    build_core_service "${svc}" "${registry}" "${push}" || return 1
  done

  # Build ContractIQ standalone images (api + web)
  if [ -d "${ROOT_DIR}/contractiq" ]; then
    step "Building ContractIQ standalone images"
    for ciq in "api" "web"; do
      local ciq_image="${registry}/contractiq-${ciq}:${IMAGE_TAG}"
      local ciq_dockerfile="${ROOT_DIR}/contractiq/${ciq}/Dockerfile"
      [ ! -f "${ciq_dockerfile}" ] && { warn "No Dockerfile for contractiq/${ciq}"; continue; }

      log "Building contractiq-${ciq}..."
      docker build -t "${ciq_image}" -t "${registry}/contractiq-${ciq}:latest" \
        -f "${ciq_dockerfile}" "${ROOT_DIR}/contractiq/${ciq}" 2>&1 | tail -3
      ok "contractiq-${ciq}: built"

      if [ "${push}" = "true" ]; then
        docker push "${ciq_image}" 2>&1 | tail -1
      fi
    done
  fi

  # Build Industrial-IoT standalone images (api + web)
  if [ -d "${ROOT_DIR}/industrial-iot" ]; then
    step "Building Industrial-IoT standalone images"
    for part in "api" "web"; do
      local img="${registry}/industrial-iot-${part}:${IMAGE_TAG}"
      local df="${ROOT_DIR}/industrial-iot/${part}/Dockerfile"
      [ ! -f "${df}" ] && { warn "No Dockerfile for industrial-iot/${part}"; continue; }
      log "Building industrial-iot-${part}..."
      docker build -t "${img}" -t "${registry}/industrial-iot-${part}:latest" \
        -f "${df}" "${ROOT_DIR}/industrial-iot/${part}" 2>&1 | tail -3
      ok "industrial-iot-${part}: built"
      if [ "${push}" = "true" ]; then docker push "${img}" 2>&1 | tail -1; fi
    done
  fi

  # Build ResolveAI standalone images (api + web)
  if [ -d "${ROOT_DIR}/resolveai" ]; then
    step "Building ResolveAI standalone images"
    for part in "api" "web"; do
      local img="${registry}/resolveai-${part}:${IMAGE_TAG}"
      local df="${ROOT_DIR}/resolveai/${part}/Dockerfile"
      [ ! -f "${df}" ] && { warn "No Dockerfile for resolveai/${part}"; continue; }
      log "Building resolveai-${part}..."
      docker build -t "${img}" -t "${registry}/resolveai-${part}:latest" \
        -f "${df}" "${ROOT_DIR}/resolveai/${part}" 2>&1 | tail -3
      ok "resolveai-${part}: built"
      if [ "${push}" = "true" ]; then docker push "${img}" 2>&1 | tail -1; fi
    done
  fi

  # Build PharmaVigil standalone images (api + web)
  if [ -d "${ROOT_DIR}/pharmavigil" ]; then
    step "Building PharmaVigil standalone images"
    for part in "api" "web"; do
      local pv_img="${registry}/pharmavigil-${part}:${IMAGE_TAG}"
      local pv_df="${ROOT_DIR}/pharmavigil/${part}/Dockerfile"
      [ ! -f "${pv_df}" ] && { warn "No Dockerfile for pharmavigil/${part}"; continue; }
      log "Building pharmavigil-${part}..."
      docker build -t "${pv_img}" -t "${registry}/pharmavigil-${part}:latest" \
        -f "${pv_df}" "${ROOT_DIR}/pharmavigil/${part}" 2>&1 | tail -3
      ok "pharmavigil-${part}: built"
      if [ "${push}" = "true" ]; then docker push "${pv_img}" 2>&1 | tail -1; fi
    done
  fi

  # Build Mideast Tourism + Wingman standalone images. Both ship k8s
  # manifests already pointing at localhost:5000/abenix/*, and
  # deploy-azure.sh builds them — the local path just never did, which is
  # why :3002 and :3006 were dead on minikube while working on AKS.
  for app in "mideasttourism" "wingman"; do
    if [ -d "${ROOT_DIR}/${app}" ]; then
      step "Building ${app} standalone images"
      for part in "api" "web"; do
        local simg="${registry}/${app}-${part}:${IMAGE_TAG}"
        local sdf="${ROOT_DIR}/${app}/${part}/Dockerfile"
        [ ! -f "${sdf}" ] && { warn "No Dockerfile for ${app}/${part}"; continue; }
        # Context is usually the part dir, but mideasttourism-api's
        # Dockerfile COPYs `api/...` and `test-data/`, so it needs the app
        # root. Mirrors BUILD_CONTEXTS in scripts/deploy-azure.sh — keep the
        # two in step.
        local sctx="${ROOT_DIR}/${app}/${part}"
        if [ "${app}-${part}" = "mideasttourism-api" ]; then
          sctx="${ROOT_DIR}/${app}"
        fi
        log "Building ${app}-${part}..."
        # Keep the full log: `| tail -3` on a failure shows the tail of a
        # buildkit stack trace rather than the actual cause.
        local slog="${ROOT_DIR}/logs/build-${app}-${part}.log"
        mkdir -p "${ROOT_DIR}/logs"
        if ! docker build -t "${simg}" -t "${registry}/${app}-${part}:latest" \
            -f "${sdf}" "${sctx}" >"${slog}" 2>&1; then
          err "${app}-${part}: build FAILED — last 25 lines:"
          tail -25 "${slog}" | sed 's/^/      /'
          return 1
        fi
        ok "${app}-${part}: built"
        if [ "${push}" = "true" ]; then docker push "${simg}" 2>&1 | tail -1; fi
      done
    fi
  done

  # Build ClaimsIQ single-container image (Spring Boot + Vaadin Flow).
  # One Dockerfile under app/ but the build context must be the claimsiq
  # root so the multi-stage gradle build can see both sdk/ and app/.
  if [ -d "${ROOT_DIR}/claimsiq" ]; then
    step "Building ClaimsIQ container"
    local img="${registry}/claimsiq:${IMAGE_TAG}"
    local df="${ROOT_DIR}/claimsiq/app/Dockerfile"
    if [ ! -f "${df}" ]; then
      warn "No Dockerfile for claimsiq"
    else
      log "Building claimsiq..."
      docker build -t "${img}" -t "${registry}/claimsiq:latest" \
        -f "${df}" "${ROOT_DIR}/claimsiq" 2>&1 | tail -3
      ok "claimsiq: built"
      if [ "${push}" = "true" ]; then docker push "${img}" 2>&1 | tail -1; fi
    fi
  fi

  # Explicit success. Under `set -e` a falsy trailing test (e.g. the
  # push guard above when push=false) would otherwise become this
  # function's return status and abort the whole deploy after the images
  # were built but before helm ran.
  return 0
}

# ── Deploy ContractIQ as k8s manifests (after Abenix is running) ─────────
deploy_contractiq() {
  if [ ! -f "${ROOT_DIR}/contractiq/k8s/contractiq.yaml" ]; then
    warn "ContractIQ k8s manifests not found, skipping"
    return 0
  fi

  step "Deploying ContractIQ to namespace ${NAMESPACE}"

  # Inject secrets from .env if available
  local ciq_key="${CONTRACTIQ_ABENIX_API_KEY:-}"
  local ciq_jwt="${CONTRACTIQ_JWT_SECRET:-contractiq-dev-secret-please-change}"
  local anth_key="${ANTHROPIC_API_KEY:-}"

  if [ -z "${ciq_key}" ]; then
    warn "CONTRACTIQ_ABENIX_API_KEY not set — chat will fail until you set it"
  fi

  # Apply manifests with secret substitution
  sed \
    -e "s|REPLACE_AT_DEPLOY_TIME|placeholder|g" \
    "${ROOT_DIR}/contractiq/k8s/contractiq.yaml" | kubectl apply -f - 2>&1 | tail -10

  # Update secret with real values (use --dry-run to generate, then apply)
  kubectl create secret generic contractiq-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=CONTRACTIQ_ABENIX_API_KEY="${ciq_key}" \
    --from-literal=CONTRACTIQ_JWT_SECRET="${ciq_jwt}" \
    --from-literal=ANTHROPIC_API_KEY="${anth_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -3

  ok "ContractIQ deployed"

  # Wait for pods to be ready
  log "Waiting for ContractIQ pods to be ready..."
  kubectl wait --for=condition=ready pod -l app=contractiq-api \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "ContractIQ API not ready in 120s"
  kubectl wait --for=condition=ready pod -l app=contractiq-web \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "ContractIQ Web not ready in 120s"
}

# ── Deploy Industrial-IoT standalone ─────────────────────────────────────────
deploy_industrial_iot() {
  if [ ! -f "${ROOT_DIR}/industrial-iot/k8s/industrial-iot.yaml" ]; then
    warn "Industrial-IoT k8s manifests not found, skipping"
    return 0
  fi
  step "Deploying Industrial-IoT to namespace ${NAMESPACE}"
  local iot_key="${INDUSTRIALIOT_ABENIX_API_KEY:-}"
  [ -z "${iot_key}" ] && warn "INDUSTRIALIOT_ABENIX_API_KEY not set — pipeline calls will 503"

  # Web-tier shared secret that gates the standalone API's proxy
  # passthroughs (/api/code-assets, /api/agents, /api/connectors). Reuse
  # the existing value if the secret is already in the cluster so a
  # rolling deploy doesn't break in-flight web pods; mint a fresh UUID
  # otherwise.
  local iot_web_secret
  iot_web_secret=$(kubectl get secret industrial-iot-secrets -n "${NAMESPACE}" \
    -o jsonpath='{.data.INDUSTRIALIOT_WEB_PROXY_SECRET}' 2>/dev/null | base64 -d 2>/dev/null)
  # Reject the manifest's REPLACE_AT_DEPLOY_TIME placeholder so a real UUID
  # is minted instead of re-using the shipped sentinel value.
  if [ -z "${iot_web_secret}" ] || [ "${iot_web_secret}" = "REPLACE_AT_DEPLOY_TIME" ]; then
    iot_web_secret=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || python3 -c 'import uuid;print(uuid.uuid4())')
  fi

  kubectl apply -f "${ROOT_DIR}/industrial-iot/k8s/industrial-iot.yaml" 2>&1 | tail -10
  kubectl create secret generic industrial-iot-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=INDUSTRIALIOT_ABENIX_API_KEY="${iot_key}" \
    --from-literal=INDUSTRIALIOT_WEB_PROXY_SECRET="${iot_web_secret}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -3
  ok "Industrial-IoT deployed"

  kubectl wait --for=condition=ready pod -l app=industrial-iot-api \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "Industrial-IoT API not ready in 120s"
  kubectl wait --for=condition=ready pod -l app=industrial-iot-web \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "Industrial-IoT Web not ready in 120s"
}

# ── Deploy ResolveAI standalone ──────────────────────────────────────────────
deploy_resolveai() {
  if [ ! -f "${ROOT_DIR}/resolveai/k8s/resolveai.yaml" ]; then
    warn "ResolveAI k8s manifests not found, skipping"
    return 0
  fi
  step "Deploying ResolveAI to namespace ${NAMESPACE}"
  local ra_key="${RESOLVEAI_ABENIX_API_KEY:-}"
  [ -z "${ra_key}" ] && warn "RESOLVEAI_ABENIX_API_KEY not set — pipeline calls will 503"

  kubectl apply -f "${ROOT_DIR}/resolveai/k8s/resolveai.yaml" 2>&1 | tail -10
  kubectl create secret generic resolveai-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=RESOLVEAI_ABENIX_API_KEY="${ra_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -3
  ok "ResolveAI deployed"

  kubectl wait --for=condition=ready pod -l app=resolveai-api \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "ResolveAI API not ready in 120s"
  kubectl wait --for=condition=ready pod -l app=resolveai-web \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "ResolveAI Web not ready in 120s"
}

# ── Deploy PharmaVigil standalone ────────────────────────────────────────────
deploy_pharmavigil() {
  if [ ! -f "${ROOT_DIR}/pharmavigil/k8s/pharmavigil.yaml" ]; then
    warn "PharmaVigil k8s manifests not found, skipping"
    return 0
  fi
  step "Deploying PharmaVigil to namespace ${NAMESPACE}"
  local pv_key="${PHARMAVIGIL_ABENIX_API_KEY:-}"
  [ -z "${pv_key}" ] && warn "PHARMAVIGIL_ABENIX_API_KEY not set — assessments will 401"

  kubectl apply -f "${ROOT_DIR}/pharmavigil/k8s/pharmavigil.yaml" 2>&1 | tail -10
  kubectl create secret generic pharmavigil-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=PHARMAVIGIL_ABENIX_API_KEY="${pv_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -3
  ok "PharmaVigil deployed"

  kubectl wait --for=condition=ready pod -l app=pharmavigil-api \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "PharmaVigil API not ready in 120s"
  kubectl wait --for=condition=ready pod -l app=pharmavigil-web \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "PharmaVigil Web not ready in 120s"
}

# ── Deploy Mideast Tourism standalone ────────────────────────────────────────
deploy_mideasttourism() {
  if [ ! -f "${ROOT_DIR}/mideasttourism/k8s/mideasttourism.yaml" ]; then
    warn "Mideast Tourism k8s manifests not found, skipping"
    return 0
  fi
  step "Deploying Mideast Tourism to namespace ${NAMESPACE}"
  local st_key="${MIDEASTTOURISM_ABENIX_API_KEY:-}"
  [ -z "${st_key}" ] && warn "MIDEASTTOURISM_ABENIX_API_KEY not set — agent calls will 401"

  kubectl apply -f "${ROOT_DIR}/mideasttourism/k8s/mideasttourism.yaml" 2>&1 | tail -10
  kubectl create secret generic mideasttourism-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=MIDEASTTOURISM_ABENIX_API_KEY="${st_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -3
  # envFrom secrets are only read at pod start, so a freshly patched key
  # needs a restart or the pod keeps the manifest placeholder.
  kubectl -n "${NAMESPACE}" rollout restart deploy/mideasttourism-api &>/dev/null || true
  kubectl -n "${NAMESPACE}" rollout restart deploy/mideasttourism-web &>/dev/null || true
  ok "Mideast Tourism deployed"

  kubectl wait --for=condition=ready pod -l app=mideasttourism-api \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "Mideast Tourism API not ready in 120s"
  kubectl wait --for=condition=ready pod -l app=mideasttourism-web \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "Mideast Tourism Web not ready in 120s"
}

# ── Deploy Wingman standalone ────────────────────────────────────────────────
deploy_wingman() {
  if [ ! -f "${ROOT_DIR}/wingman/k8s/wingman.yaml" ]; then
    warn "Wingman k8s manifests not found, skipping"
    return 0
  fi
  step "Deploying Wingman to namespace ${NAMESPACE}"
  local wm_key="${WINGMAN_ABENIX_API_KEY:-}"
  [ -z "${wm_key}" ] && warn "WINGMAN_ABENIX_API_KEY not set — agent calls will 401"
  # Live AIS is optional; the rest of Wingman runs without it.
  local ais_key="${AISSTREAM_API_KEY:-}"
  [ -z "${ais_key}" ] && warn "AISSTREAM_API_KEY not set — Operations Watch live-AIS disabled"

  kubectl apply -f "${ROOT_DIR}/wingman/k8s/wingman.yaml" 2>&1 | tail -10
  kubectl create secret generic wingman-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=WINGMAN_ABENIX_API_KEY="${wm_key}" \
    --from-literal=AISSTREAM_API_KEY="${ais_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -3
  kubectl -n "${NAMESPACE}" rollout restart deploy/wingman-api &>/dev/null || true
  kubectl -n "${NAMESPACE}" rollout restart deploy/wingman-web &>/dev/null || true
  ok "Wingman deployed"

  kubectl wait --for=condition=ready pod -l app=wingman-api \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "Wingman API not ready in 120s"
  kubectl wait --for=condition=ready pod -l app=wingman-web \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "Wingman Web not ready in 120s"
}

# ── Deploy ClaimsIQ standalone (Spring Boot + Vaadin, single container) ──────
deploy_claimsiq() {
  if [ ! -f "${ROOT_DIR}/claimsiq/k8s/claimsiq.yaml" ]; then
    warn "ClaimsIQ k8s manifest not found, skipping"
    return 0
  fi
  step "Deploying ClaimsIQ to namespace ${NAMESPACE}"
  local cq_key="${CLAIMSIQ_ABENIX_API_KEY:-}"
  [ -z "${cq_key}" ] && warn "CLAIMSIQ_ABENIX_API_KEY not set — pipeline calls will 401"

  kubectl apply -f "${ROOT_DIR}/claimsiq/k8s/claimsiq.yaml" 2>&1 | tail -10
  kubectl create secret generic claimsiq-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=CLAIMSIQ_ABENIX_API_KEY="${cq_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -3
  ok "ClaimsIQ deployed"

  # JVM cold start — 240s matches deploy-azure.sh; fast enough to avoid
  # masking real failures but slow enough to accommodate a first-run
  # Vaadin frontend bundle explode.
  kubectl wait --for=condition=ready pod -l app=claimsiq \
    --namespace="${NAMESPACE}" --timeout=240s 2>&1 | tail -3 || warn "ClaimsIQ not ready in 240s"
}

# ── Helm dependency update ───────────────────────────────────────────────────
helm_deps() {
  step "Updating Helm dependencies"
  # postgresql and redis come from bitnami. Without the repo registered,
  # `helm dependency update` fails with "no repository definition for
  # https://charts.bitnami.com/bitnami" — which only shows up on a machine
  # that has never added it, so it never bit anyone who had run helm before.
  if ! helm repo list 2>/dev/null | awk '{print $2}' | grep -q "charts.bitnami.com/bitnami"; then
    log "Registering the bitnami chart repo (postgresql + redis)"
    helm repo add bitnami https://charts.bitnami.com/bitnami &>/dev/null || true
  fi
  helm repo update &>/dev/null || true
  helm dependency update "${HELM_DIR}" 2>&1 | tail -2
  ok "Helm dependencies ready"
}

# ── Wait for pods ────────────────────────────────────────────────────────────
wait_for_pods() {
  local timeout="${1:-300}"
  step "Waiting for pods to be ready (timeout: ${timeout}s)"

  local start=$SECONDS
  while true; do
    local not_ready total_pods
    not_ready=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | grep -cv "Running\|Completed" || echo 0)
    not_ready=$(echo "${not_ready}" | tr -d '[:space:]')
    total_pods=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | wc -l)
    total_pods=$(echo "${total_pods}" | tr -d '[:space:]')
    local elapsed=$((SECONDS - start))

    if [ "${not_ready}" -eq 0 ] && [ "${total_pods}" -gt 0 ]; then
      ok "All pods are running"
      return 0
    fi

    if [ "${elapsed}" -ge "${timeout}" ]; then
      warn "Some pods not ready after ${timeout}s:"
      kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | grep -v "Running\|Completed" | sed 's/^/      /'
      return 1
    fi

    log "Waiting... (${not_ready} pods not ready, $((timeout - elapsed))s remaining)"
    sleep 10
  done
}

# ── Generate persistent JWT keys ────────────────────────────────────────────
ensure_jwt_keys() {
  # Check if JWT keys already exist in the secret
  local existing
  existing=$(kubectl get secret abenix-secrets -n "${NAMESPACE}" -o jsonpath='{.data.JWT_PRIVATE_KEY}' 2>/dev/null || echo "")
  if [ -n "${existing}" ] && [ "${existing}" != "" ]; then
    return 0
  fi

  log "Generating persistent RSA key pair for JWT..."
  local privkey pubkey
  privkey=$(openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 2>/dev/null)
  pubkey=$(echo "${privkey}" | openssl rsa -pubout 2>/dev/null)

  if [ -z "${privkey}" ] || [ -z "${pubkey}" ]; then
    warn "Could not generate JWT keys (openssl not available) — tokens won't survive pod restarts"
    return 0
  fi

  # Patch the secret with the key pair.
  # Use `base64 | tr -d '\n'` for cross-platform compatibility (macOS base64
  # has no -w flag; Linux base64 -w0 disables wrapping but macOS doesn't wrap
  # by default; tr ensures no newlines on either platform).
  local privkey_b64 pubkey_b64
  privkey_b64=$(printf '%s' "${privkey}" | base64 | tr -d '\n')
  pubkey_b64=$(printf '%s' "${pubkey}" | base64 | tr -d '\n')
  kubectl patch secret abenix-secrets -n "${NAMESPACE}" --type='json' \
    -p="[
      {\"op\":\"add\",\"path\":\"/data/JWT_PRIVATE_KEY\",\"value\":\"${privkey_b64}\"},
      {\"op\":\"add\",\"path\":\"/data/JWT_PUBLIC_KEY\",\"value\":\"${pubkey_b64}\"}
    ]" &>/dev/null || true

  ok "JWT keys generated and stored in secret"
}

# ── Database init ────────────────────────────────────────────────────────────
run_migrations() {
  step "Ensuring database and tables"
  local pg_pod
  pg_pod=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=postgresql" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [ -n "${pg_pod}" ]; then
    # `kubectl get` returns a pod NAME even when that pod is Pending or in
    # ImagePullBackOff, so don't announce success on the strength of the
    # lookup — report what the exec actually did. This previously printed
    # "Database ready" while Postgres had never started.
    if kubectl exec -n "${NAMESPACE}" "${pg_pod}" -- \
        bash -c 'PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = '"'"'abenix'"'"'" | grep -q 1 || PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -c "CREATE DATABASE abenix"' &>/dev/null; then
      ok "Database ready"
    else
      warn "Could not reach Postgres in ${pg_pod} — schema steps below will be skipped"
      return 0
    fi
  else
    warn "No Postgres pod found — skipping schema steps"
    return 0
  fi

  # Restart API to trigger table auto-creation
  kubectl -n "${NAMESPACE}" rollout restart deployment -l "app.kubernetes.io/name=api" &>/dev/null || true
  log "Waiting for API pod to be ready after restart..."
  kubectl -n "${NAMESPACE}" rollout status deployment -l "app.kubernetes.io/name=api" --timeout=120s 2>/dev/null || true
  ok "Tables created via API startup"

  # Alembic. `create_all` at API startup only adds MISSING TABLES — it never
  # alters an existing one and it never inserts the seed rows migrations
  # carry (the llm_model_pricing catalogue that feeds every model picker is
  # migration-seeded, so without this the dropdowns fall back to a hardcoded
  # list). deploy-azure.sh has always run this; the local path had not,
  # which is how minikube drifted from prod.
  local api_pod=""
  for _ in $(seq 1 30); do
    api_pod=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=api" \
      --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    [ -n "${api_pod}" ] && break
    sleep 3
  done
  if [ -z "${api_pod}" ]; then
    warn "No running API pod — skipping alembic"
    return 0
  fi

  log "Bootstrapping schema (no-op if alembic_version exists)..."
  kubectl exec -n "${NAMESPACE}" "${api_pod}" -- \
    bash -c 'cd /app/packages/db && python -m bootstrap' 2>&1 | tail -3 || true

  # `heads` (plural): this repo has independent migration branches, and
  # singular `head` errors with "Multiple head revisions are present".
  log "Running alembic upgrade heads..."
  kubectl exec -n "${NAMESPACE}" "${api_pod}" -- \
    bash -c 'cd /app/packages/db && python -m alembic upgrade heads' 2>&1 | tail -5 || true

  # Don't trust the swallowed exit code above — assert the catalogue landed.
  # Counted straight from Postgres so no Python quoting is involved.
  local catalogue=""
  if [ -n "${pg_pod}" ]; then
    catalogue=$(kubectl exec -n "${NAMESPACE}" "${pg_pod}" -- bash -c \
      'PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -d abenix -tAc "SELECT count(*) FROM llm_model_pricing WHERE is_active"' \
      2>/dev/null | tr -d '[:space:]')
  fi
  if [ -n "${catalogue}" ] && [ "${catalogue}" -gt 0 ] 2>/dev/null; then
    ok "Migrations applied — ${catalogue} models in the pricing catalogue"
  else
    warn "Model pricing catalogue is empty after alembic — every model picker will fall back to its hardcoded list"
  fi
}

# ── Seed agents ──────────────────────────────────────────────────────────────
seed_agents() {
  step "Seeding agents and accounts"

  # Wait for a Ready API pod (init containers + startup probe must pass)
  local api_pod=""
  for i in $(seq 1 30); do
    api_pod=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=api" \
      --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -n "${api_pod}" ]; then
      # Verify the pod is actually ready (not just Running)
      local ready
      ready=$(kubectl get pod "${api_pod}" -n "${NAMESPACE}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)
      if [ "${ready}" = "True" ]; then
        break
      fi
    fi
    sleep 3
  done

  if [ -z "${api_pod}" ]; then
    warn "No ready API pod found — skipping seeding"
    return
  fi

  log "Seeding via pod ${api_pod}..."
  local failed_seeds=""
  # Order matters: seed_kb grants collections to agents by slug, so it has to
  # follow seed_agents.
  #
  # Keep this list in step with the one in deploy-azure.sh. It had drifted two
  # short — no seed_code_assets and no seed_atlas — so a local cluster came up
  # with an empty Atlas and nothing to explain why, while Azure looked fine.
  for seed in seed_agents seed_users seed_portfolio_schemas seed_ml_models \
              seed_code_assets seed_kb seed_atlas; do
    run_seed "${seed}" || failed_seeds="${failed_seeds} ${seed}"
  done

  if [ -n "${failed_seeds}" ]; then
    err "Seeding FAILED for:${failed_seeds}"
    err "The platform will be missing data those seeds provide. seed_users is the"
    err "one that creates admin@abenix.dev — without it you cannot sign in."
    err "Re-run with: bash scripts/deploy.sh local"
    return 1
  fi
  ok "Seeding complete"
}

# Run one seed script inside a ready API pod.
#
# The pod is resolved per call rather than once for the whole batch. A rollout
# part-way through the batch used to kill the exec with code 137 and leave every
# later seed hitting a pod name that no longer existed, all swallowed by
# `|| true`. One retry covers a restart landing mid-seed.
run_seed() {
  local script="$1"
  local attempt
  for attempt in 1 2; do
    local pod=""
    local i
    for i in $(seq 1 40); do
      pod=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=api" \
        --field-selector=status.phase=Running \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
      if [ -n "${pod}" ] && [ "$(kubectl get pod "${pod}" -n "${NAMESPACE}" \
          -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)" = "True" ]; then
        break
      fi
      pod=""
      sleep 3
    done
    if [ -z "${pod}" ]; then
      warn "  ${script}: no ready API pod (attempt ${attempt})"
      continue
    fi
    # bash -c keeps MSYS from mangling /app paths on Windows.
    if kubectl exec -n "${NAMESPACE}" "${pod}" -- \
        bash -c "python /app/packages/db/seeds/${script}.py" 2>&1 | tail -5; then
      ok "  ${script}"
      return 0
    fi
    warn "  ${script}: failed on ${pod} (attempt ${attempt}), re-resolving pod"
    sleep 5
  done
  return 1
}

deploy_livekit() {
  step "Deploying in-cluster LiveKit (Meeting Representative backend)"

  local manifest="${ROOT_DIR}/infra/k8s/livekit-dev.yaml"
  if [ ! -f "${manifest}" ]; then
    warn "${manifest} not found — skipping LiveKit deploy"
    return 0
  fi
  kubectl apply -f "${manifest}" -n "${NAMESPACE}" 2>&1 | tail -5

  # Wait for it to be ready
  log "Waiting for LiveKit pod..."
  kubectl -n "${NAMESPACE}" rollout status deploy/livekit-server --timeout=120s 2>&1 | tail -2 || true

  # Wire env vars on the API. Honor an existing LIVEKIT_URL override
  # (e.g. operator already set it to LiveKit Cloud) — only inject the
  # in-cluster default when it's missing/empty.
  local existing_url
  existing_url=$(kubectl -n "${NAMESPACE}" get deploy/abenix-api \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LIVEKIT_URL")].value}' 2>/dev/null)
  if [ -z "${existing_url}" ] || [ "${existing_url}" = "null" ]; then
    log "Setting LIVEKIT_URL=ws://livekit-server.${NAMESPACE}.svc.cluster.local:7880"
    kubectl -n "${NAMESPACE}" set env deploy/abenix-api \
      LIVEKIT_URL="ws://livekit-server.${NAMESPACE}.svc.cluster.local:7880" \
      LIVEKIT_API_KEY=devkey \
      LIVEKIT_API_SECRET=secret \
      LIVEKIT_PUBLIC_URL="ws://localhost:7880" \
      LIVEKIT_MEET_URL="https://meet.livekit.io" \
      2>&1 | tail -2
    log "Rolling API to pick up LiveKit env..."
    kubectl -n "${NAMESPACE}" rollout status deploy/abenix-api --timeout=180s 2>&1 | tail -2 || true
  else
    log "LIVEKIT_URL already set on the deployment (${existing_url}) — leaving it alone"
  fi
  ok "LiveKit ready: in-cluster signaling at livekit-server:7880, browser via NodePort 30880 (port-forward to :7880)"
}

# ── Port forwarding ──────────────────────────────────────────────────────────
# Kill every port forward for this namespace, wrapper loops included, and
# verify they are gone. `pkill` on the kubectl child alone is not enough: the
# `while true` wrapper simply starts another one.
kill_port_forwards() {
  local killed=0

  # Wrapper loops first, by recorded PID. Killing the kubectl child alone is
  # useless: the wrapper restarts it two seconds later.
  if [ -f "${FORWARD_PIDFILE}" ]; then
    while read -r pid; do
      [ -z "${pid}" ] && continue
      if kill "${pid}" 2>/dev/null; then
        killed=$((killed + 1))
      fi
    done < "${FORWARD_PIDFILE}"
    : > "${FORWARD_PIDFILE}"
  fi

  # Then the kubectl children those wrappers spawned, and anything a previous
  # run left behind. MSYS pkill/pgrep cannot see these detached processes at
  # all, so on Windows ask PowerShell, which can read their command lines.
  local orphan
  for orphan in $(ps -ef 2>/dev/null | awk '/kubectl/ && /port-forward/ {print $2}'); do
    kill "${orphan}" 2>/dev/null || true
  done
  pkill -f "kubectl port-forward.*${NAMESPACE}" 2>/dev/null || true
  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command "
      Get-CimInstance Win32_Process -Filter \"Name='bash.exe' OR Name='kubectl.exe'\" |
        Where-Object { \$_.CommandLine -like '*port-forward*' -and \$_.CommandLine -like '*${NAMESPACE}*' } |
        ForEach-Object { try { Stop-Process -Id \$_.ProcessId -Force -ErrorAction Stop } catch {} }
    " >/dev/null 2>&1 || true
  fi
  sleep 2
  [ "${killed}" -gt 0 ] && log "stopped ${killed} port-forward wrapper(s)"
  return 0
}

# Name whatever already holds a port, so a clash reads as a clash.
port_squatter() {
  local port="$1" hit=""
  hit=$(docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null \
    | grep -E ":${port}->" | head -1 | cut -f1)
  if [ -n "${hit}" ]; then
    echo "docker container '${hit}'"
    return 0
  fi
  echo "an unknown process"
}

# Start a self-restarting port forward that reconnects if the connection drops
start_persistent_forward() {
  local svc="$1" local_port="$2" remote_port="$3"
  local ns="${NAMESPACE}"
  # A busy port makes kubectl exit immediately and the wrapper spin for ever,
  # while something else answers on the port. That looked healthy to the
  # verifier and served a different app's 404s to every test.
  if curl -s -o /dev/null --max-time 2 "http://localhost:${local_port}/" 2>/dev/null; then
    err "port ${local_port} is already taken by $(port_squatter "${local_port}") — ${svc} will NOT be forwarded"
    err "  free it, or re-run with a different port (WEB_PORT / API_PORT)"
    return 1
  fi
  nohup bash -c "echo \$\$ >> '${FORWARD_PIDFILE}'; while true; do kubectl port-forward -n ${ns} svc/${svc} ${local_port}:${remote_port} 2>/dev/null; sleep 2; done" &>/dev/null &
}

setup_port_forwards() {
  local with_runtime="${1:-false}"
  step "Setting up port forwarding"

  # Kill any existing port forwards from previous runs, wrappers included.
  kill_port_forwards

  # Start persistent (auto-reconnecting) port forwards
  start_persistent_forward "${RELEASE_NAME}-web" "${WEB_PORT}" 3000 || true
  start_persistent_forward "${RELEASE_NAME}-api" "${API_PORT}" 8000 || true
  start_persistent_forward "${RELEASE_NAME}-neo4j" 7474 7474 || true

  # Standalone apps — each on its own port so the Use Cases dropdown
  # in the core UI can deep-link to them at localhost:<port>.
  if kubectl -n "${NAMESPACE}" get svc contractiq-web &>/dev/null; then
    start_persistent_forward "contractiq-web" 3001 3001 || true
    start_persistent_forward "contractiq-api" 8001 8001 || true
  fi
  if kubectl -n "${NAMESPACE}" get svc mideasttourism-web &>/dev/null; then
    start_persistent_forward "mideasttourism-web" 3002 3002 || true
    start_persistent_forward "mideasttourism-api" 8002 8002 || true
  fi
  if kubectl -n "${NAMESPACE}" get svc industrial-iot-web &>/dev/null; then
    start_persistent_forward "industrial-iot-web" 3003 3003 || true
    start_persistent_forward "industrial-iot-api" 8003 8003 || true
  fi
  if kubectl -n "${NAMESPACE}" get svc resolveai-web &>/dev/null; then
    start_persistent_forward "resolveai-web" 3004 3004 || true
    start_persistent_forward "resolveai-api" 8004 8004 || true
  fi
  if kubectl -n "${NAMESPACE}" get svc wingman-web &>/dev/null; then
    start_persistent_forward "wingman-web" 3006 3006 || true
    start_persistent_forward "wingman-api" 8006 8006 || true
  fi
  if kubectl -n "${NAMESPACE}" get svc pharmavigil-web &>/dev/null; then
    start_persistent_forward "pharmavigil-web" 3007 3007 || true
    start_persistent_forward "pharmavigil-api" 8007 8007 || true
  fi
  # ClaimsIQ is a single Spring Boot + Vaadin container — no api/web split.
  if kubectl -n "${NAMESPACE}" get svc claimsiq &>/dev/null; then
    start_persistent_forward "claimsiq" 3005 3005 || true
  fi

  # LiveKit signaling — enables the browser to connect to in-cluster
  # LiveKit at ws://localhost:7880 (matches LIVEKIT_PUBLIC_URL).
  if kubectl -n "${NAMESPACE}" get svc livekit-server &>/dev/null; then
    start_persistent_forward "livekit-server" 7880 7880 || true
  fi

  # Observability. These used to be started only by the observability deploy
  # step, with a bare nohup outside the managed set, so kill_port_forwards
  # killed them and nothing ever brought them back.
  if kubectl -n "${NAMESPACE}" get svc "${RELEASE_NAME}-prometheus" &>/dev/null; then
    start_persistent_forward "${RELEASE_NAME}-prometheus" 9090 9090 || true
  fi
  if kubectl -n "${NAMESPACE}" get svc "${RELEASE_NAME}-grafana" &>/dev/null; then
    start_persistent_forward "${RELEASE_NAME}-grafana" 3030 3000 || true
  fi

  if [ "${with_runtime}" = "true" ]; then
    start_persistent_forward "${RELEASE_NAME}-agent-runtime" 8001 8001 || true
  fi

  # Wait for services to be reachable
  log "Waiting for services to be reachable..."
  local ready=false
  for i in $(seq 1 30); do
    local api_ok=false web_ok=false
    curl -sf --max-time 3 http://localhost:8000/api/health >/dev/null 2>&1 && api_ok=true
    curl -sf --max-time 3 http://localhost:3000 -o /dev/null 2>&1 && web_ok=true

    if [ "${api_ok}" = true ] && [ "${web_ok}" = true ]; then
      ready=true
      break
    fi
    sleep 2
  done

  if [ "${ready}" = true ]; then
    if [ "${with_runtime}" = "true" ]; then
      ok "All services reachable — ports: ${WEB_PORT} (web), ${API_PORT} (api), 8001 (runtime), 7474 (neo4j)"
    else
      ok "All services reachable — ports: ${WEB_PORT} (web), ${API_PORT} (api), 7474 (neo4j)"
    fi
  else
    warn "Some services may not be reachable yet — port forwards are running in background"
    if [ "${with_runtime}" = "true" ]; then
      warn "Ports: 3000 (web), 8000 (api), 8001 (runtime), 7474 (neo4j)"
    else
      warn "Ports: 3000 (web), 8000 (api), 7474 (neo4j)"
    fi
  fi
}

# LOCAL — Minikube with embedded execution (no runtime pod)
# Observability stack — Prometheus + Grafana + auto-loaded dashboards.
# Idempotent: re-runs are safe and refresh the dashboards if their JSON
# changed on disk.
install_observability_stack() {
  log "Installing observability stack (Prometheus + Grafana)..."
  local manifests_dir
  manifests_dir="$(dirname "$0")/../infra/observability"

  if [[ ! -f "${manifests_dir}/prometheus.yaml" ]]; then
    warn "infra/observability/ not found, skipping observability stack"
    return 0
  fi

  # Ensure the namespace exists (deploy_local creates it, but this also
  # works if someone calls install_observability_stack standalone).
  kubectl get namespace "${NAMESPACE}" &>/dev/null \
    || kubectl create namespace "${NAMESPACE}"

  # Bake every dashboard JSON in infra/observability/dashboards/ into a
  # single ConfigMap. --dry-run|apply gives idempotency: existing keys
  # get replaced, new dashboards appear in Grafana within ~30s.
  if compgen -G "${manifests_dir}/dashboards/*.json" >/dev/null; then
    local kc_args=()
    for f in "${manifests_dir}"/dashboards/*.json; do
      kc_args+=(--from-file="$(basename "$f")=$f")
    done
    kubectl create configmap abenix-grafana-dashboards \
      -n "${NAMESPACE}" "${kc_args[@]}" \
      --dry-run=client -o yaml | kubectl apply -f -
    ok "Loaded $(ls "${manifests_dir}"/dashboards/*.json | wc -l | tr -d ' ') dashboard(s) into Grafana ConfigMap"
  fi

  kubectl apply -f "${manifests_dir}/prometheus.yaml" -n "${NAMESPACE}" >/dev/null
  kubectl apply -f "${manifests_dir}/grafana.yaml"    -n "${NAMESPACE}" >/dev/null

  # Roll Grafana so it picks up the latest dashboard ConfigMap. The
  # provisioner sidecar polls every 30s but a rollout makes the change
  # visible immediately, which is what operators expect right after
  # `deploy.sh local`.
  kubectl rollout restart deployment/abenix-grafana -n "${NAMESPACE}" >/dev/null 2>&1 || true

  kubectl wait --for=condition=Available --timeout=120s \
    deployment/abenix-prometheus -n "${NAMESPACE}" 2>/dev/null \
    && ok "Prometheus ready" \
    || warn "Prometheus did not become Available within 120s; check logs"

  kubectl wait --for=condition=Available --timeout=120s \
    deployment/abenix-grafana -n "${NAMESPACE}" 2>/dev/null \
    && ok "Grafana ready" \
    || warn "Grafana did not become Available within 120s; check logs"

  # Managed forwards, so `deploy.sh forwards` restores them like every other.
  start_persistent_forward "${RELEASE_NAME}-prometheus" 9090 9090 || true
  start_persistent_forward "${RELEASE_NAME}-grafana" 3030 3000 || true
  sleep 1
  ok "Observability port forwards: prometheus→9090, grafana→3030"
}


deploy_edge_runtime_rust() {
  step "Installing edge runtime (rust, gateway.id=${EDGE_GATEWAY_ID:-edge-cluster-default})"
  helm upgrade --install abenix-edge-rust "${ROOT_DIR}/infra/helm/edge-runtime-rust" \
    --namespace "${NAMESPACE}" \
    --set image.tag="${IMAGE_TAG}" \
    --set gateway_id="${EDGE_GATEWAY_ID:-edge-cluster-default}-rust" \
    --set gateway_name="${EDGE_GATEWAY_NAME:-edge-cluster-default}-rust" \
    --set platform_url="http://${RELEASE_NAME}-api.${NAMESPACE}.svc.cluster.local:8000" \
    --set mqtt_url="mqtt://abenix-mosquitto.${NAMESPACE}.svc.cluster.local:1883" \
    --set anthropic_api_key="${ANTHROPIC_API_KEY:-}" \
    --timeout 5m --wait=false 2>&1 | tail -3 \
    || warn "edge-runtime-rust helm install failed (non-fatal)"
  ok "edge-runtime-rust installed"
}

deploy_edge_runtime_c() {
  step "Installing edge runtime (c, gateway.id=${EDGE_GATEWAY_ID:-edge-cluster-default})"
  helm upgrade --install abenix-edge-c "${ROOT_DIR}/infra/helm/edge-runtime-c" \
    --namespace "${NAMESPACE}" \
    --set image.tag="${IMAGE_TAG}" \
    --set gateway_id="${EDGE_GATEWAY_ID:-edge-cluster-default}-c" \
    --set gateway_name="${EDGE_GATEWAY_NAME:-edge-cluster-default}-c" \
    --set platform_url="http://${RELEASE_NAME}-api.${NAMESPACE}.svc.cluster.local:8000" \
    --set mqtt_url="mqtt://abenix-mosquitto.${NAMESPACE}.svc.cluster.local:1883" \
    --set anthropic_api_key="${ANTHROPIC_API_KEY:-}" \
    --timeout 5m --wait=false 2>&1 | tail -3 \
    || warn "edge-runtime-c helm install failed (non-fatal)"
  ok "edge-runtime-c installed"
}


deploy_local() {
  check_prereqs
  check_command minikube

  # Ask before the long build, not after it.
  select_apps
  log "Use-case apps: $(describe_selection)"

  step "Deploying Abenix to minikube (embedded mode)"

  # Force fresh if requested
  if [ "${FRESH}" = "true" ]; then
    log "FRESH=true — destroying existing minikube..."
    minikube delete --purge 2>/dev/null || true
    log "Waiting for Docker to recover after minikube purge..."
    sleep 5
    wait_for_docker
  fi

  ensure_minikube
  ensure_infra_images
  build_images "localhost:5000/abenix" "false"

  # Create namespace (idempotent)
  kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f - &>/dev/null
  # KEDA must exist before helm renders ScaledObjects.
  if _keda_requested; then
    ensure_keda
  fi
  helm_deps

  # MQTT broker + TimescaleDB — required by v1.1 production tooling
  step "Installing mosquitto + timescaledb (v1.1 streaming + tsdb infra)"
  helm upgrade --install abenix-mosquitto "${ROOT_DIR}/infra/helm/mosquitto" \
    --namespace "${NAMESPACE}" --timeout 5m --wait=false 2>&1 | tail -3 \
    || warn "mosquitto helm install failed"
  helm upgrade --install abenix-timescaledb "${ROOT_DIR}/infra/helm/timescaledb" \
    --namespace "${NAMESPACE}" --timeout 5m --wait=false 2>&1 | tail -3 \
    || warn "timescaledb helm install failed"
  ok "Streaming + tsdb infra installed"

  step "Installing/upgrading Helm release '${RELEASE_NAME}'"
  # shellcheck disable=SC2046
  helm upgrade --install "${RELEASE_NAME}" "${HELM_DIR}" \
    --namespace "${NAMESPACE}" \
    --values "${HELM_DIR}/values-local.yaml" \
    --set "web.image.tag=${IMAGE_TAG}" \
    --set "api.image.tag=${IMAGE_TAG}" \
    --set "agent-runtime.image.tag=${IMAGE_TAG}" \
    --set "worker.image.tag=${IMAGE_TAG}" \
    --set "cognifyWorker.image.tag=${IMAGE_TAG}" \
    --set "postgresql.image.pullPolicy=IfNotPresent" \
    --set "redis.image.pullPolicy=IfNotPresent" \
    --set "scaling.agentRuntimeImage.tag=${IMAGE_TAG}" \
    --set "corsOrigins[0]=http://localhost:${WEB_PORT}" \
    $(_build_secrets_flags) \
    --timeout 10m \
    --wait=false \
    2>&1 | tail -5
  ok "Helm release deployed"

  wait_for_pods 300 || true
  ensure_jwt_keys || true
  run_migrations || true
  seed_agents || true

  # EDGE_RUNTIME_VARIANT={python|rust|c} picks which port runs in the cluster.
  # EDGE_RUNTIME_ALL_VARIANTS=true installs all of them side-by-side (soak test).
  EDGE_RUNTIME_VARIANT="${EDGE_RUNTIME_VARIANT:-python}"
  EDGE_RUNTIME_ALL_VARIANTS="${EDGE_RUNTIME_ALL_VARIANTS:-false}"
  if [[ "${EDGE_RUNTIME_ENABLED:-true}" == "true" ]]; then
    if [[ "${EDGE_RUNTIME_VARIANT}" == "python" || "${EDGE_RUNTIME_ALL_VARIANTS}" == "true" ]]; then
      step "Installing edge runtime (python, gateway.id=${EDGE_GATEWAY_ID:-edge-cluster-default})"
      helm upgrade --install abenix-edge "${ROOT_DIR}/infra/helm/edge-runtime" \
        --namespace "${NAMESPACE}" \
        --set image.tag="${IMAGE_TAG}" \
        --set image.repository="localhost:5000/abenix/edge-runtime" \
        --set image.pullPolicy=IfNotPresent \
        --set gateway_id="${EDGE_GATEWAY_ID:-edge-cluster-default}" \
        --set gateway_name="${EDGE_GATEWAY_NAME:-edge-cluster-default}" \
        --set platform_url="http://${RELEASE_NAME}-api.${NAMESPACE}.svc.cluster.local:8000" \
        --set mqtt_url="mqtt://abenix-mosquitto.${NAMESPACE}.svc.cluster.local:1883" \
        --set anthropic_api_key="${ANTHROPIC_API_KEY:-}" \
        --timeout 5m --wait=false 2>&1 | tail -3 \
        || warn "edge-runtime helm install failed (non-fatal)"
      ok "edge-runtime installed"
    fi
    if [[ "${EDGE_RUNTIME_VARIANT}" == "rust" || "${EDGE_RUNTIME_ALL_VARIANTS}" == "true" ]]; then
      deploy_edge_runtime_rust
    fi
    if [[ "${EDGE_RUNTIME_VARIANT}" == "c" || "${EDGE_RUNTIME_ALL_VARIANTS}" == "true" ]]; then
      deploy_edge_runtime_c
    fi
  fi

  deploy_livekit || warn "LiveKit deploy failed (non-fatal — meeting agents will be unavailable)"

  # Deploy standalone apps after Abenix is running
  # Only what the operator chose. Same selector dev-local.sh uses, so APPS
  # means the same thing on both paths.
  app_selected contractiq     && { deploy_contractiq      || warn "ContractIQ deployment failed (non-fatal)"; }
  app_selected mideasttourism && { deploy_mideasttourism  || warn "Mideast Tourism deployment failed (non-fatal)"; }
  app_selected industrial-iot && { deploy_industrial_iot  || warn "Industrial-IoT deployment failed (non-fatal)"; }
  app_selected resolveai      && { deploy_resolveai       || warn "ResolveAI deployment failed (non-fatal)"; }
  app_selected wingman        && { deploy_wingman         || warn "Wingman deployment failed (non-fatal)"; }
  app_selected pharmavigil    && { deploy_pharmavigil     || warn "PharmaVigil deployment failed (non-fatal)"; }
  app_selected claimsiq       && { deploy_claimsiq        || warn "ClaimsIQ deployment failed (non-fatal)"; }
  [ "${#SELECTED_APPS[@]}" -eq 0 ] && log "No use-case apps selected — core platform only."

  # After the apps deploy, not before: each manifest recreates its own
  # *-secrets from the environment and would overwrite a freshly minted key.
  if [ -x "${ROOT_DIR}/scripts/seed-standalone-keys.sh" ]; then
    step "Seeding standalone app API keys"
    NAMESPACE="${NAMESPACE}" bash "${ROOT_DIR}/scripts/seed-standalone-keys.sh" 2>&1 | tail -14       || warn "standalone key seed failed — apps will 401 against the platform"
  fi

  setup_port_forwards "false"

  # Observability stack — Prometheus + Grafana + auto-loaded dashboards.
  # Enabled by default on `local` deploys so operators can see the
  # "Abenix Operations" dashboard right after `deploy.sh local`
  # finishes. Set `OBSERVABILITY=false` to skip (saves ~600MB RAM).
  if [[ "${OBSERVABILITY:-true}" == "true" ]]; then
    install_observability_stack
  fi


  echo ""
  echo -e "${GREEN}================================================================${NC}"
  echo -e "${GREEN}  Abenix + ContractIQ on minikube${NC}"
  echo -e "${GREEN}================================================================${NC}"
  echo ""
  echo -e "  ${CYAN}Abenix Web${NC}    http://localhost:${WEB_PORT}"
  echo -e "  ${CYAN}ContractIQ Web${NC}    http://localhost:3001"
  echo -e "  ${CYAN}Mideast Tourism${NC}  http://localhost:3002"
  echo -e "  ${CYAN}Industrial IoT${NC}   http://localhost:3003"
  echo -e "  ${CYAN}ResolveAI${NC}        http://localhost:3004"
  echo -e "  ${CYAN}ClaimsIQ${NC}         http://localhost:3005"
  echo -e "  ${CYAN}Wingman${NC}          http://localhost:3006"
  echo -e "  ${CYAN}Abenix API${NC}    http://localhost:${API_PORT}/docs"
  echo -e "  ${CYAN}ContractIQ API${NC}    http://localhost:8001/api/health"
  echo -e "  ${CYAN}Neo4j Browser${NC}    http://localhost:7474"
  if [[ "${OBSERVABILITY:-true}" == "true" ]]; then
    echo -e "  ${CYAN}Grafana${NC}           http://localhost:3030  (admin / abenix-admin)"
    echo -e "  ${CYAN}Prometheus${NC}        http://localhost:9090"
  fi
  echo ""
  echo -e "  ${YELLOW}Mode:${NC}            EMBEDDED (agents run inside API pod)"
  echo -e "  ${YELLOW}Namespace:${NC}       ${NAMESPACE}"
  echo -e "  ${YELLOW}Image tag:${NC}       ${IMAGE_TAG}"
  echo ""
  echo -e "  ${YELLOW}Upgrade:${NC}         bash scripts/deploy.sh local"
  echo -e "  ${YELLOW}Fresh restart:${NC}   FRESH=true bash scripts/deploy.sh local"
  echo -e "  ${YELLOW}Status:${NC}          bash scripts/deploy.sh status"
  echo -e "  ${YELLOW}Destroy:${NC}         bash scripts/deploy.sh destroy"
  echo -e "  ${YELLOW}E2E Tests:${NC}       bash scripts/run-e2e.sh --k8s knowledge"
  echo -e "  ${YELLOW}Stop forwards:${NC}   bash scripts/deploy.sh destroy (or restart them: bash scripts/deploy.sh forwards)"
  echo ""
}

# LOCAL-RUNTIME — Minikube with separate runtime pod
deploy_local_runtime() {
  check_prereqs
  check_command minikube

  step "Deploying Abenix to minikube WITH runtime pod (production-like)"
  echo -e "  ${YELLOW}Mode: API delegates execution to runtime pod (RUNTIME_MODE=remote)${NC}"

  if [ "${FRESH}" = "true" ]; then
    log "FRESH=true — destroying existing minikube..."
    minikube delete --purge 2>/dev/null || true
    log "Waiting for Docker to recover after minikube purge..."
    sleep 5
    wait_for_docker
  fi

  ensure_minikube
  ensure_infra_images
  build_images "localhost:5000/abenix" "false"

  kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f - &>/dev/null
  helm_deps

  step "Installing/upgrading with runtime pod enabled (RUNTIME_MODE=remote)"
  # shellcheck disable=SC2046
  helm upgrade --install "${RELEASE_NAME}" "${HELM_DIR}" \
    --namespace "${NAMESPACE}" \
    --values "${HELM_DIR}/values-local.yaml" \
    --values "${HELM_DIR}/values-local-runtime.yaml" \
    --set "web.image.tag=${IMAGE_TAG}" \
    --set "api.image.tag=${IMAGE_TAG}" \
    --set "agent-runtime.image.tag=${IMAGE_TAG}" \
    --set "worker.image.tag=${IMAGE_TAG}" \
    --set "cognifyWorker.image.tag=${IMAGE_TAG}" \
    --set "postgresql.image.pullPolicy=IfNotPresent" \
    --set "redis.image.pullPolicy=IfNotPresent" \
    --set "scaling.agentRuntimeImage.tag=${IMAGE_TAG}" \
    --set "corsOrigins[0]=http://localhost:${WEB_PORT}" \
    $(_build_secrets_flags) \
    --timeout 10m \
    --wait=false \
    2>&1 | tail -5
  ok "Helm release deployed (with runtime pod)"

  wait_for_pods 300 || true
  ensure_jwt_keys || true
  run_migrations || true
  seed_agents || true
  deploy_livekit || warn "LiveKit deploy failed (non-fatal — meeting agents will be unavailable)"
  setup_port_forwards "true"

  echo ""
  echo -e "${GREEN}================================================================${NC}"
  echo -e "${GREEN}  Abenix on minikube (production-like with runtime pod)${NC}"
  echo -e "${GREEN}================================================================${NC}"
  echo ""
  echo -e "  ${CYAN}Web App${NC}          http://localhost:3000"
  echo -e "  ${CYAN}API Docs${NC}         http://localhost:8000/docs"
  echo -e "  ${CYAN}Runtime Health${NC}   http://localhost:8001/health"
  echo -e "  ${CYAN}Neo4j Browser${NC}    http://localhost:7474"
  echo ""
  echo -e "  ${YELLOW}Mode:${NC}            ${BOLD}REMOTE${NC} (API delegates to runtime pod via HTTP)"
  echo -e "  ${YELLOW}Namespace:${NC}       ${NAMESPACE}"
  echo -e "  ${YELLOW}Image tag:${NC}       ${IMAGE_TAG}"
  echo ""
  echo -e "  ${YELLOW}Upgrade:${NC}         bash scripts/deploy.sh local-runtime"
  echo -e "  ${YELLOW}Fresh restart:${NC}   FRESH=true bash scripts/deploy.sh local-runtime"
  echo -e "  ${YELLOW}Status:${NC}          bash scripts/deploy.sh status"
  echo -e "  ${YELLOW}Destroy:${NC}         bash scripts/deploy.sh destroy"
  echo -e "  ${YELLOW}E2E Tests:${NC}       bash scripts/run-e2e.sh --k8s knowledge"
  echo -e "  ${YELLOW}Stop forwards:${NC}   bash scripts/deploy.sh destroy (or restart them: bash scripts/deploy.sh forwards)"
  echo ""
}

# CLOUD — Production Kubernetes deployment
deploy_cloud() {
  check_prereqs

  step "Deploying Abenix to cloud Kubernetes"

  local context
  context=$(kubectl config current-context 2>/dev/null)
  if [ -z "${context}" ]; then
    err "No kubectl context set. Run: kubectl config use-context <your-cluster>"
    exit 1
  fi
  log "Using kubectl context: ${context}"

  local registry="${REGISTRY:-ghcr.io/abenix}"
  build_images "${registry}" "true"

  kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f - &>/dev/null
  helm_deps

  step "Installing/upgrading Helm release '${RELEASE_NAME}' (production)"
  # shellcheck disable=SC2046
  helm upgrade --install "${RELEASE_NAME}" "${HELM_DIR}" \
    --namespace "${NAMESPACE}" \
    --values "${HELM_DIR}/values-production.yaml" \
    --set "web.image.tag=${IMAGE_TAG}" \
    --set "api.image.tag=${IMAGE_TAG}" \
    --set "agent-runtime.image.tag=${IMAGE_TAG}" \
    --set "worker.image.tag=${IMAGE_TAG}" \
    --set "cognifyWorker.image.tag=${IMAGE_TAG}" \
    $(_build_secrets_flags) \
    --timeout 15m \
    --wait=false \
    2>&1 | tail -5
  ok "Helm release deployed"

  wait_for_pods 600 || true
  run_migrations || true
  seed_agents || true
  deploy_livekit || warn "LiveKit deploy failed (non-fatal — meeting agents will be unavailable)"

  echo ""
  echo -e "${GREEN}================================================================${NC}"
  echo -e "${GREEN}  Abenix deployed to cloud Kubernetes${NC}"
  echo -e "${GREEN}================================================================${NC}"
  echo ""
  local ingress_ip
  ingress_ip=$(kubectl get ingress -n "${NAMESPACE}" -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")
  echo -e "  ${CYAN}Ingress IP:${NC}  ${ingress_ip}"
  echo -e "  ${CYAN}Context:${NC}     ${context}"
  echo -e "  ${YELLOW}Mode:${NC}        REMOTE (API delegates to runtime pods)"
  echo ""
}

# STATUS
deploy_status() {
  step "Abenix deployment status"

  echo -e "\n${BOLD}Pods:${NC}"
  kubectl get pods -n "${NAMESPACE}" -o wide 2>/dev/null || warn "No pods found"

  echo -e "\n${BOLD}Services:${NC}"
  kubectl get svc -n "${NAMESPACE}" 2>/dev/null || true

  echo -e "\n${BOLD}Config:${NC}"
  local mode
  mode=$(kubectl -n "${NAMESPACE}" get configmap abenix-config -o jsonpath='{.data.RUNTIME_MODE}' 2>/dev/null || echo "unknown")
  echo -e "  RUNTIME_MODE: ${CYAN}${mode}${NC}"

  echo -e "\n${BOLD}Health checks:${NC}"
  echo -n "  API:     " && curl -s --max-time 3 http://localhost:8000/api/health 2>/dev/null || echo "not reachable"
  echo ""
  echo -n "  Web:     " && curl -s --max-time 3 http://localhost:3000 -o /dev/null -w "HTTP %{http_code}" 2>/dev/null || echo "not reachable"
  echo ""
  echo -n "  Runtime: " && curl -s --max-time 3 http://localhost:8001/health 2>/dev/null || echo "not reachable (may be in embedded mode)"
  echo ""
  echo -n "  Neo4j:   " && curl -s --max-time 3 http://localhost:7474 -o /dev/null -w "HTTP %{http_code}" 2>/dev/null || echo "not reachable"
  echo ""
}

# DESTROY
deploy_destroy() {
  step "Destroying Abenix deployment"

  # Kill persistent port forward loops and kubectl port-forwards
  kill_port_forwards
  pkill -f "port-forward.*${RELEASE_NAME}" 2>/dev/null || true

  if helm status "${RELEASE_NAME}" -n "${NAMESPACE}" &>/dev/null; then
    helm uninstall "${RELEASE_NAME}" -n "${NAMESPACE}" --wait 2>/dev/null || true
    ok "Helm release uninstalled"
  fi

  kubectl delete pvc --all -n "${NAMESPACE}" 2>/dev/null || true
  kubectl delete namespace "${NAMESPACE}" --timeout=60s 2>/dev/null || true
  ok "Namespace and PVCs deleted"

  echo ""
  read -p "  Also delete minikube cluster? (y/N): " -r
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    minikube delete --purge 2>/dev/null || true
    ok "Minikube deleted"
  fi

  echo ""
  ok "Abenix destroyed"
}

# BUILD — Build images only
deploy_build() {
  check_prereqs

  local registry="${REGISTRY:-localhost:5000/abenix}"
  if minikube status --format='{{.Host}}' 2>/dev/null | grep -q "Running"; then
    eval "$(minikube docker-env)"
  fi
  build_images "${registry}" "false"
  ok "All images built"
}

# Re-establish every local port forward and report which ones answer.
# Forwards go stale whenever a pod restarts, so this is the supported way to
# get them all back without a full redeploy.
deploy_forwards() {
  check_prereqs
  if ! minikube status --format='{{.Host}}' 2>/dev/null | grep -q "Running"; then
    err "minikube is not running — use '$0 local' first"
    exit 1
  fi
  setup_port_forwards "false"

  step "Verifying forwards"
  local pairs=(
    "abenix-web:${WEB_PORT}" "abenix-api:${API_PORT}"
    "contractiq-web:3001" "contractiq-api:8001"
    "mideasttourism-web:3002" "mideasttourism-api:8002"
    "industrial-iot-web:3003" "industrial-iot-api:8003"
    "resolveai-web:3004" "resolveai-api:8004"
    "claimsiq:3005"
    "wingman-web:3006" "wingman-api:8006"
    "pharmavigil-web:3007" "pharmavigil-api:8007"
    "abenix-prometheus:9090" "abenix-grafana:3030"
  )
  local bad=0
  for pair in "${pairs[@]}"; do
    local label="${pair%%:*}" port="${pair##*:}" code=""
    # An app that was never deployed has no service, and reporting it as
    # down is noise rather than a finding. Selective deploys made that the
    # normal case rather than the exception.
    if ! kubectl -n "${NAMESPACE}" get svc "${label}" &>/dev/null; then
      continue
    fi
    # Any HTTP status means the tunnel carried the request; only a connect
    # failure counts, read from curl's exit status (it prints 000 itself).
    for attempt in 1 2 3; do
      if code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 "http://localhost:${port}/" 2>/dev/null)"; then
        break
      fi
      code="000"
      [ "${attempt}" -lt 3 ] && sleep 3
    done
    if [ "${code}" = "000" ]; then
      err "${label} :${port} not answering"
      bad=$((bad + 1))
      continue
    fi
    # A 200 only proves something is listening. An unrelated container bound to
    # 3000 once passed this check and then served its own 404s to every test,
    # so confirm one of our own forwards actually holds the port.
    if ! pgrep -f "kubectl port-forward.*svc/${label} ${port}:" >/dev/null 2>&1 \
       && ! ps -W 2>/dev/null | grep -q "port-forward.*svc/${label} ${port}:"; then
      if docker ps --format '{{.Ports}}' 2>/dev/null | grep -q ":${port}->"; then
        err "${label} :${port} answered HTTP ${code} but the port belongs to $(port_squatter "${port}") — not this cluster"
        bad=$((bad + 1))
        continue
      fi
    fi
    ok "${label} :${port} -> HTTP ${code}"
  done
  if [ "${bad}" -eq 0 ]; then
    ok "all forwards up"
  else
    warn "${bad} forward(s) down"
  fi
  return 0
}

# Rebuild one core service into minikube's daemon and restart just its
# deployment. Helm is deliberately not involved: images are tagged with the
# git SHA and pulled with pullPolicy: Never, so re-running helm would rewrite
# the tag on every pod for no gain. Use this to pick up a code edit without
# a full deploy.
deploy_reload() {
  local svc="${1:-}"
  # Core services are built from the repo root; each standalone app ships its
  # own Dockerfile beside its source, so it needs its own directory as context.
  local kind="core" app_dir="" app_part=""
  case "${svc}" in
    api|web|worker|agent-runtime|edge-runtime) kind="core" ;;
    contractiq-api|contractiq-web)     kind="app"; app_dir="contractiq";     app_part="${svc#contractiq-}" ;;
    industrial-iot-api|industrial-iot-web) kind="app"; app_dir="industrial-iot"; app_part="${svc#industrial-iot-}" ;;
    resolveai-api|resolveai-web)       kind="app"; app_dir="resolveai";       app_part="${svc#resolveai-}" ;;
    wingman-api|wingman-web)           kind="app"; app_dir="wingman";         app_part="${svc#wingman-}" ;;
    pharmavigil-api|pharmavigil-web)   kind="app"; app_dir="pharmavigil";     app_part="${svc#pharmavigil-}" ;;
    mideasttourism-api|mideasttourism-web) kind="app"; app_dir="mideasttourism"; app_part="${svc#mideasttourism-}" ;;
    claimsiq)                          kind="app"; app_dir="claimsiq";         app_part="app" ;;
    *)
      err "reload does not know '${svc}'"
      err "  core: api web worker agent-runtime edge-runtime"
      err "  apps: {contractiq,industrial-iot,resolveai,wingman,mideasttourism,pharmavigil}-{api,web}"
      exit 1
      ;;
  esac

  check_prereqs
  wait_for_docker
  if ! minikube status --format='{{.Host}}' 2>/dev/null | grep -q "Running"; then
    err "minikube is not running — use '$0 local' first"
    exit 1
  fi
  eval "$(minikube docker-env)"

  local registry="localhost:5000/abenix"
  if [ "${kind}" = "core" ]; then
    build_core_service "${svc}" "${registry}" "false"
    step "Restarting ${svc}"
    # The helm release pins the image to the SHA it was deployed at, so a
    # rebuild under the current SHA produces a tag the Deployment does not
    # reference. Restarting alone then silently re-runs the OLD image. Point
    # the Deployment at what was just built. Standalone apps track :latest and
    # do not need this.
    local dep
    dep=$(kubectl -n "${NAMESPACE}" get deploy -l "app.kubernetes.io/name=${svc}"       -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -n "${dep}" ]; then
      local container
      container=$(kubectl -n "${NAMESPACE}" get deploy "${dep}"         -o jsonpath='{.spec.template.spec.containers[0].name}' 2>/dev/null)
      kubectl -n "${NAMESPACE}" set image "deploy/${dep}"         "${container}=${registry}/${svc}:${IMAGE_TAG}" >/dev/null
      log "${dep}: image -> ${registry}/${svc}:${IMAGE_TAG}"
    fi
    kubectl -n "${NAMESPACE}" rollout restart deployment -l "app.kubernetes.io/name=${svc}"
    kubectl -n "${NAMESPACE}" rollout status deployment -l "app.kubernetes.io/name=${svc}" --timeout=240s
  else
    # mideasttourism-api is the one app whose Dockerfile COPYs from the app
    # root rather than from the api/ subdirectory.
    local ctx="${ROOT_DIR}/${app_dir}/${app_part}"
    local dockerfile="${ctx}/Dockerfile"
    if [ "${svc}" = "mideasttourism-api" ]; then
      ctx="${ROOT_DIR}/${app_dir}"
    fi
    # ClaimsIQ's Dockerfile is under app/ but its Gradle build needs the whole
    # claimsiq/ tree, because the app depends on the sibling sdk/ project.
    if [ "${svc}" = "claimsiq" ]; then
      ctx="${ROOT_DIR}/claimsiq"
    fi
    if [ ! -f "${dockerfile}" ]; then
      err "No Dockerfile at ${dockerfile}"
      exit 1
    fi
    log "Building ${svc}..."
    docker build -t "${registry}/${svc}:${IMAGE_TAG}" -t "${registry}/${svc}:latest" \
      -f "${dockerfile}" "${ctx}" 2>&1 | tail -3
    ok "${svc}: built"
    step "Restarting ${svc}"
    kubectl -n "${NAMESPACE}" rollout restart "deploy/${svc}"
    kubectl -n "${NAMESPACE}" rollout status "deploy/${svc}" --timeout=240s
  fi
  ok "${svc} reloaded at tag ${IMAGE_TAG}"

  # The rollout drops this service's forward, so put it back rather than
  # leaving the caller with a dead tunnel.
  warn "forward for ${svc} was dropped by the rollout — run '$0 forwards' to restore"
  return 0
}

# MAIN
case "${1:-}" in
  local)          deploy_local         ;;
  local-runtime)  deploy_local_runtime ;;
  cloud)          deploy_cloud         ;;
  status)         deploy_status        ;;
  destroy)        deploy_destroy       ;;
  build)          deploy_build         ;;
  reload)         deploy_reload "${2:-}" ;;
  forwards)       deploy_forwards      ;;
  *)              usage                ;;
esac
