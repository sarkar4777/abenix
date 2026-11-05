"""Which collections may be searched and where their live vectors sit."""

from __future__ import annotations

import logging
import uuid
from typing import Iterable

logger = logging.getLogger(__name__)


def pinecone_namespace(kb_id: str, generation: int = 0) -> str:
    # generation 0 keeps the namespace every existing collection already has
    return f"{kb_id}.g{generation}" if generation else str(kb_id)


def parse_namespace(namespace: str) -> tuple[str, int]:
    base, sep, gen = namespace.partition(".g")
    if sep and gen.isdigit():
        return base, int(gen)
    return namespace, 0


async def live_generations(kb_ids: Iterable[str]) -> dict[str, int] | None:
    """Generation per collection not being deleted, None when the database cannot say."""
    ids, passthrough = [], {}
    for k in kb_ids:
        try:
            ids.append(uuid.UUID(str(k)))
        except (ValueError, AttributeError):
            passthrough[str(k)] = 0
    if not ids:
        return passthrough
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession

        from engine.db_pool import shared_engine
        from engine.knowledge.hybrid_search import _async_db_url

        url = _async_db_url()
        if not url:
            return None
        async with AsyncSession(shared_engine(url)) as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id::text, embedding_generation "
                        "FROM knowledge_collections "
                        "WHERE id = ANY(:ids) AND deleted_at IS NULL"
                    ).bindparams(ids=ids)
                )
            ).all()
    except Exception as e:
        logger.warning("collection state lookup failed: %s", e)
        return None
    return {**passthrough, **{r[0]: int(r[1] or 0) for r in rows}}
