"""Cognify Pipeline — Transform documents into a knowledge graph."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from engine.knowledge.entity_extractor import (
    extract_from_document,
    DocumentExtractionResult,
)
from engine.knowledge.entity_resolver import resolve_entities
from engine.knowledge.graph_writer import write_entities, write_relationships
from engine.knowledge.neo4j_client import ensure_schema, is_neo4j_available

logger = logging.getLogger(__name__)


def _flush_progress(db_url: str, job_id: str, result: "CognifyResult") -> None:
    """Write in-flight counts back to cognify_jobs so the UI can show them."""
    if not db_url:
        return
    try:
        from sqlalchemy import create_engine, text as _t

        eng = create_engine(db_url)
        with eng.begin() as conn:
            conn.execute(
                _t(
                    "UPDATE cognify_jobs SET "
                    "documents_processed = :d, entities_extracted = :e, "
                    "relationships_extracted = :r, tokens_used = :t, "
                    "cost_usd = :c, "
                    "anthropic_cost = :ac, openai_cost = :oc, "
                    "google_cost = :gc, other_cost = :xc "
                    "WHERE id = :id"
                ),
                {
                    "d": result.documents_processed,
                    "e": result.entities_extracted,
                    "r": result.relationships_extracted,
                    "t": result.total_tokens,
                    "c": result.total_cost,
                    "ac": result.anthropic_cost,
                    "oc": result.openai_cost,
                    "gc": result.google_cost,
                    "xc": result.other_cost,
                    "id": job_id,
                },
            )
    except Exception as _exc:
        logger.debug("progress flush failed (non-fatal): %s", _exc)


@dataclass
class CognifyResult:
    """Result of a full cognify run."""

    kb_id: str
    job_id: str
    status: str = "complete"
    documents_processed: int = 0
    chunks_analyzed: int = 0
    entities_extracted: int = 0
    entities_after_resolution: int = 0
    entities_merged: int = 0
    relationships_extracted: int = 0
    relationships_written: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    # Per-provider spend breakdown so the KB engine page can show
    # "Anthropic $X + OpenAI $Y" instead of a single flat number.
    anthropic_cost: float = 0.0
    openai_cost: float = 0.0
    google_cost: float = 0.0
    other_cost: float = 0.0
    duration_seconds: float = 0.0
    error: str | None = None
    # Report data
    entities_by_type: dict[str, int] = field(default_factory=dict)
    top_entities: list[dict[str, Any]] = field(default_factory=list)
    relationship_types: dict[str, int] = field(default_factory=dict)
    # cognify_configs at work
    auto_accept_threshold: float = 0.0
    entities_held_back: int = 0
    relationships_held_back: int = 0
    held_back: list[dict[str, Any]] = field(default_factory=list)
    conflicts_recorded: int = 0
    documents_skipped_budget: int = 0


DEFAULT_COGNIFY_CONFIG: dict[str, Any] = {
    "auto_accept_threshold": 0.85,
    "conflict_action": "flag",
    "max_parallel_docs": 8,
    "daily_budget_usd": None,
}


def _load_cognify_config(tenant_id: str, db_url: str) -> dict[str, Any]:
    """The tenant's cognify_configs row over the defaults the settings page shows."""
    cfg = dict(DEFAULT_COGNIFY_CONFIG)
    if not db_url or not tenant_id:
        return cfg
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT auto_accept_threshold, conflict_action, max_parallel_docs, "
                    "daily_budget_usd FROM cognify_configs WHERE tenant_id = CAST(:t AS uuid)"
                ),
                {"t": tenant_id},
            ).fetchone()
            if row is not None:
                cfg.update(
                    auto_accept_threshold=float(row[0]),
                    conflict_action=row[1] or "flag",
                    max_parallel_docs=int(row[2] or 8),
                    daily_budget_usd=float(row[3]) if row[3] is not None else None,
                )
            spent = conn.execute(
                text(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM cognify_jobs "
                    "WHERE tenant_id = CAST(:t AS uuid) AND created_at >= date_trunc('day', now())"
                ),
                {"t": tenant_id},
            ).scalar()
            cfg["spent_today_usd"] = float(spent or 0)
    except Exception as e:
        logger.warning("cognify config load failed, using defaults: %s", e)
    return cfg


