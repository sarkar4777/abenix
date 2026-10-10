"""Decisions 2.5.7 follow-ups: gates left by ended runs, permission changes reaching every worker,
settled approvals scoped to the viewer, honest Needs you alerts and plural wording."""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core import capabilities as caps
from app.core import hitl
from app.routers import approvals as approvals_router
from app.routers import decisions as D
from app.routers import inbox
from app.schemas.connectors import ApprovalSignoffRequest
from models.approval import Approval, ApprovalStatus
from models.user import UserRole


def _user(role=UserRole.ADMIN, created_at=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=role,
        email="x@example.com",
        full_name="X",
        created_at=created_at,
    )


class _Redis:
    def __init__(self):
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def srem(self, key, member):
        self.sets.get(key, set()).discard(member)

    async def get(self, key):
        return self.kv.get(key)

    async def exists(self, key):
        return 1 if key in self.kv else 0


def _gate(r, tenant, execution, age, waiting):
    data = {
        "execution_id": execution,
        "gate_id": "gate-1",
        "tenant_id": tenant,
        "requested_at": time.time() - age,
        "expires_at": time.time() + 3600,
    }
    r.sets.setdefault(hitl.pending_key(tenant), set()).add(json.dumps(data))
    if waiting:
        r.kv[hitl.waiting_key(execution)] = "1"


# 1. a gate whose run ended is not shown and cannot be answered


@pytest.mark.asyncio
async def test_a_gate_whose_run_stopped_waiting_is_dropped():
    r = _Redis()
    _gate(r, "t", "ended", age=120, waiting=False)
    _gate(r, "t", "live", age=120, waiting=True)
    _gate(r, "t", "fresh", age=1, waiting=False)
    with patch.object(hitl, "get_redis", AsyncMock(return_value=r)):
        listed = {g["execution_id"] for g in await hitl.list_pending_hitl("t")}
    assert listed == {"live", "fresh"}
    assert not any("ended" in m for m in r.sets[hitl.pending_key("t")])


@pytest.mark.asyncio
async def test_answering_a_closed_gate_says_so():
    user = _user()
    ex = SimpleNamespace(id=uuid.uuid4(), tenant_id=user.tenant_id, user_id=uuid.uuid4(), status="running")
    body = ApprovalSignoffRequest(decision="deny", reason="Over the refund limit")
    with (
        patch.object(approvals_router, "_hitl_execution", AsyncMock(return_value=ex)),
        patch.object(approvals_router, "_hitl_history_row", AsyncMock(return_value=None)),
        patch.object(approvals_router, "get_pending_hitl", AsyncMock(return_value=None)),
    ):
        r = await approvals_router._sign_off_hitl(None, user, str(ex.id), "gate-1", body)
    assert r.status_code == 409 and json.loads(r.body)["error"]["error_code"] == "GATE_CLOSED"
    ex.status = SimpleNamespace(value="failed")
    with (
        patch.object(approvals_router, "_hitl_execution", AsyncMock(return_value=ex)),
        patch.object(approvals_router, "_hitl_history_row", AsyncMock(return_value=None)),
        patch.object(approvals_router, "get_pending_hitl", AsyncMock(return_value={"gate_id": "gate-1"})),
    ):
        r = await approvals_router._sign_off_hitl(None, user, str(ex.id), "gate-1", body)
    body_json = json.loads(r.body)
    assert r.status_code == 409 and "already failed" in body_json["error"]["message"]


@pytest.mark.asyncio
async def test_a_deny_with_a_reason_is_written_to_the_gate():
    user = _user()
    ex = SimpleNamespace(id=uuid.uuid4(), tenant_id=user.tenant_id, user_id=uuid.uuid4(), agent_id=None, status="running")
    body = ApprovalSignoffRequest(decision="deny", reason="Over the refund limit")

    class Db:
        def add(self, o):
            o.id = uuid.uuid4()

        async def commit(self):
            return None

        async def refresh(self, o):
            return None

    with (
        patch.object(approvals_router, "_hitl_execution", AsyncMock(return_value=ex)),
        patch.object(approvals_router, "_hitl_history_row", AsyncMock(return_value=None)),
        patch.object(approvals_router, "get_pending_hitl", AsyncMock(return_value={"gate_id": "gate-1", "action": "Refund"})),
        patch.object(approvals_router, "approver_denial", AsyncMock(return_value=None)),
        patch.object(approvals_router, "write_hitl_decision", AsyncMock(return_value=True)) as write,
        patch.object(approvals_router, "_notify_resolved", AsyncMock()),
    ):
        r = await approvals_router.sign_off(f"hitl:{ex.id}:gate-1", body, user, Db())
    assert r.status_code == 200
    kw = write.call_args.kwargs
    assert kw["decision"] == "rejected" and kw["comment"] == "Over the refund limit"


