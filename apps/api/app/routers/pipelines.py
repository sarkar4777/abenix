"""Pipeline execution API — run DAG-based tool workflows with conditional branching."""

from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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


async def _budget_error(db: AsyncSession, agent: Agent, user: User) -> Any:
    from engine.agent_budget import BUDGET_EXCEEDED, check_agent_budget

    breach = await check_agent_budget(
        db,
        agent_id=agent.id,
        tenant_id=user.tenant_id,
        agent_name=agent.name,
        daily_cost_limit=getattr(agent, "daily_cost_limit", None),
        daily_budget_usd=getattr(agent, "daily_budget_usd", None),
    )
    if breach is None:
        return None
    return error(
        breach.message, 429, error_code=BUDGET_EXCEEDED, details=breach.details()
    )


def _apply_usage(execution: Execution, result: Any) -> None:
    from engine.pipeline import pipeline_provider_costs, pipeline_usage
    from models.execution import set_provider_costs

    usage = pipeline_usage(result)
    execution.cost = usage["cost"]
    execution.input_tokens = usage["input_tokens"] or None
    execution.output_tokens = usage["output_tokens"] or None
    set_provider_costs(execution, pipeline_provider_costs(result))


def _run_cost_limit(agent: Agent, requested: float | None) -> float | None:
    caps = [
        float(v)
        for v in (requested, getattr(agent, "per_execution_cost_limit", None))
        if v is not None and float(v) > 0
    ]
    return min(caps) if caps else None


async def _timeout_for(requested: int | None) -> int:
    if requested:
        return requested
    from app.core.platform_settings import get_int_setting

    return await get_int_setting("pipeline.timeout_seconds", 300)


