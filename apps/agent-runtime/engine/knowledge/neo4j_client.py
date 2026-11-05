"""Neo4j async connection pool manager for the Knowledge Engine."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession, Query

logger = logging.getLogger(__name__)
# CALL { WITH x } runs on every 5.x the chart supports, 5.26 only warns about it per query
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

_LUCENE_SPECIAL = re.compile(r'[+\-!(){}\[\]^"~*?:\\/&|]')

_NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
_NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
_NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "abenix")
_NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

QUERY_TIMEOUT_S = float(os.environ.get("NEO4J_QUERY_TIMEOUT_S", "15"))
WRITE_TIMEOUT_S = float(os.environ.get("NEO4J_WRITE_TIMEOUT_S", "120"))
FULLTEXT_INDEX = "entity_names"

_driver: AsyncDriver | None = None
_driver_loop: asyncio.AbstractEventLoop | None = None
_schema_ready = False
_keys_ready: set[str] = set()


def cypher(text: str, timeout: float | None = None) -> Query:
    """A read query the server aborts at the timeout."""
    return Query(text, timeout=timeout if timeout is not None else QUERY_TIMEOUT_S)


def entity_scope(var: str = "e") -> str:
    """The predicate every graph read applies first, KB always and tenant once it is known."""
    return (
        f"{var}.kb_id = $kb_id AND "
        f"($tenant_id = '' OR coalesce({var}.tenant_id, $tenant_id) = $tenant_id)"
    )


def visible(var: str = "e") -> str:
    """A graph fact stays visible while at least one of its source documents is."""
    return (
        f"(size(coalesce({var}.source_doc_ids, [])) = 0 "
        f"OR any(d IN {var}.source_doc_ids WHERE NOT d IN $hidden))"
    )


def kb_token(kb_id: str) -> str:
    """One Lucene token for a KB, the analyzer would split a dashed UUID."""
    return re.sub(r"[^0-9a-zA-Z]", "", kb_id)


def _lucene_escape(text: str) -> str:
    return _LUCENE_SPECIAL.sub(lambda m: "\\" + m.group(0), text)


def fulltext_query(kb_id: str, text: str, exact_only: bool = False) -> str:
    """Lucene query with the KB filter inside it, so scoring only sees that KB."""
    cleaned = " ".join(text.split())
    phrase = _lucene_escape(cleaned)
    parts = [f'canonical_name:"{phrase}"^4', f'aliases:"{phrase}"^3']
    terms = [_lucene_escape(t) for t in cleaned.split(" ") if t]
    if not exact_only and terms:
        joined = " AND ".join(terms)
        parts += [f"canonical_name:({joined})", f"aliases:({joined})"]
    return f"+kb_token:{kb_token(kb_id)} +({' '.join(parts)})"


async def get_neo4j_driver() -> AsyncDriver:
    """Get or create the Neo4j driver for this event loop. Workers open a new loop per task."""
    global _driver, _driver_loop, _schema_ready
    loop = asyncio.get_running_loop()
    if _driver is not None and _driver_loop is not loop:
        _driver = None
        _schema_ready = False
    if _driver is None:
        _driver_loop = loop
        logger.info("Connecting to Neo4j at %s", _NEO4J_URI)
        _driver = AsyncGraphDatabase.driver(
            _NEO4J_URI,
            auth=(_NEO4J_USER, _NEO4J_PASSWORD),
            max_connection_pool_size=50,
            connection_acquisition_timeout=30,
            connection_timeout=10,
            max_transaction_retry_time=30,
        )
        # Verify connectivity
        try:
            await _driver.verify_connectivity()
            logger.info("Neo4j connection verified")
        except Exception as e:
            logger.warning(
                "Neo4j not available: %s (knowledge graph features disabled)", e
            )
    return _driver


async def get_neo4j_session() -> AsyncSession:
    """Get a new Neo4j session from the pool."""
    driver = await get_neo4j_driver()
    return driver.session(database=_NEO4J_DATABASE)


async def close_neo4j() -> None:
    """Close the Neo4j driver (call on application shutdown)."""
    global _driver, _schema_ready
    if _driver:
        await _driver.close()
        _driver = None
        _schema_ready = False
        logger.info("Neo4j connection closed")


def forget_driver() -> None:
    """Drop a driver whose event loop is gone, a new loop must open its own connections."""
    global _driver, _schema_ready
    _driver = None
    _schema_ready = False


async def is_neo4j_available() -> bool:
    """Check if Neo4j is reachable."""
    try:
        driver = await get_neo4j_driver()
        await driver.verify_connectivity()
        return True
    except Exception:
        return False


SCHEMA_STATEMENTS = (
    "CREATE CONSTRAINT entity_kb_name IF NOT EXISTS "
    "FOR (e:Entity) REQUIRE (e.kb_id, e.canonical_name) IS UNIQUE",
    "CREATE INDEX entity_type_idx IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)",
    "CREATE INDEX entity_kb_idx IF NOT EXISTS FOR (e:Entity) ON (e.kb_id)",
    "CREATE INDEX entity_pg_id_idx IF NOT EXISTS FOR (e:Entity) ON (e.pg_id)",
    "CREATE INDEX entity_kb_key_idx IF NOT EXISTS FOR (e:Entity) ON (e.kb_id, e.name_key)",
    "CREATE INDEX entity_kb_type_idx IF NOT EXISTS FOR (e:Entity) ON (e.kb_id, e.entity_type)",
    "CREATE INDEX entity_kb_concept_idx IF NOT EXISTS "
    "FOR (e:Entity) ON (e.kb_id, e.atlas_concept_id)",
    "CREATE INDEX entity_kb_mentions_idx IF NOT EXISTS "
    "FOR (e:Entity) ON (e.kb_id, e.mention_count)",
    f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX} IF NOT EXISTS FOR (e:Entity) "
    "ON EACH [e.canonical_name, e.aliases, e.kb_token] "
    "OPTIONS {indexConfig: {`fulltext.analyzer`: 'standard-no-stop-words', "
    "`fulltext.eventually_consistent`: false}}",
)


async def ensure_schema(force: bool = False) -> None:
    """Create the constraint and indexes once per process. Idempotent."""
    global _schema_ready
    if _schema_ready and not force:
        return
    driver = await get_neo4j_driver()
    failed = 0
    async with driver.session(database=_NEO4J_DATABASE) as session:
        for stmt in SCHEMA_STATEMENTS:
            try:
                await (await session.run(stmt)).consume()
            except Exception as e:
                failed += 1
                logger.warning("Neo4j schema statement failed %s %s", stmt[:60], e)
    _schema_ready = failed == 0
    logger.info("Neo4j schema ensured, %d statements failed", failed)


async def ensure_kb_keys(kb_id: str, tenant_id: str = "", batch: int = 2000) -> int:
    """Stamp the search token and tenant on nodes written before they existed."""
    marker = f"{kb_id}|{tenant_id}"
    if marker in _keys_ready:
        return 0
    driver = await get_neo4j_driver()
    total = 0
    async with driver.session(database=_NEO4J_DATABASE) as session:
        while True:
            result = await session.run(
                cypher(
                    """
                    MATCH (e:Entity {kb_id: $kb_id})
                    WHERE e.kb_token IS NULL
                       OR ($tenant_id <> '' AND e.tenant_id IS NULL)
                    WITH e LIMIT $batch
                    SET e.kb_token = $token,
                        e.tenant_id = coalesce(e.tenant_id, CASE WHEN $tenant_id = '' THEN null ELSE $tenant_id END)
                    RETURN count(e) AS n
                    """,
                    timeout=WRITE_TIMEOUT_S,
                ),
                kb_id=kb_id,
                tenant_id=tenant_id,
                token=kb_token(kb_id),
                batch=batch,
            )
            record = await result.single()
            n = record["n"] if record else 0
            total += n
            if n < batch:
                break
    _keys_ready.add(marker)
    return total


async def get_graph_stats(kb_id: str, tenant_id: str = "") -> dict[str, Any]:
    """Get node/edge counts for a knowledge base from Neo4j."""
    driver = await get_neo4j_driver()
    async with driver.session(database=_NEO4J_DATABASE) as session:
        result = await session.run(
            cypher(
                f"""
                MATCH (e:Entity {{kb_id: $kb_id}})
                WHERE {entity_scope("e")}
                WITH count(e) AS entity_count
                OPTIONAL MATCH (a:Entity {{kb_id: $kb_id}})-[r]->(b:Entity {{kb_id: $kb_id}})
                WHERE {entity_scope("a")}
                RETURN entity_count, count(r) AS relationship_count
                """
            ),
            kb_id=kb_id,
            tenant_id=tenant_id,
        )
        record = await result.single()
        if record:
            return {
                "entity_count": record["entity_count"],
                "relationship_count": record["relationship_count"],
            }
        return {"entity_count": 0, "relationship_count": 0}


async def get_subgraph(
    kb_id: str, limit: int = 100, tenant_id: str = ""
) -> dict[str, Any]:
    """Get a subgraph for visualization, top entities by mention count and their relationships."""
    limit = max(1, min(int(limit), 1000))
    driver = await get_neo4j_driver()
    async with driver.session(database=_NEO4J_DATABASE) as session:
        result = await session.run(
            cypher(
                f"""
                MATCH (e:Entity {{kb_id: $kb_id}})
                WHERE {entity_scope("e")}
                RETURN e.pg_id AS id, e.canonical_name AS name, e.entity_type AS type,
                       e.mention_count AS mentions, e.description AS description
                ORDER BY e.mention_count DESC
                LIMIT $limit
                """
            ),
            kb_id=kb_id,
            tenant_id=tenant_id,
            limit=limit,
        )
        nodes = [dict(record) async for record in result]
        names = [n["name"] for n in nodes]

        result = await session.run(
            cypher(
                f"""
                UNWIND $names AS name
                MATCH (a:Entity {{kb_id: $kb_id, canonical_name: name}})
                WHERE {entity_scope("a")}
                CALL {{
                    WITH a
                    MATCH (a)-[r]->(b:Entity {{kb_id: $kb_id}})
                    WHERE b.canonical_name IN $names
                    RETURN r, b LIMIT 200
                }}
                RETURN a.canonical_name AS source, b.canonical_name AS target,
                       type(r) AS relationship, r.weight AS weight
                LIMIT $edge_limit
                """
            ),
            kb_id=kb_id,
            tenant_id=tenant_id,
            names=names,
            edge_limit=limit * 10,
        )
        edges = [dict(record) async for record in result]

        return {"nodes": nodes, "edges": edges}


async def browse_entities(
    kb_id: str,
    tenant_id: str = "",
    entity_type: str | None = None,
    concept_id: str | None = None,
    query: str | None = None,
    after: str = "",
    limit: int = 50,
    hidden: list[str] | None = None,
) -> dict[str, Any]:
    """One page of entities by concept, type or name, keyset paged by canonical name."""
    limit = max(1, min(int(limit), 200))
    params: dict[str, Any] = {
        "kb_id": kb_id,
        "tenant_id": tenant_id,
        "after": after or "",
        "limit": limit + 1,
        "hidden": hidden or [],
    }
    filters = [entity_scope("e"), "e.canonical_name > $after", visible("e")]
    if concept_id or entity_type:
        typed = []
        if concept_id:
            typed.append("e.atlas_concept_id = $concept_id")
            params["concept_id"] = concept_id
        if entity_type:
            typed.append("e.entity_type IN [$entity_type, toLower($entity_type)]")
            params["entity_type"] = entity_type
        filters.append("(" + " OR ".join(typed) + ")")
    where = " AND ".join(filters)
    returning = (
        "RETURN e.canonical_name AS name, e.entity_type AS type, "
        "e.description AS description, e.aliases AS aliases, "
        "e.mention_count AS mentions, e.confidence AS confidence, "
        "e.atlas_concept_id AS concept_id, size(coalesce(e.source_doc_ids, [])) AS documents"
    )
    if query and query.strip():
        await ensure_schema()
        await ensure_kb_keys(kb_id, tenant_id)
        params["ft_index"] = FULLTEXT_INDEX
        params["ft_query"] = fulltext_query(kb_id, query)
        text = (
            "CALL db.index.fulltext.queryNodes($ft_index, $ft_query, {limit: 1000}) "
            f"YIELD node AS e WITH e WHERE {where} {returning} "
            "ORDER BY name LIMIT $limit"
        )
    else:
        text = (
            f"MATCH (e:Entity {{kb_id: $kb_id}}) WHERE {where} {returning} "
            "ORDER BY name LIMIT $limit"
        )
    driver = await get_neo4j_driver()
    async with driver.session(database=_NEO4J_DATABASE) as session:
        result = await session.run(cypher(text), **params)
        rows = [dict(r) async for r in result]
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "entities": rows,
        "next_cursor": rows[-1]["name"] if more and rows else None,
        "limit": limit,
    }


async def entity_neighbourhood(
    kb_id: str,
    name: str,
    tenant_id: str = "",
    limit: int = 50,
    relationship: str | None = None,
    hidden: list[str] | None = None,
) -> dict[str, Any]:
    """One hop around an entity, capped before sorting so a hub cannot blow the query up."""
    limit = max(1, min(int(limit), 200))
    rel_filter = "AND type(r) = $relationship" if relationship else ""
    driver = await get_neo4j_driver()
    params = {
        "kb_id": kb_id,
        "tenant_id": tenant_id,
        "name": name,
        "hidden": hidden or [],
    }
    async with driver.session(database=_NEO4J_DATABASE) as session:
        result = await session.run(
            cypher(
                f"""
                MATCH (e:Entity {{kb_id: $kb_id, canonical_name: $name}})
                WHERE {entity_scope("e")} AND {visible("e")}
                RETURN e.canonical_name AS name, e.entity_type AS type,
                       e.description AS description, e.aliases AS aliases,
                       e.mention_count AS mentions, e.atlas_concept_id AS concept_id
                """
            ),
            **params,
        )
        record = await result.single()
        if not record:
            return {"entity": None, "neighbours": [], "limit": limit}
        result = await session.run(
            cypher(
                f"""
                MATCH (e:Entity {{kb_id: $kb_id, canonical_name: $name}})-[r]-(o:Entity {{kb_id: $kb_id}})
                WHERE {entity_scope("e")} AND {entity_scope("o")} {rel_filter}
                WITH e, r, o LIMIT $scan
                WITH e, r, o WHERE {visible("o")} AND {visible("r")}
                RETURN type(r) AS relationship, startNode(r) = e AS outgoing,
                       r.weight AS weight, r.description AS description,
                       o.canonical_name AS name, o.entity_type AS type,
                       o.atlas_concept_id AS concept_id
                ORDER BY coalesce(weight, 0) DESC
                LIMIT $limit
                """
            ),
            relationship=relationship or "",
            limit=limit,
            scan=limit * 20,
            **params,
        )
        neighbours = [dict(r) async for r in result]
    return {"entity": dict(record), "neighbours": neighbours, "limit": limit}


async def query_entities(
    kb_id: str,
    tenant_id: str = "",
    from_type: str | None = None,
    relationship: str | None = None,
    to_type: str | None = None,
    name: str | None = None,
    limit: int = 50,
    hidden: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Typed relationship rows, the KB fixed at both ends and the expansion capped."""
    limit = max(1, min(int(limit), 200))
    clauses = [entity_scope("a"), entity_scope("b")]
    params: dict[str, Any] = {
        "kb_id": kb_id,
        "tenant_id": tenant_id,
        "limit": limit,
        "scan": limit * 50,
        "hidden": hidden or [],
    }
    if from_type:
        clauses.append("a.entity_type IN [$from_type, toLower($from_type)]")
        params["from_type"] = from_type
    if to_type:
        clauses.append("b.entity_type IN [$to_type, toLower($to_type)]")
        params["to_type"] = to_type
    if relationship:
        clauses.append("type(r) = $relationship")
        params["relationship"] = relationship.upper().replace(" ", "_")
    if name:
        clauses.append("a.canonical_name = $name")
        params["name"] = name
    text = f"""
    MATCH (a:Entity {{kb_id: $kb_id}})-[r]->(b:Entity {{kb_id: $kb_id}})
    WHERE {" AND ".join(clauses)}
    WITH a, r, b LIMIT $scan
    WITH a, r, b WHERE {visible("a")} AND {visible("b")} AND {visible("r")}
    RETURN a.canonical_name AS source, a.entity_type AS source_type,
           type(r) AS relationship, r.weight AS weight,
           b.canonical_name AS target, b.entity_type AS target_type
    ORDER BY coalesce(weight, 0) DESC
    LIMIT $limit
    """
    driver = await get_neo4j_driver()
    async with driver.session(database=_NEO4J_DATABASE) as session:
        result = await session.run(cypher(text), **params)
        return [dict(r) async for r in result]


async def concept_counts(kb_id: str, tenant_id: str = "") -> dict[str, Any]:
    """Live entity counts per type from Neo4j."""
    driver = await get_neo4j_driver()
    async with driver.session(database=_NEO4J_DATABASE) as session:
        result = await session.run(
            cypher(
                f"""
                MATCH (e:Entity {{kb_id: $kb_id}})
                WHERE {entity_scope("e")}
                RETURN e.entity_type AS type, e.atlas_concept_id AS concept_id,
                       count(e) AS n
                """
            ),
            kb_id=kb_id,
            tenant_id=tenant_id,
        )
        rows = [dict(r) async for r in result]
    return {"rows": rows, "total": sum(r["n"] for r in rows)}
