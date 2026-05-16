"""Database Query Tool — Execute read-only SQL against enterprise databases."""

from __future__ import annotations

import re
from typing import Any

from engine.tools.base import BaseTool, ToolResult

# Only allow read-only SQL
ALLOWED_PREFIXES = ("select", "with", "explain", "show", "describe")
FORBIDDEN_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "grant",
    "revoke",
)


class DatabaseQueryTool(BaseTool):
    name = "database_query"
    description = (
        "Execute read-only SQL queries against PostgreSQL databases. "
        "Read-only (SELECT only), parameterized, 30s timeout. Returns up to 10,000 rows."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SQL query to execute (SELECT only)",
            },
            "connection_string": {
                "type": "string",
                "description": "Database connection string (e.g., postgresql://user:pass@host:5432/db). If omitted, uses the platform database.",
            },
            "max_rows": {
                "type": "integer",
                "description": "Maximum rows to return (default: 1000, max: 10000)",
                "default": 1000,
            },
            "params": {
                "type": "object",
                "description": "Query parameters for parameterized queries",
                "default": {},
            },
        },
        "required": ["query"],
    }

    def __init__(self, default_connection: str = ""):
        import os

        # Fallback: if no default provided, use the platform's own database
        # (with asyncpg -> psycopg2 conversion for sync drivers used by SQL tools)
        env_url = os.environ.get("DATABASE_URL", "")
        # Convert async driver URLs to sync for psycopg2-based tools
        env_url = env_url.replace("+asyncpg", "").replace(
            "postgresql+asyncpg", "postgresql"
        )
        self._default_conn = default_connection or env_url

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments.get("query", "").strip()
        conn_str = arguments.get("connection_string", "") or self._default_conn
        max_rows = min(arguments.get("max_rows", 1000), 10_000)
        arguments.get("params", {})

        if not query:
            return ToolResult(content="Error: query is required", is_error=True)

        # Security: validate read-only
        normalized = re.sub(r"\s+", " ", query.lower().strip())
        first_word = normalized.split()[0] if normalized else ""

        if first_word not in ALLOWED_PREFIXES:
            return ToolResult(
                content=f"Error: Only read-only queries allowed (SELECT, WITH, EXPLAIN). Got: {first_word.upper()}",
                is_error=True,
            )

        for kw in FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{kw}\b", normalized):
                return ToolResult(
                    content=f"Error: Forbidden keyword '{kw.upper()}' detected. Only SELECT queries allowed.",
                    is_error=True,
                )

        if not conn_str:
            return ToolResult(
                content="Error: No connection_string provided and no default configured. "
                "Set a connection string in the agent's tool configuration or pass it as a parameter.",
                is_error=True,
            )

        try:
            import asyncpg

            # Parse connection string
            if conn_str.startswith("postgresql"):
                # asyncpg needs raw postgresql:// (not postgresql+asyncpg://)
                clean_conn = conn_str.replace("+asyncpg", "")
                # Strip sqlalchemy-style ssl query params; asyncpg handles ssl
                # via the ssl kwarg, not the URL.
                ssl_mode = None
                if "?ssl=" in clean_conn or "&ssl=" in clean_conn:
                    from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

                    parsed = urlparse(clean_conn)
                    q = dict(parse_qsl(parsed.query))
                    raw_ssl = q.pop("ssl", "") or q.pop("sslmode", "")
                    if raw_ssl in ("disable", "off", "false", "0", ""):
                        ssl_mode = False
                    elif raw_ssl in (
                        "require",
                        "verify-ca",
                        "verify-full",
                        "on",
                        "true",
                    ):
                        ssl_mode = True
                    clean_conn = urlunparse(parsed._replace(query=urlencode(q)))
                connect_kwargs = {"timeout": 30}
                if ssl_mode is not None:
                    connect_kwargs["ssl"] = ssl_mode
                conn = await asyncpg.connect(clean_conn, **connect_kwargs)
                try:
                    # Add LIMIT if not present
                    if "limit" not in normalized:
                        exec_query = f"{query.rstrip(';')} LIMIT {max_rows}"
                    else:
                        exec_query = query

                    rows = await conn.fetch(exec_query)
                    columns = list(rows[0].keys()) if rows else []
                    data = [dict(row) for row in rows[:max_rows]]

                    # Convert non-serializable types
                    import json

                    for row in data:
                        for k, v in row.items():
                            if not isinstance(
                                v, (str, int, float, bool, type(None), list, dict)
                            ):
                                row[k] = str(v)

                    return ToolResult(
                        content=json.dumps(
                            {
                                "status": "success",
                                "columns": columns,
                                "row_count": len(data),
                                "rows": data[:50],  # First 50 rows inline
                                "total_available": len(data),
                                "truncated": len(data) > 50,
                            },
                            default=str,
                        )
                    )
                finally:
                    await conn.close()
            else:
                return ToolResult(
                    content=f"Error: Unsupported database type. Connection string must start with 'postgresql'. Got: {conn_str[:20]}...",
                    is_error=True,
                )

        except ImportError:
            return ToolResult(
                content="Error: asyncpg not installed. Install with: pip install asyncpg",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                content=f"Database query error: {str(e)[:500]}", is_error=True
            )
