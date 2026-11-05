#!/usr/bin/env bash
# select-apps.sh — pick which use-case apps a startup script should launch.
#
# Sourced by scripts/dev-local.sh and scripts/deploy.sh so both honour the
# same selection in the same way.
#
# Precedence:
#   1. APPS env var          — wins always, never prompts. Use this in CI.
#   2. interactive terminal  — prompts, with a timeout so nothing hangs.
#   3. anything else         — starts them all.
#
# APPS accepts a comma-separated list of keys or 1-based numbers, plus the
# words "all" and "none":
#
#   APPS=all                       every app
#   APPS=none                      core platform only
#   APPS=pharmavigil,claimsiq      those two
#   APPS=1,3                       the first and third
#
# After calling select_apps, the chosen keys are in SELECTED_APPS.

# key|label|dir|ports|blurb
APP_REGISTRY=(
  "contractiq|ContractIQ|contractiq|3001/8001|energy contract intelligence"
  "mideasttourism|Mideast Tourism|mideasttourism|3002/8002|tourism analytics"
  "industrial-iot|Industrial IoT|industrial-iot|3003/8003|predictive maintenance + edge"
  "resolveai|ResolveAI|resolveai|3004/8004|customer-service resolution"
  "claimsiq|ClaimsIQ|claimsiq|3005|insurance FNOL (Java + Vaadin)"
  "wingman|Wingman|wingman|3006/8006|energy commodity trading"
  "pharmavigil|PharmaVigil|pharmavigil|3007/8007|drug safety + signal detection"
)

SELECTED_APPS=()
APP_SELECT_TIMEOUT="${APP_SELECT_TIMEOUT:-20}"

app_field() { # app_field <index> <field-number>
  echo "${APP_REGISTRY[$1]}" | cut -d'|' -f"$2"
}

app_key()   { app_field "$1" 1; }
app_label() { app_field "$1" 2; }
app_dir()   { app_field "$1" 3; }
app_ports() { app_field "$1" 4; }
app_blurb() { app_field "$1" 5; }

app_count() { echo "${#APP_REGISTRY[@]}"; }

_all_keys() {
  local i
  for i in "${!APP_REGISTRY[@]}"; do app_key "$i"; done
}

# Turn a user's answer into a list of keys on stdout. Unknown tokens are
# reported on stderr and skipped rather than silently dropped — a typo that
# quietly starts nothing is worse than one that says so.
parse_app_selection() {
  local answer raw token i key matched
  answer="$(echo "${1:-}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"

  if [ -z "${answer}" ] || [ "${answer}" = "all" ]; then
    _all_keys
    return 0
  fi
  if [ "${answer}" = "none" ] || [ "${answer}" = "0" ]; then
    return 0
  fi

  raw="$(echo "${answer}" | tr ',' ' ')"
  for token in ${raw}; do
    matched=0
    # a number selects by position
    if [ "${token}" -eq "${token}" ] 2>/dev/null; then
      i=$((token - 1))
      if [ "${i}" -ge 0 ] && [ "${i}" -lt "${#APP_REGISTRY[@]}" ]; then
        app_key "${i}"
        matched=1
      fi
    else
      for i in "${!APP_REGISTRY[@]}"; do
        key="$(app_key "${i}")"
        if [ "${token}" = "${key}" ]; then
          echo "${key}"
          matched=1
          break
        fi
      done
    fi
    if [ "${matched}" -eq 0 ]; then
      echo "  unknown app '${token}' — skipped" >&2
    fi
  done
  # Explicit, because the loop above ends on whatever the last test evaluated
  # to. Every name matching left that as false, so the function handed back 1
  # and `set -e` in the caller killed the deploy before it printed anything.
  return 0
}

_print_menu() {
  local i
  echo ""
  echo "  Which use-case apps should start alongside the platform?"
  echo ""
  for i in "${!APP_REGISTRY[@]}"; do
    printf "    %d  %-18s %-10s %s\n" \
      "$((i + 1))" "$(app_label "${i}")" "$(app_ports "${i}")" "$(app_blurb "${i}")"
  done
  echo ""
  echo "    Numbers or names, comma separated — e.g. \"1,3\" or \"pharmavigil,claimsiq\"."
  echo "    \"all\" for everything, \"none\" for the core platform only."
  echo "    Enter starts them all. (${APP_SELECT_TIMEOUT}s, then all)"
  echo ""
}

select_apps() {
  local answer="" chosen

  if [ -n "${APPS+x}" ]; then
    # Explicitly set, including to empty. APPS= means none.
    chosen="$(parse_app_selection "${APPS:-none}")"
  elif { [ -t 0 ] && [ -t 1 ]; } || [ -n "${APP_SELECT_FORCE_PROMPT:-}" ]; then
    _print_menu
    # -t so an unattended run cannot wedge the whole startup on a prompt.
    if ! read -r -t "${APP_SELECT_TIMEOUT}" -p "  > " answer; then
      answer=""
      echo ""
      echo "  (no answer — starting all)"
    fi
    chosen="$(parse_app_selection "${answer}")"
  else
    chosen="$(parse_app_selection "all")"
  fi

  SELECTED_APPS=()
  local k
  while IFS= read -r k; do
    # An `if` rather than `[ -n ... ] && ...`. With no apps selected the herestring
    # still yields one empty line, the test fails, and `&&` hands back 1 as the
    # loop's status. That made select_apps return 1, and `set -e` in the caller
    # killed the whole deploy without printing anything.
    if [ -n "${k}" ]; then
      SELECTED_APPS+=("${k}")
    fi
  done <<< "${chosen}"

  # Lets a caller tell "chose nothing" apart from "never asked". An empty
  # SELECTED_APPS means both, and deploy.sh needs the difference: APPS=none
  # should skip building app images, but deploy_cloud never prompts and must
  # still build all of them.
  APP_SELECTION_DONE=1
  return 0
}

app_selected() { # app_selected <key>
  local k
  for k in "${SELECTED_APPS[@]}"; do
    [ "${k}" = "$1" ] && return 0
  done
  return 1
}

describe_selection() {
  if [ "${#SELECTED_APPS[@]}" -eq 0 ]; then
    echo "core platform only — no use-case apps"
  else
    echo "${SELECTED_APPS[*]}"
  fi
}