def _hold_back(
    entities: list, relationships: list, threshold: float
) -> tuple[list, list, list[dict[str, Any]]]:
    """Drop proposals under the auto-accept threshold, and relationships left dangling."""
    if threshold <= 0:
        return entities, relationships, []
    kept = [e for e in entities if float(e.confidence) >= threshold]
    names = {e.canonical_name for e in kept}
    held = [
        {"kind": "entity", "name": e.canonical_name, "confidence": float(e.confidence)}
        for e in entities
        if float(e.confidence) < threshold
    ]
    kept_rels = []
    for r in relationships:
        if float(r.confidence) < threshold:
            held.append(
                {
                    "kind": "relationship",
                    "name": f"{r.source} {r.relationship_type} {r.target}",
                    "confidence": float(r.confidence),
                }
            )
        elif r.source in names and r.target in names:
            kept_rels.append(r)
    return kept, kept_rels, held


def _provider_key(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("chatgpt"):
        return "openai"
    if m.startswith("gemini"):
        return "google"
    return "other"


async def run_cognify(
    kb_id: str,
    tenant_id: str,
    job_id: str,
    documents: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    db_url: str = "",
) -> CognifyResult:
    """Execute the full cognify pipeline."""
    start = time.monotonic()
    cfg = config or {}
    model = cfg.get("model", "claude-sonnet-4-5-20250929")
    result = CognifyResult(kb_id=kb_id, job_id=job_id)
    tenant_cfg = _load_cognify_config(tenant_id, db_url)
    result.auto_accept_threshold = float(tenant_cfg["auto_accept_threshold"])
    budget = tenant_cfg.get("daily_budget_usd")
    spent_before = float(tenant_cfg.get("spent_today_usd") or 0)
    if budget is not None and spent_before >= budget:
        result.status = "failed"
        result.error = (
            f"Daily Cognify budget of ${budget:.2f} is used up "
            f"(${spent_before:.2f} spent today). Raise it in Settings > Cognify "
            "or wait until tomorrow (UTC)."
        )
        result.duration_seconds = time.monotonic() - start
        return result

    if cfg.get("incremental", True) and not cfg.get("force", False):
        if await _no_new_documents_since_last_cognify(kb_id, db_url, documents):
            logger.info(
                "Cognify [%s] skipped — no new documents since last_cognified_at",
                job_id[:8],
            )
            result.status = "skipped"
            result.duration_seconds = time.monotonic() - start
            return result

    # KB v2 phase 3: load the project's active ontology schema (if any)
    # and pass it through as a typing prior to the LLM extractor. The
    # schema is project-scoped, so we resolve the project from kb_id.
    ontology = await _load_active_ontology(kb_id, db_url)
    if ontology:
        logger.info(
            "Cognify [%s] using ontology schema with %d entity types, %d rel types",
            job_id[:8],
            len((ontology or {}).get("entity_types") or []),
            len((ontology or {}).get("relationship_types") or []),
        )

    # Ensure Neo4j schema
    if not await is_neo4j_available():
        result.status = "failed"
        result.error = "Neo4j is not available. Start the Neo4j container."
        return result

    await ensure_schema()

    logger.info(
        "Cognify [%s] Phase 1: Extracting entities from %d documents",
        job_id[:8],
        len(documents),
    )
    all_extraction_results: list[DocumentExtractionResult] = []
    gate = asyncio.Semaphore(max(1, int(tenant_cfg["max_parallel_docs"])))
    over_budget = asyncio.Event()

    async def _extract(doc: dict[str, Any]) -> DocumentExtractionResult | None:
        async with gate:
            if over_budget.is_set():
                result.documents_skipped_budget += 1
                return None
            return await extract_from_document(
                chunks=doc["chunks"],
                doc_id=doc["id"],
                filename=doc.get("filename", "unknown"),
                model=model,
                ontology=ontology,
            )

    todo = []
    for doc in documents:
        if not doc.get("chunks"):
            logger.warning("Document %s has no chunks, skipping", doc["id"])
            continue
        todo.append(asyncio.ensure_future(_extract(doc)))

    for fut in asyncio.as_completed(todo):
        doc_result = await fut
        if doc_result is None:
            continue
        all_extraction_results.append(doc_result)
        result.documents_processed += 1
        result.chunks_analyzed += doc_result.chunks_processed
        result.total_tokens += doc_result.total_tokens
        result.total_cost += doc_result.total_cost
        # Provider split — every call in Phase 1 uses the same `model`
        # unless the router fell back, which is invisible at this level.
        # Bucket conservatively by the requested model; the router has
        # already emitted exact Prometheus spend per call.
        _prov = _provider_key(model)
        if _prov == "anthropic":
            result.anthropic_cost += doc_result.total_cost
        elif _prov == "openai":
            result.openai_cost += doc_result.total_cost
        elif _prov == "google":
            result.google_cost += doc_result.total_cost
        else:
            result.other_cost += doc_result.total_cost
        # Running counts so the UI banner can show something ticking.
        result.entities_extracted = sum(len(r.entities) for r in all_extraction_results)
        result.relationships_extracted = sum(
            len(r.relationships) for r in all_extraction_results
        )
        _flush_progress(db_url, job_id, result)
        if budget is not None and spent_before + result.total_cost >= budget:
            over_budget.set()

    if result.documents_skipped_budget:
        result.error = (
            f"Stopped at the daily budget of ${budget:.2f}: "
            f"{result.documents_skipped_budget} document(s) were not processed"
        )

    # Aggregate raw entities and relationships
    all_raw_entities = []
    all_raw_relationships = []
    for dr in all_extraction_results:
        all_raw_entities.extend(dr.entities)
        all_raw_relationships.extend(dr.relationships)

    result.entities_extracted = len(all_raw_entities)
    result.relationships_extracted = len(all_raw_relationships)

    if not all_raw_entities:
        logger.warning(
            "Cognify [%s] No entities extracted from %d documents",
            job_id[:8],
            len(documents),
        )
        result.duration_seconds = time.monotonic() - start
        return result

    logger.info(
        "Cognify [%s] Phase 2: Resolving %d entities, %d relationships",
        job_id[:8],
        len(all_raw_entities),
        len(all_raw_relationships),
    )

    # Fetch existing entities from the KB for cross-document dedup
    existing_entities = await _fetch_existing_entities(kb_id, db_url)

    resolution = await resolve_entities(
        raw_entities=all_raw_entities,
        raw_relationships=all_raw_relationships,
        existing_entities=existing_entities,
        model=model,
        conflict_action=tenant_cfg["conflict_action"],
    )
    resolution.entities, resolution.relationships, held = _hold_back(
        resolution.entities,
        resolution.relationships,
        result.auto_accept_threshold,
    )
    result.entities_held_back = sum(1 for h in held if h["kind"] == "entity")
    result.relationships_held_back = len(held) - result.entities_held_back
    result.held_back = sorted(held, key=lambda h: -h["confidence"])[:50]

    result.entities_after_resolution = len(resolution.entities)
    result.entities_merged = resolution.merges_performed
    result.total_tokens += resolution.tokens_used
    result.total_cost += resolution.cost

    logger.info(
        "Cognify [%s] Phase 3: Writing %d entities, %d relationships to Neo4j",
        job_id[:8],
        len(resolution.entities),
        len(resolution.relationships),
    )

    # Write entities to Neo4j
    neo4j_id_map = await write_entities(kb_id, resolution.entities)

    # Write relationships to Neo4j
    rels_written = await write_relationships(kb_id, resolution.relationships)
    result.relationships_written = rels_written

    logger.info("Cognify [%s] Phase 4: Updating PostgreSQL metadata", job_id[:8])

    if db_url and resolution.conflicts:
        result.conflicts_recorded = _record_conflicts(
            tenant_id, kb_id, resolution.conflicts, db_url
        )

    if db_url:
        await _update_pg_metadata(
            kb_id=kb_id,
            tenant_id=tenant_id,
            job_id=job_id,
            entities=resolution.entities,
            relationships=resolution.relationships,
            neo4j_id_map=neo4j_id_map,
            db_url=db_url,
        )

    # Entities by type
    for e in resolution.entities:
        t = e.entity_type
        result.entities_by_type[t] = result.entities_by_type.get(t, 0) + 1

    # Top entities by mention count
    sorted_entities = sorted(
        resolution.entities, key=lambda e: e.mention_count, reverse=True
    )
    result.top_entities = [
        {
            "name": e.canonical_name,
            "type": e.entity_type,
            "mentions": e.mention_count,
            "description": e.description,
        }
        for e in sorted_entities[:20]
    ]

    # Relationship types
    for r in resolution.relationships:
        t = r.relationship_type
        result.relationship_types[t] = result.relationship_types.get(t, 0) + 1

    result.duration_seconds = time.monotonic() - start
    logger.info(
        "Cognify [%s] Complete: %d entities, %d relationships, %.1fs, $%.4f",
        job_id[:8],
        result.entities_after_resolution,
        result.relationships_written,
        result.duration_seconds,
        result.total_cost,
    )

    return result


async def _no_new_documents_since_last_cognify(
    kb_id: str,
    db_url: str,
    documents: list[dict[str, Any]],
) -> bool:
    """True iff every passed document was created at-or-before the"""
    if not db_url or not documents:
        return False
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT last_cognified_at FROM knowledge_collections "
                    "WHERE id = CAST(:kb_id AS uuid)"
                ),
                {"kb_id": kb_id},
            ).fetchone()
            if row is None or row[0] is None:
                return False
            last = row[0]
            doc_ids = [d["id"] for d in documents if d.get("id")]
            if not doc_ids:
                return False
            cnt = (
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM documents "
                        "WHERE id = ANY(:ids) AND created_at > :last"
                    ),
                    {"ids": doc_ids, "last": last},
                ).scalar()
                or 0
            )
            return cnt == 0
    except Exception:
        return False


