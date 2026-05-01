"""Circuit Breaker — per-tool health tracking with automatic fallback."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import redis.asyncio as aioredis


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5  # Failures before opening
    recovery_timeout: float = 60.0  # Seconds before trying half-open
    half_open_max_calls: int = 2  # Max calls in half-open state
    success_threshold: int = 2  # Successes in half-open to close


def _circuit_key(tool_name: str) -> str:
    return f"circuit:{tool_name}"


class CircuitBreaker:
    """Per-tool circuit breaker with Redis state."""

    def __init__(self, redis_url: str, config: CircuitBreakerConfig | None = None):
        self._redis_url = redis_url
        self._config = config or CircuitBreakerConfig()
        self._pool: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._pool is None:
            self._pool = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._pool

    async def get_state(self, tool_name: str) -> CircuitState:
        """Get the current circuit state for a tool."""
        r = await self._get_redis()
        data = await r.hgetall(_circuit_key(tool_name))
        if not data:
            return CircuitState.CLOSED

        state = CircuitState(data.get("state", "closed"))

        # Check if open circuit should transition to half-open
        if state == CircuitState.OPEN:
            opened_at = float(data.get("opened_at", 0))
            if time.time() - opened_at >= self._config.recovery_timeout:
                await self._transition(tool_name, CircuitState.HALF_OPEN)
                return CircuitState.HALF_OPEN

        return state

    async def can_execute(self, tool_name: str) -> bool:
        """Check if a tool call is allowed by the circuit breaker."""
        state = await self.get_state(tool_name)
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            r = await self._get_redis()
            data = await r.hgetall(_circuit_key(tool_name))
            half_open_calls = int(data.get("half_open_calls", 0))
            return half_open_calls < self._config.half_open_max_calls
        return False  # OPEN

    async def record_success(self, tool_name: str) -> None:
        """Record a successful tool call."""
        r = await self._get_redis()
        state = await self.get_state(tool_name)

        if state == CircuitState.HALF_OPEN:
            key = _circuit_key(tool_name)
            successes = int(await r.hincrby(key, "half_open_successes", 1))
            if successes >= self._config.success_threshold:
                await self._transition(tool_name, CircuitState.CLOSED)
        elif state == CircuitState.CLOSED:
            # Reset failure count on success
            await r.hset(_circuit_key(tool_name), "consecutive_failures", "0")

    async def record_failure(self, tool_name: str) -> CircuitState:
        """Record a failed tool call. Returns the new state."""
        r = await self._get_redis()
        state = await self.get_state(tool_name)
        key = _circuit_key(tool_name)

        if state == CircuitState.HALF_OPEN:
            # Any failure in half-open goes back to open
            await self._transition(tool_name, CircuitState.OPEN)
            return CircuitState.OPEN

        if state == CircuitState.CLOSED:
            failures = int(await r.hincrby(key, "consecutive_failures", 1))
            if failures >= self._config.failure_threshold:
                await self._transition(tool_name, CircuitState.OPEN)
                return CircuitState.OPEN

        return state

    async def _transition(self, tool_name: str, new_state: CircuitState) -> None:
        """Transition a circuit to a new state."""
        r = await self._get_redis()
        key = _circuit_key(tool_name)
        now = time.time()

        mapping: dict[str, str] = {"state": new_state.value}
        if new_state == CircuitState.OPEN:
            mapping["opened_at"] = str(now)
            mapping["half_open_calls"] = "0"
            mapping["half_open_successes"] = "0"
        elif new_state == CircuitState.HALF_OPEN:
            mapping["half_open_calls"] = "0"
            mapping["half_open_successes"] = "0"
        elif new_state == CircuitState.CLOSED:
            mapping["consecutive_failures"] = "0"

        await r.hset(key, mapping=mapping)
        await r.expire(key, 86400)  # 24h TTL

    async def get_all_states(self) -> dict[str, dict[str, Any]]:
        """Get circuit breaker states for all tools."""
        r = await self._get_redis()
        keys = []
        async for key in r.scan_iter("circuit:*"):
            keys.append(key)

        states = {}
        for key in keys:
            tool_name = key.replace("circuit:", "")
            data = await r.hgetall(key)
            states[tool_name] = {
                "state": data.get("state", "closed"),
                "consecutive_failures": int(data.get("consecutive_failures", 0)),
                "opened_at": data.get("opened_at"),
            }
        return states


class ResilientToolRegistry:
    """Wraps ToolRegistry with circuit breaker protection."""

    def __init__(
        self,
        registry: Any,
        circuit_breaker: CircuitBreaker,
        fallbacks: dict[str, str] | None = None,
    ):
        self._registry = registry
        self._cb = circuit_breaker
        self._fallbacks = fallbacks or {}  # tool_name -> fallback_tool_name

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Execute a tool with circuit breaker protection."""
        if not await self._cb.can_execute(tool_name):
            # Try fallback
            fallback = self._fallbacks.get(tool_name)
            if fallback and await self._cb.can_execute(fallback):
                tool = self._registry.get(fallback)
                if tool:
                    result = await tool.execute(arguments)
                    if not result.is_error:
                        await self._cb.record_success(fallback)
                    return result

            from engine.tools.base import ToolResult

            return ToolResult(
                content=f"Tool '{tool_name}' is temporarily unavailable (circuit open). Please try again later.",
                is_error=True,
                metadata={"circuit_state": "open"},
            )

        tool = self._registry.get(tool_name)
        if not tool:
            from engine.tools.base import ToolResult

            return ToolResult(content=f"Tool '{tool_name}' not found.", is_error=True)

        try:
            result = await tool.execute(arguments)
            if result.is_error:
                await self._cb.record_failure(tool_name)
            else:
                await self._cb.record_success(tool_name)
            return result
        except Exception as e:
            await self._cb.record_failure(tool_name)
            from engine.tools.base import ToolResult

            return ToolResult(content=f"Tool execution failed: {e}", is_error=True)
