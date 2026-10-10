"""Keeps prompt and response content out of the logs.

ABENIX_LOG_LLM_CONTENT=1 logs full LLM request bodies again, for local debugging only.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from typing import Any

OPT_IN_ENV = "ABENIX_LOG_LLM_CONTENT"

# loggers that emit request bodies, filtered on the logger and on root handlers
SDK_LOGGERS = (
    "anthropic",
    "anthropic._base_client",
    "openai",
    "openai._base_client",
    "google_genai",
    "google_genai._api_client",
    "google.genai",
    "httpx",
    "httpcore",
)
_SDK_PREFIXES = tuple(n.split(".")[0] for n in SDK_LOGGERS) + ("google.genai",)
_BODY_KEYS = ("messages", "contents", "input", "prompt", "system")

logger = logging.getLogger(__name__)


def content_logging_enabled() -> bool:
    return os.environ.get(OPT_IN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _as_mapping(value: Any) -> Mapping | None:
    if isinstance(value, Mapping):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            out = dump()
        except Exception:
            return None
        return out if isinstance(out, Mapping) else None
    return None


def _body_of(value: Any) -> Mapping | None:
    m = _as_mapping(value)
    if m is None:
        return None
    inner = _as_mapping(m.get("json_data"))
    if inner is not None:
        return inner
    if any(k in m for k in _BODY_KEYS):
        return m
    return None


def _tool_name(tool: Any) -> str:
    t = _as_mapping(tool) or {}
    fn = _as_mapping(t.get("function")) or {}
    decls = t.get("function_declarations") or t.get("functionDeclarations")
    if decls:
        return ",".join(
            str((_as_mapping(d) or {}).get("name") or "?") for d in decls if d
        )
    return str(t.get("name") or fn.get("name") or t.get("type") or "?")


def summarize_request(body: Any) -> str:
    """Model, message count, token estimate and tool names. Never any content."""
    b = _body_of(body) or _as_mapping(body) or {}
    msgs = b.get("messages")
    if msgs is None:
        msgs = b.get("contents")
    if msgs is None:
        msgs = b.get("input")
    if isinstance(msgs, (list, tuple)):
        count = len(msgs)
    elif msgs:
        count = 1
    else:
        count = 0
    try:
        size = len(json.dumps(b, default=str))
    except Exception:
        size = len(str(b))
    tools = [_tool_name(t) for t in (b.get("tools") or [])]
    return "model=%s messages=%d est_tokens=%d tools=[%s]" % (
        b.get("model") or "?",
        count,
        size // 4,
        ",".join(tools),
    )


class LLMContentFilter(logging.Filter):
    """Rewrites SDK records that carry a request body into a summary."""

    def filter(self, record: logging.LogRecord) -> bool:
        if content_logging_enabled():
            return True
        if not record.name.startswith(_SDK_PREFIXES):
            return True
        args = record.args
        if isinstance(args, Mapping):
            args = (args,)
        if not isinstance(args, tuple):
            return True
        bodies = [a for a in args if _body_of(a) is not None]
        if bodies:
            record.msg = "LLM request %s"
            record.args = (summarize_request(bodies[0]),)
        return True


_FILTER = LLMContentFilter()


def install() -> None:
    """Attach the filter. Safe to call more than once."""
    for name in SDK_LOGGERS:
        lg = logging.getLogger(name)
        if _FILTER not in lg.filters:
            lg.addFilter(_FILTER)
    for h in logging.getLogger().handlers:
        if _FILTER not in h.filters:
            h.addFilter(_FILTER)
    if content_logging_enabled():
        logger.warning(
            "%s is on, LLM prompts and responses will be written to the logs. "
            "Use it for local debugging only.",
            OPT_IN_ENV,
        )
