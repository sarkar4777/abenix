"""Orphaned MCP tools: discovery flags them, re-discovery clears them,
attach rejects them and the runtime warns the model instead of loading them.

No database. The router handlers are called directly with a scripted session.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.routers import mcp as mcp_router
from app.schemas.mcp import AttachMCPToolRequest
from engine.tool_resolver import load_agent_mcp_connections, resolve_tools
from engine.tools.base import ToolRegistry

TENANT = uuid.uuid4()


class _Result:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return list(self._rows)

    def scalars(self):
        return SimpleNamespace(all=lambda: [r for r in self._rows])


class _ScriptedDB:
    # Each execute pops the next scripted result in order.
    def __init__(self, results):
        self._results = list(results)
        self.committed = False
        self.deleted = []

    async def execute(self, _stmt):
        return self._results.pop(0)

    async def commit(self):
        self.committed = True

    async def refresh(self, _obj):
        return None

    async def delete(self, obj):
        self.deleted.append(obj)


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT, role="user")


def _conn(discovered=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        server_name="github",
        server_url="http://github-mcp:9000/mcp",
        auth_type="none",
        auth_config=None,
        discovered_tools=discovered,
        health_status="unknown",
        last_health_check=None,
    )


def _row(tool_name, conn_id, *, orphaned=False):
    return SimpleNamespace(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        mcp_connection_id=conn_id,
        tool_name=tool_name,
        tool_config={},
        approval_required=False,
        max_calls_per_execution=None,
        is_orphaned=orphaned,
        orphaned_at=datetime.now(timezone.utc) if orphaned else None,
    )


def _remote(name):
    return SimpleNamespace(name=name, description="", input_schema={}, annotations={})


def _body(resp):
    return json.loads(resp.body)


def _patched_client(tools):
    inst = AsyncMock()
    inst.initialize = AsyncMock()
    inst.list_tools = AsyncMock(return_value=tools)
    inst.close = AsyncMock()
    return patch("engine.mcp_client.MCPClient", return_value=inst)


# ── discover ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discover_flags_missing_tool_and_keeps_row():
    conn = _conn()
    live = _row("search", conn.id)
    gone = _row("old_tool", conn.id)
    db = _ScriptedDB(
        [_Result(scalar=conn), _Result(rows=[(live, "Bot A"), (gone, "Bot B")])]
    )

    with _patched_client([_remote("search")]):
        resp = await mcp_router.discover_tools(conn.id, user=_user(), db=db)

    data = _body(resp)["data"]
    assert db.deleted == []
    assert gone.is_orphaned is True and gone.orphaned_at is not None
    assert live.is_orphaned is False
    assert "removed_agent_tools" not in data
    assert [o["tool_name"] for o in data["orphaned_agent_tools"]] == ["old_tool"]
    assert data["orphaned_agent_tools"][0]["agent_name"] == "Bot B"
    assert data["orphaned_agent_tools"][0]["agent_id"] == str(gone.agent_id)


@pytest.mark.asyncio
async def test_rediscover_clears_flag_when_tool_returns():
    conn = _conn()
    back = _row("old_tool", conn.id, orphaned=True)
    db = _ScriptedDB([_Result(scalar=conn), _Result(rows=[(back, "Bot")])])

    with _patched_client([_remote("old_tool")]):
        resp = await mcp_router.discover_tools(conn.id, user=_user(), db=db)

    assert back.is_orphaned is False and back.orphaned_at is None
    assert _body(resp)["data"]["orphaned_agent_tools"] == []
    assert db.committed


@pytest.mark.asyncio
async def test_discover_keeps_existing_orphaned_at():
    conn = _conn()
    stale = _row("old_tool", conn.id, orphaned=True)
    first = stale.orphaned_at
    db = _ScriptedDB([_Result(scalar=conn), _Result(rows=[(stale, None)])])

    with _patched_client([_remote("other")]):
        await mcp_router.discover_tools(conn.id, user=_user(), db=db)

    assert stale.orphaned_at == first


# ── attach ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_attach_rejects_tool_the_server_dropped():
    conn = _conn(discovered=[{"name": "search"}])
    agent = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT)
    db = _ScriptedDB([_Result(scalar=agent), _Result(scalar=conn), _Result()])
    body = AttachMCPToolRequest(mcp_connection_id=str(conn.id), tool_name="old_tool")

    resp = await mcp_router.attach_tool(agent.id, body, user=_user(), db=db)

    assert resp.status_code == 400
    msg = _body(resp)["error"]["message"]
    assert "old_tool" in msg and "github" in msg and "no longer offered" in msg


@pytest.mark.asyncio
async def test_attach_rejects_already_orphaned_row():
    conn = _conn(discovered=[{"name": "search"}])
    agent = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT)
    existing = _row("old_tool", conn.id, orphaned=True)
    db = _ScriptedDB(
        [_Result(scalar=agent), _Result(scalar=conn), _Result(scalar=existing)]
    )
    body = AttachMCPToolRequest(mcp_connection_id=str(conn.id), tool_name="old_tool")

    resp = await mcp_router.attach_tool(agent.id, body, user=_user(), db=db)

    assert resp.status_code == 400
    assert "old_tool" in _body(resp)["error"]["message"]


@pytest.mark.asyncio
async def test_attach_allows_live_tool_and_serializes_flag():
    conn = _conn(discovered=[{"name": "search"}])
    agent = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT)
    db = _ScriptedDB([_Result(scalar=agent), _Result(scalar=conn), _Result()])
    db.add = lambda obj: None
    body = AttachMCPToolRequest(mcp_connection_id=str(conn.id), tool_name="search")

    resp = await mcp_router.attach_tool(agent.id, body, user=_user(), db=db)

    assert resp.status_code == 201
    data = _body(resp)["data"]
    assert data["is_orphaned"] is False and data["orphaned_at"] is None


# ── runtime ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_connections_splits_orphaned_rows():
    conn = _conn()
    conn.is_enabled = True
    agent_id = uuid.uuid4()
    rows = [
        _row("search", conn.id),
        _row("old_tool", conn.id, orphaned=True),
    ]
    db = _ScriptedDB([_Result(rows=rows), _Result(rows=[conn])])

    out = await load_agent_mcp_connections(
        db, agent_id, TENANT, decrypt=lambda _t, cfg: cfg
    )

    assert len(out) == 1
    assert out[0]["tools"] == ["search"]
    assert out[0]["orphaned_tools"] == ["old_tool"]
    assert "old_tool" not in out[0]["tool_settings"]


@pytest.mark.asyncio
async def test_resolver_warns_and_skips_orphaned_tool():
    remote = [
        SimpleNamespace(name="search", description="", input_schema={}, annotations={}),
        SimpleNamespace(
            name="old_tool", description="", input_schema={}, annotations={}
        ),
    ]
    inst = AsyncMock()
    inst.initialize = AsyncMock()
    inst.list_tools = AsyncMock(return_value=remote)
    inst.close = AsyncMock()

    with patch(
        "engine.agent_executor.build_tool_registry", return_value=ToolRegistry()
    ):
        with patch("engine.tool_resolver.MCPClient", return_value=inst):
            registry, clients, _ = await resolve_tools(
                [],
                [
                    {
                        "server_name": "github",
                        "server_url": "http://github-mcp:9000/mcp",
                        "tools": ["search"],
                        "orphaned_tools": ["old_tool"],
                    }
                ],
            )

    assert "search" in registry.names()
    assert "old_tool" not in registry.names()
    assert len(clients) == 1
    assert registry.mcp_warnings == [
        "tool old_tool on server github is no longer offered, "
        "remove it from the agent or re-add it on the server"
    ]


@pytest.mark.asyncio
async def test_resolver_skips_connection_with_only_orphans():
    with patch(
        "engine.agent_executor.build_tool_registry", return_value=ToolRegistry()
    ):
        with patch("engine.tool_resolver.MCPClient") as MockClient:
            registry, clients, _ = await resolve_tools(
                [],
                [
                    {
                        "server_name": "github",
                        "server_url": "http://github-mcp:9000/mcp",
                        "tools": [],
                        "orphaned_tools": ["old_tool"],
                    }
                ],
            )

    MockClient.assert_not_called()
    assert clients == []
    assert registry.names() == []
    assert len(registry.mcp_warnings) == 1
    assert "old_tool" in registry.mcp_warnings[0]
