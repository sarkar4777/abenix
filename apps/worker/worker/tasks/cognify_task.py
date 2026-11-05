"""Celery tasks for Cognify, one per document with progress kept in Postgres."""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded

from worker.celery_app import celery_app

# Add agent-runtime to path for knowledge engine imports
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://abenix:abenix@localhost:5432/abenix"
)

# a document task hands itself back well before Celery's soft limit
TIME_SLICE_S = float(os.environ.get("COGNIFY_TASK_TIME_SLICE_S", "1200"))
GRAPH_RETRY_S = float(os.environ.get("COGNIFY_GRAPH_RETRY_S", "60"))


def _get_db_url() -> str:
    """Get synchronous database URL."""
    from engine.knowledge.cognify_store import sync_url

    return sync_url(DATABASE_URL)


def _run(coro_factory):
    """A fresh loop per task, and the driver goes with it because it is bound to the loop."""

    async def main():
        from engine.knowledge.neo4j_client import close_neo4j

        try:
            return await coro_factory()
        finally:
            await close_neo4j()

    from engine.knowledge.neo4j_client import forget_driver

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(main())
    finally:
        forget_driver()
        loop.close()


def _load_document(document_id: str, kb_id: str, config: dict) -> dict | None:
    """One document's chunks, from the index when it holds the text, else from the file."""
    from sqlalchemy import text

    from engine.knowledge.cognify_store import engine_for

    with engine_for(_get_db_url()).connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, filename, file_type, storage_url, chunk_count FROM documents "
                "WHERE id = CAST(:id AS uuid) AND kb_id = CAST(:kb AS uuid) "
                "AND is_current IS NOT FALSE"
            ),
            {"id": document_id, "kb": kb_id},
        ).fetchone()
        if not row:
            return None
        default_chunking = (
            config.get("chunk_size", 1000) == 1000
            and config.get("chunk_overlap", 200) == 200
        )
        if default_chunking:
            indexed = _indexed_chunks(conn, document_id)
            if indexed:
                return {"id": document_id, "filename": row[1], "chunks": indexed}

    from worker.tasks.document_processor import _chunk_text, _extract_text, _local_path

    tmp_path = None
    try:
        local, tmp_path = _local_path(row[3], row[2])
        content = _extract_text(local, row[2])
        chunks = _chunk_text(
            content,
            chunk_size=config.get("chunk_size", 1000),
            chunk_overlap=config.get("chunk_overlap", 200),
        )
        return {"id": document_id, "filename": row[1], "chunks": chunks}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _indexed_chunks(conn, document_id: str) -> list[str]:
    """OCR and vision are not free and not stable, the indexed text is both."""
    from sqlalchemy import text

    try:
        with conn.begin_nested():
            rows = conn.execute(
                text(
                    "SELECT content FROM chunks WHERE document_id = CAST(:d AS uuid) "
                    "AND embedding_generation = (SELECT max(embedding_generation) "
                    "FROM chunks WHERE document_id = CAST(:d AS uuid)) "
                    "ORDER BY chunk_index"
                ),
                {"d": document_id},
            ).fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception as e:
        logger.debug("no indexed chunks for %s: %s", document_id, e)
        return []


def _update_job_status(job_id: str, status: str, **kwargs):
    """Update cognify job status in PostgreSQL."""
    from sqlalchemy import text

    from engine.knowledge.cognify_store import engine_for

    status_upper = (status or "").upper()
    with engine_for(_get_db_url()).begin() as conn:
        sets = ["status = :status", "heartbeat_at = now()"]
        params = {"job_id": job_id, "status": status_upper}

        if status_upper == "EXTRACTING":
            sets.append("started_at = coalesce(started_at, now())")
        elif status_upper in ("COMPLETE", "FAILED", "STOPPED"):
            sets.append("completed_at = now()")

        for key, value in kwargs.items():
            sets.append(f"{key} = :{key}")
            params[key] = value

        conn.execute(
            text(
                f"UPDATE cognify_jobs SET {', '.join(sets)} WHERE id = CAST(:job_id AS uuid)"
            ),
            params,
        )


