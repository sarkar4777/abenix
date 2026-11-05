"""Queue delivery: celery refused, NATS acked after the run, leases, and trace context across the hop."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

_RUNTIME = Path(__file__).resolve().parents[1]
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

import consumer  # noqa: E402
from engine import queue_backend as qb  # noqa: E402

TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"


class FakeMsg:
    def __init__(self, data: bytes, delivered: int = 1) -> None:
        self.data = data
        self.metadata = SimpleNamespace(num_delivered=delivered)
        self.calls: list = []

    async def ack(self):
        self.calls.append("ack")

    async def nak(self, delay=None):
        self.calls.append(("nak", delay))

    async def in_progress(self):
        self.calls.append("in_progress")

    async def term(self):
        self.calls.append("term")


def _qm(payload: dict, delivered: int = 1, trace: dict | None = None):
    env = {"task_id": "t1", "payload": payload}
    if trace:
        env["trace"] = trace
    msg = FakeMsg(json.dumps(env).encode(), delivered)
    return qb.QueueMessage(env, msg), msg


@pytest.fixture(autouse=True)
def _reset_backend():
    qb._backend = None
    yield
    qb._backend = None


@pytest.mark.asyncio
async def test_celery_backend_refuses_with_a_clear_message(monkeypatch):
    monkeypatch.setenv("QUEUE_BACKEND", "celery")
    backend = qb.get_queue_backend()
    assert isinstance(backend, qb.CeleryBackend)
    with pytest.raises(RuntimeError, match="scaling.queueBackend=nats"):
        await backend.submit("default", {"execution_id": "x"})


def test_nats_requested_never_falls_back_to_celery(monkeypatch):
    monkeypatch.setenv("QUEUE_BACKEND", "nats")
    assert isinstance(qb.get_queue_backend(), qb.NATSBackend)


@pytest.mark.asyncio
async def test_consumer_exits_non_zero_on_celery(monkeypatch):
    monkeypatch.setenv("RUNTIME_MODE", "remote")
    monkeypatch.setenv("QUEUE_BACKEND", "celery")
    with pytest.raises(SystemExit) as ei:
        await consumer.main()
    assert ei.value.code == 1


class _FakeJS:
    def __init__(self):
        self.published: list = []

    async def consumer_info(self, stream, name):
        return SimpleNamespace(num_pending=0, num_ack_pending=0)

    async def publish(self, subject, body):
        self.published.append((subject, json.loads(body)))


@pytest.mark.asyncio
async def test_submit_carries_traceparent_only_when_a_trace_is_active():
    from engine.tracing import extract_carrier, get_tracer

    b = qb.NATSBackend()
    b._ensure = AsyncMock()
    b._js = _FakeJS()
    await b.submit("default", {"execution_id": "e1"})
    assert "trace" not in b._js.published[-1][1]

    ctx = extract_carrier({"traceparent": TRACEPARENT})
    with get_tracer("t").start_as_current_span("api", context=ctx):
        await b.submit("default", {"execution_id": "e2"})
    subject, env = b._js.published[-1]
    assert subject == "agents.default"
    assert env["payload"]["execution_id"] == "e2"
    assert TRACE_ID in env["trace"]["traceparent"]


class _FakeSub:
    def __init__(self, batches):
        self.batches = list(batches)

    async def fetch(self, n, timeout=5):
        if not self.batches:
            raise asyncio.CancelledError
        return self.batches.pop(0)

    async def unsubscribe(self):
        pass


@pytest.mark.asyncio
async def test_stream_does_not_ack_and_terminates_garbage():
    good = FakeMsg(
        json.dumps({"task_id": "t", "payload": {"execution_id": "e"}}).encode()
    )
    bad = FakeMsg(b"not json")
    b = qb.NATSBackend()
    b._ensure = AsyncMock()
    sub = _FakeSub([[bad, good]])
    b._js = SimpleNamespace(pull_subscribe=AsyncMock(return_value=sub))
    got = []
    with pytest.raises(asyncio.CancelledError):
        async for qm in b.stream("default"):
            got.append(qm)
    assert [q.data["payload"]["execution_id"] for q in got] == ["e"]
    assert bad.calls == ["term"]
    assert good.calls == []
    assert got[0].num_delivered == 1


@pytest.mark.asyncio
async def test_claimed_run_is_acked_after_it_finishes_with_parent_trace():
    seen: dict = {}

    async def fake_run(payload):
        from opentelemetry import trace

        seen["trace"] = format(
            trace.get_current_span().get_span_context().trace_id, "032x"
        )
        seen["acked_before_end"] = "ack" in msg.calls

    qm, msg = _qm(
        {"execution_id": str(uuid.uuid4())}, trace={"traceparent": TRACEPARENT}
    )
    with (
        patch.object(consumer, "_claim", AsyncMock(return_value=("claimed", 0.0))),
        patch.object(consumer, "_run_one", fake_run),
    ):
        await consumer._handle_delivery(qm, asyncio.Semaphore(1))
    assert seen == {"trace": TRACE_ID, "acked_before_end": False}
    assert msg.calls == ["ack"]


@pytest.mark.asyncio
async def test_run_held_by_a_live_owner_is_redelivered_after_its_lease():
    qm, msg = _qm({"execution_id": str(uuid.uuid4())}, delivered=2)
    run = AsyncMock()
    with (
        patch.object(consumer, "_claim", AsyncMock(return_value=("owned", 12.5))),
        patch.object(consumer, "_run_one", run),
    ):
        await consumer._handle_delivery(qm, asyncio.Semaphore(1))
    run.assert_not_awaited()
    assert msg.calls == [("nak", 13.5)]


@pytest.mark.asyncio
async def test_finished_run_duplicate_is_dropped():
    qm, msg = _qm({"execution_id": str(uuid.uuid4())}, delivered=3)
    run = AsyncMock()
    with (
        patch.object(consumer, "_claim", AsyncMock(return_value=("done", 0.0))),
        patch.object(consumer, "_run_one", run),
    ):
        await consumer._handle_delivery(qm, asyncio.Semaphore(1))
    run.assert_not_awaited()
    assert msg.calls == ["ack"]


@pytest.mark.asyncio
async def test_exhausted_attempts_fail_the_run_once():
    eid = str(uuid.uuid4())
    qm, msg = _qm({"execution_id": eid, "trigger_id": "tr"}, delivered=4)
    done = AsyncMock()
    with (
        patch.object(consumer, "_claim", AsyncMock(return_value=("exhausted", 0.0))),
        patch.object(consumer, "_mark_done", done),
        patch.object(consumer, "_publish", AsyncMock()),
    ):
        await consumer._handle_delivery(qm, asyncio.Semaphore(1))
    args, kwargs = done.call_args
    assert args[:2] == (eid, "failed")
    assert kwargs["failure_code"] == "STALE_SWEEP"
    assert kwargs["trigger_id"] == "tr"
    assert msg.calls == ["ack"]


@pytest.mark.asyncio
async def test_unexpected_error_naks_for_retry():
    qm, msg = _qm({"execution_id": str(uuid.uuid4())})
    with patch.object(consumer, "_claim", AsyncMock(side_effect=OSError("db down"))):
        await consumer._handle_delivery(qm, asyncio.Semaphore(1))
    assert msg.calls == [("nak", 10)]


@pytest.mark.asyncio
async def test_heartbeat_keeps_delivery_alive_and_stops_on_takeover(monkeypatch):
    monkeypatch.setattr(consumer, "LEASE_SECONDS", 0.03)
    started = asyncio.Event()

    async def slow_run(payload):
        started.set()
        await asyncio.sleep(5)

    qm, msg = _qm({"execution_id": str(uuid.uuid4())})
    renew = AsyncMock(side_effect=[True, False])
    with (
        patch.object(consumer, "_claim", AsyncMock(return_value=("claimed", 0.0))),
        patch.object(consumer, "_run_one", slow_run),
        patch.object(consumer, "_renew", renew),
    ):
        await asyncio.wait_for(
            consumer._handle_delivery(qm, asyncio.Semaphore(1)), timeout=2
        )
    assert started.is_set()
    assert renew.await_count == 2
    assert msg.calls.count("in_progress") >= 2
    assert msg.calls[-1] == "ack"


@pytest.mark.asyncio
async def test_shutdown_cancel_leaves_message_unacked():
    started = asyncio.Event()

    async def slow_run(payload):
        started.set()
        await asyncio.sleep(5)

    qm, msg = _qm({"execution_id": str(uuid.uuid4())})
    with (
        patch.object(consumer, "_claim", AsyncMock(return_value=("claimed", 0.0))),
        patch.object(consumer, "_run_one", slow_run),
    ):
        t = asyncio.create_task(consumer._handle_delivery(qm, asyncio.Semaphore(1)))
        await started.wait()
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    assert "ack" not in msg.calls


class _Result:
    def __init__(self, first=None, rowcount=0, scalar=None):
        self._first = first
        self.rowcount = rowcount
        self._scalar = scalar

    def first(self):
        return self._first

    def scalar(self):
        return self._scalar


class _Session:
    def __init__(self, results):
        self.results = list(results)
        self.sql: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        from sqlalchemy.dialects import postgresql

        self.sql.append(str(stmt.compile(dialect=postgresql.dialect())))
        return self.results.pop(0)

    async def commit(self):
        pass


def _factory(session):
    return AsyncMock(return_value=lambda: session)


@pytest.mark.asyncio
async def test_claim_takes_a_free_or_expired_lease():
    s = _Session([_Result(first=(1,))])
    with patch.object(consumer, "_get_session_factory", _factory(s)):
        assert await consumer._claim(str(uuid.uuid4())) == ("claimed", 0.0)
    sql = s.sql[0]
    assert "lease_expires_at IS NULL" in sql
    assert "lease_expires_at < now()" in sql
    assert "delivery_attempts <" in sql
    assert "RETURNING" in sql


@pytest.mark.asyncio
async def test_claim_classifies_what_it_could_not_take():
    from models.execution import ExecutionStatus

    cases = [
        ((ExecutionStatus.COMPLETED, "x", None), ("done", 0.0)),
        ((ExecutionStatus.RUNNING, "other-pod", 9.0), ("owned", 9.0)),
        ((ExecutionStatus.RUNNING, "other-pod", -3.0), ("exhausted", 0.0)),
        (None, ("missing", 0.0)),
    ]
    for row, want in cases:
        s = _Session([_Result(first=None), _Result(first=row)])
        with patch.object(consumer, "_get_session_factory", _factory(s)):
            assert await consumer._claim(str(uuid.uuid4())) == want


@pytest.mark.asyncio
async def test_renew_reports_takeover_only_when_someone_else_owns_it():
    s = _Session([_Result(rowcount=1)])
    with patch.object(consumer, "_get_session_factory", _factory(s)):
        assert await consumer._renew(str(uuid.uuid4())) is True
    s = _Session([_Result(rowcount=0), _Result(scalar="other-pod")])
    with patch.object(consumer, "_get_session_factory", _factory(s)):
        assert await consumer._renew(str(uuid.uuid4())) is False
    # finished by us, the row just is not running any more
    s = _Session([_Result(rowcount=0), _Result(scalar=consumer.RUNNER_ID)])
    with patch.object(consumer, "_get_session_factory", _factory(s)):
        assert await consumer._renew(str(uuid.uuid4())) is True


class _DurableJS:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.calls: list = []
        self.configs: list = []

    async def consumer_info(self, stream, name):
        from nats.js.errors import NotFoundError

        self.calls.append(("info", name))
        if name not in self.existing:
            raise NotFoundError()
        return SimpleNamespace(num_pending=4, num_ack_pending=1)

    async def add_consumer(self, stream, config=None):
        self.calls.append(("add", config.durable_name))
        self.configs.append(config)
        self.existing.add(config.durable_name)

    async def publish(self, subject, body):
        self.calls.append(("publish", subject))

    async def delete_consumer(self, stream, name):
        from nats.js.errors import NotFoundError

        self.calls.append(("delete", name))
        if name not in self.existing:
            raise NotFoundError()
        self.existing.discard(name)

    async def purge_stream(self, stream, subject=None):
        self.calls.append(("purge", subject))


def _backend(js):
    b = qb.NATSBackend()
    b._ensure = AsyncMock()
    b._js = js
    return b


@pytest.mark.asyncio
async def test_first_run_to_a_pool_at_zero_creates_the_durable_before_publishing():
    js = _DurableJS()
    await _backend(js).submit("long-running", {"execution_id": "e1"})
    assert js.calls == [
        ("info", "abenix-long-running-consumer"),
        ("add", "abenix-long-running-consumer"),
        ("publish", "agents.long-running"),
    ]
    config = js.configs[0]
    assert config.filter_subject == "agents.long-running"
    assert config.ack_wait == qb.ACK_WAIT_SECONDS


@pytest.mark.asyncio
async def test_an_existing_durable_is_left_alone_and_only_checked_once_a_minute():
    js = _DurableJS(existing={"abenix-default-consumer"})
    b = _backend(js)
    await b.submit("default", {"execution_id": "e1"})
    await b.submit("default", {"execution_id": "e2"})
    assert [c[0] for c in js.calls] == ["info", "publish", "publish"]
    assert not js.configs


@pytest.mark.asyncio
async def test_a_message_is_not_published_when_its_durable_cannot_be_made():
    js = _DurableJS()
    js.add_consumer = AsyncMock(side_effect=RuntimeError("nats refused"))
    with pytest.raises(RuntimeError):
        await _backend(js).submit("default", {"execution_id": "e1"})
    assert not [c for c in js.calls if c[0] == "publish"]


@pytest.mark.asyncio
async def test_backlog_counts_queued_and_held_runs_and_none_without_a_durable():
    js = _DurableJS(existing={"abenix-default-consumer"})
    b = _backend(js)
    assert await b.backlog("default") == 5
    assert await b.backlog("gone") is None


@pytest.mark.asyncio
async def test_remove_queue_drops_the_durable_and_its_messages_and_forgets_it():
    js = _DurableJS()
    b = _backend(js)
    await b.ensure_consumer("dedicated-1")
    await b.remove_queue("dedicated-1")
    assert ("delete", "abenix-dedicated-1-consumer") in js.calls
    assert ("purge", "agents.dedicated-1") in js.calls
    js.calls.clear()
    await b.ensure_consumer("dedicated-1")
    assert ("add", "abenix-dedicated-1-consumer") in js.calls


@pytest.mark.asyncio
async def test_a_lost_connection_does_not_spin_the_fetch_loop():
    class _Lost:
        fetches = 0

        async def fetch(self, n, timeout=5):
            _Lost.fetches += 1
            if _Lost.fetches > 1:
                raise asyncio.CancelledError
            raise ConnectionError("nats gone")

        async def unsubscribe(self):
            pass

    b = qb.NATSBackend()
    b._ensure = AsyncMock()
    b._js = SimpleNamespace(pull_subscribe=AsyncMock(return_value=_Lost()))
    slept: list = []
    real_sleep = asyncio.sleep

    async def fake_sleep(s):
        slept.append(s)
        await real_sleep(0)

    with patch.object(qb.asyncio, "sleep", fake_sleep), pytest.raises(
        asyncio.CancelledError
    ):
        async for _ in b.stream("default"):
            pass
    assert slept == [1]
