import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    resp = await client.post("/api/auth/register", json={
        "email": "test@example.com",
        "password": "securepass123",
        "full_name": "Test User",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "test@example.com"
    assert data["user"]["full_name"] == "Test User"
    assert data["user"]["role"] == "admin"


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "email": "dupe@example.com",
        "password": "securepass123",
        "full_name": "First User",
    })
    resp = await client.post("/api/auth/register", json={
        "email": "dupe@example.com",
        "password": "securepass123",
        "full_name": "Second User",
    })
    assert resp.status_code == 409
    body = resp.json()
    assert body["data"] is None
    assert body["error"]["message"] == "Email already registered"


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "email": "login@example.com",
        "password": "mypassword",
        "full_name": "Login User",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "login@example.com",
        "password": "mypassword",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["email"] == "login@example.com"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "email": "wrongpw@example.com",
        "password": "correctpass",
        "full_name": "Wrong PW User",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "wrongpw@example.com",
        "password": "wrongpass",
    })
    assert resp.status_code == 401
    body = resp.json()
    assert body["data"] is None
    assert body["error"]["message"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_me_authenticated(client: AsyncClient):
    reg_resp = await client.post("/api/auth/register", json={
        "email": "me@example.com",
        "password": "mypassword",
        "full_name": "Me User",
    })
    token = reg_resp.json()["data"]["access_token"]

    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert body["data"]["user"]["email"] == "me@example.com"


@pytest.mark.asyncio
async def test_me_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient):
    reg_resp = await client.post("/api/auth/register", json={
        "email": "refresh@example.com",
        "password": "mypassword",
        "full_name": "Refresh User",
    })
    refresh_token = reg_resp.json()["data"]["refresh_token"]

    resp = await client.post("/api/auth/refresh", json={
        "refresh_token": refresh_token,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert "access_token" in body["data"]
