"""POST /api/triggers/{id}/run: tenant scoped, owner or admin, same dispatch as the scheduler."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.routers import triggers
from models.user import UserRole

pytestmark = pytest.mark.asyncio

TENANT = uuid.uuid4()


class FakeSession:
    def __init__(self, *results) -> None:
        self.results = list(results)
        self.statements: list = []
        self.commits = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        value = self.results.pop(0) if self.results else None
        return SimpleNamespace(scalar_one_or_none=lambda: value)

    async def commit(self):
        self.commits += 1


def _user(role=UserRole.USER):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT, role=role, is_active=True)


def _trigger(owner):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        agent_id=uuid.uuid4(),
        created_by=owner.id,
        name="nightly",
        default_message="run the report",
        default_context={"region": "eu"},
        run_count=3,
        last_run_at=None,
        last_status=None,
        is_active=True,
    )


def _body(resp) -> dict:
    return json.loads(resp.body)


async def _run(user, trigger, owner, *, eligible=None, dispatched=True):
    agent = SimpleNamespace(id=trigger.agent_id if trigger else None, name="Reporter")
    db = FakeSession(trigger, agent, owner)
    exec_id = uuid.uuid4()
    dispatch = AsyncMock(return_value=(SimpleNamespace(id=exec_id), dispatched))
    with patch.object(
        triggers, "check_trigger_eligibility", AsyncMock(return_value=eligible)
    ), patch.object(triggers, "dispatch_execution", dispatch), patch.object(
        triggers, "deactivate_trigger", AsyncMock()
    ) as deactivate:
        resp = await triggers.run_trigger_now(
            trigger.id if trigger else uuid.uuid4(), user, db
        )
    return resp, db, dispatch, deactivate, exec_id


async def test_owner_runs_trigger_through_dispatch():
    owner = _user()
    trig = _trigger(owner)
    resp, _, dispatch, _, exec_id = await _run(owner, trig, owner)
    assert resp.status_code == 202
    data = _body(resp)["data"]
    assert data["execution_id"] == str(exec_id)
    assert data["trigger_id"] == str(trig.id)
    kw = dispatch.await_args.kwargs
    assert kw["user"] is owner
    assert kw["trigger_id"] == str(trig.id)
    assert kw["message"] == "run the report"
    assert kw["context"] == {"region": "eu"}
    assert trig.run_count == 4
    assert trig.last_run_at is not None


async def test_lookup_is_tenant_scoped():
    owner = _user()
    resp, db, dispatch, _, _ = await _run(owner, None, owner)
    assert resp.status_code == 404
    dispatch.assert_not_awaited()
    c = db.statements[0].compile(dialect=postgresql.dialect())
    assert "agent_triggers.tenant_id" in str(c)
    assert TENANT in c.params.values()


async def test_other_member_is_forbidden():
    owner = _user()
    trig = _trigger(owner)
    resp, _, dispatch, _, _ = await _run(_user(), trig, owner)
    assert resp.status_code == 403
    dispatch.assert_not_awaited()


async def test_admin_runs_as_the_owner():
    owner = _user()
    trig = _trigger(owner)
    resp, _, dispatch, _, _ = await _run(_user(UserRole.ADMIN), trig, owner)
    assert resp.status_code == 202
    assert dispatch.await_args.kwargs["user"] is owner


async def test_ineligible_trigger_is_deactivated_not_run():
    owner = _user()
    trig = _trigger(owner)
    resp, _, dispatch, deactivate, _ = await _run(
        owner, trig, owner, eligible="agent_inactive"
    )
    assert resp.status_code == 400
    dispatch.assert_not_awaited()
    deactivate.assert_awaited_once()


async def test_queue_failure_returns_503_and_marks_failed():
    owner = _user()
    trig = _trigger(owner)
    resp, _, _, _, _ = await _run(owner, trig, owner, dispatched=False)
    assert resp.status_code == 503
    assert trig.last_status == "failed"
