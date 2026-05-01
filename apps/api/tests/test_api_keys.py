from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient) -> str:
    email = f"keys-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post("/api/auth/register", json={
        "email": email,
        "password": "securepass123",
        "full_name": "Keys Tester",
    })
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_api_key(client: AsyncClient):
    token = await _register(client)
    resp = await client.post("/api/api-keys", json={
        "name": "Test Key",
    }, headers=_auth(token))
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["name"] == "Test Key"
    assert "raw_key" in data
    assert data["raw_key"].startswith("af_")
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_list_api_keys(client: AsyncClient):
    token = await _register(client)
    await client.post("/api/api-keys", json={"name": "Key 1"}, headers=_auth(token))
    await client.post("/api/api-keys", json={"name": "Key 2"}, headers=_auth(token))

    resp = await client.get("/api/api-keys", headers=_auth(token))
    assert resp.status_code == 200
    keys = resp.json()["data"]
    assert len(keys) >= 2
    for key in keys:
        assert "raw_key" not in key


@pytest.mark.asyncio
async def test_revoke_api_key(client: AsyncClient):
    token = await _register(client)
    create_resp = await client.post("/api/api-keys", json={"name": "Revoke Me"}, headers=_auth(token))
    key_id = create_resp.json()["data"]["id"]

    resp = await client.delete(f"/api/api-keys/{key_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "revoked"


@pytest.mark.asyncio
async def test_revoke_nonexistent_key(client: AsyncClient):
    token = await _register(client)
    fake_id = str(uuid.uuid4())
    resp = await client.delete(f"/api/api-keys/{fake_id}", headers=_auth(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_keys_cross_tenant_isolation(client: AsyncClient):
    token_a = await _register(client)
    token_b = await _register(client)

    create_resp = await client.post("/api/api-keys", json={"name": "Tenant A Key"}, headers=_auth(token_a))
    key_id = create_resp.json()["data"]["id"]

    resp = await client.delete(f"/api/api-keys/{key_id}", headers=_auth(token_b))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_keys_requires_auth(client: AsyncClient):
    resp = await client.get("/api/api-keys")
    assert resp.status_code == 401


# --- X-API-Key header authentication tests ---


@pytest.mark.asyncio
async def test_api_key_auth_via_header(client: AsyncClient):
    """API key in X-API-Key header should authenticate the request."""
    token = await _register(client)
    create_resp = await client.post(
        "/api/api-keys", json={"name": "Auth Key"}, headers=_auth(token)
    )
    raw_key = create_resp.json()["data"]["raw_key"]

    # Use the API key to call a protected endpoint (list api keys)
    resp = await client.get("/api/api-keys", headers={"X-API-Key": raw_key})
    assert resp.status_code == 200
    keys = resp.json()["data"]
    assert any(k["name"] == "Auth Key" for k in keys)


@pytest.mark.asyncio
async def test_api_key_auth_invalid_key(client: AsyncClient):
    """Invalid API key should return 401."""
    resp = await client.get("/api/api-keys", headers={"X-API-Key": "af_invalidkey1234567890"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_key_auth_revoked_key(client: AsyncClient):
    """Revoked API key should not authenticate."""
    token = await _register(client)
    create_resp = await client.post(
        "/api/api-keys", json={"name": "Revoke Auth Test"}, headers=_auth(token)
    )
    raw_key = create_resp.json()["data"]["raw_key"]
    key_id = create_resp.json()["data"]["id"]

    # Revoke the key
    await client.delete(f"/api/api-keys/{key_id}", headers=_auth(token))

    # Try to use the revoked key
    resp = await client.get("/api/api-keys", headers={"X-API-Key": raw_key})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_key_auth_updates_last_used(client: AsyncClient):
    """Using an API key should update its last_used_at timestamp."""
    token = await _register(client)
    create_resp = await client.post(
        "/api/api-keys", json={"name": "Last Used Key"}, headers=_auth(token)
    )
    raw_key = create_resp.json()["data"]["raw_key"]

    # Initially last_used_at is None
    key_data = create_resp.json()["data"]
    assert key_data["last_used_at"] is None

    # Use the key
    await client.get("/api/api-keys", headers={"X-API-Key": raw_key})

    # Check last_used_at is now set (list via bearer to see all keys)
    resp = await client.get("/api/api-keys", headers=_auth(token))
    keys = resp.json()["data"]
    used_key = next(k for k in keys if k["name"] == "Last Used Key")
    assert used_key["last_used_at"] is not None


@pytest.mark.asyncio
async def test_api_key_tenant_isolation(client: AsyncClient):
    """API key from tenant A should not see tenant B's agents."""
    token_a = await _register(client)
    token_b = await _register(client)

    # Create API key for tenant A
    create_resp = await client.post(
        "/api/api-keys", json={"name": "Tenant A SDK Key"}, headers=_auth(token_a)
    )
    raw_key_a = create_resp.json()["data"]["raw_key"]

    # Create an API key for tenant B using their bearer token
    await client.post(
        "/api/api-keys", json={"name": "Tenant B Key"}, headers=_auth(token_b)
    )

    # Tenant A's API key should only see tenant A's keys
    resp = await client.get("/api/api-keys", headers={"X-API-Key": raw_key_a})
    keys = resp.json()["data"]
    assert all(k["name"] != "Tenant B Key" for k in keys)
