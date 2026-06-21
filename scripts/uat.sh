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
export AF_EMAIL="${AF_EMAIL:-admin@abenix.dev}"
export AF_PASSWORD="${AF_PASSWORD:-Admin123456}"
# Second user (low-privilege, lives inside the admin's tenant) used by the
# Multi-User RBAC spec. Override per-env if you need a different account.
export AF_VIEWER_EMAIL="${AF_VIEWER_EMAIL:-viewer@abenix.dev}"
export AF_VIEWER_PASSWORD="${AF_VIEWER_PASSWORD:-Viewer123456}"

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

if [ "${1:-}" = "--seed-only" ]; then
  echo "  ✓ seed-only mode — exiting before specs run"
  exit 0
fi

# Verify the in-cluster UAT MCP server is up — the industrial spec
# depends on it. Auto-apply the manifest if missing.
if ! kubectl -n abenix get deploy uat-mcp >/dev/null 2>&1; then
  echo "▶ Applying UAT MCP manifest..."
  kubectl apply -f e2e/fixtures/mcp_server/deployment.yaml
fi
kubectl -n abenix rollout status deploy/uat-mcp --timeout=120s 2>&1 | tail -1
echo "  ✓ uat-mcp ready"

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
run_spec "ClaimsIQ Deep"   "e2e/uat_claimsiq_deep.spec.ts"

echo
echo "════════════════════════════════════════════════════════════════"
echo "  ALL UAT SPECS PASSED — deploy gate green"
echo "════════════════════════════════════════════════════════════════"
