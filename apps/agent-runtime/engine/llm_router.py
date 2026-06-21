from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import anthropic
from google import genai as google_genai
from google.genai import types as google_types
import openai

from engine.langfuse_tracer import get_langfuse_tracer
from engine.metrics import (
    llm_errors_total,
    llm_request_duration_seconds,
    llm_tokens_total,
)

logger = logging.getLogger(__name__)

PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-opus-4-6-20250106": {"input": 15.0 / 1_000_000, "output": 75.0 / 1_000_000},
    "claude-opus-4-6": {"input": 15.0 / 1_000_000, "output": 75.0 / 1_000_000},
    "claude-sonnet-4-6-20250106": {
        "input": 3.0 / 1_000_000,
        "output": 15.0 / 1_000_000,
    },
    "claude-sonnet-4-6": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "claude-sonnet-4-5-20250929": {
        "input": 3.0 / 1_000_000,
        "output": 15.0 / 1_000_000,
    },
    "claude-sonnet-4-20250514": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "claude-haiku-4-5-20251001": {"input": 1.0 / 1_000_000, "output": 5.0 / 1_000_000},
    "claude-haiku-4-5": {"input": 1.0 / 1_000_000, "output": 5.0 / 1_000_000},
    "claude-haiku-3-5-20241022": {"input": 0.80 / 1_000_000, "output": 4.0 / 1_000_000},
    # OpenAI
    "gpt-4o": {"input": 2.50 / 1_000_000, "output": 10.0 / 1_000_000},
    "gpt-4o-mini": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    # Google
    "gemini-2.0-flash": {"input": 0.10 / 1_000_000, "output": 0.40 / 1_000_000},
    "gemini-2.5-flash": {"input": 0.30 / 1_000_000, "output": 2.50 / 1_000_000},
    "gemini-2.5-pro": {"input": 1.25 / 1_000_000, "output": 10.0 / 1_000_000},
    "gemini-1.5-pro": {"input": 1.25 / 1_000_000, "output": 5.00 / 1_000_000},
}

import os as _os

_DEFAULT_INPUT_PER_M = float(_os.environ.get("LLM_DEFAULT_PRICING_INPUT_PER_M", "3.0"))
_DEFAULT_OUTPUT_PER_M = float(
    _os.environ.get("LLM_DEFAULT_PRICING_OUTPUT_PER_M", "15.0")
)
DEFAULT_PRICING = {
    "input": _DEFAULT_INPUT_PER_M / 1_000_000,
    "output": _DEFAULT_OUTPUT_PER_M / 1_000_000,
}


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: float
    latency_ms: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = (
        None  # "end_turn" | "max_tokens" | "stop_sequence" | "tool_use"
    )
    requested_model: str | None = None
    fallback_reason: str | None = None


@dataclass
class StreamEvent:
    event: str
    data: Any


_DB_PRICING_CACHE: dict[str, dict[str, float]] = {}
_DB_PRICING_CACHE_AT: float = 0.0
_DB_PRICING_TTL = (
    60.0  # seconds — long enough to amortise, short enough to pick up admin edits
)


_DB_PROVIDER_CACHE: dict[str, str] = {}


