"""Background jobs page: run recording, skipped ticks, plain errors, Run now and the catalogue."""

from __future__ import annotations

import inspect
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core import job_runs, scheduler


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.h: dict[str, dict[str, str]] = {}
        self.lists: dict[str, list[str]] = {}

    async def ping(self):
        return True

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def get(self, k):
        return self.kv.get(k)

    async def delete(self, k):
        self.kv.pop(k, None)

    async def hset(self, k, field=None, value=None, mapping=None):
        d = self.h.setdefault(k, {})
        if mapping:
            d.update({a: str(b) for a, b in mapping.items()})
        if field is not None:
            d[field] = str(value)

    async def hgetall(self, k):
        return dict(self.h.get(k, {}))

    async def hincrby(self, k, field, n):
        d = self.h.setdefault(k, {})
        d[field] = str(int(d.get(field, 0)) + n)

    async def lpush(self, k, v):
        self.lists.setdefault(k, []).insert(0, v)

    async def ltrim(self, k, a, b):
        self.lists[k] = self.lists.get(k, [])[a : b + 1]

    async def lrange(self, k, a, b):
        return self.lists.get(k, [])[a : b + 1]


@pytest.fixture
def fake(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(job_runs, "_client", r)
    monkeypatch.setattr(job_runs, "_local_next", lambda job_id: None)
    return r


@pytest.mark.asyncio
async def test_a_run_is_recorded_with_its_summary(fake):
    async def job():
        return {"fired": 2}

    rec = await job_runs.execute("check_due_triggers", job)
    assert rec["outcome"] == "ok"
    assert rec["summary"] == "2 triggers started."
    stored = fake.h["abenix:jobs:check_due_triggers"]
    assert stored["last_outcome"] == "ok"
    assert stored["run_count"] == "1"
    assert json.loads(stored["last_result"]) == {"fired": 2}
    assert len(fake.lists["abenix:jobs:check_due_triggers:history"]) == 1
    # the running marker is gone once it finishes
    assert "abenix:jobs:check_due_triggers:running" not in fake.kv


@pytest.mark.asyncio
async def test_an_idle_tick_updates_last_run_but_not_history(fake):
    async def job():
        return {"fired": 0}

    rec = await job_runs.execute("check_due_triggers", job)
    assert rec["summary"] == "No trigger was due."
    assert fake.h["abenix:jobs:check_due_triggers"]["last_outcome"] == "ok"
    assert "abenix:jobs:check_due_triggers:history" not in fake.lists


@pytest.mark.asyncio
async def test_a_swallowed_error_still_reads_as_failed_in_plain_words(fake):
    log = logging.getLogger("abenix.scheduler")
    job_runs.install_capture()

    async def job():
        try:
            raise ConnectionRefusedError("[Errno 111] Connection refused")
        except Exception:
            log.exception("approval escalation failed")
        return None

    rec = await job_runs.execute("escalate_approvals", job)
    assert rec["outcome"] == "failed"
    assert "could not reach" in rec["error"]
    assert "Connection refused" in rec["error_detail"]
    stored = fake.h["abenix:jobs:escalate_approvals"]
    assert stored["fail_count"] == "1"
    assert stored["last_failed_at"]


@pytest.mark.asyncio
async def test_a_raising_job_never_raises_out(fake):
    async def job():
        raise RuntimeError("boom")

    rec = await job_runs.execute("ping_models", job)
    assert rec["outcome"] == "failed"
    assert rec["error"] == "It stopped with an error: RuntimeError: boom"


@pytest.mark.asyncio
async def test_losing_the_lock_is_a_skip_not_a_run(fake):
    async def ok():
        return {"escalated": 1}

    async def lost():
        job_runs.note_lock(False)
        return None

    await job_runs.execute("escalate_approvals", ok)
    rec = await job_runs.execute("escalate_approvals", lost)
    assert rec["outcome"] == "skipped"
    stored = fake.h["abenix:jobs:escalate_approvals"]
    assert stored["run_count"] == "1"
    assert stored["skip_count"] == "1"
    assert stored["last_outcome"] == "ok"
    assert stored["last_summary"] == "1 approval escalated."


@pytest.mark.asyncio
async def test_lock_miss_with_work_done_counts_as_a_run(fake):
    # improvements_tick drains proofs on replicas that missed the propose lock
    async def drained():
        job_runs.note_lock(False)
        return {"drained": 1}

    rec = await job_runs.execute("improvements_tick", drained)
    assert rec["outcome"] == "ok"


@pytest.mark.asyncio
async def test_advisory_lock_tells_the_recorder(monkeypatch):
    seen = {}

    class Result:
        def __init__(self, v):
            self.v = v

        def scalar(self):
            return self.v

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def begin(self):
            return self

        async def execute(self, *a, **k):
            return Result(False)

    monkeypatch.setattr("app.core.deps.async_session", lambda: Session())
    monkeypatch.setattr(
        job_runs, "note_lock", lambda held: seen.setdefault("held", held)
    )
    async with scheduler.advisory_lock(123) as held:
        assert held is False
    assert seen["held"] is False


def test_plain_error_words():
    assert job_runs.plain_error(None) is None
    assert "too long" in job_runs.plain_error("asyncio.TimeoutError: timed out")
    assert "migrations" in job_runs.plain_error('relation "lessons" does not exist')
    assert "credentials" in job_runs.plain_error("401 Unauthorized")
    assert "lost its database connection" in job_runs.plain_error(
        "DBAPIError: connection was closed in the middle of operation"
    )
    assert (
        job_runs.plain_error("ValueError: bad\nline two")
        == "It stopped with an error: ValueError: bad"
    )


def test_schedules_read_as_words():
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    assert job_runs.describe_schedule(IntervalTrigger(seconds=30)) == "Every 30 seconds"
    assert job_runs.describe_schedule(IntervalTrigger(minutes=1)) == "Every minute"
    assert job_runs.describe_schedule(IntervalTrigger(minutes=60)) == "Every hour"
    assert job_runs.describe_schedule(IntervalTrigger(minutes=5)) == "Every 5 minutes"
    assert (
        job_runs.describe_schedule(CronTrigger(hour=4, minute=5))
        == "Daily at 04:05 UTC"
    )
    assert (
        job_runs.describe_schedule(CronTrigger(day=1, hour=0, minute=0))
        == "Monthly on day 1 at 00:00 UTC"
    )


def test_every_scheduled_job_is_tracked_and_explained():
    src = inspect.getsource(scheduler.start_scheduler)
    added = src.count("scheduler.add_job(")
    ids = re.findall(r'_tracked\(\s*"([a-z_]+)"', src)
    assert len(ids) == added
    for jid in ids:
        info = job_runs.CATALOGUE[jid]
        assert info.title and info.what and info.why
        assert info.group in job_runs.GROUPS
    assert set(ids) == set(job_runs.CATALOGUE)


def test_purges_ask_for_confirmation():
    for jid in (
        "moderation_retention",
        "lesson_retention",
        "prune_events",
        "nightly_archive",
        "reset_monthly_quotas",
    ):
        assert job_runs.CATALOGUE[jid].destructive
    assert not job_runs.CATALOGUE["check_due_triggers"].destructive


def test_escalation_runs_every_minute():
    src = inspect.getsource(scheduler.start_scheduler)
    block = src[src.index('_tracked("escalate_approvals"') :][:200]
    assert "minutes=1," in block


class FakeScheduler:
    def __init__(self, jobs):
        self.jobs = {j.id: j for j in jobs}
        self.running = True

    def get_job(self, jid):
        return self.jobs.get(jid)

    def get_jobs(self):
        return list(self.jobs.values())


def _job(jid, seconds=30):
    from apscheduler.triggers.interval import IntervalTrigger

    return SimpleNamespace(
        id=jid,
        name=jid,
        trigger=IntervalTrigger(seconds=seconds),
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=seconds),
    )


