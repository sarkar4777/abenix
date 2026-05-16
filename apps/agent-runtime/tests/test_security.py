from __future__ import annotations

import asyncio
import time

import pytest

from engine.mcp_client import MCPTool, MCPToolResult
from engine.mcp_security import (
    MCPSecurityContext,
    MCPSecurityPolicy,
    validate_tool_annotations,
)
from engine.sandbox import ExecutionSandbox, SandboxPolicy, run_with_timeout

# ── Sandbox tests ────────────────────────────────────────────


def test_sandbox_timeout():
    sandbox = ExecutionSandbox(SandboxPolicy(timeout_seconds=0))
    sandbox.start()
    time.sleep(0.01)
    assert sandbox.check_timeout() is False
    assert len(sandbox.violations) == 1
    assert sandbox.violations[0].violation_type == "timeout"


def test_sandbox_no_timeout_before_start():
    sandbox = ExecutionSandbox(SandboxPolicy(timeout_seconds=60))
    assert sandbox.check_timeout() is True


def test_sandbox_tool_call_limit():
    sandbox = ExecutionSandbox(SandboxPolicy(max_tool_calls=3))
    sandbox.start()
    assert sandbox.check_tool_call() is True
    assert sandbox.check_tool_call() is True
    assert sandbox.check_tool_call() is True
    assert sandbox.check_tool_call() is False
    assert len(sandbox.violations) == 1
    assert sandbox.violations[0].violation_type == "tool_limit"


def test_sandbox_output_size_limit():
    sandbox = ExecutionSandbox(SandboxPolicy(max_output_chars=100))
    sandbox.start()
    assert sandbox.check_output_size("x" * 50) is True
    assert sandbox.check_output_size("x" * 51) is False
    assert sandbox.violations[0].violation_type == "output_limit"


def test_sandbox_domain_allowlist():
    sandbox = ExecutionSandbox(
        SandboxPolicy(allowed_domains=["api.anthropic.com", "example.com"])
    )
    assert sandbox.check_domain("https://api.anthropic.com/v1/messages") is True
    assert sandbox.check_domain("https://sub.example.com/path") is True
    assert sandbox.check_domain("https://evil.com/steal") is False
    assert len(sandbox.violations) == 1
    assert sandbox.violations[0].violation_type == "network_policy"


def test_sandbox_allow_all_domains():
    sandbox = ExecutionSandbox(SandboxPolicy(allow_all_domains=True))
    assert sandbox.check_domain("https://anything.anywhere.com") is True


def test_sandbox_add_domain():
    sandbox = ExecutionSandbox(SandboxPolicy(allowed_domains=[]))
    assert sandbox.check_domain("https://new.com/api") is False
    sandbox.add_domain("new.com")
    assert sandbox.check_domain("https://new.com/api") is True


def test_sandbox_get_violations_serializable():
    sandbox = ExecutionSandbox(SandboxPolicy(max_tool_calls=0))
    sandbox.check_tool_call()
    violations = sandbox.get_violations()
    assert len(violations) == 1
    assert "type" in violations[0]
    assert "message" in violations[0]
    assert "timestamp" in violations[0]


def test_sandbox_elapsed_seconds():
    sandbox = ExecutionSandbox()
    assert sandbox.get_elapsed_seconds() == 0.0
    sandbox.start()
    time.sleep(0.05)
    assert sandbox.get_elapsed_seconds() >= 0.04


@pytest.mark.asyncio
async def test_run_with_timeout_succeeds():
    async def quick():
        return 42

    result = await run_with_timeout(quick(), timeout=5)
    assert result == 42


@pytest.mark.asyncio
async def test_run_with_timeout_raises():
    async def slow():
        await asyncio.sleep(10)

    with pytest.raises(asyncio.TimeoutError):
        await run_with_timeout(slow(), timeout=0)


# ── MCP Security tests ──────────────────────────────────────


def _make_tool(
    name: str = "test_tool",
    annotations: dict | None = None,
) -> MCPTool:
    return MCPTool(
        name=name,
        description="A test tool",
        input_schema={"type": "object", "properties": {}},
        annotations=annotations or {},
    )


def test_mcp_is_destructive():
    ctx = MCPSecurityContext()
    tool = _make_tool(annotations={"destructiveHint": True})
    assert ctx.is_destructive(tool) is True
    assert ctx.is_read_only(tool) is False


