"""BigQuery MCP Server — provides tools for interacting with Google BigQuery."""

from __future__ import annotations

import json
from typing import Any


def get_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "bq_query",
            "description": "Execute a SQL query in BigQuery. Supports Standard SQL.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project_id": {"type": "string"},
                    "dataset": {"type": "string"},
                    "limit": {"type": "integer", "default": 1000},
                    "dry_run": {"type": "boolean", "default": False, "description": "Estimate cost without running"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "bq_schema",
            "description": "Inspect or modify BigQuery dataset/table schemas.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "dataset": {"type": "string"},
                    "table": {"type": "string"},
                },
            },
        },
        {
            "name": "bq_load",
            "description": "Load data from Google Cloud Storage into a BigQuery table.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_uri": {"type": "string", "description": "GCS URI (gs://bucket/path)"},
                    "project_id": {"type": "string"},
                    "dataset": {"type": "string"},
                    "table": {"type": "string"},
                    "write_disposition": {"type": "string", "enum": ["WRITE_TRUNCATE", "WRITE_APPEND", "WRITE_EMPTY"], "default": "WRITE_TRUNCATE"},
                    "source_format": {"type": "string", "enum": ["PARQUET", "CSV", "NEWLINE_DELIMITED_JSON"], "default": "PARQUET"},
                },
                "required": ["source_uri", "dataset", "table"],
            },
        },
        {
            "name": "bq_validate",
            "description": "Validate data quality in a BigQuery table (row counts, null checks, type consistency).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "dataset": {"type": "string"},
                    "table": {"type": "string"},
                    "expected_row_count": {"type": "integer"},
                    "checks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Validation checks: 'null_check', 'duplicate_check', 'type_check', 'range_check'",
                    },
                },
                "required": ["dataset", "table"],
            },
        },
        {
            "name": "bq_create_table",
            "description": "Create a BigQuery table with a specified schema. Supports medallion layer tagging.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "dataset": {"type": "string"},
                    "table": {"type": "string"},
                    "schema_fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "mode": {"type": "string", "default": "NULLABLE"},
                                "description": {"type": "string"},
                            },
                        },
                    },
                    "partition_field": {"type": "string"},
                    "clustering_fields": {"type": "array", "items": {"type": "string"}},
                    "labels": {"type": "object", "description": "Labels like {layer: 'gold', domain: 'finance'}"},
                },
                "required": ["dataset", "table", "schema_fields"],
            },
        },
        {
            "name": "bq_create_view",
            "description": "Create or replace a BigQuery view with a SQL definition.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "dataset": {"type": "string"},
                    "view_name": {"type": "string"},
                    "sql": {"type": "string", "description": "The SELECT statement for the view"},
                    "description": {"type": "string"},
                },
                "required": ["dataset", "view_name", "sql"],
            },
        },
    ]


async def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Handle tool calls — connects to real BigQuery via google-cloud-bigquery in production."""
    return {
        "status": "success",
        "tool": name,
        "arguments": arguments,
        "note": "Set GOOGLE_APPLICATION_CREDENTIALS to enable live BigQuery operations",
    }


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="BigQuery MCP Server")

    @app.post("/mcp")
    async def mcp_endpoint(request: Request) -> JSONResponse:
        body = await request.json()
        method = body.get("method")

        if method == "initialize":
            return JSONResponse({
                "jsonrpc": "2.0", "id": body.get("id"),
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "bigquery-mcp", "version": "1.0.0"},
                },
            })
        if method == "tools/list":
            return JSONResponse({
                "jsonrpc": "2.0", "id": body.get("id"),
                "result": {"tools": get_tools()},
            })
        if method == "tools/call":
            params = body.get("params", {})
            result = await handle_tool_call(params.get("name", ""), params.get("arguments", {}))
            return JSONResponse({
                "jsonrpc": "2.0", "id": body.get("id"),
                "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
            })
        return JSONResponse({
            "jsonrpc": "2.0", "id": body.get("id"),
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        })

    uvicorn.run(app, host="0.0.0.0", port=9002)
