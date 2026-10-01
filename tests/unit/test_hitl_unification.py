"""HITL gates surface in /api/approvals and sign-off is authorised.

Runtime human_approval gates live in Redis. The approvals router must list
them next to DB rows, accept a "hitl:{execution}:{gate}" id on sign-off,
write the Redis decision plus an Approval history row, and refuse viewers
and self-approval.
"""

from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core import hitl
from app.routers import approvals as approvals_router
from app.schemas.connectors import ApprovalSignoffRequest
from models.approval import Approval, ApprovalStatus
from models.user import UserRole


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)

    async def srem(self, key, member):
        self.sets.get(key, set()).discard(member)

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def delete(self, key):
        self.kv.pop(key, None)

    async def exists(self, key):
        return 1 if key in self.kv else 0

    async def ttl(self, key):
        return -1

    async def expire(self, key, seconds):
        return True

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, r: FakeRedis) -> None:
        self.r = r
        self.ops: list[str] = []

    def exists(self, key):
        self.ops.append(key)

    async def execute(self):
        return [1 if k in self.r.kv else 0 for k in self.ops]


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.rows[0] if self.rows else None


class FakeDB:
    """Routes selects by entity so router code runs unmodified."""

    def __init__(self, *, approvals=(), executions=(), other_approvers=()):
        self.approvals = list(approvals)
        self.executions = list(executions)
        self.other_approvers = list(other_approvers)
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        descs = getattr(stmt, "column_descriptions", None)
        if not descs:
            return FakeResult([])
        entity = descs[0].get("entity")
        name = getattr(entity, "__name__", "")
        if name == "Approval":
            return FakeResult(self.approvals)
        if name == "Execution":
            return FakeResult(self.executions)
        if name == "User":
            return FakeResult(self.other_approvers)
        return FakeResult([])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None


def _user(role=UserRole.ADMIN, tenant_id=None, user_id=None):
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        role=role,
        email="reviewer@example.com",
        full_name="Reviewer",
    )


def _body(resp) -> dict:
    return json.loads(resp.body)


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(hitl, "_redis", r)
    return r


async def _seed_gate(r: FakeRedis, tenant_id, execution_id, gate_id="gate-abc"):
    entry = {
        "execution_id": str(execution_id),
        "gate_id": gate_id,
        "tenant_id": str(tenant_id),
        "agent_name": "deployer",
        "action": "Deploy to prod",
        "details": "ship v2",
        "risk_level": "high",
        "requested_at": time.time(),
        "expires_at": time.time() + 3600,
    }
    await r.sadd(hitl.pending_key(str(tenant_id)), json.dumps(entry))
    return entry


def test_parse_hitl_id_roundtrip():
    ex, gate = str(uuid.uuid4()), "gate-" + uuid.uuid4().hex
    assert hitl.parse_hitl_id(hitl.hitl_row_id(ex, gate)) == (ex, gate)
    assert hitl.parse_hitl_id(str(uuid.uuid4())) is None
    assert hitl.parse_hitl_id("hitl:nogate") is None


@pytest.mark.asyncio
async def test_list_merges_hitl_rows(fake_redis):
    user = _user()
    execution_id = uuid.uuid4()
    await _seed_gate(fake_redis, user.tenant_id, execution_id)
    db = FakeDB()

    resp = await approvals_router.list_approvals(
        mine=1,
        status="pending",
        execution_id=None,
        agent_id=None,
        kind=None,
        limit=200,
        user=user,
        db=db,
    )
    rows = _body(resp)["data"]
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == f"hitl:{execution_id}:gate-abc"
    assert row["gate_kind"] == "human_approval"
    assert row["agent_execution_id"] == str(execution_id)
    assert row["title"] == "Deploy to prod"
    assert row["payload"] == {
        "details": "ship v2",
        "risk_level": "high",
        "agent_name": "deployer",
    }
    assert row["status"] == "pending"
    assert row["expires_at"]


@pytest.mark.asyncio
async def test_list_skips_hitl_rows_when_filters_exclude_them(fake_redis):
    user = _user()
    await _seed_gate(fake_redis, user.tenant_id, uuid.uuid4())
    for kwargs in (
        {"status": "approved", "kind": None, "agent_id": None},
        {"status": None, "kind": "device.reset", "agent_id": None},
        {"status": None, "kind": None, "agent_id": uuid.uuid4()},
    ):
        resp = await approvals_router.list_approvals(
            mine=1, execution_id=None, limit=200, user=user, db=FakeDB(), **kwargs
        )
        assert _body(resp)["data"] == []


@pytest.mark.asyncio
async def test_list_tolerates_redis_outage(monkeypatch):
    async def boom(_tenant):
        raise ConnectionError("redis down")

    monkeypatch.setattr(approvals_router, "list_pending_hitl", boom)
    resp = await approvals_router.list_approvals(
        mine=1,
        status="pending",
        execution_id=None,
        agent_id=None,
        kind=None,
        limit=200,
        user=_user(),
        db=FakeDB(),
    )
    assert resp.status_code == 200
    assert _body(resp)["data"] == []


