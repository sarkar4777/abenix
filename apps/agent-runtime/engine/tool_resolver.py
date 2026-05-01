"""Resolve built-in + MCP tools for an agent at execution time."""

from __future__ import annotations

import logging
from typing import Any

from engine.mcp_client import MCPClient, MCPTool
from engine.mcp_security import MCPSecurityContext, MCPSecurityPolicy, validate_tool_annotations
from engine.tools.base import BaseTool, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


class MCPToolWrapper(BaseTool):
    """Wraps an MCP server tool as a BaseTool so it plugs into ToolRegistry."""

    def __init__(
        self,
        client: MCPClient,
        mcp_tool: MCPTool,
        security_ctx: MCPSecurityContext | None = None,
    ) -> None:
        self.name = mcp_tool.name
        self.description = mcp_tool.description
        self.input_schema = mcp_tool.input_schema
        self.annotations = mcp_tool.annotations
        self._client = client
        self._mcp_tool = mcp_tool
        self._security_ctx = security_ctx

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self._security_ctx:
            result = await self._security_ctx.execute_tool(
                self._client, self._mcp_tool, arguments
            )
            return ToolResult(
                content=result.content,
                is_error=result.is_error,
                metadata=result.metadata,
            )

        result = await self._client.call_tool(self.name, arguments)
        return ToolResult(
            content=result.content,
            is_error=result.is_error,
            metadata=result.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "annotations": self.annotations,
        }


async def resolve_tools(
    builtin_tool_names: list[str],
    mcp_connections: list[dict[str, Any]],
    security_policy: MCPSecurityPolicy | None = None,
) -> tuple[ToolRegistry, list[MCPClient], MCPSecurityContext | None]:
    """Build a ToolRegistry from built-in tool names + MCP server connections."""
    from engine.agent_executor import build_tool_registry

    registry = build_tool_registry(builtin_tool_names)
    clients: list[MCPClient] = []

    security_ctx: MCPSecurityContext | None = None
    if mcp_connections:
        security_ctx = MCPSecurityContext(security_policy)

    for conn in mcp_connections:
        server_url = conn["server_url"]
        auth_type = conn.get("auth_type", "none")
        auth_config = conn.get("auth_config") or {}
        allowed_tools: list[str] = conn.get("tools", [])

        client = MCPClient(
            server_url=server_url,
            auth_type=auth_type,
            auth_config=auth_config,
        )

        try:
            await client.initialize()
            remote_tools = await client.list_tools()
        except Exception:
            logger.exception("Failed to connect to MCP server %s", server_url)
            await client.close()
            continue

        clients.append(client)

        for tool in remote_tools:
            if allowed_tools and tool.name not in allowed_tools:
                continue
            if registry.get(tool.name):
                logger.warning(
                    "MCP tool %s from %s conflicts with existing tool, skipping",
                    tool.name,
                    server_url,
                )
                continue

            warnings = validate_tool_annotations(tool)
            for w in warnings:
                logger.warning(w)

            wrapper = MCPToolWrapper(client, tool, security_ctx)
            registry.register(wrapper)
            logger.info("Registered MCP tool: %s from %s", tool.name, server_url)

    return registry, clients, security_ctx
