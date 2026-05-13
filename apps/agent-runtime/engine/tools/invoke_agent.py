from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class InvokeAgentTool(BaseTool):
    name = "invoke_agent"
    description = (
        "Invoke a registered Abenix agent by slug. The platform enqueues the "
        "sub-execution, runs it on the appropriate runtime pool, and this tool "
        "returns the parsed JSON envelope. Use it to fan a desk-level question "
        "out across the specialised Wingman agents and synthesise a unified "
        "brief from their outputs."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_slug": {
                "type": "string",
                "description": "Slug of the registered agent to invoke (e.g. 'wingman-arb-analyzer').",
            },
            "input": {
                "type": "object",
                "description": "JSON object passed as the input to the sub-agent.",
                "additionalProperties": True,
            },
            "wait_timeout_seconds": {
                "type": "integer",
                "default": 240,
                "minimum": 30,
                "maximum": 600,
            },
        },
        "required": ["agent_slug", "input"],
    }

    def __init__(
        self, *, tenant_id: str = "", api_key: str = "", api_base: str = ""
    ) -> None:
        self._tenant_id = tenant_id
        self._api_key = (
            api_key
            or os.environ.get("ABENIX_INTERNAL_API_KEY", "")
            or os.environ.get("PLATFORM_API_KEY", "")
        )
        self._api_base = (
            api_base
            or os.environ.get("ABENIX_INTERNAL_URL", "")
            or os.environ.get("ABENIX_API_URL", "http://abenix-api:8000")
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        slug = (arguments.get("agent_slug") or "").strip()
        payload = arguments.get("input") or {}
        timeout = int(arguments.get("wait_timeout_seconds") or 240)
        if not slug:
            return ToolResult(content="agent_slug is required", is_error=True)
        if not self._api_key:
            return ToolResult(
                content="ABENIX_INTERNAL_API_KEY not configured for invoke_agent on the runtime pod.",
                is_error=True,
            )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        t0 = time.time()
        try:
            async with httpx.AsyncClient(
                base_url=self._api_base, timeout=timeout + 30
            ) as client:
                lookup = await client.get(
                    f"/api/agents?search={slug}&limit=5", headers=headers
                )
                if lookup.status_code != 200:
                    return ToolResult(
                        content=f"agent lookup failed: HTTP {lookup.status_code} {lookup.text[:300]}",
                        is_error=True,
                    )
                items = (lookup.json() or {}).get("data") or []
                if isinstance(items, dict):
                    items = items.get("items") or []
                match = next(
                    (a for a in items if (a.get("slug") or "").lower() == slug.lower()),
                    None,
                )
                if match is None:
                    return ToolResult(
                        content=f"agent slug not found: {slug}", is_error=True
                    )
                agent_id = match.get("id")

                body = {
                    "input": json.dumps(payload),
                    "wait_timeout_seconds": timeout,
                }
                exec_r = await client.post(
                    f"/api/agents/{agent_id}/execute",
                    headers=headers,
                    content=json.dumps(body),
                )
                if exec_r.status_code != 200:
                    return ToolResult(
                        content=f"agent execute failed: HTTP {exec_r.status_code} {exec_r.text[:300]}",
                        is_error=True,
                    )
                data = (exec_r.json() or {}).get("data") or exec_r.json() or {}
                output = data.get("output") or data.get("output_message") or ""
                duration_ms = int((time.time() - t0) * 1000)
                parsed: Any = output
                try:
                    parsed = json.loads(output) if isinstance(output, str) else output
                except Exception:
                    s = (output or "").strip()
                    first, last = s.find("{"), s.rfind("}")
                    if first != -1 and last > first:
                        try:
                            parsed = json.loads(s[first : last + 1])
                        except Exception:
                            parsed = {"raw": s[:2000]}

                envelope = {
                    "agent_slug": slug,
                    "agent_id": agent_id,
                    "execution_id": data.get("execution_id") or data.get("id"),
                    "status": (data.get("status") or "completed"),
                    "output": parsed,
                    "duration_ms": data.get("duration_ms") or duration_ms,
                    "cost_usd": data.get("cost"),
                }
                return ToolResult(
                    content=json.dumps(envelope, default=str),
                    metadata={"agent_slug": slug},
                )
        except httpx.TimeoutException:
            return ToolResult(
                content=f"agent {slug} timed out after {timeout}s", is_error=True
            )
        except Exception as e:
            logger.warning("invoke_agent %s failed: %s", slug, e)
            return ToolResult(content=f"invoke_agent {slug} failed: {e}", is_error=True)
