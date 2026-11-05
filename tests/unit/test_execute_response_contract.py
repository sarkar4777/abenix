"""An explicit stream:true streams for every caller, and a sync run reports what really ran."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse, StreamingResponse

import app.core.execution_bus  # noqa: F401
import app.core.platform_settings  # noqa: F401
import app.core.usage  # noqa: F401
import app.services.agent_share  # noqa: F401
import engine.queue_backend  # noqa: F401
from app.routers import agents as agents_router
from app.schemas.agents import ExecuteRequest
from models.agent import AgentStatus
from models.user import UserRole

pytestmark = pytest.mark.asyncio

TENANT = uuid.uuid4()
CAN_DELEGATE = {"can_delegate": True}


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def first(self):
        return self.value


class FakeSession:
    def __init__(self, agent, on_refresh=None):
        self.results = [agent]
        self.added = []
        self.on_refresh = on_refresh
        self.closed = False

    async def execute(self, stmt):
        return _Result(self.results.pop(0) if self.results else None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def close(self):
        self.closed = True

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
            return
        if self.on_refresh:
            self.on_refresh(obj)


def _user(scopes):
    user = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=TENANT, role=UserRole.CREATOR, is_active=True
    )
    if scopes is not None:
        user._api_key_id = uuid.uuid4()
        user._api_key_scopes = scopes
    return user


def _agent():
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        slug="a",
        name="A",
        status=AgentStatus.ACTIVE,
        model_config_={"model": "gemini-2.0-flash", "tools": []},
        runtime_pool="default",
        system_prompt="",
    )


async def _execute(user, raw, db=None, events=()):
    agent = _agent()
    db = db or FakeSession(agent)
    db.results = [agent]

    async def subscribe(execution_id):
        for evt in events:
            yield evt

    backend = SimpleNamespace(submit=AsyncMock(return_value="task-1"))
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
        patch("app.core.execution_bus.subscribe_events", subscribe),
    ):
        request = SimpleNamespace(headers={}, json=AsyncMock(return_value=raw))
        resp = await agents_router.execute_agent(
            str(agent.id), ExecuteRequest(**raw), request, user=user, db=db
        )
    return resp


@pytest.mark.parametrize("scopes", [CAN_DELEGATE, {"execute": True}])
async def test_scoped_key_with_explicit_stream_gets_sse(scopes):
    resp = await _execute(_user(scopes), {"message": "hi", "stream": True})
    assert isinstance(resp, StreamingResponse)
    assert resp.media_type == "text/event-stream"


async def test_scoped_key_without_stream_still_waits_for_json():
    resp = await _execute(
        _user(CAN_DELEGATE),
        {"message": "hi"},
        events=[{"event": "done", "output": "hello"}],
    )
    assert isinstance(resp, JSONResponse)
    assert json.loads(resp.body)["data"]["output"] == "hello"


async def test_browser_caller_keeps_the_streaming_default():
    resp = await _execute(_user(None), {"message": "hi"})
    assert isinstance(resp, StreamingResponse)


async def test_wait_mode_beats_an_explicit_stream():
    resp = await _execute(
        _user(CAN_DELEGATE),
        {"message": "hi", "stream": True, "wait_mode": "submitted"},
    )
    assert isinstance(resp, JSONResponse)


def _row_after_run(row):
    row.model_used = "claude-haiku-4-5"
    row.tool_calls = [{"name": "calculator", "arguments": {}}]
    row.cost = 0.0123
    row.input_tokens = 11
    row.output_tokens = 7
    row.duration_ms = 900


async def test_sync_response_carries_what_the_row_recorded():
    agent = _agent()
    db = FakeSession(agent, on_refresh=_row_after_run)
    resp = await _execute(
        _user(CAN_DELEGATE),
        {"message": "hi", "stream": False, "wait": True},
        db=db,
        events=[{"event": "done", "output": "hello"}],
    )
    data = json.loads(resp.body)["data"]
    assert data["model"] == "claude-haiku-4-5"
    assert data["tool_calls"] == [{"name": "calculator", "arguments": {}}]
    assert data["cost"] == pytest.approx(0.0123)
    assert data["input_tokens"] == 11 and data["output_tokens"] == 7
    assert data["duration_ms"] == 900


async def test_failed_sync_response_names_the_model_too():
    agent = _agent()
    db = FakeSession(agent, on_refresh=_row_after_run)
    resp = await _execute(
        _user(CAN_DELEGATE),
        {"message": "hi", "stream": False, "wait": True},
        db=db,
        events=[{"event": "error", "error": "boom", "model": "claude-sonnet-5"}],
    )
    data = json.loads(resp.body)["data"]
    assert data["status"] == "failed"
    assert data["model"] == "claude-sonnet-5"


class _CountingSession(FakeSession):
    def __init__(self, agent, on_refresh=None):
        super().__init__(agent, on_refresh)
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


async def test_a_wait_holds_no_open_transaction():
    db = _CountingSession(_agent())
    seen = []

    class Events:
        def __iter__(self):
            seen.append(db.commits)
            yield {"event": "done", "output": "hello"}

    before = db.commits
    await _execute(
        _user(CAN_DELEGATE),
        {"message": "hi", "stream": False, "wait": True},
        db=db,
        events=Events(),
    )
    assert seen and seen[0] > before


async def test_a_queued_run_is_not_run_again_when_the_wait_breaks():
    db = _CountingSession(_agent())

    class Events:
        def __iter__(self):
            raise RuntimeError("connection lost")
            yield

    resp = await _execute(
        _user(CAN_DELEGATE),
        {"message": "hi", "stream": False, "wait": True},
        db=db,
        events=Events(),
    )
    assert resp.status_code == 202
    data = json.loads(resp.body)["data"]
    assert data["status"] == "running"
    assert data["task_id"] == "task-1"
    assert data["execution_id"]
    assert db.rollbacks == 1


async def test_a_failed_reload_after_the_wait_leaves_the_session_usable():
    def broken(_row):
        raise RuntimeError("connection lost")

    db = _CountingSession(_agent(), on_refresh=broken)
    resp = await _execute(
        _user(CAN_DELEGATE),
        {"message": "hi", "stream": False, "wait": True},
        db=db,
        events=[{"event": "done", "output": "hello"}],
    )
    assert db.rollbacks == 1
    assert json.loads(resp.body)["data"]["output"] == "hello"
