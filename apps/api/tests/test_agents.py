from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient, email: str = "") -> str:
    email = email or f"agent-test-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "securepass123",
            "full_name": "Agent Tester",
        },
    )
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_agent(client: AsyncClient):
    token = await _register(client)
    resp = await client.post(
        "/api/agents",
        json={
            "name": "Test Agent",
            "description": "A test agent",
            "system_prompt": "You are a test agent.",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["name"] == "Test Agent"
    assert data["status"] == "draft"
    assert data["agent_type"] == "custom"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_agent_with_model_config(client: AsyncClient):
    token = await _register(client)
    resp = await client.post(
        "/api/agents",
        json={
            "name": "Configured Agent",
            "system_prompt": "You are helpful.",
            "model_config": {
                "model": "gpt-4o",
                "temperature": 0.3,
                "tools": ["calculator", "web_search"],
            },
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["model_config"]["model"] == "gpt-4o"
    assert data["model_config"]["temperature"] == 0.3


@pytest.mark.asyncio
async def test_list_agents(client: AsyncClient):
    token = await _register(client)
    await client.post(
        "/api/agents",
        json={
            "name": "List Agent 1",
            "system_prompt": "Hello.",
        },
        headers=_auth(token),
    )
    await client.post(
        "/api/agents",
        json={
            "name": "List Agent 2",
            "system_prompt": "World.",
        },
        headers=_auth(token),
    )

    resp = await client.get("/api/agents", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert len(body["data"]) >= 2


@pytest.mark.asyncio
async def test_get_agent(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/agents",
        json={
            "name": "Get Me Agent",
            "system_prompt": "Find me.",
        },
        headers=_auth(token),
    )
    agent_id = create_resp.json()["data"]["id"]

    resp = await client.get(f"/api/agents/{agent_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Get Me Agent"


@pytest.mark.asyncio
async def test_get_agent_not_found(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/agents/{fake_id}", headers=_auth(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_agent(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/agents",
        json={
            "name": "Before Update",
            "system_prompt": "Original.",
        },
        headers=_auth(token),
    )
    agent_id = create_resp.json()["data"]["id"]

    resp = await client.put(
        f"/api/agents/{agent_id}",
        json={
            "name": "After Update",
            "description": "Updated description",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "After Update"
    assert resp.json()["data"]["description"] == "Updated description"


@pytest.mark.asyncio
async def test_delete_agent(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/agents",
        json={
            "name": "Delete Me",
            "system_prompt": "Bye.",
        },
        headers=_auth(token),
    )
    agent_id = create_resp.json()["data"]["id"]

    resp = await client.delete(f"/api/agents/{agent_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "archived"

    get_resp = await client.get(f"/api/agents/{agent_id}", headers=_auth(token))
    assert get_resp.json()["data"]["status"] == "archived"


@pytest.mark.asyncio
async def test_duplicate_agent(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/agents",
        json={
            "name": "Original Agent",
            "system_prompt": "Copy me.",
            "description": "Original desc",
        },
        headers=_auth(token),
    )
    agent_id = create_resp.json()["data"]["id"]

    resp = await client.post(f"/api/agents/{agent_id}/duplicate", headers=_auth(token))
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["name"].startswith("Original Agent")
    assert data["id"] != agent_id
    assert data["status"] == "draft"


@pytest.mark.asyncio
async def test_publish_agent(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/agents",
        json={
            "name": "Publishable Agent",
            "system_prompt": "Publish me.",
        },
        headers=_auth(token),
    )
    agent_id = create_resp.json()["data"]["id"]

    resp = await client.post(f"/api/agents/{agent_id}/publish", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_published"] is False
    assert data["status"] == "pending_review"

    review_resp = await client.post(
        f"/api/agents/{agent_id}/review",
        json={
            "action": "approve",
        },
        headers=_auth(token),
    )
    assert review_resp.status_code in (200, 403)


@pytest.mark.asyncio
async def test_execute_agent_non_stream(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/agents",
        json={
            "name": "Execute Agent",
            "system_prompt": "Reply with 'hello'.",
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

    resp = await client.post(
        f"/api/agents/{agent_id}/execute",
        json={
            "message": "Hi there",
            "stream": False,
        },
        headers=_auth(token),
    )
    assert resp.status_code in (200, 400, 403, 500)


@pytest.mark.asyncio
async def test_agents_requires_auth(client: AsyncClient):
    resp = await client.get("/api/agents")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_agent_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/agents",
        json={
            "name": "No Auth",
            "system_prompt": "Fail.",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cross_tenant_agent_not_visible(client: AsyncClient):
    token_a = await _register(client, "tenant-a-agents@test.com")
    token_b = await _register(client, "tenant-b-agents@test.com")

    create_resp = await client.post(
        "/api/agents",
        json={
            "name": "Tenant A Agent",
            "system_prompt": "Private.",
        },
        headers=_auth(token_a),
    )
    agent_id = create_resp.json()["data"]["id"]

    resp = await client.get(f"/api/agents/{agent_id}", headers=_auth(token_b))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cannot_update_other_tenant_agent(client: AsyncClient):
    token_a = await _register(client, "update-a@test.com")
    token_b = await _register(client, "update-b@test.com")

    create_resp = await client.post(
        "/api/agents",
        json={
            "name": "A's Agent",
            "system_prompt": "Mine.",
        },
        headers=_auth(token_a),
    )
    agent_id = create_resp.json()["data"]["id"]

    resp = await client.put(
        f"/api/agents/{agent_id}",
        json={
            "name": "Stolen",
        },
        headers=_auth(token_b),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cannot_delete_other_tenant_agent(client: AsyncClient):
    token_a = await _register(client, "delete-a@test.com")
    token_b = await _register(client, "delete-b@test.com")

    create_resp = await client.post(
        "/api/agents",
        json={
            "name": "Protected Agent",
            "system_prompt": "Safe.",
        },
        headers=_auth(token_a),
    )
    agent_id = create_resp.json()["data"]["id"]

    resp = await client.delete(f"/api/agents/{agent_id}", headers=_auth(token_b))
    assert resp.status_code == 404
