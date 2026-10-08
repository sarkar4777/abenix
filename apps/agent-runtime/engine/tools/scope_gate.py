"""Scope gate — cheap pre-check before answering a question in a meeting."""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult
from engine.tools import _meeting_session as sessmod


class ScopeGateTool(BaseTool):
    name = "scope_gate"
    risk_tier = "low"
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
        q = (arguments.get("question") or "").strip()
        sess = sessmod.get(self._execution_id)
        if not sess:
            hit = _commitment(q.lower())
            if hit:
                return ToolResult(
                    content=json.dumps(
                        {
                            "decision": "defer",
                            "reason": f"no_session_plus_commitment_shape:{hit}",
                        }
                    ),
                    metadata={"decision": "defer", "matched": hit, "no_session": True},
                )
            return ToolResult(
                content=json.dumps(
                    {
                        "decision": "answer",
                        "reason": "no_active_session_default_answer",
                        "hint": (
                            "No live session context available, the pod may have "
                            "restarted. Use persona_rag. If nothing relevant, "
                            "politely say you don't have specifics and offer to "
                            "follow up."
                        ),
                    }
                ),
                metadata={"decision": "answer", "no_session": True},
            )
        d = decide(q, sess.scope_allow, sess.scope_defer)
        return ToolResult(
            content=json.dumps({k: v for k, v in d.items() if k != "matched"}),
            metadata={"decision": d["decision"], "matched": d.get("matched")},
        )


COMMITMENT_MARKERS = (
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

SCOPE_LABEL = {
    "answer": "inside the topics you allowed",
    "defer": "hand back to you",
    "decline": "outside the topics you allowed, will decline",
}


def _commitment(q: str) -> str | None:
    return next((m for m in COMMITMENT_MARKERS if m in q), None)


def decide(question: str, allow: list[str], defer: list[str]) -> dict[str, Any]:
    """The scope rule: defer list and commitments hand back, allowed topics answer, the rest declines."""
    q = (question or "").strip().lower()
    q_words = set(_tokenize(q))
    for topic in defer or []:
        if topic.lower() in q or (set(_tokenize(topic)) & q_words):
            return {
                "decision": "defer",
                "reason": f"topic_in_defer_list:{topic}",
                "matched": topic,
            }
    hit = _commitment(q)
    if hit:
        return {
            "decision": "defer",
            "reason": f"commitment_shape:{hit}",
            "matched": hit,
        }
    for topic in allow or []:
        if topic.lower() in q or (set(_tokenize(topic)) & q_words):
            return {
                "decision": "answer",
                "reason": f"topic_in_allow_list:{topic}",
                "matched": topic,
            }
    # ring-fenced: anything the user did not authorize is politely declined
    return {
        "decision": "decline",
        "reason": "not_in_allow_list" if allow else "no_topics_authorized",
        "hint": (
            "The question is outside the topics the user authorized. "
            "Politely say you can't speak to that and offer to pass it on."
        ),
    }


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
