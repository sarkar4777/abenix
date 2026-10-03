"""Execution rows for agent runs the API drives in-process, such as a2a and batch."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.execution import Execution, ExecutionStatus


def open_run(
    *, agent: Any, user: Any, message: str, model: str, subject: tuple
) -> Execution:
    """A RUNNING row, the insert trigger stamps provenance, revision and prompt hash."""
    sid, stype = subject
    now = datetime.now(timezone.utc)
    return Execution(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        agent_id=agent.id,
        user_id=user.id,
        subject_id=sid,
        subject_type=stype,
        input_message=message,
        status=ExecutionStatus.RUNNING,
        model_requested=model,
        model_used=model,
        started_at=now,
    )


def _finish(execution: Execution) -> None:
    now = datetime.now(timezone.utc)
    execution.completed_at = execution.completed_at or now
    if execution.duration_ms is None and execution.started_at is not None:
        execution.duration_ms = int(
            (execution.completed_at - execution.started_at).total_seconds() * 1000
        )


def failure_code_for(result: Any) -> str | None:
    refusal = getattr(result, "governance_refusal", None)
    if refusal:
        return refusal.get("code") or "KILL_SWITCH"
    if getattr(result, "moderation_blocked", False):
        return "MODERATION_BLOCKED"
    if getattr(result, "budget_exceeded", False):
        return getattr(result, "failure_code", None) or "BUDGET_EXCEEDED"
    if getattr(result, "grounding_violation", False):
        return "GROUNDING_REQUIRED_VIOLATION"
    return None


def record_result(execution: Execution, result: Any, source: str) -> str | None:
    """Status, spend and outcome from an ExecutionResult. Returns the failure code, if any."""
    code = failure_code_for(result)
    execution.output_message = result.output
    execution.input_tokens = int(result.input_tokens or 0)
    execution.output_tokens = int(result.output_tokens or 0)
    execution.cost = float(result.cost or 0)
    for provider in ("anthropic", "openai", "google", "other"):
        setattr(
            execution,
            f"{provider}_cost",
            float(getattr(result, f"{provider}_cost", 0) or 0),
        )
    execution.duration_ms = int(result.duration_ms or 0)
    execution.tool_calls = result.tool_calls or None
    if getattr(result, "model", ""):
        execution.model_used = result.model
    if getattr(result, "fallback_reason", ""):
        execution.model_fallback_reason = result.fallback_reason
    if getattr(result, "risk_tier", ""):
        execution.risk_tier = result.risk_tier
    if getattr(result, "risk_reasons", None):
        execution.risk_reasons = result.risk_reasons
    traces = getattr(result, "node_traces", None) or []
    execution.execution_trace = {
        "source": source,
        "steps": [t.to_dict() for t in traces],
        "tool_calls": result.tool_calls,
    }
    if code:
        execution.status = ExecutionStatus.FAILED
        execution.failure_code = code
        refusal = getattr(result, "governance_refusal", None) or {}
        execution.error_message = (refusal.get("message") or result.output or code)[
            -2000:
        ]
    else:
        execution.status = ExecutionStatus.COMPLETED
    _finish(execution)
    return code


def record_error(execution: Execution, exc: BaseException) -> str:
    from app.core.failure_codes import classify_exception

    execution.status = ExecutionStatus.FAILED
    execution.error_message = str(exc)[:2000]
    execution.failure_code = classify_exception(exc)
    _finish(execution)
    return execution.failure_code


async def settle(db: Any, execution: Execution, api_key_id: Any = None) -> None:
    """Usage counters, outcome metric and drift hook once the row is terminal."""
    from app.core.failure_codes import emit_outcome_metric
    from app.core.usage import track_execution, update_user_usage
    from models.user import User

    if execution.cost is not None:
        tokens_in = execution.input_tokens or 0
        tokens_out = execution.output_tokens or 0
        cost = float(execution.cost or 0)
        await track_execution(
            db,
            tenant_id=execution.tenant_id,
            user_id=execution.user_id,
            agent_id=execution.agent_id,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost=cost,
        )
        owner = await db.get(User, execution.user_id)
        if owner is not None:
            await update_user_usage(
                db, owner, tokens_in, tokens_out, cost, api_key_id=api_key_id
            )
    await db.commit()
    try:
        emit_outcome_metric(
            outcome=(
                "SUCCESS" if execution.status == ExecutionStatus.COMPLETED else "FAILED"
            ),
            failure_code=execution.failure_code or "",
            agent_type="agent",
            tenant_id=str(execution.tenant_id),
        )
    except Exception:
        pass
    try:
        from app.services.execution_hooks import record_terminal

        await record_terminal(db, execution)
    except Exception:
        pass


async def prepare(
    db: Any, agent: Any, user: Any, execution: Execution, **registry_kwargs: Any
) -> dict[str, Any]:
    """The same tools, grants and moderation gate /execute gives a run."""
    from app.core.moderation_glue import build_gate_context
    from app.routers.agents import _fetch_mcp_connections
    from app.services.collection_access import resolve_agent_collections
    from engine.agent_executor import build_tool_registry

    mc = agent.model_config_ or {}
    tool_names = mc.get("tools", []) or []
    kb_ids = [
        str(c)
        for c in await resolve_agent_collections(
            db, agent_id=agent.id, tenant_id=user.tenant_id
        )
    ]
    system_prompt = str(agent.system_prompt or "")
    mcp_clients: list = []
    mcp_connections = await _fetch_mcp_connections(db, agent.id, user.tenant_id)
    if mcp_connections:
        from engine.tool_config_prompt import append_mcp_warnings
        from engine.tool_resolver import resolve_tools

        registry, mcp_clients, _ = await resolve_tools(
            tool_names, mcp_connections, kb_ids=kb_ids, **registry_kwargs
        )
        system_prompt = append_mcp_warnings(
            system_prompt, getattr(registry, "mcp_warnings", [])
        )
    else:
        registry = build_tool_registry(tool_names, kb_ids=kb_ids, **registry_kwargs)
    gate = await build_gate_context(db, execution.tenant_id, execution.user_id)
    return {
        "registry": registry,
        "system_prompt": system_prompt,
        "mcp_clients": mcp_clients,
        "moderation": gate,
        "kb_ids": kb_ids,
    }


async def after(db: Any, execution: Execution, parts: dict[str, Any]) -> None:
    """Persist what the moderation gate caught and close MCP connections."""
    from app.core.moderation_glue import persist_events

    gate = parts.get("moderation")
    try:
        if gate is not None and gate.gate is not None:
            await persist_events(db, execution.tenant_id, execution.user_id, gate)
    except Exception:  # noqa: BLE001
        pass
    for client in parts.get("mcp_clients") or []:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass
