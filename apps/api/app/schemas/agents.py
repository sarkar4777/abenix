from typing import Any

from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    message: str
    stream: bool = True
    context: dict[str, Any] | None = None  # Input variables for pipelines and agents
    wait: bool = False
    wait_timeout_seconds: int = Field(default=180, ge=5, le=1800)


class ModelConfigSchema(BaseModel):
    """Agent model configuration. Core fields are typed; extra fields (tool_config,
    input_variables, mode, pipeline_config, mcp_extensions, etc.) are preserved as-is."""
    model: str = "claude-sonnet-4-5-20250929"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    tools: list[str] = []
    max_tokens: int = Field(default=4096, ge=1, le=64000)

    model_config = {"extra": "allow"}


class CreateAgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    system_prompt: str = ""
    agent_model_config: ModelConfigSchema = Field(
        default_factory=ModelConfigSchema, alias="model_config"
    )
    category: str | None = None
    icon_url: str | None = None

    model_config = {"populate_by_name": True}


class UpdateAgentRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    system_prompt: str | None = None
    agent_model_config: ModelConfigSchema | None = Field(default=None, alias="model_config")
    category: str | None = None
    icon_url: str | None = None
    status: str | None = None
    version: str | None = None

    model_config = {"populate_by_name": True}


class AgentResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    system_prompt: str
    model_config_: dict = {}
    agent_type: str
    status: str
    version: str
    icon_url: str | None = None
    category: str | None = None
    creator_id: str
    tenant_id: str

    model_config = {"from_attributes": True}


class PublishAgentRequest(BaseModel):
    marketplace_price: float | None = None
    category: str | None = None
    visibility: str | None = None  # "tenant" | "specific" | "public"


class ReviewAgentRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    reason: str | None = None
