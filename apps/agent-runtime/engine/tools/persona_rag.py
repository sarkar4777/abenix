"""Persona-scoped retrieval from the executing user's own persona items."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from engine import credentials
from engine.tools.base import BaseTool, ConfigField, ToolResult
from engine.tools import _meeting_session as sessmod

logger = logging.getLogger(__name__)


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("ASYNC_DATABASE_URL") or ""
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _error(message: str, **meta: Any) -> ToolResult:
    return ToolResult(
        content=json.dumps({"error": message, **meta}),
        is_error=True,
        metadata={"persona_error": True, **meta},
    )


class PersonaRagTool(BaseTool):
    name = "persona_rag"
    risk_tier = "low"
    config_fields = (
        ConfigField(
            "OPENAI_API_KEY",
            label="API key",
            kind="secret",
            required=False,
            group="OpenAI",
            description=(
                "Semantic embeddings for persona search. Without it persona items "
                "are indexed with the built-in lexical embedder."
            ),
            signup_url="https://platform.openai.com/api-keys",
        ),
    )
    description = (
        "Retrieve from the executing user's own persona knowledge. Use this when "
        "the agent needs to answer AS the user (their notes, files, meeting "
        "context). Only the user's own items are ever searched. Inside a meeting "
        "only the scopes authorized for that meeting are allowed, and any other "
        "scope is denied. Returns text chunks with source citations."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "minLength": 2,
                "description": "What you're looking for, phrased as a question or topic.",
            },
            "scope": {
                "type": "string",
                "description": (
                    "Persona scope to query, for example 'self' or 'client:acme'. "
                    "In a meeting it must be one of the meeting's authorized "
                    "scopes, otherwise the result carries 'scope_denied'."
                ),
                "default": "self",
            },
            "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 15},
            "meeting_id": {
                "type": "string",
                "description": (
                    "Optional. The meeting this lookup is for. A meeting bound to "
                    "this run is enforced whether or not this is set."
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
        self.tenant_id = str(tenant_id or "")
        self.user_id = str(user_id or "")
        self.execution_id = execution_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            return await self._run(arguments)
        except Exception as e:  # noqa: BLE001
            logger.exception("persona_rag failed")
            return _error(
                f"persona search is unavailable right now ({str(e)[:200] or type(e).__name__}). "
                "Tell the user their persona knowledge could not be searched."
            )

    async def _run(self, arguments: dict[str, Any]) -> ToolResult:
        query = (arguments.get("query") or "").strip()
        if not query:
            return ToolResult(content="query is required", is_error=True)
        scope = (arguments.get("scope") or "self").strip() or "self"
        try:
            top_k = max(1, min(15, int(arguments.get("top_k", 5))))
        except (TypeError, ValueError):
            top_k = 5
        meeting_id = (arguments.get("meeting_id") or "").strip()

        sess = sessmod.get(self.execution_id) if self.execution_id else None
        owner = self.user_id or (str(sess.user_id) if sess and sess.user_id else "")
        if not owner or not self.tenant_id:
            return _error(
                "persona search needs the executing user, and this run has none. "
                "Persona knowledge is only searchable in a run started by a signed-in user."
            )
        if sess and sess.user_id and str(sess.user_id) != owner:
            return _error("this meeting belongs to another user", scope_denied=True)

        # a meeting bound to this run limits scopes, with or without meeting_id
        if sess is not None or meeting_id:
            allowed = list((sess.persona_scopes if sess else []) or [])
            if scope != "self" and scope not in allowed:
                return ToolResult(
                    content=json.dumps(
                        {
                            "scope_denied": True,
                            "requested_scope": scope,
                            "allowed_scopes": ["self", *allowed],
                            "hint": (
                                "This meeting is not authorized to query that persona "
                                "scope. Authorize it on the meeting page."
                            ),
                        }
                    ),
                    is_error=True,
                    metadata={"scope_denied": True},
                )

        db_url = _db_url()
        if not db_url:
            return _error("persona search has no database configured (DATABASE_URL)")

        import persona_vectors as pv
        from engine.db_pool import shared_engine

        results, notes = await pv.search(
            shared_engine(db_url),
            tenant_id=self.tenant_id,
            user_id=owner,
            scope=scope,
            query=query,
            top_k=top_k,
            openai_key=credentials.get("OPENAI_API_KEY"),
        )
        payload: dict[str, Any] = {
            "scope": scope,
            "query": query,
            "results": [
                {
                    "text": r["text"][:2000],
                    "score": round(r["score"], 4),
                    "source": r.get("source") or r.get("title") or "",
                    "title": r.get("title", ""),
                    "doc_id": r.get("doc_id", ""),
                }
                for r in results
            ],
            "count": len(results),
        }
        if notes:
            payload["warnings"] = notes
        return ToolResult(
            content=json.dumps(payload),
            metadata={"count": len(results), "scope": scope},
        )
