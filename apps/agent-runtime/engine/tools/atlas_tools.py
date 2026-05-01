"""Atlas tools — let agents read the ontology graph."""
from __future__ import annotations

import json
import logging
import os
import uuid as _uuid
from typing import Any

import asyncpg

from engine.tools.base import BaseTool, ToolResult


logger = logging.getLogger(__name__)


_POOL: asyncpg.Pool | None = None


def _to_asyncpg_dsn(url: str) -> tuple[str, dict[str, Any]]:
    """Strip query params from a DATABASE_URL and lift them to kwargs."""
    from urllib.parse import urlparse, parse_qs, urlunparse

    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    elif url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    parsed = urlparse(url)
    qs = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
    kwargs: dict[str, Any] = {}
    sslmode = qs.pop("sslmode", None) or qs.pop("ssl", None)
    if sslmode:
        kwargs["ssl"] = sslmode != "disable"  # libpq disable → False, anything else → True
    # Drop the rest of the query string; asyncpg gets them via kwargs only
    clean = urlunparse(parsed._replace(query=""))
    return clean, kwargs


async def _pool() -> asyncpg.Pool:
    global _POOL
    if _POOL is None or _POOL._closed:  # type: ignore[attr-defined]
        raw = os.environ.get("DATABASE_URL", "")
        if not raw:
            raise RuntimeError("DATABASE_URL not set on the runtime pod")
        dsn, extra = _to_asyncpg_dsn(raw)
        _POOL = await asyncpg.create_pool(
            dsn, min_size=1, max_size=4, command_timeout=20, **extra,
        )
    return _POOL


def _as_uuid(s: str | None) -> _uuid.UUID | None:
    if not s:
        return None
    try:
        return _uuid.UUID(str(s))
    except (TypeError, ValueError):
        return None


async def _resolve_graph_id(
    conn: asyncpg.Connection, tenant_id: str, allowed: list[str], graph_id: str | None,
) -> str | None:
    """Pick which graph to operate on."""
    tid = _as_uuid(tenant_id)
    if not tid:
        return None
    allowed_uuids = [u for u in (_as_uuid(g) for g in (allowed or [])) if u]

    gid = _as_uuid(graph_id) if graph_id else None
    if gid:
        row = await conn.fetchrow(
            "SELECT id FROM atlas_graphs WHERE id = $1 AND tenant_id = $2",
            gid, tid,
        )
        if not row:
            return None
        if allowed_uuids and gid not in allowed_uuids:
            return None
        return str(row["id"])

    if allowed_uuids:
        row = await conn.fetchrow(
            "SELECT id FROM atlas_graphs "
            "WHERE tenant_id = $1 AND id = ANY($2::uuid[]) "
            "ORDER BY updated_at DESC LIMIT 1",
            tid, allowed_uuids,
        )
    else:
        row = await conn.fetchrow(
            "SELECT id FROM atlas_graphs WHERE tenant_id = $1 "
            "ORDER BY updated_at DESC LIMIT 1",
            tid,
        )
    return str(row["id"]) if row else None


