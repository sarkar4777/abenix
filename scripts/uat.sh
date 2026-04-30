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

run_spec "Sanity"     "e2e/uat_abenix_browser.spec.ts"
run_spec "Deep"       "e2e/uat_abenix_deep.spec.ts"
run_spec "Industrial" "e2e/uat_abenix_industrial.spec.ts"

echo
echo "════════════════════════════════════════════════════════════════"
echo "  ALL UAT SPECS PASSED — deploy gate green"
echo "════════════════════════════════════════════════════════════════"
