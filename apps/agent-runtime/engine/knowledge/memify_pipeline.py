"""Memify Pipeline — Evolve the knowledge graph based on usage signals and feedback"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from engine.knowledge.neo4j_client import (
    _NEO4J_DATABASE,
    WRITE_TIMEOUT_S,
    cypher,
    get_neo4j_driver,
    is_neo4j_available,
)

logger = logging.getLogger(__name__)

MAX_DERIVE_CANDIDATES = 500


@dataclass
class MemifyResult:
    kb_id: str
    trigger: str  # "scheduled", "feedback", "manual"
    edges_strengthened: int = 0
    edges_weakened: int = 0
    nodes_pruned: int = 0
    edges_pruned: int = 0
    facts_derived: int = 0
    entities_merged: int = 0
    duration_seconds: float = 0.0


async def run_memify(
    kb_id: str,
    trigger: str = "scheduled",
    feedback_data: list[dict[str, Any]] | None = None,
    prune_threshold_days: int = 30,
    min_confidence: float = 0.2,
) -> MemifyResult:
    """Execute the memify pipeline to evolve the knowledge graph."""
    import time

    start = time.monotonic()
    result = MemifyResult(kb_id=kb_id, trigger=trigger)

    if not await is_neo4j_available():
        logger.warning("Memify skipped — Neo4j not available")
        return result

    driver = await get_neo4j_driver()

    async with driver.session(database=_NEO4J_DATABASE) as session:
        # Boost edges between entities that are both frequently accessed
        strengthen_result = await session.run(
            cypher(
                """
            MATCH (a:Entity {kb_id: $kb_id})-[r]->(b:Entity {kb_id: $kb_id})
            WHERE a.access_count > 3 AND b.access_count > 3
              AND r.weight < 5.0
            SET r.weight = r.weight + 0.1
            RETURN count(r) AS strengthened
            """,
                timeout=WRITE_TIMEOUT_S,
            ),
            kb_id=kb_id,
        )
        record = await strengthen_result.single()
        result.edges_strengthened = record["strengthened"] if record else 0

    async with driver.session(database=_NEO4J_DATABASE) as session:
        weaken_result = await session.run(
            cypher(
                """
            MATCH (a:Entity {kb_id: $kb_id})-[r]->(b:Entity {kb_id: $kb_id})
            WHERE r.weight > 0.2
              AND (a.access_count IS NULL OR a.access_count = 0)
              AND (b.access_count IS NULL OR b.access_count = 0)
              AND r.updated_at < datetime() - duration({days: $days})
            SET r.weight = r.weight * 0.9
            RETURN count(r) AS weakened
            """,
                timeout=WRITE_TIMEOUT_S,
            ),
            kb_id=kb_id,
            days=prune_threshold_days,
        )
        record = await weaken_result.single()
        result.edges_weakened = record["weakened"] if record else 0

    async with driver.session(database=_NEO4J_DATABASE) as session:
        prune_result = await session.run(
            cypher(
                """
            MATCH (e:Entity {kb_id: $kb_id})
            WHERE e.confidence < $min_conf
              AND (e.access_count IS NULL OR e.access_count = 0)
              AND e.mention_count <= 1
              AND e.updated_at < datetime() - duration({days: $days})
            DETACH DELETE e
            RETURN count(e) AS pruned
            """,
                timeout=WRITE_TIMEOUT_S,
            ),
            kb_id=kb_id,
            min_conf=min_confidence,
            days=prune_threshold_days,
        )
        record = await prune_result.single()
        result.nodes_pruned = record["pruned"] if record else 0

    if feedback_data:
        async with driver.session(database=_NEO4J_DATABASE) as session:
            for fb in feedback_data:
                rating = fb.get("rating", 0)
                entity_ids = fb.get("entity_ids", [])
                if not entity_ids:
                    continue

                weight_delta = 0.2 if rating > 0 else -0.15 if rating < 0 else 0
                if weight_delta == 0:
                    continue

                # Adjust edges connected to the feedback entities
                await session.run(
                    cypher(
                        """
                    MATCH (e:Entity {kb_id: $kb_id})
                    WHERE e.pg_id IN $entity_ids
                    SET e.access_count = COALESCE(e.access_count, 0) + 1,
                        e.confidence = CASE
                            WHEN $delta > 0 THEN LEAST(e.confidence + $delta, 1.0)
                            ELSE GREATEST(e.confidence + $delta, 0.1)
                        END
                    WITH e
                    MATCH (e)-[r]-(:Entity {kb_id: $kb_id})
                    SET r.weight = CASE
                        WHEN $delta > 0 THEN LEAST(r.weight + $delta, 5.0)
                        ELSE GREATEST(r.weight + $delta, 0.1)
                    END
                    """,
                        timeout=WRITE_TIMEOUT_S,
                    ),
                    kb_id=kb_id,
                    entity_ids=entity_ids,
                    delta=weight_delta,
                )

    # If two entities frequently appear in the same search results
    # but aren't directly connected, create a weak RELATED_TO edge
    async with driver.session(database=_NEO4J_DATABASE) as session:
        derive_result = await session.run(
            cypher(
                """
            MATCH (a:Entity {kb_id: $kb_id})
            WHERE a.access_count > 5
            WITH a LIMIT $candidates
            WITH collect(a) AS busy
            UNWIND busy AS a
            UNWIND busy AS b
            WITH a, b
            WHERE elementId(a) < elementId(b)
              AND b.kb_id = $kb_id
              AND NOT (a)--(b)
              AND any(doc IN a.source_doc_ids WHERE doc IN b.source_doc_ids)
            MERGE (a)-[r:CO_OCCURS]->(b)
            ON CREATE SET r.weight = 0.3, r.kb_id = $kb_id, r.derived = true,
                         r.updated_at = datetime()
            RETURN count(r) AS derived
            """,
                timeout=WRITE_TIMEOUT_S,
            ),
            kb_id=kb_id,
        )
        record = await derive_result.single()
        result.facts_derived = record["derived"] if record else 0

    result.duration_seconds = time.monotonic() - start
    logger.info(
        "Memify [%s] Complete: +%d strengthened, -%d weakened, -%d pruned, +%d derived (%.1fs)",
        kb_id[:8],
        result.edges_strengthened,
        result.edges_weakened,
        result.nodes_pruned,
        result.facts_derived,
        result.duration_seconds,
    )
    return result
