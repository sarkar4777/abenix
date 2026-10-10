#!/usr/bin/env bash
# Abenix browser UAT. Runs Playwright specs one after another against a live
# stack, prints a summary table and exits non-zero if any spec failed.
#
#   bash scripts/uat.sh                      the durable platform set (default)
#   bash scripts/uat.sh --suite core         one suite: core|autonomy|improvements|admin|apps|all
#   bash scripts/uat.sh --suite core,admin   several suites
#   bash scripts/uat.sh --spec uat_evals     one or more specs by name, comma separated or repeated
#   bash scripts/uat.sh --list               print the specs a run would use and stop
#   bash scripts/uat.sh --bail               stop at the first failing spec
#   bash scripts/uat.sh --seed-only          prepare users and fixtures, run nothing
#
# Env passed through to every spec:
#   BASE (web, default http://localhost:3100)  API (default http://localhost:8000)
#   USE_K8S (default true, skips Playwright's own web server)
#   AF_EMAIL / AF_PASSWORD                     admin, default admin@abenix.dev / Admin123456
#   SECOND_EMAIL / SECOND_PASSWORD             a teammate for the two-person approval steps
#   AF_VIEWER_EMAIL / AF_VIEWER_PASSWORD       low privilege user for the RBAC spec
#   GRAFANA, CLAIMSIQ_BASE, NS, RELEASE        used by single specs
#   PW_ARGS                                    extra arguments for every playwright run
#
# Retired specs and the reasons are listed in docs/08-howto/05-testing.md.

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT_DIR}"

# ── suites ────────────────────────────────────────────────────────────────
SUITE_CORE=(
  uat_first_use_tasks uat_lostness_gate
  uat_core_features_ui uat_nav_build_run_ui uat_platform_journeys_ui uat_user_journey_ui
  uat_chat_memory_ui uat_review_inbox_ui uat_meetings_ui uat_portfolio_ui uat_energy_trading_ui
  uat_abenix_browser uat_abenix_deep uat_abenix_hitl uat_abenix_sdk_playground uat_v110_palette
  uat_enterprise_critical uat_ai_builder_deep_quality uat_evals uat_source_watch
  uat_v2_enterprise uat_rules_to_agents uat_help_surfaces
)
SUITE_AUTONOMY=(uat_autonomy_ui uat_autonomy_complex_ui)
SUITE_IMPROVEMENTS=(uat_improvements_capture_ui uat_improvements_loop_ui uat_ai_build_and_heal_ui)
SUITE_ADMIN=(
  uat_cluster_view_ui uat_nav_monitor_admin_ui uat_marketplace_ui uat_governance
  uat_abenix_multi_user uat_platform_surfaces uat_abenix_industrial uat_grafana_panels
)
# standalone apps, each owned by its app; they need the app stacks running
SUITE_APPS=(
  uat_model_fallback_ui uat_apps_full uat_wingman uat_claimsiq_deep uat_pharmavigil
  uat_resolveai_browser uat_contractiq_browser
)

usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; }

suites="default"
specs_arg=""
list_only=false
bail=false
seed_only=false
while [ $# -gt 0 ]; do
  case "$1" in
    --suite) suites="${2:?--suite needs a value}"; shift 2 ;;
    --suite=*) suites="${1#*=}"; shift ;;
    --spec) specs_arg="${specs_arg:+${specs_arg},}${2:?--spec needs a value}"; shift 2 ;;
    --spec=*) specs_arg="${specs_arg:+${specs_arg},}${1#*=}"; shift ;;
    --list) list_only=true; shift ;;
    --bail) bail=true; shift ;;
    --seed-only) seed_only=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1"; usage; exit 2 ;;
  esac
done

SPECS=()
add_suite() {
  case "$1" in
    core) SPECS+=("${SUITE_CORE[@]}") ;;
    autonomy) SPECS+=("${SUITE_AUTONOMY[@]}") ;;
    improvements) SPECS+=("${SUITE_IMPROVEMENTS[@]}") ;;
    admin) SPECS+=("${SUITE_ADMIN[@]}") ;;
    apps) SPECS+=("${SUITE_APPS[@]}") ;;
    default) for s in core autonomy improvements admin; do add_suite "$s"; done ;;
    all) for s in default apps; do add_suite "$s"; done ;;
    *) echo "unknown suite: $1 (core|autonomy|improvements|admin|apps|all)"; exit 2 ;;
  esac
}
if [ -n "${specs_arg}" ]; then
  IFS=',' read -r -a SPECS <<< "${specs_arg}"
