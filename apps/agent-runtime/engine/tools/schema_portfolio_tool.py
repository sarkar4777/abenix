"""Schema-Driven Portfolio Tool — generic domain data access tool."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_SAFE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _validate_identifier(name: str) -> bool:
    return bool(_SAFE_IDENTIFIER.match(name))


def _strip_sqlalchemy_url(url: str) -> str:
    """Strip SQLAlchemy-specific bits so asyncpg.connect accepts the URL."""
    cleaned = url.replace("postgresql+asyncpg://", "postgresql://")
    if "?" in cleaned:
        base, query = cleaned.split("?", 1)
        kept = [
            p
            for p in query.split("&")
            if not p.lower().startswith(("ssl=", "sslmode="))
        ]
        cleaned = base + ("?" + "&".join(kept) if kept else "")
    return cleaned


async def load_schema_from_db(
    domain_name: str, tenant_id: str, db_url: str = ""
) -> dict | None:
    """Load a portfolio schema from the database (created via /api/portfolio-schemas).

    Returns the schema_json field, or None if not found.
    """
    db_url = db_url or os.environ.get("DATABASE_URL", "")
    if not db_url:
        return None
    try:
        import asyncpg

        conn = await asyncpg.connect(_strip_sqlalchemy_url(db_url))
        try:
            row = await conn.fetchrow(
                """
                SELECT schema_json FROM portfolio_schemas
                WHERE domain_name = $1 AND tenant_id = $2::uuid AND is_active = true
                LIMIT 1
            """,
                domain_name,
                tenant_id,
            )
            if row and row["schema_json"]:
                schema = row["schema_json"]
                if isinstance(schema, str):
                    schema = json.loads(schema)
                return schema
            return None
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("Failed to load schema %s from DB: %s", domain_name, e)
        return None


class SchemaPortfolioTool(BaseTool):
    """Schema-driven portfolio tool that adapts to any domain via a schema dict."""

    def __init__(
        self,
        schema: dict | None = None,
        user_id: str = "",
        db_url: str = "",
        *,
        domain_name: str = "",
        tenant_id: str = "",
    ) -> None:
        self.user_id = user_id
        self.db_url = db_url or os.environ.get("DATABASE_URL", "")
        self._deferred_domain = domain_name
        self._deferred_tenant = tenant_id

        if schema is None and not domain_name:
            raise ValueError(
                "SchemaPortfolioTool requires either schema= or domain_name="
            )

        if schema is not None:
            self._bind_schema(schema)
        else:
            # Deferred: tool name + minimal description until schema is loaded
            self.schema = None  # type: ignore[assignment]
            self.name = f"portfolio_{domain_name}"
            self.description = (
                f"Query the {domain_name} portfolio (schema loaded from portfolio_schemas table). "
                "Operations available after first call: list_records, get_record, search, "
                "get_summary, get_related, compare_field, discover_fields, query_fields."
            )
            self.input_schema: dict[str, Any] = {
                "type": "object",
                "properties": {
                    "operation": {"type": "string"},
                    "record_id": {"type": "string"},
                    "query": {"type": "string"},
                    "table_name": {"type": "string"},
                    "section": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["operation"],
            }

    def _bind_schema(self, schema: dict) -> None:
        self.schema = schema
        self._domain = schema["domain"]
        self._main = schema["main_table"]
        self._related = schema.get("related_tables", [])

        # Validate all identifiers in schema
        self._validate_schema()

        # Build dynamic tool metadata
        noun = self._domain["record_noun"]
        nouns = self._domain["record_noun_plural"]
        related_names = [r["label"] for r in self._related]

        self.name = f"portfolio_{self._domain['name']}"
        self.description = (
            f"Query the {self._domain['label']} database. "
            f"Use 'list_records' to see all {nouns}. "
            f"Use 'get_record' with a record_id for full details including {', '.join(related_names)}. "
            f"Use 'search' with a query to find matching {nouns} and related data. "
            f"Use 'get_summary' for aggregate portfolio statistics. "
            f"Use 'discover_fields' to find what extracted fields are available. "
            f"Use 'query_fields' to get specific field values across {nouns}. "
            f"Use 'compare_field' to compare a single field across all {nouns}. "
            f"Use 'get_related' with a table_name to get specific related data."
        )

        # Build the operations enum dynamically
        ops = [
            "list_records",
            "get_record",
            "search",
            "get_summary",
            "get_related",
            "compare_field",
        ]
        kv_tables = [r for r in self._related if r.get("is_kv_store")]
        if kv_tables:
            ops.extend(["discover_fields", "query_fields"])

        self.input_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ops,
                    "description": f"Which operation to perform on {nouns}",
                },
                "record_id": {
                    "type": "string",
                    "description": f"UUID of a specific {noun} (for get_record, query_fields)",
                },
                "query": {
                    "type": "string",
                    "description": "Search text or field name for search/compare_field/query_fields",
                },
                "table_name": {
                    "type": "string",
                    "enum": [r["label"] for r in self._related],
                    "description": "Related table to query (for get_related)",
                },
                "section": {
                    "type": "string",
                    "description": "Section filter for discover_fields/query_fields",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20)",
                    "default": 20,
                },
            },
            "required": ["operation"],
        }

    def _validate_schema(self) -> None:
        """Validate all table and column names are safe SQL identifiers."""
        assert _validate_identifier(
            self._main["name"]
        ), f"Unsafe table name: {self._main['name']}"
        for col in self._main.get("columns", {}):
            assert _validate_identifier(col), f"Unsafe column: {col}"
        for rel in self._related:
            assert _validate_identifier(rel["name"]), f"Unsafe table: {rel['name']}"
            for col in rel.get("columns", {}):
                assert _validate_identifier(col), f"Unsafe column: {col}"

    async def _get_conn(self) -> Any:
        import asyncpg

        if self.db_url:
            return await asyncpg.connect(_strip_sqlalchemy_url(self.db_url))
        return await asyncpg.connect(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            user=os.environ.get("POSTGRES_USER", "abenix"),
            password=os.environ.get("POSTGRES_PASSWORD", "abenix"),
            database=os.environ.get("POSTGRES_DB", "abenix"),
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation", "")
        if not op:
            return ToolResult(content="Error: operation is required", is_error=True)

        # Lazy schema load (deferred construction)
        if self.schema is None and self._deferred_domain:
            schema = await load_schema_from_db(
                self._deferred_domain,
                self._deferred_tenant,
                self.db_url,
            )
            if not schema:
                return ToolResult(
                    content=(
                        f"No schema found for domain '{self._deferred_domain}' in "
                        f"portfolio_schemas table for tenant {self._deferred_tenant}. "
                        "Create one via POST /api/portfolio-schemas."
                    ),
                    is_error=True,
                )
            self._bind_schema(schema)

        conn = await self._get_conn()
        try:
            handlers = {
                "list_records": self._list_records,
                "get_record": self._get_record,
                "search": self._search,
                "get_summary": self._get_summary,
                "get_related": self._get_related,
                "compare_field": self._compare_field,
                "discover_fields": self._discover_fields,
                "query_fields": self._query_fields,
            }
            handler = handlers.get(op)
            if not handler:
                return ToolResult(content=f"Unknown operation: {op}", is_error=True)
            return await handler(conn, arguments)
        except Exception as e:
            logger.error("SchemaPortfolioTool error: %s", e)
            return ToolResult(content=f"Query error: {e}", is_error=True)
        finally:
            await conn.close()

    def _fmt(self, value: Any, col_config: dict) -> str:
        """Format a value using column config."""
        if value is None:
            return "—"
        fmt = col_config.get("format")
        if fmt and isinstance(value, (int, float)):
            try:
                return fmt.format(value)
            except (ValueError, KeyError):
                pass
        if col_config.get("type") == "date" and hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        truncate = col_config.get("truncate")
        if truncate and isinstance(value, str) and len(value) > truncate:
            return value[:truncate] + "..."
        return str(value)

    async def _list_records(self, conn: Any, args: dict) -> ToolResult:
        limit = min(args.get("limit", 20), 50)
        cols = self._main["list_columns"]
        col_str = ", ".join(cols)
        scope_col = self._main["user_scope_column"]
        created_col = self._main.get("created_at_column", "created_at")
        table = self._main["name"]

        rows = await conn.fetch(
            f"SELECT {col_str} FROM {table} WHERE {scope_col} = $1 ORDER BY {created_col} DESC LIMIT $2",
            self.user_id,
            limit,
        )

        if not rows:
            return ToolResult(
                content=f"No {self._domain['record_noun_plural']} found.",
                metadata={"count": 0},
            )

        title_col = self._main["title_column"]
        col_configs = self._main["columns"]

        lines = [
            f"{self._domain['label']}: {len(rows)} {self._domain['record_noun_plural']}\n"
        ]
        for r in rows:
            title = r.get(title_col, "Untitled")
            detail_parts = []
            for c in cols:
                if c in ("id", title_col):
                    continue
                cfg = col_configs.get(c, {})
                val = self._fmt(r.get(c), cfg)
                if val != "—":
                    detail_parts.append(f"{cfg.get('label', c)}={val}")
            lines.append(f"- **{title}** (ID: {r['id']})")
            if detail_parts:
                lines.append(f"  {' | '.join(detail_parts)}")

        return ToolResult(content="\n".join(lines), metadata={"count": len(rows)})

    async def _get_record(self, conn: Any, args: dict) -> ToolResult:
        rid = args.get("record_id", "")
        if not rid:
            return ToolResult(content="Error: record_id is required", is_error=True)

        table = self._main["name"]
        scope_col = self._main["user_scope_column"]
        row = await conn.fetchrow(
            f"SELECT * FROM {table} WHERE id = $1 AND {scope_col} = $2",
            rid,
            self.user_id,
        )
        if not row:
            return ToolResult(
                content=f"{self._domain['record_noun'].title()} not found.",
                is_error=True,
            )

        title_col = self._main["title_column"]
        col_configs = self._main["columns"]
        parts = [f"# {row.get(title_col, 'Untitled')}\n"]

        for col_name, cfg in col_configs.items():
            if col_name == "id":
                continue
            val = self._fmt(row.get(col_name), cfg)
            if val != "—":
                parts.append(f"- {cfg.get('label', col_name)}: {val}")

        # Fetch related data concurrently
        async def fetch_related(rel: dict) -> tuple[dict, list]:
            fk = rel["foreign_key"]
            rel_cols = list(rel["columns"].keys())
            col_str = ", ".join(rel_cols)
            order = rel.get("order_by", "")
            order_clause = f" ORDER BY {order}" if order else ""
            rows = await conn.fetch(
                f"SELECT {col_str} FROM {rel['name']} WHERE {fk} = $1{order_clause}",
                rid,
            )
            return rel, list(rows)

        related_results = await asyncio.gather(
            *[fetch_related(r) for r in self._related]
        )

        for rel, rel_rows in related_results:
            if not rel_rows:
                continue
            parts.append(f"\n## {rel['label']} ({len(rel_rows)})")
            rel_configs = rel["columns"]
            for rr in rel_rows:
                detail_parts = []
                for col_name, cfg in rel_configs.items():
                    val = self._fmt(rr.get(col_name), cfg)
                    if val != "—":
                        detail_parts.append(f"{cfg.get('label', col_name)}: {val}")
                parts.append(f"- {' | '.join(detail_parts[:6])}")

        return ToolResult(content="\n".join(parts), metadata={"record_id": rid})

    async def _search(self, conn: Any, args: dict) -> ToolResult:
        query = args.get("query", "")
        if not query:
            return ToolResult(
                content="Error: query is required for search", is_error=True
            )

        limit = min(args.get("limit", 20), 50)
        table = self._main["name"]
        scope_col = self._main["user_scope_column"]
        title_col = self._main["title_column"]
        search_cols = self._main.get("search_columns", [title_col])

        # Search main table
        or_clauses = " OR ".join(f"{c} ILIKE $2" for c in search_cols)
        main_rows = await conn.fetch(
            f"SELECT id, {title_col} FROM {table} WHERE {scope_col} = $1 AND ({or_clauses}) LIMIT $3",
            self.user_id,
            f"%{query}%",
            limit,
        )

        # Search related tables with searchable_columns
        related_hits = []
        for rel in self._related:
            if not rel.get("searchable_columns"):
                continue
            fk = rel["foreign_key"]
            search_or = " OR ".join(
                f"r.{c} ILIKE $2" for c in rel["searchable_columns"]
            )
            hits = await conn.fetch(
                f"SELECT m.{title_col}, r.* FROM {rel['name']} r "
                f"JOIN {table} m ON r.{fk} = m.id "
                f"WHERE m.{scope_col} = $1 AND ({search_or}) LIMIT $3",
                self.user_id,
                f"%{query}%",
                limit,
            )
            for h in hits:
                rel_configs = rel["columns"]
                detail = " | ".join(
                    f"{cfg.get('label', c)}: {self._fmt(h.get(c), cfg)}"
                    for c, cfg in list(rel_configs.items())[:4]
                    if h.get(c)
                )
                related_hits.append(f"- [{h.get(title_col)}] ({rel['label']}) {detail}")

        lines = [f"Search results for '{query}':\n"]
        if main_rows:
            lines.append(
                f"## {self._domain['record_noun_plural'].title()} ({len(main_rows)})"
            )
            for r in main_rows:
                lines.append(f"- **{r.get(title_col)}** (ID: {r['id']})")
        if related_hits:
            lines.append(f"\n## Related Data ({len(related_hits)})")
            lines.extend(related_hits[:20])
        if not main_rows and not related_hits:
            lines.append("No results found.")

        return ToolResult(
            content="\n".join(lines),
            metadata={"main": len(main_rows), "related": len(related_hits)},
        )

    async def _get_summary(self, conn: Any, args: dict) -> ToolResult:
        table = self._main["name"]
        scope_col = self._main["user_scope_column"]
        aggs = self._main.get("summary_aggregations", {})

        if not aggs:
            return ToolResult(content="No summary aggregations defined.", is_error=True)

        agg_sql = ", ".join(f"{v['sql']} as {k}" for k, v in aggs.items())
        row = await conn.fetchrow(
            f"SELECT {agg_sql} FROM {table} WHERE {scope_col} = $1", self.user_id
        )

        lines = [f"# {self._domain['label']} Summary\n"]
        for key, config in aggs.items():
            val = row.get(key)
            fmt = config.get("format")
            if val is not None and fmt:
                try:
                    formatted = fmt.format(float(val))
                except (ValueError, TypeError):
                    formatted = str(val or 0)
            else:
                formatted = str(val or 0)
            lines.append(f"- {config['label']}: {formatted}")

        # Count related records
        for rel in self._related:
            count = await conn.fetchval(
                f"SELECT count(*) FROM {rel['name']} r JOIN {table} m ON r.{rel['foreign_key']} = m.id WHERE m.{scope_col} = $1",
                self.user_id,
            )
            lines.append(f"- Total {rel['label'].lower()}: {count}")

        return ToolResult(content="\n".join(lines))

    async def _get_related(self, conn: Any, args: dict) -> ToolResult:
        table_label = args.get("table_name", "")
        rid = args.get("record_id", "")
        limit = min(args.get("limit", 30), 100)

        rel = next((r for r in self._related if r["label"] == table_label), None)
        if not rel:
            available = ", ".join(r["label"] for r in self._related)
            return ToolResult(
                content=f"Table '{table_label}' not found. Available: {available}",
                is_error=True,
            )

        table = self._main["name"]
        scope_col = self._main["user_scope_column"]
        title_col = self._main["title_column"]
        fk = rel["foreign_key"]
        rel_cols = ", ".join(f"r.{c}" for c in rel["columns"])
        order = f" ORDER BY r.{rel['order_by']}" if rel.get("order_by") else ""

        where_parts = [f"m.{scope_col} = $1"]
        params: list = [self.user_id]
        idx = 2
        if rid:
            where_parts.append(f"r.{fk} = ${idx}::uuid")
            params.append(rid)
            idx += 1
        params.append(limit)
        where = " AND ".join(where_parts)

        rows = await conn.fetch(
            f"SELECT m.{title_col}, {rel_cols} FROM {rel['name']} r "
            f"JOIN {table} m ON r.{fk} = m.id WHERE {where}{order} LIMIT ${idx}",
            *params,
        )

        if not rows:
            return ToolResult(
                content=f"No {rel['label'].lower()} found.", metadata={"count": 0}
            )

        rel_configs = rel["columns"]
        lines = [f"{rel['label']} ({len(rows)}):\n"]
        for r in rows:
            parts = [f"[{r.get(title_col)}]"]
            for col_name, cfg in rel_configs.items():
                val = self._fmt(r.get(col_name), cfg)
                if val != "—":
                    parts.append(f"{cfg.get('label', col_name)}: {val}")
            lines.append(f"- {' | '.join(parts[:5])}")

        return ToolResult(content="\n".join(lines), metadata={"count": len(rows)})

    async def _discover_fields(self, conn: Any, args: dict) -> ToolResult:
        rid = args.get("record_id", "")
        kv_tables = [r for r in self._related if r.get("is_kv_store")]
        if not kv_tables:
            return ToolResult(
                content="No key-value data tables defined in this schema."
            )

        table = self._main["name"]
        scope_col = self._main["user_scope_column"]

        all_lines = []
        for kv in kv_tables:
            section_col = kv.get("section_column", "section")
            key_col = kv["key_column"]
            type_col = kv.get("type_column", "")
            conf_col = kv.get("confidence_column", "")
            fk = kv["foreign_key"]

            if rid:
                rows = await conn.fetch(
                    f"SELECT r.{section_col}, r.{key_col}"
                    f"{f', r.{type_col}' if type_col else ''}"
                    f"{f', r.{conf_col}' if conf_col else ''}"
                    f" FROM {kv['name']} r JOIN {table} m ON r.{fk} = m.id"
                    f" WHERE r.{fk} = $1 AND m.{scope_col} = $2"
                    f" ORDER BY r.{section_col}, r.{key_col}",
                    rid,
                    self.user_id,
                )
            else:
                type_sel = f", r.{type_col}" if type_col else ""
                conf_sel = f", avg(r.{conf_col}) as avg_conf" if conf_col else ""
                rows = await conn.fetch(
                    f"SELECT r.{section_col}, r.{key_col}{type_sel},"
                    f" count(DISTINCT r.{fk}) as record_count{conf_sel}"
                    f" FROM {kv['name']} r JOIN {table} m ON r.{fk} = m.id"
                    f" WHERE m.{scope_col} = $1"
                    f" GROUP BY r.{section_col}, r.{key_col}{type_sel}"
                    f" ORDER BY record_count DESC, r.{section_col}, r.{key_col}",
                    self.user_id,
                )

            if not rows:
                continue

            all_lines.append(f"## {kv['label']} ({len(rows)} fields)\n")
            current_section = ""
            for r in rows:
                sect = r.get(section_col, "")
                if sect != current_section:
                    current_section = sect
                    all_lines.append(f"\n### {current_section}")
                field = r.get(key_col, "?")
                if rid:
                    conf = (
                        f" ({r.get(conf_col, 0):.0%})"
                        if conf_col and r.get(conf_col)
                        else ""
                    )
                    all_lines.append(f"- {field}{conf}")
                else:
                    count = r.get("record_count", 0)
                    conf = f" ({r.get('avg_conf', 0):.0%})" if r.get("avg_conf") else ""
                    all_lines.append(
                        f"- {field} — in {count} {self._domain['record_noun_plural']}{conf}"
                    )

        if not all_lines:
            return ToolResult(
                content="No extracted fields found.", metadata={"count": 0}
            )

        return ToolResult(content="\n".join(all_lines))

    async def _query_fields(self, conn: Any, args: dict) -> ToolResult:
        query = args.get("query", "")
        section = args.get("section", "")
        rid = args.get("record_id", "")
        limit = min(args.get("limit", 50), 100)

        kv_tables = [r for r in self._related if r.get("is_kv_store")]
        if not kv_tables:
            return ToolResult(content="No key-value data tables in this schema.")

        table = self._main["name"]
        scope_col = self._main["user_scope_column"]
        title_col = self._main["title_column"]

        all_lines = []
        for kv in kv_tables:
            key_col = kv["key_column"]
            val_col = kv["value_column"]
            section_col = kv.get("section_column", "section")
            fk = kv["foreign_key"]

            conditions = [f"m.{scope_col} = $1"]
            params: list = [self.user_id]
            idx = 2

            if query:
                conditions.append(
                    f"(r.{key_col} ILIKE ${idx} OR r.{val_col} ILIKE ${idx})"
                )
                params.append(f"%{query}%")
                idx += 1
            if section:
                conditions.append(f"r.{section_col} = ${idx}")
                params.append(section)
                idx += 1
            if rid:
                conditions.append(f"r.{fk} = ${idx}::uuid")
                params.append(rid)
                idx += 1

            params.append(limit)
            where = " AND ".join(conditions)

            rows = await conn.fetch(
                f"SELECT m.{title_col}, r.{section_col}, r.{key_col}, r.{val_col}"
                f" FROM {kv['name']} r JOIN {table} m ON r.{fk} = m.id"
                f" WHERE {where} ORDER BY m.{title_col}, r.{section_col}, r.{key_col} LIMIT ${idx}",
                *params,
            )

            if rows:
                by_record: dict[str, list] = {}
                for r in rows:
                    t = r.get(title_col, "?")
                    if t not in by_record:
                        by_record[t] = []
                    by_record[t].append(r)

                for record_title, fields in by_record.items():
                    all_lines.append(f"\n## {record_title}")
                    for f in fields:
                        all_lines.append(f"- {f.get(key_col)}: {f.get(val_col)}")

        if not all_lines:
            return ToolResult(content="No matching data found.", metadata={"count": 0})

        return ToolResult(content="Query results:\n" + "\n".join(all_lines))

    async def _compare_field(self, conn: Any, args: dict) -> ToolResult:
        field_name = args.get("query", "") or args.get("field_name", "")
        if not field_name:
            return ToolResult(
                content="Error: query (field name) is required", is_error=True
            )

        kv_tables = [r for r in self._related if r.get("is_kv_store")]
        if not kv_tables:
            return ToolResult(content="No key-value data tables in this schema.")

        table = self._main["name"]
        scope_col = self._main["user_scope_column"]
        title_col = self._main["title_column"]
        type_col = self._main.get("type_column", "")

        all_lines = [f"Comparison of '{field_name}':\n"]
        for kv in kv_tables:
            key_col = kv["key_column"]
            val_col = kv["value_column"]
            fk = kv["foreign_key"]

            type_sel = f", m.{type_col}" if type_col else ""
            rows = await conn.fetch(
                f"SELECT m.{title_col}{type_sel}, r.{val_col}"
                f" FROM {kv['name']} r JOIN {table} m ON r.{fk} = m.id"
                f" WHERE m.{scope_col} = $1 AND r.{key_col} ILIKE $2"
                f" ORDER BY m.{title_col}",
                self.user_id,
                f"%{field_name}%",
            )

            for r in rows:
                type_str = (
                    f" ({r.get(type_col)})" if type_col and r.get(type_col) else ""
                )
                all_lines.append(
                    f"- **{r.get(title_col)}**{type_str}: {r.get(val_col)}"
                )

        if len(all_lines) <= 1:
            return ToolResult(
                content=f"Field '{field_name}' not found in any {self._domain['record_noun']}.",
                metadata={"count": 0},
            )

        return ToolResult(content="\n".join(all_lines))
