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

# Edge runtime images (edge-runtime, edge-runtime-rust, edge-runtime-c) are
# built ONCE per release and pinned by version in each chart's values.yaml.
# They are NOT rebuilt every deploy, so passing the current git SHA as
# image.tag has historically broken them (ImagePullBackOff against a tag
# the deploy never pushed — see the v1.5.x "abenix-edge-edge-runtime stuck"
# regression). Default to the empty string — the deploy script will then
# skip the --set image.tag override and the chart's pinned value wins.
# Operators cutting a new edge image can override with EDGE_IMAGE_TAG=1.2.0
# (or whatever they pushed to ACR by hand).
EDGE_IMAGE_TAG="${EDGE_IMAGE_TAG:-}"

# Set REAPER_DELETE_ORPHANS=true to authorise the reconcile phase to delete
# orphan deployments / statefulsets that aren't owned by any current helm
# release. Default is OFF — orphans are only warned about, never deleted
# without an explicit operator opt-in.
REAPER_DELETE_ORPHANS="${REAPER_DELETE_ORPHANS:-false}"

# ACR names must be globally unique AND 5-50 alphanumerics. Derive a stable
# suffix from the subscription+rg hash so repeated runs reuse the same ACR.
_default_acr_name() {
  local sub_id
  sub_id=$(az account show --query id -o tsv 2>/dev/null || echo "")
  if [ -z "${sub_id}" ]; then echo "your-acr-placeholder"; return; fi
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
  deploy            Helm-install Abenix + standalone apps (ContractIQ, Mideast Tourism).
                    Incremental — safe to re-run. --only=... supported.
  redeploy          Alias: build (per --only) + rollout restart (per --only).
  seed              Re-run agent / portfolio / ML model seed scripts, then
                    reconcile every standalone's ABENIX_API_KEY so chat works.
  seed-keys         Reconcile only the standalone ABENIX_API_KEYs (idempotent).
                    Mints any missing keys + patches secrets + restarts pods.
  test              Run all Playwright E2E suites against the AKS endpoints.
                    E2E_PROJECT=abenix|contractiq|mideasttourism to scope.
                    E2E_ONLY=test1.spec.ts,test2.spec.ts to run specific files.
  status            Report cluster, pods, services, ingress, and health endpoints.
  destroy           Uninstall helm + namespace. With KEEP_CLUSTER=false (default) also
                    deletes the AKS cluster + resource group.
  all               provision → build → deploy → seed → test (full green-field run).

Flags:
  --only=<list>     Comma-separated list of groups/services to act on.
                    Groups: abenix, contractiq, mideasttourism, observability, livekit
                    Services: api, web, worker, agent-runtime, cognify-worker,
                              contractiq-api, contractiq-web,
                              mideasttourism-api, mideasttourism-web
  --keep-cluster    On destroy: keep AKS + RG, only remove helm + namespace.
  --skip-build      On deploy: don't rebuild images (use whatever is in ACR).

Environment overrides: AZ_RESOURCE_GROUP, AZ_LOCATION, AKS_NAME, AKS_NODE_SIZE,
  AKS_NODE_COUNT, ACR_NAME, NAMESPACE, RELEASE_NAME, IMAGE_TAG,
  EDGE_IMAGE_TAG (pinned per-release version for edge runtimes; default ""
    keeps each chart's pinned values.yaml tag — DO NOT use the git SHA),
  REAPER_DELETE_ORPHANS=true (allow Phase 6 to delete orphan helm releases;
    default false — orphans are warned but not removed),
  RECONCILE_WAIT_SECS (Phase 6 settle window, default 300s).

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

  # Alembic graph guard — catches duplicate revision IDs and unmerged
  # heads before we ship an image whose db-migrate init container will
  # crashloop on the cluster.
  if [ "${SKIP_ALEMBIC_GRAPH_CHECK:-0}" != "1" ]; then
    step "Phase 0 — Alembic graph guard"
    if ! bash "${ROOT_DIR}/scripts/verify-alembic-graph.sh"; then
      err "Alembic graph is unhealthy. Fix duplicate revisions or merge unmerged heads."
      err "Set SKIP_ALEMBIC_GRAPH_CHECK=1 to bypass (NOT recommended)."
      exit 7
    fi
  fi
}

# Helper: --only parser
# Expand a group name into its service list, or pass through a service name.
_expand_only() {
  local token="$1"
  case "${token}" in
    abenix)     echo "api web worker agent-runtime cognify-worker code-runner-python code-runner-node" ;;
    contractiq)     echo "contractiq-api contractiq-web" ;;
    mideasttourism)   echo "mideasttourism-api mideasttourism-web" ;;
    industrial-iot) echo "industrial-iot-api industrial-iot-web" ;;
    resolveai)      echo "resolveai-api resolveai-web" ;;
    wingman)        echo "wingman-api wingman-web" ;;
    pharmavigil)    echo "pharmavigil-api pharmavigil-web" ;;
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

# ── Secret/config sanity gate ─────────────────────────────────────────
# The Azure OpenAI SDK appends /openai/deployments/<deploy>/... to
# AZURE_OPENAI_API_BASE / AZURE_OPENAI_ENDPOINT itself. A `.env` value
# like https://<resource>.openai.azure.com/openai/deployments leads to
# the SDK building https://...openai/deployments/openai/deployments/...
# (double-prefix), which 404s every chat call in production. Auto-strip
# the suffix and warn the operator so the .env gets fixed too.
#
# Also normalises live cluster secrets BEFORE the helm upgrade so a
# previously-broken value in abenix-secrets gets corrected on the next
# rollout, not silently carried forward.
_sanity_check_azure_endpoints() {
  step "Sanity gate — Azure OpenAI endpoint URLs"
  local fixed_any=false

  for var in AZURE_OPENAI_API_BASE AZURE_OPENAI_ENDPOINT; do
    local val="${!var:-}"
    [ -z "${val}" ] && continue
    # Strip trailing slash + the common bad suffix.
    local cleaned="${val%/}"
    cleaned="${cleaned%/openai/deployments}"
    cleaned="${cleaned%/openai}"
    if [ "${cleaned}" != "${val%/}" ]; then
      warn "${var} contained '/openai/deployments' (the SDK appends this itself)."
      warn "  was:    ${val}"
      warn "  using:  ${cleaned}"
      warn "  Please update .env to the cleaned value to avoid this warning."
      export "${var}=${cleaned}"
      fixed_any=true
    elif [[ "${val}" != http* ]]; then
      err "${var}='${val}' doesn't look like a URL (missing scheme). Aborting deploy."
      exit 6
    fi
  done

  # If a live secret already has the bad suffix, fix it in-cluster so
  # the pod rollout that follows picks up a correct value.
  if kubectl get secret abenix-secrets -n "${NAMESPACE}" >/dev/null 2>&1; then
    for key in AZURE_OPENAI_API_BASE AZURE_OPENAI_ENDPOINT; do
      local b64; b64=$(kubectl get secret abenix-secrets -n "${NAMESPACE}" \
        -o jsonpath="{.data.${key}}" 2>/dev/null || echo "")
      [ -z "${b64}" ] && continue
      local live; live=$(echo "${b64}" | base64 -d 2>/dev/null || echo "")
      [ -z "${live}" ] && continue
      local cleaned="${live%/}"
      cleaned="${cleaned%/openai/deployments}"
      cleaned="${cleaned%/openai}"
      if [ "${cleaned}" != "${live%/}" ]; then
        warn "Live abenix-secrets.${key} has '/openai/deployments' suffix — patching in-cluster."
        local new_b64; new_b64=$(printf '%s' "${cleaned}" | base64 | tr -d '\n')
        kubectl patch secret abenix-secrets -n "${NAMESPACE}" --type='json' \
          -p="[{\"op\":\"replace\",\"path\":\"/data/${key}\",\"value\":\"${new_b64}\"}]" \
          >/dev/null 2>&1 || true
        fixed_any=true
      fi
    done
  fi

  if [ "${fixed_any}" = "true" ]; then
    warn "Azure OpenAI endpoint values were normalised — proceeding."
  else
    ok "Azure OpenAI endpoint URLs look clean."
  fi
}

# ── Drift detectors (run alongside Phase 6 reconcile) ─────────────────
# 1) Configmaps not owned by a currently-installed helm release.
# 2) Deployments where managed-by isn't 'Helm' (raw kubectl apply
#    fingerprints — these miss every helm upgrade and silently drift).
# Both are surface-only — the operator decides whether to clean up.
_warn_unmanaged_configmaps() {
  local owned_pattern
  # Anything labelled with one of our helm release names is OK.
  owned_pattern=$(helm list -n "${NAMESPACE}" -q 2>/dev/null | paste -sd'|' -)
  if [ -z "${owned_pattern}" ]; then owned_pattern='__none__'; fi
  local unmanaged
  unmanaged=$(kubectl get configmap -n "${NAMESPACE}" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.labels.app\.kubernetes\.io/managed-by}{"\t"}{.metadata.labels.app\.kubernetes\.io/instance}{"\n"}{end}' 2>/dev/null \
    | awk -F'\t' -v pat="${owned_pattern}" '
        $1 == "" { next }
        $1 == "kube-root-ca.crt" { next }
        $2 != "Helm" { print $1 " (managed-by=" ($2 == "" ? "<none>" : $2) ")"; next }
        $3 !~ "^("pat")$" { print $1 " (instance=" $3 " not in current helm releases)"; }
      ')
  if [ -n "${unmanaged}" ]; then
    warn "  Unmanaged / stale configmap(s):"
    echo "${unmanaged}" | sed 's/^/      /'
  else
    ok "  All configmaps owned by current helm releases."
  fi
}

