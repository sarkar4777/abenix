"""Pre-built API connectors for common external services."""

from __future__ import annotations

import json
import os
from typing import Any

from engine.tools.base import BaseTool, ToolResult

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY", "")
GOOGLE_SHEETS_CREDENTIALS = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
JIRA_URL = os.environ.get("JIRA_URL", "")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_TOKEN = os.environ.get("JIRA_TOKEN", "")


class ApiConnectorTool(BaseTool):
    name = "api_connector"
    description = (
        "Connect to popular external services: send Slack messages, read/write "
        "Airtable records, interact with Notion databases, create Jira tickets, "
        "and push data to Google Sheets. Pre-configured connectors with simple "
        "interfaces for common integrations."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "enum": [
                    "slack", "airtable_read", "airtable_write",
                    "notion_query", "notion_create", "jira_create",
                    "jira_search", "google_sheets_read", "google_sheets_append",
                ],
                "description": "Service and action to execute",
            },
            "params": {
                "type": "object",
                "description": "Service-specific parameters",
            },
        },
        "required": ["service", "params"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        service = arguments.get("service", "")
        params = arguments.get("params", {})

        handlers = {
            "slack": self._slack_send,
            "airtable_read": self._airtable_read,
            "airtable_write": self._airtable_write,
            "notion_query": self._notion_query,
            "notion_create": self._notion_create,
            "jira_create": self._jira_create,
            "jira_search": self._jira_search,
            "google_sheets_read": self._sheets_read,
            "google_sheets_append": self._sheets_append,
        }

        fn = handlers.get(service)
        if not fn:
            return ToolResult(
                content=f"Unknown service: {service}. Available: {list(handlers.keys())}",
                is_error=True,
            )

        try:
            result = await fn(params)
            output = json.dumps(result, indent=2, default=str)
            return ToolResult(content=output, metadata={"service": service})
        except Exception as e:
            return ToolResult(content=f"Connector error: {e}", is_error=True)

    async def _slack_send(self, params: dict[str, Any]) -> dict[str, Any]:
        message = params.get("message", "")
        channel = params.get("channel", "#general")
        webhook = params.get("webhook_url", SLACK_WEBHOOK_URL)

        if not message:
            return {"error": "message is required"}

        if not webhook:
            return {
                "status": "mock",
                "message": "Slack webhook not configured. Would send:",
                "channel": channel,
                "text": message,
            }

        import aiohttp
        payload = {"text": message}
        if channel.startswith("#"):
            payload["channel"] = channel

        async with aiohttp.ClientSession() as session:
            async with session.post(webhook, json=payload) as resp:
                return {
                    "status": "success" if resp.status == 200 else "error",
                    "channel": channel,
                    "response_status": resp.status,
                }

    async def _airtable_read(self, params: dict[str, Any]) -> dict[str, Any]:
        base_id = params.get("base_id", "")
        table_name = params.get("table_name", "")
        view = params.get("view", "")
        max_records = params.get("max_records", 100)

        if not base_id or not table_name:
            return {"error": "base_id and table_name are required"}

        if not AIRTABLE_API_KEY:
            return {
                "status": "mock",
                "message": "Airtable API key not configured",
                "would_read": f"{base_id}/{table_name}",
                "sample_data": [
                    {"id": "rec1", "fields": {"Name": "Sample Record 1", "Status": "Active"}},
                    {"id": "rec2", "fields": {"Name": "Sample Record 2", "Status": "Pending"}},
                ],
            }

        import aiohttp
        url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
        headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
        query_params: dict[str, Any] = {"maxRecords": max_records}
        if view:
            query_params["view"] = view

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=query_params) as resp:
                data = await resp.json()
                records = data.get("records", [])
                return {
                    "status": "success",
                    "record_count": len(records),
                    "records": [{"id": r["id"], "fields": r["fields"]} for r in records],
                }

    async def _airtable_write(self, params: dict[str, Any]) -> dict[str, Any]:
        base_id = params.get("base_id", "")
        table_name = params.get("table_name", "")
        records = params.get("records", [])

        if not base_id or not table_name or not records:
            return {"error": "base_id, table_name, and records are required"}

        if not AIRTABLE_API_KEY:
            return {
                "status": "mock",
                "message": "Airtable API key not configured",
                "would_write": len(records),
                "to": f"{base_id}/{table_name}",
            }

        import aiohttp
        url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {"records": [{"fields": r} for r in records]}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                data = await resp.json()
                return {
                    "status": "success" if resp.status == 200 else "error",
                    "created": len(data.get("records", [])),
                }

    async def _notion_query(self, params: dict[str, Any]) -> dict[str, Any]:
        database_id = params.get("database_id", "")

        if not database_id:
            return {"error": "database_id is required"}

        if not NOTION_API_KEY:
            return {
                "status": "mock",
                "message": "Notion API key not configured",
                "would_query": database_id,
                "sample_data": [
                    {"id": "page1", "properties": {"Name": {"title": [{"text": {"content": "Sample Page"}}]}}},
                ],
            }

        import aiohttp
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        headers = {
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json={}) as resp:
                data = await resp.json()
                return {
                    "status": "success",
                    "results": data.get("results", [])[:50],
                    "has_more": data.get("has_more", False),
                }

    async def _notion_create(self, params: dict[str, Any]) -> dict[str, Any]:
        database_id = params.get("database_id", "")
        properties = params.get("properties", {})

        if not database_id or not properties:
            return {"error": "database_id and properties are required"}

        if not NOTION_API_KEY:
            return {
                "status": "mock",
                "message": "Notion API key not configured",
                "would_create_in": database_id,
                "properties": properties,
            }

        import aiohttp
        url = "https://api.notion.com/v1/pages"
        headers = {
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        payload = {"parent": {"database_id": database_id}, "properties": properties}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                data = await resp.json()
                return {"status": "success" if resp.status == 200 else "error", "page_id": data.get("id")}

    async def _jira_create(self, params: dict[str, Any]) -> dict[str, Any]:
        project = params.get("project", "")
        summary = params.get("summary", "")
        description = params.get("description", "")
        issue_type = params.get("issue_type", "Task")

        if not project or not summary:
            return {"error": "project and summary are required"}

        if not JIRA_URL or not JIRA_TOKEN:
            return {
                "status": "mock",
                "message": "Jira not configured",
                "would_create": {
                    "project": project,
                    "summary": summary,
                    "type": issue_type,
                },
            }

        import aiohttp
        import base64
        url = f"{JIRA_URL}/rest/api/3/issue"
        auth = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
        payload = {
            "fields": {
                "project": {"key": project},
                "summary": summary,
                "description": {"type": "doc", "version": 1, "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": description}]}
                ]},
                "issuetype": {"name": issue_type},
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                data = await resp.json()
                return {
                    "status": "success" if resp.status == 201 else "error",
                    "key": data.get("key"),
                    "url": f"{JIRA_URL}/browse/{data.get('key')}",
                }

    async def _jira_search(self, params: dict[str, Any]) -> dict[str, Any]:
        jql = params.get("jql", "")
        if not jql:
            return {"error": "jql query is required"}

        if not JIRA_URL or not JIRA_TOKEN:
            return {
                "status": "mock",
                "message": "Jira not configured",
                "jql": jql,
                "sample_results": [
                    {"key": "PROJ-1", "summary": "Sample issue", "status": "Open"},
                ],
            }

        import aiohttp
        import base64
        url = f"{JIRA_URL}/rest/api/3/search"
        auth = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json={"jql": jql, "maxResults": 50}) as resp:
                data = await resp.json()
                issues = data.get("issues", [])
                return {
                    "status": "success",
                    "total": data.get("total", 0),
                    "issues": [
                        {
                            "key": i["key"],
                            "summary": i["fields"].get("summary"),
                            "status": i["fields"].get("status", {}).get("name"),
                            "assignee": (i["fields"].get("assignee") or {}).get("displayName"),
                        }
                        for i in issues
                    ],
                }

    async def _sheets_read(self, params: dict[str, Any]) -> dict[str, Any]:
        spreadsheet_id = params.get("spreadsheet_id", "")
        sheet_range = params.get("range", "Sheet1!A:Z")

        if not spreadsheet_id:
            return {"error": "spreadsheet_id is required"}

        if not GOOGLE_SHEETS_CREDENTIALS:
            return {
                "status": "mock",
                "message": "Google Sheets credentials not configured",
                "would_read": f"{spreadsheet_id} / {sheet_range}",
                "sample_data": [["Header1", "Header2"], ["Value1", "Value2"]],
            }

        return {"status": "not_implemented", "message": "Google Sheets integration requires OAuth setup"}

    async def _sheets_append(self, params: dict[str, Any]) -> dict[str, Any]:
        spreadsheet_id = params.get("spreadsheet_id", "")
        sheet_range = params.get("range", "Sheet1!A:A")
        values = params.get("values", [])

        if not spreadsheet_id or not values:
            return {"error": "spreadsheet_id and values are required"}

        if not GOOGLE_SHEETS_CREDENTIALS:
            return {
                "status": "mock",
                "message": "Google Sheets credentials not configured",
                "would_append": len(values),
                "to": f"{spreadsheet_id} / {sheet_range}",
            }

        return {"status": "not_implemented", "message": "Google Sheets integration requires OAuth setup"}