def _dispatch_documents(job_id, kb_id, tenant_id, config, slots: int) -> int:
    from engine.knowledge import cognify_store as store

    claimed = store.claim_documents(_get_db_url(), job_id, slots)
    for document_id in claimed:
        run_cognify_document.delay(job_id, kb_id, tenant_id, document_id, config)
    return len(claimed)


def _after_document(job_id, kb_id, tenant_id, config) -> None:
    """Keep the job's window full, or close the job when nothing is left."""
    from engine.knowledge import cognify_store as store

    url = _get_db_url()
    state = store.job_state(url, job_id, tenant_id)
    if state.stop_requested:
        store.stop_pending_documents(url, job_id)
    elif _dispatch_documents(job_id, kb_id, tenant_id, config, 1):
        return
    if store.claim_finalize(url, job_id):
        finalize_cognify_job.delay(job_id, kb_id, tenant_id, config)


@celery_app.task(
    bind=True,
    name="worker.tasks.cognify_task.run_cognify_job",
    max_retries=1,
    default_retry_delay=60,
)
def run_cognify_job(
    self,
    job_id: str,
    kb_id: str,
    tenant_id: str,
    doc_ids: list[str] | None = None,
    config: dict | None = None,
) -> dict:
    """Plan the job, then start the first window of document tasks."""
    from engine.knowledge import cognify_pipeline as pipeline
    from engine.knowledge import cognify_store as store
    from engine.knowledge.neo4j_client import (
        ensure_kb_keys,
        ensure_schema,
        is_neo4j_available,
    )

    config = config or {}
    url = _get_db_url()
    try:
        _update_job_status(job_id, "extracting")
        tenant_cfg = pipeline.load_cognify_config(tenant_id, url)
        budget = tenant_cfg.get("daily_budget_usd")
        spent = float(tenant_cfg.get("spent_today_usd") or 0)
        if budget is not None and spent >= budget:
            message = pipeline.daily_budget_error(budget, spent)
            _update_job_status(
                job_id, "failed", error_message=message, stop_reason="daily_budget"
            )
            return {"status": "failed", "error": message}

        async def prepare() -> bool:
            if not await is_neo4j_available():
                return False
            await ensure_schema()
            await ensure_kb_keys(kb_id, tenant_id)
            return True

        if not _run(prepare):
            message = "Neo4j is not available. Start the Neo4j container."
            _update_job_status(job_id, "failed", error_message=message)
            return {"status": "failed", "error": message}

        force = bool(config.get("force"))
        if force:
            if doc_ids:
                for document_id in doc_ids:
                    store.clear_ledger(url, kb_id, document_id)
            else:
                store.clear_ledger(url, kb_id)
                _run(lambda: _reset_counts(kb_id, url))
        total = store.enqueue_documents(url, job_id, kb_id, doc_ids, force)
        if total == 0:
            _update_job_status(job_id, "complete", stop_reason="up_to_date")
            return {"status": "complete", "documents": 0}

        slots = max(1, int(tenant_cfg["max_parallel_docs"]))
        started = _dispatch_documents(job_id, kb_id, tenant_id, config, slots)
        return {"status": "extracting", "documents": total, "started": started}
    except Exception as e:
        logger.error("Cognify job %s failed: %s", job_id, e)
        _update_job_status(job_id, "failed", error_message=str(e)[:2000])
        return {"status": "failed", "error": str(e)}


async def _reset_counts(kb_id: str, url: str) -> None:
    """A forced full run recounts mentions and weights from zero."""
    from sqlalchemy import text

    from engine.knowledge.cognify_store import engine_for
    from engine.knowledge.neo4j_client import (
        _NEO4J_DATABASE,
        WRITE_TIMEOUT_S,
        cypher,
        get_neo4j_driver,
    )

    driver = await get_neo4j_driver()
    async with driver.session(database=_NEO4J_DATABASE) as session:
        for statement in (
            "MATCH (e:Entity {kb_id: $kb_id}) WHERE e.mention_count <> 0 "
            "WITH e LIMIT 5000 SET e.mention_count = 0, e.last_batch_id = '' "
            "RETURN count(e) AS n",
            "MATCH (:Entity {kb_id: $kb_id})-[r]->(:Entity {kb_id: $kb_id}) "
            "WHERE r.weight <> 0 WITH r LIMIT 5000 SET r.weight = 0, r.last_batch_id = '' "
            "RETURN count(r) AS n",
        ):
            while True:
                result = await session.run(
                    cypher(statement, timeout=WRITE_TIMEOUT_S), kb_id=kb_id
                )
                record = await result.single()
                if not record or record["n"] == 0:
                    break
    with engine_for(url).begin() as conn:
        conn.execute(
            text(
                "UPDATE graph_entities SET mention_count = 0 "
                "WHERE kb_id = CAST(:kb AS uuid)"
            ),
            {"kb": kb_id},
        )
        conn.execute(
            text(
                "UPDATE graph_relationships SET weight = 0 "
                "WHERE kb_id = CAST(:kb AS uuid)"
            ),
            {"kb": kb_id},
        )