_warn_unmanaged_deployments() {
  local unmanaged
  unmanaged=$(kubectl get deploy -n "${NAMESPACE}" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.labels.app\.kubernetes\.io/managed-by}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}' 2>/dev/null \
    | awk -F'\t' '
        $1 == "" { next }
        $2 != "Helm" { print $1 "  managed-by=" ($2 == "" ? "<none>" : $2) "  image=" $3 }
      ')
  if [ -n "${unmanaged}" ]; then
    warn "  Deployment(s) NOT managed by Helm (won't get future helm upgrades):"
    echo "${unmanaged}" | sed 's/^/      /'
  else
    ok "  All Deployments are Helm-managed."
  fi
}

# Secrets helper (Helm --set flags, mirrors deploy.sh contract)
_build_secrets_flags() {
  local flags=""
  [ -n "${ANTHROPIC_API_KEY:-}" ]        && flags="${flags} --set secrets.anthropicApiKey=${ANTHROPIC_API_KEY}"
  [ -n "${EDGE_SIGNING_KEY_FILE:-}" ]    && flags="${flags} --set-file secrets.edgeSigningKeyPem=${EDGE_SIGNING_KEY_FILE}"
  [ -n "${EDGE_SIGNING_PUBKEY_FILE:-}" ] && flags="${flags} --set-file secrets.edgeSigningPubkeyPem=${EDGE_SIGNING_PUBKEY_FILE}"
  [ -n "${ABENIX_DATA_KEY_KEK_BASE64:-}" ] && flags="${flags} --set secrets.dataKeyKekBase64=${ABENIX_DATA_KEY_KEK_BASE64}"
  [ -n "${CLAUDE_SUBSCRIPTION_TOKEN:-}" ] && flags="${flags} --set secrets.claudeSubscriptionToken=${CLAUDE_SUBSCRIPTION_TOKEN}"
  [ -n "${OPENAI_API_KEY:-}" ]           && flags="${flags} --set secrets.openaiApiKey=${OPENAI_API_KEY}"
  [ -n "${GOOGLE_API_KEY:-}" ]           && flags="${flags} --set secrets.googleApiKey=${GOOGLE_API_KEY}"
  [ -n "${AZURE_OPENAI_API_KEY:-}" ]     && flags="${flags} --set secrets.azureOpenaiApiKey=${AZURE_OPENAI_API_KEY}"
  [ -n "${AZURE_OPENAI_API_BASE:-}" ]    && flags="${flags} --set secrets.azureOpenaiApiBase=${AZURE_OPENAI_API_BASE}"
  [ -n "${AZURE_OPENAI_API_VERSION:-}" ] && flags="${flags} --set secrets.azureOpenaiApiVersion=${AZURE_OPENAI_API_VERSION}"
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
  [ -n "${CONTRACTIQ_JWT_SECRET:-}" ]    && flags="${flags} --set secrets.contractiqJwtSecret=${CONTRACTIQ_JWT_SECRET}"
  [ -n "${GOOGLE_OIDC_CLIENT_ID:-}" ]        && flags="${flags} --set secrets.sso.googleClientId=${GOOGLE_OIDC_CLIENT_ID}"
  [ -n "${GOOGLE_OIDC_CLIENT_SECRET:-}" ]    && flags="${flags} --set secrets.sso.googleClientSecret=${GOOGLE_OIDC_CLIENT_SECRET}"
  [ -n "${GITHUB_OAUTH_CLIENT_ID:-}" ]       && flags="${flags} --set secrets.sso.githubClientId=${GITHUB_OAUTH_CLIENT_ID}"
  [ -n "${GITHUB_OAUTH_CLIENT_SECRET:-}" ]   && flags="${flags} --set secrets.sso.githubClientSecret=${GITHUB_OAUTH_CLIENT_SECRET}"
  [ -n "${MICROSOFT_OIDC_CLIENT_ID:-}" ]     && flags="${flags} --set secrets.sso.microsoftClientId=${MICROSOFT_OIDC_CLIENT_ID}"
  [ -n "${MICROSOFT_OIDC_CLIENT_SECRET:-}" ] && flags="${flags} --set secrets.sso.microsoftClientSecret=${MICROSOFT_OIDC_CLIENT_SECRET}"
  [ -n "${MICROSOFT_OIDC_TENANT:-}" ]        && flags="${flags} --set secrets.sso.microsoftTenant=${MICROSOFT_OIDC_TENANT}"
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
  [code-runner-python]="apps/code-runner/Dockerfile.python"
  [code-runner-node]="apps/code-runner/Dockerfile.node"
  [contractiq-api]="contractiq/api/Dockerfile"
  [contractiq-web]="contractiq/web/Dockerfile"
  [mideasttourism-api]="mideasttourism/api/Dockerfile"
  [mideasttourism-web]="mideasttourism/web/Dockerfile"
  [industrial-iot-api]="industrial-iot/api/Dockerfile"
  [industrial-iot-web]="industrial-iot/web/Dockerfile"
  [resolveai-api]="resolveai/api/Dockerfile"
  [resolveai-web]="resolveai/web/Dockerfile"
  [wingman-api]="wingman/api/Dockerfile"
  [wingman-web]="wingman/web/Dockerfile"
  [pharmavigil-api]="pharmavigil/api/Dockerfile"
  [pharmavigil-web]="pharmavigil/web/Dockerfile"
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
  [code-runner-python]="${ROOT_DIR}/apps/code-runner"
  [code-runner-node]="${ROOT_DIR}/apps/code-runner"
  [cognify-worker]="${ROOT_DIR}"
  [contractiq-api]="${ROOT_DIR}/contractiq/api"
  [contractiq-web]="${ROOT_DIR}/contractiq/web"
  # mideasttourism-api: build context must include test-data/ for the seed endpoint,
  # so we use the mideasttourism/ directory rather than mideasttourism/api/.
  [mideasttourism-api]="${ROOT_DIR}/mideasttourism"
  [mideasttourism-web]="${ROOT_DIR}/mideasttourism/web"
  [industrial-iot-api]="${ROOT_DIR}/industrial-iot/api"
  [industrial-iot-web]="${ROOT_DIR}/industrial-iot/web"
  [resolveai-api]="${ROOT_DIR}/resolveai/api"
  [resolveai-web]="${ROOT_DIR}/resolveai/web"
  [wingman-api]="${ROOT_DIR}/wingman/api"
  [wingman-web]="${ROOT_DIR}/wingman/web"
  [pharmavigil-api]="${ROOT_DIR}/pharmavigil/api"
  [pharmavigil-web]="${ROOT_DIR}/pharmavigil/web"
  [claimsiq]="${ROOT_DIR}/claimsiq"
)

# cognify-worker is NOT a separate image — it reuses `worker`.
_cognify_worker_is_alias() { return 0; }

# NEXT_PUBLIC_* are inlined into the web bundle at build time, so forward the ones set in .env or the shell
WEB_PUBLIC_VARS=(NEXT_PUBLIC_API_URL NEXT_PUBLIC_APP_URL NEXT_PUBLIC_ENABLE_MONETIZATION NEXT_PUBLIC_AUDIT_NATIVE NEXT_PUBLIC_GRAFANA_URL)
web_build_args() { # web_build_args <svc>, fills BUILD_ARGS
  BUILD_ARGS=()
  [ "$1" = "web" ] || return 0
  local v host
  # the web bundle links to Grafana on its ingress host, known from the last deploy
  if [ -z "${NEXT_PUBLIC_GRAFANA_URL:-}" ]; then
    host="$(get_endpoint 2>/dev/null || true)"
    [ -n "${host}" ] && NEXT_PUBLIC_GRAFANA_URL="http://grafana.${host}"
  fi
  for v in "${WEB_PUBLIC_VARS[@]}"; do
    [ -n "${!v:-}" ] && BUILD_ARGS+=(--build-arg "${v}=${!v}")
  done
  return 0
}

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
  web_build_args "${svc}"
  if ! docker buildx build \
        --platform=linux/amd64 \
        --network=host \
        --push \
        -t "${img}:${IMAGE_TAG}" \
        -t "${img}:latest" \
        ${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"} \
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
    code-runner-python code-runner-node
    contractiq-api contractiq-web
    mideasttourism-api mideasttourism-web
    industrial-iot-api industrial-iot-web
    resolveai-api resolveai-web
    wingman-api wingman-web
    pharmavigil-api pharmavigil-web
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

# Streaming + time-series infra for the v1.1.0 production-tooling primitives:
# mosquitto (MQTT broker) + timescaledb (TSDB). Both run in the abenix
# namespace so the agent-runtime tools can reach them via cluster-DNS
# (mqtt://abenix-mosquitto:1883, postgres://abenix-timescaledb:5432).
deploy_streaming_tsdb() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "mosquitto" && ! _should_do "timescaledb" && ! _should_do "infra"; then
    return 0
  fi
  step "Deploying mosquitto + timescaledb (streaming + tsdb infra)"
  kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f - &>/dev/null

  helm upgrade --install abenix-mosquitto "${ROOT_DIR}/infra/helm/mosquitto" \
    --namespace "${NAMESPACE}" \
    --timeout 5m \
    --wait=false \
    2>&1 | tail -3 || warn "mosquitto helm install failed"
  ok "mosquitto installed (mqtt://abenix-mosquitto:1883)"

  helm upgrade --install abenix-timescaledb "${ROOT_DIR}/infra/helm/timescaledb" \
    --namespace "${NAMESPACE}" \
    --timeout 5m \
    --wait=false \
    2>&1 | tail -3 || warn "timescaledb helm install failed"
  ok "timescaledb installed (postgres://abenix-timescaledb:5432)"
}

