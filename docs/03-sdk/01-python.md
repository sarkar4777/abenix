# Python SDK

> The reference implementation. Async only, built on `httpx`.

Install from the monorepo:
```bash
cd packages/sdk/python && pip install -e .
```

The package is `abenix-sdk`, needs Python 3.10+, and has one dependency, `httpx`. It is also vendored into `packages/agent-sdk/` and into each standalone app under `<app>/api/sdk/`. Those copies must match `packages/sdk/python/abenix_sdk`. [`scripts/sync-sdks.sh`](../../scripts/sync-sdks.sh) copies them over, and `--check` fails on drift. `dev-local.sh` and `deploy-azure.sh` both run the check.

---

## Quick start

```python
import asyncio
from abenix_sdk import Abenix

async def main():
    async with Abenix(api_key="af_xxx", base_url="http://localhost:8000") as client:
        result = await client.execute("wingman-market-brief", "Brief me on today's crude market")
        print(result.status, result.output)

asyncio.run(main())
```

`execute` blocks until the run finishes unless you ask otherwise. No SSE handling, no JSON munging.

---

## Async only

There is no sync client. Every method is a coroutine. From a script or a notebook, wrap the calls in `asyncio.run(...)`.

---

## The `Abenix` client

```python
class Abenix:
    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
        timeout: float = 120.0,
        act_as: ActingSubject | None = None,
    ): ...

    async def me(self) -> dict: ...
    async def permissions(self) -> dict: ...
    async def execute(self, agent_slug_or_id: str, message: str, act_as: ActingSubject | None = None,
                      *, wait: bool | str | None = None, **kwargs) -> ExecutionResult: ...
    async def stream(self, agent_slug_or_id: str, message: str, act_as: ActingSubject | None = None,
                     **kwargs) -> AsyncIterator[StreamEvent]: ...
    async def watch(self, execution_id: str) -> AsyncIterator[DagSnapshot]: ...
    async def approve(self, execution_id: str, gate_id: str, comment: str = "") -> None: ...
    async def reject(self, execution_id: str, gate_id: str, comment: str = "") -> None: ...
    def set_act_as(self, act_as: ActingSubject | None) -> None: ...
    async def close(self) -> None: ...

    # Sub-clients
    executions: ExecutionsClient
    agents: AgentsClient
    knowledge: KnowledgeClient
    chat: ChatClient
    approvals: ApprovalsClient
    tools: ToolsClient
    presets: PresetsClient
    ml_models: MLModelsClient
    decisions: DecisionsClient
    sources: SourcesClient
    events: EventsClient
    actions: ActionsClient
    autonomy: AutonomyClient
    improvements: ImprovementsClient
    lessons: LessonsClient
    feedback: FeedbackClient

    http: httpx.AsyncClient   # authenticated client for endpoints with no typed method
```

- `timeout` is in seconds and applies to every request. `execute` also derives the server-side wait from it (`timeout - 5`, clamped to 5..1800, or 180 when `timeout` is 10 or less).
- `async with` closes the underlying `httpx.AsyncClient` on exit. Without it, call `await client.close()`.
- `agent_slug_or_id` takes a slug or a UUID. A slug is resolved through `/api/agents?search=` and then a paged scan. An unknown slug raises `ValueError`.
- `approve` and `reject` are the old gate-id shape. Prefer `client.approvals.approve(approval_id)`.

### Authentication

API key only, sent as `X-API-Key`. Leading and trailing whitespace is stripped, so a key read from a mounted secret with a trailing newline still works. There is no JWT or OAuth option.

### actAs

Pass `act_as` per call, or set a default with the constructor or `set_act_as`. A per-call subject wins over the default.

```python
from abenix_sdk import Abenix, ActingSubject

client = Abenix(api_key=svc_key, base_url=api_url)

alice = ActingSubject(subject_type="wingman", subject_id="alice", email="alice@yourcorp.com")
bob = ActingSubject(subject_type="wingman", subject_id="bob")

await asyncio.gather(
    client.execute("wingman-market-brief", "Brief me", act_as=alice),
    client.execute("wingman-market-brief", "Brief me", act_as=bob),
)
```

`set_act_as` changes the client in place, so for concurrent requests on behalf of different users pass `act_as` on each call. The subject goes out as `X-Abenix-Subject`, a JSON object with `subject_type`, `subject_id` and the optional `email`, `display_name`, `metadata`. `execute`, `stream`, `chat`, `tools` and `presets` send it. The other sub-clients do not. The API key needs the `can_delegate` scope.

---

## `execute` and `ExecutionResult`

```python
@dataclass
class ExecutionResult:
    output: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    duration_ms: int = 0
    model: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    confidence_score: float | None = None
    errors: list[dict] = field(default_factory=list)
    execution_id: str | None = None
    status: str = "completed"               # completed | failed | paused | running
    paused_at: ApprovalRef | None = None    # set when status == "paused"
    trigger_kind: str | None = None         # schedule, webhook, manual, event, api ...
    trigger_id: str | None = None
    trigger_name: str | None = None
    started_by: str | None = None

@dataclass
class ApprovalRef:
    approval_id: str
    title: str = ""
    payload: dict = field(default_factory=dict)
    required_signoffs: int = 1
    expires_at: str | None = None
    gate_kind: str | None = None
```

