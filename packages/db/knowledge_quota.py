"""Tenant limits on knowledge, the rules the API and the worker both enforce."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

ERROR_CODE = "KNOWLEDGE_QUOTA_EXCEEDED"
WHERE_TO_RAISE = "An admin can raise it under Settings, Token Quotas."

LIMITS_SQL = (
    "SELECT max_documents, max_chunks, max_storage_bytes, monthly_embedding_usd, "
    "monthly_cognify_usd FROM tenant_knowledge_quotas WHERE tenant_id = {t}"
)
USAGE_SQL = (
    "SELECT count(*), COALESCE(sum(d.chunk_count), 0), COALESCE(sum(d.file_size), 0) "
    "FROM documents d JOIN knowledge_collections k ON k.id = d.kb_id "
    "WHERE k.tenant_id = {t} AND k.deleted_at IS NULL AND d.is_current IS NOT FALSE"
)
SPEND_SQL = (
    "SELECT COALESCE(sum(embedding_usd), 0), COALESCE(sum(cognify_usd), 0), "
    "COALESCE(sum(embedding_tokens), 0) "
    "FROM knowledge_spend WHERE tenant_id = {t} AND period = {p}"
)
RECORD_SQL = (
    "INSERT INTO knowledge_spend (tenant_id, period, embedding_usd, "
    "embedding_tokens, cognify_usd) VALUES ({t}, {p}, {e}, {k}, {c}) "
    "ON CONFLICT (tenant_id, period) DO UPDATE SET "
    "embedding_usd = knowledge_spend.embedding_usd + EXCLUDED.embedding_usd, "
    "embedding_tokens = knowledge_spend.embedding_tokens + EXCLUDED.embedding_tokens, "
    "cognify_usd = knowledge_spend.cognify_usd + EXCLUDED.cognify_usd, "
    "updated_at = now()"
)


class KnowledgeQuotaExceeded(Exception):
    def __init__(self, message: str, limit: str) -> None:
        super().__init__(message)
        self.message = message
        self.limit = limit


@dataclass(frozen=True)
class Usage:
    documents: int = 0
    chunks: int = 0
    storage_bytes: int = 0
    embedding_usd: float = 0.0
    cognify_usd: float = 0.0
    embedding_tokens: int = 0


def period_start(now: datetime | None = None) -> datetime:
    n = now or datetime.now(timezone.utc)
    return n.astimezone(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )


def _size(n: float) -> str:
    for unit, step in (("TB", 1024**4), ("GB", 1024**3), ("MB", 1024**2)):
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{int(n)} bytes"


def check(
    limits: Mapping[str, Any] | None,
    usage: Usage,
    *,
    add_documents: int = 0,
    add_chunks: int = 0,
    add_bytes: int = 0,
    add_embedding_usd: float = 0.0,
    add_cognify_usd: float = 0.0,
) -> None:
    """Raises when this addition would pass a limit, an empty limit never does."""
    if not limits:
        return

    def over(key: str, used: float, adding: float) -> bool:
        cap = limits.get(key)
        return cap is not None and adding > 0 and used + adding > float(cap)

    if over("max_documents", usage.documents, add_documents):
        raise KnowledgeQuotaExceeded(
            f"This workspace holds {usage.documents:,} documents and its limit is "
            f"{int(limits['max_documents']):,}. Delete some or ask for more. "
            f"{WHERE_TO_RAISE}",
            "max_documents",
        )
    if over("max_chunks", usage.chunks, add_chunks):
        raise KnowledgeQuotaExceeded(
            f"This document needs {add_chunks:,} chunks, the workspace holds "
            f"{usage.chunks:,} and its limit is {int(limits['max_chunks']):,}. "
            f"{WHERE_TO_RAISE}",
            "max_chunks",
        )
    if over("max_storage_bytes", usage.storage_bytes, add_bytes):
        raise KnowledgeQuotaExceeded(
            f"This workspace stores {_size(usage.storage_bytes)} of documents and its "
            f"limit is {_size(int(limits['max_storage_bytes']))}. {WHERE_TO_RAISE}",
            "max_storage_bytes",
        )
    if over("monthly_embedding_usd", usage.embedding_usd, add_embedding_usd):
        raise KnowledgeQuotaExceeded(
            f"Embedding has cost ${usage.embedding_usd:.2f} this month and the limit "
            f"is ${float(limits['monthly_embedding_usd']):.2f}. It resets on the 1st. "
            f"{WHERE_TO_RAISE}",
            "monthly_embedding_usd",
        )
    if over("monthly_cognify_usd", usage.cognify_usd, add_cognify_usd):
        raise KnowledgeQuotaExceeded(
            f"Building knowledge graphs has cost ${usage.cognify_usd:.2f} this month "
            f"and the limit is ${float(limits['monthly_cognify_usd']):.2f}. It resets "
            f"on the 1st. {WHERE_TO_RAISE}",
            "monthly_cognify_usd",
        )


LIMIT_KEYS = (
    "max_documents",
    "max_chunks",
    "max_storage_bytes",
    "monthly_embedding_usd",
    "monthly_cognify_usd",
)