else
  IFS=',' read -r -a _suites <<< "${suites}"
  for s in "${_suites[@]}"; do add_suite "$s"; done
fi

# drop duplicates, keep order, and check every file exists
_uniq=()
for s in "${SPECS[@]}"; do
  s="${s%.spec.ts}"; s="${s#e2e/}"
  case " ${_uniq[*]-} " in *" ${s} "*) continue ;; esac
  if [ ! -f "e2e/${s}.spec.ts" ]; then echo "  ✗ no such spec: e2e/${s}.spec.ts"; exit 2; fi
  _uniq+=("$s")
done
SPECS=("${_uniq[@]}")

if ${list_only}; then
  printf '%s\n' "${SPECS[@]}"
  exit 0
fi

# ── environment ───────────────────────────────────────────────────────────
export USE_K8S="${USE_K8S:-true}"
export BASE="${BASE:-http://localhost:3100}"
export API="${API:-http://localhost:8000}"
export AF_EMAIL="${AF_EMAIL:-admin@abenix.dev}"
export AF_PASSWORD="${AF_PASSWORD:-Admin123456}"
export AF_VIEWER_EMAIL="${AF_VIEWER_EMAIL:-viewer@abenix.dev}"
export AF_VIEWER_PASSWORD="${AF_VIEWER_PASSWORD:-Viewer123456}"
if [ -n "${SECOND_EMAIL:-}" ]; then export SECOND_EMAIL SECOND_PASSWORD="${SECOND_PASSWORD:-}"; fi
# older specs read these names for the same values
export BASE_URL="${BASE_URL:-$BASE}" API_URL="${API_URL:-$API}"
export BASE_AB="${BASE_AB:-$BASE}" AB_API="${AB_API:-$API}" ABENIX_BASE="${ABENIX_BASE:-$BASE}"
export ADMIN_EMAIL="${ADMIN_EMAIL:-$AF_EMAIL}" ADMIN_PASSWORD="${ADMIN_PASSWORD:-$AF_PASSWORD}"
export NS="${NS:-abenix}" RELEASE="${RELEASE:-abenix}"
export GRAFANA="${GRAFANA:-http://localhost:3030}"
have_kubectl=false
if command -v kubectl >/dev/null 2>&1 && kubectl -n "${NS}" get deploy >/dev/null 2>&1; then
  have_kubectl=true
fi
_gf_admin() {
  ${have_kubectl} || return 0
  local base="jsonpath={.spec.template.spec.containers[0].env[?(@.name=='$1')]"
  local v sec key
  v=$(kubectl get deploy -n "${NS}" "${RELEASE}-grafana" -o "${base}.value}" 2>/dev/null || true)
  if [ -z "${v}" ]; then
    # the admin password comes from a secretKeyRef, not a literal
    sec=$(kubectl get deploy -n "${NS}" "${RELEASE}-grafana" -o "${base}.valueFrom.secretKeyRef.name}" 2>/dev/null || true)
    key=$(kubectl get deploy -n "${NS}" "${RELEASE}-grafana" -o "${base}.valueFrom.secretKeyRef.key}" 2>/dev/null || true)
    if [ -n "${sec}" ] && [ -n "${key}" ]; then
      v=$(kubectl get secret -n "${NS}" "${sec}" -o "jsonpath={.data.${key}}" 2>/dev/null | base64 -d 2>/dev/null || true)
    fi
  fi
  printf '%s' "${v}"
}
export GRAFANA_USER="${GRAFANA_USER:-$(_gf_admin GF_SECURITY_ADMIN_USER)}"
export GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-$(_gf_admin GF_SECURITY_ADMIN_PASSWORD)}"

needs() { # needs <spec>  true when the run includes it
  local s; for s in "${SPECS[@]}"; do [ "$s" = "$1" ] && return 0; done; return 1
}

# ── preflight ─────────────────────────────────────────────────────────────
echo "▶ Smoke checks (BASE=${BASE} API=${API})"
reachable() { # reachable <url>  a forward can blip for a few seconds, try three times
  local i; for i in 1 2 3; do curl -sf -m 20 "$1" -o /dev/null && return 0; sleep 5; done; return 1
}
reachable "${API}/api/health" || { echo "  ✗ API not reachable at ${API}. Run bash scripts/deploy.sh forwards"; exit 2; }
reachable "${BASE}/" || { echo "  ✗ Web not reachable at ${BASE}. Run bash scripts/deploy.sh forwards"; exit 2; }
echo "  ✓ API and web reachable"

