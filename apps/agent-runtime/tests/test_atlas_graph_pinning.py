"""model_config.atlas_graphs pins which graph the atlas tools read."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from engine.tools.atlas_tools import _resolve_graph_id

TENANT = str(uuid.uuid4())
PINNED = str(uuid.uuid4())
OTHER = str(uuid.uuid4())


def _conn(row_id: str | None) -> AsyncMock:
    conn = AsyncMock()
    conn.fetchrow.return_value = {"id": uuid.UUID(row_id)} if row_id else None
    return conn


@pytest.mark.asyncio
async def test_defaults_to_pinned_graph_when_graph_id_omitted():
    conn = _conn(PINNED)
    gid = await _resolve_graph_id(conn, TENANT, [PINNED], None)
    assert gid == PINNED
    sql, _tid, allowed = conn.fetchrow.call_args.args
    assert "ANY($2::uuid[])" in sql
    assert allowed == [uuid.UUID(PINNED)]


@pytest.mark.asyncio
async def test_rejects_graph_outside_pin_list():
    conn = _conn(OTHER)
    assert await _resolve_graph_id(conn, TENANT, [PINNED], OTHER) is None


@pytest.mark.asyncio
async def test_no_pin_falls_back_to_tenant_latest():
    conn = _conn(OTHER)
    assert await _resolve_graph_id(conn, TENANT, [], None) == OTHER
    sql = conn.fetchrow.call_args.args[0]
    assert "ANY" not in sql
