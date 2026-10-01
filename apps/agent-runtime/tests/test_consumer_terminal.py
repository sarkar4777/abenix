"""Consumer terminal follow-ups: drift hook and trigger outcome, with the slim-image fallback."""

from __future__ import annotations

import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

_RUNTIME = Path(__file__).resolve().parents[1]
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

import consumer  # noqa: E402


class FakeSession:
    def __init__(self) -> None:
        self.statements: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.statements.append((stmt, params))
        return SimpleNamespace(rowcount=1)

    async def commit(self):
        self.commits += 1


def _factory(session):
    @asynccontextmanager
    async def _open():
        yield session

    return _open


@pytest.mark.asyncio
async def test_after_terminal_calls_both_hooks():
    session = FakeSession()
    factory = _factory(session)
    record = AsyncMock(return_value=[])
    writer = AsyncMock(return_value=True)
    tid = str(uuid.uuid4())
    with patch.object(
        consumer, "_get_session_factory", AsyncMock(return_value=factory)
    ), patch("app.services.execution_hooks.record_terminal_by_id", record), patch(
        "app.routers.triggers.write_trigger_outcome", writer
    ):
        await consumer._after_terminal("ex-1", "failed", "boom", tid)
    record.assert_awaited_once_with(factory, "ex-1")
    writer.assert_awaited_once_with(factory, "ex-1", "failed", "boom", trigger_id=tid)


@pytest.mark.asyncio
async def test_after_terminal_without_trigger_skips_trigger_write():
    factory = _factory(FakeSession())
    record = AsyncMock(return_value=[])
    writer = AsyncMock()
    with patch.object(
        consumer, "_get_session_factory", AsyncMock(return_value=factory)
    ), patch("app.services.execution_hooks.record_terminal_by_id", record), patch(
        "app.routers.triggers.write_trigger_outcome", writer
    ):
        await consumer._after_terminal("ex-1", "completed", None, None)
    record.assert_awaited_once()
    writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_after_terminal_falls_back_when_api_package_is_missing():
    session = FakeSession()
    factory = _factory(session)
    tid = str(uuid.uuid4())
    missing = {"app.services.execution_hooks": None, "app.routers.triggers": None}
    with patch.object(
        consumer, "_get_session_factory", AsyncMock(return_value=factory)
    ), patch.dict(sys.modules, missing):
        await consumer._after_terminal("ex-1", "completed", None, tid)
    assert len(session.statements) == 1
    stmt, params = session.statements[0]
    assert "UPDATE agent_triggers SET last_status" in str(stmt)
    assert params["s"] == "completed"
    assert params["id"] == uuid.UUID(tid)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_hook_failure_does_not_block_trigger_write():
    factory = _factory(FakeSession())
    writer = AsyncMock(return_value=True)
    tid = str(uuid.uuid4())
    with patch.object(
        consumer, "_get_session_factory", AsyncMock(return_value=factory)
    ), patch(
        "app.services.execution_hooks.record_terminal_by_id",
        AsyncMock(side_effect=RuntimeError("redis down")),
    ), patch(
        "app.routers.triggers.write_trigger_outcome", writer
    ):
        await consumer._after_terminal("ex-1", "completed", None, tid)
    writer.assert_awaited_once()
