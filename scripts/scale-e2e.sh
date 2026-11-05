#!/usr/bin/env bash
# Proves the autoscalers on the live local cluster with real pods and real load.
#
#   bash scripts/scale-e2e.sh                  every check, about 30 minutes
#   CHECKS="a b c" bash scripts/scale-e2e.sh   only these checks
#   KEEP=1 bash scripts/scale-e2e.sh           leave the overlay and test agents in place
#
# Checks a to l are named in the table it prints, n is a run to a pool that is not
# deployed, m is a queued run nothing picks up. Deploy this branch first, the script
# stops with exit 2 when the running API does not have the code it tests.
#
# Exits 0 when nothing failed, 1 when a check failed, 2 when it could not run.
# Compatible with the bash 3.2 macOS ships. Secrets stay in a private temp directory.

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS="${NAMESPACE:-abenix}"
REL="${RELEASE_NAME:-abenix}"
HELM_DIR="${ROOT_DIR}/infra/helm/abenix"
OVERLAY="${SCALE_OVERLAY:-${HELM_DIR}/values-scale-test.yaml}"
CHECKS="${CHECKS:-a n m b c d e g f h i j l k}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@abenix.dev}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-Admin123456}"
PF_PORT="${SCALE_API_PORT:-18765}"
BASE="http://127.0.0.1:${PF_PORT}"
RUN="$(date +%m%d%H%M%S)"
POOL_DEFAULT="${REL}-agent-runtime-default"
POOL_ZERO="${REL}-agent-runtime-long-running"
POOL_PARKED="${REL}-agent-runtime-chat"
CATCHER="http://${REL}-webhook-catcher.${NS}.svc.cluster.local:8080"
BURST_RUNS="${BURST_RUNS:-30}"
FAST_SECONDS="${FAST_SECONDS:-6}"
LONG_SECONDS="${LONG_SECONDS:-100}"
STARTED_AT=$(date +%s)

OUT="$(mktemp -d "${TMPDIR:-/tmp}/scale-e2e.XXXXXX")"
PRIVATE="$(mktemp -d "${TMPDIR:-/tmp}/scale-e2e-private.XXXXXX")"
chmod 700 "${PRIVATE}"
AUTH="${PRIVATE}/auth"
: > "${AUTH}"
chmod 600 "${AUTH}"

RESULT_NAMES=""
RESULT_LINES="${OUT}/results.txt"
: > "${RESULT_LINES}"
NUMBERS="${OUT}/numbers.txt"
: > "${NUMBERS}"
FAILED=0
BG_PIDS=""
PF_PID=""
AGENTS=""
DEDICATED_AGENT=""
ASSET_ID=""
DECISION_KEY=""
PREV_REV=""
OVERLAY_ON=0
CLEANED=0
REPLICA_SNAPSHOT="${OUT}/replicas-before.txt"
: > "${REPLICA_SNAPSHOT}"

log() { printf '%s [%4ss] %s\n' "$(date +%H:%M:%S)" "$(($(date +%s) - STARTED_AT))" "$*"; }
number() { printf '%-44s %s\n' "$1" "$2" >> "${NUMBERS}"; log "measured ${1} ${2}"; }

record() { # record <check> <PASS|FAIL|SKIP> <detail>
  printf '%s|%s|%s\n' "$1" "$2" "$3" >> "${RESULT_LINES}"
  [ "$2" = "FAIL" ] && FAILED=1
  log "$2 $1 $3"
}

want() { case " ${CHECKS} " in *" $1 "*) return 0 ;; esac; return 1; }

kc() { kubectl -n "${NS}" "$@"; }

need() {
  command -v "$1" >/dev/null 2>&1 && return 0
  echo "scale-e2e could not run, $1 is not installed" >&2
  exit 2
}