# Edge runtime — separate StatefulSet that registers back to the core API,
# subscribes to MQTT for OTA bundle delivery, and runs `.agent` bundles
# in-process. One install per gateway (gateway.id is the StatefulSet name).
deploy_edge_runtime() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "edge-runtime" && ! _should_do "infra"; then
    return 0
  fi
  if [ "${EDGE_RUNTIME_ENABLED:-true}" != "true" ]; then
    log "Edge runtime disabled (EDGE_RUNTIME_ENABLED=${EDGE_RUNTIME_ENABLED}) — skipping"
    return 0
  fi
  EDGE_RUNTIME_VARIANT="${EDGE_RUNTIME_VARIANT:-python}"
  EDGE_RUNTIME_ALL_VARIANTS="${EDGE_RUNTIME_ALL_VARIANTS:-false}"
  if [ "${EDGE_RUNTIME_VARIANT}" = "python" ] || [ "${EDGE_RUNTIME_ALL_VARIANTS}" = "true" ]; then
    step "Deploying edge runtime (python, gateway.id=${EDGE_GATEWAY_ID:-edge-cluster-default})"
    local edge_token edge_pubkey
    edge_token=$(_generate_abenix_api_key 2>/dev/null || echo "")
    edge_pubkey=$(_fetch_edge_signing_pubkey || echo "")
    # Tag override only when EDGE_IMAGE_TAG is explicitly set — otherwise the
    # chart's pinned values.yaml tag wins. Passing the git SHA here is what
    # caused the 4-day ImagePullBackOff: the SHA tag was never pushed.
    local edge_tag_flag=""
    if [ -n "${EDGE_IMAGE_TAG}" ]; then
      edge_tag_flag="--set image.tag=${EDGE_IMAGE_TAG}"
    fi
    # --reset-values: drop user-supplied values from prior revisions BEFORE
    # re-applying the chart defaults + our --set flags. Without this, a
    # historical bad value (e.g. image.tag: 84de886 from a buggy v1.5.x run)
    # would carry forward forever, even after we stopped passing it.
    # shellcheck disable=SC2086
    helm upgrade --install abenix-edge "${ROOT_DIR}/infra/helm/edge-runtime" \
      --namespace "${NAMESPACE}" \
      --reset-values \
      --set image.repository="${ACR_LOGIN_SERVER:-${ACR_NAME}.azurecr.io}/abenix/edge-runtime" \
      ${edge_tag_flag} \
      --set gateway_id="${EDGE_GATEWAY_ID:-edge-cluster-default}" \
      --set gateway_name="${EDGE_GATEWAY_NAME:-edge-cluster-default}" \
      --set platform_url="http://${RELEASE_NAME}-api.${NAMESPACE}.svc.cluster.local:8000" \
      --set platform_token="${edge_token}" \
      --set signing_pubkey="${edge_pubkey}" \
      --set mqtt_url="mqtt://abenix-mosquitto.${NAMESPACE}.svc.cluster.local:1883" \
      --set anthropic_api_key="${ANTHROPIC_API_KEY:-}" \
      --timeout 5m \
      --wait=false \
      2>&1 | tail -3 || warn "edge-runtime helm install failed"
    ok "edge-runtime installed (StatefulSet abenix-edge in ${NAMESPACE})"
  fi
  if [ "${EDGE_RUNTIME_VARIANT}" = "rust" ] || [ "${EDGE_RUNTIME_ALL_VARIANTS}" = "true" ]; then
    deploy_edge_runtime_rust
  fi
  if [ "${EDGE_RUNTIME_VARIANT}" = "c" ] || [ "${EDGE_RUNTIME_ALL_VARIANTS}" = "true" ]; then
    deploy_edge_runtime_c
  fi
}

_fetch_edge_signing_pubkey() {
  local api_pod
  api_pod=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=api" \
    --field-selector=status.phase=Running --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}' 2>/dev/null)
  if [ -z "${api_pod}" ]; then return 1; fi
  kubectl exec -n "${NAMESPACE}" "${api_pod}" -c api -- python3 -c "
from app.routers.edge import _resolve_signing_key
from cryptography.hazmat.primitives import serialization
k = _resolve_signing_key()
print(k.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode(), end='')
" 2>/dev/null
}

deploy_edge_runtime_rust() {
  step "Deploying edge runtime (rust, gateway.id=${EDGE_GATEWAY_ID:-edge-cluster-default}-rust)"
  local edge_token edge_pubkey
  edge_token=$(_generate_abenix_api_key 2>/dev/null || echo "")
  if [ -z "${edge_token}" ]; then
    warn "  Could not mint platform token for edge-rust; runtime will skip /register and bundles must be pushed via direct HTTP"
  else
    log "  Minted platform_token (prefix ${edge_token:0:10}...)"
  fi
  edge_pubkey=$(_fetch_edge_signing_pubkey || echo "")
  if [ -z "${edge_pubkey}" ]; then
    warn "  Could not fetch signing pubkey; runtime will accept bundles UNVERIFIED (dev only — set EDGE_SIGNING_KEY_PEM on api pod to fix)"
  else
    log "  Signing pubkey fetched ($(printf '%s' "${edge_pubkey}" | wc -c) bytes)"
  fi
  local edge_tag_flag=""
  if [ -n "${EDGE_IMAGE_TAG}" ]; then
    edge_tag_flag="--set image.tag=${EDGE_IMAGE_TAG}"
  fi
  # shellcheck disable=SC2086
  helm upgrade --install abenix-edge-rust "${ROOT_DIR}/infra/helm/edge-runtime-rust" \
    --namespace "${NAMESPACE}" \
    --reset-values \
    --set image.repository="${ACR_LOGIN_SERVER:-${ACR_NAME}.azurecr.io}/abenix/edge-runtime-rust" \
    ${edge_tag_flag} \
    --set gateway_id="${EDGE_GATEWAY_ID:-edge-cluster-default}-rust" \
    --set gateway_name="${EDGE_GATEWAY_NAME:-edge-cluster-default}-rust" \
    --set platform_url="http://${RELEASE_NAME}-api.${NAMESPACE}.svc.cluster.local:8000" \
    --set platform_token="${edge_token}" \
    --set signing_pubkey="${edge_pubkey}" \
    --set mqtt_url="mqtt://abenix-mosquitto.${NAMESPACE}.svc.cluster.local:1883" \
    --set anthropic_api_key="${ANTHROPIC_API_KEY:-}" \
    --timeout 5m \
    --wait=false \
    2>&1 | tail -3 || warn "edge-runtime-rust helm install failed"
  ok "edge-runtime-rust installed (StatefulSet abenix-edge-rust in ${NAMESPACE})"
}

deploy_edge_runtime_c() {
  step "Deploying edge runtime (c, gateway.id=${EDGE_GATEWAY_ID:-edge-cluster-default}-c)"
  local edge_token edge_pubkey
  edge_token=$(_generate_abenix_api_key 2>/dev/null || echo "")
  if [ -z "${edge_token}" ]; then
    warn "  Could not mint platform token for edge-c"
  fi
  edge_pubkey=$(_fetch_edge_signing_pubkey || echo "")
  local edge_tag_flag=""
  if [ -n "${EDGE_IMAGE_TAG}" ]; then
    edge_tag_flag="--set image.tag=${EDGE_IMAGE_TAG}"
  fi
  # shellcheck disable=SC2086
  helm upgrade --install abenix-edge-c "${ROOT_DIR}/infra/helm/edge-runtime-c" \
    --namespace "${NAMESPACE}" \
    --reset-values \
    --set image.repository="${ACR_LOGIN_SERVER:-${ACR_NAME}.azurecr.io}/abenix/edge-runtime-c" \
    ${edge_tag_flag} \
    --set gateway_id="${EDGE_GATEWAY_ID:-edge-cluster-default}-c" \
    --set gateway_name="${EDGE_GATEWAY_NAME:-edge-cluster-default}-c" \
    --set platform_url="http://${RELEASE_NAME}-api.${NAMESPACE}.svc.cluster.local:8000" \
    --set platform_token="${edge_token}" \
    --set signing_pubkey="${edge_pubkey}" \
    --set mqtt_url="mqtt://abenix-mosquitto.${NAMESPACE}.svc.cluster.local:1883" \
    --set anthropic_api_key="${ANTHROPIC_API_KEY:-}" \
    --timeout 5m \
    --wait=false \
    2>&1 | tail -3 || warn "edge-runtime-c helm install failed"
  ok "edge-runtime-c installed (StatefulSet abenix-edge-c in ${NAMESPACE})"
}

