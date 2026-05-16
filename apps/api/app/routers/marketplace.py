from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.notifications import create_notification
from app.core.responses import error, success
from app.core.stripe import (
    create_marketplace_checkout,
    is_mock_mode,
    PLATFORM_FEE_PERCENT,
)
from app.schemas.marketplace import SubscribeRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus, AgentType
from models.marketplace import Review, Subscription
from models.payout import Payout, PayoutStatus
from models.tenant import Tenant
from models.user import User

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


def _serialize_listing(
    a: Agent,
    avg_rating: float | None,
    review_count: int,
    creator_name: str | None,
    subscriber_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "name": a.name,
        "slug": a.slug,
        "description": a.description,
        "agent_type": a.agent_type.value,
        "category": a.category,
        "icon_url": a.icon_url,
        "version": a.version,
        "model_config": a.model_config_,
        "marketplace_price": float(a.marketplace_price) if a.marketplace_price else 0,
        "is_free": a.marketplace_price is None or float(a.marketplace_price) == 0,
        "creator_name": creator_name,
        "avg_rating": round(float(avg_rating), 1) if avg_rating else 0,
        "review_count": review_count,
        "subscriber_count": subscriber_count,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("")
async def browse_marketplace(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    search: str = Query(default="", max_length=255),
    category: str = Query(default=""),
    sort: str = Query(default="popular"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=24, ge=1, le=100),
) -> JSONResponse:
    base = (
        select(
            Agent,
            func.coalesce(func.avg(Review.rating), 0).label("avg_rating"),
            func.count(Review.id.distinct()).label("review_count"),
            User.full_name.label("creator_name"),
            func.count(Subscription.id.distinct()).label("sub_count"),
        )
        .outerjoin(Review, Review.agent_id == Agent.id)
        .outerjoin(Subscription, Subscription.agent_id == Agent.id)
        .join(User, User.id == Agent.creator_id)
        .where(
            or_(
                Agent.is_published.is_(True),
                Agent.agent_type == AgentType.OOB,
            ),
            Agent.status == AgentStatus.ACTIVE,
        )
        .group_by(Agent.id, User.full_name)
    )

    if search:
        q = f"%{search}%"
        base = base.where(
            or_(
                Agent.name.ilike(q),
                Agent.description.ilike(q),
            )
        )

    if category:
        base = base.where(Agent.category == category)

    if sort == "newest":
        base = base.order_by(Agent.created_at.desc())
    elif sort == "top_rated":
        base = base.order_by(func.coalesce(func.avg(Review.rating), 0).desc())
    elif sort == "price_low":
        base = base.order_by(func.coalesce(Agent.marketplace_price, 0).asc())
    else:
        base = base.order_by(
            func.count(Subscription.id.distinct()).desc(),
            func.coalesce(func.avg(Review.rating), 0).desc(),
        )

    count_subq = base.subquery()
    count_result = await db.execute(select(func.count()).select_from(count_subq))
    total = count_result.scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(base.offset(offset).limit(per_page))
    rows = result.all()

    listings = [
        _serialize_listing(agent, avg_r, rev_c, creator, sub_c)
        for agent, avg_r, rev_c, creator, sub_c in rows
    ]

    return success(
        listings,
        meta={"total": total, "page": page, "per_page": per_page},
    )


@router.get("/{agent_id}")
async def get_marketplace_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(
            Agent,
            func.coalesce(func.avg(Review.rating), 0).label("avg_rating"),
            func.count(Review.id.distinct()).label("review_count"),
            User.full_name.label("creator_name"),
            func.count(Subscription.id.distinct()).label("sub_count"),
        )
        .outerjoin(Review, Review.agent_id == Agent.id)
        .outerjoin(Subscription, Subscription.agent_id == Agent.id)
        .join(User, User.id == Agent.creator_id)
        .where(
            Agent.id == agent_id,
            Agent.status == AgentStatus.ACTIVE,
        )
        .group_by(Agent.id, User.full_name)
    )
    row = result.one_or_none()
    if not row:
        return error("Agent not found", 404)

    agent, avg_r, rev_c, creator, sub_c = row

    sub_result = await db.execute(
        select(Subscription).where(
            Subscription.agent_id == agent_id,
            Subscription.user_id == user.id,
            Subscription.status == "active",
        )
    )
    is_subscribed = sub_result.scalar_one_or_none() is not None

    data = _serialize_listing(agent, avg_r, rev_c, creator, sub_c)
    data["system_prompt"] = agent.system_prompt
    data["is_subscribed"] = is_subscribed

    return success(data)


