#!/usr/bin/env bash
# Boots the C runtime, pushes bundles over HTTP and checks every refusal.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &> /dev/null && pwd)"
BIN="${ROOT}/build/release/edge-runtime-c"
PORT="${PORT:-18080}"
STUB_PORT="${STUB_PORT:-18000}"
WORKDIR="$(mktemp -d)"
TOKEN="smoke-token"
AUTH="Authorization: Bearer ${TOKEN}"
trap 'set +e; [[ -n "${RUNTIME_PID:-}" ]] && kill "$RUNTIME_PID" 2>/dev/null; [[ -n "${STUB_PID:-}" ]] && kill "$STUB_PID" 2>/dev/null; rm -rf "$WORKDIR"' EXIT

code_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
refused() { # refused <bundle file> <slug> <text in the answer>
  local out
  out="$(curl -s -w ' %{http_code}' -H "$AUTH" --data-binary "@${WORKDIR}/$1.agent" "http://127.0.0.1:${PORT}/agents/$2/bundle")"
  echo "$out" | grep -q ' 400$' || { echo "FAIL: $1 was not refused: $out"; exit 1; }
  echo "$out" | grep -q "$3" || { echo "FAIL: $1 refused for the wrong reason: $out"; exit 1; }
  echo "  refused $1"
}
start_runtime() { # start_runtime <env assignments>
  env GATEWAY_ID="smoke-c" PORT="$PORT" PLATFORM_URL="http://127.0.0.1:${STUB_PORT}" PLATFORM_TOKEN="" \
    MQTT_URL="" SIGNING_PUBKEY_PATH="${WORKDIR}/signing_pub.pem" BUNDLE_DIR="${WORKDIR}/agents" \
    TENANT_ID="tenant-a" ANTHROPIC_API_KEY="" EDGE_AUTH_TOKEN="$TOKEN" "$@" "$BIN" &
  RUNTIME_PID=$!
  for i in $(seq 1 50); do
    curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null && return 0
    sleep 0.2
  done
  echo "FAIL: runtime did not answer /health"
  exit 1
}

if [[ ! -x "$BIN" ]]; then
  echo "binary not built at $BIN, run make release first" >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 required for bundle generation + stub server" >&2
  exit 2
fi

echo "[1/9] generate signing keypair + sample bundle"
export WORKDIR
python3 - <<PY
import base64, hashlib, io, os, sys, tarfile, time
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

workdir = os.environ["WORKDIR"]
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
pub_pem = key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)
with open(os.path.join(workdir, "signing_pub.pem"), "wb") as f:
    f.write(pub_pem)

MANIFEST = """name: Smoke Agent
slug: %(slug)s
tenant_id: %(tenant)s
version: 0.1.0
model: claude-sonnet-4-5-20250929
temperature: 0.2
max_iterations: 3
max_tokens: 256
tools:
- current_time
- code_executor
edge_constraints:
  max_payload_bytes: 4096
  max_runtime_seconds: 5
"""
prompt = b"You are a smoke-test agent."

# placeholder signature of the right size, then sign the stripped form as bundle.c verifies it
SIG_LEN = 256  # rsa 2048 bit signature length
mtime = int(time.time())

def build(sig_bytes, slug, tenant, extra=()):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        manifest = MANIFEST % {"slug": slug, "tenant": tenant}
        for name, data in [("agent.yaml", manifest.encode()),
                           ("system_prompt.md", prompt)] + list(extra):
            info = tarfile.TarInfo(name=name)
            if data is None:
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                tar.addfile(info)
                continue
            info.size = len(data); info.mtime = mtime
            tar.addfile(info, io.BytesIO(data))
        if sig_bytes is not None:
            info = tarfile.TarInfo(name="signature.sig")
            info.size = len(sig_bytes); info.mtime = mtime
            tar.addfile(info, io.BytesIO(sig_bytes))
    return out.getvalue()

def strip_sig(buf):
    i = 0
    s_start = s_end = None
    while i + 512 <= len(buf):
        h = buf[i:i+512]
        if all(b == 0 for b in h):
            break
        name = h[:100].split(b'\x00', 1)[0].decode("ascii", "ignore")
        sz_str = h[124:124+12].split(b'\x00', 1)[0].rstrip(b' ').decode()
        sz = int(sz_str, 8) if sz_str else 0
        blocks = (sz + 511) // 512
        if name == "signature.sig":
            s_start, s_end = i, i + 512 + blocks * 512
        i += 512 + blocks * 512
    return buf[:s_start] + buf[s_end:]

