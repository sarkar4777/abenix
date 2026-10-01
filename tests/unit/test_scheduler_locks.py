"""Scheduler singletons take the transaction-scoped advisory lock."""

from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import scheduler


def _lock(held: bool, seen: list[int]):
    @asynccontextmanager
    async def _advisory_lock(key: int):
        seen.append(key)
        yield held

    return _advisory_lock


def test_no_session_scoped_lock_left_in_scheduler():
    src = inspect.getsource(scheduler)
    assert "pg_try_advisory_lock(" not in src
    assert "pg_try_advisory_xact_lock(" in src


def test_lock_keys_are_distinct():
    keys = {
        scheduler.QUOTA_LOCK_KEY,
        scheduler.ARCHIVE_LOCK_KEY,
        scheduler.SWEEP_LOCK_KEY,
        scheduler.DRIFT_LOCK_KEY,
    }
    assert len(keys) == 4


@pytest.mark.asyncio
async def test_sweeper_skips_without_the_lock():
    seen: list[int] = []
    session = MagicMock(side_effect=AssertionError("no session when not held"))
    with patch.object(scheduler, "advisory_lock", _lock(False, seen)), patch(
        "app.core.deps.async_session", session
    ):
        await scheduler.sweep_stale_executions()
    assert seen == [scheduler.SWEEP_LOCK_KEY]
    session.assert_not_called()


@pytest.mark.asyncio
async def test_drift_backlog_runs_under_its_lock(monkeypatch):
    monkeypatch.setenv("DRIFT_SCAN_INTERVAL_SECONDS", "120")
    seen: list[int] = []
    scan = AsyncMock(return_value=3)
    with patch.object(scheduler, "advisory_lock", _lock(True, seen)), patch(
        "app.services.execution_hooks.scan_backlog", scan
    ):
        await scheduler.score_drift_backlog()
    assert seen == [scheduler.DRIFT_LOCK_KEY]
    scan.assert_awaited_once()
    assert scan.await_args.kwargs["interval_seconds"] == 120


@pytest.mark.asyncio
async def test_drift_backlog_skips_without_the_lock():
    seen: list[int] = []
    scan = AsyncMock()
    with patch.object(scheduler, "advisory_lock", _lock(False, seen)), patch(
        "app.services.execution_hooks.scan_backlog", scan
    ):
        await scheduler.score_drift_backlog()
    assert seen == [scheduler.DRIFT_LOCK_KEY]
    scan.assert_not_awaited()


def test_scan_interval_has_a_floor(monkeypatch):
    monkeypatch.setenv("DRIFT_SCAN_INTERVAL_SECONDS", "5")
    assert scheduler.drift_scan_interval_seconds() == 30
    monkeypatch.delenv("DRIFT_SCAN_INTERVAL_SECONDS")
    assert scheduler.drift_scan_interval_seconds() == 300