def _clear_stale_unavailable(model: str, latency_ms: int) -> None:
    """Self-heal: a real call just succeeded, so wipe any stale 'unavailable'
    marker the hourly prober left behind (e.g. from a previous bad API key).
    Best-effort — never raises, never blocks the caller."""
    if latency_ms >= 30_000:
        return
    import os as _os_s

    db_url = _os_s.environ.get("DATABASE_URL", "")
    if not db_url:
        return
    sync_url = db_url.replace("+asyncpg", "").replace(
        "postgresql+asyncpg", "postgresql"
    )
    if "?" in sync_url:
        base, query = sync_url.split("?", 1)
        kept = [p for p in query.split("&") if not p.lower().startswith("ssl=")]
        sync_url = base + (("?" + "&".join(kept)) if kept else "")
    try:
        import psycopg2

        conn = psycopg2.connect(sync_url, connect_timeout=2)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE model_availability
                       SET status = 'available',
                           last_error = NULL,
                           consecutive_failures = 0,
                           status_since = NOW(),
                           last_ok_at = NOW(),
                           last_checked_at = NOW()
                     WHERE model = %s AND status = 'unavailable'
                    """,
                    (model,),
                )
                updated = cur.rowcount
                if updated > 0:
                    cur.execute(
                        """
                        INSERT INTO model_availability_events (model, from_status, to_status, error)
                        VALUES (%s, 'unavailable', 'available', 'self_heal_runtime_success')
                        """,
                        (model,),
                    )
                conn.commit()
                if updated > 0:
                    try:
                        from engine.model_resolver import invalidate_cache as _inv

                        _inv()
                    except Exception:
                        pass
                    logger.info(
                        "self_heal cleared stale unavailable marker for model=%s",
                        model,
                    )
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("self_heal skipped for %s: %s", model, exc)


def _load_db_pricing() -> dict[str, dict[str, float]]:
    """Fetch the current per-model pricing rows from `llm_model_pricing`."""
    global _DB_PRICING_CACHE, _DB_PRICING_CACHE_AT, _DB_PROVIDER_CACHE
    import os as _os_i
    import time as _time_i

    now = _time_i.monotonic()
    if _DB_PRICING_CACHE and (now - _DB_PRICING_CACHE_AT) < _DB_PRICING_TTL:
        return _DB_PRICING_CACHE

    db_url = _os_i.environ.get("DATABASE_URL", "")
    if not db_url:
        return {}
    # psycopg2 sync URL (this function runs in a sync context from
    # providers.complete() and we don't want to buy an asyncpg pool
    # just for this).
    sync_url = db_url.replace("+asyncpg", "").replace(
        "postgresql+asyncpg", "postgresql"
    )
    if "?" in sync_url:
        base, query = sync_url.split("?", 1)
        kept = [p for p in query.split("&") if not p.lower().startswith("ssl=")]
        sync_url = base + (("?" + "&".join(kept)) if kept else "")

    try:
        import psycopg2

        conn = psycopg2.connect(sync_url, connect_timeout=2)
        try:
            with conn.cursor() as cur:
                # Latest effective row per model. DISTINCT ON is a cheap
                # Postgres-native "latest-per-group" idiom.
                cur.execute(
                    """
                    SELECT DISTINCT ON (model)
                        model,
                        provider,
                        input_per_m,
                        output_per_m,
                        cached_input_per_m
                    FROM llm_model_pricing
                    WHERE is_active = TRUE AND effective_from <= NOW()
                    ORDER BY model, effective_from DESC
                    """
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        result = {}
        providers: dict[str, str] = {}
        for model, provider, inp, out, cached in rows:
            result[model] = {
                "input": float(inp) / 1_000_000,
                "output": float(out) / 1_000_000,
                "cached_input": (
                    (float(cached) / 1_000_000) if cached is not None else None
                ),
            }
            if provider:
                providers[model] = str(provider).lower()
        _DB_PRICING_CACHE = result
        _DB_PROVIDER_CACHE = providers
        _DB_PRICING_CACHE_AT = now
        return result
    except Exception as e:
        logger.debug(
            "llm_model_pricing load failed, falling back to code constants: %s", e
        )
        return {}


def _calc_cost(
    model: str, input_tokens: int, output_tokens: int, latency_ms: int = 0
) -> float:
    """Compute $ cost for an LLM call. Resolution order:"""
    db_prices = _load_db_pricing()
    prices = db_prices.get(model) or PRICING.get(model) or DEFAULT_PRICING
    cost = input_tokens * prices["input"] + output_tokens * prices["output"]
    _emit_llm_metrics(model, input_tokens, output_tokens, cost, latency_ms)
    return cost


def _provider_for(model: str) -> str:
    """Map model id → provider label for Prometheus. Keeps the cardinality"""
    m = model.lower()
    if m.startswith("azure-"):
        return "azure"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gpt"):
        return "openai"
    if m.startswith("gemini"):
        return "google"
    return "other"


def _emit_llm_metrics(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost: float,
    duration_ms: int,
) -> None:
    """Push a single LLM call into the prometheus counters. Swallowed
    on any error so a telemetry glitch never takes down an agent run."""
    try:
        from engine import metrics as _m

        provider = _provider_for(model)
        _m.LLM_TOKENS.labels(provider=provider, model=model, direction="input").inc(
            input_tokens
        )
        _m.LLM_TOKENS.labels(provider=provider, model=model, direction="output").inc(
            output_tokens
        )
        _m.LLM_COST_USD.labels(provider=provider, model=model).inc(cost)
        _m.LLM_DURATION.labels(provider=provider, model=model).observe(
            duration_ms / 1000.0
        )
    except Exception:
        pass


def _anthropic_tools_schema(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        out.append(
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            }
        )
    return out


def _translate_messages_for_openai(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Translate Anthropic-style message history into OpenAI chat format.

    The agent executor records tool calls as Anthropic content blocks
    (tool_use / tool_result). OpenAI's chat API wants tool_calls on the
    assistant message and a separate role:"tool" message per result.
    We also have to rewrite the toolu_* ids to call_* ids OpenAI accepts
    and keep the mapping consistent across the assistant + tool turns.
    """
    import json as _json

    out: list[dict[str, Any]] = []
    tool_id_map: dict[str, str] = {}
    counter = 0

    def _map_id(anth_id: str) -> str:
        nonlocal counter
        if anth_id in tool_id_map:
            return tool_id_map[anth_id]
        if anth_id.startswith("call_"):
            tool_id_map[anth_id] = anth_id
            return anth_id
        counter += 1
        mapped = f"call_{counter}_{anth_id[-8:] if len(anth_id) > 8 else anth_id}"
        tool_id_map[anth_id] = mapped
        return mapped

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if not isinstance(content, list):
            out.append(
                {"role": role, "content": content if content is not None else ""}
            )
            continue

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in content:
                if not isinstance(block, dict):
                    text_parts.append(str(block))
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    mapped = _map_id(block.get("id", ""))
                    tool_calls.append(
                        {
                            "id": mapped,
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": _json.dumps(block.get("input", {}) or {}),
                            },
                        }
                    )
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(text_parts) if text_parts else None,
            }
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            out.append(assistant_msg)
            continue

        if role == "user":
            text_parts = []
            tool_result_msgs: list[dict[str, Any]] = []
            for block in content:
                if not isinstance(block, dict):
                    text_parts.append(str(block))
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_result":
                    raw = block.get("content", "")
                    if isinstance(raw, list):
                        flat = "".join(
                            (b.get("text", "") if isinstance(b, dict) else str(b))
                            for b in raw
                        )
                    elif isinstance(raw, (dict, list)):
                        flat = _json.dumps(raw)
                    else:
                        flat = str(raw) if raw is not None else ""
                    tool_result_msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": _map_id(block.get("tool_use_id", "")),
                            "content": flat,
                        }
                    )
            # Emit any leading user text first, then each tool message.
            if text_parts:
                joined = "".join(text_parts)
                if joined.strip() or not tool_result_msgs:
                    out.append({"role": "user", "content": joined})
            out.extend(tool_result_msgs)
            continue

        # system or anything else: flatten text blocks
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            else:
                text_parts.append(str(block))
        out.append({"role": role, "content": "".join(text_parts)})

    return out


