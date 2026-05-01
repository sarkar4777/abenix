"""Comprehensive tests for new MCP features."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.mcp_client import (
    MCPClient,
    MCPError,
    MCPPrompt,
    MCPPromptMessage,
    MCPResource,
    MCPResourceContent,
    MCPTool,
    MCPToolResult,
)
from engine.mcp_security import (
    MCPSecurityContext,
    MCPSecurityPolicy,
    ToolCallRecord,
    validate_tool_annotations,
)
from engine.tool_resolver import MCPToolWrapper, resolve_tools
from engine.tools.base import BaseTool, ToolRegistry, ToolResult

# Ensure the API router module is importable for token encryption tests.
_api_root = Path(__file__).resolve().parents[2] / "api"
if str(_api_root) not in sys.path:
    sys.path.insert(0, str(_api_root))


# Helpers


def _mock_http_response(result_data: dict) -> MagicMock:
    """Build a fake httpx.Response that MCPClient._send will accept."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"jsonrpc": "2.0", "id": "1", "result": result_data}
    resp.headers = {"Mcp-Session-Id": "sess-abc"}
    resp.raise_for_status = MagicMock()
    return resp


def _make_tool(
    name: str = "test_tool",
    description: str = "A test tool",
    annotations: dict | None = None,
) -> MCPTool:
    return MCPTool(
        name=name,
        description=description,
        input_schema={"type": "object", "properties": {}},
        annotations=annotations or {},
    )


def _make_client_with_mock(response_data: dict) -> MCPClient:
    """Return an MCPClient whose HTTP layer returns the given result."""
    client = MCPClient(server_url="http://localhost:9000/mcp")
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=_mock_http_response(response_data))
    client._client = mock_http
    return client


# 1. MCP Client Dataclasses


class TestMCPDataclasses:
    def test_mcp_prompt_defaults(self):
        prompt = MCPPrompt(name="greet", description="A greeting prompt")
        assert prompt.name == "greet"
        assert prompt.description == "A greeting prompt"
        assert prompt.arguments == []

    def test_mcp_prompt_with_arguments(self):
        args = [{"name": "language", "required": True}]
        prompt = MCPPrompt(name="translate", description="Translate text", arguments=args)
        assert len(prompt.arguments) == 1
        assert prompt.arguments[0]["name"] == "language"

    def test_mcp_prompt_message(self):
        msg = MCPPromptMessage(role="user", content="Hello, world!")
        assert msg.role == "user"
        assert msg.content == "Hello, world!"

    def test_mcp_resource_content_text(self):
        rc = MCPResourceContent(uri="file:///readme.md", mime_type="text/markdown", text="# Hi")
        assert rc.uri == "file:///readme.md"
        assert rc.mime_type == "text/markdown"
        assert rc.text == "# Hi"
        assert rc.blob is None

    def test_mcp_resource_content_blob(self):
        rc = MCPResourceContent(uri="file:///img.png", blob="iVBORw0KGgo=")
        assert rc.blob == "iVBORw0KGgo="
        assert rc.text is None
        assert rc.mime_type is None

    def test_mcp_resource_dataclass(self):
        r = MCPResource(uri="file:///data.csv", name="data", description="Data file", mime_type="text/csv")
        assert r.uri == "file:///data.csv"
        assert r.name == "data"
        assert r.mime_type == "text/csv"

    def test_mcp_resource_default_mime_type(self):
        r = MCPResource(uri="file:///unknown", name="unk", description="")
        assert r.mime_type is None


# 2. MCP Client – read_resource, list_prompts, get_prompt


