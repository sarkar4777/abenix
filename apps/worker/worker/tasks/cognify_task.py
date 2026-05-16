"""Celery task: run cognify pipeline to build knowledge graph from documents."""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from worker.celery_app import celery_app

# Add agent-runtime to path for knowledge engine imports
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://abenix:abenix@localhost:5432/abenix"
)


def _get_db_url() -> str:
    """Get synchronous database URL."""
    url = DATABASE_URL
    # Driver swap: asyncpg/psycopg-async → bare postgresql for psycopg2.
    url = url.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")
    # Drop the ssl=disable / ssl=require query option — asyncpg-only.
    if "?" in url:
        base, query = url.split("?", 1)
        kept = [p for p in query.split("&") if not p.lower().startswith("ssl=")]
        url = base + (("?" + "&".join(kept)) if kept else "")
    return url


def _fetch_document_chunks(kb_id: str, doc_ids: list[str], config: dict) -> list[dict]:
    """Fetch documents and chunk them for cognify processing."""
    from sqlalchemy import create_engine, text

    engine = create_engine(_get_db_url())
    documents = []

    with engine.connect() as conn:
        for doc_id in doc_ids:
            row = conn.execute(
                text(
                    "SELECT id, filename, file_type, storage_url FROM documents WHERE id = :id AND kb_id = :kb_id"
                ),
                {"id": doc_id, "kb_id": kb_id},
            ).fetchone()

            if not row:
                continue

            filename = row[1]
            file_type = row[2]
            storage_url = row[3]

            # Extract text from document
            try:
                from worker.tasks.document_processor import _extract_text, _chunk_text

                text_content = _extract_text(storage_url, file_type)
                chunks = _chunk_text(
                    text_content,
                    chunk_size=config.get("chunk_size", 1000),
                    chunk_overlap=config.get("chunk_overlap", 200),
                )
                documents.append(
                    {
                        "id": doc_id,
                        "filename": filename,
                        "chunks": chunks,
                    }
                )
            except Exception as e:
                logger.error("Failed to process document %s: %s", doc_id, e)

    return documents


def _update_job_status(job_id: str, status: str, **kwargs):
    """Update cognify job status in PostgreSQL."""
    from sqlalchemy import create_engine, text

    status_upper = (status or "").upper()
    engine = create_engine(_get_db_url())
    with engine.begin() as conn:
        sets = ["status = :status"]
        params = {"job_id": job_id, "status": status_upper}

        if status_upper == "EXTRACTING":
            sets.append("started_at = now()")
        elif status_upper in ("COMPLETE", "FAILED"):
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
    """Celery task wrapper for the async cognify pipeline."""
    config = config or {}

    try:
        _update_job_status(job_id, "extracting")

        # Fetch and chunk documents
        if not doc_ids:
            _update_job_status(
                job_id, "failed", error_message="No document IDs provided"
            )
            return {"status": "failed", "error": "No document IDs"}

        documents = _fetch_document_chunks(kb_id, doc_ids, config)
        if not documents:
            _update_job_status(
                job_id, "failed", error_message="No documents could be processed"
            )
            return {"status": "failed", "error": "No documents processed"}

        # Run the async cognify pipeline
        from engine.knowledge.cognify_pipeline import run_cognify

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                run_cognify(
                    kb_id=kb_id,
                    tenant_id=tenant_id,
                    job_id=job_id,
                    documents=documents,
                    config=config,
                    db_url=_get_db_url(),
                )
            )
        finally:
            loop.close()

        # Update job with results, including per-provider cost split.
        _update_job_status(
            job_id,
            "complete" if result.status == "complete" else "failed",
            entities_extracted=result.entities_extracted,
            entities_merged=result.entities_merged,
            relationships_extracted=result.relationships_written,
            documents_processed=result.documents_processed,
            tokens_used=result.total_tokens,
            cost_usd=result.total_cost,
            anthropic_cost=result.anthropic_cost,
            openai_cost=result.openai_cost,
            google_cost=result.google_cost,
            other_cost=result.other_cost,
            duration_seconds=result.duration_seconds,
            error_message=result.error,
        )

        # Save cognify report
        try:
            from sqlalchemy import create_engine, text as sa_text
            import uuid as uuid_mod

            engine = create_engine(_get_db_url())
            with engine.begin() as conn:
                conn.execute(
                    sa_text("""
                        INSERT INTO cognify_reports (id, job_id, kb_id, entities_by_type, top_entities,
                            relationship_types, new_entities, merged_entities, new_relationships,
                            strengthened_relationships, documents_processed, chunks_analyzed)
                        VALUES (:id, CAST(:job_id AS uuid), CAST(:kb_id AS uuid), CAST(:ent_types AS jsonb), CAST(:top_ent AS jsonb),
                            CAST(:rel_types AS jsonb), :new_ent, :merged, :new_rels, :strengthened, :docs, :chunks)
                    """),
                    {
                        "id": str(uuid_mod.uuid4()),
                        "job_id": job_id,
                        "kb_id": kb_id,
                        "ent_types": json.dumps(result.entities_by_type),
                        "top_ent": json.dumps(result.top_entities),
                        "rel_types": json.dumps(result.relationship_types),
                        "new_ent": result.entities_after_resolution,
                        "merged": result.entities_merged,
                        "new_rels": result.relationships_written,
                        # NOT NULL column added in 2026-04 — first-pass
                        # cognify has no "strengthened" relationships
                        # since nothing existed before. Defaults to 0.
                        "strengthened": 0,
                        "docs": result.documents_processed,
                        "chunks": result.chunks_analyzed,
                    },
                )
        except Exception as e:
            logger.warning("Failed to save cognify report: %s", e)

        return {
            "status": result.status,
            "entities": result.entities_after_resolution,
            "relationships": result.relationships_written,
            "duration": result.duration_seconds,
            "cost": result.total_cost,
        }

    except Exception as e:
        logger.error("Cognify job %s failed: %s", job_id, e)
        _update_job_status(job_id, "failed", error_message=str(e))
        return {"status": "failed", "error": str(e)}