deploy_abenix_helm() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "api" && ! _should_do "web" && ! _should_do "worker" && ! _should_do "agent-runtime" && ! _should_do "cognify-worker"; then
    log "Abenix core not in --only filter — skipping helm upgrade"
    return 0
  fi

  step "Deploying Abenix via Helm (tag=${IMAGE_TAG})"

  # Ensure namespace
  kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f - &>/dev/null

  # Sanity gate — never let a malformed AZURE_OPENAI_API_BASE reach a pod.
  _sanity_check_azure_endpoints

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
    --set "codeRunners.registry=${ACR_LOGIN_SERVER}" \
    --set "codeRunners.imageTag=${IMAGE_TAG}" \
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
      --field-selector=status.phase=Running --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}' 2>/dev/null)
    [ -n "${api_pod}" ] && break
    sleep 3
    tries=$((tries + 1))
  done

  if [ -n "${api_pod}" ]; then
    # Bootstrap fast-path — Base.metadata.create_all + alembic stamp
    # heads if the DB is brand-new. No-op on an existing install. This
    # gives fresh deploys (PoCs, customer evals, dev sandboxes) a
    # one-shot schema instead of replaying 40+ historical migrations.
    log "Bootstrapping fresh schema (no-op if alembic_version exists)..."
    kubectl exec -n "${NAMESPACE}" "${api_pod}" -- bash -c \
      'cd /app/packages/db && python -m bootstrap' 2>&1 | tail -5 || true

    log "Running alembic upgrade heads via ${api_pod}..."
    # `heads` (plural) advances every independent migration chain in the
    # repo. We had a silent regression in v1.1.5 where a new branch
    # head (z6a7b8c9d0e1, approvals.client_token + gate_kind) was added
    # while 1100_d_dead_letter was already a separate head — `upgrade
    # head` (singular) errors with "Multiple head revisions are
    # present" and the `|| true` below swallowed it. The plural form
    # plus the new sentinel columns at the bottom of this block close
    # the loophole. NOTE: removing `|| true` would be ideal, but
    # alembic's exit code on noop is also non-zero in older versions,
    # so we keep the swallow and rely on the sentinel check instead.
    kubectl exec -n "${NAMESPACE}" "${api_pod}" -- bash -c \
      'cd /app/packages/db && python -m alembic upgrade heads' 2>&1 | tail -10 || true
    # an upgrade that committed nothing exits 0, so check the database is at every head
    local heads_out
    if ! heads_out=$(kubectl exec -n "${NAMESPACE}" "${api_pod}" -- bash -c         'cd /app/packages/db && python -m bootstrap verify' 2>&1); then
      echo "${heads_out}" | tail -3
      err "Migrations did not reach every head, aborting before traffic moves"
      exit 1
    fi
    echo "${heads_out}" | tail -1

    # Schema-drift sentinel: a small set of canonical columns that
    # MUST exist after alembic upgrade heads. The list lives in
    # scripts/_schema-sentinels.sh — single source of truth shared
    # with dev-local.sh and verify-schema.sh. When you add a
    # schema-changing migration, append the load-bearing columns to
    # that file (one place, three consumers).
    log "Verifying schema sentinels in live database..."
    # shellcheck source=_schema-sentinels.sh
    source "${ROOT_DIR}/scripts/_schema-sentinels.sh"
    local missing=""
    local entry table column exists
    for entry in "${SCHEMA_CANONICAL_COLUMNS[@]}"; do
      table="${entry%.*}"
      column="${entry#*.}"
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
    ok "Platform schema verified — all sentinel columns present"

    local uc_missing=""
    for entry in "${SCHEMA_USE_CASE_COLUMNS[@]}"; do
      table="${entry%.*}"
      column="${entry#*.}"
      exists=$(kubectl exec -n "${NAMESPACE}" "${pg}" -- bash -c \
        "PGPASSWORD=\$POSTGRES_PASSWORD psql -U postgres -d abenix -tAc \"SELECT 1 FROM information_schema.columns WHERE table_name='${table}' AND column_name='${column}'\"" \
        2>/dev/null | tr -d '[:space:]')
      [ "${exists}" = "1" ] || uc_missing="${uc_missing} ${table}.${column}"
    done
    if [ -n "${uc_missing}" ]; then
      warn "Use-case schema not yet synced:${uc_missing}"
      warn "Will be added by the use-case api pods at startup (use_case_schema_sync.py)"
    else
      ok "Use-case schema verified — all sentinel columns present"
    fi
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

# ── Verify the Claude subscription once the pods are up ─────────────────────
# A deploy used to report green while every agent run failed with "OAuth
# access token has been revoked". The token rotates and nothing checked it
# after the rollout. Runs inside the API pod, so no token or port-forward
# passes through the shell. Never fails the deploy, but says so loudly.
report_tool_credentials() {
  log "Seeded agents that still need a tool credential"
  local pod
  pod=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=api" \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [ -z "${pod}" ]; then
    warn "no running API pod, skipping the credential summary"
    return 0
  fi
  local out
  out=$(kubectl exec -i -n "${NAMESPACE}" "${pod}" -c api -- python - 2>/dev/null <<'PY'
import asyncio, os, sys
for p in ("/app/apps/api", "/app/apps/agent-runtime", "/app/packages/db"):
    sys.path.insert(0, p)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from models.agent import Agent
from engine import credentials
from app.services import tool_config

async def run():
    await credentials.ensure_fresh(force=True)
    decls = tool_config.declarations()
    eng = create_async_engine(os.environ["DATABASE_URL"])
    sf = async_sessionmaker(eng, expire_on_commit=False)
    async with sf() as db:
        rows = (await db.execute(select(Agent.slug, Agent.model_config_))).all()
    await eng.dispose()
    missing = {}
    for slug, mc in rows:
        tools = set((mc or {}).get("tools") or [])
        for n in (((mc or {}).get("pipeline_config") or {}).get("nodes") or []):
            if isinstance(n, dict) and n.get("tool_name"):
                tools.add(n["tool_name"])
        for t in tools:
            for key, req in tool_config.required_for_tool(t).items():
                if req and not credentials.get(key, default=decls[key].default):
                    missing.setdefault(key, set()).add(slug)
    if not missing:
        print("OK every required tool credential is set")
        return
    print(f"MISSING {len(missing)}")
    for key, slugs in sorted(missing.items()):
        print(f"  {key}: {len(slugs)} agent(s), e.g. {', '.join(sorted(slugs)[:4])}")

asyncio.run(run())
PY
)
  case "${out}" in
    OK*)      ok "${out#OK }" ;;
    MISSING*) warn "${out#MISSING } tool credential(s) are not set. Those agents answer with the key they need until an admin adds it under Admin -> Tool Configuration."
              printf '%s\n' "${out}" | sed -n '2,40p' | while IFS= read -r line; do log "  ${line}"; done ;;
    *)        log "credential summary unavailable: ${out:-no output}" ;;
  esac
  return 0
}

verify_ml_models_shared() {
  # A model the API stored must be readable by the agent runtime, or ml_model
  # tool calls fall back to fetching it over HTTP. A rollout can still show the
  # old pods as Running, so look again for a minute before warning.
  local api_pod rt_pod sample attempt
  for attempt in 1 2 3 4 5 6; do
    api_pod=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=api" \
      --field-selector=status.phase=Running --sort-by=.metadata.creationTimestamp \
      -o jsonpath='{.items[-1:].metadata.name}' 2>/dev/null)
    rt_pod=$(kubectl get pods -n "${NAMESPACE}" --field-selector=status.phase=Running \
      --sort-by=.metadata.creationTimestamp -o name 2>/dev/null | grep agent-runtime | tail -1 | sed 's#pod/##' | tr -d '\r')
    if [ -z "${api_pod}" ] || [ -z "${rt_pod}" ]; then
      sleep 10
      continue
    fi
    sample=$(kubectl exec -n "${NAMESPACE}" "${api_pod}" -c api -- sh -c \
      'find /data/ml-models -type f \( -name "*.pkl" -o -name "*.onnx" -o -name "*.pt" \) 2>/dev/null | head -1' 2>/dev/null | tr -d '\r')
    if [ -z "${sample}" ]; then
      log "ML model volume check: no model files yet"
      return 0
    fi
    # no MSYS_NO_PATHCONV here, it hides a Git Bash style KUBECONFIG from kubectl and the check hits another cluster
    if kubectl exec -n "${NAMESPACE}" "${rt_pod}" -- sh -c "test -f '${sample}'" 2>/dev/null; then
      ok "ML models: the runtime reads the files the API stores"
      return 0
    fi
    sleep 10
  done
  if [ -z "${api_pod}" ] || [ -z "${rt_pod}" ]; then
    warn "ML model volume check skipped, api or runtime pod not running"
  else
    warn "ML models: ${sample} exists on the API but not on the runtime. The runtime will fetch models over HTTP. Mount the same ml-models claim on both."
  fi
}

verify_subscription() {
  log "Verifying the Claude subscription token"
  local pod
  pod=$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=api" \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [ -z "${pod}" ]; then
    warn "no running API pod, skipping the subscription check"
    return 0
  fi
  local out
  out=$(kubectl exec -i -n "${NAMESPACE}" "${pod}" -c api -- python - 2>/dev/null <<'PY'
import asyncio, os, sys
sys.path.insert(0, "/app/apps/api")
sys.path.insert(0, "/app/packages/db")
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from models.user import User
from app.core.security import create_access_token

async def run():
    eng = create_async_engine(os.environ["DATABASE_URL"])
    sf = async_sessionmaker(eng, expire_on_commit=False)
    async with sf() as db:
        u = (await db.execute(
            select(User).where(User.email.in_(["admin@abenix.dev", "system@abenix.dev"]))
            .order_by(User.email.desc())
        )).scalars().first()
    await eng.dispose()
    if u is None:
        print("SKIP no admin user yet"); return
    role = getattr(u.role, "value", u.role)
    tok = create_access_token(u.id, u.tenant_id, str(role))
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("http://localhost:8000/api/admin/settings/subscription/verify",
                         headers={"Authorization": f"Bearer {tok}"}, json={})
    if r.status_code == 200:
        print("OK")
    elif r.status_code == 400 and "No subscription token" in r.text:
        print("SKIP no subscription token configured")
    else:
        print(f"FAIL {r.status_code} {r.text[:200]}")

asyncio.run(run())
PY
)
  case "${out}" in
    OK*)   ok "subscription token verified against Anthropic" ;;
    SKIP*) log "${out#SKIP }" ;;
    *)
      warn "SUBSCRIPTION TOKEN REJECTED. Every agent run will fail with INFRA_AUTH_ERROR."
      warn "  ${out:-no response from the verify endpoint}"
      warn "  Fix: bash scripts/sync-claude-subscription.sh"
      ;;
  esac
  return 0
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
      --field-selector=status.phase=Running --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}' 2>/dev/null)
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
  for script in seed_agents.py seed_users.py seed_portfolio_schemas.py seed_ml_models.py seed_code_assets.py seed_kb.py seed_atlas.py seed_kb_agent_grants.py seed_llm_pricing.py seed_backfill_agent_shares.py; do
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
    --field-selector=status.phase=Running --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}' 2>/dev/null)
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

