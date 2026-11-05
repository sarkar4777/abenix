#!/usr/bin/env bash
set -euo pipefail

# ACR remote build for every image in deploy-azure.sh DOCKERFILES map.
# Bypasses local Docker — uploads context to ACR, builds in cloud.
# Use when local BuildKit is wedged.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

ACR_NAME="${ACR_NAME:-your-acr}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"

declare -A DOCKERFILES=(
  [api]="docker/Dockerfile.api"
  [web]="docker/Dockerfile.web"
  [worker]="docker/Dockerfile.worker"
  [agent-runtime]="docker/Dockerfile.agent-runtime"
  [contractiq-api]="contractiq/api/Dockerfile"
  [contractiq-web]="contractiq/web/Dockerfile"
  [mideasttourism-api]="mideasttourism/api/Dockerfile"
  [mideasttourism-web]="mideasttourism/web/Dockerfile"
  [industrial-iot-api]="industrial-iot/api/Dockerfile"
  [industrial-iot-web]="industrial-iot/web/Dockerfile"
  [resolveai-api]="resolveai/api/Dockerfile"
  [resolveai-web]="resolveai/web/Dockerfile"
  [wingman-api]="wingman/api/Dockerfile"
  [wingman-web]="wingman/web/Dockerfile"
  [claimsiq]="claimsiq/app/Dockerfile"
)
declare -A BUILD_CONTEXTS=(
  [api]="${ROOT_DIR}"
  [web]="${ROOT_DIR}"
  [worker]="${ROOT_DIR}"
  [agent-runtime]="${ROOT_DIR}"
  [contractiq-api]="${ROOT_DIR}/contractiq/api"
  [contractiq-web]="${ROOT_DIR}/contractiq/web"
  [mideasttourism-api]="${ROOT_DIR}/mideasttourism"
  [mideasttourism-web]="${ROOT_DIR}/mideasttourism/web"
  [industrial-iot-api]="${ROOT_DIR}/industrial-iot/api"
  [industrial-iot-web]="${ROOT_DIR}/industrial-iot/web"
  [resolveai-api]="${ROOT_DIR}/resolveai/api"
  [resolveai-web]="${ROOT_DIR}/resolveai/web"
  [wingman-api]="${ROOT_DIR}/wingman/api"
  [wingman-web]="${ROOT_DIR}/wingman/web"
  [claimsiq]="${ROOT_DIR}/claimsiq"
)

if [ $# -eq 0 ]; then
  SERVICES=(api web worker agent-runtime contractiq-api contractiq-web
            mideasttourism-api mideasttourism-web industrial-iot-api industrial-iot-web
            resolveai-api resolveai-web wingman-api wingman-web claimsiq)
else
  SERVICES=("$@")
fi

echo "[acr-build] registry=${ACR_NAME} tag=${IMAGE_TAG}"
echo "[acr-build] services: ${SERVICES[*]}"
echo

to_win() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else echo "$1"; fi
}

for svc in "${SERVICES[@]}"; do
  df="${DOCKERFILES[$svc]:-}"
  ctx="${BUILD_CONTEXTS[$svc]:-${ROOT_DIR}}"
  if [ -z "$df" ]; then echo "[skip] ${svc}: no Dockerfile mapping"; continue; fi
  if [ ! -f "${ROOT_DIR}/${df}" ]; then echo "[skip] ${svc}: Dockerfile ${df} missing"; continue; fi
  log="${LOG_DIR}/acr-${svc}.log"
  rel_df="${df}"
  if [ "${ctx}" != "${ROOT_DIR}" ]; then
    rel_df="$(realpath --relative-to="${ctx}" "${ROOT_DIR}/${df}")"
  fi
  echo "[build] ${svc} (ctx=${ctx#${ROOT_DIR}/} df=${rel_df})"
  start=$(date +%s)
  if ( cd "${ctx}" && PYTHONIOENCODING=utf-8 az acr build \
       --registry "${ACR_NAME}" \
       --image "${svc}:${IMAGE_TAG}" \
       --image "${svc}:latest" \
       --file "${rel_df}" \
       --platform linux \
       --no-logs \
       . ) >"${log}" 2>&1; then
    dur=$(( $(date +%s) - start ))
    echo "[ok]    ${svc} (${dur}s)"
  else
    dur=$(( $(date +%s) - start ))
    echo "[FAIL]  ${svc} (${dur}s) — see ${log}"
    tail -20 "${log}" >&2
    exit 1
  fi
done

echo
echo "[done] all images at ${ACR_NAME}.azurecr.io/{svc}:${IMAGE_TAG}"
