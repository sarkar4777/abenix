"""Tests for the LLM call pipeline tool."""

from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from engine.tools.llm_call import LLMCallTool


@pytest.fixture
def tool() -> LLMCallTool:
    return LLMCallTool()


def _make_mock_response(
    content: str = "Hello world",
    model: str = "claude-sonnet-4-5-20250929",
    input_tokens: int = 10,
    output_tokens: int = 5,
    cost: float = 0.001,
    latency_ms: int = 100,
) -> MagicMock:
    """Create a mock LLMResponse with the given fields."""
    resp = MagicMock()
    resp.content = content
    resp.model = model
    resp.input_tokens = input_tokens
    resp.output_tokens = output_tokens
    resp.cost = cost
    resp.latency_ms = latency_ms
    return resp


class TestLLMCallTool:
    @pytest.mark.asyncio
    @patch("engine.llm_router.LLMRouter")
    async def test_basic_prompt_returns_text(
        self, MockRouter: MagicMock, tool: LLMCallTool
    ) -> None:
        """A simple prompt returns valid JSON with the response text."""
        mock_response = _make_mock_response(content="Hello world")
        mock_instance = MockRouter.return_value
        mock_instance.complete = AsyncMock(return_value=mock_response)

        result = await tool.execute({"prompt": "Hi"})

        assert result.is_error is False
        parsed = json.loads(result.content)
        assert parsed["response"] == "Hello world"

    @pytest.mark.asyncio
    @patch("engine.llm_router.LLMRouter")
    async def test_custom_model_routing(
        self, MockRouter: MagicMock, tool: LLMCallTool
    ) -> None:
        """Specifying a custom model passes it through to the router."""
        mock_response = _make_mock_response(model="gpt-4o")
        mock_instance = MockRouter.return_value
        mock_instance.complete = AsyncMock(return_value=mock_response)

        await tool.execute({"prompt": "Hi", "model": "gpt-4o"})

        mock_instance.complete.assert_awaited_once()
        call_kwargs = mock_instance.complete.call_args
        assert call_kwargs.kwargs.get("model") == "gpt-4o" or (
            call_kwargs[1].get("model") == "gpt-4o"
            if len(call_kwargs) > 1
            else call_kwargs[0][3] == "gpt-4o"
            if len(call_kwargs[0]) > 3
            else False
        )

    @pytest.mark.asyncio
    @patch("engine.llm_router.LLMRouter")
    async def test_system_prompt_passed(
        self, MockRouter: MagicMock, tool: LLMCallTool
    ) -> None:
        """A system_prompt argument is forwarded as the system parameter."""
        mock_response = _make_mock_response()
        mock_instance = MockRouter.return_value
        mock_instance.complete = AsyncMock(return_value=mock_response)

        await tool.execute(
            {"prompt": "Hi", "system_prompt": "You are helpful"}
        )

        mock_instance.complete.assert_awaited_once()
        _, kwargs = mock_instance.complete.call_args
        assert kwargs.get("system") == "You are helpful"

    @pytest.mark.asyncio
    @patch("engine.llm_router.LLMRouter")
    async def test_temperature_setting(
        self, MockRouter: MagicMock, tool: LLMCallTool
    ) -> None:
        """A custom temperature value is forwarded to the router."""
        mock_response = _make_mock_response()
        mock_instance = MockRouter.return_value
        mock_instance.complete = AsyncMock(return_value=mock_response)

        await tool.execute({"prompt": "Hi", "temperature": 0.2})

        mock_instance.complete.assert_awaited_once()
        _, kwargs = mock_instance.complete.call_args
        assert kwargs.get("temperature") == 0.2

    @pytest.mark.asyncio
    @patch("engine.llm_router.LLMRouter")
    async def test_max_tokens_in_response(
        self, MockRouter: MagicMock, tool: LLMCallTool
    ) -> None:
        """The JSON output includes input_tokens and output_tokens."""
        mock_response = _make_mock_response(input_tokens=42, output_tokens=17)
        mock_instance = MockRouter.return_value
        mock_instance.complete = AsyncMock(return_value=mock_response)

        result = await tool.execute({"prompt": "Hi"})

        assert result.is_error is False
        parsed = json.loads(result.content)
        assert parsed["input_tokens"] == 42
        assert parsed["output_tokens"] == 17

    @pytest.mark.asyncio
    async def test_empty_prompt_error(self, tool: LLMCallTool) -> None:
        """An empty prompt returns an error without calling the LLM."""
        result = await tool.execute({"prompt": ""})

        assert result.is_error is True
        assert "prompt" in result.content.lower() or "required" in result.content.lower()

    @pytest.mark.asyncio
    @patch("engine.llm_router.LLMRouter")
    async def test_llm_api_failure_returns_error(
        self, MockRouter: MagicMock, tool: LLMCallTool
    ) -> None:
        """An exception from the LLM provider is caught and returned as an error."""
        mock_instance = MockRouter.return_value
        mock_instance.complete = AsyncMock(side_effect=Exception("API error"))

        result = await tool.execute({"prompt": "Hi"})

        assert result.is_error is True
        assert "LLM call failed" in result.content

    @pytest.mark.asyncio
    @patch("engine.llm_router.LLMRouter")
    async def test_metadata_includes_model(
        self, MockRouter: MagicMock, tool: LLMCallTool
    ) -> None:
        """The parsed JSON output contains a model field matching the response."""
        mock_response = _make_mock_response(model="claude-sonnet-4-5-20250929")
        mock_instance = MockRouter.return_value
        mock_instance.complete = AsyncMock(return_value=mock_response)

        result = await tool.execute({"prompt": "Hi"})

        assert result.is_error is False
        parsed = json.loads(result.content)
        assert parsed["model"] == "claude-sonnet-4-5-20250929"
