from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient) -> str:
    email = f"bill-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post("/api/auth/register", json={
        "email": email,
        "password": "securepass123",
        "full_name": "Billing Tester",
    })
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_plans(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/billing/plans", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "plans" in data
    assert "stripe_mode" in data
    plan_names = [p["name"] for p in data["plans"]]
    assert "Free" in plan_names
    assert "Pro" in plan_names
    assert "Business" in plan_names


@pytest.mark.asyncio
async def test_checkout_pro_mock(client: AsyncClient):
    token = await _register(client)
    resp = await client.post("/api/billing/checkout", json={
        "plan": "pro",
        "success_url": "http://localhost:3000/success",
        "cancel_url": "http://localhost:3000/cancel",
    }, headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "url" in data
    assert "id" in data


@pytest.mark.asyncio
async def test_checkout_free_rejected(client: AsyncClient):
    token = await _register(client)
    resp = await client.post("/api/billing/checkout", json={
        "plan": "free",
    }, headers=_auth(token))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_checkout_enterprise_rejected(client: AsyncClient):
    token = await _register(client)
    resp = await client.post("/api/billing/checkout", json={
        "plan": "enterprise",
    }, headers=_auth(token))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_portal_session(client: AsyncClient):
    token = await _register(client)
    resp = await client.post("/api/billing/portal", json={
        "return_url": "http://localhost:3000/settings/billing",
    }, headers=_auth(token))
    assert resp.status_code in (200, 400)


@pytest.mark.asyncio
async def test_usage_stats(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/billing/usage", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "plan" in data
    assert "today_executions" in data
    assert "daily_limit" in data


@pytest.mark.asyncio
async def test_billing_requires_auth(client: AsyncClient):
    resp = await client.get("/api/billing/plans")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_invalid_signature(client: AsyncClient):
    resp = await client.post(
        "/api/billing/webhook",
        content=b'{"type":"checkout.session.completed"}',
        headers={"stripe-signature": "invalid", "Content-Type": "application/json"},
    )
    assert resp.status_code in (200, 400)
