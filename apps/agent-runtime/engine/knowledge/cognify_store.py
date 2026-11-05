"""Durable Cognify state in Postgres, the job, its documents and the chunk ledger."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_engines: dict[str, Any] = {}

MAX_DETAIL_ITEMS = 50
OPEN_DOC_STATES = ("pending", "queued", "running")
TEXT_LIMITS = {"name": 500, "type": 100, "rel": 200}


def sync_url(url: str) -> str:
    """The async driver URL the runtime carries, in the form the sync pool can use."""
    if not url:
        return url
    url = url.replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")
    if "?" in url:
        base, query = url.split("?", 1)
        kept = [p for p in query.split("&") if not p.lower().startswith("ssl=")]
        url = base + (("?" + "&".join(kept)) if kept else "")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


def usable_url(db_url: str, kb_id: str) -> str:
    """Empty when this process cannot keep progress, the runtime image has no sync driver."""
    if not db_url or _uuid_or_none(kb_id) is None:
        return ""
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        return ""
    return db_url


def engine_for(db_url: str):
    url = sync_url(db_url)
    engine = _engines.get(url)
    if engine is None:
        from sqlalchemy import create_engine

        engine = create_engine(url, pool_size=2, max_overflow=4, pool_pre_ping=True)
        _engines[url] = engine
    return engine


def dispose_engines() -> None:
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()


def _sql(statement: str):
    from sqlalchemy import text

    return text(statement)


# chunk ledger


@dataclass
class LedgerRow:
    chunk_hash: str
    chunk_index: int
    result: dict | None = None
    tokens: int = 0
    cost: float = 0.0


@dataclass
class LedgerState:
    done: set[str] = field(default_factory=set)
    pending: dict[str, LedgerRow] = field(default_factory=dict)


def ledger_state(db_url: str, kb_id: str, document_id: str) -> LedgerState:
    state = LedgerState()
    if not db_url:
        return state
    with engine_for(db_url).connect() as conn:
        rows = conn.execute(
            _sql(
                "SELECT chunk_hash, chunk_index, status, result, tokens_used, cost_usd "
                "FROM cognify_chunks WHERE kb_id = CAST(:kb AS uuid) "
                "AND document_id = CAST(:doc AS uuid)"
            ),
            {"kb": kb_id, "doc": document_id},
        ).fetchall()
    for r in rows:
        if r[2] == "done":
            state.done.add(r[0])
        else:
            state.pending[r[0]] = LedgerRow(r[0], r[1], r[3], r[4], float(r[5] or 0))
    return state


def clear_ledger(db_url: str, kb_id: str, document_id: str | None = None) -> int:
    if not db_url:
        return 0
    clause = " AND document_id = CAST(:doc AS uuid)" if document_id else ""
    with engine_for(db_url).begin() as conn:
        return (
            conn.execute(
                _sql(
                    f"DELETE FROM cognify_chunks WHERE kb_id = CAST(:kb AS uuid){clause}"
                ),
                {"kb": kb_id, "doc": document_id},
            ).rowcount
            or 0
        )


def record_extractions(
    db_url: str,
    kb_id: str,
    document_id: str,
    job_id: str,
    rows: list[LedgerRow],
    tokens: int,
    cost: float,
    cost_column: str,
    chunks_failed: int = 0,
) -> None:
    """Keep what was paid for before anything else can fail."""
    if not db_url:
        return
    with engine_for(db_url).begin() as conn:
        if rows:
            conn.execute(
                _sql(
                    """
                    INSERT INTO cognify_chunks (kb_id, document_id, chunk_hash, chunk_index,
                        status, result, job_id, tokens_used, cost_usd)
                    VALUES (CAST(:kb AS uuid), CAST(:doc AS uuid), :hash, :idx, 'extracted',
                        CAST(:result AS jsonb), CAST(:job AS uuid), :tokens, :cost)
                    ON CONFLICT (kb_id, document_id, chunk_hash) DO UPDATE SET
                        status = 'extracted', result = EXCLUDED.result,
                        chunk_index = EXCLUDED.chunk_index, job_id = EXCLUDED.job_id,
                        tokens_used = EXCLUDED.tokens_used, cost_usd = EXCLUDED.cost_usd
                    """
                ),
                [
                    {
                        "kb": kb_id,
                        "doc": document_id,
                        "hash": r.chunk_hash,
                        "idx": r.chunk_index,
                        "result": json.dumps(r.result or {}),
                        "job": job_id,
                        "tokens": r.tokens,
                        "cost": r.cost,
                    }
                    for r in rows
                ],
            )
        if cost_column not in (
            "anthropic_cost",
            "openai_cost",
            "google_cost",
            "other_cost",
        ):
            cost_column = "other_cost"
        conn.execute(
            _sql(
                f"""
                UPDATE cognify_jobs SET
                    tokens_used = tokens_used + :tokens,
                    cost_usd = cost_usd + :cost,
                    {cost_column} = {cost_column} + :cost,
                    chunks_failed = chunks_failed + :failed,
                    heartbeat_at = now()
                WHERE id = CAST(:job AS uuid)
                """
            ),
            {"tokens": tokens, "cost": cost, "failed": chunks_failed, "job": job_id},
        )


# graph mirror and batch commit


def _json_union(target: str) -> str:
    return (
        "(SELECT coalesce(jsonb_agg(DISTINCT x), '[]'::jsonb) FROM "
        f"jsonb_array_elements(CASE WHEN jsonb_typeof({target}) = 'array' "
        f"THEN {target} ELSE '[]'::jsonb END || EXCLUDED.{target.split('.')[-1]}) x)"
    )


UPSERT_ENTITY = f"""
INSERT INTO graph_entities (id, tenant_id, kb_id, canonical_name, entity_type,
    description, aliases, source_doc_ids, neo4j_node_id, mention_count,
    access_count, confidence, atlas_concept_id, atlas_graph_id)
