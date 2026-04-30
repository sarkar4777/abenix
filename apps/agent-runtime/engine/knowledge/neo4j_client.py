"""Neo4j async connection pool manager for the Knowledge Engine."""

from __future__ import annotations

import logging
import os
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession

logger = logging.getLogger(__name__)

_NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
_NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
_NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "abenix")
_NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

_driver: AsyncDriver | None = None


async def get_neo4j_driver() -> AsyncDriver:
    """Get or create the global Neo4j async driver."""
    global _driver
    if _driver is None:
        logger.info("Connecting to Neo4j at %s", _NEO4J_URI)
        _driver = AsyncGraphDatabase.driver(
            _NEO4J_URI,
            auth=(_NEO4J_USER, _NEO4J_PASSWORD),
            max_connection_pool_size=50,
        )
        # Verify connectivity
        try:
            await _driver.verify_connectivity()
            logger.info("Neo4j connection verified")
        except Exception as e:
            logger.warning("Neo4j not available: %s (knowledge graph features disabled)", e)
    return _driver


async def get_neo4j_session() -> AsyncSession:
    """Get a new Neo4j session from the pool."""
    driver = await get_neo4j_driver()
    return driver.session(database=_NEO4J_DATABASE)


async def close_neo4j() -> None:
    """Close the Neo4j driver (call on application shutdown)."""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
        logger.info("Neo4j connection closed")


async def is_neo4j_available() -> bool:
    """Check if Neo4j is reachable."""
    try:
        driver = await get_neo4j_driver()
        await driver.verify_connectivity()
        return True
    except Exception:
        return False


async def ensure_schema() -> None:
    """Create Neo4j constraints and indexes for the knowledge graph.

    Call once on startup. Idempotent (IF NOT EXISTS).
    """
    driver = await get_neo4j_driver()
    async with driver.session(database=_NEO4J_DATABASE) as session:
        constraints = [
            # Unique entity per KB
            "CREATE CONSTRAINT entity_kb_name IF NOT EXISTS "
            "FOR (e:Entity) REQUIRE (e.kb_id, e.canonical_name) IS UNIQUE",
        ]
        indexes = [
            "CREATE INDEX entity_type_idx IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)",
            "CREATE INDEX entity_kb_idx IF NOT EXISTS FOR (e:Entity) ON (e.kb_id)",
            "CREATE INDEX entity_pg_id_idx IF NOT EXISTS FOR (e:Entity) ON (e.pg_id)",
        ]
        for stmt in constraints + indexes:
            try:
                await session.run(stmt)
            except Exception as e:
                logger.debug("Neo4j schema statement skipped: %s — %s", stmt[:60], e)
        logger.info("Neo4j schema ensured (constraints + indexes)")


async def get_graph_stats(kb_id: str) -> dict[str, Any]:
    """Get node/edge counts for a knowledge base from Neo4j."""
    driver = await get_neo4j_driver()
    async with driver.session(database=_NEO4J_DATABASE) as session:
        result = await session.run(
            """
            MATCH (e:Entity {kb_id: $kb_id})
            WITH count(e) AS entity_count
            OPTIONAL MATCH (:Entity {kb_id: $kb_id})-[r]->(:Entity {kb_id: $kb_id})
            RETURN entity_count, count(r) AS relationship_count
            """,
            kb_id=kb_id,
        )
        record = await result.single()
        if record:
            return {
                "entity_count": record["entity_count"],
                "relationship_count": record["relationship_count"],
            }
        return {"entity_count": 0, "relationship_count": 0}


async def get_subgraph(kb_id: str, limit: int = 100) -> dict[str, Any]:
    """Get a subgraph for visualization — top entities by mention count + their relationships."""
    driver = await get_neo4j_driver()
    async with driver.session(database=_NEO4J_DATABASE) as session:
        # Fetch top entities
        result = await session.run(
            """
            MATCH (e:Entity {kb_id: $kb_id})
            RETURN e.pg_id AS id, e.canonical_name AS name, e.entity_type AS type,
                   e.mention_count AS mentions, e.description AS description
            ORDER BY e.mention_count DESC
            LIMIT $limit
            """,
            kb_id=kb_id, limit=limit,
        )
        nodes = [dict(record) async for record in result]
        node_ids = {n["name"] for n in nodes}

        # Fetch relationships between these entities
        result = await session.run(
            """
            MATCH (a:Entity {kb_id: $kb_id})-[r]->(b:Entity {kb_id: $kb_id})
            WHERE a.canonical_name IN $names AND b.canonical_name IN $names
            RETURN a.canonical_name AS source, b.canonical_name AS target,
                   type(r) AS relationship, r.weight AS weight
            """,
            kb_id=kb_id, names=list(node_ids),
        )
        edges = [dict(record) async for record in result]

        return {"nodes": nodes, "edges": edges}
