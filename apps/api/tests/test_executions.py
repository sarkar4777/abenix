"""Tests for execution monitoring, HITL approvals, and replay endpoints."""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient) -> str:
    email = f"exec-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post("/api/auth/register", json={
        "email": email,
        "password": "securepass123",
        "full_name": "Exec Tester",
    })
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_live_executions_empty(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/executions/live", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_live_execution_not_found(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/executions/live/{fake_id}", headers=_auth(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_execution_tree_not_found(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/executions/tree/{fake_id}", headers=_auth(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_executions_empty(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/executions", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert "meta" in data


@pytest.mark.asyncio
async def test_execution_not_found(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/executions/{fake_id}", headers=_auth(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pending_approvals_empty(client: AsyncClient):
    token = await _register(client)
    resp = await client.get("/api/executions/approvals", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_approve_gate_invalid_decision(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.post(
        f"/api/executions/{fake_id}/approve",
        params={"gate_id": "gate-1"},
        json={"decision": "maybe", "comment": ""},
        headers=_auth(token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_approve_gate_success(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.post(
        f"/api/executions/{fake_id}/approve",
        params={"gate_id": "gate-1"},
        json={"decision": "approved", "comment": "LGTM"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["decision"] == "approved"
    assert data["gate_id"] == "gate-1"


@pytest.mark.asyncio
async def test_reject_gate_success(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.post(
        f"/api/executions/{fake_id}/approve",
        params={"gate_id": "gate-2"},
        json={"decision": "rejected", "comment": "Not ready"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["decision"] == "rejected"


@pytest.mark.asyncio
async def test_replay_execution_not_found(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/executions/{fake_id}/replay", headers=_auth(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_child_executions_empty(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/executions/{fake_id}/children", headers=_auth(token))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_executions_requires_auth(client: AsyncClient):
    resp = await client.get("/api/executions")
    assert resp.status_code == 401

    resp = await client.get("/api/executions/live")
    assert resp.status_code == 401

    resp = await client.get("/api/executions/approvals")
    assert resp.status_code == 401
