from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import END, StateGraph

from engine.llm_router import LLMResponse, LLMRouter, StreamEvent
from engine.metrics import (
    agent_active_streams,
    agent_execution_duration_seconds,
    moderation_decisions_total,
    tool_execution_duration_seconds,
)
from engine.moderation_gate import GateConfig, ModerationBlocked, check as moderation_check
from engine.sandbox import ExecutionSandbox
from engine.tools.base import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


def _provider_key(model: str) -> str:
    """Classify model id into a provider bucket for cost splitting."""
    m = (model or "").lower()
    if m.startswith("claude"): return "anthropic"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("chatgpt"): return "openai"
    if m.startswith("gemini"): return "google"
    return "other"

MAX_ITERATIONS = 10
# Maximum characters per tool result kept in context. Large results (web pages,
# API responses) are truncated before being sent back to the LLM to prevent
# blowing the context window. The full result is still emitted in traces/streams.
MAX_TOOL_RESULT_CHARS = 12_000
# Estimated tokens-per-char ratio for rough context budget tracking
CHARS_PER_TOKEN = 4
# Leave headroom below the model's context limit
CONTEXT_TOKEN_BUDGET = 180_000


def _truncate_tool_result(content: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Truncate a tool result to fit within context budget."""
    if len(content) <= max_chars:
        return content
    half = max_chars // 2
    return content[:half] + f"\n\n[... truncated {len(content) - max_chars:,} chars ...]\n\n" + content[-half:]


def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough estimate of token count for the messages array."""
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(str(block.get("content", ""))) + len(str(block.get("text", ""))) + len(str(block.get("input", "")))
    return total_chars // CHARS_PER_TOKEN


class AgentState(dict):
    messages: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    iteration: int
    done: bool


@dataclass
class NodeTrace:
    """Captures input/output of each node in the agentic flow."""
    node_id: str
    node_type: str  # "llm_call", "tool_call", "user_input"
    iteration: int
    timestamp_ms: int
    duration_ms: int = 0
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "iteration": self.iteration,
            "timestamp_ms": self.timestamp_ms,
            "duration_ms": self.duration_ms,
            "input": self.input_data,
            "output": self.output_data,
            "metadata": self.metadata,
        }


@dataclass
class ExecutionEvent:
    event: str
    data: Any


@dataclass
class ExecutionResult:
    output: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    # Per-provider subtotals (all in $). Sum equals `cost`. Split at
    # the router so fallback spend across providers shows up correctly
    # on the executions table + dashboards.
    anthropic_cost: float = 0.0
    openai_cost: float = 0.0
    google_cost: float = 0.0
    other_cost: float = 0.0
    duration_ms: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    cache_hit: str = ""
    node_traces: list[NodeTrace] = field(default_factory=list)
    # Set when the moderation gate blocked the run. Downstream code sets
    # the Execution.failure_code = "MODERATION_BLOCKED" off this.
    moderation_blocked: bool = False
    moderation_block_source: str = ""  # pre_llm | post_llm

    def get_trace_summary(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.node_traces]


