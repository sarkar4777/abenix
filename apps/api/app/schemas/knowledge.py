from pydantic import BaseModel, Field


class CreateKnowledgeBaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    agent_id: str | None = None
    chunk_size: int = Field(default=1000, ge=100, le=4000)
    chunk_overlap: int = Field(default=200, ge=0, le=1000)
    # v2: optional project + visibility. Both have safe defaults so v1
    # callers (Saudi Tourism, the example app) keep working unchanged until
    # they're cut over in Phase 2.
    project_id: str | None = None
    default_visibility: str | None = Field(
        default=None, pattern="^(private|project|tenant)$",
    )
    vector_backend: str | None = Field(
        default=None, pattern="^(pinecone|pgvector)$",
    )


class UpdateKnowledgeBaseRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    agent_id: str | None = None
    project_id: str | None = None
    default_visibility: str | None = Field(
        default=None, pattern="^(private|project|tenant)$",
    )
