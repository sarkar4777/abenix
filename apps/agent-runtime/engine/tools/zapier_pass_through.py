"""Zapier NLA (Natural-Language Actions) pass-through.

Lets agents tap Zapier's 6,000+ connectors without us implementing each
one. Two flavours of Zapier API exist:
  - Zapier AI Actions ('Zapier NLA') — a Bearer-token API where each
    user grants the platform a set of "exposed actions" via a one-time
    OAuth-style consent flow. The agent then calls those actions by name.
  - Zapier Webhooks (any 'Catch Hook' URL) — fire-and-forget POST.

This tool covers both: list_actions / run_action use the NLA API,
fire_webhook posts to any Zapier 'Catch Hook' URL the user copied from
their Zap.

Auth env:
  ZAPIER_NLA_KEY   — bearer token from https://nla.zapier.com/credentials/
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_NLA_BASE = "https://nla.zapier.com/api/v1"


class ZapierPassThroughTool(BaseTool):
    name = "zapier_pass_through"
    description = (
        "Pass-through to Zapier — list / run AI Actions (any of 6,000+ "
        "connector apps the user has exposed), or fire a Zapier 'Catch "
        "Hook' webhook. NLA needs ZAPIER_NLA_KEY; webhooks just need the "
        "URL the user copied from their Zap."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["list_actions", "run_action", "fire_webhook"],
                "default": "list_actions",
            },
            "action_id": {
                "type": "string",
                "description": "run_action — the id from list_actions output.",
            },
            "instructions": {
                "type": "string",
                "description": "run_action — natural-language instructions for the action.",
            },
            "params": {
                "type": "object",
                "description": "run_action — explicit param overrides; merged with NL instructions.",
            },
            "webhook_url": {
                "type": "string",
                "description": "fire_webhook — the full Zapier Catch Hook URL.",
            },
            "payload": {
                "type": "object",
                "description": "fire_webhook — JSON payload to POST. Defaults to {}.",
            },
        },
        "required": ["operation"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation", "list_actions")

        if op == "fire_webhook":
            url = (arguments.get("webhook_url") or "").strip()
            if not url.startswith(("https://hooks.zapier.com/", "https://hooks.zap.app/")):
                return ToolResult(
                    content="webhook_url must be a hooks.zapier.com / hooks.zap.app URL",
                    is_error=True,
                )
            payload = arguments.get("payload") or {}
            try:
                async with httpx.AsyncClient(timeout=20) as c:
                    r = await c.post(url, json=payload)
                    r.raise_for_status()
                    body = r.text[:500]
                return ToolResult(
                    content=f"Zapier webhook fired ({r.status_code}). Response: {body}",
                    metadata={"status": r.status_code, "url": url},
                )
            except httpx.HTTPStatusError as e:
                return ToolResult(content=f"Webhook HTTP {e.response.status_code}: {e.response.text[:200]}", is_error=True)
            except Exception as e:
                return ToolResult(content=f"Webhook error: {e}", is_error=True)

        # NLA operations need the bearer token.
        key = os.environ.get("ZAPIER_NLA_KEY", "").strip()
        if not key:
            return ToolResult(
                content=(
                    "[zapier_pass_through not configured] ZAPIER_NLA_KEY not set. "
                    "Get one at https://nla.zapier.com/credentials/ and expose the "
                    "actions you want this agent to use."
                ),
                metadata={"skipped": True, "operation": op},
            )

        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30, headers=headers) as c:
                if op == "list_actions":
                    r = await c.get(f"{_NLA_BASE}/exposed/")
                    r.raise_for_status()
                    data = r.json()
                    actions = data.get("results") or data.get("actions") or []
                    lines = [f"Zapier NLA — {len(actions)} exposed action(s):"]
                    compact = []
                    for a in actions[:30]:
                        aid = a.get("id") or a.get("action_id")
                        desc = a.get("description") or a.get("name") or ""
                        lines.append(f"  {aid}  —  {desc}")
                        compact.append({"id": aid, "description": desc})
                    return ToolResult(content="\n".join(lines), metadata={"actions": compact})

                if op == "run_action":
                    aid = (arguments.get("action_id") or "").strip()
                    if not aid:
                        return ToolResult(content="action_id is required for run_action", is_error=True)
                    body: dict[str, Any] = {
                        "instructions": (arguments.get("instructions") or "")[:2000],
                    }
                    params = arguments.get("params")
                    if params:
                        body["params"] = params
                    r = await c.post(f"{_NLA_BASE}/exposed/{aid}/execute/", json=body)
                    r.raise_for_status()
                    data = r.json()
                    return ToolResult(
                        content=(
                            f"Zapier action {aid} executed.\n"
                            f"  status: {data.get('status', '?')}\n"
                            f"  result: {str(data.get('result'))[:500]}"
                        ),
                        metadata=data,
                    )

                return ToolResult(content=f"Unknown operation: {op}", is_error=True)
        except httpx.HTTPStatusError as e:
            return ToolResult(content=f"Zapier HTTP {e.response.status_code}: {e.response.text[:300]}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Zapier error: {e}", is_error=True)
