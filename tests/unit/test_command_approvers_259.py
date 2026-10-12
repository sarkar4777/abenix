"""Machine command approvals: the requester and every operator or admin may approve."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core import approvers as A
from app.routers import approvals as R
from models.approval import Approval, ApprovalStatus

OPS = frozenset({"telemetry.view", "telemetry.command"})
MEMBER = frozenset({"telemetry.view"})
ADMIN = frozenset({"*"})
CREATOR = frozenset({"approvals.sign", "agents.create"})


def _u(name, role="user"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        full_name=name,
        email=f"{name.lower()}@x.dev",
        role=role,
    )


def test_can_sign_command_needs_only_the_command_right():
    assert A.can_sign("user", OPS, None, "telemetry.command")
    assert A.can_sign(
        "admin", ADMIN, {"capability": "approvals.sign"}, "telemetry.command"
    )
    assert not A.can_sign("creator", CREATOR, None, "telemetry.command")
    assert not A.can_sign("user", MEMBER, None, "telemetry.command")


def test_command_approvers_lists_requester_first():
    me, ana, raj, bob = _u("Zed"), _u("Ana"), _u("Raj", "admin"), _u("Bob")
    people = [(ana, OPS), (raj, ADMIN), (bob, MEMBER), (me, OPS)]
    out, self_ok = A.command_approvers(people, None, me.id)
    assert self_ok is True
    assert [p["name"] for p in out] == ["Zed", "Ana", "Raj"]
    assert out[0]["is_requester"] is True
    assert not any(p["is_requester"] for p in out[1:])


def test_requester_without_the_right_cannot_self_approve():
    me, ana = _u("Me"), _u("Ana")
    out, self_ok = A.command_approvers([(me, MEMBER), (ana, OPS)], None, me.id)
    assert self_ok is False and [p["name"] for p in out] == ["Ana"]


def test_tier_separation_of_duties_still_holds():
    me, ana = _u("Me"), _u("Ana")
    out, self_ok = A.command_approvers(
        [(me, OPS), (ana, OPS)], {"exclude_requester": True}, me.id
    )
    assert self_ok is False and [p["name"] for p in out] == ["Ana"]


def test_sign_check_for_commands():
    me = _u("Me")
    kw = dict(policy=None, gate_kind="telemetry.command", signoffs=[])
    assert A.sign_check(me, OPS, requested_by=me.id, **kw) is None
    code, words = A.sign_check(me, MEMBER, requested_by=None, **kw)
    assert code == "MISSING_PERMISSION" and "Machine operators" in words
    # an operator who is a Member, no approvals.sign, may approve
    assert A.sign_check(_u("Ana"), OPS, requested_by=me.id, **kw) is None


@pytest.mark.asyncio
async def test_approver_denial_lets_requester_and_operators_approve(monkeypatch):
    from app.core import capabilities, hitl

    grants = {}

    async def has(db, user, cap):
        return capabilities.holds(grants[user.id], cap)

    monkeypatch.setattr(capabilities, "has_capability", has)
    me, member = _u("Me"), _u("Mo")
    grants[me.id] = OPS
    grants[member.id] = MEMBER
    pol = {"capability": "approvals.sign", "exclude_requester": False}
    assert await hitl.approver_denial(None, me, me.id, pol, "telemetry.command") is None
    refused = await hitl.approver_denial(None, member, me.id, None, "telemetry.command")
    assert refused is not None and refused.capability == "telemetry.command"


def _approval(requester, kind="telemetry.command"):
    return Approval(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        title="Set hold on press 4",
        payload={},
        required_signoffs=1,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=requester.id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        gate_kind=kind,
        policy=None,
    )


def test_list_rows_carry_approvers_and_self_approve():
    me, ana = _u("Me"), _u("Ana")
    a = _approval(me)
    people = [(me, OPS), (ana, OPS)]
    out, self_ok = R._approvers_of(a, people, [ana], (me, OPS), False)
    assert self_ok is True
    assert out == [
        {"id": str(me.id), "name": "Me", "is_requester": True},
        {"id": str(ana.id), "name": "Ana", "is_requester": False},
    ]


def test_other_kinds_list_the_eligible_and_the_requester_when_allowed():
    me, ana = _u("Me", "admin"), _u("Ana", "admin")
    a = _approval(me, kind="human_approval")
    out, self_ok = R._approvers_of(a, [], [ana], (me, ADMIN), False)
    assert self_ok is True and out[0]["is_requester"] and out[1]["name"] == "Ana"
    a.policy = {"capability": "approvals.sign", "exclude_requester": True}
    out, self_ok = R._approvers_of(a, [], [ana], (me, ADMIN), False)
    assert self_ok is False and [p["name"] for p in out] == ["Ana"]


class _Res:
    def __init__(self, a):
        self.a = a

    def scalar_one_or_none(self):
        return self.a


class _DB:
    def __init__(self, a):
        self.a = a
        self.commits = 0

    async def execute(self, stmt, params=None):
        return _Res(self.a)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None


@pytest.mark.asyncio
async def test_requester_approval_is_audited_as_approved_by_the_requester(monkeypatch):
    from app.core import audit
    from app.schemas.connectors import ApprovalSignoffRequest
    from app.services import events

    me = _u("Me")
    a = _approval(me)
    db = _DB(a)
    logged = AsyncMock()
    monkeypatch.setattr(audit, "log_action", logged)
    monkeypatch.setattr(R, "approver_denial", AsyncMock(return_value=None))
    monkeypatch.setattr(R, "wake_waiters", AsyncMock())
    monkeypatch.setattr(events, "emit", AsyncMock())
    monkeypatch.setattr(R, "_autonomy_resolved", AsyncMock())
    monkeypatch.setattr(R, "_notify_resolved", AsyncMock())
    monkeypatch.setattr(R, "_serialize_one", AsyncMock(return_value={"ok": True}))
    # no reason asked of the requester for a machine command
    resp = await R.sign_off(
        str(a.id), ApprovalSignoffRequest(decision="approve"), me, db
    )
    assert resp.status_code == 200, json.loads(resp.body)
    assert a.status == ApprovalStatus.approved
    rec = a.signoffs[0]
    assert rec["approved_by_requester"] is True and rec["self_approved"] is True
    action = logged.await_args_list[0].args[3]
    assert action == "approval.approved_by_requester"
    assert logged.await_args_list[0].args[4]["note"] == "approved by the requester"


@pytest.mark.asyncio
async def test_pending_command_notifies_every_operator_and_the_requester(monkeypatch):
    me, ana, raj, bob = _u("Me"), _u("Ana"), _u("Raj", "admin"), _u("Bob")
    a = _approval(me)
    people = [(me, OPS), (ana, OPS), (raj, ADMIN), (bob, MEMBER)]
    monkeypatch.setattr(R, "tenant_people", AsyncMock(return_value=people))
    sent = AsyncMock()
    monkeypatch.setattr(R, "create_notification", sent)
    monkeypatch.setattr(R, "_tenant_settings", AsyncMock(return_value={}))
    monkeypatch.setattr(R, "_post_webhook", AsyncMock())
    from app.core import notifications

    monkeypatch.setattr(notifications, "post_once_to_tenant_slack", AsyncMock())
    db = _DB(a)
    await R._notify_pending(db, a, requester=me)
    told = {c.kwargs["user_id"] for c in sent.await_args_list}
    assert told == {me.id, ana.id, raj.id}


# gap 5: chat hears the wait and the deny


def _command_ctx(monkeypatch):
    from engine.tools import _telemetry_api as api

    monkeypatch.setattr(
        api,
        "run_info",
        lambda: {
            "tenant": str(uuid.uuid4()),
            "user_id": "u1",
            "agent_id": "a1",
            "execution_id": "e1",
            "agent_name": "W",
        },
    )
    return api


def test_device_command_streams_waiting_then_denied_with_reason(monkeypatch):
    import asyncio

    from engine import autonomy
    from engine.tools import device_command as D

    api = _command_ctx(monkeypatch)

    async def propose(method, path, *, params=None, body=None, timeout=20):
        return (
            200,
            {
                "needs_approval": True,
                "approval": {"id": "ap1", "link": "/approvals?id=ap1"},
            },
            "",
        )

    async def denied(aid, limit, eid):
        return {
            "status": "denied",
            "signoffs": [
                {
                    "decision": "deny",
                    "user_name": "Ops Lead",
                    "reason": "Crew on the boom.",
                }
            ],
        }

    monkeypatch.setattr(api, "call", propose)
    monkeypatch.setattr(D, "wait_for", denied)
    monkeypatch.setattr(D, "_progress", AsyncMock())
    args = {
        "asset": "g/ex1",
        "signal": "Mode/Set",
        "value": "safe",
        "reason": "why not",
    }

    async def go():
        seen = []
        async for ev, data in autonomy.stream_call(D.DeviceCommandTool().execute(args)):
            seen.append((ev, data))
        return seen

    seen = asyncio.run(go())
    statuses = [d for e, d in seen if e == "tool_status"]
    assert (
        statuses[0]["status"] == "waiting_approval"
        and statuses[0]["approval_id"] == "ap1"
    )
    assert statuses[0]["name"] == "device_command" and statuses[0]["message"]
    assert statuses[-1]["status"] == "denied"
    result = seen[-1][1]
    assert result.metadata["status"] == "denied"
    assert result.metadata["reason"] == "Crew on the boom"
    assert D.DeviceCommandTool.streams_status is True


def test_executor_streams_status_tools_and_passes_deny_metadata():
    import inspect

    from engine import agent_executor

    src = inspect.getsource(agent_executor)
    assert 'getattr(tool, "streams_status", False) or autonomy.managed(' in src
    assert '_md.get("status") in ("denied", "expired")' in src


def test_inprocess_chat_forwards_tool_status():
    import inspect

    from app.routers import agents

    assert 'elif event_type == "tool_status":' in inspect.getsource(agents)


def test_tool_status_survives_the_tool_config_wrapper(monkeypatch):
    """The agent's command policy lives in parameter_defaults, so the real tool is wrapped."""
    import asyncio

    from engine import autonomy
    from engine.tools import device_command as D
    from engine.tools.base import ToolRegistry

    api = _command_ctx(monkeypatch)

    async def propose(method, path, *, params=None, body=None, timeout=20):
        return 200, {"needs_approval": True, "approval": {"id": "ap9"}}, ""

    async def expired(aid, limit, eid):
        return {"status": "expired", "signoffs": []}

    monkeypatch.setattr(api, "call", propose)
    monkeypatch.setattr(D, "wait_for", expired)
    monkeypatch.setattr(D, "_progress", AsyncMock())
    reg = ToolRegistry()
    reg.register(D.DeviceCommandTool())
    reg.apply_tool_config(
        {"device_command": {"parameter_defaults": {"policy": {"approval": "always"}}}}
    )
    tool = reg.get("device_command")
    assert type(tool).__name__ == "_DefaultedTool"
    assert tool.streams_status is True
    args = {
        "asset": "g/ex1",
        "signal": "Mode/Set",
        "value": "safe",
        "reason": "why not",
    }

    async def go():
        return [x async for x in autonomy.stream_call(tool.execute(args))]

    seen = asyncio.run(go())
    statuses = [d["status"] for e, d in seen if e == "tool_status"]
    assert statuses == ["waiting_approval", "expired"]
    assert seen[-1][1].metadata["status"] == "expired"