class AtlasQueryTool(BaseTool):
    name = "atlas_query"
    description = (
        "Search the Atlas ontology graph by node pattern. Each pattern is a "
        "{label_like, kind?} object. Returns matching nodes (and edges, if "
        "traversals are supplied). Use when the user asks about a typed "
        "concept (Counterparty, Trade, etc.) and you want structured rows "
        "instead of a vector search."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "patterns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label_like": {"type": "string", "description": "Substring to match the node label (case-insensitive)."},
                        "kind": {"type": "string", "enum": ["concept", "instance", "document", "property"]},
                    },
                    "required": ["label_like"],
                },
                "description": "One or more node patterns to match.",
            },
            "graph_id": {"type": "string", "description": "Optional. UUID of the atlas graph to query. Defaults to the agent's primary atlas."},
            "limit": {"type": "integer", "default": 25, "minimum": 1, "maximum": 200},
        },
        "required": ["patterns"],
    }

    def __init__(self, tenant_id: str, agent_id: str = "", allowed_graph_ids: list[str] | None = None) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.allowed_graph_ids = allowed_graph_ids or []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        patterns = arguments.get("patterns") or []
        if not patterns:
            return ToolResult(content="No patterns supplied.", is_error=True)
        graph_id = arguments.get("graph_id")
        limit = max(1, min(int(arguments.get("limit") or 25), 200))

        try:
            pool = await _pool()
            async with pool.acquire() as conn:
                gid = await _resolve_graph_id(conn, self.tenant_id, self.allowed_graph_ids, graph_id)
                if not gid:
                    return ToolResult(content="No accessible atlas graph found.", is_error=True)
                gid_uuid = _uuid.UUID(gid)

                cand_lists: list[list[dict[str, Any]]] = []
                for p in patterns:
                    like = (p.get("label_like") or "").lower().strip()
                    kind = p.get("kind")
                    if kind:
                        rows = await conn.fetch(
                            "SELECT id, label, kind::text, description FROM atlas_nodes "
                            "WHERE graph_id = $1 AND lower(label) LIKE $2 AND kind::text = $3 LIMIT 50",
                            gid_uuid, f"%{like}%", kind,
                        )
                    else:
                        rows = await conn.fetch(
                            "SELECT id, label, kind::text, description FROM atlas_nodes "
                            "WHERE graph_id = $1 AND lower(label) LIKE $2 LIMIT 50",
                            gid_uuid, f"%{like}%",
                        )
                    cand_lists.append([
                        {"id": str(r["id"]), "label": r["label"], "kind": r["kind"], "description": r["description"] or ""}
                        for r in rows
                    ])

                if len(cand_lists) == 1:
                    matches = cand_lists[0][:limit]
                    return ToolResult(content=json.dumps({
                        "graph_id": gid,
                        "matches": matches,
                        "count": len(matches),
                    }, indent=2))

                tuples: list[list[dict[str, Any]]] = []

                def backtrack(i: int, picked: list[dict[str, Any]]) -> None:
                    if len(tuples) >= limit:
                        return
                    if i == len(cand_lists):
                        tuples.append(list(picked))
                        return
                    for c in cand_lists[i]:
                        if any(p["id"] == c["id"] for p in picked):
                            continue
                        picked.append(c)
                        backtrack(i + 1, picked)
                        picked.pop()
                backtrack(0, [])

                return ToolResult(content=json.dumps({
                    "graph_id": gid,
                    "matches": tuples,
                    "count": len(tuples),
                }, indent=2))
        except Exception as e:
            logger.exception("atlas_query failed")
            return ToolResult(content=f"atlas_query failed: {e}", is_error=True)