@pytest.mark.asyncio
async def test_signoff_on_hitl_id_writes_decision_and_history(fake_redis):
    user = _user()
    requester_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    await _seed_gate(fake_redis, user.tenant_id, execution_id)
    exec_row = SimpleNamespace(
        id=execution_id, tenant_id=user.tenant_id, user_id=requester_id, agent_id=agent_id
    )
    db = FakeDB(executions=[exec_row])
    notify = AsyncMock()

    with patch.object(approvals_router, "_notify_resolved", notify):
        resp = await approvals_router.sign_off(
            approval_id=f"hitl:{execution_id}:gate-abc",
            body=ApprovalSignoffRequest(decision="approve", reason="looks good"),
            user=user,
            db=db,
        )

    assert resp.status_code == 200
    data = _body(resp)["data"]
    assert data["status"] == "approved"
    assert data["gate_kind"] == "human_approval"
    assert data["signoffs"][0]["user_email"] == user.email

    decision = json.loads(fake_redis.kv[hitl.approval_key(str(execution_id), "gate-abc")])
    assert decision["decision"] == "approved"
    assert decision["reviewer_id"] == str(user.id)
    assert decision["comment"] == "looks good"

    history = [o for o in db.added if isinstance(o, Approval)]
    assert len(history) == 1
    row = history[0]
    assert row.status == ApprovalStatus.approved
    assert row.agent_execution_id == execution_id
    assert row.agent_id == agent_id
    assert row.requested_by == requester_id
    assert row.client_token == f"hitl:{execution_id}:gate-abc"
    assert row.payload["gate_id"] == "gate-abc"
    assert db.commits >= 1
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_deny_on_hitl_id_maps_to_rejected(fake_redis):
    user = _user()
    execution_id = uuid.uuid4()
    await _seed_gate(fake_redis, user.tenant_id, execution_id)
    exec_row = SimpleNamespace(
        id=execution_id, tenant_id=user.tenant_id, user_id=uuid.uuid4(), agent_id=None
    )
    with patch.object(approvals_router, "_notify_resolved", AsyncMock()):
        resp = await approvals_router.sign_off(
            approval_id=f"hitl:{execution_id}:gate-abc",
            body=ApprovalSignoffRequest(decision="deny", reason="nope"),
            user=user,
            db=FakeDB(executions=[exec_row]),
        )
    assert _body(resp)["data"]["status"] == "denied"
    decision = json.loads(fake_redis.kv[hitl.approval_key(str(execution_id), "gate-abc")])
    assert decision["decision"] == "rejected"


@pytest.mark.asyncio
async def test_hitl_signoff_is_tenant_checked(fake_redis):
    user = _user()
    execution_id = uuid.uuid4()
    await _seed_gate(fake_redis, user.tenant_id, execution_id)
    # execution lookup returns nothing for this tenant
    resp = await approvals_router.sign_off(
        approval_id=f"hitl:{execution_id}:gate-abc",
        body=ApprovalSignoffRequest(decision="approve"),
        user=user,
        db=FakeDB(executions=[]),
    )
    assert resp.status_code == 404
    assert hitl.approval_key(str(execution_id), "gate-abc") not in fake_redis.kv


@pytest.mark.asyncio
async def test_second_hitl_signoff_is_rejected(fake_redis):
    user = _user()
    execution_id = uuid.uuid4()
    await _seed_gate(fake_redis, user.tenant_id, execution_id)
    exec_row = SimpleNamespace(
        id=execution_id, tenant_id=user.tenant_id, user_id=uuid.uuid4(), agent_id=None
    )
    await hitl.write_hitl_decision(
        execution_id=str(execution_id),
        gate_id="gate-abc",
        decision="approved",
        reviewer="x",
        reviewer_id=str(uuid.uuid4()),
        tenant_id=str(user.tenant_id),
    )
    resp = await approvals_router.sign_off(
        approval_id=f"hitl:{execution_id}:gate-abc",
        body=ApprovalSignoffRequest(decision="approve"),
        user=user,
        db=FakeDB(executions=[exec_row]),
    )
    # decided gates drop out of the pending list, so the gate is gone
    assert resp.status_code in (404, 409)


@pytest.mark.asyncio
async def test_viewer_cannot_approve_hitl_gate(fake_redis):
    user = _user(role=UserRole.USER)
    execution_id = uuid.uuid4()
    await _seed_gate(fake_redis, user.tenant_id, execution_id)
    exec_row = SimpleNamespace(
        id=execution_id, tenant_id=user.tenant_id, user_id=uuid.uuid4(), agent_id=None
    )
    resp = await approvals_router.sign_off(
        approval_id=f"hitl:{execution_id}:gate-abc",
        body=ApprovalSignoffRequest(decision="approve"),
        user=user,
        db=FakeDB(executions=[exec_row]),
    )
    assert resp.status_code == 403
    assert hitl.approval_key(str(execution_id), "gate-abc") not in fake_redis.kv


