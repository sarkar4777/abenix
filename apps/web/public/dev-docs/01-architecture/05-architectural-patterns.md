# Architectural patterns reference

> Every recurring shape in the codebase. If you see a piece of code and wonder "why is it built this way?", read the matching entry here. Each pattern lists its file home, its rationale, and the failure mode you get if you violate it.

---

## Tenant and identity patterns

### 1. Tenant-scoped everything

Domain rows carry `tenant_id` (`TenantMixin` in [`packages/db/models/base.py`](../../packages/db/models/base.py)). Every query filters on it. `TenantMiddleware` puts the tenant on `request.state.tenant_id`. Route handlers get the user, and with it `user.tenant_id`, from `Depends(get_current_user)`.

```python
@router.get("/widgets")
async def list_widgets(user = Depends(get_current_user), db = Depends(get_db)):
    return await db.execute(select(Widget).where(Widget.tenant_id == user.tenant_id))
```

**Violation symptom** — a missing `WHERE tenant_id = …` silently surfaces another tenant's data. Nothing in the deploy gates catches it. `scripts/verify-schema.sh` and the sentinel check only confirm that listed columns exist, so review is the guard.

### 2. actAs (delegated subject)

A service-account API key acts on behalf of an end user through the `X-Abenix-Subject` header, a JSON object with `subject_type` and `subject_id` ([`apps/api/app/core/acting_subject.py`](../../apps/api/app/core/acting_subject.py)). The key must carry the `can_delegate` scope, otherwise `get_current_user` answers 403. The execution row records the subject in `subject_type` and `subject_id`. Subject policies (`subject_policies`) are managed under `/api/access-control/policies`, with a `/api/access-control/test` endpoint to try a rule.

```python
subject = ActingSubject(subject_type="wingman", subject_id=trader.id, email=trader.email)
result = await client.with_subject(subject).execute(slug, input)
```

See [01-tenants-rbac](01-tenants-rbac.md) for the full chain.

### 3. Subject-scoped collection auto-resolution

When an acting subject is present, `resolve_agent_collections` ([`apps/api/app/services/collection_access.py`](../../apps/api/app/services/collection_access.py)) also includes the collection named `{subject_type}-{subject_id}`, if a ready one exists in the tenant. The standalone apps create these collections on demand. This is how per-trader memory works without a grant row per trader.

### 4. Polymorphic resource sharing

One table, `resource_shares`, handles sharing for seven kinds: `agent`, `pipeline`, `ml_model`, `code_asset`, `knowledge_base`, `saved_tool`, `atlas_graph` (`_SHAREABLE_KINDS` in [`apps/api/app/routers/me.py`](../../apps/api/app/routers/me.py)). Permissions rank `VIEW` < `EXECUTE` < `EDIT`. Shares can carry `expires_at`. Revoking deletes the row.

```python
ids = await accessible_resource_ids(db, user, kind="ml_model", minimum_permission=SharePermission.EXECUTE)
```

`accessible_resource_ids` lives in [`apps/api/app/core/permissions.py`](../../apps/api/app/core/permissions.py).

### 5. Audit-by-default

Mutating endpoints call `log_action()` ([`apps/api/app/core/audit.py`](../../apps/api/app/core/audit.py)), which writes an `activity_logs` row with the key holder's `user_id`, the action, resource, old and new values, address and user agent. The table is append-only and hash-chained, see [07-governance](07-governance.md#tamper-evident-audit-log). The delegated subject is recorded on the execution row (`subject_type`, `subject_id`), not on the audit row.

---

## Data and persistence patterns

### 6. JSONB for flex fields

`agents.model_config` (with the pipeline DAG inside it as `pipeline_config`), `executions.tool_calls`, `executions.node_results`, `executions.provenance`, `atlas_nodes.properties`, `tool_invocations.output_metadata` are all JSONB. Structural validation happens at the API/SDK boundary, not at the column level.

**When to add a JSONB field vs a column** — used by all rows + queried often → column. Sometimes-present, schema-evolving, used mostly for read-back → JSONB. Never put `tenant_id`, status, or anything you'll group by in JSONB.

