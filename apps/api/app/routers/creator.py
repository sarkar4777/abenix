from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import cast, Date, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.permissions import features_for
from app.core.platform_features import (
    monetization_enabled,
    require_marketplace,
    require_monetization,
)
from app.core.responses import error, success
from app.core.stripe import (
    create_connect_account,
    create_connect_login_link,
    create_connect_onboarding_link,
    get_connect_account_status,
    get_connect_balance,
)
from app.schemas.creator import OnboardCreatorRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus, AgentType
from models.execution import Execution
from models.marketplace import Review, Subscription
from models.payout import Payout
from models.user import User, UserRole

router = APIRouter(prefix="/api/creator", tags=["creator"])

# Stripe Connect, revenue and payouts
_PAID = [Depends(require_monetization)]


@router.post("/onboard", dependencies=_PAID)
async def onboard_creator(
    body: OnboardCreatorRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    account_id = user.stripe_connect_id

    if not account_id:
        result = await create_connect_account(user.email, str(user.id))
        account_id = result["account_id"]
        user.stripe_connect_id = account_id

    # Stripe onboarding never changes role. Publish rights come from
    # the role an admin assigned, see features_for().

    link_result = await create_connect_onboarding_link(
        account_id,
        body.refresh_url,
        body.return_url,
    )

    if link_result.get("mode") == "mock":
        user.stripe_connect_onboarded = True

    await db.commit()

    return success(
        {
            "account_id": account_id,
            "onboarding_url": link_result["url"],
            "mode": link_result.get("mode", "live"),
        }
    )


@router.get("/status", dependencies=_PAID)
async def creator_status(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    if not user.stripe_connect_id:
        return success(
            {
                "is_onboarded": False,
                "stripe_connect_id": None,
                "charges_enabled": False,
                "payouts_enabled": False,
                "details_submitted": False,
            }
        )

    account_status = await get_connect_account_status(user.stripe_connect_id)

    return success(
        {
            "is_onboarded": user.stripe_connect_onboarded,
            "stripe_connect_id": user.stripe_connect_id,
            "charges_enabled": account_status["charges_enabled"],
            "payouts_enabled": account_status["payouts_enabled"],
            "details_submitted": account_status["details_submitted"],
        }
    )


@router.get("/dashboard", dependencies=_PAID)
async def creator_dashboard(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="30d"),
) -> JSONResponse:
    if not user.stripe_connect_id and user.role not in (
        UserRole.CREATOR,
        UserRole.ADMIN,
    ):
        return error("Not a creator", 403)

    period_days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
    start_date = datetime.now(timezone.utc) - timedelta(days=period_days)

    payouts_query = select(Payout).where(
        Payout.creator_id == user.id,
        Payout.created_at >= start_date,
    )
    payouts_result = await db.execute(payouts_query)
    payouts = payouts_result.scalars().all()

    total_revenue = float(sum(p.amount_total for p in payouts))
    total_platform_fees = float(sum(p.platform_fee for p in payouts))
    creator_earnings = float(sum(p.creator_amount for p in payouts))

    subscriber_count_query = (
        select(func.count(Subscription.id))
        .join(Agent, Subscription.agent_id == Agent.id)
        .where(Agent.creator_id == user.id, Subscription.status == "active")
    )
    subscriber_result = await db.execute(subscriber_count_query)
    subscriber_count = subscriber_result.scalar() or 0

    published_agents_query = select(func.count(Agent.id)).where(
        Agent.creator_id == user.id,
        Agent.status == AgentStatus.ACTIVE,
        Agent.is_published.is_(True),
    )
    published_result = await db.execute(published_agents_query)
    published_agents_count = published_result.scalar() or 0

    if user.stripe_connect_id:
        balance = await get_connect_balance(user.stripe_connect_id)
    else:
        balance = {
            "available": [{"amount": 0, "currency": "usd"}],
            "pending": [{"amount": 0, "currency": "usd"}],
            "mode": "mock",
        }

    revenue_by_day_query = (
        select(
            cast(Payout.created_at, Date).label("date"),
            func.sum(Payout.creator_amount).label("earnings"),
            func.count(Payout.id).label("count"),
        )
        .where(Payout.creator_id == user.id, Payout.created_at >= start_date)
        .group_by(cast(Payout.created_at, Date))
        .order_by(cast(Payout.created_at, Date))
    )
    revenue_by_day_result = await db.execute(revenue_by_day_query)
    revenue_by_day = [
        {"date": str(row.date), "earnings": float(row.earnings), "count": row.count}
        for row in revenue_by_day_result.all()
    ]

    top_agents_query = (
        select(
            Payout.agent_id,
            Agent.name.label("agent_name"),
            func.sum(Payout.creator_amount).label("earnings"),
            func.sum(Payout.amount_total).label("revenue"),
            func.count(Payout.id).label("transactions"),
        )
        .join(Agent, Payout.agent_id == Agent.id)
        .where(Payout.creator_id == user.id, Payout.created_at >= start_date)
        .group_by(Payout.agent_id, Agent.name)
        .order_by(func.sum(Payout.creator_amount).desc())
    )
    top_agents_result = await db.execute(top_agents_query)
    top_agents = [
        {
            "agent_id": str(row.agent_id),
            "agent_name": row.agent_name,
            "earnings": float(row.earnings),
            "revenue": float(row.revenue),
            "transactions": row.transactions,
        }
        for row in top_agents_result.all()
    ]

    recent_payouts_query = (
        select(Payout)
        .where(Payout.creator_id == user.id)
        .order_by(Payout.created_at.desc())
        .limit(10)
    )
    recent_payouts_result = await db.execute(recent_payouts_query)
    recent_payouts = [
        {
            "id": str(p.id),
            "agent_id": str(p.agent_id),
            "amount_total": float(p.amount_total),
            "platform_fee": float(p.platform_fee),
            "creator_amount": float(p.creator_amount),
            "currency": p.currency,
            "status": p.status,
            "created_at": p.created_at.isoformat(),
        }
        for p in recent_payouts_result.scalars().all()
    ]

    return success(
        {
            "period": period,
            "total_revenue": total_revenue,
            "total_platform_fees": total_platform_fees,
            "creator_earnings": creator_earnings,
            "subscriber_count": subscriber_count,
            "published_agents_count": published_agents_count,
            "balance": balance,
            "revenue_by_day": revenue_by_day,
            "top_agents": top_agents,
            "recent_payouts": recent_payouts,
        }
    )


@router.get("/login-link", dependencies=_PAID)
async def creator_login_link(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    if not user.stripe_connect_id:
        return error("Not onboarded", 400)

    result = await create_connect_login_link(user.stripe_connect_id)
    return success(result)


def _listing_state(a: Agent) -> str | None:
    if a.status == AgentStatus.PENDING_REVIEW:
        return "pending"
    if a.status == AgentStatus.REJECTED:
        return "rejected"
    if a.status == AgentStatus.ACTIVE and a.is_published:
        return "live"
    return None


@router.get("/listings", dependencies=[Depends(require_marketplace)])
async def creator_listings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """The caller's marketplace listings with installs and usage, no money."""
    paid = await monetization_enabled(db)
    agents = (
        (
            await db.execute(
                select(Agent)
                .where(
                    Agent.creator_id == user.id,
                    Agent.tenant_id == user.tenant_id,
                    Agent.agent_type != AgentType.OOB,
                    Agent.status != AgentStatus.ARCHIVED,
                )
                .order_by(Agent.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    listed = [a for a in agents if _listing_state(a)]
    ids = [a.id for a in listed]

    installs: dict = {}
    runs: dict = {}
    users: dict = {}
    ratings: dict = {}
    if ids:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        for agent_id, n in (
            await db.execute(
                select(Subscription.agent_id, func.count(Subscription.id))
                .where(Subscription.agent_id.in_(ids), Subscription.status == "active")
                .group_by(Subscription.agent_id)
            )
        ).all():
            installs[agent_id] = int(n or 0)
        for agent_id, n, u in (
            await db.execute(
                select(
                    Execution.agent_id,
                    func.count(Execution.id),
                    func.count(Execution.user_id.distinct()),
                )
                .where(Execution.agent_id.in_(ids), Execution.created_at >= since)
                .group_by(Execution.agent_id)
            )
        ).all():
            runs[agent_id] = int(n or 0)
            users[agent_id] = int(u or 0)
        for agent_id, avg, n in (
            await db.execute(
                select(Review.agent_id, func.avg(Review.rating), func.count(Review.id))
                .where(Review.agent_id.in_(ids))
                .group_by(Review.agent_id)
            )
        ).all():
            ratings[agent_id] = (round(float(avg or 0), 1), int(n or 0))

    rows = []
    for a in listed:
        avg, n_reviews = ratings.get(a.id, (0, 0))
        row = {
            "id": str(a.id),
            "name": a.name,
            "description": a.description,
            "category": a.category,
            "state": _listing_state(a),
            "rejection_reason": a.rejection_reason,
            "installs": installs.get(a.id, 0),
            "runs_30d": runs.get(a.id, 0),
            "users_30d": users.get(a.id, 0),
            "avg_rating": avg,
            "review_count": n_reviews,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        }
        if paid:
            row["price"] = float(a.marketplace_price or 0)
        rows.append(row)

    eligible = [
        {"id": str(a.id), "name": a.name, "category": a.category}
        for a in agents
        if not _listing_state(a)
        and a.status in (AgentStatus.DRAFT, AgentStatus.ACTIVE)
        and a.name
    ]

    return success(
        {
            "can_list": bool(features_for(user).get("publish_to_marketplace")),
            "monetization": paid,
            "listings": rows,
            "eligible": eligible,
            "totals": {
                "live": sum(1 for r in rows if r["state"] == "live"),
                "pending": sum(1 for r in rows if r["state"] == "pending"),
                "installs": sum(r["installs"] for r in rows),
                "runs_30d": sum(r["runs_30d"] for r in rows),
            },
        }
    )
