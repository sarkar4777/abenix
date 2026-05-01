from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from abenix_sdk.agent import AgentDefinition


class AgentConfig(BaseModel):
    """Load and validate agent configuration from YAML files."""

    agents: list[AgentDefinition] = []

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AgentConfig":
        """Load agent configuration from a YAML file."""
        with open(path) as f:
            data: dict[str, Any] = yaml.safe_load(f)
        return cls(**data)
