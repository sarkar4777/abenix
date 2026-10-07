"""Persona chunk store in the platform Postgres.

The API writes chunks here and the persona_rag tool reads them. Every read is
filtered on tenant, owner and scope, so one user can never retrieve another
user's persona items. Vectors are stored as real[] and compared with pgvector
by casting at query time, with a Python cosine fallback when the extension is
missing, so a fresh install works with no Pinecone and no extension.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
EMBED_BATCH = 100
MAX_TEXT_CHARS = 1_000_000
# rows pulled for the Python fallback, persona sets are small per owner
FALLBACK_ROW_CAP = 5000


class PersonaIndexError(Exception):
    """Indexing could not finish. The message is shown to the user as is."""


def chunk_text(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]
    out: list[str] = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for i in range(0, len(text), step):
        piece = text[i : i + CHUNK_SIZE]
        if piece.strip():
            out.append(piece)
        if i + CHUNK_SIZE >= len(text):
            break
    return out


def local_model_id() -> str:
    try:
        from local_embeddings import MODEL_ID

        return MODEL_ID
    except ImportError:
        return "local-hashing-v1"


def _azure() -> tuple[str, str]:
    key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    endpoint = (
        os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        or os.environ.get("AZURE_OPENAI_API_BASE", "")
    ).rstrip("/")
    for suffix in ("/openai/deployments", "/openai"):
        if endpoint.endswith(suffix):
            endpoint = endpoint[: -len(suffix)]
    return key, endpoint.rstrip("/")


def _names() -> tuple[str, str, dict]:
    try:
        import embedding_models as em

        return (
            em.provider_model(None),
            em.azure_deployment(None),
            em.request_kwargs(None),
        )
    except ImportError:
        name = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        return name, os.environ.get("AZURE_EMBEDDING_DEPLOYMENT", name), {}


def provider_configured(openai_key: str | None = None) -> bool:
    key = openai_key if openai_key is not None else os.environ.get("OPENAI_API_KEY", "")
    az_key, az_end = _azure()
    return bool((az_key and az_end) or (key or "").strip())


def default_model(openai_key: str | None = None) -> str:
    """The embedder new chunks get: the provider model when a key is set, else local."""
    forced = os.environ.get("ABENIX_LOCAL_EMBEDDINGS", "").strip().lower()
    if forced in {"1", "true", "yes"}:
        return local_model_id()
    if provider_configured(openai_key):
        return _names()[0]
    return local_model_id()


async def embed_texts(
    texts: list[str], model: str, *, openai_key: str | None = None
) -> list[list[float]]:
    """Embed in batches of EMBED_BATCH. Raises PersonaIndexError with a readable reason."""
    if not texts:
        return []
    if model == local_model_id():
        try:
            from local_embeddings import embed_many
        except ImportError as e:
            raise PersonaIndexError("the local embedder is not installed") from e
        return await asyncio.to_thread(embed_many, texts)

    openai_name, deployment, extra = _names()
    key = (
        openai_key if openai_key is not None else os.environ.get("OPENAI_API_KEY", "")
    ).strip()
    az_key, az_end = _azure()
    errors: list[str] = []
    if az_key and az_end and model == openai_name:
        try:
            from openai import AsyncAzureOpenAI

            client = AsyncAzureOpenAI(
                api_key=az_key,
                azure_endpoint=az_end,
                api_version=os.environ.get(
                    "AZURE_OPENAI_API_VERSION", "2024-10-01-preview"
                ),
            )
            return await _batched(client, texts, deployment, extra)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Azure OpenAI: {_short(e)}")
    if key:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=key)
            return await _batched(client, texts, model, extra)
        except Exception as e:  # noqa: BLE001
            errors.append(f"OpenAI: {_short(e)}")
    if not errors:
        raise PersonaIndexError(
            f"no embedding provider is configured for {model}, set OPENAI_API_KEY"
        )
    raise PersonaIndexError("embedding failed, " + "; ".join(errors))


async def _batched(
    client: Any, texts: list[str], model: str, extra: dict
) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        resp = await client.embeddings.create(
            model=model, input=texts[i : i + EMBED_BATCH], **extra
        )
        out.extend(d.embedding for d in resp.data)
    if len(out) != len(texts):
        raise PersonaIndexError(
            f"the embedding provider returned {len(out)} vectors for {len(texts)} chunks"
        )
    return out


def _short(e: Exception) -> str:
    body = getattr(e, "body", None)
    if isinstance(body, dict) and body.get("message"):
        status = getattr(e, "status_code", "")
        return f"{status} {body['message']}".strip()[:300]
    msg = str(e).strip() or type(e).__name__
    return msg[:300]


async def write_chunks(
    session: Any,
    *,
    item_id: uuid.UUID,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    persona_scope: str,
    chunks: list[str],
    vectors: list[list[float]],
    model: str,
) -> int:
    """Replace an item's chunks. The caller commits."""
    from sqlalchemy import delete

    from models.persona_chunk import PersonaChunk

    await session.execute(delete(PersonaChunk).where(PersonaChunk.item_id == item_id))
    for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
        session.add(
            PersonaChunk(
                id=uuid.uuid4(),
                item_id=item_id,
                tenant_id=tenant_id,
                user_id=user_id,
                persona_scope=persona_scope,
                chunk_index=i,
                content=chunk,
                embedding=[float(x) for x in vec],
                embedding_model=model,
            )
        )
    return len(chunks)


