"""Resolve built-in + MCP tools for an agent at execution time."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

from engine.mcp_client import MCPClient, MCPTool
from engine.mcp_security import (
    MCPSecurityContext,
    MCPSecurityPolicy,
    validate_tool_annotations,
)
from engine.tools.base import READ_ONLY, BaseTool, Effect, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

# Matches app.core.crypto output, "v1:<b64>".
_ENC_RE = re.compile(r"^v\d+:")
_SECRET_KEYS = (
    "api_key",
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
    "token",
    "bearer",
)


class MCPToolWrapper(BaseTool):
    """Wraps an MCP server tool as a BaseTool so it plugs into ToolRegistry."""

    # reaches systems or runs code the platform did not write
    risk_tier = "medium"
    effect = Effect(kind="external", label="Call a tool on an MCP server")

    def __init__(
        self,
        client: MCPClient,
        mcp_tool: MCPTool,
        security_ctx: MCPSecurityContext | None = None,
        *,
        name: str | None = None,
        approval_required: bool = False,
        max_calls: int | None = None,
        approval_tool: BaseTool | None = None,
    ) -> None:
        self.name = name or mcp_tool.name
        self.description = mcp_tool.description
        self.input_schema = mcp_tool.input_schema
        self.annotations = mcp_tool.annotations
        if (self.annotations or {}).get("readOnlyHint"):
            self.effect = READ_ONLY
        self._client = client
        self._mcp_tool = mcp_tool
        self._security_ctx = security_ctx
        self._approval_required = bool(approval_required)
        self._max_calls = int(max_calls) if max_calls else 0
        self._approval_tool = approval_tool
        self._calls = 0

    def _needs_approval(self) -> bool:
        if self._approval_required:
            return True
        # Destructive tools the policy would block go through the gate instead of failing.
        return bool(
            self._security_ctx and self._security_ctx.needs_gate(self._mcp_tool)
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self._max_calls and self._calls >= self._max_calls:
            return ToolResult(
                content=f"max_calls_per_execution ({self._max_calls}) reached for {self.name}",
                is_error=True,
                metadata={"max_calls_reached": True},
            )
        self._calls += 1

        if self._needs_approval():
            if self._approval_tool is None:
                return ToolResult(
                    content=(
                        f"{self.name} requires approval but human_approval is not in "
                        "the agent's tools"
                    ),
                    is_error=True,
                )
            gate = await self._approval_tool.execute(
                {
                    "action": f"call {self.name}",
                    "details": json.dumps(arguments or {}, default=str)[:4000],
                    "risk_level": "high",
                }
            )
            if gate.is_error:
                return ToolResult(
                    content=f"approval denied for {self.name}: {gate.content}",
                    is_error=True,
                    metadata={"approval": gate.metadata},
                )
            if self._security_ctx:
                self._security_ctx.approve_tool(self._mcp_tool.name)

        if self._security_ctx:
            result = await self._security_ctx.execute_tool(
                self._client, self._mcp_tool, arguments
            )
            return ToolResult(
                content=result.content,
                is_error=result.is_error,
                metadata=result.metadata,
            )

        result = await self._client.call_tool(self._mcp_tool.name, arguments)
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


def _server_label(conn: dict[str, Any]) -> str:
    name = (conn.get("server_name") or "").strip()
    if name:
        return name
    host = urlparse(conn.get("server_url") or "").hostname or ""
    return host or (conn.get("server_url") or "mcp")


def _server_prefix(conn: dict[str, Any]) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", _server_label(conn)).strip("_").lower()
    return slug or "mcp"


async def resolve_tools(
    builtin_tool_names: list[str],
    mcp_connections: list[dict[str, Any]],
    security_policy: MCPSecurityPolicy | None = None,
    kb_ids: list[str] | None = None,
    **registry_kwargs: Any,
) -> tuple[ToolRegistry, list[MCPClient], MCPSecurityContext | None]:
    """Build a ToolRegistry from built-in tool names + MCP server connections.

    Connection failures are collected on ``registry.mcp_warnings`` so the
    caller can tell the model which servers are missing this run.
    """
    from engine.agent_executor import build_tool_registry

    registry = build_tool_registry(builtin_tool_names, kb_ids=kb_ids, **registry_kwargs)
    clients: list[MCPClient] = []
    warnings: list[str] = []
    registry.mcp_warnings = warnings  # type: ignore[attr-defined]

    security_ctx: MCPSecurityContext | None = None
    if mcp_connections:
        security_ctx = MCPSecurityContext(security_policy)

    approval_tool = registry.get("human_approval")

    for conn in mcp_connections:
        server_url = conn["server_url"]
        auth_type = conn.get("auth_type", "none")
        auth_config = conn.get("auth_config") or {}
        allowed_tools: list[str] = conn.get("tools", [])
        tool_settings: dict[str, dict[str, Any]] = conn.get("tool_settings") or {}
        label = _server_label(conn)

        # Rows discovery flagged as orphaned are never registered, the model is told why.
        for orphan in conn.get("orphaned_tools") or []:
            warnings.append(
                f"tool {orphan} on server {label} is no longer offered, "
                "remove it from the agent or re-add it on the server"
            )
        if not allowed_tools and conn.get("orphaned_tools"):
            continue

        client = MCPClient(
            server_url=server_url,
            auth_type=auth_type,
            auth_config=auth_config,
        )

        try:
            await client.initialize()
            remote_tools = await client.list_tools()
        except Exception as exc:
            logger.exception("Failed to connect to MCP server %s", server_url)
            await client.close()
            warnings.append(
                f"MCP server {label} unavailable ({type(exc).__name__}), "
                "its tools are not available this run"
            )
            continue

        clients.append(client)

        remote_names = {t.name for t in remote_tools}
        for missing in [n for n in allowed_tools if n not in remote_names]:
            warnings.append(
                f"MCP tool {missing} is no longer offered by {label}, re-run discovery"
            )

        for tool in remote_tools:
            if allowed_tools and tool.name not in allowed_tools:
                continue
            reg_name = tool.name
            if registry.get(reg_name):
                reg_name = f"{_server_prefix(conn)}__{tool.name}"
                logger.warning(
                    "MCP tool %s from %s conflicts with existing tool, registering as %s",
                    tool.name,
                    server_url,
                    reg_name,
                )
                if registry.get(reg_name):
                    logger.warning("MCP tool %s already registered, skipping", reg_name)
                    continue

            for w in validate_tool_annotations(tool):
                logger.warning(w)

            settings = tool_settings.get(tool.name) or {}
            wrapper = MCPToolWrapper(
                client,
                tool,
                security_ctx,
                name=reg_name,
                approval_required=bool(settings.get("approval_required")),
                max_calls=settings.get("max_calls_per_execution"),
                approval_tool=approval_tool,
            )
            registry.register(wrapper)
            tc = settings.get("tool_config")
            if isinstance(tc, dict) and tc:
                registry.apply_tool_config({reg_name: tc})
            logger.info("Registered MCP tool: %s from %s", reg_name, server_url)

    return registry, clients, security_ctx


def decrypt_auth_config(
    tenant_id: Any, cfg: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Decrypt secret values written by the API's _encrypt_auth_config."""
    if not cfg or not isinstance(cfg, dict):
        return cfg
    try:
        from app.core import crypto as _crypto
    except Exception:
        logger.warning("app.core.crypto not importable, MCP auth_config left as stored")
        return cfg
    out: dict[str, Any] = {}
    for k, v in cfg.items():
        if isinstance(v, str) and k.lower() in _SECRET_KEYS and _ENC_RE.match(v):
            out[k] = _crypto.decrypt(tenant_id, v)
        else:
            out[k] = v
    return out


