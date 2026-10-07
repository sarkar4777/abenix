from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any


from engine import credentials, governance, risk
from engine.agent_budget import BUDGET_EXCEEDED, run_budget_message, run_cost_limit
from engine.llm_router import LLMResponse, LLMRouter
from engine.metrics import (
    agent_active_streams,
    agent_execution_duration_seconds,
    moderation_decisions_total,
    tool_execution_duration_seconds,
)
from engine.moderation_gate import (
    GateConfig,
    ModerationBlocked,
    check as moderation_check,
)
from engine.sandbox import ExecutionSandbox
from engine.tools.base import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


def _provider_key(model: str) -> str:
    """Classify model id into a provider bucket for cost splitting."""
    m = (model or "").lower()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("chatgpt"):
        return "openai"
    if m.startswith("gemini"):
        return "google"
    return "other"


def _moderation_block_text(mb: Any, subject: str) -> str:
    """Explain a moderation block without inventing a policy hit.

    A provider error escalated by fail_closed has no triggered categories, and
    the old wording still claimed the content breached the policy — printing
    "Categories: n/a." and leaving no way to tell an outage from a real refusal.
    """
    decision = getattr(mb, "decision", None)
    cats = list(getattr(decision, "triggered_categories", None) or [])
    if cats:
        return f"{subject} blocked by moderation policy. Categories: {', '.join(cats[:5])}."
    reason = getattr(decision, "reason", "") or ""
    err = getattr(decision, "error", "") or ""
    if reason == "provider_error_fail_closed" or err:
        detail = f" ({err[:160]})" if err else ""
        return (
            f"{subject} blocked because the moderation provider could not be reached "
            f"and this policy is set to fail closed{detail}. "
            "Configure the provider credential or turn off fail-closed at /moderation."
        )
    return f"{subject} blocked by moderation policy."


MAX_ITERATIONS = 10


def _short(obj: Any, limit: int = 160) -> str:
    try:
        import json as _j

        s = _j.dumps(obj, default=str)
    except Exception:
        s = str(obj)
    return s if len(s) <= limit else s[:limit] + "..."


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
    return (
        content[:half]
        + f"\n\n[... truncated {len(content) - max_chars:,} chars ...]\n\n"
        + content[-half:]
    )


_RESULT_PERSIST_CHARS = int(os.environ.get("TOOL_RESULT_PERSIST_CHARS", "8000"))


def _persisted_result(content: str | None) -> str:
    """The tool result kept on the execution row, bounded so rows stay small."""
    text = content or ""
    if len(text) <= _RESULT_PERSIST_CHARS:
        return text
    dropped = len(text) - _RESULT_PERSIST_CHARS
    return text[:_RESULT_PERSIST_CHARS] + f"\n[{dropped} more characters not kept]"


def _attach_decision_record(tc: dict[str, Any], result: Any) -> None:
    record = (getattr(result, "metadata", None) or {}).get("decision_record")
    if record:
        tc["decision_record"] = record


def _model_visible_content(result: Any) -> str:
    """The text the model is shown for a tool result.

    A tool that skipped a keyed source, fell back to a weaker provider or
    could not run puts that in metadata, which the model never sees. Append
    it to the content so the answer can say so instead of inventing a reason.
    """
    content = str(getattr(result, "content", "") or "")
    md = getattr(result, "metadata", None) or {}
    notes: list[str] = [str(w) for w in (md.get("warnings") or [])]
    skipped = md.get("sources_skipped") or []
    if skipped:
        notes.append("sources not queried: " + ", ".join(str(x) for x in skipped))
    key = md.get("needs_configuration")
    if key and "Tool Configuration" not in content:
        notes.append(
            f"{key} is not configured, an admin can add it under Admin -> Tool Configuration"
        )
    if md.get("skipped") and md.get("reason") and str(md["reason"]) not in content:
        notes.append(str(md["reason"]))
    if notes:
        content += "\n\n[tool notes] " + " | ".join(dict.fromkeys(notes))
    # the model paraphrases and drops the key name, so it is told what to repeat
    if key:
        content += (
            f"\n\n[instruction] Tell the user word for word: {key} is not configured. "
            "An admin can add it under Admin -> Tool Configuration. Do not suggest shell commands or environment variables."
        )
    elif notes:
        content += (
            "\n\n[instruction] Mention each note above to the user, naming the configuration value "
            "and that an admin can add it under Admin -> Tool Configuration."
        )
    return _truncate_tool_result(content)


def _build_output_summary(metadata: Any, is_error: bool) -> dict[str, Any]:
    """Compact tool-result projection that survives the SDK round-trip.

    Carries the load-bearing metadata fields (status, resolved_symbol,
    closes, prices_count, latest_close, currency, fetched_at) so downstream
    callers — per-agent post-processors and the CIQ router defense-in-depth
    guardrail — can recompute without re-running the tool.
    """
    if not isinstance(metadata, dict):
        metadata = {}
    closes = metadata.get("closes") or []
    if not isinstance(closes, list):
        closes = []
    status_val = metadata.get("status")
    if is_error:
        status = "error"
    elif isinstance(status_val, str) and status_val:
        status = status_val
    else:
        status = "ok"
    return {
        "status": status,
        "resolved_symbol": metadata.get("resolved_symbol")
        or metadata.get("symbol")
        or "",
        "symbol": metadata.get("symbol") or "",
        "closes": closes,
        "prices_count": int(metadata.get("price_count") or len(closes) or 0),
        "latest_close": metadata.get("latest_close"),
        "fetched_at": metadata.get("fetched_at") or metadata.get("last_refresh") or "",
        "currency": metadata.get("currency") or "",
    }


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
                    total_chars += (
                        len(str(block.get("content", "")))
                        + len(str(block.get("text", "")))
                        + len(str(block.get("input", "")))
                    )
    return total_chars // CHARS_PER_TOKEN


GROUNDING_REQUIRED_TOOL = "knowledge_search"
GROUNDING_REQUIRED_ERROR = (
    "Grounded-response agent completed without invoking knowledge_search; "
    "output cannot be certified as grounded."
)


def _required_tools_missing(
    required: list[str], tool_calls: list[dict[str, Any]]
) -> list[str]:
    """Required tools the run never called, in declaration order."""
    if not required:
        return []
    called = {tc.get("name") for tc in (tool_calls or []) if isinstance(tc, dict)}
    return [t for t in required if t not in called]


