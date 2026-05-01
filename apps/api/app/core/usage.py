from __future__ import annotations

import sys
import uuid
from datetime import datetime, time, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.execution import Execution, ExecutionStatus
from models.tenant import Tenant, TenantPlan
from models.usage import RecordType, UsageRecord

from app.core.stripe import get_daily_limit
from app.core.ws_manager import ws_manager


async def track_execution(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    input_tokens: int,
    output_tokens: int,
    cost: float,
) -> None:
    now = datetime.now(timezone.utc)
    period_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    period_end = datetime.combine(now.date(), time.max, tzinfo=timezone.utc)

    record = UsageRecord(
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        record_type=RecordType.EXECUTION,
        quantity=1,
        unit="executions",
        cost=cost,
        metadata_={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        period_start=period_start,
        period_end=period_end,
    )
    db.add(record)

    token_record = UsageRecord(
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        record_type=RecordType.TOKEN,
        quantity=input_tokens + output_tokens,
        unit="tokens",
        cost=cost,
        metadata_={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        period_start=period_start,
        period_end=period_end,
    )
    db.add(token_record)
    await db.flush()


async def check_limit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> tuple[bool, str]:
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        return False, "Tenant not found"

    plan_key = tenant.plan.value if isinstance(tenant.plan, TenantPlan) else str(tenant.plan)
    daily_limit = get_daily_limit(plan_key)

    if daily_limit == -1:
        return True, ""

    now = datetime.now(timezone.utc)
    today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    count_result = await db.execute(
        select(func.count(Execution.id)).where(
            Execution.tenant_id == tenant_id,
            Execution.created_at >= today_start,
            Execution.status != ExecutionStatus.CANCELLED,
        )
    )
    today_count = count_result.scalar() or 0

    if today_count >= daily_limit:
        return False, f"Daily execution limit reached ({daily_limit}/{plan_key} plan). Upgrade for more."

    usage_pct = today_count / daily_limit * 100
    if user_id and usage_pct >= 80:
        await ws_manager.send_to_user(
            user_id,
            "usage_warning",
            {
                "used": today_count,
                "limit": daily_limit,
                "percent": round(usage_pct, 1),
                "plan": plan_key,
            },
        )

    return True, ""


async def check_user_quota(user: "User") -> str | None:
    """Check if user has exceeded their monthly token or cost quota.
    Returns error message if exceeded, None if OK.
    """
    from datetime import datetime, timezone

    # Check if quota needs monthly reset
    now = datetime.now(timezone.utc)
    if user.quota_reset_at and now >= user.quota_reset_at:
        # Will be reset by the scheduler, but check anyway
        pass

    # Check token allowance
    if user.token_monthly_allowance is not None:
        used = user.tokens_used_this_month or 0
        limit = user.token_monthly_allowance
        if used >= limit:
            return f"Monthly token quota exceeded: {used:,}/{limit:,} tokens used. Contact your admin to increase your allocation."

    # Check cost limit
    if user.cost_monthly_limit is not None:
        cost_used = float(user.cost_used_this_month or 0)
        cost_limit = float(user.cost_monthly_limit)
        if cost_used >= cost_limit:
            return f"Monthly cost limit exceeded: ${cost_used:.2f}/${cost_limit:.2f}. Contact your admin to increase your allocation."

    return None


async def update_user_usage(db: "AsyncSession", user: "User", input_tokens: int, output_tokens: int, cost: float) -> None:
    """Update user's monthly usage counters after an execution."""
    total_tokens = (input_tokens or 0) + (output_tokens or 0)
    user.tokens_used_this_month = (user.tokens_used_this_month or 0) + total_tokens
    user.cost_used_this_month = float(user.cost_used_this_month or 0) + (cost or 0)
    await db.flush()


async def get_usage_stats(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    days: int = 30,
) -> dict:
    now = datetime.now(timezone.utc)
    today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    today_exec_result = await db.execute(
        select(func.count(Execution.id)).where(
            Execution.tenant_id == tenant_id,
            Execution.created_at >= today_start,
            Execution.status != ExecutionStatus.CANCELLED,
        )
    )
    today_executions = today_exec_result.scalar() or 0

    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id)
    )
    tenant = result.scalar_one_or_none()
    plan_key = tenant.plan.value if tenant else "free"
    daily_limit = get_daily_limit(plan_key)

    from datetime import timedelta
    period_start = now - timedelta(days=days)

    total_exec_result = await db.execute(
        select(func.count(Execution.id)).where(
            Execution.tenant_id == tenant_id,
            Execution.created_at >= period_start,
        )
    )
    total_executions = total_exec_result.scalar() or 0

    token_result = await db.execute(
        select(
            func.coalesce(func.sum(Execution.input_tokens), 0),
            func.coalesce(func.sum(Execution.output_tokens), 0),
            func.coalesce(func.sum(Execution.cost), 0),
        ).where(
            Execution.tenant_id == tenant_id,
            Execution.created_at >= period_start,
        )
    )
    row = token_result.one()
    total_input_tokens = int(row[0])
    total_output_tokens = int(row[1])
    total_cost = float(row[2])

    day_col = func.date_trunc("day", Execution.created_at).label("day")
    daily_result = await db.execute(
        select(
            day_col,
            func.count(Execution.id).label("count"),
        )
        .where(
            Execution.tenant_id == tenant_id,
            Execution.created_at >= period_start,
        )
        .group_by(day_col)
        .order_by(day_col)
    )
    daily_executions = [
        {"date": row[0].strftime("%Y-%m-%d"), "count": row[1]}
        for row in daily_result.all()
    ]

    agent_result = await db.execute(
        select(
            Execution.agent_id,
            func.count(Execution.id).label("count"),
            func.coalesce(func.sum(Execution.input_tokens), 0).label("tokens"),
            func.coalesce(func.sum(Execution.cost), 0).label("cost"),
        )
        .where(
            Execution.tenant_id == tenant_id,
            Execution.created_at >= period_start,
            Execution.agent_id.isnot(None),
        )
        .group_by(Execution.agent_id)
        .order_by(func.count(Execution.id).desc())
        .limit(10)
    )
    by_agent = [
        {
            "agent_id": str(row[0]),
            "executions": row[1],
            "tokens": int(row[2]),
            "cost": round(float(row[3]), 6),
        }
        for row in agent_result.all()
    ]

    return {
        "plan": plan_key,
        "daily_limit": daily_limit,
        "today_executions": today_executions,
        "period_days": days,
        "total_executions": total_executions,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_input_tokens + total_output_tokens,
        "total_cost": round(total_cost, 6),
        "daily_executions": daily_executions,
        "by_agent": by_agent,
    }
