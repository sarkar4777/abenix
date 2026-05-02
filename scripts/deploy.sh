#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELM_DIR="${ROOT_DIR}/infra/helm/abenix"
NAMESPACE="${NAMESPACE:-abenix}"
RELEASE_NAME="${RELEASE_NAME:-abenix}"
IMAGE_TAG="${IMAGE_TAG:-$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || echo latest)}"
FRESH="${FRESH:-false}"

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
  [ -n "${EXAMPLE_APP_JWT_SECRET:-}" ]    && flags="${flags} --set secrets.example_appJwtSecret=${EXAMPLE_APP_JWT_SECRET}"
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
  echo "Usage: $0 {local|local-runtime|cloud|status|destroy|build}"
  echo ""
  echo "Commands:"
  echo "  local          Deploy to minikube — embedded execution (no runtime pod)"
  echo "  local-runtime  Deploy to minikube — separate runtime pod (test prod architecture)"
  echo "  cloud          Deploy to current kubectl context (production, remote runtime)"
  echo "  status         Check deployment health"
  echo "  destroy        Tear down the deployment"
  echo "  build          Build Docker images only"
  echo ""
  echo "Flags:"
  echo "  FRESH=true     Force destroy + recreate minikube from scratch"
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

# ── Pull + tag Bitnami images if not already present ─────────────────────────
ensure_infra_images() {
  eval "$(minikube docker-env)"

  # Only pull if not already present
  if ! docker image inspect bitnami/postgresql:16 &>/dev/null; then
    log "Pulling PostgreSQL image..."
    docker pull bitnami/postgresql:latest 2>/dev/null | tail -1
    docker tag bitnami/postgresql:latest bitnami/postgresql:16
  fi
  if ! docker image inspect bitnami/redis:7.2 &>/dev/null; then
    log "Pulling Redis image..."
    docker pull bitnami/redis:latest 2>/dev/null | tail -1
    docker tag bitnami/redis:latest bitnami/redis:7.2
  fi
  if ! docker image inspect neo4j:5-community &>/dev/null; then
    log "Pulling Neo4j image..."
    docker pull neo4j:5-community 2>/dev/null | tail -1
  fi
  ok "Infrastructure images ready"
}

# ── Build app images (only if code changed) ──────────────────────────────────
build_images() {
  local registry="${1:-localhost:5000/abenix}"
  local push="${2:-false}"

  step "Building Docker images (tag: ${IMAGE_TAG})"
  eval "$(minikube docker-env)" 2>/dev/null || true

  # NOTE: We always rebuild — Docker layer cache makes incremental builds fast,
  # and "skip if exists" caused stale images to ship without new seed YAMLs etc.
  local services=("api" "web" "worker" "agent-runtime")
  for svc in "${services[@]}"; do
    local image="${registry}/${svc}:${IMAGE_TAG}"
    local dockerfile="docker/Dockerfile.${svc}"

    [ ! -f "${ROOT_DIR}/${dockerfile}" ] && dockerfile="apps/${svc}/Dockerfile"
    [ ! -f "${ROOT_DIR}/${dockerfile}" ] && { warn "No Dockerfile for ${svc}, skipping"; continue; }

    log "Building ${svc}..."
    docker build -t "${image}" -t "${registry}/${svc}:latest" \
      -f "${ROOT_DIR}/${dockerfile}" "${ROOT_DIR}" 2>&1 | tail -3
    ok "${svc}: built"

    if [ "${push}" = "true" ]; then
      docker push "${image}" 2>&1 | tail -1
      ok "${svc}: pushed"
    fi
  done

  # Build the example app standalone images (api + web)
  if [ -d "${ROOT_DIR}/example_app" ]; then
    step "Building the example app standalone images"
    for ciq in "api" "web"; do
      local ciq_image="${registry}/example_app-${ciq}:${IMAGE_TAG}"
      local ciq_dockerfile="${ROOT_DIR}/example_app/${ciq}/Dockerfile"
      [ ! -f "${ciq_dockerfile}" ] && { warn "No Dockerfile for example_app/${ciq}"; continue; }

      log "Building example_app-${ciq}..."
      docker build -t "${ciq_image}" -t "${registry}/example_app-${ciq}:latest" \
        -f "${ciq_dockerfile}" "${ROOT_DIR}/example_app/${ciq}" 2>&1 | tail -3
      ok "example_app-${ciq}: built"

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
      [ "${push}" = "true" ] && docker push "${img}" 2>&1 | tail -1
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
      [ "${push}" = "true" ] && docker push "${img}" 2>&1 | tail -1
    done
  fi

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
      [ "${push}" = "true" ] && docker push "${img}" 2>&1 | tail -1
    fi
  fi
}

