"""Tests for engine.tools.base — the public ToolRegistry contract.

Every agent execution starts by building a ToolRegistry and consulting
it from the executor. Registry semantics are simple but they're the
load-bearing API contract between the LLM (which sees `to_dict()`
manifests) and the runtime (which calls `.execute(args)`).
"""

from __future__ import annotations

from typing import Any

import pytest

from engine.tools.base import BaseTool, ToolRegistry, ToolResult, _DefaultedTool

# ── ToolResult ──────────────────────────────────────────────────────


def test_tool_result_default_is_not_error():
    r = ToolResult(content="hi")
    assert r.is_error is False
    assert r.metadata == {}


def test_tool_result_carries_metadata():
    r = ToolResult(content="hi", metadata={"cost": 0.01, "model": "claude"})
    assert r.metadata["cost"] == 0.01


# ── Trivial tool fixture ────────────────────────────────────────────


class _PingTool(BaseTool):
    name = "ping"
    description = "respond with pong"
    input_schema = {
        "type": "object",
        "properties": {"who": {"type": "string"}},
        "required": ["who"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=f"pong:{arguments.get('who', '')}")


# ── ToolRegistry ────────────────────────────────────────────────────


def test_register_then_get():
    reg = ToolRegistry()
    t = _PingTool()
    reg.register(t)
    assert reg.get("ping") is t


def test_get_missing_returns_none():
    reg = ToolRegistry()
    assert reg.get("nope") is None


def test_register_overwrites_on_same_name():
    """register() is idempotent on tool name — last write wins. Lets
    apply_tool_config wrap a tool with _DefaultedTool by re-registering."""
    reg = ToolRegistry()
    a = _PingTool()
    b = _PingTool()
    reg.register(a)
    reg.register(b)
    assert reg.get("ping") is b


def test_list_all_serializes_each_tool():
    reg = ToolRegistry()
    reg.register(_PingTool())
    out = reg.list_all()
    assert out == [
        {
            "name": "ping",
            "description": "respond with pong",
            "input_schema": {
                "type": "object",
                "properties": {"who": {"type": "string"}},
                "required": ["who"],
            },
        }
    ]


def test_names_returns_registered_tool_ids():
    reg = ToolRegistry()
    reg.register(_PingTool())
    assert reg.names() == ["ping"]


# ── _DefaultedTool wrapping ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_defaulted_tool_injects_defaults_at_call_time():
    """When a tool has parameter_defaults configured, those values must
    be merged into every call so the LLM doesn't have to supply them."""
    inner = _PingTool()
    wrapped = _DefaultedTool(inner, defaults={"who": "operator"})
    result = await wrapped.execute({})
    assert result.content == "pong:operator"


@pytest.mark.asyncio
async def test_defaulted_tool_lets_caller_override_default():
    """Caller-supplied args must win over defaults — a user explicitly
    setting `who='alice'` should not be silently overwritten."""
    wrapped = _DefaultedTool(_PingTool(), defaults={"who": "operator"})
    result = await wrapped.execute({"who": "alice"})
    assert result.content == "pong:alice"


def test_defaulted_tool_strips_hidden_keys_from_schema():
    """Keys with a default must be removed from the LLM-facing schema
    so the model doesn't try to specify them. They're also dropped
    from `required`."""
    wrapped = _DefaultedTool(_PingTool(), defaults={"who": "fixed"})
    assert "who" not in wrapped.input_schema["properties"]
    assert "who" not in wrapped.input_schema["required"]


def test_defaulted_tool_preserves_inner_name_and_description():
    """Wrapping must be transparent to the registry — same name lookup,
    same human-facing description (with a small annotation)."""
    wrapped = _DefaultedTool(_PingTool(), defaults={"who": "fixed"})
    assert wrapped.name == "ping"
    assert wrapped.description.startswith("respond with pong")
    assert "pre-configured" in wrapped.description


def test_apply_tool_config_wraps_in_place():
    """ToolRegistry.apply_tool_config must replace a registered tool
    with its _DefaultedTool wrapper while keeping the same key."""
    reg = ToolRegistry()
    reg.register(_PingTool())
    reg.apply_tool_config({"ping": {"parameter_defaults": {"who": "fixed"}}})
    wrapped = reg.get("ping")
    assert isinstance(wrapped, _DefaultedTool)
    assert wrapped.name == "ping"


def test_apply_tool_config_no_op_when_no_defaults():
    """Passing an empty config must not wrap untouched tools — that
    would needlessly slow every call site through the indirection."""
    reg = ToolRegistry()
    original = _PingTool()
    reg.register(original)
    reg.apply_tool_config({"ping": {}})
    assert reg.get("ping") is original
