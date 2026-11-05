"""Embedding models a collection can be indexed with.

Every one of them yields 1536 floats, the width of the pgvector column and the
Pinecone index, so a collection can switch between them by re-embedding with no
schema change. Lives in packages/db because the worker, the agent runtime and
the API all need the same list.
"""

from __future__ import annotations

import os

DIM = 1536
DEFAULT = "text-embedding-3-small"
LOCAL = "local-hashing-v1"

# extra request arguments per provider model
_PROVIDER = {
    "text-embedding-3-small": {},
    "text-embedding-3-large": {"dimensions": DIM},
    "text-embedding-ada-002": {},
}

SUPPORTED = (*_PROVIDER, LOCAL)


def is_supported(model: str | None) -> bool:
    return (model or "") in SUPPORTED


def is_local(model: str | None) -> bool:
    return model == LOCAL


def provider_model(model: str | None) -> str:
    """The OpenAI model name to call. The column default means the env default."""
    env_default = os.environ.get("OPENAI_EMBEDDING_MODEL", DEFAULT)
    if not model or model == DEFAULT:
        return env_default
    return model


def azure_deployment(model: str | None) -> str:
    """Azure deployment name: the configured one for the env default, else the model name."""
    name = provider_model(model)
    if name == os.environ.get("OPENAI_EMBEDDING_MODEL", DEFAULT):
        return os.environ.get("AZURE_EMBEDDING_DEPLOYMENT", name)
    return name


def request_kwargs(model: str | None) -> dict:
    return dict(_PROVIDER.get(provider_model(model), {}))


# list price per million tokens, a tenant's spend limit works from these
_USD_PER_MTOK = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
    LOCAL: 0.0,
}


def estimated_cost(model: str | None, texts: list[str]) -> tuple[int, float]:
    """(tokens, usd) at about four characters a token, providers bill close to this."""
    tokens = sum(len(t) for t in texts) // 4
    rate = _USD_PER_MTOK.get(provider_model(model), _USD_PER_MTOK[DEFAULT])
    if is_local(model):
        rate = 0.0
    return tokens, tokens / 1_000_000 * rate
