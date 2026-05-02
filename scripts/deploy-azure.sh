#!/usr/bin/env bash
set -euo pipefail

# ── Paths ───────────────────────────────────────────────────────────────────
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELM_DIR="${ROOT_DIR}/infra/helm/abenix"

# ── Defaults (env-overridable) ──────────────────────────────────────────────
AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-abenix-rg}"
AZ_LOCATION="${AZ_LOCATION:-westeurope}"
AKS_NAME="${AKS_NAME:-abenix-aks}"
AKS_NODE_SIZE="${AKS_NODE_SIZE:-Standard_D4s_v5}"
AKS_NODE_COUNT="${AKS_NODE_COUNT:-3}"
NAMESPACE="${NAMESPACE:-abenix}"
RELEASE_NAME="${RELEASE_NAME:-abenix}"
IMAGE_TAG="${IMAGE_TAG:-$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || echo latest)}"
KEEP_CLUSTER="${KEEP_CLUSTER:-false}"

# ACR names must be globally unique AND 5-50 alphanumerics. Derive a stable
# suffix from the subscription+rg hash so repeated runs reuse the same ACR.
_default_acr_name() {
  local sub_id
  sub_id=$(az account show --query id -o tsv 2>/dev/null || echo "")
  if [ -z "${sub_id}" ]; then echo "abenixacr00000"; return; fi
  local suf
  suf=$(printf '%s|%s' "${sub_id}" "${AZ_RESOURCE_GROUP}" | md5sum 2>/dev/null | cut -c1-5)
  # md5sum may not exist on macOS — fall back to shasum
  if [ -z "${suf}" ]; then
    suf=$(printf '%s|%s' "${sub_id}" "${AZ_RESOURCE_GROUP}" | shasum 2>/dev/null | cut -c1-5)
  fi
  echo "abenixacr${suf}"
}
ACR_NAME="${ACR_NAME:-$(_default_acr_name)}"

# ── Load .env (LLM + tool API keys) + scripts/azure.env (RG/ACR pins) ──────
# azure.env holds the subscription-specific RG + ACR + region once
# discovered; loading it first means the user only has to run `source
# scripts/azure.env` once (or not at all if env vars are already exported).
if [ -f "${ROOT_DIR}/scripts/azure.env" ]; then
  set -a; source "${ROOT_DIR}/scripts/azure.env"; set +a
fi
if [ -f "${ROOT_DIR}/.env" ]; then
  set -a; source "${ROOT_DIR}/.env"; set +a
fi

# Re-read env-overridable vars now that the env files are loaded.
AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-abenix-rg}"
AZ_LOCATION="${AZ_LOCATION:-westeurope}"
AKS_NAME="${AKS_NAME:-abenix-aks}"
ACR_NAME="${ACR_NAME:-$(_default_acr_name)}"
NAMESPACE="${NAMESPACE:-abenix}"
RELEASE_NAME="${RELEASE_NAME:-abenix}"

# ── Colored logging ─────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${CYAN}[azure]${NC} $1"; }
ok()   { echo -e "${GREEN}  [ok]${NC} $1"; }
warn() { echo -e "${YELLOW}  [warn]${NC} $1"; }
err()  { echo -e "${RED}  [err]${NC} $1" >&2; }
step() { echo -e "\n${BOLD}${BLUE}▶ $1${NC}"; }

# ── CLI arg parsing ─────────────────────────────────────────────────────────
CMD="${1:-}"
shift || true
ONLY_CSV=""
SKIP_BUILD="${SKIP_BUILD:-false}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --only=*)      ONLY_CSV="${1#*=}" ;;
    --only)        ONLY_CSV="$2"; shift ;;
    --keep-cluster) KEEP_CLUSTER="true" ;;
    --skip-build)  SKIP_BUILD="true" ;;
    *)             err "Unknown flag: $1"; exit 1 ;;
  esac
  shift
done

usage() {
  cat <<EOF
Usage: $(basename "$0") <command> [flags]

Commands:
  provision         Create RG + AKS + ACR; attach ACR to AKS; get kubectl creds.
  build             Build all Docker images and push to ACR. --only=... supported.
  deploy            Helm-install Abenix + standalone apps (the example app, Saudi Tourism).
                    Incremental — safe to re-run. --only=... supported.
  redeploy          Alias: build (per --only) + rollout restart (per --only).
  seed              Re-run agent / portfolio / ML model seed scripts, then
                    reconcile every standalone's ABENIX_API_KEY so chat works.
  seed-keys         Reconcile only the standalone ABENIX_API_KEYs (idempotent).
                    Mints any missing keys + patches secrets + restarts pods.
  test              Run all Playwright E2E suites against the AKS endpoints.
                    E2E_PROJECT=abenix|example_app|sauditourism to scope.
                    E2E_ONLY=test1.spec.ts,test2.spec.ts to run specific files.
  status            Report cluster, pods, services, ingress, and health endpoints.
  destroy           Uninstall helm + namespace. With KEEP_CLUSTER=false (default) also
                    deletes the AKS cluster + resource group.
  all               provision → build → deploy → seed → test (full green-field run).

Flags:
  --only=<list>     Comma-separated list of groups/services to act on.
                    Groups: abenix, example_app, sauditourism, observability, livekit
                    Services: api, web, worker, agent-runtime, cognify-worker,
                              example_app-api, example_app-web,
                              sauditourism-api, sauditourism-web
  --keep-cluster    On destroy: keep AKS + RG, only remove helm + namespace.
  --skip-build      On deploy: don't rebuild images (use whatever is in ACR).

Environment overrides: AZ_RESOURCE_GROUP, AZ_LOCATION, AKS_NAME, AKS_NODE_SIZE,
  AKS_NODE_COUNT, ACR_NAME, NAMESPACE, RELEASE_NAME, IMAGE_TAG.

Current values:
  RG        = ${AZ_RESOURCE_GROUP}
  LOCATION  = ${AZ_LOCATION}
  AKS       = ${AKS_NAME}  (${AKS_NODE_COUNT} × ${AKS_NODE_SIZE})
  ACR       = ${ACR_NAME}
  NAMESPACE = ${NAMESPACE}
  IMAGE_TAG = ${IMAGE_TAG}
EOF
}

# ── Prereq checks ───────────────────────────────────────────────────────────
check_command() { command -v "$1" &>/dev/null || { err "$1 not installed"; exit 2; }; }
check_prereqs() {
  check_command az
  check_command kubectl
  check_command helm
  check_command docker
  # Verify az login
  if ! az account show &>/dev/null; then
    err "Not logged in to Azure. Run: az login"
    exit 3
  fi
  if [ -n "${AZ_SUBSCRIPTION:-}" ]; then
    az account set --subscription "${AZ_SUBSCRIPTION}" 2>&1 | head -2 || { err "Could not set subscription ${AZ_SUBSCRIPTION}"; exit 3; }
  fi
  local sub
  sub=$(az account show --query 'name' -o tsv 2>/dev/null)
  ok "Azure subscription: ${sub}"

  # ── Phase 0 pre-flight: SDK drift gate ──────────────────────────────
  # The Abenix Python SDK is vendored into 5 standalone-app images. If a
  # destination has drifted from the canonical packages/sdk/python copy,
  # those images would ship with stale code (e.g. missing the wait=True
  # default that synchronises async-mode execute calls). Fail before we
  # waste 20 minutes on Docker builds. Skip with SKIP_SDK_SYNC_CHECK=1.
  if [ "${SKIP_SDK_SYNC_CHECK:-0}" != "1" ]; then
    step "Phase 0 — SDK drift pre-flight"
    if ! bash "${ROOT_DIR}/scripts/sync-sdks.sh" --check; then
      err "SDK copies out of sync. Run: bash scripts/sync-sdks.sh"
      err "Or set SKIP_SDK_SYNC_CHECK=1 to bypass (NOT recommended)."
      exit 5
    fi
    ok "All SDK copies in sync"
  fi
}

# Helper: --only parser
# Expand a group name into its service list, or pass through a service name.
_expand_only() {
  local token="$1"
  case "${token}" in
    abenix)     echo "api web worker agent-runtime cognify-worker" ;;
    example_app)     echo "example_app-api example_app-web" ;;
    sauditourism)   echo "sauditourism-api sauditourism-web" ;;
    industrial-iot) echo "industrial-iot-api industrial-iot-web" ;;
    resolveai)      echo "resolveai-api resolveai-web" ;;
    claimsiq)       echo "claimsiq" ;;
    observability)  echo "observability" ;;
    livekit)        echo "livekit" ;;
    *)              echo "${token}" ;;
  esac
}

