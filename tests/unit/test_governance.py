"""Risk tiers, kill switches, tool escalation, capabilities and the audit digest."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from engine import governance, risk
from engine.tools.base import BaseTool, ToolResult

TENANT = str(uuid.uuid4())


def run(coro):
    return asyncio.run(coro)


class _Echo(BaseTool):
    name = "echo_low"
    description = "echo"
    input_schema = {"type": "object"}
    risk_tier = "low"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="ran")


class _Writer(_Echo):
    name = "writer_high"
    risk_tier = "high"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="wrote")


class _Nested(_Echo):
    name = "nested_agent"
    risk_tier = "low"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        # a nested run inside a tool still governs its own tools
        ctx = governance.RunContext(tenant_id=TENANT, base_tier="low")
        token = governance.begin_run(ctx)
        try:
            res = await _Writer().execute({})
        finally:
            governance.end_run(token)
        return ToolResult(content=res.content, is_error=res.is_error)


@pytest.fixture(autouse=True)
def _snapshot():
    governance.load_for_test()
    yield
    governance.load_for_test()


def test_tiers_order_and_highest():
    assert risk.TIERS == ("low", "medium", "high", "critical")
    assert risk.highest(["low", "high", "medium"]) == "high"
    assert risk.highest([None, "", "bogus"]) == "low"
    assert risk.above("critical", "high") and not risk.above("low", "low")


def test_merged_policy_overlays_nested_keys():
    p = risk.merged_policy("high", {"publish_approvals": {"min_approvers": 3}})
    assert p["publish_approvals"]["min_approvers"] == 3
    assert p["publish_approvals"]["exclude_author"] is True
    assert p["tool_call_action"] == "approval"


def test_validate_policy_names_each_problem():
    probs = risk.validate_policy(
        {
            "tool_call_action": "maybe",
            "review_sample_rate": 2,
            "publish_approvals": {"min_approvers": -1},
            "nonsense": 1,
        }
    )
    joined = " ".join(probs)
    assert "tool_call_action" in joined
    assert "review_sample_rate" in joined
    assert "min_approvers" in joined
    assert "nonsense" in joined
    assert risk.validate_policy({"allowed_models": ["claude-*"]}) == []


def test_model_allowed_supports_prefix():
    pol = {"allowed_models": ["claude-opus-*", "gpt-5"]}
    assert risk.model_allowed(pol, "claude-opus-5-5")
    assert risk.model_allowed(pol, "gpt-5")
    assert not risk.model_allowed(pol, "gemini-2.5-pro")
    assert risk.model_allowed({"allowed_models": []}, "anything")


def test_kill_switch_scopes_and_platform_switches():
    governance.load_for_test(
        switches=[
            (TENANT, "tool", "web_search", "vendor outage"),
            (None, "model", "gpt-4o", "retired"),
        ]
    )
    assert governance.stopped(TENANT, "tool", "web_search")[2] == "vendor outage"
    assert governance.stopped(TENANT, "tool", "calculator") is None
    assert governance.stopped("other-tenant", "model", "gpt-4o") is not None
    with pytest.raises(governance.Stopped) as e:
        governance.check(TENANT, "tool", "web_search")
    assert "Admin, Risk and Controls" in e.value.message()


def test_all_scope_stops_everything_for_the_tenant():
    governance.load_for_test(switches=[(TENANT, "all", "*", "incident")])
    assert governance.stopped(TENANT, "agent", "x")
    assert governance.stopped(TENANT, "tool", "y")
    assert governance.stopped(str(uuid.uuid4()), "tool", "y") is None


def test_stopped_tool_returns_error_result():
    governance.load_for_test(switches=[(TENANT, "tool", "echo_low", "paused")])
    ctx = governance.RunContext(tenant_id=TENANT)
    token = governance.begin_run(ctx)
    try:
        res = run(_Echo().execute({}))
    finally:
        governance.end_run(token)
    assert res.is_error and "kill switch" in res.content
    assert res.metadata["stopped"]["target"] == "echo_low"


def test_tool_above_run_tier_raises_tier_when_allowed():
    governance.load_for_test(
        policies=[(TENANT, "high", {"tool_call_action": "allow"})]
    )
    ctx = governance.RunContext(tenant_id=TENANT, base_tier="low")
    token = governance.begin_run(ctx)
    try:
        res = run(_Writer().execute({}))
    finally:
        governance.end_run(token)
    assert res.content == "wrote"
    assert ctx.tier == "high"
    assert ctx.reasons[-1]["source"] == "tool:writer_high"


def test_tool_above_run_tier_blocked_by_policy():
    governance.load_for_test(
        policies=[(TENANT, "high", {"tool_call_action": "block"})]
    )
    ctx = governance.RunContext(tenant_id=TENANT, base_tier="medium")
    token = governance.begin_run(ctx)
    try:
        res = run(_Writer().execute({}))
    finally:
        governance.end_run(token)
    assert res.is_error and "blocks the call" in res.content
    assert ctx.tier == "medium"


def test_approval_without_execution_context_fails_closed():
    # default high policy asks for approval, a run with no execution id cannot get one
    ctx = governance.RunContext(tenant_id=TENANT, base_tier="low")
    token = governance.begin_run(ctx)
    try:
        res = run(_Writer().execute({}))
    finally:
        governance.end_run(token)
    assert res.is_error and "needs approval" in res.content
    assert ctx.tier == "low"


def test_tool_at_or_below_run_tier_is_untouched():
    ctx = governance.RunContext(tenant_id=TENANT, base_tier="high")
    token = governance.begin_run(ctx)
    try:
        res = run(_Writer().execute({}))
    finally:
        governance.end_run(token)
    assert res.content == "wrote" and ctx.tier == "high" and ctx.reasons == []


def test_nested_run_inside_a_tool_is_still_governed():
    governance.load_for_test(
        policies=[(TENANT, "high", {"tool_call_action": "block"})]
    )
    outer = governance.RunContext(tenant_id=TENANT, base_tier="low")
    token = governance.begin_run(outer)
    try:
        res = run(_Nested().execute({}))
    finally:
        governance.end_run(token)
    assert res.is_error and "blocks the call" in res.content


def test_no_run_context_only_checks_kill_switches():
    res = run(_Writer().execute({}))
    assert res.content == "wrote"


def test_agent_tier_comes_from_snapshot():
    aid = str(uuid.uuid4())
    governance.load_for_test(agents=[(aid, "critical")])
    assert governance.agent_tier(aid) == "critical"
    assert governance.agent_tier(str(uuid.uuid4())) == "low"


def test_tenant_policy_is_isolated():
    governance.load_for_test(
        policies=[(TENANT, "low", {"allowed_models": ["claude-*"]})]
    )
    assert governance.policy(TENANT, "low")["allowed_models"] == ["claude-*"]
    assert governance.policy(str(uuid.uuid4()), "low")["allowed_models"] == []


def test_capability_holds_wildcards_and_qualifiers():
    from app.core.capabilities import holds, valid_capability

    assert holds(frozenset({"*"}), "decisions.publish")
    assert holds(frozenset({"decisions.*"}), "decisions.publish")
    assert holds(frozenset({"approvals.sign"}), "approvals.sign:legal")
    assert not holds(frozenset({"approvals.sign:legal"}), "approvals.sign:finance")
    assert not holds(frozenset({"decisions.view"}), "decisions.publish")
    assert valid_capability("approvals.sign:legal")
    assert valid_capability("decisions.*")
    assert not valid_capability("made.up")


def test_capabilities_merge_role_defaults_and_sets():
    from app.core import capabilities as caps

    class _Res:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Db:
        async def execute(self, _q):
            return _Res([(["decisions.publish", 7],), (None,)])

    user = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=SimpleNamespace(value="user")
    )
    caps.invalidate()
    got = run(caps.capabilities_for(_Db(), user))
    assert "decisions.publish" in got and "decisions.evaluate" in got
    assert "permissions.manage" not in got


def _row(**kw):
    base = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "action": "agent.updated",
        "details": {"a": 1},
        "ip_address": "10.0.0.1",
        "user_agent": "ua",
        "created_at": datetime(2026, 10, 2, tzinfo=timezone.utc),
        "audit_seq": 5,
    }
    base.update(kw)
    return base


def test_audit_digest_commits_to_actor_through_salt():
    from app.services.audit_chain import pii_digest, row_digest

    r = _row()
    r["pii_digest"] = pii_digest("s1", r)
    h = row_digest(None, r)
    # erasure clears the actor fields but keeps the digest, the row hash holds
    erased = {**r, "user_id": uuid.UUID(int=0), "ip_address": None, "user_agent": None}
    assert row_digest(None, erased) == h
    # a changed action does not
    assert row_digest(None, {**r, "action": "agent.deleted"}) != h
    # a changed actor shows against the salted digest
    assert pii_digest("s1", {**r, "user_id": uuid.uuid4()}) != r["pii_digest"]
    # and the link matters
    assert row_digest("abc", r) != h


def test_running_agent_stops_at_next_tool_call():
    aid = str(uuid.uuid4())
    governance.load_for_test(switches=[(TENANT, "agent", aid, "bad output")])
    ctx = governance.RunContext(tenant_id=TENANT, scope="agent", subject_id=aid)
    token = governance.begin_run(ctx)
    try:
        res = run(_Echo().execute({}))
    finally:
        governance.end_run(token)
    assert res.is_error and "bad output" in res.content


def test_stopped_pipeline_stops_its_nested_agents():
    pid = str(uuid.uuid4())
    governance.load_for_test(switches=[(TENANT, "pipeline", pid, "halt")])
    outer = governance.RunContext(tenant_id=TENANT, scope="pipeline", subject_id=pid)
    inner = governance.RunContext(
        tenant_id=TENANT, scope="agent", subject_id=str(uuid.uuid4()), parent=outer
    )
    t1 = governance.begin_run(outer)
    t2 = governance.begin_run(inner)
    try:
        res = run(_Echo().execute({}))
    finally:
        governance.end_run(t2)
        governance.end_run(t1)
    assert res.is_error and "halt" in res.content
