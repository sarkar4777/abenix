"""MCP server connection management endpoints."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.core.sanitize import sanitize_input
from app.schemas.mcp import (
    AttachMCPToolRequest,
    ConnectMCPRequest,
    DetachMCPToolRequest,
    DiscoverURLRequest,
    GetPromptRequest,
    OAuth2CallbackRequest,
    OAuth2StartRequest,
    ReadResourceRequest,
    RegistryInstallRequest,
    UpdateMCPConnectionRequest,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from models.agent import Agent
from models.mcp_connection import AgentMCPTool, MCPRegistryCache, UserMCPConnection
from models.user import User

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

TOKEN_ENCRYPT_KEY = os.environ.get("MCP_TOKEN_KEY", "abenix-mcp-default-key-32b!")


def _encrypt_token(token: str) -> str:
    """Simple XOR obfuscation for stored OAuth tokens."""
    key = hashlib.sha256(TOKEN_ENCRYPT_KEY.encode()).digest()
    encrypted = bytes(
        a ^ b for a, b in zip(token.encode(), key * (len(token) // len(key) + 1))
    )
    return base64.b64encode(encrypted).decode()


def _decrypt_token(encrypted: str) -> str:
    key = hashlib.sha256(TOKEN_ENCRYPT_KEY.encode()).digest()
    data = base64.b64decode(encrypted)
    decrypted = bytes(a ^ b for a, b in zip(data, key * (len(data) // len(key) + 1)))
    return decrypted.decode()


def _serialize_connection(c: UserMCPConnection) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "server_name": c.server_name,
        "server_url": c.server_url,
        "transport_type": c.transport_type,
        "auth_type": c.auth_type,
        "discovered_tools": c.discovered_tools,
        "health_status": c.health_status,
        "is_enabled": c.is_enabled,
        "last_health_check": (
            c.last_health_check.isoformat() if c.last_health_check else None
        ),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "oauth2_configured": bool(c.oauth2_client_id),
        "oauth2_connected": bool(c.oauth2_access_token_enc),
    }


def _serialize_agent_tool(t: AgentMCPTool) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "agent_id": str(t.agent_id),
        "mcp_connection_id": str(t.mcp_connection_id),
        "tool_name": t.tool_name,
        "tool_config": t.tool_config,
        "approval_required": t.approval_required,
        "max_calls_per_execution": t.max_calls_per_execution,
    }


@router.get("/connections")
async def list_connections(
    search: str = Query("", max_length=255, description="Search by server name"),
    sort: str = Query("newest", description="Sort: newest, oldest, name"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    query = select(UserMCPConnection).where(
        UserMCPConnection.tenant_id == user.tenant_id,
        UserMCPConnection.user_id == user.id,
    )

    if search:
        query = query.where(UserMCPConnection.server_name.ilike(f"%{search}%"))

    # Sort
    if sort == "oldest":
        query = query.order_by(UserMCPConnection.created_at.asc())
    elif sort == "name":
        query = query.order_by(UserMCPConnection.server_name.asc())
    else:  # newest (default)
        query = query.order_by(UserMCPConnection.created_at.desc())

    # Count total before pagination
    count_base = select(UserMCPConnection).where(
        UserMCPConnection.tenant_id == user.tenant_id,
        UserMCPConnection.user_id == user.id,
    )
    if search:
        count_base = count_base.where(
            UserMCPConnection.server_name.ilike(f"%{search}%")
        )
    count_query = select(func.count()).select_from(count_base.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    connections = result.scalars().all()
    data = [_serialize_connection(c) for c in connections]
    return success(data, meta={"total": total, "limit": limit, "offset": offset})


def _validate_mcp_url(url: str) -> tuple[bool, str]:
    """Reject obviously-unsafe MCP server URLs before we store creds for them.

    Without this check a user could point the MCP connection at an
    internal service (`http://abenix-api.abenix.svc.cluster.local/...`
    or `http://169.254.169.254/` for cloud metadata) and the runtime
    would happily proxy its OAuth token there. Rules:

    * Must be http(s).
    * Must not resolve to a private/link-local/loopback IP.
    * Host must be in `MCP_ALLOWED_HOSTS` (comma-separated suffixes) if
      that env var is set — operators can lock this down in production.
    """
    import ipaddress
    from urllib.parse import urlparse

    try:
        u = urlparse(url)
    except Exception:
        return False, "invalid url"
    if u.scheme not in ("http", "https"):
        return False, "scheme must be http(s)"
    host = (u.hostname or "").strip()
    if not host:
        return False, "host is required"
    # Block IP literals that hit internal infra / cloud metadata
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return False, f"private/loopback IPs not allowed ({host})"
    except ValueError:
        # Hostname, not an IP — check allow-list suffixes if configured
        pass
    # Operator-managed allow-list. When set, ANY listed host (including
    # cluster-internal services like UAT fixtures) is permitted; nothing
    # outside the list is. When unset, fall through to the conservative
    # block-list below (the default for production).
    lowered = host.lower()
    allow = (os.environ.get("MCP_ALLOWED_HOSTS") or "").strip()
    if allow:
        suffixes = [s.strip().lower() for s in allow.split(",") if s.strip()]
        if any(lowered == s or lowered.endswith("." + s) for s in suffixes):
            return True, ""
        return False, f"host '{host}' not in MCP_ALLOWED_HOSTS"
    # Block hostnames that resolve inside the cluster or to localhost
    if lowered in ("localhost", "host.docker.internal", "host.minikube.internal"):
        return False, f"internal hostname blocked ({host})"
    if lowered.endswith(".svc.cluster.local") or lowered.endswith(".cluster.local"):
        return False, "cluster-internal DNS blocked"
    return True, ""


@router.post("/connections")
async def create_connection(
    body: ConnectMCPRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    ok, reason = _validate_mcp_url(body.server_url)
    if not ok:
        return error(f"server_url rejected: {reason}", 400)
    conn = UserMCPConnection(
        tenant_id=user.tenant_id,
        user_id=user.id,
        server_name=sanitize_input(body.server_name),
        server_url=body.server_url,
        transport_type="streamable_http",
        auth_type=body.auth_type,
        auth_config=body.auth_config,
        health_status="unknown",
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)

    await log_action(
        db,
        user.tenant_id,
        user.id,
        "mcp.connected",
        {"server_name": body.server_name, "server_url": body.server_url},
    )
    await db.commit()

    return success(_serialize_connection(conn), status_code=201)


@router.get("/connections/{connection_id}")
async def get_connection(
    connection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id == connection_id,
            UserMCPConnection.tenant_id == user.tenant_id,
            UserMCPConnection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return error("Connection not found", 404)
    return success(_serialize_connection(conn))


@router.put("/connections/{connection_id}")
async def update_connection(
    connection_id: uuid.UUID,
    body: UpdateMCPConnectionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id == connection_id,
            UserMCPConnection.tenant_id == user.tenant_id,
            UserMCPConnection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return error("Connection not found", 404)

    if body.server_name is not None:
        conn.server_name = sanitize_input(body.server_name)
    if body.auth_type is not None:
        conn.auth_type = body.auth_type
    if body.auth_config is not None:
        conn.auth_config = body.auth_config
    if body.is_enabled is not None:
        conn.is_enabled = body.is_enabled

    await db.commit()
    await db.refresh(conn)
    return success(_serialize_connection(conn))


@router.delete("/connections/{connection_id}")
async def delete_connection(
    connection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id == connection_id,
            UserMCPConnection.tenant_id == user.tenant_id,
            UserMCPConnection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return error("Connection not found", 404)

    await db.execute(
        select(AgentMCPTool).where(AgentMCPTool.mcp_connection_id == connection_id)
    )

    await db.delete(conn)
    await db.commit()
    return success({"id": str(connection_id), "deleted": True})


@router.post("/connections/{connection_id}/discover")
async def discover_tools(
    connection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id == connection_id,
            UserMCPConnection.tenant_id == user.tenant_id,
            UserMCPConnection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return error("Connection not found", 404)

    from engine.mcp_client import MCPClient

    client = MCPClient(
        server_url=conn.server_url,
        auth_type=conn.auth_type,
        auth_config=conn.auth_config or {},
    )

    try:
        await client.initialize()
        tools = await client.list_tools()
    except Exception as e:
        conn.health_status = "error"
        conn.last_health_check = datetime.now(timezone.utc)
        await db.commit()
        return error(f"Failed to connect: {str(e)}", 502)
    finally:
        await client.close()

    discovered = [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
            "annotations": t.annotations,
        }
        for t in tools
    ]

    conn.discovered_tools = discovered
    conn.health_status = "healthy"
    conn.last_health_check = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(conn)

    return success(
        {
            "connection_id": str(connection_id),
            "server_name": conn.server_name,
            "tools": discovered,
            "tools_count": len(discovered),
        }
    )


@router.post("/discover")
async def discover_url(
    body: DiscoverURLRequest,
    _user: User = Depends(get_current_user),
) -> JSONResponse:
    """Inline discover: probe a URL without saving a connection."""
    from engine.mcp_client import MCPClient

    client = MCPClient(
        server_url=body.server_url,
        auth_type=body.auth_type,
        auth_config=body.auth_config or {},
    )

    try:
        await client.initialize()
        tools = await client.list_tools()

        resources = []
        try:
            resources_raw = await client.list_resources()
            resources = [
                {
                    "uri": r.uri,
                    "name": r.name,
                    "description": r.description,
                    "mime_type": r.mime_type,
                }
                for r in resources_raw
            ]
        except Exception:
            pass

        prompts = []
        try:
            prompts_raw = await client.list_prompts()
            prompts = [
                {"name": p.name, "description": p.description, "arguments": p.arguments}
                for p in prompts_raw
            ]
        except Exception:
            pass

    except Exception as e:
        return error(f"Failed to connect: {str(e)}", 502)
    finally:
        await client.close()

    discovered_tools = [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
            "annotations": t.annotations,
        }
        for t in tools
    ]

    return success(
        {
            "server_info": client.server_info,
            "tools": discovered_tools,
            "resources": resources,
            "prompts": prompts,
            "tools_count": len(discovered_tools),
            "resources_count": len(resources),
            "prompts_count": len(prompts),
        }
    )


@router.post("/connections/{connection_id}/health")
async def check_health(
    connection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id == connection_id,
            UserMCPConnection.tenant_id == user.tenant_id,
            UserMCPConnection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return error("Connection not found", 404)

    from engine.mcp_client import MCPClient

    client = MCPClient(
        server_url=conn.server_url,
        auth_type=conn.auth_type,
        auth_config=conn.auth_config or {},
    )

    healthy = await client.health_check()
    await client.close()

    conn.health_status = "healthy" if healthy else "error"
    conn.last_health_check = datetime.now(timezone.utc)
    await db.commit()

    return success(
        {
            "connection_id": str(connection_id),
            "healthy": healthy,
            "checked_at": conn.last_health_check.isoformat(),
        }
    )


@router.get("/connections/{connection_id}/resources")
async def list_resources(
    connection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id == connection_id,
            UserMCPConnection.tenant_id == user.tenant_id,
            UserMCPConnection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return error("Connection not found", 404)

    from engine.mcp_client import MCPClient

    client = MCPClient(
        server_url=conn.server_url,
        auth_type=conn.auth_type,
        auth_config=conn.auth_config or {},
    )

    try:
        await client.initialize()
        resources = await client.list_resources()
    except Exception as e:
        return error(f"Failed to list resources: {str(e)}", 502)
    finally:
        await client.close()

    data = [
        {
            "uri": r.uri,
            "name": r.name,
            "description": r.description,
            "mime_type": r.mime_type,
        }
        for r in resources
    ]
    return success(data, meta={"count": len(data)})


@router.post("/connections/{connection_id}/resources/read")
async def read_resource(
    connection_id: uuid.UUID,
    body: ReadResourceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id == connection_id,
            UserMCPConnection.tenant_id == user.tenant_id,
            UserMCPConnection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return error("Connection not found", 404)

    from engine.mcp_client import MCPClient

    client = MCPClient(
        server_url=conn.server_url,
        auth_type=conn.auth_type,
        auth_config=conn.auth_config or {},
    )

    try:
        await client.initialize()
        content = await client.read_resource(body.uri)
    except Exception as e:
        return error(f"Failed to read resource: {str(e)}", 502)
    finally:
        await client.close()

    return success(
        {
            "uri": content.uri,
            "mime_type": content.mime_type,
            "text": content.text,
            "has_blob": content.blob is not None,
        }
    )


@router.get("/connections/{connection_id}/prompts")
async def list_prompts(
    connection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id == connection_id,
            UserMCPConnection.tenant_id == user.tenant_id,
            UserMCPConnection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return error("Connection not found", 404)

    from engine.mcp_client import MCPClient

    client = MCPClient(
        server_url=conn.server_url,
        auth_type=conn.auth_type,
        auth_config=conn.auth_config or {},
    )

    try:
        await client.initialize()
        prompts = await client.list_prompts()
    except Exception as e:
        return error(f"Failed to list prompts: {str(e)}", 502)
    finally:
        await client.close()

    data = [
        {"name": p.name, "description": p.description, "arguments": p.arguments}
        for p in prompts
    ]
    return success(data, meta={"count": len(data)})


@router.post("/connections/{connection_id}/prompts/get")
async def get_prompt(
    connection_id: uuid.UUID,
    body: GetPromptRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id == connection_id,
            UserMCPConnection.tenant_id == user.tenant_id,
            UserMCPConnection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return error("Connection not found", 404)

    from engine.mcp_client import MCPClient

    client = MCPClient(
        server_url=conn.server_url,
        auth_type=conn.auth_type,
        auth_config=conn.auth_config or {},
    )

    try:
        await client.initialize()
        messages = await client.get_prompt(body.name, body.arguments)
    except Exception as e:
        return error(f"Failed to get prompt: {str(e)}", 502)
    finally:
        await client.close()

    data = [{"role": m.role, "content": m.content} for m in messages]
    return success(data, meta={"prompt_name": body.name, "messages_count": len(data)})


@router.post("/oauth2/start")
async def oauth2_start(
    body: OAuth2StartRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Start OAuth2 PKCE flow: generate code_verifier, code_challenge, state, and return auth URL."""
    result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id == uuid.UUID(body.connection_id),
            UserMCPConnection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return error("Connection not found", 404)

    if conn.auth_type != "oauth2":
        return error("Connection is not configured for OAuth2", 400)

    if not conn.oauth2_authorization_url or not conn.oauth2_client_id:
        return error("OAuth2 authorization_url and client_id must be configured", 400)

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(32)

    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": conn.oauth2_client_id,
        "redirect_uri": body.redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "scope": "openid",
    }
    auth_url = f"{conn.oauth2_authorization_url}?{urlencode(params)}"

    return success(
        {
            "authorization_url": auth_url,
            "state": state,
            "code_verifier": code_verifier,
        }
    )


