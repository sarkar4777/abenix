"""Execution Router — routes agent execution to embedded or remote runtime."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)

RUNTIME_MODE = os.environ.get("RUNTIME_MODE", "embedded").lower()
RUNTIME_URL = os.environ.get("RUNTIME_URL", "http://abenix-agent-runtime:8001")
RUNTIME_TIMEOUT = int(os.environ.get("RUNTIME_TIMEOUT", "300"))


@dataclass
class ExecutionConfig:
    """Everything needed to execute an agent."""
    message: str
    system_prompt: str
    model: str = "claude-sonnet-4-5-20250929"
    temperature: float = 0.7
    tool_names: list[str] = field(default_factory=list)
    agent_id: str = ""
    tenant_id: str = ""
    execution_id: str = ""
    agent_name: str = ""
    db_url: str = ""
    kb_ids: list[str] | None = None
    mcp_connections: list[dict[str, Any]] | None = None
    model_config: dict[str, Any] | None = None


@dataclass
class ExecutionResult:
    """Result from agent execution."""
    output: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    duration_ms: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    error: str | None = None


def is_remote_mode() -> bool:
    """Check if we should delegate to the runtime pod."""
    if RUNTIME_MODE == "remote":
        return True
    if RUNTIME_MODE == "auto" and RUNTIME_URL:
        return True
    return False


async def execute_agent(config: ExecutionConfig) -> ExecutionResult:
    """Execute an agent — routes to embedded or remote based on RUNTIME_MODE."""
    if is_remote_mode():
        return await _execute_remote(config)
    return await _execute_embedded(config)


async def stream_agent(config: ExecutionConfig) -> AsyncGenerator[dict[str, Any], None]:
    """Stream agent execution — routes to embedded or remote based on RUNTIME_MODE."""
    if is_remote_mode():
        async for event in _stream_remote(config):
            yield event
    else:
        async for event in _stream_embedded(config):
            yield event


async def _execute_embedded(config: ExecutionConfig) -> ExecutionResult:
    """Execute agent inline in the current process."""
    try:
        from engine.agent_executor import AgentExecutor, build_tool_registry
        from engine.llm_router import LLMRouter

        registry_kwargs = {
            "agent_id": config.agent_id,
            "tenant_id": config.tenant_id,
            "execution_id": config.execution_id,
            "agent_name": config.agent_name,
            "db_url": config.db_url,
            "model_config": config.model_config or {},
        }

        # Handle MCP connections
        mcp_clients = []
        if config.mcp_connections:
            from engine.tool_resolver import resolve_tools
            tool_registry, mcp_clients, _ = await resolve_tools(
                config.tool_names, config.mcp_connections
            )
        else:
            tool_registry = build_tool_registry(
                config.tool_names, kb_ids=config.kb_ids, **registry_kwargs
            )

        llm = LLMRouter()
        executor = AgentExecutor(
            llm_router=llm,
            tool_registry=tool_registry,
            system_prompt=config.system_prompt,
            model=config.model,
            temperature=config.temperature,
            agent_id=config.agent_id,
        )

        result = await executor.invoke(config.message)

        # Cleanup MCP clients
        for client in mcp_clients:
            try:
                await client.close()
            except Exception:
                pass

        return ExecutionResult(
            output=result.output,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost=result.cost,
            duration_ms=result.duration_ms,
            tool_calls=result.tool_calls,
            model=result.model,
        )

    except Exception as e:
        logger.error("Embedded execution failed: %s", e)
        return ExecutionResult(output="", error=str(e))


async def _stream_embedded(config: ExecutionConfig) -> AsyncGenerator[dict[str, Any], None]:
    """Stream agent execution inline in the current process."""
    try:
        from engine.agent_executor import AgentExecutor, build_tool_registry
        from engine.llm_router import LLMRouter

        registry_kwargs = {
            "agent_id": config.agent_id,
            "tenant_id": config.tenant_id,
            "execution_id": config.execution_id,
            "agent_name": config.agent_name,
            "db_url": config.db_url,
            "model_config": config.model_config or {},
        }

        mcp_clients = []
        if config.mcp_connections:
            from engine.tool_resolver import resolve_tools
            tool_registry, mcp_clients, _ = await resolve_tools(
                config.tool_names, config.mcp_connections
            )
        else:
            tool_registry = build_tool_registry(
                config.tool_names, kb_ids=config.kb_ids, **registry_kwargs
            )

        llm = LLMRouter()
        executor = AgentExecutor(
            llm_router=llm,
            tool_registry=tool_registry,
            system_prompt=config.system_prompt,
            model=config.model,
            temperature=config.temperature,
            agent_id=config.agent_id,
        )

        async for event in executor.stream(config.message):
            yield {"event": event.event, "data": event.data}

        for client in mcp_clients:
            try:
                await client.close()
            except Exception:
                pass

    except Exception as e:
        logger.error("Embedded stream failed: %s", e)
        yield {"event": "error", "data": {"message": str(e)}}


async def _execute_remote(config: ExecutionConfig) -> ExecutionResult:
    """Execute agent by calling the runtime pod via HTTP."""
    import httpx

    payload = {
        "message": config.message,
        "system_prompt": config.system_prompt,
        "model": config.model,
        "temperature": config.temperature,
        "tools": config.tool_names,
        "agent_id": config.agent_id,
        "tenant_id": config.tenant_id,
        "execution_id": config.execution_id,
        "agent_name": config.agent_name,
        "db_url": config.db_url,
        "kb_ids": config.kb_ids,
    }

    try:
        async with httpx.AsyncClient(timeout=RUNTIME_TIMEOUT) as client:
            resp = await client.post(f"{RUNTIME_URL}/execute", json=payload)
            if resp.status_code != 200:
                return ExecutionResult(output="", error=f"Runtime returned {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            return ExecutionResult(
                output=data.get("output", ""),
                input_tokens=data.get("input_tokens", 0),
                output_tokens=data.get("output_tokens", 0),
                cost=data.get("cost", 0.0),
                duration_ms=data.get("duration_ms", 0),
                tool_calls=data.get("tool_calls", []),
                model=data.get("model", ""),
            )
    except httpx.ConnectError:
        return ExecutionResult(output="", error=f"Cannot reach runtime at {RUNTIME_URL}. Is the runtime pod running?")
    except Exception as e:
        return ExecutionResult(output="", error=f"Runtime call failed: {e}")


async def _stream_remote(config: ExecutionConfig) -> AsyncGenerator[dict[str, Any], None]:
    """Stream agent execution from the runtime pod via SSE."""
    import httpx

    payload = {
        "message": config.message,
        "system_prompt": config.system_prompt,
        "model": config.model,
        "temperature": config.temperature,
        "tools": config.tool_names,
        "agent_id": config.agent_id,
        "tenant_id": config.tenant_id,
        "execution_id": config.execution_id,
        "agent_name": config.agent_name,
        "db_url": config.db_url,
        "kb_ids": config.kb_ids,
    }

    try:
        async with httpx.AsyncClient(timeout=RUNTIME_TIMEOUT) as client:
            async with client.stream("POST", f"{RUNTIME_URL}/execute/stream", json=payload) as resp:
                if resp.status_code != 200:
                    yield {"event": "error", "data": {"message": f"Runtime returned {resp.status_code}"}}
                    return

                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        frame, buffer = buffer.split("\n\n", 1)
                        if not frame.strip():
                            continue

                        event_type = ""
                        data_str = ""
                        for line in frame.split("\n"):
                            if line.startswith("event: "):
                                event_type = line[7:].strip()
                            elif line.startswith("data: "):
                                data_str = line[6:].strip()

                        if data_str:
                            try:
                                data = json.loads(data_str)
                                yield {"event": event_type or "message", "data": data}
                            except json.JSONDecodeError:
                                pass

    except httpx.ConnectError:
        yield {"event": "error", "data": {"message": f"Cannot reach runtime at {RUNTIME_URL}"}}
    except Exception as e:
        yield {"event": "error", "data": {"message": f"Runtime stream failed: {e}"}}