class TestMCPClientNewMethods:
    @pytest.mark.asyncio
    async def test_read_resource_returns_text(self):
        client = _make_client_with_mock({
            "contents": [
                {
                    "uri": "file:///readme.md",
                    "mimeType": "text/markdown",
                    "text": "# Project README",
                }
            ]
        })

        content = await client.read_resource("file:///readme.md")
        assert isinstance(content, MCPResourceContent)
        assert content.uri == "file:///readme.md"
        assert content.mime_type == "text/markdown"
        assert content.text == "# Project README"
        assert content.blob is None

    @pytest.mark.asyncio
    async def test_read_resource_returns_blob(self):
        client = _make_client_with_mock({
            "contents": [
                {
                    "uri": "file:///image.png",
                    "mimeType": "image/png",
                    "blob": "aW1hZ2VkYXRh",
                }
            ]
        })

        content = await client.read_resource("file:///image.png")
        assert content.blob == "aW1hZ2VkYXRh"
        assert content.text is None

    @pytest.mark.asyncio
    async def test_read_resource_empty_contents(self):
        client = _make_client_with_mock({"contents": []})

        content = await client.read_resource("file:///missing")
        assert content.uri == "file:///missing"
        assert content.text == ""
        assert content.blob is None

    @pytest.mark.asyncio
    async def test_list_prompts_parses_response(self):
        client = _make_client_with_mock({
            "prompts": [
                {
                    "name": "summarize",
                    "description": "Summarize a document",
                    "arguments": [{"name": "length", "required": False}],
                },
                {
                    "name": "translate",
                    "description": "Translate text",
                },
            ]
        })

        prompts = await client.list_prompts()
        assert len(prompts) == 2
        assert prompts[0].name == "summarize"
        assert prompts[0].description == "Summarize a document"
        assert len(prompts[0].arguments) == 1
        assert prompts[1].name == "translate"
        assert prompts[1].arguments == []

    @pytest.mark.asyncio
    async def test_list_prompts_empty(self):
        client = _make_client_with_mock({"prompts": []})
        prompts = await client.list_prompts()
        assert prompts == []

    @pytest.mark.asyncio
    async def test_get_prompt_returns_messages(self):
        client = _make_client_with_mock({
            "messages": [
                {"role": "user", "content": {"type": "text", "text": "Summarize this"}},
                {"role": "assistant", "content": {"type": "text", "text": "Here is a summary..."}},
            ]
        })

        messages = await client.get_prompt("summarize", {"length": "short"})
        assert len(messages) == 2
        assert isinstance(messages[0], MCPPromptMessage)
        assert messages[0].role == "user"
        assert messages[0].content == "Summarize this"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Here is a summary..."

    @pytest.mark.asyncio
    async def test_get_prompt_no_arguments(self):
        client = _make_client_with_mock({
            "messages": [
                {"role": "user", "content": {"type": "text", "text": "Hello"}},
            ]
        })

        messages = await client.get_prompt("greet")
        assert len(messages) == 1
        assert messages[0].content == "Hello"

    @pytest.mark.asyncio
    async def test_get_prompt_empty_messages(self):
        client = _make_client_with_mock({"messages": []})
        messages = await client.get_prompt("empty_prompt")
        assert messages == []

    @pytest.mark.asyncio
    async def test_get_prompt_string_content_fallback(self):
        """When content is a bare string (not a dict), should still work."""
        client = _make_client_with_mock({
            "messages": [
                {"role": "user", "content": "plain text content"},
            ]
        })

        messages = await client.get_prompt("simple")
        assert len(messages) == 1
        assert messages[0].content == "plain text content"


# 3. Tool Resolver – MCPToolWrapper


