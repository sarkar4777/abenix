from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient) -> str:
    email = f"mcp-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "securepass123",
            "full_name": "MCP Tester",
        },
    )
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_mcp_connection(client: AsyncClient):
    token = await _register(client)
    resp = await client.post(
        "/api/mcp/connections",
        json={
            "server_name": "Test MCP Server",
            "server_url": "http://localhost:9999/mcp",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["server_name"] == "Test MCP Server"
    assert data["auth_type"] == "none"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_mcp_connections(client: AsyncClient):
    token = await _register(client)
    await client.post(
        "/api/mcp/connections",
        json={
            "server_name": "MCP One",
            "server_url": "http://localhost:9991/mcp",
        },
        headers=_auth(token),
    )
    await client.post(
        "/api/mcp/connections",
        json={
            "server_name": "MCP Two",
            "server_url": "http://localhost:9992/mcp",
        },
        headers=_auth(token),
    )

    resp = await client.get("/api/mcp/connections", headers=_auth(token))
    assert resp.status_code == 200
    assert len(resp.json()["data"]) >= 2


@pytest.mark.asyncio
async def test_get_mcp_connection(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/mcp/connections",
        json={
            "server_name": "Get MCP",
            "server_url": "http://localhost:9993/mcp",
        },
        headers=_auth(token),
    )
    conn_id = create_resp.json()["data"]["id"]

    resp = await client.get(f"/api/mcp/connections/{conn_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["server_name"] == "Get MCP"


@pytest.mark.asyncio
async def test_update_mcp_connection(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/mcp/connections",
        json={
            "server_name": "Old Name",
            "server_url": "http://localhost:9994/mcp",
        },
        headers=_auth(token),
    )
    conn_id = create_resp.json()["data"]["id"]

    resp = await client.put(
        f"/api/mcp/connections/{conn_id}",
        json={
            "server_name": "New Name",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["server_name"] == "New Name"


@pytest.mark.asyncio
async def test_delete_mcp_connection(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/mcp/connections",
        json={
            "server_name": "Delete MCP",
            "server_url": "http://localhost:9995/mcp",
        },
        headers=_auth(token),
    )
    conn_id = create_resp.json()["data"]["id"]

    resp = await client.delete(f"/api/mcp/connections/{conn_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_mcp_connection_not_found(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/mcp/connections/{fake_id}", headers=_auth(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mcp_cross_tenant_isolation(client: AsyncClient):
    token_a = await _register(client)
    token_b = await _register(client)

    create_resp = await client.post(
        "/api/mcp/connections",
        json={
            "server_name": "Tenant A MCP",
            "server_url": "http://localhost:9996/mcp",
        },
        headers=_auth(token_a),
    )
    conn_id = create_resp.json()["data"]["id"]

    resp = await client.get(f"/api/mcp/connections/{conn_id}", headers=_auth(token_b))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mcp_requires_auth(client: AsyncClient):
    resp = await client.get("/api/mcp/connections")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mcp_registry(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/mcp/registry", headers=_auth(token))
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


@pytest.mark.asyncio
async def test_agent_tools_list_empty(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/agents",
        json={
            "name": "No Tools Agent",
            "system_prompt": "None.",
        },
        headers=_auth(token),
    )
    agent_id = create_resp.json()["data"]["id"]

    resp = await client.get(f"/api/mcp/agents/{agent_id}/tools", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"] == []
