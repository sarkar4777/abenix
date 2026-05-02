#!/usr/bin/env bash
# seed-standalone-keys.sh — idempotent ABENIX_API_KEY seeding for standalone apps
#
# For each standalone (example_app, sauditourism, industrial-iot, resolveai,
# claimsiq) this script:
#   1) Reads the existing key from <app>-secrets in the cluster.
#   2) Validates the key still exists in the platform's api_keys table and
#      is active. If yes, leaves it alone.
#   3) Otherwise mints a fresh can_delegate-scoped key for the platform admin
#      user, deactivates any prior key with the same logical name, persists
#      the new hash to api_keys, and patches the secret with the raw key.
#   4) Restarts the standalone deployment so the new key is picked up.
#
# Usage:
#   bash scripts/seed-standalone-keys.sh                # seed all 5 apps
#   bash scripts/seed-standalone-keys.sh example_app     # one app only
#
# Requirements: kubectl context already targets the cluster, abenix-api pod
# is Ready, and the namespace env-var matches deploy-azure.sh (default: abenix).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${NAMESPACE:-abenix}"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${CYAN}[seed-keys]${NC} $1"; }
ok()   { echo -e "${GREEN}  [ok]${NC} $1"; }
warn() { echo -e "${YELLOW}  [warn]${NC} $1"; }
err()  { echo -e "${RED}  [err]${NC} $1" >&2; }
step() { echo -e "\n${BOLD}▶ $1${NC}"; }

# Standalone definitions: app|secret|env_var|key_name|deployment(s)
APPS=(
  "example_app|example_app-secrets|EXAMPLE_APP_ABENIX_API_KEY|standalone-example_app|example_app-api,example_app-web"
  "sauditourism|sauditourism-secrets|SAUDITOURISM_ABENIX_API_KEY|standalone-sauditourism|sauditourism-api,sauditourism-web"
  "industrial-iot|industrial-iot-secrets|INDUSTRIALIOT_ABENIX_API_KEY|standalone-industrial-iot|industrial-iot-api,industrial-iot-web"
  "resolveai|resolveai-secrets|RESOLVEAI_ABENIX_API_KEY|standalone-resolveai|resolveai-api,resolveai-web"
  "claimsiq|claimsiq-secrets|CLAIMSIQ_ABENIX_API_KEY|standalone-claimsiq|claimsiq"
)

ONLY_APP="${1:-}"