def _openai_tools_schema(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
        )
    return out


def _google_tools_schema(
    tools: list[dict[str, Any]],
) -> list[google_types.Tool]:
    """Convert internal tool format to Google GenAI FunctionDeclarations."""

    def _to_schema(prop_def: dict[str, Any]) -> google_types.Schema:
        prop_type = str(prop_def.get("type", "string")).upper()
        kwargs: dict[str, Any] = {
            "type": prop_type,
            "description": prop_def.get("description", "") or "",
        }
        # Enum (e.g. "type": "string", "enum": [...])
        if prop_def.get("enum"):
            kwargs["enum"] = [str(x) for x in prop_def["enum"]]
        # Array: must carry items
        if prop_type == "ARRAY":
            items = prop_def.get("items") or {"type": "string"}
            kwargs["items"] = _to_schema(items)
        # Object: must carry properties (and required if present)
        if prop_type == "OBJECT":
            inner_props = prop_def.get("properties", {})
            if inner_props:
                kwargs["properties"] = {
                    k: _to_schema(v) for k, v in inner_props.items()
                }
            if prop_def.get("required"):
                kwargs["required"] = list(prop_def["required"])
        return google_types.Schema(**kwargs)

    declarations = []
    for t in tools:
        schema = t.get("input_schema", {})
        properties_raw = schema.get("properties", {})
        properties = {k: _to_schema(v) for k, v in properties_raw.items()}

        params = (
            google_types.Schema(
                type="OBJECT",
                properties=properties,
                required=schema.get("required", []),
            )
            if properties
            else None
        )

        declarations.append(
            google_types.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters=params,
            )
        )
    return [google_types.Tool(function_declarations=declarations)]


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        stream: bool = False,
        max_tokens: int = 4096,
    ) -> LLMResponse | AsyncGenerator[StreamEvent, None]: ...