VALUES (CAST(:id AS uuid), CAST(:tenant AS uuid), CAST(:kb AS uuid), :name, :type, :desc,
    CAST(:aliases AS jsonb), CAST(:docs AS jsonb), :neo4j_id, :mentions, 0, :conf,
    CAST(:concept AS uuid), CAST(:graph AS uuid))
ON CONFLICT (kb_id, canonical_name) DO UPDATE SET
    entity_type = EXCLUDED.entity_type,
    description = CASE
        WHEN length(EXCLUDED.description) > length(coalesce(graph_entities.description, ''))
        THEN EXCLUDED.description ELSE graph_entities.description END,
    aliases = {_json_union("graph_entities.aliases")},
    source_doc_ids = {_json_union("graph_entities.source_doc_ids")},
    neo4j_node_id = coalesce(EXCLUDED.neo4j_node_id, graph_entities.neo4j_node_id),
    mention_count = graph_entities.mention_count + EXCLUDED.mention_count,
    confidence = GREATEST(graph_entities.confidence, EXCLUDED.confidence),
    atlas_concept_id = coalesce(EXCLUDED.atlas_concept_id, graph_entities.atlas_concept_id),
    atlas_graph_id = coalesce(EXCLUDED.atlas_graph_id, graph_entities.atlas_graph_id),
    updated_at = now()
"""

UPSERT_RELATIONSHIP = f"""
INSERT INTO graph_relationships (id, kb_id, source_entity_id, target_entity_id,
    relationship_type, description, weight, source_doc_ids, access_count, confidence,
    atlas_edge_id)
SELECT CAST(:id AS uuid), CAST(:kb AS uuid), src.id, tgt.id, :type, :desc,
    LEAST(:weight, 9.9999), CAST(:docs AS jsonb), 0, :conf, CAST(:edge AS uuid)
FROM graph_entities src, graph_entities tgt
WHERE src.kb_id = CAST(:kb AS uuid) AND src.canonical_name = :src
  AND tgt.kb_id = CAST(:kb AS uuid) AND tgt.canonical_name = :tgt
ON CONFLICT (kb_id, source_entity_id, target_entity_id, relationship_type) DO UPDATE SET
    weight = LEAST(graph_relationships.weight + EXCLUDED.weight, 9.9999),
    source_doc_ids = {_json_union("graph_relationships.source_doc_ids")},
    atlas_edge_id = coalesce(EXCLUDED.atlas_edge_id, graph_relationships.atlas_edge_id),
    updated_at = now()