# Parse ONLY_CSV into a flat list. Returns empty (= everything) when unset.
_only_list() {
  if [ -z "${ONLY_CSV}" ]; then return; fi
  local out=""
  IFS=',' read -ra toks <<< "${ONLY_CSV}"
  for t in "${toks[@]}"; do
    t=$(echo "$t" | tr -d ' ')
    out+="$(_expand_only "$t") "
  done
  echo "${out}" | tr -s ' '
}

# True if a service should be acted on given current --only filter.
_should_do() {
  local svc="$1"
  local list
  list="$(_only_list)"
  [ -z "${list}" ] && return 0           # no filter = all
  for s in ${list}; do
    [ "$s" = "${svc}" ] && return 0
  done
  return 1
}

# Secrets helper (Helm --set flags, mirrors deploy.sh contract)
_build_secrets_flags() {
  local flags=""
  [ -n "${ANTHROPIC_API_KEY:-}" ]        && flags="${flags} --set secrets.anthropicApiKey=${ANTHROPIC_API_KEY}"
  [ -n "${OPENAI_API_KEY:-}" ]           && flags="${flags} --set secrets.openaiApiKey=${OPENAI_API_KEY}"
  [ -n "${GOOGLE_API_KEY:-}" ]           && flags="${flags} --set secrets.googleApiKey=${GOOGLE_API_KEY}"
  [ -n "${PINECONE_API_KEY:-}" ]         && flags="${flags} --set secrets.pineconeApiKey=${PINECONE_API_KEY}"
  [ -n "${TAVILY_API_KEY:-}" ]           && flags="${flags} --set secrets.tavilyApiKey=${TAVILY_API_KEY}"
  [ -n "${BRAVE_SEARCH_API_KEY:-}" ]     && flags="${flags} --set secrets.braveSearchApiKey=${BRAVE_SEARCH_API_KEY}"
  [ -n "${SERPAPI_API_KEY:-}" ]          && flags="${flags} --set secrets.serpapiApiKey=${SERPAPI_API_KEY}"
  [ -n "${SERPER_API_KEY:-}" ]           && flags="${flags} --set secrets.serperApiKey=${SERPER_API_KEY}"
  [ -n "${NEWS_API_KEY:-}" ]             && flags="${flags} --set secrets.newsApiKey=${NEWS_API_KEY}"
  [ -n "${FRED_API_KEY:-}" ]             && flags="${flags} --set secrets.fredApiKey=${FRED_API_KEY}"
  [ -n "${ALPHA_VANTAGE_API_KEY:-}" ]    && flags="${flags} --set secrets.alphaVantageApiKey=${ALPHA_VANTAGE_API_KEY}"
  [ -n "${MEDIASTACK_API_KEY:-}" ]       && flags="${flags} --set secrets.mediastackApiKey=${MEDIASTACK_API_KEY}"
  [ -n "${ENTSOE_API_KEY:-}" ]           && flags="${flags} --set secrets.entsoeApiKey=${ENTSOE_API_KEY}"
  [ -n "${EIA_API_KEY:-}" ]              && flags="${flags} --set secrets.eiaApiKey=${EIA_API_KEY}"
  [ -n "${EXAMPLE_APP_JWT_SECRET:-}" ]    && flags="${flags} --set secrets.example_appJwtSecret=${EXAMPLE_APP_JWT_SECRET}"
  echo "${flags}"
}

# PHASE 1: Provision — RG + ACR + AKS + credentials
ensure_resource_group() {
  log "Ensuring resource group: ${AZ_RESOURCE_GROUP} (${AZ_LOCATION})"
  if az group show -n "${AZ_RESOURCE_GROUP}" &>/dev/null; then
    ok "RG exists"
  else
    az group create -n "${AZ_RESOURCE_GROUP}" -l "${AZ_LOCATION}" -o none
    ok "RG created"
  fi
}

ensure_acr() {
  log "Ensuring Azure Container Registry: ${ACR_NAME}"
  if az acr show -n "${ACR_NAME}" -g "${AZ_RESOURCE_GROUP}" &>/dev/null; then
    ok "ACR exists"
  else
    az acr create -n "${ACR_NAME}" -g "${AZ_RESOURCE_GROUP}" --sku Standard --admin-enabled false -o none
    ok "ACR created"
  fi
  ACR_LOGIN_SERVER=$(az acr show -n "${ACR_NAME}" --query loginServer -o tsv)
  log "  loginServer: ${ACR_LOGIN_SERVER}"
  az acr login -n "${ACR_NAME}" 2>&1 | tail -2
}

ensure_aks() {
  log "Ensuring AKS cluster: ${AKS_NAME}"
  if az aks show -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" &>/dev/null; then
    ok "AKS exists"
  else
    log "Creating AKS (this takes ~8-15 min)..."
    az aks create \
      -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" -l "${AZ_LOCATION}" \
      --node-count "${AKS_NODE_COUNT}" \
      --node-vm-size "${AKS_NODE_SIZE}" \
      --generate-ssh-keys \
      --network-plugin azure \
      --enable-managed-identity \
      --tier free \
      -o none || warn "AKS create returned non-zero — cluster may still be up, continuing"
    ok "AKS created (or already exists)"
  fi
  log "Ensuring ACR is attached to AKS..."
  if ! az aks update -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" --attach-acr "${ACR_NAME}" -o none 2>/dev/null; then
    warn "ACR attach failed (no Owner role). Falling back to imagePullSecret."
    _ensure_acr_pull_secret
  fi
  log "Fetching kubeconfig..."
  az aks get-credentials -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" --overwrite-existing 2>&1 | tail -1
  kubectl cluster-info 2>&1 | head -2
  ok "kubectl wired to AKS"
}

# When the caller doesn't have Owner rights, --attach-acr can't write the
# role assignment. Fallback: create a docker-registry secret in the target
# namespace using ACR admin credentials, and wire it into the default SA so
# every pod picks it up automatically.
_ensure_acr_pull_secret() {
  log "Creating ACR pull secret in namespace ${NAMESPACE}..."
  local admin_enabled
  admin_enabled=$(az acr show -n "${ACR_NAME}" --query adminUserEnabled -o tsv 2>/dev/null)
  if [ "${admin_enabled}" != "true" ]; then
    log "  Enabling ACR admin user for pull-secret fallback..."
    az acr update -n "${ACR_NAME}" --admin-enabled true -o none 2>/dev/null || {
      err "Can't enable ACR admin — and can't attach ACR. Fix permissions and retry."; return 1; }
  fi
  local acr_user acr_pass
  acr_user=$(az acr credential show -n "${ACR_NAME}" --query username -o tsv 2>/dev/null)
  acr_pass=$(az acr credential show -n "${ACR_NAME}" --query passwords[0].value -o tsv 2>/dev/null)

  kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl create secret docker-registry acr-pull-secret \
    --namespace="${NAMESPACE}" \
    --docker-server="${ACR_NAME}.azurecr.io" \
    --docker-username="${acr_user}" \
    --docker-password="${acr_pass}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -1

  kubectl patch serviceaccount default -n "${NAMESPACE}" \
    -p '{"imagePullSecrets": [{"name": "acr-pull-secret"}]}' 2>&1 | tail -1 || true
  ok "ACR pull secret configured on default SA"
}

ensure_ingress_controller() {
  log "Ensuring ingress-nginx controller (for public URLs)..."
  if kubectl get ns ingress-nginx &>/dev/null; then
    ok "ingress-nginx already installed"
    return
  fi
  helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx &>/dev/null || true
  helm repo update &>/dev/null
  helm install ingress-nginx ingress-nginx/ingress-nginx \
    --namespace ingress-nginx --create-namespace \
    --set controller.service.type=LoadBalancer \
    --timeout 5m \
    --wait 2>&1 | tail -5
  ok "ingress-nginx installed"
}

# KEDA — referenced by the chart's ScaledObject resources for per-agent
# pool autoscaling. Required before helm install.
ensure_keda() {
  log "Ensuring KEDA (event-driven autoscaler)..."
  if kubectl get crd scaledobjects.keda.sh &>/dev/null; then
    ok "KEDA CRDs already installed"
    return
  fi
  helm repo add kedacore https://kedacore.github.io/charts &>/dev/null || true
  helm repo update &>/dev/null
  helm install keda kedacore/keda \
    --namespace keda --create-namespace \
    --timeout 5m \
    --wait 2>&1 | tail -5
  ok "KEDA installed"
}

