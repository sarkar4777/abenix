from __future__ import annotations

import os
from pathlib import Path

import stripe
from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parents[4] / ".env"
load_dotenv(_env_path, override=False)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_CONNECT_CLIENT_ID = os.getenv("STRIPE_CONNECT_CLIENT_ID", "")

PLATFORM_FEE_PERCENT = 20

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

PLANS = {
    "free": {
        "name": "Free",
        "price_monthly": 0,
        "exec_per_day": 50,
        "stripe_price_id": None,
    },
    "pro": {
        "name": "Pro",
        "price_monthly": 29,
        "exec_per_day": 500,
        "stripe_price_id": os.getenv("STRIPE_PRO_PRICE_ID", ""),
    },
    "business": {
        "name": "Business",
        "price_monthly": 99,
        "exec_per_day": -1,
        "stripe_price_id": os.getenv("STRIPE_BUSINESS_PRICE_ID", ""),
    },
    "enterprise": {
        "name": "Enterprise",
        "price_monthly": -1,
        "exec_per_day": -1,
        "stripe_price_id": None,
    },
}


def is_mock_mode() -> bool:
    """Returns True when Stripe secret key is not configured."""
    return not STRIPE_SECRET_KEY or not STRIPE_SECRET_KEY.startswith("sk_")


def _has_real_price(plan_key: str) -> bool:
    """Check if plan has a valid Stripe price ID for checkout."""
    plan = PLANS.get(plan_key)
    if not plan:
        return False
    price_id = plan.get("stripe_price_id")
    return bool(price_id and price_id.startswith("price_"))


def get_plan(plan_key: str) -> dict | None:
    return PLANS.get(plan_key)


def get_daily_limit(plan_key: str) -> int:
    plan = PLANS.get(plan_key, PLANS["free"])
    return plan["exec_per_day"]


async def create_checkout_session(
    customer_id: str | None,
    customer_email: str,
    plan_key: str,
    success_url: str,
    cancel_url: str,
) -> dict:
    plan = PLANS.get(plan_key)
    if not plan:
        raise ValueError("Plan '{}' not found".format(plan_key))

    price_id = plan.get("stripe_price_id")

    # Mock mode: no secret key or no real price ID
    if is_mock_mode() or not _has_real_price(plan_key):
        return {
            "id": "cs_mock_{}".format(plan_key),
            "url": "{}&session_id=cs_mock_{}".format(success_url, plan_key),
            "mode": "mock",
        }

    params: dict = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url + "&session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": cancel_url,
    }
    if customer_id:
        params["customer"] = customer_id
    else:
        params["customer_email"] = customer_email

    session = stripe.checkout.Session.create(**params)
    return {
        "id": session.id,
        "url": session.url,
        "mode": "live",
    }


async def create_portal_session(
    customer_id: str,
    return_url: str,
) -> dict:
    if is_mock_mode():
        return {
            "url": "{}?portal=mock".format(return_url),
            "mode": "mock",
        }

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return {
        "url": session.url,
        "mode": "live",
    }


def construct_webhook_event(
    payload: bytes,
    sig_header: str,
) -> stripe.Event | dict:
    if is_mock_mode() or not STRIPE_WEBHOOK_SECRET:
        import json

        data = json.loads(payload)
        return data

    return stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)


async def create_connect_account(
    email: str,
    user_id: str,
) -> dict:
    if is_mock_mode():
        return {
            "account_id": "acct_mock_{}".format(user_id[:8]),
            "mode": "mock",
        }

    account = stripe.Account.create(
        type="express",
        email=email,
        metadata={"abenix_user_id": user_id},
        capabilities={"transfers": {"requested": True}},
    )
    return {
        "account_id": account.id,
        "mode": "live",
    }


async def create_connect_onboarding_link(
    account_id: str,
    refresh_url: str,
    return_url: str,
) -> dict:
    if is_mock_mode():
        return {
            "url": "{}?onboarding=mock".format(return_url),
            "mode": "mock",
        }

    link = stripe.AccountLink.create(
        account=account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return {
        "url": link.url,
        "mode": "live",
    }


async def create_connect_login_link(account_id: str) -> dict:
    if is_mock_mode():
        return {
            "url": "https://connect.stripe.com/express/mock",
            "mode": "mock",
        }

    link = stripe.Account.create_login_link(account_id)
    return {"url": link.url, "mode": "live"}


async def get_connect_account_status(account_id: str) -> dict:
    if is_mock_mode():
        return {
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
            "mode": "mock",
        }

    account = stripe.Account.retrieve(account_id)
    return {
        "charges_enabled": account.charges_enabled,
        "payouts_enabled": account.payouts_enabled,
        "details_submitted": account.details_submitted,
        "mode": "live",
    }


async def get_connect_balance(account_id: str) -> dict:
    if is_mock_mode():
        return {
            "available": [{"amount": 15000, "currency": "usd"}],
            "pending": [{"amount": 5000, "currency": "usd"}],
            "mode": "mock",
        }

    balance = stripe.Balance.retrieve(stripe_account=account_id)
    return {
        "available": [
            {"amount": b.amount, "currency": b.currency} for b in balance.available
        ],
        "pending": [
            {"amount": b.amount, "currency": b.currency} for b in balance.pending
        ],
        "mode": "live",
    }


async def create_marketplace_checkout(
    customer_email: str,
    customer_id: str | None,
    agent_name: str,
    price_cents: int,
    creator_connect_id: str,
    agent_id: str,
    success_url: str,
    cancel_url: str,
) -> dict:
    platform_fee = int(price_cents * PLATFORM_FEE_PERCENT / 100)

    if is_mock_mode():
        return {
            "id": "cs_mock_agent_{}".format(agent_id[:8]),
            "url": "{}&session_id=cs_mock_agent_{}".format(success_url, agent_id[:8]),
            "mode": "mock",
            "platform_fee": platform_fee,
            "creator_amount": price_cents - platform_fee,
        }

    params: dict = {
        "mode": "subscription",
        "line_items": [
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": price_cents,
                    "recurring": {"interval": "month"},
                    "product_data": {"name": "Agent: {}".format(agent_name)},
                },
                "quantity": 1,
            }
        ],
        "subscription_data": {
            "application_fee_percent": PLATFORM_FEE_PERCENT,
            "transfer_data": {"destination": creator_connect_id},
        },
        "success_url": success_url + "&session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": cancel_url,
        "metadata": {"agent_id": agent_id, "type": "marketplace_agent"},
    }

    if customer_id:
        params["customer"] = customer_id
    else:
        params["customer_email"] = customer_email

    session = stripe.checkout.Session.create(**params)
    return {
        "id": session.id,
        "url": session.url,
        "mode": "live",
    }
