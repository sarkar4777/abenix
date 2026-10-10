#!/usr/bin/env bash
# sdk-e2e.sh — run every SDK against a live Abenix the way a developer would.
#
#   1. sign in to the web UI and generate an API key (Playwright)
#   2. Python SDK   pytest e2e/sdk/python_sdk_e2e.py
#   3. JS SDK       build, npm pack, install the tarball, node --test
#   4. React SDK    AgentChat and useAgentStream in jsdom with real fetch (vitest)
#   5. Java SDK     unit tests and a live smoke main in a gradle:8.7-jdk21 container
#
# Usage:
#   bash scripts/sdk-e2e.sh                  # all of them
#   bash scripts/sdk-e2e.sh python js        # a subset: key python js react java
#
# Env:
#   ABENIX_URL   API the SDKs call            (default http://localhost:8000)
#   BASE         web UI the key is minted in  (default http://localhost:3100)
#   ABENIX_API_KEY  skip minting and use this key
#   JAVA_ABENIX_URL API as seen from the container (default host.docker.internal)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

export ABENIX_URL="${ABENIX_URL:-http://localhost:8000}"
export BASE="${BASE:-http://localhost:3100}"
export SDK_KEY_FILE="${ROOT}/e2e/sdk/.sdk-key"
JAVA_ABENIX_URL="${JAVA_ABENIX_URL:-$(echo "${ABENIX_URL}" | sed -e 's#localhost#host.docker.internal#' -e 's#127\.0\.0\.1#host.docker.internal#')}"
GRADLE_IMAGE="${GRADLE_IMAGE:-gradle:8.7-jdk21}"
TSC="node ${ROOT}/node_modules/typescript/bin/tsc"
SDK_VERSION="$(node -p "require('./packages/sdk/js/package.json').version")"

if [ -t 1 ]; then G='\033[0;32m'; R='\033[0;31m'; C='\033[0;36m'; N='\033[0m'; else G=''; R=''; C=''; N=''; fi
step() { printf "\n%b>> %s%b\n" "${C}" "$1" "${N}"; }

declare -A RESULT
STEPS=("$@")
[ "${#STEPS[@]}" -eq 0 ] && STEPS=(key python js react java)
want() { local s; for s in "${STEPS[@]}"; do [ "$s" = "$1" ] && return 0; done; return 1; }
mark() { RESULT[$1]=$2; }

if ! curl -sf -m 5 "${ABENIX_URL}/api/health" >/dev/null; then
  printf "%bAPI not reachable at %s, run: bash scripts/deploy.sh forwards%b\n" "${R}" "${ABENIX_URL}" "${N}"
  exit 2
fi

if want key; then
  if [ -n "${ABENIX_API_KEY:-}" ]; then
    printf '%s' "${ABENIX_API_KEY}" > "${SDK_KEY_FILE}"
    mark key "given"
  else
    step "Generate an API key in the UI at ${BASE}"
    if USE_K8S=1 BASE="${BASE}" npx playwright test e2e/sdk/mint_key.spec.ts --reporter=list --workers=1; then
      mark key pass
    else
      mark key FAIL
    fi
  fi
fi
if [ ! -s "${SDK_KEY_FILE}" ]; then
  printf "%bNo API key in %s, cannot run the SDK suites%b\n" "${R}" "${SDK_KEY_FILE}" "${N}"
  exit 2
fi

if want python; then
  step "Python SDK"
  if python -m pytest e2e/sdk/python_sdk_e2e.py -v -p no:cacheprovider; then mark python pass; else mark python FAIL; fi
fi

build_js() {
  (cd packages/sdk/js && rm -rf dist && ${TSC} -p .)
}

if want js; then
  step "JS SDK: build, pack, install, run"
  if build_js \
    && (cd packages/sdk/js && npm pack --silent --pack-destination "${ROOT}/e2e/sdk/js" >/dev/null) \
    && (cd e2e/sdk/js && npm install --no-save --no-package-lock --silent "./abenix-sdk-${SDK_VERSION}.tgz") \
    && (cd e2e/sdk/js && npm test); then
    mark js pass
  else
    mark js FAIL
  fi
  rm -f "e2e/sdk/js/abenix-sdk-${SDK_VERSION}.tgz"
fi

if want react; then
  step "React SDK: AgentChat and useAgentStream in jsdom"
  if { [ -f packages/sdk/js/dist/index.js ] || build_js; } \
    && (cd packages/sdk/react && ${TSC} -p . --noEmit) \
    && npx vitest run --config e2e/sdk/react/vitest.config.mjs; then
    mark react pass
  else
    mark react FAIL
  fi
fi

if want java; then
  step "Java SDK: unit tests and live smoke in ${GRADLE_IMAGE}"
  winpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else echo "$1"; fi; }
  if MSYS_NO_PATHCONV=1 docker run --rm \
      -v "$(winpath "${ROOT}/claimsiq"):/work" -v abenix-sdk-gradle-cache:/home/gradle/.gradle -w /work \
      "${GRADLE_IMAGE}" gradle :sdk:test :sdk:jar :sdk:copyRuntimeLibs --no-daemon -q --console=plain \
    && MSYS_NO_PATHCONV=1 docker run --rm \
      -v "$(winpath "${ROOT}/claimsiq/sdk/build/libs"):/libs" -v "$(winpath "${ROOT}/e2e/sdk"):/e2e" \
      -e ABENIX_URL="${JAVA_ABENIX_URL}" -e SDK_KEY_FILE=/e2e/.sdk-key \
      "${GRADLE_IMAGE}" java -cp "/libs/sdk-${SDK_VERSION}.jar:/libs/deps/*" /e2e/java/LiveSmoke.java; then
    mark java pass
  else
    mark java FAIL
  fi
fi

printf "\n%-8s %s\n" "suite" "result"
rc=0
for s in "${STEPS[@]}"; do
  r="${RESULT[$s]:-skipped}"
  [ "$r" = "FAIL" ] && rc=1
  printf "%-8s %b%s%b\n" "$s" "$([ "$r" = FAIL ] && echo "${R}" || echo "${G}")" "$r" "${N}"
done
exit "${rc}"
