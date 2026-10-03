from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from prometheus_client import REGISTRY

import app.core.rate_limit as rate_limit
from app.core.ip_whitelist import IPWhitelistMiddleware
from app.core.middleware import (
    MAX_REQUEST_BODY_BYTES,
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    TenantMiddleware,
)
from app.core.observability_middleware import ObservabilityMiddleware
from app.core.security import create_access_token

pytestmark = pytest.mark.asyncio


def _stack(app):
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(IPWhitelistMiddleware)
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(TenantMiddleware)
    return app


def _build_app() -> FastAPI:
    app = FastAPI(docs_url="/docs")

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.post("/echo")
    async def echo(request: Request):
        body = await request.body()
        return {"len": len(body)}

    @app.get("/tenant")
    async def tenant(request: Request):
        tid = request.state.tenant_id
        return {"tenant_id": str(tid) if tid else None}

    @app.get("/sse")
    async def sse():
        async def gen():
            for i in range(3):
                yield f"data: {i}\n\n"
                await asyncio.sleep(0)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return _stack(app)


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    monkeypatch.setattr(rate_limit, "_IS_LOCAL_DEV", True)
    monkeypatch.delenv("IP_WHITELIST", raising=False)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _counter(path: str, status: str) -> float:
    v = REGISTRY.get_sample_value(
        "abenix_http_requests_total",
        {"method": "GET", "path": path, "status": status},
    )
    return v or 0.0


async def test_security_headers_and_docs_csp_skip():
    async with _client(_build_app()) as c:
        r = await c.get("/api/health")
        assert r.status_code == 200
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert r.headers["x-frame-options"] == "DENY"
        assert "max-age=31536000" in r.headers["strict-transport-security"]
        assert "default-src 'self'" in r.headers["content-security-policy"]
        assert r.headers["x-request-id"]

        d = await c.get("/docs")
        assert d.status_code == 200
        assert "content-security-policy" not in d.headers
        assert d.headers["x-frame-options"] == "DENY"


async def test_security_headers_not_overwritten():
    app = FastAPI()

    @app.get("/x")
    async def x():
        from fastapi.responses import JSONResponse

        return JSONResponse({}, headers={"X-Frame-Options": "SAMEORIGIN"})

    async with _client(_stack(app)) as c:
        r = await c.get("/x")
    assert r.headers.get_list("x-frame-options") == ["SAMEORIGIN"]


async def test_oversized_body_gets_413():
    async with _client(_build_app()) as c:
        ok = await c.post("/echo", content=b"x" * 10)
        assert ok.status_code == 200 and ok.json() == {"len": 10}
        r = await c.post(
            "/echo",
            content=b"",
            headers={"content-length": str(MAX_REQUEST_BODY_BYTES + 1)},
        )
    assert r.status_code == 413
    assert r.json()["error"] == {
        "message": "Request body too large. Max 10 MB.",
        "code": 413,
    }


async def test_ip_whitelist_blocks_and_exempts_health(monkeypatch):
    monkeypatch.setenv("IP_WHITELIST", "10.0.0.0/8")
    async with _client(_build_app()) as c:
        blocked = await c.get("/tenant", headers={"x-forwarded-for": "8.8.8.8"})
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == 403
        allowed = await c.get(
            "/tenant", headers={"x-forwarded-for": "10.1.2.3, 8.8.8.8"}
        )
        assert allowed.status_code == 200
        health = await c.get("/api/health", headers={"x-forwarded-for": "8.8.8.8"})
        assert health.status_code == 200


async def test_tenant_id_from_jwt():
    tid = uuid.uuid4()
    token = create_access_token(uuid.uuid4(), tid, "admin")
    async with _client(_build_app()) as c:
        r = await c.get("/tenant", headers={"authorization": f"Bearer {token}"})
        assert r.json() == {"tenant_id": str(tid)}
        anon = await c.get("/tenant")
        assert anon.json() == {"tenant_id": None}


async def test_api_key_tenant_lookup_is_cached(monkeypatch):
    tid = uuid.uuid4()
    calls: list[str] = []

    async def fake_lookup(key_hash: str):
        calls.append(key_hash)
        return tid if key_hash else None

    monkeypatch.setattr(
        TenantMiddleware, "_resolve_tenant_from_api_key", staticmethod(fake_lookup)
    )
    async with _client(_build_app()) as c:
        for _ in range(5):
            r = await c.get("/tenant", headers={"x-api-key": "af_test_key"})
            assert r.json() == {"tenant_id": str(tid)}
    assert len(calls) == 1


