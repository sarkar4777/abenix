"""POST /api/agents/{id}/execute records the parent run and carries the delegation depth."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.routers import agents as agents_router

# patched by dotted path below, import them so the patch never depends on test order
import app.core.platform_settings  # noqa: E402,F401
import app.core.usage  # noqa: E402,F401
import app.services.agent_share  # noqa: E402,F401
import engine.queue_backend  # noqa: E402,F401
from app.schemas.agents import ExecuteRequest
from models.agent import AgentStatus
from models.user import UserRole

pytestmark = pytest.mark.asyncio

TENANT = uuid.uuid4()


class _Result:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def first(self):
        return self.value


class FakeSession:
    """Answers queries in order: the agent lookup first, then parent-chain rows."""

    def __init__(self, *results) -> None:
        self.results = list(results)
        self.added: list = []

    async def execute(self, stmt):
        return _Result(self.results.pop(0) if self.results else None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()


def _user():
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=TENANT, role=UserRole.CREATOR, is_active=True
    )


def _agent():
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        slug="child-agent",
        name="Child",
        status=AgentStatus.ACTIVE,
        model_config_={"model": "claude-sonnet-4-5-20250929", "tools": []},
        runtime_pool="default",
        system_prompt="",
    )


def _request(raw: dict):
    return SimpleNamespace(headers={}, json=AsyncMock(return_value=raw))


async def _execute(user, agent, db, raw):
    backend = SimpleNamespace(submit=AsyncMock(return_value="task-1"))
    body = ExecuteRequest(
        **{k: v for k, v in raw.items() if k in ("message", "stream", "wait_mode")}
    )
    with (
        patch("app.core.usage.check_limit", AsyncMock(return_value=(True, ""))),
        patch("app.core.usage.check_user_quota", AsyncMock(return_value=None)),
        patch(
            "app.services.agent_share.resolve_agent_access",
            AsyncMock(return_value=True),
        ),
        patch("app.core.platform_settings.get_int_setting", AsyncMock(return_value=10)),
        patch.object(
            agents_router, "_fetch_mcp_connections", AsyncMock(return_value=[])
        ),
        patch.object(agents_router.settings, "scaling_exec_remote", True),
        patch("engine.queue_backend.get_queue_backend", return_value=backend),
    ):
        resp = await agents_router.execute_agent(
            str(agent.id), body, _request(raw), user=user, db=db
        )
    return resp, backend


def _raw(**extra):
    return {"message": "hi", "stream": False, "wait_mode": "submitted", **extra}


async def test_parent_and_depth_persisted_and_enqueued():
    user, agent = _user(), _agent()
    parent_id, grand_id = uuid.uuid4(), uuid.uuid4()
    caller_agent = uuid.uuid4()
    # agent row, then parent (depth 1) and grandparent (root)
    db = FakeSession(agent, (caller_agent, grand_id), (uuid.uuid4(), None))
    resp, backend = await _execute(
        user, agent, db, _raw(parent_execution_id=str(parent_id), delegation_depth=2)
    )
    assert resp.status_code == 200, resp.body
    execution = db.added[0]
    assert execution.parent_execution_id == parent_id
    payload = backend.submit.call_args.args[1]
    assert payload["parent_execution_id"] == str(parent_id)
    assert payload["delegation_depth"] == 2
    assert payload["user_id"] == str(user.id)
    assert payload["role"] == "creator"


async def test_depth_taken_from_chain_when_caller_understates_it():
    user, agent = _user(), _agent()
    parent_id = uuid.uuid4()
    chain = [(uuid.uuid4(), uuid.uuid4()), (uuid.uuid4(), uuid.uuid4())]
    db = FakeSession(agent, *chain, (uuid.uuid4(), None))
    resp, backend = await _execute(
        user, agent, db, _raw(parent_execution_id=str(parent_id), delegation_depth=0)
    )
    assert resp.status_code == 200, resp.body
    assert backend.submit.call_args.args[1]["delegation_depth"] == 3


async def test_depth_over_limit_refused():
    user, agent = _user(), _agent()
    db = FakeSession(agent, (uuid.uuid4(), None))
    resp, backend = await _execute(
        user, agent, db, _raw(parent_execution_id=str(uuid.uuid4()), delegation_depth=4)
    )
    assert resp.status_code == 400
    assert "sub-agent depth limit reached (3)" in resp.body.decode()
    backend.submit.assert_not_called()
    assert db.added == []


async def test_self_invoke_refused():
    user, agent = _user(), _agent()
    db = FakeSession(agent, (agent.id, None))
    resp, backend = await _execute(
        user, agent, db, _raw(parent_execution_id=str(uuid.uuid4()))
    )
    assert resp.status_code == 400
    assert "cannot invoke itself" in resp.body.decode()
    backend.submit.assert_not_called()


async def test_parent_from_another_tenant_refused():
    user, agent = _user(), _agent()
    db = FakeSession(agent, None)
    resp, backend = await _execute(
        user, agent, db, _raw(parent_execution_id=str(uuid.uuid4()))
    )
    assert resp.status_code == 400
    assert "parent execution not found" in resp.body.decode()
    backend.submit.assert_not_called()


async def test_top_level_run_has_no_parent():
    user, agent = _user(), _agent()
    db = FakeSession(agent)
    resp, backend = await _execute(user, agent, db, _raw())
    assert resp.status_code == 200, resp.body
    assert db.added[0].parent_execution_id is None
    payload = backend.submit.call_args.args[1]
    assert payload["delegation_depth"] == 0
    assert payload["parent_execution_id"] is None
