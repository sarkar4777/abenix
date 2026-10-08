"""HTTP client tool for making API requests to external services."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from engine.tools.base import READ_ONLY, BaseTool, Effect, ToolResult


def plain_error(e: BaseException, host: str, timeout: float) -> str:
    """What went wrong with a request, in words a person can act on."""
    import asyncio
    import socket
    import ssl

    try:
        import aiohttp
    except ImportError:  # pragma: no cover
        aiohttp = None  # type: ignore[assignment]

    if isinstance(e, (asyncio.TimeoutError, TimeoutError)) or (
        aiohttp is not None and isinstance(e, aiohttp.ServerTimeoutError)
    ):
        return f"{host} did not answer within {int(timeout)} seconds."
    if aiohttp is not None:
        if isinstance(
            e, (aiohttp.ClientConnectorCertificateError, aiohttp.ClientSSLError)
        ):
            return f"{host} failed the secure connection (SSL certificate) check."
        if isinstance(e, aiohttp.ClientConnectorError):
            dns_error = getattr(aiohttp, "ClientConnectorDNSError", ())
            if isinstance(e, dns_error) or isinstance(
                getattr(e, "os_error", None), socket.gaierror
            ):
                return (
                    f"This server cannot find {host}. Check the address, "
                    "or that this server can reach the internet."
                )
            return (
                f"This server cannot reach {host}. It may be down, or this "
                "server may not be allowed to connect to it."
            )
        if isinstance(e, aiohttp.ServerDisconnectedError):
            return f"{host} closed the connection before answering."
        if isinstance(e, aiohttp.TooManyRedirects):
            return f"{host} redirected too many times."
        if isinstance(e, aiohttp.InvalidURL):
            return "The URL is not valid."
    if isinstance(e, ssl.SSLError):
        return f"{host} failed the secure connection (SSL certificate) check."
    if isinstance(e, socket.gaierror):
        return f"This server cannot find {host}."
    if isinstance(e, (ConnectionError, OSError)):
        return f"This server cannot reach {host}."
    return f"The request to {host} failed ({e.__class__.__name__})."


class HttpClientTool(BaseTool):
    name = "http_client"
    risk_tier = "medium"
    effect = Effect(
        kind="external",
        label="Send an HTTP request that changes something",
        target_param="url",
    )
    description = (
        "Make HTTP requests to external APIs and web services. Supports GET, POST, "
        "PUT, DELETE methods with custom headers and JSON payloads. Useful for "
        "integrating with third-party APIs, fetching data from REST endpoints, "
        "and interacting with web services. Respects sandbox domain restrictions."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full http or https URL to request",
            },
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                "description": "HTTP method",
                "default": "GET",
            },
            "headers": {
                "type": "object",
                "description": "Request headers as key-value pairs",
            },
            "body": {
                "type": "object",
                "description": "JSON request body (for POST/PUT/PATCH)",
            },
            "params": {
                "type": "object",
                "description": "URL query parameters as key-value pairs",
            },
            "timeout": {
                "type": "integer",
                "description": "Request timeout in seconds (default: 15)",
                "default": 15,
            },
        },
        "required": ["url"],
    }

    @classmethod
    def effect_for(cls, arguments: dict[str, Any]) -> Effect | None:
        method = str(arguments.get("method") or "GET").upper()
        return READ_ONLY if method in ("GET", "HEAD", "OPTIONS") else cls.effect

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        url = arguments.get("url", "")
        method = arguments.get("method", "GET").upper()
        headers = arguments.get("headers", {})
        body = arguments.get("body")
        params = arguments.get("params", {})
        timeout = min(arguments.get("timeout", 15), 120)
        bearer_token = arguments.get("bearer_token")
        max_retries = min(arguments.get("max_retries", 0), 3)

        if not url:
            return ToolResult(content="Error: url is required", is_error=True)

        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            return ToolResult(
                content="Error: only HTTP/HTTPS URLs are supported", is_error=True
            )

        if not parsed.hostname:
            return ToolResult(content="Error: invalid URL", is_error=True)

        try:
            import aiohttp

            req_headers = {"User-Agent": "Abenix-Tool/1.0", **headers}
            if bearer_token:
                req_headers["Authorization"] = f"Bearer {bearer_token}"
            if body and "Content-Type" not in req_headers:
                req_headers["Content-Type"] = "application/json"

            import asyncio as _asyncio

            async with aiohttp.ClientSession() as session:
                kwargs: dict[str, Any] = {
                    "url": url,
                    "headers": req_headers,
                    "timeout": aiohttp.ClientTimeout(total=timeout),
                }
                if params:
                    kwargs["params"] = params
                if body and method in ("POST", "PUT", "PATCH"):
                    kwargs["json"] = body

                status = 0
                resp_body: Any = None
                resp_headers: dict[str, str] = {}
                last_error = ""

                for attempt in range(max_retries + 1):
                    try:
                        async with session.request(method, **kwargs) as resp:
                            status = resp.status
                            resp_headers = dict(resp.headers)
                            content_type = resp.content_type or ""

                            if status in (429, 503) and attempt < max_retries:
                                retry_after = int(
                                    resp.headers.get(
                                        "Retry-After", str(2 ** (attempt + 1))
                                    )
                                )
                                await _asyncio.sleep(min(retry_after, 60))
                                continue

                            if "json" in content_type:
                                resp_body = await resp.json()
                            else:
                                text = await resp.text()
                                if len(text) > 500_000:
                                    text = (
                                        text[:500_000]
                                        + "\n[Truncated at 500,000 characters]"
                                    )
                                resp_body = text
                            break
                    except Exception as e:
                        last_error = plain_error(e, parsed.hostname, timeout)
                        if attempt < max_retries:
                            await _asyncio.sleep(2 ** (attempt + 1))
                        else:
                            tries = (
                                f" Tried {max_retries + 1} times."
                                if max_retries
                                else ""
                            )
                            return ToolResult(
                                content=f"{last_error}{tries}",
                                is_error=True,
                                metadata={"url": url, "unreachable": True},
                            )

            result = {
                "status": status,
                "headers": {
                    k: v
                    for k, v in resp_headers.items()
                    if k.lower()
                    in (
                        "content-type",
                        "content-length",
                        "date",
                        "x-ratelimit-remaining",
                        "x-ratelimit-limit",
                        "retry-after",
                    )
                },
                "body": resp_body,
            }

            output = json.dumps(result, indent=2, default=str)
            return ToolResult(
                content=output,
                metadata={"method": method, "url": url, "status": status},
            )

        except Exception as e:
            return ToolResult(
                content=plain_error(e, parsed.hostname, timeout), is_error=True
            )