provision() {
  check_prereqs
  step "Phase 1/5 — Provisioning Azure resources"
  ensure_resource_group
  ensure_acr
  ensure_aks
  ensure_ingress_controller
  ensure_keda
  ok "Provisioning complete. ACR=${ACR_LOGIN_SERVER}  AKS context active."
}

# PHASE 2: Build + push images to ACR
# Map service → dockerfile. Keep the list in sync with Helm values + k8s manifests.
# Note: cognifyWorker reuses the `worker` image (same code, different Celery queue).
declare -A DOCKERFILES=(
  [api]="docker/Dockerfile.api"
  [web]="docker/Dockerfile.web"
  [worker]="docker/Dockerfile.worker"
  [agent-runtime]="docker/Dockerfile.agent-runtime"
  [example_app-api]="example_app/api/Dockerfile"
  [example_app-web]="example_app/web/Dockerfile"
  [sauditourism-api]="sauditourism/api/Dockerfile"
  [sauditourism-web]="sauditourism/web/Dockerfile"
  [industrial-iot-api]="industrial-iot/api/Dockerfile"
  [industrial-iot-web]="industrial-iot/web/Dockerfile"
  [resolveai-api]="resolveai/api/Dockerfile"
  [resolveai-web]="resolveai/web/Dockerfile"
  # ClaimsIQ is a single-container Spring Boot + Vaadin app — one image,
  # no api/web split. Dockerfile is inside app/ but the build context
  # MUST be the claimsiq root so the multi-stage build can reach both
  # the sdk/ and app/ submodules.
  [claimsiq]="claimsiq/app/Dockerfile"
)
# Build context — some Dockerfiles need the monorepo root, others a sub-dir.
declare -A BUILD_CONTEXTS=(
  [api]="${ROOT_DIR}"
  [web]="${ROOT_DIR}"
  [worker]="${ROOT_DIR}"
  [agent-runtime]="${ROOT_DIR}"
  [cognify-worker]="${ROOT_DIR}"
  [example_app-api]="${ROOT_DIR}/example_app/api"
  [example_app-web]="${ROOT_DIR}/example_app/web"
  # sauditourism-api: build context must include test-data/ for the seed endpoint,
  # so we use the sauditourism/ directory rather than sauditourism/api/.
  [sauditourism-api]="${ROOT_DIR}/sauditourism"
  [sauditourism-web]="${ROOT_DIR}/sauditourism/web"
  [industrial-iot-api]="${ROOT_DIR}/industrial-iot/api"
  [industrial-iot-web]="${ROOT_DIR}/industrial-iot/web"
  [resolveai-api]="${ROOT_DIR}/resolveai/api"
  [resolveai-web]="${ROOT_DIR}/resolveai/web"
  [claimsiq]="${ROOT_DIR}/claimsiq"
)

# cognify-worker is NOT a separate image — it reuses `worker`.
_cognify_worker_is_alias() { return 0; }

build_push_image() {
  local svc="$1"
  local df="${DOCKERFILES[$svc]:-}"
  local ctx="${BUILD_CONTEXTS[$svc]:-${ROOT_DIR}}"
  if [ -z "${df}" ]; then warn "${svc}: no Dockerfile mapping — skip"; return 0; fi

  # Some deploy.sh fallbacks: look under apps/<svc>/Dockerfile if the docker/ path
  # doesn't exist (matches deploy.sh behavior).
  local abs_df="${ROOT_DIR}/${df}"
  if [ ! -f "${abs_df}" ] && [ -f "${ROOT_DIR}/apps/${svc}/Dockerfile" ]; then
    abs_df="${ROOT_DIR}/apps/${svc}/Dockerfile"
  fi
  if [ ! -f "${abs_df}" ]; then warn "${svc}: Dockerfile ${df} missing — skip"; return 0; fi

  local img="${ACR_LOGIN_SERVER}/${svc}"
  local svc_log="${ROOT_DIR}/logs/build-${svc}.log"
  mkdir -p "${ROOT_DIR}/logs"
  log "Building+pushing ${svc} → ${img}:${IMAGE_TAG}  (full log: logs/build-${svc}.log)"
  if ! docker buildx build \
        --platform=linux/amd64 \
        --network=host \
        --push \
        -t "${img}:${IMAGE_TAG}" \
        -t "${img}:latest" \
        -f "${abs_df}" "${ctx}" >"${svc_log}" 2>&1; then
    err "${svc}: build/push FAILED — last 30 lines:"
    tail -30 "${svc_log}" >&2
    return 1
  fi
  tail -3 "${svc_log}" || true
  ok "${svc}: built+pushed"
}

build_and_push() {
  check_prereqs
  step "Phase 2/5 — Building + pushing images to ACR"

  # Need ACR login server; if provision hasn't run in this shell, re-derive it.
  if [ -z "${ACR_LOGIN_SERVER:-}" ]; then
    ACR_LOGIN_SERVER=$(az acr show -n "${ACR_NAME}" --query loginServer -o tsv 2>/dev/null || true)
    if [ -z "${ACR_LOGIN_SERVER}" ]; then err "ACR ${ACR_NAME} not found — run provision first"; exit 4; fi
  fi
  az acr login -n "${ACR_NAME}" 2>&1 | tail -1

  # cognify-worker reuses the worker image — don't build it separately
  local all_svcs=(
    api web worker agent-runtime
    example_app-api example_app-web
    sauditourism-api sauditourism-web
    industrial-iot-api industrial-iot-web
    resolveai-api resolveai-web
    claimsiq
  )
  local built=0 skipped=0
  for s in "${all_svcs[@]}"; do
    # cognify-worker in --only filter maps to building the worker image
    if _should_do "$s" || ( [ "$s" = "worker" ] && _should_do "cognify-worker" ); then
      build_push_image "$s"
      built=$((built+1))
    else
      skipped=$((skipped+1))
    fi
  done
  ok "Image phase: ${built} built+pushed, ${skipped} skipped (--only filter)"
}

# PHASE 3: Deploy — Helm + standalone manifests + seeds
helm_deps() {
  log "Updating Helm dependencies..."
  helm dependency update "${HELM_DIR}" 2>&1 | tail -2
  ok "Helm deps ready"
}

wait_for_pods() {
  local timeout="${1:-600}"
  log "Waiting for all pods to be ready (up to ${timeout}s)..."
  local start=$SECONDS
  while true; do
    local not_ready total
    not_ready=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | grep -cv "Running\|Completed" || echo 0)
    not_ready=$(echo "${not_ready}" | tr -d '[:space:]')
    total=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | wc -l | tr -d '[:space:]')
    local elapsed=$((SECONDS - start))
    if [ "${not_ready}" -eq 0 ] && [ "${total}" -gt 0 ]; then
      ok "All ${total} pods running"; return 0
    fi
    if [ "${elapsed}" -ge "${timeout}" ]; then
      warn "${not_ready} pods still not ready after ${timeout}s:"
      kubectl get pods -n "${NAMESPACE}" --no-headers | grep -v "Running\|Completed" | sed 's/^/        /'
      return 1
    fi
    log "  ${not_ready}/${total} pods still pending ($((timeout - elapsed))s left)"
    sleep 10
  done
}

