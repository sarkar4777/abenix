"""Fixes from the sidebar walk: meetings readiness, execution filters, trigger counts."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.routers import executions as E
from app.routers import meetings as M
from app.routers import triggers as T
from models.user import UserRole


def test_meetings_readiness_lists_what_is_missing():
    r = M.readiness_report({"LIVEKIT_URL": "wss://lk.example"}, is_admin=True)
    assert r["livekit_ready"] is False
    assert r["missing"] == ["LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"]
    assert "Tool configuration" in r["message"]
    assert r["configure_url"] == "/admin/tool-config#LIVEKIT_URL"
    assert r["works_without_keys"]


def test_meetings_readiness_never_returns_values_and_hides_admin_link():
    vals = {k: f"secret-{k}" for k in M.LIVEKIT_KEYS}
    r = M.readiness_report(vals, is_admin=False)
    assert r["livekit_ready"] is True
    assert r["missing"] == [] and r["message"] is None
    assert r["configure_url"] is None
    assert not any("secret-" in str(v) for v in r.values())


# executions and triggers lists, called directly with a recording session


class _Res:
    def scalar(self):
        return 0

    def all(self):
        return []


class _DB:
    def __init__(self):
        self.sql: list[str] = []

    async def execute(self, stmt):
        self.sql.append(
            str(
                stmt.compile(
                    dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                )
            )
        )
        return _Res()

    async def scalar(self, stmt):
        await self.execute(stmt)
        return 0


def _member():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=UserRole.USER)


LIST = dict(
    agent_id=None,
    search="",
    sort="newest",
    limit=20,
    offset=0,
    trigger_kind=None,
    trigger_id=None,
)


@pytest.mark.asyncio
async def test_execution_status_filter_takes_any_case():
    db = _DB()
    res = await E.list_executions(
        user=_member(), db=db, status="COMPLETED", since=None, **LIST
    )
    assert res.status_code == 200
    assert any("'COMPLETED'" in q or "'completed'" in q for q in db.sql)


@pytest.mark.asyncio
async def test_execution_unknown_status_is_a_400_not_a_500():
    res = await E.list_executions(
        user=_member(), db=_DB(), status="bogus", since=None, **LIST
    )
    assert res.status_code == 400
    assert "Unknown status" in json.loads(res.body)["error"]["message"]


@pytest.mark.asyncio
async def test_member_rows_are_their_own_and_since_today_filters():
    u = _member()
    db = _DB()
    await E.list_executions(user=u, db=db, status=None, since="today", **LIST)
    rows_query = db.sql[-1]
    assert str(u.id) in rows_query and "executions.created_at >=" in rows_query
    assert (
        await E.list_executions(user=u, db=_DB(), status=None, since="week", **LIST)
    ).status_code == 400


@pytest.mark.asyncio
async def test_trigger_total_counts_the_listed_rows():
    db = _DB()
    agent = uuid.uuid4()
    await T.list_triggers(
        search="walker",
        trigger_type="",
        sort="newest",
        agent_id=str(agent),
        trigger_id="",
        limit=20,
        offset=0,
        user=_member(),
        db=db,
    )
    count_sql = db.sql[0]
    assert "count(" in count_sql.lower()
    assert agent.hex in count_sql.replace("-", "") and "agents.name ILIKE" in count_sql


@pytest.mark.asyncio
async def test_meeting_will_not_go_live_without_livekit(monkeypatch):
    m = SimpleNamespace(
        status="authorized", scope_allow=["pricing"], provider="livekit"
    )

    async def _load(*a, **k):
        return m

    async def _settings(*a, **k):
        return {k: "" for k in M.LIVEKIT_KEYS}

    async def _in_budget(*a, **k):
        return None

    monkeypatch.setattr(M, "_load", _load)
    monkeypatch.setattr(M, "_livekit_settings", _settings)
    monkeypatch.setattr(M, "_meeting_budget_error", _in_budget)
    res = await M.start_meeting("x", {}, user=_member(), db=_DB())
    assert res.status_code == 400
    assert "LiveKit" in json.loads(res.body)["error"]["message"]
    assert m.status == "authorized"


def test_mcp_allow_list_reason_reads_plainly(monkeypatch):
    from app.routers import mcp

    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "custom-mcp.abenix.svc.cluster.local")
    ok, why = mcp._validate_mcp_url("http://nothing-here.invalid/mcp")
    assert not ok
    assert why.startswith("nothing-here.invalid is not on this workspace's list")
    assert mcp._validate_mcp_url("http://custom-mcp.abenix.svc.cluster.local:8080/mcp")[
        0
    ]
    assert (
        mcp._validate_mcp_url("ftp://x.example/mcp")[1]
        == "Use an http or https address"
    )


@pytest.mark.asyncio
async def test_moderation_events_never_keep_the_matched_secret(monkeypatch):
    from app.core import moderation_glue as G

    policy = SimpleNamespace(
        id=uuid.uuid4(),
        pre_llm=True,
        post_llm=True,
        on_tool_output=False,
        provider_model="omni-moderation-latest",
        thresholds={},
        default_threshold=0.5,
        category_actions={},
        default_action="block",
        custom_patterns=[r"\b\d{3}-\d{2}-\d{4}\b"],
        redaction_mask="#####",
        fail_closed=False,
    )

    async def _active(*a, **k):
        return policy

    monkeypatch.setattr(G, "load_active_policy", _active)
    ctx = await G.build_gate_context(None, uuid.uuid4(), uuid.uuid4())
    decision = SimpleNamespace(
        outcome="blocked",
        triggered_categories=["custom:0"],
        provider_response={},
        latency_ms=3,
        error=None,
    )
    ctx.gate.event_sink(
        decision=decision, source="pre_llm", content_preview="my ssn is 123-45-6789"
    )
    assert ctx.events[0]["content_preview"] == "my ssn is #####"
