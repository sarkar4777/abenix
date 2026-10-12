"""A crash answers 500 in the envelope with CORS headers, so the browser shows the error and not a network failure."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_a_500_carries_cors_for_an_allowed_origin():
    from app.core.config import settings
    from app.main import app

    path = "/api/__test_boom"

    async def boom() -> None:
        raise RuntimeError("boom")

    app.add_api_route(path, boom, methods=["GET"])
    try:
        origin = next(o for o in settings.cors_origins if o != "*")
        c = TestClient(app, raise_server_exceptions=False)
        res = c.get(path, headers={"Origin": origin, "X-Request-ID": "ref-123"})
        assert res.status_code == 500
        assert res.headers.get("access-control-allow-origin") == origin
        assert res.headers.get("access-control-allow-credentials") == "true"
        body = res.json()
        assert body["data"] is None
        assert body["error"]["error_code"] == "INTERNAL_ERROR"
        assert "ref-123" in body["error"]["message"]
        other = c.get(path, headers={"Origin": "https://evil.example"})
        assert other.status_code == 500
        assert "access-control-allow-origin" not in other.headers
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "path", "") != path
        ]