# Verify a standalone Deployment landed with the env wiring its pods
# need to talk to abenix-api. After v1.1.5 we hit a silent regression
# where industrial-iot-api ran for weeks with `env: []` and `envFrom:
# []` — the Secret existed, the seed script populated it, but the
# Deployment never asked for it (stale image tag from before the
# manifest grew envFrom). The pod looked healthy, the API key probe
# returned no_api_key, and the UI showed "KB Not Available" with no
# obvious cause. This guard catches that class of bug at deploy time
# instead of in user-visible behaviour. Call after every kubectl apply
# of a standalone Deployment.
_verify_standalone_envfrom() {
  local deploy="$1" expected_secret="$2" expected_config="$3"
  local got_secret got_config inline_count
  got_secret=$(kubectl -n "${NAMESPACE}" get deployment "${deploy}" \
    -o jsonpath='{.spec.template.spec.containers[0].envFrom[*].secretRef.name}' 2>/dev/null || echo "")
  got_config=$(kubectl -n "${NAMESPACE}" get deployment "${deploy}" \
    -o jsonpath='{.spec.template.spec.containers[0].envFrom[*].configMapRef.name}' 2>/dev/null || echo "")
  # `grep -c` exits 1 when there are zero matches, which then trips the
  # `|| echo 0` fallback AND prints the previous "0" line, producing
  # multi-line "0\n0" that breaks the `[ ${inline_count} -eq 0 ]` check
  # below. Use awk so we always emit exactly one integer.
  inline_count=$(kubectl -n "${NAMESPACE}" get deployment "${deploy}" \
    -o jsonpath='{.spec.template.spec.containers[0].env[*].name}' 2>/dev/null \
    | awk 'BEGIN{n=0} { for (i=1;i<=NF;i++) if (length($i)) n++ } END{print n+0}')
  if [[ " ${got_secret} " != *" ${expected_secret} "* ]]; then
    err "Deployment ${deploy} is missing envFrom secretRef '${expected_secret}' (got: '${got_secret}')."
    err "  This usually means the Deployment object in-cluster is older than the manifest in-repo."
    err "  Re-apply with: bash scripts/deploy-azure.sh deploy --only=${deploy}"
    return 7
  fi
  if [[ " ${got_config} " != *" ${expected_config} "* ]]; then
    err "Deployment ${deploy} is missing envFrom configMapRef '${expected_config}' (got: '${got_config}')."
    return 7
  fi
  # We're not strict about inline env (claimsiq has 1, others have 0
  # because they get everything from envFrom). What we do require is
  # that *something* feeds the container — either inline env, or
  # envFrom — never both empty.
  if [ "${inline_count:-0}" -eq 0 ] && [ -z "${got_secret// /}" ] && [ -z "${got_config// /}" ]; then
    err "Deployment ${deploy} has zero env vars (no env, no envFrom). Pod cannot reach the platform."
    return 7
  fi
  ok "  ${deploy}: envFrom secretRef=${expected_secret} configMapRef=${expected_config}"
}

deploy_contractiq() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "contractiq-api" && ! _should_do "contractiq-web"; then return 0; fi
  local manifest="${ROOT_DIR}/contractiq/k8s/contractiq.yaml"
  if [ ! -f "${manifest}" ]; then warn "ContractIQ manifest missing — skip"; return; fi

  step "Deploying ContractIQ"
  local ciq_key="${CONTRACTIQ_ABENIX_API_KEY:-}"
  # If caller key is empty OR this is a fresh Abenix DB, mint a new key.
  if [ -z "${ciq_key}" ]; then
    log "  Minting a fresh Abenix API key for ContractIQ..."
    ciq_key=$(_generate_abenix_api_key || echo "")
    if [ -n "${ciq_key}" ]; then
      ok "  Key minted (prefix ${ciq_key:0:10}...)"
    else
      warn "  Could not mint key — using placeholder; chat will fail until a key is wired"
      ciq_key="PLACEHOLDER_CHANGE_ME"
    fi
  fi
  local ciq_jwt="${CONTRACTIQ_JWT_SECRET:-contractiq-dev-secret-please-change}"
  local anth_key="${ANTHROPIC_API_KEY:-}"

  # Apply the secret with real values FIRST so any pod created by the
  # subsequent manifest apply picks up the live key, not the manifest's
  # REPLACE_AT_DEPLOY_TIME placeholder.
  kubectl create secret generic contractiq-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=CONTRACTIQ_ABENIX_API_KEY="${ciq_key}" \
    --from-literal=CONTRACTIQ_JWT_SECRET="${ciq_jwt}" \
    --from-literal=ANTHROPIC_API_KEY="${anth_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -2

  # Strip the manifest's stringData Secret document so it doesn't
  # overwrite the live secret we just applied. Buffer each YAML
  # document between `---` separators; flush only the non-Secret ones.
  sed \
    -e "s|localhost:5000/abenix/contractiq-api:latest|${ACR_LOGIN_SERVER}/contractiq-api:${IMAGE_TAG}|g" \
    -e "s|localhost:5000/abenix/contractiq-web:latest|${ACR_LOGIN_SERVER}/contractiq-web:${IMAGE_TAG}|g" \
    -e "s|imagePullPolicy: IfNotPresent|imagePullPolicy: Always|g" \
    "${manifest}" | python -c "
import sys, yaml
docs = list(yaml.safe_load_all(sys.stdin))
out = [d for d in docs if d and d.get('kind') != 'Secret']
print(yaml.safe_dump_all(out))
" | kubectl apply -f - 2>&1 | tail -5

  # Force a rollout so pods pick up the freshly-applied secret keys
  # even when the manifest apply was a no-op.
  kubectl -n "${NAMESPACE}" rollout restart deploy/contractiq-api 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout restart deploy/contractiq-web 2>&1 | tail -1 || true

  kubectl -n "${NAMESPACE}" rollout status deploy/contractiq-api --timeout=180s 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout status deploy/contractiq-web --timeout=180s 2>&1 | tail -1 || true
  _verify_standalone_envfrom contractiq-api contractiq-secrets contractiq-config || exit 7
  # -web is a Next.js frontend with only inline env (INTERNAL_URL +
  # NODE_ENV). It doesn't need envFrom — the api container does. Skip.
  ok "ContractIQ deployed"
}

deploy_mideasttourism() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "mideasttourism-api" && ! _should_do "mideasttourism-web"; then return 0; fi
  local manifest="${ROOT_DIR}/mideasttourism/k8s/mideasttourism.yaml"
  if [ ! -f "${manifest}" ]; then warn "Mideast Tourism manifest missing — skip"; return; fi

  step "Deploying Mideast Tourism"
  local st_key="${MIDEASTTOURISM_ABENIX_API_KEY:-}"
  if [ -z "${st_key}" ]; then
    # Reuse the ContractIQ key if it was just minted (same tenant, same Abenix),
    # otherwise mint a fresh one for MideastTourism.
    st_key=$(kubectl get secret contractiq-secrets -n "${NAMESPACE}" \
      -o jsonpath='{.data.CONTRACTIQ_ABENIX_API_KEY}' 2>/dev/null | base64 -d 2>/dev/null)
    if [ -z "${st_key}" ] || [ "${st_key}" = "PLACEHOLDER_CHANGE_ME" ]; then
      log "  Minting Abenix API key for Mideast Tourism..."
      st_key=$(_generate_abenix_api_key || echo "PLACEHOLDER_CHANGE_ME")
    fi
  fi
  local st_jwt="${MIDEASTTOURISM_JWT_SECRET:-mideast-tourism-dev-secret}"

  sed \
    -e "s|localhost:5000/abenix/mideasttourism-api:latest|${ACR_LOGIN_SERVER}/mideasttourism-api:${IMAGE_TAG}|g" \
    -e "s|localhost:5000/abenix/mideasttourism-web:latest|${ACR_LOGIN_SERVER}/mideasttourism-web:${IMAGE_TAG}|g" \
    -e "s|imagePullPolicy: IfNotPresent|imagePullPolicy: Always|g" \
    "${manifest}" | kubectl apply -f - 2>&1 | tail -5

  kubectl create secret generic mideasttourism-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=MIDEASTTOURISM_ABENIX_API_KEY="${st_key}" \
    --from-literal=MIDEASTTOURISM_JWT_SECRET="${st_jwt}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -2

  # Always restart both after the secret patch — see deploy_wingman comment.
  kubectl -n "${NAMESPACE}" rollout restart deploy/mideasttourism-api 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout restart deploy/mideasttourism-web 2>&1 | tail -1 || true

  kubectl -n "${NAMESPACE}" rollout status deploy/mideasttourism-api --timeout=180s 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout status deploy/mideasttourism-web --timeout=180s 2>&1 | tail -1 || true
  _verify_standalone_envfrom mideasttourism-api mideasttourism-secrets mideasttourism-config || exit 7
  # -web is a Next.js frontend; api carries the platform credentials.
  ok "Mideast Tourism deployed"
}