deploy_abenix_helm() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "api" && ! _should_do "web" && ! _should_do "worker" && ! _should_do "agent-runtime" && ! _should_do "cognify-worker"; then
    log "Abenix core not in --only filter — skipping helm upgrade"
    return 0
  fi

  step "Deploying Abenix via Helm (tag=${IMAGE_TAG})"

  # Ensure namespace
  kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f - &>/dev/null

  helm_deps

  # Prefer values-azure.yaml (right-sized for a demo cluster). Fall back to
  # values-production.yaml only if azure.yaml doesn't exist yet.
  local values_override=""
  if [ -f "${HELM_DIR}/values-azure.yaml" ]; then
    values_override="--values ${HELM_DIR}/values-azure.yaml"
  elif [ -f "${HELM_DIR}/values-production.yaml" ]; then
    values_override="--values ${HELM_DIR}/values-production.yaml"
  fi

  # Helm templates use image.repository as the full "registry/path" string.
  # shellcheck disable=SC2046,SC2086
  helm upgrade --install "${RELEASE_NAME}" "${HELM_DIR}" \
    --namespace "${NAMESPACE}" \
    ${values_override} \
    --set "web.image.repository=${ACR_LOGIN_SERVER}/web" \
    --set "web.image.tag=${IMAGE_TAG}" \
    --set "web.image.pullPolicy=Always" \
    --set "api.image.repository=${ACR_LOGIN_SERVER}/api" \
    --set "api.image.tag=${IMAGE_TAG}" \
    --set "api.image.pullPolicy=Always" \
    --set "worker.image.repository=${ACR_LOGIN_SERVER}/worker" \
    --set "worker.image.tag=${IMAGE_TAG}" \
    --set "worker.image.pullPolicy=Always" \
    --set "agent-runtime.image.repository=${ACR_LOGIN_SERVER}/agent-runtime" \
    --set "agent-runtime.image.tag=${IMAGE_TAG}" \
    --set "agent-runtime.image.pullPolicy=Always" \
    --set "cognifyWorker.image.repository=${ACR_LOGIN_SERVER}/worker" \
    --set "cognifyWorker.image.tag=${IMAGE_TAG}" \
    --set "cognifyWorker.image.pullPolicy=Always" \
    $(_build_secrets_flags) \
    --timeout 15m \
    --wait=false \
    2>&1 | tail -6
  ok "Helm release ${RELEASE_NAME} installed/updated"
}

