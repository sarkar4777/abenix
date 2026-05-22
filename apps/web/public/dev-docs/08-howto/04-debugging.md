# Debugging — common failure modes + how to chase them

> The 15 problems you'll actually hit, ranked by frequency, with the fastest path to a fix.

---

## The first move — always the same

When something's wrong:
1. **Get the `execution_id`** from the UI (URL or trace panel) or from the user.
2. **Open `/executions/{id}`** — the trace + tool waterfall + raw payload.
3. **Click "View Trace"** to jump to Grafana Tempo for the distributed view.
4. **`kubectl -n abenix logs ...`** if Tempo is unhelpful.

If you don't have the execution_id, query Postgres:
```sql
SELECT id, status, failure_code, error_message
FROM executions
WHERE tenant_id = $1
  AND agent_id IN (SELECT id FROM agents WHERE slug = $2)
ORDER BY created_at DESC LIMIT 10;
```

---

## #1 — Agent output is JSON-parse-fail

**Symptom**: execution `status='completed'` but `failure_code='output_schema'`, `output.parsed=null`, `output.raw` has the LLM's text.

**Cause**: The LLM didn't produce valid JSON matching `model_config.output_schema`.

**Fix**:
- Inspect `output.raw` — is the schema realistic? LLMs handle 5-10 fields gracefully. 30+ fields gets brittle.
- Tighten the system prompt — explicit "Output STRICT JSON only, no prose, no fences."
- Add an example output in the prompt's `## Output` section.
- If the LLM consistently wraps in fences, the runtime's one-retry-with-feedback should fix it. If it persists, your prompt isn't strict enough.

> **Trap** — the example output in the prompt is read by the LLM as "what good looks like." If your example numbers are stale, the LLM will produce stale numbers. Use `<placeholder>` syntax for time-dependent values.

---

## #2 — Tool call returns `is_error=true`

**Symptom**: trace shows a red tool node. the agent tries to recover or stops.

**Fix**:
- Click the tool node in the trace → view `metadata.error`.
- Common: external API rate-limited (Tavily, EIA), auth expired (Yahoo), network timeout.
- Check tool-specific env vars — `TAVILY_API_KEY` etc.

If the tool itself raised an exception, it bubbles to the runtime which catches it and writes `is_error=true`. The exception text is in `metadata.exception`.

---

## #3 — Execution stuck on `status='running'` forever

**Symptom**: dashboard never updates. SSE doesn't deliver a terminal event.

**Cause**: runtime pod OOM-killed mid-loop, NATS dropped the message, or a pipeline node hung.

**Fix**:
- Check `kubectl -n abenix top pods -l app=agent-runtime-default` for recent OOM.
- Wait — the reconciliation sweeper in `worker` marks stuck executions failed after `agent.timeout` (default 300s).
- Force-resolve: `UPDATE executions SET status='failed', failure_code='operator_force_resolve' WHERE id = $1`.

> **Why the sweeper** — without it, an OOM-killed pod would leave the row in `running` forever. The sweeper runs every 60s and unsticks stale rows.

---

## #4 — LLM rate-limit storm

**Symptom**: thousands of `LLM_RATE_LIMIT` errors in 5 minutes. Grafana cost chart spikes.

**Fix**:
- Identify the offender: `SELECT agent_slug, COUNT(*) FROM executions WHERE created_at > now() - interval '15 min' GROUP BY 1 ORDER BY 2 DESC;`
- Common cause: a webhook that fans out to N agents synchronously, or a misconfigured pipeline with no `max_iterations`.
- Short-term: pause the agent via `/agents → Edit → status=paused`.
- Long-term: add a `client_token` for idempotency + a tenant quota.

---

## #5 — Knowledge base returns no results

**Symptom**: `kb_search` returns empty array even though docs were uploaded.

**Fix**:
- Check the KB status: `SELECT * FROM knowledge_bases WHERE id = $1`. Status should be `ready`.
- Check chunk count: `SELECT COUNT(*) FROM kb_chunks WHERE kb_id = $1`. If 0, the ingest worker failed.
- Logs: `kubectl -n abenix logs deploy/cognify-worker | grep <doc_id>`.

Common causes:
- PDF parser choked on a scanned image (no OCR fallback wired by default).
- Embedding API key missing — check `OPENAI_API_KEY` / equivalent.
- Pgvector extension not installed (`CREATE EXTENSION vector;` should have run as part of migration).

---

## #6 — Pipeline step fails but error isn't shown

**Symptom**: pipeline run shows a red step but the error message is empty.