async def _apply_dlp(tenant_id: Any, result: Any) -> None:
    from app.core.deps import async_session
    from engine.dlp import apply_to_pipeline_result

    try:
        async with async_session() as s:
            await apply_to_pipeline_result(s, tenant_id, result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pipeline dlp skipped: %s", exc)


async def _save_detached(row: Any) -> None:
    from app.core.deps import async_session

    async with async_session() as s:
        await s.merge(row)
        await s.commit()


@router.post("/{agent_id}/execute")
async def execute_pipeline(
    agent_id: str,
    body: ExecutePipelineRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Execute a DAG-based pipeline of tool calls against an agent's tool set."""
    if not body.nodes:
        return await execute_saved_pipeline(
            agent_id,
            ExecuteSavedPipelineRequest(
                context=body.context, timeout_seconds=body.timeout_seconds
            ),
            user,
            db,
        )
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

    budget_error = await _budget_error(db, agent, user)
    if budget_error is not None:
        return budget_error

    # Get tool names from agent config
    model_config = agent.model_config_ or {}
    tool_names = list(model_config.get("tools", []))
    tool_nodes = [n for n in body.nodes if n.type == "tool"]
    agent_nodes = [n for n in body.nodes if n.type == "agent"]
    if not tool_names and tool_nodes:
        return error("Agent has no tools configured", 400)

    # Tool nodes must reference tools available on the agent. Agent nodes
    # auto-add `agent_step` to the registry below — they don't need it on
    # the parent agent's tool list.
    requested_tools = {n.tool_name for n in tool_nodes if n.tool_name}
    available = set(tool_names)
    missing = requested_tools - available
    if missing:
        return error(
            f"Pipeline uses tools not available on this agent: {sorted(missing)}. "
            f"Available: {sorted(available)}",
            400,
        )

    # For type='agent' nodes, validate each referenced sub-agent exists +
    # caller has access (same tenant_id check as the parent agent lookup).
    if agent_nodes:
        sub_ids = [n.agent_id for n in agent_nodes if n.agent_id]
        sub_slugs = [n.agent_slug for n in agent_nodes if n.agent_slug]
        clauses = []
        if sub_ids:
            clauses.append(Agent.id.in_(sub_ids))
        if sub_slugs:
            clauses.append(Agent.slug.in_(sub_slugs))
        if clauses:
            sub_res = await db.execute(
                select(Agent.id, Agent.slug).where(
                    or_(
                        Agent.tenant_id == user.tenant_id,
                        Agent.agent_type == AgentType.OOB,
                    ),
                    or_(*clauses),
                )
            )
            found = sub_res.all()
            found_ids = {str(r[0]) for r in found}
            found_slugs = {r[1] for r in found if r[1]}
            for n in agent_nodes:
                if n.agent_id and str(n.agent_id) not in found_ids:
                    return error(
                        f"Sub-agent not found or not accessible: id={n.agent_id}",
                        400,
                    )
                if n.agent_slug and n.agent_slug not in found_slugs:
                    return error(
                        f"Sub-agent not found or not accessible: slug={n.agent_slug}",
                        400,
                    )
        # Auto-register agent_step so the executor can dispatch the sub-agent.
        if "agent_step" not in tool_names:
            tool_names.append("agent_step")

    # Check for duplicate node IDs
    node_ids = [n.id for n in body.nodes]
    if len(node_ids) != len(set(node_ids)):
        return error("Duplicate node IDs in pipeline definition", 400)

    # Create execution record
    from app.core.acting_subject import subject_columns_for
    from app.core.run_origin import caller_kind

    _sid, _stype = subject_columns_for(user)
    execution = Execution(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=user.tenant_id,
        user_id=user.id,
        subject_id=_sid,
        subject_type=_stype,
        input_message=f"[pipeline:{len(body.nodes)} nodes]",
        status=ExecutionStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
        trigger_kind=caller_kind(user, "builder"),
    )
    db.add(execution)
    await db.commit()

    # Build tool registry and execute pipeline
    from engine.agent_executor import build_tool_registry
    from engine.pipeline import (
        PipelineExecutor,
        parse_pipeline_nodes,
        serialize_pipeline_result,
    )

    tool_registry = build_tool_registry(tool_names)
    executor = PipelineExecutor(
        tool_registry=tool_registry,
        timeout_seconds=await _timeout_for(body.timeout_seconds),
        # Without db_url, _resolve_agent_by_slug cannot look up a
        # `type: agent` node and every such node failed with the
        # misleading "agent_slug 'x' not found in DB". agents.py
        # already passes this; the pipelines routes did not.
        # agent_id + tenant_id are REQUIRED for self-healing: pipeline.py
        # only calls healing.capture_failure when db_url, agent_id and
        # tenant_id are all set. No call site passed the latter two, so no
        # pipeline_run_diffs row was ever written and Pipeline Surgeon
        # always answered "no failure diff found".
        db_url=os.environ.get("DATABASE_URL", ""),
        agent_id=str(agent_id),
        tenant_id=str(user.tenant_id),
        cost_limit=_run_cost_limit(agent, getattr(body, "cost_limit", None)),
    )

    raw_nodes = [n.model_dump() for n in body.nodes]
    pipeline_nodes = parse_pipeline_nodes(raw_nodes)

    try:
        _ctx = dict(body.context or {})
        _ctx.setdefault("__execution_id", str(execution.id))
        pipeline_result = await executor.execute(pipeline_nodes, _ctx)
    except Exception as e:
        # Don't bubble a 5xx — UI's failure-render code needs status+execution_id
        # (see feedback_failure_visibility memory). Return 200 with failed body.
        execution.status = ExecutionStatus.FAILED
        execution.error_message = str(e)
        execution.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return success(
            {
                "execution_id": str(execution.id),
                "agent_id": agent_id,
                "status": "failed",
                "error_message": str(e),
            }
        )

    # Update execution record
    serialized = serialize_pipeline_result(pipeline_result)
    execution.status = (
        ExecutionStatus.COMPLETED
        if pipeline_result.status == "completed"
        else ExecutionStatus.FAILED
    )
    execution.duration_ms = pipeline_result.total_duration_ms
    _apply_usage(execution, pipeline_result)
    execution.completed_at = datetime.now(timezone.utc)
    await _apply_dlp(user.tenant_id, pipeline_result)
    execution.output_message = (
        str(pipeline_result.final_output)[:5000]
        if pipeline_result.final_output
        else None
    )
    execution.risk_tier = pipeline_result.risk_tier or execution.risk_tier
    execution.risk_reasons = pipeline_result.risk_reasons or None
    if pipeline_result.failure_code:
        execution.failure_code = pipeline_result.failure_code
    execution.node_results = serialized.get("node_results")
    if pipeline_result.status == "failed":
        # Surface the first node error so the UI doesn't have to dig through
        # node_results to learn why the pipeline failed.
        first_err = next(iter(pipeline_result.node_errors.values()), None)
        if first_err:
            execution.error_message = first_err
            serialized["error_message"] = first_err
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

    budget_error = await _budget_error(db, agent, user)
    if budget_error is not None:
        return budget_error

    # Extract pipeline config
    model_config = agent.model_config_ or {}
    pipeline_config = model_config.get("pipeline_config")
    if not pipeline_config:
        return error("No pipeline configuration found for this agent", 400)

    raw_nodes = pipeline_config.get("nodes")
    if not raw_nodes:
        return error("Pipeline configuration has no nodes defined", 400)

    # Get tool names from agent config
    tool_names = list(model_config.get("tools", []))
    # Saved-config nodes are raw dicts — classify by raw["type"]
    saved_tool_nodes = [
        n for n in raw_nodes if (n.get("type") or "tool").lower() == "tool"
    ]
    saved_agent_nodes = [
        n for n in raw_nodes if (n.get("type") or "tool").lower() == "agent"
    ]
    if not tool_names and saved_tool_nodes:
        return error("Agent has no tools configured", 400)

    # Tool nodes must reference tools available on the agent.
    requested_tools = {n["tool_name"] for n in saved_tool_nodes if n.get("tool_name")}
    available = set(tool_names)
    missing = requested_tools - available
    if missing:
        return error(
            f"Pipeline uses tools not available on this agent: {sorted(missing)}. "
            f"Available: {sorted(available)}",
            400,
        )

    if saved_agent_nodes and "agent_step" not in tool_names:
        tool_names.append("agent_step")

    # Check for duplicate node IDs
    node_ids = [n.get("id") for n in raw_nodes]
    if len(node_ids) != len(set(node_ids)):
        return error("Duplicate node IDs in pipeline definition", 400)

    # Create execution record
    from app.core.acting_subject import subject_columns_for
    from app.core.run_origin import caller_kind

    _sid, _stype = subject_columns_for(user)
    execution = Execution(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=user.tenant_id,
        user_id=user.id,
        subject_id=_sid,
        subject_type=_stype,
        input_message=f"[pipeline-saved:{len(raw_nodes)} nodes]",
        status=ExecutionStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
        trigger_kind=caller_kind(user, "builder"),
    )
    db.add(execution)
    await db.commit()

    # Build tool registry and execute saved pipeline
    from engine.agent_executor import build_tool_registry
    from engine.pipeline import (
        PipelineExecutor,
        parse_pipeline_nodes,
        serialize_pipeline_result,
    )

    tool_registry = build_tool_registry(tool_names)
    executor = PipelineExecutor(
        tool_registry=tool_registry,
        timeout_seconds=await _timeout_for(body.timeout_seconds),
        # Without db_url, _resolve_agent_by_slug cannot look up a
        # `type: agent` node and every such node failed with the
        # misleading "agent_slug 'x' not found in DB". agents.py
        # already passes this; the pipelines routes did not.
        # agent_id + tenant_id are REQUIRED for self-healing: pipeline.py
        # only calls healing.capture_failure when db_url, agent_id and
        # tenant_id are all set. No call site passed the latter two, so no
        # pipeline_run_diffs row was ever written and Pipeline Surgeon
        # always answered "no failure diff found".
        db_url=os.environ.get("DATABASE_URL", ""),
        agent_id=str(agent_id),
        tenant_id=str(user.tenant_id),
        cost_limit=_run_cost_limit(agent, getattr(body, "cost_limit", None)),
    )

    pipeline_nodes = parse_pipeline_nodes(raw_nodes)

    try:
        _ctx = dict(body.context or {})
        _ctx.setdefault("__execution_id", str(execution.id))
        pipeline_result = await executor.execute(pipeline_nodes, _ctx)
    except Exception as e:
        execution.status = ExecutionStatus.FAILED
        execution.error_message = str(e)
        execution.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return success(
            {
                "execution_id": str(execution.id),
                "agent_id": agent_id,
                "status": "failed",
                "error_message": str(e),
            }
        )

    # Update execution record
    serialized = serialize_pipeline_result(pipeline_result)
    execution.status = (
        ExecutionStatus.COMPLETED
        if pipeline_result.status == "completed"
        else ExecutionStatus.FAILED
    )
    execution.duration_ms = pipeline_result.total_duration_ms
    _apply_usage(execution, pipeline_result)
    execution.completed_at = datetime.now(timezone.utc)
    await _apply_dlp(user.tenant_id, pipeline_result)
    execution.output_message = (
        str(pipeline_result.final_output)[:5000]
        if pipeline_result.final_output
        else None
    )
    execution.risk_tier = pipeline_result.risk_tier or execution.risk_tier
    execution.risk_reasons = pipeline_result.risk_reasons or None
    if pipeline_result.failure_code:
        execution.failure_code = pipeline_result.failure_code
    execution.node_results = serialized.get("node_results")
    if pipeline_result.status == "failed":
        first_err = next(iter(pipeline_result.node_errors.values()), None)
        if first_err:
            execution.error_message = first_err
            serialized["error_message"] = first_err
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

    budget_error = await _budget_error(db, agent, user)
    if budget_error is not None:
        return budget_error

    model_config = agent.model_config_ or {}
    tool_names = list(model_config.get("tools", []))
    stream_tool_nodes = [n for n in body.nodes if n.type == "tool"]
    stream_agent_nodes = [n for n in body.nodes if n.type == "agent"]
    if not tool_names and stream_tool_nodes:
        return error("Agent has no tools configured", 400)

    requested_tools = {n.tool_name for n in stream_tool_nodes if n.tool_name}
    available_tools = set(tool_names)
    missing = requested_tools - available_tools
    if missing:
        return error(
            f"Pipeline uses tools not available on this agent: {sorted(missing)}",
            400,
        )

    if stream_agent_nodes and "agent_step" not in tool_names:
        tool_names.append("agent_step")

    node_ids = [n.id for n in body.nodes]
    if len(node_ids) != len(set(node_ids)):
        return error("Duplicate node IDs in pipeline definition", 400)

    from app.core.acting_subject import subject_columns_for
    from app.core.run_origin import caller_kind

    _sid, _stype = subject_columns_for(user)
    execution = Execution(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=user.tenant_id,
        user_id=user.id,
        subject_id=_sid,
        subject_type=_stype,
        input_message=f"[pipeline-stream:{len(body.nodes)} nodes]",
        status=ExecutionStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
        trigger_kind=caller_kind(user, "builder"),
    )
    db.add(execution)
    await db.commit()

    from engine.agent_executor import build_tool_registry
    from engine.pipeline import (
        PipelineExecutor,
        parse_pipeline_nodes,
        pipeline_timed_out,
        serialize_pipeline_result,
    )

    tool_registry = build_tool_registry(tool_names)

    event_queue: asyncio.Queue[str | None] = asyncio.Queue()

    _statuses: dict[str, str] = dict.fromkeys(node_ids, "pending")

    async def on_node_start(node_id: str, tool_name: str) -> None:
        _statuses[node_id] = "running"
        event_data = json_module.dumps({"node_id": node_id, "tool_name": tool_name})
        await event_queue.put(f"event: node_start\ndata: {event_data}\n\n")

    async def on_node_complete(
        node_id: str,
        status: str,
        duration_ms: int,
        output: Any,
        error_message: str | None = None,
        error_type: str | None = None,
    ) -> None:
        _statuses[node_id] = status
        event_data = json_module.dumps(
            {
                "node_id": node_id,
                "status": status,
                "duration_ms": duration_ms,
                "error_message": error_message,
                "error_type": error_type,
            },
            default=str,
        )
        await event_queue.put(f"event: node_complete\ndata: {event_data}\n\n")

    executor = PipelineExecutor(
        tool_registry=tool_registry,
        timeout_seconds=await _timeout_for(body.timeout_seconds),
        on_node_start=on_node_start,
        on_node_complete=on_node_complete,
        # agent_id + tenant_id are REQUIRED for self-healing: pipeline.py
        # only calls healing.capture_failure when db_url, agent_id and
        # tenant_id are all set. No call site passed the latter two, so no
        # pipeline_run_diffs row was ever written and Pipeline Surgeon
        # always answered "no failure diff found".
        db_url=os.environ.get("DATABASE_URL", ""),
        agent_id=str(agent_id),
        tenant_id=str(user.tenant_id),
        cost_limit=_run_cost_limit(agent, getattr(body, "cost_limit", None)),
    )

    raw_nodes = [n.model_dump() for n in body.nodes]
    pipeline_nodes = parse_pipeline_nodes(raw_nodes)

    async def run_pipeline() -> None:
        try:
            _ctx = dict(body.context or {})
            _ctx.setdefault("__execution_id", str(execution.id))
            try:
                pipeline_result = await asyncio.wait_for(
                    executor.execute(pipeline_nodes, _ctx),
                    # the engine checks its budget between layers, this catches a step that hangs
                    timeout=executor.timeout_seconds + 5,
                )
            except asyncio.TimeoutError:
                pipeline_result = pipeline_timed_out(
                    executor.timeout_seconds, _statuses
                )
                execution.error_message = pipeline_result.node_errors["pipeline"]
            await _apply_dlp(user.tenant_id, pipeline_result)
            execution.status = (
                ExecutionStatus.COMPLETED
                if pipeline_result.status == "completed"
                else ExecutionStatus.FAILED
            )
            execution.duration_ms = pipeline_result.total_duration_ms
            _apply_usage(execution, pipeline_result)
            execution.completed_at = datetime.now(timezone.utc)
            execution.output_message = (
                str(pipeline_result.final_output)[:5000]
                if pipeline_result.final_output
                else None
            )
            execution.risk_tier = pipeline_result.risk_tier or execution.risk_tier
            execution.risk_reasons = pipeline_result.risk_reasons or None
            if pipeline_result.failure_code:
                execution.failure_code = pipeline_result.failure_code
            await _save_detached(execution)

            serialized = serialize_pipeline_result(pipeline_result)
            serialized["execution_id"] = str(execution.id)
            serialized["agent_id"] = agent_id
            event_data = json_module.dumps(serialized, default=str)
            await event_queue.put(f"event: pipeline_complete\ndata: {event_data}\n\n")
        except Exception as e:
            execution.status = ExecutionStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.now(timezone.utc)
            await _save_detached(execution)
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

    # the run outlives the request, its final write goes through a session of its own
    await db.close()
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
        select(Agent).where(
            Agent.id == agent_id,
            or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB),
        )
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
        select(Agent).where(
            Agent.id == agent_id,
            or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB),
        )
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
            db.add(
                PipelineState(
                    agent_id=agent_id,
                    tenant_id=str(user.tenant_id),
                    key=key,
                    value=value,
                )
            )
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
    from engine.pipeline import (
        PipelineExecutor,
        parse_pipeline_nodes,
        serialize_pipeline_result,
    )
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
        select(Agent).where(
            Agent.id == agent_id,
            or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB),
        )
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    budget_error = await _budget_error(db, agent, user)
    if budget_error is not None:
        return budget_error

    model_config = agent.model_config_ or {}
    pipeline_config = model_config.get("pipeline_config")
    if not pipeline_config or not pipeline_config.get("nodes"):
        return error("Agent has no pipeline config", 400)

    tool_names = model_config.get("tools", [])
    tool_registry = build_tool_registry(tool_names)

    raw_nodes = pipeline_config["nodes"]
    pipeline_nodes = parse_pipeline_nodes(raw_nodes)

    downstream_ids: set[str] = {start_from}
    adjacency: dict[str, list[str]] = {}
    for n in pipeline_nodes:
        for dep in n.depends_on:
            adjacency.setdefault(dep, []).append(n.id)
    frontier = [start_from]
    while frontier:
        nxt: list[str] = []
        for nid in frontier:
            for child in adjacency.get(nid, []):
                if child not in downstream_ids:
                    downstream_ids.add(child)
                    nxt.append(child)
        frontier = nxt

    cached_outputs: dict = {}
    if original.node_results:
        for nid, nr in original.node_results.items():
            if nid not in downstream_ids and nr.get("status") == "completed":
                cached_outputs[nid] = nr.get("output")

    cached_outputs.update(override_context)
    if original.input_message:
        cached_outputs.setdefault("user_message", original.input_message)

    pipeline_nodes = [n for n in pipeline_nodes if n.id in downstream_ids]

    executor = PipelineExecutor(
        tool_registry=tool_registry,
        timeout_seconds=120,
        # agent_id + tenant_id are REQUIRED for self-healing: pipeline.py
        # only calls healing.capture_failure when db_url, agent_id and
        # tenant_id are all set. No call site passed the latter two, so no
        # pipeline_run_diffs row was ever written and Pipeline Surgeon
        # always answered "no failure diff found".
        db_url=os.environ.get("DATABASE_URL", ""),
        agent_id=str(agent_id),
        tenant_id=str(user.tenant_id),
        cost_limit=_run_cost_limit(agent, getattr(body, "cost_limit", None)),
    )
    # pipeline.py's healing capture reads the execution id from the
    # context. Without it capture_failure got the all-zeros UUID and the
    # insert died on the executions FK, so Pipeline Surgeon never had a
    # diff to work with.
    _ctx = dict(cached_outputs or {})
    # A replay's own execution row is created further down, so anchor the diff
    # to the execution being replayed.
    _ctx.setdefault("__execution_id", str(original.id))
    result = await executor.execute(pipeline_nodes, _ctx)
    serialized = serialize_pipeline_result(result)

    # Create new execution record for the replay
    from app.core.acting_subject import subject_columns_for

    _sid, _stype = subject_columns_for(user)
    replay_exec = Execution(
        trigger_kind="replay",
        trigger_name=f"Replay from {start_from}"[:255],
        tenant_id=user.tenant_id,
        agent_id=agent.id,
        user_id=user.id,
        subject_id=_sid,
        subject_type=_stype,
        input_message=f"Replay from {start_from} (original: {execution_id})",
        status=(
            ExecutionStatus.COMPLETED
            if result.status == "completed"
            else ExecutionStatus.FAILED
        ),
        model_used="pipeline",
        duration_ms=result.total_duration_ms,
        cost=serialized["cost"],
        input_tokens=serialized["input_tokens"] or None,
        output_tokens=serialized["output_tokens"] or None,
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


def _registry_names_for_nodes(
    nodes: list[dict[str, Any]], caller_tools: list[str]
) -> list[str]:
    """Tool names the validator needs in order to judge these nodes.

    The UI sends the *agent's* selected tools, but a pipeline step picks its
    tool per-step in the designer — `code_asset`, `ml_model`, `llm_call`,
    `agent_step`, `sub_pipeline`, `approval_gate`, `connector_call` all have
    their own config panels and are not normally in an agent's tool list.
    Validating against the agent list alone rejected perfectly good pipelines
    with a misleading "Unknown tool 'code_asset'", which is the opposite of
    helpful. Union the caller's list with every tool the nodes actually
    reference that the runtime can really run, so "Unknown tool" is reserved
    for names that genuinely do not exist.
    """
    names = {t for t in (caller_tools or []) if isinstance(t, str)}
    referenced: set[str] = set()
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        for key in ("tool", "tool_name", "tool_slug"):
            v = n.get(key)
            if isinstance(v, str) and v:
                referenced.add(v)
    if referenced:
        try:
            from engine.agent_executor import list_tool_classes  # type: ignore

            names |= referenced & set(list_tool_classes())
        except Exception as exc:  # pragma: no cover
            logger.debug("could not consult runtime tool registry: %s", exc)
    return sorted(names)


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

    tool_names = _registry_names_for_nodes(nodes, tool_names)

    try:
        tool_registry = build_tool_registry(tool_names)
    except Exception as e:
        return error(f"Failed to build tool registry: {e}", 500)

    result = validate_pipeline(
        nodes, tool_registry, available_context_keys=context_keys
    )
    payload = result.to_dict()
    # The registry above intentionally includes step tools that aren't on the
    # agent, so argument checking is accurate instead of collapsing to
    # "Unknown tool". But execute_pipeline refuses tools the agent hasn't been
    # granted, so surface that as its own finding — otherwise validation would
    # pass something execution then rejects.
    granted = {t for t in (body.get("tools") or []) if isinstance(t, str)}
    if granted:
        for n in nodes:
            if not isinstance(n, dict):
                continue
            t = n.get("tool") or n.get("tool_name") or n.get("tool_slug")
            if isinstance(t, str) and t and t not in granted and t != "agent_step":
                payload.setdefault("errors", []).append(
                    {
                        "node_id": n.get("id", ""),
                        "field": "tool",
                        "message": (
                            f"Tool '{t}' exists but is not enabled on this agent"
                        ),
                        "severity": "error",
                        "suggestion": (
                            f"Add '{t}' to the agent's tools, or the pipeline will "
                            f"fail at execution with "
                            f"'uses tools not available on this agent'."
                        ),
                    }
                )
                payload["valid"] = False
    return success(payload)


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
    tool_names = _registry_names_for_nodes(body.get("nodes", []), tool_names)
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
        # Honour the configurable Builder validation model. Falls back to the
        # critic default inside `critique` when the setting is unset.
        from app.core.platform_settings import get_setting as _ps_get

        critic_model = (
            await _ps_get("ai_builder.validation.model")
        ) or "claude-sonnet-4-5-20250929"
        report = await critique(
            kind="pipeline",
            config={"nodes": nodes, "tools": tool_names},
            purpose=purpose,
            model=critic_model,
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
    score = (
        (tier3_dict or {}).get("coherence_score")
        if tier3_dict
        else (10 if severity == "ok" else 6 if severity == "warn" else 2)
    )

    return success(
        {
            "tier1": tier1.to_dict(),
            "tier2": tier2.to_dict(),
            "tier3": tier3_dict,
            "overall": {"valid": valid, "severity": severity, "score": score},
        }
    )


@router.post("/{agent_id}/validate")
async def validate_agent_pipeline(
    agent_id: str,
    body: ExecutePipelineRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Dry-run validate a pipeline against an agent's config — no side effects.

    Returns {valid, errors, plan} so the UI can surface structural and
    cross-reference problems before the user hits Execute.
    """
    from engine.pipeline import parse_pipeline_nodes

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
    tool_names = list(model_config.get("tools", []))
    errors: list[str] = []

    tool_nodes = [n for n in body.nodes if n.type == "tool"]
    agent_nodes = [n for n in body.nodes if n.type == "agent"]

    requested_tools = {n.tool_name for n in tool_nodes if n.tool_name}
    missing_tools = requested_tools - set(tool_names)
    if missing_tools:
        errors.append(
            f"missing_tools: {sorted(missing_tools)} (available: {sorted(tool_names)})"
        )

    if agent_nodes:
        sub_ids = [n.agent_id for n in agent_nodes if n.agent_id]
        sub_slugs = [n.agent_slug for n in agent_nodes if n.agent_slug]
        clauses = []
        if sub_ids:
            clauses.append(Agent.id.in_(sub_ids))
        if sub_slugs:
            clauses.append(Agent.slug.in_(sub_slugs))
        found_ids: set[str] = set()
        found_slugs: set[str] = set()
        if clauses:
            sub_res = await db.execute(
                select(Agent.id, Agent.slug).where(
                    or_(
                        Agent.tenant_id == user.tenant_id,
                        Agent.agent_type == AgentType.OOB,
                    ),
                    or_(*clauses),
                )
            )
            for r in sub_res.all():
                found_ids.add(str(r[0]))
                if r[1]:
                    found_slugs.add(r[1])
        for n in agent_nodes:
            if n.agent_id and str(n.agent_id) not in found_ids:
                errors.append(f"unknown_agent_id: {n.agent_id} (node: {n.id})")
            if n.agent_slug and n.agent_slug not in found_slugs:
                errors.append(f"unknown_agent_slug: {n.agent_slug} (node: {n.id})")

    # Duplicate IDs + unknown deps
    node_ids = [n.id for n in body.nodes]
    if len(node_ids) != len(set(node_ids)):
        errors.append("duplicate_node_ids")
    known_ids = set(node_ids)
    for n in body.nodes:
        for dep in n.depends_on:
            if dep not in known_ids:
                errors.append(f"unknown_dependency: {dep} (node: {n.id})")

    # Build the topological plan so the UI can render execution layers.
    plan: list[list[str]] = []
    try:
        from engine.pipeline import _topological_sort

        raw_nodes = [n.model_dump() for n in body.nodes]
        parsed = parse_pipeline_nodes(raw_nodes)
        if not any(e.startswith("unknown_dependency") for e in errors):
            plan = _topological_sort(parsed)
    except ValueError as e:
        errors.append(f"dag_error: {e}")

    return success(
        {
            "valid": len(errors) == 0,
            "errors": errors,
            "plan": plan,
        }
    )
