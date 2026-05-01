from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.core.stripe import (
    PLANS,
    _has_real_price,
    construct_webhook_event,
    create_checkout_session,
    create_portal_session,
    is_mock_mode,
)
from app.core.usage import get_usage_stats
from app.schemas.billing import CheckoutRequest, PortalRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent
from models.marketplace import Subscription
from models.payout import Payout, PayoutStatus
from models.tenant import Tenant, TenantPlan
from models.user import User

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/plans")
async def list_plans(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    plans = []
    for key, plan in PLANS.items():
        has_checkout = (
            key in ("pro", "business") if is_mock_mode() else _has_real_price(key)
        )
        plans.append(
            {
                "key": key,
                "name": plan["name"],
                "price_monthly": plan["price_monthly"],
                "exec_per_day": plan["exec_per_day"],
                "has_checkout": has_checkout,
            }
        )
    return success(
        {"plans": plans, "stripe_mode": "mock" if is_mock_mode() else "live"}
    )


@router.post("/checkout")
async def create_checkout(
    body: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if body.plan not in PLANS:
        return error("Invalid plan", 400)

    PLANS[body.plan]
    if body.plan in ("free", "enterprise"):
        return error("This plan does not support checkout", 400)
    if not is_mock_mode() and not _has_real_price(body.plan):
        return error(
            "Missing Stripe price ID for this plan. Configure STRIPE_PRO_PRICE_ID or STRIPE_BUSINESS_PRICE_ID.",
            400,
        )

    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        return error("Tenant not found", 404)

    try:
        session = await create_checkout_session(
            customer_id=tenant.stripe_customer_id,
            customer_email=user.email,
            plan_key=body.plan,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
    except Exception as e:
        return error("Failed to create checkout: {}".format(str(e)), 500)

    if session.get("mode") == "mock":
        tenant.plan = TenantPlan(body.plan)
        await db.commit()

    return success(session)


@router.post("/portal")
async def create_portal(
    body: PortalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        return error("Tenant not found", 404)

    if not tenant.stripe_customer_id and not is_mock_mode():
        return error("No billing account found. Subscribe to a plan first.", 400)

    try:
        session = await create_portal_session(
            customer_id=tenant.stripe_customer_id or "cus_mock",
            return_url=body.return_url,
        )
    except Exception as e:
        return error("Failed to create portal: {}".format(str(e)), 500)

    return success(session)


@router.get("/usage")
async def get_billing_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    stats = await get_usage_stats(db, user.tenant_id)
    return success(stats)


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = construct_webhook_event(payload, sig_header)
    except Exception as e:
        return error("Webhook signature verification failed: {}".format(str(e)), 400)

    if isinstance(event, dict):
        event_type = event.get("type", "")
        event_data = event.get("data", {}).get("object", {})
    else:
        event_type = event.type
        event_data = event.data.object

    if event_type == "checkout.session.completed":
        metadata = event_data.get("metadata", {})
        if metadata.get("type") == "marketplace_agent":
            await _handle_marketplace_checkout(db, event_data)
        else:
            await _handle_checkout_completed(db, event_data)
    elif event_type == "account.updated":
        await _handle_connect_account_updated(db, event_data)
    elif event_type == "invoice.paid":
        await _handle_invoice_paid(db, event_data)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(db, event_data)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(db, event_data)

    return success({"received": True})


async def _handle_checkout_completed(
    db: AsyncSession,
    data: dict[str, Any],
) -> None:
    customer_id = data.get("customer")
    customer_email = data.get("customer_email") or data.get("customer_details", {}).get(
        "email"
    )

    if not customer_email:
        return

    result = await db.execute(
        select(Tenant)
        .join(User, User.tenant_id == Tenant.id)
        .where(User.email == customer_email)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        return

    if customer_id:
        tenant.stripe_customer_id = customer_id
    await db.commit()


async def _handle_invoice_paid(
    db: AsyncSession,
    data: dict[str, Any],
) -> None:
    from datetime import datetime, time as dt_time, timezone

    from app.core.stripe import PLATFORM_FEE_PERCENT
    from models.usage import RecordType, UsageRecord

    stripe_sub_id = data.get("subscription")
    if not stripe_sub_id:
        return

    # Look up the subscription
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return

    # Update current_period_end from invoice line items
    lines = data.get("lines", {}).get("data", [])
    if lines:
        period_end_ts = lines[0].get("period", {}).get("end")
        if period_end_ts:
            subscription.current_period_end = datetime.fromtimestamp(
                period_end_ts, tz=timezone.utc
            )

    # Get user for tenant info
    user_result = await db.execute(select(User).where(User.id == subscription.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        await db.commit()
        return

    # Create usage record for the payment
    amount_paid = data.get("amount_paid", 0) / 100  # cents to dollars
    if amount_paid > 0:
        now = datetime.now(timezone.utc)
        period_start = datetime.combine(now.date(), dt_time.min, tzinfo=timezone.utc)
        period_end = datetime.combine(now.date(), dt_time.max, tzinfo=timezone.utc)

        usage_record = UsageRecord(
            tenant_id=user.tenant_id,
            user_id=user.id,
            agent_id=subscription.agent_id,
            record_type=RecordType.EXECUTION,
            quantity=1,
            unit="subscription_payment",
            cost=amount_paid,
            metadata_={
                "stripe_subscription_id": stripe_sub_id,
                "stripe_invoice_id": data.get("id"),
                "amount_paid": amount_paid,
            },
            period_start=period_start,
            period_end=period_end,
        )
        db.add(usage_record)

    # If marketplace subscription with paid agent, create payout for creator
    if subscription.agent_id:
        agent_result = await db.execute(
            select(Agent).where(Agent.id == subscription.agent_id)
        )
        agent = agent_result.scalar_one_or_none()

        if agent and agent.marketplace_price and float(agent.marketplace_price) > 0:
            price = float(agent.marketplace_price)
            platform_fee = round(price * PLATFORM_FEE_PERCENT / 100, 2)
            creator_amount = round(price - platform_fee, 2)

            payout = Payout(
                creator_id=agent.creator_id,
                subscription_id=subscription.id,
                agent_id=agent.id,
                stripe_charge_id=data.get("charge"),
                amount_total=price,
                platform_fee=platform_fee,
                creator_amount=creator_amount,
                currency="usd",
                status=PayoutStatus.COMPLETED.value,
            )
            db.add(payout)

    await db.commit()


async def _handle_subscription_updated(
    db: AsyncSession,
    data: dict[str, Any],
) -> None:
    customer_id = data.get("customer")
    if not customer_id:
        return

    result = await db.execute(
        select(Tenant).where(Tenant.stripe_customer_id == customer_id)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        return

    price_id = None
    items = data.get("items", {}).get("data", [])
    if items:
        price_id = items[0].get("price", {}).get("id")

    if price_id:
        for plan_key, plan in PLANS.items():
            if plan["stripe_price_id"] == price_id:
                tenant.plan = TenantPlan(plan_key)
                break

    status = data.get("status")
    if status in ("canceled", "unpaid", "past_due"):
        tenant.plan = TenantPlan.FREE

    await db.commit()


async def _handle_subscription_deleted(
    db: AsyncSession,
    data: dict[str, Any],
) -> None:
    customer_id = data.get("customer")
    if not customer_id:
        return

    result = await db.execute(
        select(Tenant).where(Tenant.stripe_customer_id == customer_id)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        return

    tenant.plan = TenantPlan.FREE
    await db.commit()


async def _handle_marketplace_checkout(
    db: AsyncSession,
    data: dict[str, Any],
) -> None:
    metadata = data.get("metadata", {})
    agent_id = metadata.get("agent_id")
    if not agent_id:
        return

    customer_email = data.get("customer_email") or data.get("customer_details", {}).get(
        "email"
    )
    if not customer_email:
        return

    user_result = await db.execute(select(User).where(User.email == customer_email))
    user = user_result.scalar_one_or_none()
    if not user:
        return

    agent_result = await db.execute(
        select(Agent).where(Agent.id == uuid.UUID(agent_id))
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        return

    stripe_sub_id = data.get("subscription")

    subscription = Subscription(
        user_id=user.id,
        agent_id=agent.id,
        stripe_subscription_id=stripe_sub_id,
        stripe_payment_intent_id=data.get("payment_intent"),
        plan_type="paid",
        status="active",
    )
    db.add(subscription)
    await db.flush()

    price = float(agent.marketplace_price) if agent.marketplace_price else 0
    from app.core.stripe import PLATFORM_FEE_PERCENT

    platform_fee = round(price * PLATFORM_FEE_PERCENT / 100, 2)
    creator_amount = round(price - platform_fee, 2)

    payout = Payout(
        creator_id=agent.creator_id,
        subscription_id=subscription.id,
        agent_id=agent.id,
        stripe_transfer_id=data.get("transfer"),
        amount_total=price,
        platform_fee=platform_fee,
        creator_amount=creator_amount,
        currency="usd",
        status=PayoutStatus.COMPLETED.value,
    )
    db.add(payout)
    await db.commit()


async def _handle_connect_account_updated(
    db: AsyncSession,
    data: dict[str, Any],
) -> None:
    account_id = data.get("id")
    if not account_id:
        return

    result = await db.execute(select(User).where(User.stripe_connect_id == account_id))
    user = result.scalar_one_or_none()
    if not user:
        return

    details_submitted = data.get("details_submitted", False)
    if details_submitted:
        user.stripe_connect_onboarded = True
        await db.commit()
