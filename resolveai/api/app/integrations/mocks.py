"""Synthetic stubs for Stripe / Shopify / Zendesk / ShipEngine."""
from __future__ import annotations

import asyncio
import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any


def _seeded(key: str, salt: str) -> random.Random:
    """A stable PRNG seeded off (key, salt) pairs — deterministic per run."""
    digest = hashlib.sha256(f"{salt}:{key}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _StripeMock:
    """Fake Stripe — returns a synthetic charge id after a short delay."""

    async def refund(self, order_id: str, amount_usd: float) -> dict[str, Any]:
        rng = _seeded(order_id, "stripe-refund")
        await asyncio.sleep(rng.uniform(0.2, 0.5))
        charge_id = f"ch_mock_{rng.getrandbits(48):012x}"
        refund_id = f"re_mock_{rng.getrandbits(48):012x}"
        return {
            "provider": "stripe-mock",
            "refund_id": refund_id,
            "charge_id": charge_id,
            "order_id": order_id,
            "amount_usd": round(amount_usd, 2),
            "currency": "usd",
            "status": "succeeded",
            "created_at": _now_iso(),
        }


class _ShopifyMock:
    """Fake Shopify — deterministic order payload keyed off customer_id."""

    async def get_order(self, order_id: str) -> dict[str, Any]:
        rng = _seeded(order_id, "shopify-order")
        await asyncio.sleep(rng.uniform(0.1, 0.3))
        customer_ltv = round(rng.uniform(30.0, 4500.0), 2)
        line_count = rng.randint(1, 3)
        line_items = [
            {
                "sku": f"SKU-{rng.randint(1000, 9999)}",
                "title": rng.choice([
                    "Trail Runner 9", "Cloudwave Bluetooth", "Merino Base Layer",
                    "Alloy Commuter Bike", "Sous-vide Precision Cooker",
                ]),
                "quantity": rng.randint(1, 2),
                "price_usd": round(rng.uniform(19.0, 349.0), 2),
            }
            for _ in range(line_count)
        ]
        total = round(sum(it["price_usd"] * it["quantity"] for it in line_items), 2)
        return {
            "provider": "shopify-mock",
            "order_id": order_id,
            "status": rng.choice(["fulfilled", "partially_fulfilled", "in_transit", "delivered"]),
            "financial_status": rng.choice(["paid", "partially_refunded", "paid"]),
            "line_items": line_items,
            "total_usd": total,
            "customer": {
                "ltv_usd": customer_ltv,
                "tier": "vip" if customer_ltv > 2000 else "standard",
                "orders_count": rng.randint(1, 24),
            },
            "created_at": _now_iso(),
        }


class _ZendeskMock:
    """Fake Zendesk — mints a ticket id; no persistence."""

    async def create_ticket(self, subject: str, body: str) -> dict[str, Any]:
        rng = _seeded(f"{subject}|{body[:40]}", "zendesk-ticket")
        await asyncio.sleep(rng.uniform(0.1, 0.3))
        return {
            "provider": "zendesk-mock",
            "ticket_id": f"zd_mock_{rng.getrandbits(32):08x}",
            "subject": subject,
            "status": "open",
            "created_at": _now_iso(),
        }


class _ShipEngineMock:
    """Fake ShipEngine — returns a deterministic delivery timeline."""

    async def track(self, tracking_no: str) -> dict[str, Any]:
        rng = _seeded(tracking_no, "shipengine-track")
        await asyncio.sleep(rng.uniform(0.1, 0.3))
        today = datetime.now(timezone.utc)
        ship_date = today - timedelta(days=rng.randint(1, 6))
        events = [
            {"ts": (ship_date + timedelta(hours=1)).isoformat(),
             "status": "label_created", "location": "Portland, OR"},
            {"ts": (ship_date + timedelta(hours=6)).isoformat(),
             "status": "accepted_by_carrier", "location": "Portland, OR"},
            {"ts": (ship_date + timedelta(days=1)).isoformat(),
             "status": "in_transit", "location": "Denver, CO"},
            {"ts": (ship_date + timedelta(days=2)).isoformat(),
             "status": "out_for_delivery", "location": "Austin, TX"},
        ]
        delivered = rng.random() > 0.3
        if delivered:
            events.append({
                "ts": (ship_date + timedelta(days=2, hours=5)).isoformat(),
                "status": "delivered",
                "location": "Austin, TX",
            })
        return {
            "provider": "shipengine-mock",
            "tracking_no": tracking_no,
            "carrier": rng.choice(["usps", "ups", "fedex", "dhl"]),
            "status": "delivered" if delivered else "out_for_delivery",
            "estimated_delivery_at": (ship_date + timedelta(days=2)).isoformat(),
            "events": events,
        }


# Module-level singletons — routers import these directly.
stripe_mock = _StripeMock()
shopify_mock = _ShopifyMock()
zendesk_mock = _ZendeskMock()
shipengine_mock = _ShipEngineMock()