@celery_app.task(
    bind=True,
    name="worker.tasks.cognify_task.run_cognify_document",
    max_retries=8,
)
def run_cognify_document(
    self,
    job_id: str,
    kb_id: str,
    tenant_id: str,
    document_id: str,
    config: dict | None = None,
) -> dict:
    """Extract and write what this document still needs. Reruns skip finished chunks."""
    from engine.knowledge import cognify_pipeline as pipeline
    from engine.knowledge import cognify_store as store
    from engine.knowledge.graph_writer import GraphUnavailable

    config = config or {}
    url = _get_db_url()
    state = store.job_state(url, job_id, tenant_id)
    row = store.document_row(url, job_id, document_id)
    if row and row["status"] in ("done", "failed", "stopped"):
        return {"status": row["status"]}
    if state.stop_requested:
        store.set_document_state(url, job_id, document_id, "stopped")
        _after_document(job_id, kb_id, tenant_id, config)
        return {"status": "stopped"}
    first_attempt = not row or row["attempts"] == 0
    store.set_document_state(url, job_id, document_id, "running", bump_attempts=True)

    deadline = time.monotonic() + TIME_SLICE_S

    def fail(message: str) -> dict:
        store.set_document_state(
            url, job_id, document_id, "failed", error=message[:2000]
        )
        _after_document(job_id, kb_id, tenant_id, config)
        return {"status": "failed", "error": message}

    try:
        doc = _load_document(document_id, kb_id, config)
        if not doc or not doc.get("chunks"):
            return fail("No text could be read from this document")

        async def work():
            ontology = await asyncio.to_thread(
                pipeline.load_active_ontology, kb_id, url
            )
            ctx = pipeline.build_context(
                kb_id, tenant_id, job_id, config, url, ontology=ontology
            )
            ctx.deadline = deadline
            return await pipeline.cognify_document(ctx, doc, count_totals=first_attempt)

        outcome = _run(work)
    except SoftTimeLimitExceeded:
        return _continue_later(self, url, job_id, document_id, "the task time limit")
    except GraphUnavailable as e:
        store.set_document_state(url, job_id, document_id, "queued", error=str(e)[:500])
        try:
            raise self.retry(countdown=GRAPH_RETRY_S, exc=e)
        except GraphUnavailable:
            store.request_stop(url, job_id, pipeline.STOP_GRAPH_DOWN)
            return fail(pipeline.stop_message(pipeline.STOP_GRAPH_DOWN))
    except Exception as e:
        logger.exception("Cognify document %s failed", document_id)
        return fail(str(e))

    if outcome.stop_reason == pipeline.STOP_TIME_SLICE:
        store.set_document_state(
            url,
            job_id,
            document_id,
            "queued",
            chunks_total=outcome.chunks_selected,
            chunks_done=outcome.chunks_done,
            chunks_skipped=outcome.chunks_skipped if first_attempt else 0,
        )
        _requeue([job_id, kb_id, tenant_id, document_id, config])
        return {"status": "continuing", "chunks_done": outcome.chunks_done}

    stopped = bool(outcome.stop_reason)
    store.set_document_state(
        url,
        job_id,
        document_id,
        "stopped" if stopped else "done",
        chunks_total=outcome.chunks_selected,
        chunks_done=outcome.chunks_done,
        chunks_skipped=outcome.chunks_skipped if first_attempt else 0,
        chunks_failed=outcome.chunks_failed,
        error=(outcome.errors[0] if outcome.errors else None),
    )
    if (
        outcome.finished
        and pipeline.ChunkSelection.from_config(config).covers_everything
    ):
        store.mark_document_cognified(url, document_id, job_id)
    _after_document(job_id, kb_id, tenant_id, config)
    return {
        "status": "stopped" if stopped else "done",
        "chunks_done": outcome.chunks_done,
        "chunks_skipped": outcome.chunks_skipped,
        "chunks_failed": outcome.chunks_failed,
    }