_get_api_pod() {
  kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/name=api" \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}

# Run a python one-liner inside the api pod that:
#   - checks if the given raw key exists+active in api_keys (returns "VALID")
#   - if not, mints a new key under name=<key_name>, deactivates older keys
#     with the same name, and prints the new raw key on stdout (last line).
# Args: $1 = current_raw_key (may be empty), $2 = key_name
_validate_or_mint() {
  local current_raw="$1" key_name="$2" api_pod
  api_pod=$(_get_api_pod)
  if [ -z "${api_pod}" ]; then
    err "  No ready abenix-api pod — cannot mint key"
    return 1
  fi

  # Run with stdin so the raw key never appears in `ps` listings or shell history
  printf '%s\n%s\n' "${current_raw}" "${key_name}" | \
    kubectl exec -n "${NAMESPACE}" -i "${api_pod}" -c api -- python -c "
import asyncio, hashlib, os, secrets, sys
sys.path.insert(0, '/app/packages/db')
from datetime import datetime, timezone
from models.api_key import ApiKey
from models.user import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

raw = sys.stdin.readline().strip()
name = sys.stdin.readline().strip()

async def run():
    eng = create_async_engine(os.environ['DATABASE_URL'], echo=False)
    sf = async_sessionmaker(eng, expire_on_commit=False)
    async with sf() as db:
        # Resolve the platform admin user — owner of every minted key
        u = (await db.execute(
            select(User).where(User.email.in_(['admin@abenix.dev','system@abenix.dev']))
            .order_by(User.email.desc())
        )).scalars().first()
        if u is None:
            print('NO_ADMIN', file=sys.stderr); sys.exit(2)

        reuse = False
        if raw and raw.startswith('af_'):
            h = hashlib.sha256(raw.encode()).hexdigest()
            row = (await db.execute(
                select(ApiKey).where(ApiKey.key_hash == h, ApiKey.is_active.is_(True))
            )).scalar_one_or_none()
            if row is not None:
                # Make sure it has can_delegate scope; if a legacy key was minted
                # without it, upgrade in place rather than rotating.
                sc = row.scopes or {}
                actions = (sc.get('allowed_actions') or []) if isinstance(sc, dict) else []
                if 'can_delegate' not in actions:
                    actions = list(set(list(actions) + ['can_delegate', 'execute', 'list']))
                    row.scopes = {'allowed_actions': actions}
                    await db.commit()
                # Tag the name for traceability if it lacks one
                if not row.name or row.name in ('platform-bootstrap', 'platform-key'):
                    row.name = name
                    await db.commit()
                reuse = True

        if reuse:
            print('REUSED', flush=True)
            print(raw, flush=True)
        else:
            # Deactivate any prior keys with this name (rotation)
            old = (await db.execute(
                select(ApiKey).where(ApiKey.name == name, ApiKey.is_active.is_(True))
            )).scalars().all()
            for k in old:
                k.is_active = False
            new_raw = 'af_' + secrets.token_urlsafe(40)
            ak = ApiKey(
                user_id=u.id,
                tenant_id=u.tenant_id,
                name=name,
                key_prefix=new_raw[:8] + '****' + new_raw[-4:],
                key_hash=hashlib.sha256(new_raw.encode()).hexdigest(),
                scopes={'allowed_actions': ['can_delegate', 'execute', 'list', 'read']},
                is_active=True,
            )
            db.add(ak)
            await db.commit()
            print('MINTED', flush=True)
            print(new_raw, flush=True)
    await eng.dispose()

asyncio.run(run())
" 2>/dev/null
}

_seed_one() {
  local spec="$1"
  IFS='|' read -r app secret env_var key_name deploys <<< "${spec}"

  step "Seeding ${app}"

  # Existence guard — the secret should already exist; if not, the standalone
  # has not been deployed yet so skip with a warning rather than failing.
  if ! kubectl get secret -n "${NAMESPACE}" "${secret}" >/dev/null 2>&1; then
    warn "  Secret ${secret} not found — run deploy first; skipping ${app}"
    return 0
  fi

  local current
  current=$(kubectl get secret -n "${NAMESPACE}" "${secret}" \
    -o jsonpath="{.data.${env_var}}" 2>/dev/null | base64 -d 2>/dev/null || true)

  local result
  result=$(_validate_or_mint "${current}" "${key_name}" || true)
  local status raw
  status=$(echo "${result}" | head -1)
  raw=$(echo "${result}" | tail -1)

  if [ "${status}" = "REUSED" ]; then
    ok "  Existing key valid (prefix ${raw:0:10}…) — reuse"
    return 0
  fi

  if [ "${status}" != "MINTED" ] || [ -z "${raw}" ] || [[ "${raw}" != af_* ]]; then
    err "  Could not mint key for ${app} (status=${status:-<empty>})"
    return 1
  fi

  ok "  Minted fresh key (prefix ${raw:0:10}…)"

  # Patch the secret in-place — keeps any other keys (JWT, ANTHROPIC) intact.
  local b64
  b64=$(printf '%s' "${raw}" | base64 -w0 2>/dev/null || printf '%s' "${raw}" | base64 | tr -d '\n')
  kubectl patch secret -n "${NAMESPACE}" "${secret}" --type=json \
    -p="[{\"op\":\"add\",\"path\":\"/data/${env_var}\",\"value\":\"${b64}\"}]" >/dev/null
  ok "  Patched ${secret}.${env_var}"

  # Restart the affected deployments so the new env propagates.
  IFS=',' read -ra dps <<< "${deploys}"
  for dp in "${dps[@]}"; do
    if kubectl get deploy -n "${NAMESPACE}" "${dp}" >/dev/null 2>&1; then
      kubectl rollout restart -n "${NAMESPACE}" "deploy/${dp}" >/dev/null 2>&1 || true
      ok "  Restarted deploy/${dp}"
    fi
  done
}

main() {
  step "Standalone API-key seed (namespace=${NAMESPACE})"

  # Wait briefly for the api pod (deploy-azure.sh's seed_agents already does
  # this, but if this script is run standalone we want the same guard).
  local api_pod=""
  for i in $(seq 1 20); do
    api_pod=$(_get_api_pod)
    [ -n "${api_pod}" ] && break
    sleep 3
  done
  if [ -z "${api_pod}" ]; then
    err "abenix-api pod is not Ready — cannot seed keys"
    exit 1
  fi

  for spec in "${APPS[@]}"; do
    IFS='|' read -r app rest <<< "${spec}"
    if [ -n "${ONLY_APP}" ] && [ "${ONLY_APP}" != "${app}" ]; then
      continue
    fi
    _seed_one "${spec}" || warn "${app}: seed failed (continuing)"
  done

  ok "Standalone key seeding complete"
}

main "$@"
