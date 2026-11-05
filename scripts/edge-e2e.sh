#!/usr/bin/env bash
# End to end test of the edge product on the live minikube cluster, real pods, one per variant.
# Prints a pass, fail table and exits nonzero on any failure.
#
#   EDGE_E2E_VARIANTS   which runtimes, default "python rust c"
#   EDGE_E2E_GATEWAY=0  leaves out gateway mode
#   EDGE_E2E_SKIP_BUILD=1  uses images already on the cluster
#   EDGE_E2E_SKIP_API_DOWN=1  leaves out scaling the API to 0
#   KEEP=1              leaves the test pods and objects in place
#   ADMIN_EMAIL, ADMIN_PASSWORD  platform admin, defaults are the seeded ones
#   ANTHROPIC_API_KEY or CLAUDE_SUBSCRIPTION_TOKEN  used when abenix-secrets holds no model credential
set -u

export PATH="/opt/homebrew/bin:$HOME/.docker/bin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS="${NAMESPACE:-abenix}"
API_DEPLOY="${API_DEPLOY:-abenix-api}"
API_RELEASE="${RELEASE_NAME:-abenix}"
API_SVC="${API_DEPLOY}.${NS}.svc.cluster.local:8000"
BROKER_HOST="abenix-mosquitto.${NS}.svc.cluster.local"
MQTT_URL="mqtt://${BROKER_HOST}:1883"
TESTBED_NS="${TESTBED_NAMESPACE:-abenix-testbed}"
TAG="${EDGE_E2E_TAG:-e2e}"
REGISTRY="localhost:5000/abenix"
RUN="$(date +%s)"
VARIANTS="${EDGE_E2E_VARIANTS:-python rust c}"
TOOL="e2e-edge-tool"
UPLINK="e2e-uplink"
GW_REL="e2e-gw"
GROUP="e2e-${RUN}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/edge-e2e.XXXXXX")"
chmod 700 "$WORK"
RESULTS="$WORK/results"
: > "$RESULTS"
API_REPLICAS=""
RELEASES=""
SECRETS=""
FAILED=0
PASSED=0
SKIPPED=0
HAVE_MODEL=0
LLM_MODE=""
LLM_KEY=""
LLM_TOKEN=""

say() { printf '%s\n' "$(redact "$*")"; }
step() { say ""; say "== $*"; }

# anything that could carry a secret goes through here before it is shown
redact() {
  local text="$*" s
  for s in $SECRETS; do
    text="${text//"$s"/***}"
  done
  printf '%s' "$text"
}
remember_secret() { [ -n "$1" ] && SECRETS="$SECRETS $1"; }

record() { # record <where> <check> <pass|fail|skip> [message]
  local where="$1" check="$2" status="$3" msg="${4:-}"
  # kubectl exec adds its own last line, the reason is the one before it
  msg="$(redact "$msg" | grep -v '^command terminated with exit code' | tail -1 | tr '\t' ' ' | cut -c1-400)"
  printf '%s\t%s\t%s\t%s\n' "$where" "$check" "$status" "$msg" >> "$RESULTS"
  case "$status" in
    pass) PASSED=$((PASSED + 1)); printf '  pass %s %s\n' "$where" "$check" ;;
    skip) SKIPPED=$((SKIPPED + 1)); printf '  skip %s %s, %s\n' "$where" "$check" "$msg" ;;
    *) FAILED=$((FAILED + 1)); printf '  FAIL %s %s, %s\n' "$where" "$check" "$msg" ;;
  esac
}

# check <where> <name> <command...>, the last output line is the reason on failure
check() {
  local where="$1" name="$2" out
  shift 2
  out="$("$@" 2>&1)"
  if [ $? -eq 0 ]; then
    record "$where" "$name" pass
    return 0
  fi
  record "$where" "$name" fail "$out"
  return 1
}

tool() { kubectl exec -n "$NS" "$TOOL" -- python /tmp/e2e/tool.py "$@" </dev/null; }
tool_in() { kubectl exec -i -n "$NS" "$TOOL" -- python /tmp/e2e/tool.py "$@"; }
save_secret() { printf '%s' "$2" | tool_in save-secret "$1" >/dev/null; }
new_token() { head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-40; }

restore_api() {
  [ -z "$API_REPLICAS" ] && return 0
  say "restoring ${API_DEPLOY} to ${API_REPLICAS} replicas"
  kubectl scale "deployment/${API_DEPLOY}" -n "$NS" --replicas="$API_REPLICAS" >/dev/null 2>&1
  kubectl rollout status "deployment/${API_DEPLOY}" -n "$NS" --timeout=300s >/dev/null 2>&1 \
    || say "WARNING ${API_DEPLOY} is not ready after 300 s, check it by hand"
  API_REPLICAS=""
}

