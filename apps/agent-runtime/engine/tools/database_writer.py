"""Database Writer Tool — INSERT/UPSERT rows into PostgreSQL."""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class DatabaseWriterTool(BaseTool):
    name = "database_writer"
    description = (
        "Write data to PostgreSQL tables (INSERT or UPSERT). "
        "Tables must be prefixed with 'af_' for safety. Max 10,000 rows per call. "
        "Can also CREATE TABLE IF NOT EXISTS."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["insert", "upsert", "create_table"],
                "description": "Write operation to perform",
            },
            "table": {
                "type": "string",
                "description": "Table name (must start with 'af_')",
            },
            "rows": {
                "type": "array",
                "description": "Array of row objects to insert (for insert/upsert)",
                "items": {"type": "object"},
            },
            "columns": {
                "type": "object",
                "description": "Column definitions for create_table: {name: type}",
            },
            "conflict_column": {
                "type": "string",
                "description": "Column for ON CONFLICT (upsert only)",
            },
            "connection_string": {
                "type": "string",
                "description": "PostgreSQL connection string (optional, uses platform DB if omitted)",
            },
        },
        "required": ["operation", "table"],
    }

    def __init__(self, default_connection: str = ""):
        self._default_conn = default_connection

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        operation = arguments.get("operation", "")
        table = arguments.get("table", "")
        conn_str = arguments.get("connection_string", "") or self._default_conn

        if not table.startswith("af_"):
            return ToolResult(
                content="Error: Table name must start with 'af_' for safety. Example: af_repo_analyses",
                is_error=True,
            )

        if not conn_str:
            import os

            conn_str = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "")
            if not conn_str:
                return ToolResult(
                    content="Error: No database connection available", is_error=True
                )
        else:
            conn_str = conn_str.replace("+asyncpg", "")

        try:
            import asyncpg

            conn = await asyncpg.connect(conn_str, timeout=30)
            try:
                if operation == "create_table":
                    columns = arguments.get("columns", {})
                    if not columns:
                        return ToolResult(
                            content="Error: columns required for create_table",
                            is_error=True,
                        )
                    col_defs = ", ".join(
                        f"{name} {dtype}" for name, dtype in columns.items()
                    )
                    await conn.execute(
                        f"CREATE TABLE IF NOT EXISTS {table} (id SERIAL PRIMARY KEY, {col_defs}, created_at TIMESTAMPTZ DEFAULT now())"
                    )
                    return ToolResult(
                        content=json.dumps(
                            {"status": "success", "table": table, "action": "created"}
                        )
                    )

                elif operation in ("insert", "upsert"):
                    rows = arguments.get("rows", [])
                    if not rows:
                        return ToolResult(
                            content="Error: rows array is required", is_error=True
                        )
                    if len(rows) > 10000:
                        return ToolResult(
                            content="Error: Max 10,000 rows per call", is_error=True
                        )

                    # Auto-create table if it doesn't exist
                    cols = list(rows[0].keys())
                    col_types = []
                    for k, v in rows[0].items():
                        if isinstance(v, int):
                            col_types.append(f"{k} BIGINT")
                        elif isinstance(v, float):
                            col_types.append(f"{k} DOUBLE PRECISION")
                        elif isinstance(v, bool):
                            col_types.append(f"{k} BOOLEAN")
                        elif isinstance(v, dict) or isinstance(v, list):
                            col_types.append(f"{k} JSONB")
                        else:
                            col_types.append(f"{k} TEXT")

                    await conn.execute(
                        f"CREATE TABLE IF NOT EXISTS {table} (id SERIAL PRIMARY KEY, {', '.join(col_types)}, created_at TIMESTAMPTZ DEFAULT now())"
                    )

                    # Insert rows
                    placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
                    col_names = ", ".join(cols)

                    if operation == "upsert" and arguments.get("conflict_column"):
                        conflict_col = arguments["conflict_column"]
                        update_set = ", ".join(
                            f"{c} = EXCLUDED.{c}" for c in cols if c != conflict_col
                        )
                        sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT ({conflict_col}) DO UPDATE SET {update_set}"
                    else:
                        sql = (
                            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
                        )

                    inserted = 0
                    for row in rows:
                        values = []
                        for c in cols:
                            v = row.get(c)
                            if isinstance(v, (dict, list)):
                                v = json.dumps(v)
                            values.append(v)
                        await conn.execute(sql, *values)
                        inserted += 1

                    return ToolResult(
                        content=json.dumps(
                            {
                                "status": "success",
                                "table": table,
                                "operation": operation,
                                "rows_written": inserted,
                                "columns": cols,
                            }
                        )
                    )

                return ToolResult(
                    content=f"Error: Unknown operation: {operation}", is_error=True
                )

            finally:
                await conn.close()

        except ImportError:
            return ToolResult(content="Error: asyncpg not installed", is_error=True)
        except Exception as e:
            return ToolResult(
                content=f"Database write error: {str(e)[:500]}", is_error=True
            )
