# Abenix Python SDK

Execute, stream, and monitor Abenix AI agents from any Python application.

```python
from abenix_sdk import Abenix

async with Abenix(api_key="af_...", base_url="https://api.abenix.dev") as forge:
    result = await forge.execute("example_app-extractor", "Extract terms from this PDF: ...")
    print(result.output)
```

## Wait / async semantics

The platform's `/api/agents/{id}/execute` endpoint is **async by default**:
it queues the execution onto a runtime pool (KEDA-scaled) and returns
`{execution_id, mode: "async"}` immediately. That works great for browser
callers (the web UI subscribes to `/api/executions/{id}/watch` for live
progress), but breaks SDK callers who block on `result.output`.

The SDK's `forge.execute()` therefore **always sends `wait=True`** plus a
sensible `wait_timeout_seconds` derived from the client's request timeout.
If the server still returns an async response (e.g. a queue dispatcher
fallback or an older API version), the SDK polls `/api/executions/{id}`
until the row is terminal (`completed | failed | cancelled`) and returns
the final `ExecutionResult`. You will never see an empty-output regression
unless the entire wait+poll path is broken.

You can override this:

```python
# Fire-and-forget — get back the execution_id only.
result = await forge.execute("slow-agent", "...", wait=False)
```

## Server-side default behaviour

The `/api/agents/{id}/execute` endpoint also defaults `wait=True` for any
caller that authenticates with a platform `X-API-Key` (i.e. SDK callers).
Cookie / JWT (browser) callers keep the async-by-default behaviour because
they have UI for live monitoring. This is belt-and-suspenders alongside
the SDK fix: even if a future SDK ships with `wait` accidentally dropped,
the server still returns synchronously to API-key callers.

If a request explicitly sets `wait` (`true` or `false`), the explicit
value always wins.

## Sync invariant — never edit a non-canonical copy

This SDK is **vendored** into five additional locations so each standalone
app's Docker image carries its own copy:

| Path                                       | Purpose                          |
| ------------------------------------------ | -------------------------------- |
| `packages/sdk/python/abenix_sdk/`          | **Canonical** — edit only here.  |
| `packages/agent-sdk/abenix_sdk/`           | Used by `apps/agent-runtime`.    |
| `example_app/api/sdk/abenix_sdk/`           | Vendored into the example app image.  |
| `industrial-iot/api/sdk/abenix_sdk/`       | Vendored into Industrial-IoT.    |
| `resolveai/api/sdk/abenix_sdk/`            | Vendored into ResolveAI.         |
| `sauditourism/api/sdk/abenix_sdk/`         | Vendored into Saudi Tourism.     |

After editing the canonical copy:

```bash
bash scripts/sync-sdks.sh           # copy canonical → all destinations
bash scripts/sync-sdks.sh --check   # CI mode: exit non-zero on drift
```

`--check` is wired into:
* `scripts/deploy-azure.sh` Phase 0 — fails the deploy before any Docker build.
* `scripts/dev-local.sh` startup — fails the dev boot before processes spawn.

Set `SKIP_SDK_SYNC_CHECK=1` to bypass (not recommended outside debugging).

## Acting subjects (RBAC delegation)

Platform API keys with the `can_delegate` scope can act on behalf of an
end user via the `X-Abenix-Subject` header:

```python
from abenix_sdk import Abenix, ActingSubject

subject = ActingSubject(
    subject_type="example_app",
    subject_id="user-123",
    email="user@example.com",
)
async with Abenix(api_key="af_...", act_as=subject) as forge:
    result = await forge.execute("...", "...")
```