def _grounding_violated(
    require_knowledge_search: bool, tool_calls: list[dict[str, Any]]
) -> bool:
    """True when the agent required a knowledge_search call and never made one."""
    if not require_knowledge_search:
        return False
    return bool(_required_tools_missing([GROUNDING_REQUIRED_TOOL], tool_calls))


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
    # Why `model` differs from the requested one, when it does.
    fallback_reason: str = ""
    cache_hit: str = ""
    node_traces: list[NodeTrace] = field(default_factory=list)
    # Set when the moderation gate blocked the run. Downstream code sets
    # the Execution.failure_code = "MODERATION_BLOCKED" off this.
    moderation_blocked: bool = False
    moderation_block_source: str = ""  # pre_llm | post_llm
    # Set when the agent is configured with require_knowledge_search=True
    # but completed the run without ever invoking the knowledge_search
    # tool. Downstream callers map this to failure_code=
    # GROUNDING_REQUIRED_VIOLATION so auditors can prove the response
    # cannot be certified as grounded.
    grounding_violation: bool = False
    grounding_block_source: str = ""  # no_knowledge_search_invocation
    # tier the run ended at and what raised it, see engine.governance
    risk_tier: str = ""
    risk_reasons: list[dict[str, Any]] = field(default_factory=list)
    # set when a kill switch or tier policy refused the run before it started
    governance_refusal: dict[str, Any] | None = None
    # set when the run stopped at its per-run cost limit
    budget_exceeded: bool = False
    failure_code: str = ""

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
        tenant_id: str = "",
        require_knowledge_search: bool = False,
        require_tools: list[str] | None = None,
        risk_tier: str = "",
        agent_name: str = "",
        cost_limit: float | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> None:
        self.llm_router = llm_router
        # earlier turns of a chat thread, sent ahead of the new user message
        self.history: list[dict[str, Any]] = [
            {"role": m["role"], "content": m["content"]}
            for m in (history or [])
            if isinstance(m, dict)
            and m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
            and m["content"]
        ]
        self.cost_limit = run_cost_limit(cost_limit)
        self.risk_tier = risk.normalize(risk_tier)
        if agent_name:
            self.agent_name = agent_name
        self.tool_registry = tool_registry
        if tool_config:
            tool_registry.apply_tool_config(
                tool_config, asset_schemas=asset_schemas or {}
            )
        self.system_prompt = system_prompt
        self.model = model
        self.temperature = temperature
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.cache = cache
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        # Policy-gate snapshot. None = no gate (backward-compatible
        # default); callers with an active ModerationPolicy build a
        # GateConfig in the API layer and pass it in.
        self.moderation_gate = moderation_gate
        self.execution_id = execution_id
        # Grounded-response contract: when True the agent MUST invoke
        # knowledge_search at least once. If it doesn't, the run is
        # marked grounding_violation so the caller can emit
        # failure_code=GROUNDING_REQUIRED_VIOLATION and reject the
        # output. No auto-retry — the caller decides what to do.
        self.require_knowledge_search = bool(require_knowledge_search)
        # model_config.require_tools, plus knowledge_search when the grounding flag is on
        self.require_tools: list[str] = list(
            dict.fromkeys(
                [str(t) for t in (require_tools or []) if t]
                + ([GROUNDING_REQUIRED_TOOL] if self.require_knowledge_search else [])
            )
        )
        # node traces of the last stream() so the caller can persist them
        self._node_traces: list[dict[str, Any]] = []
        if sandbox is None:
            from engine.sandbox import SandboxPolicy

            base_timeout = 300
            base_tool_calls = 50
            if max_iterations > MAX_ITERATIONS:
                scale = max(1.0, max_iterations / MAX_ITERATIONS)
                policy = SandboxPolicy(
                    timeout_seconds=int(base_timeout * scale),
                    max_tool_calls=int(base_tool_calls * scale),
                    timeout_overridden=True,
                )
                sandbox = ExecutionSandbox(policy=policy)
            else:
                sandbox = ExecutionSandbox()
        self.sandbox = sandbox

    def _over_budget(self, spent: float) -> bool:
        return self.cost_limit is not None and spent >= self.cost_limit

    def _budget_stop_text(self, spent: float, partial: str = "") -> str:
        msg = run_budget_message(self.cost_limit or 0.0, spent)
        return f"{partial}\n\n{msg}" if partial else msg

    def _missing_required(self, tool_calls: list[dict[str, Any]]) -> list[str]:
        return _required_tools_missing(self.require_tools, tool_calls)

    def _grounding_violated(self, tool_calls: list[dict[str, Any]]) -> bool:
        return bool(self._missing_required(tool_calls))

    def get_trace_summary(self) -> list[dict[str, Any]]:
        return list(self._node_traces)

    async def _final_answer(
        self, messages: list[dict[str, Any]], tools: Any
    ) -> LLMResponse | None:
        """One last turn after the step limit, asking for the answer from what is in hand."""
        note = (
            "You have used all the steps available for this task. Do not call any "
            "more tools. Give your final answer now, using only what you already "
            "gathered, in the format you were asked for. Say plainly what you "
            "could not establish."
        )
        msgs = list(messages)
        last = msgs[-1] if msgs else None
        if last and last.get("role") == "user":
            content = last.get("content")
            if isinstance(content, list):
                msgs[-1] = {
                    **last,
                    "content": [*content, {"type": "text", "text": note}],
                }
            else:
                msgs[-1] = {**last, "content": f"{content}\n\n{note}"}
        else:
            msgs.append({"role": "user", "content": note})
        try:
            resp = await self.llm_router.complete(
                messages=msgs,
                system=self.system_prompt or None,
                tools=tools if tools else None,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=False,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("final answer after step limit failed: %s", e)
            return None
        return resp if isinstance(resp, LLMResponse) and resp.content else None

    def _begin_governed_run(self) -> tuple[Any, Any, Any]:
        parent = governance.current()
        # the stored tier wins over a lower one a caller passed
        base = risk.highest([self.risk_tier, governance.agent_tier(self.agent_id)])
        if parent is not None:
            # a nested agent never runs below the run that called it
            base = risk.highest([base, parent.tier])
        ctx = governance.RunContext(
            tenant_id=str(getattr(self, "tenant_id", "") or ""),
            execution_id=str(self.execution_id or ""),
            agent_name=str(getattr(self, "agent_name", "") or ""),
            base_tier=base,
            tier=base,
            scope="agent",
            subject_id=str(self.agent_id or ""),
            parent=parent,
        )
        if base != "low":
            ctx.reasons.append({"tier": base, "source": "agent", "detail": ""})
        return ctx, parent, governance.begin_run(ctx)

    @staticmethod
    def _end_governed_run(ctx: Any, parent: Any, token: Any, who: str) -> None:
        governance.end_run(token)
        if parent is not None:
            parent.raise_to(ctx.tier, f"agent:{who}")

    async def _governance_refusal(self) -> dict[str, Any] | None:
        """Kill switches and the tier's model list, checked before any token is spent."""
        await governance.ensure_fresh()
        tenant = str(getattr(self, "tenant_id", "") or "")
        try:
            governance.check(tenant, "agent", str(self.agent_id or "*"))
            governance.check(tenant, "model", str(self.model or "*"))
        except governance.Stopped as s:
            return {
                "code": "KILL_SWITCH",
                "message": s.message(),
                "scope": s.scope,
                "target": s.target,
            }
        ctx = governance.current()
        tier = ctx.tier if ctx else self.risk_tier
        if not risk.model_allowed(governance.policy(tenant, tier), self.model):
            return {
                "code": "MODEL_NOT_ALLOWED",
                "message": (
                    f"The model {self.model} is not on the allowed list for {tier} risk work "
                    "in this tenant. Pick an allowed model or ask an admin to add it "
                    "under Admin, Risk and Controls."
                ),
                "scope": "model",
                "target": str(self.model or ""),
            }
        return None

    async def invoke(self, input_message: str) -> ExecutionResult:
        await governance.ensure_fresh()
        ctx, parent, token = self._begin_governed_run()
        try:
            refusal = await self._governance_refusal()
            if refusal is not None:
                result = ExecutionResult(
                    output=refusal["message"],
                    model=self.model,
                    governance_refusal=refusal,
                )
            else:
                result = await self._invoke_governed(input_message)
        finally:
            self._end_governed_run(
                ctx,
                parent,
                token,
                str(getattr(self, "agent_name", "") or self.agent_id),
            )
        result.risk_tier = ctx.tier
        result.risk_reasons = list(ctx.reasons)
        return result

    async def _invoke_governed(self, input_message: str) -> ExecutionResult:
        from engine.tracing import get_tracer, current_trace_id

        credentials.set_tenant(getattr(self, "tenant_id", ""))
        tracer = get_tracer("abenix.agent_executor")
        with tracer.start_as_current_span("agent.execute") as _span:
            _span.set_attribute("agent.id", str(self.agent_id))
            _span.set_attribute(
                "agent.name", str(getattr(self, "agent_name", "") or "")
            )
            _span.set_attribute("agent.model", str(self.model or ""))
            _span.set_attribute("execution.id", str(self.execution_id or ""))
            _span.set_attribute("tenant.id", str(getattr(self, "tenant_id", "") or ""))
            self._trace_id_for_log = current_trace_id()
            return await self._invoke_impl(input_message)

    async def _invoke_impl(self, input_message: str) -> ExecutionResult:
        start = time.monotonic()
        await self.sandbox.apply_platform_defaults()
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
                    source="pre_llm",
                    outcome=_mod_pre.outcome,
                ).inc()
            except ModerationBlocked as mb:
                moderation_decisions_total.labels(
                    source="pre_llm",
                    outcome="blocked",
                ).inc()
                duration = int((time.monotonic() - start) * 1000)
                return ExecutionResult(
                    output=(_moderation_block_text(mb, "Request")),
                    duration_ms=duration,
                    model=self.model,
                    moderation_blocked=True,
                    moderation_block_source="pre_llm",
                )

        messages: list[dict[str, Any]] = [
            *self.history,
            {"role": "user", "content": input_message},
        ]
        tools = self.tool_registry.list_all()
        all_tool_calls: list[dict[str, Any]] = []
        node_traces: list[NodeTrace] = []
        total_input = 0
        total_output = 0
        total_cost = 0.0
        effective_model: str | None = None
        effective_fallback_reason: str | None = None
        # Per-provider subtotals for the executions row split.
        provider_costs: dict[str, float] = {
            "anthropic": 0.0,
            "openai": 0.0,
            "google": 0.0,
            "other": 0.0,
        }
        node_counter = 0

        node_traces.append(
            NodeTrace(
                node_id=f"node_{node_counter}",
                node_type="user_input",
                iteration=0,
                timestamp_ms=int(start * 1000),
                input_data={"message": input_message[:500]},
                output_data={},
            )
        )
        node_counter += 1

        # replies that depend on earlier turns stay out of the shared cache
        if self.cache and not self.history:
            cache_result = await self.cache.check(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                temperature=self.temperature,
                system=self.system_prompt or None,
                agent_id=self.agent_id,
                tenant_id=self.tenant_id,
            )
            if cache_result.hit and cache_result.response:
                duration = int((time.monotonic() - start) * 1000)
                agent_execution_duration_seconds.observe(duration / 1000)
                # A cached response by definition didn't invoke the
                # knowledge_search tool on this run — if the agent
                # requires grounding, we must fail the cache hit too.
                # Otherwise the guardrail silently passes warm-cache
                # answers that bypass the grounding contract.
                _ground_cache = self._grounding_violated(all_tool_calls)
                return ExecutionResult(
                    output=(
                        GROUNDING_REQUIRED_ERROR
                        if _ground_cache
                        else cache_result.response.get("content", "")
                    ),
                    duration_ms=duration,
                    model=cache_result.response.get("model", self.model),
                    cache_hit=cache_result.layer,
                    node_traces=node_traces,
                    grounding_violation=_ground_cache,
                    grounding_block_source=(
                        "no_knowledge_search_invocation" if _ground_cache else ""
                    ),
                )

        for iteration in range(self.max_iterations):
            if not self.sandbox.check_timeout():
                duration = int((time.monotonic() - start) * 1000)
                agent_execution_duration_seconds.observe(duration / 1000)
                _ground_to = self._grounding_violated(all_tool_calls)
                return ExecutionResult(
                    output=(
                        GROUNDING_REQUIRED_ERROR
                        if _ground_to
                        else "Execution timed out."
                    ),
                    input_tokens=total_input,
                    output_tokens=total_output,
                    cost=total_cost,
                    duration_ms=duration,
                    tool_calls=all_tool_calls,
                    model=self.model,
                    node_traces=node_traces,
                    grounding_violation=_ground_to,
                    grounding_block_source=(
                        "no_knowledge_search_invocation" if _ground_to else ""
                    ),
                )

            # Anthropic forces streaming when max_tokens could breach the
            # 10-minute soft deadline. Whenever we're on Claude with a big
            # max_tokens we call through the streaming API and collapse the
            # event stream back into an LLMResponse.
            _need_stream = bool(
                self.model.startswith("claude") and (self.max_tokens or 0) > 8192
            )
            complete_kwargs: dict[str, Any] = {
                "messages": messages,
                "system": self.system_prompt or None,
                "tools": tools if tools else None,
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": _need_stream,
            }

            if (
                self.cache
                and self.cache.prompt_optimizer
                and self.model.startswith("claude")
            ):
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
                        accum_tool_calls.append(
                            {
                                "id": ev.data.get("id", ""),
                                "name": ev.data.get("name", ""),
                                "arguments": ev.data.get("arguments", {}),
                            }
                        )
                    elif ev.event == "done":
                        done_meta = ev.data
                resp = LLMResponse(
                    # The router reports which model actually served the
                    # call, which can differ from the agent's configured one
                    # (subscription mode pins to the plan's model, and the
                    # degradation chain may land on another provider).
                    # Substituting self.model here hid that, so audit rows
                    # recorded the requested model as if it had run.
                    model=done_meta.get("model") or self.model,
                    input_tokens=done_meta.get("input_tokens", 0),
                    output_tokens=done_meta.get("output_tokens", 0),
                    cost=done_meta.get("cost", 0.0),
                    latency_ms=done_meta.get(
                        "latency_ms", int((time.monotonic() - llm_start) * 1000)
                    ),
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
            # Remember which model actually served this turn so the done
            # payload (and therefore the executions row) reflects reality.
            if resp.model:
                effective_model = resp.model
            if getattr(resp, "fallback_reason", None):
                effective_fallback_reason = resp.fallback_reason
            # Split by provider so the executions row can show a
            # per-provider breakdown (critical when a call fell back
            # from Anthropic to OpenAI).
            _prov = _provider_key(resp.model)
            provider_costs[_prov] = provider_costs.get(_prov, 0.0) + resp.cost

            node_traces.append(
                NodeTrace(
                    node_id=f"node_{node_counter}",
                    node_type="llm_call",
                    iteration=iteration,
                    timestamp_ms=int(llm_start * 1000),
                    duration_ms=llm_duration,
                    input_data={
                        "message_count": len(messages),
                        "tools_available": len(tools),
                    },
                    output_data={
                        "content_preview": resp.content[:300] if resp.content else "",
                        "tool_calls": len(resp.tool_calls),
                        "input_tokens": resp.input_tokens,
                        "output_tokens": resp.output_tokens,
                    },
                    metadata={"model": resp.model, "cost": round(resp.cost, 6)},
                )
            )
            node_counter += 1

            if resp.tool_calls and self._over_budget(total_cost):
                return self._budget_result(
                    start,
                    resp.content or "",
                    total_input,
                    total_output,
                    total_cost,
                    provider_costs,
                    all_tool_calls,
                    node_traces,
                    iteration,
                    node_counter,
                    effective_model or resp.model,
                    effective_fallback_reason,
                )

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
                            source="post_llm",
                            outcome=_mod_post.outcome,
                        ).inc()
                    except ModerationBlocked as mb:
                        moderation_decisions_total.labels(
                            source="post_llm",
                            outcome="blocked",
                        ).inc()
                        return ExecutionResult(
                            output=(_moderation_block_text(mb, "Response")),
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

                if self.cache and not self.history and output_text == resp.content:
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
                        tenant_id=self.tenant_id,
                    )

                grounding_violation = self._grounding_violated(all_tool_calls)
                return ExecutionResult(
                    output=(
                        GROUNDING_REQUIRED_ERROR if grounding_violation else output_text
                    ),
                    input_tokens=total_input,
                    output_tokens=total_output,
                    cost=total_cost,
                    anthropic_cost=provider_costs.get("anthropic", 0.0),
                    openai_cost=provider_costs.get("openai", 0.0),
                    google_cost=provider_costs.get("google", 0.0),
                    other_cost=provider_costs.get("other", 0.0),
                    duration_ms=duration,
                    tool_calls=all_tool_calls,
                    model=effective_model or resp.model,
                    fallback_reason=effective_fallback_reason or "",
                    node_traces=node_traces,
                    grounding_violation=grounding_violation,
                    grounding_block_source=(
                        "no_knowledge_search_invocation" if grounding_violation else ""
                    ),
                )

            assistant_content: list[dict[str, Any]] = []
            if resp.content:
                assistant_content.append({"type": "text", "text": resp.content})
            for tc in resp.tool_calls:
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["arguments"],
                    }
                )
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results_content: list[dict[str, Any]] = []
            for tc in resp.tool_calls:
                all_tool_calls.append(tc)

                if not self.sandbox.check_tool_call():
                    tool_results_content.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc["id"],
                            "content": "Tool call limit exceeded",
                            "is_error": True,
                        }
                    )
                    continue

                tool = self.tool_registry.get(tc["name"])
                if tool:
                    tool_start = time.monotonic()
                    try:
                        from engine import progress as _wm_progress

                        await _wm_progress.publish(
                            self.execution_id,
                            {
                                "phase": "tool_call",
                                "tool": tc["name"],
                                "arguments_preview": _short(tc.get("arguments")),
                                "agent_id": self.agent_id,
                            },
                        )
                    except Exception:
                        pass
                    from engine.tracing import get_tracer as _gt

                    _tracer = _gt("abenix.agent_executor")
                    with _tracer.start_as_current_span(f"tool.{tc['name']}") as _tspan:
                        _tspan.set_attribute("tool.name", tc["name"])
                        _tspan.set_attribute(
                            "tool.args_preview", _short(tc.get("arguments"))
                        )
                        result = await tool.execute(tc["arguments"])
                        _tspan.set_attribute(
                            "tool.is_error", bool(getattr(result, "is_error", False))
                        )
                    tool_dur = int((time.monotonic() - tool_start) * 1000)
                    try:
                        from engine import progress as _wm_progress

                        await _wm_progress.publish(
                            self.execution_id,
                            {
                                "phase": "tool_result",
                                "tool": tc["name"],
                                "is_error": bool(result.is_error),
                                "duration_ms": tool_dur,
                                "result_preview": (result.content or "")[:240],
                                "agent_id": self.agent_id,
                            },
                        )
                    except Exception:
                        pass
                    tool_execution_duration_seconds.labels(
                        tool_name=tc["name"]
                    ).observe(tool_dur / 1000)

                    node_traces.append(
                        NodeTrace(
                            node_id=f"node_{node_counter}",
                            node_type="tool_call",
                            iteration=iteration,
                            timestamp_ms=int(tool_start * 1000),
                            duration_ms=tool_dur,
                            input_data={
                                "tool": tc["name"],
                                "arguments": tc["arguments"],
                            },
                            output_data={
                                "content_preview": result.content[:500],
                                "is_error": result.is_error,
                                "metadata": result.metadata,
                            },
                        )
                    )
                    node_counter += 1
                    tc["result"] = _persisted_result(result.content)
                    tc["is_error"] = bool(result.is_error)
                    tc["duration_ms"] = tool_dur
                    _attach_decision_record(tc, result)
                else:
                    result = ToolResult(
                        content=f"Unknown tool: {tc['name']}", is_error=True
                    )

                self.sandbox.check_output_size(result.content)

                # Attach an output_summary back onto the tool_call entry the
                # caller will receive. This is what the CIQ router's
                # canonical-anchor guardrail reads — without it the router
                # would have to refetch yahoo_finance to know the closes.
                tc["output_summary"] = _build_output_summary(
                    result.metadata, bool(result.is_error)
                )

                # Truncate large tool results to prevent context overflow
                context_content = _model_visible_content(result)
                tool_results_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": context_content,
                        "is_error": result.is_error,
                    }
                )

            messages.append({"role": "user", "content": tool_results_content})

            # Check if accumulated context is approaching the limit
            est_tokens = _estimate_messages_tokens(messages)
            if est_tokens > CONTEXT_TOKEN_BUDGET:
                logger.warning(
                    "Context budget exceeded (%d est. tokens), stopping execution",
                    est_tokens,
                )
                duration = int((time.monotonic() - start) * 1000)
                return ExecutionResult(
                    output=resp.content
                    or "Execution stopped: context window limit reached. The gathered information may be incomplete.",
                    input_tokens=total_input,
                    output_tokens=total_output,
                    cost=total_cost,
                    duration_ms=duration,
                    tool_calls=all_tool_calls,
                    model=resp.model,
                    node_traces=node_traces,
                )

        grounding_violation = self._grounding_violated(all_tool_calls)
        final_text = ""
        if not grounding_violation:
            # out of steps: answer from what was gathered rather than return nothing usable
            final = await self._final_answer(messages, tools)
            if final is not None:
                final_text = final.content or ""
                total_input += final.input_tokens
                total_output += final.output_tokens
                total_cost += final.cost
        duration = int((time.monotonic() - start) * 1000)
        agent_execution_duration_seconds.observe(duration / 1000)
        return ExecutionResult(
            output=(
                GROUNDING_REQUIRED_ERROR
                if grounding_violation
                else final_text or "Max iterations reached."
            ),
            input_tokens=total_input,
            output_tokens=total_output,
            cost=total_cost,
            anthropic_cost=provider_costs.get("anthropic", 0.0),
            openai_cost=provider_costs.get("openai", 0.0),
            google_cost=provider_costs.get("google", 0.0),
            other_cost=provider_costs.get("other", 0.0),
            duration_ms=duration,
            tool_calls=all_tool_calls,
            model=effective_model or self.model,
            fallback_reason=effective_fallback_reason or "",
            node_traces=node_traces,
            grounding_violation=grounding_violation,
            grounding_block_source=(
                "no_knowledge_search_invocation" if grounding_violation else ""
            ),
        )

    def _budget_result(
        self,
        start: float,
        partial: str,
        total_input: int,
        total_output: int,
        total_cost: float,
        provider_costs: dict[str, float],
        tool_calls: list[dict[str, Any]],
        node_traces: list[NodeTrace],
        iteration: int,
        node_counter: int,
        model: str,
        fallback_reason: str | None,
    ) -> ExecutionResult:
        duration = int((time.monotonic() - start) * 1000)
        agent_execution_duration_seconds.observe(duration / 1000)
        node_traces.append(
            NodeTrace(
                node_id=f"node_{node_counter}",
                node_type="budget_stop",
                iteration=iteration,
                timestamp_ms=int(time.monotonic() * 1000),
                input_data={"cost_limit": self.cost_limit},
                output_data={"spent": round(total_cost, 6)},
                metadata={"failure_code": BUDGET_EXCEEDED},
            )
        )
        return ExecutionResult(
            output=self._budget_stop_text(total_cost, partial),
            input_tokens=total_input,
            output_tokens=total_output,
            cost=total_cost,
            anthropic_cost=provider_costs.get("anthropic", 0.0),
            openai_cost=provider_costs.get("openai", 0.0),
            google_cost=provider_costs.get("google", 0.0),
            other_cost=provider_costs.get("other", 0.0),
            duration_ms=duration,
            tool_calls=tool_calls,
            model=model or self.model,
            fallback_reason=fallback_reason or "",
            node_traces=node_traces,
            budget_exceeded=True,
            failure_code=BUDGET_EXCEEDED,
        )

    async def stream(self, input_message: str) -> AsyncGenerator[ExecutionEvent, None]:
        await governance.ensure_fresh()
        ctx, parent, token = self._begin_governed_run()
        try:
            refusal = await self._governance_refusal()
            if refusal is not None:
                yield ExecutionEvent(event="token", data=refusal["message"])
                yield ExecutionEvent(
                    event="done",
                    data={
                        "total_tokens": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost": 0.0,
                        "duration_ms": 0,
                        "model": self.model,
                        "error": refusal["message"],
                        "failure_code": refusal["code"],
                        "governance_refusal": refusal,
                        "risk_tier": ctx.tier,
                        "risk_reasons": list(ctx.reasons),
                    },
                )
                return
            async for ev in self._stream_governed(input_message):
                if ev.event == "done" and isinstance(ev.data, dict):
                    ev.data["risk_tier"] = ctx.tier
                    ev.data["risk_reasons"] = list(ctx.reasons)
                yield ev
        finally:
            self._end_governed_run(
                ctx,
                parent,
                token,
                str(getattr(self, "agent_name", "") or self.agent_id),
            )

    async def _stream_governed(
        self, input_message: str
    ) -> AsyncGenerator[ExecutionEvent, None]:
        from engine.tracing import get_tracer, current_trace_id

        tracer = get_tracer("abenix.agent_executor")
        with tracer.start_as_current_span("agent.execute") as _span:
            _span.set_attribute("agent.id", str(self.agent_id))
            _span.set_attribute(
                "agent.name", str(getattr(self, "agent_name", "") or "")
            )
            _span.set_attribute("agent.model", str(self.model or ""))
            _span.set_attribute("execution.id", str(self.execution_id or ""))
            _span.set_attribute("tenant.id", str(getattr(self, "tenant_id", "") or ""))
            self._trace_id_for_log = current_trace_id()
            async for _ev in self._stream_impl(input_message):
                if (
                    _ev.event == "done"
                    and isinstance(_ev.data, dict)
                    and self._trace_id_for_log
                ):
                    _ev.data["trace_id"] = self._trace_id_for_log
                yield _ev

    async def _stream_impl(
        self, input_message: str
    ) -> AsyncGenerator[ExecutionEvent, None]:
        start = time.monotonic()
        credentials.set_tenant(getattr(self, "tenant_id", ""))
        agent_active_streams.inc()
        await self.sandbox.apply_platform_defaults()
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
                    source="pre_llm",
                    outcome=_mod_pre.outcome,
                ).inc()
                if _mod_pre.outcome == "redacted":
                    yield ExecutionEvent(
                        event="moderation",
                        data={
                            "source": "pre_llm",
                            "outcome": "redacted",
                            "categories": list(_mod_pre.triggered_categories),
                            "message": "Your message was redacted by the moderation policy before the agent saw it.",
                        },
                    )
            except ModerationBlocked as mb:
                moderation_decisions_total.labels(
                    source="pre_llm",
                    outcome="blocked",
                ).inc()
                duration = int((time.monotonic() - start) * 1000)
                agent_active_streams.dec()
                yield ExecutionEvent(
                    event="token",
                    data=(_moderation_block_text(mb, "Request")),
                )
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

        messages: list[dict[str, Any]] = [
            *self.history,
            {"role": "user", "content": input_message},
        ]
        tools = self.tool_registry.list_all()
        all_tool_calls: list[dict[str, Any]] = []
        self._node_traces = []
        total_input = 0
        total_output = 0
        total_cost = 0.0
        effective_model: str | None = None
        effective_fallback_reason: str | None = None

        # replies that depend on earlier turns stay out of the shared cache
        if self.cache and not self.history:
            cache_result = await self.cache.check(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                temperature=self.temperature,
                system=self.system_prompt or None,
                agent_id=self.agent_id,
                tenant_id=self.tenant_id,
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

            # Remember which model actually served this turn. Without this the
            # streaming path reported self.model no matter what the router
            # chose, so an executions row for a subscription-served run still
            # named the requested model.
            if done_data.get("model"):
                effective_model = done_data["model"]
            if done_data.get("fallback_reason"):
                effective_fallback_reason = done_data["fallback_reason"]

            stream_tool_calls = done_data.get("tool_calls", [])

            if stream_tool_calls and self._over_budget(total_cost):
                async for _bev in self._budget_stop_events(
                    start,
                    total_input,
                    total_output,
                    total_cost,
                    iteration,
                    effective_model,
                    effective_fallback_reason,
                ):
                    yield _bev
                return

            if not stream_tool_calls:
                duration = int((time.monotonic() - start) * 1000)
                agent_execution_duration_seconds.observe(duration / 1000)
                agent_active_streams.dec()

                # Post-LLM gate on the streamed answer. The tokens are already out,
                # so a redaction goes to the client as a replacement it applies.
                _post_redacted = False
                if self.moderation_gate is not None:
                    try:
                        _checked, _mod_post = await moderation_check(
                            full_text,
                            source="post_llm",
                            config=self.moderation_gate,
                            execution_id=self.execution_id,
                        )
                        moderation_decisions_total.labels(
                            source="post_llm", outcome=_mod_post.outcome
                        ).inc()
                        if _mod_post.outcome == "redacted" and _checked != full_text:
                            full_text = _checked
                            _post_redacted = True
                            yield ExecutionEvent(
                                event="moderation",
                                data={
                                    "source": "post_llm",
                                    "outcome": "redacted",
                                    "categories": list(_mod_post.triggered_categories),
                                    "content": full_text,
                                    "message": "The answer was redacted by the moderation policy.",
                                },
                            )
                    except ModerationBlocked as mb:
                        moderation_decisions_total.labels(
                            source="post_llm", outcome="blocked"
                        ).inc()
                        yield ExecutionEvent(
                            event="moderation",
                            data={
                                "source": "post_llm",
                                "outcome": "blocked",
                                "content": _moderation_block_text(mb, "Response"),
                                "message": "The answer was blocked by the moderation policy.",
                            },
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
                                "effective_model": effective_model or self.model,
                                "error": "moderation_blocked",
                                "moderation_blocked": True,
                                "moderation_block_source": "post_llm",
                            },
                        )
                        return

                if self.cache and not self.history and not _post_redacted:
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
                        tenant_id=self.tenant_id,
                    )

                _grounding_failed = self._grounding_violated(all_tool_calls)
                _done_payload: dict[str, Any] = {
                    "total_tokens": total_input + total_output,
                    "input_tokens": total_input,
                    "output_tokens": total_output,
                    "cost": round(total_cost, 6),
                    "duration_ms": duration,
                    "model": self.model,
                    # What actually ran, so the API can persist model_used
                    # and the reason it differed from the request.
                    "effective_model": effective_model or self.model,
                    "fallback_reason": effective_fallback_reason,
                }
                _missing_early = self._missing_required(all_tool_calls)
                if _grounding_failed:
                    _done_payload["error"] = "grounding_required_violation"
                    _done_payload["grounding_violation"] = True
                    _done_payload["missing_tools"] = _missing_early
                    if _missing_early == [GROUNDING_REQUIRED_TOOL]:
                        _done_payload["grounding_block_source"] = (
                            "no_knowledge_search_invocation"
                        )
                        yield ExecutionEvent(
                            event="token", data=f"\n\n{GROUNDING_REQUIRED_ERROR}"
                        )
                    else:
                        _done_payload["failure_code"] = "REQUIRED_TOOLS_VIOLATION"
                        _done_payload["grounding_block_source"] = (
                            "missing: " + ", ".join(_missing_early)
                        )
                        yield ExecutionEvent(
                            event="token",
                            data=f"\n\n[required tools not called: {', '.join(_missing_early)}]",
                        )
                elif not all_tool_calls and self.tool_registry.names():
                    _done_payload["warnings"] = [
                        "completed without calling any tool although tools were available"
                    ]
                yield ExecutionEvent(event="done", data=_done_payload)
                return

            assistant_content: list[dict[str, Any]] = []
            if full_text:
                assistant_content.append({"type": "text", "text": full_text})
            for tc in stream_tool_calls:
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["arguments"],
                    }
                )
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results_content: list[dict[str, Any]] = []
            for tc in stream_tool_calls:
                all_tool_calls.append(tc)

                if not self.sandbox.check_tool_call():
                    tool_results_content.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc["id"],
                            "content": "Tool call limit exceeded",
                            "is_error": True,
                        }
                    )
                    continue

                tool = self.tool_registry.get(tc["name"])
                if tool:
                    tool_start = time.monotonic()
                    try:
                        from engine import progress as _wm_progress

                        await _wm_progress.publish(
                            self.execution_id,
                            {
                                "phase": "tool_call",
                                "tool": tc["name"],
                                "arguments_preview": _short(tc.get("arguments")),
                                "agent_id": self.agent_id,
                            },
                        )
                    except Exception:
                        pass
                    from engine.tracing import get_tracer as _gt

                    _tracer = _gt("abenix.agent_executor")
                    with _tracer.start_as_current_span(f"tool.{tc['name']}") as _tspan:
                        _tspan.set_attribute("tool.name", tc["name"])
                        _tspan.set_attribute(
                            "tool.args_preview", _short(tc.get("arguments"))
                        )
                        result = await tool.execute(tc["arguments"])
                        _tspan.set_attribute(
                            "tool.is_error", bool(getattr(result, "is_error", False))
                        )
                    tool_dur = int((time.monotonic() - tool_start) * 1000)
                    try:
                        from engine import progress as _wm_progress

                        await _wm_progress.publish(
                            self.execution_id,
                            {
                                "phase": "tool_result",
                                "tool": tc["name"],
                                "is_error": bool(result.is_error),
                                "duration_ms": tool_dur,
                                "result_preview": (result.content or "")[:240],
                                "agent_id": self.agent_id,
                            },
                        )
                    except Exception:
                        pass
                    tool_execution_duration_seconds.labels(
                        tool_name=tc["name"]
                    ).observe(tool_dur / 1000)
                else:
                    result = ToolResult(
                        content=f"Unknown tool: {tc['name']}", is_error=True
                    )
                    tool_dur = 0

                self.sandbox.check_output_size(result.content)

                # Same enrichment as the non-stream path: stamp output_summary
                # back onto the tool_call entry so downstream callers can
                # canonical-anchor without round-tripping the tool.
                tc["output_summary"] = _build_output_summary(
                    result.metadata, bool(result.is_error)
                )

                yield ExecutionEvent(
                    event="tool_result",
                    data={"name": tc["name"], "result": result.content},
                )

                _trace = {
                    "node_type": "tool_call",
                    "tool": tc["name"],
                    "duration_ms": tool_dur,
                    "input": tc["arguments"],
                    "output_preview": result.content[:500],
                    "output": _persisted_result(result.content),
                    "is_error": result.is_error,
                    "metadata": result.metadata,
                    "output_summary": tc["output_summary"],
                }
                # the tool_call event went out before the tool ran, so the result rides on the trace
                tc["result_preview"] = result.content[:500]
                tc["result"] = _persisted_result(result.content)
                tc["is_error"] = bool(result.is_error)
                tc["duration_ms"] = tool_dur
                _attach_decision_record(tc, result)
                self._node_traces.append(_trace)
                yield ExecutionEvent(event="node_trace", data=_trace)

                # Truncate large tool results to prevent context overflow
                context_content = _model_visible_content(result)
                tool_results_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": context_content,
                        "is_error": result.is_error,
                    }
                )

            messages.append({"role": "user", "content": tool_results_content})

            # Check if accumulated context is approaching the limit
            est_tokens = _estimate_messages_tokens(messages)
            if est_tokens > CONTEXT_TOKEN_BUDGET:
                logger.warning(
                    "Context budget exceeded (%d est. tokens), stopping stream",
                    est_tokens,
                )
                yield ExecutionEvent(
                    event="token",
                    data={
                        "content": "\n\n*Context limit reached — returning results gathered so far.*"
                    },
                )
                break

        duration = int((time.monotonic() - start) * 1000)
        agent_execution_duration_seconds.observe(duration / 1000)
        agent_active_streams.dec()
        _grounding_failed = self._grounding_violated(all_tool_calls)
        _done_payload2: dict[str, Any] = {
            "total_tokens": total_input + total_output,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cost": round(total_cost, 6),
            "duration_ms": duration,
            "model": self.model,
            # Same contract as the early-return payload above, so the API
            # persists model_used on both streaming exits rather than only one.
            "effective_model": effective_model or self.model,
            "fallback_reason": effective_fallback_reason,
        }
        _missing = self._missing_required(all_tool_calls)
        if _grounding_failed:
            _done_payload2["error"] = "grounding_required_violation"
            _done_payload2["grounding_violation"] = True
            _done_payload2["missing_tools"] = _missing
            if _missing == [GROUNDING_REQUIRED_TOOL]:
                _done_payload2["grounding_block_source"] = (
                    "no_knowledge_search_invocation"
                )
                yield ExecutionEvent(
                    event="token", data=f"\n\n{GROUNDING_REQUIRED_ERROR}"
                )
            else:
                _done_payload2["failure_code"] = "REQUIRED_TOOLS_VIOLATION"
                _done_payload2["grounding_block_source"] = "missing: " + ", ".join(
                    _missing
                )
                yield ExecutionEvent(
                    event="token",
                    data=f"\n\n[required tools not called: {', '.join(_missing)}]",
                )
        elif not all_tool_calls and self.tool_registry.names():
            _done_payload2["warnings"] = [
                "completed without calling any tool although tools were available"
            ]
        yield ExecutionEvent(event="done", data=_done_payload2)

    async def _budget_stop_events(
        self,
        start: float,
        total_input: int,
        total_output: int,
        total_cost: float,
        iteration: int,
        effective_model: str | None,
        fallback_reason: str | None,
    ) -> AsyncGenerator[ExecutionEvent, None]:
        duration = int((time.monotonic() - start) * 1000)
        agent_execution_duration_seconds.observe(duration / 1000)
        agent_active_streams.dec()
        msg = self._budget_stop_text(total_cost)
        trace = {
            "node_type": "budget_stop",
            "iteration": iteration,
            "cost_limit": self.cost_limit,
            "spent": round(total_cost, 6),
            "is_error": True,
            "output_preview": msg,
        }
        self._node_traces.append(trace)
        yield ExecutionEvent(event="node_trace", data=trace)
        yield ExecutionEvent(event="token", data=f"\n\n{msg}")
        yield ExecutionEvent(
            event="done",
            data={
                "total_tokens": total_input + total_output,
                "input_tokens": total_input,
                "output_tokens": total_output,
                "cost": round(total_cost, 6),
                "duration_ms": duration,
                "model": self.model,
                "effective_model": effective_model or self.model,
                "fallback_reason": fallback_reason,
                "error": msg,
                "failure_code": BUDGET_EXCEEDED,
                "budget_exceeded": True,
                "cost_limit": self.cost_limit,
            },
        )


