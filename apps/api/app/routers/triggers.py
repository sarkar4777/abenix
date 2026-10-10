"""Agent Triggers — event-based (webhook) and scheduled (cron) execution."""

from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus, AgentType
from models.agent_trigger import AgentTrigger
from models.user import User

router = APIRouter(prefix="/api/triggers", tags=["triggers"])

_BACKGROUND_TASKS: set = set()


def _next_cron_run(cron_expr: str) -> datetime | None:
    """Calculate next run time from a cron expression using croniter."""
    from app.core.scheduler import next_cron_run

    return next_cron_run(cron_expr)


@router.post("")
async def create_trigger(
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Create a webhook or schedule trigger for an agent."""
    agent_id = body.get("agent_id")
    trigger_type = body.get("trigger_type", "webhook")
    name = body.get("name") or ""
    if not isinstance(name, str) or len(name.strip()) > 255:
        return error("name must be text of at most 255 characters", 400)
    name = name.strip()
    # Validate default_context is dict if provided
    if body.get("default_context") is not None and not isinstance(
        body.get("default_context"), dict
    ):
        return error("default_context must be a JSON object", 400)

    if not agent_id:
        return error("agent_id is required", 400)
    if trigger_type not in ("webhook", "schedule"):
        return error("trigger_type must be 'webhook' or 'schedule'", 400)

    # Verify agent exists and user has access
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)
    from app.services.agent_share import resolve_agent_access
    from models.resource_share import SharePermission

    if not await resolve_agent_access(
        db, user, agent, permission_required=SharePermission.EXECUTE
    ):
        return error("You can only add triggers to agents you can run", 403)

    trigger = AgentTrigger(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        agent_id=uuid.UUID(agent_id),
        created_by=user.id,
        trigger_type=trigger_type,
        name=name or f"{agent.name} trigger",
        default_message=body.get(
            "default_message", f"Triggered execution of {agent.name}"
        ),
        default_context=body.get("default_context"),
        is_active=True,
    )

    if trigger_type == "webhook":
        trigger.webhook_token = secrets.token_urlsafe(32)
    elif trigger_type == "schedule":
        cron_expr = body.get("cron_expression", "0 * * * *")  # Default: hourly
        from app.core.scheduler import is_valid_cron

        if not is_valid_cron(cron_expr):
            return error(f"Invalid cron expression: {cron_expr}", 400)
        trigger.cron_expression = cron_expr
        trigger.next_run_at = _next_cron_run(cron_expr)

    db.add(trigger)
    await db.commit()
    await db.refresh(trigger)

    result_data: dict[str, Any] = {
        "id": str(trigger.id),
        "agent_id": str(trigger.agent_id),
        "agent_name": agent.name,
        "trigger_type": trigger.trigger_type,
        "name": trigger.name,
        "is_active": trigger.is_active,
        "default_message": trigger.default_message,
        "default_context": trigger.default_context,
    }

    if trigger_type == "webhook":
        result_data["webhook_url"] = f"/api/triggers/webhook/{trigger.webhook_token}"
        result_data["webhook_token"] = trigger.webhook_token
    elif trigger_type == "schedule":
        result_data["cron_expression"] = trigger.cron_expression
        result_data["next_run_at"] = (
            trigger.next_run_at.isoformat() if trigger.next_run_at else None
        )

    return success(result_data, status_code=201)


@router.get("")
async def list_triggers(
    search: str = Query("", max_length=255, description="Search by trigger name"),
    trigger_type: str = Query("", description="Filter: webhook, schedule"),
    sort: str = Query("newest", description="Sort: newest, oldest, name"),
    agent_id: str = Query("", description="Only triggers for this agent"),
    trigger_id: str = Query("", description="Only this trigger, for links from a run"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Triggers the caller manages: their own and those on their agents, all for an admin.

    Webhook URLs carry the secret that fires the agent, so they are never
    listed to other members.
    """
    from app.core.permissions import is_admin

    query = (
        select(AgentTrigger, Agent.name)
        .join(Agent, AgentTrigger.agent_id == Agent.id)
        .where(AgentTrigger.tenant_id == user.tenant_id)
    )
    if not is_admin(user):
        query = query.where(
            or_(AgentTrigger.created_by == user.id, Agent.creator_id == user.id)
        )
    if agent_id:
        try:
            query = query.where(AgentTrigger.agent_id == uuid.UUID(agent_id))
        except ValueError:
            return error("agent_id is not a valid id", 400)
    if trigger_id:
        try:
            query = query.where(AgentTrigger.id == uuid.UUID(trigger_id))
        except ValueError:
            return error("trigger_id is not a valid id", 400)

    if search:
        # rows show the agent name, so match on it too
        query = query.where(
            or_(
                AgentTrigger.name.ilike(f"%{search}%"),
                Agent.name.ilike(f"%{search}%"),
            )
        )
    if trigger_type:
        query = query.where(AgentTrigger.trigger_type == trigger_type)

    # count the same rows the page lists
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0

    # Sort
    if sort == "oldest":
        query = query.order_by(AgentTrigger.created_at.asc())
    elif sort == "name":
        query = query.order_by(AgentTrigger.name.asc())
    else:  # newest (default)
        query = query.order_by(AgentTrigger.created_at.desc(), AgentTrigger.id)

    # Apply pagination
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.all()
    recent = await recent_runs(db, user.tenant_id, [t.id for t, _ in rows])
    data = [
        {
            "id": str(t.id),
            "agent_id": str(t.agent_id),
            "agent_name": agent_name,
            "trigger_type": t.trigger_type,
            "name": t.name,
            "is_active": t.is_active,
            "webhook_url": (
                f"/api/triggers/webhook/{t.webhook_token}" if t.webhook_token else None
            ),
            "webhook_token": t.webhook_token,
            "cron_expression": t.cron_expression,
            "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None,
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
            "run_count": t.run_count,
            "last_status": t.last_status,
            "recent_runs": recent.get(t.id, []),
        }
        for t, agent_name in rows
    ]
    return success(data, meta={"total": total, "limit": limit, "offset": offset})


RECENT_RUNS = 5


def _run_row(e: Any) -> dict[str, Any]:
    status = e.status.value if hasattr(e.status, "value") else str(e.status)
    return {
        "id": str(e.id),
        "status": status.lower(),
        "trigger_kind": e.trigger_kind,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "duration_ms": e.duration_ms,
        "failure_code": e.failure_code,
    }


async def recent_runs(
    db: AsyncSession, tenant_id: Any, trigger_ids: list[Any], n: int = RECENT_RUNS
) -> dict[Any, list[dict[str, Any]]]:
    """The newest n runs of each trigger, in one query."""
    from models.execution import Execution

    if not trigger_ids:
        return {}
    rank = (
        func.row_number()
        .over(partition_by=Execution.trigger_id, order_by=Execution.created_at.desc())
        .label("rank")
    )
    inner = (
        select(Execution.id, rank)
        .where(
            Execution.tenant_id == tenant_id,
            Execution.trigger_id.in_(trigger_ids),
        )
        .subquery()
    )
    rows = (
        (
            await db.execute(
                select(Execution)
                .join(inner, inner.c.id == Execution.id)
                .where(inner.c.rank <= n)
                .order_by(Execution.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    out: dict[Any, list[dict[str, Any]]] = {}
    for e in rows:
        out.setdefault(e.trigger_id, []).append(_run_row(e))
    return out


@router.get("/{trigger_id}/runs")
async def list_trigger_runs(
    trigger_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Runs this trigger started, newest first."""
    from models.execution import Execution

    trigger = (
        await db.execute(
            select(AgentTrigger).where(
                AgentTrigger.id == trigger_id,
                AgentTrigger.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not trigger or not await _can_manage(db, user, trigger):
        return error("Trigger not found", 404)
    where = [Execution.tenant_id == user.tenant_id, Execution.trigger_id == trigger.id]
    total = await db.scalar(select(func.count(Execution.id)).where(*where)) or 0
    rows = (
        (
            await db.execute(
                select(Execution)
                .where(*where)
                .order_by(Execution.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return success(
        [_run_row(e) for e in rows],
        meta={"total": total, "trigger_name": trigger.name},
    )


async def _can_manage(db: AsyncSession, user: User, trigger: AgentTrigger) -> bool:
    """Trigger creator, the agent's owner, or an admin."""
    from app.core.permissions import is_admin

    if is_admin(user) or trigger.created_by == user.id:
        return True
    owner = (
        await db.execute(select(Agent.creator_id).where(Agent.id == trigger.agent_id))
    ).scalar_one_or_none()
    return owner == user.id


@router.delete("/{trigger_id}")
async def delete_trigger(
    trigger_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(AgentTrigger).where(
            AgentTrigger.id == trigger_id,
            AgentTrigger.tenant_id == user.tenant_id,
        )
    )
    trigger = result.scalar_one_or_none()
    if not trigger or not await _can_manage(db, user, trigger):
        return error("Trigger not found", 404)
    await db.delete(trigger)
    await db.commit()
    return success({"deleted": True})


@router.put("/{trigger_id}")
async def update_trigger(
    trigger_id: uuid.UUID,
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(AgentTrigger).where(
            AgentTrigger.id == trigger_id,
            AgentTrigger.tenant_id == user.tenant_id,
        )
    )
    trigger = result.scalar_one_or_none()
    if not trigger or not await _can_manage(db, user, trigger):
        return error("Trigger not found", 404)

    if "is_active" in body:
        trigger.is_active = body["is_active"]
    if "name" in body:
        trigger.name = body["name"]
    if "default_message" in body:
        trigger.default_message = body["default_message"]
    if "default_context" in body:
        trigger.default_context = body["default_context"]
    if "cron_expression" in body and trigger.trigger_type == "schedule":
        trigger.cron_expression = body["cron_expression"]
        trigger.next_run_at = _next_cron_run(body["cron_expression"])

    await db.commit()
    return success({"updated": True})


# Reasons stored in agent_triggers.last_status (20 chars max) when a
# trigger is auto-deactivated. The UI lists them next to the trigger.
DEACTIVATION_REASONS = {
    "agent_deleted": "the agent was deleted",
    "agent_inactive": "the agent is no longer active",
    "owner_missing": "the trigger owner no longer exists",
    "owner_inactive": "the trigger owner is deactivated",
    "access_revoked": "the trigger owner lost execute access to the agent",
}


async def trigger_stopped(trigger: AgentTrigger) -> str | None:
    """The kill switch message when this trigger, or the agent it runs, is stopped."""
    from engine import governance

    await governance.ensure_fresh()
    try:
        governance.check(trigger.tenant_id, "trigger", str(trigger.id))
        governance.check(trigger.tenant_id, "agent", str(trigger.agent_id))
        governance.check(trigger.tenant_id, "pipeline", str(trigger.agent_id))
    except governance.Stopped as s:
        return s.message()
    return None


async def check_trigger_eligibility(
    db: AsyncSession,
    trigger: AgentTrigger,
    agent: Agent | None,
    owner: Any,
) -> str | None:
    """Return a DEACTIVATION_REASONS key when the trigger must not fire."""
    from app.core.permissions import accessible_resource_ids, is_admin
    from models.resource_share import SharePermission

    if agent is None or agent.status == AgentStatus.ARCHIVED:
        return "agent_deleted"
    if agent.status != AgentStatus.ACTIVE:
        return "agent_inactive"
    if owner is None:
        return "owner_missing"
    if not getattr(owner, "is_active", True):
        return "owner_inactive"
    if agent.agent_type == AgentType.OOB:
        return None
    if agent.tenant_id != owner.tenant_id:
        return "access_revoked"
    if is_admin(owner) or agent.creator_id == owner.id:
        return None
    shared = await accessible_resource_ids(
        db, owner, kind="agent", minimum_permission=SharePermission.EXECUTE
    )
    if agent.id in shared:
        return None
    return "access_revoked"


async def deactivate_trigger(
    db: AsyncSession,
    trigger: AgentTrigger,
    reason: str,
    *,
    owner: Any = None,
) -> None:
    """Switch the trigger off, record why, tell the owner."""
    trigger.is_active = False
    trigger.last_status = reason[:20]
    await db.commit()
    notify_user_id = owner.id if owner is not None else trigger.created_by
    if not notify_user_id:
        return
    try:
        from app.core.notifications import create_notification
        from models.notification import NotificationType

        await create_notification(
            db,
            tenant_id=trigger.tenant_id,
            user_id=notify_user_id,
            type=NotificationType.SYSTEM_ALERT.value,
            title="Trigger deactivated",
            message=(
                f"Trigger '{trigger.name}' was switched off because "
                f"{DEACTIVATION_REASONS.get(reason, reason)}."
            ),
            link="/triggers",
            metadata={
                "trigger_id": str(trigger.id),
                "agent_id": str(trigger.agent_id),
                "reason": reason,
            },
        )
        await db.commit()
    except Exception as exc:
        import logging

        logging.getLogger("abenix.triggers").warning(
            "trigger %s deactivation notice failed: %s", trigger.id, exc
        )


def _model_for(agent: Agent) -> str:
    cfg = agent.model_config_ or {}
    if cfg.get("mode") == "pipeline":
        return "pipeline"
    return cfg.get("model", "claude-sonnet-4-5-20250929")


async def dispatch_execution(
    db: AsyncSession,
    *,
    agent: Agent,
    user: Any,
    message: str,
    context: dict[str, Any],
    trigger_id: str | None = None,
    parent_execution_id: uuid.UUID | None = None,
    execution: Any = None,
    trigger_kind: str | None = None,
    trigger_name: str | None = None,
) -> tuple[Any, bool]:
    """Create (or take) a RUNNING execution and hand it to the runtime.

    Mirrors POST /api/agents/{id}/execute: when scaling.execRemote is on the
    job goes to the agent's pool on the queue backend, otherwise it runs in
    this process. Returns (execution, dispatched). On a queue failure the
    execution is marked FAILED so nothing is left RUNNING.
    """
    from app.core import run_origin
    from app.core.config import settings
    from models.execution import Execution, ExecutionStatus

    model_cfg = agent.model_config_ or {}
    is_pipeline = model_cfg.get("mode") == "pipeline"
    pool = getattr(agent, "runtime_pool", None) or "default"

    if execution is None:
        execution = Execution(
            tenant_id=user.tenant_id,
            agent_id=agent.id,
            user_id=user.id,
            input_message=message,
            status=ExecutionStatus.RUNNING,
            model_used=_model_for(agent),
            model_requested=_model_for(agent),
            started_at=datetime.now(timezone.utc),
            parent_execution_id=parent_execution_id,
        )
        run_origin.stamp(
            execution, trigger_kind, trigger_id=trigger_id, name=trigger_name
        )
        db.add(execution)
        await db.commit()
        await db.refresh(execution)
    elif trigger_kind:
        run_origin.stamp(
            execution, trigger_kind, trigger_id=trigger_id, name=trigger_name
        )

    from engine.agent_budget import BUDGET_EXCEEDED, check_agent_budget

    breach = await check_agent_budget(
        db,
        agent_id=agent.id,
        tenant_id=execution.tenant_id,
        agent_name=getattr(agent, "name", ""),
        daily_cost_limit=getattr(agent, "daily_cost_limit", None),
        daily_budget_usd=getattr(agent, "daily_budget_usd", None),
    )
    if breach:
        execution.status = ExecutionStatus.FAILED
        execution.error_message = breach.message
        execution.failure_code = BUDGET_EXCEEDED
        execution.completed_at = datetime.now(timezone.utc)
        await db.commit()
        if trigger_id:
            try:
                await _notify_trigger_failure(
                    db,
                    tenant_id=execution.tenant_id,
                    user_id=user.id,
                    trigger_id=trigger_id,
                    execution_id=str(execution.id),
                    error=breach.message,
                )
                await db.commit()
            except Exception:
                pass
        return execution, False

    from engine.risk import (
        DRAFT_NOT_RELEASED,
        draft_needs_release,
        draft_release_message,
    )

    if draft_needs_release(getattr(agent, "status", None), model_cfg.get("risk_tier")):
        msg = draft_release_message(agent.name, model_cfg.get("risk_tier"))
        execution.status = ExecutionStatus.FAILED
        execution.error_message = msg
        execution.failure_code = DRAFT_NOT_RELEASED
        execution.completed_at = datetime.now(timezone.utc)
        await db.commit()
        if trigger_id:
            try:
                await _notify_trigger_failure(
                    db,
                    tenant_id=execution.tenant_id,
                    user_id=user.id,
                    trigger_id=trigger_id,
                    execution_id=str(execution.id),
                    error=msg,
                )
                await db.commit()
            except Exception:
                pass
        return execution, False

    if settings.scaling_exec_remote and pool != "inline":
        try:
            runtime_path = Path(__file__).resolve().parents[3] / "agent-runtime"
            if str(runtime_path) not in sys.path and runtime_path.exists():
                sys.path.insert(0, str(runtime_path))
            from engine.queue_backend import get_queue_backend  # type: ignore

            await get_queue_backend().submit(
                pool,
                {
                    "execution_id": str(execution.id),
                    "agent_id": str(agent.id),
                    "tenant_id": str(execution.tenant_id),
                    "user_id": str(user.id),
                    "api_key_id": None,
                    "message": message,
                    "context": context or {},
                    "is_pipeline": is_pipeline,
                    "trigger_id": trigger_id,
                },
            )
            return execution, True
        except Exception as exc:
            from app.core.failure_codes import classify_exception

            execution.status = ExecutionStatus.FAILED
            execution.error_message = f"queue submit failed: {exc}"[:2000]
            execution.failure_code = classify_exception(exc)
            execution.completed_at = datetime.now(timezone.utc)
            await db.commit()
            if trigger_id:
                try:
                    await _notify_trigger_failure(
                        db,
                        tenant_id=execution.tenant_id,
                        user_id=user.id,
                        trigger_id=trigger_id,
                        execution_id=str(execution.id),
                        error=str(exc),
                    )
                    await db.commit()
                except Exception:
                    pass
            return execution, False

    _t = asyncio.create_task(
        _execute_triggered_agent(
            execution_id=str(execution.id),
            agent=agent,
            user=user,
            message=message,
            context=context or {},
            trigger_id=trigger_id,
            db_url=str(_get_db_url()),
        )
    )
    _BACKGROUND_TASKS.add(_t)
    _t.add_done_callback(_BACKGROUND_TASKS.discard)
    return execution, True


def _not_dispatched_error(execution: Any) -> Any:
    if getattr(execution, "failure_code", None) == "BUDGET_EXCEEDED":
        return error(
            execution.error_message,
            429,
            error_code="BUDGET_EXCEEDED",
            details={"execution_id": str(execution.id)},
        )
    if getattr(execution, "failure_code", None) == "DRAFT_NOT_RELEASED":
        return error(
            execution.error_message,
            409,
            error_code="DRAFT_NOT_RELEASED",
            details={"execution_id": str(execution.id)},
        )
    return error("Trigger execution could not be queued", 503)


async def _notify_trigger_failure(
    db: AsyncSession,
    *,
    tenant_id: Any,
    user_id: Any,
    trigger_id: str,
    execution_id: str,
    error: str,
) -> None:
    """Route trigger failures through create_notification (WS + Slack + email)."""
    from app.core.notifications import create_notification
    from models.notification import NotificationType

    await create_notification(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        type=NotificationType.EXECUTION_FAILED.value,
        title="Scheduled trigger failed",
        message=f"Trigger {trigger_id[:8]} failed: {error[:400]}",
        link=f"/executions/{execution_id}",
        metadata={
            "execution_id": execution_id,
            "trigger_id": trigger_id,
            "reason": "trigger_exception",
        },
    )


def trigger_outcome_status(status: Any) -> str:
    return "completed" if str(status or "").lower() == "completed" else "failed"


async def write_trigger_outcome(
    session_factory: Any,
    execution_id: str,
    status: str,
    error: str | None,
    *,
    trigger_id: str | None = None,
) -> bool:
    """Stamp last_status / last_run_at on the trigger that fired this execution.

    The id comes from the queue payload, or from executions.trigger_id when the
    message had none. A failed outcome also notifies the owner, which is where
    the error text lands since agent_triggers has no last_error column.
    """
    if not trigger_id:
        return False

    from sqlalchemy import update

    try:
        tid = uuid.UUID(str(trigger_id))
    except ValueError:
        return False
    outcome = trigger_outcome_status(status)
    async with session_factory() as db:
        r = await db.execute(
            update(AgentTrigger)
            .where(AgentTrigger.id == tid)
            .values(last_status=outcome, last_run_at=datetime.now(timezone.utc))
        )
        await db.commit()
        updated = (getattr(r, "rowcount", 0) or 0) > 0
        if not updated or outcome != "failed":
            return updated
        await notify_trigger_failure_once(db, tid, execution_id, error)
    return updated


async def notify_trigger_failure_once(
    db: AsyncSession, trigger_id: Any, execution_id: Any, error: str | None
) -> bool:
    """Tell the trigger's owner it failed, once per run whichever process finished it."""
    import logging

    from app.services.run_announcer import claim

    try:
        row = (
            await db.execute(
                select(AgentTrigger.created_by, AgentTrigger.tenant_id).where(
                    AgentTrigger.id == uuid.UUID(str(trigger_id))
                )
            )
        ).first()
        if not row or not row[0]:
            return False
        if not await claim(f"trigger-failed:{execution_id}"):
            return False
        await _notify_trigger_failure(
            db,
            tenant_id=row[1],
            user_id=row[0],
            trigger_id=str(trigger_id),
            execution_id=str(execution_id),
            error=str(error or "execution failed"),
        )
        await db.commit()
        return True
    except Exception as exc:
        logging.getLogger("abenix.triggers").warning(
            "trigger %s failure notice skipped: %s", trigger_id, exc
        )
        return False


@router.post("/webhook/{token}")
async def receive_webhook(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Receive an event from an external system and trigger agent execution."""
    result = await db.execute(
        select(AgentTrigger).where(
            AgentTrigger.webhook_token == token,
            AgentTrigger.is_active.is_(True),
        )
    )
    trigger = result.scalar_one_or_none()
    if not trigger:
        return error("Invalid or inactive webhook token", 404)
    stopped = await trigger_stopped(trigger)
    if stopped:
        # 423 tells the sender to retry later, the trigger itself is untouched
        return error(stopped, 423)

    # Parse incoming payload
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    message = payload.get(
        "message", trigger.default_message or "Webhook triggered execution"
    )
    default_ctx = (
        trigger.default_context if isinstance(trigger.default_context, dict) else {}
    )
    payload_ctx = (
        payload.get("context", {}) if isinstance(payload.get("context"), dict) else {}
    )
    context = {**default_ctx, **payload_ctx}

    agent_result = await db.execute(select(Agent).where(Agent.id == trigger.agent_id))
    agent = agent_result.scalar_one_or_none()

    from models.user import User as UserModel

    user_result = await db.execute(
        select(UserModel).where(UserModel.id == trigger.created_by)
    )
    trigger_user = user_result.scalar_one_or_none()

    reason = await check_trigger_eligibility(db, trigger, agent, trigger_user)
    if reason:
        await deactivate_trigger(db, trigger, reason, owner=trigger_user)
        return error(f"Trigger deactivated: {DEACTIVATION_REASONS[reason]}", 400)

    trigger.run_count = (trigger.run_count or 0) + 1
    trigger.last_run_at = datetime.now(timezone.utc)
    await db.commit()

    execution, dispatched = await dispatch_execution(
        db,
        agent=agent,
        user=trigger_user,
        message=message,
        context=context,
        trigger_id=str(trigger.id),
        trigger_kind="webhook",
        trigger_name=trigger.name,
    )
    if not dispatched:
        trigger.last_status = "failed"
        await db.commit()
        return _not_dispatched_error(execution)

    return success(
        {
            "execution_id": str(execution.id),
            "agent_id": str(trigger.agent_id),
            "agent_name": agent.name,
            "status": "running",
            "message": message,
            "trigger_id": str(trigger.id),
        },
        status_code=202,
    )


def _get_db_url() -> str:
    from app.core.config import settings

    return str(settings.database_url).replace("+asyncpg", "")


async def _execute_triggered_agent(
    execution_id: str,
    agent: Agent,
    user: Any,
    message: str,
    context: dict[str, Any],
    trigger_id: str | None,
    db_url: str,
) -> None:
    """Background task: execute the agent and update results."""
    try:
        from engine.llm_router import LLMRouter
        from engine.agent_executor import AgentExecutor, build_tool_registry

        model_cfg = agent.model_config_ or {}
        tool_names = model_cfg.get("tools", [])

        # Inject context into message (same as regular execution)
        if context:
            context_lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
            message = f"{message}\n\n[Input Parameters]\n{context_lines}"

        registry = build_tool_registry(
            tool_names,
            agent_id=str(agent.id),
            tenant_id=str(user.tenant_id),
            execution_id=execution_id,
            agent_name=agent.name,
            db_url=db_url,
        )

        executor = AgentExecutor(
            llm_router=LLMRouter(),
            tool_registry=registry,
            system_prompt=str(agent.system_prompt or ""),
            model=model_cfg.get("model", "claude-sonnet-4-5-20250929"),
            temperature=model_cfg.get("temperature", 0.3),
            agent_id=str(agent.id),
            cost_limit=getattr(agent, "per_execution_cost_limit", None),
        )

        result = await executor.invoke(message)
        _over = bool(getattr(result, "budget_exceeded", False))

        # Update execution in database
        import asyncpg

        conn = await asyncpg.connect(
            f"postgresql://{db_url.split('://', 1)[1]}" if "://" in db_url else db_url
        )
        try:
            await conn.execute(
                "UPDATE executions SET status = $7, output_message = $1, "
                "input_tokens = $2, output_tokens = $3, cost = $4, duration_ms = $5, "
                "failure_code = $8, error_message = $9, "
                "completed_at = now() WHERE id = $6::uuid",
                result.output[:10000],
                result.input_tokens,
                result.output_tokens,
                float(result.cost),
                result.duration_ms,
                execution_id,
                "FAILED" if _over else "COMPLETED",
                result.failure_code if _over else None,
                result.output[-1000:] if _over else None,
            )
            if trigger_id:
                await conn.execute(
                    "UPDATE agent_triggers SET last_status = $2 WHERE id = $1::uuid",
                    trigger_id,
                    "failed" if _over else "completed",
                )
        finally:
            await conn.close()

    except Exception as e:
        row = None
        try:
            import asyncpg

            conn = await asyncpg.connect(
                f"postgresql://{db_url.split('://', 1)[1]}"
                if "://" in db_url
                else db_url
            )
            await conn.execute(
                "UPDATE executions SET status = 'FAILED', error_message = $1, completed_at = now() WHERE id = $2::uuid",
                str(e)[:1000],
                execution_id,
            )
            if trigger_id:
                await conn.execute(
                    "UPDATE agent_triggers SET last_status = 'failed' WHERE id = $1::uuid",
                    trigger_id,
                )
                row = await conn.fetchrow(
                    "SELECT created_by, tenant_id FROM agent_triggers WHERE id = $1::uuid",
                    trigger_id,
                )
            await conn.close()
        except Exception:
            row = None
        # Notification goes through create_notification so Slack and email
        # fire alongside the in-app bell.
        try:
            if trigger_id and row and row["created_by"]:
                from app.core.deps import fresh_session

                async with fresh_session() as ndb:
                    await _notify_trigger_failure(
                        ndb,
                        tenant_id=row["tenant_id"],
                        user_id=row["created_by"],
                        trigger_id=trigger_id,
                        execution_id=execution_id,
                        error=str(e),
                    )
                    await ndb.commit()
        except Exception:
            pass


@router.post("/{trigger_id}/run")
async def run_trigger_now(
    trigger_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Fire a trigger once, through the same path the scheduler uses."""

    result = await db.execute(
        select(AgentTrigger).where(
            AgentTrigger.id == trigger_id,
            AgentTrigger.tenant_id == user.tenant_id,
        )
    )
    trigger = result.scalar_one_or_none()
    if not trigger:
        return error("Trigger not found", 404)
    if not await _can_manage(db, user, trigger):
        return error(
            "Only the trigger owner, the agent owner or an admin can run it", 403
        )
    stopped = await trigger_stopped(trigger)
    if stopped:
        return error(stopped, 423)

    agent = (
        await db.execute(select(Agent).where(Agent.id == trigger.agent_id))
    ).scalar_one_or_none()
    owner = (
        await db.execute(select(User).where(User.id == trigger.created_by))
    ).scalar_one_or_none()

    reason = await check_trigger_eligibility(db, trigger, agent, owner)
    if reason:
        await deactivate_trigger(db, trigger, reason, owner=owner)
        return error(f"Trigger deactivated: {DEACTIVATION_REASONS[reason]}", 400)

    trigger.run_count = (trigger.run_count or 0) + 1
    trigger.last_run_at = datetime.now(timezone.utc)
    await db.commit()

    # runs as the owner, like a scheduled fire, so grants and quotas match
    execution, dispatched = await dispatch_execution(
        db,
        agent=agent,
        user=owner,
        message=trigger.default_message or "Manual trigger run",
        context=(
            trigger.default_context if isinstance(trigger.default_context, dict) else {}
        ),
        trigger_id=str(trigger.id),
        trigger_kind="manual",
        trigger_name=trigger.name,
    )
    if not dispatched:
        trigger.last_status = "failed"
        await db.commit()
        return _not_dispatched_error(execution)

    return success(
        {
            "execution_id": str(execution.id),
            "trigger_id": str(trigger.id),
            "agent_id": str(trigger.agent_id),
            "agent_name": agent.name,
            "status": "running",
        },
        status_code=202,
    )
