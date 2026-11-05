#!/usr/bin/env bash
# smoke test — boot the C runtime, push a sample bundle over HTTP, hit /execute.
# stub platform = python -m http.server (we don't actually verify register).
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &> /dev/null && pwd)"
BIN="${ROOT}/build/release/edge-runtime-c"
PORT="${PORT:-18080}"
STUB_PORT="${STUB_PORT:-18000}"
WORKDIR="$(mktemp -d)"
trap 'set +e; [[ -n "${RUNTIME_PID:-}" ]] && kill "$RUNTIME_PID" 2>/dev/null; [[ -n "${STUB_PID:-}" ]] && kill "$STUB_PID" 2>/dev/null; rm -rf "$WORKDIR"' EXIT

if [[ ! -x "$BIN" ]]; then
  echo "binary not built at $BIN — run 'make release' first" >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 required for bundle generation + stub server" >&2
  exit 2
fi

echo "[1/6] generate signing keypair + sample bundle"
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

manifest = """name: Smoke Agent
slug: smoke-agent
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

# build the bundle with a placeholder sig of the correct size, then sign the
# byte-stripped form (matches what edge-runtime-c verifies — see bundle.c).
SIG_LEN = 256  # rsa 2048 bit signature length
mtime = int(time.time())

def build(sig_bytes):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for name, data in [("agent.yaml", manifest.encode()),
                           ("system_prompt.md", prompt)]:
            info = tarfile.TarInfo(name=name)
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

# build with placeholder sig so layout is final, then sign the stripped form.
placeholder = build(b"\x00" * SIG_LEN)
to_sign = strip_sig(placeholder)
sig = key.sign(
    to_sign,
    padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
    hashes.SHA256(),
)
final = build(sig)
with open(os.path.join(workdir, "smoke.agent"), "wb") as f:
    f.write(final)
print(f"bundle size = {len(final)} bytes")
PY
test_rc=$?
if [[ $test_rc -ne 0 ]]; then
  echo "bundle generation failed" >&2
  exit 1
fi

echo "[2/6] start stub platform on :${STUB_PORT}"
( cd "$WORKDIR" && python3 -m http.server "$STUB_PORT" >/dev/null 2>&1 ) &
STUB_PID=$!

echo "[3/6] start runtime on :${PORT}"
GATEWAY_ID="smoke-c" \
  PORT="$PORT" \
  PLATFORM_URL="http://127.0.0.1:${STUB_PORT}" \
  PLATFORM_TOKEN="" \
  MQTT_URL="" \
  SIGNING_PUBKEY_PATH="${WORKDIR}/signing_pub.pem" \
  BUNDLE_DIR="${WORKDIR}/agents" \
  ANTHROPIC_API_KEY="" \
  "$BIN" &
RUNTIME_PID=$!

echo "[4/6] wait for /health"
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    break
  fi
  sleep 0.2
done
HEALTH="$(curl -s "http://127.0.0.1:${PORT}/health" || true)"
echo "  health = $HEALTH"
echo "$HEALTH" | grep -q '"status":"ok"' || { echo "FAIL: /health"; exit 1; }
echo "$HEALTH" | grep -q '"gateway_id":"smoke-c"' || { echo "FAIL: gateway_id"; exit 1; }

echo "[5/6] POST bundle"
PUT="$(curl -sS --data-binary "@${WORKDIR}/smoke.agent" \
            -H "Content-Type: application/x-tar" \
            "http://127.0.0.1:${PORT}/agents/smoke-agent/bundle")"
echo "  put = $PUT"
echo "$PUT" | grep -q '"slug":"smoke-agent"' || { echo "FAIL: bundle install"; exit 1; }

LIST="$(curl -s "http://127.0.0.1:${PORT}/agents")"
echo "  list = $LIST"
echo "$LIST" | grep -q '"slug":"smoke-agent"' || { echo "FAIL: agent not registered"; exit 1; }

echo "[6/6] POST execute (no API key -> stub echo)"
EXEC="$(curl -sS -H "Content-Type: application/json" \
              -d '{"message":"hello-edge-c"}' \
              "http://127.0.0.1:${PORT}/agents/smoke-agent/execute")"
echo "  exec = $EXEC"
echo "$EXEC" | grep -q '"slug":"smoke-agent"' || { echo "FAIL: slug missing"; exit 1; }
echo "$EXEC" | grep -q '"echo":"hello-edge-c"' || { echo "FAIL: echo missing"; exit 1; }
echo "$EXEC" | grep -q '"duration_ms"' || { echo "FAIL: duration_ms missing"; exit 1; }

echo "[7/7] POST execute with params.code (platform manifests list tools unindented)"
CODE="$(curl -sS -H "Content-Type: application/json"               -d '{"message":"","params":{"code":"print(6*7)"}}'               "http://127.0.0.1:${PORT}/agents/smoke-agent/execute")"
echo "  code = $CODE"
echo "$CODE" | grep -q '"stdout":"42' || { echo "FAIL: code_executor did not run"; exit 1; }

echo
echo "PASS: edge-runtime-c smoke test"
