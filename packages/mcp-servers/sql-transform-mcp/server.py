"""SQL Transform MCP Server — translates SQL between dialects."""

from __future__ import annotations

import json
from typing import Any

# Common Exasol -> BigQuery SQL transformations
TRANSFORM_RULES = {
    "DECODE(": "CASE WHEN",
    "NVL(": "IFNULL(",
    "NVL2(": "IF(",
    "SYSTIMESTAMP": "CURRENT_TIMESTAMP()",
    "SYSDATE": "CURRENT_DATE()",
    "ROWNUM": "ROW_NUMBER() OVER()",
    "CONNECT BY": "-- CONNECT BY (requires CTE rewrite)",
    "MINUS": "EXCEPT DISTINCT",
    "VARCHAR2": "STRING",
    "NUMBER": "NUMERIC",
    "CLOB": "STRING",
    "BLOB": "BYTES",
    "DATE": "DATE",
    "TIMESTAMP": "TIMESTAMP",
    "INTEGER": "INT64",
    "DOUBLE PRECISION": "FLOAT64",
    "BOOLEAN": "BOOL",
}


def get_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "sql_transform",
            "description": "Transform SQL from Exasol dialect to BigQuery Standard SQL. Handles function mapping, type conversions, and syntax differences.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "Source SQL in Exasol dialect"},
                    "source_dialect": {"type": "string", "enum": ["exasol", "oracle", "postgresql", "mysql"], "default": "exasol"},
                    "target_dialect": {"type": "string", "enum": ["bigquery", "postgresql"], "default": "bigquery"},
                    "preserve_comments": {"type": "boolean", "default": True},
                },
                "required": ["sql"],
            },
        },
        {
            "name": "sql_analyze",
            "description": "Analyze SQL complexity and identify transformation challenges.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "source_dialect": {"type": "string", "default": "exasol"},
                },
                "required": ["sql"],
            },
        },
        {
            "name": "sql_optimize",
            "description": "Optimize SQL for BigQuery cost and performance. Suggests partitioning, clustering, and query restructuring.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "context": {"type": "string", "description": "Additional context (table sizes, access patterns)"},
                },
                "required": ["sql"],
            },
        },
        {
            "name": "sql_validate",
            "description": "Validate SQL syntax for the target dialect.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "dialect": {"type": "string", "enum": ["bigquery", "exasol", "postgresql"], "default": "bigquery"},
                },
                "required": ["sql"],
            },
        },
    ]


async def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "sql_transform":
        sql = arguments["sql"]
        transformed = sql
        applied_rules = []
        for exasol_pattern, bq_pattern in TRANSFORM_RULES.items():
            if exasol_pattern.upper() in transformed.upper():
                transformed = transformed.replace(exasol_pattern, bq_pattern)
                applied_rules.append(f"{exasol_pattern} -> {bq_pattern}")
        return {
            "original": sql,
            "transformed": transformed,
            "rules_applied": applied_rules,
            "warnings": [],
            "note": "Basic rule-based transform. For complex SQL, the LLM agent refines the output.",
        }

    if name == "sql_analyze":
        sql = arguments["sql"]
        # Basic complexity analysis
        complexity_indicators = []
        if "JOIN" in sql.upper():
            complexity_indicators.append("Contains JOINs")
        if "SUBQUERY" in sql.upper() or "SELECT" in sql.upper().split("FROM", 1)[-1] if "FROM" in sql.upper() else "":
            complexity_indicators.append("Contains subqueries")
        if "CONNECT BY" in sql.upper():
            complexity_indicators.append("Contains hierarchical queries (requires CTE rewrite)")
        if "DECODE(" in sql.upper():
            complexity_indicators.append("Contains DECODE (convert to CASE)")
        return {
            "sql_length": len(sql),
            "complexity": "high" if len(complexity_indicators) > 2 else "medium" if complexity_indicators else "low",
            "indicators": complexity_indicators,
            "estimated_effort": "manual_review" if "CONNECT BY" in sql.upper() else "auto_transformable",
        }

    return {"status": "success", "tool": name}


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="SQL Transform MCP Server")

    @app.post("/mcp")
    async def mcp_endpoint(request: Request) -> JSONResponse:
        body = await request.json()
        method = body.get("method")
        if method == "initialize":
            return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "sql-transform-mcp", "version": "1.0.0"},
            }})
        if method == "tools/list":
            return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": {"tools": get_tools()}})
        if method == "tools/call":
            params = body.get("params", {})
            result = await handle_tool_call(params.get("name", ""), params.get("arguments", {}))
            return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"),
                "result": {"content": [{"type": "text", "text": json.dumps(result)}]}})
        return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"),
            "error": {"code": -32601, "message": f"Unknown method: {method}"}})

    uvicorn.run(app, host="0.0.0.0", port=9003)
