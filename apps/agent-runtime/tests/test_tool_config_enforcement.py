"""tool_config is enforced at dispatch, not just described in the prompt."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from engine.mcp_client import MCPTool, MCPToolResult
from engine.tool_config_prompt import append_mcp_warnings, build_tool_config_prompt
from engine.tool_resolver import MCPToolWrapper, resolve_tools
from engine.tools.base import BaseTool, ToolRegistry, ToolResult, _DefaultedTool


class _EchoTool(BaseTool):
    name = "echo"
    description = "echo the args"
    input_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "asset_id": {"type": "string"},
            "allow_network": {"type": "boolean"},
        },
        "required": ["text", "asset_id"],
    }

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(dict(arguments))
        return ToolResult(content=str(sorted(arguments.items())))


class _Gate(BaseTool):
    """Stand-in for human_approval that records what it was asked and answers as told."""

    name = "human_approval"
    description = "gate"
    input_schema = {"type": "object", "properties": {}}

    def __init__(self, approve: bool) -> None:
        self._approve = approve
        self.requests: list[dict[str, Any]] = []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.requests.append(dict(arguments))
        if self._approve:
            return ToolResult(
                content="Approved by qa.", metadata={"decision": "approved"}
            )
        return ToolResult(
            content="Rejected by qa. Reason: no.",
            is_error=True,
            metadata={"decision": "rejected"},
        )


# max_calls


@pytest.mark.asyncio
async def test_max_calls_stops_the_n_plus_one_call():
    inner = _EchoTool()
    wrapped = _DefaultedTool(inner, max_calls=2)
    r1 = await wrapped.execute({"text": "a", "asset_id": "x"})
    r2 = await wrapped.execute({"text": "b", "asset_id": "x"})
    r3 = await wrapped.execute({"text": "c", "asset_id": "x"})
    assert not r1.is_error and not r2.is_error
    assert r3.is_error
    assert r3.content == "max_calls (2) reached for echo"
    assert len(inner.calls) == 2


@pytest.mark.asyncio
async def test_max_calls_zero_means_unlimited():
    inner = _EchoTool()
    wrapped = _DefaultedTool(inner, max_calls=0)
    for i in range(5):
        assert not (await wrapped.execute({"text": str(i), "asset_id": "x"})).is_error
    assert len(inner.calls) == 5


def test_apply_tool_config_wraps_for_max_calls_alone():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    reg.apply_tool_config({"echo": {"max_calls": 3}})
    assert isinstance(reg.get("echo"), _DefaultedTool)


# locked defaults


@pytest.mark.asyncio
async def test_locked_defaults_win_over_model_arguments():
    inner = _EchoTool()
    wrapped = _DefaultedTool(
        inner, defaults={"asset_id": "pinned", "allow_network": False}
    )
    await wrapped.execute({"text": "hi", "asset_id": "evil", "allow_network": True})
    assert inner.calls[0]["asset_id"] == "pinned"
    assert inner.calls[0]["allow_network"] is False
    assert inner.calls[0]["text"] == "hi"


@pytest.mark.asyncio
async def test_unlocked_defaults_can_be_overridden():
    inner = _EchoTool()
    wrapped = _DefaultedTool(
        inner, defaults={"asset_id": "pinned"}, locked_defaults=False
    )
    await wrapped.execute({"text": "hi", "asset_id": "mine"})
    assert inner.calls[0]["asset_id"] == "mine"


def test_apply_tool_config_reads_locked_defaults_flag():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    reg.apply_tool_config(
        {"echo": {"parameter_defaults": {"asset_id": "p"}, "locked_defaults": False}}
    )
    assert reg.get("echo")._locked is False


# require_approval


@pytest.mark.asyncio
async def test_require_approval_without_human_approval_errors():
    inner = _EchoTool()
    wrapped = _DefaultedTool(inner, require_approval=True)
    r = await wrapped.execute({"text": "hi", "asset_id": "x"})
    assert r.is_error
    assert (
        r.content
        == "require_approval set but human_approval is not in the agent's tools"
    )
    assert inner.calls == []


@pytest.mark.asyncio
async def test_require_approval_routes_through_gate_and_proceeds_on_approve():
    inner = _EchoTool()
    gate = _Gate(approve=True)
    wrapped = _DefaultedTool(inner, require_approval=True, approval_tool=gate)
    r = await wrapped.execute({"text": "hi", "asset_id": "x"})
    assert not r.is_error
    assert len(inner.calls) == 1
    assert gate.requests[0]["action"] == "call echo"
    assert '"text": "hi"' in gate.requests[0]["details"]


@pytest.mark.asyncio
async def test_require_approval_denied_blocks_the_call():
    inner = _EchoTool()
    gate = _Gate(approve=False)
    wrapped = _DefaultedTool(inner, require_approval=True, approval_tool=gate)
    r = await wrapped.execute({"text": "hi", "asset_id": "x"})
    assert r.is_error
    assert r.content.startswith("approval denied:")
    assert inner.calls == []


def test_apply_tool_config_passes_registered_gate_and_never_gates_itself():
    reg = ToolRegistry()
    reg.register(_EchoTool())
    gate = _Gate(approve=True)
    reg.register(gate)
    reg.apply_tool_config(
        {
            "echo": {"require_approval": True},
            "human_approval": {"require_approval": True},
        }
    )
    assert reg.get("echo")._approval_tool is gate
    assert reg.get("human_approval") is gate


# MCP per-tool settings


def _mcp_tool(name: str, annotations: dict | None = None) -> MCPTool:
    return MCPTool(
        name=name,
        description="d",
        input_schema={"type": "object", "properties": {}},
        annotations=annotations or {},
    )


@pytest.mark.asyncio
async def test_mcp_wrapper_enforces_max_calls_per_execution():
    client = AsyncMock()
    client.call_tool = AsyncMock(return_value=MCPToolResult(content="ok"))
    w = MCPToolWrapper(client, _mcp_tool("t"), None, max_calls=1)
    assert not (await w.execute({})).is_error
    r = await w.execute({})
    assert r.is_error and "max_calls_per_execution (1) reached" in r.content
    assert client.call_tool.await_count == 1


@pytest.mark.asyncio
async def test_mcp_wrapper_approval_required_without_gate_errors():
    client = AsyncMock()
    client.call_tool = AsyncMock(return_value=MCPToolResult(content="ok"))
    w = MCPToolWrapper(client, _mcp_tool("t"), None, approval_required=True)
    r = await w.execute({})
    assert r.is_error and "human_approval" in r.content
    client.call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcp_destructive_tool_unblocked_by_gate_approval():
    from engine.mcp_security import MCPSecurityContext

    client = AsyncMock()
    client.call_tool = AsyncMock(return_value=MCPToolResult(content="deleted"))
    ctx = MCPSecurityContext()
    tool = _mcp_tool("rm", {"destructiveHint": True})
    gate = _Gate(approve=True)
    w = MCPToolWrapper(client, tool, ctx, approval_tool=gate)
    r = await w.execute({"path": "/x"})
    assert not r.is_error and r.content == "deleted"
    assert "rm" in ctx._approved_tools
    assert gate.requests[0]["action"] == "call rm"


@pytest.mark.asyncio
async def test_resolve_tools_applies_per_tool_settings_and_tool_config():
    builtin = ToolRegistry()
    gate = _Gate(approve=True)
    builtin.register(gate)
    remote = [_mcp_tool("search"), _mcp_tool("write")]
    with patch("engine.agent_executor.build_tool_registry", return_value=builtin):
        with patch("engine.tool_resolver.MCPClient") as MockClient:
            inst = AsyncMock()
            inst.initialize = AsyncMock()
            inst.list_tools = AsyncMock(return_value=remote)
            inst.close = AsyncMock()
            MockClient.return_value = inst
            registry, _, _ = await resolve_tools(
                [],
                [
                    {
                        "server_name": "Files",
                        "server_url": "http://files:9000/mcp",
                        "tools": ["search", "write", "gone"],
                        "tool_settings": {
                            "write": {
                                "approval_required": True,
                                "max_calls_per_execution": 3,
                                "tool_config": {"parameter_defaults": {"mode": "safe"}},
                            }
                        },
                    }
                ],
            )
    write = registry.get("write")
    assert isinstance(write, _DefaultedTool)
    assert write._inner._approval_required is True
    assert write._inner._max_calls == 3
    assert write._inner._approval_tool is gate
    assert any("gone" in w for w in registry.mcp_warnings)


# shared prompt text


def test_prompt_helper_covers_every_setting():
    out = build_tool_config_prompt(
        "base",
        {
            "echo": {
                "usage_instructions": "Use sparingly.",
                "max_calls": 2,
                "require_approval": True,
                "parameter_defaults": {"asset_id": "p"},
            }
        },
    )
    assert out.startswith("base")
    assert "## Tool Usage Guidelines" in out
    assert "Use sparingly." in out
    assert "Maximum 2 calls per execution." in out
    assert "human approval" in out
    assert "asset_id=p" in out


def test_prompt_helper_noop_without_config():
    assert build_tool_config_prompt("base", None) == "base"
    assert build_tool_config_prompt("base", {"echo": {}}) == "base"


def test_mcp_warning_note_is_appended_once():
    out = append_mcp_warnings("base", ["MCP server X unavailable"])
    assert out.endswith("- MCP server X unavailable")
    assert append_mcp_warnings("base", []) == "base"