class AnthropicProvider(LLMProvider):
    DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.client = anthropic.AsyncAnthropic()

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        stream: bool = False,
        max_tokens: int = 4096,
    ) -> LLMResponse | AsyncGenerator[StreamEvent, None]:
        model = model or self.DEFAULT_MODEL
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            system_text = str(system).strip()
            if system_text:
                kwargs["system"] = [
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
        if tools:
            kwargs["tools"] = _anthropic_tools_schema(tools)

        if stream:
            return self._stream(kwargs, model)
        return await self._non_stream(kwargs, model)

    async def _non_stream(self, kwargs: dict[str, Any], model: str) -> LLMResponse:
        start = time.monotonic()
        resp = await self.client.messages.create(**kwargs)
        latency = int((time.monotonic() - start) * 1000)

        content = ""
        tool_calls: list[dict[str, Any]] = []
        for block in resp.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.id,
                        "name": block.name,
                        "arguments": block.input,
                    }
                )

        cost = _calc_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        return LLMResponse(
            content=content,
            model=model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cost=cost,
            latency_ms=latency,
            tool_calls=tool_calls,
            stop_reason=getattr(resp, "stop_reason", None),
        )

    async def _stream(
        self, kwargs: dict[str, Any], model: str
    ) -> AsyncGenerator[StreamEvent, None]:
        start = time.monotonic()
        input_tokens = 0
        output_tokens = 0
        tool_calls: list[dict[str, Any]] = []
        current_tool: dict[str, Any] | None = None
        tool_json_buf = ""

        # Stream exceptions surface during iteration, NOT when the router
        # awaits provider.complete(). Catch them here so the outer counter
        # actually sees Anthropic 429/5xx/timeouts.
        try:
            async with self.client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "message_start":
                        input_tokens = event.message.usage.input_tokens
                    elif event.type == "content_block_start":
                        if event.content_block.type == "tool_use":
                            current_tool = {
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                            }
                            tool_json_buf = ""
                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            yield StreamEvent(event="token", data=event.delta.text)
                        elif event.delta.type == "input_json_delta":
                            tool_json_buf += event.delta.partial_json
                    elif event.type == "content_block_stop":
                        if current_tool:
                            import json

                            try:
                                args = (
                                    json.loads(tool_json_buf) if tool_json_buf else {}
                                )
                            except json.JSONDecodeError:
                                args = {}
                            current_tool["arguments"] = args
                            tool_calls.append(current_tool)
                            yield StreamEvent(
                                event="tool_call",
                                data={
                                    "name": current_tool["name"],
                                    "arguments": args,
                                },
                            )
                            current_tool = None
                    elif event.type == "message_delta":
                        output_tokens = event.usage.output_tokens
        except Exception as e:
            llm_errors_total.labels(
                model=model,
                error_type=type(e).__name__,
                provider="anthropic",
            ).inc()
            raise

        latency = int((time.monotonic() - start) * 1000)
        cost = _calc_cost(model, input_tokens, output_tokens)
        yield StreamEvent(
            event="done",
            data={
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": round(cost, 6),
                "latency_ms": latency,
                "tool_calls": tool_calls,
            },
        )


