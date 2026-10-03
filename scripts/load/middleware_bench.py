"""In-process benchmark of the API middleware stack, old BaseHTTPMiddleware vs pure ASGI.

Usage: python scripts/load/middleware_bench.py [--requests 5000] [--concurrency 200]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for sub in ("apps/api", "packages/db"):
    sys.path.insert(0, str(ROOT / sub))
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("IP_WHITELIST", "0.0.0.0/0,::/0")

import httpx  # noqa: E402
import structlog  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from starlette.middleware.base import (  # noqa: E402
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.responses import JSONResponse, Response  # noqa: E402

import app.core.rate_limit as rate_limit  # noqa: E402
from app.core.ip_whitelist import IPWhitelistMiddleware  # noqa: E402
from app.core.middleware import (  # noqa: E402
    AUTH_PATHS,
    MAX_REQUEST_BODY_BYTES,
    MAX_UPLOAD_BODY_BYTES,
    RATE_LIMIT_SKIP,
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    TenantMiddleware,
)
from app.core.observability_middleware import (  # noqa: E402
    ObservabilityMiddleware,
    _status_family,
)
from app.core.security import verify_token  # noqa: E402
from app.core.telemetry import (  # noqa: E402
    http_request_duration_seconds,
    http_requests_total,
)

# Pre-rewrite classes, kept here only for comparison.


class old_TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request.state.tenant_id = None
        api_key = request.headers.get("x-api-key", "")
        if api_key.startswith("af_"):
            tenant_id = await TenantMiddleware._resolve_tenant_from_api_key(
                hashlib.sha256(api_key.encode()).hexdigest()
            )
            if tenant_id:
                request.state.tenant_id = tenant_id
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            payload = verify_token(auth.removeprefix("Bearer "))
            tid = payload.get("tenant_id")
            if tid:
                try:
                    request.state.tenant_id = uuid.UUID(tid)
                except ValueError:
                    pass
        return await call_next(request)


class old_RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        if path in RATE_LIMIT_SKIP:
            return await call_next(request)
        from app.core.rate_limit import rate_limit_auth, rate_limit_user

        if path in AUTH_PATHS or path.startswith("/api/auth/invite/"):
            blocked = await rate_limit_auth(request)
            if blocked:
                return blocked
        blocked = await rate_limit_user(request)
        if blocked:
            return blocked
        return await call_next(request)


class old_SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
        path = request.url.path
        if not (
            path.startswith("/docs")
            or path.startswith("/redoc")
            or path == "/openapi.json"
        ):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; frame-ancestors 'none'; "
                "img-src 'self' data: blob: https:; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "connect-src 'self' https: wss:",
            )
        return response


class old_BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            length = int(content_length)
            is_upload = "upload" in request.url.path or "multipart" in (
                request.headers.get("content-type", "")
            )
            limit = MAX_UPLOAD_BODY_BYTES if is_upload else MAX_REQUEST_BODY_BYTES
            if length > limit:
                return JSONResponse(
                    status_code=413,
                    content={
                        "data": None,
                        "error": {
                            "message": "Request body too large. Max {} MB.".format(
                                limit // (1024 * 1024)
                            ),
                            "code": 413,
                        },
                    },
                )
        return await call_next(request)


class old_IPWhitelistMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, **kwargs: Any) -> None:
        super().__init__(app, **kwargs)
        raw = os.environ.get("IP_WHITELIST", "").strip()
        self.networks = [
            ipaddress.ip_network(e.strip(), strict=False)
            for e in raw.split(",")
            if e.strip()
        ]
        self.enabled = len(self.networks) > 0

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if not self.enabled:
            return await call_next(request)
        if request.url.path in ("/api/health", "/api/health/ready", "/api/metrics"):
            return await call_next(request)
        forwarded = request.headers.get("x-forwarded-for")
        client_ip = (
            forwarded.split(",")[0].strip()
            if forwarded
            else (request.client.host if request.client else None)
        )
        if not client_ip:
            return await call_next(request)
        try:
            addr = ipaddress.ip_address(client_ip)
            for network in self.networks:
                if addr in network:
                    return await call_next(request)
        except ValueError:
            pass
        return JSONResponse(
            status_code=403,
            content={
                "data": None,
                "error": {"message": "Access denied: IP not in whitelist", "code": 403},
                "meta": None,
            },
        )


class old_ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        tenant_id = str(getattr(request.state, "tenant_id", None) or "")
        path = request.url.path
        method = request.method
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id, method=method, path=path, tenant_id=tenant_id
        )
        log = structlog.get_logger("abenix.http")
        start = time.monotonic()
        response = await call_next(request)
        duration_s = time.monotonic() - start
        status = response.status_code
        route = request.scope.get("route")
        route_path = getattr(route, "path", None) or "other"
        http_requests_total.labels(
            method=method, path=route_path, status=_status_family(status)
        ).inc()
        http_request_duration_seconds.labels(method=method, path=route_path).observe(
            duration_s
        )
        response.headers["X-Request-ID"] = request_id
        log.info("http_request", status=status, duration_ms=int(duration_s * 1000))
        return response


OLD = (
    old_SecurityHeadersMiddleware,
    old_IPWhitelistMiddleware,
    old_ObservabilityMiddleware,
    old_BodySizeLimitMiddleware,
    old_RateLimitMiddleware,
    old_TenantMiddleware,
)
NEW = (
    SecurityHeadersMiddleware,
    IPWhitelistMiddleware,
    ObservabilityMiddleware,
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    TenantMiddleware,
)


def build(stack: tuple) -> FastAPI:
    app = FastAPI()

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/ping")
    async def ping():
        return {"pong": True}

    for cls in stack:
        app.add_middleware(cls)
    return app


async def run(app: FastAPI, path: str, total: int, concurrency: int) -> float:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://bench") as c:
        for _ in range(50):
            await c.get(path)
        sem = asyncio.Semaphore(concurrency)

        async def one() -> None:
            async with sem:
                r = await c.get(path)
                assert r.status_code == 200, r.status_code

        t0 = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(total)))
        return total / (time.perf_counter() - t0)


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--requests", type=int, default=5000)
    p.add_argument("--concurrency", type=int, default=200)
    p.add_argument("--rounds", type=int, default=3)
    args = p.parse_args()

    rate_limit._IS_LOCAL_DEV = True
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING)
    )

    variants = {"bare": (), "old": OLD, "new": NEW}
    for path in ("/api/health", "/api/ping"):
        print(f"{path}  requests={args.requests} concurrency={args.concurrency}")
        results = {}
        for name, stack in variants.items():
            best = 0.0
            for _ in range(args.rounds):
                best = max(
                    best,
                    await run(build(stack), path, args.requests, args.concurrency),
                )
            results[name] = best
            print(f"  {name:5s} {best:9.0f} req/s")
        print(f"  speedup new/old: {results['new'] / results['old']:.2f}x")


if __name__ == "__main__":
    asyncio.run(main())
