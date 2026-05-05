#!/usr/bin/env bash
# Abenix v1.1.0 — production-tooling UAT smoke against a live cluster.
#
# Drives the v1.1 control plane end-to-end:
#   1. login            → /api/auth/login                 → JWT
#   2. connectors list  → GET /api/connectors             → [count]
#   3. approvals list   → GET /api/approvals?mine=1       → [count]
#   4. edge gateways    → GET /api/edge/gateways          → [count]
#   5. mqtt trigger     → POST /api/agents/iot-pump-mqtt-trigger/execute
#                                                          → execution_id
#
# Each step prints  ✓ / ✘  with a one-line reason.  Aborts on the first
# failure with a non-zero exit code, so this script doubles as a deploy
# gate.
#
# Override env:
#   API=http://localhost:8000
#   AF_EMAIL=admin@abenix.dev AF_PASSWORD=Admin123456
#
# Usage:
#   bash scripts/uat-v110.sh

set -uo pipefail

API="${API:-http://localhost:8000}"
EMAIL="${AF_EMAIL:-admin@abenix.dev}"
PASSWORD="${AF_PASSWORD:-Admin123456}"

# ─── Pretty output helpers ────────────────────────────────────────────
GREEN=$(printf '\033[32m'); RED=$(printf '\033[31m')
DIM=$(printf '\033[2m');    BOLD=$(printf '\033[1m')
RESET=$(printf '\033[0m')

ok()   { printf '  %s✓%s %s\n'      "${GREEN}" "${RESET}" "$1"; }
fail() { printf '  %s✘%s %s\n'      "${RED}"   "${RESET}" "$1" >&2; exit 1; }
info() { printf '%s▶ %s%s\n'        "${BOLD}"  "$1" "${RESET}"; }
note() { printf '    %s%s%s\n'      "${DIM}"   "$1" "${RESET}"; }

require_jq() {
  command -v jq >/dev/null 2>&1 || fail "jq is required (apt-get install jq | brew install jq)"
}

# ─── Step 1 — login ────────────────────────────────────────────────────
step_login() {
  info "1/5  login"
  local body resp_code
  body=$(mktemp)
  resp_code=$(curl -sS -o "${body}" -w '%{http_code}' \
    -X POST "${API}/api/auth/login" \
    -H 'Content-Type: application/json' \
    --data "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}" || true)

  if [[ "${resp_code}" != "200" ]]; then
    note "HTTP ${resp_code}"
    note "$(head -c 200 "${body}" || true)"
    rm -f "${body}"
    fail "login HTTP ${resp_code}"
  fi

  TOKEN=$(jq -r '.data.access_token // .access_token' < "${body}")
  rm -f "${body}"
  if [[ -z "${TOKEN}" || "${TOKEN}" == "null" ]]; then
    fail "login returned no access_token"
  fi
  ok "logged in as ${EMAIL}"
}

# ─── Step 2 — connectors list ──────────────────────────────────────────
step_connectors() {
  info "2/5  GET /api/connectors"
  local body code
  body=$(mktemp)
  code=$(curl -sS -o "${body}" -w '%{http_code}' \
    -H "Authorization: Bearer ${TOKEN}" \
    "${API}/api/connectors" || true)

  if [[ "${code}" != "200" ]]; then
    note "HTTP ${code} — was the v1.1 connector router deployed?"
    note "$(head -c 200 "${body}" || true)"
    rm -f "${body}"
    fail "connectors list returned HTTP ${code}"
  fi

  local n
  n=$(jq -r '(.data // .) | length' < "${body}" 2>/dev/null || echo "0")
  rm -f "${body}"
  ok "connectors list returned ${n} row(s) (≥0 expected)"
}

# ─── Step 3 — approvals list ───────────────────────────────────────────
step_approvals() {
  info "3/5  GET /api/approvals?mine=1"
  local body code
  body=$(mktemp)
  code=$(curl -sS -o "${body}" -w '%{http_code}' \
    -H "Authorization: Bearer ${TOKEN}" \
    "${API}/api/approvals?mine=1" || true)

  if [[ "${code}" != "200" ]]; then
    note "HTTP ${code} — was the v1.1 approvals router deployed?"
    note "$(head -c 200 "${body}" || true)"
    rm -f "${body}"
    fail "approvals list returned HTTP ${code}"
  fi

  local n
  n=$(jq -r '(.data // .) | length' < "${body}" 2>/dev/null || echo "0")
  rm -f "${body}"
  ok "approvals list returned ${n} row(s) (≥0 expected)"
}

# ─── Step 4 — edge gateways list ───────────────────────────────────────
step_edge() {
  info "4/5  GET /api/edge/gateways"
  local body code
  body=$(mktemp)
  code=$(curl -sS -o "${body}" -w '%{http_code}' \
    -H "Authorization: Bearer ${TOKEN}" \
    "${API}/api/edge/gateways" || true)

  if [[ "${code}" != "200" ]]; then
    note "HTTP ${code} — was the v1.1 edge router deployed?"
    note "$(head -c 200 "${body}" || true)"
    rm -f "${body}"
    fail "edge gateways list returned HTTP ${code}"
  fi

  local n
  n=$(jq -r '(.data // .) | length' < "${body}" 2>/dev/null || echo "0")
  rm -f "${body}"
  ok "edge gateways list returned ${n} row(s) (≥0 expected)"
}

# ─── Step 5 — fire one MQTT-triggered pipeline ─────────────────────────
step_mqtt_trigger() {
  info "5/5  fire MQTT-triggered pipeline"
  local agent_slug="${V110_TRIGGER_AGENT_SLUG:-iot-pump-mqtt-trigger}"
  local idem
  idem="uat-v110-$(date +%s)-$$"

  local body code
  body=$(mktemp)
  code=$(curl -sS -o "${body}" -w '%{http_code}' \
    -X POST "${API}/api/agents/${agent_slug}/execute" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: ${idem}" \
    --data '{"input":{"asset_id":"PUMP-UAT-1","vibration_rms":7.4,"timestamp":"2026-05-05T00:00:00Z"},"wait":false}' \
    || true)

  if [[ "${code}" != "200" && "${code}" != "201" && "${code}" != "202" ]]; then
    note "HTTP ${code} — agent slug '${agent_slug}' may not exist on this cluster yet"
    note "$(head -c 200 "${body}" || true)"
    rm -f "${body}"
    fail "MQTT-triggered pipeline returned HTTP ${code}"
  fi

  local exec_id
  exec_id=$(jq -r '.data.execution_id // .execution_id // ""' < "${body}" 2>/dev/null || true)
  rm -f "${body}"

  if [[ -z "${exec_id}" || "${exec_id}" == "null" ]]; then
    fail "execute response missing execution_id"
  fi
  ok "queued execution ${exec_id} (idempotency-key=${idem})"
}

# ─── Main ──────────────────────────────────────────────────────────────
main() {
  require_jq
  printf '%sAbenix v1.1.0 — production-tooling UAT%s\n' "${BOLD}" "${RESET}"
  printf '  api=%s\n  user=%s\n\n' "${API}" "${EMAIL}"

  step_login
  step_connectors
  step_approvals
  step_edge
  step_mqtt_trigger

  printf '\n%s%s ALL v1.1 UAT STEPS PASSED %s%s\n' "${GREEN}" "${BOLD}" "${RESET}" "${RESET}"
}

main "$@"