"""


def _uuid_or_none(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return None


@dataclass
class BatchCounts:
    chunks: int = 0
    documents: int = 0
    entities_extracted: int = 0
    entities_merged: int = 0
    relationships_extracted: int = 0
    entities_written: int = 0
    entities_failed: int = 0
    relationships_written: int = 0
    relationships_failed: int = 0
    off_ontology: int = 0
    held_back: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    conflicts: int = 0
    entities_held: int = 0
    relationships_held: int = 0


def commit_batch(
    db_url: str,
    kb_id: str,
    tenant_id: str,
    document_id: str,
    job_id: str,
    entities: list,
    relationships: list,
    neo4j_ids: dict[str, str],
    chunk_hashes: list[str],
    counts: BatchCounts,
) -> dict[str, str]:
    """Mirror, ledger and job counters in one transaction. Returns entity ids by name."""
    if not db_url:
        return {}
    pg_ids: dict[str, str] = {}
    with engine_for(db_url).begin() as conn:
        if entities:
            conn.execute(
                _sql(UPSERT_ENTITY),
                [
                    {
                        "id": str(uuid.uuid4()),
                        "tenant": tenant_id,
                        "kb": kb_id,
                        "name": e.canonical_name[: TEXT_LIMITS["name"]],
                        "type": (e.entity_type or "concept")[: TEXT_LIMITS["type"]],
                        "desc": e.description or "",
                        "aliases": json.dumps(e.aliases or []),
                        "docs": json.dumps(e.source_doc_ids or []),
                        "neo4j_id": neo4j_ids.get(e.canonical_name),
                        "mentions": e.mention_count,
                        "conf": float(e.confidence),
                        "concept": _uuid_or_none(
                            (e.properties or {}).get("atlas_concept_id")
                        ),
                        "graph": _uuid_or_none(
                            (e.properties or {}).get("atlas_graph_id")
                        ),
                    }
                    for e in entities
                ],
            )
            rows = conn.execute(
                _sql(
                    "SELECT canonical_name, id FROM graph_entities "
                    "WHERE kb_id = CAST(:kb AS uuid) AND canonical_name = ANY(:names)"
                ),
                {
                    "kb": kb_id,
                    "names": [
                        e.canonical_name[: TEXT_LIMITS["name"]] for e in entities
                    ],
                },
            ).fetchall()
            pg_ids = {r[0]: str(r[1]) for r in rows}
        if relationships:
            conn.execute(
                _sql(UPSERT_RELATIONSHIP),
                [
                    {
                        "id": str(uuid.uuid4()),
                        "kb": kb_id,
                        "src": r.source[: TEXT_LIMITS["name"]],
                        "tgt": r.target[: TEXT_LIMITS["name"]],
                        "type": r.relationship_type[: TEXT_LIMITS["rel"]],
                        "desc": r.description or "",
                        "weight": float(r.weight),
                        "docs": json.dumps(r.source_doc_ids or []),
                        "conf": float(r.confidence),
                        "edge": _uuid_or_none(r.atlas_edge_id),
                    }
                    for r in relationships
                ],
            )
        if chunk_hashes:
            conn.execute(
                _sql(
                    "UPDATE cognify_chunks SET status = 'done', result = NULL "
                    "WHERE kb_id = CAST(:kb AS uuid) AND document_id = CAST(:doc AS uuid) "
                    "AND chunk_hash = ANY(:hashes)"
                ),
                {"kb": kb_id, "doc": document_id, "hashes": chunk_hashes},
            )
        conn.execute(
            _sql(
                """
                UPDATE cognify_jobs SET
                    chunks_processed = chunks_processed + :chunks,
                    entities_extracted = entities_extracted + :extracted,
                    entities_merged = entities_merged + :merged,
                    relationships_extracted = relationships_extracted + :rels,
                    entities_written = entities_written + :ew,
                    entities_failed = entities_failed + :ef,
                    relationships_written = relationships_written + :rw,
                    relationships_failed = relationships_failed + :rf,
                    off_ontology_dropped = off_ontology_dropped + :off,
                    details = coalesce(details, '{}'::jsonb) || jsonb_build_object(
                        'entities_held_back',
                        coalesce((details->>'entities_held_back')::int, 0) + :eh,
                        'relationships_held_back',
                        coalesce((details->>'relationships_held_back')::int, 0) + :rh,
                        'conflicts_recorded',
                        coalesce((details->>'conflicts_recorded')::int, 0) + :cf,
                        'held_back',
                        CASE WHEN jsonb_array_length(coalesce(details->'held_back', '[]'::jsonb)) < :cap
                        THEN coalesce(details->'held_back', '[]'::jsonb) || CAST(:held AS jsonb)
                        ELSE details->'held_back' END,
                        'errors',
                        CASE WHEN jsonb_array_length(coalesce(details->'errors', '[]'::jsonb)) < :cap
                        THEN coalesce(details->'errors', '[]'::jsonb) || CAST(:errs AS jsonb)
                        ELSE details->'errors' END
                    ),
                    heartbeat_at = now()
                WHERE id = CAST(:job AS uuid)
                """
            ),
            {
                "chunks": counts.chunks,
                "extracted": counts.entities_extracted,
                "merged": counts.entities_merged,
                "rels": counts.relationships_extracted,
                "ew": counts.entities_written,
                "ef": counts.entities_failed,
                "rw": counts.relationships_written,
                "rf": counts.relationships_failed,
                "off": counts.off_ontology,
                "eh": counts.entities_held,
                "rh": counts.relationships_held,
                "cf": counts.conflicts,
                "cap": MAX_DETAIL_ITEMS,
                "held": json.dumps(counts.held_back[:MAX_DETAIL_ITEMS]),
                "errs": json.dumps(counts.errors[:10]),
                "job": job_id,
            },
        )
    return pg_ids


# job state


@dataclass
class JobState:
    exists: bool = False
    status: str = ""
    cost: float = 0.0
    budget: float | None = None
    stop_requested: bool = False
    stop_reason: str | None = None
    spent_today: float = 0.0
    chunks_paid: int = 0


def job_state(db_url: str, job_id: str, tenant_id: str) -> JobState:
    if not db_url:
        return JobState()
    with engine_for(db_url).connect() as conn:
        row = conn.execute(
            _sql(
                "SELECT status, cost_usd, budget_usd, stop_requested, stop_reason, "
                "chunks_processed + chunks_failed FROM cognify_jobs WHERE id = CAST(:job AS uuid)"
            ),
            {"job": job_id},
        ).fetchone()
        spent = conn.execute(
            _sql(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM cognify_jobs "
                "WHERE tenant_id = CAST(:t AS uuid) "
                "AND created_at >= date_trunc('day', now())"
            ),
            {"t": tenant_id},
        ).scalar()
    if row is None:
        return JobState(spent_today=float(spent or 0))
    return JobState(
        exists=True,
        status=str(row[0]),
        cost=float(row[1] or 0),
        budget=float(row[2]) if row[2] is not None else None,
        stop_requested=bool(row[3]),
        stop_reason=row[4],
        spent_today=float(spent or 0),
        chunks_paid=int(row[5] or 0),
    )


def request_stop(db_url: str, job_id: str, reason: str) -> None:
    if not db_url:
        return
    with engine_for(db_url).begin() as conn:
        conn.execute(
            _sql(
                "UPDATE cognify_jobs SET stop_requested = true, "
                "stop_reason = coalesce(stop_reason, :reason), heartbeat_at = now() "
                "WHERE id = CAST(:job AS uuid)"
            ),
            {"job": job_id, "reason": reason},
        )


def add_job_totals(db_url: str, job_id: str, chunks_total: int, skipped: int) -> None:
    if not db_url:
        return
    with engine_for(db_url).begin() as conn:
        conn.execute(
            _sql(
                "UPDATE cognify_jobs SET chunks_total = chunks_total + :total, "
                "chunks_skipped = chunks_skipped + :skipped, heartbeat_at = now() "
                "WHERE id = CAST(:job AS uuid)"
            ),
            {"job": job_id, "total": chunks_total, "skipped": skipped},
        )


def mark_document_cognified(db_url: str, document_id: str, job_id: str) -> None:
    if not db_url:
        return
    with engine_for(db_url).begin() as conn:
        conn.execute(
            _sql(
                "UPDATE documents SET cognified_at = now(), "
                "last_cognify_job_id = CAST(:job AS uuid) "
                "WHERE id = CAST(:doc AS uuid)"
            ),
            {"job": job_id, "doc": document_id},
        )


def refresh_kb_counters(db_url: str, kb_id: str) -> None:
    if not db_url:
        return
    with engine_for(db_url).begin() as conn:
        conn.execute(
            _sql(
                """
                UPDATE knowledge_collections SET
                    entity_count = (SELECT count(*) FROM graph_entities
                                    WHERE kb_id = CAST(:kb AS uuid)),
                    relationship_count = (SELECT count(*) FROM graph_relationships
                                          WHERE kb_id = CAST(:kb AS uuid)),
                    graph_enabled = true,
                    last_cognified_at = now()
                WHERE id = CAST(:kb AS uuid)
                """
            ),
            {"kb": kb_id},
        )


# documents inside a job


def enqueue_documents(
    db_url: str,
    job_id: str,
    kb_id: str,
    doc_ids: list[str] | None,
    force: bool,
) -> int:
    """Register what this job will process. Rerunning the task adds nothing twice."""
    filters = [
        "kb_id = CAST(:kb AS uuid)",
        "status = 'READY'",
        "is_current IS NOT FALSE",
    ]
    params: dict[str, Any] = {"kb": kb_id, "job": job_id}
    if doc_ids:
        filters.append("id = ANY(CAST(:ids AS uuid[]))")
        params["ids"] = doc_ids
    elif not force:
        filters.append("cognified_at IS NULL")
    with engine_for(db_url).begin() as conn:
        conn.execute(
            _sql(
                "INSERT INTO cognify_job_documents (job_id, document_id, status) "
                f"SELECT CAST(:job AS uuid), id, 'pending' FROM documents "
                f"WHERE {' AND '.join(filters)} ON CONFLICT DO NOTHING"
            ),
            params,
        )
        total = (
            conn.execute(
                _sql(
                    "SELECT count(*) FROM cognify_job_documents "
                    "WHERE job_id = CAST(:job AS uuid)"
                ),
                {"job": job_id},
            ).scalar()
            or 0
        )
        conn.execute(
            _sql(
                "UPDATE cognify_jobs SET documents_total = :total, heartbeat_at = now() "
                "WHERE id = CAST(:job AS uuid)"
            ),
            {"total": total, "job": job_id},
        )
    return int(total)


def claim_documents(db_url: str, job_id: str, limit: int) -> list[str]:
    """Move up to limit pending documents to queued. Two workers never get the same one."""
    if limit <= 0:
        return []
    with engine_for(db_url).begin() as conn:
        rows = conn.execute(
            _sql(
                """
                UPDATE cognify_job_documents SET status = 'queued', updated_at = now()
                WHERE job_id = CAST(:job AS uuid) AND document_id IN (
                    SELECT document_id FROM cognify_job_documents
                    WHERE job_id = CAST(:job AS uuid) AND status = 'pending'
                    ORDER BY document_id LIMIT :n FOR UPDATE SKIP LOCKED)
                RETURNING document_id
                """
            ),
            {"job": job_id, "n": limit},
        ).fetchall()
    return [str(r[0]) for r in rows]


def set_document_state(
    db_url: str,
    job_id: str,
    document_id: str,
    status: str,
    error: str | None = None,
    chunks_total: int | None = None,
    chunks_done: int = 0,
    chunks_skipped: int = 0,
    chunks_failed: int = 0,
    bump_attempts: bool = False,
) -> None:
    with engine_for(db_url).begin() as conn:
        conn.execute(
            _sql(
                """
                UPDATE cognify_job_documents SET
                    status = :status,
                    error = coalesce(:error, error),
                    chunks_total = coalesce(:total, chunks_total),
                    chunks_done = chunks_done + :done,
                    chunks_skipped = chunks_skipped + :skipped,
                    chunks_failed = chunks_failed + :failed,
                    attempts = attempts + :attempt,
                    updated_at = now()
                WHERE job_id = CAST(:job AS uuid) AND document_id = CAST(:doc AS uuid)
                """
            ),
            {
                "status": status,
                "error": error,
                "total": chunks_total,
                "done": chunks_done,
                "skipped": chunks_skipped,
                "failed": chunks_failed,
                "attempt": 1 if bump_attempts else 0,
                "job": job_id,
                "doc": document_id,
            },
        )


def document_row(db_url: str, job_id: str, document_id: str) -> dict[str, Any] | None:
    with engine_for(db_url).connect() as conn:
        row = conn.execute(
            _sql(
                "SELECT status, attempts FROM cognify_job_documents "
                "WHERE job_id = CAST(:job AS uuid) AND document_id = CAST(:doc AS uuid)"
            ),
            {"job": job_id, "doc": document_id},
        ).fetchone()
    return {"status": row[0], "attempts": row[1]} if row else None


def stop_pending_documents(db_url: str, job_id: str) -> int:
    with engine_for(db_url).begin() as conn:
        return (
            conn.execute(
                _sql(
                    "UPDATE cognify_job_documents SET status = 'stopped', updated_at = now() "
                    "WHERE job_id = CAST(:job AS uuid) AND status = 'pending'"
                ),
                {"job": job_id},
            ).rowcount
            or 0
        )


def document_summary(db_url: str, job_id: str) -> dict[str, int]:
    with engine_for(db_url).connect() as conn:
        rows = conn.execute(
            _sql(
                "SELECT status, count(*) FROM cognify_job_documents "
                "WHERE job_id = CAST(:job AS uuid) GROUP BY status"
            ),
            {"job": job_id},
        ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def claim_finalize(db_url: str, job_id: str) -> bool:
    """True for exactly one caller, once no document is still open."""
    with engine_for(db_url).begin() as conn:
        done = conn.execute(
            _sql(
                """
                UPDATE cognify_jobs SET status = 'RESOLVING', heartbeat_at = now()
                WHERE id = CAST(:job AS uuid) AND status = 'EXTRACTING'
                  AND NOT EXISTS (
                    SELECT 1 FROM cognify_job_documents
                    WHERE job_id = CAST(:job AS uuid)
                      AND status IN ('pending', 'queued', 'running'))
                """
            ),
            {"job": job_id},
        ).rowcount
    return bool(done)
