"""Sub-pipeline tool — execute a nested pipeline within a parent pipeline step."""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class SubPipelineTool(BaseTool):
    name = "sub_pipeline"
    description = (
        "Execute a nested pipeline as a single step within a parent pipeline. "
        "Define a set of pipeline nodes with dependencies, conditions, and data "
        "flow — they will be executed as a self-contained DAG. Results from the "
        "sub-pipeline are returned as the step output. Useful for composing "
        "reusable pipeline fragments and modular workflow design."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "tool_name": {"type": "string"},
                        "arguments": {"type": "object", "default": {}},
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": [],
                        },
                        "condition": {"type": "object"},
                        "input_mappings": {"type": "object", "default": {}},
                    },
                    "required": ["id", "tool_name"],
                },
                "description": "List of pipeline node definitions for the sub-pipeline",
            },
            "context": {
                "type": "object",
                "description": "Optional context data passed to the sub-pipeline",
                "default": {},
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Timeout for the sub-pipeline execution",
                "default": 60,
                "minimum": 5,
                "maximum": 300,
            },
        },
        "required": ["nodes"],
    }

    def __init__(self, tool_registry: Any = None) -> None:
        """Initialize with an optional parent tool registry to share tools."""
        self._parent_registry = tool_registry

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raw_nodes = arguments.get("nodes", [])
        context = arguments.get("context", {})
        timeout_seconds = arguments.get("timeout_seconds", 60)

        if not raw_nodes:
            return ToolResult(
                content="Error: at least one node is required", is_error=True
            )

        try:
            from engine.pipeline import (
                PipelineExecutor,
                parse_pipeline_nodes,
                serialize_pipeline_result,
            )

            nodes = parse_pipeline_nodes(raw_nodes)

            # Use the parent registry if available, otherwise build a minimal one
            if self._parent_registry is not None:
                registry = self._parent_registry
            else:
                from engine.tools.base import ToolRegistry

                registry = ToolRegistry()

            executor = PipelineExecutor(
                tool_registry=registry,
                timeout_seconds=timeout_seconds,
            )

            result = await executor.execute(nodes, context=context)
            serialized = serialize_pipeline_result(result)

            return ToolResult(
                content=json.dumps(serialized, indent=2, default=str),
                metadata={
                    "status": result.status,
                    "node_count": len(nodes),
                    "completed_count": len(result.execution_path),
                    "failed_count": len(result.failed_nodes),
                    "skipped_count": len(result.skipped_nodes),
                    "total_duration_ms": result.total_duration_ms,
                },
            )

        except ValueError as e:
            return ToolResult(
                content=f"Sub-pipeline validation error: {e}", is_error=True
            )
        except Exception as e:
            return ToolResult(content=f"Sub-pipeline failed: {e}", is_error=True)
