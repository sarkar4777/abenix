from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient) -> str:
    email = f"kb-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "securepass123",
            "full_name": "KB Tester",
        },
    )
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_knowledge_base(client: AsyncClient):
    token = await _register(client)
    resp = await client.post(
        "/api/knowledge-bases",
        json={
            "name": "Test KB",
            "description": "A test knowledge base",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["name"] == "Test KB"
    assert data["chunk_size"] == 1000
    assert data["chunk_overlap"] == 200
    assert "id" in data


@pytest.mark.asyncio
async def test_create_kb_custom_chunking(client: AsyncClient):
    token = await _register(client)
    resp = await client.post(
        "/api/knowledge-bases",
        json={
            "name": "Custom Chunks KB",
            "chunk_size": 500,
            "chunk_overlap": 100,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["chunk_size"] == 500
    assert data["chunk_overlap"] == 100


@pytest.mark.asyncio
async def test_list_knowledge_bases(client: AsyncClient):
    token = await _register(client)
    await client.post(
        "/api/knowledge-bases",
        json={
            "name": "KB One",
        },
        headers=_auth(token),
    )
    await client.post(
        "/api/knowledge-bases",
        json={
            "name": "KB Two",
        },
        headers=_auth(token),
    )

    resp = await client.get("/api/knowledge-bases", headers=_auth(token))
    assert resp.status_code == 200
    assert len(resp.json()["data"]) >= 2


@pytest.mark.asyncio
async def test_get_knowledge_base(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/knowledge-bases",
        json={
            "name": "Get KB",
        },
        headers=_auth(token),
    )
    kb_id = create_resp.json()["data"]["id"]

    resp = await client.get(f"/api/knowledge-bases/{kb_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Get KB"


@pytest.mark.asyncio
async def test_update_knowledge_base(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/knowledge-bases",
        json={
            "name": "Old KB Name",
        },
        headers=_auth(token),
    )
    kb_id = create_resp.json()["data"]["id"]

    resp = await client.put(
        f"/api/knowledge-bases/{kb_id}",
        json={
            "name": "New KB Name",
            "description": "Updated",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "New KB Name"


@pytest.mark.asyncio
async def test_delete_knowledge_base(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/knowledge-bases",
        json={
            "name": "Delete KB",
        },
        headers=_auth(token),
    )
    kb_id = create_resp.json()["data"]["id"]

    resp = await client.delete(f"/api/knowledge-bases/{kb_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_kb_not_found(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/knowledge-bases/{fake_id}", headers=_auth(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_kb_cross_tenant_isolation(client: AsyncClient):
    token_a = await _register(client)
    token_b = await _register(client)

    create_resp = await client.post(
        "/api/knowledge-bases",
        json={
            "name": "Tenant A KB",
        },
        headers=_auth(token_a),
    )
    kb_id = create_resp.json()["data"]["id"]

    resp = await client.get(f"/api/knowledge-bases/{kb_id}", headers=_auth(token_b))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_kb_requires_auth(client: AsyncClient):
    resp = await client.get("/api/knowledge-bases")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_invalid_file_type(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/knowledge-bases",
        json={
            "name": "Upload KB",
        },
        headers=_auth(token),
    )
    kb_id = create_resp.json()["data"]["id"]

    resp = await client.post(
        f"/api/knowledge-bases/{kb_id}/upload",
        files={
            "file": ("test.exe", b"fake binary content", "application/octet-stream")
        },
        headers=_auth(token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_documents_empty(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post(
        "/api/knowledge-bases",
        json={
            "name": "Empty Docs KB",
        },
        headers=_auth(token),
    )
    kb_id = create_resp.json()["data"]["id"]

    resp = await client.get(
        f"/api/knowledge-bases/{kb_id}/documents", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []
