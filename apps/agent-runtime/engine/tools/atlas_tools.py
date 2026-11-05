"""Atlas tools — let agents read the ontology graph."""

from __future__ import annotations

import json
import logging
import os
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


_POOL: asyncpg.Pool | None = None


def _to_asyncpg_dsn(url: str) -> tuple[str, dict[str, Any]]:
    """Strip query params from a DATABASE_URL and lift them to kwargs."""
    from urllib.parse import urlparse, parse_qs, urlunparse

    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://") :]
    elif url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    parsed = urlparse(url)
    qs = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
    kwargs: dict[str, Any] = {}
    sslmode = qs.pop("sslmode", None) or qs.pop("ssl", None)
    if sslmode:
        kwargs["ssl"] = (
            sslmode != "disable"
        )  # libpq disable → False, anything else → True
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
            dsn,
            min_size=1,
            max_size=4,
            command_timeout=20,
            **extra,
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
    conn: asyncpg.Connection,
    tenant_id: str,
    allowed: list[str],
    graph_id: str | None,
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
            gid,
            tid,
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
            tid,
            allowed_uuids,
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
    risk_tier = "low"
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
                        "label_like": {
                            "type": "string",
                            "description": "Substring to match the node label (case-insensitive).",
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["concept", "instance", "document", "property"],
                        },
                    },
                    "required": ["label_like"],
                },
                "description": "One or more node patterns to match.",
            },
            "graph_id": {
                "type": "string",
                "description": "Optional. UUID of the atlas graph to query. Defaults to the agent's primary atlas.",
            },
            "limit": {"type": "integer", "default": 25, "minimum": 1, "maximum": 200},
        },
        "required": ["patterns"],
    }

    def __init__(
        self,
        tenant_id: str,
        agent_id: str = "",
        allowed_graph_ids: list[str] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.allowed_graph_ids = allowed_graph_ids or []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        # Accept three input shapes — the LLM tends to pass `query` or
        # `q`, the docs show `patterns: [{label_like: ...}]`, and some
        # seeded pipelines used `patterns: ["Asset"]` (string list).
        # Normalize all of them to the canonical {label_like} shape.
        patterns = arguments.get("patterns") or []
        if not patterns:
            single = arguments.get("query") or arguments.get("q")
            if single:
                patterns = [single]
        if not patterns:
            return ToolResult(
                content=(
                    "No patterns supplied. Pass either `patterns: [{label_like: 'Asset'}]` "
                    "or `query: 'Asset'` to search the ontology."
                ),
                is_error=True,
            )
        # Coerce string patterns to the canonical {label_like} object.
        patterns = [{"label_like": p} if isinstance(p, str) else p for p in patterns]
        graph_id = arguments.get("graph_id")
        limit = max(1, min(int(arguments.get("limit") or 25), 200))

        try:
            pool = await _pool()
            async with pool.acquire() as conn:
                gid = await _resolve_graph_id(
                    conn, self.tenant_id, self.allowed_graph_ids, graph_id
                )
                if not gid:
                    return ToolResult(
                        content="No accessible atlas graph found.", is_error=True
                    )
                gid_uuid = _uuid.UUID(gid)

                cand_lists: list[list[dict[str, Any]]] = []
                for p in patterns:
                    like = (p.get("label_like") or "").lower().strip()
                    kind = p.get("kind")
                    if kind:
                        rows = await conn.fetch(
                            "SELECT id, label, kind::text, description FROM atlas_nodes "
                            "WHERE graph_id = $1 AND lower(label) LIKE $2 AND kind::text = $3 LIMIT 50",
                            gid_uuid,
                            f"%{like}%",
                            kind,
                        )
                    else:
                        rows = await conn.fetch(
                            "SELECT id, label, kind::text, description FROM atlas_nodes "
                            "WHERE graph_id = $1 AND lower(label) LIKE $2 LIMIT 50",
                            gid_uuid,
                            f"%{like}%",
                        )
                    cand_lists.append(
                        [
                            {
                                "id": str(r["id"]),
                                "label": r["label"],
                                "kind": r["kind"],
                                "description": r["description"] or "",
                            }
                            for r in rows
                        ]
                    )

                if len(cand_lists) == 1:
                    matches = cand_lists[0][:limit]
                    return ToolResult(
                        content=json.dumps(
                            {
                                "graph_id": gid,
                                "matches": matches,
                                "count": len(matches),
                            },
                            indent=2,
                        )
                    )

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

                return ToolResult(
                    content=json.dumps(
                        {
                            "graph_id": gid,
                            "matches": tuples,
                            "count": len(tuples),
                        },
                        indent=2,
                    )
                )
        except Exception as e:
            logger.exception("atlas_query failed")
            return ToolResult(content=f"atlas_query failed: {e}", is_error=True)


class AtlasTraverseTool(BaseTool):
    name = "atlas_traverse"
    risk_tier = "low"
    description = (
        "Return the 1-hop neighbourhood of a node (incoming + outgoing edges "
        "and the nodes on the other end). Pick the node by exact label match, "
        "or by id if you already have it. Use when you've located a concept "
        "and want to walk to related concepts."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "label": {
                "type": "string",
                "description": "Exact label of the node (case-insensitive).",
            },
            "node_id": {
                "type": "string",
                "description": "Or pass a node UUID directly.",
            },
            "graph_id": {"type": "string"},
            "max_edges": {
                "type": "integer",
                "default": 50,
                "minimum": 1,
                "maximum": 200,
            },
        },
    }

    def __init__(
        self,
        tenant_id: str,
        agent_id: str = "",
        allowed_graph_ids: list[str] | None = None,
    ) -> None:
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
                gid = await _resolve_graph_id(
                    conn,
                    self.tenant_id,
                    self.allowed_graph_ids,
                    arguments.get("graph_id"),
                )
                if not gid:
                    return ToolResult(
                        content="No accessible atlas graph found.", is_error=True
                    )
                gid_uuid = _uuid.UUID(gid)

                if node_id and _as_uuid(node_id):
                    node = await conn.fetchrow(
                        "SELECT id, label, kind::text, description FROM atlas_nodes "
                        "WHERE id = $1 AND graph_id = $2",
                        _uuid.UUID(node_id),
                        gid_uuid,
                    )
                else:
                    node = await conn.fetchrow(
                        "SELECT id, label, kind::text, description FROM atlas_nodes "
                        "WHERE graph_id = $1 AND lower(label) = lower($2) LIMIT 1",
                        gid_uuid,
                        label,
                    )
                if not node:
                    return ToolResult(
                        content=json.dumps({"found": False, "label": label or None})
                    )

                nid = str(node["id"])
                edges = await conn.fetch(
                    "SELECT e.id, e.from_node_id, e.to_node_id, e.label, e.cardinality_from, e.cardinality_to, "
                    "       fn.label AS from_label, tn.label AS to_label "
                    "FROM atlas_edges e "
                    "JOIN atlas_nodes fn ON fn.id = e.from_node_id "
                    "JOIN atlas_nodes tn ON tn.id = e.to_node_id "
                    "WHERE e.graph_id = $1 AND (e.from_node_id = $2 OR e.to_node_id = $2) "
                    "LIMIT $3",
                    gid_uuid,
                    _uuid.UUID(nid),
                    max_edges,
                )

                outgoing = [
                    {
                        "edge_id": str(r["id"]),
                        "label": r["label"],
                        "cardinality_from": r["cardinality_from"],
                        "cardinality_to": r["cardinality_to"],
                        "to": {"id": str(r["to_node_id"]), "label": r["to_label"]},
                    }
                    for r in edges
                    if str(r["from_node_id"]) == nid
                ]
                incoming = [
                    {
                        "edge_id": str(r["id"]),
                        "label": r["label"],
                        "cardinality_from": r["cardinality_from"],
                        "cardinality_to": r["cardinality_to"],
                        "from": {
                            "id": str(r["from_node_id"]),
                            "label": r["from_label"],
                        },
                    }
                    for r in edges
                    if str(r["to_node_id"]) == nid
                ]

                return ToolResult(
                    content=json.dumps(
                        {
                            "graph_id": gid,
                            "node": {
                                "id": nid,
                                "label": node["label"],
                                "kind": node["kind"],
                                "description": node["description"] or "",
                            },
                            "outgoing": outgoing,
                            "incoming": incoming,
                            "edge_count": len(outgoing) + len(incoming),
                        },
                        indent=2,
                    )
                )
        except Exception as e:
            logger.exception("atlas_traverse failed")
            return ToolResult(content=f"atlas_traverse failed: {e}", is_error=True)


class AtlasSearchGroundedTool(BaseTool):
    name = "atlas_search_grounded"
    risk_tier = "low"
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
            "near_label": {
                "type": "string",
                "description": "Concept label to ground retrieval around (e.g. 'Counterparty').",
            },
            "graph_id": {"type": "string"},
            "max_docs": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
        },
        "required": ["near_label"],
    }

    def __init__(
        self,
        tenant_id: str,
        agent_id: str = "",
        allowed_graph_ids: list[str] | None = None,
    ) -> None:
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
                gid = await _resolve_graph_id(
                    conn,
                    self.tenant_id,
                    self.allowed_graph_ids,
                    arguments.get("graph_id"),
                )
                if not gid:
                    return ToolResult(
                        content="No accessible atlas graph found.", is_error=True
                    )
                gid_uuid = _uuid.UUID(gid)

                # instances count as seeds too, an agent asks about "Nordtek" as often as "Supplier"
                seeds = await conn.fetch(
                    "SELECT id, label, kind::text AS kind FROM atlas_nodes "
                    "WHERE graph_id = $1 AND lower(label) LIKE $2 AND kind::text <> 'document' "
                    "ORDER BY (lower(label) = $3) DESC, length(label) LIMIT 5",
                    gid_uuid,
                    f"%{near.lower()}%",
                    near.lower(),
                )
                if not seeds:
                    labels = await conn.fetch(
                        "SELECT label FROM atlas_nodes WHERE graph_id = $1 "
                        "AND kind::text <> 'document' ORDER BY label LIMIT 40",
                        gid_uuid,
                    )
                    return ToolResult(
                        content=json.dumps(
                            {
                                "found": False,
                                "near_label": near,
                                "labels_in_graph": [r["label"] for r in labels],
                                "hint": "Retry with one of these labels, or use knowledge_search for document text.",
                            }
                        )
                    )

                seed_ids = [r["id"] for r in seeds]
                docs = await conn.fetch(
                    "SELECT DISTINCT n.id, n.label, n.document_id, n.properties "
                    "FROM atlas_nodes n "
                    "JOIN atlas_edges e ON (e.from_node_id = n.id OR e.to_node_id = n.id) "
                    "WHERE n.graph_id = $1 AND n.kind::text = 'document' "
                    "  AND (e.from_node_id = ANY($2::uuid[]) OR e.to_node_id = ANY($2::uuid[])) "
                    "LIMIT $3",
                    gid_uuid,
                    seed_ids,
                    max_docs,
                )

                rel = await conn.fetch(
                    "SELECT e.label AS rel, a.label AS src, b.label AS dst "
                    "FROM atlas_edges e "
                    "JOIN atlas_nodes a ON a.id = e.from_node_id "
                    "JOIN atlas_nodes b ON b.id = e.to_node_id "
                    "WHERE e.from_node_id = ANY($1::uuid[]) OR e.to_node_id = ANY($1::uuid[]) "
                    "LIMIT 40",
                    seed_ids,
                )
                neighbours = [f"{r['src']} -[{r['rel']}]-> {r['dst']}" for r in rel]
                return ToolResult(
                    content=json.dumps(
                        {
                            "graph_id": gid,
                            "near_label": near,
                            "seeds": [
                                {
                                    "id": str(s["id"]),
                                    "label": s["label"],
                                    "kind": s["kind"],
                                }
                                for s in seeds
                            ],
                            "neighbours": neighbours,
                            "documents": [
                                {
                                    "node_id": str(d["id"]),
                                    "filename": d["label"],
                                    "kb_document_id": (
                                        str(d["document_id"])
                                        if d["document_id"]
                                        else None
                                    ),
                                    "properties": (
                                        json.loads(d["properties"])
                                        if isinstance(d["properties"], str)
                                        else (d["properties"] or {})
                                    ),
                                }
                                for d in docs
                            ],
                            "count": len(docs),
                        },
                        indent=2,
                    )
                )
        except Exception as e:
            logger.exception("atlas_search_grounded failed")
            return ToolResult(
                content=f"atlas_search_grounded failed: {e}", is_error=True
            )


async def _entity_counts(
    conn: asyncpg.Connection, graph_id: _uuid.UUID
) -> dict[str, Any] | None:
    """How many real entities Cognify has found per concept, when a collection is bound."""
    kb = await conn.fetchval("SELECT kb_id FROM atlas_graphs WHERE id = $1", graph_id)
    if not kb or not isinstance(kb, _uuid.UUID):
        return None
    rows = await conn.fetch(
        "SELECT coalesce(n.label, e.entity_type) AS concept, count(*) AS c "
        "FROM graph_entities e LEFT JOIN atlas_nodes n ON n.id = e.atlas_concept_id "
        "WHERE e.kb_id = $1 GROUP BY 1 ORDER BY c DESC LIMIT 50",
        kb,
    )
    return {
        "kb_id": str(kb),
        "entities_by_concept": {r["concept"]: int(r["c"]) for r in rows},
    }


class AtlasInstancesTool(BaseTool):
    name = "atlas_instances"
    risk_tier = "low"
    description = (
        "Read the real entities behind an atlas concept, the instances Cognify "
        "extracted from the bound knowledge collection into the graph database. "
        "List them by concept, find one by name, or follow a relationship from "
        "one concept to another. Use after atlas_describe when the question is "
        "about actual things and not the schema."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "graph_id": {
                "type": "string",
                "description": "Optional. Defaults to the agent's primary atlas.",
            },
            "concept": {
                "type": "string",
                "description": "Concept label, for example Counterparty.",
            },
            "name": {
                "type": "string",
                "description": "Find entities by name or alias, or the start of a neighbourhood.",
            },
            "neighbours": {
                "type": "boolean",
                "description": "Return what the entity called name relates to.",
                "default": False,
            },
            "relationship": {
                "type": "string",
                "description": "Only this relationship type, for example SETTLES_VIA.",
            },
            "to_concept": {
                "type": "string",
                "description": "Follow relationships from concept to this concept.",
            },
            "limit": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
        },
    }

    def __init__(
        self,
        tenant_id: str,
        agent_id: str = "",
        allowed_graph_ids: list[str] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.allowed_graph_ids = allowed_graph_ids or []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from engine.knowledge.document_acl import hidden_for_search
        from engine.knowledge.neo4j_client import (
            browse_entities,
            entity_neighbourhood,
            query_entities,
        )

        limit = max(1, min(int(arguments.get("limit") or 25), 100))
        concept = (arguments.get("concept") or "").strip() or None
        name = (arguments.get("name") or "").strip() or None
        relationship = (arguments.get("relationship") or "").strip() or None
        to_concept = (arguments.get("to_concept") or "").strip() or None
        try:
            pool = await _pool()
            async with pool.acquire() as conn:
                gid = await _resolve_graph_id(
                    conn,
                    self.tenant_id,
                    self.allowed_graph_ids,
                    arguments.get("graph_id"),
                )
                if not gid:
                    return ToolResult(
                        content="No accessible atlas graph found.", is_error=True
                    )
                kb = await conn.fetchval(
                    "SELECT kb_id FROM atlas_graphs WHERE id = $1", _uuid.UUID(gid)
                )
            if not kb:
                return ToolResult(
                    content="This atlas is not bound to a knowledge collection.",
                    is_error=True,
                )
            kb_id = str(kb)
            hidden = sorted(await hidden_for_search([kb_id], agent_id=self.agent_id))
            scope = {"tenant_id": self.tenant_id, "limit": limit, "hidden": hidden}
            if arguments.get("neighbours") and name:
                out = await entity_neighbourhood(
                    kb_id, name, relationship=relationship, **scope
                )
            elif relationship or to_concept:
                out = {
                    "matches": await query_entities(
                        kb_id,
                        from_type=concept,
                        relationship=relationship,
                        to_type=to_concept,
                        name=name,
                        **scope,
                    )
                }
            else:
                out = await browse_entities(
                    kb_id, entity_type=concept, query=name, **scope
                )
            return ToolResult(
                content=json.dumps(
                    {"graph_id": gid, "kb_id": kb_id, **out}, indent=2, default=str
                )
            )
        except Exception as e:
            logger.warning("atlas_instances failed: %s", e)
            return ToolResult(content=f"atlas_instances failed: {e}", is_error=True)


class AtlasDescribeTool(BaseTool):
    name = "atlas_describe"
    risk_tier = "low"
    description = (
        "Summarise an atlas graph: total nodes/edges per kind, top edge labels, "
        "and the most-connected concepts. Use as the first step when the user "
        "asks 'what do you know about X?' — gives the agent a map of the "
        "domain before it dives into specifics."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "graph_id": {
                "type": "string",
                "description": "Optional. Defaults to the agent's primary atlas.",
            },
            "top_n": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
        },
    }

    def __init__(
        self,
        tenant_id: str,
        agent_id: str = "",
        allowed_graph_ids: list[str] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.allowed_graph_ids = allowed_graph_ids or []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        top_n = max(1, min(int(arguments.get("top_n") or 10), 50))
        try:
            pool = await _pool()
            async with pool.acquire() as conn:
                gid = await _resolve_graph_id(
                    conn,
                    self.tenant_id,
                    self.allowed_graph_ids,
                    arguments.get("graph_id"),
                )
                if not gid:
                    return ToolResult(
                        content="No accessible atlas graph found.", is_error=True
                    )
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
                    gid_uuid,
                    top_n,
                )
                top_concepts = await conn.fetch(
                    "SELECT n.label, d.c FROM (SELECT id, count(*) AS c FROM ("
                    "SELECT from_node_id AS id FROM atlas_edges WHERE graph_id = $1 "
                    "UNION ALL SELECT to_node_id FROM atlas_edges WHERE graph_id = $1"
                    ") ends GROUP BY id) d JOIN atlas_nodes n ON n.id = d.id "
                    "WHERE n.kind::text = 'concept' ORDER BY d.c DESC LIMIT $2",
                    gid_uuid,
                    top_n,
                )
                entity_counts = await _entity_counts(conn, gid_uuid)
                return ToolResult(
                    content=json.dumps(
                        {
                            "graph_id": gid,
                            "name": meta["name"] if meta else None,
                            "description": (meta["description"] if meta else None)
                            or "",
                            "version": int(meta["version"]) if meta else 0,
                            "totals": {
                                "nodes": int(meta["node_count"]) if meta else 0,
                                "edges": int(meta["edge_count"]) if meta else 0,
                            },
                            "by_kind": {r["k"]: int(r["c"]) for r in kind_counts},
                            "top_edge_labels": [
                                {"label": r["label"], "count": int(r["c"])}
                                for r in top_edges
                            ],
                            "most_connected_concepts": [
                                {"label": r["label"], "edges": int(r["c"])}
                                for r in top_concepts
                            ],
                            "context_graph": entity_counts,
                        },
                        indent=2,
                    )
                )
        except Exception as e:
            logger.exception("atlas_describe failed")
            return ToolResult(content=f"atlas_describe failed: {e}", is_error=True)


