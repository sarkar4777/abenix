"""Write resolved entities and relationships to the Neo4j knowledge graph in bounded batches."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from neo4j import unit_of_work
from neo4j.exceptions import (
    ServiceUnavailable,
    SessionExpired,
    TransientError,
)

from engine.knowledge.entity_blocking import name_key
from engine.knowledge.entity_resolver import ResolvedEntity, ResolvedRelationship
from engine.knowledge.neo4j_client import (
    FULLTEXT_INDEX,
    WRITE_TIMEOUT_S,
    _NEO4J_DATABASE,
    cypher,
    entity_scope,
    fulltext_query,
    get_neo4j_driver,
    kb_token,
)

logger = logging.getLogger(__name__)

MAX_DESCRIPTION_LENGTH = 2000
MAX_ALIASES = 20
# an entity named in more documents than this keeps the first ones, which can only hide it
MAX_SOURCE_DOC_IDS = 5000
ENTITY_BATCH_SIZE = int(os.environ.get("COGNIFY_ENTITY_BATCH", "200"))
RELATIONSHIP_BATCH_SIZE = int(os.environ.get("COGNIFY_RELATIONSHIP_BATCH", "500"))
WRITE_ATTEMPTS = 4
MAX_ERRORS_KEPT = 10

TRANSIENT_ERRORS = (ServiceUnavailable, SessionExpired, TransientError, OSError)


class GraphUnavailable(RuntimeError):
    """Neo4j kept failing after retries, nothing in the batch can be called written."""


@dataclass
class WriteStats:
    written: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    ids: dict[str, str] = field(default_factory=dict)

    def note(self, message: str) -> None:
        if len(self.errors) < MAX_ERRORS_KEPT:
            self.errors.append(message[:300])


_UNION_DOCS = """reduce(acc = coalesce({target}, []), d IN props.source_doc_ids |
                        CASE WHEN d IN acc THEN acc ELSE acc + d END)[0..$max_docs]"""

ENTITY_CYPHER = f"""
UNWIND $batch AS props
MERGE (e:Entity {{kb_id: props.kb_id, canonical_name: props.canonical_name}})
ON CREATE SET e.created_at = datetime()
SET e.tenant_id = coalesce(e.tenant_id, CASE WHEN props.tenant_id = '' THEN null ELSE props.tenant_id END),
    e.kb_token = props.kb_token,
    e.name_key = props.name_key,
    e.entity_type = props.entity_type,
    e.atlas_concept_id = coalesce(props.atlas_concept_id, e.atlas_concept_id),
    e.atlas_graph_id = coalesce(props.atlas_graph_id, e.atlas_graph_id),
    e.description = CASE
        WHEN size(props.description) >= size(coalesce(e.description, ''))
        THEN props.description ELSE e.description END,
    e.aliases = reduce(acc = coalesce(e.aliases, []), a IN props.aliases |
                        CASE WHEN a IN acc THEN acc ELSE acc + a END)[0..$max_aliases],
    e.mention_count = CASE
        WHEN props.batch_id <> '' AND e.last_batch_id = props.batch_id
        THEN e.mention_count
        ELSE coalesce(e.mention_count, 0) + props.mention_count END,
    e.last_batch_id = props.batch_id,
    e.confidence = CASE
        WHEN e.confidence IS NULL OR props.confidence > e.confidence
        THEN props.confidence ELSE e.confidence END,
    e.pg_id = CASE WHEN props.pg_id <> '' THEN props.pg_id ELSE e.pg_id END,
    e.source_doc_ids = {_UNION_DOCS.format(target="e.source_doc_ids")},
    e.updated_at = datetime()
RETURN e.canonical_name AS name, elementId(e) AS eid
"""


def relationship_cypher(safe_type: str) -> str:
    return f"""
UNWIND $batch AS props
MATCH (a:Entity {{kb_id: props.kb_id, canonical_name: props.source}})
MATCH (b:Entity {{kb_id: props.kb_id, canonical_name: props.target}})
MERGE (a)-[r:{safe_type}]->(b)
SET r.kb_id = props.kb_id,
    r.description = props.description,
    r.weight = CASE
        WHEN props.batch_id <> '' AND r.last_batch_id = props.batch_id THEN r.weight
        WHEN r.weight IS NOT NULL THEN r.weight + props.weight
        ELSE props.weight END,
    r.last_batch_id = props.batch_id,
    r.atlas_edge_id = coalesce(props.atlas_edge_id, r.atlas_edge_id),
    r.source_doc_ids = {_UNION_DOCS.format(target="r.source_doc_ids")},
    r.pg_id = props.pg_id,
    r.updated_at = datetime()