def _requeue(args, kwargs=None) -> None:
    run_cognify_document.apply_async(args=args, kwargs=kwargs or {}, countdown=1)


def _continue_later(task, url, job_id, document_id, why) -> dict:
    from engine.knowledge import cognify_store as store

    store.set_document_state(url, job_id, document_id, "queued")
    logger.info("Cognify document %s continues after %s", document_id, why)
    _requeue(task.request.args, task.request.kwargs)
    return {"status": "continuing"}


@celery_app.task(
    bind=True,
    name="worker.tasks.cognify_task.finalize_cognify_job",
    max_retries=2,
    default_retry_delay=60,
)
def finalize_cognify_job(
    self, job_id: str, kb_id: str, tenant_id: str, config: dict | None = None
) -> dict:
    """KB wide resolution, counters, report and the job's final status."""
    from sqlalchemy import text

    from engine.knowledge import cognify_pipeline as pipeline
    from engine.knowledge import cognify_store as store
    from engine.knowledge.kb_resolution import resolve_kb_entities

    config = config or {}
    url = _get_db_url()
    state = store.job_state(url, job_id, tenant_id)
    resolution = None
    if not state.stop_requested and config.get("kb_resolution", True):
        left = None
        if state.budget is not None:
            left = max(state.budget - state.cost, 0.0)
        try:
            resolution = _run(
                lambda: resolve_kb_entities(
                    kb_id,
                    tenant_id,
                    db_url=url,
                    model=config.get("model") or pipeline.DEFAULT_COGNIFY_MODEL,
                    budget_left=left,
                    use_llm=bool(config.get("llm_resolution", True)),
                )
            )
        except SoftTimeLimitExceeded:
            logger.warning("Cognify job %s stopped resolving at the time limit", job_id)
        except Exception as e:
            logger.warning("KB wide resolution failed for job %s: %s", job_id, e)

    if resolution is not None and resolution.cost:
        store.record_extractions(
            url,
            kb_id,
            kb_id,
            job_id,
            [],
            resolution.tokens,
            resolution.cost,
            f"{pipeline._provider_key(config.get('model') or pipeline.DEFAULT_COGNIFY_MODEL)}_cost",
        )
    store.refresh_kb_counters(url, kb_id)

    summary = store.document_summary(url, job_id)
    with store.engine_for(url).connect() as conn:
        job = conn.execute(
            text(
                "SELECT stop_reason, chunks_failed, entities_failed, relationships_failed, "
                "cost_usd, budget_usd, started_at, details, entities_written, "
                "entities_merged, relationships_written, chunks_processed, chunks_skipped "
                "FROM cognify_jobs WHERE id = CAST(:job AS uuid)"
            ),
            {"job": job_id},
        ).fetchone()
        duration = conn.execute(
            text(
                "SELECT EXTRACT(EPOCH FROM now() - coalesce(started_at, created_at)) "
                "FROM cognify_jobs WHERE id = CAST(:job AS uuid)"
            ),
            {"job": job_id},
        ).scalar()

    stop_reason = job[0]
    failed_docs = summary.get("failed", 0)
    done_docs = summary.get("done", 0)
    parts = []
    if stop_reason in pipeline.STOP_MESSAGES:
        parts.append(
            pipeline.stop_message(
                stop_reason,
                float(job[5]) if job[5] is not None else None,
                float(job[4] or 0),
            )
        )
    if summary.get("stopped"):
        parts.append(f"{summary['stopped']} document(s) were not finished.")
    if failed_docs:
        parts.append(f"{failed_docs} document(s) failed.")
    if job[1]:
        parts.append(f"{job[1]} chunk(s) failed. Run Cognify again to retry them.")
    if job[2] or job[3]:
        parts.append(
            f"{job[2]} entities and {job[3]} relationships could not be written to the graph."
        )
    if stop_reason:
        status = "stopped"
    elif failed_docs and not done_docs:
        status = "failed"
    else:
        status = "complete"

    _update_job_status(
        job_id,
        status,
        documents_processed=done_docs,
        entities_merged=int(job[9] or 0)
        + (resolution.exact_merges + resolution.llm_merges if resolution else 0),
        duration_seconds=float(duration or 0),
        error_message=" ".join(parts) or None,
    )
    _save_report(url, job_id, kb_id, job, summary, resolution)
    return {"status": status, "documents": done_docs}