class OpenAIProvider(LLMProvider):
    DEFAULT_MODEL = "gpt-4o"

    def __init__(self) -> None:
        self.client = openai.AsyncOpenAI()

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        stream: bool = False,
        max_tokens: int = 4096,
    ) -> LLMResponse | AsyncGenerator[StreamEvent, None]:
        model = model or self.DEFAULT_MODEL
        api_messages: list[dict[str, Any]] = []
        if system:
            api_messages.append({"role": "system", "content": system})
        api_messages.extend(_translate_messages_for_openai(messages))

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = _openai_tools_schema(tools)

        if stream:
            return self._stream(kwargs, model)
        return await self._non_stream(kwargs, model)

    async def _non_stream(self, kwargs: dict[str, Any], model: str) -> LLMResponse:
        start = time.monotonic()
        resp = await self.client.chat.completions.create(**kwargs)
        latency = int((time.monotonic() - start) * 1000)

        choice = resp.choices[0]
        content = choice.message.content or ""
        tool_calls: list[dict[str, Any]] = []
        if choice.message.tool_calls:
            import json

            for tc in choice.message.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": json.loads(tc.function.arguments),
                    }
                )

        input_tokens = resp.usage.prompt_tokens if resp.usage else 0
        output_tokens = resp.usage.completion_tokens if resp.usage else 0
        cost = _calc_cost(model, input_tokens, output_tokens)
        return LLMResponse(
            content=content,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            latency_ms=latency,
            tool_calls=tool_calls,
        )

    async def _stream(
        self, kwargs: dict[str, Any], model: str
    ) -> AsyncGenerator[StreamEvent, None]:
        import json as json_mod

        start = time.monotonic()
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

        input_tokens = 0
        output_tokens = 0
        tool_calls_buf: dict[int, dict[str, Any]] = {}

        # OpenAI/Azure raise on the initial `create` for 401/429/5xx and
        # during chunk iteration for mid-stream drops — wrap both.
        provider_label = "azure" if model.startswith("azure-") else "openai"
        try:
            resp = await self.client.chat.completions.create(**kwargs)

            async for chunk in resp:
                if chunk.usage:
                    input_tokens = chunk.usage.prompt_tokens
                    output_tokens = chunk.usage.completion_tokens
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                if delta.content:
                    yield StreamEvent(event="token", data=delta.content)
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_buf:
                            tool_calls_buf[idx] = {
                                "id": tc.id or "",
                                "name": (
                                    tc.function.name
                                    if tc.function and tc.function.name
                                    else ""
                                ),
                                "arguments_str": "",
                            }
                        if tc.function and tc.function.arguments:
                            tool_calls_buf[idx][
                                "arguments_str"
                            ] += tc.function.arguments
        except Exception as e:
            llm_errors_total.labels(
                model=model,
                error_type=type(e).__name__,
                provider=provider_label,
            ).inc()
            raise

        tool_calls: list[dict[str, Any]] = []
        for buf in tool_calls_buf.values():
            try:
                args = (
                    json_mod.loads(buf["arguments_str"]) if buf["arguments_str"] else {}
                )
            except json_mod.JSONDecodeError:
                args = {}
            entry = {"id": buf["id"], "name": buf["name"], "arguments": args}
            tool_calls.append(entry)
            yield StreamEvent(
                event="tool_call",
                data={"name": entry["name"], "arguments": args},
            )

        latency = int((time.monotonic() - start) * 1000)
        cost = _calc_cost(model, input_tokens, output_tokens)
        yield StreamEvent(
            event="done",
            data={
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": round(cost, 6),
                "latency_ms": latency,
                "tool_calls": tool_calls,
            },
        )


