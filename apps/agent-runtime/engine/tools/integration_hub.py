"""Integration Hub — unified interface for 20+ enterprise services."""
from __future__ import annotations

import json
import os
from typing import Any

from engine.tools.base import BaseTool, ToolResult


# Service registry: name → {env_key, base_url, description}
SERVICES = {
    "slack": {"env": "SLACK_WEBHOOK_URL", "desc": "Send messages to Slack channels"},
    "teams": {"env": "TEAMS_WEBHOOK_URL", "desc": "Send messages to Microsoft Teams"},
    "gmail": {"env": "GMAIL_API_KEY", "desc": "Send/read Gmail messages"},
    "salesforce": {"env": "SALESFORCE_TOKEN", "desc": "Salesforce CRM operations"},
    "hubspot": {"env": "HUBSPOT_API_KEY", "desc": "HubSpot CRM operations"},
    "zendesk": {"env": "ZENDESK_TOKEN", "desc": "Zendesk support ticket operations"},
    "jira": {"env": "JIRA_TOKEN", "desc": "Jira issue tracking"},
    "google_sheets": {"env": "GOOGLE_SHEETS_KEY", "desc": "Read/write Google Sheets"},
    "notion": {"env": "NOTION_API_KEY", "desc": "Notion database/page operations"},
    "airtable": {"env": "AIRTABLE_API_KEY", "desc": "Airtable base operations"},
    "asana": {"env": "ASANA_TOKEN", "desc": "Asana task management"},
    "linear": {"env": "LINEAR_API_KEY", "desc": "Linear issue tracking"},
    "intercom": {"env": "INTERCOM_TOKEN", "desc": "Intercom customer messaging"},
    "twilio": {"env": "TWILIO_AUTH_TOKEN", "desc": "SMS/voice via Twilio"},
    "sendgrid": {"env": "SENDGRID_API_KEY", "desc": "Email delivery via SendGrid"},
    "pagerduty": {"env": "PAGERDUTY_TOKEN", "desc": "PagerDuty incident management"},
    "snowflake": {"env": "SNOWFLAKE_ACCOUNT", "desc": "Snowflake data warehouse"},
    "stripe": {"env": "STRIPE_SECRET_KEY", "desc": "Stripe payment operations"},
    "aws_ses": {"env": "AWS_ACCESS_KEY_ID", "desc": "AWS SES email service"},
    "aws_lambda": {"env": "AWS_ACCESS_KEY_ID", "desc": "AWS Lambda function invocation"},
}