cleanup() {
  local code=$?
  trap - EXIT INT TERM
  restore_api
  if [ "${KEEP:-0}" = "1" ]; then
    say "KEEP=1, the test pods stay in namespace ${NS}, releases${RELEASES}"
  else
    say "cleaning up"
    kubectl get pod -n "$NS" "$TOOL" >/dev/null 2>&1 && tool cleanup >/dev/null 2>&1
    local r
    for r in $RELEASES; do
      helm uninstall "$r" -n "$NS" >/dev/null 2>&1
      kubectl delete pvc -n "$NS" -l "app.kubernetes.io/instance=$r" --wait=false >/dev/null 2>&1
    done
    kubectl delete pod,svc -n "$NS" -l "app.kubernetes.io/part-of=edge-e2e" --wait=false >/dev/null 2>&1
  fi
  rm -rf "$WORK"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

print_table() {
  say ""
  printf '%-10s %-36s %-5s %s\n' "WHERE" "CHECK" "RESULT" "DETAIL"
  while IFS="$(printf '\t')" read -r where name status msg; do
    printf '%-10s %-36s %-5s %s\n' "$where" "$name" "$status" "$msg"
  done < "$RESULTS"
  say ""
  say "${PASSED} passed, ${FAILED} failed, ${SKIPPED} skipped"
}

die() { say "edge-e2e cannot run, $*"; exit 2; }

preflight() {
  local c
  for c in kubectl helm base64 tr cut; do
    command -v "$c" >/dev/null 2>&1 || die "$c is not installed"
  done
  [ "$(kubectl config current-context 2>/dev/null)" = "minikube" ] || [ -n "${EDGE_E2E_ANY_CONTEXT:-}" ] \
    || die "kubectl does not point at minikube, set EDGE_E2E_ANY_CONTEXT=1 to run against this cluster"
  kubectl get "deployment/${API_DEPLOY}" -n "$NS" >/dev/null 2>&1 || die "no deployment ${API_DEPLOY} in namespace ${NS}"
  kubectl get svc abenix-mosquitto -n "$NS" >/dev/null 2>&1 || die "no abenix-mosquitto service in namespace ${NS}, the MQTT checks need it"
}

secret_value() { # secret_value <secret> <namespace> <key>
  kubectl get secret "$1" -n "$2" -o "go-template={{index .data \"$3\"}}" 2>/dev/null | grep -v '^<no value>$' | base64 --decode 2>/dev/null
}

real_secret() {
  case "$(printf '%s' "$1" | tr 'A-Z' 'a-z')" in
    ''|placeholder|changeme|dev|none|null|unset|your-key-here) return 1 ;;
  esac
  return 0
}

find_model_credential() {
  local k v
  for k in ANTHROPIC_API_KEY anthropic-api-key; do
    v="$(secret_value abenix-secrets "$NS" "$k")"
    if real_secret "$v"; then
      LLM_MODE="existing"; LLM_KEY="$k"; HAVE_MODEL=1
      say "model credential found in abenix-secrets under ${k}"
      return 0
    fi
  done
  v="$(secret_value abenix-secrets "$NS" CLAUDE_SUBSCRIPTION_TOKEN)"
  if real_secret "$v"; then
    LLM_MODE="existing"; LLM_TOKEN="CLAUDE_SUBSCRIPTION_TOKEN"; HAVE_MODEL=1
    say "subscription token found in abenix-secrets under CLAUDE_SUBSCRIPTION_TOKEN"
    return 0
  fi
  if real_secret "${ANTHROPIC_API_KEY:-}" || real_secret "${CLAUDE_SUBSCRIPTION_TOKEN:-}"; then
    LLM_MODE="host"; HAVE_MODEL=1
    remember_secret "${ANTHROPIC_API_KEY:-}"
    remember_secret "${CLAUDE_SUBSCRIPTION_TOKEN:-}"
    say "abenix-secrets holds no model credential, using the one from this shell's environment"
    return 0
  fi
  say "NO MODEL CREDENTIAL. In secret abenix-secrets the keys ANTHROPIC_API_KEY, anthropic-api-key and CLAUDE_SUBSCRIPTION_TOKEN are empty,"
  say "and this shell has neither ANTHROPIC_API_KEY nor CLAUDE_SUBSCRIPTION_TOKEN. The real model answer checks are skipped, everything else runs."
}

llm_values() {
  case "$LLM_MODE" in
    existing)
      printf 'existing_llm_secret:\n  name: abenix-secrets\n  api_key_key: "%s"\n  auth_token_key: "%s"\n' "$LLM_KEY" "$LLM_TOKEN"
      ;;
    host)
      printf 'anthropic_api_key: "%s"\nanthropic_auth_token: "%s"\n' "${ANTHROPIC_API_KEY:-}" "${CLAUDE_SUBSCRIPTION_TOKEN:-}"
      ;;
  esac
}

build_images() {
  if [ "${EDGE_E2E_SKIP_BUILD:-0}" = "1" ]; then
    say "using images already on the cluster, tag ${TAG}"
    return 0
  fi
  step "Building the images on the cluster's docker"
  local env_out r
  env_out="$(minikube docker-env --shell bash 2>/dev/null)" || die "minikube docker-env failed, is minikube running"
  ( eval "$env_out"
    for r in edge-runtime edge-runtime-rust edge-runtime-c; do
      say "building ${r}"
      docker build -q -t "${REGISTRY}/${r}:${TAG}" "${ROOT}/apps/${r}" >/dev/null || exit 1
    done ) || die "an image build failed"
}

