"""Scope gate — cheap pre-check before answering a question in a meeting."""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult
from engine.tools import _meeting_session as sessmod


class ScopeGateTool(BaseTool):
    name = "scope_gate"
    description = (
        "Check whether a meeting question is inside the user-declared "
        "topic allow-list. Returns {decision: 'answer'|'defer'|'decline', "
        "reason: str}. Call this BEFORE formulating an answer — if the "
        "decision is 'defer', call defer_to_human; if 'decline', call "
        "meeting_speak with a polite decline."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "string"},
            "question": {"type": "string", "minLength": 2},
        },
        "required": ["meeting_id", "question"],
    }

    def __init__(self, *, execution_id: str = ""):
        self._execution_id = execution_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        q = (arguments.get("question") or "").strip().lower()
        sess = sessmod.get(self._execution_id)
        (arguments.get("meeting_id") or "").strip()
        if not sess:
            commitment_markers = (
                "by friday",
                "by monday",
                "by tuesday",
                "by wednesday",
                "by thursday",
                "by next",
                "by end of",
                "can you commit",
                "will you ",
                "promise",
                "signed off",
                "approve ",
                "approved",
                "sign this",
                "authorize",
                "budget",
                "how much",
                "contract value",
                "pricing",
            )
            for m in commitment_markers:
                if m in q:
                    return ToolResult(
                        content=json.dumps(
                            {
                                "decision": "defer",
                                "reason": f"no_session_plus_commitment_shape:{m}",
                            }
                        ),
                        metadata={
                            "decision": "defer",
                            "matched": m,
                            "no_session": True,
                        },
                    )
            return ToolResult(
                content=json.dumps(
                    {
                        "decision": "answer",
                        "reason": "no_active_session_default_answer",
                        "hint": (
                            "No live session context available — the pod may have "
                            "restarted. Use persona_rag; if nothing relevant, "
                            "politely say you don't have specifics and offer to "
                            "follow up."
                        ),
                    }
                ),
                metadata={"decision": "answer", "no_session": True},
            )

        # Tokenize the question into words for keyword matching. Whole-
        # phrase substring matching ("candidate background" must appear
        # verbatim) was too strict — "what is your background?" never
        # matched any allow-list topic, so every question deferred.
        q_words = set(_tokenize(q))

        # Defer-list wins: these topics MUST always defer even if they
        # also happen to appear in the allow-list.
        for topic in sess.scope_defer:
            tw = set(_tokenize(topic))
            if topic.lower() in q or (tw & q_words):
                return ToolResult(
                    content=json.dumps(
                        {
                            "decision": "defer",
                            "reason": f"topic_in_defer_list:{topic}",
                        }
                    ),
                    metadata={"decision": "defer", "matched": topic},
                )

        for topic in sess.scope_allow:
            tw = set(_tokenize(topic))
            if topic.lower() in q or (tw & q_words):
                return ToolResult(
                    content=json.dumps(
                        {
                            "decision": "answer",
                            "reason": f"topic_in_allow_list:{topic}",
                        }
                    ),
                    metadata={"decision": "answer", "matched": topic},
                )

        # Commitment-shaped heuristics — ALWAYS defer
        commitment_markers = (
            "by friday",
            "by monday",
            "by tuesday",
            "by wednesday",
            "by thursday",
            "by next",
            "by end of",
            "can you commit",
            "will you ",
            "promise",
            "signed off",
            "approve ",
            "approved",
            "sign this",
            "authorize",
            "budget",
            "how much",
            "contract value",
            "pricing",
        )
        for m in commitment_markers:
            if m in q:
                return ToolResult(
                    content=json.dumps(
                        {
                            "decision": "defer",
                            "reason": f"commitment_shape:{m}",
                        }
                    ),
                    metadata={"decision": "defer", "matched": m},
                )

        return ToolResult(
            content=json.dumps(
                {
                    "decision": "answer",
                    "reason": "no_allow_match_default_answer",
                    "hint": (
                        "No allow-list topic matched the question, but it's also "
                        "not a defer-list topic or commitment. Try persona_rag "
                        "first; if no relevant context found, politely tell the "
                        "asker you don't have specifics on that topic."
                    ),
                }
            ),
            metadata={"decision": "answer"},
        )


# Stop-words that shouldn't count as "topic keywords" — otherwise every
# question containing "the" would match every allow-list topic that
# contains "the".
_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "of",
    "on",
    "in",
    "to",
    "for",
    "with",
    "your",
    "my",
    "our",
    "you",
    "i",
    "we",
    "this",
    "that",
    "these",
    "those",
    "what",
    "where",
    "when",
    "who",
    "why",
    "how",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "tell",
    "me",
    "us",
    "about",
}


def _tokenize(text: str) -> list[str]:
    """Split into lowercase content words, dropping stop-words + tokens"""
    import re

    return [
        w
        for w in re.findall(r"[a-z][a-z0-9]+", text.lower())
        if len(w) >= 3 and w not in _STOP
    ]