_TOOL_CLASSES_LOADED = False
_TOOL_CLASSES: dict[str, type] = {}
_CONTEXT_TOOL_FACTORIES: dict[str, Any] = {}


def get_tool_class(slug: str) -> type | None:
    """Public registry lookup. Used by the direct-execute API.

    Falls through to the context-tool factory map so tools that need
    constructor args (ml_model, code_asset, memory_*, meeting_*) are
    still reachable via /api/tools/{slug}/execute. The direct-execute
    caller passes tenant_id + execution_id which satisfies those
    constructors.
    """
    _ensure_tool_classes()
    cls = _TOOL_CLASSES.get(slug)
    if cls is not None:
        return cls
    return _CONTEXT_TOOL_FACTORIES.get(slug)


def list_tool_classes() -> list[str]:
    _ensure_tool_classes()
    return sorted(list(_TOOL_CLASSES.keys()) + list(_CONTEXT_TOOL_FACTORIES.keys()))


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
    from engine.tools.monte_carlo_curve import MonteCarloCurveTool
    from engine.tools.realized_vol_calc import RealizedVolCalcTool
    from engine.tools.eex_public_summary import EexPublicSummaryTool
    from engine.tools.event_stream import (
        EventBufferTool,
        RedisStreamConsumerTool,
        RedisStreamPublisherTool,
        KafkaConsumerTool,
    )
    from engine.tools.llm_route import LLMRouteTool
    from engine.tools.tavily_search import TavilySearchTool
    from engine.tools.news_feed import NewsFeedTool
    from engine.tools.academic_search import AcademicSearchTool
    from engine.tools.yahoo_finance import YahooFinanceTool
    from engine.tools.options_data import OptionsDataTool
    from engine.tools.entso_e_tool import EntsoETool
    from engine.tools.ember_tool import EmberClimateTool
    from engine.tools.ecb_rates_tool import ECBRatesTool
    from engine.tools.eia_open_data import EiaOpenDataTool
    from engine.tools.open_meteo import OpenMeteoTool
    from engine.tools.ais_stream import AisStreamTool
    from engine.tools.bunker_fuel import BunkerFuelTool
    from engine.tools.vessel_specs import VesselSpecsTool
    from engine.tools.refined_products_forwards import RefinedProductsForwardsTool
    from engine.tools.freight_worldscale import FreightWorldscaleTool
    from engine.tools.freight_baltic_blpg import FreightBalticBlpgTool
    from engine.tools.port_constraints import PortConstraintsTool

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
    from engine.tools.connector_call import ConnectorCallTool
    from engine.tools.approval_gate import ApprovalGateTool
    from engine.tools.mqtt_publish import MqttPublishTool
    from engine.tools.tsdb_query import TsdbQueryTool
    from engine.tools.windowed_state import WindowedStateTool
    from engine.tools.subscribed_feed import SubscribedFeedTool

    _TOOL_CLASSES.update(
        {
            "web_search": WebSearchTool,
            "calculator": CalculatorTool,
            "file_reader": FileReaderTool,
            "current_time": CurrentTimeTool,
            "document_extractor": DocumentExtractorTool,
            "csv_analyzer": CsvAnalyzerTool,
            "financial_calculator": FinancialCalculatorTool,
            "risk_analyzer": RiskAnalyzerTool,
            "market_data": MarketDataTool,
            "json_transformer": JsonTransformerTool,
            "text_analyzer": TextAnalyzerTool,
            "http_client": HttpClientTool,
            "code_executor": CodeExecutorTool,
            "date_calculator": DateCalculatorTool,
            "regex_extractor": RegexExtractorTool,
            "unit_converter": UnitConverterTool,
            "spreadsheet_analyzer": SpreadsheetAnalyzerTool,
            "presentation_analyzer": PresentationAnalyzerTool,
            "data_exporter": DataExporterTool,
            "api_connector": ApiConnectorTool,
            "llm_call": LLMCallTool,
            "email_sender": EmailSenderTool,
            "data_merger": DataMergerTool,
            "github_tool": GitHubTool,
            "agent_step": AgentStepTool,
            "sub_pipeline": SubPipelineTool,
            "database_query": DatabaseQueryTool,
            "database_writer": DatabaseWriterTool,
            "cloud_storage": CloudStorageTool,
            "image_analyzer": ImageAnalyzerTool,
            "file_system": FileSystemTool,
            "schema_validator": SchemaValidatorTool,
            "structured_analyzer": StructuredAnalyzerTool,
            "speech_to_text": SpeechToTextTool,
            "text_to_speech": TextToSpeechTool,
            "integration_hub": IntegrationHubTool,
            "pii_redactor": PIIRedactorTool,
            "time_series_analyzer": TimeSeriesAnalyzerTool,
            "monte_carlo_curve": MonteCarloCurveTool,
            "realized_vol_calc": RealizedVolCalcTool,
            "eex_public_summary": EexPublicSummaryTool,
            "event_buffer": EventBufferTool,
            "redis_stream_consumer": RedisStreamConsumerTool,
            "redis_stream_publisher": RedisStreamPublisherTool,
            "kafka_consumer": KafkaConsumerTool,
            "llm_route": LLMRouteTool,
            "tavily_search": TavilySearchTool,
            "news_feed": NewsFeedTool,
            "academic_search": AcademicSearchTool,
            "yahoo_finance": YahooFinanceTool,
            "options_data": OptionsDataTool,
            "entso_e": EntsoETool,
            "ember_climate": EmberClimateTool,
            "ecb_rates": ECBRatesTool,
            "eia_open_data": EiaOpenDataTool,
            "open_meteo": OpenMeteoTool,
            "ais_stream": AisStreamTool,
            "bunker_fuel": BunkerFuelTool,
            "vessel_specs": VesselSpecsTool,
            "refined_products_forwards": RefinedProductsForwardsTool,
            "freight_worldscale": FreightWorldscaleTool,
            "freight_baltic_blpg": FreightBalticBlpgTool,
            "port_constraints": PortConstraintsTool,
            "weather": WeatherTool,
            "geocoding": GeocodingTool,
            "world_bank": WorldBankTool,
            "crypto_market": CryptoMarketTool,
            "fred_economic": FredEconomicTool,
            "gov_data_us": GovDataUSTool,
            "patents_trademarks": PatentsTrademarksTool,
            "mermaid_diagram": MermaidDiagramTool,
            "semantic_diff": SemanticDiffTool,
            "address_normalize": AddressNormalizeTool,
            "translation": TranslationTool,
            "plotly_chart": PlotlyChartTool,
            "twilio_sms": TwilioSmsTool,
            "browser_automation": BrowserAutomationTool,
            "cloud_cost": CloudCostTool,  # sandboxed_job moved to _CONTEXT_TOOL_FACTORIES (needs tenant_id)
            "zapier_pass_through": ZapierPassThroughTool,
        }
    )
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
    from engine.tools.kyc_met_pdf_extractor import KycMetPdfExtractorTool
    from engine.tools.country_cpi_lookup import CountryCpiLookupTool
    from engine.tools.industry_segment_risk import IndustrySegmentRiskTool
    from engine.tools.moodys_orbis_lookup import MoodysOrbisLookupTool
    from engine.tools.notional_volume_score import NotionalVolumeScoreTool

    # Public regulatory / credit data sources — generic, any tenant can use them.
    from engine.tools.phmsa_lookup import PhmsaLookupTool
    from engine.tools.epa_echo import EpaEchoTool
    from engine.tools.moodys_api import MoodysApiTool
    from engine.tools.bundesanzeiger import BundesanzeigerTool
    from engine.tools.ferc_elibrary import FercElibraryTool
    from engine.tools.companies_house import CompaniesHouseTool
    from engine.tools.edgar_filings import EdgarFilingsTool
    from engine.tools.spg_ratings import SPGRatingsTool
    from engine.tools.fitch_connect import FitchConnectTool

    _TOOL_CLASSES.update(
        {
            "sanctions_screening": SanctionsScreeningTool,
            "pep_screening": PEPScreeningTool,
            "adverse_media": AdverseMediaTool,
            "ubo_discovery": UBODiscoveryTool,
            "country_risk_index": CountryRiskIndexTool,
            "legal_existence_verifier": LegalExistenceVerifierTool,
            "kyc_scorer": KYCScorerTool,
            "regulatory_enforcement": RegulatoryEnforcementTool,
            "kyc_met_pdf_extractor": KycMetPdfExtractorTool,
            "country_cpi_lookup": CountryCpiLookupTool,
            "industry_segment_risk": IndustrySegmentRiskTool,
            "moodys_orbis_lookup": MoodysOrbisLookupTool,
            "notional_volume_score": NotionalVolumeScoreTool,
            "phmsa_lookup": PhmsaLookupTool,
            "epa_echo": EpaEchoTool,
            "moodys_api": MoodysApiTool,
            "bundesanzeiger_filings": BundesanzeigerTool,
            "ferc_elibrary": FercElibraryTool,
            "companies_house": CompaniesHouseTool,
            "edgar_filings": EdgarFilingsTool,
            "spg_ratings_api": SPGRatingsTool,
            "fitch_connect": FitchConnectTool,
            "connector_call": ConnectorCallTool,
            "mqtt_publish": MqttPublishTool,
            "tsdb_query": TsdbQueryTool,
            "windowed_state": WindowedStateTool,
            "subscribed_feed": SubscribedFeedTool,
        }
    )
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
    from engine.tools.invoke_agent import InvokeAgentTool
    from engine.tools.recall_trajectory import RecallTrajectoryTool
    from engine.tools.narrate import NarrateTool
    from engine.tools.knowledge_search import KnowledgeSearchTool
    from engine.tools.vector_search import VectorSearchTool
    from engine.tools.graph_explorer_tool import GraphExplorerTool
    from engine.tools.schema_portfolio_tool import SchemaPortfolioTool
    from engine.tools.atlas_tools import (
        AtlasQueryTool,
        AtlasTraverseTool,
        AtlasSearchGroundedTool,
        AtlasDescribeTool,
        AtlasAsOfTool,
    )
    from engine.tools.decision_tools import DECISION_TOOLS
    from engine.tools.source_tools import SOURCE_TOOLS

    _CONTEXT_TOOL_FACTORIES.update(DECISION_TOOLS)
    _CONTEXT_TOOL_FACTORIES.update(SOURCE_TOOLS)
    _CONTEXT_TOOL_FACTORIES.update(
        {
            "memory_store": MemoryStoreTool,
            "memory_recall": MemoryRecallTool,
            "memory_forget": MemoryForgetTool,
            "human_approval": HumanApprovalTool,
            "approval_gate": ApprovalGateTool,
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
            "invoke_agent": InvokeAgentTool,
            "recall_trajectory": RecallTrajectoryTool,
            "narrate": NarrateTool,
            "knowledge_search": KnowledgeSearchTool,
            "vector_search": VectorSearchTool,
            "graph_explorer": GraphExplorerTool,
            "schema_portfolio_tool": SchemaPortfolioTool,
            "atlas_query": AtlasQueryTool,
            "atlas_traverse": AtlasTraverseTool,
            "atlas_search_grounded": AtlasSearchGroundedTool,
            "atlas_describe": AtlasDescribeTool,
            "atlas_as_of": AtlasAsOfTool,
        }
    )
    _TOOL_CLASSES_LOADED = True