def _parse_as_of(raw: str | None) -> datetime | None:
    if not raw:
        return datetime.now(timezone.utc)
    s = str(raw).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _as_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        return _parse_as_of(v)
    return None


def _in_window(row: dict[str, Any], as_of: datetime) -> bool:
    created = _as_dt(row.get("created_at"))
    vf = _as_dt(row.get("valid_from"))
    vt = _as_dt(row.get("valid_to"))
    if created and created > as_of:
        return False
    if vf and vf > as_of:
        return False
    if vt and vt <= as_of:
        return False
    return True


def _shape_as_of(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    label_like: str,
    kind: str,
    limit: int,
) -> dict[str, Any]:
    by_id = {str(n["id"]): n for n in nodes}
    picked = [
        n
        for n in nodes
        if (not label_like or label_like in str(n.get("label") or "").lower())
        and (not kind or str(n.get("kind") or "") == kind)
    ]
    picked_ids = {str(n["id"]) for n in picked}
    filtered = bool(label_like or kind)
    rel = [
        e
        for e in edges
        if str(e.get("from_node_id")) in by_id
        and str(e.get("to_node_id")) in by_id
        and (
            not filtered
            or str(e.get("from_node_id")) in picked_ids
            or str(e.get("to_node_id")) in picked_ids
        )
    ]
    return {
        "node_total": len(picked),
        "edge_total": len(rel),
        "truncated": len(picked) > limit or len(rel) > limit,
        "nodes": [
            {
                "id": str(n["id"]),
                "label": n.get("label"),
                "kind": n.get("kind"),
                "description": n.get("description") or "",
            }
            for n in picked[:limit]
        ],
        "edges": [
            {
                "id": str(e["id"]),
                "label": e.get("label"),
                "from": {
                    "id": str(e["from_node_id"]),
                    "label": by_id[str(e["from_node_id"])].get("label"),
                },
                "to": {
                    "id": str(e["to_node_id"]),
                    "label": by_id[str(e["to_node_id"])].get("label"),
                },
            }
            for e in rel[:limit]
        ],
    }


