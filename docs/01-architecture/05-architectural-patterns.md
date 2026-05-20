# Architectural patterns reference

> A single page collecting every recurring pattern in the codebase. If you see a piece of code and wonder "why is it shaped like this?", it's probably here.

---

## 1. Tenant-scoped everything

Every row carries `tenant_id`. every query filters by tenant. every JWT/API key carries a tenant. Middleware (`TenantMiddleware`) establishes the active tenant. route handlers receive it via `Depends(get_current_user)`.

**Code shape**:
```python
@router.get("/widgets")
async def list_widgets(user: User = Depends(get_current_user), db = Depends(get_db)):
    return await db.execute(
        select(Widget).where(Widget.tenant_id == user.tenant_id)
    )
```

**Trap**: never trust a `tenant_id` from a request body. The only source is the resolved auth subject.

See: [`01-tenants-rbac`](01-tenants-rbac.md).

---

## 2. actAs (delegated subject)

A service-account API key acts on behalf of an end-user via `X-Abenix-Subject: <type>:<id>`. RBAC + audit + sharing attribute to the subject.

**Code shape (Python SDK)**:
```python
subject = ActingSubject(subject_type="wingman", subject_id=trader.id, email=trader.email)
result = await client.with_subject(subject).execute(slug, input)
```

See: [`01-tenants-rbac`](01-tenants-rbac.md#the-actas-delegated-subject-pattern).

---

## 3. Polymorphic resource sharing

One table — `resource_shares` — handles sharing for 6 resource kinds (agent, pipeline, ml_model, code_asset, knowledge_base, saved_tool). Single permission predicate.

**Code shape**:
```python
if not await user_can(user, db, action="execute", resource=("ml_model", model_id)):
    raise HTTPException(403)
```

See: [`04-data-model/04-resource-shares`](../04-data-model/04-resource-shares.md).

---

## 4. JSONB for flex fields

`agents.model_config_`, `executions.payload`, `executions.output`, `pipeline_steps.config`, `atlas_nodes.properties`, `tool_invocations.metadata` — all JSONB. Structural validation at the API/SDK boundary, not at the column level.

**When to add a JSONB field vs a column**:
- Used by all rows + queried often → column.
- Sometimes-present, schema-evolving, used mostly for read-back → JSONB.

---

## 5. Thin-app pattern

Vertical apps own UI + auth + caching. the platform owns everything else. Vertical apps NEVER hold business logic — every interesting calculation lives in a platform agent.

See: [`07-standalone-apps/00-pattern`](../07-standalone-apps/00-pattern.md).

---

## 6. Three-tier resolution with fail-loud

For data-producing endpoints (e.g. corridor scan):

```
Tier 1: live agent → real-service tools → ML models     (preferred)
Tier 2: cached prior result (if fresh)                  (fast path)
Tier 3: explicit "no data" envelope                     (fail-loud)
```

No synthesis tier. If the agent fails, the UI shows "no recent scan" rather than fabricating numbers. Trader trust > availability.

See: [`02-runtime/00-agent-execution`](../02-runtime/00-agent-execution.md) + [`07-standalone-apps/01-wingman`](../07-standalone-apps/01-wingman.md#three-tier-resolution-for-mispricing-scans).

---

## 7. Durable pause/resume on approval gates

When a tool needs human signoff, the runtime persists the loop state to Postgres and exits the pod. On signoff, a fresh pod re-hydrates and resumes. Long approvals don't pin pods.

See: [`02-runtime/05-approvals-hitl`](../02-runtime/05-approvals-hitl.md).

---

## 8. SSE + NATS bridge for live updates

The runtime publishes execution events to NATS JetStream. The API server bridges them to browser SSE connections subscribed per execution_id. Reconnect via `Last-Event-ID`.

See: [`02-runtime/04-streaming-tracing`](../02-runtime/04-streaming-tracing.md).

---

## 9. Distributed tracing across the SDK boundary

W3C `traceparent` propagates from the calling app's span through the SDK through the platform API through NATS through the runtime through the LLM SDK. One Tempo trace shows the whole flow.

See: [`02-runtime/04-streaming-tracing`](../02-runtime/04-streaming-tracing.md).

---

## 10. Self-healing pipelines

When a pipeline step fails, the engine can route via an `onError` edge to a recovery step. Recovery steps often call a meta-agent that decides whether to retry, escalate, or skip.

See: [`02-runtime/01-pipelines`](../02-runtime/01-pipelines.md).

---

## 11. Structured error envelope

Every non-2xx HTTP response is `{data:null, error:{message, code, error_code, details}}`. UI branches on stable `error_code` strings. messages are translated.

See: [`05-ui/02-api-client`](../05-ui/02-api-client.md).

---

## 12. The four-pool runtime

Four agent-runtime deployments (`default`, `chat`, `heavy-reasoning`, `long-running`) isolate workloads. Each scaled by KEDA on its own NATS queue depth.

See: [`06-deployment/03-keda`](../06-deployment/03-keda.md).

---

## 13. Tool registry pattern

Tools self-register at import. the registry maps slug → class. instances are constructed per call with the execution context. No tool-side state.

See: [`02-runtime/02-tools`](../02-runtime/02-tools.md).

---

## 14. MCP servers as a parallel tool source

MCP servers are tool sources discoverable at runtime. The runtime client lists tools, registers them under `<server>.<tool>`, and dispatches the same way as native tools.

See: [`02-runtime/03-mcp`](../02-runtime/03-mcp.md).

---

## 15. Vendored SDK with sync-check

The Python SDK lives canonically at `packages/sdk/python/abenix_sdk/`. Every standalone app vendors a copy under `<app>/api/sdk/abenix_sdk/`. CI runs `scripts/sync-sdks.sh --check` on every commit. drift fails the build.

**Why vendoring** — the SDK runs inside Docker images of standalone apps. pinning a published version would create a release-coupling problem at scale.

---

## 16. PII-redacting span processor

Sensitive attributes (`llm.prompt`, `tool.args`, `agent.system_prompt`) are hash+length replaced before OTel export. Safe to share traces with support.

See: [`02-runtime/04-streaming-tracing`](../02-runtime/04-streaming-tracing.md#pii-redaction-in-spans).

---

## 17. Per-tenant rate limit + quota

Two layers:
- **Soft**: per-tenant rps + monthly token cap (Redis counters. `RateLimitMiddleware`).
- **Hard**: per-tenant `executions_per_day_cap` on `tenant_settings`.

Surface error code: `RATE_LIMITED` or `TENANT_QUOTA_EXCEEDED`.

---

## 18. Audit-by-default

Every mutating endpoint emits an `audit_logs` row via `log_action(db, tenant_id, user_id, action, metadata, resource_type, resource_id)`. Append-only. Never deleted. Compliance can export per tenant.

---

## 19. Schema migration policy: expand → backfill → contract

For risky migrations:
1. Add new column (expand) — old code keeps working.
2. Deploy backfill job.
3. Deploy code that reads/writes new column.
4. Wait one release cycle.
5. Drop old column (contract).

Never expand-and-contract in a single migration on a production table.

---

## 20. Idempotency keys

Every mutating SDK call accepts `client_token`. The server upserts on `(tenant_id, client_token)` and returns the prior response if it matches. Safe to retry network failures.

Example: `await client.execute(slug, input, client_token=f"scan-{corridor_id}-{date}")`.

---

## 21. Soft delete via status enum

Rows are rarely hard-deleted. Instead, `status` flips to `'deleted'`. List queries filter `status != 'deleted'`. The archive job moves cold rows out periodically.

---

## 22. Time-series via Timescale

`executions` is a Timescale hypertable on `created_at`. After 90 days rows compress. after 365 they move to cold storage. Keeps the hot index small.

See: [`06-deployment/02-helm`](../06-deployment/02-helm.md) and [`04-data-model/02-executions`](../04-data-model/02-executions.md).

---

## 23. Helm for platform, kubectl for standalone apps

Platform services are helm-managed. Standalone apps are kubectl-applied. Different release cadences. coupling them would cause cross-team blockers.

See: [`06-deployment/02-helm`](../06-deployment/02-helm.md).

---

## 24. Reconciliation sweepers in Celery beat

When NATS misses a terminal event (rare, but happens), a beat job in `worker` finds stuck-running executions every 60s and marks them failed. Same pattern for unsent notifications, expired approvals.

---

## 25. Bodhi rebrand pattern

The deployed cluster shows "Bodhi" branding (a demo brand) but HEAD source is always Abenix-named. Achieved by `scripts/apply-bodhi-and-deploy.sh` which sed-replaces at deploy time and reverts after. **Never** commit Bodhi-branded source.

---

## See also

- [00-overview](00-overview.md) — system overview that links to most of these
- [08-howto/04-debugging](../08-howto/04-debugging.md) — patterns under stress
