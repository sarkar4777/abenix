# Agent-to-agent communication

> Multi-agent orchestration sits on top of a single primitive — the `invoke_agent` tool — plus a Redis pub/sub channel that aggregates progress events across the whole call tree. Both pieces are small and worth reading top to bottom.

---

## The shape of a multi-agent call

Most multi-agent flows in this codebase follow a fan-out / fan-in pattern that looks like this.

```mermaid
sequenceDiagram
  autonumber
  participant Caller as Standalone app<br/>(Wingman API)
  participant Plat as Platform API
  participant Root as Root agent<br/>(desk-copilot)
  participant Sub1 as Sub-agent<br/>(arb-analyzer)
  participant Sub2 as Sub-agent<br/>(mispricing-extractor)
  participant Sub3 as Sub-agent<br/>(scenario-forecaster)
  participant Bus as Redis pub/sub

  Caller->>Plat: POST /agents/desk-copilot/execute
  Plat->>Root: dispatch (execution_id=R)
  Root->>Bus: subscribe channel R
  Root->>Root: invoke_agent("arb-analyzer", …)
  Root->>Plat: POST /agents/arb-analyzer/execute
  Plat->>Sub1: dispatch (execution_id=S1, parent=R)
  Sub1->>Bus: publish to channel R<br/>(sub_started, S1)
  par
    Root->>Plat: invoke_agent("mispricing-extractor", …)
    Plat->>Sub2: dispatch (S2, parent=R)
  and
    Root->>Plat: invoke_agent("scenario-forecaster", …)
    Plat->>Sub3: dispatch (S3, parent=R)
  end
  Sub1-->>Plat: completed
  Sub2-->>Plat: completed
  Sub3-->>Plat: completed
  Root->>Bus: publish (sub_finished, S1, S2, S3)
  Root->>Root: synthesise final brief from sub outputs
  Root-->>Plat: completed
  Plat-->>Caller: SSE stream + final output
```

Five things to notice.

1. The **fan-out** is just three back-to-back `invoke_agent` calls. The tool returns once the sub-agent's execution finishes. Concurrency is the caller's job — wrap them in `asyncio.gather` if you want parallel.
2. Every sub-execution gets a fresh `execution_id` and an explicit `parent_execution_id` pointing at the root.
3. Progress events from every level **publish to the root's channel**. The SSE consumer subscribes once and sees the whole tree.
4. The cost ledger on the root execution accumulates each sub's cost. The dashboard shows one cost number per top-level run.
5. There is no shared memory between sub-agents. They communicate only through their inputs (passed by the root) and their outputs (read by the root).

---

## The `invoke_agent` tool — every load-bearing line

The tool lives in [`apps/agent-runtime/engine/tools/invoke_agent.py`](../../apps/agent-runtime/engine/tools/invoke_agent.py). It does five things in order.

### 1. Resolve the agent by slug

```python
lookup = await client.get(f"/api/agents?search={slug}&limit=5", headers=headers)
match = next((a for a in items if (a.get("slug") or "").lower() == slug.lower()), None)
```

Search is case-insensitive. The first exact-slug match wins. A typo in the slug returns a clear "agent slug not found" tool error — the LLM sees the error and usually self-corrects on the next iteration.

### 2. Submit the sub-execution

```python
submit_body = {
    "message": json.dumps(payload),     # the agent input, JSON-encoded
    "stream": False,
    "wait_mode": "submitted",           # returns immediately with execution_id
}
submit_r = await client.post(f"/api/agents/{agent_id}/execute", ...)
sub_exec_id = submit_data["execution_id"]
```

`wait_mode = "submitted"` is the key flag. The tool does not block on the platform API. It gets an execution_id back, then takes over polling itself. This gives the tool full control over the timeout and lets it emit interim progress events.

### 3. Link the sub-execution to the root channel

```python
root_id = await progress.root_for(self._execution_id)
if root_id:
    await progress.set_parent(sub_exec_id, root_id)
    await progress.publish(self._execution_id, {
        "phase": "sub_started",
        "agent_slug": slug,
        "agent_name": match.get("name") or slug,
        "sub_execution_id": sub_exec_id,
    }, root_execution_id=root_id)
```

`progress.root_for` resolves "what is the *root* execution for the current run?" — if the current run is itself a sub, it walks one hop up. `set_parent` stores the child → root mapping in Redis. From then on, every progress event published by the sub-execution's runtime pod lands on the *root's* SSE channel.

This is what makes nested fan-outs work. A root invokes A. A invokes B. B's events still publish to the root's channel because B's `set_parent` walked up through A and found the root.

### 4. Poll until terminal