deploy_industrial_iot() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "industrial-iot-api" && ! _should_do "industrial-iot-web"; then return 0; fi
  local manifest="${ROOT_DIR}/industrial-iot/k8s/industrial-iot.yaml"
  if [ ! -f "${manifest}" ]; then warn "Industrial-IoT manifest missing — skip"; return; fi

  step "Deploying Industrial-IoT"
  local iot_key="${INDUSTRIALIOT_ABENIX_API_KEY:-}"
  if [ -z "${iot_key}" ]; then
    # Reuse an existing tenant key if one's already minted; else mint fresh.
    iot_key=$(kubectl get secret contractiq-secrets -n "${NAMESPACE}" \
      -o jsonpath='{.data.CONTRACTIQ_ABENIX_API_KEY}' 2>/dev/null | base64 -d 2>/dev/null)
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

  # Web-tier shared secret that gates the standalone API's proxy
  # passthroughs (/api/code-assets, /api/agents, /api/connectors). Reuse
  # the existing value if already in the cluster so rolling pods stay in
  # sync; mint a fresh UUID otherwise.
  local iot_web_secret
  iot_web_secret=$(kubectl get secret industrial-iot-secrets -n "${NAMESPACE}" \
    -o jsonpath='{.data.INDUSTRIALIOT_WEB_PROXY_SECRET}' 2>/dev/null | base64 -d 2>/dev/null)
  # Also mint a fresh UUID if the existing value is the placeholder that
  # ships in the k8s manifest — re-using REPLACE_AT_DEPLOY_TIME defeats the
  # whole point of a shared secret.
  if [ -z "${iot_web_secret}" ] || [ "${iot_web_secret}" = "REPLACE_AT_DEPLOY_TIME" ]; then
    iot_web_secret=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || python3 -c 'import uuid;print(uuid.uuid4())')
  fi

  kubectl create secret generic industrial-iot-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=INDUSTRIALIOT_ABENIX_API_KEY="${iot_key}" \
    --from-literal=INDUSTRIALIOT_WEB_PROXY_SECRET="${iot_web_secret}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -2

  # Always restart both — see deploy_wingman comment about envFrom +
  # secret-patch ordering.
  kubectl -n "${NAMESPACE}" rollout restart deploy/industrial-iot-api 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout restart deploy/industrial-iot-web 2>&1 | tail -1 || true

  kubectl -n "${NAMESPACE}" rollout status deploy/industrial-iot-api --timeout=180s 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout status deploy/industrial-iot-web --timeout=180s 2>&1 | tail -1 || true
  _verify_standalone_envfrom industrial-iot-api industrial-iot-secrets industrial-iot-config || exit 7
  # industrial-iot-web is a Next.js frontend that proxies through
  # industrial-iot-api; it intentionally has no envFrom (only inline
  # INTERNAL_URL + NODE_ENV in the manifest). Skip the envFrom verifier
  # — same shape as contractiq-web / resolveai-web / mideasttourism-web.
  ok "Industrial-IoT deployed"
}

deploy_pharmavigil() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "pharmavigil-api" && ! _should_do "pharmavigil-web"; then return 0; fi
  local manifest="${ROOT_DIR}/pharmavigil/k8s/pharmavigil.yaml"
  if [ ! -f "${manifest}" ]; then warn "PharmaVigil manifest missing — skip"; return; fi

  step "Deploying PharmaVigil"
  local pv_key="${PHARMAVIGIL_ABENIX_API_KEY:-}"
  if [ -z "${pv_key}" ]; then
    pv_key=$(kubectl get secret pharmavigil-secrets -n "${NAMESPACE}" \
      -o jsonpath='{.data.PHARMAVIGIL_ABENIX_API_KEY}' 2>/dev/null | base64 -d 2>/dev/null)
    if [ -z "${pv_key}" ] || [ "${pv_key}" = "REPLACE_AT_DEPLOY_TIME" ]; then
      log "  Minting Abenix API key for PharmaVigil..."
      pv_key=$(_generate_abenix_api_key || echo "PLACEHOLDER_CHANGE_ME")
    fi
  fi

  sed \
    -e "s|localhost:5000/abenix/pharmavigil-api:latest|${ACR_LOGIN_SERVER}/pharmavigil-api:${IMAGE_TAG}|g" \
    -e "s|localhost:5000/abenix/pharmavigil-web:latest|${ACR_LOGIN_SERVER}/pharmavigil-web:${IMAGE_TAG}|g" \
    -e "s|imagePullPolicy: IfNotPresent|imagePullPolicy: Always|g" \
    "${manifest}" | kubectl apply -f - 2>&1 | tail -5

  # The manifest ships a placeholder Secret, so this has to follow the apply
  # or it gets clobbered by it.
  kubectl create secret generic pharmavigil-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=PHARMAVIGIL_ABENIX_API_KEY="${pv_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -2

  kubectl -n "${NAMESPACE}" rollout restart deploy/pharmavigil-api 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout restart deploy/pharmavigil-web 2>&1 | tail -1 || true
  ok "PharmaVigil deployed"
}


deploy_wingman() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "wingman-api" && ! _should_do "wingman-web"; then return 0; fi
  local manifest="${ROOT_DIR}/wingman/k8s/wingman.yaml"
  if [ ! -f "${manifest}" ]; then warn "Wingman manifest missing — skip"; return; fi

  step "Deploying Wingman"
  local wm_key="${WINGMAN_ABENIX_API_KEY:-}"
  if [ -z "${wm_key}" ]; then
    # Reuse an existing tenant key if minted (any of the standalone secrets);
    # else mint fresh.
    wm_key=$(kubectl get secret contractiq-secrets -n "${NAMESPACE}" \
      -o jsonpath='{.data.CONTRACTIQ_ABENIX_API_KEY}' 2>/dev/null | base64 -d 2>/dev/null)
    if [ -z "${wm_key}" ] || [ "${wm_key}" = "PLACEHOLDER_CHANGE_ME" ]; then
      log "  Minting Abenix API key for Wingman..."
      wm_key=$(_generate_abenix_api_key || echo "PLACEHOLDER_CHANGE_ME")
    fi
  fi

  # AISStream.io key — env var on the deploy host. Required for the live
  # AIS feature; the rest of Wingman runs without it.
  local ais_key="${AISSTREAM_API_KEY:-}"
  if [ -z "${ais_key}" ]; then
    warn "AISSTREAM_API_KEY not set — Operations Watch live-AIS will be disabled."
    ais_key="PLACEHOLDER_NEEDS_AISSTREAM_KEY"
  fi

  sed \
    -e "s|localhost:5000/abenix/wingman-api:latest|${ACR_LOGIN_SERVER}/wingman-api:${IMAGE_TAG}|g" \
    -e "s|localhost:5000/abenix/wingman-web:latest|${ACR_LOGIN_SERVER}/wingman-web:${IMAGE_TAG}|g" \
    -e "s|hostPath: { path: /var/lib/abenix/data, type: DirectoryOrCreate }|persistentVolumeClaim: { claimName: abenix-shared-data }|g" \
    -e "s|imagePullPolicy: IfNotPresent|imagePullPolicy: Always|g" \
    "${manifest}" | kubectl apply -f - 2>&1 | tail -5

  kubectl create secret generic wingman-secrets \
    --namespace="${NAMESPACE}" \
    --from-literal=WINGMAN_ABENIX_API_KEY="${wm_key}" \
    --from-literal=AISSTREAM_API_KEY="${ais_key}" \
    --dry-run=client -o yaml | kubectl apply -f - 2>&1 | tail -2

  # Mirror AISSTREAM_API_KEY into the agent-runtime + worker secrets so the
  # ais_stream tool can read it — those pods are what actually open the
  # WebSocket when an agent calls the tool.
  if [ "${ais_key}" != "PLACEHOLDER_NEEDS_AISSTREAM_KEY" ]; then
    log "  Mirroring AISSTREAM_API_KEY into abenix-secrets for the runtime tool..."
    kubectl patch secret -n "${NAMESPACE}" abenix-secrets --type=json \
      -p="[{\"op\":\"add\",\"path\":\"/data/AISSTREAM_API_KEY\",\"value\":\"$(echo -n "${ais_key}" | base64 -w0)\"}]" 2>&1 | tail -1 || true
    kubectl -n "${NAMESPACE}" rollout restart deploy/abenix-agent-runtime-default 2>&1 | tail -1 || true
  fi

  # Always rollout-restart after the secret patch above. kubectl apply
  # on the manifest creates the Secret with REPLACE_AT_DEPLOY_TIME, then
  # the dry-run-apply patches in the real value — but envFrom secrets
  # only re-read at pod start, so without a restart the pod runs with
  # the placeholder forever. The earlier conditional-restart pattern
  # only fired when --only targeted exactly ONE side, which is exactly
  # the case where pods would silently retain the placeholder.
  kubectl -n "${NAMESPACE}" rollout restart deploy/wingman-api 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout restart deploy/wingman-web 2>&1 | tail -1 || true

  kubectl -n "${NAMESPACE}" rollout status deploy/wingman-api --timeout=180s 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout status deploy/wingman-web --timeout=180s 2>&1 | tail -1 || true
  _verify_standalone_envfrom wingman-api wingman-secrets wingman-config || exit 7
  _verify_standalone_envfrom wingman-web wingman-secrets wingman-config || exit 7
  ok "Wingman deployed"
}

