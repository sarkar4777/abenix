from __future__ import annotations

import json
import logging
import os
from typing import Any

from redisvl.extensions.cache.llm import SemanticCache as RVLSemanticCache
from redisvl.query.filter import Tag
from redisvl.utils.vectorize import OpenAITextVectorizer

logger = logging.getLogger(__name__)

TTL_SECONDS = 604800  # 7 days
SIMILARITY_THRESHOLD = 0.92
DISTANCE_THRESHOLD = 2 * (1 - SIMILARITY_THRESHOLD)  # 0.16 in Redis cosine [0-2]


class SemanticCache:
    def __init__(self, redis_url: str | None = None) -> None:
        url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        vectorizer = OpenAITextVectorizer(model="text-embedding-3-small")
        self._cache = RVLSemanticCache(
            name="abenix_semantic",
            redis_url=url,
            vectorizer=vectorizer,
            distance_threshold=DISTANCE_THRESHOLD,
            ttl=TTL_SECONDS,
            filterable_fields=[{"name": "agent_id", "type": "tag"}],
        )

    async def get(self, prompt: str, agent_id: str) -> dict[str, Any] | None:
        agent_filter = Tag("agent_id") == agent_id
        results = await self._cache.acheck(
            prompt=prompt,
            filter_expression=agent_filter,
        )
        if not results:
            return None

        top = results[0]
        raw = top.get("response", top.get("metadata", ""))
        if not raw:
            return None

        logger.debug(
            "semantic cache hit agent=%s dist=%.3f",
            agent_id,
            float(top.get("vector_distance", 0)),
        )
        if isinstance(raw, str):
            return json.loads(raw)
        return raw

    async def set(self, prompt: str, response: dict[str, Any], agent_id: str) -> None:
        await self._cache.astore(
            prompt=prompt,
            response=json.dumps(response, default=str),
            filters={"agent_id": agent_id},
        )

    async def close(self) -> None:
        pass