def signed(slug="smoke-agent", tenant="tenant-a", extra=()):
    to_sign = strip_sig(build(b"\x00" * SIG_LEN, slug, tenant, extra))
    sig = key.sign(
        to_sign,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    return build(sig, slug, tenant, extra)

good = signed()
bundles = {
    "smoke": good,
    "other-tenant": signed(slug="foreign", tenant="tenant-b"),
    "bad-slug": signed(slug="../../evil"),
    "bad-member": signed(slug="member", extra=[("../evil", b"owned")]),
    "symlink": signed(slug="linker", extra=[("link", None)]),
    "unsigned": build(None, "unsigned", "tenant-a"),
    "tampered": good.replace(b"You are a smoke-test agent.", b"You are a smoke-test agenT."),
}
for name, data in bundles.items():
    with open(os.path.join(workdir, name + ".agent"), "wb") as f:
        f.write(data)
print("bundle size = %d bytes" % len(good))
PY
test_rc=$?
if [[ $test_rc -ne 0 ]]; then
  echo "bundle generation failed" >&2
  exit 1
fi

echo "[2/9] start stub platform on :${STUB_PORT}"
( cd "$WORKDIR" && python3 -m http.server "$STUB_PORT" >/dev/null 2>&1 ) &
STUB_PID=$!

echo "[3/9] start refusals"
expect_refusal() { # expect_refusal <text> <env assignments>
  local text="$1" out rc
  shift
  out="$(env GATEWAY_ID=x PORT="$PORT" MQTT_URL="" BUNDLE_DIR="${WORKDIR}/refused" "$@" "$BIN" 2>&1)"
  rc=$?
  [[ $rc -ne 0 ]] || { echo "FAIL: started when it should refuse: $text"; exit 1; }
  echo "$out" | grep -q "$text" || { echo "FAIL: wrong refusal, wanted $text: $out"; exit 1; }
}
expect_refusal "no signing public key" SIGNING_PUBKEY_PATH=/nonexistent EDGE_AUTH_TOKEN=x
expect_refusal "no signing public key" SIGNING_PUBKEY_PATH=/nonexistent EDGE_AUTH_TOKEN=x EDGE_ALLOW_UNSIGNED=TRUE
expect_refusal "no EDGE_AUTH_TOKEN" SIGNING_PUBKEY_PATH="${WORKDIR}/signing_pub.pem"
head -c 16 /dev/urandom > "${WORKDIR}/garbage.pem"
expect_refusal "could not be parsed" SIGNING_PUBKEY_PATH="${WORKDIR}/garbage.pem" EDGE_AUTH_TOKEN=x

echo "[4/9] start runtime on :${PORT}"
start_runtime
HEALTH="$(curl -s "http://127.0.0.1:${PORT}/health" || true)"
echo "  health = $HEALTH"
echo "$HEALTH" | grep -q '"status":"ok"' || { echo "FAIL: /health"; exit 1; }
echo "$HEALTH" | grep -q '"gateway_id":"smoke-c"' || { echo "FAIL: gateway_id"; exit 1; }

echo "[5/9] POST bundle"
[[ "$(code_of --data-binary "@${WORKDIR}/smoke.agent" "http://127.0.0.1:${PORT}/agents/smoke-agent/bundle")" == "401" ]] \
  || { echo "FAIL: install without the token was not refused"; exit 1; }
[[ "$(code_of -H 'Authorization: Bearer wrong' --data-binary "@${WORKDIR}/smoke.agent" "http://127.0.0.1:${PORT}/agents/smoke-agent/bundle")" == "401" ]] \
  || { echo "FAIL: install with a wrong token was not refused"; exit 1; }
PUT="$(curl -sS -H "$AUTH" --data-binary "@${WORKDIR}/smoke.agent" \
            -H "Content-Type: application/x-tar" \
            "http://127.0.0.1:${PORT}/agents/smoke-agent/bundle")"
echo "  put = $PUT"
echo "$PUT" | grep -q '"slug":"smoke-agent"' || { echo "FAIL: bundle install"; exit 1; }
DIGEST="$(echo "$PUT" | sed -n 's/.*"digest":"\([0-9a-f]*\)".*/\1/p')"

LIST="$(curl -s "http://127.0.0.1:${PORT}/agents")"
echo "$LIST" | grep -q '"slug":"smoke-agent"' || { echo "FAIL: agent not registered"; exit 1; }

echo "[6/9] bad bundles"
refused other-tenant foreign "does not match"
refused bad-slug evil "slug"
refused bad-member member "unsafe path"
refused symlink linker "link or device"
refused unsigned unsigned "unsigned"
refused tampered smoke-agent "signature"
refused smoke other-name "sent to"
[[ "$(code_of -H "$AUTH" --data-binary "@${WORKDIR}/smoke.agent" "http://127.0.0.1:${PORT}/agents/..%2f..%2fetc/bundle")" != "200" ]] \
  || { echo "FAIL: traversal in the URL was accepted"; exit 1; }
[[ ! -e "${WORKDIR}/evil" ]] || { echo "FAIL: a refused bundle wrote outside the folder"; exit 1; }
curl -s "http://127.0.0.1:${PORT}/agents" | grep -q "\"digest\":\"${DIGEST}\"" \
  || { echo "FAIL: a refused bundle changed the loaded agent"; exit 1; }

echo "[7/9] POST execute (no API key -> stub echo)"
[[ "$(code_of -d '{}' "http://127.0.0.1:${PORT}/agents/smoke-agent/execute")" == "401" ]] \
  || { echo "FAIL: execute without the token was not refused"; exit 1; }
EXEC="$(curl -sS -H "$AUTH" -H "Content-Type: application/json" \
              -d '{"message":"hello-edge-c"}' \
              "http://127.0.0.1:${PORT}/agents/smoke-agent/execute")"
echo "  exec = $EXEC"
echo "$EXEC" | grep -q '"slug":"smoke-agent"' || { echo "FAIL: slug missing"; exit 1; }
echo "$EXEC" | grep -q '"echo":"hello-edge-c"' || { echo "FAIL: echo missing"; exit 1; }
echo "$EXEC" | grep -q '"duration_ms"' || { echo "FAIL: duration_ms missing"; exit 1; }
CODE="$(curl -sS -H "$AUTH" -d '{"message":"","params":{"code":"print(6*7)"}}' "http://127.0.0.1:${PORT}/agents/smoke-agent/execute")"
echo "$CODE" | grep -q 'code_executor is off' || { echo "FAIL: params.code ran without the flag: $CODE"; exit 1; }

echo "[8/9] restart, the saved bundle reloads with its real digest"
kill "$RUNTIME_PID"; wait "$RUNTIME_PID" 2>/dev/null
start_runtime EDGE_ENABLE_CODE_EXECUTOR=true ABENIX_TEST_SECRET=leak-me
curl -s "http://127.0.0.1:${PORT}/agents" | grep -q "\"digest\":\"${DIGEST}\"" \
  || { echo "FAIL: agent did not survive the restart"; exit 1; }

echo "[9/9] params.code with the flag, platform manifests list tools unindented"
CODE="$(curl -sS -H "$AUTH" -d '{"message":"","params":{"code":"print(6*7)"}}' "http://127.0.0.1:${PORT}/agents/smoke-agent/execute")"
echo "  code = $CODE"
echo "$CODE" | grep -q '"stdout":"42' || { echo "FAIL: code_executor did not run"; exit 1; }
ENVOUT="$(curl -sS -H "$AUTH" -d '{"message":"","params":{"code":"import os;print(sorted(os.environ));print(os.environ.get(\"ABENIX_TEST_SECRET\"))"}}' "http://127.0.0.1:${PORT}/agents/smoke-agent/execute")"
echo "  env = $ENVOUT"
echo "$ENVOUT" | grep -q 'leak-me\|EDGE_AUTH_TOKEN' && { echo "FAIL: the child saw the parent environment"; exit 1; }
START="$(date +%s)"
SLOW="$(curl -sS -H "$AUTH" -d '{"message":"","params":{"code":"import os,time\nif os.fork()==0:\n time.sleep(60)\nelse:\n time.sleep(60)\n"}}' "http://127.0.0.1:${PORT}/agents/smoke-agent/execute")"
echo "  slow = $SLOW"
echo "$SLOW" | grep -q 'code_executor_timeout' || { echo "FAIL: long code was not stopped"; exit 1; }
[[ $(( $(date +%s) - START )) -lt 10 ]] || { echo "FAIL: the time limit did not hold"; exit 1; }

echo
echo "PASS: edge-runtime-c smoke test"
