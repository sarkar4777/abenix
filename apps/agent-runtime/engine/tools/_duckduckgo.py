"""DuckDuckGo search for the tools that work without a provider key."""

from __future__ import annotations

import asyncio
from typing import Any

# live runs show each engine answering empty for many real queries, so walk them
BACKENDS = {
    "text": ("duckduckgo", "yahoo", "brave", "startpage", "mojeek", "auto"),
    "news": ("duckduckgo", "bing", "yahoo"),
}
EMPTY_NOTE = (
    "The keyless search often answers empty, so this does not prove there are none."
)
_TIMEOUT_SECONDS = 10


class SearchFailed(Exception):
    pass


def _query(kind: str, query: str, max_results: int, backend: str) -> list[dict]:
    from ddgs import DDGS

    with DDGS(timeout=_TIMEOUT_SECONDS) as client:
        return getattr(client, kind)(query, max_results=max_results, backend=backend)


def _is_empty_answer(exc: Exception) -> bool:
    # ddgs reports an empty search by raising, with this message on its base exception
    return "no results found" in str(exc).lower()


async def search(kind: str, query: str, max_results: Any) -> list[dict]:
    """Rows from the first backend with any, empty if none, SearchFailed if all broke."""
    errors: list[str] = []
    answered = False
    for backend in BACKENDS[kind]:
        try:
            # the client is sync and blocks for seconds
            rows = await asyncio.to_thread(
                _query, kind, query, int(max_results), backend
            )
        except ImportError as exc:
            raise SearchFailed("the ddgs package is not installed") from exc
        except Exception as exc:
            if _is_empty_answer(exc):
                answered = True
            else:
                errors.append(f"{backend} backend said {exc}")
            continue
        if rows:
            return [dict(r, backend=backend) for r in rows]
        answered = True
    if answered:
        return []
    raise SearchFailed(". ".join(errors))
