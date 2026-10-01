"""Scheduler trigger claiming: row locks, single run_count bump, eligibility."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.core import scheduler
from app.routers import triggers
from models.agent import Agent, AgentStatus, AgentType
from models.agent_trigger import AgentTrigger
from models.user import UserRole


def test_claim_statement_uses_for_update_skip_locked():
    now = datetime.now(timezone.utc)
    sql = str(
        scheduler.due_trigger_claim_stmt(now).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}
        )
    )
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "agent_triggers.next_run_at <=" in sql
    assert f"LIMIT {scheduler.TRIGGER_CLAIM_BATCH}" in sql or "LIMIT %(param_1)s" in sql


def test_claim_trigger_bumps_run_count_once_and_advances_next_run():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    t = AgentTrigger(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        trigger_type="schedule",
        name="t",
        cron_expression="*/5 * * * *",
        next_run_at=now - timedelta(minutes=1),
        run_count=3,
        is_active=True,
    )
    scheduler.claim_trigger(t, now)
    assert t.run_count == 4
    assert t.last_run_at == now
    assert t.next_run_at == datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc)
    assert t.is_active is True


def test_claim_trigger_one_shot_deactivates():
    now = datetime.now(timezone.utc)
    t = AgentTrigger(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        trigger_type="schedule",
        name="t",
        cron_expression=None,
        next_run_at=now,
        run_count=0,
        is_active=True,
    )
    scheduler.claim_trigger(t, now)
    assert t.run_count == 1
    assert t.is_active is False


@pytest.mark.asyncio
async def test_run_trigger_does_not_bump_run_count_again():
    """_check_due_triggers claims (run_count+1), _run_trigger only dispatches."""
    agent = _agent()
    owner = _owner(agent.tenant_id, agent.creator_id)
    trig = AgentTrigger(
        id=uuid.uuid4(),
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        created_by=owner.id,
        trigger_type="schedule",
        name="t",
        cron_expression="* * * * *",
        default_message="go",
        run_count=7,
        is_active=True,
    )
    db = _FakeSession({AgentTrigger: trig, Agent: agent})
    dispatch = AsyncMock(return_value=(SimpleNamespace(id=uuid.uuid4()), True))

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield db

    with patch("app.core.deps.fresh_session", fake_session), patch(
        "app.routers.triggers.dispatch_execution", dispatch
    ), patch("app.routers.triggers.check_trigger_eligibility", AsyncMock(return_value=None)):
        await scheduler._run_trigger(str(trig.id), str(agent.id))

    assert trig.run_count == 7
    dispatch.assert_awaited_once()
    assert dispatch.await_args.kwargs["trigger_id"] == str(trig.id)
    assert dispatch.await_args.kwargs["message"] == "go"


@pytest.mark.asyncio
async def test_run_trigger_deactivates_when_ineligible():
    agent = _agent(status=AgentStatus.ARCHIVED)
    owner = _owner(agent.tenant_id, agent.creator_id)
    trig = AgentTrigger(
        id=uuid.uuid4(),
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        created_by=owner.id,
        trigger_type="schedule",
        name="t",
        cron_expression="* * * * *",
        run_count=1,
        is_active=True,
    )
    db = _FakeSession({AgentTrigger: trig, Agent: agent})
    dispatch = AsyncMock()
    deactivate = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield db

    with patch("app.core.deps.fresh_session", fake_session), patch(
        "app.routers.triggers.dispatch_execution", dispatch
    ), patch("app.routers.triggers.deactivate_trigger", deactivate):
        await scheduler._run_trigger(str(trig.id), str(agent.id))

    dispatch.assert_not_awaited()
    deactivate.assert_awaited_once()
    assert deactivate.await_args.args[2] == "agent_deleted"


# --- eligibility -----------------------------------------------------------


def _agent(status=AgentStatus.ACTIVE, agent_type=AgentType.CUSTOM, tenant_id=None):
    return Agent(
        id=uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        creator_id=uuid.uuid4(),
        name="a",
        description="",
        system_prompt="",
        status=status,
        agent_type=agent_type,
        model_config_={},
    )


def _owner(tenant_id, user_id=None, role=UserRole.USER, is_active=True):
    return SimpleNamespace(
        id=user_id or uuid.uuid4(), tenant_id=tenant_id, role=role, is_active=is_active
    )


def _trigger(agent, owner):
    return AgentTrigger(
        id=uuid.uuid4(),
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        created_by=owner.id,
        trigger_type="schedule",
        name="t",
        is_active=True,
    )


class _FakeSession:
    def __init__(self, by_entity):
        self.by_entity = by_entity
        self.commits = 0

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        row = self.by_entity.get(entity)
        if entity is not None and entity.__name__ == "User":
            row = self.by_entity.get("User")
        return SimpleNamespace(scalar_one_or_none=lambda: row)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "agent_kwargs, owner_kwargs, expected",
    [
        ({}, {}, "access_revoked"),
        ({"status": AgentStatus.ARCHIVED}, {}, "agent_deleted"),
        ({"status": AgentStatus.DRAFT}, {}, "agent_inactive"),
        ({}, {"is_active": False}, "owner_inactive"),
        ({}, {"role": UserRole.ADMIN}, None),
        ({"agent_type": AgentType.OOB}, {}, None),
    ],
)
async def test_eligibility_matrix(agent_kwargs, owner_kwargs, expected):
    agent = _agent(**agent_kwargs)
    owner = _owner(agent.tenant_id, **owner_kwargs)
    trig = _trigger(agent, owner)
    with patch("app.core.permissions.accessible_resource_ids", AsyncMock(return_value=set())):
        reason = await triggers.check_trigger_eligibility(object(), trig, agent, owner)
    assert reason == expected


@pytest.mark.asyncio
async def test_eligibility_owner_is_creator():
    agent = _agent()
    owner = _owner(agent.tenant_id, user_id=agent.creator_id)
    assert await triggers.check_trigger_eligibility(object(), _trigger(agent, owner), agent, owner) is None


@pytest.mark.asyncio
async def test_eligibility_execute_share_grants_access():
    agent = _agent()
    owner = _owner(agent.tenant_id)
    with patch(
        "app.core.permissions.accessible_resource_ids", AsyncMock(return_value={agent.id})
    ) as shares:
        reason = await triggers.check_trigger_eligibility(object(), _trigger(agent, owner), agent, owner)
    assert reason is None
    from models.resource_share import SharePermission

    assert shares.await_args.kwargs["minimum_permission"] == SharePermission.EXECUTE


@pytest.mark.asyncio
async def test_eligibility_missing_agent_or_owner():
    agent = _agent()
    owner = _owner(agent.tenant_id)
    trig = _trigger(agent, owner)
    assert await triggers.check_trigger_eligibility(object(), trig, None, owner) == "agent_deleted"
    assert await triggers.check_trigger_eligibility(object(), trig, agent, None) == "owner_missing"


@pytest.mark.asyncio
async def test_deactivate_trigger_records_reason_and_notifies():
    agent = _agent()
    owner = _owner(agent.tenant_id)
    trig = _trigger(agent, owner)
    db = _FakeSession({})
    notify = AsyncMock()
    with patch("app.core.notifications.create_notification", notify):
        await triggers.deactivate_trigger(db, trig, "access_revoked", owner=owner)
    assert trig.is_active is False
    assert trig.last_status == "access_revoked"
    assert db.commits == 2
    assert notify.await_args.kwargs["user_id"] == owner.id
    assert notify.await_args.kwargs["metadata"]["reason"] == "access_revoked"
