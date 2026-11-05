"""KB wide entity resolution, streamed from Neo4j with memory that does not grow with the KB."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from neo4j import unit_of_work

from engine.knowledge import cognify_store as store
from engine.knowledge.entity_blocking import CandidateGroup, NameBlocker
from engine.knowledge.entity_resolver import ResolvedEntity, _llm_resolve
from engine.knowledge.graph_writer import (
    MAX_ALIASES,
    MAX_SOURCE_DOC_IDS,
    safe_relationship_type,
)
from engine.knowledge.neo4j_client import (
    WRITE_TIMEOUT_S,
    _NEO4J_DATABASE,
    cypher,
    entity_scope,
    get_neo4j_driver,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = int(os.environ.get("COGNIFY_RESOLVE_PAGE", "5000"))
LLM_GROUPS_PER_CALL = 30
MAX_MERGES = int(os.environ.get("COGNIFY_MAX_MERGES_PER_JOB", "5000"))


@dataclass
class KBResolution:
    names_scanned: int = 0
    groups_found: int = 0
    exact_merges: int = 0
    llm_merges: int = 0
    undecided_groups: int = 0
    tokens: int = 0
    cost: float = 0.0
    truncated: bool = False
    errors: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


async def stream_entities(
    kb_id: str, tenant_id: str = "", page_size: int = PAGE_SIZE
) -> AsyncIterator[list[tuple[str, str]]]:
    """Pages of (name, type) in name order, each page its own short query."""
    driver = await get_neo4j_driver()
    after = ""
    async with driver.session(database=_NEO4J_DATABASE) as session:
        while True:
            result = await session.run(
                cypher(
                    f"""
                    MATCH (e:Entity {{kb_id: $kb_id}})
                    WHERE e.canonical_name > $after AND {entity_scope("e")}
                    RETURN e.canonical_name AS name, e.entity_type AS type
                    ORDER BY e.canonical_name
                    LIMIT $limit
                    """,
                    timeout=WRITE_TIMEOUT_S,
                ),
                kb_id=kb_id,
                tenant_id=tenant_id,
                after=after,
                limit=page_size,
            )
            page = [(r["name"], r["type"] or "concept") async for r in result]
            if not page:
                return
            yield page
            after = page[-1][0]
            if len(page) < page_size:
                return


async def merge_pair(kb_id: str, keep: str, duplicate: str) -> bool:
    """Move a duplicate's relationships, aliases and documents onto keep, then delete it."""
    if keep == duplicate:
        return False
    driver = await get_neo4j_driver()

    @unit_of_work(timeout=WRITE_TIMEOUT_S)
    async def work(tx):
        rows = await tx.run(
            """
            MATCH (d:Entity {kb_id: $kb_id, canonical_name: $dup})-[r]-(:Entity {kb_id: $kb_id})
            RETURN DISTINCT type(r) AS t
            """,
            kb_id=kb_id,
            dup=duplicate,
        )
        types = [safe_relationship_type(r["t"]) async for r in rows]
        for t in types:
            for pattern, merge in (
                ("(d)-[r:{t}]->(o)", "(k)-[n:{t}]->(o)"),
                ("(o)-[r:{t}]->(d)", "(o)-[n:{t}]->(k)"),
            ):
                await tx.run(
                    f"""
                    MATCH (d:Entity {{kb_id: $kb_id, canonical_name: $dup}})
                    MATCH (k:Entity {{kb_id: $kb_id, canonical_name: $keep}})
                    MATCH {pattern.format(t=t)}
                    WHERE o.kb_id = $kb_id AND o <> k AND o <> d
                    MERGE {merge.format(t=t)}
                    SET n.kb_id = $kb_id,
                        n.weight = coalesce(n.weight, 0) + coalesce(r.weight, 0),
                        n.description = coalesce(n.description, r.description),
                        n.source_doc_ids = reduce(acc = coalesce(n.source_doc_ids, []),
                            x IN coalesce(r.source_doc_ids, []) |
                            CASE WHEN x IN acc THEN acc ELSE acc + x END)[0..$max_docs],
                        n.updated_at = datetime()
                    DELETE r
                    """,
                    kb_id=kb_id,
                    dup=duplicate,
                    keep=keep,
                    max_docs=MAX_SOURCE_DOC_IDS,
                )
        result = await tx.run(
            """
            MATCH (d:Entity {kb_id: $kb_id, canonical_name: $dup})
            MATCH (k:Entity {kb_id: $kb_id, canonical_name: $keep})
            SET k.mention_count = coalesce(k.mention_count, 0) + coalesce(d.mention_count, 0),
                k.aliases = reduce(acc = coalesce(k.aliases, []),
                    a IN [d.canonical_name] + coalesce(d.aliases, []) |
                    CASE WHEN a IN acc OR a = k.canonical_name THEN acc ELSE acc + a END)[0..$max_aliases],
                k.source_doc_ids = reduce(acc = coalesce(k.source_doc_ids, []),
                    x IN coalesce(d.source_doc_ids, []) |
                    CASE WHEN x IN acc THEN acc ELSE acc + x END)[0..$max_docs],
                k.confidence = CASE WHEN coalesce(d.confidence, 0) > coalesce(k.confidence, 0)
                               THEN d.confidence ELSE k.confidence END,
                k.updated_at = datetime()
            DETACH DELETE d
            RETURN count(*) AS merged
            """,
            kb_id=kb_id,
            dup=duplicate,
            keep=keep,
            max_aliases=MAX_ALIASES,
            max_docs=MAX_SOURCE_DOC_IDS,
        )
        record = await result.single()
        return bool(record and record["merged"])

    async with driver.session(database=_NEO4J_DATABASE) as session:
        return await session.execute_write(work)