ensure_jwt_keys() {
  local existing
  existing=$(kubectl get secret abenix-secrets -n "${NAMESPACE}" -o jsonpath='{.data.JWT_PRIVATE_KEY}' 2>/dev/null || echo "")
  if [ -n "${existing}" ]; then ok "JWT keys already set"; return; fi
  log "Generating RSA key pair for JWT..."
  local privkey pubkey
  privkey=$(openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 2>/dev/null)
  pubkey=$(echo "${privkey}" | openssl rsa -pubout 2>/dev/null)
  if [ -z "${privkey}" ]; then warn "openssl missing — tokens will not survive restart"; return; fi
  local pb eb
  pb=$(printf '%s' "${privkey}" | base64 | tr -d '\n')
  eb=$(printf '%s' "${pubkey}" | base64 | tr -d '\n')
  kubectl patch secret abenix-secrets -n "${NAMESPACE}" --type='json' \
    -p="[
      {\"op\":\"add\",\"path\":\"/data/JWT_PRIVATE_KEY\",\"value\":\"${pb}\"},
      {\"op\":\"add\",\"path\":\"/data/JWT_PUBLIC_KEY\",\"value\":\"${eb}\"}
    ]" &>/dev/null || true
  ok "JWT keys generated"
}

run_migrations() {
  step "Ensuring abenix database + tables + schema is current"
  local pg
  pg=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=postgresql" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [ -n "${pg}" ]; then
    kubectl exec -n "${NAMESPACE}" "${pg}" -- bash -c \
      'PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = '"'"'abenix'"'"'" | grep -q 1 || PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -c "CREATE DATABASE abenix"' 2>/dev/null
    ok "Database ready"
  fi

  # Wait for an API pod that we can run alembic against. The pod
  # ships /app/packages/db with the Alembic config + migrations.
  local api_pod="" tries=0
  while [ -z "${api_pod}" ] && [ "$tries" -lt 30 ]; do
    api_pod=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=api" \
      --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    [ -n "${api_pod}" ] && break
    sleep 3
    tries=$((tries + 1))
  done

  if [ -n "${api_pod}" ]; then
    log "Running alembic upgrade head via ${api_pod}..."
    kubectl exec -n "${NAMESPACE}" "${api_pod}" -- bash -c \
      'cd /app/packages/db && python -m alembic upgrade head' 2>&1 | tail -10 || true

    # Schema-drift sentinel: a small set of canonical columns that
    # MUST exist after alembic upgrade head. If any is missing the
    # catchup migration didn't fully apply — fail loud so prod
    # rollouts don't proceed against a half-migrated database.
    log "Verifying schema sentinels in live database..."
    local missing=""
    for col in \
      "executions:node_results" \
      "executions:execution_trace" \
      "executions:failure_code" \
      "agent_shares:shared_with_user_id" \
      "moderation_policies:default_action"; do
      local table="${col%:*}"
      local column="${col#*:}"
      local exists
      exists=$(kubectl exec -n "${NAMESPACE}" "${pg}" -- bash -c \
        "PGPASSWORD=\$POSTGRES_PASSWORD psql -U postgres -d abenix -tAc \"SELECT 1 FROM information_schema.columns WHERE table_name='${table}' AND column_name='${column}'\"" \
        2>/dev/null | tr -d '[:space:]')
      [ "${exists}" = "1" ] || missing="${missing} ${table}.${column}"
    done

    if [ -n "${missing}" ]; then
      err "Schema drift after alembic — missing columns:${missing}"
      err "Inspect packages/db/alembic/versions/x4y5z6a7b8c9_schema_drift_catchup.py"
      err "Production rollout aborted — DB is not at the expected schema."
      exit 6
    fi
    ok "Schema verified — all sentinel columns present"
  else
    warn "No ready API pod — skipping alembic + schema verification"
  fi

  kubectl -n "${NAMESPACE}" rollout restart deployment -l "app.kubernetes.io/name=api" 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout status deployment -l "app.kubernetes.io/name=api" --timeout=180s 2>&1 | tail -1 || true
  # Same trick for web — when IMAGE_TAG matches what's already deployed
  # (e.g. uncommitted source edits in --only=web rebuilds), Helm produces
  # no new manifest hash and won't recreate pods, so the new digest just
  # sits in ACR. Force a rollout so pullPolicy: Always actually pulls.
  if [ -z "${ONLY_CSV}" ] || _should_do "web"; then
    kubectl -n "${NAMESPACE}" rollout restart deploy/abenix-web 2>&1 | tail -1 || true
    kubectl -n "${NAMESPACE}" rollout status deploy/abenix-web --timeout=180s 2>&1 | tail -1 || true
  fi
}

seed_agents() {
  step "Seeding agents + portfolio schemas + sample ML models"

  # Pre-flight: lint every agent YAML against the strict schema BEFORE
  # we ship anything to the cluster. Catches the ClaimsIQ-class silent-
  # coerce bug (pipeline_config nested under model_config) at deploy
  # time, not 2-5s into a production execution.
  if [ -f "${ROOT_DIR}/scripts/lint-agent-seeds.py" ]; then
    log "Linting agent YAMLs against strict schema..."
    if ! python "${ROOT_DIR}/scripts/lint-agent-seeds.py"; then
      err "Agent seed lint failed — refusing to seed a broken catalog"
      return 1
    fi
  fi

  local api_pod=""
  for i in $(seq 1 30); do
    api_pod=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=api" \
      --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -n "${api_pod}" ]; then
      local ready
      ready=$(kubectl get pod "${api_pod}" -n "${NAMESPACE}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)
      [ "${ready}" = "True" ] && break
    fi
    sleep 3
  done
  if [ -z "${api_pod}" ]; then warn "No ready API pod — skipping seed"; return; fi
  log "Seeding via ${api_pod}..."
  # seed_kb runs AFTER seed_agents because it grants collections to agents by slug.
  local seed_failed=0
  for script in seed_agents.py seed_users.py seed_portfolio_schemas.py seed_ml_models.py seed_kb.py; do
    # Capture exit code via a temp file because we still want to show
    # the last 10 lines of output. The seed_agents.py loader now exits
    # non-zero on schema validation failure (the ClaimsIQ fix); this
    # block surfaces that to the deploy script.
    local _rc=0
    kubectl exec -n "${NAMESPACE}" "${api_pod}" -- bash -c "python /app/packages/db/seeds/${script}" 2>&1 | tail -10 || _rc=$?
    if [ "${_rc}" != "0" ]; then
      err "Seed ${script} exited ${_rc}"
      seed_failed=1
    fi
  done
  if [ "${seed_failed}" = "1" ]; then
    err "One or more seed scripts failed — agent catalog may be broken"
    return 1
  fi
  ok "Seeding complete"
}

deploy_livekit() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "livekit"; then return 0; fi
  step "Deploying LiveKit (in-cluster)"
  local manifest="${ROOT_DIR}/infra/k8s/livekit-dev.yaml"
  if [ ! -f "${manifest}" ]; then warn "livekit manifest missing — skip"; return; fi
  kubectl apply -f "${manifest}" -n "${NAMESPACE}" 2>&1 | tail -3
  kubectl -n "${NAMESPACE}" rollout status deploy/livekit-server --timeout=120s 2>&1 | tail -1 || true
  local existing_url
  existing_url=$(kubectl -n "${NAMESPACE}" get deploy/abenix-api \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LIVEKIT_URL")].value}' 2>/dev/null)
  if [ -z "${existing_url}" ]; then
    kubectl -n "${NAMESPACE}" set env deploy/abenix-api \
      LIVEKIT_URL="ws://livekit-server.${NAMESPACE}.svc.cluster.local:7880" \
      LIVEKIT_API_KEY=devkey \
      LIVEKIT_API_SECRET=secret \
      LIVEKIT_PUBLIC_URL="wss://livekit.example.com" \
      LIVEKIT_MEET_URL="https://meet.livekit.io" 2>&1 | tail -1
    kubectl -n "${NAMESPACE}" rollout status deploy/abenix-api --timeout=180s 2>&1 | tail -1 || true
  fi
  ok "LiveKit ready"
}

# Generate a fresh Abenix platform API key inside the Azure cluster
# (the local .env key is tied to the minikube DB and won't work here).
# Returns the API key string on stdout, empty on failure.
_generate_abenix_api_key() {
  local api_pod
  api_pod=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=api" \
    --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [ -z "${api_pod}" ]; then return 1; fi
  # Run a one-shot python that creates a platform API key for the system user
  # with can_delegate scope (same setup deploy.sh relies on implicitly).
  kubectl exec -n "${NAMESPACE}" "${api_pod}" -c api -- python -c "
import asyncio, hashlib, os, secrets, sys
sys.path.insert(0, '/app/packages/db')
from models.api_key import ApiKey
from models.user import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

async def run():
    eng = create_async_engine(os.environ['DATABASE_URL'], echo=False)
    sf = async_sessionmaker(eng, expire_on_commit=False)
    async with sf() as db:
        u = (await db.execute(
            select(User).where(User.email.in_(['system@abenix.dev','admin@abenix.dev']))
            .order_by(User.email.desc())
        )).scalars().first()
        if u is None:
            raise SystemExit('no admin/system user seeded')
        raw = 'af_' + secrets.token_urlsafe(40)
        key = ApiKey(
            user_id=u.id,
            tenant_id=u.tenant_id,
            name='platform-bootstrap',
            key_prefix=raw[:8],
            key_hash=hashlib.sha256(raw.encode()).hexdigest(),
            scopes={'allowed_actions': ['can_delegate', 'execute', 'read']},
            is_active=True,
        )
        db.add(key)
        await db.commit()
        print(raw)
    await eng.dispose()
asyncio.run(run())
" 2>/dev/null | tail -1
}

# Mint a platform-internal key + patch abenix-secrets so the api pod's
# self-callbacks (e.g. SDK._resolve_agent_id from /api/conversations/{id}/turn)
# can authenticate against /api/agents.
_wire_abenix_platform_key() {
  log "  Wiring ABENIX_PLATFORM_API_KEY into abenix-secrets..."
  local pk
  pk=$(_generate_abenix_api_key || echo "")
  if [ -z "${pk}" ] || [[ "${pk}" != af_* ]]; then
    warn "  Could not mint platform key — chat self-callbacks will 401."
    return 1
  fi
  kubectl patch secret -n "${NAMESPACE}" abenix-secrets --type=json \
    -p="[{\"op\":\"add\",\"path\":\"/data/ABENIX_PLATFORM_API_KEY\",\"value\":\"$(echo -n "${pk}" | base64 -w0)\"}]" 2>&1 | tail -1
  kubectl -n "${NAMESPACE}" rollout restart deploy/abenix-api 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout status deploy/abenix-api --timeout=120s 2>&1 | tail -1 || true
  ok "  ABENIX_PLATFORM_API_KEY wired (prefix ${pk:0:10}…)"
}

deploy_example_app() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "example_app-api" && ! _should_do "example_app-web"; then return 0; fi
  local manifest="${ROOT_DIR}/example_app/k8s/example_app.yaml"
  if [ ! -f "${manifest}" ]; then warn "the example app manifest missing — skip"; return; fi

  step "Deploying the example app"
  local ciq_key="${EXAMPLE_APP_ABENIX_API_KEY:-}"
  # If caller key is empty OR this is a fresh Abenix DB, mint a new key.
  if [ -z "${ciq_key}" ]; then
    log "  Minting a fresh Abenix API key for the example app..."
    ciq_key=$(_generate_abenix_api_key || echo "")
    if [ -n "${ciq_key}" ]; then
      ok "  Key minted (prefix ${ciq_key:0:10}...)"
    else
      warn "  Could not mint key — using placeholder; chat will fail until a key is wired"
      ciq_key="PLACEHOLDER_CHANGE_ME"
    fi
  fi
  local ciq_jwt="${EXAMPLE_APP_JWT_SECRET:-example_app-dev-secret-please-change}"
  local anth_key="${ANTHROPIC_API_KEY:-}"

  # Apply the secret with real values FIRST so any pod created by the
  # subsequent manifest apply picks up the live key, not the manifest's
  # REPLACE_AT_DEPLOY_TIME placeholder.
  kubectl create secret generic example_app-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=EXAMPLE_APP_ABENIX_API_KEY="${ciq_key}" \
    --from-literal=EXAMPLE_APP_JWT_SECRET="${ciq_jwt}" \
    --from-literal=ANTHROPIC_API_KEY="${anth_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -2

  # Strip the manifest's stringData Secret document so it doesn't
  # overwrite the live secret we just applied. Buffer each YAML
  # document between `---` separators; flush only the non-Secret ones.
  sed \
    -e "s|localhost:5000/abenix/example_app-api:latest|${ACR_LOGIN_SERVER}/example_app-api:${IMAGE_TAG}|g" \
    -e "s|localhost:5000/abenix/example_app-web:latest|${ACR_LOGIN_SERVER}/example_app-web:${IMAGE_TAG}|g" \
    -e "s|imagePullPolicy: IfNotPresent|imagePullPolicy: Always|g" \
    "${manifest}" | python -c "
import sys, yaml
docs = list(yaml.safe_load_all(sys.stdin))
out = [d for d in docs if d and d.get('kind') != 'Secret']
print(yaml.safe_dump_all(out))
" | kubectl apply -f - 2>&1 | tail -5

  # Force a rollout so pods pick up the freshly-applied secret keys
  # even when the manifest apply was a no-op.
  kubectl -n "${NAMESPACE}" rollout restart deploy/example_app-api 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout restart deploy/example_app-web 2>&1 | tail -1 || true

  kubectl -n "${NAMESPACE}" rollout status deploy/example_app-api --timeout=180s 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout status deploy/example_app-web --timeout=180s 2>&1 | tail -1 || true
  ok "the example app deployed"
}

deploy_sauditourism() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "sauditourism-api" && ! _should_do "sauditourism-web"; then return 0; fi
  local manifest="${ROOT_DIR}/sauditourism/k8s/sauditourism.yaml"
  if [ ! -f "${manifest}" ]; then warn "Saudi Tourism manifest missing — skip"; return; fi

  step "Deploying Saudi Tourism"
  local st_key="${SAUDITOURISM_ABENIX_API_KEY:-}"
  if [ -z "${st_key}" ]; then
    # Reuse the the example app key if it was just minted (same tenant, same Abenix),
    # otherwise mint a fresh one for SauditTourism.
    st_key=$(kubectl get secret example_app-secrets -n "${NAMESPACE}" \
      -o jsonpath='{.data.EXAMPLE_APP_ABENIX_API_KEY}' 2>/dev/null | base64 -d 2>/dev/null)
    if [ -z "${st_key}" ] || [ "${st_key}" = "PLACEHOLDER_CHANGE_ME" ]; then
      log "  Minting Abenix API key for Saudi Tourism..."
      st_key=$(_generate_abenix_api_key || echo "PLACEHOLDER_CHANGE_ME")
    fi
  fi
  local st_jwt="${SAUDITOURISM_JWT_SECRET:-saudi-tourism-dev-secret}"

  sed \
    -e "s|localhost:5000/abenix/sauditourism-api:latest|${ACR_LOGIN_SERVER}/sauditourism-api:${IMAGE_TAG}|g" \
    -e "s|localhost:5000/abenix/sauditourism-web:latest|${ACR_LOGIN_SERVER}/sauditourism-web:${IMAGE_TAG}|g" \
    -e "s|imagePullPolicy: IfNotPresent|imagePullPolicy: Always|g" \
    "${manifest}" | kubectl apply -f - 2>&1 | tail -5

  if _should_do "sauditourism-api" && ! _should_do "sauditourism-web"; then
    kubectl -n "${NAMESPACE}" rollout restart deploy/sauditourism-api 2>&1 | tail -1 || true
  elif _should_do "sauditourism-web" && ! _should_do "sauditourism-api"; then
    kubectl -n "${NAMESPACE}" rollout restart deploy/sauditourism-web 2>&1 | tail -1 || true
  fi

  kubectl create secret generic sauditourism-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=SAUDITOURISM_ABENIX_API_KEY="${st_key}" \
    --from-literal=SAUDITOURISM_JWT_SECRET="${st_jwt}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -2

  kubectl -n "${NAMESPACE}" rollout status deploy/sauditourism-api --timeout=180s 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout status deploy/sauditourism-web --timeout=180s 2>&1 | tail -1 || true
  ok "Saudi Tourism deployed"
}

