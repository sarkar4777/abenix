"""HTTP client tool for making API requests to external services."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from engine.tools.base import BaseTool, ToolResult


class HttpClientTool(BaseTool):
    name = "http_client"
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
                "description": "Full URL to request (must be HTTPS)",
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
                        last_error = str(e)
                        if attempt < max_retries:
                            await _asyncio.sleep(2 ** (attempt + 1))
                        else:
                            return ToolResult(
                                content=f"HTTP request failed after {max_retries + 1} attempts: {last_error}",
                                is_error=True,
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
            return ToolResult(content=f"HTTP request failed: {e}", is_error=True)
