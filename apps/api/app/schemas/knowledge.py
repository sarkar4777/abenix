import sys
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from chunks_store import SEARCH_LANGUAGES


def _known_language(value: str | None) -> str | None:
    if value is not None and value not in SEARCH_LANGUAGES:
        raise ValueError(
            f"search_language must be one of {', '.join(SEARCH_LANGUAGES)}"
        )
    return value


class CreateKnowledgeBaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    agent_id: str | None = None
    chunk_size: int = Field(default=1000, ge=100, le=4000)
    chunk_overlap: int = Field(default=200, ge=0, le=1000)
    # v2: optional project + visibility. Both have safe defaults so v1
    # callers (Mideast Tourism, ContractIQ) keep working unchanged until
    # they're cut over in Phase 2.
    project_id: str | None = None
    default_visibility: str | None = Field(
        default=None,
        pattern="^(private|project|tenant)$",
    )
    vector_backend: str | None = Field(
        default=None,
        pattern="^(pinecone|pgvector)$",
    )
    search_language: str | None = None
    rerank_mode: str | None = Field(default=None, pattern="^(auto|off)$")
    # deferred skips the vector index during a bulk load, build it when loaded
    index_mode: str | None = Field(default=None, pattern="^(shared|deferred)$")

    _language = field_validator("search_language")(_known_language)


class UpdateKnowledgeBaseRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    agent_id: str | None = None
    project_id: str | None = None
    default_visibility: str | None = Field(
        default=None,
        pattern="^(private|project|tenant)$",
    )
    search_language: str | None = None
    rerank_mode: str | None = Field(default=None, pattern="^(auto|off)$")
    index_mode: str | None = Field(default=None, pattern="^deferred$")

    _language = field_validator("search_language")(_known_language)
