#!/usr/bin/env bash
# Edge runtime end-to-end smoke test on minikube.
#   1. installs the helm chart
#   2. waits for the gateway pod to come up
#   3. picks a sample agent, marks it edge-compatible
#   4. compiles + deploys via the platform API
#   5. port-forwards the gateway and hits /agents/{slug}/execute
#
# Requires: kubectl, helm, jq, curl. Assumes the platform API is reachable
# at $PLATFORM_URL (default http://localhost:8000) and the caller has a
# valid bearer token in $PLATFORM_TOKEN.

set -euo pipefail

NAMESPACE=${NAMESPACE:-abenix}
RELEASE=${RELEASE:-edge-test}
GATEWAY_ID=${GATEWAY_ID:-test-001}
PLATFORM_URL=${PLATFORM_URL:-http://localhost:8000}
PLATFORM_TOKEN=${PLATFORM_TOKEN:-}
AGENT_SLUG=${AGENT_SLUG:-edge-smoke-agent}
CHART=${CHART:-infra/helm/edge-runtime/}
LOCAL_PORT=${LOCAL_PORT:-18080}

step() { echo -e "\033[1;36m▶ $*\033[0m"; }
fail() { echo -e "\033[1;31m✗ $*\033[0m" >&2; exit 1; }
ok()   { echo -e "\033[1;32m✓ $*\033[0m"; }

[ -z "$PLATFORM_TOKEN" ] && fail "PLATFORM_TOKEN is required"

step "helm install $RELEASE ($GATEWAY_ID)"
helm upgrade --install "$RELEASE" "$CHART" \
  --namespace "$NAMESPACE" --create-namespace \
  --set "gateway_id=$GATEWAY_ID" \
  --set "gateway_name=$GATEWAY_ID" \
  --set "platform_url=$PLATFORM_URL" \
  --set "platform_token=$PLATFORM_TOKEN" \
  --wait --timeout 180s

step "waiting for pod ready"
kubectl wait --namespace "$NAMESPACE" --for=condition=ready pod \
  -l app.kubernetes.io/instance="$RELEASE" --timeout=180s

step "registering gateway with platform"
GW_BODY=$(curl -fsSL -X POST "$PLATFORM_URL/api/edge/gateways/register" \
  -H "Authorization: Bearer $PLATFORM_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"gateway_id\":\"$GATEWAY_ID\",\"name\":\"$GATEWAY_ID\"}")
GW_PK=$(echo "$GW_BODY" | jq -r '.data.gateway.id')
[ -z "$GW_PK" ] || [ "$GW_PK" = "null" ] && fail "could not register gateway: $GW_BODY"
ok "gateway $GW_PK"

step "finding sample agent slug=$AGENT_SLUG"
AGENT_LIST=$(curl -fsSL "$PLATFORM_URL/api/agents?limit=200" \
  -H "Authorization: Bearer $PLATFORM_TOKEN")
AGENT_ID=$(echo "$AGENT_LIST" | jq -r ".data.agents[] | select(.slug==\"$AGENT_SLUG\") | .id")
if [ -z "$AGENT_ID" ] || [ "$AGENT_ID" = "null" ]; then
  step "creating sample agent"
  AGENT_ID=$(curl -fsSL -X POST "$PLATFORM_URL/api/agents" \
    -H "Authorization: Bearer $PLATFORM_TOKEN" \
    -H "Content-Type: application/json" \
    -d @- <<EOF | jq -r '.data.agent.id // .data.id'
{
  "name": "Edge Smoke Agent",
  "slug": "$AGENT_SLUG",
  "system_prompt": "You are an edge smoke agent. Reply with 'ok'.",
  "agent_model_config": {
    "model": "claude-haiku-4-5-20251001",
    "temperature": 0.0,
    "max_tokens": 64,
    "max_iterations": 1,
    "tools": ["current_time"],
    "edge_compatible": true,
    "edge_constraints": {
      "max_payload_bytes": 4096,
      "max_runtime_seconds": 5,
      "mqtt_subscribe": [],
      "mqtt_publish": []
    }
  }
}
EOF
)
fi
[ -z "$AGENT_ID" ] || [ "$AGENT_ID" = "null" ] && fail "could not get/create agent"
ok "agent $AGENT_ID"

step "deploying agent → gateway"
DEPLOY=$(curl -fsSL -X POST "$PLATFORM_URL/api/edge/gateways/$GW_PK/deploy" \
  -H "Authorization: Bearer $PLATFORM_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"agent_id\":\"$AGENT_ID\"}")
echo "$DEPLOY" | jq -e '.data.deployed == true' >/dev/null \
  || fail "deploy failed: $DEPLOY"
DIGEST=$(echo "$DEPLOY" | jq -r '.data.bundle_digest')
ok "bundle_digest ${DIGEST:0:16}…"

step "port-forwarding gateway → :$LOCAL_PORT"
kubectl -n "$NAMESPACE" port-forward "svc/$RELEASE-edge-runtime" "$LOCAL_PORT:8080" \
  >/tmp/edge-pf.log 2>&1 &
PF_PID=$!
trap 'kill $PF_PID 2>/dev/null || true' EXIT
sleep 3

step "GET /agents on gateway"
GW_AGENTS=$(curl -fsSL "http://127.0.0.1:$LOCAL_PORT/agents")
echo "$GW_AGENTS" | jq -e ".agents[] | select(.slug==\"$AGENT_SLUG\")" >/dev/null \
  || fail "agent not loaded on gateway: $GW_AGENTS"
ok "gateway lists $AGENT_SLUG"

step "POST /agents/$AGENT_SLUG/execute"
EXEC=$(curl -fsSL -X POST "http://127.0.0.1:$LOCAL_PORT/agents/$AGENT_SLUG/execute" \
  -H "Content-Type: application/json" \
  -d '{"message":"hello edge"}')
echo "$EXEC" | jq -e '.slug and (.duration_ms | type == "number")' >/dev/null \
  || fail "execute response shape wrong: $EXEC"
ok "executed; duration=$(echo "$EXEC" | jq -r '.duration_ms')ms"

ok "edge smoke test PASSED"
