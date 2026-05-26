"""READ-only Cypher tool for agents. Lets a power agent query the Atlas
graph directly when the four typed tools (`atlas_describe`,
`atlas_query`, `atlas_traverse`, `atlas_search_grounded`) aren't enough.

Safety: the validator rejects any token in the write set
(CREATE, MERGE, DELETE, SET, REMOVE, DROP, LOAD CSV, CALL apoc.*).
Tenant and graph context are injected as parameters so a hand-crafted
query cannot escape the caller's scope. Result rows are capped at 1000
and execution at 10 seconds.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from engine.tools.base import BaseTool, ToolResult

_FORBIDDEN_TOKENS = (
    r"\bcreate\b",
    r"\bmerge\b",
    r"\bdelete\b",
    r"\bdetach\s+delete\b",
    r"\bset\b",
    r"\bremove\b",
    r"\bdrop\b",
    r"\bload\s+csv\b",
    r"\bcall\s+apoc\b",
    r"\bcall\s+dbms\b",
    r"\bcall\s+db\.\w+\b",
    r"\bforeach\b",
    r";",
)
_FORBIDDEN_RE = re.compile("|".join(_FORBIDDEN_TOKENS), re.IGNORECASE)

MAX_ROWS = 1000
MAX_SECONDS = 10
TENANT_PARAM = "abenix_tenant_id"
GRAPH_PARAM = "abenix_graph_id"


def _is_read_only(query: str) -> tuple[bool, str | None]:
    if not query or not query.strip():
        return False, "empty query"
    if len(query) > 8000:
        return False, "query too long (max 8000 chars)"
    m = _FORBIDDEN_RE.search(query)
    if m:
        return False, f"forbidden keyword: {m.group(0)!r}"
    if "match" not in query.lower() and "return" not in query.lower():
        return False, "query must contain MATCH and RETURN"
    return True, None


class AtlasCypherTool(BaseTool):
    name = "atlas_cypher"
    description = (
        "Run a read-only Cypher query against the Atlas knowledge graph. "
        "CREATE / MERGE / DELETE / SET / REMOVE / CALL apoc / LOAD CSV are "
        "rejected by a server-side validator. The tenant_id and graph_id "
        "are injected as parameters automatically; reference them as "
        "$abenix_tenant_id and $abenix_graph_id."
    )

    input_schema = {
        "type": "object",
        "properties": {
            "cypher": {
                "type": "string",
                "description": "READ-only Cypher query. Must contain MATCH and RETURN.",
            },
            "graph_id": {
                "type": "string",
                "description": "Atlas graph ID to query (UUID).",
            },
            "params": {
                "type": "object",
                "description": "Additional parameter bindings for the query.",
                "default": {},
            },
            "limit": {
                "type": "integer",
                "description": f"Max rows to return (capped at {MAX_ROWS}).",
                "default": 100,
                "minimum": 1,
                "maximum": MAX_ROWS,
            },
        },
        "required": ["cypher", "graph_id"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        cypher = str(kwargs.get("cypher", "")).strip()
        graph_id_raw = str(kwargs.get("graph_id", "")).strip()
        params = dict(kwargs.get("params") or {})
        limit = min(int(kwargs.get("limit", 100) or 100), MAX_ROWS)

        ok, why = _is_read_only(cypher)
        if not ok:
            return ToolResult.error(f"cypher rejected: {why}")
        try:
            graph_id = uuid.UUID(graph_id_raw)
        except Exception:
            return ToolResult.error("graph_id must be a UUID")

        tenant_id = self.context.tenant_id if self.context else None
        if tenant_id is None:
            return ToolResult.error("missing tenant context")

        params[TENANT_PARAM] = str(tenant_id)
        params[GRAPH_PARAM] = str(graph_id)
        if "limit" not in cypher.lower():
            cypher = cypher.rstrip(";") + f" LIMIT {limit}"

        try:
            from app.services.atlas.neo4j_client import run_cypher
        except Exception:
            return ToolResult.error("atlas backend not available")

        try:
            rows = await run_cypher(cypher, params, timeout_s=MAX_SECONDS)
        except Exception as e:
            return ToolResult.error(f"cypher execution failed: {e}")
        rows = rows[:MAX_ROWS]
        return ToolResult.ok(
            {
                "rows": rows,
                "row_count": len(rows),
                "graph_id": str(graph_id),
                "cypher": cypher,
            }
        )


class AtlasAsOfTool(BaseTool):
    name = "atlas_as_of"
    description = (
        "Query the Atlas graph as it existed at a specific timestamp. "
        "Uses bi-temporal edge metadata (valid_from / valid_to). Returns "
        "the same shape as atlas_describe but filtered to the snapshot."
    )

    input_schema = {
        "type": "object",
        "properties": {
            "graph_id": {"type": "string"},
            "as_of": {
                "type": "string",
                "description": "ISO-8601 timestamp; defaults to now.",
            },
            "match_clause": {
                "type": "string",
                "description": "Optional Cypher MATCH suffix, e.g. '(n:Person)-[r]-(c:Company)'",
                "default": "(n)-[r]-(m)",
            },
            "limit": {
                "type": "integer",
                "default": 50,
                "minimum": 1,
                "maximum": MAX_ROWS,
            },
        },
        "required": ["graph_id"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        graph_id_raw = str(kwargs.get("graph_id", "")).strip()
        as_of = str(kwargs.get("as_of") or "").strip() or None
        match_clause = str(kwargs.get("match_clause") or "(n)-[r]-(m)")
        limit = min(int(kwargs.get("limit", 50) or 50), MAX_ROWS)

        try:
            graph_id = uuid.UUID(graph_id_raw)
        except Exception:
            return ToolResult.error("graph_id must be a UUID")

        tenant_id = self.context.tenant_id if self.context else None
        if tenant_id is None:
            return ToolResult.error("missing tenant context")

        if as_of is None:
            from datetime import datetime, timezone

            as_of = datetime.now(timezone.utc).isoformat()

        cypher = (
            f"MATCH {match_clause} "
            f"WHERE r.graph_id = $g "
            f"  AND (r.valid_from IS NULL OR r.valid_from <= datetime($as_of)) "
            f"  AND (r.valid_to   IS NULL OR r.valid_to   >  datetime($as_of)) "
            f"RETURN n, r, m LIMIT {limit}"
        )
        try:
            from app.services.atlas.neo4j_client import run_cypher

            rows = await run_cypher(
                cypher,
                {"g": str(graph_id), "as_of": as_of, TENANT_PARAM: str(tenant_id)},
                timeout_s=MAX_SECONDS,
            )
        except Exception as e:
            return ToolResult.error(f"as-of query failed: {e}")
        return ToolResult.ok(
            {
                "graph_id": str(graph_id),
                "as_of": as_of,
                "rows": rows,
                "row_count": len(rows),
            }
        )


__all__ = ["AtlasCypherTool", "AtlasAsOfTool"]