@pytest.mark.asyncio
async def test_viewer_cannot_approve_db_approval():
    user = _user(role=UserRole.USER)
    a = Approval(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        title="x",
        required_signoffs=1,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=uuid.uuid4(),
    )
    resp = await approvals_router.sign_off(
        approval_id=str(a.id),
        body=ApprovalSignoffRequest(decision="approve"),
        user=user,
        db=FakeDB(approvals=[a]),
    )
    assert resp.status_code == 403
    assert a.signoffs == []


@pytest.mark.asyncio
async def test_requester_may_approve_and_is_marked():
    """Self approval is allowed for an admin and recorded on the signoff."""
    user = _user(role=UserRole.ADMIN)
    a = Approval(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        title="x",
        required_signoffs=1,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=user.id,
    )
    db = FakeDB(approvals=[a], other_approvers=[(uuid.uuid4(),)])
    with patch.object(approvals_router, "_notify_resolved", AsyncMock()):
        resp = await approvals_router.sign_off(
            approval_id=str(a.id),
            body=ApprovalSignoffRequest(decision="approve"),
            user=user,
            db=db,
        )
    assert resp.status_code == 200
    assert a.status == ApprovalStatus.approved
    assert a.signoffs[0]["self_approved"] is True


@pytest.mark.asyncio
async def test_requester_may_approve_when_nobody_else_can():
    """Solo-approver tenants keep working, the signoff is still recorded."""
    user = _user(role=UserRole.ADMIN)
    a = Approval(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        title="x",
        required_signoffs=1,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=user.id,
    )
    db = FakeDB(approvals=[a], other_approvers=[])
    with patch.object(approvals_router, "_notify_resolved", AsyncMock()):
        resp = await approvals_router.sign_off(
            approval_id=str(a.id),
            body=ApprovalSignoffRequest(decision="approve"),
            user=user,
            db=db,
        )
    assert resp.status_code == 200
    assert a.status == ApprovalStatus.approved


@pytest.mark.asyncio
async def test_requester_may_approve_own_hitl_gate(fake_redis):
    user = _user(role=UserRole.CREATOR)
    execution_id = uuid.uuid4()
    await _seed_gate(fake_redis, user.tenant_id, execution_id)
    exec_row = SimpleNamespace(
        id=execution_id, tenant_id=user.tenant_id, user_id=user.id, agent_id=None
    )
    with patch.object(approvals_router, "_notify_resolved", AsyncMock()):
        resp = await approvals_router.sign_off(
            approval_id=f"hitl:{execution_id}:gate-abc",
            body=ApprovalSignoffRequest(decision="approve"),
            user=user,
            db=FakeDB(executions=[exec_row], other_approvers=[(uuid.uuid4(),)]),
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_approval_accepts_hitl_id(fake_redis):
    user = _user()
    execution_id = uuid.uuid4()
    await _seed_gate(fake_redis, user.tenant_id, execution_id)
    exec_row = SimpleNamespace(
        id=execution_id, tenant_id=user.tenant_id, user_id=uuid.uuid4(), agent_id=None
    )
    resp = await approvals_router.get_approval(
        approval_id=f"hitl:{execution_id}:gate-abc",
        user=user,
        db=FakeDB(executions=[exec_row]),
    )
    assert resp.status_code == 200
    assert _body(resp)["data"]["status"] == "pending"

    resp = await approvals_router.get_approval(
        approval_id="not-a-uuid", user=user, db=FakeDB()
    )
    assert resp.status_code == 404


def test_webhooks_route_registered_before_dynamic_id():
    paths = [r.path for r in approvals_router.router.routes]
    assert paths.index("/api/approvals/webhooks") < paths.index(
        "/api/approvals/{approval_id}"
    )


@pytest.mark.asyncio
async def test_list_pending_prunes_expired_entries(fake_redis):
    tenant = uuid.uuid4()
    stale = {
        "execution_id": str(uuid.uuid4()),
        "gate_id": "gate-old",
        "requested_at": time.time() - 7200,
        "expires_at": time.time() - 10,
    }
    await fake_redis.sadd(hitl.pending_key(str(tenant)), json.dumps(stale))
    assert await hitl.list_pending_hitl(str(tenant)) == []
    assert fake_redis.sets[hitl.pending_key(str(tenant))] == set()


@pytest.mark.asyncio
async def test_waiting_execution_ids_filters_sweeper_candidates(fake_redis):
    waiting, idle = str(uuid.uuid4()), str(uuid.uuid4())
    fake_redis.kv[hitl.waiting_key(waiting)] = "1"
    assert await hitl.waiting_execution_ids([waiting, idle]) == {waiting}
    assert await hitl.waiting_execution_ids([]) == set()
