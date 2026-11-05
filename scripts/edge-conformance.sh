#!/usr/bin/env bash
# The three edge runtimes against one contract, in docker with a real broker and no cluster.
# NO_BUILD=1 reuses images already tagged abenix/<runtime>:local.
set -u

export PATH="/opt/homebrew/bin:$HOME/.docker/bin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NET="edge-conf-$$"
FAILS=0
TOKEN="conformance-token"
TENANT="tenant-a"
RESULTS="$(mktemp)"

note() { printf '%s\n' "$*"; }
record() { # record <runtime> <check> <ok or message>
  if [ "$3" = "ok" ]; then
    printf '%-8s %-34s pass\n' "$1" "$2" >> "$RESULTS"
  else
    printf '%-8s %-34s FAIL %s\n' "$1" "$2" "$3" >> "$RESULTS"
    FAILS=$((FAILS + 1))
  fi
}

cleanup() {
  docker ps -aq --filter "label=$NET" | xargs docker rm -f >/dev/null 2>&1
  docker volume ls -q --filter "label=$NET" | xargs docker volume rm >/dev/null 2>&1
  docker network rm "$NET" >/dev/null 2>&1
  rm -f "$RESULTS"
}
trap cleanup EXIT

tool() { docker exec -i -e E2E_BROKER=broker e2e-tool-$$ python /tmp/e2e-tool.py "$@"; }

if [ "${NO_BUILD:-0}" != "1" ]; then
  for r in edge-runtime edge-runtime-rust edge-runtime-c; do
    note "building $r"
    docker build -q -t "abenix/$r:local" "$ROOT/apps/$r" >/dev/null || { note "build failed for $r"; exit 1; }
  done
fi

docker network create --label "$NET" "$NET" >/dev/null
docker run -d --name "broker-$$" --label "$NET" --network "$NET" --network-alias broker eclipse-mosquitto:2 \
  sh -c 'printf "listener 1883 0.0.0.0\nallow_anonymous true\n" > /tmp/m.conf; exec mosquitto -c /tmp/m.conf' >/dev/null
docker run -d --name "e2e-tool-$$" --label "$NET" --network "$NET" --network-alias tool \
  --entrypoint python abenix/edge-runtime:local -c 'import time; time.sleep(86400)' >/dev/null
docker cp "$ROOT/scripts/lib/edge_e2e_tool.py" "e2e-tool-$$:/tmp/e2e-tool.py" >/dev/null
docker exec -d "e2e-tool-$$" python /tmp/e2e-tool.py blackhole
printf '%s' "$TOKEN" | tool save-secret tok
PUB="$(tool test-key)"
sleep 2

start() { # start <name> <image> <gateway id> <volume> [env]
  local name="$1" image="$2" gw="$3" vol="$4"
  shift 4
  docker run -d --name "$name" --label "$NET" --network "$NET" --network-alias "$name" --read-only --tmpfs /tmp \
    --mount "type=volume,source=$vol,target=/var/edge/agents,volume-label=$NET" --user 1001 \
    -e GATEWAY_ID="$gw" -e EDGE_AUTH_TOKEN="$TOKEN" -e SIGNING_PUBKEY_PEM="$PUB" -e TENANT_ID="$TENANT" \
    -e ANTHROPIC_API_KEY=dummy -e ANTHROPIC_BASE_URL="http://tool:8099" -e PLATFORM_URL= -e EDGE_MODE=legacy \
    "$@" "$image" >/dev/null
}

wait_up() { # wait_up <container>
  local i
  for i in $(seq 1 40); do
    tool wait-up "http://$1:8080" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

refuses() { # refuses <runtime> <check> <image> <text> [env]
  local runtime="$1" check="$2" image="$3" text="$4" out rc
  shift 4
  out="$(docker run --rm --network "$NET" -e EDGE_MODE=legacy -e PLATFORM_URL= "$@" "$image" 2>&1)"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    record "$runtime" "$check" "it started"
  elif ! printf '%s' "$out" | grep -q "$text"; then
    record "$runtime" "$check" "wrong refusal $(printf '%s' "$out" | tail -1)"
  else
    record "$runtime" "$check" ok
  fi
}

for pair in python:edge-runtime rust:edge-runtime-rust c:edge-runtime-c; do
  rt="${pair%%:*}"
  image="abenix/${pair##*:}:local"
  name="conf-$rt-$$"
  gw="conf-$rt"
  vol="conf-vol-$rt-$$"
  note "== $rt"

  refuses "$rt" refuse_start_no_key "$image" "no signing public key" -e EDGE_AUTH_TOKEN=x
  refuses "$rt" refuse_start_loose_allow_unsigned "$image" "no signing public key" -e EDGE_AUTH_TOKEN=x -e EDGE_ALLOW_UNSIGNED=TRUE
  refuses "$rt" refuse_start_no_token "$image" "no EDGE_AUTH_TOKEN" -e SIGNING_PUBKEY_PEM="$PUB"

  start "$name" "$image" "$gw" "$vol" -e MQTT_URL="mqtt://broker:1883"
  if ! wait_up "$name"; then
    record "$rt" start "did not answer /health, $(docker logs --tail 3 "$name" 2>&1 | tail -1)"
    continue
  fi
  record "$rt" start ok

  out="$(tool suite "http://$name:8080" tok "$TENANT" conf-agent 2>&1)"
  digest=""
  while IFS="$(printf '\t')" read -r check msg; do
    case "$check" in
      digest) digest="$msg" ;;
      '') ;;
      *) if [ -n "$msg" ]; then record "$rt" "$check" "$msg"; else record "$rt" suite "$check"; fi ;;
    esac
  done <<< "$out"

  msg="$(tool mqtt-send "$gw" conf-online "$TENANT" true yes 2>&1)" && record "$rt" mqtt_online_ack ok || record "$rt" mqtt_online_ack "$msg"
  msg="$(tool mqtt-send "$gw" conf-foreign other-tenant false yes 2>&1)" && record "$rt" mqtt_foreign_tenant_refused ok || record "$rt" mqtt_foreign_tenant_refused "$msg"

  docker stop -t 20 "$name" >/dev/null
  offline_digest="$(tool mqtt-send "$gw" conf-offline "$TENANT" true no 2>&1)"
  docker start "$name" >/dev/null
  if wait_up "$name"; then
    msg="$(tool wait-agent "http://$name:8080" conf-offline "$offline_digest" 30 2>&1)" && record "$rt" mqtt_offline_retained_arrives ok || record "$rt" mqtt_offline_retained_arrives "$msg"
    msg="$(tool agents "http://$name:8080" conf-agent "$digest" 2>&1)" && record "$rt" http_bundle_survives_restart ok || record "$rt" http_bundle_survives_restart "$msg"
    msg="$(tool exec-alive "http://$name:8080" tok conf-agent 2>&1)" && record "$rt" execute_after_restart ok || record "$rt" execute_after_restart "$msg"
  else
    record "$rt" restart "did not come back"
  fi
  docker rm -f "$name" >/dev/null 2>&1
