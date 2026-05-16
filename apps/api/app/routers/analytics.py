from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus, AgentType
from models.execution import Execution, ExecutionStatus
from models.user import User

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _period_start(period: str) -> datetime:
    now = datetime.now(timezone.utc)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "90d":
        return now - timedelta(days=90)
    return now - timedelta(days=30)


def _granularity_trunc(granularity: str) -> str:
    if granularity == "hourly":
        return "hour"
    if granularity == "weekly":
        return "week"
    return "day"


def _base_filters(tenant_id, start, agent_id=None):
    """Return a list of SQLAlchemy filter conditions for analytics queries."""
    filters = [Execution.tenant_id == tenant_id, Execution.created_at >= start]
    if agent_id:
        filters.append(Execution.agent_id == agent_id)
    return filters


@router.get("/overview")
async def get_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="30d"),
    agent_id: uuid.UUID | None = Query(default=None),
) -> JSONResponse:
    start = _period_start(period)
    tenant_id = user.tenant_id
    bf = _base_filters(tenant_id, start, agent_id)

    select(Execution).where(*bf)

    total_result = await db.execute(select(func.count(Execution.id)).where(*bf))
    total_executions = total_result.scalar() or 0

    completed_result = await db.execute(
        select(func.count(Execution.id)).where(
            *bf, Execution.status == ExecutionStatus.COMPLETED
        )
    )
    completed = completed_result.scalar() or 0

    failed_result = await db.execute(
        select(func.count(Execution.id)).where(
            *bf, Execution.status == ExecutionStatus.FAILED
        )
    )
    failed = failed_result.scalar() or 0

    success_rate = (
        round((completed / total_executions * 100), 1) if total_executions > 0 else 0
    )

    avg_duration_result = await db.execute(
        select(func.avg(Execution.duration_ms)).where(
            *bf,
            Execution.status == ExecutionStatus.COMPLETED,
            Execution.duration_ms.isnot(None),
        )
    )
    avg_duration = avg_duration_result.scalar()
    avg_response_ms = round(float(avg_duration)) if avg_duration else 0

    cost_result = await db.execute(
        select(func.coalesce(func.sum(Execution.cost), 0)).where(*bf)
    )
    total_cost = round(float(cost_result.scalar() or 0), 6)

    token_result = await db.execute(
        select(
            func.coalesce(func.sum(Execution.input_tokens), 0),
            func.coalesce(func.sum(Execution.output_tokens), 0),
        ).where(*bf)
    )
    row = token_result.one()
    total_input_tokens = int(row[0])
    total_output_tokens = int(row[1])

    cache_hit_rate = 0.0

    return success(
        {
            "total_executions": total_executions,
            "completed": completed,
            "failed": failed,
            "success_rate": success_rate,
            "avg_response_ms": avg_response_ms,
            "total_cost": total_cost,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "cache_hit_rate": cache_hit_rate,
            "period": period,
        }
    )


@router.get("/executions")
async def get_executions_timeseries(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="30d"),
    granularity: str = Query(default="daily"),
    agent_id: uuid.UUID | None = Query(default=None),
) -> JSONResponse:
    start = _period_start(period)
    trunc = _granularity_trunc(granularity)

    day_col = func.date_trunc(trunc, Execution.created_at).label("bucket")

    total_q = (
        select(
            day_col,
            func.count(Execution.id).label("total"),
            func.count(
                case(
                    (Execution.status == ExecutionStatus.COMPLETED, Execution.id),
                )
            ).label("completed"),
            func.count(
                case(
                    (Execution.status == ExecutionStatus.FAILED, Execution.id),
                )
            ).label("failed"),
            func.coalesce(func.avg(Execution.duration_ms), 0).label("avg_duration"),
        )
        .where(
            *_base_filters(user.tenant_id, start, agent_id),
        )
        .group_by(day_col)
        .order_by(day_col)
    )
    result = await db.execute(total_q)
    rows = result.all()

    data = []
    for row in rows:
        total = row[1]
        error_rate = round((row[3] / total * 100), 1) if total > 0 else 0
        data.append(
            {
                "date": (
                    row[0].strftime("%Y-%m-%d")
                    if trunc == "day"
                    else row[0].isoformat()
                ),
                "total": total,
                "completed": row[2],
                "failed": row[3],
                "error_rate": error_rate,
                "avg_duration_ms": round(float(row[4])),
            }
        )

    return success(data)


