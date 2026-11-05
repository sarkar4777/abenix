#!/usr/bin/env bash
# Boots a throwaway Abenix stack for the browser smoke in CI: Postgres and
# Redis from docker-compose, the API with uvicorn and the web app's
# standalone server. Model calls go to the stub provider, so no key is needed.
#
#   bash scripts/ci-e2e-stack.sh up      start everything and wait until it answers
#   bash scripts/ci-e2e-stack.sh down    stop the API, web and containers
#   bash scripts/ci-e2e-stack.sh logs    print the tail of the API and web logs
#
# Env: API_PORT (8000) WEB_PORT (3000) DATABASE_URL REDIS_URL
#      START_INFRA=0 to use a Postgres and Redis that are already running
#      SKIP_WEB_BUILD=1 to reuse the last standalone copy in logs/ci-e2e/web-app

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT_DIR}"

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
LOG_DIR="${ROOT_DIR}/logs/ci-e2e"
PY="${PYTHON:-python}"
mkdir -p "${LOG_DIR}"

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://abenix:abenix@127.0.0.1:5432/abenix}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-${REDIS_URL%/*}/1}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-${REDIS_URL%/*}/2}"
# both flags gate the stub provider, see apps/agent-runtime/engine/llm_stub.py
export CI=true ABENIX_LLM_STUB=1
# a non-empty key marks the provider configured, the stub answers before it is ever used
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-ci-stub-not-a-real-key}"
export SECRET_KEY="${SECRET_KEY:-ci-only-secret-key-not-for-production-0123456789}"
export CORS_ORIGINS="[\"http://localhost:${WEB_PORT}\"]"
export DEBUG=true PGSSLMODE=disable ENVIRONMENT=ci SCALING_EXEC_REMOTE=false QUEUE_BACKEND=celery
export STORAGE_BACKEND=local STORAGE_LOCAL_DIR="${ROOT_DIR}/data/ci-uploads"
export NEXT_TELEMETRY_DISABLED=1

wait_http() { # wait_http <url> <name> <seconds>
  local i
  for i in $(seq 1 "$3"); do
    if curl -sf -m 5 "$1" -o /dev/null; then echo "  ✓ $2 answers at $1"; return 0; fi
    sleep 1
  done
  echo "  ✗ $2 did not answer at $1 within $3 s"
  return 1
}

up() {
  if [ "${START_INFRA:-1}" = "1" ]; then
    echo "▶ Postgres and Redis"
    docker compose up -d postgres redis
    for _ in $(seq 1 60); do
      docker compose exec -T postgres pg_isready -U abenix >/dev/null 2>&1 && break
      sleep 1
    done
    docker compose exec -T postgres pg_isready -U abenix
  fi

  echo "▶ Schema and seeds"
  (
    cd packages/db
    PYTHONPATH=. "${PY}" -m bootstrap
    PYTHONPATH=. "${PY}" -m alembic upgrade heads
    PYTHONPATH=. "${PY}" seeds/seed_users.py
    PYTHONPATH=. "${PY}" seeds/seed_subject_policies.py
    PYTHONPATH=. "${PY}" seeds/seed_agents.py >/dev/null
  )

  echo "▶ API on ${API_PORT}"
  (
    cd apps/api
    PYTHONPATH=".:../../packages/db:../../apps/agent-runtime" nohup "${PY}" -m uvicorn app.main:app \
      --host 127.0.0.1 --port "${API_PORT}" > "${LOG_DIR}/api.log" 2>&1 &
    echo $! > "${LOG_DIR}/api.pid"
  )
  wait_http "http://localhost:${API_PORT}/api/health" API 120 || { tail -60 "${LOG_DIR}/api.log"; return 1; }

  echo "▶ Web on ${WEB_PORT}"
  if [ "${SKIP_WEB_BUILD:-0}" != "1" ] || [ ! -d "${LOG_DIR}/web-app" ]; then
    (cd apps/web && NEXT_PUBLIC_API_URL="http://localhost:${API_PORT}" npx next build > "${LOG_DIR}/web-build.log" 2>&1)       || { tail -60 "${LOG_DIR}/web-build.log"; return 1; }
    # serve a copy of the standalone build, so a later build in apps/web cannot swap chunks under it
    rm -rf "${LOG_DIR}/web-app"
    cp -r apps/web/.next/standalone "${LOG_DIR}/web-app"
    cp -r apps/web/.next/static "${LOG_DIR}/web-app/apps/web/.next/static"
    [ -d apps/web/public ] && cp -r apps/web/public "${LOG_DIR}/web-app/apps/web/public"
  fi
  (
    cd "${LOG_DIR}/web-app/apps/web"
    PORT="${WEB_PORT}" HOSTNAME=127.0.0.1 nohup node server.js > "${LOG_DIR}/web.log" 2>&1 &
    echo $! > "${LOG_DIR}/web.pid"
  )
  wait_http "http://localhost:${WEB_PORT}/" Web 120 || { tail -60 "${LOG_DIR}/web.log"; return 1; }
}

down() {
  local f
  for f in api web; do
    [ -f "${LOG_DIR}/${f}.pid" ] && kill "$(cat "${LOG_DIR}/${f}.pid")" 2>/dev/null || true
    rm -f "${LOG_DIR}/${f}.pid"
  done
  if [ "${START_INFRA:-1}" = "1" ]; then docker compose down -v; fi
}

logs() {
  local f
  for f in api web web-build; do
    [ -f "${LOG_DIR}/${f}.log" ] || continue
    echo "──── ${f}.log"
    tail -150 "${LOG_DIR}/${f}.log"
  done
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  logs) logs ;;
  *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