def test_mcp_is_read_only():
    ctx = MCPSecurityContext()
    tool = _make_tool(annotations={"readOnlyHint": True})
    assert ctx.is_read_only(tool) is True
    assert ctx.is_destructive(tool) is False


def test_mcp_requires_approval_for_destructive():
    ctx = MCPSecurityContext()
    destructive = _make_tool(annotations={"destructiveHint": True})
    read_only = _make_tool(annotations={"readOnlyHint": True})
    plain = _make_tool(annotations={})

    assert ctx.requires_approval(destructive) is True
    assert ctx.requires_approval(read_only) is False
    assert ctx.requires_approval(plain) is False


def test_mcp_call_limit():
    policy = MCPSecurityPolicy(max_calls_per_execution=2)
    ctx = MCPSecurityContext(policy)
    tool = _make_tool(annotations={"readOnlyHint": True})

    ctx.call_count = 2
    allowed, reason = ctx.check_call_allowed(tool)
    assert allowed is False
    assert "limit" in reason.lower()


def test_mcp_blocks_unapproved_destructive():
    ctx = MCPSecurityContext(MCPSecurityPolicy(block_unapproved_destructive=True))
    tool = _make_tool(annotations={"destructiveHint": True})

    allowed, reason = ctx.check_call_allowed(tool)
    assert allowed is False
    assert "approval" in reason.lower()


def test_mcp_approve_tool_allows_destructive():
    ctx = MCPSecurityContext(MCPSecurityPolicy(block_unapproved_destructive=True))
    tool = _make_tool(name="delete_all", annotations={"destructiveHint": True})

    ctx.approve_tool("delete_all")
    allowed, _ = ctx.check_call_allowed(tool)
    assert allowed is True


def test_mcp_audit_records_serializable():
    ctx = MCPSecurityContext()
    records = ctx.get_audit_records()
    assert isinstance(records, list)


def test_validate_annotations_warns_on_conflict():
    tool = _make_tool(annotations={"destructiveHint": True, "readOnlyHint": True})
    warnings = validate_tool_annotations(tool)
    assert any("both" in w.lower() for w in warnings)


def test_validate_annotations_warns_on_empty():
    tool = _make_tool(annotations={})
    warnings = validate_tool_annotations(tool)
    assert any("no annotations" in w.lower() for w in warnings)


def test_validate_annotations_clean():
    tool = _make_tool(annotations={"readOnlyHint": True})
    warnings = validate_tool_annotations(tool)
    assert len(warnings) == 0


@pytest.mark.asyncio
async def test_mcp_execute_tool_blocks_when_limit_exceeded():
    policy = MCPSecurityPolicy(max_calls_per_execution=0)
    ctx = MCPSecurityContext(policy)
    tool = _make_tool(annotations={"readOnlyHint": True})

    class FakeClient:
        async def call_tool(self, name, arguments):
            return MCPToolResult(content="ok", is_error=False)

    result = await ctx.execute_tool(FakeClient(), tool, {})
    assert result.is_error is True
    assert "limit" in result.content.lower()
    assert len(ctx.audit_log) == 1


@pytest.mark.asyncio
async def test_mcp_execute_tool_enforces_timeout():
    policy = MCPSecurityPolicy(call_timeout=0.01)
    ctx = MCPSecurityContext(policy)
    tool = _make_tool(annotations={"readOnlyHint": True})

    class SlowClient:
        async def call_tool(self, name, arguments):
            await asyncio.sleep(10)
            return MCPToolResult(content="ok", is_error=False)

    result = await ctx.execute_tool(SlowClient(), tool, {})
    assert result.is_error is True
    assert "timed out" in result.content.lower()


@pytest.mark.asyncio
async def test_mcp_execute_tool_success():
    ctx = MCPSecurityContext()
    tool = _make_tool(annotations={"readOnlyHint": True})

    class OkClient:
        async def call_tool(self, name, arguments):
            return MCPToolResult(content="result data", is_error=False)

    result = await ctx.execute_tool(OkClient(), tool, {"q": "test"})
    assert result.is_error is False
    assert result.content == "result data"
    assert ctx.call_count == 1
    assert len(ctx.audit_log) == 1
    assert ctx.audit_log[0].tool_name == "test_tool"
