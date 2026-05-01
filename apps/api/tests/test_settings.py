from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient) -> str:
    email = f"settings-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post("/api/auth/register", json={
        "email": email,
        "password": "securepass123",
        "full_name": "Settings Tester",
    })
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_profile(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/settings/profile", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "email" in data
    assert "full_name" in data
    assert data["full_name"] == "Settings Tester"


@pytest.mark.asyncio
async def test_update_profile(client: AsyncClient):
    token = await _register(client)
    resp = await client.put("/api/settings/profile", json={
        "full_name": "Updated Name",
    }, headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["full_name"] == "Updated Name"


@pytest.mark.asyncio
async def test_change_password(client: AsyncClient):
    token = await _register(client)
    resp = await client.post("/api/settings/password", json={
        "current_password": "securepass123",
        "new_password": "newpassword456",
    }, headers=_auth(token))
    assert resp.status_code == 200
    assert "message" in resp.json()["data"]


@pytest.mark.asyncio
async def test_change_password_wrong_current(client: AsyncClient):
    token = await _register(client)
    resp = await client.post("/api/settings/password", json={
        "current_password": "wrongpassword",
        "new_password": "newpassword456",
    }, headers=_auth(token))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_change_password_too_short(client: AsyncClient):
    token = await _register(client)
    resp = await client.post("/api/settings/password", json={
        "current_password": "securepass123",
        "new_password": "short",
    }, headers=_auth(token))
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_get_notifications(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/settings/notifications", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "execution_complete" in data


@pytest.mark.asyncio
async def test_update_notifications(client: AsyncClient):
    token = await _register(client)
    resp = await client.put("/api/settings/notifications", json={
        "execution_complete": False,
        "weekly_report": True,
        "marketing": False,
    }, headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["execution_complete"] is False
    assert data["weekly_report"] is True


@pytest.mark.asyncio
async def test_get_activity_log(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/settings/activity", headers=_auth(token))
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


@pytest.mark.asyncio
async def test_get_sessions(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/settings/sessions", headers=_auth(token))
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


@pytest.mark.asyncio
async def test_settings_requires_auth(client: AsyncClient):
    resp = await client.get("/api/settings/profile")
    assert resp.status_code == 401
