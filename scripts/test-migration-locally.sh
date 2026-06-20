#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

NAME=pg-migtest-$$
PORT=55434

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "▶ starting postgres container ${NAME} on :${PORT}"
docker run -d --rm --name "$NAME" \
  -p "${PORT}:5432" \
  -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=test \
  pgvector/pgvector:pg15 >/dev/null

echo "▶ waiting for postgres"
for i in $(seq 1 30); do
  if docker exec "$NAME" pg_isready -U postgres >/dev/null 2>&1; then
    echo "  ready after ${i}s"; break
  fi
  sleep 1
done

docker exec "$NAME" psql -U postgres -d test -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
docker exec "$NAME" psql -U postgres -d test -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;" >/dev/null

export DATABASE_URL="postgresql+asyncpg://postgres:test@localhost:${PORT}/test"

cd packages/db
echo "▶ bootstrapping schema via ORM (Base.metadata.create_all)"
PYTHONPATH="$(pwd)" python -m bootstrap 2>&1 | tail -10

echo
echo "▶ stamping alembic to a8b9c0d1e2f3's parent (z9y8x7w6v5u4)"
PYTHONPATH="$(pwd)" python -m alembic stamp z9y8x7w6v5u4 2>&1 | tail -5

echo
echo "▶ pre-dropping columns the new migration adds (so bootstrap leftovers don't collide)"
docker exec "$NAME" psql -U postgres -d test -c "
  ALTER TABLE llm_model_pricing DROP COLUMN IF EXISTS capabilities;
  ALTER TABLE llm_model_pricing DROP COLUMN IF EXISTS fallback_to;
  ALTER TABLE llm_model_pricing DROP COLUMN IF EXISTS provider_endpoint;
  ALTER TABLE llm_model_pricing DROP COLUMN IF EXISTS display_name;
  ALTER TABLE llm_model_pricing DROP COLUMN IF EXISTS is_deprecated;
  ALTER TABLE llm_model_pricing DROP COLUMN IF EXISTS deprecated_at;
  ALTER TABLE llm_model_pricing DROP COLUMN IF EXISTS migration_hint;
  ALTER TABLE executions DROP COLUMN IF EXISTS model_requested;
  ALTER TABLE executions DROP COLUMN IF EXISTS model_fallback_reason;
  DROP TABLE IF EXISTS model_availability_events;
  DROP TABLE IF EXISTS model_availability;
" >/dev/null

echo
echo "▶ running ONLY the new migration: a8b9c0d1e2f3"
PYTHONPATH="$(pwd)" python -m alembic upgrade a8b9c0d1e2f3 2>&1 | tail -30

echo
echo "▶ verifying llm_model_pricing rows landed"
docker exec "$NAME" psql -U postgres -d test -c "SELECT model, provider, is_active, is_deprecated FROM llm_model_pricing WHERE provider = 'azure' ORDER BY model;"

echo
echo "▶ verifying model_availability rows seeded"
docker exec "$NAME" psql -U postgres -d test -c "SELECT model, status FROM model_availability ORDER BY model LIMIT 12;"

echo
echo "▶ verifying executions columns"
docker exec "$NAME" psql -U postgres -d test -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'executions' AND column_name IN ('model_requested', 'model_used', 'model_fallback_reason') ORDER BY column_name;"

echo
echo "✔ migration green"