```python
deadline = t0 + timeout       # default 240s, max 600s
while time.time() < deadline:
    await asyncio.sleep(2.0)
    poll_r = await client.get(f"/api/executions/{sub_exec_id}", headers=headers)
    status = poll_r.json()["data"].get("status", "running").lower()
    if status in {"completed", "succeeded", "failed", "error", "cancelled"}:
        break
```

Two-second polling. Stops on any terminal state. If the deadline hits first, the tool emits a `sub_timeout` event and returns a tool error to the LLM — which can decide whether to retry, fall back, or give up.

### 5. Parse the output and return the envelope

```python
parsed = json.loads(output) if isinstance(output, str) else output
envelope = {
    "agent_slug": slug,
    "agent_id": agent_id,
    "execution_id": sub_exec_id,
    "status": row.get("status") or "completed",
    "output": parsed,
    "duration_ms": row.get("duration_ms") or duration_ms,
    "cost_usd": row.get("cost"),
}
return ToolResult(content=json.dumps(envelope, default=str), metadata={"agent_slug": slug})
```

The envelope is what the calling LLM sees in its tool result. `output` is the sub-agent's parsed JSON. `cost_usd` lets the LLM reason about cost if it has been prompted to. The `metadata` field is for the runtime's accounting — the LLM does not read it.

If the sub's output is markdown-fenced JSON, the parse fallback finds the first balanced `{...}` block and extracts that. If it cannot parse anything sensible it returns `{"raw": "<first 2000 chars>"}` — the calling agent will see a string, not a structured output, and that is enough information for it to decide what to do.

---

## The Redis pub/sub channel — one root, one channel, all levels

The events that drive the live UI come from [`apps/agent-runtime/engine/progress.py`](../../apps/agent-runtime/engine/progress.py). Three primitives.

```python
async def set_parent(child_execution_id: str, root_execution_id: str) -> None:
    """Map child to root. Stored as Redis SET key: progress.parent.<child> -> <root>."""

async def root_for(execution_id: str) -> str:
    """Walk up at most 8 hops to find the root. Returns "" if none."""

async def publish(execution_id: str, event: dict, root_execution_id: str = None) -> None:
    """Publish to the root's channel: progress.<root_execution_id>."""
```

Channel naming is `progress.<root_execution_id>`. The API server's SSE bridge subscribes when a client opens the stream and unsubscribes when the client disconnects. There is no buffering — events that arrive while no subscriber is attached are lost. (Critical paths like terminal `completed` events are *also* persisted to the executions table, so the UI can poll if it missed the live tick.)

### Event types you will see

| Phase | Emitted by | Carries |
|---|---|---|
| `agent_started` | runtime pod | execution_id, agent_slug, model |
| `iteration_start` | runtime pod (each loop) | iteration index, prior tool count |
| `tool_call` | runtime pod | tool name, args (redacted), iteration |
| `tool_result` | runtime pod | tool name, duration, is_error |
| `sub_started` | invoke_agent | sub_execution_id, agent_slug |
| `sub_finished` | invoke_agent | sub_execution_id, status, duration_ms, cost_usd |
| `sub_timeout` | invoke_agent | sub_execution_id, timeout_seconds |
| `agent_finished` | runtime pod | execution_id, status, cost_usd |