def _save_report(url, job_id, kb_id, job, summary, resolution) -> None:
    from sqlalchemy import text

    from engine.knowledge.cognify_store import engine_for

    details = dict(job[7] or {})
    details.update(
        documents=summary,
        chunks_skipped=int(job[12] or 0),
        chunks_failed=int(job[1] or 0),
        entities_failed=int(job[2] or 0),
        relationships_failed=int(job[3] or 0),
        stop_reason=job[0],
    )
    if resolution is not None:
        details["kb_resolution"] = {
            "names_scanned": resolution.names_scanned,
            "groups_found": resolution.groups_found,
            "exact_merges": resolution.exact_merges,
            "llm_merges": resolution.llm_merges,
            "undecided_groups": resolution.undecided_groups,
            "truncated": resolution.truncated,
        }
    try:
        with engine_for(url).begin() as conn:
            types = conn.execute(
                text(
                    "SELECT entity_type, count(*) FROM graph_entities "
                    "WHERE kb_id = CAST(:kb AS uuid) GROUP BY entity_type"
                ),
                {"kb": kb_id},
            ).fetchall()
            rels = conn.execute(
                text(
                    "SELECT relationship_type, count(*) FROM graph_relationships "
                    "WHERE kb_id = CAST(:kb AS uuid) GROUP BY relationship_type"
                ),
                {"kb": kb_id},
            ).fetchall()
            top = conn.execute(
                text(
                    "SELECT canonical_name, entity_type, mention_count, description "
                    "FROM graph_entities WHERE kb_id = CAST(:kb AS uuid) "
                    "ORDER BY mention_count DESC LIMIT 20"
                ),
                {"kb": kb_id},
            ).fetchall()
            conn.execute(
                text(
                    """
                    INSERT INTO cognify_reports (id, job_id, kb_id, entities_by_type, top_entities,
                        relationship_types, new_entities, merged_entities, new_relationships,
                        strengthened_relationships, documents_processed, chunks_analyzed,
                        processing_details)
                    VALUES (:id, CAST(:job_id AS uuid), CAST(:kb_id AS uuid), CAST(:ent_types AS jsonb),
                        CAST(:top_ent AS jsonb), CAST(:rel_types AS jsonb), :new_ent, :merged, :new_rels,
                        0, :docs, :chunks, CAST(:details AS jsonb))
                    ON CONFLICT (job_id) DO NOTHING
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "job_id": job_id,
                    "kb_id": kb_id,
                    "ent_types": json.dumps({r[0]: r[1] for r in types}),
                    "top_ent": json.dumps(
                        [
                            {
                                "name": r[0],
                                "type": r[1],
                                "mentions": r[2],
                                "description": r[3],
                            }
                            for r in top
                        ]
                    ),
                    "rel_types": json.dumps({r[0]: r[1] for r in rels}),
                    "new_ent": int(job[8] or 0),
                    "merged": int(job[9] or 0),
                    "new_rels": int(job[10] or 0),
                    "docs": summary.get("done", 0),
                    "chunks": int(job[11] or 0),
                    "details": json.dumps(details, default=str),
                },
            )
    except Exception as e:
        logger.warning("Failed to save cognify report: %s", e)


@celery_app.task(
    bind=True,
    name="worker.tasks.cognify_task.delete_kb_graph",
    max_retries=5,
    default_retry_delay=120,
)
def delete_kb_graph_task(self, kb_id: str) -> dict:
    """Remove a KB's graph from Neo4j in small transactions, retried while Neo4j is away."""
    from engine.knowledge.graph_writer import GraphUnavailable, delete_kb_graph

    try:
        return _run(lambda: delete_kb_graph(kb_id))
    except GraphUnavailable as e:
        raise self.retry(exc=e)
