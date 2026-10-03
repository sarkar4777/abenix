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
    elif event.type == "error":
        print("\n  failed:", event.message, event.error_code)
```

Each event is a `StreamEvent` dataclass. `type` is one of `token`, `tool_call`, `tool_result`, `node_start`, `node_complete`, `done`, `error`, with type-specific fields such as `text`, `name`, `arguments`, `result`, `node_id`, `status`, `duration_ms`, `cost`, `message`. The iterator ends when the server closes the stream. There is no automatic reconnect.

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

`init_tracing(service_name, fastapi_app=None)` does nothing and returns `False` unless `OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_TEMPO_ENDPOINT`) is set and the OpenTelemetry packages are installed. The SDK does not install them. It needs the OTel SDK, the OTLP gRPC exporter, and the `httpx` and `fastapi` instrumentations. Sampling reads `OTEL_TRACES_SAMPLER_ARG` (default `0.1`). It also adds a span processor that redacts prompt, tool and body attributes. `current_trace_id()` returns the active trace id or `None`. See [`packages/sdk/python/abenix_sdk/tracing.py`](../../packages/sdk/python/abenix_sdk/tracing.py).

---

## Error handling

What a failure raises depends on the method.

| Methods | Raises |
|---|---|
| `me`, `permissions`, `agents.by_slug/create/update`, `sources`, `events` | `AbenixError` |
| `decisions` | `AbenixDecisionError` (a subclass of `AbenixError`) |
| `execute`, `stream`, `watch`, `executions`, `approvals`, `knowledge`, `chat`, `tools`, `presets`, `ml_models`, `agents.list/get/find_by_slug` | `httpx.HTTPStatusError` |
| `execute` or `stream` with an unknown slug, `approvals.return_for_changes` with a blank reason, `events.subscribe([])`, `decisions.import_rules` with a bad `mode` | `ValueError` |

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
perms = await client.permissions()
print(perms["email"], perms["role"])
if "decisions.publish" not in perms["capabilities"]:
    print("this key cannot publish decisions")
```

`permissions()` returns `user_id`, `tenant_id`, `email`, `name`, `role`, `is_admin`, `features` and `capabilities`.

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

Also there: `list`, `get`, `create`, `compare`, `versions`, `version`, `export`, `propose_rules`, `add_test`, `evaluations`, `reference_sets`, `reference_set`, `put_reference_set`. The server's `/check` and `/versions/{n}/try` endpoints have no SDK method yet.

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