async def _load_active_ontology(kb_id: str, db_url: str) -> dict | None:
    """Load the active ontology schema for the KB's project."""
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                SELECT s.entity_types, s.relationship_types
                FROM knowledge_collections kb
                JOIN knowledge_projects p ON p.id = kb.project_id
                JOIN ontology_schemas s ON s.id = p.ontology_schema_id
                WHERE kb.id = CAST(:kb_id AS uuid)
                LIMIT 1
                """
                ),
                {"kb_id": kb_id},
            ).fetchone()
            if row is None:
                return None
            return {
                "entity_types": row[0] or [],
                "relationship_types": row[1] or [],
            }
    except Exception as e:
        logger.warning("Failed to load active ontology for kb %s: %s", kb_id, e)
        return None


async def _fetch_existing_entities(kb_id: str, db_url: str) -> list[dict[str, Any]]:
    """Fetch existing entities from PostgreSQL for cross-document dedup."""
    if not db_url:
        return []

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT canonical_name, entity_type, aliases, source_doc_ids, confidence "
                    "FROM graph_entities WHERE kb_id = :kb_id"
                ),
                {"kb_id": kb_id},
            ).fetchall()
            return [
                {
                    "canonical_name": r[0],
                    "entity_type": r[1],
                    "aliases": r[2] or [],
                    "source_doc_ids": r[3] if isinstance(r[3], list) else [],
                    "confidence": float(r[4]) if r[4] is not None else 1.0,
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("Could not fetch existing entities: %s", e)
        return []


def _record_conflicts(tenant_id: str, kb_id: str, conflicts: list, db_url: str) -> int:
    """One cognify_conflicts row per disagreement, skipping ones already on file."""
    import uuid as uuid_mod

    from sqlalchemy import create_engine, text

    def _doc(v: str) -> str | None:
        try:
            return str(uuid_mod.UUID(str(v)))
        except (TypeError, ValueError):
            return None

    written = 0
    try:
        engine = create_engine(db_url)
        with engine.begin() as conn:
            for c in conflicts:
                a_doc, b_doc = _doc(c.a_doc_id), _doc(c.b_doc_id)
                if not a_doc or not b_doc:
                    continue
                r = conn.execute(
                    text(
                        """
                        INSERT INTO cognify_conflicts (id, tenant_id, knowledge_base_id,
                            entity_canonical_name, property_name, source_a_doc_id,
                            source_a_value, source_a_confidence, source_b_doc_id,
                            source_b_value, source_b_confidence, status, resolved_value,
                            resolved_at)
                        SELECT CAST(:id AS uuid), CAST(:t AS uuid), CAST(:kb AS uuid), :entity,
                            :prop, CAST(:a_doc AS uuid), :a_val, :a_conf, CAST(:b_doc AS uuid),
                            :b_val, :b_conf, :status, :resolved,
                            CASE WHEN :status = 'open' THEN NULL ELSE now() END
                        WHERE NOT EXISTS (
                            SELECT 1 FROM cognify_conflicts
                            WHERE knowledge_base_id = CAST(:kb AS uuid)
                              AND entity_canonical_name = :entity
                              AND property_name = :prop
                              AND source_a_value = :a_val AND source_b_value = :b_val
                              AND status IN ('open', :status))
                        """
                    ),
                    {
                        "id": str(uuid_mod.uuid4()),
                        "t": tenant_id,
                        "kb": kb_id,
                        "entity": c.entity[:512],
                        "prop": c.property,
                        "a_doc": a_doc,
                        "a_val": c.a_value,
                        "a_conf": float(c.a_confidence),
                        "b_doc": b_doc,
                        "b_val": c.b_value,
                        "b_conf": float(c.b_confidence),
                        "status": c.status,
                        "resolved": c.resolved_value,
                    },
                )
                written += r.rowcount or 0
    except Exception as e:
        logger.warning("Could not record cognify conflicts for kb %s: %s", kb_id, e)
    return written


async def _update_pg_metadata(
    kb_id: str,
    tenant_id: str,
    job_id: str,
    entities: list,
    relationships: list,
    neo4j_id_map: dict[str, str],
    db_url: str,
) -> None:
    """Write entity_registry and relationship_registry rows to PostgreSQL.

    This keeps PG as the source of truth for metadata while Neo4j stores the graph.
    """
    try:
        import json
        import uuid as uuid_mod
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)

        with engine.begin() as conn:
            # Upsert entities
            for e in entities:
                neo4j_id = neo4j_id_map.get(e.canonical_name, "")
                conn.execute(
                    text(
                        """
                        INSERT INTO graph_entities (id, tenant_id, kb_id, canonical_name, entity_type,
                            description, aliases, source_doc_ids, neo4j_node_id, mention_count,
                            access_count, confidence)
                        VALUES (:id, :tenant_id, CAST(:kb_id AS uuid), :name, :type, :desc, CAST(:aliases AS jsonb),
                            CAST(:doc_ids AS jsonb), :neo4j_id, :mentions, 0, :confidence)
                        ON CONFLICT (kb_id, canonical_name)
                        DO UPDATE SET
                            description = CASE WHEN length(EXCLUDED.description) > length(COALESCE(graph_entities.description, ''))
                                          THEN EXCLUDED.description ELSE graph_entities.description END,
                            aliases = EXCLUDED.aliases,
                            neo4j_node_id = EXCLUDED.neo4j_node_id,
                            mention_count = graph_entities.mention_count + EXCLUDED.mention_count,
                            updated_at = now()
                    """
                    ),
                    {
                        "id": str(uuid_mod.uuid4()),
                        "tenant_id": tenant_id,
                        "kb_id": kb_id,
                        "name": e.canonical_name,
                        "type": e.entity_type,
                        "desc": e.description or "",
                        "aliases": json.dumps(e.aliases or []),
                        "doc_ids": json.dumps(e.source_doc_ids or []),
                        "neo4j_id": neo4j_id,
                        "mentions": e.mention_count,
                        "confidence": float(e.confidence),
                    },
                )

            # Upsert relationships (entities must exist from step above)
            rels_written = 0
            for r in relationships:
                result = conn.execute(
                    text(
                        """
                        INSERT INTO graph_relationships (id, kb_id, source_entity_id, target_entity_id,
                            relationship_type, description, weight, source_doc_ids,
                            access_count, confidence)
                        SELECT :id, CAST(:kb_id AS uuid), src.id, tgt.id, :rel_type, :desc, :weight, CAST(:doc_ids AS jsonb),
                               0, 1.0
                        FROM graph_entities src, graph_entities tgt
                        WHERE src.kb_id = CAST(:kb_id AS uuid) AND src.canonical_name = :src_name
                          AND tgt.kb_id = CAST(:kb_id AS uuid) AND tgt.canonical_name = :tgt_name
                        ON CONFLICT DO NOTHING
                    """
                    ),
                    {
                        "id": str(uuid_mod.uuid4()),
                        "kb_id": kb_id,
                        "src_name": r.source,
                        "tgt_name": r.target,
                        "rel_type": r.relationship_type,
                        "desc": r.description or "",
                        "weight": float(r.weight),
                        "doc_ids": json.dumps(r.source_doc_ids or []),
                    },
                )
                rels_written += result.rowcount

            if rels_written < len(relationships):
                logger.warning(
                    "Only %d/%d relationships written to PG (some entities may not have matched)",
                    rels_written,
                    len(relationships),
                )

            # Update KB counters
            conn.execute(
                text(
                    """
                    UPDATE knowledge_collections SET
                        entity_count = (SELECT count(*) FROM graph_entities WHERE kb_id = :kb_id),
                        relationship_count = (SELECT count(*) FROM graph_relationships WHERE kb_id = :kb_id),
                        graph_enabled = true,
                        last_cognified_at = now()
                    WHERE id = CAST(:kb_id AS uuid)
                """
                ),
                {"kb_id": kb_id},
            )

    except Exception as e:
        logger.error("Failed to update PG metadata for kb %s: %s", kb_id, e)