class AgentExecutor:
    def __init__(
        self,
        llm_router: LLMRouter,
        tool_registry: ToolRegistry,
        system_prompt: str = "",
        model: str = "claude-sonnet-4-5-20250929",
        temperature: float = 0.7,
        max_iterations: int = MAX_ITERATIONS,
        max_tokens: int = 4096,
        cache: Any | None = None,
        agent_id: str = "",
        sandbox: ExecutionSandbox | None = None,
        moderation_gate: GateConfig | None = None,
        execution_id: str = "",
        tool_config: dict[str, dict[str, Any]] | None = None,
        asset_schemas: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.llm_router = llm_router
        self.tool_registry = tool_registry
        if tool_config:
            tool_registry.apply_tool_config(tool_config, asset_schemas=asset_schemas or {})
        self.system_prompt = system_prompt
        self.model = model
        self.temperature = temperature
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.cache = cache
        self.agent_id = agent_id
        # Policy-gate snapshot. None = no gate (backward-compatible
        # default); callers with an active ModerationPolicy build a
        # GateConfig in the API layer and pass it in.
        self.moderation_gate = moderation_gate
        self.execution_id = execution_id
        if sandbox is None:
            from engine.sandbox import SandboxPolicy
            base_timeout = 300
            base_tool_calls = 50
            if max_iterations > MAX_ITERATIONS:
                scale = max(1.0, max_iterations / MAX_ITERATIONS)
                policy = SandboxPolicy(
                    timeout_seconds=int(base_timeout * scale),
                    max_tool_calls=int(base_tool_calls * scale),
                )
                sandbox = ExecutionSandbox(policy=policy)
            else:
                sandbox = ExecutionSandbox()
        self.sandbox = sandbox

    async def invoke(self, input_message: str) -> ExecutionResult:
        start = time.monotonic()
        self.sandbox.start()

        # Runs once on the user-supplied input_message. On block we bail
        # before paying a single LLM token. On redact the masked text
        # becomes the actual prompt so the LLM never sees the raw span.
        if self.moderation_gate is not None:
            try:
                input_message, _mod_pre = await moderation_check(
                    input_message,
                    source="pre_llm",
                    config=self.moderation_gate,
                    execution_id=self.execution_id,
                )
                moderation_decisions_total.labels(
                    source="pre_llm", outcome=_mod_pre.outcome,
                ).inc()
            except ModerationBlocked as mb:
                moderation_decisions_total.labels(
                    source="pre_llm", outcome="blocked",
                ).inc()
                duration = int((time.monotonic() - start) * 1000)
                return ExecutionResult(
                    output=(
                        "Request blocked by moderation policy. "
                        f"Categories: {', '.join(mb.decision.triggered_categories[:5]) or 'n/a'}."
                    ),
                    duration_ms=duration,
                    model=self.model,
                    moderation_blocked=True,
                    moderation_block_source="pre_llm",
                )

        messages: list[dict[str, Any]] = [{"role": "user", "content": input_message}]
        tools = self.tool_registry.list_all()
        all_tool_calls: list[dict[str, Any]] = []
        node_traces: list[NodeTrace] = []
        total_input = 0
        total_output = 0
        total_cost = 0.0
        # Per-provider subtotals for the executions row split.
        provider_costs: dict[str, float] = {
            "anthropic": 0.0, "openai": 0.0, "google": 0.0, "other": 0.0,
        }
        node_counter = 0

        node_traces.append(NodeTrace(
            node_id=f"node_{node_counter}",
            node_type="user_input",
            iteration=0,
            timestamp_ms=int(start * 1000),
            input_data={"message": input_message[:500]},
            output_data={},
        ))
        node_counter += 1

        if self.cache:
            cache_result = await self.cache.check(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                temperature=self.temperature,
                system=self.system_prompt or None,
                agent_id=self.agent_id,
            )
            if cache_result.hit and cache_result.response:
                duration = int((time.monotonic() - start) * 1000)
                agent_execution_duration_seconds.observe(duration / 1000)
                return ExecutionResult(
                    output=cache_result.response.get("content", ""),
                    duration_ms=duration,
                    model=cache_result.response.get("model", self.model),
                    cache_hit=cache_result.layer,
                    node_traces=node_traces,
                )

        for iteration in range(self.max_iterations):
            if not self.sandbox.check_timeout():
                duration = int((time.monotonic() - start) * 1000)
                agent_execution_duration_seconds.observe(duration / 1000)
                return ExecutionResult(
                    output="Execution timed out.",
                    input_tokens=total_input,
                    output_tokens=total_output,
                    cost=total_cost,
                    duration_ms=duration,
                    tool_calls=all_tool_calls,
                    model=self.model,
                    node_traces=node_traces,
                )

            # Anthropic forces streaming when max_tokens could breach the
            # 10-minute soft deadline. Whenever we're on Claude with a big
            # max_tokens we call through the streaming API and collapse the
            # event stream back into an LLMResponse.
            _need_stream = bool(self.model.startswith("claude") and (self.max_tokens or 0) > 8192)
            complete_kwargs: dict[str, Any] = {
                "messages": messages,
                "system": self.system_prompt or None,
                "tools": tools if tools else None,
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": _need_stream,
            }

            if self.cache and self.cache.prompt_optimizer and self.model.startswith("claude"):
                optimized = self.cache.prompt_optimizer.optimize(
                    messages=messages,
                    system=self.system_prompt or None,
                    tools=tools if tools else None,
                )
                if "system" in optimized:
                    complete_kwargs["system"] = optimized["system"]
                if "tools" in optimized:
                    complete_kwargs["tools"] = optimized["tools"]

            llm_start = time.monotonic()
            if _need_stream:
                # Collapse the StreamEvent generator into an LLMResponse.
                stream_gen = await self.llm_router.complete(**complete_kwargs)
                full_text = ""
                accum_tool_calls: list[dict[str, Any]] = []
                done_meta: dict[str, Any] = {}
                async for ev in stream_gen:  # type: ignore[union-attr]
                    if ev.event == "token":
                        full_text += ev.data
                    elif ev.event == "tool_call":
                        accum_tool_calls.append({
                            "id": ev.data.get("id", ""),
                            "name": ev.data.get("name", ""),
                            "arguments": ev.data.get("arguments", {}),
                        })
                    elif ev.event == "done":
                        done_meta = ev.data
                resp = LLMResponse(
                    content=full_text,
                    model=self.model,
                    input_tokens=done_meta.get("input_tokens", 0),
                    output_tokens=done_meta.get("output_tokens", 0),
                    cost=done_meta.get("cost", 0.0),
                    latency_ms=done_meta.get("latency_ms", int((time.monotonic() - llm_start) * 1000)),
                    tool_calls=accum_tool_calls,
                    stop_reason=done_meta.get("stop_reason"),
                )
            else:
                resp = await self.llm_router.complete(**complete_kwargs)
                assert isinstance(resp, LLMResponse)
            llm_duration = int((time.monotonic() - llm_start) * 1000)

            total_input += resp.input_tokens
            total_output += resp.output_tokens
            total_cost += resp.cost
            # Split by provider so the executions row can show a
            # per-provider breakdown (critical when a call fell back
            # from Anthropic to OpenAI).
            _prov = _provider_key(resp.model)
            provider_costs[_prov] = provider_costs.get(_prov, 0.0) + resp.cost

            node_traces.append(NodeTrace(
                node_id=f"node_{node_counter}",
                node_type="llm_call",
                iteration=iteration,
                timestamp_ms=int(llm_start * 1000),
                duration_ms=llm_duration,
                input_data={"message_count": len(messages), "tools_available": len(tools)},
                output_data={
                    "content_preview": resp.content[:300] if resp.content else "",
                    "tool_calls": len(resp.tool_calls),
                    "input_tokens": resp.input_tokens,
                    "output_tokens": resp.output_tokens,
                },
                metadata={"model": resp.model, "cost": round(resp.cost, 6)},
            ))
            node_counter += 1

            if not resp.tool_calls:
                duration = int((time.monotonic() - start) * 1000)
                agent_execution_duration_seconds.observe(duration / 1000)

                # Final model response before it leaves the agent. Same
                # block/redact/flag semantics as pre-LLM. We don't write
                # a redacted response to the cache because a different
                # tenant might have a different policy.
                output_text = resp.content
                if self.moderation_gate is not None:
                    try:
                        output_text, _mod_post = await moderation_check(
                            output_text,
                            source="post_llm",
                            config=self.moderation_gate,
                            execution_id=self.execution_id,
                        )
                        moderation_decisions_total.labels(
                            source="post_llm", outcome=_mod_post.outcome,
                        ).inc()
                    except ModerationBlocked as mb:
                        moderation_decisions_total.labels(
                            source="post_llm", outcome="blocked",
                        ).inc()
                        return ExecutionResult(
                            output=(
                                "Response blocked by moderation policy. "
                                f"Categories: {', '.join(mb.decision.triggered_categories[:5]) or 'n/a'}."
                            ),
                            input_tokens=total_input,
                            output_tokens=total_output,
                            cost=total_cost,
                            duration_ms=duration,
                            tool_calls=all_tool_calls,
                            model=resp.model,
                            node_traces=node_traces,
                            moderation_blocked=True,
                            moderation_block_source="post_llm",
                        )

                if self.cache and output_text == resp.content:
                    # Only cache un-redacted responses — redacted output
                    # depends on tenant policy and would leak to other
                    # tenants sharing the same cache key.
                    response_data = {
                        "content": resp.content,
                        "model": resp.model,
                        "input_tokens": resp.input_tokens,
                        "output_tokens": resp.output_tokens,
                    }
                    await self.cache.store(
                        model=self.model,
                        messages=messages,
                        tools=tools if tools else None,
                        temperature=self.temperature,
                        response=response_data,
                        agent_id=self.agent_id,
                    )

                return ExecutionResult(
                    output=output_text,
                    input_tokens=total_input,
                    output_tokens=total_output,
                    cost=total_cost,
                    anthropic_cost=provider_costs.get("anthropic", 0.0),
                    openai_cost=provider_costs.get("openai", 0.0),
                    google_cost=provider_costs.get("google", 0.0),
                    other_cost=provider_costs.get("other", 0.0),
                    duration_ms=duration,
                    tool_calls=all_tool_calls,
                    model=resp.model,
                    node_traces=node_traces,
                )

            assistant_content: list[dict[str, Any]] = []
            if resp.content:
                assistant_content.append({"type": "text", "text": resp.content})
            for tc in resp.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["arguments"],
                })
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results_content: list[dict[str, Any]] = []
            for tc in resp.tool_calls:
                all_tool_calls.append(tc)

                if not self.sandbox.check_tool_call():
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": "Tool call limit exceeded",
                        "is_error": True,
                    })
                    continue

                tool = self.tool_registry.get(tc["name"])
                if tool:
                    tool_start = time.monotonic()
                    result = await tool.execute(tc["arguments"])
                    tool_dur = int((time.monotonic() - tool_start) * 1000)
                    tool_execution_duration_seconds.labels(tool_name=tc["name"]).observe(tool_dur / 1000)

                    node_traces.append(NodeTrace(
                        node_id=f"node_{node_counter}",
                        node_type="tool_call",
                        iteration=iteration,
                        timestamp_ms=int(tool_start * 1000),
                        duration_ms=tool_dur,
                        input_data={"tool": tc["name"], "arguments": tc["arguments"]},
                        output_data={
                            "content_preview": result.content[:500],
                            "is_error": result.is_error,
                            "metadata": result.metadata,
                        },
                    ))
                    node_counter += 1
                else:
                    result = ToolResult(content=f"Unknown tool: {tc['name']}", is_error=True)

                self.sandbox.check_output_size(result.content)

                # Truncate large tool results to prevent context overflow
                context_content = _truncate_tool_result(result.content)
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": context_content,
                    "is_error": result.is_error,
                })

            messages.append({"role": "user", "content": tool_results_content})

            # Check if accumulated context is approaching the limit
            est_tokens = _estimate_messages_tokens(messages)
            if est_tokens > CONTEXT_TOKEN_BUDGET:
                logger.warning("Context budget exceeded (%d est. tokens), stopping execution", est_tokens)
                duration = int((time.monotonic() - start) * 1000)
                return ExecutionResult(
                    output=resp.content or "Execution stopped: context window limit reached. The gathered information may be incomplete.",
                    input_tokens=total_input,
                    output_tokens=total_output,
                    cost=total_cost,
                    duration_ms=duration,
                    tool_calls=all_tool_calls,
                    model=resp.model,
                    node_traces=node_traces,
                )

        duration = int((time.monotonic() - start) * 1000)
        agent_execution_duration_seconds.observe(duration / 1000)
        return ExecutionResult(
            output="Max iterations reached.",
            input_tokens=total_input,
            output_tokens=total_output,
            cost=total_cost,
            anthropic_cost=provider_costs.get("anthropic", 0.0),
            openai_cost=provider_costs.get("openai", 0.0),
            google_cost=provider_costs.get("google", 0.0),
            other_cost=provider_costs.get("other", 0.0),
            duration_ms=duration,
            tool_calls=all_tool_calls,
            model=self.model,
            node_traces=node_traces,
        )

    async def stream(self, input_message: str) -> AsyncGenerator[ExecutionEvent, None]:
        start = time.monotonic()
        agent_active_streams.inc()
        self.sandbox.start()

        # Pre-LLM moderation gate. On block we emit a synthetic `done`
        # event with error fields set and return without spending any
        # LLM tokens. On redact the masked text becomes the prompt.
        if self.moderation_gate is not None:
            try:
                input_message, _mod_pre = await moderation_check(
                    input_message,
                    source="pre_llm",
                    config=self.moderation_gate,
                    execution_id=self.execution_id,
                )
                moderation_decisions_total.labels(
                    source="pre_llm", outcome=_mod_pre.outcome,
                ).inc()
            except ModerationBlocked as mb:
                moderation_decisions_total.labels(
                    source="pre_llm", outcome="blocked",
                ).inc()
                duration = int((time.monotonic() - start) * 1000)
                agent_active_streams.dec()
                yield ExecutionEvent(event="token", data=(
                    "Request blocked by moderation policy. "
                    f"Categories: {', '.join(mb.decision.triggered_categories[:5]) or 'n/a'}."
                ))
                yield ExecutionEvent(
                    event="done",
                    data={
                        "total_tokens": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost": 0.0,
                        "duration_ms": duration,
                        "model": self.model,
                        "error": "moderation_blocked",
                        "moderation_blocked": True,
                        "moderation_block_source": "pre_llm",
                    },
                )
                return

        messages: list[dict[str, Any]] = [{"role": "user", "content": input_message}]
        tools = self.tool_registry.list_all()
        all_tool_calls: list[dict[str, Any]] = []
        total_input = 0
        total_output = 0
        total_cost = 0.0

        if self.cache:
            cache_result = await self.cache.check(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                temperature=self.temperature,
                system=self.system_prompt or None,
                agent_id=self.agent_id,
            )
            if cache_result.hit and cache_result.response:
                cached_content = cache_result.response.get("content", "")
                yield ExecutionEvent(event="token", data=cached_content)
                duration = int((time.monotonic() - start) * 1000)
                agent_execution_duration_seconds.observe(duration / 1000)
                agent_active_streams.dec()
                yield ExecutionEvent(
                    event="done",
                    data={
                        "total_tokens": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost": 0.0,
                        "duration_ms": duration,
                        "model": self.model,
                        "cache_hit": cache_result.layer,
                    },
                )
                return

        for iteration in range(self.max_iterations):
            if not self.sandbox.check_timeout():
                duration = int((time.monotonic() - start) * 1000)
                agent_execution_duration_seconds.observe(duration / 1000)
                agent_active_streams.dec()
                yield ExecutionEvent(
                    event="done",
                    data={
                        "total_tokens": total_input + total_output,
                        "input_tokens": total_input,
                        "output_tokens": total_output,
                        "cost": round(total_cost, 6),
                        "duration_ms": duration,
                        "model": self.model,
                        "error": "Execution timed out",
                    },
                )
                return

            stream_resp = await self.llm_router.complete(
                messages=messages,
                system=self.system_prompt or None,
                tools=tools if tools else None,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            )

            full_text = ""
            iteration_tool_calls: list[dict[str, Any]] = []
            done_data: dict[str, Any] = {}

            async for event in stream_resp:  # type: ignore[union-attr]
                if event.event == "token":
                    full_text += event.data
                    yield ExecutionEvent(event="token", data=event.data)
                elif event.event == "tool_call":
                    iteration_tool_calls.append(event.data)
                    yield ExecutionEvent(event="tool_call", data=event.data)
                elif event.event == "done":
                    done_data = event.data

            total_input += done_data.get("input_tokens", 0)
            total_output += done_data.get("output_tokens", 0)
            total_cost += done_data.get("cost", 0.0)

            stream_tool_calls = done_data.get("tool_calls", [])

            if not stream_tool_calls:
                duration = int((time.monotonic() - start) * 1000)
                agent_execution_duration_seconds.observe(duration / 1000)
                agent_active_streams.dec()

                if self.cache:
                    response_data = {
                        "content": full_text,
                        "model": self.model,
                        "input_tokens": total_input,
                        "output_tokens": total_output,
                    }
                    await self.cache.store(
                        model=self.model,
                        messages=messages,
                        tools=tools if tools else None,
                        temperature=self.temperature,
                        response=response_data,
                        agent_id=self.agent_id,
                    )

                yield ExecutionEvent(
                    event="done",
                    data={
                        "total_tokens": total_input + total_output,
                        "input_tokens": total_input,
                        "output_tokens": total_output,
                        "cost": round(total_cost, 6),
                        "duration_ms": duration,
                        "model": self.model,
                    },
                )
                return

            assistant_content: list[dict[str, Any]] = []
            if full_text:
                assistant_content.append({"type": "text", "text": full_text})
            for tc in stream_tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["arguments"],
                })
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results_content: list[dict[str, Any]] = []
            for tc in stream_tool_calls:
                all_tool_calls.append(tc)

                if not self.sandbox.check_tool_call():
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": "Tool call limit exceeded",
                        "is_error": True,
                    })
                    continue

                tool = self.tool_registry.get(tc["name"])
                if tool:
                    tool_start = time.monotonic()
                    result = await tool.execute(tc["arguments"])
                    tool_dur = int((time.monotonic() - tool_start) * 1000)
                    tool_execution_duration_seconds.labels(tool_name=tc["name"]).observe(tool_dur / 1000)
                else:
                    result = ToolResult(content=f"Unknown tool: {tc['name']}", is_error=True)
                    tool_dur = 0

                self.sandbox.check_output_size(result.content)

                yield ExecutionEvent(
                    event="tool_result",
                    data={"name": tc["name"], "result": result.content},
                )

                yield ExecutionEvent(
                    event="node_trace",
                    data={
                        "node_type": "tool_call",
                        "tool": tc["name"],
                        "duration_ms": tool_dur,
                        "input": tc["arguments"],
                        "output_preview": result.content[:500],
                        "is_error": result.is_error,
                        "metadata": result.metadata,
                    },
                )

                # Truncate large tool results to prevent context overflow
                context_content = _truncate_tool_result(result.content)
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": context_content,
                    "is_error": result.is_error,
                })

            messages.append({"role": "user", "content": tool_results_content})

            # Check if accumulated context is approaching the limit
            est_tokens = _estimate_messages_tokens(messages)
            if est_tokens > CONTEXT_TOKEN_BUDGET:
                logger.warning("Context budget exceeded (%d est. tokens), stopping stream", est_tokens)
                yield ExecutionEvent(
                    event="token",
                    data={"content": "\n\n*Context limit reached — returning results gathered so far.*"},
                )
                break

        duration = int((time.monotonic() - start) * 1000)
        agent_execution_duration_seconds.observe(duration / 1000)
        agent_active_streams.dec()
        yield ExecutionEvent(
            event="done",
            data={
                "total_tokens": total_input + total_output,
                "input_tokens": total_input,
                "output_tokens": total_output,
                "cost": round(total_cost, 6),
                "duration_ms": duration,
                "model": self.model,
            },
        )


