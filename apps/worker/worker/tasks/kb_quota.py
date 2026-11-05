"""Tenant knowledge limits as the worker sees them, over psycopg2."""

from __future__ import annotations

import logging
from typing import Any

import knowledge_quota as kq

logger = logging.getLogger(__name__)


def tenant_of(cur: Any, kb_id: str) -> str | None:
    cur.execute(
        "SELECT tenant_id::text FROM knowledge_collections WHERE id = %s", (kb_id,)
    )
    row = cur.fetchone()
    return row[0] if row else None


def limits_and_usage(cur: Any, tenant_id: str) -> tuple[dict | None, kq.Usage]:
    cur.execute(kq.LIMITS_SQL.format(t="%s"), (tenant_id,))
    row = cur.fetchone()
    limits = dict(zip(kq.LIMIT_KEYS, row)) if row else None
    if not limits:
        return None, kq.Usage()
    cur.execute(kq.USAGE_SQL.format(t="%s"), (tenant_id,))
    docs, chunks, size = cur.fetchone()
    cur.execute(kq.SPEND_SQL.format(t="%s", p="%s"), (tenant_id, kq.period_start()))
    emb, cog, tokens = cur.fetchone()
    return limits, kq.Usage(
        documents=int(docs),
        chunks=int(chunks),
        storage_bytes=int(size),
        embedding_usd=float(emb),
        cognify_usd=float(cog),
        embedding_tokens=int(tokens),
    )


def enforce(cur: Any, tenant_id: str, **adding: Any) -> None:
    limits, usage = limits_and_usage(cur, tenant_id)
    kq.check(limits, usage, **adding)


def record_spend(
    cur: Any,
    tenant_id: str,
    *,
    embedding_usd: float = 0.0,
    embedding_tokens: int = 0,
    cognify_usd: float = 0.0,
) -> None:
    cur.execute(
        kq.RECORD_SQL.format(t="%s", p="%s", e="%s", k="%s", c="%s"),
        (tenant_id, kq.period_start(), embedding_usd, embedding_tokens, cognify_usd),
    )


def enforce_for_kb(kb_id: str, **adding: Any) -> None:
    """One short connection, a document or a batch asks once."""
    import psycopg2

    from worker.tasks.document_processor import _sync_db_url

    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            tenant = tenant_of(cur, kb_id)
            if tenant:
                enforce(cur, tenant, **adding)
    finally:
        conn.close()


def record_for_kb(kb_id: str, **spent: Any) -> None:
    """Spend already happened, a failed write only loses the count."""
    import psycopg2

    from worker.tasks.document_processor import _sync_db_url

    try:
        conn = psycopg2.connect(_sync_db_url())
        try:
            with conn.cursor() as cur:
                tenant = tenant_of(cur, kb_id)
                if tenant:
                    record_spend(cur, tenant, **spent)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("knowledge spend not recorded for %s: %s", kb_id, e)
