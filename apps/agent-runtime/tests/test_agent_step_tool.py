"""Tests for the AgentStepTool with mocked AgentExecutor."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.tools.agent_step import AgentStepTool

# ── Mock data classes ─────────────────────────────────────────────


@dataclass
class MockExecutionResult:
    """Mimics engine.agent_executor.ExecutionResult."""

    output: str = "Mock agent response"
    input_tokens: int = 150
    output_tokens: int = 200
    cost: float = 0.005
    duration_ms: int = 1200
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model: str = "claude-sonnet-4-5-20250929"
    cache_hit: str = ""
    node_traces: list[Any] = field(default_factory=list)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def tool() -> AgentStepTool:
    return AgentStepTool()


# ── Tests ─────────────────────────────────────────────────────────


class TestAgentStepTool:
    @pytest.mark.asyncio
    async def test_basic_agent_execution(self, tool: AgentStepTool) -> None:
        """Basic agent execution returns a response from the mocked executor."""
        mock_result = MockExecutionResult(output="The answer is 42.")

        with patch("engine.agent_executor.AgentExecutor") as MockExecutor, patch(
            "engine.agent_executor.build_tool_registry"
        ) as mock_build, patch("engine.llm_router.LLMRouter"), patch(
            "engine.sandbox.ExecutionSandbox"
        ), patch(
            "engine.sandbox.SandboxPolicy"
        ):
            mock_instance = AsyncMock()
            mock_instance.invoke = AsyncMock(return_value=mock_result)
            MockExecutor.return_value = mock_instance
            mock_build.return_value = MagicMock()

            result = await tool.execute(
                {
                    "input_message": "What is the meaning of life?",
                    "system_prompt": "You are a helpful assistant.",
                }
            )

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["response"] == "The answer is 42."

    @pytest.mark.asyncio
    async def test_agent_with_tools(self, tool: AgentStepTool) -> None:
        """Verify build_tool_registry is called with the provided tools list."""
        mock_result = MockExecutionResult()

        with patch("engine.agent_executor.AgentExecutor") as MockExecutor, patch(
            "engine.agent_executor.build_tool_registry"
        ) as mock_build, patch("engine.llm_router.LLMRouter"), patch(
            "engine.sandbox.ExecutionSandbox"
        ), patch(
            "engine.sandbox.SandboxPolicy"
        ):
            mock_instance = AsyncMock()
            mock_instance.invoke = AsyncMock(return_value=mock_result)
            MockExecutor.return_value = mock_instance
            mock_build.return_value = MagicMock()

            await tool.execute(
                {
                    "input_message": "Search for something",
                    "system_prompt": "You are a researcher.",
                    "tools": ["web_search", "calculator"],
                }
            )

        mock_build.assert_called_once_with(["web_search", "calculator"])

    @pytest.mark.asyncio
    async def test_agent_respects_max_iterations(self, tool: AgentStepTool) -> None:
        """Verify max_iterations is forwarded to the executor."""
        mock_result = MockExecutionResult()

        with patch("engine.agent_executor.AgentExecutor") as MockExecutor, patch(
            "engine.agent_executor.build_tool_registry"
        ) as mock_build, patch("engine.llm_router.LLMRouter"), patch(
            "engine.sandbox.ExecutionSandbox"
        ), patch(
            "engine.sandbox.SandboxPolicy"
        ):
            mock_instance = AsyncMock()
            mock_instance.invoke = AsyncMock(return_value=mock_result)
            MockExecutor.return_value = mock_instance
            mock_build.return_value = MagicMock()

            await tool.execute(
                {
                    "input_message": "Analyze this data",
                    "system_prompt": "You are an analyst.",
                    "max_iterations": 5,
                }
            )

        # Check that AgentExecutor was created with max_iterations=5
        call_kwargs = MockExecutor.call_args
        assert call_kwargs.kwargs.get("max_iterations") == 5

    @pytest.mark.asyncio
    async def test_agent_custom_model(self, tool: AgentStepTool) -> None:
        """Verify model is forwarded to the executor."""
        mock_result = MockExecutionResult(model="claude-opus-4-20250514")

        with patch("engine.agent_executor.AgentExecutor") as MockExecutor, patch(
            "engine.agent_executor.build_tool_registry"
        ) as mock_build, patch("engine.llm_router.LLMRouter"), patch(
            "engine.sandbox.ExecutionSandbox"
        ), patch(
            "engine.sandbox.SandboxPolicy"
        ):
            mock_instance = AsyncMock()
            mock_instance.invoke = AsyncMock(return_value=mock_result)
            MockExecutor.return_value = mock_instance
            mock_build.return_value = MagicMock()

            await tool.execute(
                {
                    "input_message": "Complex reasoning task",
                    "system_prompt": "You are a deep thinker.",
                    "model": "claude-opus-4-20250514",
                }
            )

        call_kwargs = MockExecutor.call_args
        assert call_kwargs.kwargs.get("model") == "claude-opus-4-20250514"

    @pytest.mark.asyncio
    async def test_agent_custom_temperature(self, tool: AgentStepTool) -> None:
        """Verify temperature is forwarded to the executor."""
        mock_result = MockExecutionResult()

        with patch("engine.agent_executor.AgentExecutor") as MockExecutor, patch(
            "engine.agent_executor.build_tool_registry"
        ) as mock_build, patch("engine.llm_router.LLMRouter"), patch(
            "engine.sandbox.ExecutionSandbox"
        ), patch(
            "engine.sandbox.SandboxPolicy"
        ):
            mock_instance = AsyncMock()
            mock_instance.invoke = AsyncMock(return_value=mock_result)
            MockExecutor.return_value = mock_instance
            mock_build.return_value = MagicMock()

            await tool.execute(
                {
                    "input_message": "Be creative",
                    "system_prompt": "You are a creative writer.",
                    "temperature": 1.5,
                }
            )

        call_kwargs = MockExecutor.call_args
        assert call_kwargs.kwargs.get("temperature") == 1.5

    @pytest.mark.asyncio
    async def test_missing_input_message_error(self, tool: AgentStepTool) -> None:
        """Missing or empty input_message should return an error."""
        result = await tool.execute(
            {
                "input_message": "",
                "system_prompt": "You are a helper.",
            }
        )

        assert result.is_error
        assert "input_message" in result.content.lower()

    @pytest.mark.asyncio
    async def test_agent_timeout(self, tool: AgentStepTool) -> None:
        """AgentExecutor raising TimeoutError should return an error result."""
        with patch("engine.agent_executor.AgentExecutor") as MockExecutor, patch(
            "engine.agent_executor.build_tool_registry"
        ) as mock_build, patch("engine.llm_router.LLMRouter"), patch(
            "engine.sandbox.ExecutionSandbox"
        ), patch(
            "engine.sandbox.SandboxPolicy"
        ):
            mock_instance = AsyncMock()
            mock_instance.invoke = AsyncMock(
                side_effect=TimeoutError("Agent execution timed out")
            )
            MockExecutor.return_value = mock_instance
            mock_build.return_value = MagicMock()

            result = await tool.execute(
                {
                    "input_message": "This will take too long",
                    "system_prompt": "You are slow.",
                }
            )

        assert result.is_error
        assert (
            "failed" in result.content.lower() or "timed out" in result.content.lower()
        )

    @pytest.mark.asyncio
    async def test_agent_output_includes_metadata(self, tool: AgentStepTool) -> None:
        """Output includes token counts, cost, and other metadata."""
        mock_result = MockExecutionResult(
            output="Analysis complete.",
            input_tokens=500,
            output_tokens=300,
            cost=0.0123,
            duration_ms=2500,
            tool_calls=[{"name": "calculator", "input": {"expr": "2+2"}}],
            model="claude-sonnet-4-5-20250929",
            node_traces=[MagicMock(), MagicMock(), MagicMock()],
        )

        with patch("engine.agent_executor.AgentExecutor") as MockExecutor, patch(
            "engine.agent_executor.build_tool_registry"
        ) as mock_build, patch("engine.llm_router.LLMRouter"), patch(
            "engine.sandbox.ExecutionSandbox"
        ), patch(
            "engine.sandbox.SandboxPolicy"
        ):
            mock_instance = AsyncMock()
            mock_instance.invoke = AsyncMock(return_value=mock_result)
            MockExecutor.return_value = mock_instance
            mock_build.return_value = MagicMock()

            result = await tool.execute(
                {
                    "input_message": "Analyze the data",
                    "system_prompt": "You are a data analyst.",
                }
            )

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["response"] == "Analysis complete."
        assert parsed["input_tokens"] == 500
        assert parsed["output_tokens"] == 300
        assert parsed["cost"] == 0.0123
        assert parsed["duration_ms"] == 2500
        assert parsed["tool_calls_count"] == 1
        assert parsed["iterations"] == 3
        assert parsed["model"] == "claude-sonnet-4-5-20250929"

        # Verify metadata on the ToolResult
        assert result.metadata["model"] == "claude-sonnet-4-5-20250929"
        assert result.metadata["input_tokens"] == 500
        assert result.metadata["output_tokens"] == 300
        assert result.metadata["cost"] == 0.0123
        assert result.metadata["tool_calls_count"] == 1
