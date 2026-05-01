from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge, Histogram

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

http_requests_total = Counter(
    "abenix_http_requests_total",
    "HTTP requests by method/path/status",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "abenix_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)

# Business metrics (5.3.2)
agents_created_total = Counter(
    "abenix_agents_created_total",
    "Total agents created",
    ["type"],
)

executions_completed_total = Counter(
    "abenix_executions_completed_total",
    "Total executions completed",
    ["status"],
)

knowledge_searches_total = Counter(
    "abenix_knowledge_searches_total",
    "Total knowledge engine searches",
    ["mode"],
)

# The dashboards need structured data on every failure, every $ spent,
# and every sandbox pod. These counters + histograms are the raw inputs
# Grafana aggregates into the "Abenix Operations" dashboard.

execution_outcomes_total = Counter(
    "abenix_execution_outcomes_total",
    "Executions by final outcome + structured failure code",
    ["outcome", "failure_code", "agent_type"],
)

# LLM-level spend + volume. Broken out by provider + model so Grafana
# can stack "Anthropic vs OpenAI vs Google" cost over time.
llm_tokens_total = Counter(
    "abenix_llm_tokens_total",
    "Input/output tokens consumed by LLM calls",
    ["provider", "model", "direction"],  # direction = input|output
)
llm_cost_usd_total = Counter(
    "abenix_llm_cost_usd_total",
    "Dollar cost of LLM calls (inclusive of input + output tokens)",
    ["provider", "model"],
)
llm_call_duration_seconds = Histogram(
    "abenix_llm_call_duration_seconds",
    "Wall-clock latency of LLM provider calls",
    ["provider", "model"],
    buckets=(0.1, 0.3, 0.5, 1, 2, 5, 10, 20, 30, 60, 120),
)

# Sandboxed-job metrics — code_asset, sandboxed_job tool, ml_model
# inference all funnel through the same backend. `backend` = k8s|docker,
# `image_family` = python|node|go|rust|ruby|java|perl|other.
sandbox_runs_total = Counter(
    "abenix_sandbox_runs_total",
    "Sandboxed job runs (code_asset + sandboxed_job tool + ml_model)",
    ["backend", "image_family", "outcome"],  # outcome = ok|timeout|nonzero
)
sandbox_run_duration_seconds = Histogram(
    "abenix_sandbox_run_duration_seconds",
    "Sandbox end-to-end runtime (build + run + log fetch)",
    ["backend", "image_family"],
    buckets=(1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
)

# Active-execution gauge. This is what the dashboard counter reads —
# exposing it as a Prometheus gauge means Grafana sees the real-time
# value without the Postgres round-trip, AND alerts can fire when it
# sticks too high for too long (the "67 running forever" signal).
active_executions = Gauge(
    "abenix_active_executions",
    "Executions currently in RUNNING status (per tenant)",
    ["tenant_id"],
)

# Stale-sweeper activity. A healthy cluster has sweep_stale_total close
# to zero. Spikes mean pods are crashing silently and the plan needs
# investigation. Dashboard panel: "Sweeps (24h)" with red threshold >10.
stale_sweeps_total = Counter(
    "abenix_stale_sweeps_total",
    "Executions the stale-sweeper marked FAILED because they outlived "
    "the STALE_EXECUTION_MAX_MINUTES window",
    ["reason"],  # reason = owning_pod_crashed | unknown
)

# Notification fan-out. Separates in-app + ws + email + slack channels
# so operators can tell if an outage is "no notifications getting out"
# vs "notifications storm".
notifications_sent_total = Counter(
    "abenix_notifications_sent_total",
    "Notifications emitted, by channel + severity",
    ["channel", "severity"],  # channel=in_app|ws|slack|email
)

# Tool call counter — how often is each tool invoked. High-volume tools
# (database_query, http_client) drive latency + cost; this lets us spot
# a runaway agent hitting the same tool 1000x in a loop.
tool_calls_total = Counter(
    "abenix_tool_calls_total",
    "Tool invocations per agent execution",
    ["tool_name", "outcome"],  # outcome = ok|error
)


def setup_telemetry(
    app: FastAPI,
    *,
    otel_enabled: bool = False,
    otel_exporter: str = "stdout",
    otel_endpoint: str = "http://localhost:4317",
) -> None:
    if not otel_enabled:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        resource = Resource.create({"service.name": "abenix-api"})
        provider = TracerProvider(resource=resource)

        if otel_exporter == "otlp":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            exporter = OTLPSpanExporter(endpoint=otel_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        else:
            from opentelemetry.sdk.trace.export import (
                ConsoleSpanExporter,
                SimpleSpanProcessor,
            )

            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

        trace.set_tracer_provider(provider)

        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry tracing enabled (exporter=%s)", otel_exporter)
    except ImportError:
        logger.warning("OpenTelemetry packages not installed, tracing disabled")


def get_tracer(name: str):
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:
        return None


def get_trace_headers() -> dict[str, str]:
    """Extract current trace context as HTTP headers for propagation to downstream services."""
    try:
        from opentelemetry.propagate import inject

        headers: dict[str, str] = {}
        inject(headers)
        return headers
    except ImportError:
        return {}
