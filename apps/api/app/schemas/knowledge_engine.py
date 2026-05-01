"""Pydantic schemas for Knowledge Engine API endpoints."""

from pydantic import BaseModel, Field


class CognifyRequest(BaseModel):
    doc_ids: list[str] | None = None
    model: str = "claude-sonnet-4-5-20250929"
    chunk_size: int = Field(default=1000, ge=200, le=4000)
    chunk_overlap: int = Field(default=200, ge=0, le=1000)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: str = Field(default="hybrid")  # "vector" | "graph" | "hybrid"
    top_k: int = Field(default=5, ge=1, le=50)
    graph_depth: int = Field(default=2, ge=1, le=4)


class FeedbackRequest(BaseModel):
    execution_id: str | None = None
    query: str
    result_entity_ids: list[str] = []
    result_chunk_ids: list[str] = []
    search_mode: str = "hybrid"
    rating: int = Field(ge=-1, le=1)  # -1 (bad), 0 (neutral), 1 (good)
    comment: str | None = None
