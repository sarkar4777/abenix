"""Write resolved entities and relationships to Neo4j knowledge graph.

Handles MERGE semantics (create-or-update) to support incremental cognify runs.
"""

from __future__ import annotations

import logging

from engine.knowledge.entity_resolver import ResolvedEntity, ResolvedRelationship
from engine.knowledge.neo4j_client import get_neo4j_driver

logger = logging.getLogger(__name__)

# Neo4j property size limits
MAX_DESCRIPTION_LENGTH = 2000
MAX_ALIASES = 20


async def write_entities(
    kb_id: str,
    entities: list[ResolvedEntity],
    pg_id_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """Write entities to Neo4j. Returns mapping: canonical_name → neo4j_element_id.

    Uses MERGE to create-or-update — safe for incremental cognify runs.
    """
    driver = await get_neo4j_driver()
    name_to_neo4j_id: dict[str, str] = {}
    pg_id_map = pg_id_map or {}

    async with driver.session() as session:
        # Batch entities for efficiency
        batch_size = 50
        for i in range(0, len(entities), batch_size):
            batch = entities[i : i + batch_size]
            params_list = []
            for e in batch:
                params_list.append(
                    {
                        "kb_id": kb_id,
                        "canonical_name": e.canonical_name,
                        "entity_type": e.entity_type,
                        "description": (e.description or "")[:MAX_DESCRIPTION_LENGTH],
                        "aliases": (e.aliases or [])[:MAX_ALIASES],
                        "mention_count": e.mention_count,
                        "confidence": float(e.confidence),
                        "pg_id": pg_id_map.get(e.canonical_name, ""),
                        "source_doc_ids": e.source_doc_ids or [],
                    }
                )

            result = await session.run(
                """
                UNWIND $batch AS props
                MERGE (e:Entity {kb_id: props.kb_id, canonical_name: props.canonical_name})
                SET e.entity_type = props.entity_type,
                    e.description = props.description,
                    e.aliases = props.aliases,
                    e.mention_count = COALESCE(e.mention_count, 0) + props.mention_count,
                    e.confidence = props.confidence,
                    e.pg_id = props.pg_id,
                    e.source_doc_ids = props.source_doc_ids,
                    e.updated_at = datetime()
                RETURN e.canonical_name AS name, elementId(e) AS eid
                """,
                batch=params_list,
            )

            async for record in result:
                name_to_neo4j_id[record["name"]] = record["eid"]

    logger.info("Wrote %d entities to Neo4j for kb %s", len(entities), kb_id)
    return name_to_neo4j_id


async def write_relationships(
    kb_id: str,
    relationships: list[ResolvedRelationship],
    pg_id_map: dict[str, str] | None = None,
) -> int:
    """Write relationships to Neo4j. Returns count of relationships written.

    Uses dynamic relationship types via APOC or per-type batching.
    """
    driver = await get_neo4j_driver()
    pg_id_map = pg_id_map or {}
    written = 0

    # Group relationships by type for efficient Cypher execution
    by_type: dict[str, list[ResolvedRelationship]] = {}
    for r in relationships:
        if r.relationship_type not in by_type:
            by_type[r.relationship_type] = []
        by_type[r.relationship_type].append(r)

    async with driver.session() as session:
        for rel_type, rels in by_type.items():
            # Sanitize relationship type for Cypher (must be valid identifier)
            safe_type = rel_type.upper().replace(" ", "_").replace("-", "_")
            if not safe_type.isidentifier():
                safe_type = "RELATED_TO"

            batch = []
            for r in rels:
                batch.append(
                    {
                        "kb_id": kb_id,
                        "source": r.source,
                        "target": r.target,
                        "description": (r.description or "")[:MAX_DESCRIPTION_LENGTH],
                        "weight": float(r.weight),
                        "source_doc_ids": r.source_doc_ids or [],
                        "pg_id": pg_id_map.get(
                            f"{r.source}|{safe_type}|{r.target}", ""
                        ),
                    }
                )

            # Use APOC for dynamic relationship types
            try:
                result = await session.run(
                    f"""
                    UNWIND $batch AS props
                    MATCH (a:Entity {{kb_id: props.kb_id, canonical_name: props.source}})
                    MATCH (b:Entity {{kb_id: props.kb_id, canonical_name: props.target}})
                    MERGE (a)-[r:{safe_type}]->(b)
                    SET r.kb_id = props.kb_id,
                        r.description = props.description,
                        r.weight = CASE WHEN r.weight IS NOT NULL THEN r.weight + props.weight ELSE props.weight END,
                        r.source_doc_ids = props.source_doc_ids,
                        r.pg_id = props.pg_id,
                        r.updated_at = datetime()
                    RETURN count(r) AS cnt
                    """,
                    batch=batch,
                )
                record = await result.single()
                if record:
                    written += record["cnt"]
            except Exception as e:
                logger.error(
                    "Failed to write %d %s relationships: %s", len(rels), safe_type, e
                )

    logger.info(
        "Wrote %d relationships (%d types) to Neo4j for kb %s",
        written,
        len(by_type),
        kb_id,
    )
    return written


async def delete_kb_graph(kb_id: str) -> dict[str, int]:
    """Delete all entities and relationships for a knowledge base from Neo4j."""
    driver = await get_neo4j_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e:Entity {kb_id: $kb_id})
            DETACH DELETE e
            RETURN count(e) AS deleted
            """,
            kb_id=kb_id,
        )
        record = await result.single()
        deleted = record["deleted"] if record else 0
        logger.info(
            "Deleted %d entities (and their relationships) from Neo4j for kb %s",
            deleted,
            kb_id,
        )
        return {"entities_deleted": deleted}
