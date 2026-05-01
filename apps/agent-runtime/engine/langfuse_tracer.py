from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_tracer_instance: LangfuseTracer | None = None


class LangfuseTracer:
    def __init__(self, public_key: str, secret_key: str, host: str | None = None) -> None:
        from langfuse import Langfuse
        kwargs: dict[str, Any] = {
            "public_key": public_key,
            "secret_key": secret_key,
        }
        if host:
            kwargs["host"] = host
        self._client = Langfuse(**kwargs)
        self._trace = self._client.trace(name="agent-runtime")

    def trace_llm_call(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        response: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        latency_ms: int,
    ) -> None:
        self._trace.generation(
            name="llm_call",
            model=model,
            input=messages,
            output=response,
            usage={
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            },
            metadata={
                "cost": cost,
                "latency_ms": latency_ms,
            },
        )

    def trace_tool_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        result: str,
        duration_ms: int,
    ) -> None:
        self._trace.span(
            name=f"tool:{tool_name}",
            input=arguments,
            output=result,
            metadata={"duration_ms": duration_ms},
        )

    def flush(self) -> None:
        self._client.flush()


def get_langfuse_tracer() -> LangfuseTracer | None:
    global _tracer_instance
    if _tracer_instance is not None:
        return _tracer_instance

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not public_key or not secret_key:
        return None

    try:
        host = os.environ.get("LANGFUSE_HOST")
        _tracer_instance = LangfuseTracer(public_key, secret_key, host)
        logger.info("Langfuse tracing enabled")
        return _tracer_instance
    except Exception:
        logger.warning("Failed to initialize Langfuse tracer", exc_info=True)
        return None