start_tool() {
  step "Starting the tool pod and the uplink relay"
  local image="${REGISTRY}/edge-runtime:${TAG}"
  kubectl delete pod,svc -n "$NS" -l "app.kubernetes.io/part-of=edge-e2e" --wait=true >/dev/null 2>&1
  kubectl apply -n "$NS" -f - >/dev/null <<YAML || die "the tool pod could not be created"
apiVersion: v1
kind: Pod
metadata:
  name: ${TOOL}
  labels: {app.kubernetes.io/part-of: edge-e2e, e2e-role: tool}
spec:
  restartPolicy: Never
  containers:
    - name: tool
      image: ${image}
      imagePullPolicy: IfNotPresent
      command: ["python", "-c", "import time; time.sleep(86400)"]
      env:
        - {name: E2E_API, value: "http://${API_SVC}"}
        - {name: E2E_BROKER, value: "${BROKER_HOST}"}
        - {name: E2E_UPLINK, value: "http://${UPLINK}.${NS}.svc.cluster.local:18001"}
---
apiVersion: v1
kind: Pod
metadata:
  name: ${UPLINK}
  labels: {app.kubernetes.io/part-of: edge-e2e, e2e-role: uplink}
spec:
  restartPolicy: Never
  containers:
    - name: uplink
      image: ${image}
      imagePullPolicy: IfNotPresent
      command: ["python", "-m", "abenix_edge.sim.uplink"]
      env:
        - {name: UPLINK_TARGET, value: "${API_SVC}"}
---
apiVersion: v1
kind: Service
metadata:
  name: ${UPLINK}
  labels: {app.kubernetes.io/part-of: edge-e2e}
spec:
  selector: {e2e-role: uplink}
  ports:
    - {name: relay, port: 18000, targetPort: 18000}
    - {name: control, port: 18001, targetPort: 18001}
YAML
  kubectl wait pod "$TOOL" "$UPLINK" -n "$NS" --for=condition=ready --timeout=240s >/dev/null 2>&1 \
    || die "the tool pods are not ready, is image ${image} on the cluster"
  kubectl exec -i -n "$NS" "$TOOL" -- sh -c 'mkdir -p /tmp/e2e && cat > /tmp/e2e/tool.py' < "${ROOT}/scripts/lib/edge_e2e_tool.py" \
    || die "could not copy the tool into its pod"
  kubectl exec -n "$NS" "$TOOL" -- sh -c 'nohup python /tmp/e2e/tool.py blackhole >/dev/null 2>&1 &' </dev/null
  BLACKHOLE="http://$(kubectl get pod "$TOOL" -n "$NS" -o jsonpath='{.status.podIP}'):8099"
  printf '{"email":"%s","password":"%s"}' "${ADMIN_EMAIL:-admin@abenix.dev}" "${ADMIN_PASSWORD:-Admin123456}" | tool_in save-env
  local msg
  msg="$(tool ready 2>&1)" || die "$msg"
  tool signing-key > "$WORK/platform_pub.pem" || die "could not read the platform signing key"
  tool test-key > "$WORK/test_pub.pem" || die "could not make the test key"
  ok_or_die_api_tenant
}

ok_or_die_api_tenant() {
  local id out
  id="$(tool agent "e2e probe ${RUN}" current_time 30)" || die "could not create a test agent, $id"
  out="$(tool compile "$id" probe.agent)" || die "could not compile a test agent, $out"
  TENANT="$(printf '%s' "$out" | cut -d' ' -f2)"
  [ -n "$TENANT" ] || die "the compiled bundle names no tenant"
}

image_of() { case "$1" in python) echo edge-runtime ;; rust) echo edge-runtime-rust ;; c) echo edge-runtime-c ;; esac; }
short_of() { case "$1" in python) echo py ;; rust) echo rs ;; c) echo c ;; esac; }

common_values() { # common_values <release> <image name> <auth token> [volume size]
  cat <<YAML
fullnameOverride: "$1"
image:
  repository: "${REGISTRY}/$2"
  tag: "${TAG}"
  pullPolicy: IfNotPresent
auth_token: "$3"
persistence:
  size: ${4:-64Mi}
YAML
}

install_release() { # install_release <release> <chart> <values file> <extra helm args...>
  local rel="$1" chart="$2" values="$3" out
  shift 3
  case " $RELEASES " in *" $rel "*) ;; *) RELEASES="$RELEASES $rel" ;; esac
  out="$(helm upgrade --install "$rel" "${ROOT}/infra/helm/${chart}" -n "$NS" -f "$values" "$@" --wait --timeout 300s 2>&1)" \
    || { printf '%s\n' "$out" | tail -2; return 1; }
}

wait_pod_ready() { # wait_pod_ready <pod> <seconds>
  local i
  for i in $(seq 1 "$2"); do
    if [ "$(kubectl get pod "$1" -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)" = "True" ]; then
      return 0
    fi
    sleep 1
  done
  echo "pod $1 is not ready after $2 s"
  return 1
}