deploy_industrial_iot() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "industrial-iot-api" && ! _should_do "industrial-iot-web"; then return 0; fi
  local manifest="${ROOT_DIR}/industrial-iot/k8s/industrial-iot.yaml"
  if [ ! -f "${manifest}" ]; then warn "Industrial-IoT manifest missing — skip"; return; fi

  step "Deploying Industrial-IoT"
  local iot_key="${INDUSTRIALIOT_ABENIX_API_KEY:-}"
  if [ -z "${iot_key}" ]; then
    # Reuse an existing tenant key if one's already minted; else mint fresh.
    iot_key=$(kubectl get secret example_app-secrets -n "${NAMESPACE}" \
      -o jsonpath='{.data.EXAMPLE_APP_ABENIX_API_KEY}' 2>/dev/null | base64 -d 2>/dev/null)
    if [ -z "${iot_key}" ] || [ "${iot_key}" = "PLACEHOLDER_CHANGE_ME" ]; then
      log "  Minting Abenix API key for Industrial-IoT..."
      iot_key=$(_generate_abenix_api_key || echo "PLACEHOLDER_CHANGE_ME")
    fi
  fi

  sed \
    -e "s|localhost:5000/abenix/industrial-iot-api:latest|${ACR_LOGIN_SERVER}/industrial-iot-api:${IMAGE_TAG}|g" \
    -e "s|localhost:5000/abenix/industrial-iot-web:latest|${ACR_LOGIN_SERVER}/industrial-iot-web:${IMAGE_TAG}|g" \
    -e "s|imagePullPolicy: IfNotPresent|imagePullPolicy: Always|g" \
    "${manifest}" | kubectl apply -f - 2>&1 | tail -5

  kubectl create secret generic industrial-iot-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=INDUSTRIALIOT_ABENIX_API_KEY="${iot_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -2

  if _should_do "industrial-iot-api" && ! _should_do "industrial-iot-web"; then
    kubectl -n "${NAMESPACE}" rollout restart deploy/industrial-iot-api 2>&1 | tail -1 || true
  elif _should_do "industrial-iot-web" && ! _should_do "industrial-iot-api"; then
    kubectl -n "${NAMESPACE}" rollout restart deploy/industrial-iot-web 2>&1 | tail -1 || true
  fi

  kubectl -n "${NAMESPACE}" rollout status deploy/industrial-iot-api --timeout=180s 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout status deploy/industrial-iot-web --timeout=180s 2>&1 | tail -1 || true
  ok "Industrial-IoT deployed"
}

deploy_resolveai() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "resolveai-api" && ! _should_do "resolveai-web"; then return 0; fi
  local manifest="${ROOT_DIR}/resolveai/k8s/resolveai.yaml"
  if [ ! -f "${manifest}" ]; then warn "ResolveAI manifest missing — skip"; return; fi

  step "Deploying ResolveAI"
  local ra_key="${RESOLVEAI_ABENIX_API_KEY:-}"
  if [ -z "${ra_key}" ]; then
    ra_key=$(kubectl get secret example_app-secrets -n "${NAMESPACE}" \
      -o jsonpath='{.data.EXAMPLE_APP_ABENIX_API_KEY}' 2>/dev/null | base64 -d 2>/dev/null)
    if [ -z "${ra_key}" ] || [ "${ra_key}" = "PLACEHOLDER_CHANGE_ME" ]; then
      log "  Minting Abenix API key for ResolveAI..."
      ra_key=$(_generate_abenix_api_key || echo "PLACEHOLDER_CHANGE_ME")
    fi
  fi

  sed \
    -e "s|localhost:5000/abenix/resolveai-api:latest|${ACR_LOGIN_SERVER}/resolveai-api:${IMAGE_TAG}|g" \
    -e "s|localhost:5000/abenix/resolveai-web:latest|${ACR_LOGIN_SERVER}/resolveai-web:${IMAGE_TAG}|g" \
    -e "s|imagePullPolicy: IfNotPresent|imagePullPolicy: Always|g" \
    "${manifest}" | kubectl apply -f - 2>&1 | tail -5

  kubectl create secret generic resolveai-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=RESOLVEAI_ABENIX_API_KEY="${ra_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -2

  if _should_do "resolveai-api" && ! _should_do "resolveai-web"; then
    kubectl -n "${NAMESPACE}" rollout restart deploy/resolveai-api 2>&1 | tail -1 || true
  elif _should_do "resolveai-web" && ! _should_do "resolveai-api"; then
    kubectl -n "${NAMESPACE}" rollout restart deploy/resolveai-web 2>&1 | tail -1 || true
  fi

  kubectl -n "${NAMESPACE}" rollout status deploy/resolveai-api --timeout=180s 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout status deploy/resolveai-web --timeout=180s 2>&1 | tail -1 || true
  ok "ResolveAI deployed"
}

deploy_claimsiq() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "claimsiq"; then return 0; fi
  local manifest="${ROOT_DIR}/claimsiq/k8s/claimsiq.yaml"
  if [ ! -f "${manifest}" ]; then warn "ClaimsIQ manifest missing — skip"; return; fi

  step "Deploying ClaimsIQ"
  local cq_key="${CLAIMSIQ_ABENIX_API_KEY:-}"
  if [ -z "${cq_key}" ]; then
    # Reuse an existing tenant key if one's already minted; else mint fresh.
    cq_key=$(kubectl get secret example_app-secrets -n "${NAMESPACE}" \
      -o jsonpath='{.data.EXAMPLE_APP_ABENIX_API_KEY}' 2>/dev/null | base64 -d 2>/dev/null)
    if [ -z "${cq_key}" ] || [ "${cq_key}" = "PLACEHOLDER_CHANGE_ME" ]; then
      log "  Minting Abenix API key for ClaimsIQ..."
      cq_key=$(_generate_abenix_api_key || echo "PLACEHOLDER_CHANGE_ME")
    fi
  fi

  sed \
    -e "s|localhost:5000/abenix/claimsiq:latest|${ACR_LOGIN_SERVER}/claimsiq:${IMAGE_TAG}|g" \
    -e "s|imagePullPolicy: IfNotPresent|imagePullPolicy: Always|g" \
    "${manifest}" | kubectl apply -f - 2>&1 | tail -5

  if _should_do "claimsiq"; then
    kubectl -n "${NAMESPACE}" rollout restart deploy/claimsiq 2>&1 | tail -1 || true
  fi

  kubectl create secret generic claimsiq-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=CLAIMSIQ_ABENIX_API_KEY="${cq_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -2

  # JVM cold start on a fresh pod is slow — 240s is generous but saves
  # a false-positive rollout failure when the Vaadin frontend bundle is
  # still being exploded.
  kubectl -n "${NAMESPACE}" rollout status deploy/claimsiq --timeout=240s 2>&1 | tail -1 || true
  ok "ClaimsIQ deployed"
}

