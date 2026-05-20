# Python SDK

> The reference implementation. Async-first, threadsafe, OTel-instrumented out of the box.

Install:
```bash
pip install abenix-sdk
# or, in this monorepo:
cd packages/sdk/python && pip install -e .
```

The SDK ships as a single package `abenix_sdk` and is vendored into every standalone app under `<app>/api/sdk/`. The vendored copy is kept in sync with `packages/sdk/python/abenix_sdk` by [`scripts/sync-sdks.sh`](../../scripts/sync-sdks.sh) which runs as part of every CI build.

---

## Quick start

```python
import asyncio
from abenix_sdk import Abenix

async def main():
    async with Abenix(api_url="http://localhost:8000", api_key="af_xxx") as client:
        result = await client.execute(
            "wingman-market-brief",
            input_data={},
            wait="complete",
        )
        print(result.output)

asyncio.run(main())
```

That's the full surface for a typical call. No SSE handling, no JSON munging — the SDK does it.

---

## Sync vs async

The Python SDK has both a sync and async surface. They share zero code paths under the hood — the sync client uses `requests`, the async client uses `httpx`. Both expose the same method names.

```python
from abenix_sdk import Abenix, AbenixSync

# Async (preferred for FastAPI / asyncio apps)
async with Abenix(...) as client:
    result = await client.execute(...)

# Sync (for scripts, Jupyter, Django views, etc.)
with AbenixSync(...) as client:
    result = client.execute(...)
```

Within a single process you can mix the two — there's no shared state.

---

## The `Abenix` client

```python
class Abenix:
    def __init__(
        self,
        api_url: str,
        api_key: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
        retries: int = 3,
        otel_tracer: trace.Tracer | None = None,
    ): ...
    
    async def __aenter__(self): ...
    async def __aexit__(self, *exc): ...
    
    def with_subject(self, subject: ActingSubject) -> "Abenix": ...
    
    # Primary surface
    async def execute(self, slug: str, input_data: dict, wait: str = "submitted", ...) -> ExecutionResult: ...
    
    # Sub-clients
    executions: ExecutionsClient
    agents: AgentsClient
    knowledge: KnowledgeClient
    ml_models: MLModelsClient
    code_assets: CodeAssetsClient
    approvals: ApprovalsClient
```

### Authentication options

Pick one:
- `api_key="af_..."` — service account key. Sent as `X-API-Key`.
- `token="ey..."` — JWT (issued by `/api/auth/login`). Sent as `Authorization: Bearer …`. Will auto-refresh if a refresh token was supplied.

The SDK does **not** support OAuth flows directly. If you're using an external IdP (Okta, Auth0), exchange for a JWT via `/api/auth/exchange` and pass it in.

### `with_subject` — actAs

Returns a **shallow copy** of the client with `X-Abenix-Subject` set on subsequent calls. Doesn't mutate the original.

```python
service = Abenix(api_url, api_key=svc_key)

# Two parallel threads, two different subjects, one client pool:
alice = service.with_subject(ActingSubject(subject_type="wingman", subject_id="alice"))
bob = service.with_subject(ActingSubject(subject_type="wingman", subject_id="bob"))

await asyncio.gather(
    alice.execute(...),
    bob.execute(...),
)
```

---

## `ExecutionResult`

```python
@dataclass
class ExecutionResult:
    execution_id: UUID
    status: str                  # "running" | "completed" | "failed" | "waiting_approval" | "cancelled"
    output: dict | None          # parsed output (matches agent.output_schema if set)
    raw_output: str | None       # raw LLM text if output couldn't be parsed
    cost_usd: float
    duration_ms: int
    failure_code: str | None
    error_message: str | None
    approval_ref: ApprovalRef | None
```

`output` is `None` until `status` is terminal. Use the field-by-field accessor on `ExecutionResult.terminal_or_raise()` if you want an exception on non-success:

```python
result = (await client.execute("...", input_data, wait="complete")).terminal_or_raise()
print(result.output["fair_value_spread_usd_mt"])
```

---

## Streaming

```python
async for event in client.execute("...", input_data, wait="stream"):
    if event.type == "tool.end":
        print(f"  tool {event.tool_slug} returned in {event.latency_ms}ms")
    elif event.type == "completed":
        print(f"  done: {event.output}")
```

Each event is an `ExecEvent` dataclass — `type`, plus type-specific fields. The iterator closes after the terminal event.

If the connection drops, the iterator raises `AbenixDisconnected`. Re-subscribe with `client.executions.events(execution_id, since=last_event_id)`:

```python
last_id = None
while True:
    try:
        async for event in client.executions.events(execution_id, since=last_id):
            handle(event)
            last_id = event.id
            if event.is_terminal:
                return
    except AbenixDisconnected:
        await asyncio.sleep(1)
```

---

## OpenTelemetry integration

The SDK auto-instruments if `OTEL_TRACES_EXPORTER` is set or you pass a `tracer`:

```python
from opentelemetry import trace
client = Abenix(api_url, api_key=key, otel_tracer=trace.get_tracer("my_service"))
```

Without an OTel setup, the SDK still propagates the W3C `traceparent` header from the current span if there's an active tracer. With no tracer at all, the header is omitted and the platform creates a root span.

The standalone apps' SDK helpers (`abenix_sdk.tracing.install_default_tracing`) do the wiring:

```python
from abenix_sdk.tracing import install_default_tracing
install_default_tracing(service_name="wingman-api")
```

This sets up the exporter, instruments FastAPI + httpx + asyncpg, and adds the PII redaction processor. See [`packages/sdk/python/abenix_sdk/tracing.py`](../../packages/sdk/python/abenix_sdk/tracing.py).

---

## Error handling

```python
from abenix_sdk import AbenixError

try:
    result = await client.execute(...)
except AbenixError as e:
    if e.error_code == "RATE_LIMITED":
        await asyncio.sleep(int(e.headers.get("Retry-After", "5")))
        result = await client.execute(...)
    elif e.error_code == "VALIDATION_ERROR":
        print("Bad input:", e.details)
    else:
        raise
```

Specific exception subclasses for the common cases — `AbenixRateLimited`, `AbenixValidationError`, `AbenixNotFound`, `AbenixForbidden`, `AbenixServerError` — let you write `except AbenixRateLimited:` directly.

---

## Sample: a typical Wingman endpoint

```python
# wingman/api/main.py — fragment
from abenix_sdk import Abenix, ActingSubject

@app.post("/api/wingman/mispricing/{corridor_id}/scan")
async def scan_corridor(corridor_id: str, current_user: WingmanUser = Depends(auth)):
    async with Abenix(
        api_url=os.environ["ABENIX_API_URL"],
        api_key=os.environ["WINGMAN_ABENIX_API_KEY"],
    ) as client:
        subject = ActingSubject(
            subject_type="wingman",
            subject_id=current_user.id,
            email=current_user.email,
            display_name=current_user.display_name,
        )
        result = await client.with_subject(subject).execute(
            "wingman-mispricing-extractor",
            input_data={"corridor": {"id": corridor_id}},
            wait="submitted",
            client_token=f"scan-{corridor_id}-{int(time.time())}",
        )
        return {"execution_id": str(result.execution_id), "status": result.status}
```

That's it. Wingman holds no business logic. the agent does.

---

## See also

- [00-overview](00-overview.md) — design philosophy + actAs explainer
- [02-typescript](02-typescript.md) — TS SDK
- [03-java](03-java.md) — Java SDK
- [09-reference/00-rest-api](../09-reference/00-rest-api.md) — underlying REST surface (rarely needed. SDK covers everything)