_TOOL_CLASSES_LOADED = False
_TOOL_CLASSES: dict[str, type] = {}
_CONTEXT_TOOL_FACTORIES: dict[str, Any] = {}


def _ensure_tool_classes() -> None:
    """Import all tool classes once and cache them at module level."""
    global _TOOL_CLASSES_LOADED, _TOOL_CLASSES
    if _TOOL_CLASSES_LOADED:
        return
    from engine.tools.api_connector import ApiConnectorTool
    from engine.tools.calculator import CalculatorTool
    from engine.tools.code_executor import CodeExecutorTool
    from engine.tools.csv_analyzer import CsvAnalyzerTool
    from engine.tools.current_time import CurrentTimeTool
    from engine.tools.data_exporter import DataExporterTool
    from engine.tools.date_calculator import DateCalculatorTool
    from engine.tools.document_extractor import DocumentExtractorTool
    from engine.tools.file_reader import FileReaderTool
    from engine.tools.financial_calculator import FinancialCalculatorTool
    from engine.tools.http_client import HttpClientTool
    from engine.tools.json_transformer import JsonTransformerTool
    from engine.tools.market_data import MarketDataTool
    from engine.tools.presentation_analyzer import PresentationAnalyzerTool
    from engine.tools.regex_extractor import RegexExtractorTool
    from engine.tools.risk_analyzer import RiskAnalyzerTool
    from engine.tools.spreadsheet_analyzer import SpreadsheetAnalyzerTool
    from engine.tools.text_analyzer import TextAnalyzerTool
    from engine.tools.unit_converter import UnitConverterTool
    from engine.tools.web_search import WebSearchTool
    from engine.tools.llm_call import LLMCallTool
    from engine.tools.email_sender import EmailSenderTool
    from engine.tools.data_merger import DataMergerTool
    from engine.tools.github_tool import GitHubTool
    from engine.tools.agent_step import AgentStepTool
    from engine.tools.sub_pipeline import SubPipelineTool
    from engine.tools.memory_store import MemoryStoreTool
    from engine.tools.memory_recall import MemoryRecallTool
    from engine.tools.memory_forget import MemoryForgetTool
    from engine.tools.human_approval import HumanApprovalTool
    from engine.tools.database_query import DatabaseQueryTool
    from engine.tools.database_writer import DatabaseWriterTool
    from engine.tools.cloud_storage import CloudStorageTool
    from engine.tools.image_analyzer import ImageAnalyzerTool
    from engine.tools.file_system import FileSystemTool
    from engine.tools.schema_validator import SchemaValidatorTool
    from engine.tools.structured_analyzer import StructuredAnalyzerTool
    from engine.tools.speech_to_text import SpeechToTextTool
    from engine.tools.text_to_speech import TextToSpeechTool
    from engine.tools.integration_hub import IntegrationHubTool
    from engine.tools.pii_redactor import PIIRedactorTool
    from engine.tools.time_series_analyzer import TimeSeriesAnalyzerTool
    from engine.tools.event_stream import (
        EventBufferTool, RedisStreamConsumerTool,
        RedisStreamPublisherTool, KafkaConsumerTool,
    )
    from engine.tools.llm_route import LLMRouteTool
    from engine.tools.tavily_search import TavilySearchTool
    from engine.tools.news_feed import NewsFeedTool
    from engine.tools.academic_search import AcademicSearchTool
    from engine.tools.yahoo_finance import YahooFinanceTool
    from engine.tools.entso_e_tool import EntsoETool
    from engine.tools.ember_tool import EmberClimateTool
    from engine.tools.ecb_rates_tool import ECBRatesTool
    from engine.tools.graph_explorer_tool import GraphExplorerTool
    from engine.tools.schema_portfolio_tool import SchemaPortfolioTool
    # New tools (Tier 1/2/3 ecosystem expansion)
    from engine.tools.weather import WeatherTool
    from engine.tools.geocoding import GeocodingTool
    from engine.tools.world_bank import WorldBankTool
    from engine.tools.crypto_market import CryptoMarketTool
    from engine.tools.fred_economic import FredEconomicTool
    from engine.tools.gov_data_us import GovDataUSTool
    from engine.tools.patents_trademarks import PatentsTrademarksTool
    from engine.tools.mermaid_diagram import MermaidDiagramTool
    from engine.tools.semantic_diff import SemanticDiffTool
    from engine.tools.address_normalize import AddressNormalizeTool
    from engine.tools.translation import TranslationTool
    from engine.tools.plotly_chart import PlotlyChartTool
    from engine.tools.twilio_sms import TwilioSmsTool
    from engine.tools.browser_automation import BrowserAutomationTool
    from engine.tools.sandboxed_job import SandboxedJobTool
    from engine.tools.cloud_cost import CloudCostTool
    from engine.tools.zapier_pass_through import ZapierPassThroughTool

    _TOOL_CLASSES.update({
        "web_search": WebSearchTool, "calculator": CalculatorTool,
        "file_reader": FileReaderTool, "current_time": CurrentTimeTool,
        "document_extractor": DocumentExtractorTool, "csv_analyzer": CsvAnalyzerTool,
        "financial_calculator": FinancialCalculatorTool, "risk_analyzer": RiskAnalyzerTool,
        "market_data": MarketDataTool, "json_transformer": JsonTransformerTool,
        "text_analyzer": TextAnalyzerTool, "http_client": HttpClientTool,
        "code_executor": CodeExecutorTool, "date_calculator": DateCalculatorTool,
        "regex_extractor": RegexExtractorTool, "unit_converter": UnitConverterTool,
        "spreadsheet_analyzer": SpreadsheetAnalyzerTool,
        "presentation_analyzer": PresentationAnalyzerTool,
        "data_exporter": DataExporterTool, "api_connector": ApiConnectorTool,
        "llm_call": LLMCallTool, "email_sender": EmailSenderTool,
        "data_merger": DataMergerTool, "github_tool": GitHubTool,
        "agent_step": AgentStepTool, "sub_pipeline": SubPipelineTool,
        "database_query": DatabaseQueryTool, "database_writer": DatabaseWriterTool,
        "cloud_storage": CloudStorageTool, "image_analyzer": ImageAnalyzerTool,
        "file_system": FileSystemTool, "schema_validator": SchemaValidatorTool,
        "structured_analyzer": StructuredAnalyzerTool,
        "speech_to_text": SpeechToTextTool, "text_to_speech": TextToSpeechTool,
        "integration_hub": IntegrationHubTool, "pii_redactor": PIIRedactorTool,
        "time_series_analyzer": TimeSeriesAnalyzerTool,
        "event_buffer": EventBufferTool, "redis_stream_consumer": RedisStreamConsumerTool,
        "redis_stream_publisher": RedisStreamPublisherTool,
        "kafka_consumer": KafkaConsumerTool, "llm_route": LLMRouteTool,
        "tavily_search": TavilySearchTool, "news_feed": NewsFeedTool,
        "academic_search": AcademicSearchTool, "yahoo_finance": YahooFinanceTool,
        "entso_e": EntsoETool, "ember_climate": EmberClimateTool,
        "ecb_rates": ECBRatesTool,
        "weather": WeatherTool, "geocoding": GeocodingTool,
        "world_bank": WorldBankTool, "crypto_market": CryptoMarketTool,
        "fred_economic": FredEconomicTool, "gov_data_us": GovDataUSTool,
        "patents_trademarks": PatentsTrademarksTool,
        "mermaid_diagram": MermaidDiagramTool, "semantic_diff": SemanticDiffTool,
        "address_normalize": AddressNormalizeTool, "translation": TranslationTool,
        "plotly_chart": PlotlyChartTool, "twilio_sms": TwilioSmsTool,
        "browser_automation": BrowserAutomationTool,
        "cloud_cost": CloudCostTool,  # sandboxed_job moved to _CONTEXT_TOOL_FACTORIES (needs tenant_id)
        "zapier_pass_through": ZapierPassThroughTool,
    })
    # Moderation tool — stateless, uses OPENAI_API_KEY env.
    from engine.tools.moderation import ModerationVetTool
    _TOOL_CLASSES["moderation_vet"] = ModerationVetTool
    from engine.tools.graph_builder import GraphBuilderTool
    _TOOL_CLASSES["graph_builder"] = GraphBuilderTool
    from engine.tools.weather_simulator import WeatherSimulatorTool
    _TOOL_CLASSES["weather_simulator"] = WeatherSimulatorTool
    from engine.tools.sentiment_analyzer import SentimentAnalyzerTool
    _TOOL_CLASSES["sentiment_analyzer"] = SentimentAnalyzerTool
    from engine.tools.scenario_planner import ScenarioPlannerTool
    _TOOL_CLASSES["scenario_planner"] = ScenarioPlannerTool
    from engine.tools.document_parser import DocumentParserTool
    _TOOL_CLASSES["document_parser"] = DocumentParserTool
    from engine.tools.structured_extractor import StructuredExtractorTool
    _TOOL_CLASSES["structured_extractor"] = StructuredExtractorTool
    from engine.tools.credit_risk import CreditRiskTool
    _TOOL_CLASSES["credit_risk"] = CreditRiskTool
    # KYC / AML compliance tool suite
    from engine.tools.sanctions_screening import SanctionsScreeningTool
    from engine.tools.pep_screening import PEPScreeningTool
    from engine.tools.adverse_media import AdverseMediaTool
    from engine.tools.ubo_discovery import UBODiscoveryTool
    from engine.tools.country_risk_index import CountryRiskIndexTool
    from engine.tools.legal_existence import LegalExistenceVerifierTool
    from engine.tools.kyc_scorer import KYCScorerTool
    from engine.tools.regulatory_enforcement import RegulatoryEnforcementTool
    _TOOL_CLASSES.update({
        "sanctions_screening": SanctionsScreeningTool,
        "pep_screening": PEPScreeningTool,
        "adverse_media": AdverseMediaTool,
        "ubo_discovery": UBODiscoveryTool,
        "country_risk_index": CountryRiskIndexTool,
        "legal_existence_verifier": LegalExistenceVerifierTool,
        "kyc_scorer": KYCScorerTool,
        "regulatory_enforcement": RegulatoryEnforcementTool,
    })
    # Store context tool factories (need constructor args)
    from engine.tools.ml_model_tool import MLModelTool
    from engine.tools.meeting_join import MeetingJoinTool
    from engine.tools.meeting_listen import MeetingListenTool
    from engine.tools.meeting_speak import MeetingSpeakTool
    from engine.tools.meeting_post_chat import MeetingPostChatTool
    from engine.tools.meeting_leave import MeetingLeaveTool
    from engine.tools.persona_rag import PersonaRagTool
    from engine.tools.defer_to_human import DeferToHumanTool
    from engine.tools.scope_gate import ScopeGateTool
    from engine.tools.code_asset import CodeAssetTool
    _CONTEXT_TOOL_FACTORIES.update({
        "memory_store": MemoryStoreTool, "memory_recall": MemoryRecallTool,
        "memory_forget": MemoryForgetTool, "human_approval": HumanApprovalTool,
        "ml_model": MLModelTool,
        "sandboxed_job": SandboxedJobTool,
        "code_asset": CodeAssetTool,
        "meeting_join": MeetingJoinTool,
        "meeting_listen": MeetingListenTool,
        "meeting_speak": MeetingSpeakTool,
        "meeting_post_chat": MeetingPostChatTool,
        "meeting_leave": MeetingLeaveTool,
        "persona_rag": PersonaRagTool,
        "defer_to_human": DeferToHumanTool,
        "scope_gate": ScopeGateTool,
    })
    _TOOL_CLASSES_LOADED = True