# a spec run during a rollout hits pods that are about to go away
if ${have_kubectl}; then
  rolling="$(kubectl -n "${NS}" get deploy -o jsonpath='{range .items[*]}{.metadata.name} {.spec.replicas} {.status.updatedReplicas} {.status.readyReplicas}{"\n"}{end}' 2>/dev/null \
    | awk '$2>0 && ($3!=$2 || $4!=$2) {print $1}')"
  if [ -n "${rolling}" ]; then
    echo "  ! rollout in progress or pods not ready, failures may be noise:"
    printf '      %s\n' ${rolling}
  fi
fi

# a rotated Claude subscription token fails every model step with a 401
_admin_tok=$(curl -sf -X POST "${API}/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${AF_EMAIL}\",\"password\":\"${AF_PASSWORD}\"}" \
  | python -c 'import sys,json; j=json.load(sys.stdin); print((j.get("data") or j).get("access_token",""))' 2>/dev/null || true)
if [ -n "${_admin_tok}" ] && curl -s -m 60 -X POST "${API}/api/admin/settings/subscription/verify" \
    -H "Authorization: Bearer ${_admin_tok}" -H 'Content-Type: application/json' -d '{}' | grep -qi 'revoked'; then
  echo "  ! the Claude subscription token was revoked, run bash scripts/sync-claude-subscription.sh"
fi

if [ ! -f "e2e/fixtures/uat_kb_doc.pdf" ] || [ ! -f "e2e/fixtures/uat_ml_model.pkl" ] \
  || [ e2e/fixtures/build.py -nt e2e/fixtures/uat_ml_model.pkl ]; then
  echo "▶ Regenerating UAT fixtures"
  python e2e/fixtures/build.py
fi

# the RBAC spec signs in as a low privilege member of the admin's tenant
seed_viewer() {
  local tok http resp
  tok=$(curl -sf -X POST "${API}/api/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\":\"${AF_EMAIL}\",\"password\":\"${AF_PASSWORD}\"}" \
    | python -c 'import sys,json; j=json.load(sys.stdin); print((j.get("data") or j).get("access_token",""))') || true
  [ -n "${tok}" ] || { echo "  ✗ admin login failed for ${AF_EMAIL}"; return 1; }
  resp=$(mktemp)
  http=$(curl -s -o "${resp}" -w '%{http_code}' -X POST "${API}/api/team/dev-create-member" \
    -H "Authorization: Bearer ${tok}" -H 'Content-Type: application/json' \
    -d "{\"email\":\"${AF_VIEWER_EMAIL}\",\"password\":\"${AF_VIEWER_PASSWORD}\",\"role\":\"user\"}")
  case "${http}" in
    201) echo "  ✓ created ${AF_VIEWER_EMAIL}" ;;
    409) echo "  ✓ ${AF_VIEWER_EMAIL} already exists" ;;
    *) echo "  ✗ HTTP ${http} from dev-create-member"; cat "${resp}"; rm -f "${resp}"; return 1 ;;
  esac
  rm -f "${resp}"
}
if needs uat_abenix_multi_user || ${seed_only}; then
  echo "▶ Seeding viewer ${AF_VIEWER_EMAIL}"
  seed_viewer || exit 1
fi

# in-cluster MCP fixtures for the industrial and platform-surfaces specs
bring_up_mcp() { # bring_up_mcp <deploy-name> <manifest> <dockerfile>
  local name="$1" manifest="$2" dockerfile="$3"
  kubectl -n "${NS}" get deploy "${name}" >/dev/null 2>&1 || kubectl apply -f "${manifest}"
  # the manifests carry a placeholder registry that minikube cannot pull
  if kubectl config current-context 2>/dev/null | grep -q minikube \
      && ! kubectl -n "${NS}" get deploy "${name}" -o jsonpath='{.spec.template.spec.containers[0].image}' | grep -q '^localhost:5000/'; then
    echo "  minikube, building ${name} locally"
    eval "$(minikube docker-env)"
    docker build -q -t "localhost:5000/abenix/${name}:latest" -f "${dockerfile}" e2e/fixtures/mcp_server >/dev/null
    kubectl -n "${NS}" set image "deploy/${name}" "server=localhost:5000/abenix/${name}:latest" >/dev/null
    kubectl -n "${NS}" patch deploy "${name}" --type=json \
      -p '[{"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Never"}]' >/dev/null
  fi
  kubectl -n "${NS}" rollout status "deploy/${name}" --timeout=120s >/dev/null || { echo "  ✗ ${name} never became ready"; return 1; }
  echo "  ✓ ${name} ready"
}
if ${have_kubectl} && { needs uat_abenix_industrial || needs uat_platform_surfaces || ${seed_only}; }; then
  echo "▶ MCP fixtures"
  bring_up_mcp uat-mcp e2e/fixtures/mcp_server/deployment.yaml e2e/fixtures/mcp_server/Dockerfile || exit 1
  bring_up_mcp custom-mcp e2e/fixtures/mcp_server/deployment-custom.yaml e2e/fixtures/mcp_server/Dockerfile.custom || exit 1
  allowed="$(kubectl -n "${NS}" get configmap "${RELEASE}-config" -o jsonpath='{.data.MCP_ALLOWED_HOSTS}' 2>/dev/null || true)"
  for host in uat-mcp custom-mcp; do
    case "${allowed}" in
      *"${host}.${NS}.svc.cluster.local"*) ;;
      *) echo "  ✗ ${host}.${NS}.svc.cluster.local is not in MCP_ALLOWED_HOSTS, add it to mcpAllowedHosts in values-local.yaml"; exit 1 ;;
    esac
  done