AS_OF_SCAN = 5000


async def _snapshot_state(
    conn: asyncpg.Connection,
    graph_id: _uuid.UUID,
    version: int,
    label_like: str,
    kind: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The graph at a version, each row's newest change at or before it."""
    state = (
        "SELECT DISTINCT ON (row_id) row_id, deleted, payload FROM atlas_snapshot_rows "
        "WHERE graph_id = $1 AND kind = '{kind}' AND version <= $2 "
        "ORDER BY row_id, version DESC"
    )
    node_rows = await conn.fetch(
        f"SELECT payload FROM ({state.format(kind='n')}) s WHERE NOT deleted "
        "AND ($3 = '' OR lower(payload->>'label') LIKE $4) "
        "AND ($5 = '' OR payload->>'kind' = $5) LIMIT $6",
        graph_id,
        version,
        label_like,
        f"%{label_like}%",
        kind,
        AS_OF_SCAN,
    )
    nodes = [_payload(r["payload"]) for r in node_rows]
    ids = [str(n["id"]) for n in nodes]
    edge_rows = await conn.fetch(
        f"SELECT payload FROM ({state.format(kind='e')}) s WHERE NOT deleted "
        "AND payload->>'from_node_id' = ANY($3) AND payload->>'to_node_id' = ANY($3) "
        "LIMIT $4",
        graph_id,
        version,
        ids,
        AS_OF_SCAN,
    )
    return nodes, [_payload(r["payload"]) for r in edge_rows]


def _payload(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value or {})


class AtlasAsOfTool(BaseTool):
    name = "atlas_as_of"
    risk_tier = "low"
    description = (
        "Show an atlas graph as it stood at a past moment. Reads the newest "
        "saved snapshot taken at or before the timestamp, or the live graph "
        "when nothing changed since then, and honours valid_from / valid_to "
        "on live rows. Use for 'what did the ontology say on date X' and audit "
        "questions. Optionally narrow to nodes whose label contains a term."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "graph_id": {
                "type": "string",
                "description": "Optional. Defaults to the agent's primary atlas.",
            },
            "as_of": {
                "type": "string",
                "description": "ISO-8601 date or timestamp, UTC when no offset is given. Defaults to now.",
            },
            "label_like": {
                "type": "string",
                "description": "Only nodes whose label contains this text (case-insensitive), plus their edges.",
            },
            "kind": {
                "type": "string",
                "enum": ["concept", "instance", "document", "property"],
            },
            "limit": {
                "type": "integer",
                "description": "Max nodes and max edges returned.",
                "default": 100,
                "minimum": 1,
                "maximum": 1000,
            },
        },
    }

    def __init__(
        self,
        tenant_id: str,
        agent_id: str = "",
        allowed_graph_ids: list[str] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.allowed_graph_ids = allowed_graph_ids or []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        as_of = _parse_as_of(arguments.get("as_of"))
        if as_of is None:
            return ToolResult(
                content="as_of must be an ISO-8601 date or timestamp", is_error=True
            )
        label_like = (arguments.get("label_like") or "").strip().lower()
        kind = (arguments.get("kind") or "").strip()
        limit = max(1, min(int(arguments.get("limit") or 100), 1000))
        try:
            pool = await _pool()
            async with pool.acquire() as conn:
                gid = await _resolve_graph_id(
                    conn,
                    self.tenant_id,
                    self.allowed_graph_ids,
                    arguments.get("graph_id"),
                )
                if not gid:
                    return ToolResult(
                        content="No accessible atlas graph found.", is_error=True
                    )
                gid_uuid = _uuid.UUID(gid)
                graph = await conn.fetchrow(
                    "SELECT created_at, updated_at, version FROM atlas_graphs WHERE id = $1",
                    gid_uuid,
                )
                out: dict[str, Any] = {"graph_id": gid, "as_of": as_of.isoformat()}
                created = _as_dt(graph["created_at"]) if graph else None
                if created and as_of < created:
                    out.update(
                        found=False,
                        reason=f"the graph was created at {created.isoformat()}",
                    )
                    return ToolResult(content=json.dumps(out, indent=2))

                updated = _as_dt(graph["updated_at"]) if graph else None
                if updated is None or as_of >= updated:
                    node_rows = await conn.fetch(
                        "SELECT id, label, kind::text AS kind, description, "
                        "created_at, valid_from, valid_to FROM atlas_nodes "
                        "WHERE graph_id = $1 AND ($3 = '' OR lower(label) LIKE $4) "
                        "AND ($5 = '' OR kind::text = $5) LIMIT $2",
                        gid_uuid,
                        AS_OF_SCAN,
                        label_like,
                        f"%{label_like}%",
                        kind,
                    )
                    edge_rows = await conn.fetch(
                        "SELECT id, from_node_id, to_node_id, label, created_at, "
                        "valid_from, valid_to FROM atlas_edges "
                        "WHERE graph_id = $1 AND from_node_id = ANY($2) "
                        "AND to_node_id = ANY($2) LIMIT $3",
                        gid_uuid,
                        [r["id"] for r in node_rows],
                        AS_OF_SCAN,
                    )
                    nodes = [dict(r) for r in node_rows if _in_window(dict(r), as_of)]
                    edges = [dict(r) for r in edge_rows if _in_window(dict(r), as_of)]
                    out.update(
                        found=True,
                        source="live",
                        version=graph["version"] if graph else None,
                    )
                else:
                    snap = await conn.fetchrow(
                        "SELECT id, version, label, created_at, payload "
                        "FROM atlas_snapshots WHERE graph_id = $1 AND created_at <= $2 "
                        "ORDER BY created_at DESC LIMIT 1",
                        gid_uuid,
                        as_of,
                    )
                    if not snap:
                        first = await conn.fetchval(
                            "SELECT min(created_at) FROM atlas_snapshots WHERE graph_id = $1",
                            gid_uuid,
                        )
                        reason = "no snapshot was saved at or before as_of"
                        if first:
                            reason += f", the earliest is {_as_dt(first).isoformat()}"
                        out.update(found=False, reason=reason)
                        return ToolResult(content=json.dumps(out, indent=2))
                    payload = snap["payload"]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    payload = payload or {}
                    if payload.get("format") == "diff":
                        nodes, edges = await _snapshot_state(
                            conn, gid_uuid, snap["version"], label_like, kind
                        )
                    else:
                        nodes = list(payload.get("nodes") or [])
                        edges = list(payload.get("edges") or [])
                    out.update(
                        found=True,
                        source="snapshot",
                        version=snap["version"],
                        snapshot={
                            "id": str(snap["id"]),
                            "version": snap["version"],
                            "label": snap["label"],
                            "created_at": _as_dt(snap["created_at"]).isoformat(),
                        },
                    )
                out.update(
                    _shape_as_of(
                        nodes, edges, label_like=label_like, kind=kind, limit=limit
                    )
                )
                return ToolResult(content=json.dumps(out, indent=2, default=str))
        except Exception as e:
            logger.exception("atlas_as_of failed")
            return ToolResult(content=f"atlas_as_of failed: {e}", is_error=True)


ATLAS_TOOL_NAMES = {
    "atlas_query": AtlasQueryTool,
    "atlas_traverse": AtlasTraverseTool,
    "atlas_search_grounded": AtlasSearchGroundedTool,
    "atlas_describe": AtlasDescribeTool,
    "atlas_as_of": AtlasAsOfTool,
    "atlas_instances": AtlasInstancesTool,
}
