"""Adaptive Retry — LLM-powered intelligent retry strategy."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class RetryPolicy:
    strategy: str = "fixed"  # "fixed", "adaptive", "circuit_breaker"
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_factor: float = 2.0


@dataclass
class RetryResult:
    success: bool
    result: Any = None
    attempts: int = 0
    final_error: str | None = None
    strategy_used: str = "fixed"
    modifications: list[str] = field(default_factory=list)


async def retry_with_policy(
    func: Callable[..., Awaitable[Any]],
    args: dict[str, Any],
    policy: RetryPolicy,
    *,
    llm_advisor: Callable[..., Awaitable[str]] | None = None,
    context: str = "",
) -> RetryResult:
    """Execute a function with the specified retry policy."""
    if policy.strategy == "adaptive" and llm_advisor:
        return await _adaptive_retry(func, args, policy, llm_advisor, context)
    return await _fixed_retry(func, args, policy)


async def _fixed_retry(
    func: Callable[..., Awaitable[Any]],
    args: dict[str, Any],
    policy: RetryPolicy,
) -> RetryResult:
    """Standard retry with exponential backoff."""
    last_error = None
    for attempt in range(policy.max_retries + 1):
        try:
            result = await func(**args)
            return RetryResult(success=True, result=result, attempts=attempt + 1)
        except Exception as e:
            last_error = str(e)
            if attempt < policy.max_retries:
                delay = min(
                    policy.base_delay * (policy.backoff_factor**attempt),
                    policy.max_delay,
                )
                await asyncio.sleep(delay)

    return RetryResult(
        success=False,
        attempts=policy.max_retries + 1,
        final_error=last_error,
        strategy_used="fixed",
    )


async def _adaptive_retry(
    func: Callable[..., Awaitable[Any]],
    args: dict[str, Any],
    policy: RetryPolicy,
    llm_advisor: Callable[..., Awaitable[str]],
    context: str,
) -> RetryResult:
    """LLM-powered adaptive retry that modifies approach based on failures."""
    modifications = []
    current_args = dict(args)
    last_error = None

    for attempt in range(policy.max_retries + 1):
        try:
            result = await func(**current_args)
            return RetryResult(
                success=True,
                result=result,
                attempts=attempt + 1,
                strategy_used="adaptive",
                modifications=modifications,
            )
        except Exception as e:
            last_error = str(e)
            if attempt >= policy.max_retries:
                break

            # Ask LLM for advice
            advice_prompt = (
                f"A tool execution failed. Context: {context}\n"
                f"Error: {last_error}\n"
                f"Current arguments: {json.dumps(current_args, default=str)}\n"
                f"Attempt {attempt + 1} of {policy.max_retries + 1}.\n"
                f"Should I retry with modified arguments? If so, provide the "
                f"modified arguments as JSON. If not, respond with GIVE_UP and explain why.\n"
                f"Respond with either:\n"
                f'1. {{"retry": true, "modified_args": {{...}}, "reason": "..."}}\n'
                f'2. {{"retry": false, "reason": "..."}}'
            )

            try:
                advice_raw = await llm_advisor(advice_prompt)
                advice = json.loads(advice_raw)

                if not advice.get("retry", True):
                    modifications.append(
                        f"LLM advised giving up: {advice.get('reason', 'unknown')}"
                    )
                    break

                if "modified_args" in advice:
                    current_args.update(advice["modified_args"])
                    reason = advice.get("reason", "LLM modified arguments")
                    modifications.append(f"Attempt {attempt + 1}: {reason}")

            except (json.JSONDecodeError, Exception):
                # If LLM advice fails, fall back to simple retry
                modifications.append(
                    f"Attempt {attempt + 1}: LLM advice unavailable, retrying as-is"
                )

            delay = min(
                policy.base_delay * (policy.backoff_factor**attempt),
                policy.max_delay,
            )
            await asyncio.sleep(delay)

    return RetryResult(
        success=False,
        attempts=policy.max_retries + 1,
        final_error=last_error,
        strategy_used="adaptive",
        modifications=modifications,
    )