async def resolve_asset_schemas(
    tool_config: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """For every tool with parameter_defaults that points at an uploaded"""
    out: dict[str, dict[str, Any]] = {}
    if not tool_config:
        return out
    try:
        import os as _os
        from sqlalchemy import text as _sql_text
        from sqlalchemy.ext.asyncio import create_async_engine as _ace

        db_url = _os.environ.get("DATABASE_URL", "")
        if not db_url:
            return out
        # The runtime already targets asyncpg — no dialect rewrite needed.
        engine = _ace(db_url, pool_pre_ping=True, pool_size=1)
        try:
            async with engine.begin() as conn:
                for tool_name, tc in (tool_config or {}).items():
                    defaults = (tc or {}).get("parameter_defaults") or {}
                    if not defaults:
                        continue
                    asset_id = defaults.get("code_asset_id")
                    model_id = defaults.get("model_id") or defaults.get("ml_model_id")
                    row = None
                    if asset_id:
                        r = await conn.execute(_sql_text(
                            "SELECT input_schema FROM code_assets "
                            "WHERE id = CAST(:id AS uuid)"
                        ), {"id": str(asset_id)})
                        row = r.first()
                    elif model_id:
                        r = await conn.execute(_sql_text(
                            "SELECT input_schema FROM ml_models "
                            "WHERE id = CAST(:id AS uuid)"
                        ), {"id": str(model_id)})
                        row = r.first()
                    if row and row[0]:
                        out[tool_name] = {"input_schema": row[0]}
        finally:
            await engine.dispose()
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).warning(
            "resolve_asset_schemas failed (LLM will see generic input schema): %s", e,
        )
    return out