Every event has an `execution_id` (the emitter) and a `root_execution_id` (the subscriber's channel). The UI uses `execution_id` to draw the right node on the live DAG. It uses the channel as a coarse filter — every event for this top-level run, regardless of depth.

---

## Cost attribution across the tree

There is no special-case logic for "sum sub-costs into root". Each execution row carries its own `cost`, `anthropic_cost`, `openai_cost`, `google_cost`, `other_cost`. The dashboard's "total cost for top-level run" query is a simple recursive CTE on `parent_execution_id`.

```sql
WITH RECURSIVE tree AS (
  SELECT id, parent_execution_id, cost, agent_id
    FROM executions WHERE id = :root_execution_id
  UNION ALL
  SELECT e.id, e.parent_execution_id, e.cost, e.agent_id
    FROM executions e JOIN tree t ON e.parent_execution_id = t.id
)
SELECT SUM(cost) FROM tree;
```

This is the source of truth for the per-run cost shown on the executions list. If you ever see the dashboard report a smaller number than the sum of LLM provider invoices, the first place to look is whether some sub-execution wrote `cost = NULL` instead of `0`. The trigger that backfills cost from `(input_tokens, output_tokens, model)` only fires on insert — manually-inserted test rows can slip past it.

---

## When to use invoke_agent vs pipeline DAG

Both shapes exist and they overlap a lot. The rule of thumb:

| Use **invoke_agent** when… | Use a **pipeline** when… |
|---|---|
| The orchestration is dynamic — the LLM decides which sub-agents to call based on intent. | The orchestration is static — the same DAG runs every time, just with different inputs. |
| You need a single LLM context to synthesise sub outputs into a brief. | Each step is independent and the merge logic is simple (zip, join, concat). |
| You want full LLM judgement on retries, fallbacks, and "is this answer good enough?". | You want reliable, deterministic behaviour with cheap-and-predictable retries. |
| There are 3–10 calls per run. | There are 10+ calls per run, or any forEach/while loops. |

The Wingman Desk Copilot is the canonical `invoke_agent` example. It looks at the trader's question, decides which 2–5 specialists to call, fires them, and writes a synthesised brief.

The Wingman Mispricing Scan is the canonical pipeline example. It always runs the same six tool calls in the same order with the same merge logic. There's no LLM judgement in the orchestration — the LLM only judges within each step.

Mixing the two is fine and common. A pipeline node with `type: agent` runs an `agent_step` wrapping an LLM call. An LLM step can call `invoke_agent` as a tool. The runtime doesn't care which way the call goes — every execution looks the same from the cost / audit / RBAC perspective.

---

## Trajectory recall — a meta pattern

A subset of multi-agent flows in this codebase use `recall_trajectory` as the first call in a copilot agent. The pattern is:

1. Call `recall_trajectory(query=<user question>)`. Returns up to K past runs whose intent text overlaps the new query.
2. Read what specialists those past runs invoked and what came out.
3. Decide which specialists to invoke this time, possibly adapted from the past plans.
4. Fan out with `invoke_agent`.
5. Synthesise and **write a new trajectory row** keyed by intent + outcome.

Trajectories live in their own table, keyed on `(tenant_id, intent_hash)` with the full plan + structured outputs + cost stored as JSONB. The store is described in [`docs/TRAJECTORY_MEMORY.md`](../TRAJECTORY_MEMORY.md). The recall tool is a thin SQL wrapper.

This is what lets the Wingman Desk Copilot get noticeably better the more it is used by the same desk. It is not RL. It is not fine-tuning. It is structured memory of "the last 200 plans that worked here".

---

## Sub-agent budgets and safeguards

Three hard limits keep multi-agent fan-outs from running away.

### Per-call timeout (240s default, 600s max)

`invoke_agent`'s `wait_timeout_seconds` argument is clamped between 30 and 600. A sub-agent that takes longer than the configured ceiling returns a tool error and frees the parent LLM to retry or fall back. The default of 240s is calibrated for "an agent that does a real KB search plus a couple of tool calls".

### Per-execution iteration budget

Every agent execution has a `max_iterations` ceiling (default 25, configurable per-agent). The runtime stops after that many tool-call rounds, regardless of whether the LLM thinks it is done. This is what stops a buggy LLM that gets stuck in "call this tool again, no really" from burning the whole budget.

### No re-delegation through invoke_agent

`invoke_agent` uses the runtime pod's internal service key for the sub-call. It does not propagate the parent execution's X-Abenix-Subject. The platform looks up the root execution's subject via `parent_execution_id` for audit / collection-scoping purposes. This means a compromised sub-agent cannot escalate to a different subject — the chain depth is enforced at the runtime boundary.

### No recursion depth check (yet)

There is currently no explicit `max_depth` on the call tree. In practice every agent has a bounded `max_iterations` so the tree terminates, but a recursive agent that always invokes itself would do so a lot of times before the budget cuts it off. The work-around for now is "do not build an agent that invokes itself recursively without an explicit base case in the prompt". A `max_depth` setting is in the backlog.

---

## Debugging a fan-out

When a multi-agent run goes wrong, the symptoms usually look like "the synthesised brief is missing something important" rather than a hard error. The reliable debugging sequence:

1. Open the **executions tree view** for the top-level run. It shows the root + every sub with status, duration, cost.
2. Click into the slowest or most-failing sub. The sub's own execution detail shows the LLM turns and tool calls.
3. If one sub returned `{"raw": "<text>"}` instead of structured JSON, that is the bug. The sub-agent's system prompt is not constraining its output shape. Fix it there.
4. If a sub succeeded but its output looks fine and the brief is still wrong, the bug is in the root's synthesis prompt — it is mis-reading the structured output. Look at the LLM turn where the root sees the tool result.

The OTel trace ties all of this together. One trace spans root + every sub + every LLM call. Search by `root_execution_id` in Tempo.

---

## See also

- [00-agent-execution](00-agent-execution.md) — single agent run, the building block
- [01-pipelines](01-pipelines.md) — static-DAG alternative
- [04-streaming-tracing](04-streaming-tracing.md) — how the SSE bridge subscribes to the root channel
- [05-approvals-hitl](05-approvals-hitl.md) — what happens when a sub-agent hits a human gate
- [TRAJECTORY_MEMORY](../TRAJECTORY_MEMORY.md) — the recall_trajectory backing store