class GoogleProvider(LLMProvider):
    DEFAULT_MODEL = "gemini-2.0-flash"

    def __init__(self) -> None:
        self.client = google_genai.Client()

    def _build_contents(
        self, messages: list[dict[str, Any]], system: str | None
    ) -> tuple[list[google_types.Content], str | None]:
        contents: list[google_types.Content] = []
        tool_id_to_name: dict[str, str] = {}

        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            raw = msg.get("content", "")

            if isinstance(raw, list):
                parts: list[google_types.Part] = []
                for block in raw:
                    if not isinstance(block, dict):
                        parts.append(google_types.Part(text=str(block)))
                        continue

                    block_type = block.get("type", "")
                    if block_type == "text":
                        parts.append(google_types.Part(text=block["text"]))
                    elif block_type == "tool_use":
                        tool_id_to_name[block["id"]] = block["name"]
                        parts.append(
                            google_types.Part(
                                function_call=google_types.FunctionCall(
                                    name=block["name"],
                                    args=block.get("input", {}),
                                )
                            )
                        )
                    elif block_type == "tool_result":
                        tool_name = tool_id_to_name.get(
                            block.get("tool_use_id", ""), "unknown"
                        )
                        result_content = block.get("content", "")
                        parts.append(
                            google_types.Part(
                                function_response=google_types.FunctionResponse(
                                    name=tool_name,
                                    response={"result": result_content},
                                )
                            )
                        )
                    else:
                        parts.append(google_types.Part(text=str(block)))

                if parts:
                    contents.append(google_types.Content(role=role, parts=parts))
            else:
                contents.append(
                    google_types.Content(
                        role=role,
                        parts=[google_types.Part(text=str(raw))],
                    )
                )
        return contents, system

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        stream: bool = False,
        max_tokens: int = 4096,
    ) -> LLMResponse | AsyncGenerator[StreamEvent, None]:
        model_name = model or self.DEFAULT_MODEL
        contents, sys_instruction = self._build_contents(messages, system)

        config = google_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if sys_instruction:
            config.system_instruction = sys_instruction
        if tools:
            config.tools = _google_tools_schema(tools)

        if stream:
            return self._stream(model_name, contents, config)
        return await self._non_stream(model_name, contents, config)

    async def _non_stream(
        self,
        model_name: str,
        contents: list[google_types.Content],
        config: google_types.GenerateContentConfig,
    ) -> LLMResponse:
        start = time.monotonic()
        resp = await asyncio.to_thread(
            self.client.models.generate_content,
            model=model_name,
            contents=contents,
            config=config,
        )
        latency = int((time.monotonic() - start) * 1000)

        content = ""
        tool_calls: list[dict[str, Any]] = []

        if resp.candidates and resp.candidates[0].content:
            for part in resp.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    from uuid import uuid4

                    tool_calls.append(
                        {
                            "id": f"call_{uuid4().hex[:8]}",
                            "name": part.function_call.name,
                            "arguments": (
                                dict(part.function_call.args)
                                if part.function_call.args
                                else {}
                            ),
                        }
                    )
                elif hasattr(part, "text") and part.text:
                    content += part.text

        input_tokens = (
            (resp.usage_metadata.prompt_token_count or 0) if resp.usage_metadata else 0
        )
        output_tokens = (
            (resp.usage_metadata.candidates_token_count or 0)
            if resp.usage_metadata
            else 0
        )
        # Gemini occasionally returns a usage_metadata object whose
        # *_token_count fields are None (e.g. when the response was
        # blocked by safety filters or truncated). Coerce to int so
        # _calc_cost doesn't get `None * float`.
        cost = _calc_cost(model_name, int(input_tokens or 0), int(output_tokens or 0))

        return LLMResponse(
            content=content,
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            latency_ms=latency,
            tool_calls=tool_calls,
        )

    async def _stream(
        self,
        model_name: str,
        contents: list[google_types.Content],
        config: google_types.GenerateContentConfig,
    ) -> AsyncGenerator[StreamEvent, None]:
        start = time.monotonic()
        input_tokens = 0
        output_tokens = 0
        tool_calls: list[dict[str, Any]] = []

        # Gemini 429 RESOURCE_EXHAUSTED + safety blocks raise from either
        # the initial generate_content_stream call or while we iterate the
        # generator. The router's try/except never sees these because we
        # return an AsyncGenerator before any provider work happens. Catch
        # both sites so abenix_llm_errors_total actually moves.
        try:
            resp = await asyncio.to_thread(
                self.client.models.generate_content_stream,
                model=model_name,
                contents=contents,
                config=config,
            )

            for chunk in resp:
                if chunk.candidates and chunk.candidates[0].content:
                    for part in chunk.candidates[0].content.parts:
                        if hasattr(part, "function_call") and part.function_call:
                            from uuid import uuid4

                            tc = {
                                "id": f"call_{uuid4().hex[:8]}",
                                "name": part.function_call.name,
                                "arguments": (
                                    dict(part.function_call.args)
                                    if part.function_call.args
                                    else {}
                                ),
                            }
                            tool_calls.append(tc)
                            yield StreamEvent(
                                event="tool_call",
                                data={
                                    "name": tc["name"],
                                    "arguments": tc["arguments"],
                                },
                            )
                        elif hasattr(part, "text") and part.text:
                            yield StreamEvent(event="token", data=part.text)
                if chunk.usage_metadata:
                    input_tokens = chunk.usage_metadata.prompt_token_count or 0
                    output_tokens = chunk.usage_metadata.candidates_token_count or 0
        except Exception as e:
            llm_errors_total.labels(
                model=model_name,
                error_type=type(e).__name__,
                provider="google",
            ).inc()
            raise

        latency = int((time.monotonic() - start) * 1000)
        cost = _calc_cost(model_name, input_tokens, output_tokens)
        yield StreamEvent(
            event="done",
            data={
                "model": model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": round(cost, 6),
                "latency_ms": latency,
                "tool_calls": tool_calls,
            },
        )


