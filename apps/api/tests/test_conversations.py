from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient) -> str:
    email = f"conv-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post("/api/auth/register", json={
        "email": email,
        "password": "securepass123",
        "full_name": "Conv Tester",
    })
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_conversations_empty(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/conversations", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["data"], list)
    assert body["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_create_conversation(client: AsyncClient):
    token = await _register(client)
    resp = await client.post("/api/conversations", json={
        "title": "My First Chat",
    }, headers=_auth(token))
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["title"] == "My First Chat"
    assert data["message_count"] == 0
    assert data["is_shared"] is False


@pytest.mark.asyncio
async def test_get_conversation_with_messages(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post("/api/conversations", json={
        "title": "Test Chat",
    }, headers=_auth(token))
    conv_id = create_resp.json()["data"]["id"]

    await client.post(f"/api/conversations/{conv_id}/messages", json={
        "role": "user",
        "content": "Hello there",
    }, headers=_auth(token))
    await client.post(f"/api/conversations/{conv_id}/messages", json={
        "role": "assistant",
        "content": "Hi! How can I help?",
        "input_tokens": 10,
        "output_tokens": 15,
        "cost": 0.001,
    }, headers=_auth(token))

    resp = await client.get(f"/api/conversations/{conv_id}", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["messages"]) == 2
    assert data["message_count"] == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_update_conversation_title(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post("/api/conversations", json={
        "title": "Old Title",
    }, headers=_auth(token))
    conv_id = create_resp.json()["data"]["id"]

    resp = await client.put(f"/api/conversations/{conv_id}", json={
        "title": "New Title",
    }, headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "New Title"


@pytest.mark.asyncio
async def test_delete_conversation(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post("/api/conversations", json={
        "title": "Delete Me",
    }, headers=_auth(token))
    conv_id = create_resp.json()["data"]["id"]

    resp = await client.delete(f"/api/conversations/{conv_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True

    get_resp = await client.get(f"/api/conversations/{conv_id}", headers=_auth(token))
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_share_conversation(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post("/api/conversations", json={
        "title": "Shareable Chat",
    }, headers=_auth(token))
    conv_id = create_resp.json()["data"]["id"]

    await client.post(f"/api/conversations/{conv_id}/messages", json={
        "role": "user",
        "content": "What is AI?",
    }, headers=_auth(token))

    share_resp = await client.post(
        f"/api/conversations/{conv_id}/share", headers=_auth(token)
    )
    assert share_resp.status_code == 200
    share_data = share_resp.json()["data"]
    assert "share_token" in share_data
    assert "share_url" in share_data

    shared_resp = await client.get(
        f"/api/conversations/shared/{share_data['share_token']}"
    )
    assert shared_resp.status_code == 200
    shared_data = shared_resp.json()["data"]
    assert shared_data["title"] == "Shareable Chat"
    assert len(shared_data["messages"]) == 1


@pytest.mark.asyncio
async def test_unshare_conversation(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post("/api/conversations", json={
        "title": "Unshare Me",
    }, headers=_auth(token))
    conv_id = create_resp.json()["data"]["id"]

    share_resp = await client.post(
        f"/api/conversations/{conv_id}/share", headers=_auth(token)
    )
    share_token = share_resp.json()["data"]["share_token"]

    unshare_resp = await client.delete(
        f"/api/conversations/{conv_id}/share", headers=_auth(token)
    )
    assert unshare_resp.status_code == 200

    shared_resp = await client.get(f"/api/conversations/shared/{share_token}")
    assert shared_resp.status_code == 404


@pytest.mark.asyncio
async def test_conversations_require_auth(client: AsyncClient):
    resp = await client.get("/api/conversations")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_save_message_with_blocks(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post("/api/conversations", json={
        "title": "Blocks Chat",
    }, headers=_auth(token))
    conv_id = create_resp.json()["data"]["id"]

    blocks = [
        {"type": "text", "content": "Here is the answer:"},
        {"type": "tool", "name": "search", "arguments": {"q": "AI"}},
    ]
    resp = await client.post(f"/api/conversations/{conv_id}/messages", json={
        "role": "assistant",
        "content": "Here is the answer:",
        "blocks": blocks,
        "input_tokens": 50,
        "output_tokens": 100,
        "cost": 0.005,
        "model_used": "claude-sonnet-4-5-20250929",
    }, headers=_auth(token))
    assert resp.status_code == 201
    msg = resp.json()["data"]
    assert msg["blocks"] == blocks
    assert msg["model_used"] == "claude-sonnet-4-5-20250929"


@pytest.mark.asyncio
async def test_conversation_pagination(client: AsyncClient):
    token = await _register(client)

    for i in range(3):
        await client.post("/api/conversations", json={
            "title": f"Chat {i}",
        }, headers=_auth(token))

    resp = await client.get(
        "/api/conversations?page=1&per_page=2", headers=_auth(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["meta"]["total"] == 3
    assert body["meta"]["page"] == 1
    assert body["meta"]["per_page"] == 2


@pytest.mark.asyncio
async def test_conversation_not_found(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/conversations/{fake_id}", headers=_auth(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_message_updates_conversation_stats(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post("/api/conversations", json={
        "title": "Stats Chat",
    }, headers=_auth(token))
    conv_id = create_resp.json()["data"]["id"]

    await client.post(f"/api/conversations/{conv_id}/messages", json={
        "role": "user",
        "content": "Hello",
    }, headers=_auth(token))
    await client.post(f"/api/conversations/{conv_id}/messages", json={
        "role": "assistant",
        "content": "Hi",
        "input_tokens": 10,
        "output_tokens": 20,
        "cost": 0.002,
    }, headers=_auth(token))

    resp = await client.get(f"/api/conversations/{conv_id}", headers=_auth(token))
    data = resp.json()["data"]
    assert data["message_count"] == 2
    assert data["total_tokens"] == 30
    assert data["total_cost"] == 0.002
