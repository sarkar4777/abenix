# Architectural patterns reference

> Every recurring shape in the codebase. If you see a piece of code and wonder "why is it built this way?", read the matching entry here. Each pattern lists its file home, its rationale, and the failure mode you get if you violate it.

---

## Tenant and identity patterns

### 1. Tenant-scoped everything

Every domain row carries `tenant_id` (`TenantMixin` in [`packages/db/models/base.py`](../../packages/db/models/base.py)). Every query joins or filters on it. Middleware (`TenantMiddleware`) establishes the active tenant. Route handlers receive it via `Depends(get_current_user)`.

```python
@router.get("/widgets")
async def list_widgets(user = Depends(get_current_user), db = Depends(get_db)):
    return await db.execute(select(Widget).where(Widget.tenant_id == user.tenant_id))
```

**Violation symptom** — a missing `WHERE tenant_id = …` will silently surface another tenant's data the first time a customer with a colliding ID exists. The verify-schema gate (`scripts/verify-schema.sh`) refuses to start a deploy if any new table is missing the column.

### 2. actAs (delegated subject) with policy enforcement

A service-account API key acts on behalf of an end-user via `X-Abenix-Subject` (JSON header). RBAC + audit + sharing attribute to the subject. Permission to delegate is gated by two predicates — the key must have `can_delegate` scope, and a `SubjectPolicy` row must match (explicit or wildcard).

```python
subject = ActingSubject(subject_type="wingman", subject_id=trader.id, email=trader.email)
result = await client.with_subject(subject).execute(slug, input)
```

Chain depth is exactly one — a delegated subject cannot re-delegate. See [01-tenants-rbac](01-tenants-rbac.md) for the full chain.

### 3. Subject-scoped collection auto-resolution

When an acting subject is present, `resolve_agent_collections` ([`apps/api/app/services/collection_access.py`](../../apps/api/app/services/collection_access.py)) adds a subject-scoped collection leg to the query. The collection name follows `{subject_type}-{subject_id}` and is auto-created on first reference. This is how per-trader memory works without one row per trader in `tenant_settings`.

### 4. Polymorphic resource sharing

One table — `resource_shares` — handles sharing for six resource kinds (agent, pipeline, ml_model, code_asset, knowledge_base, saved_tool). Single permission predicate. Three-tier ranks (view < use < edit). Expiry-aware reads. Hard-delete to revoke, with the audit row left behind for compliance.

```python
if not await user_can(user, db, action="execute", resource=("ml_model", model_id)):
    raise HTTPException(403)
```

### 5. Audit-by-default with dual attribution

Every mutating endpoint emits an `audit_logs` row via `log_action()` carrying both `user_id` (key holder) and `actor_subject_*` (delegated subject). Compliance queries can filter on either axis. Append-only.

---

## Data and persistence patterns

### 6. JSONB for flex fields

`agents.model_config_`, `executions.payload`, `executions.output`, `pipeline_steps.config`, `atlas_nodes.properties`, `tool_invocations.metadata` — all JSONB. Structural validation at the API/SDK boundary, not at the column level.

**When to add a JSONB field vs a column** — used by all rows + queried often → column. Sometimes-present, schema-evolving, used mostly for read-back → JSONB. Never put `tenant_id`, status, or anything you'll group by in JSONB.

### 7. Soft delete via status enum

Rows are rarely hard-deleted. Instead, `status` flips to `'deleted'`. List queries filter `status != 'deleted'`. An archive job (Celery beat) moves cold rows out periodically.

**Trap** — `DELETE FROM agents …` directly in psql will break referential integrity on `executions` and `agent_revisions`. Always use the API.

### 8. Idempotency keys

Every mutating SDK call accepts `client_token`. The server upserts on `(tenant_id, client_token)` and returns the prior response if it matches. Safe to retry network failures.

```python
await client.execute(slug, input, client_token=f"scan-{corridor_id}-{date}")
```

Stored in `execution_idempotency` with 24h expiry. See [09-state-machines](../02-runtime/09-state-machines.md#idempotency).

### 9. Schema migration policy — expand → backfill → contract

For risky migrations: add new column (expand), deploy backfill job, deploy code reading/writing new column, wait one release cycle, drop old column (contract). Never expand-and-contract in one migration on a production table.

### 10. Schema drift catchup migration

`packages/db/alembic/versions/x4y5z6a7b8c9_schema_drift_catchup.py` is idempotent and information_schema-guarded. It picks up any columns that exist in the ORM but not in the database. Re-running is always safe. The `scripts/_schema-sentinels.sh` file is the single source of truth for which columns must exist post-migration.

### 11. Time-series via Timescale

`executions` is a Timescale hypertable on `created_at`. After 90 days rows compress. After 365 they move to cold storage. Keeps the hot index small.

### 12. Sentinel-column verification gate

Both `dev-local.sh` and `deploy-azure.sh` run a post-migration check against `scripts/_schema-sentinels.sh`. If any sentinel column is missing, deploy stops with a clear error. This catches "migration script ran but didn't actually do what it said" — a recurring class of failure before this gate existed.

---

## Runtime and execution patterns

### 13. The four-pool runtime

Four agent-runtime deployments (`default`, `chat`, `heavy-reasoning`, `long-running`) isolate workloads. Each scaled by KEDA on its own NATS queue depth. A Monte-Carlo on heavy-reasoning never starves chat.

- Pool picker: [`apps/api/app/services/agent_dispatch.py`](../../apps/api/app/services/agent_dispatch.py) — reads agent metadata (`agent_type`, `model_config.preset`, `max_iterations`).
- Deployment manifests: [`infra/helm/abenix/templates/agent-runtime-*.yaml`](../../infra/helm/abenix/templates/).
- KEDA ScaledObjects: see [06-deployment/03-keda](../06-deployment/03-keda.md).

### 14. Three-tier resolution with fail-loud

For data-producing endpoints:

```
Tier 1: live agent → real-service tools → ML models     (preferred)
Tier 2: cached prior result (if fresh)                  (fast path)
Tier 3: explicit "no data" envelope                     (fail-loud)
```

**No synthesis tier.** If the agent fails, the UI shows "no recent scan" rather than fabricating numbers. Trader trust > availability.

### 15. Durable pause/resume on approval gates

When a tool needs human signoff, the runtime persists the loop state to `executions.pause_state` (JSONB) and exits the pod. On signoff, a fresh pod re-hydrates and resumes from the saved state. Long approvals don't pin pods.

- Pause + resume code: [`apps/agent-runtime/engine/agent_executor.py`](../../apps/agent-runtime/engine/agent_executor.py) — search for `pause_state`.
- Approval signoff handler: [`apps/api/app/routers/approvals.py`](../../apps/api/app/routers/approvals.py).
- Full flow doc: [02-runtime/05-approvals-hitl](../02-runtime/05-approvals-hitl.md).

### 16. SSE bridge over NATS pub/sub

The runtime publishes execution events to a Redis pub/sub channel (`progress.<root_execution_id>`). The API server's SSE bridge subscribes per execution_id. Reconnect via `Last-Event-ID` replays the last 100 events.

- Publisher: [`apps/agent-runtime/engine/progress.py`](../../apps/agent-runtime/engine/progress.py).
- SSE bridge: [`apps/api/app/routers/executions.py`](../../apps/api/app/routers/executions.py) (the `stream` and `watch` routes).
- Full streaming + tracing doc: [02-runtime/04-streaming-tracing](../02-runtime/04-streaming-tracing.md).

### 17. Root-execution channel aggregation

When an agent calls `invoke_agent`, the sub-execution's pod publishes its events to the **root's** channel, not its own. The subscriber sees the whole tree on one stream.

- Walk-up logic: [`apps/agent-runtime/engine/progress.py:75`](../../apps/agent-runtime/engine/progress.py) — `async def root_for(execution_id)` caps the recursion at 8 hops.
- Sub-execution publisher: [`apps/agent-runtime/engine/tools/invoke_agent.py`](../../apps/agent-runtime/engine/tools/invoke_agent.py).

### 18. Distributed tracing across the SDK boundary

W3C `traceparent` propagates from the calling app's span through the SDK, through the platform API, through NATS, through the runtime, through the LLM SDK. One Tempo trace shows the whole flow. The SDK auto-injects `traceparent` if a tracer is active in the caller's process. Otherwise it skips quietly.

- SDK injector: [`packages/sdk/python/abenix_sdk/_tracing.py`](../../packages/sdk/python/abenix_sdk/).
- API extractor: [`apps/api/app/core/telemetry.py`](../../apps/api/app/core/telemetry.py).
- Runtime span continuation: [`apps/agent-runtime/engine/tracing.py`](../../apps/agent-runtime/engine/tracing.py).

### 19. Self-healing pipelines via error_branch

When a pipeline node fails, the engine can route via an `on_error: error_branch` edge to a recovery node. Recovery nodes often call a meta-agent that decides whether to retry, escalate, or skip.

- Edge resolver: [`apps/agent-runtime/engine/pipeline.py`](../../apps/agent-runtime/engine/pipeline.py) — search for `on_error`.
- Per-node fail-fast vs failure-isolated branching: [02-runtime/07-pipeline-data-flow](../02-runtime/07-pipeline-data-flow.md#error-handling).
- Full self-healing + drift doc: [02-runtime/10-pipeline-healing-drift](../02-runtime/10-pipeline-healing-drift.md).

### 20. Topological-sort scheduler with deterministic layer order

[`_topological_sort()` at `pipeline.py:286`](../../apps/agent-runtime/engine/pipeline.py) returns `list[list[str]]` where each inner list runs concurrently. Within a layer, IDs are sorted alphabetically for determinism — re-running the same pipeline twice produces byte-identical SSE traces.

- Caller: line 466 in the same file, inside the main `execute_pipeline()` loop.
- Test: [`apps/agent-runtime/tests/test_pipeline.py`](../../apps/agent-runtime/tests/test_pipeline.py).

### 21. Whole-value vs embedded template semantics

`{{plan}}` (the entire string) returns the structured value of `plan` unchanged. `"prefix {{plan}} suffix"` returns a string with `plan` interpolated via JSON. This distinction is load-bearing — leading whitespace silently switches behaviour.

- Resolver: `_resolve_inputs()` in [`apps/agent-runtime/engine/pipeline.py`](../../apps/agent-runtime/engine/pipeline.py) around line 339.
- Test coverage: [`apps/agent-runtime/tests/test_pipeline.py`](../../apps/agent-runtime/tests/test_pipeline.py) — search for `whole_value` and `embedded`.

### 22. Self-attaching tools with the `_DefaultedTool` wrapper

Tools registered with `parameter_defaults` are wrapped — the wrapper hides the defaulted parameters from the LLM's view of the schema. The LLM never sees the pre-set blob hash or tenant ID it would have to guess. The wrapper merges defaults at execution time.

- Wrapper class: [`_DefaultedTool` at `apps/agent-runtime/engine/tools/base.py:31`](../../apps/agent-runtime/engine/tools/base.py).
- Registration helper that wraps a tool with defaults: same file, around line 111.

### 23. In-process sandbox with domain whitelist

`ExecutionSandbox` ([`apps/agent-runtime/engine/sandbox.py`](../../apps/agent-runtime/engine/sandbox.py)) enforces:

- Per-execution wall clock timeout.
- Per-tool call count cap.
- Per-tool output size cap.
- Network domain whitelist (~13 hardcoded domains for first-party tools).

Violations are tracked as `SandboxViolation` records and surface as `sandbox_violation` failure_code.

### 24. MCP destructive-hint approval gate

MCP tools annotated with `destructiveHint: true` require explicit approval. Read-only tools can auto-approve if `auto_approve_read_only=True` is set on the agent's MCP policy. The audit trail in `MCPSecurityContext` records every call.

### 25. Provider-cost ledger with per-provider columns

`executions.{anthropic_cost, openai_cost, google_cost, other_cost}` sum to `executions.cost`. Lets dashboards split spend by provider. The pricing dict in [`apps/agent-runtime/engine/llm_router.py`](../../apps/agent-runtime/engine/llm_router.py) is the source of truth for input/output rates, refreshed from a DB-backed cache every 60s so admin edits propagate.

### 26. Reconciliation sweepers in Celery beat

`worker.tasks.sweepers.expire_running_executions` flips stuck-running rows to failed after `RUNNING_EXECUTION_TTL`. Other sweepers: expired approvals, unsent notifications, orphaned uploads. Catches the rare case where NATS or a pod crashed before writing terminal status.

---

## Error handling and observability patterns

### 27. Structured error envelope

Every non-2xx HTTP response is `{data:null, error:{message, code, error_code, details}}`. UI branches on stable `error_code` strings. Messages are translatable.

### 28. PII-redacting span processor

Sensitive attributes (`llm.prompt`, `tool.args`, `agent.system_prompt`, `tool.output`) are hash+length replaced before OTel export. `tracing.py:_redact_value()` returns `<redacted len=N sha256=XXX>`. Traces are safe to share with support.

**Known gap** — nested JSON inside `tool.metadata` is not deep-redacted. A tool that pushes a customer record into `metadata.user_data` will export it. Use the redaction-safe accessor.

### 29. Failure-code taxonomy with stable strings

`executions.failure_code` is an indexed string column whose values are a hand-curated taxonomy (`llm_timeout`, `tool_error`, `iteration_limit`, `sandbox_violation`, …). Alerts group on `failure_code`. New codes get added when a class of failure shows up enough to warrant its own alert. See [09-state-machines](../02-runtime/09-state-machines.md#failure-code-taxonomy).

### 30. Lazy Prometheus metric registration

`_safe_metric()` in `metrics.py` registers a counter / histogram only if one with the same name isn't already there. Survives gunicorn fork without "metric already registered" exceptions.

### 31. Per-tenant rate-limit + monthly quota

Two layers — soft (per-tenant rps + monthly token cap, Redis counters in `RateLimitMiddleware`) and hard (per-tenant `executions_per_day_cap` on `tenant_settings`). Surface codes: `RATE_LIMITED`, `TENANT_QUOTA_EXCEEDED`. The hard cap fires *before* enqueue, so a quota-exceeded tenant cannot fill the runtime backlog.

---

## Deployment and packaging patterns

### 32. Vendored SDK with sync-check

The Python SDK lives canonically at `packages/sdk/python/abenix_sdk/`. The vertical apps that live in this repo vendor a copy under `<app>/api/sdk/abenix_sdk/`. CI runs `scripts/sync-sdks.sh --check` on every commit and drift fails the build.

**Why vendor** — the SDK runs inside the standalone app's Docker image. Pinning a published version would create a release-coupling problem. Vendoring keeps the example deployments simple. **Third-party apps outside this repo should `pip install abenix-sdk`** — vendoring is an in-repo convenience, not a recommendation.

### 33. Helm for platform, kubectl for example standalones

Platform services are helm-managed. The six in-repo standalone apps are kubectl-applied. Different release cadences. Coupling them would create cross-team blockers. Third-party apps follow whatever pattern fits their stack.

### 34. KEDA dual-trigger autoscaling

Each runtime pool's ScaledObject has a NATS-lag trigger (primary) and an optional Prometheus p95-duration trigger. They use OR semantics — whichever demands more replicas wins. The p95 trigger catches "queue is short but each item is slow" — a state the lag trigger alone misses. See [08-queue-scaling](../02-runtime/08-queue-scaling.md).

### 35. Bodhi rebrand pattern

The deployed cluster shows "Bodhi" branding (a demo brand) but HEAD source is always Abenix-named. Achieved by `scripts/apply-bodhi-and-deploy.sh` which sed-replaces at deploy time and reverts after. **Never** commit Bodhi-branded source. This is a release-time decoration, not a source-tree state.

### 36. Per-pool concurrency tuning

`AGENT_CONCURRENCY` is set per-pool in the Helm chart. The chat pool runs higher concurrency (~20 in-flight) on smaller pods. The heavy-reasoning pool runs ~5 in-flight on larger pods. Long-running runs 1 in-flight per pod because each execution can hold a single connection to an external service for minutes.

### 37. Standalone-key reconciler in dev-local

`scripts/dev-local.sh` runs an idempotent reconciler that mints `<APP>_ABENIX_API_KEY` for every standalone app before launch. Already-valid keys are reused. New keys upsert and the script exports them so the app's start.sh inherits the value.

---

## UI patterns

### 38. The apiFetch + structured error envelope contract

`apiFetch` ([`apps/web/src/lib/api.ts`](../../apps/web/src/lib/api.ts)) parses the structured error envelope, throws `ApiError` with `error_code` on mutating non-2xx, and returns parsed JSON on success. UI components branch on `err.error_code` for stable handling. See [05-ui/02-api-client](../05-ui/02-api-client.md).

### 39. React Flow canvas with custom node types

The Agent Builder and Pipeline Builder use one React Flow instance per page with custom node types — agent, tool, condition, switch, forEach, while, merge. Node validation is per-type. The validation chip in the corner deep-links to the first invalid node.

### 40. SWR + targeted `mutate` for list pages

Lists are fetched with SWR. After a mutation, only the affected key is invalidated — not the whole cache. This is how the agents-list page can show the new row in < 200ms after create. See [`apps/web/src/lib/swr.ts`](../../apps/web/src/lib/swr.ts).

### 41. Resource share dialog as a generic mount

`ResourceShareDialog` is one component used on every resource page (agents, KBs, ML, code assets). The page passes `(resource_type, resource_id)` and the dialog handles the rest. New resource types need only register a label and they get the same UX.

---

## Communication patterns between standalones and platform

### 42. SDK is the only public boundary

Third-party apps must use the published SDK. They never import from this monorepo, never read helm values, never see internal Redis keys. The SDK is semver and is the contract.

### 43. actAs every call, even from anonymous users

A user-facing flow without login should still set `subject_type="anonymous"` with a synthetic subject_id (e.g. a hashed IP or a UUID stored in a cookie). This keeps the audit log consistent and lets per-anonymous-user shares work the same way as per-real-user shares.

### 44. SSE proxy at the BFF tier

Standalone apps proxy SSE through their own backend rather than letting the SPA talk to the platform directly. The proxy applies the app's own auth and lets the app pre-filter / enrich events.

### 45. Cache only with audit trail

Per-app caches only hold values that came from a real platform call. Every cached entry carries the `execution_id` it came from so the UI can deep-link to the trace. Hand-poked cache values violate the audit contract and are forbidden — there's no synthesis tier.

---

## When you should break these

Most of these patterns earn their keep most of the time. Two situations where the pattern is *not* the right answer.

- **One-off experiments**. A throwaway script that wants to test "does this prompt work?" does not need actAs, idempotency, or pause/resume. Use the raw HTTP API and move on.
- **Performance-critical tight loops**. A high-volume inbound webhook handler that wants to call the platform 1k+ times a second should *not* go through the standard SDK. Use the batch endpoint (one POST, many executions) or skip the platform entirely if the work is truly stateless. Don't pretend the regular path will scale.

In both cases, the violation should be documented at the call site so the next reader knows why the usual pattern doesn't apply.

---

## See also

- [00-overview](00-overview.md) — high-level system view linking back to many of these patterns.
- [02-runtime/06-agent-to-agent](../02-runtime/06-agent-to-agent.md) — patterns 16, 17, 25 in action.
- [02-runtime/07-pipeline-data-flow](../02-runtime/07-pipeline-data-flow.md) — patterns 19, 20, 21.
- [02-runtime/08-queue-scaling](../02-runtime/08-queue-scaling.md) — patterns 13, 34, 36.
- [02-runtime/09-state-machines](../02-runtime/09-state-machines.md) — patterns 7, 8, 15, 29.
- [08-howto/04-debugging](../08-howto/04-debugging.md) — patterns under stress.
