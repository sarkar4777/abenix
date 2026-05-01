from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.telemetry import http_request_duration_seconds, http_requests_total


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        tenant_id = str(getattr(request.state, "tenant_id", None) or "")
        path = request.url.path
        method = request.method

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=method,
            path=path,
            tenant_id=tenant_id,
        )

        log = structlog.get_logger("abenix.http")
        start = time.monotonic()

        response = await call_next(request)

        duration_s = time.monotonic() - start
        duration_ms = int(duration_s * 1000)
        status = response.status_code

        http_requests_total.labels(method=method, path=path, status=status).inc()
        http_request_duration_seconds.labels(method=method, path=path).observe(
            duration_s
        )

        response.headers["X-Request-ID"] = request_id

        log.info(
            "http_request",
            status=status,
            duration_ms=duration_ms,
        )

        return response