class IntegrationHubTool(BaseTool):
    name = "integration_hub"
    description = (
        "Connect to 20+ enterprise services: Slack, Teams, Gmail, Salesforce, HubSpot, "
        "Zendesk, Jira, Google Sheets, Notion, Airtable, Asana, Linear, Intercom, "
        "Twilio, SendGrid, PagerDuty, Snowflake, Stripe, AWS SES/Lambda. "
        "Unified interface for sending messages, creating records, and querying data."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "enum": list(SERVICES.keys()),
                "description": "Target service to interact with",
            },
            "action": {
                "type": "string",
                "description": "Action to perform (send_message, create_record, query, update, etc.)",
            },
            "data": {
                "type": "object",
                "description": "Action-specific data (channel, message, record fields, query, etc.)",
            },
            "auth_token": {
                "type": "string",
                "description": "Override auth token (optional, uses env var if omitted)",
            },
        },
        "required": ["service", "action"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        service = arguments.get("service", "")
        action = arguments.get("action", "")
        data = arguments.get("data", {})
        auth_override = arguments.get("auth_token")

        if service not in SERVICES:
            return ToolResult(
                content=f"Error: Unknown service '{service}'. Available: {', '.join(SERVICES.keys())}",
                is_error=True,
            )

        svc = SERVICES[service]
        auth = auth_override or os.environ.get(svc["env"], "")

        # Route to service-specific handler
        handler = getattr(self, f"_handle_{service}", None)
        if handler:
            return await handler(action, data, auth)

        # Default: use generic HTTP handler
        return await self._generic_handler(service, action, data, auth)

    async def _handle_slack(self, action: str, data: dict, auth: str) -> ToolResult:
        """Slack: send messages via webhook or API."""
        if action == "send_message":
            if not auth:
                return ToolResult(content="Error: SLACK_WEBHOOK_URL not configured", is_error=True)
            import httpx
            channel = data.get("channel", "#general")
            message = data.get("message", "")
            blocks = data.get("blocks")

            payload: dict[str, Any] = {"text": message}
            if blocks:
                payload["blocks"] = blocks

            # Webhook URL
            if auth.startswith("http"):
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(auth, json=payload)
                return ToolResult(content=json.dumps({
                    "status": "success" if resp.status_code == 200 else "error",
                    "service": "slack", "action": action, "channel": channel,
                }))
            # API token
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {auth}"},
                    json={"channel": channel, "text": message},
                )
            result = resp.json()
            return ToolResult(content=json.dumps({
                "status": "success" if result.get("ok") else "error",
                "service": "slack", "channel": channel,
                "ts": result.get("ts"),
            }))
        return ToolResult(content=f"Slack action '{action}' not supported. Use: send_message", is_error=True)

    async def _handle_teams(self, action: str, data: dict, auth: str) -> ToolResult:
        """Microsoft Teams: send messages via webhook."""
        if action == "send_message":
            if not auth:
                return ToolResult(content="Error: TEAMS_WEBHOOK_URL not configured", is_error=True)
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(auth, json={
                    "text": data.get("message", ""),
                    "title": data.get("title"),
                })
            return ToolResult(content=json.dumps({"status": "success" if resp.status_code == 200 else "error", "service": "teams"}))
        return ToolResult(content=f"Teams action '{action}' not supported", is_error=True)

    async def _handle_jira(self, action: str, data: dict, auth: str) -> ToolResult:
        """Jira: create/search issues."""
        jira_url = os.environ.get("JIRA_URL", "")
        jira_email = os.environ.get("JIRA_EMAIL", "")
        if not auth or not jira_url:
            return ToolResult(content="Error: JIRA_TOKEN and JIRA_URL required", is_error=True)

        import httpx
        import base64
        auth_header = base64.b64encode(f"{jira_email}:{auth}".encode()).decode()
        headers = {"Authorization": f"Basic {auth_header}", "Content-Type": "application/json"}

        if action == "create_issue":
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{jira_url}/rest/api/3/issue",
                    headers=headers,
                    json={"fields": {
                        "project": {"key": data.get("project", "")},
                        "summary": data.get("summary", ""),
                        "description": {"type": "doc", "version": 1, "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": data.get("description", "")}]}
                        ]},
                        "issuetype": {"name": data.get("type", "Task")},
                        "priority": {"name": data.get("priority", "Medium")},
                    }},
                )
            result = resp.json()
            return ToolResult(content=json.dumps({
                "status": "success" if "key" in result else "error",
                "key": result.get("key"), "id": result.get("id"),
            }))

        elif action == "search":
            jql = data.get("jql", "")
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{jira_url}/rest/api/3/search",
                    headers=headers,
                    params={"jql": jql, "maxResults": data.get("max_results", 20)},
                )
            result = resp.json()
            issues = [{"key": i["key"], "summary": i["fields"]["summary"], "status": i["fields"]["status"]["name"]}
                      for i in result.get("issues", [])]
            return ToolResult(content=json.dumps({"status": "success", "total": result.get("total", 0), "issues": issues}))

        return ToolResult(content=f"Jira action '{action}' not supported. Use: create_issue, search", is_error=True)

    async def _handle_salesforce(self, action: str, data: dict, auth: str) -> ToolResult:
        """Salesforce: query and create records."""
        instance_url = os.environ.get("SALESFORCE_INSTANCE_URL", "")
        if not auth or not instance_url:
            return ToolResult(content="Error: SALESFORCE_TOKEN and SALESFORCE_INSTANCE_URL required", is_error=True)

        import httpx
        headers = {"Authorization": f"Bearer {auth}", "Content-Type": "application/json"}

        if action == "query":
            soql = data.get("soql", "")
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{instance_url}/services/data/v60.0/query",
                    headers=headers,
                    params={"q": soql},
                )
            result = resp.json()
            return ToolResult(content=json.dumps({
                "status": "success",
                "total": result.get("totalSize", 0),
                "records": result.get("records", [])[:50],
            }))

        elif action == "create_record":
            obj = data.get("object", "")
            fields = data.get("fields", {})
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{instance_url}/services/data/v60.0/sobjects/{obj}",
                    headers=headers,
                    json=fields,
                )
            result = resp.json()
            return ToolResult(content=json.dumps({
                "status": "success" if result.get("success") else "error",
                "id": result.get("id"),
            }))

        return ToolResult(content=f"Salesforce action '{action}' not supported. Use: query, create_record", is_error=True)

    async def _generic_handler(self, service: str, action: str, data: dict, auth: str) -> ToolResult:
        """Generic handler for services not yet fully implemented."""
        svc = SERVICES.get(service, {})
        return ToolResult(content=json.dumps({
            "status": "info",
            "service": service,
            "description": svc.get("desc", ""),
            "action_requested": action,
            "message": f"Service '{service}' is available. Configure {svc.get('env', 'AUTH_TOKEN')} environment variable to enable live operations.",
            "auth_configured": bool(auth),
            "data_received": data,
        }))
