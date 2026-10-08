"""Outbound URL guard for calls the platform makes on a tenant's behalf.

Used by connectors in the API and in the runtime ``connector_call`` tool. A
URL is refused when it names an internal host, a cluster DNS name, or an
address on a private, loopback, link-local, multicast or reserved range, and
again when its host resolves to one. ``send_guarded`` follows redirects by
hand so every hop is checked the same way.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

INTERNAL_NAMES = frozenset(
    {
        "localhost",
        "host.docker.internal",
        "host.minikube.internal",
        "metadata.google.internal",
        "metadata",
        "kubernetes.default.svc",
        "kubernetes.default",
        "kubernetes",
    }
)
INTERNAL_SUFFIXES = (
    ".svc.cluster.local",
    ".cluster.local",
    ".svc",
    ".internal",
    ".local",
)
MAX_REDIRECTS = 3


class Blocked(Exception):
    """The URL, or a redirect hop, may not be called."""

    def __init__(self, reason: str, url: str = "", hop: int = 0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.url = url
        self.hop = hop


class TooManyRedirects(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(f"It redirected more than {limit} times")
        self.limit = limit


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def static_reason(url: str, allowed_hosts: Iterable[str] = ()) -> str | None:
    """Why the URL is refused on its face, before any DNS lookup."""
    try:
        u = urlparse(url or "")
    except ValueError:
        return "The URL is not valid"
    if u.scheme not in ("http", "https"):
        return "The URL must start with http:// or https://"
    try:
        host = (u.hostname or "").lower().rstrip(".")
        _ = u.port
    except ValueError:
        return "The URL has an invalid port"
    if not host:
        return "The URL has no host name"
    if host in {h.strip().lower() for h in allowed_hosts if h.strip()}:
        return None
    if host in INTERNAL_NAMES:
        return f"{host} is an internal host name"
    if host.endswith(INTERNAL_SUFFIXES):
        return f"{host} is a cluster-internal name"
    try:
        if _private_ip(ipaddress.ip_address(host)):
            return f"{host} is a private or loopback address"
    except ValueError:
        pass
    try:
        if _private_ip(ipaddress.ip_address(int(host))):
            return f"{host} is a private address written as a number"
    except ValueError:
        pass
    return None


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port)
    return [str(i[4][0]) for i in infos]


async def check(
    url: str,
    *,
    allow_private: bool = False,
    allowed_hosts: Iterable[str] = (),
    require_dns: bool = True,
) -> str | None:
    """Why the URL must not be called, or None. Judged on what it resolves to now.

    ``require_dns=False`` lets a host that does not resolve yet pass, for a
    URL being saved rather than called.
    """
    allowed_hosts = list(allowed_hosts)
    if allow_private:
        u = urlparse(url or "")
        if u.scheme not in ("http", "https") or not u.hostname:
            return "The URL must start with http:// or https:// and name a host"
        return None
    reason = static_reason(url, allowed_hosts)
    if reason:
        return reason
    u = urlparse(url)
    host = (u.hostname or "").lower().rstrip(".")
    if host in {h.strip().lower() for h in allowed_hosts if h.strip()}:
        return None
    try:
        addrs = await _resolve(host, u.port or (443 if u.scheme == "https" else 80))
    except (OSError, UnicodeError):
        return f"{host} does not resolve" if require_dns else None
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a.split("%", 1)[0])
        except ValueError:
            continue
        if _private_ip(ip):
            return f"{host} resolves to a private address ({ip})"
    return None


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    return (url.scheme, url.host, url.port)


async def send_guarded(
    client: httpx.AsyncClient,
    request: httpx.Request,
    *,
    allow_private: bool = False,
    allowed_hosts: Iterable[str] = (),
    max_redirects: int = MAX_REDIRECTS,
    sensitive_headers: Iterable[str] = (),
) -> httpx.Response:
    """Send with redirects followed by hand, each hop checked first.

    Raises Blocked when a hop is refused and TooManyRedirects past the limit.
    ``sensitive_headers`` are dropped once a hop leaves the first origin.
    """
    allowed_hosts = list(allowed_hosts)
    first = _origin(request.url)
    drop = {h.lower() for h in sensitive_headers} | {"authorization"}
    hop = 0
    while True:
        reason = await check(
            str(request.url), allow_private=allow_private, allowed_hosts=allowed_hosts
        )
        if reason:
            raise Blocked(reason, str(request.url), hop)
        resp = await client.send(request, follow_redirects=False)
        nxt: Any = resp.next_request
        if not resp.is_redirect or nxt is None:
            return resp
        if hop >= max_redirects:
            raise TooManyRedirects(max_redirects)
        await resp.aclose()
        hop += 1
        if _origin(nxt.url) != first:
            for h in list(nxt.headers.keys()):
                if h.lower() in drop:
                    del nxt.headers[h]
        request = nxt
