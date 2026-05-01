from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient) -> str:
    email = f"notif-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post("/api/auth/register", json={
        "email": email,
        "password": "securepass123",
        "full_name": "Notification Tester",
    })
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_notifications_empty(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/notifications", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["data"], list)
    assert body["meta"]["unread"] == 0


@pytest.mark.asyncio
async def test_unread_count(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/notifications/unread-count", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["unread"] == 0


@pytest.mark.asyncio
async def test_mark_read_not_found(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.post(f"/api/notifications/{fake_id}/read", headers=_auth(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mark_all_read(client: AsyncClient):
    token = await _register(client)
    resp = await client.post("/api/notifications/read-all", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["marked_all_read"] is True


@pytest.mark.asyncio
async def test_notifications_require_auth(client: AsyncClient):
    resp = await client.get("/api/notifications")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_notification_pagination(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/notifications?page=1&per_page=5", headers=_auth(token))
    assert resp.status_code == 200
    meta = resp.json()["meta"]
    assert meta["page"] == 1
    assert meta["per_page"] == 5


@pytest.mark.asyncio
async def test_live_stats_endpoint(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/analytics/live-stats", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "active_executions" in data
    assert "today_executions" in data
    assert "success_rate" in data
    assert "total_agents" in data
    assert "today_cost" in data


@pytest.mark.asyncio
async def test_live_stats_requires_auth(client: AsyncClient):
    resp = await client.get("/api/analytics/live-stats")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_subscribe_creates_notification(client: AsyncClient):
    publisher_token = await _register(client)

    create_resp = await client.post("/api/agents", json={
        "name": f"Notif Agent {uuid.uuid4().hex[:6]}",
        "system_prompt": "Test notifications.",
        "description": "Agent for notification test",
    }, headers=_auth(publisher_token))
    agent_id = create_resp.json()["data"]["id"]

    await client.post(f"/api/agents/{agent_id}/publish", headers=_auth(publisher_token))
    await client.post(f"/api/agents/{agent_id}/review", json={
        "action": "approve",
    }, headers=_auth(publisher_token))

    subscriber_token = await _register(client)
    sub_resp = await client.post(f"/api/marketplace/subscribe/{agent_id}", json={
        "plan_type": "free",
    }, headers=_auth(subscriber_token))
    assert sub_resp.status_code == 201

    resp = await client.get("/api/notifications", headers=_auth(publisher_token))
    assert resp.status_code == 200
    notifications = resp.json()["data"]
    sub_notifs = [n for n in notifications if n["type"] == "new_subscriber"]
    assert len(sub_notifs) >= 1
    assert "subscribed" in sub_notifs[0]["message"]


@pytest.mark.asyncio
async def test_mark_read_works(client: AsyncClient):
    publisher_token = await _register(client)

    create_resp = await client.post("/api/agents", json={
        "name": f"Read Agent {uuid.uuid4().hex[:6]}",
        "system_prompt": "Test mark read.",
        "description": "Agent for read test",
    }, headers=_auth(publisher_token))
    agent_id = create_resp.json()["data"]["id"]

    await client.post(f"/api/agents/{agent_id}/publish", headers=_auth(publisher_token))
    await client.post(f"/api/agents/{agent_id}/review", json={
        "action": "approve",
    }, headers=_auth(publisher_token))

    subscriber_token = await _register(client)
    await client.post(f"/api/marketplace/subscribe/{agent_id}", json={
        "plan_type": "free",
    }, headers=_auth(subscriber_token))

    list_resp = await client.get("/api/notifications", headers=_auth(publisher_token))
    notifications = list_resp.json()["data"]
    assert len(notifications) > 0

    notif_id = notifications[0]["id"]
    read_resp = await client.post(f"/api/notifications/{notif_id}/read", headers=_auth(publisher_token))
    assert read_resp.status_code == 200
    assert read_resp.json()["data"]["is_read"] is True

    count_resp = await client.get("/api/notifications/unread-count", headers=_auth(publisher_token))
    assert count_resp.json()["data"]["unread"] == 0
