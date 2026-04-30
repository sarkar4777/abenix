from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class AgentConfig(BaseModel):
    """Configuration for an agent loaded from YAML."""

    name: str
    description: str
    model: str = "claude-sonnet-4-20250514"
    system_prompt: str = ""
    tools: list[str] = []
    max_iterations: int = 10
    temperature: float = 0.7


class BaseAgent(ABC):
    """Base class for all Abenix agents."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    @abstractmethod
    async def invoke(self, input_message: str, context: dict[str, Any] | None = None) -> str:
        """Execute the agent with the given input."""
        ...

    @abstractmethod
    async def stream(self, input_message: str, context: dict[str, Any] | None = None):
        """Stream the agent's response."""
        ...
