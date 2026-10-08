"""The autonomy gate at every level, the ledger, and what the model sees."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import random
import sys
from pathlib import Path
from typing import Any

import pytest

from engine import autonomy, governance
from engine.tools.base import (
    READ_ONLY,
    BaseTool,
    Effect,
    ToolRegistry,
    ToolResult,
    _DefaultedTool,
)

T = "11111111-1111-1111-1111-111111111111"
AGENT = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"
OWNER = "44444444-4444-4444-4444-444444444444"
AT = "55555555-5555-5555-5555-555555555555"
G = "66666666-6666-6666-6666-666666666666"
EXEC = "77777777-7777-7777-7777-777777777777"
APPROVAL = "88888888-8888-8888-8888-888888888888"
REVIEWER = "99999999-9999-9999-9999-999999999999"


class Valve(BaseTool):
    name = "valve"
    description = "Set a valve"
    risk_tier = "low"
    effect = Effect(
        kind="control",
        label="Set a valve position",
        target_param="valve",
        magnitude_param="position",
        reversible=True,
    )
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string"},
            "valve": {"type": "string"},
            "position": {"type": "number"},
        },
    }

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @classmethod
    def effect_for(cls, arguments: dict[str, Any]) -> Effect | None:
        return READ_ONLY if arguments.get("operation") == "read" else cls.effect

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(dict(arguments))
        return ToolResult(content=json.dumps({"ok": True, **arguments}))


class Plain(BaseTool):
    name = "plain"
    description = "No effect"
    risk_tier = "low"
    input_schema = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(dict(arguments))
        return ToolResult(content="ok")


def action_type(**over: Any) -> dict[str, Any]:
    at = {
        "id": AT,
        "tenant_id": T,
        "key": "valve.set",
        "label": "Set a valve position",
        "tool_name": "valve",
        "match": None,
        "world_model": {"kind": "agent_stated", "metric": "flow"},
        "outcome_probe": {"kind": "tool", "after_s": 60},
        "limits_decision_key": None,
        "max_band_width": 0.5,
        "reversible": True,
        "ceiling": None,
        "policy": None,
    }
    at.update(over)
    return at


def grant(level: int, **over: Any) -> dict[str, Any]:
    g = {
        "id": G,
        "tenant_id": T,
        "agent_id": AGENT,
        "action_type_id": AT,
        "scope": None,
        "level": level,
        "ceiling": 4,
        "state": "active",
        "agent_config_hash": None,
        "granted_by": OWNER,
        "creator_id": None,
        "agent_name": "Valve bot",
    }
    g.update(over)
    return g


class Ledger:
    def __init__(self, fail: Exception | None = None) -> None:
        self.ops: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail

    async def __call__(self, op: str, data: dict[str, Any]) -> None:
        if self.fail is not None:
            raise self.fail
        self.ops.append((op, dict(data)))

    def rows(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for op, d in self.ops:
            if op == "insert":
                out[d["id"]] = dict(d)
            elif op == "update" and d["id"] in out:
                out[d["id"]].update(d)
        return out

    def only(self) -> dict[str, Any]:
        rows = list(self.rows().values())
        assert len(rows) == 1, rows
        return rows[0]

    def notes(self) -> list[dict[str, Any]]:
        return [d for op, d in self.ops if op == "notify"]


class Approver:
    def __init__(self, final: dict[str, Any] | None = None, fail: str = "") -> None:
        self.final = final or {"status": "approved", "signoffs": []}
        self.fail = fail
        self.bodies: list[dict[str, Any]] = []

    async def create(self, body: dict[str, Any], *, user_id: str, tenant_id: str):
        self.bodies.append(body)
        self.user_id = user_id
        if self.fail:
            return None, self.fail
        return {"id": APPROVAL}, ""

    async def wait(self, approval_id: str, *, expires_s: int, execution_id: str | None):
        self.waited = (approval_id, expires_s, execution_id)
        return {"id": approval_id, **self.final}


def ok_limits(*breach_reason: str):
    async def decide(tenant: str, key: str, facts: dict[str, Any]) -> dict[str, Any]:
        decide.facts = facts  # type: ignore[attr-defined]
        if breach_reason:
            return {
                "outcome": "decided",
                "result": {"ok": False, "reason": breach_reason[0]},
            }
        return {"outcome": "no_match", "result": None}

    return decide


@pytest.fixture(autouse=True)
def _clean():
    governance.load_for_test()
    yield
    autonomy.configure()
    autonomy.load_for_test()
    autonomy._loaded_at = 0.0
    governance.configure()
    governance.load_for_test()
    governance.invalidate()


def setup(
    level: int | None = None,
    *,
    at: dict[str, Any] | None = None,
    g: dict[str, Any] | None = None,
    approver: Approver | None = None,
    decider: Any = None,
    ledger: Ledger | None = None,
    hashes: dict[str, str] | None = None,
) -> tuple[Ledger, Approver]:
    ledger = ledger or Ledger()
    approver = approver or Approver()
    autonomy.configure(
        writer=ledger,
        approver=approver,
        decider=decider,
        stats=lambda tenant, gid: _stats(),
    )
    types = [at or action_type()] if (at or level is not None) else []
    grants = [g or grant(level)] if level is not None or g else []
    autonomy.load_for_test(types, grants, hashes or {})
    return ledger, approver


async def _stats() -> dict[str, Any]:
    return {"held": 47, "scored": 50, "agreement_pct": 92}


async def run_call(tool: BaseTool, args: dict[str, Any], **ctx: Any) -> ToolResult:
    call_id = ctx.pop("tool_call", None)
    rc = governance.RunContext(
        tenant_id=T,
        execution_id=EXEC,
        agent_name="Valve bot",
        agent_id=ctx.pop("agent_id", AGENT),
        user_id=USER,
        **ctx,
    )
    token = governance.begin_run(rc)
    try:
        if call_id:
            autonomy.set_tool_call(call_id)
        result = await tool.execute(args)
    finally:
        governance.end_run(token)
    await autonomy.flush()
    return result


PRED = {"metric": "flow", "value": 10.0, "low": 9.0, "high": 11.0}


# no grant: today's behaviour plus one ledger row


async def test_tool_without_effect_is_not_recorded():
    ledger, _ = setup()
    tool = Plain()
    res = await run_call(tool, {"_intent": "why"})
    assert res.content == "ok" and res.metadata == {}
    assert tool.calls == [{}]
    assert ledger.ops == []


async def test_read_operation_is_not_recorded():
    ledger, _ = setup(4)
    tool = Valve()
    await run_call(tool, {"operation": "read", "valve": "V1"})
    assert ledger.ops == []
    assert tool.calls == [{"operation": "read", "valve": "V1"}]


async def test_unmanaged_effect_is_recorded_and_runs():
    ledger, _ = setup()
    tool = Valve()
    res = await run_call(
        tool,
        {"valve": "V1", "position": 40, "_intent": "open it", "_prediction": PRED},
        tool_call="call-1",
    )
    assert tool.calls == [{"valve": "V1", "position": 40}]
    assert "autonomy" not in res.metadata
    row = ledger.only()
    assert row["mode"] == "unmanaged"
    assert row["status"] == "executed"
    assert row["target"] == "V1"
    assert row["intent"] == "open it"
    assert row["prediction"]["value"] == 10.0
    assert row["tool_call_id"] == "call-1"
    # a nested run never borrows the outer call id
    nested = Valve()
    ledger.ops.clear()
    await run_call(nested, {"valve": "V2"})
    assert ledger.only()["tool_call_id"] is None
    assert row["agent_id"] == AGENT and row["user_id"] == USER
    assert row["outcome_status"] == "none"
    assert row["result_preview"].startswith('{"ok": true')


async def test_unmanaged_records_a_failed_call():
    ledger, _ = setup()

    class Broken(Valve):
        async def execute(self, arguments):
            return ToolResult(content="nope", is_error=True)

    await run_call(Broken(), {"valve": "V1"})
    assert ledger.only()["status"] == "failed"


async def test_ledger_down_never_breaks_the_call(caplog):
    setup(ledger=Ledger(fail=RuntimeError("connection refused")))
    tool = Valve()
    res = await run_call(tool, {"valve": "V1", "position": 1})
    assert not res.is_error and tool.calls


async def test_missing_ledger_table_is_logged_once_and_skipped(caplog):
    ledger = Ledger(fail=RuntimeError('relation "agent_actions" does not exist'))
    setup(ledger=ledger)
    tool = Valve()
    for _ in range(3):
        res = await run_call(tool, {"valve": "V1"})
        assert not res.is_error
    assert len(tool.calls) == 3
    assert (
        sum("action ledger is not ready" in r.getMessage() for r in caplog.records) == 1
    )


async def test_no_database_at_all_still_runs(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    autonomy.configure()
    autonomy.load_for_test()
    tool = Valve()
    res = await run_call(tool, {"valve": "V1"})
    assert not res.is_error and tool.calls == [{"valve": "V1"}]


async def test_autonomy_args_are_stripped_for_every_tool():
    setup()
    plain, valve = Plain(), Valve()
    await run_call(plain, {"a": 1, "_intent": "x", "_prediction": {}})
    await run_call(valve, {"valve": "V", "_intent": "x", "_prediction": PRED})
    # outside any run too
    await plain.execute({"b": 2, "_intent": "y"})
    await autonomy.flush()
    assert plain.calls == [{"a": 1}, {"b": 2}]
    assert valve.calls == [{"valve": "V"}]


# levels


async def test_off_blocks_without_calling():
    ledger, _ = setup(0)
    tool = Valve()
    res = await run_call(tool, {"valve": "V1", "position": 40})
    assert res.is_error
    assert res.content == (
        "This agent is not allowed to set a valve position (Off). "
        f"An owner can change this on the Autonomy page: /autonomy/{G}"
    )
    assert tool.calls == []
    row = ledger.only()
    assert row["status"] == "blocked" and row["level_at_time"] == 0


async def test_watching_never_calls_the_tool():
    ledger, approver = setup(1)
    tool = Valve()
    res = await run_call(
        tool, {"valve": "V1", "position": 40, "_intent": "too low", "_prediction": PRED}
    )
    assert tool.calls == []
    assert not res.is_error
    assert res.content == autonomy.WATCHING_TEXT
    meta = res.metadata["autonomy"]
    assert meta["status"] == "watching" and meta["level_label"] == "Watching"
    assert meta["proposed"]["arguments"] == {"valve": "V1", "position": 40}
    assert meta["proposed"]["intent"] == "too low"
    row = ledger.only()
    assert row["mode"] == "watching" and row["status"] == "watching"
    assert row["grant_id"] == G and row["action_type_id"] == AT
    assert row["prediction"]["source"] == "agent_stated"
    assert approver.bodies == []


async def test_asks_first_approved_runs_with_the_arguments():
    ledger, approver = setup(
        2,
        approver=Approver(
            {
                "status": "approved",
                "decided_at": "2026-10-08T10:00:00+00:00",
                "signoffs": [
                    {
                        "user_id": REVIEWER,
                        "user_email": "rev@x.dev",
                        "decision": "approve",
                        "reason": "fine",
                    }
                ],
            }
        ),
    )
    tool = Valve()
    res = await run_call(
        tool, {"valve": "V1", "position": 40, "_intent": "low", "_prediction": PRED}
    )
    assert tool.calls == [{"valve": "V1", "position": 40}]
    body = approver.bodies[0]
    assert body["gate_kind"] == "action:valve.set"
    assert body["title"] == "Valve bot wants to set a valve position"
    assert body["required_signoffs"] == 1 and body["expires_seconds"] == 1800
    card = body["payload"]
    for key in (
        "action_id",
        "action_type",
        "agent",
        "level",
        "level_label",
        "target",
        "arguments",
        "intent",
        "prediction",
        "limits",
        "fallback_reason",
        "record",
        "editable_arguments",
    ):
        assert key in card
    assert card["record"]["text"] == "Held 47 of 50 times"
    assert card["level_label"] == "Asks first" and card["target"] == "V1"
    assert approver.user_id == USER
    assert approver.waited == (APPROVAL, 1800, EXEC)
    row = ledger.only()
    assert row["status"] == "executed"
    assert row["approval_id"] == APPROVAL
    assert row["decided_by"] == REVIEWER
    assert row["outcome_status"] == "pending" and row["outcome_due_at"] is not None
    statuses = [d.get("status") for op, d in ledger.ops if d.get("status")]
    assert statuses == ["pending", "approved", "executed"]
    assert res.metadata["autonomy"]["status"] == "executed"


async def test_asks_first_edited_arguments_are_applied():
    ledger, _ = setup(
        2,
        approver=Approver(
            {
                "status": "approved",
                "payload": {"edited_arguments": {"position": 30}},
                "signoffs": [{"user_id": REVIEWER, "decision": "approve"}],
            }
        ),
    )
    tool = Valve()
    await run_call(tool, {"valve": "V1", "position": 40})
    assert tool.calls == [{"valve": "V1", "position": 30}]
    statuses = [d.get("status") for op, d in ledger.ops if d.get("status")]
    assert statuses == ["pending", "edited", "executed"]
    assert ledger.only()["arguments"] == {"valve": "V1", "position": 30}


async def test_asks_first_rejected_does_not_run():
    ledger, _ = setup(
        2,
        approver=Approver(
            {
                "status": "denied",
                "signoffs": [
                    {
                        "user_id": REVIEWER,
                        "user_email": "rev@x.dev",
                        "decision": "deny",
                        "reason": "Pump is in maintenance.",
                    }
                ],
            }
        ),
    )
    tool = Valve()
    res = await run_call(tool, {"valve": "V1", "position": 40})
    assert tool.calls == []
    assert res.is_error
    assert "rev@x.dev rejected this action: Pump is in maintenance." in res.content
    row = ledger.only()
    assert (
        row["status"] == "rejected" and row["decision_note"] == "Pump is in maintenance"
    )


async def test_asks_first_expired_does_not_run():
    ledger, _ = setup(2, approver=Approver({"status": "expired", "signoffs": []}))
    tool = Valve()
    res = await run_call(tool, {"valve": "V1", "position": 40})
    assert tool.calls == [] and res.is_error
    assert "expired" in res.content
    assert ledger.only()["status"] == "expired"


async def test_asks_first_when_the_approval_cannot_be_created():
    ledger, _ = setup(2, approver=Approver(fail="failed to create approval: 500"))
    tool = Valve()
    res = await run_call(tool, {"valve": "V1"})
    assert tool.calls == [] and res.is_error
    assert ledger.only()["status"] == "blocked"


async def test_within_limits_runs_alone_with_a_confident_prediction():
    ledger, approver = setup(3)
    tool = Valve()
    res = await run_call(tool, {"valve": "V1", "position": 40, "_prediction": PRED})
    assert tool.calls == [{"valve": "V1", "position": 40}]
    assert approver.bodies == []
    row = ledger.only()
    assert row["mode"] == "auto" and row["status"] == "executed"
    assert res.metadata["autonomy"]["mode"] == "auto"


@pytest.mark.parametrize(
    "pred, reason",
    [
        (None, "No confident prediction"),
        ({"metric": "flow", "value": 10, "low": 1, "high": 19}, "wider"),
    ],
)
async def test_within_limits_falls_back_to_asking(pred, reason):
    ledger, approver = setup(3)
    tool = Valve()
    args: dict[str, Any] = {"valve": "V1", "position": 40}
    if pred:
        args["_prediction"] = pred
    await run_call(tool, args)
    assert len(approver.bodies) == 1
    card = approver.bodies[0]["payload"]
    assert reason in card["fallback_reason"]
    assert card["level"] == 3
    assert tool.calls == [{"valve": "V1", "position": 40}]


async def test_world_model_timeout_falls_back_to_asking():
    async def slow(tenant, key, facts):
        await asyncio.sleep(1)
        return {"outcome": "decided", "result": {"value": 1}}

    _, approver = setup(
        3,
        at=action_type(world_model={"kind": "decision", "ref": "m", "timeout_s": 0.05}),
        decider=slow,
    )
    await run_call(Valve(), {"valve": "V1", "position": 40})
    card = approver.bodies[0]["payload"]
    assert "did not answer" in card["fallback_reason"]
    assert card["prediction"]["value"] is None


async def test_decision_world_model_prediction():
    async def model(tenant, key, facts):
        assert facts == {"pos": 40}
        return {"outcome": "decided", "result": {"value": 12, "low": 11, "high": 13}}

    ledger, approver = setup(
        3,
        at=action_type(
            world_model={
                "kind": "decision",
                "ref": "flow_model",
                "metric": "flow",
                "inputs": {"pos": "{{args.position}}"},
            }
        ),
        decider=model,
    )
    tool = Valve()
    await run_call(tool, {"valve": "V1", "position": 40})
    assert approver.bodies == [] and tool.calls
    pred = ledger.only()["prediction"]
    assert pred["source"] == "decision" and pred["value"] == 12


async def test_acts_and_reports_runs_and_notifies_the_owner():
    ledger, approver = setup(4)
    tool = Valve()
    res = await run_call(tool, {"valve": "V1", "position": 40})
    assert tool.calls and approver.bodies == []
    row = ledger.only()
    assert row["mode"] == "reported" and row["status"] == "executed"
    assert row["outcome_status"] == "pending"
    note = ledger.notes()[0]
    assert note["user_id"] == OWNER and note["link"] == f"/autonomy/{G}"
    assert res.metadata["autonomy"]["mode"] == "reported"


async def test_outcome_none_when_the_probe_is_none():
    ledger, _ = setup(4, at=action_type(outcome_probe={"kind": "none"}))
    await run_call(Valve(), {"valve": "V1"})
    row = ledger.only()
    assert row["outcome_status"] == "none" and "outcome_due_at" not in row


@pytest.mark.parametrize("level", [0, 1, 2, 3, 4])
async def test_limits_breach_blocks_at_every_level(level):
    decide = ok_limits("position 120 is above the 100 limit")
    ledger, approver = setup(
        level, at=action_type(limits_decision_key="valve_limits"), decider=decide
    )
    tool = Valve()
    res = await run_call(tool, {"valve": "V1", "position": 120, "_prediction": PRED})
    assert tool.calls == [] and res.is_error
    assert approver.bodies == []
    row = ledger.only()
    assert row["status"] == "blocked"
    if level:
        assert "position 120 is above the 100 limit" in res.content
        assert autonomy.LIMITS_TEXT in res.content
        assert row["limits_result"]["ok"] is False
        assert decide.facts["target"] == "V1"


async def test_limits_that_cannot_be_checked_block():
    async def broken(tenant, key, facts):
        raise RuntimeError("decision store down")

    _, _ = setup(4, at=action_type(limits_decision_key="valve_limits"), decider=broken)
    tool = Valve()
    res = await run_call(tool, {"valve": "V1"})
    assert tool.calls == [] and res.is_error
    assert "could not be checked" in res.content


async def test_limits_inside_let_the_call_through():
    ledger, _ = setup(
        4, at=action_type(limits_decision_key="valve_limits"), decider=ok_limits()
    )
    tool = Valve()
    await run_call(tool, {"valve": "V1", "position": 50})
    assert tool.calls
    assert ledger.only()["limits_result"] == {
        "ok": True,
        "decision_key": "valve_limits",
        "reasons": [],
    }


async def test_kill_switch_wins_over_any_level():
    ledger, _ = setup(4)
    governance.load_for_test(switches=[(T, "tool", "valve", "maintenance")])
    tool = Valve()
    res = await run_call(tool, {"valve": "V1"})
    assert res.is_error and "kill switch" in res.content
    assert tool.calls == [] and ledger.ops == []


async def test_config_change_caps_at_asks_first():
    _, approver = setup(4, g=grant(4, agent_config_hash="old"), hashes={AGENT: "new"})
    tool = Valve()
    await run_call(tool, {"valve": "V1"}, agent_config_hash="new")
    card = approver.bodies[0]["payload"]
    assert card["level"] == 2 and "changed" in card["fallback_reason"]


async def test_paused_grant_asks_first():
    _, approver = setup(4, g=grant(4, state="paused"))
    await run_call(Valve(), {"valve": "V1"})
    assert approver.bodies[0]["payload"]["level"] == 2


async def test_target_outside_scope_asks_first():
    _, approver = setup(4, g=grant(4, scope={"param": "valve", "equals": "V1"}))
    inside = Valve()
    await run_call(inside, {"valve": "V1"})
    assert approver.bodies == [] and inside.calls
    outside = Valve()
    await run_call(outside, {"valve": "V2"})
    card = approver.bodies[0]["payload"]
    assert "outside the scope" in card["fallback_reason"]
    assert outside.calls == [{"valve": "V2"}]


async def test_action_type_match_glob():
    ledger, _ = setup(1, at=action_type(match={"param": "valve", "glob": "controls.*"}))
    a, b = Valve(), Valve()
    await run_call(a, {"valve": "controls.v1"})
    await run_call(b, {"valve": "other"})
    assert a.calls == [] and b.calls == [{"valve": "other"}]
    modes = sorted(r["mode"] for r in ledger.rows().values())
    assert modes == ["unmanaged", "watching"]


async def test_other_agent_is_unmanaged():
    ledger, _ = setup(0)
    tool = Valve()
    await run_call(tool, {"valve": "V1"}, agent_id="someone-else")
    assert tool.calls and ledger.only()["mode"] == "unmanaged"


async def test_tier_approval_is_not_asked_twice():
    _, approver = setup(2)
    governance.load_for_test(policies=[(T, "high", {"tool_call_action": "approval"})])

    class HighValve(Valve):
        risk_tier = "high"

    tool = HighValve()
    rc = governance.RunContext(
        tenant_id=T, execution_id=EXEC, agent_name="Valve bot", agent_id=AGENT
    )
    token = governance.begin_run(rc)
    try:
        await tool.execute({"valve": "V1"})
    finally:
        governance.end_run(token)
    await autonomy.flush()
    assert tool.calls and len(approver.bodies) == 1
    assert approver.bodies[0]["risk_tier"] == "high"
    assert rc.tier == "high"


# wrappers go through the gate once


async def test_defaulted_tool_is_gated_once():
    ledger, _ = setup(4)
    inner = Valve()
    wrapped = _DefaultedTool(inner, defaults={"valve": "V9"})
    await run_call(wrapped, {"position": 3, "_intent": "x"})
    assert inner.calls == [{"position": 3, "valve": "V9"}]
    row = ledger.only()
    assert row["target"] == "V9" and row["mode"] == "reported"


async def test_defaulted_tool_watching_skips_inner():
    setup(1)
    inner = Valve()
    res = await run_call(
        _DefaultedTool(inner, defaults={"valve": "V9"}), {"position": 3}
    )
    assert inner.calls == [] and res.content == autonomy.WATCHING_TEXT


async def test_mcp_tool_is_gated_once():
    from engine.mcp_client import MCPTool, MCPToolResult
    from engine.tool_resolver import MCPToolWrapper

    class Client:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def call_tool(self, name, arguments):
            self.calls.append(dict(arguments))
            return MCPToolResult(content="done")

    ledger, _ = setup()
    client = Client()
    tool = MCPToolWrapper(client, MCPTool("reset", "Reset a device", {}))
    await run_call(tool, {"device": "d1", "_intent": "stuck"})
    assert client.calls == [{"device": "d1"}]
    row = ledger.only()
    assert row["tool_name"] == "reset" and row["intent"] == "stuck"

    ro = MCPToolWrapper(
        client, MCPTool("look", "Look", {}, annotations={"readOnlyHint": True})
    )
    ledger.ops.clear()
    await run_call(ro, {"device": "d1"})
    assert ledger.ops == []


async def test_mcp_tool_watching_skips_the_server():
    from engine.mcp_client import MCPTool
    from engine.tool_resolver import MCPToolWrapper

    class Client:
        calls = 0

        async def call_tool(self, name, arguments):
            Client.calls += 1

    setup(1, at=action_type(tool_name="reset"))
    tool = MCPToolWrapper(Client(), MCPTool("reset", "Reset", {}))
    res = await run_call(tool, {"device": "d1"})
    assert Client.calls == 0 and res.content == autonomy.WATCHING_TEXT


async def test_dynamic_tool_effect_follows_permissions():
    from engine.tools.dynamic_tool import DynamicTool

    quiet = DynamicTool("calc", "", "result = 1")
    loud = DynamicTool("post", "", "result = 1", permissions={"network": True})
    assert autonomy.resolve_effect(quiet, {}) is READ_ONLY
    assert autonomy.resolve_effect(loud, {}).kind == "external"


# what the model sees


def test_description_and_schema_gain_autonomy_inputs_with_a_grant():
    setup(2)
    reg = ToolRegistry()
    reg.register(Valve())
    reg.register(Plain())
    rc = governance.RunContext(tenant_id=T, agent_id=AGENT)
    token = governance.begin_run(rc)
    try:
        tools = {t["name"]: t for t in reg.list_all()}
    finally:
        governance.end_run(token)
    v = tools["valve"]
    assert v["description"].endswith(
        "Autonomy for this action: Asks first. A person approves, edits or rejects, "
        "then it runs. Pass _intent (why) and _prediction {metric,value,low,high} with the call."
    )
    assert "_intent" in v["input_schema"]["properties"]
    assert "_prediction" in v["input_schema"]["properties"]
    assert tools["plain"]["description"] == "No effect"
    assert "_intent" not in tools["plain"]["input_schema"]["properties"]
    # the class schema is untouched
    assert "_intent" not in Valve.input_schema["properties"]


def test_description_unchanged_without_grant_or_run():
    setup(2)
    reg = ToolRegistry()
    reg.register(Valve())
    assert reg.list_all()[0]["description"] == "Set a valve"
    rc = governance.RunContext(tenant_id=T, agent_id="other")
    token = governance.begin_run(rc)
    try:
        assert reg.list_all()[0]["description"] == "Set a valve"
    finally:
        governance.end_run(token)


# runs carry who they act for


def test_agent_run_context_carries_agent_user_and_hash():
    from unittest.mock import MagicMock

    from engine.agent_executor import AgentExecutor

    autonomy.load_for_test([], [], {AGENT: "abc"})
    reg = ToolRegistry()
    reg.run_user_id = USER  # type: ignore[attr-defined]
    ex = AgentExecutor(
        llm_router=MagicMock(), tool_registry=reg, agent_id=AGENT, tenant_id=T
    )
    ctx, parent, token = ex._begin_governed_run()
    try:
        assert ctx.agent_id == AGENT
        assert ctx.user_id == USER
        assert ctx.agent_config_hash == "abc"
    finally:
        governance.end_run(token)
    ex2 = AgentExecutor(
        llm_router=MagicMock(),
        tool_registry=ToolRegistry(),
        agent_id=AGENT,
        user_id="u2",
    )
    ctx2, _, token2 = ex2._begin_governed_run()
    governance.end_run(token2)
    assert ctx2.user_id == "u2"


def test_registry_remembers_the_run_user():
    from engine.agent_executor import build_tool_registry

    reg = build_tool_registry(["calculator"], user_id=USER)
    assert reg.run_user_id == USER


# pipelines


async def _drain_healing() -> None:
    # pipeline runs leave healing writes behind, finish them on this loop
    from engine import healing

    await asyncio.gather(*list(healing._INFLIGHT), return_exceptions=True)


async def test_pipeline_watching_node_output():
    from engine.pipeline import PipelineExecutor, PipelineNode

    ledger, _ = setup(1)
    reg = ToolRegistry()
    tool = Valve()
    reg.register(tool)
    reg.run_user_id = USER  # type: ignore[attr-defined]
    ex = PipelineExecutor(tool_registry=reg, agent_id=AGENT, tenant_id=T)
    result = await ex.execute(
        [
            PipelineNode(
                id="set", tool_name="valve", arguments={"valve": "V1", "position": 7}
            )
        ],
        {"__execution_id": EXEC},
    )
    await autonomy.flush()
    await _drain_healing()
    assert tool.calls == []
    out = result.node_results["set"].output
    assert out["status"] == "watching"
    assert out["proposed"]["arguments"] == {"valve": "V1", "position": 7}
    row = ledger.only()
    assert row["agent_id"] == AGENT and row["user_id"] == USER


async def test_pipeline_unmanaged_node_runs():
    from engine.pipeline import PipelineExecutor, PipelineNode

    ledger, _ = setup()
    reg = ToolRegistry()
    tool = Valve()
    reg.register(tool)
    ex = PipelineExecutor(tool_registry=reg, agent_id=AGENT, tenant_id=T)
    result = await ex.execute(
        [PipelineNode(id="set", tool_name="valve", arguments={"valve": "V1"})]
    )
    await autonomy.flush()
    await _drain_healing()
    assert tool.calls == [{"valve": "V1"}]
    assert result.node_results["set"].output["ok"] is True
    assert ledger.only()["mode"] == "unmanaged"


# snapshot loading


async def test_snapshot_loader_and_missing_tables():
    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return (
            [
                {
                    **action_type(),
                    "match": None,
                    "world_model": json.dumps({"kind": "none"}),
                }
            ],
            [grant(1)],
            {AGENT: "h1"},
        )

    autonomy.configure(loader=loader)
    await autonomy.ensure_fresh()
    assert calls["n"] == 1
    assert autonomy.config_hash(AGENT) == "h1"
    assert autonomy.match_action_type(T, "valve", {})["world_model"] == {"kind": "none"}


# sample plant


async def test_sample_plant_read_and_set(monkeypatch):
    from engine.tools import sample_plant

    monkeypatch.delenv("REDIS_URL", raising=False)
    sample_plant._memory.clear()
    tool = sample_plant.SamplePlantTool()
    rc = governance.RunContext(tenant_id=T)
    token = governance.begin_run(rc)
    try:
        first = json.loads((await tool.execute({"operation": "read"})).content)
        assert set(first) >= {"pressure_bar", "setpoint_bar", "demand", "alarm"}
        res = await tool.execute({"operation": "set_setpoint", "setpoint_bar": 5.2})
        assert json.loads(res.content)["setpoint_bar"] == 5.2
        again = json.loads((await tool.execute({"operation": "read"})).content)
        assert again["setpoint_bar"] == 5.2
        bad = await tool.execute({"operation": "set_setpoint", "setpoint_bar": "x"})
        assert bad.is_error
        assert (await tool.execute({"operation": "open"})).is_error
    finally:
        governance.end_run(token)
    await autonomy.flush()


def test_sample_plant_dynamics_settle_to_setpoint_times_demand():
    from engine.tools import sample_plant

    rng = random.Random(7)
    state = {"setpoint_bar": 4.5, "demand": 1.0, "pressure_bar": 3.0, "updated_at": 0.0}
    state["setpoint_bar"] = 5.0
    s = sample_plant.advance(state, 30.0, rng)
    assert abs(s["pressure_bar"] - sample_plant.settles_to(s)) < 0.1
    # demand drifts so the plant leaves the band sooner or later
    seen = set()
    s = {"setpoint_bar": 4.5, "demand": 1.0, "pressure_bar": 4.5, "updated_at": 0.0}
    for i in range(1, 400):
        s = sample_plant.advance(s, i * 30.0, rng)
        seen.add(sample_plant.alarm(s["pressure_bar"]) is None)
        assert sample_plant.DEMAND_MIN <= s["demand"] <= sample_plant.DEMAND_MAX
    assert seen == {True, False}


def test_sample_plant_is_predictable_from_one_read():
    from engine.tools import sample_plant

    near, inside = 0, 0
    for seed in range(300):
        rng = random.Random(seed)
        demand = rng.uniform(sample_plant.DEMAND_MIN, sample_plant.DEMAND_MAX)
        s = {
            "setpoint_bar": 4.5,
            "demand": demand,
            "pressure_bar": 4.5 * demand,
            "updated_at": 0.0,
        }
        s = sample_plant.advance(s, 120.0, rng)
        read = sample_plant.view(s)
        # what the sample agent does with a read
        setpoint = round(4.5 / read["demand"], 2)
        predicted = setpoint * read["demand"]
        s["setpoint_bar"] = setpoint
        at_30 = sample_plant.advance(s, 150.0, rng)
        at_60 = sample_plant.advance(at_30, 180.0, rng)
        near += abs(at_30["pressure_bar"] - predicted) <= 0.1
        inside += abs(at_60["pressure_bar"] - predicted) <= 0.25
    # the read's note promises 0.1 bar in 30 s, the agent's band is 0.25 bar
    assert near / 300 >= 0.9
    assert inside == 300


async def test_sample_plant_read_says_how_it_responds(monkeypatch):
    from engine.tools import sample_plant

    monkeypatch.delenv("REDIS_URL", raising=False)
    sample_plant._memory.clear()
    tool = sample_plant.SamplePlantTool()
    rc = governance.RunContext(tenant_id=T)
    token = governance.begin_run(rc)
    try:
        read = json.loads((await tool.execute({"operation": "read"})).content)
        assert 0.8 <= read["demand"] <= 1.25
        assert "setpoint_bar x demand" in read["note"]
        assert "30 seconds" in read["note"] and "0.1 bar" in read["note"]
        assert abs(read["pressure_bar"] - read["setpoint_bar"] * read["demand"]) < 0.1
        res = json.loads(
            (
                await tool.execute({"operation": "set_setpoint", "setpoint_bar": 4.0})
            ).content
        )
        said = float(res["message"].split("settles to about ")[1].split(" bar")[0])
        assert abs(said - 4.0 * res["demand"]) < 0.02
    finally:
        governance.end_run(token)
    await autonomy.flush()


def test_sample_plant_effect_and_registration():
    from engine.agent_executor import get_tool_class, list_tool_classes
    from engine.tools.sample_plant import SamplePlantTool

    assert SamplePlantTool.effect_for({"operation": "read"}) is READ_ONLY
    eff = SamplePlantTool.effect_for({"operation": "set_setpoint"})
    assert eff.kind == "control"
    assert SamplePlantTool.risk_tier == "low"
    assert "sample_plant" in list_tool_classes()
    assert get_tool_class("sample_plant") is SamplePlantTool


async def test_sample_plant_set_is_watched_with_a_grant(monkeypatch):
    from engine.tools import sample_plant

    monkeypatch.delenv("REDIS_URL", raising=False)
    sample_plant._memory.clear()
    ledger, _ = setup(
        1,
        at=action_type(
            tool_name="sample_plant",
            key="sample_plant.set_setpoint",
            label="Change the plant pressure setpoint",
        ),
    )
    tool = sample_plant.SamplePlantTool()
    res = await run_call(
        tool,
        {
            "operation": "set_setpoint",
            "setpoint_bar": 4.8,
            "_intent": "pressure low",
            "_prediction": {
                "metric": "pressure_bar",
                "value": 4.5,
                "low": 4.2,
                "high": 4.8,
            },
        },
    )
    assert res.content == autonomy.WATCHING_TEXT
    assert T not in sample_plant._memory
    read = await run_call(tool, {"operation": "read"})
    assert not read.is_error
    assert [r["mode"] for r in ledger.rows().values()] == ["watching"]


# the lint


def _lint_module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "check-tool-config.py"
    spec = importlib.util.spec_from_file_location("check_tool_config", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_tool_config"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_lint_passes_on_the_tree(capsys):
    mod = _lint_module()
    assert mod.main([]) == 0, capsys.readouterr().out


def test_lint_fails_a_medium_tool_without_effect(monkeypatch, capsys):
    mod = _lint_module()

    class Loud(BaseTool):
        name = "loud"
        risk_tier = "medium"

        async def execute(self, arguments):
            return ToolResult(content="")

    real = mod.tool_classes

    def fake():
        found, exempt, failed = real()
        found["engine.tools.fake.Loud"] = Loud
        exempt.add("Loud")
        return found, exempt, failed

    monkeypatch.setattr(mod, "tool_classes", fake)
    assert mod.main([]) == 1
    assert "engine.tools.fake.Loud is medium risk and does not declare effect" in (
        capsys.readouterr().out
    )


# what reaches the stream and the flight recorder


def _router_calling(tool_name: str, args: dict[str, Any]):
    from unittest.mock import MagicMock

    from engine.llm_router import LLMRouter, StreamEvent

    turns = {"n": 0}

    async def complete(**kwargs):
        turns["n"] += 1
        first = turns["n"] == 1

        async def gen():
            if not first:
                yield StreamEvent(event="token", data="done")
            yield StreamEvent(
                event="done",
                data={
                    "model": "claude-sonnet-4-5-20250929",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost": 0.0,
                    "latency_ms": 1,
                    "tool_calls": (
                        [{"id": "tc1", "name": tool_name, "arguments": args}]
                        if first
                        else []
                    ),
                },
            )

        return gen()

    router = LLMRouter()
    provider = MagicMock()
    provider.complete = complete
    router._providers["anthropic"] = provider
    return router


async def _stream(level: int, approver: Approver | None = None):
    from engine.agent_executor import AgentExecutor

    ledger, approver = setup(level, approver=approver)
    reg = ToolRegistry()
    tool = Valve()
    reg.register(tool)
    ex = AgentExecutor(
        llm_router=_router_calling("valve", {"valve": "V1", "position": 4}),
        tool_registry=reg,
        agent_id=AGENT,
        tenant_id=T,
        execution_id=EXEC,
        agent_name="Valve bot",
    )
    events = [e async for e in ex.stream("go")]
    await autonomy.flush()
    return events, tool, ledger, approver


async def test_stream_tool_result_carries_autonomy_and_pending_event():
    events, tool, ledger, approver = await _stream(2)
    names = [e.event for e in events]
    assert "action_pending" in names
    assert names.index("action_pending") < names.index("tool_result")
    pending = next(e for e in events if e.event == "action_pending").data
    assert pending["name"] == "valve"
    assert pending["autonomy"]["status"] == "pending"
    assert pending["autonomy"]["approval_id"] == APPROVAL
    tr = next(e for e in events if e.event == "tool_result").data
    auto = tr["autonomy"]
    for key in (
        "action_id",
        "grant_id",
        "level",
        "level_label",
        "mode",
        "status",
        "approval_id",
        "action_key",
        "action_label",
    ):
        assert key in auto, key
    assert auto["status"] == "executed" and auto["action_key"] == "valve.set"
    assert tool.calls == [{"valve": "V1", "position": 4}]
    trace = next(e for e in events if e.event == "node_trace").data
    assert trace["metadata"]["autonomy"]["action_id"] == auto["action_id"]


async def test_stream_watching_result_and_unmanaged_has_none():
    events, tool, _, _ = await _stream(1)
    tr = next(e for e in events if e.event == "tool_result").data
    assert tr["autonomy"]["status"] == "watching" and tool.calls == []
    assert "action_pending" not in [e.event for e in events]


async def test_invoke_tool_calls_carry_autonomy():
    from engine.agent_executor import _attach_decision_record

    tc: dict[str, Any] = {}
    _attach_decision_record(
        tc, ToolResult(content="", metadata={"autonomy": {"action_id": "a"}})
    )
    assert tc["autonomy"] == {"action_id": "a"}
    plain: dict[str, Any] = {}
    _attach_decision_record(plain, ToolResult(content=""))
    assert "autonomy" not in plain


def test_consumer_copies_autonomy_onto_tool_calls():
    import consumer

    calls = [{"name": "valve"}]
    consumer._merge_tool_trace(
        calls,
        {
            "node_type": "tool_call",
            "tool": "valve",
            "output_preview": "x",
            "duration_ms": 1,
            "metadata": {"autonomy": {"action_id": "a", "status": "watching"}},
        },
    )
    assert calls[0]["autonomy"]["action_id"] == "a"
    entries = consumer._pipeline_tool_calls(
        {
            "set": {
                "tool_name": "valve",
                "output": {"status": "watching"},
                "metadata": {"autonomy": {"action_id": "b"}},
            }
        }
    )
    assert entries[0]["autonomy"]["action_id"] == "b"


async def test_removed_grant_is_unmanaged():
    ledger, _ = setup(0, g=grant(0, state="removed"))
    tool = Valve()
    res = await run_call(tool, {"valve": "V1"})
    assert not res.is_error and tool.calls
    assert ledger.only()["mode"] == "unmanaged"


async def test_sample_action_type_matches_set_setpoint_only():
    from engine.tools import sample_plant

    sample_plant._memory.clear()
    ledger, approver = setup(
        2,
        at=action_type(
            tool_name="sample_plant",
            key="sample_plant.set_setpoint",
            match={"param": "operation", "glob": "set_setpoint"},
            max_band_width=0.2,
            limits_decision_key="sample_plant_limits",
        ),
        decider=ok_limits("setpoint_bar 7.2 is above the 6.0 limit"),
    )
    tool = sample_plant.SamplePlantTool()
    res = await run_call(tool, {"operation": "set_setpoint", "setpoint_bar": 7.2})
    assert res.is_error and "above the 6.0 limit" in res.content
    assert approver.bodies == []
    assert ledger.only()["status"] == "blocked"


def test_limit_facts_read_a_json_text_payload():
    facts = autonomy.limit_facts(
        {"topic": "controls.b", "payload": '{"mw": 200, "soc_pct": 70}', "qos": 0},
        "controls.b",
    )
    assert facts["payload"] == {"mw": 200, "soc_pct": 70}
    assert facts["target"] == "controls.b" and facts["qos"] == 0


def test_limit_facts_keep_text_that_is_not_an_object():
    facts = autonomy.limit_facts({"payload": "{not json", "note": "[1, 2]"}, None)
    assert facts == {"payload": "{not json", "note": "[1, 2]"}


async def test_limits_see_inside_a_json_text_payload():
    decide = ok_limits("mw 200 is above 50")
    setup(2, at=action_type(limits_decision_key="valve_limits"), decider=decide)
    tool = Valve()
    res = await run_call(tool, {"valve": "V1", "payload": '{"mw": 200}'})
    assert res.is_error and tool.calls == []
    assert decide.facts["payload"] == {"mw": 200}


async def test_pipeline_card_uses_the_name_people_gave_it():
    ledger, approver = setup(
        2,
        g=grant(2, agent_name="Battery dispatch flow"),
        approver=Approver({"status": "approved", "signoffs": []}),
    )
    await run_call(Valve(), {"valve": "V1", "position": 40})
    body = approver.bodies[0]
    assert body["title"].startswith("Battery dispatch flow wants to")
    assert body["payload"]["agent"]["name"] == "Battery dispatch flow"
    assert ledger.ops[0][1]["agent_name"] == "Battery dispatch flow"
