#!/usr/bin/env bash
# Unit tests for the app selector. No cluster, no docker, runs in a second.
#
#   bash scripts/lib/test-select-apps.sh
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT_DIR}/scripts/lib/select-apps.sh"

PASS=0
FAIL=0

check() { # check <name> <expected> <actual>
  if [ "$2" = "$3" ]; then
    printf '  ok   %s\n' "$1"
    PASS=$((PASS + 1))
  else
    printf '  FAIL %s\n       expected: %s\n       actual:   %s\n' "$1" "$2" "$3"
    FAIL=$((FAIL + 1))
  fi
}

joined() { parse_app_selection "$1" 2>/dev/null | tr '\n' ' ' | sed 's/ $//'; }

ALL="contractiq mideasttourism industrial-iot resolveai claimsiq wingman pharmavigil"

echo "parse_app_selection"
check "empty means all"            "${ALL}" "$(joined '')"
check "all means all"              "${ALL}" "$(joined 'all')"
check "ALL is case insensitive"    "${ALL}" "$(joined 'ALL')"
check "none means none"            ""       "$(joined 'none')"
check "zero means none"            ""       "$(joined '0')"
check "single key"                 "pharmavigil" "$(joined 'pharmavigil')"
check "two keys"                   "pharmavigil claimsiq" "$(joined 'pharmavigil,claimsiq')"
check "spaces are tolerated"       "pharmavigil claimsiq" "$(joined ' pharmavigil , claimsiq ')"
check "numbers select by position" "contractiq industrial-iot" "$(joined '1,3')"
check "last number"                "pharmavigil" "$(joined '7')"
check "mixed keys and numbers"     "contractiq pharmavigil" "$(joined '1,pharmavigil')"
check "unknown token is skipped"   "pharmavigil" "$(joined 'nosuchapp,pharmavigil')"
check "out-of-range number skipped" ""         "$(joined '99')"
check "case insensitive key"       "pharmavigil" "$(joined 'PharmaVigil')"

echo ""
echo "select_apps precedence"
APPS=none;        select_apps; check "APPS=none wins"   "" "${SELECTED_APPS[*]-}"
APPS=pharmavigil; select_apps; check "APPS=key wins"    "pharmavigil" "${SELECTED_APPS[*]-}"
APPS=all;         select_apps; check "APPS=all wins"    "${ALL}" "${SELECTED_APPS[*]-}"
APPS="";          select_apps; check "APPS= means none" "" "${SELECTED_APPS[*]-}"
# Not a terminal here, so it must fall through to all rather than block.
unset APPS;       select_apps; check "non-interactive means all" "${ALL}" "${SELECTED_APPS[*]-}"

echo ""
echo "interactive prompt"
# Git Bash on Windows gives no pty, so the prompt branch is reached through
# APP_SELECT_FORCE_PROMPT. Everything past that point is the real code path.
ask() { # ask <answer>
  printf '%s
' "$1" | APP_SELECT_FORCE_PROMPT=1 APP_SELECT_TIMEOUT=3     bash "${ROOT_DIR}/scripts/lib/_ask_once.sh" 2>/dev/null
}
check "prompt: numbers"      "contractiq pharmavigil" "$(ask '1,7')"
check "prompt: none"         ""                       "$(ask 'none')"
check "prompt: by name"      "pharmavigil"            "$(ask 'pharmavigil')"
check "prompt: bare Enter"   "${ALL}"                 "$(ask '')"
# Closed stdin makes read fail immediately, which is the timeout path.
check "prompt: no answer"    "${ALL}"   "$(APP_SELECT_FORCE_PROMPT=1 APP_SELECT_TIMEOUT=2 bash "${ROOT_DIR}/scripts/lib/_ask_once.sh" </dev/null 2>/dev/null)"

echo ""
echo "registry"
check "every app has five fields" "yes" \
  "$(for i in "${!APP_REGISTRY[@]}"; do
       [ "$(echo "${APP_REGISTRY[$i]}" | awk -F'|' '{print NF}')" -eq 5 ] || { echo no; exit; }
     done; echo yes)"
check "every app dir exists" "yes" \
  "$(for i in "${!APP_REGISTRY[@]}"; do
       [ -d "${ROOT_DIR}/$(app_dir "$i")" ] || { echo "no:$(app_dir "$i")"; exit; }
     done; echo yes)"
check "app_selected finds a chosen key" "found" \
  "$(SELECTED_APPS=(wingman pharmavigil); app_selected pharmavigil && echo found || echo missing)"
check "app_selected rejects an unchosen key" "missing" \
  "$(SELECTED_APPS=(wingman); app_selected pharmavigil && echo found || echo missing)"

echo ""
echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
