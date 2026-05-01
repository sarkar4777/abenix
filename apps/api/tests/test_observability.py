from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_ready_returns_checks(client: AsyncClient):
    resp = await client.get("/api/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert "postgres" in body
    assert "redis" in body


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus(client: AsyncClient):
    resp = await client.get("/api/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    text = resp.text
    assert "abenix_http_requests_total" in text


@pytest.mark.asyncio
async def test_request_id_header_returned(client: AsyncClient):
    resp = await client.get("/api/health")
    assert "x-request-id" in resp.headers


@pytest.mark.asyncio
async def test_request_id_passthrough(client: AsyncClient):
    custom_id = "test-trace-id-12345"
    resp = await client.get("/api/health", headers={"X-Request-ID": custom_id})
    assert resp.headers["x-request-id"] == custom_id


@pytest.mark.asyncio
async def test_metrics_not_rate_limited(client: AsyncClient):
    for _ in range(5):
        resp = await client.get("/api/metrics")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_ready_not_rate_limited(client: AsyncClient):
    for _ in range(5):
        resp = await client.get("/api/health/ready")
        assert resp.status_code == 200