def _mirror_merge(db_url: str, kb_id: str, keep: str, duplicate: str) -> None:
    """The same merge in the Postgres mirror, relationships first because of the foreign keys."""
    if not db_url:
        return
    from sqlalchemy import text

    with store.engine_for(db_url).begin() as conn:
        rows = conn.execute(
            text(
                "SELECT canonical_name, id FROM graph_entities "
                "WHERE kb_id = CAST(:kb AS uuid) AND canonical_name IN (:keep, :dup)"
            ),
            {"kb": kb_id, "keep": keep, "dup": duplicate},
        ).fetchall()
        ids = {r[0]: r[1] for r in rows}
        if duplicate not in ids:
            return
        dup_id = ids[duplicate]
        if keep not in ids:
            conn.execute(
                text("UPDATE graph_entities SET canonical_name = :keep WHERE id = :id"),
                {"keep": keep, "id": dup_id},
            )
            return
        keep_id = ids[keep]
        for col, other in (
            ("source_entity_id", "target_entity_id"),
            ("target_entity_id", "source_entity_id"),
        ):
            conn.execute(
                text(
                    f"""
                    DELETE FROM graph_relationships r USING graph_relationships k
                    WHERE r.{col} = :dup AND k.{col} = :keep AND k.kb_id = r.kb_id
                      AND k.{other} = r.{other}
                      AND k.relationship_type = r.relationship_type
                    """
                ),
                {"dup": dup_id, "keep": keep_id},
            )
            conn.execute(
                text(
                    f"UPDATE graph_relationships SET {col} = :keep WHERE {col} = :dup"
                ),
                {"dup": dup_id, "keep": keep_id},
            )
        conn.execute(
            text(
                """
                UPDATE graph_entities k SET
                    mention_count = k.mention_count + d.mention_count,
                    aliases = coalesce(k.aliases, '[]'::jsonb) || jsonb_build_array(d.canonical_name),
                    source_doc_ids = coalesce(k.source_doc_ids, '[]'::jsonb)
                                     || coalesce(d.source_doc_ids, '[]'::jsonb),
                    updated_at = now()
                FROM graph_entities d WHERE k.id = :keep AND d.id = :dup
                """
            ),
            {"keep": keep_id, "dup": dup_id},
        )
        conn.execute(
            text("DELETE FROM graph_entities WHERE id = :dup"), {"dup": dup_id}
        )


async def _apply_merge(
    kb_id: str, db_url: str, keep: str, duplicate: str, out: KBResolution
) -> bool:
    try:
        merged = await merge_pair(kb_id, keep, duplicate)
        if merged:
            await asyncio.to_thread(_mirror_merge, db_url, kb_id, keep, duplicate)
        return merged
    except Exception as e:
        if len(out.errors) < 10:
            out.errors.append(f"could not merge {duplicate} into {keep} {e}"[:300])
        logger.warning("entity merge failed: %s", e)
        return False


async def resolve_kb_entities(
    kb_id: str,
    tenant_id: str,
    db_url: str = "",
    model: str = "",
    budget_left: float | None = None,
    use_llm: bool = True,
    threshold: float = 0.85,
    max_merges: int = MAX_MERGES,
) -> KBResolution:
    """Merge names that normalize the same, ask the model about close ones within budget."""
    out = KBResolution()
    blocker = NameBlocker(threshold=threshold)
    try:
        async for page in stream_entities(kb_id, tenant_id):
            await asyncio.to_thread(blocker.add, page)
            out.names_scanned += len(page)
        groups: list[CandidateGroup] = await asyncio.to_thread(blocker.groups)
    finally:
        out.stats = dict(blocker.stats.__dict__)
        out.truncated = blocker.stats.truncated
        await asyncio.to_thread(blocker.close)
    out.groups_found = len(groups)

    merges = 0
    fuzzy: list[CandidateGroup] = []
    for g in groups:
        if not g.exact:
            fuzzy.append(g)
            continue
        keep = max(g.names, key=lambda n: (len(n), n))
        for dup in g.names:
            if dup != keep and merges < max_merges:
                if await _apply_merge(kb_id, db_url, keep, dup, out):
                    out.exact_merges += 1
                    merges += 1

    if not use_llm or not model:
        out.undecided_groups = len(fuzzy)
        return out
    for start in range(0, len(fuzzy), LLM_GROUPS_PER_CALL):
        if budget_left is not None and out.cost >= budget_left:
            out.undecided_groups = len(fuzzy) - start
            break
        if merges >= max_merges:
            out.undecided_groups = len(fuzzy) - start
            out.truncated = True
            break
        part = fuzzy[start : start + LLM_GROUPS_PER_CALL]
        answer = await _llm_resolve(
            [
                [
                    ResolvedEntity(
                        canonical_name=n, entity_type=g.entity_type, description=""
                    )
                    for n in g.names
                ]
                for g in part
            ],
            model,
        )
        out.tokens += int(answer.get("tokens") or 0)
        out.cost += float(answer.get("cost") or 0.0)
        known = {n for g in part for n in g.names}
        for cluster in answer.get("clusters") or []:
            keep = cluster.get("canonical")
            if keep not in known:
                continue
            for alias in cluster.get("aliases") or []:
                if alias in known and alias != keep and merges < max_merges:
                    if await _apply_merge(kb_id, db_url, keep, alias, out):
                        out.llm_merges += 1
                        merges += 1
    return out


def report_details(out: KBResolution) -> str:
    return json.dumps({k: v for k, v in out.__dict__.items() if k != "errors"})