done

note "== python in gateway mode"
docker exec -d -e E2E_BROKER=broker "e2e-tool-$$" python /tmp/e2e-tool.py fake-platform
docker exec "e2e-tool-$$" sh -c 'mkdir -p /tmp/e2e' >/dev/null
printf '%s\n' "$PUB" | docker exec -i "e2e-tool-$$" sh -c 'cat > /tmp/e2e/pub.pem'
sleep 1
GW="conf-gw-$$"
gw_start() {
  docker run -d --name "$GW" --label "$NET" --network "$NET" --network-alias "$GW" --read-only --tmpfs /tmp --user 1001 \
    --mount "type=volume,source=conf-gw-data-$$,target=/var/lib/abenix-edge,volume-label=$NET" \
    -e EDGE_MODE=gateway -e ABENIX_URL=http://tool:8100 -e ABENIX_ENROLL_TOKEN=etk_conf -e ABENIX_EDGE_DATA=/var/lib/abenix-edge \
    -e EDGE_AUTH_TOKEN="$TOKEN" -e MQTT_URL=mqtt://broker:1883 -e ANTHROPIC_API_KEY=dummy -e ANTHROPIC_BASE_URL=http://tool:8099 \
    abenix/edge-runtime:local >/dev/null
}
gcheck() { # gcheck <check> <command...>
  local name="$1" out
  shift
  if out="$("$@" 2>&1)"; then record gateway "$name" ok; else record gateway "$name" "$(printf '%s' "$out" | tail -1)"; fi
}
rows() { docker exec "$GW" python -c "
import os, time
p = '/var/lib/abenix-edge/rows1.csv'
new = not os.path.exists(p)
t = int(time.time() * 1000)
with open(p, 'a') as f:
    if new: f.write('ts,seq\n')
    for i in range($1, $2 + 1): f.write(f'{t + i},{i}\n')
"; }
gw_start
if wait_up "$GW"; then
  gcheck enrols tool fake-expect "s['enrolls'] == 1 and s['heartbeats'] > 0" 30
  rows 1 5
  gcheck file_tail_delivers tool fake-expect "s['values'].get('seq', [])[:5] == [1, 2, 3, 4, 5]" 30
  tool mqtt-publish conf/sensors/s1 2 >/dev/null 2>&1
  gcheck mqtt_bridge_delivers tool fake-expect "'temp_c' in s['values']" 30
  gcheck agents_role_mqtt_ack tool mqtt-send conf-gw conf-agent tenant-a true yes
  gcheck agents_role_tenant_from_enrolment tool mqtt-send conf-gw conf-foreign other-tenant false yes
  gcheck agents_role_needs_token tool push "http://$GW:8080" conf-agent missing - 401
  gcheck agents_role_executes tool exec-alive "http://$GW:8080" tok conf-agent
  tool fake-link down >/dev/null
  rows 6 15
  sleep 3
  docker stop -t 20 "$GW" >/dev/null
  docker start "$GW" >/dev/null
  wait_up "$GW"
  rows 16 25
  sleep 3
  tool fake-link up >/dev/null
  gcheck backfill_after_cut_and_restart tool fake-expect "s['values'].get('seq') == list(range(1, 26))" 60
  gcheck edge_seq_no_gap_over_restart tool fake-expect "(lambda v: len(v) > 3 and v == list(range(1, len(v) + 1)))(s['values'].get('Edge/Seq', []))" 30
  gcheck stays_enrolled_after_restart tool fake-expect "s['enrolls'] == 1" 5
  gcheck agent_survives_restart tool agents "http://$GW:8080" conf-agent -
else
  record gateway start "did not answer /health, $(docker logs --tail 3 "$GW" 2>&1 | tail -1)"
fi

note ""
cat "$RESULTS"
note ""
if [ "$FAILS" -gt 0 ]; then
  note "$FAILS checks failed"
  exit 1
fi
note "all checks passed"