@pytest.mark.asyncio
async def test_run_now_needs_confirmation_for_purges(fake, monkeypatch):
    called = []

    async def purge():
        called.append(1)
        return {"held_text": 3}

    job_runs.register("moderation_retention", purge)
    monkeypatch.setattr(
        scheduler,
        "get_scheduler",
        lambda: FakeScheduler([_job("moderation_retention")]),
    )
    with pytest.raises(job_runs.RunNowError) as e:
        await job_runs.run_now("moderation_retention", by="a@b.c", confirmed=False)
    assert e.value.code == "CONFIRM_REQUIRED"
    assert not called
    out = await job_runs.run_now("moderation_retention", by="a@b.c", confirmed=True)
    assert out["status"] == "ok"
    assert out["run"]["summary"] == "3 held texts removed."
    stored = fake.h["abenix:jobs:moderation_retention"]
    assert stored["last_trigger"] == "manual"
    assert stored["last_by"] == "a@b.c"
    assert stored["manual_count"] == "1"


@pytest.mark.asyncio
async def test_run_now_unknown_job_is_404(fake, monkeypatch):
    monkeypatch.setattr(scheduler, "get_scheduler", lambda: FakeScheduler([]))
    with pytest.raises(job_runs.RunNowError) as e:
        await job_runs.run_now("nope", by="a@b.c", confirmed=True)
    assert e.value.status == 404


