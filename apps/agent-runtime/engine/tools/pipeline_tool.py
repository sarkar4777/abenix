"""Pipeline-as-Tool — wraps a saved pipeline agent as a callable tool for agents."""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class PipelineAgentTool(BaseTool):
    """Wraps a saved pipeline agent so it can be invoked as a tool by LLM agents."""

    def __init__(
        self,
        agent_name: str,
        agent_description: str,
        pipeline_config: dict[str, Any],
        tool_registry: Any,
        timeout_seconds: int = 120,
    ) -> None:
        self.name = f"pipeline:{agent_name}"
        self.description = (
            f"Execute the '{agent_name}' pipeline. {agent_description} "
            f"Pass input as a JSON context object with relevant data."
        )
        self.input_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "context": {
                    "type": "object",
                    "description": f"Input context for the {agent_name} pipeline. Include relevant data fields.",
                    "default": {},
                },
                "message": {
                    "type": "string",
                    "description": "Primary input message or query for the pipeline",
                    "default": "",
                },
            },
        }
        self._pipeline_config = pipeline_config
        self._tool_registry = tool_registry
        self._timeout_seconds = timeout_seconds

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from engine.pipeline import PipelineExecutor, parse_pipeline_nodes, serialize_pipeline_result

        context = arguments.get("context", {})
        message = arguments.get("message", "")
        if message:
            context["user_message"] = message

        raw_nodes = self._pipeline_config.get("nodes", [])
        if not raw_nodes:
            return ToolResult(content="Pipeline has no nodes configured", is_error=True)

        try:
            pipeline_nodes = parse_pipeline_nodes(raw_nodes)

            # Inject message into search nodes
            for node in pipeline_nodes:
                if node.tool_name == "web_search" and "query" not in node.arguments:
                    node.arguments["query"] = message

            executor = PipelineExecutor(
                tool_registry=self._tool_registry,
                timeout_seconds=self._timeout_seconds,
            )
            result = await executor.execute(pipeline_nodes, context)
            serialized = serialize_pipeline_result(result)

            return ToolResult(
                content=json.dumps(serialized, default=str),
                metadata={
                    "pipeline_status": result.status,
                    "execution_path": result.execution_path,
                    "total_duration_ms": result.total_duration_ms,
                },
            )
        except Exception as e:
            return ToolResult(content=f"Pipeline execution failed: {e}", is_error=True)