class AtlasTraverseTool(BaseTool):
    name = "atlas_traverse"
    description = (
        "Return the 1-hop neighbourhood of a node (incoming + outgoing edges "
        "and the nodes on the other end). Pick the node by exact label match, "
        "or by id if you already have it. Use when you've located a concept "
        "and want to walk to related concepts."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "description": "Exact label of the node (case-insensitive)."},
            "node_id": {"type": "string", "description": "Or pass a node UUID directly."},
            "graph_id": {"type": "string"},
            "max_edges": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
        },
    }

    def __init__(self, tenant_id: str, agent_id: str = "", allowed_graph_ids: list[str] | None = None) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.allowed_graph_ids = allowed_graph_ids or []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        label = (arguments.get("label") or "").strip()
        node_id = arguments.get("node_id")
        max_edges = max(1, min(int(arguments.get("max_edges") or 50), 200))
        if not label and not node_id:
            return ToolResult(content="Provide `label` or `node_id`.", is_error=True)

        try:
            pool = await _pool()
            async with pool.acquire() as conn:
                gid = await _resolve_graph_id(conn, self.tenant_id, self.allowed_graph_ids, arguments.get("graph_id"))
                if not gid:
                    return ToolResult(content="No accessible atlas graph found.", is_error=True)
                gid_uuid = _uuid.UUID(gid)

                if node_id and _as_uuid(node_id):
                    node = await conn.fetchrow(
                        "SELECT id, label, kind::text, description FROM atlas_nodes "
                        "WHERE id = $1 AND graph_id = $2",
                        _uuid.UUID(node_id), gid_uuid,
                    )
                else:
                    node = await conn.fetchrow(
                        "SELECT id, label, kind::text, description FROM atlas_nodes "
                        "WHERE graph_id = $1 AND lower(label) = lower($2) LIMIT 1",
                        gid_uuid, label,
                    )
                if not node:
                    return ToolResult(content=json.dumps({"found": False, "label": label or None}))

                nid = str(node["id"])
                edges = await conn.fetch(
                    "SELECT e.id, e.from_node_id, e.to_node_id, e.label, e.cardinality_from, e.cardinality_to, "
                    "       fn.label AS from_label, tn.label AS to_label "
                    "FROM atlas_edges e "
                    "JOIN atlas_nodes fn ON fn.id = e.from_node_id "
                    "JOIN atlas_nodes tn ON tn.id = e.to_node_id "
                    "WHERE e.graph_id = $1 AND (e.from_node_id = $2 OR e.to_node_id = $2) "
                    "LIMIT $3",
                    gid_uuid, _uuid.UUID(nid), max_edges,
                )

                outgoing = [{
                    "edge_id": str(r["id"]), "label": r["label"],
                    "cardinality_from": r["cardinality_from"], "cardinality_to": r["cardinality_to"],
                    "to": {"id": str(r["to_node_id"]), "label": r["to_label"]},
                } for r in edges if str(r["from_node_id"]) == nid]
                incoming = [{
                    "edge_id": str(r["id"]), "label": r["label"],
                    "cardinality_from": r["cardinality_from"], "cardinality_to": r["cardinality_to"],
                    "from": {"id": str(r["from_node_id"]), "label": r["from_label"]},
                } for r in edges if str(r["to_node_id"]) == nid]

                return ToolResult(content=json.dumps({
                    "graph_id": gid,
                    "node": {"id": nid, "label": node["label"], "kind": node["kind"], "description": node["description"] or ""},
                    "outgoing": outgoing,
                    "incoming": incoming,
                    "edge_count": len(outgoing) + len(incoming),
                }, indent=2))
        except Exception as e:
            logger.exception("atlas_traverse failed")
            return ToolResult(content=f"atlas_traverse failed: {e}", is_error=True)


class AtlasSearchGroundedTool(BaseTool):
    name = "atlas_search_grounded"
    description = (
        "Find KB documents that are linked (as document-kind nodes) to "
        "concepts near a target term in the ontology. Use this instead of "
        "vector-only `knowledge_search` when the user asks about a typed "
        "concept and you want chunks that are *bound* to that concept, not "
        "just lexically similar."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "near_label": {"type": "string", "description": "Concept label to ground retrieval around (e.g. 'Counterparty')."},
            "graph_id": {"type": "string"},
            "max_docs": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
        },
        "required": ["near_label"],
    }

    def __init__(self, tenant_id: str, agent_id: str = "", allowed_graph_ids: list[str] | None = None) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.allowed_graph_ids = allowed_graph_ids or []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        near = (arguments.get("near_label") or "").strip()
        if not near:
            return ToolResult(content="`near_label` is required.", is_error=True)
        max_docs = max(1, min(int(arguments.get("max_docs") or 10), 50))

        try:
            pool = await _pool()
            async with pool.acquire() as conn:
                gid = await _resolve_graph_id(conn, self.tenant_id, self.allowed_graph_ids, arguments.get("graph_id"))
                if not gid:
                    return ToolResult(content="No accessible atlas graph found.", is_error=True)
                gid_uuid = _uuid.UUID(gid)

                seeds = await conn.fetch(
                    "SELECT id, label FROM atlas_nodes "
                    "WHERE graph_id = $1 AND lower(label) LIKE $2 AND kind::text = 'concept' LIMIT 5",
                    gid_uuid, f"%{near.lower()}%",
                )
                if not seeds:
                    return ToolResult(content=json.dumps({"found": False, "near_label": near}))

                seed_ids = [r["id"] for r in seeds]
                docs = await conn.fetch(
                    "SELECT DISTINCT n.id, n.label, n.document_id, n.properties "
                    "FROM atlas_nodes n "
                    "JOIN atlas_edges e ON (e.from_node_id = n.id OR e.to_node_id = n.id) "
                    "WHERE n.graph_id = $1 AND n.kind::text = 'document' "
                    "  AND (e.from_node_id = ANY($2::uuid[]) OR e.to_node_id = ANY($2::uuid[])) "
                    "LIMIT $3",
                    gid_uuid, seed_ids, max_docs,
                )

                return ToolResult(content=json.dumps({
                    "graph_id": gid,
                    "near_label": near,
                    "seeds": [{"id": str(s["id"]), "label": s["label"]} for s in seeds],
                    "documents": [{
                        "node_id": str(d["id"]),
                        "filename": d["label"],
                        "kb_document_id": str(d["document_id"]) if d["document_id"] else None,
                        "properties": (json.loads(d["properties"]) if isinstance(d["properties"], str) else (d["properties"] or {})),
                    } for d in docs],
                    "count": len(docs),
                }, indent=2))
        except Exception as e:
            logger.exception("atlas_search_grounded failed")
            return ToolResult(content=f"atlas_search_grounded failed: {e}", is_error=True)