`output` is the agent's final text. A failed run does not raise, so check `status`.

| `wait` | Behaviour |
|---|---|
| omitted, `True` or `"completed"` | Blocks until the run ends. If the server answers in async mode, the SDK polls `/api/executions/{id}` until a terminal status or the wait timeout. |
| `"submitted"` | Returns at once with `execution_id` and `status` (usually `"running"`). `output` is empty. |
| `"until_gate"` | Blocks, but returns early with `status="paused"` and `paused_at` when a HITL gate opens. |
| `False` | Asks the server not to wait, but the async fallback still polls. Use `"submitted"` to get the id back without waiting. |

Extra keyword arguments go into the request body. `context={...}` passes input variables to an agent or pipeline.

```python
res = await client.execute(
    "contract-execute-flow",
    "Execute the Acme renewal",
    wait="until_gate",
    context={"counterparty_id": cp_id, "amount_usd": 2_400_000},
)

if res.status == "paused":
    gate = res.paused_at
    print(gate.approval_id, gate.title, gate.payload)
    approval = await client.approvals.wait_for(gate.approval_id, timeout_seconds=3600)
    if approval.get("status") == "approved":
        async for snap in client.watch(res.execution_id):
            if snap.is_terminal:
                break
        row = await client.executions.get(res.execution_id)
        print(row["status"], row["output_message"])
elif res.status == "completed":
    print(res.output)
else:
    print("run ended as", res.status)
```

### What started a run

Every run records it. `ExecutionResult` carries `trigger_kind`, `trigger_id`,
`trigger_name` and `started_by`, and `executions.list` filters on them.

```python
runs = await client.executions.list(trigger_kind=["schedule", "webhook"], limit=10)
for r in runs:
    print(r["id"], r["status"], r["started_by"])

nightly = await client.executions.list(trigger_id=trigger_id)
```

---

## Streaming

```python
async for event in client.stream("deep-research", "Analyze market trends for EVs"):
    if event.type == "token":
        print(event.text, end="")
    elif event.type == "tool_call":
        print(f"\n  tool {event.name}")
    elif event.type == "done":
        print(f"\n  cost ${event.cost} in {event.duration_ms}ms")
        run = await client.executions.get(event.execution_id)
    elif event.type == "error":
        print("\n  failed:", event.message, event.error_code)
```

Each event is a `StreamEvent` dataclass. `type` is one of `token`, `tool_call`, `tool_result`, `node_start`, `node_complete`, `done`, `error`, with type-specific fields such as `text`, `name`, `arguments`, `result`, `node_id`, `status`, `duration_ms`, `cost`, `message`. `done` carries `execution_id`. Any other event the server sends, such as `moderation`, `reply_checking` or `node_trace`, arrives with `type` set to its name. Only `error` means the run failed. `data` holds the raw payload of every event. The iterator ends when the server closes the stream. There is no automatic reconnect.

To follow a run started elsewhere, use `watch`. It yields a `DagSnapshot` per `snapshot` event (status, progress, nodes, edges, cost so far) and stops on `end`.

```python
async for snap in client.watch(execution_id):
    print(snap.status, snap.progress)
    if snap.is_terminal:
        break
```

`client.executions.watch_raw_sse(execution_id)` yields the raw SSE bytes instead, for proxying the stream to a browser unchanged.

---

## OpenTelemetry integration

The client itself has no tracing code. `abenix_sdk.tracing.init_tracing` sets up OTel for your service and instruments `httpx`, so SDK calls carry a W3C `traceparent` header and the platform-side run joins your trace.

```python
from abenix_sdk.tracing import init_tracing

init_tracing("wingman-api", fastapi_app=app)
```

`init_tracing(service_name, fastapi_app=None)` does nothing and returns `False` unless `OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_TEMPO_ENDPOINT`) is set and the OpenTelemetry packages are installed. The SDK does not install them. It needs the OTel SDK, the OTLP gRPC exporter, and the `httpx` and `fastapi` instrumentations. Sampling reads `OTEL_TRACES_SAMPLER_ARG` (default `0.1`), and `OTEL_SERVICE_NAME` overrides `service_name`. It also adds a span processor that redacts prompt, tool and body attributes. `current_trace_id()` returns the active trace id or `None`. See [`packages/sdk/python/abenix_sdk/tracing.py`](../../packages/sdk/python/abenix_sdk/tracing.py).

---

## Error handling

What a failure raises depends on the method.

