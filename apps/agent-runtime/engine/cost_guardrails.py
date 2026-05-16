"""Cost Guardrails — pre-execution prediction and runtime enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis

# Model pricing per 1M tokens (input, output) in USD
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
    "claude-haiku-3-5": (0.25, 1.25),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gemini-2.0-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.0),
}

DEFAULT_PRICING = (3.0, 15.0)  # fallback


@dataclass
class CostPrediction:
    estimated_cost: float
    model: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    within_budget: bool
    budget_remaining: float | None
    warning: str | None = None


@dataclass
class CostCheckResult:
    allowed: bool
    current_cost: float
    limit: float | None
    reason: str | None = None


def predict_cost(
    model: str,
    estimated_input_tokens: int = 2000,
    estimated_output_tokens: int = 1000,
    max_iterations: int = 1,
    tool_count: int = 0,
    per_execution_limit: float | None = None,
) -> CostPrediction:
    """Predict the cost of an execution before it starts."""
    input_price, output_price = MODEL_PRICING.get(model, DEFAULT_PRICING)

    # Estimate: each iteration may use tools which add ~500 tokens each
    total_input = estimated_input_tokens + (tool_count * 500 * max_iterations)
    total_output = estimated_output_tokens * max_iterations

    estimated = (total_input / 1_000_000 * input_price) + (
        total_output / 1_000_000 * output_price
    )

    within_budget = True
    warning = None
    budget_remaining = None

    if per_execution_limit:
        budget_remaining = per_execution_limit - estimated
        if estimated > per_execution_limit:
            within_budget = False
            warning = f"Predicted cost ${estimated:.4f} exceeds per-execution limit ${per_execution_limit:.4f}"
        elif estimated > per_execution_limit * 0.8:
            warning = f"Predicted cost ${estimated:.4f} is close to per-execution limit ${per_execution_limit:.4f}"

    return CostPrediction(
        estimated_cost=round(estimated, 6),
        model=model,
        estimated_input_tokens=total_input,
        estimated_output_tokens=total_output,
        within_budget=within_budget,
        budget_remaining=(
            round(budget_remaining, 6) if budget_remaining is not None else None
        ),
        warning=warning,
    )


class CostEnforcer:
    """Runtime cost enforcement during execution."""

    def __init__(
        self,
        redis_url: str,
        execution_id: str,
        tenant_id: str,
        agent_id: str,
        per_execution_limit: float | None = None,
        daily_agent_limit: float | None = None,
        daily_tenant_limit: float | None = None,
        monthly_tenant_limit: float | None = None,
    ):
        self._redis_url = redis_url
        self._execution_id = execution_id
        self._tenant_id = tenant_id
        self._agent_id = agent_id
        self._per_execution_limit = per_execution_limit
        self._daily_agent_limit = daily_agent_limit
        self._daily_tenant_limit = daily_tenant_limit
        self._monthly_tenant_limit = monthly_tenant_limit
        self._accumulated_cost = 0.0
        self._pool: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._pool is None:
            self._pool = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._pool

    async def record_cost(self, cost: float) -> CostCheckResult:
        """Record cost from an LLM call and check against limits."""
        self._accumulated_cost += cost
        r = await self._get_redis()

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        day_key = f"cost:daily:{self._tenant_id}:{now.strftime('%Y-%m-%d')}"
        month_key = f"cost:monthly:{self._tenant_id}:{now.strftime('%Y-%m')}"
        agent_day_key = f"cost:agent:{self._agent_id}:{now.strftime('%Y-%m-%d')}"

        pipe = r.pipeline()
        pipe.incrbyfloat(day_key, cost)
        pipe.expire(day_key, 86400 * 2)
        pipe.incrbyfloat(month_key, cost)
        pipe.expire(month_key, 86400 * 35)
        pipe.incrbyfloat(agent_day_key, cost)
        pipe.expire(agent_day_key, 86400 * 2)
        results = await pipe.execute()

        daily_total = float(results[0])
        monthly_total = float(results[2])
        agent_daily_total = float(results[4])

        # Check per-execution hard limit
        if (
            self._per_execution_limit
            and self._accumulated_cost > self._per_execution_limit
        ):
            return CostCheckResult(
                allowed=False,
                current_cost=self._accumulated_cost,
                limit=self._per_execution_limit,
                reason=f"Per-execution cost limit exceeded: ${self._accumulated_cost:.4f} > ${self._per_execution_limit:.4f}",
            )

        # Check daily agent limit
        if self._daily_agent_limit and agent_daily_total > self._daily_agent_limit:
            return CostCheckResult(
                allowed=False,
                current_cost=agent_daily_total,
                limit=self._daily_agent_limit,
                reason=f"Daily agent cost limit exceeded: ${agent_daily_total:.2f} > ${self._daily_agent_limit:.2f}",
            )

        # Check daily tenant limit
        if self._daily_tenant_limit and daily_total > self._daily_tenant_limit:
            return CostCheckResult(
                allowed=False,
                current_cost=daily_total,
                limit=self._daily_tenant_limit,
                reason=f"Daily tenant cost limit exceeded: ${daily_total:.2f} > ${self._daily_tenant_limit:.2f}",
            )

        # Check monthly tenant limit
        if self._monthly_tenant_limit and monthly_total > self._monthly_tenant_limit:
            return CostCheckResult(
                allowed=False,
                current_cost=monthly_total,
                limit=self._monthly_tenant_limit,
                reason=f"Monthly tenant cost limit exceeded: ${monthly_total:.2f} > ${self._monthly_tenant_limit:.2f}",
            )

        return CostCheckResult(
            allowed=True,
            current_cost=self._accumulated_cost,
            limit=self._per_execution_limit,
        )

    async def get_budget_status(self) -> dict[str, Any]:
        """Get current budget usage status."""
        r = await self._get_redis()
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        day_key = f"cost:daily:{self._tenant_id}:{now.strftime('%Y-%m-%d')}"
        month_key = f"cost:monthly:{self._tenant_id}:{now.strftime('%Y-%m')}"

        pipe = r.pipeline()
        pipe.get(day_key)
        pipe.get(month_key)
        results = await pipe.execute()

        return {
            "execution_cost": self._accumulated_cost,
            "per_execution_limit": self._per_execution_limit,
            "daily_tenant_cost": float(results[0] or 0),
            "daily_tenant_limit": self._daily_tenant_limit,
            "monthly_tenant_cost": float(results[1] or 0),
            "monthly_tenant_limit": self._monthly_tenant_limit,
        }
