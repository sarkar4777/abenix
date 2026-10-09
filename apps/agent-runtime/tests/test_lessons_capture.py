"""Runtime lesson capture: masking, idempotent keys, and a run that never waits on or fails with the store."""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_RUNTIME = Path(__file__).resolve().parents[1]
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

from engine import lessons  # noqa: E402

T = str(uuid.uuid4())
A = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _reset():
    lessons.configure(writer=None)
    yield
    lessons.configure(writer=None)


def test_secrets_always_masked_pii_only_when_tenant_masks():
    raw = "mail ana@x.dev key api_key=abcdefghijklmnopqrstuvwxyz123"
    plain = lessons.mask_text(raw, None)
    assert "abcdefghijklmnopqrstuvwxyz123" not in plain
    assert "ana@x.dev" in plain
    masked = lessons.mask_text(raw, {"enabled": True, "mode": "mask"})
    assert "ana@x.dev" not in masked
    assert "[EMAIL_MASKED]" in masked
    off = lessons.mask_text(raw, {"enabled": False, "mode": "mask"})
    assert "ana@x.dev" in off


def test_block_mode_masks_too_and_custom_patterns_apply():
    out = lessons.mask_text(
        "order ORD-12345 for ana@x.dev",
        {"mode": "block", "custom_patterns": {"order": r"ORD-\d+"}},
    )
    assert "ORD-12345" not in out and "ana@x.dev" not in out


def test_row_caps_and_polarity():
    r = lessons.row(
        tenant_id=T,
        agent_id=A,
        source="positive",
        input_text="x" * 20000,
        note="n" * 9000,
        key="k" * 500,
    )
    assert r["polarity"] == "positive"
    assert len(r["input_text"]) == lessons.TEXT_CAP
    assert len(r["note"]) == lessons.NOTE_CAP
    assert len(r["capture_key"]) == lessons.KEY_CAP
    assert (
        lessons.row(tenant_id=T, agent_id=A, source="thumbs")["polarity"] == "negative"
    )


def test_capture_key_skips_empty_parts():
    assert lessons.capture_key("fb", None, "", "u1") == "fb:u1"


@pytest.mark.asyncio
async def test_capture_returns_at_once_and_writes_behind():
    seen = []
    gate = asyncio.Event()

    async def writer(fields):
        await gate.wait()
        seen.append(fields)

    lessons.configure(writer=writer)
    t0 = time.perf_counter()
    task = lessons.capture_run_failed(
        tenant_id=T, agent_id=A, execution_id="e1", error="boom", failure_code="X"
    )
    assert time.perf_counter() - t0 < 0.05
    assert task is not None and not seen
    gate.set()
    await lessons.flush()
    assert seen[0]["source"] == "run_failed"
    assert seen[0]["key"] == "e1"


@pytest.mark.asyncio
async def test_database_down_never_raises_and_pauses_capture():
    async def down(fields):
        raise ConnectionRefusedError("connection refused")

    lessons.configure(writer=down)
    task = lessons.capture(tenant_id=T, agent_id=A, source="thumbs")
    await lessons.flush()
    assert task is not None and task.exception() is None
    # paused after a failure, later captures cost nothing
    assert lessons.capture(tenant_id=T, agent_id=A, source="thumbs") is None


@pytest.mark.asyncio
async def test_real_writer_with_unreachable_database_never_raises():
    with patch(
        "engine.lessons._connect_kwargs",
        return_value=("postgresql://x@127.0.0.1:1/x", {}),
    ):
        lessons._pools.clear()
        task = lessons.capture(tenant_id=T, agent_id=A, source="thumbs")
        t0 = time.perf_counter()
        await asyncio.wait_for(lessons.flush(), 15)
        assert task is not None and task.exception() is None
        assert time.perf_counter() - t0 < 15
    lessons._pools.clear()


@pytest.mark.asyncio
async def test_in_flight_cap_drops_instead_of_queueing():
    gate = asyncio.Event()

    async def slow(fields):
        await gate.wait()

    lessons.configure(writer=slow)
    for _ in range(lessons.MAX_IN_FLIGHT):
        assert lessons.capture(tenant_id=T, agent_id=A, source="thumbs") is not None
    assert lessons.capture(tenant_id=T, agent_id=A, source="thumbs") is None
    assert lessons.dropped == 1
    gate.set()
    await lessons.flush()


def test_capture_without_a_loop_or_ids_is_a_no_op():
    assert lessons.capture(tenant_id=T, agent_id=A, source="thumbs") is None
    assert lessons.capture(tenant_id="", agent_id=A, source="thumbs") is None


@pytest.mark.asyncio
async def test_consumer_failed_run_capture_survives_bad_rows():
    import consumer

    calls = []
    with patch("engine.lessons.capture_run_failed", lambda **kw: calls.append(kw)):
        consumer._capture_failed("e1", (None, None, T, A, "hi"), None, "boom", "X")
        consumer._capture_failed("e2", (None, None), None, "boom", "X")
    assert calls and calls[0]["agent_id"] == A and calls[0]["failure_code"] == "X"


@pytest.mark.asyncio
async def test_mark_done_with_lesson_store_down_still_finishes(monkeypatch):
    import consumer

    async def down(fields):
        raise OSError("database is down")

    lessons.configure(writer=down)

    class Res:
        def one_or_none(self):
            return (None, None, T, A, "question")

    class Session:
        async def execute(self, *a, **k):
            return Res()

        async def commit(self):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(
        consumer, "_get_session_factory", AsyncMock(return_value=lambda: Session())
    )
    monkeypatch.setattr(consumer, "_after_terminal", AsyncMock())
    exec_id = str(uuid.uuid4())
    t0 = time.perf_counter()
    await consumer._mark_done(exec_id, "failed", None, "boom", failure_code="X")
    assert time.perf_counter() - t0 < 1.0
    await lessons.flush()
