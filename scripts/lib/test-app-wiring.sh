#!/usr/bin/env bash
# Prove the selector is wired into both startup scripts, not just that the
# selector itself parses. The unit tests in test-select-apps.sh cover the
# parsing; this covers the integration, which is where it actually broke:
# ContractIQ kept its own hardcoded start block and ran whatever the operator
# chose, and PharmaVigil was in the registry with no start.sh to call.
#
#   bash scripts/lib/test-app-wiring.sh
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

check() {
  printf '  %-34s ' "$1"
  if [ "$2" = "$3" ]; then echo "ok"; else echo "FAIL  expected [$2] got [$3]"; FAILED=1; fi
}
FAILED=0

# ── deploy.sh: which deploy_* would run for a given APPS value ────────────
deploy_for() {
  APPS="$1" bash -c '
    source scripts/lib/select-apps.sh
    select_apps
    out=""
    for k in contractiq mideasttourism industrial-iot resolveai wingman pharmavigil claimsiq; do
      app_selected "$k" && out="$out $k"
    done
    echo "${out# }"
  '
}

echo "deploy.sh / dev-local.sh selection"
check "APPS=none -> nothing"        ""                          "$(deploy_for none)"
check "APPS=pharmavigil -> one"     "pharmavigil"               "$(deploy_for pharmavigil)"
check "APPS=7,5 -> two by number"   "pharmavigil claimsiq"      "$(deploy_for 7,5)"
check "APPS=all -> every app"       "contractiq mideasttourism industrial-iot resolveai wingman pharmavigil claimsiq" "$(deploy_for all)"

# ── the guard lines really exist in deploy.sh ────────────────────────────
echo ""
echo "wiring present in the scripts"
check "deploy.sh guards every app" "7" \
  "$(grep -cE '^  app_selected [a-z-]+ +&& \{ deploy_' scripts/deploy.sh)"
check "deploy.sh calls select_apps" "1" \
  "$(grep -c '^  select_apps$' scripts/deploy.sh)"
check "dev-local.sh calls select_apps" "1" \
  "$(grep -c '^select_apps$' scripts/dev-local.sh)"
check "dev-local.sh loops the registry" "2" \
  "$(grep -c 'for _app_i in "\${!APP_REGISTRY\[@\]}"; do' scripts/dev-local.sh | head -1)"
check "no hardcoded app start blocks left" "0" \
  "$(grep -cE 'bash "\$ROOT_DIR/(contractiq|wingman|resolveai|claimsiq|mideasttourism|industrial-iot)/start.sh"' scripts/dev-local.sh)"

# ── every registry app has the pieces a deploy needs ─────────────────────
echo ""
echo "registry integrity"
source scripts/lib/select-apps.sh
missing=""
for i in "${!APP_REGISTRY[@]}"; do
  d="$(app_dir "$i")"
  [ -f "$d/start.sh" ] || missing="$missing ${d}:start.sh"
  [ -d "$d/k8s" ] || missing="$missing ${d}:k8s"
done
check "every app has start.sh + k8s/" "" "${missing# }"

echo ""
[ "$FAILED" -eq 0 ] && echo "integration verified" || echo "INTEGRATION PROBLEMS"
exit "$FAILED"
