#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${CYAN}[e2e]${NC} $1"; }
ok()   { echo -e "${GREEN}  [ok]${NC} $1"; }
warn() { echo -e "${YELLOW}  [warn]${NC} $1"; }
err()  { echo -e "${RED}  [err]${NC} $1"; }

# ── Parse args ───────────────────────────────────────────────────────────────
USE_K8S=""
HEADED=""
TEST_FILTER=""
EXTRA_ARGS=""

for arg in "$@"; do
  case "${arg}" in
    --k8s)       USE_K8S="true" ;;
    --headed)    HEADED="--headed" ;;
    sanity)      TEST_FILTER="uat_abenix_browser" ;;
    deep)        TEST_FILTER="uat_abenix_deep" ;;
    industrial)  TEST_FILTER="uat_abenix_industrial" ;;
    all)         TEST_FILTER="uat_abenix_" ;;
    *)           EXTRA_ARGS="${EXTRA_ARGS} ${arg}" ;;
  esac
done

API_URL="${API_URL:-http://localhost:8000}"
BASE_URL="${BASE_URL:-http://localhost:3000}"

# ── Verify services ─────────────────────────────────────────────────────────
log "Checking service availability..."

check_service() {
  local name="$1" url="$2"
  if curl -sf --max-time 5 "${url}" -o /dev/null 2>/dev/null; then
    ok "${name} reachable at ${url}"
    return 0
  else
    err "${name} not reachable at ${url}"
    return 1
  fi
}

API_OK=false
WEB_OK=false

check_service "API" "${API_URL}/api/health" && API_OK=true
check_service "Web" "${BASE_URL}" && WEB_OK=true

if [ "${API_OK}" != "true" ]; then
  err "API is not running. Start services first:"
  echo "  Local dev:  bash scripts/dev-local.sh"
  echo "  Kubernetes: bash scripts/deploy.sh local-runtime"
  exit 1
fi

if [ "${WEB_OK}" != "true" ] && [ -z "${USE_K8S}" ]; then
  warn "Web not reachable — Playwright will auto-start it"
fi

# ── Install browsers if needed ───────────────────────────────────────────────
if ! npx playwright install --dry-run chromium &>/dev/null 2>&1; then
  log "Installing Playwright browsers..."
  npx playwright install chromium 2>&1 | tail -3
fi

# ── Run tests ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}>> Running E2E Tests${NC}"
echo ""

export API_URL
export BASE_URL

if [ -n "${USE_K8S}" ]; then
  export USE_K8S="true"
  log "Mode: K8s deployment (skipping webServer auto-start)"
else
  log "Mode: Local dev (webServer auto-start enabled)"
fi

if [ -n "${TEST_FILTER}" ]; then
  log "Filter: ${TEST_FILTER}"
fi

PLAYWRIGHT_CMD="npx playwright test"

if [ -n "${TEST_FILTER}" ]; then
  PLAYWRIGHT_CMD="${PLAYWRIGHT_CMD} ${TEST_FILTER}"
fi

if [ -n "${HEADED}" ]; then
  PLAYWRIGHT_CMD="${PLAYWRIGHT_CMD} --headed"
fi

PLAYWRIGHT_CMD="${PLAYWRIGHT_CMD}${EXTRA_ARGS}"

log "Running: ${PLAYWRIGHT_CMD}"
echo ""

set +e
${PLAYWRIGHT_CMD}
TEST_EXIT=$?
set -e

# ── Report ───────────────────────────────────────────────────────────────────
echo ""
if [ "${TEST_EXIT}" -eq 0 ]; then
  echo -e "${GREEN}================================================================${NC}"
  echo -e "${GREEN}  All E2E tests passed!${NC}"
  echo -e "${GREEN}================================================================${NC}"
else
  echo -e "${RED}================================================================${NC}"
  echo -e "${RED}  Some E2E tests failed (exit code: ${TEST_EXIT})${NC}"
  echo -e "${RED}================================================================${NC}"
fi

echo ""
echo -e "  ${CYAN}HTML Report:${NC}   npx playwright show-report"
echo -e "  ${CYAN}Screenshots:${NC}   e2e/screenshots/"
echo -e "  ${CYAN}Test Results:${NC}  e2e/test-results/"
echo ""

# Show screenshots if any were captured
if [ -d "e2e/screenshots" ]; then
  local_screenshots=$(ls -1 e2e/screenshots/*.png 2>/dev/null | wc -l)
  local_screenshots=$(echo "${local_screenshots}" | tr -d '[:space:]')
  if [ "${local_screenshots}" -gt 0 ]; then
    echo -e "  ${YELLOW}Screenshots captured:${NC}"
    ls -1 e2e/screenshots/*.png 2>/dev/null | sed 's/^/    /'
    echo ""
  fi
fi

exit ${TEST_EXIT}