### 7. Soft delete via status

Agents and pipelines are not hard-deleted. `DELETE /api/agents/{id}` sets `status` to `archived`. Regular reads hide archived agents, `GET /api/agents/deleted` lists them, and `POST /api/agents/{id}/restore` brings one back with its triggers.

Separately, the `nightly_archive` job dumps recording tables (`executions`, `messages`, `activity_logs`, the `*_invocations` tables) past their retention to object storage and deletes them.

**Trap** — `DELETE FROM agents …` directly in psql fails on the foreign keys from `executions` and `agent_revisions`. Always use the API.

### 8. Idempotency keys

`POST /api/agents/{id}/execute` honours an `Idempotency-Key` header on non-streaming calls. The server keys on `(tenant_id, key)` in `execution_idempotency` for 24 hours and returns the stored response with `idempotent_replay: true` on a repeat. Approvals take a `client_token` in the body and dedupe on `(tenant_id, client_token)`.

```bash
curl -X POST .../api/agents/my-agent/execute -H "Idempotency-Key: scan-$CORRIDOR-$DATE" -d '{"message": "...", "stream": false}'
```

See [09-state-machines](../02-runtime/09-state-machines.md#idempotency--collapsing-retries-on-the-wire).

### 9. Schema migration policy — expand → backfill → contract

For risky migrations: add new column (expand), deploy backfill job, deploy code reading/writing new column, wait one release cycle, drop old column (contract). Never expand-and-contract in one migration on a production table.

### 10. Schema drift catchup migration

`packages/db/alembic/versions/x4y5z6a7b8c9_schema_drift_catchup.py` is idempotent and information_schema-guarded. It picks up any columns that exist in the ORM but not in the database. Re-running is always safe. The `scripts/_schema-sentinels.sh` file is the single source of truth for which columns must exist post-migration.

### 11. Retention through the nightly archive

There are no hypertables in the main database. Hot tables stay small through the nightly archive: rows past retention (30 days for `*_invocations`, 60 for `executions` and `messages`, 90 for `activity_logs`, overridable per tenant in `retention_policies`) are dumped to `archives/<tenant>/<run>.jsonl.gz` and deleted. See [`apps/api/app/services/archiver.py`](../../apps/api/app/services/archiver.py).

### 12. Sentinel-column verification gate

Both `dev-local.sh` and `deploy-azure.sh` run a post-migration check against `scripts/_schema-sentinels.sh`. If any sentinel column is missing, deploy stops with a clear error. This catches "migration script ran but didn't actually do what it said" — a recurring class of failure before this gate existed.

---

## Runtime and execution patterns

### 13. The four-pool runtime

Four agent-runtime Deployments on Azure (`default`, `chat`, `heavy-reasoning`, `long-running`) isolate workloads. Each is scaled by KEDA on the lag of its own JetStream consumer. A Monte-Carlo on heavy-reasoning never starves chat.

- Pool picker: [`apps/api/app/routers/agents.py`](../../apps/api/app/routers/agents.py) reads the `agents.runtime_pool` column, set from `/admin/scaling` or the agent YAML. `inline` keeps the run on the API pod.
- Deployment manifests: [`infra/helm/abenix/templates/agent-runtime-pools.yaml`](../../infra/helm/abenix/templates/agent-runtime-pools.yaml), one Deployment per entry in `scaling.pools`.
- KEDA ScaledObjects: see [06-deployment/03-keda](../06-deployment/03-keda.md).

### 14. Three-tier resolution with fail-loud

For data-producing endpoints:

```
Tier 1: live agent → real-service tools → ML models     (preferred)
Tier 2: cached prior result (if fresh)                  (fast path)
Tier 3: explicit "no data" envelope                     (fail-loud)
```

**No synthesis tier.** If the agent fails, the UI shows "no recent scan" rather than fabricating numbers. Trader trust > availability.

### 15. Approval gates block in the pod

Approval gates hold the run inside its pod. The `approval_gate` tool creates an `approvals` row and polls it every 2 s. The `human_approval` tool, which tier escalation also uses, keeps the gate in Redis (`hitl:approval:*`) and polls it every 2 s. Both set `hitl:waiting:<execution_id>`, so the stale sweeper does not fail a run that is waiting on a person. The run stays `running` until the gate resolves or times out. Nothing saves the loop to the database.

- Gate tools: [`engine/tools/approval_gate.py`](../../apps/agent-runtime/engine/tools/approval_gate.py), [`engine/tools/human_approval.py`](../../apps/agent-runtime/engine/tools/human_approval.py).
- Approval endpoints: [`apps/api/app/routers/approvals.py`](../../apps/api/app/routers/approvals.py), HITL decisions through [`apps/api/app/core/hitl.py`](../../apps/api/app/core/hitl.py).
- Full flow doc: [02-runtime/05-approvals-hitl](../02-runtime/05-approvals-hitl.md).

### 16. SSE bridge over Redis pub/sub

Execution events travel over Redis, not NATS. The API and the runtime publish to `exec:events:<execution_id>` and append to a replay list of the last 500 events with a 1 h TTL. `GET /api/executions/{id}/stream` replays the list and then follows live, so a client that reconnects gets what it missed.

Tool-level narration for a whole agent tree goes on a second channel, `progress:<root_execution_id>`, whose prefix each app can change with `PROGRESS_CHANNEL_PREFIX`.

- Event bus: [`apps/api/app/core/execution_bus.py`](../../apps/api/app/core/execution_bus.py), and `_publish` in [`apps/agent-runtime/consumer.py`](../../apps/agent-runtime/consumer.py).
- Progress publisher: [`apps/agent-runtime/engine/progress.py`](../../apps/agent-runtime/engine/progress.py).
- SSE routes: [`apps/api/app/routers/executions.py`](../../apps/api/app/routers/executions.py) (`stream` and `watch`).
- Full streaming + tracing doc: [02-runtime/04-streaming-tracing](../02-runtime/04-streaming-tracing.md).

### 17. Root-execution channel aggregation

When an agent calls `invoke_agent`, the tool registers the child execution under its root (`set_parent`, key `parent:<child_id>`). The child's progress events then go to the **root's** channel, so a subscriber sees the whole tree on one stream.

- Lookup: `root_for(execution_id)` in [`apps/agent-runtime/engine/progress.py`](../../apps/agent-runtime/engine/progress.py) is one Redis read and falls back to the run's own id. Children are registered against the root directly, so there is no walk up the tree.
- Registration: [`apps/agent-runtime/engine/tools/invoke_agent.py`](../../apps/agent-runtime/engine/tools/invoke_agent.py).

### 18. Distributed tracing

The API and the runtime both call `init_tracing` ([`apps/agent-runtime/engine/tracing.py`](../../apps/agent-runtime/engine/tracing.py)) and export to Tempo over OTLP. The API also turns on FastAPI and httpx auto-instrumentation, so a caller that sends a W3C `traceparent` header continues its trace in the API, and outbound httpx calls carry it on. The SDKs do not inject `traceparent` themselves.

The queue hop carries the context too. The NATS backend puts the `traceparent` in the envelope's `trace` field and the consumer starts its `agent_runtime.run` span under it. `invoke_agent` sends the header on the execute call it makes for a child agent, and the runtime's HTTP server continues any incoming `traceparent`. So with `OTEL_EXPORTER_OTLP_ENDPOINT` set, one trace spans the API, the queue, the runtime and child runs. The consumer records the trace id on `executions.trace_id`, which is how the run page links to Tempo.

### 19. Self-healing pipelines via error_branch

Each pipeline node has `on_error`: `stop` (default), `continue` or `error_branch`. With `error_branch` and an `error_branch_node`, a failure routes to that recovery node. Recovery nodes often call a meta-agent that decides whether to retry, escalate, or skip.

- Edge resolver: [`apps/agent-runtime/engine/pipeline.py`](../../apps/agent-runtime/engine/pipeline.py) — search for `on_error`.
- Per-node fail-fast vs failure-isolated branching: [02-runtime/07-pipeline-data-flow](../02-runtime/07-pipeline-data-flow.md#error-handling--on_error).
- Full self-healing + drift doc: [02-runtime/10-pipeline-healing-drift](../02-runtime/10-pipeline-healing-drift.md).

### 20. Topological-sort scheduler with deterministic layer order

`_topological_sort()` in [`apps/agent-runtime/engine/pipeline.py`](../../apps/agent-runtime/engine/pipeline.py) returns `list[list[str]]` where each inner list can run concurrently. Within a layer, IDs are sorted for determinism, so the same pipeline always schedules in the same order. A cycle raises `ValueError` naming the nodes in it.

- Caller: `PipelineExecutor.execute()` in the same file.
- Tests: [`apps/agent-runtime/tests/test_pipeline.py`](../../apps/agent-runtime/tests/test_pipeline.py).

### 21. Whole-value vs embedded template semantics

`{{plan}}` as the entire string returns the structured value of `plan` unchanged. `"prefix {{plan}} suffix"` returns a string with `plan` interpolated, dicts and lists as JSON. A missing value becomes `[not available]`. The check is a full match on the string, so leading or trailing whitespace silently switches to the embedded behaviour.

- Resolver: `_resolve_templates()` in [`apps/agent-runtime/engine/pipeline.py`](../../apps/agent-runtime/engine/pipeline.py). `_resolve_inputs()` next to it handles explicit `input_mappings`.

### 22. Self-attaching tools with the `_DefaultedTool` wrapper

Tools configured with `parameter_defaults` are wrapped. The wrapper hides the defaulted parameters from the LLM's view of the schema, so the LLM never sees the pre-set blob hash or tenant ID it would have to guess. The wrapper merges the defaults back at execution time.

- Wrapper class: `_DefaultedTool` in [`apps/agent-runtime/engine/tools/base.py`](../../apps/agent-runtime/engine/tools/base.py).
- Where tools get wrapped: `ToolRegistry.apply_tool_config` in the same file.

### 23. In-process sandbox with domain whitelist

`ExecutionSandbox` ([`apps/agent-runtime/engine/sandbox.py`](../../apps/agent-runtime/engine/sandbox.py)) enforces:

- A per-execution wall clock timeout, `SANDBOX_TIMEOUT_SECONDS` (300) or the `sandbox.timeout_seconds` platform setting.
- A tool call cap, 50 per run.
- An output size cap, 250 000 characters.
- A network domain whitelist of 13 hardcoded domains for first-party tools.

Violations are recorded as `SandboxViolation` entries. Container-level failures from sandboxed jobs map to `SANDBOX_TIMEOUT`, `SANDBOX_OOM`, `SANDBOX_NONZERO_EXIT` and `SANDBOX_IMAGE_BLOCKED`.

### 24. MCP destructive-hint approval gate

MCP tools annotated with `destructiveHint: true` require explicit approval. Read-only tools auto-approve while the policy's `auto_approve_read_only` is on, which is the default. `MCPSecurityContext` in [`apps/agent-runtime/engine/mcp_security.py`](../../apps/agent-runtime/engine/mcp_security.py) keeps the audit trail of every call.

### 25. Provider-cost ledger with per-provider columns

`executions.{anthropic_cost, openai_cost, google_cost, other_cost}` sum to `executions.cost`. Lets dashboards split spend by provider. Rates come from the `llm_model_pricing` table, cached for 60 s in [`apps/agent-runtime/engine/llm_router.py`](../../apps/agent-runtime/engine/llm_router.py) so admin edits propagate, with `DEFAULT_PRICING` in the same file as the fallback.

### 26. Reconciliation sweepers in the API scheduler

There is no Celery beat. Sweepers run on APScheduler in the API pod ([`apps/api/app/core/scheduler.py`](../../apps/api/app/core/scheduler.py)), each under a Postgres advisory lock so one replica does the work. `sweep_stale_executions` flips runs still `running` after `STALE_EXECUTION_MAX_MINUTES` (10) to failed with `STALE_SWEEP`, skipping runs waiting on an approval and runs whose queue lease is still live. `escalate_approvals` escalates overdue tiered approvals every 15 minutes. `reconcile_active_executions_gauge` re-syncs the gauge every 5. These catch the case where a pod died before writing terminal status.

---

## Error handling and observability patterns

### 27. Structured error envelope

Every non-2xx HTTP response built with `error()` ([`apps/api/app/core/responses.py`](../../apps/api/app/core/responses.py)) is `{data: null, error: {message, code, error_code?, details?}}`. UI code branches on stable `error_code` strings such as `EVAL_GATE` or `KILL_SWITCH`.

### 28. PII-redacting span processor

Sensitive span attributes (`llm.prompt`, `llm.completion`, `llm.messages`, `tool.args`, `tool.input`, `tool.output`, `agent.system_prompt`, `agent.input_message`, `agent.output_message` and a few more) are replaced before export. `_redact_value()` in [`engine/tracing.py`](../../apps/agent-runtime/engine/tracing.py) returns `<redacted len=N sha256=XXX>`.

**Known gap** — redaction is by attribute key. An attribute outside the key list exports as-is, so don't put customer records into custom span attributes.

### 29. Failure-code taxonomy with stable strings

`executions.failure_code` is an indexed string. `classify_exception` in [`apps/api/app/core/failure_codes.py`](../../apps/api/app/core/failure_codes.py) maps an error to one code by ordered regex rules, for example `STALE_SWEEP`, `LLM_RATE_LIMIT`, `LLM_PROVIDER_ERROR`, `LLM_AUTH_ERROR`, `SANDBOX_TIMEOUT`, `MODERATION_BLOCKED`, `KILL_SWITCH`, `MODEL_NOT_ALLOWED`, `TOOL_NOT_FOUND`, `TOOL_ERROR`, `BUDGET_EXCEEDED`, `INFRA_CRASH`, with `UNKNOWN_ERROR` as the fallback. Alerts group on it. See [09-state-machines](../02-runtime/09-state-machines.md#failure-code-taxonomy).

### 30. Lazy Prometheus metric registration

`_safe_metric()` in [`engine/metrics.py`](../../apps/agent-runtime/engine/metrics.py), and `_safe_counter`, `_safe_gauge`, `_safe_histogram` in [`app/core/telemetry.py`](../../apps/api/app/core/telemetry.py), register a metric only if one with the same name isn't already there. A module imported twice, or the runtime engine loaded inside the API, no longer raises "metric already registered".

### 31. Rate limits, daily caps and monthly quotas

Three layers, all before the execution row is written:

- `RateLimitMiddleware` keeps per-user and per-IP sliding windows in Redis (`abenix:ratelimit:*`). In production the user limit defaults to 300 requests a minute, `RATE_LIMIT_USER_REQ_PER_MIN` overrides it. Over the limit is a 429 with `Retry-After`.
- `check_limit` in [`apps/api/app/core/usage.py`](../../apps/api/app/core/usage.py) enforces the tenant's daily execution cap for its plan.
- `check_user_quota` enforces the user's monthly token and cost allowance.

The last two answer 429 from the execute handler, so a tenant over quota cannot fill the runtime backlog.

---

## Deployment and packaging patterns

### 32. Vendored SDK with sync-check

The Python SDK lives canonically at `packages/sdk/python/abenix_sdk/`. The vertical apps that live in this repo vendor a copy under `<app>/api/sdk/abenix_sdk/`. `dev-local.sh` and `deploy-azure.sh` both run `scripts/sync-sdks.sh --check` and stop on drift. The CI workflow does not run it.

**Why vendor** — the SDK runs inside the standalone app's Docker image. Pinning a published version would create a release-coupling problem. Vendoring keeps the example deployments simple. **Third-party apps outside this repo should `pip install abenix-sdk`** — vendoring is an in-repo convenience, not a recommendation.

### 33. Helm for platform, kubectl for example standalones

Platform services are helm-managed. The in-repo standalone apps ship a manifest under `<app>/k8s/` that `deploy-azure.sh` applies with `kubectl apply`. Different release cadences. Coupling them would create cross-team blockers. Third-party apps follow whatever pattern fits their stack.

### 34. KEDA dual-trigger autoscaling

Each runtime pool's ScaledObject has a queue trigger, JetStream consumer lag, and a Prometheus p95-duration trigger when `scaling.keda.prometheusUrl` is set (threshold 90 s). KEDA takes whichever demands more replicas. The p95 trigger catches "queue is short but each item is slow", which the lag trigger alone misses. See [08-queue-scaling](../02-runtime/08-queue-scaling.md).

### 35. Rebrand script, not used

`scripts/apply-bodhi-and-deploy.sh` can sed-replace the brand at deploy time and revert afterwards. It is not part of the standard deploy and the cluster runs Abenix branding end to end. **Never** commit rebranded source.

### 36. Per-pool concurrency tuning

`AGENT_CONCURRENCY` comes from each pool's `concurrency_per_replica` in the values (default 3). On Azure: `default` 3, `chat` 6, `heavy-reasoning` 2, `long-running` 1, because each long-running execution can hold a connection to an external service for minutes.

### 37. Standalone-key reconciler in dev-local

`scripts/dev-local.sh` runs an idempotent reconciler that mints `<APP>_ABENIX_API_KEY` for every standalone app before launch. Already-valid keys are reused. New keys upsert and the script exports them so the app's start.sh inherits the value.

---

## UI patterns

### 38. The apiFetch + structured error envelope contract

`apiFetch` ([`apps/web/src/lib/api-client.ts`](../../apps/web/src/lib/api-client.ts)) parses the structured error envelope, throws `ApiError` on a non-2xx from a mutating method (or any method with `throwOnError: true`), and returns parsed JSON on success. UI components branch on `err.errorCode` for stable handling. See [05-ui/02-api-client](../05-ui/02-api-client.md).

### 39. React Flow canvas with custom node types

The Agent Builder and Pipeline Builder use React Flow with custom node types. The builder registers `agent`, `tool`, `knowledge` and `mcp` ([`components/builder/nodes.tsx`](../../apps/web/src/components/builder/nodes.tsx)). The pipeline canvas adds `pipelineStep`, `condition`, `output`, `forEachStep`, `agentStep`, `switchNode` and `mergeNode` ([`components/builder/pipeline/PipelineNodes.tsx`](../../apps/web/src/components/builder/pipeline/PipelineNodes.tsx)).

### 40. SWR + targeted `mutate` for list pages

Lists are fetched through `useApi` ([`apps/web/src/hooks/useApi.ts`](../../apps/web/src/hooks/useApi.ts)), a thin wrapper over SWR that exposes `mutate`. After a change, the page revalidates its own key rather than the whole cache.

### 41. Resource share dialog as a generic mount

`ResourceShareDialog` ([`components/share/ResourceShareDialog.tsx`](../../apps/web/src/components/share/ResourceShareDialog.tsx)) is one component used on the resource pages (knowledge, ML models, code runner, Atlas). The page passes `(resource_type, resource_id)` and the dialog handles the rest. A new resource kind also needs adding to `_SHAREABLE_KINDS` on the API.

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

- **One-off experiments**. A throwaway script that wants to test "does this prompt work?" does not need actAs, idempotency, or approval gates. Use the raw HTTP API and move on.
- **Performance-critical tight loops**. A high-volume inbound webhook handler that wants to call the platform 1k+ times a second should *not* go through the standard SDK. Use the batch endpoints under `/api/batch` or skip the platform entirely if the work is truly stateless. Don't pretend the regular path will scale.

In both cases, the violation should be documented at the call site so the next reader knows why the usual pattern doesn't apply.

---

## See also

- [00-overview](00-overview.md) — high-level system view linking back to many of these patterns.
- [02-runtime/06-agent-to-agent](../02-runtime/06-agent-to-agent.md) — patterns 16, 17, 25 in action.
- [02-runtime/07-pipeline-data-flow](../02-runtime/07-pipeline-data-flow.md) — patterns 19, 20, 21.
- [02-runtime/08-queue-scaling](../02-runtime/08-queue-scaling.md) — patterns 13, 34, 36.
- [02-runtime/09-state-machines](../02-runtime/09-state-machines.md) — patterns 7, 8, 15, 29.
- [08-howto/04-debugging](../08-howto/04-debugging.md) — patterns under stress.
