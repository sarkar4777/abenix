"""IP Whitelist Middleware — restrict API access to specific IP ranges."""
from __future__ import annotations

import ipaddress
import os
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """Block requests from IPs not in the whitelist."""

    def __init__(self, app: Any, **kwargs: Any) -> None:
        super().__init__(app, **kwargs)
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

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if not self.enabled:
            return await call_next(request)

        # Allow health checks from anywhere
        if request.url.path in ("/api/health", "/api/health/ready", "/api/metrics"):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
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

    @staticmethod
    def _get_client_ip(request: Request) -> str | None:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return None
