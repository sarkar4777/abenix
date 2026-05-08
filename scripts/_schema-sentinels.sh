#!/usr/bin/env bash
# Canonical schema sentinels — single source of truth.
#
# Sourced by:
#   - scripts/dev-local.sh           (local Postgres in Docker)
#   - scripts/deploy-azure.sh        (AKS via kubectl exec on the api pod)
#   - scripts/verify-schema.sh       (standalone verifier, supports --pod=)
#   - scripts/dev-minikube.sh        (kicks deploy.sh which uses the same chain)
#
# Each entry is "table.column". After `alembic upgrade heads` runs, every
# row here MUST exist in the live database — otherwise we've got drift
# (the migration failed silently, the live DB is on an older head, or
# someone shipped an ORM change without a matching migration). The check
# is fail-loud everywhere — no `|| true` swallows.
#
# When you add a schema-changing migration:
#   1. Write the migration under packages/db/alembic/versions/.
#   2. Add the load-bearing columns it introduces to this list.
#   3. The next deploy in any environment runs `alembic upgrade heads`
#      and verifies these sentinels — if anything is missing, the
#      deploy aborts before traffic flips.
SCHEMA_CANONICAL_COLUMNS=(
  "executions.node_results"
  "executions.execution_trace"
  "executions.failure_code"
  "agent_shares.shared_with_user_id"
  "moderation_policies.default_action"
  "agent_memories.importance"
  "approvals.client_token"
  "approvals.gate_kind"
)
