"""IP Whitelist Middleware — restrict API access to specific IP ranges."""

from __future__ import annotations

import ipaddress
import os

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_EXEMPT_PATHS = frozenset({"/api/health", "/api/health/ready", "/api/metrics"})


class IPWhitelistMiddleware:
    """Block requests from IPs not in the whitelist."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        raw = os.environ.get("IP_WHITELIST", "").strip()
        self.networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        if raw:
            for entry in raw.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                try:
                    self.networks.append(ipaddress.ip_network(entry, strict=False))
                except ValueError:
                    pass  # Skip invalid entries
        self.enabled = len(self.networks) > 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not self.enabled
            or scope["path"] in _EXEMPT_PATHS
        ):
            await self.app(scope, receive, send)
            return

        client_ip = self._get_client_ip(scope)
        if not client_ip:
            await self.app(scope, receive, send)
            return

        try:
            addr = ipaddress.ip_address(client_ip)
            for network in self.networks:
                if addr in network:
                    await self.app(scope, receive, send)
                    return
        except ValueError:
            pass

        response = JSONResponse(
            status_code=403,
            content={
                "data": None,
                "error": {"message": "Access denied: IP not in whitelist", "code": 403},
                "meta": None,
            },
        )
        await response(scope, receive, send)

    @staticmethod
    def _get_client_ip(scope: Scope) -> str | None:
        forwarded = Headers(scope=scope).get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = scope.get("client")
        if client:
            return client[0]
        return None
