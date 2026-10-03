from __future__ import annotations

import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.telemetry import http_request_duration_seconds, http_requests_total


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    tmpl = getattr(route, "path", None) if route else None
    return tmpl or "other"


def _status_family(status: int) -> str:
    if 200 <= status < 300:
        return "2xx"
    if 300 <= status < 400:
        return "3xx"
    if 400 <= status < 500:
        return "4xx"
    if 500 <= status < 600:
        return "5xx"
    return "other"


class ObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get("x-request-id") or str(uuid.uuid4())
        tenant_id = str((scope.get("state") or {}).get("tenant_id") or "")
        path = scope["path"]
        method = scope["method"]

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=method,
            path=path,
            tenant_id=tenant_id,
        )

        log = structlog.get_logger("abenix.http")
        start = time.monotonic()
        status: int | None = None
        recorded = False

        def record() -> None:
            nonlocal recorded
            if recorded or status is None:
                return
            recorded = True
            duration_s = time.monotonic() - start
            route_path = _route_template(scope)
            http_requests_total.labels(
                method=method, path=route_path, status=_status_family(status)
            ).inc()
            http_request_duration_seconds.labels(
                method=method, path=route_path
            ).observe(duration_s)
            log.info(
                "http_request",
                status=status,
                duration_ms=int(duration_s * 1000),
            )

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
                await send(message)
                return
            await send(message)
            if message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                record()

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # Covers streams cut short by a client disconnect.
            record()