refuses_start() { # refuses_start <image> <text> <env args...>
  local image="$1" text="$2" name="e2e-refuse-$$-$RANDOM" i phase out
  shift 2
  kubectl run "$name" -n "$NS" --image="$image" --image-pull-policy=IfNotPresent --restart=Never \
    --labels="app.kubernetes.io/part-of=edge-e2e" --env=EDGE_MODE=legacy --env=PLATFORM_URL= "$@" >/dev/null 2>&1
  for i in $(seq 1 60); do
    phase="$(kubectl get pod "$name" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null)"
    case "$phase" in Succeeded|Failed) break ;; esac
    sleep 1
  done
  out="$(kubectl logs "$name" -n "$NS" 2>&1)"
  kubectl delete pod "$name" -n "$NS" --wait=false >/dev/null 2>&1
  [ "$phase" = "Failed" ] || { echo "the pod ended up $phase instead of refusing to start"; return 1; }
  printf '%s' "$out" | grep -q "$text" || { echo "wrong refusal, $(printf '%s' "$out" | tail -1)"; return 1; }
}

legacy_variant() { # legacy_variant <python|rust|c>
  local v="$1" short image chart rel neg gw auth neg_auth values neg_values base neg_base
  short="$(short_of "$v")"
  image="$(image_of "$v")"
  chart="$image"
  rel="e2e-${short}"
  neg="e2e-${short}-neg"
  gw="e2e-${short}-${RUN}"
  base="http://${rel}.${NS}.svc.cluster.local:8080"
  neg_base="http://${neg}.${NS}.svc.cluster.local:8080"
  auth="$(new_token)"; neg_auth="$(new_token)"
  remember_secret "$auth"; remember_secret "$neg_auth"
  save_secret "auth-${short}" "$auth"
  save_secret "neg-${short}" "$neg_auth"

  step "${v} runtime"
  check "$v" refuses_start_without_signing_key refuses_start "${REGISTRY}/${image}:${TAG}" "no signing public key" --env=EDGE_AUTH_TOKEN=x
  check "$v" refuses_start_without_auth_token refuses_start "${REGISTRY}/${image}:${TAG}" "no EDGE_AUTH_TOKEN" --env=EDGE_ALLOW_UNSIGNED=true

  local platform_token
  platform_token="$(tool mint "e2e ${rel} ${RUN}" 2>&1)" || { record "$v" chart_install fail "could not mint a platform token, $platform_token"; return 0; }
  remember_secret "$platform_token"

  values="$WORK/${rel}.yaml"
  { common_values "$rel" "$image" "$auth"
    cat <<YAML
gateway_id: "${gw}"
gateway_name: "${gw}"
platform_url: "http://${API_SVC}"
platform_token: "${platform_token}"
mqtt_url: "${MQTT_URL}"
tenant_id: "${TENANT}"
endpoint_url: "${base}"
YAML
    llm_values
  } > "$values"
  check "$v" chart_install install_release "$rel" "$chart" "$values" --set-file "signing_pubkey=$WORK/platform_pub.pem" || return 0

  neg_values="$WORK/${neg}.yaml"
  { common_values "$neg" "$image" "$neg_auth"
    cat <<YAML
gateway_id: "${neg}-${RUN}"
platform_url: "http://${API_SVC}"
tenant_id: "e2e-tenant-a"
anthropic_api_key: "dummy-key-for-a-silent-server"
anthropic_base_url: "${BLACKHOLE}"
YAML
  } > "$neg_values"
  check "$v" chart_install_refusal_pod install_release "$neg" "$chart" "$neg_values" --set-file "signing_pubkey=$WORK/test_pub.pem" || return 0

  local pk out agent slug digest line name msg
  pk="$(tool find-gw "$gw" 90 2>&1)"
  if [ $? -eq 0 ]; then
    record "$v" gateway_registered pass
  else
    record "$v" gateway_registered fail "$pk"
    return 0
  fi

  agent="$(tool agent "e2e ${v} ota ${RUN}" current_time 60 2>&1)" || { record "$v" agent_created fail "$agent"; return 0; }
  out="$(tool compile "$agent" "${short}.agent" 2>&1)"
  if [ $? -eq 0 ]; then
    record "$v" bundle_compiled_and_signed pass
  else
    record "$v" bundle_compiled_and_signed fail "$out"
    return 0
  fi
  slug="$(printf '%s' "$out" | cut -d' ' -f1)"
  digest="$(printf '%s' "$out" | cut -d' ' -f3)"

  check "$v" http_push_refused_without_auth tool push "$base" "$slug" "${short}.agent" - 401
  check "$v" http_push_with_auth tool push "$base" "$slug" "${short}.agent" "auth-${short}" 200
  check "$v" http_pushed_agent_loaded tool agents "$base" "$slug" "$digest"

  # no gateway listens on this id, so MQTT goes unanswered and only HTTP can confirm
  local http_gw http_pk bad http_agent
  http_gw="e2e-http-${short}-${RUN}"
  http_pk="$(tool register-gw "$http_gw" "$base" 2>&1)"
  if [ $? -eq 0 ]; then
    check "$v" platform_set_push_token tool set-push "$http_pk" "auth-${short}"
    check "$v" platform_http_fallback_delivers tool deploy "$http_pk" "$agent" "d['deployed'] and d['delivered_via']=='http' and d['gateway_reachable']"
    bad="$(new_token)"; save_secret "bad-${short}" "$bad"
    tool set-push "$http_pk" "bad-${short}" >/dev/null 2>&1
    check "$v" platform_says_when_token_is_wrong tool deploy "$http_pk" "$agent" "not d['deployed'] and d['delivered_via'] is None and d['http']['status']==401"
  else
    record "$v" platform_http_fallback_delivers fail "$http_pk"
  fi

  # online over MQTT
  digest="$(tool deploy "$pk" "$agent" "d['deployed'] and d['delivered_via']=='mqtt' and d['mqtt']['acked']" 2>&1)"
  if [ $? -eq 0 ]; then
    record "$v" mqtt_ota_online_acked pass
    check "$v" mqtt_bundle_retained_at_qos1 tool mqtt-retained "$gw" "$slug" "$digest"
    check "$v" mqtt_online_agent_loaded tool wait-agent "$base" "$slug" "$digest" 30
  else
    record "$v" mqtt_ota_online_acked fail "$digest"
  fi

  # offline at publish time
  local off_agent off_out off_slug off_digest
  off_agent="$(tool agent "e2e ${v} offline ${RUN}" current_time 60 2>&1)"
  off_out="$(tool compile "$off_agent" "${short}-off.agent" 2>&1)"
  off_slug="$(printf '%s' "$off_out" | cut -d' ' -f1)"
  kubectl scale "statefulset/${rel}" -n "$NS" --replicas=0 >/dev/null
  kubectl wait --for=delete "pod/${rel}-0" -n "$NS" --timeout=120s >/dev/null 2>&1
  off_digest="$(tool deploy "$pk" "$off_agent" "not d['deployed'] and d['queued'] and d['delivered_via'] is None and d['gateway_reachable'] is False and d['_status']==200" 2>&1)"
  if [ $? -eq 0 ]; then
    record "$v" mqtt_offline_reported_as_queued pass
  else
    record "$v" mqtt_offline_reported_as_queued fail "$off_digest"
    off_digest="-"
  fi
  kubectl scale "statefulset/${rel}" -n "$NS" --replicas=1 >/dev/null
  if wait_pod_ready "${rel}-0" 180 >/dev/null; then
    check "$v" mqtt_offline_gateway_catches_up tool wait-agent "$base" "$off_slug" "$off_digest" 90
  else
    record "$v" mqtt_offline_gateway_catches_up fail "the pod did not come back"
  fi

  # real answer from the model
  if [ "$HAVE_MODEL" = "1" ]; then
    check "$v" execute_real_model_answer tool ask "$base" "auth-${short}" "$slug"
  else
    record "$v" execute_real_model_answer skip "no model credential in abenix-secrets or this shell"
    check "$v" execute_route_answers tool exec-alive "$base" "auth-${short}" "$slug"
  fi

  # refusals on the pod that trusts the test key
  out="$(tool suite "$neg_base" "neg-${short}" e2e-tenant-a e2e-good 2>&1)"
  if [ $? -ne 0 ]; then
    record "$v" refusal_suite fail "$(printf '%s' "$out" | tail -1)"
  fi
  local neg_digest=""
  while IFS="$(printf '\t')" read -r name msg; do
    case "$name" in
      '') ;;
      digest) neg_digest="$msg" ;;
      *)
        if [ "$msg" = "ok" ]; then record "$v" "$name" pass; else record "$v" "$name" fail "$msg"; fi
        ;;
    esac
  done <<OUT