@router.get("/tokens")
async def get_token_breakdown(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="30d"),
    agent_id: uuid.UUID | None = Query(default=None),
) -> JSONResponse:
    start = _period_start(period)

    day_col = func.date_trunc("day", Execution.created_at).label("day")

    by_model_q = (
        select(
            Execution.model_used,
            func.coalesce(func.sum(Execution.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(Execution.output_tokens), 0).label("output_tokens"),
            func.count(Execution.id).label("count"),
            func.coalesce(func.sum(Execution.cost), 0).label("cost"),
        )
        .where(
            *_base_filters(user.tenant_id, start, agent_id),
            Execution.model_used.isnot(None),
        )
        .group_by(Execution.model_used)
        .order_by(func.sum(Execution.input_tokens).desc())
    )
    result = await db.execute(by_model_q)

    by_model = []
    for row in result.all():
        by_model.append(
            {
                "model": row[0],
                "input_tokens": int(row[1]),
                "output_tokens": int(row[2]),
                "total_tokens": int(row[1]) + int(row[2]),
                "executions": row[3],
                "cost": round(float(row[4]), 6),
            }
        )

    daily_q = (
        select(
            day_col,
            Execution.model_used,
            func.coalesce(func.sum(Execution.input_tokens), 0).label("input_t"),
            func.coalesce(func.sum(Execution.output_tokens), 0).label("output_t"),
        )
        .where(
            *_base_filters(user.tenant_id, start, agent_id),
            Execution.model_used.isnot(None),
        )
        .group_by(day_col, Execution.model_used)
        .order_by(day_col)
    )
    daily_result = await db.execute(daily_q)

    daily_map: dict[str, dict[str, Any]] = {}
    for row in daily_result.all():
        date_str = row[0].strftime("%Y-%m-%d")
        if date_str not in daily_map:
            daily_map[date_str] = {"date": date_str}
        model_key = (row[1] or "unknown").replace("-", "_").replace(".", "_")
        daily_map[date_str][model_key] = int(row[2]) + int(row[3])

    daily_tokens = list(daily_map.values())

    return success(
        {
            "by_model": by_model,
            "daily_tokens": daily_tokens,
        }
    )


@router.get("/costs")
async def get_cost_breakdown(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="30d"),
    agent_id: uuid.UUID | None = Query(default=None),
) -> JSONResponse:
    start = _period_start(period)

    by_agent_q = (
        select(
            Execution.agent_id,
            Agent.name,
            Agent.icon_url,
            Agent.category,
            func.count(Execution.id).label("executions"),
            func.coalesce(func.sum(Execution.cost), 0).label("cost"),
            func.coalesce(func.sum(Execution.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(Execution.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.avg(Execution.duration_ms), 0).label("avg_duration"),
        )
        .join(Agent, Agent.id == Execution.agent_id)
        .where(
            *_base_filters(user.tenant_id, start, agent_id),
        )
        .group_by(Execution.agent_id, Agent.name, Agent.icon_url, Agent.category)
        .order_by(func.sum(Execution.cost).desc())
        .limit(20)
    )
    result = await db.execute(by_agent_q)

    by_agent = []
    for row in result.all():
        by_agent.append(
            {
                "agent_id": str(row[0]),
                "name": row[1],
                "icon_url": row[2],
                "category": row[3],
                "executions": row[4],
                "cost": round(float(row[5]), 6),
                "input_tokens": int(row[6]),
                "output_tokens": int(row[7]),
                "total_tokens": int(row[6]) + int(row[7]),
                "avg_duration_ms": round(float(row[8])),
            }
        )

    day_col = func.date_trunc("day", Execution.created_at).label("day")
    daily_cost_q = (
        select(
            day_col,
            func.coalesce(func.sum(Execution.cost), 0).label("cost"),
        )
        .where(
            *_base_filters(user.tenant_id, start, agent_id),
        )
        .group_by(day_col)
        .order_by(day_col)
    )
    daily_result = await db.execute(daily_cost_q)

    daily_costs = [
        {"date": row[0].strftime("%Y-%m-%d"), "cost": round(float(row[1]), 6)}
        for row in daily_result.all()
    ]

    return success(
        {
            "by_agent": by_agent,
            "daily_costs": daily_costs,
        }
    )


@router.get("/live-stats")
async def get_live_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    tenant_id = user.tenant_id
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Single aggregated query instead of 7 sequential ones (perf: ~100ms vs ~1.5s)
    from sqlalchemy import case

    stats_result = await db.execute(
        select(
            func.count(
                case((Execution.status == ExecutionStatus.RUNNING, Execution.id))
            ).label("active"),
            func.count(case((Execution.created_at >= today_start, Execution.id))).label(
                "today_total"
            ),
            func.count(
                case(
                    (
                        (Execution.created_at >= today_start)
                        & (Execution.status == ExecutionStatus.COMPLETED),
                        Execution.id,
                    )
                )
            ).label("today_completed"),
            func.count(
                case(
                    (
                        (Execution.created_at >= today_start)
                        & (Execution.status == ExecutionStatus.FAILED),
                        Execution.id,
                    )
                )
            ).label("today_failed"),
            func.coalesce(
                func.sum(case((Execution.created_at >= today_start, Execution.cost))), 0
            ).label("today_cost"),
            func.coalesce(
                func.sum(
                    case((Execution.created_at >= today_start, Execution.input_tokens))
                ),
                0,
            ).label("today_input_tokens"),
            func.coalesce(
                func.sum(
                    case((Execution.created_at >= today_start, Execution.output_tokens))
                ),
                0,
            ).label("today_output_tokens"),
        ).where(Execution.tenant_id == tenant_id)
    )
    row = stats_result.one()
    active_executions = row.active or 0
    today_total = row.today_total or 0
    today_completed = row.today_completed or 0
    today_failed = row.today_failed or 0
    today_cost = round(float(row.today_cost or 0), 2)
    today_input_tokens = int(row.today_input_tokens or 0)
    today_output_tokens = int(row.today_output_tokens or 0)
    today_total_tokens = today_input_tokens + today_output_tokens

    success_rate = (
        round(today_completed / today_total * 100, 1) if today_total > 0 else 100.0
    )

    # Count agents visible to user (own tenant + OOB agents)
    agent_count_result = await db.execute(
        select(func.count(Agent.id)).where(
            or_(Agent.tenant_id == tenant_id, Agent.agent_type == AgentType.OOB),
            Agent.status != AgentStatus.ARCHIVED,
        )
    )
    total_agents = agent_count_result.scalar() or 0

    return success(
        {
            "active_executions": active_executions,
            "today_executions": today_total,
            "today_completed": today_completed,
            "today_failed": today_failed,
            "success_rate": success_rate,
            "total_agents": total_agents,
            "today_cost": today_cost,
            "today_input_tokens": today_input_tokens,
            "today_output_tokens": today_output_tokens,
            "today_total_tokens": today_total_tokens,
        }
    )


@router.get("/failures")
async def get_failure_summary(
    hours: int = 24,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Group recent failures by `failure_code` for the /alerts page."""
    hours = max(1, min(168, int(hours)))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    from sqlalchemy import desc, func

    q = await db.execute(
        select(
            Execution.failure_code,
            func.count(Execution.id).label("count"),
            func.max(Execution.completed_at).label("latest_at"),
            func.array_agg(Execution.agent_id.distinct()).label("agent_ids"),
            func.max(Execution.error_message).label("sample_message"),
        )
        .where(
            Execution.tenant_id == user.tenant_id,
            Execution.status == ExecutionStatus.FAILED,
            Execution.created_at >= cutoff,
        )
        .group_by(Execution.failure_code)
        .order_by(desc("count"))
    )
    rows = q.all()
    return success(
        [
            {
                "failure_code": r.failure_code or "UNKNOWN_ERROR",
                "count": int(r.count),
                "latest_at": r.latest_at.isoformat() if r.latest_at else None,
                "agent_ids": [str(a) for a in (r.agent_ids or []) if a],
                "sample_message": (r.sample_message or "")[:500],
            }
            for r in rows
        ]
    )


def _drift_config_key(tenant_id: str) -> str:
    return f"drift:config:enabled:{tenant_id}"


@router.get("/drift-alerts/config")
async def get_drift_config(user: User = Depends(get_current_user)) -> JSONResponse:
    """Read the tenant-wide drift detection toggle."""
    import os as _os
    import redis.asyncio as aioredis
    from app.core.config import settings

    env = (_os.environ.get("DRIFT_DETECTION_ENABLED", "true") or "").strip().lower()
    global_on = env not in ("0", "false", "no", "off")
    try:
        r = aioredis.from_url(str(settings.redis_url), decode_responses=True)
        raw = await r.get(_drift_config_key(str(user.tenant_id)))
        await r.aclose()
        tenant_on = None if raw is None else raw.strip().lower() not in ("0", "false")
    except Exception:
        tenant_on = None
    enabled = tenant_on if tenant_on is not None else global_on
    return success(
        {"enabled": enabled, "global": global_on, "tenant_override": tenant_on}
    )


@router.put("/drift-alerts/config")
async def set_drift_config(
    body: dict,
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Turn drift detection on/off for the current tenant. Overrides the
    global DRIFT_DETECTION_ENABLED env default."""
    if "enabled" not in body:
        return error("Body must include `enabled: boolean`", 400)
    enabled = bool(body.get("enabled"))
    import redis.asyncio as aioredis
    from app.core.config import settings

    try:
        r = aioredis.from_url(str(settings.redis_url), decode_responses=True)
        await r.set(_drift_config_key(str(user.tenant_id)), "1" if enabled else "0")
        await r.aclose()
    except Exception as e:
        return error(f"redis write failed: {e}", 500)
    return success({"enabled": enabled})


@router.get("/drift-alerts")
async def list_drift_alerts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    agent_id: uuid.UUID | None = Query(default=None),
    severity: str | None = Query(default=None),
    acknowledged: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> JSONResponse:
    """List drift detection alerts for the tenant."""
    from models.drift_alert import DriftAlert

    query = select(DriftAlert).where(DriftAlert.tenant_id == user.tenant_id)
    if agent_id:
        query = query.where(DriftAlert.agent_id == agent_id)
    if severity:
        query = query.where(DriftAlert.severity == severity)
    if acknowledged is not None:
        query = query.where(DriftAlert.acknowledged == acknowledged)
    query = query.order_by(DriftAlert.created_at.desc()).limit(limit)

    result = await db.execute(query)
    alerts = result.scalars().all()
    # Best-effort join to agent.name for the UI label
    agent_names: dict[str, str] = {}
    agent_ids = {str(a.agent_id) for a in alerts}
    if agent_ids:
        from models.agent import Agent as _Agent

        ar = await db.execute(
            select(_Agent.id, _Agent.name).where(_Agent.id.in_(agent_ids))
        )
        agent_names = {str(_id): _name for _id, _name in ar.all()}
    return success(
        [
            {
                "id": str(a.id),
                "agent_id": str(a.agent_id),
                "agent_name": agent_names.get(str(a.agent_id)),
                "severity": a.severity,
                # Expose under both field names so older and newer clients agree
                "metric": a.metric,
                "metric_name": a.metric,
                "baseline_value": a.baseline_value,
                "current_value": a.current_value,
                "deviation_pct": a.deviation_pct,
                "message": f"{a.metric} deviated {a.deviation_pct:+.1f}% from baseline ({a.baseline_value:.2f} → {a.current_value:.2f})",
                "execution_id": str(a.execution_id) if a.execution_id else None,
                "acknowledged": a.acknowledged,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in alerts
        ]
    )


@router.post("/drift-alerts/{alert_id}/acknowledge")
async def acknowledge_drift_alert(
    alert_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Mark a drift alert as acknowledged."""
    from models.drift_alert import DriftAlert

    result = await db.execute(
        select(DriftAlert).where(
            DriftAlert.id == alert_id,
            DriftAlert.tenant_id == user.tenant_id,
        )
    )
    alert = result.scalar_one_or_none()
    if not alert:
        return success({"error": "Alert not found"})

    alert.acknowledged = True
    await db.commit()
    return success({"acknowledged": True})


@router.get("/per-user")
async def get_per_user_analytics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Per-user token and cost breakdown. Admin sees all users, others see only themselves."""

    if user.role.value == "admin":
        # Admin sees all users in the tenant
        result = await db.execute(
            select(
                User.id,
                User.email,
                User.full_name,
                User.role,
                User.token_monthly_allowance,
                User.tokens_used_this_month,
                User.cost_monthly_limit,
                User.cost_used_this_month,
            ).where(User.tenant_id == user.tenant_id, User.is_active.is_(True))
        )
        users_data = [
            {
                "id": str(r.id),
                "email": r.email,
                "full_name": r.full_name,
                "role": r.role.value,
                "token_allowance": r.token_monthly_allowance,
                "tokens_used": r.tokens_used_this_month or 0,
                "cost_limit": (
                    float(r.cost_monthly_limit) if r.cost_monthly_limit else None
                ),
                "cost_used": float(r.cost_used_this_month or 0),
                "usage_pct": (
                    round(
                        (r.tokens_used_this_month or 0)
                        / max(r.token_monthly_allowance or 1, 1)
                        * 100,
                        1,
                    )
                    if r.token_monthly_allowance
                    else None
                ),
            }
            for r in result.all()
        ]
        return success(users_data)
    else:
        # Regular user sees only their own usage
        return success(
            {
                "id": str(user.id),
                "email": user.email,
                "token_allowance": user.token_monthly_allowance,
                "tokens_used": user.tokens_used_this_month or 0,
                "cost_limit": (
                    float(user.cost_monthly_limit) if user.cost_monthly_limit else None
                ),
                "cost_used": float(user.cost_used_this_month or 0),
                "usage_pct": (
                    round(
                        (user.tokens_used_this_month or 0)
                        / max(user.token_monthly_allowance or 1, 1)
                        * 100,
                        1,
                    )
                    if user.token_monthly_allowance
                    else None
                ),
            }
        )