**Fix**:
- The step's child execution row has the real error. Click into the step in the trace.
- If the step is a tool (no sub-execution), inspect `pipeline_step_runs.error_payload`.
- Use the **validation chip** in the builder topbar — clicking it scrolls the canvas to the offending node (this was the audit's pass-1 fix).

---

## #7 — Frontend toast shows "Server error (500)"

**Symptom**: generic 500 toast, no detail.

**Fix**:
- Open browser DevTools → Network tab → find the request → look at the response body.
- Backend logs: `kubectl -n abenix logs -l app=abenix-api -f --tail=200`.
- Look for the `X-Request-ID` header → grep logs for that.

If the request body had `error_code` but the toast didn't show it, your frontend code probably has `toastError("Failed", e?.message)` without considering `e?.errorCode`. Update the catch:

```ts
toastError(
  `Failed (${e?.errorCode || e?.status || "unknown"})`,
  e?.message,
);
```

---

## #8 — Webhook signature verification fails

**Symptom**: `WEBHOOK_SIGNATURE_INVALID` on inbound webhooks.

**Fix**:
- Check the webhook secret in `tenant_settings.webhook_secrets`.
- The webhook source must compute HMAC-SHA256 of the raw body + send as `X-Abenix-Signature: sha256=<hex>`.
- Common cause: middleware or proxy modifies the body before the verifier runs — disable trim/whitespace mods in your reverse proxy.

---

## #9 — Approval gate never resumes

**Symptom**: human signs off but the execution stays `waiting_approval`.

**Fix**:
- Check `approvals.status` — should be `approved`.
- Check NATS: `kubectl -n abenix exec deploy/nats -- nats consumer report exec`.
- If the `exec.resume` message wasn't delivered, the worker's approval-router job will redeliver within 60s.
- Force: `UPDATE approvals SET status='approved' WHERE id = $1; UPDATE executions SET status='running' WHERE id = $2;` then publish manually.

---

## #10 — `ImagePullBackOff` after a deploy

**Symptom**: new pods can't pull the image.

**Fix**:
- Check the registry tag actually exists: `az acr repository show-tags -n your-acr --repository abenix-api --top 5`.
- Check the AKS-ACR attach is intact: `az aks check-acr -n abenix-aks -g abenix-rg --acr your-acr`.
- Re-attach if needed: `az aks update --attach-acr ...`.
- For cross-ACR migration, see [`feedback_publish_public_traps`](../) for the gotchas.

---

## #11 — Bodhi/Abenix branding flip on `abenix-web` rollout

**Symptom**: after a normal helm upgrade, the site shows "Abenix" instead of "Bodhi" (or vice versa).

**Fix**:
- Bodhi is applied at deploy time via `scripts/apply-bodhi-and-deploy.sh`. The HEAD source is always Abenix-named.
- Re-apply: `bash scripts/apply-bodhi-and-deploy.sh --with-wingman`.
- See [`feedback_bodhi_demo_rebrand`](../) memory for the rationale.

---

## #12 — Wingman corridor shows "data unavailable"

**Symptom**: home cards say "No recent scan."

**Fix**:
- The agent failed sanity. Cache is intentionally empty until the agent succeeds.
- Trigger a fresh scan: open Price at Risk Lens → click the corridor → fires `POST /api/wingman/mispricing/.../scan`.
- Inspect the resulting execution. usually a tool failure (Tavily key, EIA key, etc.).
- See [`07-standalone-apps/01-wingman`](../07-standalone-apps/01-wingman.md#three-tier-resolution-for-mispricing-scans).

---

## #13 — Custom MCP server isn't loading

**Symptom**: agent has `mcp_extensions` but the tools don't appear.

**Fix**:
- Check the runtime pod logs at startup for MCP handshake errors.
- `kubectl -n abenix logs deploy/agent-runtime-default | grep mcp`.
- For stdio MCP servers, the child process spawn errors are most common — check the `command` and `env` fields.
- For HTTP MCP servers, test reachability from inside the pod: `kubectl exec ... -- curl <endpoint>`.

---

## #14 — Slow page load on /agents with many agents

**Symptom**: list page takes 3-5s with 200+ agents.

**Fix**:
- It's the SSR render serialising 200 cards. Switch to client-side fetch (the page should already use `useApi`).
- Add pagination — `GET /api/agents?page=1&limit=50`.
- Collapse categories by default (already done in v1.5.x).

---

## #15 — Sandbox tool times out

**Symptom**: `code_executor` returns `timeout_seconds exceeded`.

**Fix**:
- Default is 30s. Bump per-call: `code_executor({code: ..., timeout_seconds: 120})`.
- Cap is 300s — beyond that, use a long-running pipeline node.
- If the code is doing network calls, check `network=true` is passed. Default sandbox has no network egress.

---

## Tracing checklist (when nothing else helps)

```bash
# 1. Get the execution_id from the user / UI
EID=...

# 2. Get the trace_id
kubectl -n abenix exec deploy/abenix-api -- python -c "
import asyncio, asyncpg, os
async def go():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'].replace('+asyncpg',''))
    row = await conn.fetchrow('SELECT trace_id, status, failure_code, error_message FROM executions WHERE id = \$1', '$EID')
    print(dict(row))
asyncio.run(go())
"

# 3. Open Grafana Explore with trace_id={trace_id}

# 4. If trace empty, fall back to logs across all 4 runtime pools:
for d in default chat heavy-reasoning long-running; do
  kubectl -n abenix logs -l app=agent-runtime-$d --tail=500 | grep $EID
done
```

---

## See also

- [02-runtime/04-streaming-tracing](../02-runtime/04-streaming-tracing.md) — events + OTel
- [06-deployment/04-observability](../06-deployment/04-observability.md) — Prom + Tempo + Grafana
- [05-testing](05-testing.md) — testing + reproducing in CI