class AzureOpenAIProvider(OpenAIProvider):
    DEFAULT_MODEL = "azure-gpt-4o"

    def __init__(self) -> None:
        endpoint = _os.environ.get("AZURE_OPENAI_API_BASE", "").rstrip("/")
        if endpoint.endswith("/openai/deployments"):
            endpoint = endpoint[: -len("/openai/deployments")]
        if endpoint.endswith("/openai"):
            endpoint = endpoint[: -len("/openai")]
        api_key = _os.environ.get("AZURE_OPENAI_API_KEY", "")
        api_version = _os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-01-preview")
        self.client = openai.AsyncAzureOpenAI(
            azure_endpoint=endpoint or "https://placeholder.invalid",
            api_key=api_key or "placeholder",
            api_version=api_version,
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        stream: bool = False,
        max_tokens: int = 4096,
    ) -> LLMResponse | AsyncGenerator[StreamEvent, None]:
        model_full = model or self.DEFAULT_MODEL
        deployment = (
            model_full[len("azure-") :]
            if model_full.startswith("azure-")
            else model_full
        )
        api_messages: list[dict[str, Any]] = []
        if system:
            api_messages.append({"role": "system", "content": system})
        api_messages.extend(_translate_messages_for_openai(messages))
        kwargs: dict[str, Any] = {
            "model": deployment,
            "messages": api_messages,
            "temperature": temperature,
        }
        is_reasoning = (
            deployment.startswith("gpt-5")
            or deployment.startswith("o1")
            or deployment.startswith("o3")
        )
        if is_reasoning:
            kwargs["max_completion_tokens"] = max_tokens
            kwargs.pop("temperature", None)
        else:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = _openai_tools_schema(tools)
        if stream:
            return self._stream(kwargs, model_full)
        return await self._non_stream(kwargs, model_full)


PROVIDER_MAP: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "google": GoogleProvider,
    "azure": AzureOpenAIProvider,
}

MODEL_TO_PROVIDER: dict[str, str] = {
    "claude-sonnet-4-5-20250929": "anthropic",
    "claude-sonnet-4-20250514": "anthropic",
    "claude-haiku-3-5-20241022": "anthropic",
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "gemini-2.0-flash": "google",
    "gemini-2.5-flash": "google",
    "gemini-2.5-pro": "google",
    "gemini-1.5-pro": "google",
}


