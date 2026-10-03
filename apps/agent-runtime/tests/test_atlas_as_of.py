"""atlas_as_of answers from atlas snapshots and the live atlas tables."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from engine.tools import atlas_tools
from engine.tools.atlas_tools import AtlasAsOfTool

TENANT = str(uuid.uuid4())
GID = uuid.uuid4()
NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
A, B, C = (uuid.uuid4() for _ in range(3))


class _Conn:
    def __init__(self, graph, snapshot=None, nodes=(), edges=(), first_snap=None):
        self.graph = graph
        self.snapshot = snapshot
        self.nodes = list(nodes)
        self.edges = list(edges)
        self.first_snap = first_snap
        self.snapshot_args = None

    async def fetchrow(self, sql, *args):
        if "FROM atlas_graphs WHERE id = $1 AND tenant_id" in sql:
            return {"id": GID}
        if "FROM atlas_graphs WHERE id = $1" in sql:
            return self.graph
        if "FROM atlas_snapshots" in sql:
            self.snapshot_args = args
            return self.snapshot
        raise AssertionError(sql)

    async def fetch(self, sql, *args):
        if "FROM atlas_nodes" in sql:
            return self.nodes
        if "FROM atlas_edges" in sql:
            return self.edges
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        return self.first_snap


def _install(monkeypatch, conn):
    class _Pool:
        @asynccontextmanager
        async def acquire(self):
            yield conn

    async def _pool():
        return _Pool()

    monkeypatch.setattr(atlas_tools, "_pool", _pool)


def _node(nid, label, created, **kw):
    return {
        "id": nid,
        "label": label,
        "kind": "concept",
        "description": "",
        "created_at": created,
        "valid_from": kw.get("valid_from"),
        "valid_to": kw.get("valid_to"),
    }


async def _run(monkeypatch, conn, **args):
    _install(monkeypatch, conn)
    tool = AtlasAsOfTool(tenant_id=TENANT)
    res = await tool.execute({"graph_id": str(GID), **args})
    assert not res.is_error, res.content
    return json.loads(res.content)


@pytest.mark.asyncio
async def test_reads_the_snapshot_saved_before_as_of(monkeypatch):
    snap_at = NOW - timedelta(days=30)
    payload = {
        "nodes": [
            {"id": str(A), "label": "Counterparty", "kind": "concept"},
            {"id": str(B), "label": "Trade", "kind": "concept"},
        ],
        "edges": [
            {
                "id": str(C),
                "from_node_id": str(A),
                "to_node_id": str(B),
                "label": "books",
            }
        ],
    }
    conn = _Conn(
        graph={
            "created_at": NOW - timedelta(days=90),
            "updated_at": NOW,
            "version": 9,
        },
        snapshot={
            "id": uuid.uuid4(),
            "version": 4,
            "label": None,
            "created_at": snap_at,
            "payload": json.dumps(payload),
        },
    )
    as_of = (NOW - timedelta(days=10)).isoformat()
    out = await _run(monkeypatch, conn, as_of=as_of)
    assert out["found"] is True
    assert out["source"] == "snapshot"
    assert out["version"] == 4
    assert conn.snapshot_args[1] == NOW - timedelta(days=10)
    assert {n["label"] for n in out["nodes"]} == {"Counterparty", "Trade"}
    assert out["edges"][0]["from"]["label"] == "Counterparty"
    assert out["edges"][0]["to"]["label"] == "Trade"


@pytest.mark.asyncio
async def test_live_rows_honour_the_validity_window(monkeypatch):
    conn = _Conn(
        graph={
            "created_at": NOW - timedelta(days=90),
            "updated_at": NOW - timedelta(days=5),
            "version": 3,
        },
        nodes=[
            _node(A, "Current", NOW - timedelta(days=60)),
            _node(
                B,
                "Retired",
                NOW - timedelta(days=60),
                valid_to=NOW - timedelta(days=20),
            ),
            _node(C, "Later", NOW - timedelta(days=60), valid_from=NOW),
        ],
    )
    out = await _run(monkeypatch, conn, as_of=(NOW - timedelta(days=1)).isoformat())
    assert out["source"] == "live"
    assert [n["label"] for n in out["nodes"]] == ["Current"]
    assert conn.snapshot_args is None


@pytest.mark.asyncio
async def test_before_the_graph_existed(monkeypatch):
    conn = _Conn(graph={"created_at": NOW, "updated_at": NOW, "version": 1})
    out = await _run(monkeypatch, conn, as_of="2020-01-01")
    assert out["found"] is False
    assert "created" in out["reason"]


@pytest.mark.asyncio
async def test_no_snapshot_old_enough_says_so(monkeypatch):
    conn = _Conn(
        graph={
            "created_at": NOW - timedelta(days=90),
            "updated_at": NOW,
            "version": 2,
        },
        snapshot=None,
        first_snap=NOW - timedelta(days=3),
    )
    out = await _run(monkeypatch, conn, as_of=(NOW - timedelta(days=30)).isoformat())
    assert out["found"] is False
    assert "earliest" in out["reason"]


@pytest.mark.asyncio
async def test_label_filter_keeps_touching_edges(monkeypatch):
    conn = _Conn(
        graph={
            "created_at": NOW - timedelta(days=90),
            "updated_at": NOW - timedelta(days=5),
            "version": 3,
        },
        nodes=[
            _node(A, "Counterparty", NOW - timedelta(days=60)),
            _node(B, "Trade", NOW - timedelta(days=60)),
        ],
        edges=[
            {
                "id": C,
                "from_node_id": A,
                "to_node_id": B,
                "label": "books",
                "created_at": NOW - timedelta(days=60),
                "valid_from": None,
                "valid_to": None,
            }
        ],
    )
    out = await _run(monkeypatch, conn, label_like="counter")
    assert [n["label"] for n in out["nodes"]] == ["Counterparty"]
    assert out["edge_total"] == 1


@pytest.mark.asyncio
async def test_bad_timestamp_is_rejected():
    res = await AtlasAsOfTool(tenant_id=TENANT).execute({"as_of": "last tuesday"})
    assert res.is_error


def test_cypher_tool_is_gone():
    assert "atlas_cypher" not in atlas_tools.ATLAS_TOOL_NAMES
    assert "atlas_as_of" in atlas_tools.ATLAS_TOOL_NAMES