# ── Deploy the example app as k8s manifests (after Abenix is running) ─────────
deploy_example_app() {
  if [ ! -f "${ROOT_DIR}/example_app/k8s/example_app.yaml" ]; then
    warn "the example app k8s manifests not found, skipping"
    return 0
  fi

  step "Deploying the example app to namespace ${NAMESPACE}"

  # Inject secrets from .env if available
  local ciq_key="${EXAMPLE_APP_ABENIX_API_KEY:-}"
  local ciq_jwt="${EXAMPLE_APP_JWT_SECRET:-example_app-dev-secret-please-change}"
  local anth_key="${ANTHROPIC_API_KEY:-}"

  if [ -z "${ciq_key}" ]; then
    warn "EXAMPLE_APP_ABENIX_API_KEY not set — chat will fail until you set it"
  fi

  # Apply manifests with secret substitution
  sed \
    -e "s|REPLACE_AT_DEPLOY_TIME|placeholder|g" \
    "${ROOT_DIR}/example_app/k8s/example_app.yaml" | kubectl apply -f - 2>&1 | tail -10

  # Update secret with real values (use --dry-run to generate, then apply)
  kubectl create secret generic example_app-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=EXAMPLE_APP_ABENIX_API_KEY="${ciq_key}" \
    --from-literal=EXAMPLE_APP_JWT_SECRET="${ciq_jwt}" \
    --from-literal=ANTHROPIC_API_KEY="${anth_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -3

  ok "the example app deployed"

  # Wait for pods to be ready
  log "Waiting for the example app pods to be ready..."
  kubectl wait --for=condition=ready pod -l app=example_app-api \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "the example app API not ready in 120s"
  kubectl wait --for=condition=ready pod -l app=example_app-web \
    --namespace="${NAMESPACE}" --timeout=120s 2>&1 | tail -3 || warn "the example app Web not ready in 120s"
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

  kubectl apply -f "${ROOT_DIR}/industrial-iot/k8s/industrial-iot.yaml" 2>&1 | tail -10
  kubectl create secret generic industrial-iot-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=INDUSTRIALIOT_ABENIX_API_KEY="${iot_key}" \
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
    kubectl exec -n "${NAMESPACE}" "${pg_pod}" -- \
      bash -c 'PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = '"'"'abenix'"'"'" | grep -q 1 || PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -c "CREATE DATABASE abenix"' 2>/dev/null
    ok "Database ready"
  fi

  # Restart API to trigger table auto-creation
  kubectl -n "${NAMESPACE}" rollout restart deployment -l "app.kubernetes.io/name=api" &>/dev/null || true
  log "Waiting for API pod to be ready after restart..."
  kubectl -n "${NAMESPACE}" rollout status deployment -l "app.kubernetes.io/name=api" --timeout=120s 2>/dev/null || true
  ok "Tables created via API startup"
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
  # Use bash -c to prevent MSYS/Git Bash from mangling /app paths on Windows
  kubectl exec -n "${NAMESPACE}" "${api_pod}" -- \
    bash -c 'python /app/packages/db/seeds/seed_agents.py' 2>&1 | tail -5 || true
  kubectl exec -n "${NAMESPACE}" "${api_pod}" -- \
    bash -c 'python /app/packages/db/seeds/seed_users.py' 2>&1 | tail -5 || true
  # SchemaPortfolioTool reads its schema from the portfolio_schemas table
  # at runtime — without a row for energy_contracts the CIQ chat agent
  # replies "portfolio not configured". Seed the energy_contracts schema
  # for every tenant so chat works out of the box on a fresh deploy.
  kubectl exec -n "${NAMESPACE}" "${api_pod}" -- \
    bash -c 'python /app/packages/db/seeds/seed_portfolio_schemas.py' 2>&1 | tail -5 || true
  # Sample ML models (iris/housing/churn) for the OOB ml_prediction_pipeline.
  kubectl exec -n "${NAMESPACE}" "${api_pod}" -- \
    bash -c 'python /app/packages/db/seeds/seed_ml_models.py' 2>&1 | tail -5 || true
  # KB seed: policy/persona/SOP for ResolveAI, policies for ClaimsIQ,
  # equipment refs for Industrial IoT. MUST run AFTER seed_agents because
  # it grants collections to agents by slug.
  kubectl exec -n "${NAMESPACE}" "${api_pod}" -- \
    bash -c 'python /app/packages/db/seeds/seed_kb.py' 2>&1 | tail -5 || true
  ok "Seeding complete"
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
# Start a self-restarting port forward that reconnects if the connection drops
start_persistent_forward() {
  local svc="$1" local_port="$2" remote_port="$3"
  local ns="${NAMESPACE}"
  nohup bash -c "while true; do kubectl port-forward -n ${ns} svc/${svc} ${local_port}:${remote_port} 2>/dev/null; sleep 2; done" &>/dev/null &
}

setup_port_forwards() {
  local with_runtime="${1:-false}"
  step "Setting up port forwarding"

  # Kill any existing port forwards from previous runs
  pkill -f "kubectl port-forward.*${NAMESPACE}" 2>/dev/null || true
  sleep 2

  # Start persistent (auto-reconnecting) port forwards
  start_persistent_forward "${RELEASE_NAME}-web" 3000 3000
  start_persistent_forward "${RELEASE_NAME}-api" 8000 8000
  start_persistent_forward "${RELEASE_NAME}-neo4j" 7474 7474

  # Standalone apps — each on its own port so the Use Cases dropdown
  # in the core UI can deep-link to them at localhost:<port>.
  if kubectl -n "${NAMESPACE}" get svc example_app-web &>/dev/null; then
    start_persistent_forward "example_app-web" 3001 3001
    start_persistent_forward "example_app-api" 8001 8001
  fi
  if kubectl -n "${NAMESPACE}" get svc sauditourism-web &>/dev/null; then
    start_persistent_forward "sauditourism-web" 3002 3002
    start_persistent_forward "sauditourism-api" 8002 8002
  fi
  if kubectl -n "${NAMESPACE}" get svc industrial-iot-web &>/dev/null; then
    start_persistent_forward "industrial-iot-web" 3003 3003
    start_persistent_forward "industrial-iot-api" 8003 8003
  fi
  if kubectl -n "${NAMESPACE}" get svc resolveai-web &>/dev/null; then
    start_persistent_forward "resolveai-web" 3004 3004
    start_persistent_forward "resolveai-api" 8004 8004
  fi
  # ClaimsIQ is a single Spring Boot + Vaadin container — no api/web split.
  if kubectl -n "${NAMESPACE}" get svc claimsiq &>/dev/null; then
    start_persistent_forward "claimsiq" 3005 3005
  fi

  # LiveKit signaling — enables the browser to connect to in-cluster
  # LiveKit at ws://localhost:7880 (matches LIVEKIT_PUBLIC_URL).
  if kubectl -n "${NAMESPACE}" get svc livekit-server &>/dev/null; then
    start_persistent_forward "livekit-server" 7880 7880
  fi

  if [ "${with_runtime}" = "true" ]; then
    start_persistent_forward "${RELEASE_NAME}-agent-runtime" 8001 8001
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
      ok "All services reachable — ports: 3000 (web), 8000 (api), 8001 (runtime), 7474 (neo4j)"
    else
      ok "All services reachable — ports: 3000 (web), 8000 (api), 7474 (neo4j)"
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

  # Set up port forwards so operators can reach both immediately.
  pkill -f "kubectl port-forward.*abenix-prometheus" 2>/dev/null || true
  pkill -f "kubectl port-forward.*abenix-grafana"    2>/dev/null || true
  nohup kubectl port-forward -n "${NAMESPACE}" svc/abenix-prometheus 9090:9090 > /tmp/pf-prometheus.log 2>&1 &
  nohup kubectl port-forward -n "${NAMESPACE}" svc/abenix-grafana    3030:3000 > /tmp/pf-grafana.log    2>&1 &
  sleep 1
  ok "Observability port forwards: prometheus→9090, grafana→3030"
}


deploy_local() {
  check_prereqs
  check_command minikube

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
  helm_deps

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
    $(_build_secrets_flags) \
    --timeout 10m \
    --wait=false \
    2>&1 | tail -5
  ok "Helm release deployed"

  wait_for_pods 300 || true
  ensure_jwt_keys || true
  run_migrations || true
  seed_agents || true
  deploy_livekit || warn "LiveKit deploy failed (non-fatal — meeting agents will be unavailable)"

  # Deploy standalone apps after Abenix is running
  deploy_example_app     || warn "the example app deployment failed (non-fatal)"
  deploy_industrial_iot || warn "Industrial-IoT deployment failed (non-fatal)"
  deploy_resolveai      || warn "ResolveAI deployment failed (non-fatal)"
  deploy_claimsiq       || warn "ClaimsIQ deployment failed (non-fatal)"

  setup_port_forwards "false"

  # Observability stack — Prometheus + Grafana + auto-loaded dashboards.
  # Enabled by default on `local` deploys so operators can see the
  # "Abenix Operations" dashboard right after `deploy.sh local`
  # finishes. Set `OBSERVABILITY=false` to skip (saves ~600MB RAM).
  if [[ "${OBSERVABILITY:-true}" == "true" ]]; then
    install_observability_stack
  fi

  # Forward the example app ports too
  if kubectl get svc example_app-web -n "${NAMESPACE}" &>/dev/null; then
    log "Setting up the example app port forwards..."
    pkill -f "kubectl port-forward.*example_app" 2>/dev/null || true
    nohup kubectl port-forward -n "${NAMESPACE}" svc/example_app-web 3001:3001 > /tmp/pf-ciq-web.log 2>&1 &
    nohup kubectl port-forward -n "${NAMESPACE}" svc/example_app-api 8001:8001 > /tmp/pf-ciq-api.log 2>&1 &
    sleep 2
    ok "the example app port forwards: web→3001, api→8001"
  fi

  echo ""
  echo -e "${GREEN}================================================================${NC}"
  echo -e "${GREEN}  Abenix + the example app on minikube${NC}"
  echo -e "${GREEN}================================================================${NC}"
  echo ""
  echo -e "  ${CYAN}Abenix Web${NC}    http://localhost:3000"
  echo -e "  ${CYAN}the example app Web${NC}    http://localhost:3001"
  echo -e "  ${CYAN}ClaimsIQ${NC}         http://localhost:3005"
  echo -e "  ${CYAN}Abenix API${NC}    http://localhost:8000/docs"
  echo -e "  ${CYAN}the example app API${NC}    http://localhost:8001/api/health"
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
  echo -e "  ${YELLOW}Stop forwards:${NC}   pkill -f 'kubectl port-forward.*abenix'"
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
  echo -e "  ${YELLOW}Stop forwards:${NC}   pkill -f 'kubectl port-forward.*abenix'"
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
  pkill -f "kubectl port-forward.*${NAMESPACE}" 2>/dev/null || true
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

# MAIN
case "${1:-}" in
  local)          deploy_local         ;;
  local-runtime)  deploy_local_runtime ;;
  cloud)          deploy_cloud         ;;
  status)         deploy_status        ;;
  destroy)        deploy_destroy       ;;
  build)          deploy_build         ;;
  *)              usage                ;;
esac
