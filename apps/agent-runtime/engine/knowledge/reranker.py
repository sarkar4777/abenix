"""Rerank hybrid-search candidates by relevance to the query.

Providers, picked by RERANKER_PROVIDER or the keys present:
  - `cohere` (automatic when `COHERE_API_KEY` is set) - `rerank-english-v3.0`
  - `llm`    (only when RERANKER_PROVIDER=llm) - Claude Haiku scores each hit
  - `none`   - passthrough

`build_citation` turns a chunk's metadata into a document / page / chunk anchor.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    document_id: str
    document_name: str | None = None
    page: int | None = None
    chunk_index: int | None = None
    char_offset_start: int | None = None
    char_offset_end: int | None = None
    anchor_url: str | None = None

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "document_name": self.document_name,
            "page": self.page,
            "chunk_index": self.chunk_index,
            "char_offset_start": self.char_offset_start,
            "char_offset_end": self.char_offset_end,
            "anchor_url": self.anchor_url,
        }


def _first(md: dict, *keys: str) -> Any:
    for k in keys:
        if md.get(k) is not None:
            return md[k]
    return None


def build_citation(
    metadata: dict | None, fallback_document_id: str | None = None
) -> Citation | None:
    if not metadata and not fallback_document_id:
        return None
    md = metadata or {}
    doc_id = md.get("document_id") or md.get("doc_id") or fallback_document_id
    if not doc_id:
        return None
    page = _first(md, "page", "page_number")
    chunk_index = _first(md, "chunk_index", "chunk_idx")
    char_start = _first(md, "char_offset_start", "offset_start")
    char_end = _first(md, "char_offset_end", "offset_end")
    document_name = md.get("document_name") or md.get("filename")
    parts = []
    if document_name:
        parts.append(document_name)
    if page is not None:
        parts.append(f"page {page}")
    if chunk_index is not None:
        parts.append(f"chunk {chunk_index}")
    anchor = " · ".join(parts) if parts else None
    return Citation(
        document_id=str(doc_id),
        document_name=document_name,
        page=page,
        chunk_index=chunk_index,
        char_offset_start=char_start,
        char_offset_end=char_end,
        anchor_url=anchor,
    )


def provider() -> str:
    explicit = os.environ.get("RERANKER_PROVIDER", "").strip().lower()
    if explicit in ("cohere", "llm", "none"):
        return explicit
    # the llm scorer adds a model call to every search, so it is opt-in
    if os.environ.get("COHERE_API_KEY", "").strip():
        return "cohere"
    return "none"


async def _rerank_cohere(
    query: str, documents: list[str], top_k: int
) -> list[tuple[int, float]] | None:
    try:
        import httpx
    except ImportError:
        return None
    api_key = os.environ.get("COHERE_API_KEY", "").strip()
    if not api_key:
        return None
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://api.cohere.com/v1/rerank",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "rerank-english-v3.0",
                "query": query,
                "documents": documents,
                "top_n": min(top_k, len(documents)),
            },
        )
        if r.status_code != 200:
            logger.warning("cohere rerank failed: %s", r.text[:200])
            return None
        data = r.json()
        return [
            (item["index"], item["relevance_score"]) for item in data.get("results", [])
        ]


async def _rerank_llm(
    query: str, documents: list[str], top_k: int
) -> list[tuple[int, float]] | None:
    # Lightweight scoring: ask Haiku for a 0-1 relevance per doc. Cheap.
    try:
        import json
        import httpx
    except ImportError:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    numbered = "\n\n".join(f"[{i}] {d[:600]}" for i, d in enumerate(documents))
    prompt = (
        f"Query: {query}\n\nDocuments:\n{numbered}\n\n"
        "Return ONLY a JSON array of objects "
        '[{"index": int, "score": float}], one per document, '
        "score in [0,1] for relevance. No prose."
    )
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        if r.status_code != 200:
            return None
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []))
        try:
            parsed = json.loads(text[text.find("[") : text.rfind("]") + 1])
            ranked = sorted(parsed, key=lambda x: x.get("score", 0), reverse=True)[
                :top_k
            ]
            return [(int(x["index"]), float(x["score"])) for x in ranked]
        except Exception:
            return None


async def rerank(
    query: str,
    items: list[dict[str, Any]],
    *,
    text_key: str = "content",
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Rerank `items` by relevance to `query`. Each item is a dict that
    contains text under `text_key` (and any other fields). Returns the
    top_k items, with `score` overwritten."""
    if not items:
        return items
    chosen = provider()
    if chosen == "none":
        return items[:top_k]
    documents = [str(it.get(text_key, "")) for it in items]
    ranked: list[tuple[int, float]] | None = None
    if chosen == "cohere":
        ranked = await _rerank_cohere(query, documents, top_k)
    if ranked is None and chosen == "llm":
        ranked = await _rerank_llm(query, documents, top_k)
    if ranked is None:
        return items[:top_k]
    out: list[dict[str, Any]] = []
    for idx, score in ranked:
        if 0 <= idx < len(items):
            row = dict(items[idx])
            row["score"] = score
            row["reranker"] = chosen
            out.append(row)
    return out


__all__ = ["rerank", "build_citation", "Citation", "provider"]