| Methods | Raises |
|---|---|
| `me`, `permissions`, `agents.by_slug/create/update`, `sources`, `events`, `actions`, `autonomy`, `improvements`, `lessons`, `feedback`, `ml_models` and `code_assets` (all but `list`), `kill_switches`, `api_keys` | `AbenixError` |
| `decisions` | `AbenixDecisionError` (a subclass of `AbenixError`) |
| `execute`, `stream`, `watch`, `executions`, `approvals`, `knowledge`, `chat`, `tools`, `presets`, `ml_models.list`, `code_assets.list`, `agents.list/get/find_by_slug` | `httpx.HTTPStatusError` |
| `execute` or `stream` with an unknown slug, `approvals.return_for_changes`, `actions.flag_harm` or `lessons.report` with a blank text, `feedback.give` with a rating other than 1 or -1, `events.subscribe([])`, `decisions.import_rules` with a bad `mode`, `decisions.update_test` with an unknown field, `ml_models.upload` with bytes and no filename or framework, `code_assets.create` with no source or git URL, `api_keys.create` with an unknown scopes shape | `ValueError` |

`approve` and `reject` on the client do not check the response at all.

`AbenixError` carries `status`, `code` and `details`, and the message is `str(e)`. See [Errors from these clients](#errors-from-these-clients). For `httpx.HTTPStatusError`, read the envelope from the response:

```python
import httpx

try:
    result = await client.execute("invoice-triage", "Route INV-1042")
except httpx.HTTPStatusError as e:
    err = e.response.json().get("error") or {}
    if e.response.status_code == 429:
        await asyncio.sleep(int(e.response.headers.get("Retry-After", "5")))
    else:
        print(e.response.status_code, err.get("error_code"), err.get("message"))
        raise
```

The SDK does not retry anything itself.

---

## Platform clients

These calls return the `data` field of the response and raise on any 4xx or 5xx. The examples assume a client built like this:

```python
from abenix_sdk import Abenix, AbenixError, AbenixDecisionError

client = Abenix(api_key="af_xxx", base_url="http://localhost:8000")
```

### Errors from these clients

```python
class AbenixError(Exception):
    status: int          # HTTP status
    code: str | None     # server error_code, e.g. "STALE_DRAFT"
    details: Any         # extra context from the envelope

class AbenixDecisionError(AbenixError): ...
```

There is no `message` attribute. Use `str(e)`. Decision calls raise `AbenixDecisionError` and everything else here raises `AbenixError`, so `except AbenixError` catches both.

```python
try:
    await client.decisions.get("no-such-decision")
except AbenixDecisionError as e:
    print(e.status, e.code, str(e))
```

### `me()` and `permissions()`

```python
me = await client.me()
print(me["user"]["email"])
perms = await client.permissions()
print(perms["email"], perms["role"])
if "decisions.publish" not in perms["capabilities"]:
    print("this key cannot publish decisions")
```

`me()` returns `{"user": {...}}` with `id`, `email`, `full_name`, `role` and `tenant_id`. `permissions()` returns `user_id`, `tenant_id`, `email`, `name`, `role`, `is_admin`, `features` and `capabilities`.

### Agents

```python
agent = await client.agents.by_slug("invoice-triage")
if agent is None:
    agent = await client.agents.create({
        "name": "Invoice Triage",
        "slug": "invoice-triage",
        "system_prompt": "Route each invoice to the right queue.",
        "model_config": {"model": "claude-sonnet-4-5-20250929", "tools": ["calculator"]},
    })
await client.agents.update(agent["id"], {"description": "Routes invoices"})
```

- `by_slug(slug)` returns `None` on 404 and raises on anything else.
- `create(body)` takes the same fields as `POST /api/agents`, including `model_config`.
- `update(agent_id, body)` sends a `PUT`. A `name` in the body renames the slug too, so leave it out to keep the slug.

### Decisions

Versioned business rules. See [08-howto/09-decisions](../08-howto/09-decisions.md) for the model.

```python
res = await client.decisions.evaluate(
    "credit-limit",
    {"segment": "smb", "annual_revenue": 1_200_000},
    as_of="2026-10-01",
)
if res["outcome"] == "decided":
    print(res["result"], res["applied_rules"])
elif res["outcome"] == "missing_facts":
    print("need", res["missing_facts"])

batch = await client.decisions.evaluate_batch(
    "credit-limit",
    [{"facts": {"segment": "smb", "annual_revenue": 900_000}},
     {"facts": {"segment": "enterprise", "annual_revenue": 40_000_000}}],
)
print(batch["counts"])
```

`outcome` is one of `decided`, `no_match`, `missing_facts`, `invalid_facts`. Missing facts are never guessed.

Changing rules goes through a draft. Every draft carries an `etag`. Pass it back on `save_draft` or `import_rules` and the SDK sends it as `If-Match`. If someone saved the draft in between, the call fails with `code == "STALE_DRAFT"` and `details["current"]` holds their version. Each successful save returns the new `etag`.

```python
key = "credit-limit"
draft = await client.decisions.new_draft(key, note="Raise SMB cap")
n, etag = draft["version"], draft["etag"]

try:
    saved = await client.decisions.import_rules(key, n, rules, mode="merge", etag=etag)
    saved = await client.decisions.save_draft(
        key, n, etag=saved["etag"], valid_from="2026-11-01", change_note="SMB cap to 250k",
    )
except AbenixDecisionError as e:
    if e.code == "STALE_DRAFT":
        print("someone else saved, reload", e.details["current"]["etag"])
    raise

print(saved["problems"])                                # [] when the draft compiles
print(await client.decisions.validate(key, n))
print(await client.decisions.diff(key, n - 1, n))
print(await client.decisions.publish_plan(key, n))      # what publishing would supersede
await client.decisions.propose(key, n, note="SMB cap to 250k")
# await client.decisions.withdraw(key, n)                # pull it back to draft
```

After sign-off:

```python
await client.decisions.publish(key, n, expected_current=n - 1)
await client.decisions.retire(key, n - 1)
await client.decisions.update(key, risk_tier="medium", tags=["credit"])
print(await client.decisions.tests(key))
```

| Method | Signature |
|---|---|
| `evaluate` | `(key, facts, *, as_of=None, known_at=None, version=None, trace=True, persist=False, idempotency_key=None)` |
| `evaluate_batch` | `(key, items, *, as_of=None, version=None)` |
| `new_draft` | `(key, *, note="", from_version=None)` |
| `save_draft` | `(key, version, *, etag=None, authoring=None, content=None, valid_from=None, valid_to=None, clear_valid_from=False, clear_valid_to=False, change_note=None, provenance=None)` |
| `import_rules` | `(key, version, rules, *, mode="merge", etag=None)`, `mode` is `merge` or `replace` |
| `validate` | `(key, version)` |
| `propose` | `(key, version, *, note="")` |
| `withdraw` | `(key, version)` |
| `publish_plan` | `(key, version)` |
| `publish` | `(key, version, *, expected_current=None)` |
| `retire` | `(key, version)` |
| `diff` | `(key, a, b)` |
| `tests` | `(key)` |
| `update` | `(key, *, name=None, description=None, risk_tier=None, tags=None, log_mode=None)` |
| `list` | `(q="")` |
| `get` | `(key)`, the decision with its versions |
| `create` | `(name, *, key=None, rules=None, risk_tier="low", description="")` |
| `compare` | `(key, facts, targets)`, two or more targets, each `{label, version}` or `{as_of, known_at}` |
| `versions` | `(key)`, the `versions` list from `get` |
| `version` | `(key, n)` |
| `export` | `(key, version=None)` |
| `propose_rules` | `(key, rules, *, note, mode="merge")`, new draft, import and propose in one call |
| `add_test` | `(key, name, facts, *, expected=None, expected_outcome="decided", as_of=None, match="exact")`, `match` is `exact` or `subset` |
| `update_test` | `(key, test_id, **fields)`, any of `name`, `facts`, `expected`, `expected_outcome`, `as_of`, `match`. The rest stay as they are |
| `delete_test` | `(key, test_id)` |
| `evaluations` | `(key, limit=50)` |
| `reference_sets` | `()` |
| `reference_set` | `(key)` |
| `put_reference_set` | `(key, name, values, description="")`, creates the set on a 404, otherwise saves a new version |

A golden test with `match="subset"` passes when every key in `expected` is in the result with the same value. Extra keys in the result are ignored and nested objects are matched the same way. Lists and plain values must be equal. The default `exact` needs the whole result to equal `expected`.

```python
t = await client.decisions.add_test(
    key, "gold tier", {"tenure_years": 6}, expected={"tier": "gold"}, match="subset",
)
await client.decisions.update_test(key, t["id"], expected={"tier": "gold", "limit": 5000})
await client.decisions.delete_test(key, t["id"])
```

No SDK method yet for `/check`, `/versions/{n}/try`, `/versions/{n}/presence`, deleting a reference set, or archiving a decision. Use `client.http` for those.

### Sources

Watched pages and feeds. See [02-runtime/17-source-watch](../02-runtime/17-source-watch.md).

```python
src = await client.sources.create(
    "EU AI Act page",
    "https://example.org/ai-act",
    kind="html",
    cadence_minutes=1440,
    selector="main",
    jurisdiction="EU",
    tags=["ai-act"],
)
result = await client.sources.check_now(src["id"])
print(result["outcome"])

for ch in await client.sources.changes(limit=20):
    full = await client.sources.change(ch["id"])
```

Other methods: `list(q="")`, `get`, `update(source_id, **fields)`, `delete`, `pause(source_id, reason="")`, `resume`, `snapshots(source_id, limit=100)`, `snapshot(snapshot_id, *, full=False)`, `source_changes(source_id, limit=100)`, `validate_url(url)`, `preview(url, *, kind=None, selector=None)`, `settings()`.

### Events

Platform events sent to a webhook, or used to start an agent or pipeline. See [02-runtime/19-outbound-events](../02-runtime/19-outbound-events.md).

```python
print([e["type"] for e in await client.events.catalog()])

sub = await client.events.subscribe(
    ["decision.published", "source.changed"],
    url="https://hooks.example.com/abenix",
    name="rules feed",
)
secret = sub["signing_secret"]          # returned once, store it

failed = await client.events.deliveries(sub["id"], limit=20, status="failed")
for d in failed:
    await client.events.redeliver(d["id"])
```

`subscribe(events, *, url=None, name="", filter=None, target_type="webhook", target=None)` raises `ValueError` on an empty list. Also there: `list`, `update`, `delete`, `test`.

On the receiving side, check each delivery with the static `EventsClient.verify_signature(secret, body, signature)`. It computes `"sha256=" + HMAC-SHA256(secret, body)` and compares it to the `X-Abenix-Signature` header in constant time. Pass the raw body, not re-serialised JSON. It returns `False` when the secret or header is missing.

```python
from fastapi import FastAPI, Request, HTTPException
from abenix_sdk import EventsClient

app = FastAPI()

@app.post("/abenix")
async def hook(request: Request):
    raw = await request.body()
    if not EventsClient.verify_signature(SECRET, raw, request.headers.get("X-Abenix-Signature")):
        raise HTTPException(401)
    event = await request.json()
    print(request.headers["X-Abenix-Event"], event["id"])
    return {"ok": True}
```

### Approvals: return for changes

Sends an approval back to the requester instead of approving or denying it. A decision version goes back to draft. See [02-runtime/05-approvals-hitl](../02-runtime/05-approvals-hitl.md).

```python
await client.approvals.return_for_changes(
    approval_id, "Cap should be 200k, not 250k", client_token="ret-123",
)
```

`return_for_changes(approval_id, reason, *, client_token=None)` raises `ValueError` when `reason` is blank. It posts a `return` signoff.

### Actions

Earned autonomy for actions your app takes itself. Propose first, act only when the decision is `run`, then say it ran and what happened, so the agent's track record moves. The action type must be enrolled on the Autonomy page. See [08-howto/13-earned-autonomy](../08-howto/13-earned-autonomy.md#8-drive-it-from-a-standalone-app).

```python
d = await client.actions.propose(
    "trade.execute",
    {"symbol": "TTF", "lots": 5},
    target="TTF-Q1",
    intent="Spread is two sigma under fair value",
    prediction={"metric": "pnl_eur", "value": 12000, "low": 4000, "high": 20000},
)
args = {"symbol": "TTF", "lots": 5}
if d["decision"] == "wait":
    d = await client.actions.wait(d["action_id"], timeout_seconds=1800)
    args = d.get("arguments") or args          # a reviewer may have edited them
if d["decision"] == "run":
    await place_order(**args)
    await client.actions.executed(d["action_id"], True, result_preview="filled")
    await client.actions.report_outcome(d["action_id"], 9800)
```

| Method | Calls |
|---|---|
| `propose(action_key, arguments=None, *, agent_id=None, target=None, intent=None, prediction=None)` | `POST /api/autonomy/actions/propose`. Returns `{action_id, decision, approval_id, message}`. `decision` is `run`, `wait`, `watching` or `blocked` |
| `wait(action_id, *, timeout_seconds=60)` | Long-polls `GET /api/autonomy/actions/{id}/wait` in chunks of up to 120 s until the decision is not `wait`. Returns `{decision, status, arguments, edited, decided_by_name, decision_note, message}` |
| `executed(action_id, ok=True, *, result_preview=None)` | `POST /api/autonomy/actions/{id}/executed`. 409 `NOT_CLEARED` unless the action was cleared to run |
| `report_outcome(action_id, value, *, note=None)` | `POST /api/autonomy/actions/{id}/outcome` with `source: "api"`. Needs `actions.review` |
| `flag_harm(action_id, note)` | `POST /api/autonomy/actions/{id}/harm`. Drops the grant to Asks first. `ValueError` on a blank note. Needs `actions.review` |
| `get(action_id)` | `GET /api/autonomy/actions/{id}`, the action with its card, outcome and score. Needs `autonomy.view` |

`agent_id` is optional when only one agent holds a grant on the action type. A type nobody holds a grant on returns `run` with "Not enrolled, so it runs as before."

### Autonomy

Read the ladder for your own UI. Needs `autonomy.view`.

| Method | Calls |
|---|---|
| `overview()` | `GET /api/autonomy/overview`. Counts for the last 7 days, every grant, ready to promote, recently demoted, unmanaged actions |
| `grant(grant_id)` | `GET /api/autonomy/grants/{id}`. Level, stats, next-step checklist, level history and chart points |
| `grant_actions(grant_id, *, status=None, limit=50, before=None)` | `GET /api/autonomy/grants/{id}/actions`. `{items, next_before}`, pass `next_before` back as `before` |

```python
for g in (await client.autonomy.overview())["ready_to_promote"]:
    print(g["agent"]["name"], g["action_type"]["label"], g["next"]["next_label"])
```

### Feedback, lessons and improvements

Tell an agent what it got wrong and follow the fixes that come of it. A lesson never changes an agent by itself, it feeds a proposal that is proven and approved first. See [08-howto/16-self-improvement](../08-howto/16-self-improvement.md).

| Method | Calls |
|---|---|
| `feedback.give(rating, *, execution_id=None, conversation_id=None, message_id=None, agent_id=None, correction=None)` | `POST /api/improvements/feedback`. Returns `id`, `lesson_id`, `agent_id`, `rating`. `rating` is 1 or -1, `ValueError` otherwise. A thumbs down with a correction becomes a lesson with it as the right answer, its id is `lesson_id` |
| `lessons.report(agent_id, note, *, expected=None, execution_id=None, input=None, output=None)` | `POST /api/improvements/lessons` with `source: "sdk"`. Returns `{lesson_id, agent_id}`. `ValueError` on a blank note |
| `improvements.list(*, agent_id=None, state=None, limit=50)` | `GET /api/improvements/proposals`, returns the items. `state` is one of `drafting`, `proving`, `failed_proof`, `awaiting_approval`, `approved`, `rejected`, `released`, `kept`, `rolled_back`, `superseded` |
| `improvements.get(proposal_id)` | `GET /api/improvements/proposals/{id}` with its proof and watch result |

```python
await client.feedback.give(-1, execution_id=run_id, correction="0 °C is 273.15 K")
for p in await client.improvements.list(agent_id=agent_id, state="rolled_back"):
    print(p["cluster"]["title"], p["watch_result"]["reason"])
```

### ML models

Register trained models and call them. A name stands for its active version, a UUID for one exact version.

```python
model = await client.ml_models.upload(
    "churn",
    "churn.joblib",
    feature_names=["age", "income", "tenure"],
    description="Churn risk, retrained weekly",
)
print(model["version"], model["status"])                # 1.0.0 ready
print(await client.ml_models.predict("churn", {"age": 35, "income": 50000, "tenure": 24}))
why = await client.ml_models.explain("churn", {"age": 35, "income": 50000, "tenure": 24})
print(why["method"], why["contributions"][0])
print(await client.ml_models.get("churn"))
await client.ml_models.delete("churn", all_versions=True)
```

| Method | Calls |
|---|---|
| `list()` | `GET /api/ml-models`, every version you can see |
| `get(name_or_id)` | `GET /api/ml-models/{id}`, the version with its deployments |
| `upload(name, file, *, filename=None, framework=None, version=None, description="", input_schema=None, feature_names=None, output_schema=None, tags=None)` | `POST /api/ml-models` as multipart. `file` is a path or raw bytes. Bytes need a `filename` with the extension, or a `framework` (`sklearn`, `xgboost`, `onnx`, `pytorch`). `feature_names` is stored on the input schema so predictions can take rows keyed by name. A version is picked for you when left out |
| `predict(name_or_id, input_data, *, timeout=None)` | `POST /api/ml-models/{id}/predict` |
| `explain(name_or_id, input_data, baseline=None, *, timeout=None)` | `POST /api/ml-models/{id}/explain`. One row in, per-feature `contributions` and a `waterfall` from the baseline value to the prediction out. `baseline` is a dict by feature name or a list, the model's training means are used when it is left out. See [Explanations](../02-runtime/12-ml-models.md#explanations) |
| `delete(name_or_id, *, all_versions=False)` | `DELETE /api/ml-models/{id}`. With a name, the active version, or every version with `all_versions=True`. Returns `{"deleted": [ids]}` |

`upload` raises `AbenixError` with these codes:

| Code | Status | Meaning |
|---|---|---|
| `MODEL_LOAD_FAILED` | 422 | The file did not load. `details["model"]` is the stored error version, the active version did not change |
| `VERSION_EXISTS` | 409 | That version is taken, `details["next_version"]` is free |
| `UNSUPPORTED_FRAMEWORK` | 422 | TensorFlow or an unknown `.bin`, convert to ONNX |
| none | 400 | An extension the registry does not take |

A name that matches no model raises `AbenixError` 404 `NOT_FOUND`. See [02-runtime/12-ml-models](../02-runtime/12-ml-models.md).

### Code assets

Bring your own code, then run it from agents and pipelines with the `code_asset` tool. See [02-runtime/11-sandboxed-code-execution](../02-runtime/11-sandboxed-code-execution.md).

```python
asset = await client.code_assets.create("scorer", "./scorer", description="Scores rows")
if asset["status"] != "ready":
    raise RuntimeError(asset["error"])
asset = await client.code_assets.new_version(asset["id"], "./scorer")
print(asset["version"])
print(await client.code_assets.run(asset["id"], {"rows": [[1, 2]]}))
```

| Method | Calls |
|---|---|
| `list()` | `GET /api/code-assets` |
| `get(name_or_id)` | `GET /api/code-assets/{id}` |
| `create(name, source=None, *, description="", git_url=None, git_ref=None, filename=None)` | `POST /api/code-assets` as multipart. `source` is a zip, a tar.gz, a folder or raw bytes of either. A folder is zipped in memory, leaving out `.git`, virtualenvs, `node_modules` and caches. Or give `git_url` and `git_ref` and no source |
| `new_version(name_or_id, source=None, *, git_url=None, git_ref=None, filename=None)` | `POST /api/code-assets/{id}/versions`. Agents keep the same asset id |
| `run(code_asset_id, input=None, *, timeout_seconds=None, timeout=None)` | Runs the asset through `tools.execute("code_asset", ...)` |

`create` answers once analysis is done. It returns the row even when analysis failed, so check `status` (`ready` or `failed`) and `error`. `new_version` raises `AbenixError` 422 when the new code does not analyse cleanly, and the live version stays.

### Kill switches

Stop part of the platform for the whole tenant until someone clears it. Needs `risk.view` to list and `killswitch.manage` to set or clear.

```python
sw = await client.kill_switches.set("agent", "groundwork-trainer", "Bad outputs after the 2.1 data load")
print([k["target"] for k in await client.kill_switches.list()])
await client.kill_switches.clear(sw["id"])
```

| Method | Calls |
|---|---|
| `list(*, include_cleared=False)` | `GET /api/governance/kill-switches`, returns the switches |
| `set(scope, target, reason)` | `POST /api/governance/kill-switches`. `scope` is `all`, `agent`, `pipeline`, `tool`, `model`, `trigger`, `decision`, `source` or `improvements`. `target` is a name or id in that scope, `*` for all of them, and is always `*` for `all` and `improvements`. `reason` needs at least 3 characters. A switch already on comes back as it is |
| `clear(switch_id)` | `POST /api/governance/kill-switches/{id}/clear` |

### API keys

Keys of the calling user. An admin sees every key in the tenant.

```python
key = await client.api_keys.create("groundwork-ci", ["can_delegate"], max_monthly_tokens=2_000_000)
store_secret(key["raw_key"])                         # only in this response
for k in await client.api_keys.list():
    print(k["name"], k["key_prefix"], k["last_used_at"])
await client.api_keys.revoke(key["id"])
```

| Method | Calls |
|---|---|
| `list()` | `GET /api/api-keys`, active keys only |
| `create(name, scopes=None, *, expires_at=None, max_monthly_tokens=None, max_monthly_cost=None)` | `POST /api/api-keys`. `scopes` is `{"can_delegate": True}`, `{"allowed_actions": [...]}` or a list of actions. Any other shape raises `ValueError` before the call, the server would drop it silently |
| `revoke(key_id)` | `DELETE /api/api-keys/{id}`, returns `{id, status: "revoked"}` |

---

## Other sub-clients

The older sub-clients. They return the `data` field and raise `httpx.HTTPStatusError` on a 4xx or 5xx, not `AbenixError`.

### `executions`

| Method | Calls |
|---|---|
| `live()` | `GET /api/executions/live`, returns a list of `LiveExecution` dataclasses (`execution_id`, `agent_id`, `agent_name`, `status`, `current_step`, `current_tool`, tokens, `cost`, `iteration`, `max_iterations`, `confidence_score`) |
| `get(execution_id)` | `GET /api/executions/{id}`, the stored row with `status`, `output_message` and the trace |
| `list(*, agent_id=None, status=None, trigger_kind=None, trigger_id=None, search="", limit=20, offset=0)` | `GET /api/executions`. `trigger_kind` takes a string or a list |
| `replay(execution_id)` | `GET /api/executions/{id}/replay`, the trace for step-through viewing. It does not run anything again |
| `tree(execution_id)` | `GET /api/executions/tree/{id}`, parent plus child runs |
| `pending_approvals()` | `GET /api/executions/approvals`, open human-approval gates in the tenant |
| `watch_raw_sse(execution_id)` | `GET /api/executions/{id}/watch`, raw SSE bytes |

Running a past execution again on its recorded input is `POST /api/governance/runs/{id}/replay`, which has no SDK method. Call it through `client.http`.

### `agents`

Besides `by_slug`, `create` and `update` above:

- `list()` is `GET /api/agents`, the first page only (20 agents)
- `get(agent_id)` is `GET /api/agents/{id}`
- `find_by_slug(slug)` searches `GET /api/agents?search=` and returns the exact slug match or `None`. Prefer `by_slug`

### `approvals`

| Method | Notes |
|---|---|
| `list(*, status=None, execution_id=None, agent_id=None, kind=None, limit=200)` | `GET /api/approvals` |
| `get(approval_id)` | `GET /api/approvals/{id}` |
| `create(title, payload, *, required_signoffs=1, expires_seconds=86400, gate_kind=None, agent_id=None, agent_execution_id=None, client_token=None)` | `POST /api/approvals`. A reused `client_token` returns the existing approval |
| `signoff(approval_id, decision, *, reason="", client_token=None, edited_arguments=None)` | `decision` is `approve`, `deny` or `return`. `edited_arguments` only on an `action:*` approval with `approve` |
| `approve(approval_id, *, reason="", client_token=None, edited_arguments=None)` | `signoff` with `approve` |
| `deny(approval_id, *, reason="", client_token=None)` | `signoff` with `deny` |
| `return_for_changes(approval_id, reason, *, client_token=None)` | see above |
| `wait_for(approval_id, *, timeout_seconds=60, poll_seconds=2.0)` | Long-polls `/wait` in chunks of up to 120 s. A busy answer (429, 502, 503, 504) or a dropped connection is retried until the timeout. Returns the last row seen, still `pending` if time ran out |
| `subscribe()` | Async iterator over `GET /api/notifications/stream?types=approval_pending,approval_resolved`. Yields `{event, data}` |
| `configure_webhook(*, url, secret=None)` | `PUT /api/approvals/webhooks`. Needs the admin or owner role |

### `knowledge`

| Method | Calls |
|---|---|
| `bootstrap_project(slug, name, description="", collections=None)` | `POST /api/knowledge-projects/bootstrap`. Idempotent. Unknown `agent_slugs` in a collection come back in `skipped_agents` |
| `ensure_subject_collection(project_slug, subject_type, subject_id, description="", default_visibility="private", vector_backend="pgvector")` | `POST /api/knowledge-projects/{slug}/subject-collections/ensure` |
| `upload(kb_id, file, *, filename=None, content_type=None)` | `POST /api/knowledge-bases/{kb_id}/upload` as multipart. `file` is a path or raw bytes, bytes need a `filename`. Returns the document row with `status: processing`. `AbenixError` 400 for an empty or unsupported file |
| `documents(kb_id)` | `GET /api/knowledge-bases/{kb_id}/documents`. Poll it until the document is `ready` before you search |
| `cognify(kb_id, doc_ids=None, model="claude-sonnet-4-5-20250929", chunk_size=1000, chunk_overlap=200)` | `POST /api/knowledge-engines/{kb_id}/cognify` |
| `graph_stats(kb_id)` | `GET /api/knowledge-engines/{kb_id}/graph-stats` |
| `search(kb_id, query, mode="hybrid", top_k=5, graph_depth=2)` | `POST /api/knowledge-engines/{kb_id}/search`. Returns `results` (each with `content`, `score`, `source`, `metadata`), `mode_used`, `vector_count`, `graph_count`, `entities_found` and `latency_ms` |
| `graph(kb_id, limit=100)` | `GET /api/knowledge-engines/{kb_id}/graph` |
| `cognify_jobs(kb_id)` | `GET /api/knowledge-engines/{kb_id}/cognify-jobs` |

### `chat`

Persistent threads on `/api/conversations`. Every method takes an optional `act_as`.

| Method | Calls |
|---|---|
| `create(*, agent_slug=None, agent_id=None, app_slug=None, title=None)` | `POST /api/conversations` |
| `list(*, app_slug=None, agent_slug=None, archived=False, limit=50, offset=0)` | `GET /api/conversations`, `offset` is turned into a page number |
| `get(thread_id)` | Thread with its messages |
| `send(thread_id, content, *, context=None, agent_slug=None, attachments=None)` | `POST /api/conversations/{id}/turn`. Returns `{thread, user_message, assistant_message}` |
| `rename(thread_id, title)` | `PUT` with `{title}` |
| `archive(thread_id, *, archived=True)` | `PUT` with `{is_archived}` |
| `delete(thread_id)` | Deletes the thread and its messages |

### `tools` and `presets`

- `tools.list()` and its alias `tools.catalog()` return `GET /api/tools`
- `tools.execute(slug, arguments=None, config=None, *, timeout=None)` runs one tool through `POST /api/tools/{slug}/execute`, outside the agent loop
- `presets.list(*, tool_slug=None, ui_group=None, asset_class=None)`, `presets.get(slug)`, `presets.upsert(body)` and `presets.delete(slug)` manage `/api/tool-presets`
- `presets.run(slug, arguments=None, config=None, *, timeout=None)` runs a preset, your arguments merged over its defaults

### `ml_models` and `code_assets`

See [ML models](#ml-models) and [Code assets](#code-assets) above. Their calls raise `AbenixError`, except `list()` which raises `httpx.HTTPStatusError`. Deploy has no SDK method, use `client.http`.

---

## Sample: a typical Wingman endpoint

```python
# wingman/api/main.py, fragment
import os
from abenix_sdk import Abenix, ActingSubject

abenix = Abenix(
    api_key=os.environ["WINGMAN_ABENIX_API_KEY"],
    base_url=os.environ["ABENIX_API_URL"],
)

@app.post("/api/wingman/mispricing/{corridor_id}/scan")
async def scan_corridor(corridor_id: str, current_user: WingmanUser = Depends(auth)):
    subject = ActingSubject(
        subject_type="wingman",
        subject_id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
    )
    result = await abenix.execute(
        "wingman-mispricing-extractor",
        f"Scan corridor {corridor_id}",
        act_as=subject,
        wait="submitted",
        context={"corridor": {"id": corridor_id}},
    )
    return {"execution_id": result.execution_id, "status": result.status}
```

One client for the whole app, the subject passed per call. Wingman holds no business logic. The agent does.

---

## See also

- [00-overview](00-overview.md) — design philosophy + actAs explainer
- [02-typescript](02-typescript.md) — TS SDK
- [03-java](03-java.md) — Java SDK
- [09-reference/00-rest-api](../09-reference/00-rest-api.md) — underlying REST surface, for endpoints with no SDK method (call them through `client.http`)
