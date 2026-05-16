from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient) -> str:
    email = f"analytics-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "securepass123",
            "full_name": "Analytics Tester",
        },
    )
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_analytics_overview(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/analytics/overview", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "total_executions" in data
    assert "success_rate" in data
    assert "total_cost" in data
    assert "period" in data


@pytest.mark.asyncio
async def test_analytics_overview_periods(client: AsyncClient):
    token = await _register(client)
    for period in ("7d", "30d", "90d"):
        resp = await client.get(
            f"/api/analytics/overview?period={period}", headers=_auth(token)
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["period"] == period


@pytest.mark.asyncio
async def test_analytics_executions(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/analytics/executions", headers=_auth(token))
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


@pytest.mark.asyncio
async def test_analytics_tokens(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/analytics/tokens", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "by_model" in data
    assert "daily_tokens" in data


@pytest.mark.asyncio
async def test_analytics_costs(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/analytics/costs", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "by_agent" in data
    assert "daily_costs" in data


@pytest.mark.asyncio
async def test_analytics_requires_auth(client: AsyncClient):
    resp = await client.get("/api/analytics/overview")
    assert resp.status_code == 401
