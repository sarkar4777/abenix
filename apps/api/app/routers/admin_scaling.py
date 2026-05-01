"""Admin scaling API — /api/admin/scaling/*"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import JSONResponse
from sqlalchemy import func as sqlfunc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success
from app.routers.auth import get_current_user
from models.agent import Agent, AgentStatus
from models.user import User
from models.execution import Execution

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/scaling", tags=["admin-scaling"])


# Canonical pool taxonomy — mirrors SCALING_PLAN.md.
# Kept in the API (not DB) because it's a platform decision, not per-agent.
POOLS = [
    {
        "key": "inline",
        "label": "Fast mode (in-app, no queue)",
        "description": "Run directly in the main app. Lowest latency; best for simple chat-style agents. No queue, no scale-out — keep for agents that finish in < 2s.",
        "default_min_replicas": 0,
        "default_max_replicas": 0,
        "default_concurrency": 0,
        "node_affinity": None,
    },
    {
        "key": "default",
        "label": "Default (recommended)",
        "description": "Runs on a dedicated worker. Crash-isolated from the main app and auto-scales under load. Good choice for most agents.",
        "default_min_replicas": 1,
        "default_max_replicas": 10,
        "default_concurrency": 3,
        "node_affinity": None,
    },
    {
        "key": "chat",
        "label": "Chat (latency-sensitive)",
        "description": "Kept warm so the first-token latency stays low for chat UX.",
        "default_min_replicas": 2,
        "default_max_replicas": 20,
        "default_concurrency": 6,
        "node_affinity": None,
    },
    {
        "key": "heavy-reasoning",
        "label": "Heavy reasoning (2.5-Pro, long docs)",
        "description": "For extraction / valuator / benchmarker — large contexts, memory-optimised.",
        "default_min_replicas": 1,
        "default_max_replicas": 15,
        "default_concurrency": 2,
        "node_affinity": "memory-optimised",
    },
    {
        "key": "gpu",
        "label": "GPU (local LLMs / embeddings)",
        "description": "H100/A100 node pool — enable only when you run local models.",
        "default_min_replicas": 0,
        "default_max_replicas": 4,
        "default_concurrency": 2,
        "node_affinity": "gpu",
    },
    {
        "key": "long-running",
        "label": "Long-running (Monte Carlo, sandboxed jobs)",
        "description": "Stress tests, code-runner, heavy compute — isolated so it can't starve chat.",
        "default_min_replicas": 0,
        "default_max_replicas": 8,
        "default_concurrency": 1,
        "node_affinity": None,
    },
]


def _is_admin(user: User) -> bool:
    role = getattr(user, "role", None)
    if role is None:
        return False
    r = role.value if hasattr(role, "value") else str(role)
    return r.lower() == "admin"


def _ensure_admin(user: User) -> None:
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin role required")


def _serialize_agent_scale(a: Agent) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "name": a.name,
        "slug": a.slug,
        "category": a.category,
        "status": a.status.value if hasattr(a.status, "value") else str(a.status),
        "agent_type": a.agent_type.value if hasattr(a.agent_type, "value") else str(a.agent_type),
        "runtime_pool": a.runtime_pool or "default",
        "dedicated_mode": bool(getattr(a, "dedicated_mode", False)),
        "effective_pool": (
            f"dedicated-{a.id}"
            if bool(getattr(a, "dedicated_mode", False))
            else (a.runtime_pool or "default")
        ),
        "min_replicas": a.min_replicas,
        "max_replicas": a.max_replicas,
        "concurrency_per_replica": a.concurrency_per_replica,
        "rate_limit_qps": a.rate_limit_qps,
        "daily_budget_usd": float(a.daily_budget_usd) if a.daily_budget_usd is not None else None,
        "daily_cost_limit": float(a.daily_cost_limit) if a.daily_cost_limit is not None else None,
        "model": (a.model_config_ or {}).get("model"),
    }


@router.get("/pools")
async def list_pools(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return the canonical pool list + per-pool agent counts + recent
    usage so the UI can render a meaningful health card for each pool."""
    _ensure_admin(user)

    # Count agents per pool (across all tenants) so admins see the whole fleet
    counts = {}
    for (pool, n) in (await db.execute(
        select(Agent.runtime_pool, sqlfunc.count(Agent.id)).group_by(Agent.runtime_pool)
    )).all():
        counts[pool or "default"] = n

    # 24-hour execution counts per pool (join via agents)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    exec_counts: dict[str, int] = {}
    try:
        rows = (await db.execute(
            select(Agent.runtime_pool, sqlfunc.count(Execution.id))
            .join(Execution, Execution.agent_id == Agent.id)
            .where(Execution.created_at >= since)
            .group_by(Agent.runtime_pool)
        )).all()
        for pool, n in rows:
            exec_counts[pool or "default"] = int(n)
    except Exception:
        # Execution model column name may differ in older deploys; non-fatal
        exec_counts = {}

    out = []
    for p in POOLS:
        out.append({
            **p,
            "agent_count": counts.get(p["key"], 0),
            "executions_24h": exec_counts.get(p["key"], 0),
        })
    return success({"pools": out})


