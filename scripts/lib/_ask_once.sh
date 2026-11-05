#!/usr/bin/env bash
# Test helper: run one selection and print the chosen keys, nothing else.
# The menu goes to stderr so the caller can compare the result cleanly.
set -uo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT_DIR}/scripts/lib/select-apps.sh"
unset APPS
select_apps >&2
echo "${SELECTED_APPS[*]-}"
