from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)
_initialized = False

_REDACT_KEYS = {
    "llm.prompt", "llm.completion", "llm.messages",
    "tool.args", "tool.args_preview", "tool.input", "tool.output",
    "agent.system_prompt", "agent.input_message", "agent.output_message",
    "input.value", "output.value",
    "http.request.body", "http.response.body",
}


def _redact_value(v: Any) -> str:
    s = str(v) if v is not None else ""
    if not s:
        return "<empty>"
    h = hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"<redacted len={len(s)} sha256={h}>"


def _build_redacting_processor():
    try:
        from opentelemetry.sdk.trace import SpanProcessor

        class _RSP(SpanProcessor):
            def on_start(self, span, parent_context=None):
                return

            def on_end(self, span):
                try:
                    attrs = dict(getattr(span, "attributes", {}) or {})
                    for key in list(attrs.keys()):
                        if key in _REDACT_KEYS:
                            try:
                                span._attributes[key] = _redact_value(attrs[key])
                            except Exception:
                                pass
                except Exception:
                    pass

            def shutdown(self):
                return

            def force_flush(self, timeout_millis: int = 30000):
                return True

        return _RSP()
    except Exception:
        return None


def init_tracing(service_name: str, fastapi_app: Any = None) -> bool:
    """Initialize OpenTelemetry tracing + auto-instrument a FastAPI app.

    Reads:
      OTEL_EXPORTER_OTLP_ENDPOINT — required to enable (no-op without it)
      OTEL_TRACES_SAMPLER_ARG — float 0..1 (default 0.1 = 10%)
      OTEL_SERVICE_NAME — overrides service_name arg if set

    Safe to call repeatedly; only the first call wires the provider.
    Returns True if tracing was enabled, False if SDK missing or endpoint unset.
    """
    global _initialized
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("OTEL_TEMPO_ENDPOINT")
    if not endpoint:
        return False
    if _initialized:
        if fastapi_app is not None:
            _instrument_fastapi(fastapi_app)
        return True
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    except Exception as e:
        logger.warning("abenix_sdk.tracing: opentelemetry not installed (%s); install deps to enable", e)
        return False

    sampling_ratio = float(os.environ.get("OTEL_TRACES_SAMPLER_ARG", "0.1"))
    sampler = ParentBased(root=TraceIdRatioBased(sampling_ratio))
    resource = Resource.create({
        "service.name": os.environ.get("OTEL_SERVICE_NAME", service_name),
        "service.version": os.environ.get("BUILD_VERSION", "dev"),
        "deployment.environment": os.environ.get("ENVIRONMENT", "prod"),
    })
    provider = TracerProvider(resource=resource, sampler=sampler)
    _rsp = _build_redacting_processor()
    if _rsp is not None:
        provider.add_span_processor(_rsp)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
        endpoint=endpoint, insecure=not endpoint.startswith("https"),
    )))
    trace.set_tracer_provider(provider)
    _initialized = True
    logger.info("abenix_sdk.tracing: enabled service=%s endpoint=%s sample=%.2f", service_name, endpoint, sampling_ratio)
    if fastapi_app is not None:
        _instrument_fastapi(fastapi_app)
    _instrument_httpx()
    return True


def _instrument_fastapi(app: Any) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
    except Exception as e:
        logger.debug("fastapi auto-instrument skipped: %s", e)


def _instrument_httpx() -> None:
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except Exception:
        pass


def current_trace_id() -> str | None:
    try:
        from opentelemetry import trace
        ctx = trace.get_current_span().get_span_context()
        if not ctx.is_valid:
            return None
        return format(ctx.trace_id, "032x")
    except Exception:
        return None