class AtlasDescribeTool(BaseTool):
    name = "atlas_describe"
    description = (
        "Summarise an atlas graph: total nodes/edges per kind, top edge labels, "
        "and the most-connected concepts. Use as the first step when the user "
        "asks 'what do you know about X?' — gives the agent a map of the "
        "domain before it dives into specifics."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "graph_id": {"type": "string", "description": "Optional. Defaults to the agent's primary atlas."},
            "top_n": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
        },
    }

    def __init__(self, tenant_id: str, agent_id: str = "", allowed_graph_ids: list[str] | None = None) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.allowed_graph_ids = allowed_graph_ids or []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        top_n = max(1, min(int(arguments.get("top_n") or 10), 50))
        try:
            pool = await _pool()
            async with pool.acquire() as conn:
                gid = await _resolve_graph_id(conn, self.tenant_id, self.allowed_graph_ids, arguments.get("graph_id"))
                if not gid:
                    return ToolResult(content="No accessible atlas graph found.", is_error=True)
                gid_uuid = _uuid.UUID(gid)

                meta = await conn.fetchrow(
                    "SELECT name, description, version, node_count, edge_count "
                    "FROM atlas_graphs WHERE id = $1",
                    gid_uuid,
                )
                kind_counts = await conn.fetch(
                    "SELECT kind::text AS k, COUNT(*) AS c FROM atlas_nodes WHERE graph_id = $1 GROUP BY kind",
                    gid_uuid,
                )
                top_edges = await conn.fetch(
                    "SELECT label, COUNT(*) AS c FROM atlas_edges WHERE graph_id = $1 "
                    "GROUP BY label ORDER BY c DESC LIMIT $2",
                    gid_uuid, top_n,
                )
                top_concepts = await conn.fetch(
                    "SELECT n.label, COUNT(e.id) AS c FROM atlas_nodes n "
                    "LEFT JOIN atlas_edges e ON (e.from_node_id = n.id OR e.to_node_id = n.id) "
                    "WHERE n.graph_id = $1 AND n.kind::text = 'concept' "
                    "GROUP BY n.label ORDER BY c DESC LIMIT $2",
                    gid_uuid, top_n,
                )
                return ToolResult(content=json.dumps({
                    "graph_id": gid,
                    "name": meta["name"] if meta else None,
                    "description": (meta["description"] if meta else None) or "",
                    "version": int(meta["version"]) if meta else 0,
                    "totals": {"nodes": int(meta["node_count"]) if meta else 0, "edges": int(meta["edge_count"]) if meta else 0},
                    "by_kind": {r["k"]: int(r["c"]) for r in kind_counts},
                    "top_edge_labels": [{"label": r["label"], "count": int(r["c"])} for r in top_edges],
                    "most_connected_concepts": [{"label": r["label"], "edges": int(r["c"])} for r in top_concepts],
                }, indent=2))
        except Exception as e:
            logger.exception("atlas_describe failed")
            return ToolResult(content=f"atlas_describe failed: {e}", is_error=True)


ATLAS_TOOL_NAMES = {
    "atlas_query": AtlasQueryTool,
    "atlas_traverse": AtlasTraverseTool,
    "atlas_search_grounded": AtlasSearchGroundedTool,
    "atlas_describe": AtlasDescribeTool,
}