$out
OUT

  # the refusal pod has no MQTT, so only its volume can bring the bundle back
  kubectl delete pod "${neg}-0" -n "$NS" >/dev/null 2>&1
  if wait_pod_ready "${neg}-0" 180 >/dev/null; then
    check "$v" bundle_survives_pod_delete tool wait-agent "$neg_base" e2e-good "${neg_digest:--}" 30
    check "$v" agent_serves_after_pod_delete tool exec-alive "$neg_base" "neg-${short}" e2e-good
  else
    record "$v" bundle_survives_pod_delete fail "the pod did not come back"
  fi

  # rotate the token, the chart rolls the pod
  local new_auth
  new_auth="$(new_token)"; remember_secret "$new_auth"
  sed "s/^auth_token: .*/auth_token: \"${new_auth}\"/" "$values" > "$values.new" && mv "$values.new" "$values"
  save_secret "old-${short}" "$auth"
  save_secret "auth-${short}" "$new_auth"
  save_secret "new-${short}" "$new_auth"
  if install_release "$rel" "$chart" "$values" --set-file "signing_pubkey=$WORK/platform_pub.pem" >/dev/null && wait_pod_ready "${rel}-0" 180 >/dev/null; then
    check "$v" auth_token_rotation tool auth-rotated "$base" "old-${short}" "new-${short}" "$slug"
  else
    record "$v" auth_token_rotation fail "the upgrade with the new token did not come up"
  fi
  save_secret "slug-${short}" "$slug"
  eval "SLUG_${short}=\$slug"
}