def build_tool_registry(
    tool_names: list[str],
    kb_ids: list[str] | None = None,
    *,
    agent_id: str = "",
    tenant_id: str = "",
    execution_id: str = "",
    agent_name: str = "",
    db_url: str = "",
    acting_subject: dict | None = None,
    model_config: dict | None = None,
) -> ToolRegistry:
    _ensure_tool_classes()

    available = _TOOL_CLASSES

    # Enterprise tools that need execution context (constructed per-call)
    MemoryStoreCls = _CONTEXT_TOOL_FACTORIES.get("memory_store")
    MemoryRecallCls = _CONTEXT_TOOL_FACTORIES.get("memory_recall")
    MemoryForgetCls = _CONTEXT_TOOL_FACTORIES.get("memory_forget")
    HumanApprovalCls = _CONTEXT_TOOL_FACTORIES.get("human_approval")

    context_tools: dict[str, Any] = {}
    if MemoryStoreCls:
        context_tools["memory_store"] = lambda: MemoryStoreCls(
            db_url=db_url, agent_id=agent_id, tenant_id=tenant_id
        )
    if MemoryRecallCls:
        context_tools["memory_recall"] = lambda: MemoryRecallCls(
            db_url=db_url, agent_id=agent_id, tenant_id=tenant_id
        )
    if MemoryForgetCls:
        context_tools["memory_forget"] = lambda: MemoryForgetCls(
            db_url=db_url, agent_id=agent_id, tenant_id=tenant_id
        )
    if HumanApprovalCls:
        context_tools["human_approval"] = lambda: HumanApprovalCls(
            execution_id=execution_id,
            tenant_id=tenant_id,
            agent_name=agent_name,
        )
    MLModelCls = _CONTEXT_TOOL_FACTORIES.get("ml_model")
    if MLModelCls:
        context_tools["ml_model"] = lambda: MLModelCls(
            db_url=db_url, tenant_id=tenant_id,
        )
    SandboxCls = _CONTEXT_TOOL_FACTORIES.get("sandboxed_job")
    if SandboxCls:
        # Tenant-scoped Redis overrides for enabled / allow_network / allowed_images
        # are read at execute time; falls back to env vars when nothing is set.
        import os as _os
        _redis_url = _os.environ.get("REDIS_URL", "")
        context_tools["sandboxed_job"] = lambda: SandboxCls(
            tenant_id=tenant_id, redis_url=_redis_url,
        )
    CodeAssetCls = _CONTEXT_TOOL_FACTORIES.get("code_asset")
    if CodeAssetCls:
        import os as _os2
        _redis_url2 = _os2.environ.get("REDIS_URL", "")
        context_tools["code_asset"] = lambda: CodeAssetCls(
            tenant_id=tenant_id, redis_url=_redis_url2, db_url=db_url,
        )

    # ── Meeting + persona + safety tools — all need execution context.
    # Extract user_id from acting_subject if available so persona_rag's
    # "self" scope + defer_to_human's notifications land on the right user.
    _user_id = ""
    if acting_subject and isinstance(acting_subject, dict):
        _user_id = str(acting_subject.get("user_id") or acting_subject.get("sub") or "")
    for _tool_name in (
        "meeting_join", "meeting_listen", "meeting_speak",
        "meeting_post_chat", "meeting_leave",
    ):
        _Cls = _CONTEXT_TOOL_FACTORIES.get(_tool_name)
        if not _Cls:
            continue
        if _tool_name == "meeting_join":
            # MeetingJoinTool needs the wider set for scope + user tracking
            context_tools[_tool_name] = lambda Cls=_Cls: Cls(
                execution_id=execution_id, tenant_id=tenant_id,
                user_id=_user_id, agent_id=agent_id,
            )
        else:
            context_tools[_tool_name] = lambda Cls=_Cls: Cls(execution_id=execution_id)
    PersonaRagCls = _CONTEXT_TOOL_FACTORIES.get("persona_rag")
    if PersonaRagCls:
        context_tools["persona_rag"] = lambda: PersonaRagCls(
            kb_ids=kb_ids or [], tenant_id=tenant_id,
            user_id=_user_id, execution_id=execution_id,
        )
    DeferCls = _CONTEXT_TOOL_FACTORIES.get("defer_to_human")
    if DeferCls:
        context_tools["defer_to_human"] = lambda: DeferCls(
            execution_id=execution_id, tenant_id=tenant_id, user_id=_user_id,
        )
    ScopeGateCls = _CONTEXT_TOOL_FACTORIES.get("scope_gate")
    if ScopeGateCls:
        context_tools["scope_gate"] = lambda: ScopeGateCls(execution_id=execution_id)

    registry = ToolRegistry()
    for name in tool_names:
        # Check context tools first (need constructor args)
        if name in context_tools:
            registry.register(context_tools[name]())
        elif name in available:
            registry.register(available[name]())
        else:
            logger.warning("Unknown tool requested: %s", name)

    # Each tool is tenant-scoped; if the agent's model_config carries
    # `atlas_graphs: ["uuid", ...]`, that list further restricts which
    # graphs the tool can read. With no list, the agent sees every
    # atlas in its tenant — same boundary as every other tenant tool.
    atlas_allow = list((model_config or {}).get("atlas_graphs") or []) if isinstance(model_config, dict) else []
    atlas_tool_requested = any(name.startswith("atlas_") for name in tool_names)
    if atlas_tool_requested:
        try:
            from engine.tools.atlas_tools import ATLAS_TOOL_NAMES
            for name in tool_names:
                cls = ATLAS_TOOL_NAMES.get(name)
                if cls and name not in registry.names():
                    registry.register(cls(
                        tenant_id=str(tenant_id),
                        agent_id=str(agent_id),
                        allowed_graph_ids=atlas_allow,
                    ))
                    logger.info("Registered %s with allow=%s", name, atlas_allow or "<all-tenant>")
        except Exception as e:
            logger.error("Failed to register atlas tools: %s", e)

    if kb_ids:
        # Register hybrid knowledge search (graph + vector) as primary
        try:
            from engine.tools.knowledge_search import KnowledgeSearchTool
            registry.register(KnowledgeSearchTool(
                kb_ids=kb_ids, tenant_id=tenant_id, agent_id=agent_id,
            ))
        except ImportError:
            pass
        # Also register vector search as fallback
        from engine.tools.vector_search import VectorSearchTool
        registry.register(VectorSearchTool(kb_ids=kb_ids))
        # Register knowledge store for writing content to knowledge base
        try:
            from engine.tools.knowledge_store import KnowledgeStoreTool
            registry.register(KnowledgeStoreTool(kb_ids=kb_ids, tenant_id=tenant_id))
        except ImportError:
            pass

    logger.info("build_tool_registry: acting_subject=%s, tool_names=%s", acting_subject, tool_names)
    if acting_subject:
        subject_id = acting_subject.get("subject_id")
        subject_type = acting_subject.get("subject_type") or "subject"
        kb_namespace = f"{subject_type}-{subject_id}" if subject_id else None

        # Register any `portfolio_<domain>` tool dynamically (deferred schema load)
        for tname in tool_names:
            if tname.startswith("portfolio_") and subject_id:
                domain = tname[len("portfolio_"):]
                try:
                    from engine.tools.schema_portfolio_tool import SchemaPortfolioTool
                    tool = SchemaPortfolioTool(
                        domain_name=domain,
                        user_id=subject_id,
                        tenant_id=str(tenant_id),
                        db_url=db_url,
                    )
                    registry.register(tool)
                    logger.info("Registered subject-scoped tool: %s for subject %s", tname, subject_id)
                except Exception as e:
                    logger.error("Failed to register %s tool: %s", tname, e)

        if "graph_explorer" in tool_names and kb_namespace:
            try:
                from engine.tools.graph_explorer_tool import GraphExplorerTool
                registry.register(GraphExplorerTool(kb_id=kb_namespace))
                logger.info("Registered graph_explorer tool with kb_id %s", kb_namespace)
            except Exception as e:
                logger.error("Failed to register graph_explorer tool: %s", e)

        # knowledge_search needs kb_ids — register it with a subject-namespaced KB if not already
        if "knowledge_search" in tool_names and "knowledge_search" not in registry.names() and kb_namespace:
            try:
                from engine.tools.knowledge_search import KnowledgeSearchTool
                registry.register(KnowledgeSearchTool(
                    kb_ids=[kb_namespace], tenant_id=tenant_id, agent_id=agent_id,
                ))
                logger.info("Registered knowledge_search with kb_id %s", kb_namespace)
            except Exception as e:
                logger.error("Failed to register knowledge_search tool: %s", e)

    return registry
