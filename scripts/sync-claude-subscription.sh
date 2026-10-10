#!/usr/bin/env bash
# sync-claude-subscription.sh — point the platform at the Claude subscription
# credential this machine already uses.
#
# Claude Code stores a rotating OAuth credential in ~/.claude/.credentials.json.
# The access token expires (typically within hours) and Claude Code mints a new
# one, revoking the old. A token pasted once into Admin -> LLM Settings therefore
# stops working with "OAuth access token has been revoked", which looks like a
# platform fault but is just a stale copy.
#
# Run this whenever agent calls start failing with an auth error. It reads the
# current access token and writes it into the platform setting. The token value
# is never printed.
#
# Usage:
#   bash scripts/sync-claude-subscription.sh
#   API_PORT=8100 bash scripts/sync-claude-subscription.sh
#   API_URL=http://localhost:8000 bash scripts/sync-claude-subscription.sh

set -euo pipefail

API_URL="${API_URL:-http://localhost:${API_PORT:-8000}}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@abenix.dev}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-Admin123456}"
CRED_FILE="${CLAUDE_CREDENTIALS_FILE:-${HOME}/.claude/.credentials.json}"

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${CYAN}[sync-sub]${NC} $1"; }
ok()   { echo -e "${GREEN}  [ok]${NC} $1"; }
warn() { echo -e "${YELLOW}  [warn]${NC} $1"; }
err()  { echo -e "${RED}  [err]${NC} $1" >&2; }

if [ ! -f "${CRED_FILE}" ]; then
  err "No credential file at ${CRED_FILE}"
  err "Sign in with Claude Code on this machine first, or set CLAUDE_CREDENTIALS_FILE."
  exit 1
fi

PY_BIN=""
for c in python3 python; do
  if "${c}" -c 'import sys' >/dev/null 2>&1; then PY_BIN="${c}"; break; fi
done
if [ -z "${PY_BIN}" ]; then
  err "Python 3 is needed to read the credential file, install it and re-run"
  exit 1
fi

log "Reading ${CRED_FILE}"
log "Platform API ${API_URL}"

# Everything that touches the token stays inside python so it never reaches the
# shell's argv, environment, or this script's output.
PYTHONIOENCODING=utf-8 "${PY_BIN}" - "${CRED_FILE}" "${API_URL}" "${ADMIN_EMAIL}" "${ADMIN_PASSWORD}" <<'PY'
import datetime
import io
import json
import sys
import urllib.error
import urllib.request

cred_file, api_url, email, password = sys.argv[1:5]

with io.open(cred_file, encoding="utf-8") as fh:
    cred = json.load(fh)

oauth = cred.get("claudeAiOauth") or {}
token = (oauth.get("accessToken") or "").strip()
if not token:
    print("  [err] no claudeAiOauth.accessToken in the credential file", file=sys.stderr)
    raise SystemExit(1)

expires_at = oauth.get("expiresAt")
if expires_at:
    ts = int(expires_at)
    when = datetime.datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts)
    left = when - datetime.datetime.now()
    if left.total_seconds() <= 0:
        print(f"  [warn] this access token expired at {when} — open Claude Code to refresh it")
    else:
        mins = int(left.total_seconds() // 60)
        print(f"  [ok] token valid for another {mins} min (until {when:%Y-%m-%d %H:%M})")

sub_type = oauth.get("subscriptionType") or "unknown"
print(f"  [ok] subscription type: {sub_type}")


def call(path, payload=None, method=None, bearer=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {}
    if data:
        headers["Content-Type"] = "application/json"
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(f"{api_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"error": {"message": raw[:300]}}


try:
    status, body = call("/api/auth/login", {"email": email, "password": password})
except urllib.error.URLError as e:
    print(f"  [err] cannot reach the platform at {api_url}: {e.reason}", file=sys.stderr)
    print("  [err] is the deploy finished and the API forward up? Try: bash scripts/deploy.sh forwards", file=sys.stderr)
    raise SystemExit(1)
if status != 200:
    print(f"  [err] platform login failed: HTTP {status}", file=sys.stderr)
    raise SystemExit(1)
jwt = (body.get("data") or body).get("access_token")

# Write the token, then make sure subscription mode is actually on.
status, body = call(
    "/api/admin/settings/llm.subscription.token", {"value": token}, method="PATCH", bearer=jwt
)
if status != 200:
    msg = (body.get("error") or {}).get("message", body)
    print(f"  [err] could not store token: HTTP {status} {msg}", file=sys.stderr)
    raise SystemExit(1)
print("  [ok] token stored in llm.subscription.token")

status, body = call(
    "/api/admin/settings/llm.subscription.enabled", {"value": "true"}, method="PATCH", bearer=jwt
)
print(f"  [ok] subscription mode enabled (HTTP {status})")

# Prove it end to end rather than assuming the write was enough.
status, body = call("/api/admin/settings/subscription/verify", {}, bearer=jwt)
if status == 200:
    print("  [ok] verify passed — the platform can reach Anthropic with this token")
else:
    msg = (body.get("error") or {}).get("message", body)
    print(f"  [err] verify FAILED: HTTP {status} {msg}", file=sys.stderr)
    raise SystemExit(1)
PY

ok "Subscription credential synced"
warn "Re-run this after Claude Code rotates the token (auth errors on agent runs are the signal)."