api_down_check() {
  [ "${EDGE_E2E_SKIP_API_DOWN:-0}" = "1" ] && { say "skipping the API down check"; return 0; }
  step "Platform API at 0 replicas"
  API_REPLICAS="$(kubectl get "deployment/${API_DEPLOY}" -n "$NS" -o jsonpath='{.spec.replicas}')"
  kubectl scale "deployment/${API_DEPLOY}" -n "$NS" --replicas=0 >/dev/null
  local i pods
  for i in $(seq 1 120); do
    pods="$(kubectl get pods -n "$NS" -l "app.kubernetes.io/name=api,app.kubernetes.io/instance=${API_RELEASE}" --no-headers 2>/dev/null | wc -l | tr -d ' ')"
    [ "$pods" = "0" ] && break
    sleep 1
  done
  local v short base slug
  for v in $VARIANTS; do
    short="$(short_of "$v")"
    base="http://e2e-${short}.${NS}.svc.cluster.local:8080"
    eval "slug=\${SLUG_${short}:-}"
    if [ -z "$slug" ]; then
      record "$v" serves_with_api_down skip "this variant did not get far enough to have an agent"
      continue
    fi
    check "$v" health_with_api_down tool wait-up "$base"
    if [ "$HAVE_MODEL" = "1" ]; then
      check "$v" real_answer_with_api_down tool ask "$base" "auth-${short}" "$slug"
    else
      check "$v" serves_with_api_down tool exec-alive "$base" "auth-${short}" "$slug"
    fi
    kubectl delete pod "e2e-${short}-0" -n "$NS" >/dev/null 2>&1
    if wait_pod_ready "e2e-${short}-0" 180 >/dev/null; then
      check "$v" restart_with_api_down_keeps_agent tool agents "$base" "$slug" -
    else
      record "$v" restart_with_api_down_keeps_agent fail "the pod did not come back without the API"
    fi
  done
  restore_api
}

gw_py() { kubectl exec -n "$NS" "${GW_REL}-0" -c edge-runtime -- python -c "$1" </dev/null; }
gw_status_expr() { # gw_status_expr <python expr over s> <seconds> <message>
  local i
  for i in $(seq 1 "$2"); do
    if gw_py "
import json, sys, urllib.request
s = json.load(urllib.request.urlopen('http://127.0.0.1:8081/status', timeout=3))
sys.exit(0 if ($1) else 1)" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "$3"
  return 1
}

append_rows() { # append_rows <from> <to> <t0 ms>
  gw_py "
import os
os.makedirs('/var/lib/abenix-edge/e2e', exist_ok=True)
p = '/var/lib/abenix-edge/e2e/seq.csv'
new = not os.path.exists(p)
with open(p, 'a') as f:
    if new: f.write('ts,seq\n')
    for i in range($1, $2 + 1): f.write(f'{$3 + i * 2000},{i}\n')
"
}

