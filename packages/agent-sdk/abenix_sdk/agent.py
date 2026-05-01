from typing import Any

from pydantic import BaseModel


class ToolDefinition(BaseModel):
    """Definition of a tool available to an agent."""

    name: str
    description: str
    input_schema: dict[str, Any]


class AgentDefinition(BaseModel):
    """Definition of an Abenix agent."""

    name: str
    description: str
    model: str = "claude-sonnet-4-20250514"
    system_prompt: str = ""
    tools: list[ToolDefinition] = []
    max_iterations: int = 10
    temperature: float = 0.7
    metadata: dict[str, Any] = {}
