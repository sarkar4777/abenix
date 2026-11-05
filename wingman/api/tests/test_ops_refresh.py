"""Ops Refresh starts the agent and returns at once, and its result can only say what happened."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402


class _Forge:
    def __init__(self, row=None, fail=None):
        self.row = row or {}
        self.fail = fail
        self.calls = []
        self.executions = SimpleNamespace(get=self._get)

    async def _get(self, execution_id):
        if self.fail:
            raise self.fail
        return self.row

    async def execute(self, slug, body, **kw):
        self.calls.append((slug, kw))
        if self.fail:
            raise self.fail
        return SimpleNamespace(execution_id="run-1", status="running")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def world(monkeypatch):
    written = []
    monkeypatch.setattr(
        main.result_cache, "write", lambda page, key, data: written.append(data)
    )
    monkeypatch.setattr(
        main.result_cache, "_payload_is_load_bearing", lambda data: True
    )
    main._OPS_RUNS.clear()
    return written


def _use(monkeypatch, forge):
    monkeypatch.setattr(main, "_abenix_client", lambda *a: forge)


def test_refresh_submits_and_does_not_wait_for_the_agent(world, monkeypatch):
    forge = _Forge()
    _use(monkeypatch, forge)
    out = asyncio.run(main.ops_snapshot())["data"]
    assert out == {"execution_id": "run-1", "status": "running"}
    assert forge.calls[0][1] == {"wait": "submitted"}


def test_a_failed_start_is_an_error_the_page_can_show(world, monkeypatch):
    _use(monkeypatch, _Forge(fail=OSError("no route")))
    with pytest.raises(main.HTTPException) as err:
        asyncio.run(main.ops_snapshot())
    assert err.value.status_code == 502 and "no route" in err.value.detail


def test_a_finished_run_gives_the_snapshot_and_fills_the_cache(world, monkeypatch):
    forge = _Forge({"status": "completed", "output": '{"vessels": [{"mmsi": 1}]}'})
    _use(monkeypatch, forge)
    asyncio.run(main.ops_snapshot())
    out = asyncio.run(main.ops_result("run-1"))["data"]
    assert out["status"] == "completed"
    assert out["snapshot"]["vessels"] == [{"mmsi": 1}]
    assert world[0]["execution_id"] == "run-1"


def test_a_failed_run_says_why_and_leaves_the_cache_alone(world, monkeypatch):
    forge = _Forge({"status": "failed", "error_message": "AIS feed refused"})
    _use(monkeypatch, forge)
    asyncio.run(main.ops_snapshot())
    out = asyncio.run(main.ops_result("run-1"))["data"]
    assert out["error_message"] == "AIS feed refused" and out["snapshot"] is None
    assert world == []


def test_a_run_from_elsewhere_can_not_write_the_ops_cache(world, monkeypatch):
    _use(monkeypatch, _Forge({"status": "completed", "output": '{"vessels": [1]}'}))
    asyncio.run(main.ops_result("someone-elses-run"))
    assert world == []