gateway_mode() {
  step "Gateway mode"
  local conf opc="" testbed=false created pk gid token token2 auth values old_key msg
  if kubectl get svc meter -n "$TESTBED_NS" >/dev/null 2>&1 && kubectl get svc opc-plc -n "$TESTBED_NS" >/dev/null 2>&1; then
    testbed=true
    opc="$(secret_value testbed-credentials "$TESTBED_NS" opcua-password)"
    remember_secret "$opc"
  fi
  conf="{\"run\":\"${RUN}\",\"group\":\"${GROUP}\",\"testbed\":${testbed},\"testbed_ns\":\"${TESTBED_NS}\",\"opcua_password\":\"${opc}\"}"
  created="$(printf '%s' "$conf" | tool_in gw-create 2>&1)"
  if [ $? -ne 0 ]; then
    record gateway gateway_created fail "$created"
    return 0
  fi
  record gateway gateway_created pass
  pk="$(printf '%s' "$created" | cut -d' ' -f1)"
  gid="$(printf '%s' "$created" | cut -d' ' -f2)"

  token="$(tool gw-install "$pk" "http://${UPLINK}.${NS}.svc.cluster.local:18000" 2>&1)"
  if [ $? -ne 0 ]; then
    record gateway install_token fail "$token"
    return 0
  fi
  remember_secret "$token"
  save_secret enroll-1 "$token"
  auth="$(new_token)"; remember_secret "$auth"; save_secret auth-gw "$auth"
  tool set-push "$pk" auth-gw >/dev/null 2>&1

  values="$WORK/${GW_REL}.yaml"
  gateway_values "$token" "$auth" > "$values"
  check gateway chart_install_gateway_mode install_release "$GW_REL" edge-runtime "$values" || return 0

  check gateway enrolled_with_etk_token tool gw-wait "$pk" "g['enrolled_at'] is not None" 60
  check gateway used_token_refused tool enroll-refused enroll-1
  check gateway heartbeat_on_platform tool gw-wait "$pk" "g['status']=='online' and g.get('uptime_s') is not None and g['applied_version']==g['config_version']" 60

  # every collector type, delivered means it reached telemetry
  ( tool mqtt-publish "e2e/${RUN}/sensors/s1" 40 >/dev/null 2>&1 & )
  append_rows 1 5 "$(( ($(date +%s) - 900) * 1000 ))" >/dev/null 2>&1
  local line kind node
  for line in can_j1939:truck-j can_obd2:truck-o nmea_gps:truck-g mqtt_bridge:sens file_tail:log; do
    kind="${line%%:*}"; node="${line##*:}"
    check gateway "collector_${kind}_delivers" tool devices "$GROUP" "$node" 180
  done
  if [ "$testbed" = "true" ]; then
    check gateway collector_modbus_delivers tool devices "$GROUP" meter-1 180
    check gateway collector_opcua_delivers tool devices "$GROUP" plc 180
  else
    record gateway collector_modbus_delivers skip "no testbed in ${TESTBED_NS}, run bash scripts/deploy.sh testbed"
    record gateway collector_opcua_delivers skip "no testbed in ${TESTBED_NS}, run bash scripts/deploy.sh testbed"
  fi
  check gateway collector_health_reports_running tool gw-wait "$pk" "all(c['status']=='running' for c in g['collector_health'] if c['name'] not in ('bulk',))" 60

  # the agents role on an enrolled gateway
  local agent out slug digest
  agent="$(tool agent "e2e gateway agent ${RUN}" current_time 60 2>&1)"
  out="$(tool compile "$agent" gw.agent 2>&1)"
  slug="$(printf '%s' "$out" | cut -d' ' -f1)"
  digest="$(tool deploy "$pk" "$agent" "d['deployed'] and d['delivered_via']=='mqtt'" 2>&1)"
  if [ $? -eq 0 ]; then
    record gateway agents_role_mqtt_ota pass
    local gw_base="http://${GW_REL}.${NS}.svc.cluster.local:8080"
    check gateway agents_role_agent_loaded tool wait-agent "$gw_base" "$slug" "$digest" 30
    check gateway agents_role_needs_token tool push "$gw_base" "$slug" gw.agent - 401
    if [ "$HAVE_MODEL" = "1" ]; then
      check gateway agents_role_real_model_answer tool ask "$gw_base" auth-gw "$slug"
    else
      record gateway agents_role_real_model_answer skip "no model credential in abenix-secrets or this shell"
      check gateway agents_role_execute_answers tool exec-alive "$gw_base" auth-gw "$slug"
    fi
  else
    record gateway agents_role_mqtt_ota fail "$digest"
  fi

  # uplink cut, a pod delete during the cut, then backfill with nothing lost
  local t0_ms t0 cut_start cut_end
  cut_start="$(date +%s)"
  t0="$(( cut_start - 400 ))"
  t0_ms="$(( t0 * 1000 ))"
  check gateway uplink_cut tool uplink cut
  append_rows 101 130 "$t0_ms" >/dev/null 2>&1
  check gateway buffer_holds_during_cut gw_status_expr "s['buffer']['depth'] > 0 and s['uplink']['status'] != 'online'" 60 "the buffer did not fill or the uplink still says online"
  kubectl delete pod "${GW_REL}-0" -n "$NS" >/dev/null 2>&1
  if wait_pod_ready "${GW_REL}-0" 240 >/dev/null; then
    record gateway pod_delete_during_cut pass
  else
    record gateway pod_delete_during_cut fail "the pod did not come back while the uplink was cut"
  fi
  sleep 3
  append_rows 131 160 "$t0_ms" >/dev/null 2>&1
  sleep 5
  check gateway uplink_restored tool uplink restore
  cut_end="$(date +%s)"
  check gateway backfill_zero_loss_in_order tool expect-seq "$GROUP" log csv seq "$(( t0 + 200 ))" "$(( t0 + 330 ))" 101 160 240
  check gateway edge_seq_no_gaps_over_the_cut tool edge-seq "$gid" "$(( cut_start - 5 ))" "$(( cut_end + 5 ))" 120

  # enrolment token rotation
  token="$(tool gw-install "$pk" "http://${UPLINK}.${NS}.svc.cluster.local:18000" 2>&1)"
  token2="$(tool gw-install "$pk" "http://${UPLINK}.${NS}.svc.cluster.local:18000" 2>&1)"
  remember_secret "$token"; remember_secret "$token2"
  save_secret enroll-replaced "$token"
  tool set-push "$pk" auth-gw >/dev/null 2>&1
  check gateway replaced_token_refused tool enroll-refused enroll-replaced
  old_key="$(gw_py "import json; print(json.load(open('/var/lib/abenix-edge/state.json'))['key'])" 2>/dev/null)"
  remember_secret "$old_key"
  save_secret old-gw-key "$old_key"
  gateway_values "$token2" "$auth" > "$values"
  if install_release "$GW_REL" edge-runtime "$values" >/dev/null && wait_pod_ready "${GW_REL}-0" 240 >/dev/null; then
    check gateway re_enrols_with_new_token tool gw-wait "$pk" "g['enrolled_at'] is not None and g['status']=='online'" 90
    check gateway old_gateway_key_refused tool key-refused old-gw-key
  else
    record gateway re_enrols_with_new_token fail "the upgrade with the new token did not come up"
  fi

  # buffer limit, with the uplink cut so nothing drains
  tool uplink cut >/dev/null 2>&1
  gw_py "
import base64, os, time
os.makedirs('/var/lib/abenix-edge/e2e', exist_ok=True)
t = int(time.time() * 1000)
with open('/var/lib/abenix-edge/e2e/bulk1.csv', 'w') as f:
    f.write('ts,seq,pad\n')
    for i in range(1, 6001):
        f.write(f'{t + i},{i},{base64.b64encode(os.urandom(6000)).decode()}\n')
" >/dev/null 2>&1
  check gateway buffer_limit_drops_oldest gw_status_expr "s['buffer']['dropped_size'] > 0 and s['buffer']['bytes'] <= s['buffer']['max_bytes']" 240 "no reading was dropped, or the buffer grew past its limit"
  check gateway buffer_limit_keeps_newest buffer_keeps_newest

  # revoke
  check gateway revoke_call tool gw-revoke "$pk"
  tool uplink restore >/dev/null 2>&1
  check gateway revoked_on_platform tool gw-wait "$pk" "g['status']=='revoked'" 30
  check gateway revoke_stops_the_gateway gw_status_expr "'revoked' in str(s.get('problem')).lower() and not [c for c in s['collectors'] if c['status'] == 'running']" 60 "the gateway did not stop its collectors after the revoke"
  append_rows 201 205 "$t0_ms" >/dev/null 2>&1
  sleep 6
  check gateway revoked_gateway_stops_reading seq_absent_from_buffer 201
}