class TestMCPToolWrapper:
    @pytest.mark.asyncio
    async def test_execute_without_security_context(self):
        mcp_tool = _make_tool(name="read_file", annotations={"readOnlyHint": True})
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(
            return_value=MCPToolResult(content="file contents here", is_error=False)
        )

        wrapper = MCPToolWrapper(client=mock_client, mcp_tool=mcp_tool, security_ctx=None)
        result = await wrapper.execute({"path": "/tmp/test.txt"})

        assert isinstance(result, ToolResult)
        assert result.content == "file contents here"
        assert result.is_error is False
        mock_client.call_tool.assert_awaited_once_with("read_file", {"path": "/tmp/test.txt"})

    @pytest.mark.asyncio
    async def test_execute_with_security_context(self):
        mcp_tool = _make_tool(name="delete_file", annotations={"destructiveHint": True})
        mock_client = AsyncMock()

        security_ctx = MCPSecurityContext(MCPSecurityPolicy(block_unapproved_destructive=False))
        mock_client.call_tool = AsyncMock(
            return_value=MCPToolResult(content="deleted", is_error=False)
        )

        wrapper = MCPToolWrapper(client=mock_client, mcp_tool=mcp_tool, security_ctx=security_ctx)
        result = await wrapper.execute({"path": "/tmp/old.txt"})

        assert isinstance(result, ToolResult)
        assert result.content == "deleted"
        assert security_ctx.call_count == 1

    @pytest.mark.asyncio
    async def test_execute_blocked_by_security(self):
        mcp_tool = _make_tool(name="drop_table", annotations={"destructiveHint": True})
        mock_client = AsyncMock()

        security_ctx = MCPSecurityContext(MCPSecurityPolicy(block_unapproved_destructive=True))

        wrapper = MCPToolWrapper(client=mock_client, mcp_tool=mcp_tool, security_ctx=security_ctx)
        result = await wrapper.execute({"table": "users"})

        assert result.is_error is True
        assert "approval" in result.content.lower()
        mock_client.call_tool.assert_not_awaited()

    def test_to_dict(self):
        mcp_tool = _make_tool(
            name="search", annotations={"readOnlyHint": True, "openWorldHint": True}
        )
        wrapper = MCPToolWrapper(
            client=AsyncMock(), mcp_tool=mcp_tool, security_ctx=None
        )
        d = wrapper.to_dict()
        assert d["name"] == "search"
        assert d["description"] == "A test tool"
        assert d["annotations"]["readOnlyHint"] is True
        assert "input_schema" in d

    def test_wrapper_attributes_mirror_mcp_tool(self):
        mcp_tool = _make_tool(name="calc", description="Calculator tool")
        wrapper = MCPToolWrapper(
            client=AsyncMock(), mcp_tool=mcp_tool, security_ctx=None
        )
        assert wrapper.name == "calc"
        assert wrapper.description == "Calculator tool"
        assert wrapper.input_schema == mcp_tool.input_schema
        assert wrapper.annotations == mcp_tool.annotations


# 4. Tool Resolver – resolve_tools