install_observability() {
  if [ "${SKIP_OBSERVABILITY:-false}" = "true" ]; then return 0; fi
  if [ -n "${ONLY_CSV}" ] && ! _should_do "observability"; then return 0; fi
  step "Installing observability stack (Prometheus + Grafana)"
  local dir="${ROOT_DIR}/infra/observability"
  if [ ! -f "${dir}/prometheus.yaml" ]; then warn "observability manifests missing — skip"; return; fi

  if compgen -G "${dir}/dashboards/*.json" >/dev/null; then
    local kc_args=()
    for f in "${dir}"/dashboards/*.json; do
      kc_args+=(--from-file="$(basename "$f")=$f")
    done
    kubectl create configmap abenix-grafana-dashboards -n "${NAMESPACE}" "${kc_args[@]}" \
      --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -1
  fi
  kubectl apply -f "${dir}/prometheus.yaml" -n "${NAMESPACE}" 2>&1 | tail -1
  kubectl apply -f "${dir}/grafana.yaml"    -n "${NAMESPACE}" 2>&1 | tail -1
  kubectl rollout restart deployment/abenix-grafana -n "${NAMESPACE}" 2>&1 | tail -1 || true
  kubectl wait --for=condition=Available --timeout=120s deploy/abenix-prometheus -n "${NAMESPACE}" 2>&1 | tail -1 || true
  kubectl wait --for=condition=Available --timeout=120s deploy/abenix-grafana -n "${NAMESPACE}" 2>&1 | tail -1 || true
  ok "Observability ready"
}

# Create a single ingress routing all three web apps + APIs through the
# ingress-nginx LoadBalancer IP. This replaces the local port-forwards.
setup_ingress() {
  step "Configuring Ingress for public access"
  local lb_ip
  lb_ip=$(kubectl -n ingress-nginx get svc ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
  local i=0
  while [ -z "${lb_ip}" ] && [ $i -lt 30 ]; do
    sleep 5
    lb_ip=$(kubectl -n ingress-nginx get svc ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
    i=$((i+1))
  done
  if [ -z "${lb_ip}" ]; then warn "LoadBalancer IP not yet assigned — ingress will be reachable once Azure assigns one"; return; fi

  log "LoadBalancer IP: ${lb_ip}"
  local host="${lb_ip}.nip.io"

  cat <<EOF | kubectl apply -f - 2>&1 | tail -3
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: abenix-ingress
  namespace: ${NAMESPACE}
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
spec:
  ingressClassName: nginx
  rules:
    - host: ${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: ${RELEASE_NAME}-web, port: { number: 3000 } } }
    - host: ciq.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: example_app-web, port: { number: 3001 } } }
    - host: tourism.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: sauditourism-web, port: { number: 3002 } } }
    - host: iot.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: industrial-iot-web, port: { number: 3003 } } }
    - host: care.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: resolveai-web, port: { number: 3004 } } }
    - host: claims.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: claimsiq, port: { number: 3005 } } }
    - host: api.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: ${RELEASE_NAME}-api, port: { number: 8000 } } }
    - host: ciq-api.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: example_app-api, port: { number: 8001 } } }
    - host: tourism-api.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: sauditourism-api, port: { number: 8002 } } }
EOF

  echo "${host}" > "${ROOT_DIR}/.azure-endpoint"

  # Stamp NEXT_PUBLIC_ABENIX_WEB_URL on standalone web deployments so
  # cross-app links ("/executions", "/code-runner") point at the abenix
  # web ingress rather than 404'ing on the standalone origin.
  local abenix_web_url="http://${host}"
  for dep in industrial-iot-web example_app-web sauditourism-web resolveai-web claimsiq; do
    if kubectl -n "${NAMESPACE}" get deploy "${dep}" >/dev/null 2>&1; then
      kubectl -n "${NAMESPACE}" set env deploy/"${dep}" \
        NEXT_PUBLIC_ABENIX_WEB_URL="${abenix_web_url}" 2>&1 | tail -1 || true
    fi
  done

  ok "Ingress ready: http://${host}  (ciq.${host}, tourism.${host}, iot.${host}, care.${host}, claims.${host})"
}

deploy_all() {
  check_prereqs
  # Ensure ACR_LOGIN_SERVER is set
  if [ -z "${ACR_LOGIN_SERVER:-}" ]; then
    ACR_LOGIN_SERVER=$(az acr show -n "${ACR_NAME}" --query loginServer -o tsv 2>/dev/null || true)
    if [ -z "${ACR_LOGIN_SERVER}" ]; then err "ACR ${ACR_NAME} missing — run provision first"; exit 4; fi
  fi
  # Make sure kubectl is targeting the AKS cluster
  az aks get-credentials -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" --overwrite-existing &>/dev/null || true

  step "Phase 3/5 — Deploying all workloads (ONLY=${ONLY_CSV:-<all>})"

  # Idempotent: also ensure KEDA when entering deploy directly (skipping provision).
  ensure_keda || warn "KEDA install failed — ScaledObject resources will fail"
  deploy_abenix_helm
  wait_for_pods 600 || true
  ensure_jwt_keys || true
  run_migrations || true
  seed_agents || true
  _wire_abenix_platform_key || true
  deploy_livekit || warn "LiveKit deploy failed (non-fatal)"
  deploy_example_app || warn "the example app deploy failed (non-fatal)"
  deploy_sauditourism || warn "Saudi Tourism deploy failed (non-fatal)"
  deploy_industrial_iot || warn "Industrial-IoT deploy failed (non-fatal)"
  deploy_resolveai || warn "ResolveAI deploy failed (non-fatal)"
  deploy_claimsiq || warn "ClaimsIQ deploy failed (non-fatal)"
  # Phase 4 — idempotent ABENIX_API_KEY reconciliation. Every standalone
  # secret is validated against the platform api_keys table; orphaned keys
  # (DB was reseeded but secret kept its stale hash) are rotated and the
  # affected deployments are restarted. This is what makes a fresh
  # `deploy-azure.sh deploy` produce a working chat path with zero manual
  # post-install steps.
  seed_standalone_keys || warn "Standalone key seed failed (chat will 401 in some apps)"
  install_observability || warn "Observability install failed (non-fatal)"
  setup_ingress || warn "Ingress setup failed — you can still port-forward"

  ok "Deployment complete"
}

# Wrapper around scripts/seed-standalone-keys.sh — runs the per-app loop
# that mints / rotates / patches each standalone secret idempotently.
seed_standalone_keys() {
  if [ -n "${ONLY_CSV}" ]; then
    # When --only is set, only run the reseed if the user is touching
    # standalone-related groups.
    case "${ONLY_CSV}" in
      *example_app*|*sauditourism*|*industrial-iot*|*resolveai*|*claimsiq*) ;;
      *) return 0 ;;
    esac
  fi
  step "Phase 4 — Reconcile standalone ABENIX_API_KEYs"
  NAMESPACE="${NAMESPACE}" bash "${ROOT_DIR}/scripts/seed-standalone-keys.sh" 2>&1 \
    | sed 's/^/      /' || return 1
}

# PHASE 4: Status + health check
get_endpoint() {
  if [ -f "${ROOT_DIR}/.azure-endpoint" ]; then
    cat "${ROOT_DIR}/.azure-endpoint"
  else
    local lb_ip
    lb_ip=$(kubectl -n ingress-nginx get svc ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null)
    if [ -n "${lb_ip}" ]; then echo "${lb_ip}.nip.io"; fi
  fi
}

deploy_status() {
  step "Deployment status"

  echo -e "\n${BOLD}Cluster:${NC}"
  kubectl cluster-info 2>&1 | head -2 || true

  echo -e "\n${BOLD}Pods (${NAMESPACE}):${NC}"
  kubectl get pods -n "${NAMESPACE}" 2>/dev/null || warn "Namespace ${NAMESPACE} not found"

  echo -e "\n${BOLD}Services:${NC}"
  kubectl get svc -n "${NAMESPACE}" 2>/dev/null | head -20 || true

  local host
  host=$(get_endpoint)
  if [ -z "${host}" ]; then
    warn "No ingress endpoint yet"
    return
  fi

  echo -e "\n${BOLD}Public URLs:${NC}"
  echo -e "  ${CYAN}Abenix Web${NC}    http://${host}"
  echo -e "  ${CYAN}the example app Web${NC}    http://ciq.${host}"
  echo -e "  ${CYAN}Saudi Tourism${NC}     http://tourism.${host}"
  echo -e "  ${CYAN}ClaimsIQ${NC}          http://claims.${host}"
  echo -e "  ${CYAN}Abenix API${NC}    http://api.${host}/api/health"
  echo -e "  ${CYAN}the example app API${NC}    http://ciq-api.${host}/api/health"
  echo -e "  ${CYAN}Saudi Tourism API${NC} http://tourism-api.${host}/api/health"
  echo -e "  ${CYAN}ClaimsIQ Health${NC}   http://claims.${host}/actuator/health"

  echo -e "\n${BOLD}Health checks:${NC}"
  for u in "http://${host}" "http://ciq.${host}" "http://tourism.${host}" "http://claims.${host}/actuator/health/liveness" \
           "http://api.${host}/api/health" "http://ciq-api.${host}/api/health" "http://tourism-api.${host}/api/health"; do
    local code
    code=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" "${u}" 2>/dev/null || echo "---")
    if [ "${code}" = "200" ] || [ "${code}" = "301" ] || [ "${code}" = "307" ]; then
      echo -e "  ${GREEN}${code}${NC}  ${u}"
    else
      echo -e "  ${YELLOW}${code}${NC}  ${u}"
    fi
  done
}

# PHASE 5: End-to-end Playwright tests against the AKS endpoint
deploy_test() {
  step "Phase 5/5 — Running Playwright E2E suites against AKS"
  local host
  host=$(get_endpoint)
  if [ -z "${host}" ]; then err "No ingress endpoint. Run 'deploy-azure.sh deploy' first."; exit 7; fi
  ok "Target: http://${host}"

  local project="${E2E_PROJECT:-all}"
  local af_base="http://${host}"
  local af_api="http://api.${host}"
  local ciq_base="http://ciq.${host}"
  local ciq_api="http://ciq-api.${host}"
  local st_base="http://tourism.${host}"
  local st_api="http://tourism-api.${host}"

  local total_passed=0 total_failed=0 suite_failures=()

  run_suite() {
    local name="$1"; local dir="$2"; shift 2
    log "Running ${name} (dir=${dir})"
    pushd "${dir}" >/dev/null
    # shellcheck disable=SC2068
    if env "$@" npx playwright test --reporter=list --timeout=600000 2>&1 | tee "/tmp/pw-${name}.log" | tail -20; then
      ok "${name}: PASS"
      total_passed=$((total_passed+1))
    else
      warn "${name}: FAIL"
      total_failed=$((total_failed+1))
      suite_failures+=("${name}")
    fi
    popd >/dev/null
  }

  if [ "${project}" = "all" ] || [ "${project}" = "example_app" ]; then
    run_suite "example_app-wave1" "${ROOT_DIR}/example_app" \
      BASE_URL="${ciq_base}" API_URL="${ciq_api}" \
      -- --grep "^Wave 1" || true
    run_suite "example_app-wave2" "${ROOT_DIR}/example_app" \
      BASE_URL="${ciq_base}" API_URL="${ciq_api}" \
      -- --grep "^Wave 2" || true
  fi

  if [ "${project}" = "all" ] || [ "${project}" = "sauditourism" ]; then
    run_suite "sauditourism" "${ROOT_DIR}/sauditourism" \
      BASE_URL="${st_base}" API_URL="${st_api}" \
      || true
  fi

  if [ "${project}" = "all" ] || [ "${project}" = "abenix" ]; then
    local suites="${E2E_ONLY:-uat_abenix_browser.spec.ts,uat_abenix_deep.spec.ts,uat_abenix_industrial.spec.ts}"
    local files=""
    IFS=',' read -ra arr <<< "${suites}"
    for s in "${arr[@]}"; do
      [ -f "${ROOT_DIR}/e2e/${s}" ] && files+="e2e/${s} "
    done
    if [ -n "${files}" ]; then
      run_suite "abenix" "${ROOT_DIR}" \
        BASE_URL="${af_base}" API_URL="${af_api}" PLAYWRIGHT_BASE_URL="${af_base}" \
        -- ${files}
    else
      warn "No Abenix E2E files matched — skip"
    fi
  fi

  echo ""
  step "Test summary"
  echo -e "  ${GREEN}${total_passed} suite(s) PASS${NC}"
  if [ ${total_failed} -gt 0 ]; then
    echo -e "  ${RED}${total_failed} suite(s) FAIL:${NC} ${suite_failures[*]}"
    exit 7
  fi
  ok "All E2E suites green"
}

# Destroy — tear down everything (or just helm/namespace if --keep-cluster)
deploy_destroy() {
  step "Destroying deployment"
  # Kill any port-forwards from a previous run
  pkill -f "kubectl port-forward.*${NAMESPACE}" 2>/dev/null || true

  if kubectl get ns "${NAMESPACE}" &>/dev/null; then
    kubectl delete -n "${NAMESPACE}" ingress --all --timeout=60s 2>&1 | tail -1 || true
    if helm status "${RELEASE_NAME}" -n "${NAMESPACE}" &>/dev/null; then
      helm uninstall "${RELEASE_NAME}" -n "${NAMESPACE}" --wait 2>&1 | tail -2 || true
    fi
    kubectl delete -n "${NAMESPACE}" deploy/example_app-api deploy/example_app-web deploy/sauditourism-api deploy/sauditourism-web deploy/claimsiq 2>/dev/null || true
    kubectl delete -n "${NAMESPACE}" svc/example_app-api svc/example_app-web svc/sauditourism-api svc/sauditourism-web svc/claimsiq 2>/dev/null || true
    kubectl delete pvc --all -n "${NAMESPACE}" 2>/dev/null || true
    kubectl delete namespace "${NAMESPACE}" --timeout=120s 2>/dev/null || true
    ok "Namespace ${NAMESPACE} deleted"
  fi

  if [ "${KEEP_CLUSTER}" = "true" ]; then
    warn "KEEP_CLUSTER=true — leaving AKS + RG + ACR in place"
    return
  fi

  log "Deleting AKS cluster ${AKS_NAME}..."
  az aks delete -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" --yes --no-wait 2>&1 | tail -1 || true
  log "Deleting ACR ${ACR_NAME}..."
  az acr delete -n "${ACR_NAME}" -g "${AZ_RESOURCE_GROUP}" --yes 2>&1 | tail -1 || true
  log "Deleting resource group ${AZ_RESOURCE_GROUP}..."
  az group delete -n "${AZ_RESOURCE_GROUP}" --yes --no-wait 2>&1 | tail -1 || true
  rm -f "${ROOT_DIR}/.azure-endpoint"
  ok "Destroy initiated (async — Azure will finish in the background)"
}

# MAIN
case "${CMD}" in
  provision)  provision ;;
  build)      provision; build_and_push ;;
  deploy)
    check_prereqs
    ACR_LOGIN_SERVER=$(az acr show -n "${ACR_NAME}" --query loginServer -o tsv 2>/dev/null || true)
    if [ -z "${ACR_LOGIN_SERVER}" ]; then err "ACR missing — run provision first"; exit 4; fi
    az aks get-credentials -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" --overwrite-existing &>/dev/null || true
    if [ "${SKIP_BUILD}" != "true" ]; then
      build_and_push
    fi
    deploy_all
    ;;
  redeploy)
    check_prereqs
    ACR_LOGIN_SERVER=$(az acr show -n "${ACR_NAME}" --query loginServer -o tsv 2>/dev/null || true)
    if [ -z "${ACR_LOGIN_SERVER}" ]; then err "ACR missing — run provision first"; exit 4; fi
    az aks get-credentials -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" --overwrite-existing &>/dev/null || true
    if [ -z "${ONLY_CSV}" ]; then warn "redeploy without --only rebuilds everything (same as 'deploy')"; fi
    build_and_push
    deploy_all
    ;;
  seed)
    check_prereqs
    az aks get-credentials -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" --overwrite-existing &>/dev/null || true
    seed_agents
    # Always reconcile standalone keys after a manual reseed — agents/users
    # may have been recreated under fresh tenant IDs which would invalidate
    # the existing ABENIX_API_KEYs in standalone-secrets.
    NAMESPACE="${NAMESPACE}" bash "${ROOT_DIR}/scripts/seed-standalone-keys.sh" || true
    ;;
  seed-keys)
    check_prereqs
    az aks get-credentials -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" --overwrite-existing &>/dev/null || true
    NAMESPACE="${NAMESPACE}" bash "${ROOT_DIR}/scripts/seed-standalone-keys.sh"
    ;;
  test)
    check_prereqs
    az aks get-credentials -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" --overwrite-existing &>/dev/null || true
    deploy_test
    ;;
  status)
    check_prereqs
    az aks get-credentials -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" --overwrite-existing &>/dev/null || true
    deploy_status
    ;;
  destroy)
    check_prereqs
    az aks get-credentials -n "${AKS_NAME}" -g "${AZ_RESOURCE_GROUP}" --overwrite-existing &>/dev/null || true
    deploy_destroy
    ;;
  all)
    provision
    build_and_push
    deploy_all
    deploy_status
    deploy_test
    ;;
  ""|-h|--help|help)
    usage ;;
  *)
    err "Unknown command: ${CMD}"
    usage
    exit 1
    ;;
esac