async def test_api_key_misses_are_not_cached(monkeypatch):
    tid = uuid.uuid4()
    known: dict[str, uuid.UUID] = {}
    calls: list[str] = []

    async def fake_lookup(key_hash: str):
        calls.append(key_hash)
        return known.get(key_hash)

    monkeypatch.setattr(
        TenantMiddleware, "_resolve_tenant_from_api_key", staticmethod(fake_lookup)
    )
    async with _client(_build_app()) as c:
        r = await c.get("/tenant", headers={"x-api-key": "af_new"})
        assert r.json() == {"tenant_id": None}
        known[calls[0]] = tid
        r = await c.get("/tenant", headers={"x-api-key": "af_new"})
        assert r.json() == {"tenant_id": str(tid)}
    assert len(calls) == 2


async def test_rate_limit_429(monkeypatch):
    counts: dict[str, int] = {}

    async def fake_window(key, limit, window_seconds):
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > limit:
            return False, 0, 7
        return True, limit - counts[key], 0

    monkeypatch.setattr(rate_limit, "_IS_LOCAL_DEV", False)
    monkeypatch.delenv("RATE_LIMIT_BYPASS_TOKEN", raising=False)
    monkeypatch.setattr(rate_limit, "_DEFAULT_ANON_LIMIT", 1)
    monkeypatch.setattr(rate_limit, "_DEFAULT_AUTH_LIMIT", 1)
    monkeypatch.setattr(rate_limit, "sliding_window_check", fake_window)

    async with _client(_build_app()) as c:
        first = await c.get("/tenant")
        assert first.status_code == 200
        second = await c.get("/tenant")
        assert second.status_code == 429
        assert second.headers["retry-after"] == "7"
        for _ in range(3):
            assert (await c.get("/api/health")).status_code == 200
        login = await c.post("/api/auth/login", headers={"x-forwarded-for": "1.2.3.4"})
        assert login.status_code == 404
        login = await c.post("/api/auth/login", headers={"x-forwarded-for": "1.2.3.4"})
        assert login.status_code == 429
    assert "auth:1.2.3.4" in counts


async def test_sse_streams_through_stack_and_records_metrics():
    app = _build_app()
    before = _counter("/sse", "2xx")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/sse",
        "raw_path": b"/sse",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"test")],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }
    sent: list[dict] = []

    async def receive():
        await asyncio.sleep(10)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)

    start = sent[0]
    assert start["type"] == "http.response.start" and start["status"] == 200
    hdrs = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert hdrs["content-type"].startswith("text/event-stream")
    assert "x-request-id" in hdrs and "content-security-policy" in hdrs
    chunks = [m["body"] for m in sent[1:] if m.get("body")]
    assert chunks == [b"data: 0\n\n", b"data: 1\n\n", b"data: 2\n\n"]
    assert _counter("/sse", "2xx") == before + 1

    async with _client(app) as c:
        r = await c.get("/sse")
        assert r.text == "data: 0\n\ndata: 1\n\ndata: 2\n\n"
    assert _counter("/sse", "2xx") == before + 2


async def test_status_family_from_response_start():
    before = _counter("other", "4xx")
    async with _client(_build_app()) as c:
        r = await c.get("/nope")
    assert r.status_code == 404
    assert _counter("other", "4xx") == before + 1


async def test_websocket_scope_passes_through(monkeypatch):
    monkeypatch.setenv("IP_WHITELIST", "10.0.0.0/8")
    seen: list[tuple] = []

    async def inner(scope, receive, send):
        seen.append((scope, receive, send))

    app = inner
    for cls in (
        SecurityHeadersMiddleware,
        IPWhitelistMiddleware,
        ObservabilityMiddleware,
        BodySizeLimitMiddleware,
        RateLimitMiddleware,
        TenantMiddleware,
    ):
        app = cls(app)

    scope = {
        "type": "websocket",
        "path": "/ws",
        "headers": [(b"x-forwarded-for", b"8.8.8.8")],
        "client": ("8.8.8.8", 1),
    }
    snapshot = dict(scope)

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        pass

    await app(scope, receive, send)
    assert len(seen) == 1
    s, r, w = seen[0]
    assert s is scope and s == snapshot
    assert r is receive and w is send