class TestResolveTools:
    @pytest.mark.asyncio
    async def test_resolve_builtin_only(self):
        with patch("engine.agent_executor.build_tool_registry") as mock_build:
            registry = ToolRegistry()
            mock_build.return_value = registry

            result_registry, clients, sec_ctx = await resolve_tools(
                builtin_tool_names=["calculator"],
                mcp_connections=[],
            )

            assert result_registry is registry
            assert clients == []
            assert sec_ctx is None
            mock_build.assert_called_once_with(["calculator"])

    @pytest.mark.asyncio
    async def test_resolve_with_mcp_connection(self):
        builtin_registry = ToolRegistry()

        remote_tools = [
            _make_tool(name="github_search", annotations={"readOnlyHint": True}),
            _make_tool(name="github_create_pr", annotations={"destructiveHint": False}),
        ]

        with patch("engine.agent_executor.build_tool_registry", return_value=builtin_registry):
            with patch("engine.tool_resolver.MCPClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.initialize = AsyncMock()
                mock_instance.list_tools = AsyncMock(return_value=remote_tools)
                mock_instance.close = AsyncMock()
                MockClient.return_value = mock_instance

                registry, clients, sec_ctx = await resolve_tools(
                    builtin_tool_names=[],
                    mcp_connections=[
                        {
                            "server_url": "http://github-mcp:9000/mcp",
                            "auth_type": "api_key",
                            "auth_config": {"api_key": "test-key"},
                        }
                    ],
                )

                assert len(clients) == 1
                assert sec_ctx is not None
                assert "github_search" in registry.names()
                assert "github_create_pr" in registry.names()

    @pytest.mark.asyncio
    async def test_resolve_failed_mcp_connection_skipped(self):
        builtin_registry = ToolRegistry()

        with patch("engine.agent_executor.build_tool_registry", return_value=builtin_registry):
            with patch("engine.tool_resolver.MCPClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.initialize = AsyncMock(side_effect=Exception("Connection refused"))
                mock_instance.close = AsyncMock()
                MockClient.return_value = mock_instance

                registry, clients, sec_ctx = await resolve_tools(
                    builtin_tool_names=[],
                    mcp_connections=[
                        {"server_url": "http://dead-server:9000/mcp"},
                    ],
                )

                assert clients == []
                assert registry.names() == []
                mock_instance.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_tool_name_conflict_skips_mcp(self):
        """When a built-in tool has the same name as an MCP tool, the MCP tool is skipped."""
        builtin_registry = ToolRegistry()
        # Simulate a built-in tool already registered with name "calculator"
        fake_builtin = MagicMock(spec=BaseTool)
        fake_builtin.name = "calculator"
        builtin_registry.register(fake_builtin)

        remote_tools = [_make_tool(name="calculator")]

        with patch("engine.agent_executor.build_tool_registry", return_value=builtin_registry):
            with patch("engine.tool_resolver.MCPClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.initialize = AsyncMock()
                mock_instance.list_tools = AsyncMock(return_value=remote_tools)
                mock_instance.close = AsyncMock()
                MockClient.return_value = mock_instance

                registry, clients, _ = await resolve_tools(
                    builtin_tool_names=[],
                    mcp_connections=[
                        {"server_url": "http://mcp:9000/mcp"},
                    ],
                )

                # The original built-in should remain; MCP duplicate should be skipped
                assert registry.get("calculator") is fake_builtin

    @pytest.mark.asyncio
    async def test_resolve_filters_allowed_tools(self):
        """Only tools listed in 'tools' allowlist are registered from a server."""
        builtin_registry = ToolRegistry()

        remote_tools = [
            _make_tool(name="tool_a"),
            _make_tool(name="tool_b"),
            _make_tool(name="tool_c"),
        ]

        with patch("engine.agent_executor.build_tool_registry", return_value=builtin_registry):
            with patch("engine.tool_resolver.MCPClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.initialize = AsyncMock()
                mock_instance.list_tools = AsyncMock(return_value=remote_tools)
                mock_instance.close = AsyncMock()
                MockClient.return_value = mock_instance

                registry, clients, _ = await resolve_tools(
                    builtin_tool_names=[],
                    mcp_connections=[
                        {
                            "server_url": "http://mcp:9000/mcp",
                            "tools": ["tool_a", "tool_c"],
                        }
                    ],
                )

                names = registry.names()
                assert "tool_a" in names
                assert "tool_c" in names
                assert "tool_b" not in names

    @pytest.mark.asyncio
    async def test_resolve_creates_security_context_when_connections_present(self):
        builtin_registry = ToolRegistry()
        policy = MCPSecurityPolicy(max_calls_per_execution=5)

        with patch("engine.agent_executor.build_tool_registry", return_value=builtin_registry):
            with patch("engine.tool_resolver.MCPClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.initialize = AsyncMock()
                mock_instance.list_tools = AsyncMock(return_value=[_make_tool(name="x")])
                mock_instance.close = AsyncMock()
                MockClient.return_value = mock_instance

                _, _, sec_ctx = await resolve_tools(
                    builtin_tool_names=[],
                    mcp_connections=[{"server_url": "http://mcp:9000/mcp"}],
                    security_policy=policy,
                )

                assert sec_ctx is not None
                assert sec_ctx.policy.max_calls_per_execution == 5


# 5. MCP Security – extended coverage


class TestMCPSecurityExtended:
    def test_call_count_increments_on_success(self):
        ctx = MCPSecurityContext()
        assert ctx.call_count == 0

    def test_default_policy_values(self):
        policy = MCPSecurityPolicy()
        assert policy.max_calls_per_execution == 10
        assert policy.call_timeout == 30.0
        assert policy.auto_approve_read_only is True
        assert policy.block_unapproved_destructive is True
        assert policy.allowed_domains == []

    def test_custom_policy(self):
        policy = MCPSecurityPolicy(
            max_calls_per_execution=3,
            call_timeout=5.0,
            auto_approve_read_only=False,
            block_unapproved_destructive=False,
        )
        assert policy.max_calls_per_execution == 3
        assert policy.call_timeout == 5.0

    def test_no_annotation_tool_is_not_destructive(self):
        ctx = MCPSecurityContext()
        tool = _make_tool(annotations={})
        assert ctx.is_destructive(tool) is False
        assert ctx.is_read_only(tool) is False

    def test_requires_approval_with_auto_approve_disabled(self):
        """When auto_approve_read_only is False, read-only tools are not auto-approved but still
        don't require explicit approval because they are not destructive."""
        policy = MCPSecurityPolicy(auto_approve_read_only=False)
        ctx = MCPSecurityContext(policy)
        ro_tool = _make_tool(annotations={"readOnlyHint": True})
        # Not destructive -> requires_approval returns False
        assert ctx.requires_approval(ro_tool) is False

    def test_check_call_allowed_at_exactly_limit(self):
        policy = MCPSecurityPolicy(max_calls_per_execution=5)
        ctx = MCPSecurityContext(policy)
        ctx.call_count = 5
        allowed, reason = ctx.check_call_allowed(_make_tool())
        assert allowed is False
        assert "5" in reason

    def test_check_call_allowed_under_limit(self):
        policy = MCPSecurityPolicy(max_calls_per_execution=5)
        ctx = MCPSecurityContext(policy)
        ctx.call_count = 4
        tool = _make_tool(annotations={"readOnlyHint": True})
        allowed, reason = ctx.check_call_allowed(tool)
        assert allowed is True
        assert reason == ""

    @pytest.mark.asyncio
    async def test_execute_tool_records_audit_on_success(self):
        ctx = MCPSecurityContext()
        tool = _make_tool(name="fetch_data", annotations={"readOnlyHint": True})

        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(
            return_value=MCPToolResult(content="data here", is_error=False)
        )

        result = await ctx.execute_tool(mock_client, tool, {"url": "http://example.com"})
        assert result.content == "data here"
        assert len(ctx.audit_log) == 1
        record = ctx.audit_log[0]
        assert record.tool_name == "fetch_data"
        assert record.is_error is False
        assert record.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_tool_records_audit_on_block(self):
        policy = MCPSecurityPolicy(max_calls_per_execution=0)
        ctx = MCPSecurityContext(policy)
        tool = _make_tool(annotations={"readOnlyHint": True})

        mock_client = AsyncMock()
        result = await ctx.execute_tool(mock_client, tool, {})
        assert result.is_error is True
        assert len(ctx.audit_log) == 1
        assert ctx.audit_log[0].duration_ms == 0

    @pytest.mark.asyncio
    async def test_execute_tool_timeout_increments_call_count(self):
        policy = MCPSecurityPolicy(call_timeout=0.01)
        ctx = MCPSecurityContext(policy)
        tool = _make_tool(annotations={"readOnlyHint": True})

        async def _slow_call(*a, **kw):
            await asyncio.sleep(10)

        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(side_effect=_slow_call)

        result = await ctx.execute_tool(mock_client, tool, {})
        assert result.is_error is True
        assert ctx.call_count == 1
        assert len(ctx.audit_log) == 1
        assert "timed out" in ctx.audit_log[0].result.lower()

    @pytest.mark.asyncio
    async def test_execute_tool_exception_increments_call_count(self):
        ctx = MCPSecurityContext()
        tool = _make_tool(annotations={"readOnlyHint": True})

        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(side_effect=RuntimeError("network error"))

        with pytest.raises(RuntimeError, match="network error"):
            await ctx.execute_tool(mock_client, tool, {})

        assert ctx.call_count == 1
        assert len(ctx.audit_log) == 1
        assert ctx.audit_log[0].is_error is True

    def test_get_audit_records_format(self):
        ctx = MCPSecurityContext()
        ctx.audit_log.append(ToolCallRecord(
            tool_name="test",
            arguments={"a": 1},
            result="ok" * 200,  # long result
            is_error=False,
            duration_ms=42,
            required_approval=False,
            annotations={"readOnlyHint": True},
        ))
        records = ctx.get_audit_records()
        assert len(records) == 1
        rec = records[0]
        assert rec["tool_name"] == "test"
        assert rec["duration_ms"] == 42
        assert rec["read_only"] is True
        assert rec["destructive"] is False
        # result_preview is truncated to 200 chars
        assert len(rec["result_preview"]) <= 200

    def test_approve_tool_idempotent(self):
        ctx = MCPSecurityContext()
        ctx.approve_tool("my_tool")
        ctx.approve_tool("my_tool")
        assert "my_tool" in ctx._approved_tools


# 6. validate_tool_annotations


class TestValidateToolAnnotations:
    def test_no_warnings_for_read_only(self):
        tool = _make_tool(annotations={"readOnlyHint": True})
        assert validate_tool_annotations(tool) == []

    def test_no_warnings_for_destructive_only(self):
        tool = _make_tool(annotations={"destructiveHint": True})
        assert validate_tool_annotations(tool) == []

    def test_warning_for_conflicting_hints(self):
        tool = _make_tool(annotations={"destructiveHint": True, "readOnlyHint": True})
        warnings = validate_tool_annotations(tool)
        assert len(warnings) >= 1
        assert any("both" in w.lower() for w in warnings)

    def test_warning_for_empty_annotations(self):
        tool = _make_tool(annotations={})
        warnings = validate_tool_annotations(tool)
        assert len(warnings) >= 1
        assert any("no annotations" in w.lower() for w in warnings)

    def test_no_warnings_for_custom_annotation(self):
        tool = _make_tool(annotations={"openWorldHint": True})
        warnings = validate_tool_annotations(tool)
        assert warnings == []


# 7. Token Encryption Roundtrip


class TestTokenEncryption:
    def _get_encrypt_decrypt(self):
        from app.routers.mcp import _decrypt_token, _encrypt_token
        return _encrypt_token, _decrypt_token

    def test_roundtrip_simple_token(self):
        encrypt, decrypt = self._get_encrypt_decrypt()
        token = "sk-test-token-abc123"
        encrypted = encrypt(token)
        assert encrypted != token
        assert decrypt(encrypted) == token

    def test_roundtrip_long_token(self):
        encrypt, decrypt = self._get_encrypt_decrypt()
        token = "a" * 500
        encrypted = encrypt(token)
        assert decrypt(encrypted) == token

    def test_roundtrip_unicode_token(self):
        encrypt, decrypt = self._get_encrypt_decrypt()
        token = "token-with-special-chars-!@#$%^&*()"
        encrypted = encrypt(token)
        assert decrypt(encrypted) == token

    def test_roundtrip_empty_string(self):
        encrypt, decrypt = self._get_encrypt_decrypt()
        encrypted = encrypt("")
        assert decrypt(encrypted) == ""

    def test_encrypted_is_base64(self):
        encrypt, _ = self._get_encrypt_decrypt()
        import base64
        encrypted = encrypt("some-token")
        # Should not raise
        base64.b64decode(encrypted)

    def test_different_tokens_produce_different_ciphertexts(self):
        encrypt, _ = self._get_encrypt_decrypt()
        e1 = encrypt("token-one")
        e2 = encrypt("token-two")
        assert e1 != e2
