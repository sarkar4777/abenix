from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient) -> tuple[str, str]:
    email = f"team-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "securepass123",
            "full_name": "Team Tester",
        },
    )
    data = resp.json()["data"]
    return data["access_token"], data["user"]["id"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_members(client: AsyncClient):
    token, _ = await _register(client)
    resp = await client.get("/api/team/members", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "members" in data
    assert "pending_invites" in data
    assert len(data["members"]) >= 1


@pytest.mark.asyncio
async def test_invite_member(client: AsyncClient):
    token, _ = await _register(client)
    resp = await client.post(
        "/api/team/invite",
        json={
            "email": f"invited-{uuid.uuid4().hex[:8]}@test.com",
            "role": "creator",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["role"] == "creator"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_invite_duplicate_email(client: AsyncClient):
    token, _ = await _register(client)
    invite_email = f"dupe-invite-{uuid.uuid4().hex[:8]}@test.com"
    await client.post(
        "/api/team/invite",
        json={
            "email": invite_email,
            "role": "user",
        },
        headers=_auth(token),
    )

    resp = await client.post(
        "/api/team/invite",
        json={
            "email": invite_email,
            "role": "user",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_invite(client: AsyncClient):
    token, _ = await _register(client)
    invite_resp = await client.post(
        "/api/team/invite",
        json={
            "email": f"cancel-{uuid.uuid4().hex[:8]}@test.com",
            "role": "user",
        },
        headers=_auth(token),
    )
    invite_id = invite_resp.json()["data"]["id"]

    resp = await client.delete(f"/api/team/invites/{invite_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cannot_change_own_role(client: AsyncClient):
    token, user_id = await _register(client)
    resp = await client.put(
        f"/api/team/members/{user_id}/role",
        json={
            "role": "user",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cannot_remove_self(client: AsyncClient):
    token, user_id = await _register(client)
    resp = await client.delete(f"/api/team/members/{user_id}", headers=_auth(token))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_team_requires_auth(client: AsyncClient):
    resp = await client.get("/api/team/members")
    assert resp.status_code == 401
