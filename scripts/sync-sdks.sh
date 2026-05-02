#!/usr/bin/env bash
# sync-sdks.sh — keep all 6 copies of the Abenix Python SDK aligned.
#
# Canonical source:
#   packages/sdk/python/abenix_sdk/
#
# Destinations (per-app embedded copies — must NEVER be edited directly):
#   packages/agent-sdk/abenix_sdk/
#   example_app/api/sdk/abenix_sdk/
#   industrial-iot/api/sdk/abenix_sdk/
#   resolveai/api/sdk/abenix_sdk/
#   sauditourism/api/sdk/abenix_sdk/
#
# Why: the SDK is vendored into each standalone app's Docker image so the
# images don't depend on a published wheel. A sync script + hash-based
# drift check keeps these honest. CI calls `--check`; humans call it
# without args (or with `--write`) to actually copy.
#
# Usage:
#   bash scripts/sync-sdks.sh              # copy canonical → destinations, fail on drift
#   bash scripts/sync-sdks.sh --check      # verify only, exit non-zero on drift
#   bash scripts/sync-sdks.sh --write      # alias of default
#
# Exit codes:
#   0 — all in sync
#   1 — drift (or post-copy hash mismatch, e.g. write-protected file)
#   2 — bad usage / canonical missing
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CANONICAL="${ROOT_DIR}/packages/sdk/python/abenix_sdk"

DESTINATIONS=(
  "${ROOT_DIR}/packages/agent-sdk/abenix_sdk"
  "${ROOT_DIR}/example_app/api/sdk/abenix_sdk"
  "${ROOT_DIR}/industrial-iot/api/sdk/abenix_sdk"
  "${ROOT_DIR}/resolveai/api/sdk/abenix_sdk"
  "${ROOT_DIR}/sauditourism/api/sdk/abenix_sdk"
)

# ── colors ────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; N='\033[0m'
else
  R=''; G=''; Y=''; C=''; N=''
fi
log()  { printf "%b\n" "${C}[sync-sdks]${N} $*"; }
ok()   { printf "%b\n" "  ${G}✓${N} $*"; }
warn() { printf "%b\n" "  ${Y}!${N} $*"; }
err()  { printf "%b\n" "  ${R}✗${N} $*" >&2; }

MODE="write"
case "${1:-}" in
  --check) MODE="check" ;;
  --write|"") MODE="write" ;;
  -h|--help)
    sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *)
    err "Unknown arg: $1 (use --check or --write)"
    exit 2
    ;;
esac

if [ ! -d "${CANONICAL}" ]; then
  err "Canonical SDK missing: ${CANONICAL}"
  exit 2
fi

# Pick a python — most repos have python3, on Windows-msys often `python`.
PYBIN=""
for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1; then PYBIN="$c"; break; fi
done
if [ -z "${PYBIN}" ]; then
  err "No python interpreter found (need python3/python/py for hashing)"
  exit 2
fi

# Inline Python hasher: deterministic sha256 over (rel-path | content)
# across all non-pycache files. Works on Linux, macOS, and msys.
read -r -d '' HASH_SCRIPT <<'PYHASH' || true
import hashlib, os, sys
root = sys.argv[1]
if not os.path.isdir(root):
    print("MISSING"); sys.exit(0)
files = []
for dp, dns, fns in os.walk(root):
    if "__pycache__" in dp.split(os.sep):
        continue
    for fn in fns:
        if fn.endswith((".pyc", ".pyo")):
            continue
        rel = os.path.relpath(os.path.join(dp, fn), root).replace(os.sep, "/")
        files.append(rel)
files.sort()
h = hashlib.sha256()
for rel in files:
    with open(os.path.join(root, rel), "rb") as f:
        body = f.read()
    h.update(rel.encode())
    h.update(b"\0")
    h.update(body)
    h.update(b"\0\0")
print(h.hexdigest())
PYHASH

hash_dir() {
  "${PYBIN}" -c "${HASH_SCRIPT}" "$1" 2>/dev/null || echo "ERR"
}

CANON_HASH=$(hash_dir "${CANONICAL}")
log "Canonical hash: ${CANON_HASH}  (${CANONICAL#${ROOT_DIR}/})"

drift_files=()
for dest in "${DESTINATIONS[@]}"; do
  d_hash=$(hash_dir "${dest}")
  rel="${dest#${ROOT_DIR}/}"
  if [ "${d_hash}" = "${CANON_HASH}" ]; then
    ok "in sync: ${rel}"
  else
    drift_files+=("${rel}")
    if [ "${MODE}" = "check" ]; then
      err "drift:   ${rel}  (hash=${d_hash})"
    else
      warn "drift:   ${rel}  → copying canonical"
    fi
  fi
done

if [ "${MODE}" = "check" ]; then
  if [ ${#drift_files[@]} -ne 0 ]; then
    err "${#drift_files[@]} SDK copy(ies) out of sync. Run: bash scripts/sync-sdks.sh"
    for f in "${drift_files[@]}"; do err "  - ${f}"; done
    exit 1
  fi
  ok "All ${#DESTINATIONS[@]} SDK copies in sync with canonical."
  exit 0
fi

# WRITE MODE — copy canonical → drifted destinations.
copies_done=0
for dest in "${DESTINATIONS[@]}"; do
  rel="${dest#${ROOT_DIR}/}"
  d_hash=$(hash_dir "${dest}")
  if [ "${d_hash}" = "${CANON_HASH}" ]; then
    continue
  fi
  parent="$(dirname "${dest}")"
  mkdir -p "${parent}"
  # Wipe and copy. Don't try to delta-update — these are tiny dirs.
  rm -rf "${dest}"
  if ! cp -R "${CANONICAL}" "${dest}"; then
    err "cp failed for ${rel} (likely write-protected). Aborting."
    exit 1
  fi
  # Strip __pycache__ that some tooling pre-creates
  find "${dest}" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
  ok "copied → ${rel}"
  copies_done=$((copies_done + 1))
done

# Re-hash everything; fail loud if anything still differs (write-protected,
# stale __pycache__ that re-spawned, race with another tool, etc.).
post_drift=()
for dest in "${DESTINATIONS[@]}"; do
  d_hash=$(hash_dir "${dest}")
  rel="${dest#${ROOT_DIR}/}"
  if [ "${d_hash}" != "${CANON_HASH}" ]; then
    post_drift+=("${rel}")
    err "POST-COPY drift: ${rel}  (hash=${d_hash} != ${CANON_HASH})"
  fi
done

if [ ${#post_drift[@]} -ne 0 ]; then
  err "Sync FAILED — ${#post_drift[@]} dest(s) still differ after copy."
  err "Most likely cause: a destination has a write-protected file."
  exit 1
fi

if [ "${copies_done}" -eq 0 ]; then
  ok "Idempotent run — nothing to do (all ${#DESTINATIONS[@]} copies already in sync)."
else
  ok "Synced ${copies_done} destination(s); all ${#DESTINATIONS[@]} now match canonical."
fi
exit 0
