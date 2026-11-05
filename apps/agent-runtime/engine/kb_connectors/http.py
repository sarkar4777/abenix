"""HTTP for SaaS connectors, every hop goes through the outbound URL guard."""

from __future__ import annotations

import base64
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from engine import url_guard
from engine.kb_connectors.base import (
    AuthError,
    ConfigError,
    ConnectorError,
    Gone,
    TooLarge,
    TransientError,
    with_retries,
)

TIMEOUT = httpx.Timeout(60.0, connect=15.0)


def allow_private() -> bool:
    return url_guard.env_flag("CONNECTORS_ALLOW_PRIVATE_TARGETS")


def allowed_hosts() -> list[str]:
    raw = os.environ.get("KB_CONNECTORS_ALLOWED_HOSTS", "")
    return [h.strip() for h in raw.split(",") if h.strip()]


async def check_url(url: str, what: str, require_dns: bool = False) -> None:
    reason = await url_guard.check(
        url,
        allow_private=allow_private(),
        allowed_hosts=allowed_hosts(),
        require_dns=require_dns,
    )
    if reason:
        raise ConfigError(
            f"{what} cannot be used. {reason}. An operator can list this host in "
            "KB_CONNECTORS_ALLOWED_HOSTS or set CONNECTORS_ALLOW_PRIVATE_TARGETS."
        )


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after", "")
    try:
        return float(raw)
    except ValueError:
        return None


class GuardedClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.client = httpx.AsyncClient(timeout=TIMEOUT, transport=transport)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _send(self, request: httpx.Request, stream: bool) -> httpx.Response:
        try:
            resp = await url_guard.send_guarded(
                self.client,
                request,
                allow_private=allow_private(),
                allowed_hosts=allowed_hosts(),
                stream=stream,
            )
        except url_guard.Blocked as e:
            raise ConfigError(f"The request was refused. {e.reason}") from e
        except url_guard.TooManyRedirects as e:
            raise ConnectorError(str(e)) from e
        except httpx.TransportError as e:
            raise TransientError(f"Could not reach {request.url.host}: {e}") from e
        if resp.status_code < 400:
            return resp
        if stream:
            await resp.aread()
        host = request.url.host
        if resp.status_code in (408, 425, 429) or resp.status_code >= 500:
            raise TransientError(
                f"{host} answered {resp.status_code}", _retry_after(resp)
            )
        if resp.status_code in (401, 403):
            raise AuthError(
                f"{host} refused these credentials ({resp.status_code}). "
                f"{resp.text[:200]}"
            )
        if resp.status_code == 410:
            raise Gone(f"{host} no longer honours this position.")
        raise ConnectorError(
            f"{host} answered {resp.status_code} for {request.url.path}. "
            f"{resp.text[:200]}"
        )

    async def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        async def once() -> httpx.Response:
            return await self._send(self.client.build_request(method, url, **kw), False)

        return await with_retries(once, **self._retry_options())

    async def download(self, url: str, max_bytes: int, **kw: Any) -> bytes:
        """Stops reading at the limit, a size header can be wrong or missing."""

        async def once() -> bytes:
            resp = await self._send(self.client.build_request("GET", url, **kw), True)
            try:
                out = bytearray()
                async for part in resp.aiter_bytes():
                    out.extend(part)
                    if len(out) > max_bytes:
                        raise TooLarge(
                            f"It is larger than the limit of {max_bytes} bytes."
                        )
                return bytes(out)
            finally:
                await resp.aclose()

        return await with_retries(once, **self._retry_options())

    def _retry_options(self) -> dict[str, Any]:
        sleep = getattr(self, "sleep", None)
        return {"sleep": sleep} if sleep else {}


def basic_auth(user: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()