@router.post("/oauth2/callback")
async def oauth2_callback(
    body: OAuth2CallbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Complete OAuth2 PKCE: exchange code for tokens and store encrypted."""
    result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id == uuid.UUID(body.connection_id),
            UserMCPConnection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return error("Connection not found", 404)

    if not conn.oauth2_token_url or not conn.oauth2_client_id:
        return error("OAuth2 token_url and client_id must be configured", 400)

    import httpx

    token_data = {
        "grant_type": "authorization_code",
        "code": body.code,
        "code_verifier": body.code_verifier,
        "client_id": conn.oauth2_client_id,
        "redirect_uri": (
            conn.auth_config.get("redirect_uri", "") if conn.auth_config else ""
        ),
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(conn.oauth2_token_url, data=token_data)
            resp.raise_for_status()
            tokens = resp.json()
    except Exception as e:
        return error(f"Token exchange failed: {str(e)}", 502)

    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in")

    conn.oauth2_access_token_enc = _encrypt_token(access_token)
    if refresh_token:
        conn.oauth2_refresh_token_enc = _encrypt_token(refresh_token)
    if expires_in:
        from datetime import timedelta

        conn.oauth2_token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=expires_in
        )

    conn.auth_config = {**(conn.auth_config or {}), "access_token": access_token}

    await db.commit()
    await db.refresh(conn)

    await log_action(
        db,
        user.tenant_id,
        user.id,
        "mcp.oauth2_connected",
        {
            "connection_id": body.connection_id,
            "server_name": conn.server_name,
        },
    )
    await db.commit()

    return success(
        {
            "connection_id": body.connection_id,
            "connected": True,
            "expires_at": (
                conn.oauth2_token_expires_at.isoformat()
                if conn.oauth2_token_expires_at
                else None
            ),
        }
    )


@router.get("/agents/{agent_id}/tools")
async def list_agent_mcp_tools(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    agent_result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user.tenant_id)
    )
    if not agent_result.scalar_one_or_none():
        return error("Agent not found", 404)

    result = await db.execute(
        select(AgentMCPTool).where(AgentMCPTool.agent_id == agent_id)
    )
    tools = result.scalars().all()
    data = [_serialize_agent_tool(t) for t in tools]
    return success(data, meta={"count": len(data)})


@router.post("/agents/{agent_id}/tools")
async def attach_tool(
    agent_id: uuid.UUID,
    body: AttachMCPToolRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    agent_result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user.tenant_id)
    )
    if not agent_result.scalar_one_or_none():
        return error("Agent not found", 404)

    conn_result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id == uuid.UUID(body.mcp_connection_id),
            UserMCPConnection.user_id == user.id,
        )
    )
    if not conn_result.scalar_one_or_none():
        return error("MCP connection not found", 404)

    existing = await db.execute(
        select(AgentMCPTool).where(
            AgentMCPTool.agent_id == agent_id,
            AgentMCPTool.mcp_connection_id == uuid.UUID(body.mcp_connection_id),
            AgentMCPTool.tool_name == body.tool_name,
        )
    )
    if existing.scalar_one_or_none():
        return error("Tool already attached", 409)

    tool = AgentMCPTool(
        agent_id=agent_id,
        mcp_connection_id=uuid.UUID(body.mcp_connection_id),
        tool_name=body.tool_name,
        tool_config=body.tool_config,
        approval_required=body.approval_required,
        max_calls_per_execution=body.max_calls_per_execution,
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return success(_serialize_agent_tool(tool), status_code=201)


@router.delete("/agents/{agent_id}/tools")
async def detach_tool(
    agent_id: uuid.UUID,
    body: DetachMCPToolRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(AgentMCPTool).where(
            AgentMCPTool.agent_id == agent_id,
            AgentMCPTool.mcp_connection_id == uuid.UUID(body.mcp_connection_id),
            AgentMCPTool.tool_name == body.tool_name,
        )
    )
    tool = result.scalar_one_or_none()
    if not tool:
        return error("Tool not attached", 404)

    await db.delete(tool)
    await db.commit()
    return success(
        {"agent_id": str(agent_id), "tool_name": body.tool_name, "detached": True}
    )


@router.get("/registry")
async def browse_registry(
    category: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> JSONResponse:
    query = select(MCPRegistryCache).order_by(MCPRegistryCache.popularity_score.desc())

    if search:
        query = query.where(
            MCPRegistryCache.name.ilike(f"%{search}%")
            | MCPRegistryCache.description.ilike(f"%{search}%")
        )

    result = await db.execute(query)
    entries = result.scalars().all()

    if category:
        entries = [e for e in entries if e.categories and category in e.categories]

    data = [
        {
            "id": str(e.id),
            "registry_id": e.registry_id,
            "name": e.name,
            "description": e.description,
            "server_url": e.server_url,
            "auth_type": e.auth_type,
            "categories": e.categories,
            "tools_count": e.tools_count,
            "popularity_score": e.popularity_score,
            "verified": e.verified,
        }
        for e in entries
    ]
    return success(data, meta={"count": len(data)})


@router.post("/registry/install")
async def install_from_registry(
    body: RegistryInstallRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Install an MCP server from the registry as a user connection."""
    result = await db.execute(
        select(MCPRegistryCache).where(MCPRegistryCache.registry_id == body.registry_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        return error("Registry entry not found", 404)

    conn = UserMCPConnection(
        tenant_id=user.tenant_id,
        user_id=user.id,
        server_name=sanitize_input(body.server_name),
        server_url=entry.server_url,
        transport_type="streamable_http",
        auth_type=entry.auth_type,
        health_status="unknown",
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)

    await log_action(
        db,
        user.tenant_id,
        user.id,
        "mcp.installed_from_registry",
        {
            "registry_id": body.registry_id,
            "server_url": entry.server_url,
        },
    )
    await db.commit()

    return success(_serialize_connection(conn), status_code=201)


@router.post("/registry/sync")
async def sync_registry(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Seed/sync registry with curated MCP servers."""
    curated = [
        {
            "registry_id": "github-mcp",
            "name": "GitHub",
            "description": "Access GitHub repositories, issues, PRs, and actions",
            "server_url": "https://api.githubcopilot.com/mcp",
            "auth_type": "oauth2",
            "categories": ["development", "version-control"],
            "tools_count": 12,
            "popularity_score": 95,
            "verified": True,
        },
        {
            "registry_id": "slack-mcp",
            "name": "Slack",
            "description": "Send messages, manage channels, and search Slack workspace",
            "server_url": "https://mcp.slack.com/v1",
            "auth_type": "oauth2",
            "categories": ["communication", "productivity"],
            "tools_count": 8,
            "popularity_score": 90,
            "verified": True,
        },
        {
            "registry_id": "postgres-mcp",
            "name": "PostgreSQL",
            "description": "Query and manage PostgreSQL databases",
            "server_url": "https://mcp.postgresql.org/v1",
            "auth_type": "api_key",
            "categories": ["database", "analytics"],
            "tools_count": 6,
            "popularity_score": 88,
            "verified": True,
        },
        {
            "registry_id": "stripe-mcp",
            "name": "Stripe",
            "description": "Manage payments, subscriptions, and financial data",
            "server_url": "https://mcp.stripe.com/v1",
            "auth_type": "api_key",
            "categories": ["finance", "payments"],
            "tools_count": 10,
            "popularity_score": 85,
            "verified": True,
        },
        {
            "registry_id": "notion-mcp",
            "name": "Notion",
            "description": "Access and manage Notion pages, databases, and blocks",
            "server_url": "https://mcp.notion.so/v1",
            "auth_type": "oauth2",
            "categories": ["productivity", "knowledge-management"],
            "tools_count": 9,
            "popularity_score": 82,
            "verified": True,
        },
        {
            "registry_id": "jira-mcp",
            "name": "Jira",
            "description": "Create and manage issues, sprints, and projects in Jira",
            "server_url": "https://mcp.atlassian.com/jira/v1",
            "auth_type": "oauth2",
            "categories": ["project-management", "development"],
            "tools_count": 7,
            "popularity_score": 78,
            "verified": True,
        },
        {
            "registry_id": "google-drive-mcp",
            "name": "Google Drive",
            "description": "Access and manage Google Drive files and folders",
            "server_url": "https://mcp.googleapis.com/drive/v1",
            "auth_type": "oauth2",
            "categories": ["storage", "productivity"],
            "tools_count": 5,
            "popularity_score": 75,
            "verified": True,
        },
        {
            "registry_id": "weather-mcp",
            "name": "Weather",
            "description": "Current weather, forecasts, and historical weather data",
            "server_url": "https://mcp.weather.gov/v1",
            "auth_type": "none",
            "categories": ["data", "utilities"],
            "tools_count": 4,
            "popularity_score": 60,
            "verified": False,
        },
    ]

    synced = 0
    for entry in curated:
        existing = await db.execute(
            select(MCPRegistryCache).where(
                MCPRegistryCache.registry_id == entry["registry_id"]
            )
        )
        record = existing.scalar_one_or_none()
        if record:
            record.name = entry["name"]
            record.description = entry["description"]
            record.server_url = entry["server_url"]
            record.auth_type = entry["auth_type"]
            record.categories = entry["categories"]
            record.tools_count = entry["tools_count"]
            record.popularity_score = entry["popularity_score"]
            record.verified = entry["verified"]
        else:
            record = MCPRegistryCache(
                registry_id=entry["registry_id"],
                name=entry["name"],
                description=entry["description"],
                server_url=entry["server_url"],
                auth_type=entry["auth_type"],
                categories=entry["categories"],
                tools_count=entry["tools_count"],
                popularity_score=entry["popularity_score"],
                verified=entry["verified"],
            )
            db.add(record)
        synced += 1

    await db.commit()

    return success({"synced": synced, "total_entries": len(curated)})