deploy_resolveai() {
  if [ -n "${ONLY_CSV}" ] && ! _should_do "resolveai-api" && ! _should_do "resolveai-web"; then return 0; fi
  local manifest="${ROOT_DIR}/resolveai/k8s/resolveai.yaml"
  if [ ! -f "${manifest}" ]; then warn "ResolveAI manifest missing — skip"; return; fi

  step "Deploying ResolveAI"
  local ra_key="${RESOLVEAI_ABENIX_API_KEY:-}"
  if [ -z "${ra_key}" ]; then
    ra_key=$(kubectl get secret contractiq-secrets -n "${NAMESPACE}" \
      -o jsonpath='{.data.CONTRACTIQ_ABENIX_API_KEY}' 2>/dev/null | base64 -d 2>/dev/null)
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

  # Always restart both after the secret patch — see deploy_wingman comment.
  kubectl -n "${NAMESPACE}" rollout restart deploy/resolveai-api 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout restart deploy/resolveai-web 2>&1 | tail -1 || true

  kubectl -n "${NAMESPACE}" rollout status deploy/resolveai-api --timeout=180s 2>&1 | tail -1 || true
  kubectl -n "${NAMESPACE}" rollout status deploy/resolveai-web --timeout=180s 2>&1 | tail -1 || true
  _verify_standalone_envfrom resolveai-api resolveai-secrets resolveai-config || exit 7
  # -web is a Next.js frontend; api carries the platform credentials.
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
    cq_key=$(kubectl get secret contractiq-secrets -n "${NAMESPACE}" \
      -o jsonpath='{.data.CONTRACTIQ_ABENIX_API_KEY}' 2>/dev/null | base64 -d 2>/dev/null)
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
  _verify_standalone_envfrom claimsiq claimsiq-secrets claimsiq-config || exit 7
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
  if [ -f "${dir}/tempo.yaml" ]; then
    kubectl apply -f "${dir}/tempo.yaml" -n "${NAMESPACE}" 2>&1 | tail -1
  fi
  kubectl get secret abenix-grafana-admin -n "${NAMESPACE}" >/dev/null 2>&1 \
    || kubectl create secret generic abenix-grafana-admin -n "${NAMESPACE}" \
         --from-literal=admin-password="${GRAFANA_ADMIN_PASSWORD:-abenix-admin}" 2>&1 | tail -1
  kubectl apply -f "${dir}/grafana.yaml"    -n "${NAMESPACE}" 2>&1 | tail -1
  kubectl rollout restart deployment/abenix-grafana -n "${NAMESPACE}" 2>&1 | tail -1 || true
  kubectl wait --for=condition=Available --timeout=120s deploy/abenix-prometheus -n "${NAMESPACE}" 2>&1 | tail -1 || true
  kubectl wait --for=condition=Available --timeout=120s deploy/abenix-grafana -n "${NAMESPACE}" 2>&1 | tail -1 || true
  # Grant the api SA read on nodes/pods/PVCs so /api/admin/cluster works.
  # Idempotent: safe to apply every deploy.
  if [ -f "${ROOT_DIR}/infra/k8s/abenix-cluster-reader.yaml" ]; then
    kubectl apply -f "${ROOT_DIR}/infra/k8s/abenix-cluster-reader.yaml" 2>&1 | tail -2 || true
  fi
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
            backend: { service: { name: contractiq-web, port: { number: 3001 } } }
    - host: tourism.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: mideasttourism-web, port: { number: 3002 } } }
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
            backend: { service: { name: contractiq-api, port: { number: 8001 } } }
    - host: tourism-api.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: mideasttourism-api, port: { number: 8002 } } }
    - host: grafana.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: abenix-grafana, port: { number: 3000 } } }
    - host: tempo.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: abenix-tempo, port: { number: 3200 } } }
    - host: prom.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: abenix-prometheus, port: { number: 9090 } } }
    - host: safety.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: pharmavigil-web, port: { number: 3007 } } }
    - host: safety-api.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: pharmavigil-api, port: { number: 8007 } } }
    - host: wm.${host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: wingman-web, port: { number: 3006 } } }
EOF

  echo "${host}" > "${ROOT_DIR}/.azure-endpoint"

  # Stamp NEXT_PUBLIC_ABENIX_WEB_URL on standalone web deployments so
  # cross-app links ("/executions", "/code-runner") point at the abenix
  # web ingress rather than 404'ing on the standalone origin.
  local abenix_web_url="http://${host}"
  for dep in industrial-iot-web contractiq-web mideasttourism-web resolveai-web claimsiq; do
    if kubectl -n "${NAMESPACE}" get deploy "${dep}" >/dev/null 2>&1; then
      kubectl -n "${NAMESPACE}" set env deploy/"${dep}" \
        NEXT_PUBLIC_ABENIX_WEB_URL="${abenix_web_url}" 2>&1 | tail -1 || true
    fi
  done

  ok "Ingress ready: http://${host}  (ciq, tourism, iot, care, claims, safety, wm, grafana, prom, tempo each .${host})"
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
  deploy_streaming_tsdb || warn "MQTT/TSDB infra deploy failed (non-fatal — tools fall back to local)"
  deploy_abenix_helm
  deploy_edge_runtime || warn "Edge runtime deploy failed (non-fatal — set EDGE_RUNTIME_ENABLED=false to silence)"
  wait_for_pods 600 || true
  ensure_jwt_keys || true
  run_migrations || true
  seed_agents || true
  verify_subscription || true
  verify_ml_models_shared || true
  report_tool_credentials || true
  _wire_abenix_platform_key || true
  deploy_livekit || warn "LiveKit deploy failed (non-fatal)"
  deploy_contractiq || warn "ContractIQ deploy failed (non-fatal)"
  deploy_mideasttourism || warn "Mideast Tourism deploy failed (non-fatal)"
  deploy_industrial_iot || warn "Industrial-IoT deploy failed (non-fatal)"
  deploy_resolveai || warn "ResolveAI deploy failed (non-fatal)"
  deploy_wingman || warn "Wingman deploy failed (non-fatal)"
  deploy_pharmavigil || warn "PharmaVigil deploy failed (non-fatal)"
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

  # Phase 6 — the gate. Every redeploy MUST end with a clean cluster.
  # reconcile_cluster_state exits non-zero (and bubbles via set -e) if any
  # pod is still stuck after a 5-minute settle window. reconcile_standalone_apps
  # cross-checks the per-app deploy/svc state.
  local reconcile_rc=0
  reconcile_cluster_state || reconcile_rc=$?
  local standalone_rc=0
  reconcile_standalone_apps || standalone_rc=$?
  if [ "${reconcile_rc}" != "0" ] || [ "${standalone_rc}" != "0" ]; then
    err "Deployment finished with stale cluster state — fix above and rerun."
    exit 9
  fi

  ok "Deployment complete"
}

# ── Phase 6 — Cluster reconciliation ────────────────────────────────────────
# Sweeps the abenix namespace at the END of every deploy:
#   1. Reaps always-safe leftovers (Completed/Failed pods, curl-exec debug
#      pods left by `kubectl run --rm` calls that didn't get a TTY hangup).
#   2. Waits up to 5 minutes for any post-deploy pods to settle.
#   3. Classifies anything still bad: stale-image / crashloop / pending /
#      completed-leftover, with actionable log output for each.
#   4. Reports orphan helm releases (chart name not in the known-good list).
#   5. Exits non-zero if anything's still off after the wait window — so the
#      script becomes the gate that catches stale state, not the operator's
#      eyeballs the next morning.
#
# Knobs:
#   REAPER_DELETE_ORPHANS=true → permits deleting orphan deployments / sts.
#     Default off — reversibility matters; we just warn.
#   RECONCILE_WAIT_SECS=300    → upper bound for the "let new pods settle"
#                                wait loop.

# Always-safe cleanup: delete every Completed pod (kubectl run --rm
# leftovers, init-container Jobs that finished, etc.) and any Failed pod
# whose only purpose was to crash. Both classes are by definition recoverable
# from spec (their controllers will recreate them if needed).
_reap_completed_failed_pods() {
  local completed_count failed_count curl_debug_count
  completed_count=$(kubectl get pods -n "${NAMESPACE}" \
    --field-selector=status.phase=Succeeded --no-headers 2>/dev/null \
    | wc -l | tr -d '[:space:]')
  failed_count=$(kubectl get pods -n "${NAMESPACE}" \
    --field-selector=status.phase=Failed --no-headers 2>/dev/null \
    | wc -l | tr -d '[:space:]')
  if [ "${completed_count}" -gt 0 ]; then
    log "  Reaping ${completed_count} Completed pod(s)..."
    kubectl delete pod -n "${NAMESPACE}" \
      --field-selector=status.phase=Succeeded \
      --grace-period=0 --wait=false 2>&1 | tail -3 || true
  fi
  if [ "${failed_count}" -gt 0 ]; then
    log "  Reaping ${failed_count} Failed pod(s)..."
    kubectl delete pod -n "${NAMESPACE}" \
      --field-selector=status.phase=Failed \
      --grace-period=0 --wait=false 2>&1 | tail -3 || true
  fi
  # curl-exec-* / uat-probe-* pods are debug shells from prior sessions
  # (kubectl run with --rm but no TTY close = orphan). They're harmless but
  # they pollute `kubectl get pods` output; nuke any older than 1h.
  curl_debug_count=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null \
    | awk '/^(curl-exec-|uat-probe-)/ { print $1 }' | wc -l | tr -d '[:space:]')
  if [ "${curl_debug_count}" -gt 0 ]; then
    log "  Reaping ${curl_debug_count} curl-exec-* / uat-probe-* debug pod(s)..."
    kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null \
      | awk '/^(curl-exec-|uat-probe-)/ { print $1 }' \
      | xargs -r kubectl delete pod -n "${NAMESPACE}" --grace-period=0 --wait=false 2>&1 \
      | tail -3 || true
  fi
}

# Wait up to RECONCILE_WAIT_SECS for any not-Running pods to settle. Returns
# the LIST of still-bad pod names on stdout; empty stdout = clean cluster.
_wait_for_settle() {
  local timeout="${RECONCILE_WAIT_SECS:-300}"
  local start=$SECONDS
  local bad=""
  while true; do
    bad=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null \
      | awk '$3 !~ /^(Running|Completed|Succeeded)$/ { print $1 }')
    if [ -z "${bad}" ]; then break; fi
    local elapsed=$((SECONDS - start))
    if [ "${elapsed}" -ge "${timeout}" ]; then break; fi
    sleep 10
  done
  echo "${bad}"
}