ready_of() { # replicas Ready on a Deployment, 0 when it is gone
  local n
  n=$(kc get deploy "$1" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
  echo "${n:-0}"
}

desired_of() {
  local n
  n=$(kc get deploy "$1" -o jsonpath='{.spec.replicas}' 2>/dev/null)
  echo "${n:-0}"
}

wait_for() { # wait_for <seconds> <command...>, 0 once it succeeds, 1 on timeout
  local limit=$1 start
  shift
  start=$(date +%s)
  while [ $(($(date +%s) - start)) -lt "${limit}" ]; do
    "$@" >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

ready_at_least() { [ "$(ready_of "$1")" -ge "$2" ]; }
ready_at_most() { [ "$(ready_of "$1")" -le "$2" ] && [ "$(desired_of "$1")" -le "$2" ]; }

# samples a Deployment's Ready replicas once a second into a file, epoch then count
sample_start() { # sample_start <name> <deployment>
  local file="${OUT}/sample.$1" dep="$2"
  : > "${file}"
  (
    while :; do
      printf '%s %s\n' "$(date +%s)" "$(ready_of "${dep}")" >> "${file}"
      sleep 2
    done
  ) >/dev/null 2>&1 &
  eval "SAMPLER_$1=$!"
  BG_PIDS="${BG_PIDS} $!"
}

sample_stop() {
  local pid
  eval "pid=\${SAMPLER_$1:-}"
  [ -n "${pid}" ] && kill "${pid}" 2>/dev/null
}

sample_peak() { awk 'BEGIN{m=0} $2>m{m=$2} END{print m}' "${OUT}/sample.$1" 2>/dev/null; }

sample_first() { # epoch of the first sample at or above a count, empty when never
  awk -v want="$2" '$2>=want{print $1; exit}' "${OUT}/sample.$1" 2>/dev/null
}

# the bearer token goes through a curl config file so it never shows in ps or a log
login() {
  local body
  body=$(jq -n --arg e "${ADMIN_EMAIL}" --arg p "${ADMIN_PASSWORD}" '{email:$e,password:$p}')
  local tok
  tok=$(printf '%s' "${body}" | curl -sS -m 30 -H 'Content-Type: application/json' -d @- \
    "${BASE}/api/auth/login" 2>/dev/null | jq -r '.data.access_token // empty' 2>/dev/null)
  [ -n "${tok}" ] || return 1
  printf 'header = "Authorization: Bearer %s"\n' "${tok}" > "${AUTH}"
  chmod 600 "${AUTH}"
  return 0
}

pf_start() {
  [ -n "${PF_PID}" ] && kill "${PF_PID}" 2>/dev/null
  # not through kc, a function in the background would leave kubectl behind on kill
  kubectl -n "${NS}" port-forward "svc/${REL}-api" "${PF_PORT}:8000" >/dev/null 2>&1 &
  PF_PID=$!
  local i
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    curl -sS -m 3 -o /dev/null "${BASE}/api/health" 2>/dev/null && return 0
    sleep 2
  done
  return 1
}

API_CODE=0
API_BODY=""
api() { # api <METHOD> <path> [json], sets API_CODE and API_BODY, 0 on a 2xx
  local method=$1 path=$2 data="${3:-}" tries=0
  while :; do
    if [ -n "${data}" ]; then
      API_CODE=$(printf '%s' "${data}" | curl -sS -m 60 -K "${AUTH}" -X "${method}" \
        -H 'Content-Type: application/json' -d @- -o "${PRIVATE}/resp" -w '%{http_code}' \
        "${BASE}${path}" 2>/dev/null)
    else
      API_CODE=$(curl -sS -m 60 -K "${AUTH}" -X "${method}" -o "${PRIVATE}/resp" \
        -w '%{http_code}' "${BASE}${path}" 2>/dev/null)
    fi
    tries=$((tries + 1))
    # a rolled API pod takes the port forward with it, a refused call has code 000
    if [ "${API_CODE:-000}" = "000" ] && [ "${tries}" -lt 4 ]; then
      pf_start >/dev/null 2>&1
      continue
    fi
    if [ "${API_CODE}" = "401" ] && [ "${tries}" -lt 4 ]; then
      login >/dev/null 2>&1
      continue
    fi
    if [ "${API_CODE}" = "429" ] && [ "${tries}" -lt 8 ]; then
      sleep 2
      continue
    fi
    break
  done
  API_BODY=$(cat "${PRIVATE}/resp" 2>/dev/null)
  case "${API_CODE}" in 2*) return 0 ;; esac
  return 1
}

sql() { # runs one read or cleanup statement in Postgres, output is rows
  kc exec "${REL}-postgresql-0" -- sh -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" psql -U postgres -d abenix -Atc "$1"' sh "$1" 2>/dev/null
}

wait_node() { # wait_node <id> <seconds> [dep]
  jq -n --arg id "$1" --argjson s "$2" --arg dep "${3:-}" \
    '{id:$id,label:$id,tool_name:"wait",arguments:{seconds:$s},depends_on:(if $dep=="" then [] else [$dep] end)}'
}

post_node() { # post_node <id> <path> [dep], a side effect counted at the catcher
  jq -n --arg id "$1" --arg url "${CATCHER}$2" --arg dep "${3:-}" \
    '{id:$id,label:$id,tool_name:"http_client",arguments:{url:$url,method:"POST",body:{m:"{{input.message}}"}},depends_on:(if $dep=="" then [] else [$dep] end)}'
}

create_pipeline() { # create_pipeline <name> <pool> <node json>..., id on stdout via CREATED
  local name=$1 pool=$2 nodes
  shift 2
  nodes=$(printf '%s\n' "$@" | jq -s '.')
  local body
  body=$(jq -n --arg n "scale-e2e-${RUN}-${name}" --argjson nodes "${nodes}" --arg pool "${pool}" \
    '{name:$n,description:"Created by scripts/scale-e2e.sh, removed when it ends.",category:"utility",model_config:{mode:"pipeline",tools:["http_client"],pipeline_config:{nodes:$nodes},runtime_pool:$pool}}')
  CREATED=""
  api POST /api/agents "${body}" || {
    log "agent ${name} not created, status ${API_CODE}: $(printf '%s' "${API_BODY}" | jq -r '.error.message // empty' | cut -c1-200)"
    return 1
  }
  CREATED=$(printf '%s' "${API_BODY}" | jq -r '.data.id // .id // empty')
  [ -n "${CREATED}" ] || return 1
  AGENTS="${AGENTS} ${CREATED}"
}

create_stub_agent() {
  local body
  body=$(jq -n --arg n "scale-e2e-${RUN}-$1" \
    '{name:$n,description:"Created by scripts/scale-e2e.sh, removed when it ends.",category:"utility",system_prompt:"Answer in one short sentence.",model:"claude-haiku-4-5-20251001",tools:[]}')
  CREATED=""
  api POST /api/agents "${body}" || return 1
  CREATED=$(printf '%s' "${API_BODY}" | jq -r '.data.id // .id // empty')
  [ -n "${CREATED}" ] || return 1
  AGENTS="${AGENTS} ${CREATED}"
}

EXEC_ID=""
TASK_ID=""
start_run() { # start_run <agent id> <message>, queues one run through the public API
  EXEC_ID=""
  TASK_ID=""
  local body
  body=$(jq -n --arg m "$2" '{message:$m,wait:false,stream:false}')
  api POST "/api/agents/$1/execute" "${body}" || return 1
  EXEC_ID=$(printf '%s' "${API_BODY}" | jq -r '.data.execution_id // empty')
  TASK_ID=$(printf '%s' "${API_BODY}" | jq -r '.data.task_id // empty')
  [ -n "${EXEC_ID}" ]
}

count_status() { # count_status <agent id> <STATUS>
  sql "select count(*) from executions where agent_id='$1' and status='$2'"
}

no_running() { [ "$(count_status "$1" RUNNING)" = "0" ]; }

run_status() { sql "select status from executions where id='$1'"; }
run_done() { [ "$(run_status "$1")" != "RUNNING" ] && [ -n "$(run_status "$1")" ]; }

catcher_count() { # how many posts the catcher has for a path, with a body filter if given
  kc exec -i "deploy/${REL}-webhook-catcher" -- python -c '
import json, sys, urllib.parse, urllib.request
path, want = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""
url = "http://127.0.0.1:8080/api/requests?path=" + urllib.parse.quote(path)
items = json.load(urllib.request.urlopen(url))["items"]
print(sum(1 for i in items if not want or (i.get("json") or {}).get("m") == want))
' "$@" 2>/dev/null
}

catcher_distinct() {
  kc exec -i "deploy/${REL}-webhook-catcher" -- python -c '
import json, sys, urllib.parse, urllib.request
url = "http://127.0.0.1:8080/api/requests?path=" + urllib.parse.quote(sys.argv[1])
items = json.load(urllib.request.urlopen(url))["items"]
print(len({(i.get("json") or {}).get("m") for i in items}))
' "$1" 2>/dev/null
}

durable_lag() { # pending plus held on a pool's durable, empty when it has no durable
  kc exec "${REL}-nats-0" -- wget -qO- 'http://localhost:8222/jsz?acc=A&consumers=true' 2>/dev/null \
    | jq -r --arg c "abenix-$1-consumer" \
      '[.account_details[]?.stream_detail[]?.consumer_detail[]? | select(.name==$c)] | if length==0 then "" else (.[0].num_pending + .[0].num_ack_pending | tostring) end'
}

drop_durable() { # removes a test pool's durable and queued messages
  kc exec -i "deploy/${REL}-api" -c api -- python3 - "$1" >/dev/null 2>&1 <<'PY'
import asyncio, os, sys
import nats

async def main(pool):
    nc = await nats.connect(
        os.environ.get("NATS_URL", "nats://abenix-nats:4222"),
        user=os.environ.get("NATS_USER", "abenix"),
        password=os.environ.get("NATS_PASSWORD") or None,
    )
    js = nc.jsm()
    try:
        await js.delete_consumer("agents", f"abenix-{pool}-consumer")
    except Exception:
        pass
    await js.purge_stream("agents", subject=f"agents.{pool}")
    await nc.close()

asyncio.run(main(sys.argv[1]))
PY
}

scaler_ready() { # every ScaledObject Ready and none in fallback, paused ones excepted
  kc get scaledobject -o json 2>/dev/null | jq -e '
    [.items[] | select(.metadata.annotations["autoscaling.keda.sh/paused-replicas"] == null)
      | (.status.conditions // []) as $c
      | (($c | map(select(.type=="Ready" and .status=="True")) | length) == 1)
        and (($c | map(select(.type=="Fallback" and .status=="True")) | length) == 0)]
    | length > 0 and all' >/dev/null
}

scaler_not_ready_names() {
  kc get scaledobject -o json 2>/dev/null | jq -r '
    .items[] | select(.metadata.annotations["autoscaling.keda.sh/paused-replicas"] == null)
    | select(((.status.conditions // []) | map(select(.type=="Ready" and .status=="True")) | length) == 0)
    | .metadata.name' | tr '\n' ' '
}

# Getting the overlay on and off

running_tag() { # image tag of the first Deployment with this label
  kc get deploy -l "$1" -o jsonpath='{.items[0].spec.template.spec.containers[0].image}' 2>/dev/null | sed 's/.*://'
}

apply_overlay() {
  local deps
  deps=$(kc get deploy -o json 2>/dev/null | jq -r '.items[] | select(.metadata.labels["app.kubernetes.io/managed-by"]=="Helm") | "\(.metadata.name) \(.spec.replicas) \(.spec.template.spec.containers[0].name) \(.spec.template.spec.containers[0].image)"')
  printf '%s\n' "${deps}" > "${REPLICA_SNAPSHOT}"
  PREV_REV=$(helm -n "${NS}" history "${REL}" -o json 2>/dev/null | jq -r '.[-1].revision // empty')
  [ -n "${PREV_REV}" ] || { echo "scale-e2e could not run, no helm release ${REL}" >&2; return 1; }
  helm -n "${NS}" get values "${REL}" -o yaml > "${PRIVATE}/current-values.yaml" 2>/dev/null || return 1
  chmod 600 "${PRIVATE}/current-values.yaml"
  log "applying the overlay on top of revision ${PREV_REV}"
  OVERLAY_ON=1
  # the autoscalers own replicas on live objects, helm must not stop on that
  # deploy.sh reload moves images past the release values, keep what runs now
  set -- --set "api.image.tag=$(running_tag app.kubernetes.io/name=api)" \
    --set "web.image.tag=$(running_tag app.kubernetes.io/name=web)" \
    --set "worker.image.tag=$(running_tag app.kubernetes.io/name=worker)" \
    --set "cognifyWorker.image.tag=$(running_tag app.kubernetes.io/component=cognify-worker)" \
    --set "agent-runtime.image.tag=$(running_tag app.kubernetes.io/name=agent-runtime)" \
    --set "scaling.agentRuntimeImage.tag=$(running_tag app.kubernetes.io/name=agent-runtime)"
  if ! helm upgrade "${REL}" "${HELM_DIR}" -n "${NS}" -f "${PRIVATE}/current-values.yaml" \
    -f "${OVERLAY}" "$@" --server-side=true --force-conflicts --timeout 10m --wait=false \
    > "${PRIVATE}/helm.log" 2>&1; then
    echo "helm upgrade failed: $(grep -m1 -i '^error' "${PRIVATE}/helm.log" | cut -c1-200)" >&2
    return 1
  fi
  # abenix-config changed, its readers only see that after a restart
  kc rollout restart "deploy/${REL}-api" "deploy/${POOL_DEFAULT}" >/dev/null 2>&1
  kc rollout status "deploy/${REL}-api" --timeout=300s >/dev/null 2>&1 || return 1
  kc rollout status "deploy/${POOL_DEFAULT}" --timeout=300s >/dev/null 2>&1 || return 1
  pf_start || return 1
  login
}

restore() {
  [ "${CLEANED}" = "1" ] && return
  CLEANED=1
  trap '' INT TERM
  local p
  for p in ${BG_PIDS}; do kill "${p}" 2>/dev/null; done
  kc delete pod scale-e2e-load --ignore-not-found --wait=false >/dev/null 2>&1
  if [ "${KEEP:-}" = "1" ]; then
    log "KEEP=1, overlay at revision above ${PREV_REV:-?} and test agents stay"
    [ -n "${PF_PID}" ] && kill "${PF_PID}" 2>/dev/null
    rm -rf "${PRIVATE}"
    return
  fi
  [ "${OVERLAY_ON}" = "1" ] && log "restoring the cluster"
  if [ "${OVERLAY_ON}" = "1" ]; then
    curl -sS -m 3 -o /dev/null "${BASE}/api/health" 2>/dev/null || pf_start >/dev/null 2>&1
    [ -s "${AUTH}" ] || login >/dev/null 2>&1
  fi
  if [ -n "${DEDICATED_AGENT}" ]; then
    api POST "/api/admin/scaling/agents/${DEDICATED_AGENT}/dedicated-mode" '{"enabled":false}' >/dev/null 2>&1
    kc delete scaledobject,deploy -l "abenix.io/dedicated-agent=${DEDICATED_AGENT}" --ignore-not-found >/dev/null 2>&1
  fi
  for p in ${AGENTS}; do
    api DELETE "/api/agents/${p}?force=true" >/dev/null 2>&1
    sql "delete from improvement_proposals where agent_id='${p}'" >/dev/null 2>&1
  done
  [ -n "${ASSET_ID}" ] && api DELETE "/api/code-assets/${ASSET_ID}" >/dev/null 2>&1
  [ -n "${DECISION_KEY}" ] && api DELETE "/api/decisions/${DECISION_KEY}" >/dev/null 2>&1
  if [ "${OVERLAY_ON}" = "1" ] && [ -n "${PREV_REV}" ]; then
    if helm rollback "${REL}" "${PREV_REV}" -n "${NS}" --server-side=true --force-conflicts \
      --timeout 10m > "${PRIVATE}/rollback.log" 2>&1; then
      log "helm back at revision ${PREV_REV}"
    else
      log "RESTORE PROBLEM helm rollback failed, run: helm rollback ${REL} ${PREV_REV} -n ${NS}"
      FAILED=1
    fi
    # a removed HPA leaves its last replica count, a rollback undoes a deploy.sh reload
    while read -r d n c image; do
      [ -n "${d}" ] || continue
      [ "$(desired_of "${d}")" = "${n}" ] || kc scale "deploy/${d}" --replicas="${n}" >/dev/null 2>&1
      [ "$(kc get deploy "${d}" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)" = "${image}" ] \
        || kc set image "deploy/${d}" "${c}=${image}" >/dev/null 2>&1
    done < "${REPLICA_SNAPSHOT}"
    kc rollout restart "deploy/${REL}-api" "deploy/${POOL_DEFAULT}" >/dev/null 2>&1
    kc rollout status "deploy/${REL}-api" --timeout=300s >/dev/null 2>&1
    drop_durable long-running
    drop_durable chat
  fi
  [ -n "${PF_PID}" ] && kill "${PF_PID}" 2>/dev/null
  rm -rf "${PRIVATE}"
  [ "${OVERLAY_ON}" = "1" ] && log "restored"
}

print_table() {
  echo
  echo "Measured numbers, compare with the docs by hand"
  sed 's/^/  /' "${NUMBERS}"
  echo
  printf '%-7s %-5s %s\n' "check" "state" "detail"
  printf '%-7s %-5s %s\n' "-----" "-----" "------"
  while IFS='|' read -r name state detail; do
    printf '%-7s %-5s %s\n' "${name}" "${state}" "${detail}"
  done < "${RESULT_LINES}"
  echo
  echo "Took $(($(date +%s) - STARTED_AT)) s. Logs in ${OUT}"
}

finish() {
  local code=$?
  restore
  print_table
  [ "${FAILED}" = "1" ] && code=1
  exit "${code}"
}

# The checks

check_a() {
  local keda not
  keda=$(kubectl -n keda get pods -l app=keda-operator -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
  if [ "${keda}" != "Running" ]; then
    record a FAIL "KEDA operator is not running in namespace keda"
    return
  fi
  if wait_for 240 scaler_ready; then
    local n
    n=$(kc get scaledobject -o name 2>/dev/null | wc -l | tr -d ' ')
    record a PASS "KEDA running, ${n} ScaledObjects Ready, none in fallback"
  else
    not=$(scaler_not_ready_names)
    record a FAIL "not Ready after 240 s: ${not}"
  fi
}

check_n() {
  local id start took
  create_pipeline nopool default "$(wait_node w 1)" || { record n FAIL "test agent not created"; return; }
  id=${CREATED}
  api PATCH "/api/admin/scaling/agents/${id}" '{"runtime_pool":"gpu"}'
  if [ "${API_CODE}" != "400" ]; then
    record n FAIL "admin API accepted a pool that is not deployed, status ${API_CODE}"
    return
  fi
  # the builder writes the pool through model_config, which cannot look at the cluster
  api PUT "/api/agents/${id}" '{"model_config":{"mode":"pipeline","tools":["http_client"],"pipeline_config":{"nodes":[{"id":"w","label":"w","tool_name":"wait","arguments":{"seconds":1},"depends_on":[]}]},"runtime_pool":"gpu"}}' \
    || api PATCH "/api/agents/${id}" '{"model_config":{"mode":"pipeline","tools":["http_client"],"pipeline_config":{"nodes":[{"id":"w","label":"w","tool_name":"wait","arguments":{"seconds":1},"depends_on":[]}]},"runtime_pool":"gpu"}}'
  start=$(date +%s)
  start_run "${id}" "nopool"
  took=$(($(date +%s) - start))
  local code msg stuck
  code=$(printf '%s' "${API_BODY}" | jq -r '.error.error_code // empty')
  msg=$(printf '%s' "${API_BODY}" | jq -r '.error.message // empty' | cut -c1-120)
  stuck=$(count_status "${id}" RUNNING)
  if [ "${API_CODE}" = "503" ] && [ "${code}" = "POOL_NOT_DEPLOYED" ] && [ "${stuck}" = "0" ]; then
    record n PASS "refused in ${took} s with POOL_NOT_DEPLOYED, no run left running"
  else
    record n FAIL "status ${API_CODE} code ${code:-none}, running rows ${stuck}, ${msg}"
  fi
}

M_EXEC=""
M_START=0
check_m_start() {
  create_pipeline parked chat "$(wait_node w 1)" || { record m FAIL "test agent not created"; return; }
  local id=${CREATED}
  # a pool whose autoscaler is paused at zero is the same as a consumer that cannot reach NATS
  kc annotate scaledobject "${POOL_PARKED}" autoscaling.keda.sh/paused-replicas=0 --overwrite >/dev/null 2>&1
  start_run "${id}" "parked" || { record m FAIL "run not queued, status ${API_CODE}"; return; }
  M_EXEC=${EXEC_ID}
  M_START=$(date +%s)
  log "m run ${M_EXEC} parked, the sweep should fail it in about 3 minutes"
}

check_m_finish() {
  [ -n "${M_EXEC}" ] || return
  local waited=0 row
  wait_for $((420 - ($(date +%s) - M_START))) run_done "${M_EXEC}"
  waited=$(($(date +%s) - M_START))
  row=$(sql "select status||' '||coalesce(failure_code,'none') from executions where id='${M_EXEC}'")
  kc annotate scaledobject "${POOL_PARKED}" autoscaling.keda.sh/paused-replicas- >/dev/null 2>&1
  number "queued run with no consumer failed after (s)" "${waited}"
  if [ "${row}" = "FAILED QUEUE_NOT_PICKED_UP" ]; then
    record m PASS "failed by the sweep after ${waited} s with QUEUE_NOT_PICKED_UP"
  else
    record m FAIL "after ${waited} s the row reads ${row}"
  fi
}

B_AGENT=""
check_b() {
  local start id nodes ok=0 failed_submit=0 i path="/scale-e2e/${RUN}/b"
  create_pipeline burst default "$(wait_node pause "${FAST_SECONDS}")" "$(post_node mark "${path}" pause)" \
    || { record b FAIL "test agent not created"; return; }
  id=${CREATED}
  B_AGENT=${id}
  local before
  before=$(ready_of "${POOL_DEFAULT}")
  sample_start b "${POOL_DEFAULT}"
  : > "${OUT}/b-runs.txt"
  start=$(date +%s)
  i=0
  while [ "${i}" -lt "${BURST_RUNS}" ]; do
    i=$((i + 1))
    if start_run "${id}" "b-${i}"; then
      printf '%s %s\n' "${EXEC_ID}" "${TASK_ID}" >> "${OUT}/b-runs.txt"
      ok=$((ok + 1))
    else
      failed_submit=$((failed_submit + 1))
    fi
  done
  log "b queued ${ok} runs in $(($(date +%s) - start)) s, lag on the durable $(durable_lag default)"
  wait_for 240 ready_at_least "${POOL_DEFAULT}" 3
  wait_for 300 no_running "${id}"
  local drained=$(($(date +%s) - start))
  sample_stop b
  local peak first to_max
  peak=$(sample_peak b)
  first=$(sample_first b 3)
  to_max="never"
  [ -n "${first}" ] && to_max=$((first - start))
  local rows done_rows reruns ids_ok tasks posted distinct
  rows=$(sql "select count(*) from executions where agent_id='${id}'")
  done_rows=$(count_status "${id}" COMPLETED)
  reruns=$(sql "select count(*) from executions where agent_id='${id}' and delivery_attempts<>1")
  sql "select id from executions where agent_id='${id}' order by id" > "${OUT}/b-db-ids.txt"
  awk '{print $1}' "${OUT}/b-runs.txt" | sort > "${OUT}/b-api-ids.txt"
  sort "${OUT}/b-db-ids.txt" -o "${OUT}/b-db-ids.txt"
  ids_ok=$(diff "${OUT}/b-api-ids.txt" "${OUT}/b-db-ids.txt" >/dev/null 2>&1 && echo yes || echo no)
  tasks=$(awk '{print $2}' "${OUT}/b-runs.txt" | sort -u | wc -l | tr -d ' ')
  posted=$(catcher_count "${path}")
  distinct=$(catcher_distinct "${path}")
  number "default pool replicas before, peak" "${before}, ${peak}"
  number "seconds from first enqueue to 3 pods" "${to_max}"
  number "seconds to drain ${BURST_RUNS} runs" "${drained}"
  local detail="pods ${before} to ${peak}, ${done_rows} of ${BURST_RUNS} completed, reruns ${reruns}, side effects ${posted} over ${distinct} runs, ${tasks} task ids, rows match API ${ids_ok}"
  if [ "${peak}" -ge 3 ] && [ "${failed_submit}" = "0" ] && [ "${done_rows}" = "${BURST_RUNS}" ] \
    && [ "${rows}" = "${BURST_RUNS}" ] && [ "${reruns}" = "0" ] && [ "${posted}" = "${BURST_RUNS}" ] \
    && [ "${distinct}" = "${BURST_RUNS}" ] && [ "${tasks}" = "${BURST_RUNS}" ] && [ "${ids_ok}" = "yes" ]; then
    record b PASS "${detail}"
  else
    record b FAIL "${detail}, submit failures ${failed_submit}, pod scale down history in ${OUT}"
  fi
}

check_c() {
  local id i p path="/scale-e2e/${RUN}/c" execs="" start killed_note="natural scale down"
  [ "$(ready_of "${POOL_DEFAULT}")" -ge 2 ] || {
    # run on its own, put pods up first so there is something to scale down
    create_pipeline warmup default "$(wait_node pause 20)" || { record c FAIL "test agent not created"; return; }
    id=${CREATED}
    i=0
    while [ "${i}" -lt 12 ]; do i=$((i + 1)); start_run "${id}" "warm-${i}"; done
    wait_for 120 ready_at_least "${POOL_DEFAULT}" 2
  }
  create_pipeline long default "$(wait_node pause "${LONG_SECONDS}")" "$(post_node mark "${path}" pause)" \
    || { record c FAIL "test agent not created"; return; }
  id=${CREATED}
  start=$(date +%s)
  i=0
  while [ "${i}" -lt 2 ]; do
    i=$((i + 1))
    start_run "${id}" "c-${i}" && execs="${execs} ${EXEC_ID}"
  done
  # every pod that starts terminating is noted with the time, to compare with where runs were
  : > "${OUT}/c-terminating.txt"
  (
    while :; do
      kc get pods -l "abenix.io/pool=default" -o json 2>/dev/null | jq -r --arg t "$(date +%s)" \
        '.items[] | select(.metadata.deletionTimestamp != null) | "\($t) \(.metadata.name)"' >> "${OUT}/c-terminating.txt"
      sleep 3
    done
  ) >/dev/null 2>&1 &
  local watcher=$!
  BG_PIDS="${BG_PIDS} ${watcher}"
  sleep 12
  local holders
  holders=$(sql "select distinct split_part(runner_id,':',1) from executions where agent_id='${id}' and runner_id is not null" | tr '\n' ' ')
  log "c long runs held by ${holders:-nobody yet}"
  # natural scale down is one pod at a time, give it most of the run's length
  local waited=0 hit=""
  while [ "${waited}" -lt 60 ] && [ -z "${hit}" ]; do
    for p in ${holders}; do
      grep -q " ${p}\$" "${OUT}/c-terminating.txt" 2>/dev/null && hit=${p}
    done
    sleep 5
    waited=$((waited + 5))
  done
  if [ -z "${hit}" ]; then
    # the scale down picked idle pods, so stop one holding a run the way a scale down would
    hit=$(printf '%s' "${holders}" | awk '{print $1}')
    killed_note="pod stopped by hand with SIGTERM, the scale down only picked idle pods"
    [ -n "${hit}" ] && kc delete pod "${hit}" --wait=false >/dev/null 2>&1
  fi
  wait_for $((LONG_SECONDS + 150)) no_running "${id}"
  kill "${watcher}" 2>/dev/null
  local ran_on done_rows reruns posted
  done_rows=$(count_status "${id}" COMPLETED)
  reruns=$(sql "select count(*) from executions where agent_id='${id}' and delivery_attempts<>1")
  ran_on=$(sql "select count(*) from executions where agent_id='${id}' and split_part(runner_id,':',1)='${hit}'")
  posted=$(catcher_count "${path}")
  local t0=$(date +%s) back=never
  wait_for 240 ready_at_most "${POOL_DEFAULT}" 1 && back=$(($(date +%s) - t0))
  number "seconds back to 1 pod after the long runs" "${back}"
  local detail="${killed_note}, pod ${hit:-none} finished ${ran_on} runs while terminating, ${done_rows} of 2 completed, reruns ${reruns}, side effects ${posted}, back to 1 in ${back} s"
  if [ "${done_rows}" = "2" ] && [ "${reruns}" = "0" ] && [ "${posted}" = "2" ] \
    && [ "${ran_on:-0}" -ge 1 ] && [ "${back}" != "never" ]; then
    record c PASS "${detail}"
  else
    record c FAIL "${detail}"
  fi
}

check_d() {
  local path="/scale-e2e/${RUN}/d" id start
  if [ "$(desired_of "${POOL_ZERO}")" != "0" ] || [ "$(ready_of "${POOL_ZERO}")" != "0" ]; then
    wait_for 120 ready_at_most "${POOL_ZERO}" 0 || { record d FAIL "the pool is not at zero to begin with"; return; }
  fi
  local pods
  pods=$(kc get pods -l "abenix.io/pool=long-running" -o name 2>/dev/null | wc -l | tr -d ' ')
  local had
  had=$(durable_lag long-running)
  log "d pods before ${pods}, durable before the first run ${had:-missing}"
  create_pipeline zero long-running "$(wait_node pause 1)" "$(post_node mark "${path}" pause)" \
    || { record d FAIL "test agent not created"; return; }
  id=${CREATED}
  sample_start d "${POOL_ZERO}"
  start=$(date +%s)
  start_run "${id}" "d-1" || { sample_stop d; record d FAIL "run refused, status ${API_CODE}: $(printf '%s' "${API_BODY}" | jq -r '.error.message // empty' | cut -c1-120)"; return; }
  local exec=${EXEC_ID}
  wait_for 240 run_done "${exec}"
  local finished=$(($(date +%s) - start))
  local first pod_ready=never
  first=$(sample_first d 1)
  [ -n "${first}" ] && pod_ready=$((first - start))
  local row runner posted
  row=$(run_status "${exec}")
  runner=$(sql "select split_part(runner_id,':',1) from executions where id='${exec}'")
  posted=$(catcher_count "${path}")
  number "wake from zero, seconds to a Ready pod" "${pod_ready}"
  number "wake from zero, seconds to run finished" "${finished}"
  local t0=$(date +%s) back=never
  wait_for 240 ready_at_most "${POOL_ZERO}" 0 && back=$(($(date +%s) - t0))
  sample_stop d
  number "seconds back to zero" "${back}"
  case "${runner}" in "${POOL_ZERO}"-*) local on_pool=yes ;; *) local on_pool=no ;; esac
  local detail="durable before run ${had:-missing}, pod in ${pod_ready} s, run ${row} in ${finished} s, ran on the pool ${on_pool}, side effects ${posted}, back to zero in ${back} s"
  if [ "${row}" = "COMPLETED" ] && [ "${on_pool}" = "yes" ] && [ "${posted}" = "1" ] && [ "${back}" != "never" ]; then
    record d PASS "${detail}"
  else
    record d FAIL "${detail}"
  fi
}

check_e() {
  local before_path="/scale-e2e/${RUN}/e-before" after_path="/scale-e2e/${RUN}/e-after" id
  create_pipeline crash default "$(post_node before "${before_path}")" "$(wait_node pause 45 before)" \
    "$(post_node after "${after_path}" pause)" || { record e FAIL "test agent not created"; return; }
  id=${CREATED}
  start_run "${id}" "e-1" || { record e FAIL "run not queued, status ${API_CODE}"; return; }
  local exec=${EXEC_ID} tries=0 holder=""
  while [ "${tries}" -lt 40 ] && { [ -z "${holder}" ] || [ "$(catcher_count "${before_path}")" = "0" ]; }; do
    holder=$(sql "select split_part(runner_id,':',1) from executions where id='${exec}'")
    sleep 2
    tries=$((tries + 1))
  done
  [ -n "${holder}" ] || { record e FAIL "no pod took the run"; return; }
  log "e killing ${holder} mid run"
  local t0=$(date +%s)
  kc delete pod "${holder}" --grace-period=0 --force >/dev/null 2>&1
  wait_for 300 run_done "${exec}"
  local took=$(($(date +%s) - t0))
  local row attempts runner again n_before n_after rows
  row=$(run_status "${exec}")
  attempts=$(sql "select delivery_attempts from executions where id='${exec}'")
  runner=$(sql "select split_part(runner_id,':',1) from executions where id='${exec}'")
  rows=$(sql "select count(*) from executions where agent_id='${id}'")
  n_before=$(catcher_count "${before_path}")
  n_after=$(catcher_count "${after_path}")
  number "seconds from pod kill to run finished" "${took}"
  number "side effect before the kill ran times" "${n_before}"
  number "side effect after the kill ran times" "${n_after}"

  # the Idempotency-Key claim, a retried call must not start a second run
  local key="scale-e2e-${RUN}-key" first second body fast
  create_pipeline retry default "$(wait_node pause 1)" || { record e FAIL "test agent not created"; return; }
  fast=${CREATED}
  body=$(jq -n '{message:"e-key",wait:true,stream:false,wait_timeout_seconds:60}')
  first=$(printf '%s' "${body}" | curl -sS -m 90 -K "${AUTH}" -H 'Content-Type: application/json' \
    -H "Idempotency-Key: ${key}" -d @- "${BASE}/api/agents/${fast}/execute" 2>/dev/null \
    | jq -r '.data.execution_id // empty')
  second=$(printf '%s' "${body}" | curl -sS -m 90 -K "${AUTH}" -H 'Content-Type: application/json' \
    -H "Idempotency-Key: ${key}" -d @- "${BASE}/api/agents/${fast}/execute" 2>/dev/null \
    | jq -r '.data.execution_id // empty')
  local key_rows
  key_rows=$(sql "select count(*) from executions where agent_id='${fast}'")

  local detail="run ${row} on ${runner} after ${attempts} deliveries in ${took} s, one row ${rows}, step before the kill ran ${n_before} times, step after ${n_after}, same Idempotency-Key gave ${key_rows} runs"
  if [ "${row}" = "COMPLETED" ] && [ "${attempts}" = "2" ] && [ "${rows}" = "1" ] && [ "${n_after}" = "1" ] \
    && [ "${runner}" != "${holder}" ] && [ -n "${first}" ] && [ "${first}" = "${second}" ] && [ "${key_rows}" = "1" ]; then
    record e PASS "${detail}. A takeover reruns from the start, so the earlier step repeating is the at least once the docs describe"
  else
    record e FAIL "${detail}, key answers ${first:-none} and ${second:-none}"
  fi
}

check_f() {
  local have
  have=$(kc exec "deploy/${REL}-prometheus" -- wget -qO- \
    'http://localhost:9090/api/v1/query?query=count(abenix_execution_duration_seconds_bucket%7Bpool%3D%22default%22%7D)' 2>/dev/null \
    | jq -r '.data.result | length')
  if [ "${have:-0}" = "0" ]; then
    record f SKIP "Prometheus has no abenix_execution_duration_seconds for the default pool, the trigger reads nothing"
    return
  fi
  local index
  index=$(kc get scaledobject "${POOL_DEFAULT}" -o json | jq '[.spec.triggers[].type] | index("prometheus")')
  if [ "${index}" = "null" ]; then
    record f SKIP "scaling.keda.prometheusUrl is not set, the trigger is not rendered"
    return
  fi
  wait_for 240 ready_at_most "${POOL_DEFAULT}" 1
  local id old i
  create_pipeline slow default "$(wait_node pause 8)" || { record f FAIL "test agent not created"; return; }
  id=${CREATED}
  old=$(kc get scaledobject "${POOL_DEFAULT}" -o json | jq -r ".spec.triggers[${index}].metadata.threshold")
  kc patch scaledobject "${POOL_DEFAULT}" --type=json \
    -p "[{\"op\":\"replace\",\"path\":\"/spec/triggers/${index}/metadata/threshold\",\"value\":\"3000\"}]" >/dev/null 2>&1
  sample_start f "${POOL_DEFAULT}"
  local maxlag=0 lag start=$(date +%s)
  # one run at a time keeps the lag below its threshold, only latency can add pods
  i=0
  while [ "${i}" -lt 10 ] && [ "$(ready_of "${POOL_DEFAULT}")" -lt 2 ]; do
    i=$((i + 1))
    start_run "${id}" "f-${i}"
    wait_for 40 run_done "${EXEC_ID}"
    lag=$(durable_lag default)
    [ "${lag:-0}" -gt "${maxlag}" ] && maxlag=${lag:-0}
  done
  wait_for 60 ready_at_least "${POOL_DEFAULT}" 2
  sample_stop f
  local peak first took=never
  peak=$(sample_peak f)
  first=$(sample_first f 2)
  [ -n "${first}" ] && took=$((first - start))
  kc patch scaledobject "${POOL_DEFAULT}" --type=json \
    -p "[{\"op\":\"replace\",\"path\":\"/spec/triggers/${index}/metadata/threshold\",\"value\":\"${old}\"}]" >/dev/null 2>&1
  number "p95 trigger, seconds to a second pod" "${took}"
  if [ "${peak}" -ge 2 ]; then
    record f PASS "p95 above a 3 s threshold took the pool to ${peak} pods in ${took} s, queue lag stayed at ${maxlag}, threshold put back to ${old} ms"
  else
    record f FAIL "p95 above a 3 s threshold left the pool at ${peak} after ${i} runs, lag ${maxlag}"
  fi
}

ded_gone() { [ -z "$(kc get scaledobject,deploy -l "abenix.io/dedicated-agent=$1" -o name 2>/dev/null)" ]; }
ded_scaler_ready() {
  kc get scaledobject -l "abenix.io/dedicated-agent=$1" -o json 2>/dev/null | jq -e \
    '.items | length == 1 and (.[0].status.conditions // [] | map(select(.type=="Ready" and .status=="True")) | length == 1)' >/dev/null
}

check_g() {
  create_stub_agent dedicated || { record g FAIL "test agent not created"; return; }
  local id=${CREATED} start
  DEDICATED_AGENT=${id}
  start=$(date +%s)
  if ! api POST "/api/admin/scaling/agents/${id}/dedicated-mode" '{"enabled":true}'; then
    record g FAIL "turning it on answered ${API_CODE}: $(printf '%s' "${API_BODY}" | jq -r '.error.message // empty' | cut -c1-160)"
    return
  fi
  local pool state dep
  pool=$(printf '%s' "${API_BODY}" | jq -r '.data.effective_pool')
  state=$(printf '%s' "${API_BODY}" | jq -r '.data.dedicated_state')
  dep=$(kc get deploy -l "abenix.io/dedicated-agent=${id}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [ -z "${dep}" ] || [ "${pool}" != "dedicated-${id}" ]; then
    record g FAIL "no Deployment after turning it on, effective pool ${pool}, state ${state}"
    return
  fi
  wait_for 120 ded_scaler_ready "${id}" || { record g FAIL "ScaledObject not Ready for ${dep}"; return; }
  wait_for 240 ready_at_least "${dep}" 1 || { record g FAIL "${dep} has no Ready pod"; return; }
  local up=$(($(date +%s) - start))
  number "dedicated pool, seconds from on to a Ready pod" "${up}"
  start_run "${id}" "hello dedicated" || { record g FAIL "run refused, status ${API_CODE}"; return; }
  local exec=${EXEC_ID}
  wait_for 120 run_done "${exec}"
  local row runner out
  row=$(run_status "${exec}")
  runner=$(sql "select split_part(runner_id,':',1) from executions where id='${exec}'")
  out=$(sql "select left(coalesce(output_message,''),60) from executions where id='${exec}'")
  local t0 gone=never
  t0=$(date +%s)
  api POST "/api/admin/scaling/agents/${id}/dedicated-mode" '{"enabled":false}'
  state=$(printf '%s' "${API_BODY}" | jq -r '.data.dedicated_state // empty')
  wait_for 180 ded_gone "${id}" && gone=$(($(date +%s) - t0))
  local durable_left
  durable_left=$(durable_lag "dedicated-${id}")
  start_run "${id}" "back on the shared pool"
  local back_exec=${EXEC_ID} back_runner
  wait_for 120 run_done "${back_exec}"
  back_runner=$(sql "select split_part(runner_id,':',1) from executions where id='${back_exec}'")
  number "dedicated pool, seconds from off to removed" "${gone}"
  local on_ded=no on_shared=no
  case "${runner}" in "${dep}"-*) on_ded=yes ;; esac
  case "${back_runner}" in "${POOL_DEFAULT}"-*) on_shared=yes ;; esac
  local detail="run ${row} on its own pod ${on_ded}, off answered ${state}, removed in ${gone} s, durable left ${durable_left:-no}, next run on the shared pool ${on_shared}"
  if [ "${row}" = "COMPLETED" ] && [ "${on_ded}" = "yes" ] && [ "${gone}" != "never" ] \
    && [ -z "${durable_left}" ] && [ "${on_shared}" = "yes" ]; then
    DEDICATED_AGENT=""
    record g PASS "${detail}, reply ${out}"
  else
    record g FAIL "${detail}"
  fi
}

H_PID=""
rules_backlog() { # t2 defines no rules, so this is what puts entries in the rules pool's streams
  kc exec -i "deploy/${REL}-api" -c api -- python3 - "$1" >/dev/null 2>&1 <<'PY'
import asyncio, os, sys, time
import redis.asyncio as aioredis
from app.telemetry.rules.evaluator import SHARDS, in_stream

async def main(seconds):
    r = aioredis.from_url(os.environ["REDIS_URL"])
    end = time.time() + seconds
    while time.time() < end:
        pipe = r.pipeline(transaction=False)
        for shard in range(SHARDS):
            for _ in range(300):
                pipe.xadd(in_stream(shard), {"t": "scale-e2e"}, maxlen=20000, approximate=True)
        await pipe.execute()
        await asyncio.sleep(0.2)
    await r.aclose()

asyncio.run(main(int(sys.argv[1])))
PY
}

check_h_start() {
  sample_start hi "${REL}-telemetry-ingest"
  sample_start hr "${REL}-telemetry-rules"
  rules_backlog 100 &
  BG_PIDS="${BG_PIDS} $!"
  # KEEP here is this script's, the load test has its own flag of the same name
  ( KEEP="" SECONDS_RUN="${TELEMETRY_SECONDS:-150}" LOADTEST_OUT_DIR="${OUT}/telemetry" \
      bash "${ROOT_DIR}/scripts/telemetry-loadtest.sh" t2 > "${OUT}/telemetry-t2.log" 2>&1 ) &
  H_PID=$!
  BG_PIDS="${BG_PIDS} ${H_PID}"
}

check_h_finish() {
  [ -n "${H_PID}" ] || return
  wait "${H_PID}"
  local code=$?
  sample_stop hi
  sample_stop hr
  grep -E '^(PASS|FAIL) ' "${OUT}/telemetry-t2.log" | sed 's/^/  /'
  while read -r state name measured limit; do
    [ -n "${name}" ] && number "telemetry t2 ${name}" "${measured#measured=} (${state} ${limit})"
  done <<EOF
$(grep -E '^(PASS|FAIL) ' "${OUT}/telemetry-t2.log")
EOF
  local i_peak r_peak t0 i_back=never r_back=never
  i_peak=$(sample_peak hi)
  r_peak=$(sample_peak hr)
  t0=$(date +%s)
  wait_for 240 ready_at_most "${REL}-telemetry-ingest" 1 && i_back=$(($(date +%s) - t0))
  wait_for 240 ready_at_most "${REL}-telemetry-rules" 1 && r_back=$(($(date +%s) - t0))
  number "telemetry ingest replicas peak, seconds back" "${i_peak}, ${i_back}"
  number "telemetry rules replicas peak, seconds back" "${r_peak}, ${r_back}"
  local detail="t2 exit ${code}, ingest peak ${i_peak} back in ${i_back} s, rules peak ${r_peak} on a backlog written straight to its streams since t2 has no rules, back in ${r_back} s"
  if [ "${code}" = "0" ] && [ "${i_peak}" -ge 2 ] && [ "${r_peak}" -ge 2 ] \
    && [ "${i_back}" != "never" ] && [ "${r_back}" != "never" ]; then
    record h PASS "${detail}"
  else
    record h FAIL "${detail}, log ${OUT}/telemetry-t2.log"
  fi
}

I_AGENT=""
check_i_start() {
  local dep="${REL}-improvements-proof" id tenant i
  [ "$(desired_of "${dep}")" = "0" ] || wait_for 120 ready_at_most "${dep}" 0
  create_stub_agent proof || { record i FAIL "test agent not created"; return; }
  id=${CREATED}
  I_AGENT=${id}
  tenant=$(sql "select tenant_id from agents where id='${id}'")
  i=0
  while [ "${i}" -lt 4 ]; do
    i=$((i + 1))
    sql "insert into improvement_proposals (id,tenant_id,agent_id,change_kind,state) values (gen_random_uuid(),'${tenant}','${id}','prompt','drafting')" >/dev/null
  done
  sample_start i "${dep}"
  I_START=$(date +%s)
}

check_i_finish() {
  [ -n "${I_AGENT}" ] || return
  local dep="${REL}-improvements-proof"
  wait_for $((300 - ($(date +%s) - I_START))) ready_at_least "${dep}" 1
  local first took=never
  first=$(sample_first i 1)
  [ -n "${first}" ] && took=$((first - I_START))
  sql "delete from improvement_proposals where agent_id='${I_AGENT}'" >/dev/null
  local t0 back=never
  t0=$(date +%s)
  wait_for 300 ready_at_most "${dep}" 0 && back=$(($(date +%s) - t0))
  sample_stop i
  local peak
  peak=$(sample_peak i)
  number "proof pool, seconds to first pod, peak pods" "${took}, ${peak}"
  number "proof pool, seconds back to zero" "${back}"
  if [ "${peak}" -ge 1 ] && [ "${back}" != "never" ]; then
    record i PASS "0 to ${peak} in ${took} s on 4 queued proposals, back to 0 in ${back} s"
  else
    record i FAIL "peak ${peak}, first pod ${took} s, back ${back} s"
  fi
}

runner_pod() { kc get pods -l "abenix.io/pool=default,app.kubernetes.io/name=agent-runtime" --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null; }

upload_asset() {
  local zip="${ROOT_DIR}/e2e/fixtures/uat_python_app.zip" tries=0 status=""
  [ -f "${zip}" ] || return 1
  ASSET_ID=$(curl -sS -m 120 -K "${AUTH}" -F "file=@${zip};type=application/zip" \
    -F "metadata={\"name\":\"scale-e2e-${RUN}\",\"description\":\"scale-e2e\"}" \
    "${BASE}/api/code-assets" 2>/dev/null | jq -r '.data.id // .id // empty')
  [ -n "${ASSET_ID}" ] || return 1
  while [ "${tries}" -lt 60 ]; do
    api GET "/api/code-assets/${ASSET_ID}"
    status=$(printf '%s' "${API_BODY}" | jq -r '.data.status // .status // empty')
    case "${status}" in ready|analyzed) return 0 ;; error|failed) return 1 ;; esac
    tries=$((tries + 1))
    sleep 4
  done
  return 1
}

bench() { # bench <log> <args...>, runs the bench inside a pool pod, exit code is the bench's
  local log=$1 pod rc
  shift
  pod=$(runner_pod)
  [ -n "${pod}" ] || return 2
  kc exec -i "${pod}" -c agent-runtime -- sh -c 'cat > /tmp/bench.py' < "${ROOT_DIR}/scripts/load/code_runner_bench.py" 2>/dev/null
  kc exec "${pod}" -c agent-runtime -- python3 /tmp/bench.py --asset "${ASSET_ID}" "$@" >> "${log}" 2>&1
  rc=$?
  return "${rc}"
}

find_runner() { kc get deploy -l "abenix.io/asset=${ASSET_ID},app=abenix-code-runner" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null; }

check_j() {
  if ! upload_asset; then
    record j FAIL "the test code asset did not become ready, id ${ASSET_ID:-none}"
    return
  fi
  local input='{"a":2,"b":3}' log="${OUT}/runner-bench.log" rc dep
  : > "${log}"
  bench "${log}" --input "${input}" --scenario cold,warm,zero --n 200 --max-p50-ms 500 --max-p99-ms 5000
  rc=$?
  dep=$(find_runner)
  [ -n "${dep}" ] || { record j FAIL "no runner Deployment for the asset, bench exit ${rc}"; return; }
  # concurrent calls for a while so CPU rises past its target on the small requests
  sample_start j "${dep}"
  local i=0 rc2=0 t0
  t0=$(date +%s)
  while [ $(($(date +%s) - t0)) -lt 150 ] && [ "$(ready_of "${dep}")" -lt 2 ]; do
    i=$((i + 1))
    bench "${log}" --input "${input}" --scenario concurrency --concurrency 64 --n 64 --min-calls-per-s 0 || rc2=$?
  done
  sample_stop j
  local peak
  peak=$(sample_peak j)
  grep -E '^\{' "${log}" | while read -r line; do
    printf '%s' "${line}" | jq -r 'select(.scenario) | "\(.scenario) p50_ms=\(.p50_ms // "-") p99_ms=\(.p99_ms // "-") calls_per_s=\(.calls_per_s // "-") first_call_ms=\(.first_call_ms // "-") seconds_until_warm=\(.seconds_until_warm_again // .seconds_until_warm // "-") errors=\(.errors // 0)"' 2>/dev/null
  done | sort -u | tail -12 > "${OUT}/runner-summary.txt"
  sed 's/^/  /' "${OUT}/runner-summary.txt"
  local s
  while read -r s; do number "runner $(printf '%s' "${s}" | cut -d' ' -f1)" "$(printf '%s' "${s}" | cut -d' ' -f2-)"; done < "${OUT}/runner-summary.txt"
  number "doc says, warm p50, p99, calls a second, after zero" "17.9 ms, 21.6 ms, 57, 3.5 s"
  # idle past CODE_RUNNER_IDLE_SECONDS, then the reaper must take it to zero
  log "j waiting for the runner to go idle, then forcing the reaper"
  sleep 70
  local job="scale-e2e-reap-${RUN}" reaped=no
  kc create job "${job}" "--from=cronjob/${REL}-code-runner-reaper" >/dev/null 2>&1
  kc wait --for=condition=complete "job/${job}" --timeout=240s >/dev/null 2>&1
  wait_for 200 ready_at_most "${dep}" 0 && reaped=yes
  kc delete job "${job}" --ignore-not-found >/dev/null 2>&1
  # the next call wakes it
  local before after wake=never
  before=$(date +%s)
  sample_start j2 "${dep}"
  bench "${log}" --input "${input}" --scenario warm --n 5 --max-p50-ms 0 --max-p99-ms 0
  local rc3=$?
  wait_for 200 ready_at_least "${dep}" 1
  sample_stop j2
  after=$(sample_first j2 1)
  [ -n "${after}" ] && wake=$((after - before))
  number "runner after reaper, seconds to a Ready pod" "${wake}"
  local detail="thresholds exit ${rc}, HPA peak ${peak} pods, reaper to zero ${reaped}, next call woke it in ${wake} s, wake call exit ${rc3}"
  if [ "${rc}" = "0" ] && [ "${peak}" -ge 2 ] && [ "${reaped}" = "yes" ] && [ "${wake}" != "never" ] && [ "${rc3}" = "0" ]; then
    record j PASS "${detail}"
  else
    record j FAIL "${detail}, log ${log}"
  fi
}

hpa_target() { # replica count an HPA on this Deployment holds, its spec is the source
  kc get hpa -o json 2>/dev/null | jq -r --arg d "$1" '.items[] | select(.spec.scaleTargetRef.name==$d) | .metadata.name' | head -1
}

check_k() {
  local dep missing=""
  for dep in "${REL}-api" "${REL}-web" "${REL}-worker" "${REL}-cognify-worker"; do
    [ -n "$(hpa_target "${dep}")" ] || missing="${missing} ${dep}"
  done
  if [ -n "${missing}" ]; then
    record k FAIL "no HPA on${missing}, the overlay should have enabled them"
    return
  fi
  local image pull
  image=$(kc get deploy "${REL}-api" -o jsonpath='{.spec.template.spec.containers[0].image}')
  pull=$(kc get deploy "${REL}-api" -o jsonpath='{.spec.template.spec.containers[0].imagePullPolicy}')
  # real HTTP from inside the cluster, a port forward cannot carry enough to move CPU
  kc delete pod scale-e2e-load --ignore-not-found >/dev/null 2>&1
  kc run scale-e2e-load --image="${image}" --image-pull-policy="${pull}" --restart=Never \
    --env="TARGETS=http://${REL}-api:8000/api/health http://${REL}-web:3000/login" \
    --command -- python3 -c '
import multiprocessing, os, threading, time, urllib.request
end = time.time() + 240
def hit(url):
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=10).read()
        except Exception:
            time.sleep(0.05)
def worker(url):
    ts = [threading.Thread(target=hit, args=(url,), daemon=True) for _ in range(16)]
    [t.start() for t in ts]
    [t.join() for t in ts]
ps = [multiprocessing.Process(target=worker, args=(u,)) for u in os.environ["TARGETS"].split() for _ in range(3)]
[p.start() for p in ps]
[p.join() for p in ps]
' >/dev/null 2>&1
  # Celery work needs embeddings and a key, so these two are driven by plain CPU in the pod
  local burn='import multiprocessing, time
def b():
    end = time.time() + 200
    while time.time() < end:
        pass
ps = [multiprocessing.Process(target=b) for _ in range(2)]
[p.start() for p in ps]
[p.join() for p in ps]'
  ( kc exec "deploy/${REL}-worker" -- python3 -c "${burn}" ) >/dev/null 2>&1 &
  BG_PIDS="${BG_PIDS} $!"
  ( kc exec "deploy/${REL}-cognify-worker" -- python3 -c "${burn}" ) >/dev/null 2>&1 &
  BG_PIDS="${BG_PIDS} $!"
  sample_start ka "${REL}-api"
  sample_start kw "${REL}-web"
  sample_start kq "${REL}-worker"
  sample_start kc "${REL}-cognify-worker"
  local t0 name peak first
  t0=$(date +%s)
  sleep 240
  sample_stop ka
  sample_stop kw
  sample_stop kq
  sample_stop kc
  kc delete pod scale-e2e-load --ignore-not-found --wait=false >/dev/null 2>&1
  # a CPU HPA waits 300 s by default before it lets a pod go
  local back=never t1
  t1=$(date +%s)
  k_all_back() {
    ready_at_most "${REL}-api" 1 && ready_at_most "${REL}-web" 1 && ready_at_most "${REL}-worker" 1 \
      && ready_at_most "${REL}-cognify-worker" 1
  }
  wait_for 420 k_all_back && back=$(($(date +%s) - t1))
  local detail="" ok=1 kind
  for name in ka:api kw:web kq:worker kc:cognify; do
    kind=${name#*:}
    name=${name%%:*}
    peak=$(sample_peak "${name}")
    first=$(sample_first "${name}" 2)
    [ -n "${first}" ] && first=$((first - t0)) || first=never
    number "HPA ${kind}, peak pods, seconds to second pod" "${peak}, ${first}"
    detail="${detail} ${kind} ${peak}"
    [ "${peak}" -ge 2 ] || ok=0
  done
  number "HPAs, seconds back to 1 pod after load" "${back}"
  [ "${back}" != "never" ] || ok=0
  if [ "${ok}" = "1" ]; then
    record k PASS "peaks${detail}, all back to 1 in ${back} s, worker and cognify driven by CPU in the pod, not by Celery jobs"
  else
    record k FAIL "peaks${detail}, back ${back}"
  fi
}

check_l() {
  local detail="" ok=1
  if command -v k6 >/dev/null 2>&1; then
    local rc
    BASE="${BASE}" PASSWORD="${ADMIN_PASSWORD}" EMAIL="${ADMIN_EMAIL}" \
      k6 run --quiet --summary-trend-stats "avg,med,p(95),p(99)" "${ROOT_DIR}/scripts/load/baseline.js" \
      > "${OUT}/k6.log" 2>&1
    rc=$?
    grep -E 'http_req_duration|http_req_failed|http_reqs|checks' "${OUT}/k6.log" | sed 's/^/  /' | cut -c1-120
    number "k6 baseline exit" "${rc}"
    detail="k6 exit ${rc}"
    [ "${rc}" = "0" ] || ok=0
  else
    detail="k6 not installed, brew install k6"
  fi

  local pod key token rc2
  pod=$(kc get pods -l app.kubernetes.io/name=api --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [ -n "${pod}" ]; then
    kc exec -i "${pod}" -c api -- env BASE="http://${REL}-api:8000" AF_EMAIL="${ADMIN_EMAIL}" AF_PASSWORD="${ADMIN_PASSWORD}" \
      python3 - < "${ROOT_DIR}/scripts/load/decision_load_setup.py" > "${PRIVATE}/decision.json" 2>/dev/null
    key=$(jq -r '.key // empty' "${PRIVATE}/decision.json" 2>/dev/null)
    token=$(jq -r '.token // empty' "${PRIVATE}/decision.json" 2>/dev/null)
    DECISION_KEY=${key}
    if [ -n "${key}" ] && [ -n "${token}" ]; then
      kc exec -i "${pod}" -c api -- python3 - --base "http://${REL}-api:8000" --token "${token}" --key "${key}" \
        --concurrency 100 --seconds 30 < "${ROOT_DIR}/scripts/load/decision_load.py" > "${OUT}/decision-load.log" 2>&1
      rc2=$?
      grep -E '^(PASS|FAIL) ' "${OUT}/decision-load.log" | sed 's/^/  /' | cut -c1-120
      while read -r state name measured limit; do
        [ -n "${name}" ] && number "decisions ${name}" "${measured#measured=} (${state} ${limit})"
      done <<EOF
$(grep -E '^(PASS|FAIL) ' "${OUT}/decision-load.log")
EOF
      number "doc says, decisions a second" "1467, 1306, 1096"
      detail="${detail}, decision_load exit ${rc2}"
      [ "${rc2}" = "0" ] || ok=0
    else
      detail="${detail}, decision setup gave no key"
      ok=0
    fi
  else
    detail="${detail}, no API pod for decision_load"
    ok=0
  fi

  if [ -n "${ASSET_ID}" ]; then
    local log="${OUT}/runner-bench-final.log" rc3
    : > "${log}"
    bench "${log}" --input '{"a":2,"b":3}' --scenario warm,concurrency --n 200 --concurrency 64
    rc3=$?
    grep -E '^(PASS|FAIL) ' "${log}" | sed 's/^/  /' | cut -c1-120
    while read -r state name measured limit; do
      [ -n "${name}" ] && number "bench ${name}" "${measured#measured=} (${state} ${limit})"
    done <<EOF
$(grep -E '^(PASS|FAIL) ' "${log}")
EOF
    detail="${detail}, code_runner_bench exit ${rc3}"
    [ "${rc3}" = "0" ] || ok=0
  else
    detail="${detail}, code_runner_bench skipped, check j made no asset"
  fi
  if [ "${ok}" = "1" ]; then
    record l PASS "${detail}"
  else
    record l FAIL "${detail}, logs in ${OUT}"
  fi
}

main() {

  for tool in kubectl helm curl jq awk python3; do need "${tool}"; done
  [ -f "${OVERLAY}" ] || { echo "scale-e2e could not run, no overlay at ${OVERLAY}" >&2; exit 2; }
  kubectl get ns "${NS}" >/dev/null 2>&1 || { echo "scale-e2e could not run, no namespace ${NS}" >&2; exit 2; }
  kc get deploy "${REL}-webhook-catcher" >/dev/null 2>&1 || {
    echo "scale-e2e could not run, it counts side effects at the webhook catcher, set devCatchers.enabled" >&2
    exit 2
  }
  kubectl top nodes >/dev/null 2>&1 || log "metrics server not answering, check k will fail"
  kc get cronjob "${REL}-code-runner-reaper" >/dev/null 2>&1 || log "no reaper CronJob, check j will fail"

  trap finish EXIT
  trap 'exit 130' INT TERM

  pf_start || { echo "scale-e2e could not run, no port forward to the API" >&2; exit 2; }
  login || { echo "scale-e2e could not run, the admin login was refused, set ADMIN_EMAIL and ADMIN_PASSWORD" >&2; exit 2; }
  api GET /api/admin/scaling/pools
  if ! printf '%s' "${API_BODY}" | jq -e '.data | has("dedicated_available")' >/dev/null 2>&1; then
    echo "scale-e2e could not run, the API image does not have this branch yet, deploy it first" >&2
    exit 2
  fi

  apply_overlay || { echo "scale-e2e could not run, the overlay did not apply" >&2; exit 2; }
  log "output in ${OUT}"

  want a && check_a
  want n && check_n
  want m && check_m_start
  want b && check_b
  want c && check_c
  want d && check_d
  want e && check_e
  want g && check_g
  want f && check_f
  want m && check_m_finish
  want h && check_h_start
  want i && check_i_start
  want h && check_h_finish
  want i && check_i_finish
  want j && check_j
  want l && check_l
  want k && check_k
  exit 0
}

# a test sources this file for its helpers
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
