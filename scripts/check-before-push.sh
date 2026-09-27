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

PY_BLACK_PIN="black==24.8.0"
PY_RUFF_PIN="ruff==0.6.9"

ensure_pinned() {
  # CI installs these exact versions — match locally so green here = green CI.
  local current_black current_ruff
  current_black=$(python -m black --version 2>/dev/null | awk '{print $3}' || true)
  current_ruff=$(python -m ruff --version 2>/dev/null | awk '{print $2}' || true)
  if [ "$current_black" != "24.8.0" ] || [ "$current_ruff" != "0.6.9" ]; then
    say "Pinning toolchain to CI versions ($PY_BLACK_PIN, $PY_RUFF_PIN)"
    python -m pip install --quiet "$PY_BLACK_PIN" "$PY_RUFF_PIN"
  fi
}

run_python() {
  ensure_pinned

  say "Python: black --check (24.8.0)"
  python -m black --check apps/api apps/agent-runtime apps/worker packages/db
  ok "black"

  say "Python: ruff (0.6.9)"
  python -m ruff check apps/api apps/agent-runtime apps/worker packages/db
  ok "ruff"

  say "Python: pytest tests/unit/"
  python -m pytest tests/unit/ -q --tb=short
  ok "pytest"

  say "Python: agent seed lint"
  python scripts/lint-agent-seeds.py
  ok "agent seeds"

  say "Docs: README images exist and are tracked"
  python scripts/check-readme-images.py
  ok "readme images"

  # Each standalone app keeps its own suite under <app>/api/tests. Nothing ran
  # them — not CI, not this script — so they could rot unnoticed. They are
  # cheap (no cluster, under a second each) so there is no reason to skip them.
  for _app in contractiq resolveai wingman industrial-iot mideasttourism pharmavigil; do
    if compgen -G "${_app}/api/tests/test_*.py" > /dev/null 2>&1; then
      say "Python: ${_app}/api tests"
      ( cd "${_app}/api" && python -m pytest tests/ -q --tb=short )
      ok "${_app} tests"
    fi
  done

  if [ -f apps/api/requirements.txt ]; then
    say "Python: pip-audit (with .pip-audit-ignore)"
    python -m pip install --quiet pip-audit
    local ignore_args=""
    if [ -f .pip-audit-ignore ]; then
      while IFS= read -r line; do
        line="${line%%#*}"
        line="$(echo "$line" | tr -d '[:space:]')"
        [ -n "$line" ] && ignore_args="$ignore_args --ignore-vuln $line"
      done < .pip-audit-ignore
    fi
    python -m pip_audit -r apps/api/requirements.txt $ignore_args
    ok "pip-audit"
  fi
}

run_web() {
  say "Web: eslint"
  npm run lint
  ok "eslint"

  say "Web: tsc --noEmit"
  ( cd apps/web && npx tsc --noEmit )
  ok "tsc"

  say "Web: vitest"
  npm test
  ok "vitest"

  if [ "$FAST" -eq 0 ]; then
    say "Web: next build"
    ( cd apps/web && NEXT_TELEMETRY_DISABLED=1 npm run build )
    ok "next build"
  else
    say "Web: skipping next build (--fast)"
  fi

  if [ -f scripts/validate-mermaid.mjs ]; then
    say "Docs: mermaid syntax"
    node scripts/validate-mermaid.mjs
    ok "mermaid"
  fi

  # The in-app developer guide serves a copy of docs/ from public/, and nothing
  # kept the two in step — the mirror had fallen six files behind. Sync, then
  # check the manifest that drives the nav resolves both ways.
  if [ -f scripts/sync-dev-docs.sh ]; then
    say "Docs: in-app mirror + nav manifest"
    bash scripts/sync-dev-docs.sh >/dev/null
    python - <<'PY'
import json, pathlib, sys
man = json.loads(pathlib.Path("docs/manifest.json").read_text(encoding="utf-8"))
listed = {d["slug"] for s in man["sections"] for d in s["docs"]}
on_disk = {str(p.relative_to("docs")).replace("\\", "/")[:-3]
           for p in pathlib.Path("docs").rglob("*.md")} - {"TRAJECTORY_MEMORY"}
ghosts = sorted(s for s in listed if not (pathlib.Path("docs") / f"{s}.md").exists())
orphans = sorted(d for d in on_disk - listed if not d.startswith("screenshots/"))
for g in ghosts:
    print(f"  nav entry has no file: {g}")
for o in orphans:
    print(f"  doc missing from nav : {o}")
sys.exit(1 if ghosts or orphans else 0)
PY
    ok "dev-docs in sync"
  fi
}

echo -e "${B}check-before-push${N} — running the same gates CI will"
echo

START=$SECONDS
if [ "$WEB_ONLY" -eq 0 ]; then run_python; fi
if [ "$PY_ONLY" -eq 0 ]; then run_web; fi

echo
ok "$(( SECONDS - START ))s — clean. Safe to push."
