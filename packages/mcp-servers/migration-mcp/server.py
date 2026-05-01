"""Migration MCP Server — orchestration tools for data migration tracking."""

from __future__ import annotations

import json
from typing import Any


def get_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "migration_plan",
            "description": "Create or update a migration plan. Organizes tables into waves based on dependencies, size, and priority.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "update", "get"]},
                    "plan_id": {"type": "string"},
                    "tables": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "schema": {"type": "string"},
                                "table": {"type": "string"},
                                "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                                "size_gb": {"type": "number"},
                                "depends_on": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                    "wave_count": {"type": "integer", "default": 6},
                    "strategy": {"type": "string", "enum": ["medallion", "data_vault", "hybrid"], "default": "medallion"},
                },
                "required": ["action"],
            },
        },
        {
            "name": "migration_status",
            "description": "Get migration status for specific tables or all tables.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                    "schema": {"type": "string"},
                    "table": {"type": "string"},
                    "wave": {"type": "integer"},
                    "status_filter": {"type": "string", "enum": ["pending", "in_progress", "completed", "failed", "validated"]},
                },
            },
        },
        {
            "name": "migration_validate",
            "description": "Run validation checks comparing source (Exasol) and target (BigQuery) data.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "schema": {"type": "string"},
                    "table": {"type": "string"},
                    "checks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Checks: 'row_count', 'checksum', 'sample_compare', 'schema_match', 'null_distribution'",
                    },
                    "sample_size": {"type": "integer", "default": 1000},
                },
                "required": ["schema", "table"],
            },
        },
        {
            "name": "migration_rollback",
            "description": "Generate a rollback plan for a failed migration step.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                    "failed_step": {"type": "string"},
                    "error_message": {"type": "string"},
                },
                "required": ["plan_id", "failed_step"],
            },
        },
        {
            "name": "migration_progress",
            "description": "Get overall migration progress metrics: tables migrated, data volume, time estimates.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                },
            },
        },
    ]


async def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "migration_plan":
        return {
            "status": "success", "mode": "demo", "plan_id": "MIG-2025-001",
            "waves": [
                {"wave": 1, "name": "Reference Data", "tables": 45, "size_gb": 2.3, "status": "COMPLETED", "duration_hours": 4},
                {"wave": 2, "name": "Finance Core", "tables": 82, "size_gb": 45.6, "status": "IN_PROGRESS", "duration_hours": 18},
                {"wave": 3, "name": "Operations", "tables": 120, "size_gb": 89.2, "status": "PLANNED", "duration_hours": 36},
                {"wave": 4, "name": "Analytics Views", "tables": 95, "size_gb": 12.1, "status": "PLANNED", "duration_hours": 8},
                {"wave": 5, "name": "Reports & Dashboards", "tables": 67, "size_gb": 5.4, "status": "PLANNED", "duration_hours": 12},
                {"wave": 6, "name": "Archive & Audit", "tables": 78, "size_gb": 1.8, "status": "PLANNED", "duration_hours": 6},
            ],
            "total_tables": 487, "total_size_gb": 156.4, "estimated_hours": 84,
        }

    if name == "migration_status":
        return {
            "status": "success", "mode": "demo",
            "plan_id": arguments.get("plan_id", "MIG-2025-001"),
            "overall_progress": 26.3,
            "tables_migrated": 128, "tables_total": 487,
            "data_migrated_gb": 47.9, "data_total_gb": 156.4,
            "current_wave": 2, "current_wave_name": "Finance Core",
            "active_tables": ["TRANSACTIONS", "POSITIONS", "FX_RATES"],
            "errors": 0, "warnings": 3,
            "estimated_completion": "2025-03-28T18:00:00Z",
        }

    if name == "migration_validate":
        return {
            "status": "success", "mode": "demo",
            "validation_type": arguments.get("validation_type", "row_count"),
            "table": arguments.get("table", "FINANCE.TRANSACTIONS"),
            "source_count": 2847593, "target_count": 2847593,
            "match": True, "discrepancy": 0,
            "checks_passed": 7, "checks_total": 7,
        }

    if name == "migration_rollback":
        return {
            "status": "success", "mode": "demo",
            "table": arguments.get("table", "FINANCE.TRANSACTIONS"),
            "action": "rollback_prepared",
            "bigquery_table_dropped": False,
            "query_router_reverted": True,
            "message": "Rollback plan ready. Requires human approval to execute.",
        }

    if name == "migration_progress":
        return {
            "status": "success", "mode": "demo",
            "tables_by_status": {"completed": 128, "in_progress": 3, "planned": 356, "failed": 0},
            "data_volume": {"migrated_gb": 47.9, "remaining_gb": 108.5, "total_gb": 156.4},
            "time": {"elapsed_hours": 22, "remaining_hours": 62, "total_estimated_hours": 84},
            "cost": {"compute_usd": 234.50, "storage_usd": 12.80, "network_usd": 45.20, "total_usd": 292.50},
            "quality": {"validations_passed": 128, "validations_failed": 0, "warnings": 3},
        }

    return {"status": "error", "message": f"Unknown tool: {name}"}


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Migration MCP Server")

    @app.post("/mcp")
    async def mcp_endpoint(request: Request) -> JSONResponse:
        body = await request.json()
        method = body.get("method")
        if method == "initialize":
            return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "migration-mcp", "version": "1.0.0"},
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

    uvicorn.run(app, host="0.0.0.0", port=9004)