class LLMRouter:
    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def _get_provider(self, name: str) -> LLMProvider:
        if name not in self._providers:
            cls = PROVIDER_MAP.get(name)
            if not cls:
                raise ValueError(f"Unknown provider: {name}")
            self._providers[name] = cls()
        return self._providers[name]

    def route(self, model: str) -> LLMProvider:
        _load_db_pricing()
        provider_name = _DB_PROVIDER_CACHE.get(model) or MODEL_TO_PROVIDER.get(model)
        if not provider_name:
            if model.startswith("azure-"):
                provider_name = "azure"
            elif model.startswith("claude"):
                provider_name = "anthropic"
            elif model.startswith("gpt"):
                provider_name = "openai"
            elif model.startswith("gemini"):
                provider_name = "google"
            else:
                provider_name = "anthropic"
        return self._get_provider(provider_name)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        model: str = "claude-sonnet-4-5-20250929",
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse | AsyncGenerator[StreamEvent, None]:
        requested_model = model
        fallback_reason: str | None = None
        try:
            from engine.model_resolver import resolve as _resolve

            required = {"tools": True} if tools else {}
            decision = _resolve(model, required_capabilities=required)
            if decision.effective != model:
                logger.warning(
                    "model_resolver swap requested=%s effective=%s reason=%s chain=%s",
                    decision.requested,
                    decision.effective,
                    decision.reason,
                    decision.chain,
                )
                model = decision.effective
                fallback_reason = decision.reason
        except Exception as exc:
            logger.debug("model_resolver bypass: %s", exc)
        provider = self.route(model)
        _load_db_pricing()
        provider_name = _DB_PROVIDER_CACHE.get(model) or MODEL_TO_PROVIDER.get(
            model, "anthropic"
        )
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                result = await provider.complete(
                    messages=messages,
                    system=system,
                    tools=tools,
                    model=model,
                    temperature=temperature,
                    stream=stream,
                    max_tokens=max_tokens,
                )
                if not stream and isinstance(result, LLMResponse):
                    result.requested_model = requested_model
                    result.fallback_reason = fallback_reason
                    llm_tokens_total.labels(model=model, direction="input").inc(
                        result.input_tokens
                    )
                    llm_tokens_total.labels(model=model, direction="output").inc(
                        result.output_tokens
                    )
                    llm_request_duration_seconds.labels(
                        model=model, provider=provider_name
                    ).observe(result.latency_ms / 1000)
                    tracer = get_langfuse_tracer()
                    if tracer:
                        tracer.trace_llm_call(
                            model=model,
                            messages=messages,
                            response=result.content,
                            input_tokens=result.input_tokens,
                            output_tokens=result.output_tokens,
                            cost=result.cost,
                            latency_ms=result.latency_ms,
                        )
                    logger.info(
                        "llm_complete model=%s tokens_in=%d tokens_out=%d cost=%.6f latency_ms=%d",
                        result.model,
                        result.input_tokens,
                        result.output_tokens,
                        result.cost,
                        result.latency_ms,
                    )
                    # Self-heal: a real call just succeeded — clear any stale
                    # 'unavailable' row the hourly prober left behind. Runs in
                    # a thread so the DB hop never blocks the response.
                    try:
                        import asyncio as _asyncio_h

                        _asyncio_h.create_task(
                            _asyncio_h.to_thread(
                                _clear_stale_unavailable, model, result.latency_ms
                            )
                        )
                    except Exception:
                        pass
                return result
            except Exception as e:
                last_error = e
                llm_errors_total.labels(
                    model=model,
                    error_type=type(e).__name__,
                    provider=provider_name,
                ).inc()
                wait = 2**attempt
                logger.warning(
                    "llm_complete attempt=%d/%d failed: %s, retrying in %ds",
                    attempt + 1,
                    3,
                    str(e),
                    wait,
                )
                if attempt < 2:
                    await asyncio.sleep(wait)

        # Provider failover: try alternate providers before giving up.
        # The azure entry keeps Azure-only deploys functional when a single
        # Azure deployment 5xxs — degrades powerful -> least within Azure
        # before reaching for cross-provider keys.
        fallback_models = {
            "anthropic": "azure-gpt-4o",
            "openai": "azure-gpt-4o",
            "google": "azure-gpt-4o",
            "azure": "azure-gpt-4o-mini",
        }
        fallback_model = fallback_models.get(provider_name)
        if fallback_model and fallback_model != model:
            logger.warning(
                "llm_complete primary provider %s failed after 3 attempts, falling back to %s",
                provider_name,
                fallback_model,
            )
            try:
                fallback_provider = self.route(fallback_model)
                result = await fallback_provider.complete(
                    messages=messages,
                    system=system,
                    tools=tools,
                    model=fallback_model,
                    temperature=temperature,
                    stream=stream,
                    max_tokens=max_tokens,
                )
                if not stream and isinstance(result, LLMResponse):
                    result.requested_model = requested_model
                    result.fallback_reason = fallback_reason or "provider_failover"
                    _emit_llm_metrics(
                        fallback_model,
                        result.input_tokens,
                        result.output_tokens,
                        result.cost,
                        result.latency_ms,
                    )
                    logger.info(
                        "llm_complete fallback model=%s tokens_in=%d tokens_out=%d cost=%.6f latency_ms=%d primary=%s",
                        fallback_model,
                        result.input_tokens,
                        result.output_tokens,
                        result.cost,
                        result.latency_ms,
                        model,
                    )
                return result
            except Exception as fallback_error:
                logger.error(
                    "llm_complete fallback to %s also failed: %s",
                    fallback_model,
                    fallback_error,
                )

        raise last_error  # type: ignore[misc]
