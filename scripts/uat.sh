#!/usr/bin/env bash
# Abenix canonical UAT — runs all three browser-driven specs in
# the order required by deploy-gating policy.
#
#   1. Sanity     — uat_abenix_browser.spec.ts        (61 tests)
#   2. Deep       — uat_abenix_deep.spec.ts           (31 tests)
#   3. Industrial — uat_abenix_industrial.spec.ts     (~18 tests)
#
# Pre-requisites:
#   • port-forward 3000 → svc/abenix-web
#   • port-forward 8000 → svc/abenix-api
#   • python e2e/fixtures/build.py has been run at least once
#   • e2e/fixtures/mcp_server has been built/pushed/applied to the
#     cluster — see e2e/fixtures/mcp_server/README.md.
#
# A single failure in any spec aborts the run with a non-zero exit
# code. This is the gate the deploy pipeline reads.
#
# Override env:
#   BASE=http://localhost:3000  API=http://localhost:8000
#   AF_EMAIL=admin@abenix.dev AF_PASSWORD=Admin123456

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT_DIR}"

export BASE="${BASE:-http://localhost:3000}"
export API="${API:-http://localhost:8000}"
# uat_apps_full.spec.ts reads these names, keep them in step with BASE and API
export BASE_AB="${BASE_AB:-$BASE}"
export AB_API="${AB_API:-$API}"
export AF_EMAIL="${AF_EMAIL:-admin@abenix.dev}"
export AF_PASSWORD="${AF_PASSWORD:-Admin123456}"
# Second user (low-privilege, lives inside the admin's tenant) used by the
# Multi-User RBAC spec. Override per-env if you need a different account.
export AF_VIEWER_EMAIL="${AF_VIEWER_EMAIL:-viewer@abenix.dev}"
export AF_VIEWER_PASSWORD="${AF_VIEWER_PASSWORD:-Viewer123456}"
# The Grafana spec defaults to the Azure host, which is not reachable from
# a local run. deploy.sh forwards grafana to 3030. Anonymous viewing is off in
# the chart, so the spec needs credentials — read them off the deployment so
# they cannot drift from what is actually running.
export GRAFANA="${GRAFANA:-http://localhost:3030}"
_gf_admin() {
  kubectl get deploy -n abenix abenix-grafana \
    -o "jsonpath={.spec.template.spec.containers[0].env[?(@.name=='$1')].value}" 2>/dev/null || true
}
export GRAFANA_USER="${GRAFANA_USER:-$(_gf_admin GF_SECURITY_ADMIN_USER)}"
export GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-$(_gf_admin GF_SECURITY_ADMIN_PASSWORD)}"

# Ensure binary fixtures exist before anyone drives the spec.
if [ ! -f "e2e/fixtures/uat_kb_doc.pdf" ] || [ ! -f "e2e/fixtures/uat_python_app.zip" ] \
    || [ ! -f "e2e/fixtures/uat_ml_model.pkl" ]; then
  echo "▶ Regenerating UAT fixtures..."
  python e2e/fixtures/build.py
fi

# Smoke-check the cluster surface so failures are obvious up-front.
echo "▶ Smoke checks..."
curl -sf "${API}/api/health" > /dev/null || {
  echo "  ✘ API not reachable at ${API} — port-forward 8000?"; exit 2;
}
curl -sf "${BASE}/" > /dev/null || {
  echo "  ✘ Web not reachable at ${BASE} — port-forward 3000?"; exit 2;
}
echo "  ✓ API + Web reachable"

# ── Seed the low-privilege "viewer" user used by the Multi-User RBAC spec.
# Uses POST /api/team/dev-create-member so the new user lands in the SAME
# tenant as the admin (the public /api/auth/register creates a brand-new
# tenant — wrong shape for tenant-internal RBAC tests). Idempotent: if the
# user already exists the endpoint returns 409 and we move on.
seed_viewer() {
  echo "▶ Seeding viewer ${AF_VIEWER_EMAIL} ..."
  local login_json
  login_json=$(curl -sf -X POST "${API}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"${AF_EMAIL}\",\"password\":\"${AF_PASSWORD}\"}") || {
    echo "  ✘ admin login failed — cannot seed viewer"; return 1;
  }
  local tok
  tok=$(printf '%s' "${login_json}" | python -c \
    'import sys,json; j=json.load(sys.stdin); print((j.get("data") or j).get("access_token",""))')
  if [ -z "${tok}" ]; then
    echo "  ✘ admin token missing in login response"; return 1;
  fi
  local resp http
  resp=$(mktemp)
  http=$(curl -s -o "${resp}" -w '%{http_code}' \
    -X POST "${API}/api/team/dev-create-member" \
    -H "Authorization: Bearer ${tok}" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"${AF_VIEWER_EMAIL}\",\"password\":\"${AF_VIEWER_PASSWORD}\",\"role\":\"user\"}")
  case "${http}" in
    201) echo "  ✓ created ${AF_VIEWER_EMAIL}" ;;
    409) echo "  ✓ ${AF_VIEWER_EMAIL} already exists (idempotent)" ;;
    *)   echo "  ✘ unexpected HTTP ${http} from dev-create-member:"; cat "${resp}"; rm -f "${resp}"; return 1;;
  esac
  rm -f "${resp}"
}

