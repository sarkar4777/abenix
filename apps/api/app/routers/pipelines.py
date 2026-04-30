"""Pipeline execution API — run DAG-based tool workflows with conditional branching."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncio
import json as json_module

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.schemas.pipelines import (
    ExecutePipelineRequest,
    ExecuteSavedPipelineRequest,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from models.agent import Agent, AgentStatus, AgentType
from models.execution import Execution, ExecutionStatus
from models.user import User

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


@router.post("/{agent_id}/execute")
async def execute_pipeline(
    agent_id: str,
    body: ExecutePipelineRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Execute a DAG-based pipeline of tool calls against an agent's tool set."""
    # Validate agent exists and user has access (includes OOB agents)
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    if agent.status not in (AgentStatus.ACTIVE, AgentStatus.DRAFT):
        return error("Agent is not in an executable state", 400)

    # Get tool names from agent config
    model_config = agent.model_config_ or {}
    tool_names = model_config.get("tools", [])
    if not tool_names:
        return error("Agent has no tools configured", 400)

    # Check that all pipeline nodes reference available tools
    requested_tools = {n.tool_name for n in body.nodes}
    available = set(tool_names)
    missing = requested_tools - available
    if missing:
        return error(
            f"Pipeline uses tools not available on this agent: {sorted(missing)}. "
            f"Available: {sorted(available)}",
            400,
        )

    # Check for duplicate node IDs
    node_ids = [n.id for n in body.nodes]
    if len(node_ids) != len(set(node_ids)):
        return error("Duplicate node IDs in pipeline definition", 400)

    # Create execution record
    execution = Execution(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=user.tenant_id,
        user_id=user.id,
        input_message=f"[pipeline:{len(body.nodes)} nodes]",
        status=ExecutionStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    db.add(execution)
    await db.commit()

    # Build tool registry and execute pipeline
    from engine.agent_executor import build_tool_registry
    from engine.pipeline import PipelineExecutor, parse_pipeline_nodes, serialize_pipeline_result

    tool_registry = build_tool_registry(tool_names)
    executor = PipelineExecutor(
        tool_registry=tool_registry,
        timeout_seconds=body.timeout_seconds,
    )

    raw_nodes = [n.model_dump() for n in body.nodes]
    pipeline_nodes = parse_pipeline_nodes(raw_nodes)

    try:
        pipeline_result = await executor.execute(pipeline_nodes, body.context)
    except Exception as e:
        execution.status = ExecutionStatus.FAILED
        execution.error_message = str(e)
        execution.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return error(f"Pipeline execution failed: {e}", 500)

    # Update execution record
    serialized = serialize_pipeline_result(pipeline_result)
    execution.status = (
        ExecutionStatus.COMPLETED
        if pipeline_result.status == "completed"
        else ExecutionStatus.FAILED
    )
    execution.duration_ms = pipeline_result.total_duration_ms
    execution.completed_at = datetime.now(timezone.utc)
    execution.output_message = (
        str(pipeline_result.final_output)[:5000]
        if pipeline_result.final_output
        else None
    )
    execution.node_results = serialized.get("node_results")
    await db.commit()

    serialized["execution_id"] = str(execution.id)
    serialized["agent_id"] = agent_id

    return success(serialized)


@router.get("/{agent_id}/config")
async def get_pipeline_config(
    agent_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Return the saved pipeline_config from the agent's model_config_ JSONB column."""
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    model_config = agent.model_config_ or {}
    pipeline_config = model_config.get("pipeline_config")
    if pipeline_config is None:
        return error("No pipeline configuration found for this agent", 400)

    return success(pipeline_config)


@router.post("/{agent_id}/execute-saved")
async def execute_saved_pipeline(
    agent_id: str,
    body: ExecuteSavedPipelineRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Execute a pipeline using the agent's saved pipeline_config."""
    # Validate agent exists and user has access (includes OOB agents)
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    if agent.status not in (AgentStatus.ACTIVE, AgentStatus.DRAFT):
        return error("Agent is not in an executable state", 400)

    # Extract pipeline config
    model_config = agent.model_config_ or {}
    pipeline_config = model_config.get("pipeline_config")
    if not pipeline_config:
        return error("No pipeline configuration found for this agent", 400)

    raw_nodes = pipeline_config.get("nodes")
    if not raw_nodes:
        return error("Pipeline configuration has no nodes defined", 400)

    # Get tool names from agent config
    tool_names = model_config.get("tools", [])
    if not tool_names:
        return error("Agent has no tools configured", 400)

    # Check that all pipeline nodes reference available tools
    requested_tools = {n["tool_name"] for n in raw_nodes if "tool_name" in n}
    available = set(tool_names)
    missing = requested_tools - available
    if missing:
        return error(
            f"Pipeline uses tools not available on this agent: {sorted(missing)}. "
            f"Available: {sorted(available)}",
            400,
        )

    # Check for duplicate node IDs
    node_ids = [n.get("id") for n in raw_nodes]
    if len(node_ids) != len(set(node_ids)):
        return error("Duplicate node IDs in pipeline definition", 400)

    # Create execution record
    execution = Execution(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=user.tenant_id,
        user_id=user.id,
        input_message=f"[pipeline-saved:{len(raw_nodes)} nodes]",
        status=ExecutionStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    db.add(execution)
    await db.commit()

    # Build tool registry and execute saved pipeline
    from engine.agent_executor import build_tool_registry
    from engine.pipeline import PipelineExecutor, parse_pipeline_nodes, serialize_pipeline_result

    tool_registry = build_tool_registry(tool_names)
    executor = PipelineExecutor(
        tool_registry=tool_registry,
        timeout_seconds=body.timeout_seconds,
    )

    pipeline_nodes = parse_pipeline_nodes(raw_nodes)

    try:
        pipeline_result = await executor.execute(pipeline_nodes, body.context)
    except Exception as e:
        execution.status = ExecutionStatus.FAILED
        execution.error_message = str(e)
        execution.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return error(f"Pipeline execution failed: {e}", 500)

    # Update execution record
    serialized = serialize_pipeline_result(pipeline_result)
    execution.status = (
        ExecutionStatus.COMPLETED
        if pipeline_result.status == "completed"
        else ExecutionStatus.FAILED
    )
    execution.duration_ms = pipeline_result.total_duration_ms
    execution.completed_at = datetime.now(timezone.utc)
    execution.output_message = (
        str(pipeline_result.final_output)[:5000]
        if pipeline_result.final_output
        else None
    )
    execution.node_results = serialized.get("node_results")
    await db.commit()

    serialized["execution_id"] = str(execution.id)
    serialized["agent_id"] = agent_id

    return success(serialized)


@router.post("/{agent_id}/execute-stream")
async def execute_pipeline_stream(
    agent_id: str,
    body: ExecutePipelineRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Execute a pipeline with real-time SSE streaming of node progress."""
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == user.tenant_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    if agent.status not in (AgentStatus.ACTIVE, AgentStatus.DRAFT):
        return error("Agent is not in an executable state", 400)

    model_config = agent.model_config_ or {}
    tool_names = model_config.get("tools", [])
    if not tool_names:
        return error("Agent has no tools configured", 400)

    requested_tools = {n.tool_name for n in body.nodes}
    available_tools = set(tool_names)
    missing = requested_tools - available_tools
    if missing:
        return error(
            f"Pipeline uses tools not available on this agent: {sorted(missing)}",
            400,
        )

    node_ids = [n.id for n in body.nodes]
    if len(node_ids) != len(set(node_ids)):
        return error("Duplicate node IDs in pipeline definition", 400)

    execution = Execution(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=user.tenant_id,
        user_id=user.id,
        input_message=f"[pipeline-stream:{len(body.nodes)} nodes]",
        status=ExecutionStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    db.add(execution)
    await db.commit()

    from engine.agent_executor import build_tool_registry
    from engine.pipeline import PipelineExecutor, parse_pipeline_nodes, serialize_pipeline_result

    tool_registry = build_tool_registry(tool_names)

    event_queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def on_node_start(node_id: str, tool_name: str) -> None:
        event_data = json_module.dumps({"node_id": node_id, "tool_name": tool_name})
        await event_queue.put(f"event: node_start\ndata: {event_data}\n\n")

    async def on_node_complete(
        node_id: str, status: str, duration_ms: int, output: Any
    ) -> None:
        event_data = json_module.dumps({
            "node_id": node_id,
            "status": status,
            "duration_ms": duration_ms,
        }, default=str)
        await event_queue.put(f"event: node_complete\ndata: {event_data}\n\n")

    executor = PipelineExecutor(
        tool_registry=tool_registry,
        timeout_seconds=body.timeout_seconds,
        on_node_start=on_node_start,
        on_node_complete=on_node_complete,
    )

    raw_nodes = [n.model_dump() for n in body.nodes]
    pipeline_nodes = parse_pipeline_nodes(raw_nodes)

    async def run_pipeline() -> None:
        try:
            pipeline_result = await executor.execute(pipeline_nodes, body.context)
            execution.status = (
                ExecutionStatus.COMPLETED
                if pipeline_result.status == "completed"
                else ExecutionStatus.FAILED
            )
            execution.duration_ms = pipeline_result.total_duration_ms
            execution.completed_at = datetime.now(timezone.utc)
            execution.output_message = (
                str(pipeline_result.final_output)[:5000]
                if pipeline_result.final_output
                else None
            )
            await db.commit()

            serialized = serialize_pipeline_result(pipeline_result)
            serialized["execution_id"] = str(execution.id)
            serialized["agent_id"] = agent_id
            event_data = json_module.dumps(serialized, default=str)
            await event_queue.put(f"event: pipeline_complete\ndata: {event_data}\n\n")
        except Exception as e:
            execution.status = ExecutionStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.now(timezone.utc)
            await db.commit()
            event_data = json_module.dumps({"error": str(e)})
            await event_queue.put(f"event: pipeline_error\ndata: {event_data}\n\n")
        finally:
            await event_queue.put(None)

    async def event_generator():
        task = asyncio.create_task(run_pipeline())
        try:
            while True:
                event = await event_queue.get()
                if event is None:
                    break
                yield event
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{agent_id}/state")
async def get_pipeline_state(
    agent_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Return all persistent key-value state for a pipeline agent."""
    from models.pipeline_state import PipelineState

    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB))
    )
    if not result.scalar_one_or_none():
        return error("Agent not found", 404)

    state_result = await db.execute(
        select(PipelineState).where(PipelineState.agent_id == agent_id)
    )
    states = state_result.scalars().all()
    return success({s.key: s.value for s in states})


@router.put("/{agent_id}/state")
async def update_pipeline_state(
    agent_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Bulk update pipeline state keys. Body is a dict of key-value pairs."""
    from models.pipeline_state import PipelineState

    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB))
    )
    if not result.scalar_one_or_none():
        return error("Agent not found", 404)

    for key, value in body.items():
        existing = await db.execute(
            select(PipelineState).where(
                PipelineState.agent_id == agent_id,
                PipelineState.key == key,
            )
        )
        state = existing.scalar_one_or_none()
        if state:
            state.value = value
        else:
            db.add(PipelineState(
                agent_id=agent_id,
                tenant_id=str(user.tenant_id),
                key=key,
                value=value,
            ))
    await db.commit()
    return success({"updated": len(body)})


@router.post("/{agent_id}/replay")
async def replay_pipeline(
    agent_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Replay a pipeline from a specific node using cached outputs from a previous execution.

    Body: { "execution_id": str, "start_from_node": str, "context": dict }
    """
    from engine.pipeline import PipelineExecutor, parse_pipeline_nodes, serialize_pipeline_result
    from engine.agent_executor import build_tool_registry

    execution_id = body.get("execution_id")
    start_from = body.get("start_from_node")
    override_context = body.get("context", {})

    if not execution_id or not start_from:
        return error("execution_id and start_from_node are required", 400)

    # Load original execution
    exec_result = await db.execute(
        select(Execution).where(
            Execution.id == execution_id,
            Execution.tenant_id == user.tenant_id,
        )
    )
    original = exec_result.scalar_one_or_none()
    if not original:
        return error("Original execution not found", 404)

    # Load agent config
    agent_result = await db.execute(
        select(Agent).where(Agent.id == agent_id, or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB))
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    model_config = agent.model_config_ or {}
    pipeline_config = model_config.get("pipeline_config")
    if not pipeline_config or not pipeline_config.get("nodes"):
        return error("Agent has no pipeline config", 400)

    tool_names = model_config.get("tools", [])
    tool_registry = build_tool_registry(tool_names)

    raw_nodes = pipeline_config["nodes"]
    pipeline_nodes = parse_pipeline_nodes(raw_nodes)

    # Pre-populate node_outputs from the original execution's node_results
    cached_outputs: dict = {}
    if original.node_results:
        for nid, nr in original.node_results.items():
            if nid != start_from and nr.get("status") == "completed":
                cached_outputs[nid] = nr.get("output")

    # Merge with override context
    cached_outputs.update(override_context)
    if original.input_message:
        cached_outputs.setdefault("user_message", original.input_message)

    # Filter nodes: only execute start_from_node and its downstream
    # For simplicity, execute the full pipeline but with cached outputs pre-loaded
    executor = PipelineExecutor(tool_registry=tool_registry, timeout_seconds=120)
    result = await executor.execute(pipeline_nodes, cached_outputs)
    serialized = serialize_pipeline_result(result)

    # Create new execution record for the replay
    replay_exec = Execution(
        tenant_id=user.tenant_id,
        agent_id=agent.id,
        user_id=user.id,
        input_message=f"Replay from {start_from} (original: {execution_id})",
        status=ExecutionStatus.COMPLETED if result.status == "completed" else ExecutionStatus.FAILED,
        model_used="pipeline",
        duration_ms=result.total_duration_ms,
        node_results=serialized.get("node_results"),
        execution_trace={
            "replay_from": start_from,
            "original_execution_id": str(execution_id),
            "pipeline_status": result.status,
            "execution_path": result.execution_path,
        },
        parent_execution_id=original.id,
    )
    replay_exec.completed_at = datetime.now(timezone.utc)
    db.add(replay_exec)
    await db.commit()

    serialized["execution_id"] = str(replay_exec.id)
    serialized["replayed_from"] = str(execution_id)
    return success(serialized)


@router.post("/validate")
async def validate_pipeline_endpoint(
    body: dict,
    user: User = Depends(get_current_user),
) -> Any:
    """Validate a pipeline definition without executing it."""
    from engine.agent_executor import build_tool_registry
    from engine.pipeline_validator import validate_pipeline

    nodes = body.get("nodes", [])
    tool_names = body.get("tools", [])
    context_keys = set(body.get("context_keys", []))

    if not isinstance(nodes, list):
        return error("'nodes' must be a list", 400)

    try:
        tool_registry = build_tool_registry(tool_names)
    except Exception as e:
        return error(f"Failed to build tool registry: {e}", 500)

    result = validate_pipeline(nodes, tool_registry, available_context_keys=context_keys)
    return success(result.to_dict())


@router.post("/validate-smart")
async def validate_pipeline_smart(
    body: dict,
    user: User = Depends(get_current_user),
) -> Any:
    """Run the layered AI Validate stack on a pipeline config."""
    from engine.agent_executor import build_tool_registry
    from engine.pipeline_validator import validate_pipeline
    from engine.pipeline_validator_semantic import validate_semantic
    from engine.pipeline_validator_llm import critique

    nodes = body.get("nodes", [])
    tool_names = body.get("tools", [])
    context_keys = set(body.get("context_keys", []))
    purpose = body.get("purpose", "")
    deep = bool(body.get("deep", False))

    if not isinstance(nodes, list):
        return error("'nodes' must be a list", 400)

    try:
        tool_registry = build_tool_registry(tool_names)
    except Exception as e:
        return error(f"Failed to build tool registry: {e}", 500)

    tier1 = validate_pipeline(nodes, tool_registry, available_context_keys=context_keys)
    tier2 = validate_semantic(nodes, tool_registry, tier1=tier1)

    tier3_dict: dict | None = None
    if deep:
        report = await critique(
            kind="pipeline",
            config={"nodes": nodes, "tools": tool_names},
            purpose=purpose,
        )
        tier3_dict = report.to_dict()

    # Overall verdict — start from structural validity, demote for tier2 errors.
    valid = tier1.valid and len(tier2.errors) == 0
    if valid and len(tier2.warnings) > 0:
        severity = "warn"
    elif valid:
        severity = "ok"
    else:
        severity = "error"
    score = (tier3_dict or {}).get("coherence_score") if tier3_dict else (
        10 if severity == "ok" else 6 if severity == "warn" else 2
    )

    return success({
        "tier1": tier1.to_dict(),
        "tier2": tier2.to_dict(),
        "tier3": tier3_dict,
        "overall": {"valid": valid, "severity": severity, "score": score},
    })
