"""Pydantic schemas for Knowledge Engine API endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class CognifyRequest(BaseModel):
    doc_ids: list[str] | None = None
    # empty picks the platform's cheap default, COGNIFY_DEFAULT_MODEL
    model: str = ""
    chunk_size: int = Field(default=1000, ge=200, le=4000)
    chunk_overlap: int = Field(default=200, ge=0, le=1000)
    force: bool = False
    dry_run: bool = False
    max_cost_usd: float | None = Field(default=None, ge=0)
    selection: Literal["all", "sample", "salient"] = "all"
    sample_rate: float = Field(default=1.0, gt=0, le=1)
    max_chunks_per_doc: int | None = Field(default=None, ge=1)
    max_parallel_chunks: int | None = Field(default=None, ge=1, le=64)
    requests_per_minute: float | None = Field(default=None, gt=0)
    tokens_per_minute: float | None = Field(default=None, gt=0)
    llm_resolution: bool = True


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