# 2. a permission change reaches every worker at once


def test_invalidate_clears_here_and_tells_the_other_workers():
    uid = uuid.uuid4()
    caps._cache[uid] = (time.monotonic(), frozenset({"x"}))
    before = caps._gen
    with patch.object(caps, "_publish", AsyncMock()) as pub:

        async def go():
            caps.invalidate(uid)
            await asyncio.sleep(0)

        asyncio.run(go())
    assert uid not in caps._cache and caps._gen > before
    pub.assert_awaited_once_with(uid)


def test_a_message_from_another_worker_drops_the_entry():
    uid = uuid.uuid4()
    caps._cache[uid] = (time.monotonic(), frozenset({"x"}))
    caps._drop(caps._parse(str(uid)))
    assert uid not in caps._cache
    other = uuid.uuid4()
    caps._cache[other] = (time.monotonic(), frozenset())
    caps._drop(caps._parse("*"))
    assert caps._cache == {}


@pytest.mark.asyncio
async def test_a_read_racing_a_change_is_not_kept():
    u = _user(role=UserRole.USER)

    class Db:
        async def execute(self, stmt):
            caps._drop(u.id)
            return SimpleNamespace(all=lambda: [])

    await caps._load(Db(), u)
    assert u.id not in caps._cache


def test_every_worker_listens_and_role_changes_invalidate():
    from app import main
    from app.routers import team

    assert "start_listener()" in inspect.getsource(main.on_startup)
    assert "caps.invalidate(member.id)" in inspect.getsource(team.update_member_role)
    assert "caps.invalidate(member.id)" in inspect.getsource(team.remove_member)


# 3. settled approvals for the people they concern


def _approval(status, requested_by=None, signoffs=None, created=None):
    return Approval(
        id=uuid.uuid4(),
        status=status,
        requested_by=requested_by or uuid.uuid4(),
        signoffs=signoffs or [],
        gate_kind="human_approval",
        created_at=created or dt.datetime.now(dt.timezone.utc),
    )


def test_settled_rows_from_before_you_joined_are_not_yours():
    joined = dt.datetime.now(dt.timezone.utc)
    me = _user(role=UserRole.USER, created_at=joined)
    old = _approval(ApprovalStatus.approved, created=joined - dt.timedelta(days=3))
    assert approvals_router._visible_row(me, old, None) is False
    later = _approval(ApprovalStatus.approved, created=joined + dt.timedelta(minutes=5))
    assert approvals_router._visible_row(me, later, None) is True
    mine = _approval(ApprovalStatus.denied, requested_by=me.id, created=joined - dt.timedelta(days=3))
    assert approvals_router._visible_row(me, mine, ("NOT_SIGNER", "x")) is True
    signed = _approval(ApprovalStatus.approved, signoffs=[{"user_id": str(me.id)}], created=joined - dt.timedelta(days=3))
    assert approvals_router._visible_row(me, signed, ("ALREADY_SIGNED", "x")) is True
    never = _approval(ApprovalStatus.approved, created=joined + dt.timedelta(minutes=5))
    assert approvals_router._visible_row(me, never, ("NOT_SIGNER", "x")) is False
    waiting = _approval(ApprovalStatus.pending, created=joined - dt.timedelta(days=3))
    assert approvals_router._visible_row(me, waiting, None) is True


# 4. Needs you alerts are about your own runs unless you see everyone's


def test_alerts_for_a_member_are_their_own_failures():
    assert inbox._own_runs(_user(role=UserRole.ADMIN)) == []
    clause = inbox._own_runs(_user(role=UserRole.USER))
    assert len(clause) == 1 and "executions.user_id" in str(clause[0])
    assert "_own_runs(user)" in inspect.getsource(inbox.rising_failures)


# 5. plural wording


def test_summary_wording_agrees_with_the_count():
    one_ok = D._summary([], [], [], [], [], 1)
    assert one_ok == "Ready. 1 golden test passes."
    assert D._summary([], [], [], [], [], 3) == "Ready. 3 golden tests pass."
    assert D._summary([], [], [], [], [], 0) == "Ready. There are no golden tests yet."
    assert D._summary([], [{"x": 1}], [], [], [], 1) == "The golden test fails."
    assert D._summary([], [{"x": 1}], [], [], [], 4) == "1 of 4 golden tests fails."
    assert D._summary([], [{}, {}], [], [], [], 4) == "2 of 4 golden tests fail."
    assert "1 pair of rules disagrees" in D._summary([], [], [{"kind": "conflict"}], [], [], 2)
    assert "1 result changes" in D._summary([], [], [], [], [{}], 2)
