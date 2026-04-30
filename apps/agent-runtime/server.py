"""Abenix Agent Runtime — Standalone microservice."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("agent-runtime")

app = FastAPI(title="Abenix Runtime", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "agent-runtime"}


@app.get("/metrics")
async def metrics():
    """Prometheus /metrics scrape endpoint."""
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    except ImportError:
        return JSONResponse(
            {"error": "prometheus_client not installed"},
            status_code=503,
        )
    from fastapi.responses import Response
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.post("/execute")
async def execute(request: Request):
    """Execute an agent synchronously. Called by the API server."""
    body = await request.json()

    try:
        from engine.agent_executor import AgentExecutor, build_tool_registry
        from engine.llm_router import LLMRouter

        tool_names = body.get("tools", [])
        registry_kwargs = {
            "agent_id": body.get("agent_id", ""),
            "tenant_id": body.get("tenant_id", ""),
            "execution_id": body.get("execution_id", ""),
            "agent_name": body.get("agent_name", ""),
            "db_url": body.get("db_url", ""),
        }
        kb_ids = body.get("kb_ids")

        tool_registry = build_tool_registry(tool_names, kb_ids=kb_ids, **registry_kwargs)
        llm = LLMRouter()

        executor = AgentExecutor(
            llm_router=llm,
            tool_registry=tool_registry,
            system_prompt=body.get("system_prompt", ""),
            model=body.get("model", "claude-sonnet-4-5-20250929"),
            temperature=body.get("temperature", 0.7),
            agent_id=body.get("agent_id", ""),
        )

        result = await executor.invoke(body.get("message", ""))

        return JSONResponse({
            "output": result.output,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost": result.cost,
            "duration_ms": result.duration_ms,
            "tool_calls": result.tool_calls,
            "model": result.model,
        })

    except Exception as e:
        logger.error("Execution failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/execute/stream")
async def execute_stream(request: Request):
    """Execute an agent with SSE streaming."""
    body = await request.json()

    async def event_generator():
        try:
            from engine.agent_executor import AgentExecutor, build_tool_registry
            from engine.llm_router import LLMRouter

            tool_names = body.get("tools", [])
            registry_kwargs = {
                "agent_id": body.get("agent_id", ""),
                "tenant_id": body.get("tenant_id", ""),
                "execution_id": body.get("execution_id", ""),
                "agent_name": body.get("agent_name", ""),
                "db_url": body.get("db_url", ""),
            }
            kb_ids = body.get("kb_ids")

            tool_registry = build_tool_registry(tool_names, kb_ids=kb_ids, **registry_kwargs)
            llm = LLMRouter()

            executor = AgentExecutor(
                llm_router=llm,
                tool_registry=tool_registry,
                system_prompt=body.get("system_prompt", ""),
                model=body.get("model", "claude-sonnet-4-5-20250929"),
                temperature=body.get("temperature", 0.7),
                agent_id=body.get("agent_id", ""),
            )

            async for event in executor.stream(body.get("message", "")):
                yield f"event: {event.event}\ndata: {json.dumps(event.data, default=str)}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8001"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, workers=2)
