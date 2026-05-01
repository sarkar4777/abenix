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
    name = body.get("name", "")
    # Validate default_context is dict if provided
    if body.get("default_context") is not None and not isinstance(body.get("default_context"), dict):
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

    trigger = AgentTrigger(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        agent_id=uuid.UUID(agent_id),
        created_by=user.id,
        trigger_type=trigger_type,
        name=name or f"{agent.name} trigger",
        default_message=body.get("default_message", f"Triggered execution of {agent.name}"),
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
        result_data["next_run_at"] = trigger.next_run_at.isoformat() if trigger.next_run_at else None

    return success(result_data, status_code=201)


@router.get("")
async def list_triggers(
    search: str = Query("", max_length=255, description="Search by trigger name"),
    trigger_type: str = Query("", description="Filter: webhook, schedule"),
    sort: str = Query("newest", description="Sort: newest, oldest, name"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all triggers for the current tenant."""
    query = (
        select(AgentTrigger, Agent.name)
        .join(Agent, AgentTrigger.agent_id == Agent.id)
        .where(AgentTrigger.tenant_id == user.tenant_id)
    )

    if search:
        query = query.where(AgentTrigger.name.ilike(f"%{search}%"))
    if trigger_type:
        query = query.where(AgentTrigger.trigger_type == trigger_type)

    # Sort
    if sort == "oldest":
        query = query.order_by(AgentTrigger.created_at.asc())
    elif sort == "name":
        query = query.order_by(AgentTrigger.name.asc())
    else:  # newest (default)
        query = query.order_by(AgentTrigger.created_at.desc())

    # Count total before pagination
    count_base = select(AgentTrigger).where(AgentTrigger.tenant_id == user.tenant_id)
    if search:
        count_base = count_base.where(AgentTrigger.name.ilike(f"%{search}%"))
    if trigger_type:
        count_base = count_base.where(AgentTrigger.trigger_type == trigger_type)
    count_query = select(func.count()).select_from(count_base.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.all()
    data = [
        {
            "id": str(t.id),
            "agent_id": str(t.agent_id),
            "agent_name": agent_name,
            "trigger_type": t.trigger_type,
            "name": t.name,
            "is_active": t.is_active,
            "webhook_url": f"/api/triggers/webhook/{t.webhook_token}" if t.webhook_token else None,
            "webhook_token": t.webhook_token,
            "cron_expression": t.cron_expression,
            "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None,
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
            "run_count": t.run_count,
            "last_status": t.last_status,
        }
        for t, agent_name in rows
    ]
    return success(data, meta={"total": total, "limit": limit, "offset": offset})


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
    if not trigger:
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
    if not trigger:
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

    # Parse incoming payload
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    message = payload.get("message", trigger.default_message or "Webhook triggered execution")
    default_ctx = trigger.default_context if isinstance(trigger.default_context, dict) else {}
    payload_ctx = payload.get("context", {}) if isinstance(payload.get("context"), dict) else {}
    context = {**default_ctx, **payload_ctx}

    # Get the agent
    agent_result = await db.execute(select(Agent).where(Agent.id == trigger.agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent or agent.status != AgentStatus.ACTIVE:
        return error("Agent not available", 400)

    # Get the user who created the trigger (for execution context)
    from models.user import User as UserModel
    user_result = await db.execute(select(UserModel).where(UserModel.id == trigger.created_by))
    trigger_user = user_result.scalar_one_or_none()
    if not trigger_user:
        return error("Trigger owner not found", 400)

    # Create execution (non-streaming, returns immediately with execution_id)
    from models.execution import Execution, ExecutionStatus
    execution = Execution(
        tenant_id=trigger.tenant_id,
        agent_id=trigger.agent_id,
        user_id=trigger.created_by,
        input_message=message,
        status=ExecutionStatus.RUNNING,
        model_used=agent.model_config_.get("model", "claude-sonnet-4-5-20250929") if agent.model_config_ else "claude-sonnet-4-5-20250929",
    )
    db.add(execution)

    # Update trigger stats
    trigger.run_count = (trigger.run_count or 0) + 1
    trigger.last_run_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(execution)

    # Launch execution in background
    asyncio.create_task(
        _execute_triggered_agent(
            execution_id=str(execution.id),
            agent=agent,
            user=trigger_user,
            message=message,
            context=context,
            trigger_id=str(trigger.id),
            db_url=str(_get_db_url()),
        )
    )

    return success({
        "execution_id": str(execution.id),
        "agent_id": str(trigger.agent_id),
        "agent_name": agent.name,
        "status": "running",
        "message": message,
        "trigger_id": str(trigger.id),
    }, status_code=202)


def _get_db_url() -> str:
    from app.core.config import settings
    return str(settings.database_url).replace("+asyncpg", "")


async def _execute_triggered_agent(
    execution_id: str,
    agent: Agent,
    user: Any,
    message: str,
    context: dict[str, Any],
    trigger_id: str,
    db_url: str,
) -> None:
    """Background task: execute the agent and update results."""
    try:
        from engine.llm_router import LLMRouter
        from engine.agent_executor import AgentExecutor, build_tool_registry
        from app.core.config import settings

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
        )

        result = await executor.invoke(message)

        # Update execution in database
        import asyncpg
        conn = await asyncpg.connect(f"postgresql://{db_url.split('://', 1)[1]}" if "://" in db_url else db_url)
        try:
            await conn.execute(
                "UPDATE executions SET status = 'COMPLETED', output_message = $1, "
                "input_tokens = $2, output_tokens = $3, cost = $4, duration_ms = $5, "
                "completed_at = now() WHERE id = $6::uuid",
                result.output[:10000], result.input_tokens, result.output_tokens,
                float(result.cost), result.duration_ms, execution_id,
            )
            # Update trigger status
            await conn.execute(
                "UPDATE agent_triggers SET last_status = 'completed' WHERE id = $1::uuid",
                trigger_id,
            )
        finally:
            await conn.close()

    except Exception as e:
        # Mark execution as failed + fire an in-app notification so the
        # owner of the trigger hears about the failure instead of having
        # to poll the dashboard. Without this, a broken scheduled trigger
        # would silently keep accumulating failures forever.
        try:
            import asyncpg
            conn = await asyncpg.connect(f"postgresql://{db_url.split('://', 1)[1]}" if "://" in db_url else db_url)
            await conn.execute(
                "UPDATE executions SET status = 'FAILED', error_message = $1, completed_at = now() WHERE id = $2::uuid",
                str(e)[:1000], execution_id,
            )
            await conn.execute(
                "UPDATE agent_triggers SET last_status = 'failed' WHERE id = $1::uuid",
                trigger_id,
            )
            # Pull user_id + tenant from the trigger so we know whom to notify.
            row = await conn.fetchrow(
                "SELECT created_by, tenant_id FROM agent_triggers WHERE id = $1::uuid",
                trigger_id,
            )
            await conn.close()
        except Exception:
            row = None
        # Notification wiring lives outside the raw SQL block — any issue
        # here must not mask the real error we already logged.
        try:
            if row and row["created_by"]:
                from models.notification import Notification, NotificationType
                from app.core.deps import async_session
                from app.core.ws_manager import ws_manager
                async with async_session() as ndb:
                    n = Notification(
                        tenant_id=row["tenant_id"],
                        user_id=row["created_by"],
                        type=NotificationType.EXECUTION_FAILED,
                        title="Scheduled trigger failed",
                        message=f"Trigger {trigger_id[:8]} failed: {str(e)[:400]}",
                        link=f"/triggers",
                        metadata_={
                            "execution_id": execution_id,
                            "trigger_id": trigger_id,
                            "reason": "trigger_exception",
                        },
                    )
                    ndb.add(n)
                    await ndb.commit()
                try:
                    await ws_manager.send_to_user(
                        row["created_by"], "notification",
                        {
                            "type": "execution_failed",
                            "title": "Scheduled trigger failed",
                            "message": str(e)[:200],
                            "link": "/triggers",
                        },
                    )
                except Exception:
                    pass
        except Exception:
            pass