async def resolve_asset_schemas(
    tool_config: dict[str, dict[str, Any]] | None,
    tenant_id: str = "",
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
                    # Scope to the tenant whenever the caller knows it.
                    tenant_clause = (
                        " AND tenant_id = CAST(:tid AS uuid)" if tenant_id else ""
                    )
                    params: dict[str, Any] = (
                        {"tid": str(tenant_id)} if tenant_id else {}
                    )
                    if asset_id:
                        r = await conn.execute(
                            _sql_text(
                                "SELECT input_schema FROM code_assets "
                                "WHERE id = CAST(:id AS uuid)" + tenant_clause
                            ),
                            {"id": str(asset_id), **params},
                        )
                        row = r.first()
                    elif model_id:
                        r = await conn.execute(
                            _sql_text(
                                "SELECT input_schema FROM ml_models "
                                "WHERE id = CAST(:id AS uuid)" + tenant_clause
                            ),
                            {"id": str(model_id), **params},
                        )
                        row = r.first()
                    if row and row[0]:
                        out[tool_name] = {"input_schema": row[0]}
        finally:
            await engine.dispose()
    except Exception as e:
        import logging as _log

        _log.getLogger(__name__).warning(
            "resolve_asset_schemas failed (LLM will see generic input schema): %s",
            e,
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
    user_id: str = "",
    user_role: str = "",
    delegation_depth: int = 0,
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
    ApprovalGateCls = _CONTEXT_TOOL_FACTORIES.get("approval_gate")
    if ApprovalGateCls:
        context_tools["approval_gate"] = lambda: ApprovalGateCls(
            execution_id=execution_id,
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            user_role=user_role,
        )
    MLModelCls = _CONTEXT_TOOL_FACTORIES.get("ml_model")
    if MLModelCls:
        context_tools["ml_model"] = lambda: MLModelCls(
            db_url=db_url,
            tenant_id=tenant_id,
            execution_id=execution_id,
            agent_id=agent_id,
        )
    SandboxCls = _CONTEXT_TOOL_FACTORIES.get("sandboxed_job")
    if SandboxCls:
        # Tenant-scoped Redis overrides for enabled / allow_network / allowed_images
        # are read at execute time; falls back to env vars when nothing is set.
        import os as _os

        _redis_url = _os.environ.get("REDIS_URL", "")
        context_tools["sandboxed_job"] = lambda: SandboxCls(
            tenant_id=tenant_id,
            redis_url=_redis_url,
        )
    from engine.tools.decision_tools import DECISION_TOOLS as _DECISION_TOOLS
    from engine.tools.source_tools import SOURCE_TOOLS as _SOURCE_TOOLS

    _acting_user = ""
    if acting_subject and isinstance(acting_subject, dict):
        _acting_user = str(
            acting_subject.get("user_id") or acting_subject.get("sub") or ""
        )
    for _dname, _DCls in {**_DECISION_TOOLS, **_SOURCE_TOOLS}.items():
        context_tools[_dname] = lambda Cls=_DCls: Cls(
            tenant_id=tenant_id,
            execution_id=execution_id,
            user_id=user_id or _acting_user,
            agent_name=agent_name,
        )
    CodeAssetCls = _CONTEXT_TOOL_FACTORIES.get("code_asset")
    if CodeAssetCls:
        import os as _os2

        _redis_url2 = _os2.environ.get("REDIS_URL", "")
        context_tools["code_asset"] = lambda: CodeAssetCls(
            tenant_id=tenant_id,
            redis_url=_redis_url2,
            db_url=db_url,
            execution_id=execution_id,
            agent_id=agent_id,
        )

    # ── Meeting + persona + safety tools — all need execution context.
    # Extract user_id from acting_subject if available so persona_rag's
    # "self" scope + defer_to_human's notifications land on the right user.
    _user_id = str(user_id or "")
    if not _user_id and acting_subject and isinstance(acting_subject, dict):
        _user_id = str(acting_subject.get("user_id") or acting_subject.get("sub") or "")
    for _tool_name in (
        "meeting_join",
        "meeting_listen",
        "meeting_speak",
        "meeting_post_chat",
        "meeting_leave",
    ):
        _Cls = _CONTEXT_TOOL_FACTORIES.get(_tool_name)
        if not _Cls:
            continue
        if _tool_name == "meeting_join":
            # MeetingJoinTool needs the wider set for scope + user tracking
            context_tools[_tool_name] = lambda Cls=_Cls: Cls(
                execution_id=execution_id,
                tenant_id=tenant_id,
                user_id=_user_id,
                agent_id=agent_id,
            )
        else:
            context_tools[_tool_name] = lambda Cls=_Cls: Cls(execution_id=execution_id)
    PersonaRagCls = _CONTEXT_TOOL_FACTORIES.get("persona_rag")
    if PersonaRagCls:
        context_tools["persona_rag"] = lambda: PersonaRagCls(
            kb_ids=kb_ids or [],
            tenant_id=tenant_id,
            user_id=_user_id,
            execution_id=execution_id,
        )
    DeferCls = _CONTEXT_TOOL_FACTORIES.get("defer_to_human")
    if DeferCls:
        context_tools["defer_to_human"] = lambda: DeferCls(
            execution_id=execution_id,
            tenant_id=tenant_id,
            user_id=_user_id,
        )
    ScopeGateCls = _CONTEXT_TOOL_FACTORIES.get("scope_gate")
    if ScopeGateCls:
        context_tools["scope_gate"] = lambda: ScopeGateCls(execution_id=execution_id)

    InvokeAgentCls = _CONTEXT_TOOL_FACTORIES.get("invoke_agent")
    if InvokeAgentCls:
        # the sub-agent runs as whoever started this run, never the platform key owner
        context_tools["invoke_agent"] = lambda: InvokeAgentCls(
            tenant_id=str(tenant_id or ""),
            execution_id=str(execution_id or ""),
            agent_id=str(agent_id or ""),
            user_id=str(user_id or ""),
            user_role=user_role,
            delegation_depth=delegation_depth,
        )

    from engine.tools.agent_step import AgentStepTool as _AgentStep

    context_tools["agent_step"] = lambda: _AgentStep(
        user_id=str(user_id or ""),
        user_role=user_role,
        delegation_depth=delegation_depth,
    )

    NarrateCls = _CONTEXT_TOOL_FACTORIES.get("narrate")
    if NarrateCls:
        context_tools["narrate"] = lambda: NarrateCls(
            execution_id=execution_id, agent_name=agent_name, agent_slug=agent_name
        )

    RecallCls = _CONTEXT_TOOL_FACTORIES.get("recall_trajectory")
    if RecallCls:
        context_tools["recall_trajectory"] = lambda: RecallCls(
            db_url=db_url, tenant_id=tenant_id
        )

    registry = ToolRegistry()
    unknown_tools: list[str] = []
    for name in tool_names:
        # Check context tools first (need constructor args)
        if name in context_tools:
            registry.register(context_tools[name]())
        elif name in available:
            registry.register(available[name]())
        elif name.startswith("portfolio_") and registry.get(name) is not None:
            continue  # registered above from the tenant's schemas
        else:
            unknown_tools.append(name)

    if unknown_tools:
        # Names outside the registry may be saved tools. Only approved rows load, into the sandbox.
        from engine.tools.dynamic_tool import DynamicTool, fetch_saved_tools

        saved = fetch_saved_tools(str(tenant_id or ""), db_url, unknown_tools)
        for name in unknown_tools:
            row = saved.get(name)
            if row is None:
                logger.warning(
                    "Unknown tool requested: %s (agent %s)", name, agent_id or "-"
                )
            elif row.get("status") != "approved":
                logger.warning(
                    "Saved tool %s is %s, not approved, skipped (agent %s)",
                    name,
                    row.get("status") or "pending",
                    agent_id or "-",
                )
            else:
                registry.register(
                    DynamicTool(
                        tool_name=name,
                        tool_description=row.get("description") or "",
                        tool_code=row.get("code") or "",
                        permissions=row.get("permissions") or {},
                        input_schema=row.get("input_schema") or {},
                    )
                )
                logger.info(
                    "Loaded approved saved tool %s (agent %s)", name, agent_id or "-"
                )

    # Each tool is tenant-scoped; if the agent's model_config carries
    # `atlas_graphs: ["uuid", ...]`, that list further restricts which
    # graphs the tool can read. With no list, the agent sees every
    # atlas in its tenant — same boundary as every other tenant tool.
    atlas_allow = (
        list((model_config or {}).get("atlas_graphs") or [])
        if isinstance(model_config, dict)
        else []
    )
    atlas_tool_requested = any(name.startswith("atlas_") for name in tool_names)
    if atlas_tool_requested:
        try:
            from engine.tools.atlas_tools import ATLAS_TOOL_NAMES

            for name in tool_names:
                cls = ATLAS_TOOL_NAMES.get(name)
                if cls and name not in registry.names():
                    registry.register(
                        cls(
                            tenant_id=str(tenant_id),
                            agent_id=str(agent_id),
                            allowed_graph_ids=atlas_allow,
                        )
                    )
                    logger.info(
                        "Registered %s with allow=%s",
                        name,
                        atlas_allow or "<all-tenant>",
                    )
        except Exception as e:
            logger.error("Failed to register atlas tools: %s", e)

    if kb_ids:
        # Register hybrid knowledge search (graph + vector) as primary
        try:
            from engine.tools.knowledge_search import KnowledgeSearchTool

            registry.register(
                KnowledgeSearchTool(
                    kb_ids=kb_ids,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    user_role=user_role,
                )
            )
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

    logger.info(
        "build_tool_registry: acting_subject=%s, tool_names=%s",
        acting_subject,
        tool_names,
    )
    # portfolio_<domain> reads rows scoped to the actAs subject, or to the user running the agent
    _portfolio_scope = str(
        (
            (acting_subject or {}).get("subject_id")
            if isinstance(acting_subject, dict)
            else ""
        )
        or user_id
        or ""
    )
    for tname in tool_names:
        if tname.startswith("portfolio_") and _portfolio_scope:
            domain = tname[len("portfolio_") :]
            try:
                from engine.tools.schema_portfolio_tool import SchemaPortfolioTool

                registry.register(
                    SchemaPortfolioTool(
                        domain_name=domain,
                        user_id=_portfolio_scope,
                        tenant_id=str(tenant_id),
                        db_url=db_url,
                    )
                )
            except Exception as e:
                logger.error("Failed to register %s tool: %s", tname, e)

    if acting_subject:
        subject_id = acting_subject.get("subject_id")
        subject_type = acting_subject.get("subject_type") or "subject"
        kb_namespace = f"{subject_type}-{subject_id}" if subject_id else None

        if "graph_explorer" in tool_names and kb_namespace:
            try:
                from engine.tools.graph_explorer_tool import GraphExplorerTool

                registry.register(GraphExplorerTool(kb_id=kb_namespace))
                logger.info(
                    "Registered graph_explorer tool with kb_id %s", kb_namespace
                )
            except Exception as e:
                logger.error("Failed to register graph_explorer tool: %s", e)

        # knowledge_search needs kb_ids — register it with a subject-namespaced KB if not already
        if (
            "knowledge_search" in tool_names
            and "knowledge_search" not in registry.names()
            and kb_namespace
        ):
            try:
                from engine.tools.knowledge_search import KnowledgeSearchTool

                registry.register(
                    KnowledgeSearchTool(
                        kb_ids=[kb_namespace],
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        user_id=user_id,
                        user_role=user_role,
                    )
                )
                logger.info("Registered knowledge_search with kb_id %s", kb_namespace)
            except Exception as e:
                logger.error("Failed to register knowledge_search tool: %s", e)

    return registry
