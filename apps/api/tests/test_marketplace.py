from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient) -> str:
    email = f"mkt-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "securepass123",
            "full_name": "Marketplace Tester",
        },
    )
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_and_publish(client: AsyncClient, token: str) -> str:
    create_resp = await client.post(
        "/api/agents",
        json={
            "name": f"Published Agent {uuid.uuid4().hex[:6]}",
            "system_prompt": "I am published.",
            "description": "A marketplace agent",
        },
        headers=_auth(token),
    )
    agent_id = create_resp.json()["data"]["id"]
    await client.post(f"/api/agents/{agent_id}/publish", headers=_auth(token))
    await client.post(
        f"/api/agents/{agent_id}/review",
        json={"action": "approve"},
        headers=_auth(token),
    )
    return agent_id


@pytest.mark.asyncio
async def test_browse_marketplace(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/marketplace", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["data"], list)
    assert "total" in body["meta"]


@pytest.mark.asyncio
async def test_marketplace_search(client: AsyncClient):
    token = await _register(client)
    resp = await client.get(
        "/api/marketplace?search=nonexistent-agent-xyz", headers=_auth(token)
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_marketplace_pagination(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/marketplace?page=1&per_page=5", headers=_auth(token))
    assert resp.status_code == 200
    meta = resp.json()["meta"]
    assert meta["page"] == 1
    assert meta["per_page"] == 5


@pytest.mark.asyncio
async def test_marketplace_detail(client: AsyncClient):
    token = await _register(client)
    agent_id = await _create_and_publish(client, token)

    resp = await client.get(f"/api/marketplace/{agent_id}", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "name" in data
    assert "system_prompt" in data


@pytest.mark.asyncio
async def test_marketplace_detail_not_found(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/marketplace/{fake_id}", headers=_auth(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_subscribe_to_agent(client: AsyncClient):
    token_publisher = await _register(client)
    agent_id = await _create_and_publish(client, token_publisher)

    token_subscriber = await _register(client)
    resp = await client.post(
        f"/api/marketplace/subscribe/{agent_id}",
        json={
            "plan_type": "free",
        },
        headers=_auth(token_subscriber),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["agent_id"] == agent_id
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_subscribe_duplicate(client: AsyncClient):
    token_publisher = await _register(client)
    agent_id = await _create_and_publish(client, token_publisher)

    token_subscriber = await _register(client)
    await client.post(
        f"/api/marketplace/subscribe/{agent_id}",
        json={
            "plan_type": "free",
        },
        headers=_auth(token_subscriber),
    )

    resp = await client.post(
        f"/api/marketplace/subscribe/{agent_id}",
        json={
            "plan_type": "free",
        },
        headers=_auth(token_subscriber),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_marketplace_requires_auth(client: AsyncClient):
    resp = await client.get("/api/marketplace")
    assert resp.status_code == 401
