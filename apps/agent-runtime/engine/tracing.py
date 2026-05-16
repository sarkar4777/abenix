from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_initialized = False
_NOOP_TRACER = None

_REDACT_KEYS = {
    "llm.prompt",
    "llm.completion",
    "llm.messages",
    "tool.args",
    "tool.args_preview",
    "tool.input",
    "tool.output",
    "agent.system_prompt",
    "agent.input_message",
    "agent.output_message",
    "input.value",
    "output.value",
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


def init_tracing(service_name: str) -> None:
    """Initialize OpenTelemetry tracing — call once at service startup.

    Reads:
      OTEL_EXPORTER_OTLP_ENDPOINT — required (e.g. http://abenix-tempo:4317)
      OTEL_SERVICE_NAME — overrides service_name arg if set
      OTEL_TRACES_SAMPLER_ARG — float 0..1, default 0.1 (10% baseline)
    """
    global _initialized
    if _initialized:
        return
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get(
        "OTEL_TEMPO_ENDPOINT"
    )
    if not endpoint:
        logger.info("tracing: OTEL_EXPORTER_OTLP_ENDPOINT not set; tracing disabled")
        _initialized = True
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import (
            ParentBased,
            TraceIdRatioBased,
        )
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
    except Exception as e:
        logger.warning("tracing: opentelemetry imports failed: %s", e)
        _initialized = True
        return

    sampling_ratio = float(os.environ.get("OTEL_TRACES_SAMPLER_ARG", "0.1"))
    sampler = ParentBased(root=TraceIdRatioBased(sampling_ratio))

    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME", service_name),
            "service.version": os.environ.get("BUILD_VERSION", "dev"),
            "deployment.environment": os.environ.get("ENVIRONMENT", "prod"),
        }
    )

    provider = TracerProvider(resource=resource, sampler=sampler)
    _rsp = _build_redacting_processor()
    if _rsp is not None:
        provider.add_span_processor(_rsp)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=endpoint,
                insecure=not endpoint.startswith("https"),
            )
        )
    )
    trace.set_tracer_provider(provider)
    _initialized = True
    logger.info(
        "tracing: initialized service=%s endpoint=%s sample=%.2f",
        service_name,
        endpoint,
        sampling_ratio,
    )


def get_tracer(name: str = "abenix.runtime"):
    """Return a tracer; falls back to a no-op when OTel is not initialized."""
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:
        return _NoopTracer()


class _NoopSpan:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def set_attribute(self, *args, **kwargs):
        pass

    def set_attributes(self, *args, **kwargs):
        pass

    def set_status(self, *args, **kwargs):
        pass

    def record_exception(self, *args, **kwargs):
        pass

    def add_event(self, *args, **kwargs):
        pass


class _NoopTracer:
    def start_as_current_span(self, *args, **kwargs):
        return _NoopSpan()

    def start_span(self, *args, **kwargs):
        return _NoopSpan()


def current_trace_id() -> str | None:
    """Return the hex trace_id of the currently-active span, or None."""
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        if not ctx.is_valid:
            return None
        return format(ctx.trace_id, "032x")
    except Exception:
        return None


def inject_carrier() -> dict:
    """Inject W3C traceparent + tracestate into a carrier dict for downstream propagation."""
    try:
        from opentelemetry import propagate

        carrier: dict = {}
        propagate.inject(carrier)
        return carrier
    except Exception:
        return {}


def extract_carrier(carrier: dict):
    """Return a Context restored from a carrier dict (e.g. NATS envelope, HTTP headers)."""
    try:
        from opentelemetry import propagate

        return propagate.extract(carrier)
    except Exception:
        return None
