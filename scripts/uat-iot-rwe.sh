#!/usr/bin/env bash
# Smoke-test the three RWE-inspired pipelines end-to-end via the platform
# API. Exercises the full agent runtime (validate → configure → reason →
# route → finalise) without needing the browser. Useful when the cluster
# web port-forward isn't available.
#
# Required env:
#   API=http://localhost:8000  (default)
#   AF_EMAIL / AF_PASSWORD     (defaults to seeded admin)

set -uo pipefail

API="${API:-http://localhost:8000}"
EMAIL="${AF_EMAIL:-admin@abenix.dev}"
PASSWORD="${AF_PASSWORD:-Admin123456}"

echo "▶ logging in as ${EMAIL} via ${API}"
TOKEN=$(curl -fs -X POST "${API}/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['access_token'])")

if [ -z "${TOKEN:-}" ]; then echo "✘ no token"; exit 1; fi
echo "  ✓ got token"

resolve_agent_id() {
  local slug="$1"
  for off in 0 100 200; do
    local id
    id=$(curl -fs -H "Authorization: Bearer ${TOKEN}" "${API}/api/agents?limit=100&offset=${off}" \
      | python3 -c "import sys,json,os; d=json.load(sys.stdin); s=os.environ['SLUG']; print(next((a['id'] for a in (d.get('data') or []) if a.get('slug')==s), ''))" 2>/dev/null)
    SLUG="$slug" id=$(SLUG="$slug" python3 -c "import sys,json,os; d=json.load(open(0)); s=os.environ['SLUG']; print(next((a['id'] for a in (d.get('data') or []) if a.get('slug')==s), ''))" < <(curl -fs -H "Authorization: Bearer ${TOKEN}" "${API}/api/agents?limit=100&offset=${off}"))
    if [ -n "$id" ]; then echo "$id"; return 0; fi
  done
  return 1
}

run_pipeline() {
  local slug="$1"
  local payload_json="$2"
  echo
  echo "▶ executing ${slug}"
  local agent_id
  agent_id=$(resolve_agent_id "$slug")
  if [ -z "$agent_id" ]; then echo "  ✘ agent ${slug} not found"; return 1; fi
  echo "  agent_id=${agent_id}"
  local body
  body=$(SLUG="$slug" PAYLOAD="$payload_json" python3 -c "
import os,json
p=json.loads(os.environ['PAYLOAD'])
msg=json.dumps(p)
print(json.dumps({'message':msg,'context':{'message':msg, **p},'wait':True,'wait_timeout_seconds':240}))
")

  # Stream SSE and capture the final 'event: complete' or 'event: error' marker.
  local raw
  raw=$(curl -sN --max-time 300 -X POST "${API}/api/agents/${agent_id}/execute" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "$body")
  local status
  status=$(echo "$raw" | grep -oE 'event: (complete|end|error|done)' | tail -1 | awk '{print $2}')
  local node_count
  node_count=$(echo "$raw" | grep -c 'node_complete')
  local fail_count
  fail_count=$(echo "$raw" | grep -c '"status": "failed"')
  echo "  events=${status:-none} nodes_complete=${node_count} nodes_failed=${fail_count}"
  if [ -n "$status" ] && [ "$node_count" -gt 1 ] && [ "$fail_count" -lt 2 ]; then
    echo "  ✓ ok"; return 0
  fi
  echo "  ✘ pipeline did not complete cleanly"
  return 1
}

run_pipeline_old() {
  local slug="$1"
  local payload_json="$2"
  local res=""
  return 0
}

# ── ValueEdge ────────────────────────────────────────────────────────
VE_INPUT='{
  "capacity_mw": 1200,
  "location": "Dogger Bank C, UK North Sea",
  "water_depth_m": 27,
  "distance_to_shore_km": 130,
  "soil_type": "clay",
  "wind_class": "I",
  "grid_voltage_kv": 220
}'
run_pipeline "iot-valueedge-pipeline" "$VE_INPUT" || ve_fail=1

# ── FieldEdge ────────────────────────────────────────────────────────
FE_INPUT='{
  "turbine_id": "TURB-04",
  "model": "V120-2.0",
  "issue": "Blade leading-edge erosion observed during this week climb inspection on blade 3, leading edge of outboard 8 metres shows pitting and exposed glass fibre, no through-skin damage."
}'
run_pipeline "iot-fieldedge-pipeline" "$FE_INPUT" || fe_fail=1

# ── BedROCC ──────────────────────────────────────────────────────────
BR_INPUT='{
  "alarm": {
    "code": "GBX-VIB-HI",
    "asset": "NL-T-08",
    "subsystem": "gearbox",
    "raw_severity": "MAJOR",
    "value_mm_per_s": 5.2,
    "threshold_mm_per_s": 4.5,
    "timestamp": "2026-05-05T08:14:33Z"
  },
  "recent_alarms": [
    {"code":"GBX-OIL-TEMP-HI","asset":"NL-T-08","ts":"2026-05-05T08:14:01Z"},
    {"code":"GBX-VIB-HI","asset":"NL-T-08","ts":"2026-05-05T08:14:33Z"},
    {"code":"PCS-FLT-A2","asset":"NL-T-08","ts":"2026-05-05T08:15:01Z"}
  ]
}'
run_pipeline "iot-bedrocc-pipeline" "$BR_INPUT" || br_fail=1

echo
if [ -z "${ve_fail:-}${fe_fail:-}${br_fail:-}" ]; then
  echo "✓ ALL THREE PIPELINES PASSED"
  exit 0
else
  echo "✘ at least one pipeline failed: ve=${ve_fail:-0} fe=${fe_fail:-0} br=${br_fail:-0}"
  exit 1
fi
