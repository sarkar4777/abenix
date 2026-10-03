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