@router.get("/agents")
async def list_agents_with_scale(
    pool: str = "",
    limit: int = 200,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List all agents with their scaling knobs. Supports filter by pool."""
    _ensure_admin(user)
    q = select(Agent).order_by(Agent.name).limit(max(1, min(500, limit)))
    if pool:
        q = q.where(Agent.runtime_pool == pool)
    rows = (await db.execute(q)).scalars().all()
    return success({"agents": [_serialize_agent_scale(a) for a in rows]})


@router.patch("/agents/{agent_id}")
async def update_agent_scale(
    agent_id: str,
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update scaling knobs on an agent."""
    _ensure_admin(user)
    a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not a:
        return error("Agent not found", 404)

    updates: dict[str, Any] = {}

    if "runtime_pool" in body:
        pool = str(body["runtime_pool"]).strip().lower()
        valid = {p["key"] for p in POOLS}
        if pool not in valid:
            return error(f"Invalid pool; choose one of {sorted(valid)}", 400)
        updates["runtime_pool"] = pool
        if pool == "inline":
            updates.setdefault("min_replicas", 0)
            updates.setdefault("max_replicas", 1)      # respect bounds
            updates.setdefault("concurrency_per_replica", 1)

    # Integer fields with bounds — keep values sane so nobody can
    # accidentally set max_replicas=10000 and blow the budget.
    int_bounds = {
        "min_replicas": (0, 50),
        "max_replicas": (1, 100),
        "concurrency_per_replica": (1, 20),
        "rate_limit_qps": (1, 10_000),
    }
    for field, (lo, hi) in int_bounds.items():
        if field in body:
            v = body[field]
            if v is None:
                updates[field] = None
            else:
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    return error(f"{field} must be an integer", 400)
                if iv < lo or iv > hi:
                    return error(f"{field} must be between {lo} and {hi}", 400)
                updates[field] = iv

    if "daily_budget_usd" in body:
        v = body["daily_budget_usd"]
        if v is None:
            updates["daily_budget_usd"] = None
        else:
            try:
                fv = float(v)
            except (TypeError, ValueError):
                return error("daily_budget_usd must be numeric", 400)
            if fv < 0 or fv > 100_000:
                return error("daily_budget_usd must be between 0 and 100000", 400)
            updates["daily_budget_usd"] = fv

    if "status" in body:
        s = str(body["status"]).strip().lower()
        try:
            updates["status"] = AgentStatus(s)
        except ValueError:
            return error(f"Invalid status '{s}'", 400)

    # Cross-field validation: max >= min
    final_min = updates.get("min_replicas", a.min_replicas)
    final_max = updates.get("max_replicas", a.max_replicas)
    if final_min is not None and final_max is not None and final_min > final_max:
        return error("min_replicas cannot exceed max_replicas", 400)

    if not updates:
        return error("No updatable fields provided", 400)

    for k, v in updates.items():
        setattr(a, k, v)
    await db.commit()
    await db.refresh(a)

    logger.info(
        "[admin.scaling] %s updated agent %s (slug=%s): %s",
        user.email, a.id, a.slug, {k: str(v)[:50] for k, v in updates.items()},
    )
    return success(_serialize_agent_scale(a))


@router.post("/agents/{agent_id}/pause")
async def pause_agent(
    agent_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Quick pause — sets status=archived so the runtime will refuse
    executions (but the row stays for audit/unpause)."""
    _ensure_admin(user)
    a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not a:
        return error("Agent not found", 404)
    a.status = AgentStatus.ARCHIVED
    await db.commit()
    await db.refresh(a)
    logger.warning("[admin.scaling] PAUSED %s (slug=%s) by %s", a.id, a.slug, user.email)
    return success({"id": str(a.id), "status": a.status.value})


@router.post("/agents/{agent_id}/resume")
async def resume_agent(
    agent_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _ensure_admin(user)
    a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not a:
        return error("Agent not found", 404)
    a.status = AgentStatus.ACTIVE
    await db.commit()
    await db.refresh(a)
    logger.info("[admin.scaling] RESUMED %s (slug=%s) by %s", a.id, a.slug, user.email)
    return success({"id": str(a.id), "status": a.status.value})


@router.post("/agents/{agent_id}/dedicated-mode")
async def set_dedicated_mode(
    agent_id: str,
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Toggle per-agent dedicated pod scaling."""
    _ensure_admin(user)
    a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not a:
        return error("Agent not found", 404)
    enabled = bool(body.get("enabled", False))
    a.dedicated_mode = enabled
    await db.commit()
    await db.refresh(a)
    logger.info(
        "[admin.scaling] dedicated_mode=%s on agent %s (slug=%s) by %s",
        enabled, a.id, a.slug, user.email,
    )
    return success(_serialize_agent_scale(a))


@router.get("/agents/{agent_id}/cost-projection")
async def cost_projection(
    agent_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Project hourly + daily + monthly cost for this agent based on"""
    _ensure_admin(user)
    a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not a:
        return error("Agent not found", 404)

    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = (await db.execute(
        select(Execution)
        .where(Execution.agent_id == a.id, Execution.created_at >= since_24h)
        .order_by(Execution.created_at.desc())
        .limit(500)
    )).scalars().all()
    runs_24h = len(rows)
    total_cost = sum(float(r.cost_usd or 0) for r in rows)
    avg_cost_per_run = total_cost / runs_24h if runs_24h > 0 else 0.0
    avg_duration_ms = (
        sum(int(r.duration_ms or 0) for r in rows) / runs_24h
        if runs_24h > 0 else 0.0
    )

    runs_per_hour = runs_24h / 24.0 if runs_24h else 0.0
    # Per-pool fixed costs (placeholder until a real billing API plugs in).
    # Tuned to give the operator a sane, clearly-labelled estimate.
    POD_COST_USD_PER_HOUR_PER_REPLICA = 0.012  # rough Azure E2-medium
    shared_replica_share = 0.05  # this agent's share of a multi-tenant pool

    avg_replicas_shared = max(1, a.min_replicas) * shared_replica_share
    avg_replicas_dedicated = max(1, a.min_replicas)
    peak_replicas = a.max_replicas

    def _scenario(replicas: float) -> dict[str, Any]:
        infra_per_h = replicas * POD_COST_USD_PER_HOUR_PER_REPLICA
        token_per_h = runs_per_hour * avg_cost_per_run
        per_h = infra_per_h + token_per_h
        return {
            "replicas_avg": round(replicas, 2),
            "infra_usd_per_hour": round(infra_per_h, 4),
            "token_usd_per_hour": round(token_per_h, 4),
            "total_usd_per_hour": round(per_h, 4),
            "total_usd_per_day": round(per_h * 24, 2),
            "total_usd_per_month": round(per_h * 24 * 30, 2),
        }

    return success({
        "agent_id": str(a.id),
        "telemetry_24h": {
            "runs": runs_24h,
            "total_cost_usd": round(total_cost, 4),
            "avg_cost_per_run_usd": round(avg_cost_per_run, 4),
            "avg_duration_ms": round(avg_duration_ms, 0),
            "runs_per_hour": round(runs_per_hour, 2),
        },
        "scenarios": {
            "shared":    _scenario(avg_replicas_shared),
            "dedicated": _scenario(avg_replicas_dedicated),
            "peak":      _scenario(peak_replicas),
        },
        "current": "dedicated" if getattr(a, "dedicated_mode", False) else "shared",
        "notes": [
            "Infra cost uses a $0.012/hour per-pod baseline; tune in code or per-cluster billing.",
            "Token cost is the trailing 24h average per run × current run-rate.",
            "Shared mode credits this agent ~5% of a pool replica (multi-tenant amortisation).",
            "Dedicated mode pins min_replicas pods; peak shows the max_replicas worst case.",
        ],
    })


@router.get("/tenants/{tenant_id}/spend")
async def tenant_spend(
    tenant_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Per-tenant spend today + this month, vs. configured daily_budget_usd
    aggregated across all their agents. Drives the P4 budget alert."""
    _ensure_admin(user)

    start_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start_month = start_day.replace(day=1)

    # Cost column may not exist in older deployments — guard gracefully
    try:
        today = (await db.execute(
            select(sqlfunc.coalesce(sqlfunc.sum(Execution.cost_usd), 0))
            .join(Agent, Agent.id == Execution.agent_id)
            .where(Agent.tenant_id == tenant_id, Execution.created_at >= start_day)
        )).scalar() or 0.0
        month = (await db.execute(
            select(sqlfunc.coalesce(sqlfunc.sum(Execution.cost_usd), 0))
            .join(Agent, Agent.id == Execution.agent_id)
            .where(Agent.tenant_id == tenant_id, Execution.created_at >= start_month)
        )).scalar() or 0.0
    except Exception as e:
        logger.debug("tenant_spend cost columns not available: %s", e)
        today, month = 0.0, 0.0

    # Sum of configured daily budgets across this tenant's agents
    budgets = (await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(Agent.daily_budget_usd), 0))
        .where(Agent.tenant_id == tenant_id, Agent.daily_budget_usd.is_not(None))
    )).scalar() or 0.0

    return success({
        "tenant_id": tenant_id,
        "today_usd": float(today),
        "month_usd": float(month),
        "daily_budget_usd": float(budgets),
        "budget_utilization_pct": (float(today) / float(budgets) * 100.0) if float(budgets) > 0 else None,
    })