@pytest.mark.asyncio
async def test_run_now_that_loses_the_lock_says_so(fake, monkeypatch):
    async def lost():
        job_runs.note_lock(False)
        return None

    job_runs.register("escalate_approvals", lost)
    monkeypatch.setattr(
        scheduler, "get_scheduler", lambda: FakeScheduler([_job("escalate_approvals")])
    )
    out = await job_runs.run_now("escalate_approvals", by="a@b.c", confirmed=False)
    assert out["status"] == "skipped"
    assert "Another replica" in out["run"]["summary"]


@pytest.mark.asyncio
async def test_list_takes_the_earliest_next_run_from_live_replicas(fake, monkeypatch):
    job = _job("check_due_triggers", 30)
    monkeypatch.setattr(scheduler, "get_scheduler", lambda: FakeScheduler([job]))
    now = datetime.now(timezone.utc)
    soon = now + timedelta(seconds=4)
    fake.h["abenix:jobs:replicas"] = {
        "api-b": now.isoformat(),
        "api-dead": (now - timedelta(minutes=30)).isoformat(),
    }
    fake.h["abenix:jobs:check_due_triggers:next"] = {
        "api-b": soon.isoformat(),
        "api-dead": (now + timedelta(seconds=1)).isoformat(),
    }
    out = await job_runs.list_jobs()
    row = out["jobs"][0]
    assert row["next_run_at"] == soon.isoformat()
    assert row["schedule"] == "Every 30 seconds"
    assert [r["name"] for r in out["replicas"]] == ["api-b"]


def test_escalation_minutes_rule():
    from engine import risk

    assert risk.escalate_minutes({"escalate_after_hours": 4}) == 240
    assert (
        risk.escalate_minutes({"escalate_after_hours": 24, "escalate_after_minutes": 2})
        == 2
    )
    assert (
        risk.escalate_minutes({"escalate_after_minutes": 0, "escalate_after_hours": 1})
        == 60
    )
    assert risk.escalate_minutes(None) == 0
    assert risk.wait_words(2) == "2 min"
    assert risk.wait_words(240) == "4h"
    assert risk.wait_words(90) == "1h 30 min"


def test_escalation_minutes_validation():
    from engine.risk import validate_policy

    assert validate_policy({"publish_approvals": {"escalate_after_minutes": 2}}) == []
    assert validate_policy({"publish_approvals": {"escalate_after_minutes": 0}}) == []
    for bad in (-1, 720 * 60 + 1, 1.5, True, "5"):
        problems = validate_policy(
            {"publish_approvals": {"escalate_after_minutes": bad}}
        )
        assert any("escalate_after_minutes" in p for p in problems), bad
