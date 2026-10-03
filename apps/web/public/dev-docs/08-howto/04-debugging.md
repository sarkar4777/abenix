# Debugging — common failure modes + how to chase them

> The problems you will actually hit, with the fastest path to a fix.

---

## The first move — always the same

When something's wrong:
1. **Get the `execution_id`** from the UI (URL or trace panel) or from the user.
2. **Open `/executions/{id}`** — status, `failure_code`, `error_message`, tool calls and node results.
3. **Click "View Trace"** to jump to Grafana Tempo, when traces are exported (see [04-observability](../06-deployment/04-observability.md#traces)).
4. **Read the pod logs** if neither helps.

If you don't have the execution_id, query Postgres:
```sql
SELECT id, status, failure_code, error_message, created_at
FROM executions
WHERE tenant_id = $1
  AND agent_id IN (SELECT id FROM agents WHERE slug = $2)
ORDER BY created_at DESC LIMIT 10;
```

Execution status is one of `running`, `completed`, `failed` or `cancelled`.
`failure_code` comes from `apps/api/app/core/failure_codes.py`, for example
`LLM_RATE_LIMIT`, `LLM_PROVIDER_ERROR`, `LLM_INVALID_RESPONSE`, `LLM_AUTH_ERROR`,
`CONFIG_UNKNOWN_MODEL`, `SANDBOX_TIMEOUT`, `SANDBOX_OOM`, `TOOL_ERROR`,
`TOOL_NOT_FOUND`, `MODERATION_BLOCKED`, `KILL_SWITCH`, `MODEL_NOT_ALLOWED`,
`BUDGET_EXCEEDED`, `INFRA_CRASH`, `INFRA_AUTH_ERROR` and `STALE_SWEEP`. The
`/alerts` page groups failures by it.

---

## #1 — Agent output is not the JSON you asked for

**Symptom**: the run completes but the output is prose or fenced JSON, or a
downstream pipeline node fails to parse it. Sometimes `failure_code` is
`LLM_INVALID_RESPONSE`.

**Fix**:
- Read `output_message` on the execution row. Is the schema realistic? 5 to 10 fields hold up, 30+ gets brittle.
- Tighten the system prompt — "Output STRICT JSON only, no prose, no fences."
- Add an example output to the prompt.

> **Trap** — the example output in the prompt is read by the LLM as "what good looks like." If your example numbers are stale, the LLM will produce stale numbers. Use `<placeholder>` syntax for time-dependent values.

---

## #2 — A tool call failed

**Symptom**: the tool node is red in the trace, the agent recovers or stops.

**Fix**:
- Open the tool call on `/executions/{id}`. The first `TOOL_RESULT_PERSIST_CHARS` (8000) characters of each result are kept on the row.
- Common: the provider rate-limited, a key expired, a network timeout.
- A tool that is not configured says so in its result. **Admin -> Tool Configuration** shows which keys are missing and where each value comes from.

---

## #3 — Execution stuck on `running`

**Symptom**: the page never reaches a final state, the live stream sends no terminal event.

**Cause**: the pod running it died mid-run (OOM or eviction), or a pipeline node hung.

**Fix**:
- Check for restarts: `kubectl -n abenix get pods -l app.kubernetes.io/name=agent-runtime` and `kubectl -n abenix describe pod <pod>`.
- Wait. The API scheduler's stale sweeper runs every 5 minutes and marks runs still `running` after `STALE_EXECUTION_MAX_MINUTES` (default 10) as `failed` with `failure_code=STALE_SWEEP`. The `abenix_stale_sweeps_total` metric counts them.
- A pipeline is cut off at the `pipeline.timeout_seconds` setting (default 300) with `SANDBOX_TIMEOUT`, see [platform settings](../09-reference/04-platform-settings.md#execution-limits).

---

## #4 — LLM rate-limit storm

**Symptom**: many runs fail with `LLM_RATE_LIMIT` within minutes. The cost panel spikes.

**Fix**:
- Find the offender:
  ```sql
  SELECT a.slug, count(*) FROM executions e JOIN agents a ON a.id = e.agent_id
  WHERE e.created_at > now() - interval '15 minutes' AND e.failure_code = 'LLM_RATE_LIMIT'
  GROUP BY 1 ORDER BY 2 DESC;
  ```
- Common cause: a trigger or webhook fanning out to many runs at once, or a pipeline with a large `max_iterations`.
- Short term: pause the trigger, or archive the agent.
- On a Claude subscription in exclusive mode, every request goes to one model. Lower `llm.subscription.default_model` or turn exclusive off.

---

## #5 — Knowledge search returns nothing

**Symptom**: `knowledge_search` comes back empty though documents were uploaded.

**Fix**:
- Check the documents: `SELECT filename, status, chunk_count, error_message FROM documents WHERE kb_id = $1`. Status should be `ready`. `degraded` means chunks were stored but the embedder was unavailable, so nothing is searchable by vector until it is re-embedded. `failed` carries the reason.
- Check the agent can read the collection. Being listed on the collection is not enough, it needs an `AgentCollectionGrant` with READ.
- Worker logs: `kubectl -n abenix logs deploy/abenix-worker --tail=200` and `deploy/abenix-cognify-worker`.
- A collection embedded with one embedder answers poorly to queries embedded with another. With no OpenAI or Azure key, both sides use the local hashed embedder, see [local setup](00-local-setup.md#knowledge-bases-without-an-embedding-key).

---

## #6 — Pipeline step fails but the error isn't obvious

**Fix**:
- Agent steps have their own child execution, linked by `parent_execution_id`. Open it for the real error.
- For tool steps, the step's entry in `node_results` on the parent row carries the error.
- The builder's validation chip scrolls the canvas to the offending node.
- Failed runs can be diagnosed by the Pipeline Surgeon, see [pipeline healing](../02-runtime/10-pipeline-healing-drift.md).

---

## #7 — Frontend toast shows "Server error (500)"

**Fix**:
- Browser DevTools → Network → the request → response body.
- Backend logs: `kubectl -n abenix logs -l app.kubernetes.io/name=api -f --tail=200`, or `logs/abenix-api.log` with `dev-local.sh`.
- Every API response carries `X-Request-ID`. Grep the logs for it.

If the response had `error_code` but the toast did not show it, the catch
probably ignores `e?.errorCode`:

```ts
toastError(
  `Failed (${e?.errorCode || e?.status || "unknown"})`,
  e?.message,
);
```

---

## #8 — A webhook receiver rejects Abenix's signature

**Symptom**: your endpoint refuses outbound event or approval webhooks.

**Fix**:
- Outbound events are signed with the subscription's signing secret, shown once when the subscription is created. Details and the exact header in [outbound events](../02-runtime/19-outbound-events.md).
- The approval webhook (`PUT /api/approvals/webhooks`) sends `X-Abenix-Signature: sha256=<hex>`, an HMAC-SHA256 of the raw JSON body with the secret you set.
- Verify against the raw body. A proxy or framework that re-serialises JSON breaks the signature.
- Delivery history and replay: `GET /api/webhooks/{id}/deliveries` and `POST /api/webhooks/deliveries/{delivery_id}/redeliver`.

---

## #9 — Approval gate never resumes

**Symptom**: someone signed off but the run did not continue.

**Fix**:
- Check the approval row: `SELECT status, decided_at FROM approvals WHERE id = $1`. Status is `pending`, `approved`, `denied`, `expired` or `returned`.
- `GET /api/approvals/{id}/wait?timeout_seconds=60` long-polls one approval until it leaves `pending`, useful to see what the waiting side sees.
- If it expired before anyone decided, the run ends rather than resumes. Check the gate's `expires_seconds`.

See [approvals](../02-runtime/05-approvals-hitl.md).

---

## #10 — `ImagePullBackOff` after a deploy

**Fix**:
- Right after `deploy-azure.sh ... --only=...`, you hit [the --only trap](../06-deployment/deploy-only-trap.md). `helm rollback abenix -n abenix`, then `bash scripts/deploy-azure.sh redeploy` in full.
- Check the tag exists: `az acr repository show-tags -n <acr> --repository api --top 5`.
- Check the ACR attach: `az aks check-acr -n abenix-aks -g abenix-rg --acr <acr>.azurecr.io`. Re-run `bash scripts/deploy-azure.sh provision` to attach again.
- Edge runtime pods: the image is pinned, never rebuilt. Do not set `EDGE_IMAGE_TAG` to the git SHA.

---

## #11 — `OAuth access token has been revoked`

**Symptom**: every run fails with `LLM_AUTH_ERROR` on a cluster using a Claude subscription.

**Fix**: the subscription token rotated. Run `bash scripts/sync-claude-subscription.sh`, then confirm with `POST /api/admin/settings/subscription/verify`.

---

## #12 — Wingman shows "data unavailable"

**Symptom**: home cards say "No recent scan."

**Fix**:
- The agent failed. Wingman keeps only agent-produced numbers, so the cache stays empty until a run succeeds.
- Trigger a fresh scan from the lens page and open the resulting execution. Usually a tool key is missing.
- See [`07-standalone-apps/01-wingman`](../07-standalone-apps/01-wingman.md).

---

## #13 — Custom MCP server isn't loading

**Symptom**: the connection fails to register, or its tools never appear.

**Fix**:
- `400 host '<yours>' not in MCP_ALLOWED_HOSTS` means the host is not allowed. Add it to `mcpAllowedHosts` in the Helm values, see [env vars](../09-reference/01-env-vars.md#mcp-servers).
- For a remote server, test reachability from inside the API pod: `kubectl -n abenix exec deploy/abenix-api -- curl -sS <endpoint>`.
- Check the API logs around the register call for the handshake error.

---

## #14 — Slow pages with many records

**Fix**:
- Check the request in DevTools. A list endpoint returning hundreds of rows is the usual cause, use its paging parameters.
- `SQL_ECHO=1` on a local API logs every statement, which shows N+1 queries quickly. Never in production.

---

## #15 — Code execution times out

**Symptom**: `code_executor` stops at 30 seconds, or a sandbox run ends with `SANDBOX_TIMEOUT`.

**Fix**:
- `code_executor` is an in-process Python sandbox with a fixed 30 second limit, no network and an import allow-list. It is for small computations.
- For real workloads use a code asset or `sandboxed_job`. Their budget is the `sandbox.timeout_seconds` setting (default 300, up to 1800).
- A code asset needs network granted explicitly, `allow_network`, and the cluster's `SANDBOXED_JOB_ALLOW_NETWORK` has to allow it.

---

## Tracing checklist (when nothing else helps)

```bash
# 1. Get the execution_id from the user / UI
EID=...

# 2. Read the row, including trace_id
kubectl -n abenix exec deploy/abenix-api -- python -c "
import asyncio, asyncpg, os
async def go():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'].replace('+asyncpg','').split('?')[0])
    row = await conn.fetchrow('SELECT trace_id, status, failure_code, error_message FROM executions WHERE id = \$1', '$EID')
    print(dict(row))
asyncio.run(go())
"

# 3. Open Grafana Explore with that trace_id

# 4. If there is no trace, grep the runtime pools and the API
kubectl -n abenix logs -l app.kubernetes.io/name=agent-runtime --tail=500 --prefix | grep $EID
kubectl -n abenix logs -l app.kubernetes.io/name=api --tail=500 --prefix | grep $EID
```

---

## See also

- [02-runtime/04-streaming-tracing](../02-runtime/04-streaming-tracing.md) — events + OTel
- [06-deployment/04-observability](../06-deployment/04-observability.md) — Prom + Tempo + Grafana
- [06-deployment/disaster-recovery](../06-deployment/disaster-recovery.md) — when the platform itself is down
- [05-testing](05-testing.md) — testing + reproducing in CI