RETURN count(r) AS cnt
"""


def safe_relationship_type(rel_type: str) -> str:
    safe = (rel_type or "").upper().replace(" ", "_").replace("-", "_")
    return safe if safe.isidentifier() and safe.isascii() else "RELATED_TO"


def _chunks(rows: list, size: int) -> list[list]:
    return [rows[i : i + size] for i in range(0, len(rows), max(size, 1))]


async def _write(driver, statement: str, batch: list[dict], **params):
    """One managed transaction with retries on what Neo4j calls transient."""

    @unit_of_work(timeout=WRITE_TIMEOUT_S)
    async def work(tx):
        result = await tx.run(statement, batch=batch, **params)
        return [dict(r) async for r in result]

    delay = 0.5
    for attempt in range(WRITE_ATTEMPTS):
        try:
            async with driver.session(database=_NEO4J_DATABASE) as session:
                return await session.execute_write(work)
        except TRANSIENT_ERRORS as e:
            if attempt == WRITE_ATTEMPTS - 1:
                raise GraphUnavailable(str(e)) from e
            logger.warning("Neo4j write retry %d after %s", attempt + 1, e)
            await asyncio.sleep(delay)
            delay *= 2
    raise GraphUnavailable("Neo4j write gave up")


async def _write_isolating(driver, statement, batch, stats, on_rows, **params):
    """A row Neo4j rejects fails alone, the rest of the batch still lands."""
    try:
        on_rows(await _write(driver, statement, batch, **params), batch)
    except GraphUnavailable:
        raise
    except Exception as e:
        if len(batch) == 1:
            stats.failed += 1
            stats.note(
                f"{batch[0].get('canonical_name') or batch[0].get('source')} {e}"
            )
            logger.error("Graph write rejected one row %s", e)
            return
        mid = len(batch) // 2
        for part in (batch[:mid], batch[mid:]):
            await _write_isolating(driver, statement, part, stats, on_rows, **params)


async def write_entities(
    kb_id: str,
    entities: list[ResolvedEntity],
    pg_id_map: dict[str, str] | None = None,
    tenant_id: str = "",
    batch_id: str = "",
    batch_size: int = ENTITY_BATCH_SIZE,
) -> WriteStats:
    """MERGE entities. Reruns merge aliases and documents and do not lose either."""
    driver = await get_neo4j_driver()
    stats = WriteStats()
    pg_id_map = pg_id_map or {}
    rows = [
        {
            "kb_id": kb_id,
            "kb_token": kb_token(kb_id),
            "tenant_id": tenant_id,
            "batch_id": batch_id,
            "canonical_name": e.canonical_name,
            "name_key": name_key(e.canonical_name),
            "entity_type": e.entity_type,
            "description": (e.description or "")[:MAX_DESCRIPTION_LENGTH],
            "aliases": (e.aliases or [])[:MAX_ALIASES],
            "mention_count": e.mention_count,
            "confidence": float(e.confidence),
            "pg_id": pg_id_map.get(e.canonical_name, ""),
            "source_doc_ids": e.source_doc_ids or [],
            "atlas_concept_id": (e.properties or {}).get("atlas_concept_id"),
            "atlas_graph_id": (e.properties or {}).get("atlas_graph_id"),
        }
        for e in sorted(entities, key=lambda x: x.canonical_name)
    ]

    def landed(result_rows: list[dict], _batch: list[dict]) -> None:
        stats.written += len(result_rows)
        for r in result_rows:
            stats.ids[r["name"]] = r["eid"]

    for batch in _chunks(rows, batch_size):
        await _write_isolating(
            driver,
            ENTITY_CYPHER,
            batch,
            stats,
            landed,
            max_aliases=MAX_ALIASES,
            max_docs=MAX_SOURCE_DOC_IDS,
        )
    logger.info(
        "Wrote %d entities to Neo4j for kb %s, %d failed",
        stats.written,
        kb_id,
        stats.failed,
    )
    return stats


async def write_relationships(
    kb_id: str,
    relationships: list[ResolvedRelationship],
    pg_id_map: dict[str, str] | None = None,
    batch_id: str = "",
    batch_size: int = RELATIONSHIP_BATCH_SIZE,
) -> WriteStats:
    """MERGE relationships per type, in batches, counting every row that did not land."""
    driver = await get_neo4j_driver()
    pg_id_map = pg_id_map or {}
    stats = WriteStats()

    by_type: dict[str, list[ResolvedRelationship]] = {}
    for r in relationships:
        by_type.setdefault(safe_relationship_type(r.relationship_type), []).append(r)

    def landed(result_rows: list[dict], batch: list[dict]) -> None:
        count = result_rows[0]["cnt"] if result_rows else 0
        stats.written += count
        missing = len(batch) - count
        if missing > 0:
            stats.failed += missing
            stats.note(
                f"{missing} relationships had an endpoint missing from the graph"
            )

    for safe_type, rels in by_type.items():
        rows = [
            {
                "kb_id": kb_id,
                "batch_id": batch_id,
                "source": r.source,
                "target": r.target,
                "description": (r.description or "")[:MAX_DESCRIPTION_LENGTH],
                "weight": float(r.weight),
                "source_doc_ids": r.source_doc_ids or [],
                "atlas_edge_id": r.atlas_edge_id,
                "pg_id": pg_id_map.get(f"{r.source}|{safe_type}|{r.target}", ""),
            }
            for r in sorted(rels, key=lambda x: (x.source, x.target))
        ]
        statement = relationship_cypher(safe_type)
        for batch in _chunks(rows, batch_size):
            await _write_isolating(
                driver,
                statement,
                batch,
                stats,
                landed,
                max_docs=MAX_SOURCE_DOC_IDS,
            )

    logger.info(
        "Wrote %d relationships (%d types) to Neo4j for kb %s, %d failed",
        stats.written,
        len(by_type),
        kb_id,
        stats.failed,
    )
    return stats


async def stamp_pg_ids(kb_id: str, pg_ids: dict[str, str]) -> None:
    """Point graph nodes back at their Postgres rows, memify feedback looks them up by this."""
    if not pg_ids:
        return
    driver = await get_neo4j_driver()
    rows = [{"name": k, "pg_id": v} for k, v in pg_ids.items()]
    for batch in _chunks(rows, ENTITY_BATCH_SIZE):
        await _write(
            driver,
            """
            UNWIND $batch AS props
            MATCH (e:Entity {kb_id: $kb_id, canonical_name: props.name})
            SET e.pg_id = props.pg_id
            """,
            batch,
            kb_id=kb_id,
        )


async def fetch_existing_entities(
    kb_id: str, names: list[str], tenant_id: str = ""
) -> list[dict]:
    """Stored entities matching these names only, by normalized key then alias."""
    keys = sorted({name_key(n) for n in names if name_key(n)})
    if not keys:
        return []
    driver = await get_neo4j_driver()
    out: dict[str, dict] = {}
    async with driver.session(database=_NEO4J_DATABASE) as session:
        for batch in _chunks(keys, 500):
            result = await session.run(
                cypher(
                    f"""
                    UNWIND $keys AS key
                    MATCH (e:Entity {{kb_id: $kb_id, name_key: key}})
                    WHERE {entity_scope("e")}
                    RETURN e.canonical_name AS canonical_name,
                           e.entity_type AS entity_type, e.aliases AS aliases,
                           e.source_doc_ids AS source_doc_ids, e.confidence AS confidence
                    """
                ),
                kb_id=kb_id,
                tenant_id=tenant_id,
                keys=batch,
            )
            async for r in result:
                out[r["canonical_name"]] = dict(r)
        queries = [
            {"key": k, "q": fulltext_query(kb_id, k, exact_only=True)}
            for k in keys
            if len(k) > 2
        ]
        for batch in _chunks(queries, 200):
            result = await session.run(
                cypher(
                    f"""
                    UNWIND $queries AS item
                    CALL db.index.fulltext.queryNodes($index, item.q, {{limit: 5}})
                    YIELD node AS e
                    WITH item, e WHERE {entity_scope("e")}
                    RETURN item.key AS key, e.canonical_name AS canonical_name,
                           e.entity_type AS entity_type, e.aliases AS aliases,
                           e.source_doc_ids AS source_doc_ids, e.confidence AS confidence
                    """
                ),
                kb_id=kb_id,
                tenant_id=tenant_id,
                index=FULLTEXT_INDEX,
                queries=batch,
            )
            async for r in result:
                # the analyzer matches more loosely than the key, so check it
                if any(name_key(a) == r["key"] for a in r["aliases"] or []):
                    row = dict(r)
                    row.pop("key", None)
                    out[row["canonical_name"]] = row
    return [
        {
            **row,
            "aliases": row.get("aliases") or [],
            "source_doc_ids": row.get("source_doc_ids") or [],
            "confidence": float(
                row["confidence"] if row.get("confidence") is not None else 1.0
            ),
        }
        for row in out.values()
    ]


async def delete_kb_graph(kb_id: str, batch: int = 5000) -> dict[str, int]:
    """Delete a knowledge base's graph in small transactions, safe for very large KBs."""
    driver = await get_neo4j_driver()
    deleted = 0
    while True:
        rows = await _write(
            driver,
            """
            MATCH (e:Entity {kb_id: $kb_id})
            WITH e LIMIT $limit
            DETACH DELETE e
            RETURN count(*) AS deleted
            """,
            [],
            kb_id=kb_id,
            limit=batch,
        )
        n = rows[0]["deleted"] if rows else 0
        deleted += n
        if n < batch:
            break
    logger.info(
        "Deleted %d entities and their relationships from Neo4j for kb %s",
        deleted,
        kb_id,
    )
    return {"entities_deleted": deleted}
