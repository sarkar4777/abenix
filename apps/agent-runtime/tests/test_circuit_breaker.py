"""Tests for circuit breaker logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from engine.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    ResilientToolRegistry,
)


class TestCircuitBreakerConfig:
    def test_defaults(self):
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.recovery_timeout == 60.0
        assert config.half_open_max_calls == 2
        assert config.success_threshold == 2

    def test_custom_config(self):
        config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout=30.0)
        assert config.failure_threshold == 3
        assert config.recovery_timeout == 30.0


class TestCircuitState:
    def test_states(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestResilientToolRegistry:
    @pytest.mark.asyncio
    async def test_execute_healthy_tool(self):
        from engine.tools.base import ToolResult

        mock_tool = MagicMock()
        mock_tool.execute = AsyncMock(return_value=ToolResult(content="result"))

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_tool

        mock_cb = MagicMock()
        mock_cb.can_execute = AsyncMock(return_value=True)
        mock_cb.record_success = AsyncMock()

        registry = ResilientToolRegistry(mock_registry, mock_cb)
        result = await registry.execute_tool("test_tool", {"key": "value"})

        assert result.content == "result"
        assert not result.is_error
        mock_cb.record_success.assert_called_once_with("test_tool")

    @pytest.mark.asyncio
    async def test_execute_open_circuit_no_fallback(self):
        mock_registry = MagicMock()
        mock_cb = MagicMock()
        mock_cb.can_execute = AsyncMock(return_value=False)

        registry = ResilientToolRegistry(mock_registry, mock_cb)
        result = await registry.execute_tool("broken_tool", {})

        assert result.is_error
        assert "temporarily unavailable" in result.content

    @pytest.mark.asyncio
    async def test_execute_with_fallback(self):
        from engine.tools.base import ToolResult

        fallback_tool = MagicMock()
        fallback_tool.execute = AsyncMock(return_value=ToolResult(content="fallback result"))

        mock_registry = MagicMock()
        mock_registry.get.return_value = fallback_tool

        mock_cb = MagicMock()
        mock_cb.can_execute = AsyncMock(side_effect=lambda name: name == "alt_tool")
        mock_cb.record_success = AsyncMock()

        registry = ResilientToolRegistry(
            mock_registry, mock_cb, fallbacks={"broken_tool": "alt_tool"}
        )
        result = await registry.execute_tool("broken_tool", {})

        assert result.content == "fallback result"
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self):
        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        mock_cb = MagicMock()
        mock_cb.can_execute = AsyncMock(return_value=True)

        registry = ResilientToolRegistry(mock_registry, mock_cb)
        result = await registry.execute_tool("nonexistent", {})

        assert result.is_error
        assert "not found" in result.content

    @pytest.mark.asyncio
    async def test_execute_records_failure_on_error(self):
        from engine.tools.base import ToolResult

        mock_tool = MagicMock()
        mock_tool.execute = AsyncMock(return_value=ToolResult(content="error", is_error=True))

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_tool

        mock_cb = MagicMock()
        mock_cb.can_execute = AsyncMock(return_value=True)
        mock_cb.record_failure = AsyncMock()

        registry = ResilientToolRegistry(mock_registry, mock_cb)
        result = await registry.execute_tool("failing_tool", {})

        mock_cb.record_failure.assert_called_once_with("failing_tool")

    @pytest.mark.asyncio
    async def test_execute_records_failure_on_exception(self):
        mock_tool = MagicMock()
        mock_tool.execute = AsyncMock(side_effect=RuntimeError("boom"))

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_tool

        mock_cb = MagicMock()
        mock_cb.can_execute = AsyncMock(return_value=True)
        mock_cb.record_failure = AsyncMock()

        registry = ResilientToolRegistry(mock_registry, mock_cb)
        result = await registry.execute_tool("exploding_tool", {})

        assert result.is_error
        assert "boom" in result.content
        mock_cb.record_failure.assert_called_once()
