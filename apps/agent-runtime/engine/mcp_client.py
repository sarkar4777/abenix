"""MCP Client implementing the 2025-11-25 Model Context Protocol spec.

Communicates with MCP servers over Streamable HTTP transport using JSON-RPC 2.0.
"""

from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

JSON_RPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-11-25"


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPResource:
    uri: str
    name: str
    description: str
    mime_type: str | None = None


@dataclass
class MCPResourceContent:
    uri: str
    mime_type: str | None = None
    text: str | None = None
    blob: str | None = None


@dataclass
class MCPPrompt:
    name: str
    description: str
    arguments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MCPPromptMessage:
    role: str
    content: str


@dataclass
class MCPToolResult:
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class MCPError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"MCP error {code}: {message}")


class MCPClient:
    """Client for a single MCP server connection."""

    def __init__(
        self,
        server_url: str,
        auth_type: str = "none",
        auth_config: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.auth_type = auth_type
        self.auth_config = auth_config or {}
        self.timeout = timeout
        self._session_id: str | None = None
        self._server_info: dict[str, Any] = {}
        self._capabilities: dict[str, Any] = {}
        self._client: httpx.AsyncClient | None = None

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        if self.auth_type == "api_key":
            key = self.auth_config.get("api_key", "")
            headers["Authorization"] = f"Bearer {key}"
        elif self.auth_type == "oauth2":
            token = self.auth_config.get("access_token", "")
            headers["Authorization"] = f"Bearer {token}"

        return headers

    def _make_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "jsonrpc": JSON_RPC_VERSION,
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params or {},
        }

    async def _send(self, request: dict[str, Any]) -> dict[str, Any]:
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)

        response = await self._client.post(
            self.server_url,
            json=request,
            headers=self._build_headers(),
        )

        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id

        response.raise_for_status()
        body = response.json()

        if "error" in body and body["error"]:
            err = body["error"]
            raise MCPError(
                code=err.get("code", -1),
                message=err.get("message", "Unknown MCP error"),
                data=err.get("data"),
            )

        return body.get("result", {})

    async def initialize(self) -> dict[str, Any]:
        result = await self._send(
            self._make_request(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "Abenix",
                        "version": "0.1.0",
                    },
                },
            )
        )

        self._server_info = result.get("serverInfo", {})
        self._capabilities = result.get("capabilities", {})

        await self._send(self._make_request("notifications/initialized"))

        logger.info(
            "MCP connected to %s (protocol %s)",
            self._server_info.get("name", "unknown"),
            result.get("protocolVersion", "unknown"),
        )
        return result

    async def list_tools(self) -> list[MCPTool]:
        result = await self._send(self._make_request("tools/list"))
        tools: list[MCPTool] = []
        for t in result.get("tools", []):
            tools.append(
                MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    annotations=t.get("annotations", {}),
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        result = await self._send(
            self._make_request(
                "tools/call",
                {
                    "name": name,
                    "arguments": arguments,
                },
            )
        )

        content_parts = result.get("content", [])
        text_parts = []
        for part in content_parts:
            if part.get("type") == "text":
                text_parts.append(part.get("text", ""))
            elif part.get("type") == "image":
                text_parts.append(f"[image: {part.get('mimeType', 'unknown')}]")
            else:
                text_parts.append(str(part))

        return MCPToolResult(
            content="\n".join(text_parts) if text_parts else str(result),
            is_error=result.get("isError", False),
        )

    async def list_resources(self) -> list[MCPResource]:
        result = await self._send(self._make_request("resources/list"))
        resources: list[MCPResource] = []
        for r in result.get("resources", []):
            resources.append(
                MCPResource(
                    uri=r["uri"],
                    name=r.get("name", ""),
                    description=r.get("description", ""),
                    mime_type=r.get("mimeType"),
                )
            )
        return resources

    async def read_resource(self, uri: str) -> MCPResourceContent:
        result = await self._send(self._make_request("resources/read", {"uri": uri}))
        contents = result.get("contents", [])
        if not contents:
            return MCPResourceContent(uri=uri, text="")
        first = contents[0]
        return MCPResourceContent(
            uri=first.get("uri", uri),
            mime_type=first.get("mimeType"),
            text=first.get("text"),
            blob=first.get("blob"),
        )

    async def list_prompts(self) -> list[MCPPrompt]:
        result = await self._send(self._make_request("prompts/list"))
        prompts: list[MCPPrompt] = []
        for p in result.get("prompts", []):
            prompts.append(
                MCPPrompt(
                    name=p["name"],
                    description=p.get("description", ""),
                    arguments=p.get("arguments", []),
                )
            )
        return prompts

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> list[MCPPromptMessage]:
        result = await self._send(
            self._make_request(
                "prompts/get",
                {
                    "name": name,
                    "arguments": arguments or {},
                },
            )
        )
        messages: list[MCPPromptMessage] = []
        for m in result.get("messages", []):
            content = m.get("content", {})
            text = (
                content.get("text", "") if isinstance(content, dict) else str(content)
            )
            messages.append(
                MCPPromptMessage(
                    role=m.get("role", "user"),
                    content=text,
                )
            )
        return messages

    async def health_check(self) -> bool:
        try:
            await self.initialize()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def server_info(self) -> dict[str, Any]:
        return self._server_info

    @property
    def capabilities(self) -> dict[str, Any]:
        return self._capabilities
