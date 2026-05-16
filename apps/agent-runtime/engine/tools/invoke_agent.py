from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx

from engine import progress
from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

TERMINAL = {"completed", "succeeded", "failed", "error", "cancelled"}


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
        self,
        *,
        tenant_id: str = "",
        execution_id: str = "",
        api_key: str = "",
        api_base: str = "",
    ) -> None:
        self._tenant_id = tenant_id
        self._execution_id = execution_id
        self._api_key = (
            api_key
            or os.environ.get("ABENIX_PLATFORM_API_KEY", "")
            or os.environ.get("INTERNAL_API_TOKEN", "")
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
                content="No platform API key on the runtime pod (looked for ABENIX_PLATFORM_API_KEY / INTERNAL_API_TOKEN).",
                is_error=True,
            )

        root_id = (
            await progress.root_for(self._execution_id) if self._execution_id else ""
        )

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key.startswith("af_"):
            headers["X-API-Key"] = self._api_key
        else:
            headers["Authorization"] = f"Bearer {self._api_key}"

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

                submit_body = {
                    "message": (
                        json.dumps(payload) if not isinstance(payload, str) else payload
                    ),
                    "stream": False,
                    "wait_mode": "submitted",
                }
                submit_r = await client.post(
                    f"/api/agents/{agent_id}/execute",
                    headers=headers,
                    content=json.dumps(submit_body),
                )
                if submit_r.status_code != 200:
                    return ToolResult(
                        content=f"agent execute submit failed: HTTP {submit_r.status_code} {submit_r.text[:300]}",
                        is_error=True,
                    )
                submit_data = (
                    (submit_r.json() or {}).get("data") or submit_r.json() or {}
                )
                sub_exec_id = submit_data.get("execution_id") or submit_data.get("id")
                if not sub_exec_id:
                    return ToolResult(
                        content="submitted but no sub-execution_id returned",
                        is_error=True,
                    )

                if root_id:
                    await progress.set_parent(sub_exec_id, root_id)
                    await progress.publish(
                        self._execution_id,
                        {
                            "phase": "sub_started",
                            "agent_slug": slug,
                            "agent_name": (match.get("name") or slug),
                            "sub_execution_id": sub_exec_id,
                        },
                        root_execution_id=root_id,
                    )

                deadline = t0 + timeout
                row: dict[str, Any] = {}
                while time.time() < deadline:
                    await asyncio.sleep(2.0)
                    poll_r = await client.get(
                        f"/api/executions/{sub_exec_id}", headers=headers
                    )
                    if poll_r.status_code != 200:
                        continue
                    row = (poll_r.json() or {}).get("data") or {}
                    status = (row.get("status") or "running").lower()
                    if status in TERMINAL:
                        break

                if not row or (row.get("status") or "running").lower() not in TERMINAL:
                    if root_id:
                        await progress.publish(
                            self._execution_id,
                            {
                                "phase": "sub_timeout",
                                "agent_slug": slug,
                                "sub_execution_id": sub_exec_id,
                            },
                            root_execution_id=root_id,
                        )
                    return ToolResult(
                        content=f"agent {slug} timed out after {timeout}s",
                        is_error=True,
                    )

                output = row.get("output") or row.get("output_message") or ""
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

                if root_id:
                    await progress.publish(
                        self._execution_id,
                        {
                            "phase": "sub_finished",
                            "agent_slug": slug,
                            "sub_execution_id": sub_exec_id,
                            "status": row.get("status"),
                            "duration_ms": row.get("duration_ms") or duration_ms,
                            "cost_usd": row.get("cost"),
                        },
                        root_execution_id=root_id,
                    )

                envelope = {
                    "agent_slug": slug,
                    "agent_id": agent_id,
                    "execution_id": sub_exec_id,
                    "status": (row.get("status") or "completed"),
                    "output": parsed,
                    "duration_ms": row.get("duration_ms") or duration_ms,
                    "cost_usd": row.get("cost"),
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
