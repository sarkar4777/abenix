"""Persona-scoped retrieval."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from engine.tools.base import BaseTool, ToolResult
from engine.tools import _meeting_session as sessmod

logger = logging.getLogger(__name__)


class PersonaRagTool(BaseTool):
    name = "persona_rag"
    description = (
        "Retrieve from the user's persona-scoped knowledge. Use this when "
        "the agent needs to answer AS the user (their meeting notes, "
        "action items, personal context). The agent can only access scopes "
        "explicitly authorized for the current meeting; any request for an "
        "unauthorized scope is denied. Returns text chunks with source "
        "citations — never unfiltered persona data."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string", "minLength": 2,
                "description": "What you're looking for, phrased as a question or topic.",
            },
            "scope": {
                "type": "string",
                "description": (
                    "Persona scope to query. Must be in the meeting's "
                    "pre-authorized scope list (or in the default 'self' scope). "
                    "Unknown / unauthorized scopes return an empty result with a "
                    "'scope_denied' flag."
                ),
                "default": "self",
            },
            "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 15},
            "meeting_id": {
                "type": "string",
                "description": (
                    "Optional — if set, the request must fit within this meeting's "
                    "authorized scopes."
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        *,
        kb_ids: list[str] | None = None,
        tenant_id: str = "",
        user_id: str = "",
        execution_id: str = "",
    ):
        self.kb_ids = kb_ids or []
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.execution_id = execution_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = (arguments.get("query") or "").strip()
        if not query:
            return ToolResult(content="query is required", is_error=True)

        scope = (arguments.get("scope") or "self").strip()
        top_k = int(arguments.get("top_k", 5))
        meeting_id = (arguments.get("meeting_id") or "").strip()

        # Scope check — must be in the meeting's authorized list if meeting_id provided
        if meeting_id:
            sess = sessmod.get(self.execution_id)
            allowed = (sess.persona_scopes if sess else []) or []
            # 'self' is implicit for anyone with tenant access
            if scope != "self" and scope not in allowed:
                return ToolResult(
                    content=json.dumps({
                        "scope_denied": True,
                        "requested_scope": scope,
                        "allowed_scopes": ["self", *allowed],
                        "hint": (
                            "This meeting is not authorized to query that persona "
                            "scope. Authorize it in /meetings/<id>/authorize."
                        ),
                    }),
                    is_error=True,
                    metadata={"scope_denied": True},
                )

        results = await _persona_vector_search(
            query=query, kb_ids=self.kb_ids, tenant_id=self.tenant_id,
            user_id=self.user_id, scope=scope, top_k=top_k,
        )
        return ToolResult(
            content=json.dumps(
                {
                    "scope": scope,
                    "query": query,
                    "results": [
                        {
                            "text": r["text"][:2000],
                            "score": r["score"],
                            "source": r.get("source", ""),
                            "doc_id": r.get("doc_id", ""),
                        }
                        for r in results
                    ],
                    "count": len(results),
                }
            ),
            metadata={"count": len(results), "scope": scope},
        )


async def _persona_vector_search(
    *,
    query: str,
    kb_ids: list[str],
    tenant_id: str,
    user_id: str,
    scope: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """Pinecone query with hard metadata filter — tenant + user + persona scope."""
    try:
        from openai import AsyncOpenAI
        from pinecone import Pinecone
    except ImportError:
        return []
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    pinecone_key = os.environ.get("PINECONE_API_KEY", "").strip()
    index_name = os.environ.get("PINECONE_INDEX_NAME", "abenix-knowledge")
    if not (api_key and pinecone_key):
        return []

    client = AsyncOpenAI(api_key=api_key)
    try:
        emb = await client.embeddings.create(model="text-embedding-3-small", input=query)
        vec = emb.data[0].embedding
    except Exception as e:
        logger.warning("persona_rag: embed failed: %s", e)
        return []

    pc = Pinecone(api_key=pinecone_key)
    index = pc.Index(index_name)

    # Hard filter — if Pinecone doesn't receive all required fields the
    # chunk cannot match, which is exactly what we want for ring-fencing.
    flt: dict[str, Any] = {
        "persona_scope": {"$eq": scope},
        "tenant_id": {"$eq": tenant_id},
    }
    if scope == "self":
        flt["user_id"] = {"$eq": user_id}

    results: list[dict[str, Any]] = []
    # Persona namespace per tenant so a mis-filter still can't cross tenants.
    namespace = f"persona:{tenant_id}"
    try:
        resp = index.query(
            namespace=namespace, vector=vec, top_k=top_k,
            include_metadata=True, filter=flt,
        )
    except Exception as e:
        logger.warning("persona_rag: pinecone query failed: %s", e)
        return []

    matches = getattr(resp, "matches", None) or (
        resp.get("matches", []) if isinstance(resp, dict) else []
    )
    for m in matches:
        meta = getattr(m, "metadata", None) or (
            m.get("metadata", {}) if isinstance(m, dict) else {}
        ) or {}
        # Defense-in-depth: re-verify the filter held (Pinecone bugs have
        # returned mis-filtered results before in certain index versions).
        if meta.get("tenant_id") != tenant_id:
            continue
        if meta.get("persona_scope") != scope:
            continue
        if scope == "self" and meta.get("user_id") != user_id:
            continue
        score = getattr(m, "score", None) or (
            m.get("score", 0.0) if isinstance(m, dict) else 0.0
        )
        results.append(
            {
                "text": meta.get("text", "") or "",
                "score": float(score),
                "source": meta.get("filename", ""),
                "doc_id": meta.get("doc_id", ""),
            }
        )
    results.sort(key=lambda r: r["score"], reverse=True)
    return results