# Classify one bad pod and print a one-line diagnosis + remediation hint.
# Returns 0 always (caller aggregates).
_classify_bad_pod() {
  local pod="$1"
  local phase reason image owner_kind owner_name
  phase=$(kubectl get pod -n "${NAMESPACE}" "${pod}" -o jsonpath='{.status.phase}' 2>/dev/null)
  # waiting reason on the FIRST container that's stuck
  reason=$(kubectl get pod -n "${NAMESPACE}" "${pod}" \
    -o jsonpath='{.status.containerStatuses[0].state.waiting.reason}' 2>/dev/null)
  image=$(kubectl get pod -n "${NAMESPACE}" "${pod}" \
    -o jsonpath='{.spec.containers[0].image}' 2>/dev/null)
  owner_kind=$(kubectl get pod -n "${NAMESPACE}" "${pod}" \
    -o jsonpath='{.metadata.ownerReferences[0].kind}' 2>/dev/null)
  owner_name=$(kubectl get pod -n "${NAMESPACE}" "${pod}" \
    -o jsonpath='{.metadata.ownerReferences[0].name}' 2>/dev/null)

  case "${reason}" in
    ImagePullBackOff|ErrImagePull)
      err "  ${pod}: STALE-IMAGE (${reason})"
      err "    image:  ${image}"
      err "    owner:  ${owner_kind}/${owner_name}"
      err "    fix:    rebuild + push that tag, or rerun deploy without --only=... to restore canonical state"
      echo "stale-image"
      ;;
    CrashLoopBackOff)
      err "  ${pod}: CRASHLOOP (last 50 log lines):"
      kubectl logs -n "${NAMESPACE}" "${pod}" --tail=50 2>&1 | sed 's/^/      /' || true
      echo "crashloop"
      ;;
    CreateContainerConfigError|CreateContainerError|InvalidImageName)
      err "  ${pod}: CONTAINER-CONFIG (${reason})"
      kubectl describe pod -n "${NAMESPACE}" "${pod}" 2>&1 | grep -E "^\s*(Reason|Message):" | head -4 | sed 's/^/      /' || true
      echo "container-config"
      ;;
    "")
      if [ "${phase}" = "Pending" ]; then
        err "  ${pod}: PENDING — describing node-selector / PVC / quota cause:"
        kubectl describe pod -n "${NAMESPACE}" "${pod}" 2>&1 \
          | grep -E "(FailedScheduling|Insufficient|PersistentVolumeClaim|nodeSelector)" \
          | head -4 | sed 's/^/      /' || true
        echo "pending"
      else
        warn "  ${pod}: phase=${phase} (no waiting reason); kubectl describe for details"
        echo "unknown"
      fi
      ;;
    *)
      warn "  ${pod}: ${reason} (phase=${phase})"
      echo "${reason}"
      ;;
  esac
}

# Cross-check helm releases against the known-good set. Anything else is an
# orphan candidate — chart was removed from the repo but the release lives
# on. Warns; never deletes (chart-level cleanup is operator's call).
_warn_orphan_helm_releases() {
  local known_pattern='^(abenix|abenix-edge|abenix-edge-c|abenix-edge-rust|abenix-mosquitto|abenix-timescaledb|abenix-observability|abenix-keda-mqtt-trigger|abenix-livekit)$'
  local orphans
  orphans=$(helm list -n "${NAMESPACE}" -q 2>/dev/null \
    | grep -Ev "${known_pattern}" || true)
  if [ -n "${orphans}" ]; then
    warn "  Orphan helm release(s) — chart not in canonical set, please review:"
    echo "${orphans}" | sed 's/^/      /'
    if [ "${REAPER_DELETE_ORPHANS}" = "true" ]; then
      warn "  REAPER_DELETE_ORPHANS=true — uninstalling orphans..."
      while IFS= read -r rel; do
        [ -z "${rel}" ] && continue
        helm uninstall "${rel}" -n "${NAMESPACE}" 2>&1 | tail -2 || true
      done <<< "${orphans}"
    fi
  fi
}

# Final reconcile phase. Runs at the END of deploy_all / redeploy.
# Exits the whole script non-zero if anything's still bad after wait+sweep.
reconcile_cluster_state() {
  step "Phase 6 — Reconciling cluster state (sweep + verify clean)"

  log "Reaping always-safe leftovers (Completed/Failed/debug pods)..."
  _reap_completed_failed_pods

  log "Waiting up to ${RECONCILE_WAIT_SECS:-300}s for pods to settle..."
  local bad_list
  bad_list=$(_wait_for_settle)

  _warn_orphan_helm_releases
  log "Checking configmap ownership..."
  _warn_unmanaged_configmaps
  log "Checking Deployment manager labels..."
  _warn_unmanaged_deployments

  if [ -z "${bad_list}" ]; then
    echo ""
    echo -e "  ${GREEN}══════════════════════════════════════════════════════${NC}"
    echo -e "  ${GREEN}  ALL GREEN ✓  — cluster clean${NC}"
    echo -e "  ${GREEN}    0 stale pods, 0 stuck helm releases${NC}"
    echo -e "  ${GREEN}══════════════════════════════════════════════════════${NC}"
    echo ""
    return 0
  fi

  # Classify each remaining bad pod.
  local stale_image=0 crashloop=0 pending=0 other=0
  err "Stale pods detected after ${RECONCILE_WAIT_SECS:-300}s settle window:"
  while IFS= read -r pod; do
    [ -z "${pod}" ] && continue
    local cls
    cls=$(_classify_bad_pod "${pod}" | tail -1)
    case "${cls}" in
      stale-image) stale_image=$((stale_image+1)) ;;
      crashloop)   crashloop=$((crashloop+1)) ;;
      pending)     pending=$((pending+1)) ;;
      *)           other=$((other+1)) ;;
    esac
  done <<< "${bad_list}"

  local total=$((stale_image + crashloop + pending + other))
  echo ""
  err "══════════════════════════════════════════════════════"
  err "  STALE: ${total} pod(s) — breakdown:"
  err "    stale-image:  ${stale_image}"
  err "    crashloop:    ${crashloop}"
  err "    pending:      ${pending}"
  err "    other:        ${other}"
  err "══════════════════════════════════════════════════════"
  echo ""
  return 9
}

# Verify each standalone app's api+web pods are 1/1 Running and the service
# has at least one endpoint. Surfaces silent breakage (deployment landed but
# pod didn't come ready, or service selector drifted off the pod labels).
_check_endpoints_for_svc() {
  local svc="$1"
  local count
  count=$(kubectl get endpoints -n "${NAMESPACE}" "${svc}" \
    -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null \
    | tr ' ' '\n' | grep -c '.' || true)
  echo "${count:-0}"
}

reconcile_standalone_apps() {
  step "Phase 6b — Reconciling standalone apps"
  local apps=(contractiq mideasttourism industrial-iot resolveai wingman claimsiq)
  local failed=0
  for app in "${apps[@]}"; do
    # claimsiq is a single combined deployment (no -api/-web split).
    local deploys=()
    if [ "${app}" = "claimsiq" ]; then
      deploys=(claimsiq)
    else
      deploys=("${app}-api" "${app}-web")
    fi
    for dep in "${deploys[@]}"; do
      if ! kubectl get deploy -n "${NAMESPACE}" "${dep}" >/dev/null 2>&1; then
        warn "  ${dep}: NOT DEPLOYED (deploy_${app//-/_} may have been skipped)"
        continue
      fi
      local ready desired
      ready=$(kubectl get deploy -n "${NAMESPACE}" "${dep}" \
        -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
      desired=$(kubectl get deploy -n "${NAMESPACE}" "${dep}" \
        -o jsonpath='{.spec.replicas}' 2>/dev/null)
      ready="${ready:-0}"; desired="${desired:-1}"
      if [ "${ready}" != "${desired}" ]; then
        err "  ${dep}: ${ready}/${desired} ready — pod isn't healthy"
        failed=$((failed+1))
        continue
      fi
      local ep_count
      ep_count=$(_check_endpoints_for_svc "${dep}")
      if [ "${ep_count}" = "0" ]; then
        err "  ${dep}: 0 service endpoints — selector mismatch or pods unready"
        failed=$((failed+1))
        continue
      fi
      ok "  ${dep}: ${ready}/${desired} ready, ${ep_count} endpoint(s)"
    done
  done
  if [ "${failed}" -gt 0 ]; then
    err "Standalone reconcile: ${failed} deployment(s) unhealthy"
    return 9
  fi
  ok "All standalone apps healthy"
}

# Wrapper around scripts/seed-standalone-keys.sh — runs the per-app loop
# that mints / rotates / patches each standalone secret idempotently.
seed_standalone_keys() {
  if [ -n "${ONLY_CSV}" ]; then
    # When --only is set, only run the reseed if the user is touching
    # standalone-related groups.
    case "${ONLY_CSV}" in
      *contractiq*|*mideasttourism*|*industrial-iot*|*resolveai*|*claimsiq*) ;;
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
  printf "  ${CYAN}%-22s${NC} %s\n" \
    "Abenix Web"          "http://${host}" \
    "Abenix API"          "http://api.${host}/api/health" \
    "ContractIQ"          "http://ciq.${host}" \
    "ContractIQ API"      "http://ciq-api.${host}/api/health" \
    "Mideast Tourism"     "http://tourism.${host}" \
    "Mideast Tourism API" "http://tourism-api.${host}/api/health" \
    "Industrial IoT"      "http://iot.${host}" \
    "ResolveAI"           "http://care.${host}" \
    "ClaimsIQ"            "http://claims.${host}" \
    "ClaimsIQ health"     "http://claims.${host}/actuator/health" \
    "Grafana"             "http://grafana.${host}" \
    "Prometheus"          "http://prom.${host}" \
    "Tempo"               "http://tempo.${host}" \
    "PharmaVigil"         "http://safety.${host}" \
    "PharmaVigil API"     "http://safety-api.${host}/health" \
    "Wingman"             "http://wm.${host}"


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

  if [ "${project}" = "all" ] || [ "${project}" = "contractiq" ]; then
    run_suite "contractiq-wave1" "${ROOT_DIR}/contractiq" \
      BASE_URL="${ciq_base}" API_URL="${ciq_api}" \
      -- --grep "^Wave 1" || true
    run_suite "contractiq-wave2" "${ROOT_DIR}/contractiq" \
      BASE_URL="${ciq_base}" API_URL="${ciq_api}" \
      -- --grep "^Wave 2" || true
  fi

  if [ "${project}" = "all" ] || [ "${project}" = "mideasttourism" ]; then
    run_suite "mideasttourism" "${ROOT_DIR}/mideasttourism" \
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
    kubectl delete -n "${NAMESPACE}" deploy/contractiq-api deploy/contractiq-web deploy/mideasttourism-api deploy/mideasttourism-web deploy/claimsiq 2>/dev/null || true
    kubectl delete -n "${NAMESPACE}" svc/contractiq-api svc/contractiq-web svc/mideasttourism-api svc/mideasttourism-web svc/claimsiq 2>/dev/null || true
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
    verify_subscription || true
  verify_ml_models_shared || true
  report_tool_credentials || true
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
