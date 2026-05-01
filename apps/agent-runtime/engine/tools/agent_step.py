"""Agent step tool — run a full AI agent as a pipeline step."""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class AgentStepTool(BaseTool):
    name = "agent_step"
    description = (
        "Run a full AI agent as a pipeline step. The agent has its own LLM loop, "
        "can use tools, and iterates autonomously until it produces a final answer. "
        "Use this to chain agents within a pipeline — the output of one agent can "
        "feed into another. Supports all available tools and LLM models."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "input_message": {
                "type": "string",
                "description": "The task or prompt for the agent to work on",
            },
            "system_prompt": {
                "type": "string",
                "description": "System prompt defining the agent's role and behavior",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tool names available to the agent",
                "default": [],
            },
            "model": {
                "type": "string",
                "description": "LLM model to use",
                "default": "claude-sonnet-4-5-20250929",
            },
            "max_iterations": {
                "type": "integer",
                "description": "Maximum number of LLM reasoning loops",
                "default": 10,
                "minimum": 1,
                "maximum": 25,
            },
            "temperature": {
                "type": "number",
                "description": "Sampling temperature",
                "default": 0.7,
                "minimum": 0,
                "maximum": 2,
            },
        },
        "required": ["input_message", "system_prompt"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        input_message = arguments.get("input_message", "")
        system_prompt = arguments.get("system_prompt", "")
        raw_tools = arguments.get("tools", [])
        # Handle both list and comma-separated string formats
        if isinstance(raw_tools, str):
            tool_names = [t.strip() for t in raw_tools.split(",") if t.strip()]
        elif isinstance(raw_tools, list):
            tool_names = raw_tools
        else:
            tool_names = []
        model = arguments.get("model", "claude-sonnet-4-5-20250929")
        max_iterations = arguments.get("max_iterations", 10)
        temperature = arguments.get("temperature", 0.7)

        # Coerce non-string inputs (from upstream node outputs) to JSON strings
        if not isinstance(input_message, str):
            import json as _j

            input_message = _j.dumps(input_message, default=str, indent=2)
        if not isinstance(system_prompt, str):
            import json as _j

            system_prompt = _j.dumps(system_prompt, default=str, indent=2)

        if not input_message.strip():
            return ToolResult(content="Error: input_message is required", is_error=True)
        if not system_prompt.strip():
            return ToolResult(content="Error: system_prompt is required", is_error=True)

        try:
            from engine.agent_executor import AgentExecutor, build_tool_registry
            from engine.llm_router import LLMRouter
            from engine.sandbox import ExecutionSandbox, SandboxPolicy

            # Build a sub-agent with its own sandbox (reduced limits to prevent runaway)
            sub_sandbox = ExecutionSandbox(
                SandboxPolicy(
                    timeout_seconds=120,
                    max_tool_calls=20,
                    max_output_chars=50_000,
                )
            )

            tool_registry = (
                build_tool_registry(tool_names)
                if tool_names
                else build_tool_registry([])
            )
            router = LLMRouter()

            executor = AgentExecutor(
                llm_router=router,
                tool_registry=tool_registry,
                system_prompt=system_prompt,
                model=model,
                temperature=temperature,
                max_iterations=max_iterations,
                sandbox=sub_sandbox,
            )

            result = await executor.invoke(input_message)

            output = {
                "response": result.output,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost": result.cost,
                "duration_ms": result.duration_ms,
                "tool_calls_count": len(result.tool_calls) if result.tool_calls else 0,
                "iterations": len(result.node_traces) if result.node_traces else 0,
            }

            return ToolResult(
                content=json.dumps(output, indent=2, default=str),
                metadata={
                    "model": result.model,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "cost": result.cost,
                    "tool_calls_count": (
                        len(result.tool_calls) if result.tool_calls else 0
                    ),
                },
            )

        except Exception as e:
            return ToolResult(content=f"Agent step failed: {e}", is_error=True)
