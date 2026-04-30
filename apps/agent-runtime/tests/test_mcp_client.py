from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.mcp_client import MCPClient, MCPError, MCPTool, MCPToolResult


def _make_mock_response(result_data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": result_data}
    resp.headers = {"Mcp-Session-Id": "session-123"}
    resp.raise_for_status = MagicMock()
    return resp


def test_mcp_tool_dataclass():
    tool = MCPTool(
        name="test_tool",
        description="A test tool",
        input_schema={"type": "object"},
        annotations={"readOnlyHint": True},
    )
    assert tool.name == "test_tool"
    assert tool.annotations["readOnlyHint"] is True


def test_mcp_tool_result_defaults():
    result = MCPToolResult(content="ok")
    assert result.is_error is False
    assert result.metadata == {}


def test_mcp_error():
    err = MCPError(code=-32600, message="Invalid Request")
    assert err.code == -32600
    assert "Invalid Request" in str(err)


def test_mcp_error_with_data():
    err = MCPError(code=-32600, message="Bad", data={"detail": "missing field"})
    assert err.data == {"detail": "missing field"}


class TestMCPClient:
    def test_init_defaults(self):
        client = MCPClient(server_url="http://localhost:9000/mcp")
        assert client.server_url == "http://localhost:9000/mcp"
        assert client.auth_type == "none"
        assert client.timeout == 30.0

    def test_init_with_auth(self):
        client = MCPClient(
            server_url="http://localhost:9000/mcp",
            auth_type="api_key",
            auth_config={"key": "test-key-123"},
        )
        assert client.auth_type == "api_key"

    def test_server_info_before_init(self):
        client = MCPClient(server_url="http://localhost:9000/mcp")
        assert client.server_info == {}

    def test_capabilities_before_init(self):
        client = MCPClient(server_url="http://localhost:9000/mcp")
        assert client.capabilities == {}

    @pytest.mark.asyncio
    async def test_initialize_success(self):
        client = MCPClient(server_url="http://localhost:9000/mcp")
        init_resp = _make_mock_response({
            "protocolVersion": "2025-11-25",
            "serverInfo": {"name": "test-server", "version": "1.0"},
            "capabilities": {"tools": {}},
        })
        notify_resp = _make_mock_response({})

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=[init_resp, notify_resp])
        client._client = mock_http

        result = await client.initialize()
        assert "serverInfo" in result

    @pytest.mark.asyncio
    async def test_list_tools_parses_response(self):
        client = MCPClient(server_url="http://localhost:9000/mcp")
        mock_response = _make_mock_response({
            "tools": [
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "inputSchema": {"type": "object"},
                    "annotations": {"readOnlyHint": True},
                }
            ]
        })

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._client = mock_http

        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "read_file"
        assert tools[0].annotations["readOnlyHint"] is True

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        client = MCPClient(server_url="http://localhost:9000/mcp")
        init_resp = _make_mock_response({
            "protocolVersion": "2025-11-25",
            "serverInfo": {"name": "test-server", "version": "1.0"},
            "capabilities": {},
        })
        notify_resp = _make_mock_response({})

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=[init_resp, notify_resp])
        client._client = mock_http

        healthy = await client.health_check()
        assert healthy is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        client = MCPClient(server_url="http://localhost:9000/mcp")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=Exception("Connection refused"))
        client._client = mock_http

        healthy = await client.health_check()
        assert healthy is False
