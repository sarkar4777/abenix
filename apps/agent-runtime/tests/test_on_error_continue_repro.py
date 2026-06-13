"""Reproduction for on_error='continue' bug.

Boom node fails, downstream depends on it with depends_on=[boom].
With on_error='continue', downstream should run, not be skipped.
"""

from __future__ import annotations

import asyncio
import json

from engine.pipeline import PipelineExecutor, PipelineNode
from engine.tools.base import BaseTool, ToolRegistry, ToolResult


class FailTool(BaseTool):
    name = "fail"
    description = "Always fails"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict) -> ToolResult:
        # Mirror http_client error shape: string content, is_error=True
        return ToolResult(content="HTTP request failed: boom", is_error=True)


class EchoTool(BaseTool):
    name = "echo"
    description = "Echo"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict) -> ToolResult:
        return ToolResult(content=json.dumps({"ran": True, "args": arguments}))


async def main():
    reg = ToolRegistry()
    reg.register(FailTool())
    reg.register(EchoTool())

    nodes = [
        PipelineNode(id="boom", tool_name="fail", on_error="continue"),
        PipelineNode(id="downstream", tool_name="echo", depends_on=["boom"]),
    ]
    exe = PipelineExecutor(tool_registry=reg)
    result = await exe.execute(nodes, context={})

    print("STATUS:", result.status)
    print("PATH:", result.execution_path)
    print("SKIPPED:", result.skipped_nodes)
    print("FAILED:", result.failed_nodes)
    for nid, r in result.node_results.items():
        print(f"  {nid}: status={r.status} output={r.output!r} error={r.error!r}")


if __name__ == "__main__":
    asyncio.run(main())
