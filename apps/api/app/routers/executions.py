"""Live execution monitoring and HITL approval endpoints."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.execution_state import (
    get_execution_tree,
    get_live_state,
    get_tenant_live_executions,
)
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent
from models.execution import Execution, ExecutionStatus
from models.user import User

router = APIRouter(prefix="/api/executions", tags=["executions"])


@router.get("/live")
async def list_live_executions(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Get all currently-running executions for the tenant."""
    executions = await get_tenant_live_executions(str(user.tenant_id))
    return success(executions)


@router.get("/live/stream")
async def stream_live_executions(
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE stream that emits execution state changes every 2 seconds."""
    tenant_id = str(user.tenant_id)

    async def _generate():
        prev_snapshot = ""
        while True:
            executions = await get_tenant_live_executions(tenant_id)
            snapshot = json.dumps(executions, default=str)
            if snapshot != prev_snapshot:
                yield f"event: state\ndata: {snapshot}\n\n"
                prev_snapshot = snapshot
            if not executions:
                yield "event: idle\ndata: {}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/live/{execution_id}")
async def get_live_execution(
    execution_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Get live state for a specific execution."""
    state = await get_live_state(str(execution_id))
    if not state:
        return error("Execution not found or not running", 404)
    if state.get("tenant_id") != str(user.tenant_id):
        return error("Execution not found or not running", 404)
    return success(state)


@router.get("/tree/{execution_id}")
async def get_execution_tree_endpoint(
    execution_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Get the execution tree (parent + all child executions)."""
    tree = await get_execution_tree(str(execution_id))
    if not tree["parent"]:
        return error("Execution tree not found", 404)
    if tree["parent"].get("tenant_id") != str(user.tenant_id):
        return error("Execution tree not found", 404)
    return success(tree)


class ApprovalRequest(BaseModel):
    decision: str  # "approved" or "rejected"
    comment: str = ""


@router.get("/approvals")
async def list_pending_approvals(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """List all pending HITL approval requests for the tenant."""
    # Import here to avoid circular dependency with agent-runtime
    import importlib
    try:
        hitl = importlib.import_module("engine.tools.human_approval")
        approvals = await hitl.list_pending_approvals(str(user.tenant_id))
    except ImportError:
        # Agent runtime not on path — use Redis directly
        import redis.asyncio as aioredis
        from app.core.config import settings as app_cfg
        r = aioredis.from_url(app_cfg.redis_url, decode_responses=True)
        members = await r.smembers(f"hitl:pending:{user.tenant_id}")
        await r.aclose()
        approvals = []
        for m in members:
            data = json.loads(m)
            # Check if already decided
            check_r = aioredis.from_url(app_cfg.redis_url, decode_responses=True)
            decided = await check_r.get(
                f"hitl:approval:{data['execution_id']}:{data['gate_id']}"
            )
            await check_r.aclose()
            if not decided:
                approvals.append(data)
    return success(approvals)


@router.post("/{execution_id}/approve")
async def approve_execution_gate(
    execution_id: uuid.UUID,
    body: ApprovalRequest,
    gate_id: str = Query(..., description="The gate ID to approve/reject"),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Approve or reject a Human-in-the-Loop gate."""
    if body.decision not in ("approved", "rejected"):
        return error("Decision must be 'approved' or 'rejected'", 400)

    import redis.asyncio as aioredis
    from app.core.config import settings as app_cfg

    r = aioredis.from_url(app_cfg.redis_url, decode_responses=True)
    approval_key = f"hitl:approval:{execution_id}:{gate_id}"
    result = json.dumps({
        "decision": body.decision,
        "reviewer": user.full_name or user.email,
        "comment": body.comment,
        "decided_at": __import__("time").time(),
    })
    await r.set(approval_key, result, ex=7200)
    await r.aclose()

    return success({
        "execution_id": str(execution_id),
        "gate_id": gate_id,
        "decision": body.decision,
    })


@router.get("/{execution_id}/stream", response_model=None)
async def stream_execution_events(
    execution_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse | JSONResponse:
    """Replay-then-live SSE stream of events for a (Wave-2 remote) execution."""
    # Authz: the execution must belong to the caller's tenant
    result = await db.execute(
        select(Execution).where(
            Execution.id == execution_id,
            Execution.tenant_id == user.tenant_id,
        )
    )
    if result.scalar_one_or_none() is None:
        return error("Execution not found", 404)

    from app.core.execution_bus import subscribe_events

    async def _gen():
        async for evt in subscribe_events(str(execution_id)):
            data = json.dumps(evt, default=str)
            ev_name = evt.get("event") or "message"
            yield f"event: {ev_name}\ndata: {data}\n\n".encode()

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _assemble_dag_snapshot(
    execution_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """Join the live Redis state + the persisted execution row into a"""
    # Historical view from Postgres
    result = await db.execute(
        select(Execution, Agent.name, Agent.model_config_)
        .outerjoin(Agent, Execution.agent_id == Agent.id)
        .where(Execution.id == execution_id)
    )
    row = result.first()
    if row is None:
        return {}
    execution, agent_name, agent_mc = row

    # Live view from Redis (may be None if the execution finished long ago
    # or if Redis is down — we just fall back to the DB view).
    live = await get_live_state(str(execution_id))
    live = live or {}

    # Derive mode from the agent's model_config (pipeline vs agent).
    mode = "pipeline" if (agent_mc or {}).get("mode") == "pipeline" else "agent"

    # Node results from the execution row. Pipeline runs populate this;
    # single-agent runs leave it empty and we synthesise a one-node
    # graph so the UI can still render *something* useful.
    node_results = (execution.node_results or {}) if hasattr(execution, "node_results") else {}
    live_node_statuses = live.get("node_statuses") or {}

    nodes: list[dict] = []
    edges: list[dict] = []
    pipeline_nodes = (agent_mc or {}).get("pipeline_config", {}).get("nodes", []) if mode == "pipeline" else []

    if pipeline_nodes:
        # Build one Node per declared pipeline step.
        for n in pipeline_nodes:
            nid = n.get("id")
            nr = node_results.get(nid) or {}
            # Prefer live status, then result status, then pending.
            status = (
                live_node_statuses.get(nid)
                or nr.get("status")
                or "pending"
            )
            node_out = nr.get("output") if isinstance(nr, dict) else None
            cost = None
            tokens_in = None
            tokens_out = None
            if isinstance(node_out, dict):
                cost = node_out.get("cost")
                tokens_in = node_out.get("input_tokens")
                tokens_out = node_out.get("output_tokens")
            nodes.append({
                "id": nid,
                "label": n.get("label") or nid,
                "tool_name": n.get("tool_name") or (n.get("type") == "structured" and "__structured__" or n.get("tool") or ""),
                "agent_slug": n.get("agent_slug"),
                "status": status,
                "started_at": nr.get("started_at") if isinstance(nr, dict) else None,
                "completed_at": nr.get("completed_at") if isinstance(nr, dict) else None,
                "duration_ms": (nr.get("duration_ms") if isinstance(nr, dict) else None),
                "input": n.get("arguments") or {},
                "output": node_out,
                "cost": cost,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "tool_calls": nr.get("tool_calls") if isinstance(nr, dict) else None,
                "error": nr.get("error") if isinstance(nr, dict) else None,
            })
        # Edges = declared depends_on plus template-inferred refs (same
        # rule the engine applies at execution time). Simple first
        # pass: use declared depends_on only — the engine already
        # expanded template refs into depends_on at parse time.
        for n in pipeline_nodes:
            for dep in (n.get("depends_on") or []):
                edges.append({"from": dep, "to": n.get("id"), "field": None})
    else:
        # Iterative-agent mode: one synthetic node representing the
        # whole run, tool_calls populate the chain. The UI renders it
        # as a linear trace.
        tool_calls = execution.tool_calls or []
        nodes.append({
            "id": "agent",
            "label": agent_name or "Agent",
            "tool_name": "agent",
            "agent_slug": None,
            "status": live.get("status") or (execution.status.value if hasattr(execution.status, "value") else str(execution.status)).lower(),
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
            "duration_ms": execution.duration_ms,
            "input": {"message": execution.input_message},
            "output": execution.output_message,
            "cost": float(execution.cost) if execution.cost is not None else None,
            "tokens_in": execution.input_tokens,
            "tokens_out": execution.output_tokens,
            "tool_calls": tool_calls,
            "error": execution.error_message,
        })

    total = len(nodes) or 1
    completed = sum(1 for n in nodes if n["status"] == "completed")
    status_raw = live.get("status") or (
        execution.status.value if hasattr(execution.status, "value")
        else str(execution.status)
    )
    status = status_raw.lower() if isinstance(status_raw, str) else str(status_raw).lower()

    return {
        "execution_id": str(execution_id),
        "agent_id": str(execution.agent_id),
        "agent_name": agent_name,
        "mode": mode,
        "status": status,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        "current_node_id": live.get("current_step") or None,
        "progress": {"completed": completed, "total": total},
        "cost_so_far": float(execution.cost) if execution.cost is not None else (
            float(live.get("cost") or 0) if live else 0.0
        ),
        "tokens": {
            "in": int(execution.input_tokens or 0),
            "out": int(execution.output_tokens or 0),
        },
        "nodes": nodes,
        "edges": edges,
    }


@router.get("/{execution_id}/watch")
async def watch_execution(
    execution_id: uuid.UUID,
    request: Request,
    token: str | None = Query(None, description="Bearer token fallback (EventSource can't set headers)"),
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Live DAG snapshot stream for a single execution."""
    # Resolve the caller manually because `Depends(get_current_user)` doesn't
    # support a query-param token fallback, and browser EventSource has no
    # way to send Authorization/X-API-Key headers.
    effective_auth = authorization
    if not effective_auth and token:
        effective_auth = f"Bearer {token}"
    try:
        user = await get_current_user(
            authorization=effective_auth,
            x_api_key=x_api_key,
            x_abenix_subject=None,
            db=db,
        )
    except Exception:
        return error("Unauthorized", 401)

    # Authz — execution must belong to the caller's tenant.
    result = await db.execute(
        select(Execution).where(
            Execution.id == execution_id,
            Execution.tenant_id == user.tenant_id,
        )
    )
    if result.scalar_one_or_none() is None:
        return error("Execution not found", 404)

    from app.core.execution_bus import subscribe_events

    async def _gen():
        # Always emit an initial snapshot so a client that connects
        # AFTER the pipeline finishes still gets the full graph and
        # can close cleanly.
        try:
            initial = await _assemble_dag_snapshot(execution_id, db)
            yield f"event: snapshot\ndata: {json.dumps(initial, default=str)}\n\n".encode()
            if initial.get("status") in ("completed", "failed"):
                yield b"event: end\ndata: {}\n\n"
                return
        except Exception as e:  # pragma: no cover
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n".encode()
            return

        last_emit = 0.0
        debounce = 0.05
        try:
            async for evt in subscribe_events(str(execution_id)):
                ev = evt.get("event") or "message"
                now = asyncio.get_event_loop().time()
                if now - last_emit < debounce and ev not in ("done", "error"):
                    continue
                last_emit = now
                snap = await _assemble_dag_snapshot(execution_id, db)
                yield f"event: snapshot\ndata: {json.dumps(snap, default=str)}\n\n".encode()
                if ev in ("done", "error") or snap.get("status") in ("completed", "failed"):
                    yield b"event: end\ndata: {}\n\n"
                    return
        except asyncio.CancelledError:
            # Client disconnected — nothing to clean up, the bus
            # subscription is GC'd when the generator closes.
            return

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{execution_id}")
async def get_execution(
    execution_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get a historical execution record from the database."""
    result = await db.execute(
        select(Execution, Agent.name, Agent.system_prompt, Agent.model_config_)
        .outerjoin(Agent, Execution.agent_id == Agent.id)
        .where(
            Execution.id == execution_id,
            Execution.tenant_id == user.tenant_id,
        )
    )
    row = result.first()
    if not row:
        return error("Execution not found", 404)
    execution = row[0]
    data = _serialize_execution(execution)
    data["agent_name"] = row[1]
    data["system_prompt"] = row[2]
    # Include tool_config if present for debugging
    mc = row[3] or {}
    if mc.get("tool_config"):
        data["tool_config"] = mc["tool_config"]
    return success(data)


@router.get("")
async def list_executions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    agent_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    search: str = Query("", max_length=255, description="Search in input message"),
    sort: str = Query("newest", description="Sort: newest, oldest, cost_high, cost_low, duration"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    """List past executions with optional filters."""
    query = select(Execution).where(Execution.tenant_id == user.tenant_id)
    count_query = select(func.count(Execution.id)).where(
        Execution.tenant_id == user.tenant_id
    )

    if agent_id:
        query = query.where(Execution.agent_id == agent_id)
        count_query = count_query.where(Execution.agent_id == agent_id)
    if status:
        query = query.where(Execution.status == ExecutionStatus(status))
        count_query = count_query.where(Execution.status == ExecutionStatus(status))
    if search:
        query = query.where(Execution.input_message.ilike(f"%{search}%"))
        count_query = count_query.where(Execution.input_message.ilike(f"%{search}%"))

    total = (await db.execute(count_query)).scalar() or 0

    # Completed / failed counts (unfiltered by status so the KPI cards are always correct)
    base_where = [Execution.tenant_id == user.tenant_id]
    if agent_id:
        base_where.append(Execution.agent_id == agent_id)
    if search:
        base_where.append(Execution.input_message.ilike(f"%{search}%"))
    completed_count = (await db.execute(
        select(func.count(Execution.id)).where(*base_where, Execution.status == ExecutionStatus.COMPLETED)
    )).scalar() or 0
    failed_count = (await db.execute(
        select(func.count(Execution.id)).where(*base_where, Execution.status == ExecutionStatus.FAILED)
    )).scalar() or 0

    # Join with Agent to get agent_name
    joined_query = (
        select(Execution, Agent.name.label("agent_name"))
        .outerjoin(Agent, Execution.agent_id == Agent.id)
        .where(Execution.tenant_id == user.tenant_id)
    )
    if agent_id:
        joined_query = joined_query.where(Execution.agent_id == agent_id)
    if status:
        joined_query = joined_query.where(Execution.status == ExecutionStatus(status))
    if search:
        joined_query = joined_query.where(Execution.input_message.ilike(f"%{search}%"))

    # Sort
    if sort == "oldest":
        joined_query = joined_query.order_by(Execution.created_at.asc())
    elif sort == "cost_high":
        joined_query = joined_query.order_by(Execution.cost.desc().nullslast())
    elif sort == "cost_low":
        joined_query = joined_query.order_by(Execution.cost.asc().nullsfirst())
    elif sort == "duration":
        joined_query = joined_query.order_by(Execution.duration_ms.desc().nullslast())
    else:  # newest (default)
        joined_query = joined_query.order_by(desc(Execution.created_at))

    joined_query = joined_query.offset(offset).limit(limit)

    result = await db.execute(joined_query)
    rows = result.all()

    data = []
    for row in rows:
        exec_obj = row[0]
        agent_name = row[1] if len(row) > 1 else None
        serialized = _serialize_execution(exec_obj)
        serialized["agent_name"] = agent_name
        data.append(serialized)

    return success(data, meta={"total": total, "completed": completed_count, "failed": failed_count, "limit": limit, "offset": offset})


@router.delete("/{execution_id}")
async def delete_execution(
    execution_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Delete an execution. Owner or admin only."""
    result = await db.execute(
        select(Execution).where(
            Execution.id == execution_id,
            Execution.tenant_id == user.tenant_id,
        )
    )
    execution = result.scalar_one_or_none()
    if not execution:
        return error("Execution not found", 404)

    # Only owner or admin can delete
    if execution.user_id != user.id and user.role.value != "admin":
        return error("Permission denied", 403)

    await db.delete(execution)
    await db.commit()
    return success({"deleted": True})


@router.get("/{execution_id}/replay")
async def get_execution_replay(
    execution_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get the full execution trace for step-through replay."""
    result = await db.execute(
        select(Execution).where(
            Execution.id == execution_id,
            Execution.tenant_id == user.tenant_id,
        )
    )
    execution = result.scalar_one_or_none()
    if not execution:
        return error("Execution not found", 404)

    trace = getattr(execution, "execution_trace", None) or {}
    return success({
        "execution": _serialize_execution(execution),
        "trace": trace,
        "steps": trace.get("steps", []),
        "total_steps": len(trace.get("steps", [])),
        "confidence_score": float(execution.confidence_score) if hasattr(execution, "confidence_score") and execution.confidence_score else None,
    })


@router.get("/{execution_id}/children")
async def get_child_executions(
    execution_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get all child executions spawned by a parent execution."""
    if not hasattr(Execution, "parent_execution_id"):
        return success([])

    result = await db.execute(
        select(Execution).where(
            Execution.parent_execution_id == execution_id,
            Execution.tenant_id == user.tenant_id,
        ).order_by(Execution.created_at)
    )
    children = result.scalars().all()
    return success([_serialize_execution(e) for e in children])


def _serialize_execution(e: Execution) -> dict:
    data = {
        "id": str(e.id),
        "agent_id": str(e.agent_id),
        "user_id": str(e.user_id),
        "input_message": e.input_message,
        "output_message": e.output_message,
        "status": e.status.value if hasattr(e.status, "value") else str(e.status),
        "input_tokens": e.input_tokens,
        "output_tokens": e.output_tokens,
        "cost": float(e.cost) if e.cost else None,
        "model_used": e.model_used,
        "duration_ms": e.duration_ms,
        "tool_calls": e.tool_calls,
        "node_results": e.node_results,
        "error_message": e.error_message,
        "failure_code": getattr(e, "failure_code", None),
        "execution_trace": e.execution_trace if hasattr(e, "execution_trace") else None,
        "started_at": e.started_at.isoformat() if e.started_at else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "completed_at": e.completed_at.isoformat() if e.completed_at else None,
    }
    # New fields from migration e5f6a7b8c9d0
    if hasattr(e, "confidence_score"):
        data["confidence_score"] = float(e.confidence_score) if e.confidence_score else None
    if hasattr(e, "parent_execution_id"):
        data["parent_execution_id"] = str(e.parent_execution_id) if e.parent_execution_id else None
    if hasattr(e, "retry_count"):
        data["retry_count"] = e.retry_count
    return data
