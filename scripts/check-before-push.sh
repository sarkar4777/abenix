#!/usr/bin/env bash
# Run the exact gates CI runs, locally. Use this before `git push` —
# it's faster to find a problem here than wait for CI to red.
#
# Usage:
#   bash scripts/check-before-push.sh            # full
#   bash scripts/check-before-push.sh --fast     # skip web build (slow)
#   bash scripts/check-before-push.sh --python   # only python gates
#   bash scripts/check-before-push.sh --web      # only web gates

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; C='\033[0;36m'; B='\033[1m'; N='\033[0m'
say()  { echo -e "${C}▸${N} $1"; }
ok()   { echo -e "${G}✓${N} $1"; }
fail() { echo -e "${R}✗${N} $1" >&2; }

FAST=0
PY_ONLY=0
WEB_ONLY=0
for a in "$@"; do
  case "$a" in
    --fast)   FAST=1 ;;
    --python) PY_ONLY=1 ;;
    --web)    WEB_ONLY=1 ;;
    -h|--help)
      grep -E '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) fail "Unknown flag: $a"; exit 2 ;;
  esac
done

run_python() {
  say "Python: black --check"
  black --check apps/api apps/agent-runtime apps/worker packages/db
  ok "black"

  say "Python: ruff"
  ruff check apps/api apps/agent-runtime apps/worker packages/db
  ok "ruff"

  say "Python: pytest tests/unit/"
  pytest tests/unit/ -q --tb=short
  ok "pytest"
}

run_web() {
  say "Web: eslint"
  npm run lint
  ok "eslint"

  say "Web: tsc --noEmit"
  ( cd apps/web && npx tsc --noEmit )
  ok "tsc"

  if [ "$FAST" -eq 0 ]; then
    say "Web: next build"
    ( cd apps/web && NEXT_TELEMETRY_DISABLED=1 npm run build )
    ok "next build"
  else
    say "Web: skipping next build (--fast)"
  fi
}

echo -e "${B}check-before-push${N} — running the same gates CI will"
echo

START=$SECONDS
if [ "$WEB_ONLY" -eq 0 ]; then run_python; fi
if [ "$PY_ONLY" -eq 0 ]; then run_web; fi

echo
ok "$(( SECONDS - START ))s — clean. Safe to push."
