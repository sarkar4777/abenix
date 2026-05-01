from __future__ import annotations

from pydantic import BaseModel, Field


class ConnectMCPRequest(BaseModel):
    server_name: str = Field(min_length=1, max_length=255)
    server_url: str = Field(min_length=1, max_length=1000)
    auth_type: str = "none"
    auth_config: dict | None = None


class UpdateMCPConnectionRequest(BaseModel):
    server_name: str | None = Field(default=None, min_length=1, max_length=255)
    auth_type: str | None = None
    auth_config: dict | None = None
    is_enabled: bool | None = None


class AttachMCPToolRequest(BaseModel):
    mcp_connection_id: str
    tool_name: str
    tool_config: dict | None = None
    approval_required: bool = False
    max_calls_per_execution: int | None = None


class DetachMCPToolRequest(BaseModel):
    tool_name: str
    mcp_connection_id: str


class OAuth2StartRequest(BaseModel):
    connection_id: str
    redirect_uri: str = Field(min_length=1, max_length=1000)


class OAuth2CallbackRequest(BaseModel):
    connection_id: str
    code: str
    state: str
    code_verifier: str


class DiscoverURLRequest(BaseModel):
    server_url: str = Field(min_length=1, max_length=1000)
    auth_type: str = "none"
    auth_config: dict | None = None


class ReadResourceRequest(BaseModel):
    uri: str


class GetPromptRequest(BaseModel):
    name: str
    arguments: dict[str, str] = Field(default_factory=dict)


class RegistryInstallRequest(BaseModel):
    registry_id: str
    server_name: str = Field(min_length=1, max_length=255)