# reads the buffer file itself, the sender is cut off so nothing leaves it
buffer_seqs_py() { # buffer_seqs_py <subject suffix> <python test over seqs>
  gw_py "
import json, sqlite3, sys, zlib
db = sqlite3.connect('file:/var/lib/abenix-edge/buffer.db?mode=ro', uri=True)
seqs = [v['value'] for row in db.execute(\"SELECT body FROM chunks WHERE subject LIKE '%$1'\") for v in json.loads(zlib.decompress(row[0])) if v['name'] == 'seq']
sys.exit(0 if ($2) else 1)" >/dev/null 2>&1
}

buffer_keeps_newest() {
  local i
  for i in $(seq 1 48); do
    buffer_seqs_py /bulk/fill "seqs and max(seqs) == 6000 and min(seqs) > 1" && return 0
    sleep 5
  done
  echo "the newest readings are not in the buffer, or the oldest were not the ones dropped"
  return 1
}

seq_absent_from_buffer() {
  buffer_seqs_py /log/csv "$1 not in seqs" && return 0
  echo "a reading written after the revoke was still collected"
  return 1
}

gateway_values() { # gateway_values <enrol token> <auth token>
  common_values "$GW_REL" edge-runtime "$2" 512Mi
  local image="${REGISTRY}/edge-runtime:${TAG}"
  cat <<YAML
mode: gateway
gateway_id: "e2e-gw"
platform_url: "http://${UPLINK}.${NS}.svc.cluster.local:18000"
enroll_token: "$1"
mqtt_url: "${MQTT_URL}"
endpoint_url: "http://${GW_REL}.${NS}.svc.cluster.local:8080"
resources:
  requests: {cpu: 100m, memory: 128Mi}
  limits: {cpu: "1", memory: 512Mi}
extra_containers:
  - name: canbus
    image: "${image}"
    imagePullPolicy: IfNotPresent
    command: ["python", "-m", "abenix_edge.sim.canbus"]
    env:
      - {name: CANBUS_LISTEN, value: "127.0.0.1"}
      - {name: CAN_CHANNEL, value: vcan0}
      - {name: CAN_BITRATE, value: "250000"}
    securityContext: {runAsNonRoot: true, allowPrivilegeEscalation: false}
  - name: ecu
    image: "${image}"
    imagePullPolicy: IfNotPresent
    command: ["python", "-m", "abenix_edge.sim.ecu"]
    env:
      - {name: CAN_HOST, value: "127.0.0.1"}
      - {name: CAN_PORT, value: "29536"}
      - {name: CAN_CHANNEL, value: vcan0}
    securityContext: {runAsNonRoot: true, allowPrivilegeEscalation: false}
YAML
  llm_values
}

# a run with KEEP=1 leaves pods and volumes, they would confuse this one
remove_old_run() {
  local r
  for r in e2e-py e2e-py-neg e2e-rs e2e-rs-neg e2e-c e2e-c-neg "$GW_REL"; do
    helm uninstall "$r" -n "$NS" >/dev/null 2>&1
    kubectl delete pvc -n "$NS" -l "app.kubernetes.io/instance=$r" --wait=true >/dev/null 2>&1
  done
}

main() {
  preflight
  remove_old_run
  build_images
  start_tool
  find_model_credential
  local v
  for v in $VARIANTS; do
    legacy_variant "$v"
  done
  api_down_check
  if [ "${EDGE_E2E_GATEWAY:-1}" = "1" ]; then
    gateway_mode
  fi
  print_table
  if [ "$FAILED" -gt 0 ]; then
    say "edge-e2e FAILED"
    exit 1
  fi
  say "edge-e2e passed"
}

main "$@"