async def load_agent_mcp_connections(
    db: Any,
    agent_id: Any,
    tenant_id: Any,
    decrypt: Any = None,
) -> list[dict[str, Any]]:
    """Load the enabled MCP connections attached to an agent, with per-tool settings."""
    import uuid as _uuid

    from sqlalchemy import select

    from models.mcp_connection import AgentMCPTool, UserMCPConnection  # type: ignore

    decrypt = decrypt or decrypt_auth_config
    if isinstance(agent_id, str):
        agent_id = _uuid.UUID(agent_id)
    if isinstance(tenant_id, str) and tenant_id:
        tenant_id = _uuid.UUID(tenant_id)

    result = await db.execute(
        select(AgentMCPTool).where(AgentMCPTool.agent_id == agent_id)
    )
    agent_tools = result.scalars().all()
    if not agent_tools:
        return []

    conn_ids = {t.mcp_connection_id for t in agent_tools}
    conn_result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id.in_(conn_ids),
            UserMCPConnection.tenant_id == tenant_id,
            UserMCPConnection.is_enabled,
        )
    )
    connections = {c.id: c for c in conn_result.scalars().all()}

    mcp_conns: dict[str, dict[str, Any]] = {}
    for tool in agent_tools:
        conn = connections.get(tool.mcp_connection_id)
        if not conn:
            continue
        key = str(conn.id)
        if key not in mcp_conns:
            mcp_conns[key] = {
                "connection_id": key,
                "server_name": conn.server_name,
                "server_url": conn.server_url,
                "auth_type": conn.auth_type,
                "auth_config": decrypt(conn.tenant_id, conn.auth_config) or {},
                "tools": [],
                "tool_settings": {},
                "orphaned_tools": [],
            }
        if getattr(tool, "is_orphaned", False):
            mcp_conns[key]["orphaned_tools"].append(tool.tool_name)
            continue
        mcp_conns[key]["tools"].append(tool.tool_name)
        mcp_conns[key]["tool_settings"][tool.tool_name] = {
            "approval_required": bool(tool.approval_required),
            "max_calls_per_execution": tool.max_calls_per_execution,
            "tool_config": tool.tool_config or {},
        }

    return list(mcp_conns.values())


def get_default_registry_descriptions() -> list[dict[str, str]]:
    """Name + description for every registered built-in tool.

    Reads the class attributes so tools that need constructor args still
    show up. Used by the Pipeline Surgeon to bound the tools it may use.
    """
    from engine.agent_executor import (
        _CONTEXT_TOOL_FACTORIES,
        _TOOL_CLASSES,
        _ensure_tool_classes,
    )

    _ensure_tool_classes()
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for slug, cls in list(_TOOL_CLASSES.items()) + list(
        _CONTEXT_TOOL_FACTORIES.items()
    ):
        if slug in seen:
            continue
        seen.add(slug)
        desc = getattr(cls, "description", "")
        if not isinstance(desc, str):
            desc = ""
        out.append({"name": slug, "description": " ".join(desc.split())[:400]})
    out.sort(key=lambda d: d["name"])
    return out