# owner, tenant and scope are checked on the chunk and on its item
_OWNER_WHERE = """
FROM persona_chunks c
JOIN persona_items i ON i.id = c.item_id
WHERE c.tenant_id = :t AND c.user_id = :u AND c.persona_scope = :s
  AND i.tenant_id = :t AND i.user_id = :u AND i.persona_scope = :s
  AND i.deleted_at IS NULL AND i.status = 'indexed'
"""

GROUPS_SQL = (
    "SELECT c.embedding_model, count(*) " + _OWNER_WHERE + "GROUP BY c.embedding_model"
)

VECTOR_SQL = (
    "SELECT c.content, i.title, i.source, i.id::text, c.chunk_index, "
    "1 - (CAST(c.embedding AS vector) <=> CAST(:emb AS vector)) AS score "
    + _OWNER_WHERE
    + "AND c.embedding_model = :m "
    "ORDER BY CAST(c.embedding AS vector) <=> CAST(:emb AS vector) LIMIT :k"
)

FALLBACK_SQL = (
    "SELECT c.content, i.title, i.source, i.id::text, c.chunk_index, c.embedding "
    + _OWNER_WHERE
    + "AND c.embedding_model = :m LIMIT :cap"
)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _row(r: Any, score: float) -> dict[str, Any]:
    return {
        "text": r[0] or "",
        "title": r[1] or "",
        "source": r[2] or "",
        "doc_id": r[3],
        "chunk_index": r[4],
        "score": float(score),
    }


async def search(
    engine: Any,
    *,
    tenant_id: str,
    user_id: str,
    scope: str,
    query: str,
    top_k: int = 5,
    openai_key: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Top chunks owned by user_id in scope. Returns (results, notes about anything skipped)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    t, u = uuid.UUID(str(tenant_id)), uuid.UUID(str(user_id))
    base = {"t": t, "u": u, "s": scope}
    notes: list[str] = []
    results: list[dict[str, Any]] = []
    async with AsyncSession(engine) as session:
        groups = (await session.execute(text(GROUPS_SQL), base)).all()
    for model, count in groups:
        try:
            qvec = (await embed_texts([query], model, openai_key=openai_key))[0]
        except PersonaIndexError as e:
            notes.append(f"{count} chunks embedded with {model} were skipped: {e}")
            continue
        params = {**base, "m": model}
        try:
            emb = "[" + ",".join(f"{x:.7f}" for x in qvec) + "]"
            async with AsyncSession(engine) as session:
                rows = (
                    await session.execute(
                        text(VECTOR_SQL), {**params, "emb": emb, "k": top_k}
                    )
                ).all()
            results.extend(_row(r, r[5]) for r in rows)
        except Exception as e:  # noqa: BLE001
            logger.info("persona search without pgvector (%s), using python cosine", e)
            async with AsyncSession(engine) as session:
                rows = (
                    await session.execute(
                        text(FALLBACK_SQL), {**params, "cap": FALLBACK_ROW_CAP}
                    )
                ).all()
            scored = [(r, cosine(qvec, list(r[5] or []))) for r in rows]
            scored.sort(key=lambda x: x[1], reverse=True)
            results.extend(_row(r, s) for r, s in scored[:top_k])
    # a zero or NaN score shares nothing with the query
    results = [r for r in results if r["score"] > 0]
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k], notes


async def store_status(engine: Any) -> dict[str, Any]:
    """Whether the chunk table exists and pgvector is installed."""
    from sqlalchemy import text

    out: dict[str, Any] = {"table": False, "pgvector": False}
    try:
        async with engine.connect() as conn:
            out["table"] = bool(
                (
                    await conn.execute(
                        text("SELECT to_regclass('persona_chunks') IS NOT NULL")
                    )
                ).scalar()
            )
            out["pgvector"] = bool(
                (
                    await conn.execute(
                        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                    )
                ).scalar()
            )
    except Exception as e:  # noqa: BLE001
        out["error"] = _short(e)
    return out