seed_viewer

# Bring up an in-cluster MCP fixture. Both fixtures are applied the same way,
# so this is one function rather than two copies that drift apart.
#
# The manifests ship a placeholder registry, because publish-public.sh scrubs
# real ACR names out of the tree. On minikube that can never pull, which
# aborted the whole gate before a single spec ran. Build into the minikube
# daemon and point the deployment at that instead.
bring_up_mcp() { # bring_up_mcp <deploy-name> <manifest> <dockerfile> <needed-by>
  local name="$1" manifest="$2" dockerfile="$3" needed_by="$4"

  if ! kubectl -n abenix get deploy "${name}" >/dev/null 2>&1; then
    echo "▶ Applying ${name} manifest..."
    kubectl apply -f "${manifest}"
  fi

  if kubectl config current-context 2>/dev/null | grep -q minikube; then
    echo "▶ minikube — building ${name} locally"
    eval "$(minikube docker-env)"
    docker build -q -t "localhost:5000/abenix/${name}:latest" \
      -f "${dockerfile}" e2e/fixtures/mcp_server >/dev/null
    kubectl -n abenix set image "deploy/${name}" \
      "server=localhost:5000/abenix/${name}:latest" >/dev/null
    kubectl -n abenix patch deploy "${name}" --type=json \
      -p '[{"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Never"}]' >/dev/null
  fi

  if ! kubectl -n abenix rollout status "deploy/${name}" --timeout=120s; then
    echo "  ✗ ${name} never became ready — ${needed_by} needs it."
    kubectl -n abenix describe pod -l "app=${name}" | sed -n '/Events:/,$p' | tail -12
    exit 1
  fi
  echo "  ✓ ${name} ready"
}

bring_up_mcp uat-mcp \
  e2e/fixtures/mcp_server/deployment.yaml \
  e2e/fixtures/mcp_server/Dockerfile \
  "the Industrial spec"

bring_up_mcp custom-mcp \
  e2e/fixtures/mcp_server/deployment-custom.yaml \
  e2e/fixtures/mcp_server/Dockerfile.custom \
  "the platform-surfaces spec"

# A registered MCP host has to be on the API's allow-list or registration
# answers 400 long before it tries to connect. Say so here rather than let a
# spec fail with a status code and no explanation.
allowed="$(kubectl -n abenix get configmap abenix-config \
  -o jsonpath='{.data.MCP_ALLOWED_HOSTS}' 2>/dev/null || true)"
for host in uat-mcp custom-mcp; do
  case "${allowed}" in
    *"${host}.abenix.svc.cluster.local"*) ;;
    *)
      echo "  ✗ ${host}.abenix.svc.cluster.local is not in MCP_ALLOWED_HOSTS."
      echo "    Add it to mcpAllowedHosts in infra/helm/abenix/values-local.yaml"
      echo "    and redeploy. Registration would answer 400 otherwise."
      exit 1
      ;;
  esac
done
echo "  ✓ both MCP hosts are on the allow-list"

# Fixtures come up before this exit. --seed-only means prepare the cluster
# and stop, and the MCP fixtures are part of preparing it.
if [ "${1:-}" = "--seed-only" ]; then
  echo "  ✓ seed-only mode — exiting before specs run"
  exit 0
fi

# Run each spec — abort on first failure (set -e).
export PLAYWRIGHT_HTML_REPORT=playwright-report

run_spec() {
  local label="$1"
  local spec="$2"
  echo
  echo "════════════════════════════════════════════════════════════════"
  echo "  ${label} → ${spec}"
  echo "════════════════════════════════════════════════════════════════"
  npx playwright test "${spec}" --reporter=list --workers=1 --timeout=300000
}

run_spec "Sanity"          "e2e/uat_abenix_browser.spec.ts"
run_spec "Deep"            "e2e/uat_abenix_deep.spec.ts"
run_spec "Industrial"      "e2e/uat_abenix_industrial.spec.ts"
run_spec "HITL"            "e2e/uat_abenix_hitl.spec.ts"
run_spec "SDK Playground"  "e2e/uat_abenix_sdk_playground.spec.ts"
run_spec "Apps Full"       "e2e/uat_apps_full.spec.ts"
run_spec "Wingman"         "e2e/uat_wingman.spec.ts"
run_spec "Multi-User RBAC" "e2e/uat_abenix_multi_user.spec.ts"
# ClaimsIQ is the Vaadin app on its own port — BASE for every other spec
# points at the Abenix web UI, which is not what this one drives.
BASE_URL="${CLAIMSIQ_BASE:-http://localhost:3005}" API_URL="${API}" \
  run_spec "ClaimsIQ Deep"   "e2e/uat_claimsiq_deep.spec.ts"
run_spec "Grafana Panels"  "e2e/uat_grafana_panels.spec.ts"
run_spec "PharmaVigil"     "e2e/uat_pharmavigil.spec.ts"
run_spec "Help surfaces"   "e2e/uat_help_surfaces.spec.ts"
run_spec "Platform surfaces" "e2e/uat_platform_surfaces.spec.ts"

echo
echo "════════════════════════════════════════════════════════════════"
echo "  ALL UAT SPECS PASSED — deploy gate green"
echo "════════════════════════════════════════════════════════════════"