fi

if ${seed_only}; then
  echo "  ✓ seed-only, no specs run"
  exit 0
fi

# ── run ───────────────────────────────────────────────────────────────────
# outside e2e/test-results, which every playwright run empties
LOG_DIR="${ROOT_DIR}/logs/uat"
mkdir -p "${LOG_DIR}"
R_NAME=(); R_STATUS=(); R_PASSED=(); R_FAILED=(); R_SKIPPED=(); R_NOTRUN=(); R_SECS=()
overall=0

count_of() { # count_of <word> <log>  the number Playwright printed before it
  grep -Eo "^ +[0-9]+ $1" "$2" | tail -1 | grep -Eo '[0-9]+' || echo 0
}

for spec in "${SPECS[@]}"; do
  echo
  echo "════ ${spec} ════"
  log="${LOG_DIR}/${spec}.log"
  # a redeploy between specs drops the forwards, wait rather than fail every test
  if ! reachable "${API}/api/health" || ! reachable "${BASE}/"; then
    echo "  ! API or web is not answering, waiting up to 3 minutes (bash scripts/deploy.sh forwards restarts them)"
    for _ in $(seq 1 18); do curl -sf -m 5 "${API}/api/health" -o /dev/null && curl -sf -m 10 "${BASE}/" -o /dev/null && break; sleep 10; done
  fi
  start=$(date +%s)
  base_url="${BASE_URL}"
  # ClaimsIQ is its own Vaadin app, not the Abenix web UI
  [ "${spec}" = "uat_claimsiq_deep" ] && base_url="${CLAIMSIQ_BASE:-http://localhost:3005}"
  # shellcheck disable=SC2086
  BASE_URL="${base_url}" npx playwright test "e2e/${spec}.spec.ts" --project=chromium --workers=1 \
    --reporter=list --output="e2e/test-results/${spec}" ${PW_ARGS:-} 2>&1 | tee "${log}"
  rc=${PIPESTATUS[0]}
  R_NAME+=("${spec}")
  R_PASSED+=("$(count_of passed "${log}")")
  R_FAILED+=("$(count_of failed "${log}")")
  R_SKIPPED+=("$(count_of skipped "${log}")")
  R_NOTRUN+=("$(count_of "did not run" "${log}")")
  R_SECS+=("$(( $(date +%s) - start ))")
  if [ "${rc}" -eq 0 ]; then R_STATUS+=("PASS"); else R_STATUS+=("FAIL"); overall=1; fi
  if [ "${rc}" -ne 0 ] && ${bail}; then break; fi
done

echo
echo "════ UAT summary ════"
printf '%-34s %-6s %6s %6s %7s %7s %7s\n' SPEC RESULT PASSED FAILED SKIPPED NOTRUN SECONDS
for i in "${!R_NAME[@]}"; do
  printf '%-34s %-6s %6s %6s %7s %7s %7s\n' "${R_NAME[$i]}" "${R_STATUS[$i]}" "${R_PASSED[$i]}" "${R_FAILED[$i]}" "${R_SKIPPED[$i]}" "${R_NOTRUN[$i]}" "${R_SECS[$i]}"
done
echo "logs: ${LOG_DIR}"
if [ "${overall}" -ne 0 ]; then echo "UAT FAILED"; else echo "UAT PASSED"; fi
exit "${overall}"