@router.post("/subscribe/{agent_id}")
async def subscribe_to_agent(
    agent_id: uuid.UUID,
    body: SubscribeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.status == AgentStatus.ACTIVE,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    existing = await db.execute(
        select(Subscription).where(
            Subscription.agent_id == agent_id,
            Subscription.user_id == user.id,
            Subscription.status == "active",
        )
    )
    if existing.scalar_one_or_none():
        return error("Already subscribed", 409)

    price = float(agent.marketplace_price) if agent.marketplace_price else 0

    if price > 0:
        creator_result = await db.execute(
            select(User).where(User.id == agent.creator_id)
        )
        creator = creator_result.scalar_one_or_none()

        if (
            not creator
            or not creator.stripe_connect_id
            or not creator.stripe_connect_onboarded
        ):
            return error("Agent creator has not set up payments", 400)

        if is_mock_mode():
            subscription = Subscription(
                user_id=user.id,
                agent_id=agent_id,
                plan_type=body.plan_type,
                status="active",
            )
            db.add(subscription)
            await db.flush()

            platform_fee = round(price * PLATFORM_FEE_PERCENT / 100, 2)
            creator_amount = round(price - platform_fee, 2)
            payout = Payout(
                creator_id=creator.id,
                subscription_id=subscription.id,
                agent_id=agent_id,
                amount_total=price,
                platform_fee=platform_fee,
                creator_amount=creator_amount,
                currency="usd",
                status=PayoutStatus.COMPLETED.value,
            )
            db.add(payout)
            await db.commit()
            await db.refresh(subscription)

            await _notify_new_subscriber(db, agent, user)

            return success(
                {
                    "id": str(subscription.id),
                    "agent_id": str(subscription.agent_id),
                    "plan_type": subscription.plan_type,
                    "status": subscription.status,
                    "mode": "mock",
                },
                status_code=201,
            )

        price_cents = int(price * 100)
        result_tenant = await db.execute(
            select(Tenant).where(Tenant.id == user.tenant_id)
        )
        tenant = result_tenant.scalar_one_or_none()

        try:
            checkout = await create_marketplace_checkout(
                customer_email=user.email,
                customer_id=tenant.stripe_customer_id if tenant else None,
                agent_name=agent.name,
                price_cents=price_cents,
                creator_connect_id=creator.stripe_connect_id,
                agent_id=str(agent_id),
                success_url=body.success_url,
                cancel_url=body.cancel_url,
            )
        except Exception as e:
            return error("Failed to create checkout: {}".format(str(e)), 500)

        return success(
            {
                "checkout_url": checkout["url"],
                "checkout_id": checkout["id"],
                "mode": checkout["mode"],
            },
            status_code=201,
        )
    else:
        subscription = Subscription(
            user_id=user.id,
            agent_id=agent_id,
            plan_type=body.plan_type,
            status="active",
        )
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)

        await _notify_new_subscriber(db, agent, user)

        return success(
            {
                "id": str(subscription.id),
                "agent_id": str(subscription.agent_id),
                "plan_type": subscription.plan_type,
                "status": subscription.status,
            },
            status_code=201,
        )


async def _notify_new_subscriber(
    db: AsyncSession, agent: Agent, subscriber: User
) -> None:
    try:
        creator_result = await db.execute(
            select(User).where(User.id == agent.creator_id)
        )
        creator = creator_result.scalar_one_or_none()
        if not creator:
            return

        await create_notification(
            db,
            tenant_id=creator.tenant_id,
            user_id=creator.id,
            type="new_subscriber",
            title="New subscriber",
            message=f"{subscriber.full_name or subscriber.email} subscribed to {agent.name}",
            link="/creator",
            metadata={
                "agent_id": str(agent.id),
                "agent_name": agent.name,
                "subscriber_name": subscriber.full_name or subscriber.email,
            },
        )
        await db.commit()
    except Exception:
        pass
