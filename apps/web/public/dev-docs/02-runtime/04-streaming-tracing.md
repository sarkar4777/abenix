# Streaming events + distributed tracing

> How a run reports progress while it runs, and how it shows up in traces afterwards.

---

## Three channels

| Channel | Carries | Kept for | Read by |
|---|---|---|---|
| Redis pub/sub `exec:events:<execution_id>` plus the list `exec:events:<execution_id>:log` | Every event of a queued run | Last 500 events, 1 hour | `GET /api/executions/{id}/stream`, `/watch`, and the streaming execute call for pool-routed agents |
| The HTTP response of an inline run | The same events, written straight to the caller as SSE | The life of the request | The chat and pipeline pages that called execute with `stream: true` |
| Redis live state (`execution_state.py`) | A small status record per running execution | 1 hour | Live Debug, `GET /api/executions/live` and `/live/stream` |

Only the queue consumer publishes to `exec:events:*`. An inline run streams over its own response and does not publish to the bus.

OpenTelemetry traces are separate. See [OpenTelemetry tracing](#opentelemetry-tracing).

---

## Event types

Each event is a JSON object with an `event` field. The consumer puts the payload fields next to it ([`consumer.py`](../../apps/agent-runtime/consumer.py) `_publish`).

| `event` | Payload | Sent by |
|---|---|---|
| `start` | `execution_id`, `agent`, `pool`, `mode` (`agent` or `pipeline`) | Consumer, on pickup |
| `token` | `data`, a text fragment | Executor, as the model streams |
| `tool_call` | The call the model asked for: `name`, `arguments` | Executor, before the tool runs |
| `tool_result` | `name`, `result`, `is_error`, and `autonomy` when an earned-autonomy gate acted | Executor, after the tool runs |
| `node_trace` | `node_type`, `tool`, `duration_ms`, `input`, `output_preview` (500 characters), `output`, `is_error`, `metadata`, `output_summary` | Executor, after the tool runs |
| `action_pending` | `name`, `autonomy` | Executor, while an earned-autonomy action waits for a person |
| `reply_checking` | `message` | Executor, while a moderation policy checks the reply |
| `moderation` | `source`, `outcome`, `review_id`, `categories`, `content`, `message` and the hold timeout | Executor, when moderation blocks or holds |
| `node_start` | `node_id`, `tool_name`, `label` | Consumer, pipeline runs |
| `node_complete` | `node_id`, `status`, `duration_ms`, then `error` and `error_type`, or `output_preview` and `produced_fields` | Consumer, pipeline runs |
| `done` | `execution_id`, `output`, `input_tokens`, `output_tokens`, `cost`, `duration_ms`, `model`, `failure_code`, and `validation_warnings` when an output schema found problems | Consumer, on success |
| `error` | The same fields as `done`, with `error` set | Consumer, on failure |

A subscriber also sees `heartbeat` every 15 seconds while nothing arrives. A subscription ends after `done` or `error`.

The inline execute stream ([`agents.py`](../../apps/api/app/routers/agents.py) `_stream_execution`) sends the same names, with `token` as `{text}` and `error` as `{message}`. Inline pipelines send `node_start`, `node_complete`, `token`, `done` and `error`. `POST /api/pipelines/{agent_id}/execute-stream` sends `node_complete`, `pipeline_complete` and `pipeline_error`.

---

## SSE endpoints

| Route | Gives |
|---|---|
| `POST /api/agents/{id}/execute` with `stream: true` | The run's events as SSE. An inline run streams directly. A pool-routed run is read from the bus and rewritten to the inline shape |
| `GET /api/executions/{id}/stream` | The stored log, then live events from the bus, as `event: <name>` frames. Tenant-checked |
| `GET /api/executions/{id}/watch` | A `snapshot` frame with the whole DAG state on connect and after each bus event (at most one per 50 ms), then `end`. Takes `?token=` because a browser `EventSource` cannot set headers |
| `GET /api/executions/live/stream` | A `state` frame with every live run in the tenant when it changes, checked every 2 seconds, and `idle` when nothing runs |
| `GET /api/executions/{id}/replay` | Not a stream. The stored `execution_trace` steps for step-through replay |

Example from `/stream`:

```
event: start
data: {"event": "start", "execution_id": "…", "agent": "Market Analyst", "pool": "default", "mode": "agent"}

event: tool_call
data: {"event": "tool_call", "name": "web_search", "arguments": {"query": "propane prices"}}

event: done
data: {"event": "done", "execution_id": "…", "output": "…", "cost": 0.0042, "duration_ms": 2417, "model": "claude-sonnet-4-5-20250929"}
```

### Reconnecting

There is no `Last-Event-ID` support. A client that reconnects to `/stream` gets the stored log again from the start, up to 500 events, then live events. After an hour the log is gone, so read the finished run from `GET /api/executions/{id}` instead.

The Python SDK's `watch` reads `/watch`. The web app uses it in [`LiveDagView.tsx`](../../apps/web/src/components/shared/LiveDagView.tsx).

---

## OpenTelemetry tracing

[`engine/tracing.py`](../../apps/agent-runtime/engine/tracing.py) sets up tracing in each runtime consumer (service `agent-runtime-<pool>`), the runtime HTTP server (`agent-runtime`) and the API (`abenix-api`). Nothing is exported unless `OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_TEMPO_ENDPOINT`) is set. Export is OTLP over gRPC. The sampler is parent-based with ratio `OTEL_TRACES_SAMPLER_ARG`, default 0.1. The helm chart sets the endpoint only on the runtime pools, see [06-deployment/04-observability](../06-deployment/04-observability.md#traces).

Spans the runtime makes:

| Span | Where | Attributes |
|---|---|---|
| `agent_runtime.run` | Consumer, one per queued run | `abenix.execution_id`, `abenix.pool` |
| `agent.execute` | Executor, one per run | `agent.id`, `agent.name`, `agent.model`, `execution.id`, `tenant.id` |
| `tool.<name>` | Executor, one per tool call | `tool.name`, `tool.args_preview`, `tool.is_error` |
| `<METHOD> <path>` | Runtime HTTP server, only for requests that carry `traceparent` | |

The API adds FastAPI and httpx auto-instrumentation when the packages are installed.

### Context across the queue

With `OTEL_EXPORTER_OTLP_ENDPOINT` set, one trace spans a whole run. The NATS backend puts the W3C `traceparent` in the message's `trace` field, and the pool consumer starts its `agent_runtime.run` span under it. `invoke_agent` sends the header on the execute call it makes for a child agent, and the runtime's HTTP server continues any incoming `traceparent`. So API, queue, runtime and child runs share one `trace_id`.

The run's `trace_id` is stored on the execution row. On `/executions/<id>` the **View Trace** button opens Grafana Explore on Tempo with that id. It uses `NEXT_PUBLIC_GRAFANA_URL`, default `http://localhost:3010`.

### Redaction

A span processor replaces these attributes with `<redacted len=N sha256=<12 hex>>` before export: `llm.prompt`, `llm.completion`, `llm.messages`, `tool.args`, `tool.args_preview`, `tool.input`, `tool.output`, `agent.system_prompt`, `agent.input_message`, `agent.output_message`, `input.value`, `output.value`. There is no switch to turn it off.

### Adding a span

```python
from engine.tracing import get_tracer

tracer = get_tracer("abenix.my_tool")

async def heavy_compute():
    with tracer.start_as_current_span("compute.fft", attributes={"window_size": 1024}) as span:
        result = do_fft(...)
        span.set_attribute("result.peaks", len(result.peaks))
        return result
```

`get_tracer` returns a no-op tracer when OpenTelemetry is not installed, so the code runs either way.

---

## Progress narration

[`engine/progress.py`](../../apps/agent-runtime/engine/progress.py) is a separate, optional channel for standalone apps that want tool-level narration across a parent run and its sub-agents. It publishes to `progress:<root_execution_id>` in Redis. The prefixes come from `PROGRESS_CHANNEL_PREFIX` and `PROGRESS_PARENT_KEY_PREFIX`. With no `REDIS_URL` it does nothing.

---

## See also

- [00-agent-execution](00-agent-execution.md) for the loop that emits these events
- [06-deployment/04-observability](../06-deployment/04-observability.md) for the deployed Tempo, Prometheus and Grafana stack
- [08-howto/04-debugging](../08-howto/04-debugging.md) for when to look at events, traces or logs

---

## Source map

| What | Where |
|---|---|
| **Consumer publish** | [`apps/agent-runtime/consumer.py`](../../apps/agent-runtime/consumer.py) — `_publish`, `_run_one`, `_run_traced` |
| **Event bus** | [`apps/api/app/core/execution_bus.py`](../../apps/api/app/core/execution_bus.py) — `subscribe_events` |
| **Live state** | [`apps/api/app/core/execution_state.py`](../../apps/api/app/core/execution_state.py) |
| **SSE routes** | [`apps/api/app/routers/executions.py`](../../apps/api/app/routers/executions.py) — `stream_execution_events`, `watch_execution`, `stream_live_executions` |
| **Executor events** | [`apps/agent-runtime/engine/agent_executor.py`](../../apps/agent-runtime/engine/agent_executor.py) — `stream` |
| **Tracing** | [`apps/agent-runtime/engine/tracing.py`](../../apps/agent-runtime/engine/tracing.py), [`apps/api/app/core/telemetry.py`](../../apps/api/app/core/telemetry.py) |
