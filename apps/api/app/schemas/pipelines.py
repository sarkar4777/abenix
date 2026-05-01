"""Schemas for pipeline execution API."""

from typing import Any

from pydantic import BaseModel, Field


class PipelineConditionSchema(BaseModel):
    source_node: str
    field: str
    operator: str = "eq"
    value: Any


class PipelineInputMappingSchema(BaseModel):
    source_node: str
    source_field: str = "__all__"


class ForEachConfigSchema(BaseModel):
    source_node: str
    source_field: str
    item_variable: str = "current_item"
    max_concurrency: int = Field(default=10, ge=1, le=50)


class SwitchCaseSchema(BaseModel):
    operator: str = "eq"
    value: Any
    target_node: str


class SwitchConfigSchema(BaseModel):
    source_node: str
    field: str
    cases: list[SwitchCaseSchema] = Field(default_factory=list)
    default_node: str | None = None


class MergeConfigSchema(BaseModel):
    mode: str = Field(default="append", pattern="^(append|zip|join)$")
    join_field: str | None = None
    source_nodes: list[str] = Field(default_factory=list)


class PipelineNodeSchema(BaseModel):
    id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    condition: PipelineConditionSchema | None = None
    input_mappings: dict[str, PipelineInputMappingSchema] = Field(default_factory=dict)
    max_retries: int = Field(default=0, ge=0, le=5)
    retry_delay_ms: int = Field(default=1000, ge=100, le=30000)
    for_each: ForEachConfigSchema | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    on_error: str = Field(default="stop", pattern="^(stop|continue|error_branch)$")
    error_branch_node: str | None = None
    switch: SwitchConfigSchema | None = None
    merge: MergeConfigSchema | None = None


class ExecutePipelineRequest(BaseModel):
    nodes: list[PipelineNodeSchema] = Field(..., min_length=1, max_length=50)
    context: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=120, ge=5, le=600)
    cost_limit: float | None = Field(default=None, ge=0.001, le=100.0)


class ExecuteSavedPipelineRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=120, ge=5, le=600)
