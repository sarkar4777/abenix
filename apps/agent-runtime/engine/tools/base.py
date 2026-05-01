from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict[str, Any]

    @abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        ...

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class _DefaultedTool(BaseTool):
    """Transparent wrapper that HIDES pre-configured parameter keys"""

    def __init__(
        self,
        inner: BaseTool,
        defaults: dict[str, Any] | None = None,
        asset_input_schema: dict[str, Any] | None = None,
    ) -> None:
        self._inner = inner
        self._defaults = defaults or {}
        self.name = inner.name
        # Build a filtered schema that removes pre-set keys.
        props = dict((inner.input_schema or {}).get("properties") or {})
        required = list((inner.input_schema or {}).get("required") or [])
        hidden: list[str] = []
        for k in list(self._defaults.keys()):
            if k in props:
                props.pop(k)
                hidden.append(k)
            if k in required:
                required.remove(k)
        # If the caller provided a richer schema for the `input` field
        # (from upload-time discovery), inline it so the LLM knows the
        # exact shape to produce.
        if asset_input_schema and "input" in props:
            props["input"] = {**asset_input_schema, "description": props["input"].get("description", "")}
        self.input_schema = {
            **(inner.input_schema or {}),
            "properties": props,
            "required": required,
        }
        # Annotate the description so the LLM understands which fields
        # are auto-filled (purely informational — doesn't affect dispatch).
        extra = f" (pre-configured: {', '.join(hidden)})" if hidden else ""
        self.description = (inner.description or "") + extra

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        # Merge defaults back in. LLM-supplied args WIN if the LLM
        # somehow decided to override — being permissive so pipelines
        # that hand-craft args still work.
        merged = {**self._defaults, **(arguments or {})}
        return await self._inner.execute(merged)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_all(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def apply_tool_config(
        self,
        tool_config: dict[str, dict[str, Any]] | None,
        asset_schemas: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Wrap every tool that has parameter_defaults (or an asset-"""
        if not tool_config and not asset_schemas:
            return
        tool_config = tool_config or {}
        asset_schemas = asset_schemas or {}
        for name, tool in list(self._tools.items()):
            tc = tool_config.get(name) or {}
            defaults = tc.get("parameter_defaults") or {}
            asset_schema = (asset_schemas.get(name) or {}).get("input_schema")
            if not defaults and not asset_schema:
                continue
            self._tools[name] = _DefaultedTool(tool, defaults=defaults, asset_input_schema=asset_schema)
