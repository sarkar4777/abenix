"""Lessons: grouping, suggested cases, capture that never breaks the caller, clustering, retention and erase."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core import capabilities as caps
from app.core import scheduler
from app.routers import lessons as router
from app.services import eval_assertions as EA
from app.services import lessons as svc
from engine import lessons as L
from models.agent import Agent
from models.evals import EvalCase, EvalSuite
from models.improvement import Lesson, LessonCluster

pytestmark = pytest.mark.asyncio

T = uuid.uuid4()
A = uuid.uuid4()


def _lesson(**kw):
    base = dict(
        id=uuid.uuid4(),
        tenant_id=T,
        agent_id=A,
        source="correction",
        polarity="negative",
        input_text="What is the price of copper today?",
        output_text="Copper was 8,100 dollars last month.",
        expected="Use today's price from the market tool.",
        note=None,
        failure_code=None,
        tool_name=None,
        execution_id=uuid.uuid4(),
        cluster_id=None,
        case_id=None,
        by_user=None,
        meta={},
        created_at=datetime.now(timezone.utc),
    )
    base.update(kw)
    return Lesson(**base)


# grouping


def test_tokens_drop_numbers_ids_and_stopwords():
    out = svc.tokens(
        "The price of COPPER is 8,100 on 2026-01-01 for id 0a1b2c3d-1111-2222-3333-444455556666"
    )
    assert out == ["price", "copper"]


def test_same_mistake_gets_the_same_signature_and_wording_changes_still_match():
    a = _lesson()
    b = _lesson(
        input_text="what is the price of copper today??", execution_id=uuid.uuid4()
    )
    ga, gb = svc.grouping(a), svc.grouping(b)
    assert svc.signature(ga) == svc.signature(gb)
    c = _lesson(input_text="Tell me copper's price today please, quickly")
    gc = svc.grouping(c)
    cluster = SimpleNamespace(meta={"base": ga["base"], "keys": ga["keys"]})
    assert svc.best_match(gc, [cluster]) is cluster


def test_different_failure_codes_never_group():
    a = svc.grouping(
        _lesson(source="run_failed", failure_code="TOOL_ERROR", note="timeout")
    )
    b = svc.grouping(
        _lesson(source="run_failed", failure_code="LLM_RATE_LIMIT", note="timeout")
    )
    assert a["base"] != b["base"]
    cluster = SimpleNamespace(meta={"base": a["base"], "keys": a["keys"]})
    assert svc.best_match(b, [cluster]) is None


def test_positive_lessons_share_one_group_per_agent():
    a = svc.grouping(_lesson(source="positive", polarity="positive"))
    b = svc.grouping(
        _lesson(source="positive", polarity="positive", input_text="other")
    )
    assert svc.signature(a) == svc.signature(b)
    assert a["family"] == "positive"


def test_trend_keeps_fourteen_days_and_series_ends_today():
    t = None
    today = datetime(2026, 10, 8, tzinfo=timezone.utc)
    for d in range(20):
        t = svc.trend_add(t, (today - timedelta(days=d)).date().isoformat())
    assert len(t) == svc.TREND_DAYS
    series = svc.trend_series(t, today)
    assert len(series) == svc.TREND_DAYS and series[-1] == 1


def test_severity():
    assert svc.severity_for({"sources": {"harm": 1}}, 1) == "high"
    assert svc.severity_for({"sources": {"thumbs": 12}}, 12) == "high"
    assert svc.severity_for({"sources": {"correction": 1}}, 1) == "medium"
    assert svc.severity_for({"sources": {"thumbs": 1}}, 1) == "low"


# suggested cases


def test_correction_becomes_a_reference_case_with_a_valid_judge():
    spec = svc.case_for(_lesson())
    assert spec["reference_output"] == "Use today's price from the market tool."
    assert spec["assertions"][0]["type"] == "judge"
    assert EA.validate(spec["assertions"][0]) == []
    assert "needs_confirmation" not in spec["tags"]


def test_note_only_is_marked_for_a_person_to_confirm():
    spec = svc.case_for(
        _lesson(source="note", expected=None, note="it ignored the date")
    )
    assert spec["reference_output"] is None
    assert "needs_confirmation" in spec["tags"]
    assert "it ignored the date" in spec["assertions"][0]["rubric"]


def test_positive_case_keeps_the_good_answer():
    spec = svc.case_for(_lesson(source="positive", polarity="positive", expected=None))
    assert spec["reference_output"].startswith("Copper")


def test_no_case_without_an_input_or_for_drift():
    assert svc.case_for(_lesson(input_text="")) is None
    assert svc.case_for(_lesson(source="drift")) is None


def test_cases_need_two_lessons_or_a_strong_signal():
    one = SimpleNamespace(negative_count=1, meta={"sources": {"thumbs": 1}})
    assert not svc.wants_cases(one)
    two = SimpleNamespace(negative_count=2, meta={"sources": {"thumbs": 2}})
    assert svc.wants_cases(two)
    harm = SimpleNamespace(negative_count=1, meta={"sources": {"harm": 1}})
    assert svc.wants_cases(harm)


# capture never breaks the caller


class _Nested:
    def __init__(self, fail_on_enter=False):
        self.fail_on_enter = fail_on_enter

    async def __aenter__(self):
        if self.fail_on_enter:
            raise ConnectionError("database is down")
        return self

    async def __aexit__(self, *a):
        return False


class CaptureDB:
    def __init__(self, fail=False, down=False, returning=True):
        self.fail, self.down, self.returning = fail, down, returning
        self.sql: list[tuple[str, dict]] = []

    def begin_nested(self):
        return _Nested(self.down)

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.sql.append((sql, params or {}))
        if self.fail and "INSERT INTO lessons" in sql:
            raise RuntimeError("relation lessons does not exist")
        if "settings->'dlp'" in sql:
            return SimpleNamespace(scalar=lambda: {"enabled": True, "mode": "mask"})
        new = uuid.uuid4() if self.returning else None
        return SimpleNamespace(scalar=lambda: new)


async def test_capture_masks_and_emits():
    db = CaptureDB()
    svc._dlp.clear()
    lid = await svc.capture(
        db,
        tenant_id=T,
        agent_id=A,
        source="correction",
        input_text="mail me at ana@x.dev",
        expected="x",
        key="k1",
    )
    assert lid is not None
    insert = next(p for s, p in db.sql if "INSERT INTO lessons" in s)
    assert "ana@x.dev" not in insert["input_text"]
    assert insert["capture_key"] == "k1"
    assert any(
        "event_outbox" in s and p.get("e") == "lesson.captured" for s, p in db.sql
    )


async def test_repeat_capture_is_a_no_op_without_an_event():
    db = CaptureDB(returning=False)
    assert (
        await svc.capture(db, tenant_id=T, agent_id=A, source="thumbs", key="k") is None
    )
    assert not any("event_outbox" in s for s, _ in db.sql)


@pytest.mark.parametrize(
    "db", [CaptureDB(fail=True), CaptureDB(down=True), SimpleNamespace()]
)
async def test_capture_never_raises(db):
    svc._dlp.clear()
    assert await svc.capture(db, tenant_id=T, agent_id=A, source="thumbs") is None


async def test_unknown_source_and_missing_ids_are_ignored():
    db = CaptureDB()
    assert await svc.capture(db, tenant_id=T, agent_id=A, source="made_up") is None
    assert await svc.capture(db, tenant_id=None, agent_id=A, source="thumbs") is None
    assert db.sql == []


async def test_action_lesson_reads_the_run_input():
    db = CaptureDB()
    action = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=T,
        agent_id=A,
        execution_id=uuid.uuid4(),
        intent="set it",
        arguments={"value": 5},
        tool_name="sample_plant",
        agent_config_hash="h",
    )
    assert await svc.capture_action(db, action, "harm", note="it broke") is not None
    insert = next(p for s, p in db.sql if "INSERT INTO lessons" in s)
    assert insert["source"] == "harm" and insert["tool_name"] == "sample_plant"
    assert insert["capture_key"].startswith("action:")


def test_feedback_source_rules():
    assert svc._feedback_source(1, None) == "positive"
    assert svc._feedback_source(-1, None) == "thumbs"
    assert svc._feedback_source(-1, "say 5") == "correction"


# clustering


class Store:
    def __init__(self, lessons, agents):
        self.lessons = lessons
        self.agents = agents
        self.clusters: list = []
        self.suites: list = []
        self.cases: list = []
        self.events: list = []


class TickDB:
    def __init__(self, store: Store):
        self.store = store
        self.commits = 0

    def add(self, obj):
        bucket = {
            LessonCluster: self.store.clusters,
            EvalSuite: self.store.suites,
            EvalCase: self.store.cases,
        }.get(type(obj))
        if bucket is not None:
            bucket.append(obj)

    async def delete(self, obj):
        self.store.lessons.remove(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "event_outbox" in sql:
            self.store.events.append(params)
            return SimpleNamespace()
        entity = stmt.column_descriptions[0]["entity"]
        rows: list = []
        if entity is Lesson and "lessons.cluster_id IS NULL" in sql:
            rows = [x for x in self.store.lessons if x.cluster_id is None]
        elif entity is Lesson:
            rows = [x for x in self.store.lessons if x.case_id is None]
            cid = stmt.whereclause.compile().params
            want = [v for v in cid.values() if isinstance(v, uuid.UUID)]
            rows = [x for x in rows if x.cluster_id in want]
        elif entity is Agent:
            rows = self.store.agents
        elif entity is LessonCluster:
            rows = list(self.store.clusters)
        elif entity is EvalSuite:
            rows = list(self.store.suites)
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: list(rows)),
            scalar_one_or_none=lambda: rows[0] if rows else None,
        )


async def test_cluster_tick_groups_similar_lessons_and_suggests_cases():
    agent = Agent(id=A, tenant_id=T, name="Pricer", creator_id=uuid.uuid4())
    l1 = _lesson()
    l2 = _lesson(input_text="what is the price of copper today??")
    l3 = _lesson(
        source="thumbs", expected=None, input_text="How do I reset my password?"
    )
    store = Store([l1, l2, l3], [agent])
    db = TickDB(store)
    with patch.object(svc, "_default_model", AsyncMock(return_value=None)):
        out = await svc.cluster_tick(db)
    assert out["lessons"] == 3
    assert len(store.clusters) == 2
    price = next(c for c in store.clusters if c.count == 2)
    assert l1.cluster_id == l2.cluster_id == price.id
    assert price.severity == "medium" and price.negative_count == 2
    assert price.title.startswith("Wrong answers about")
    # two corrections earn suggested cases in a new, non-gating improvement suite
    assert len(store.cases) == 2 and all(c.state == "suggested" for c in store.cases)
    assert (
        store.suites[0].name == svc.IMPROVEMENT_SUITE
        and store.suites[0].gating is False
    )
    assert {c.source_lesson_id for c in store.cases} == {l1.id, l2.id}
    assert out["clusters_opened"] == 2 and len(store.events) == 2

    # a second run reads nothing old and changes nothing
    again = await svc.cluster_tick(db)
    assert again["lessons"] == 0 and len(store.clusters) == 2

    # a later similar lesson joins the same group
    l4 = _lesson(input_text="copper price today?")
    store.lessons.append(l4)
    with patch.object(svc, "_default_model", AsyncMock(return_value=None)):
        await svc.cluster_tick(db)
    assert l4.cluster_id == price.id and price.count == 3


class OrderDB(TickDB):
    """Fails like Postgres when a lesson points at a cluster that was never flushed."""

    def __init__(self, store: Store):
        super().__init__(store)
        self.flushed: set = set()

    async def flush(self):
        for x in self.store.lessons:
            if x.cluster_id is not None and x.cluster_id not in self.flushed:
                raise AssertionError("lessons_cluster_id_fkey")
        self.flushed |= {c.id for c in self.store.clusters}


async def test_new_clusters_are_written_before_lessons_point_at_them():
    agent = Agent(id=A, tenant_id=T, name="Pricer", creator_id=uuid.uuid4())
    other = _lesson(
        source="thumbs", expected=None, input_text="How do I reset my password?"
    )
    store = Store([_lesson(), other], [agent])
    db = OrderDB(store)
    with patch.object(svc, "_default_model", AsyncMock(return_value=None)):
        out = await svc.cluster_tick(db)
    assert out["lessons"] == 2 and len(store.clusters) == 2
    assert all(c.id in db.flushed for c in store.clusters)


async def test_lessons_of_a_deleted_agent_are_dropped():
    store = Store([_lesson()], [])
    db = TickDB(store)
    out = await svc.cluster_tick(db)
    assert out["lessons"] == 0 and store.lessons == [] and store.clusters == []


async def test_titles_fall_back_when_the_model_fails():
    agent = Agent(id=A, tenant_id=T, name="Pricer", creator_id=uuid.uuid4())
    store = Store([_lesson()], [agent])
    db = TickDB(store)
    with (
        patch.object(svc, "_default_model", AsyncMock(return_value="m")),
        patch.object(svc, "_title", AsyncMock(side_effect=RuntimeError("no key"))),
    ):
        await svc.cluster_tick(db)
    assert store.clusters[0].title.startswith("Wrong answers about")


async def test_titles_from_the_model_are_used():
    agent = Agent(id=A, tenant_id=T, name="Pricer", creator_id=uuid.uuid4())
    store = Store([_lesson()], [agent])
    db = TickDB(store)
    with (
        patch.object(svc, "_default_model", AsyncMock(return_value="m")),
        patch.object(svc, "_title", AsyncMock(return_value="Uses last month's price")),
    ):
        out = await svc.cluster_tick(db)
    assert store.clusters[0].title == "Uses last month's price" and out["titled"] == 1


def test_fixed_group_reopens_on_a_new_mistake():
    c = LessonCluster(
        id=uuid.uuid4(),
        tenant_id=T,
        agent_id=A,
        signature="s",
        count=1,
        negative_count=1,
        severity="low",
        trend=[],
        state="fixed",
        meta={},
    )
    svc._apply(c, _lesson())
    assert c.state == "open" and c.count == 2
    svc._apply(c, _lesson(source="positive", polarity="positive"))
    assert c.negative_count == 2


# suggested case state


def test_accepting_never_turns_the_suite_into_a_gate():
    case = SimpleNamespace(state="suggested")
    suite = SimpleNamespace(gating=False)
    svc._set_state(case, suite, "accept")
    assert case.state == "accepted" and suite.gating is False
    with pytest.raises(svc.LessonError):
        svc._set_state(SimpleNamespace(state="accepted"), suite, "drop")


async def test_owner_switches_the_gate_and_others_cannot():
    agent = Agent(id=A, tenant_id=T, name="Pricer", creator_id=uuid.uuid4())
    suite = SimpleNamespace(id=uuid.uuid4(), gating=False)
    db = SimpleNamespace(commit=AsyncMock())
    state = {"gating": True, "failing": 2}
    with (
        patch.object(svc, "_agent", AsyncMock(return_value=agent)),
        patch.object(svc, "_find_suite", AsyncMock(return_value=suite)),
        patch.object(svc, "gate_state", AsyncMock(return_value=state)),
        patch.object(svc, "can_manage", AsyncMock(return_value=True)),
    ):
        assert await svc.set_gate(db, _user(), A, True) == state
    assert suite.gating is True
    with (
        patch.object(svc, "_agent", AsyncMock(return_value=agent)),
        patch.object(svc, "can_manage", AsyncMock(return_value=False)),
    ):
        with pytest.raises(svc.LessonError) as e:
            await svc.set_gate(db, _user(), A, False)
    assert e.value.status == 403


async def test_gate_needs_tests_to_turn_on():
    agent = Agent(id=A, tenant_id=T, name="Pricer", creator_id=uuid.uuid4())
    with (
        patch.object(svc, "_agent", AsyncMock(return_value=agent)),
        patch.object(svc, "_find_suite", AsyncMock(return_value=None)),
        patch.object(svc, "can_manage", AsyncMock(return_value=True)),
    ):
        with pytest.raises(svc.LessonError) as e:
            await svc.set_gate(SimpleNamespace(), _user(), A, True)
    assert e.value.code == "NO_TESTS"


# retention, erase, wiring


def test_retention_days_bounds():
    assert svc.retention_days(None) == 180
    assert svc.retention_days({"improvements": {"retention_days": 2}}) == 7
    assert svc.retention_days({"improvements": {"retention_days": "90"}}) == 90
    assert svc.retention_days({"improvements": {"retention_days": "x"}}) == 180


async def test_purge_runs_bounded_batches_per_table():
    calls = []

    class DB:
        async def execute(self, sql, params):
            calls.append((str(sql), params))
            n = 10 if len(calls) == 1 else 3
            return SimpleNamespace(rowcount=n)

        async def commit(self):
            return None

    out = await svc.purge_retention(DB(), batch=10)
    assert out == {"lessons": 13, "feedback": 3, "clusters": 3}
    assert all("LIMIT :batch" in s and "retention_days" in s for s, _ in calls)


def test_erase_covers_feedback_lessons_proposals_and_cases():
    sql = " ".join(str(s) for s in svc.ERASE_SQL)
    for table in ("feedback", "lessons", "improvement_proposals", "eval_cases"):
        assert table in sql


def test_capabilities_and_events_are_catalogued():
    from app.services import events

    for cap in (
        "improvements.view",
        "improvements.propose",
        "improvements.approve",
        "feedback.give",
    ):
        assert cap in caps.KEYS
    for role in ("user", "creator"):
        assert "feedback.give" in caps.ROLE_DEFAULTS[role]
    assert "lesson.captured" in events.CATALOG and "cluster.opened" in events.CATALOG


def test_routes_and_jobs_exist():
    paths = {(r.path, tuple(sorted(r.methods))) for r in router.router.routes}
    for path, method in [
        ("/api/improvements/feedback", "POST"),
        ("/api/improvements/overview", "GET"),
        ("/api/improvements/agents/{agent_id}", "GET"),
        ("/api/improvements/clusters/{cluster_id}", "GET"),
        ("/api/improvements/clusters/{cluster_id}/dismiss", "POST"),
        ("/api/improvements/lessons", "GET"),
        ("/api/improvements/lessons", "POST"),
        ("/api/improvements/cases/{case_id}/accept", "POST"),
        ("/api/improvements/cases/{case_id}/drop", "POST"),
        ("/api/improvements/cases/{case_id}", "PATCH"),
        ("/api/improvements/cases/bulk", "POST"),
        ("/api/improvements/agents/{agent_id}/gate", "PUT"),
    ]:
        assert (path, (method,)) in paths
    assert callable(scheduler.group_lessons) and callable(scheduler.lesson_retention)


async def test_feedback_route_maps_errors():
    async def boom(db, user, body):
        raise svc.LessonError("rating must be 1 or -1.", 400, "BAD_RATING")

    bg = SimpleNamespace(add_task=lambda *a, **k: None)
    with patch.object(svc, "give_feedback", boom):
        resp = await router.give_feedback(
            router.FeedbackBody(rating=3), bg, SimpleNamespace(tenant_id=T), None
        )
    assert resp.status_code == 400


async def test_feedback_route_groups_soon_when_a_lesson_was_made():
    added = []

    async def ok(db, user, body):
        return {"id": "f", "lesson_id": "l"}

    bg = SimpleNamespace(add_task=lambda fn, *a: added.append(fn))
    with patch.object(svc, "give_feedback", ok):
        resp = await router.give_feedback(
            router.FeedbackBody(rating=-1), bg, SimpleNamespace(tenant_id=T), None
        )
    assert resp.status_code == 201 and added == [svc.cluster_soon]


async def test_cluster_soon_is_debounced_and_swallows_errors():
    svc._soon.clear()

    @asynccontextmanager
    async def lock(key):
        raise RuntimeError("database is down")
        yield  # pragma: no cover

    with patch("app.core.scheduler.advisory_lock", lock):
        await svc.cluster_soon(T)
        await svc.cluster_soon(T)


# feedback


class FeedbackDB:
    def __init__(self, agent, existing=None):
        self.agent, self.existing = agent, existing
        self.added: list = []
        self.sql: list[str] = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def execute(self, stmt, params=None):
        self.sql.append(str(stmt))
        ent = getattr(stmt, "column_descriptions", [{}])[0].get("entity")
        row = self.agent if ent is Agent else self.existing
        return SimpleNamespace(scalar_one_or_none=lambda: row)


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=T, role="admin")


async def test_thumbs_down_with_a_correction_becomes_a_correction_lesson():
    agent = Agent(id=A, tenant_id=T, name="Pricer", creator_id=uuid.uuid4())
    db = FeedbackDB(agent)
    ex = uuid.uuid4()
    target = {
        "agent_id": A,
        "input_message": "price?",
        "output_message": "old",
        "config_hash": "h",
    }
    cap = AsyncMock(return_value=uuid.uuid4())
    with (
        patch.object(svc, "_execution_target", AsyncMock(return_value=target)),
        patch.object(svc, "capture", cap),
        patch.object(svc, "visible_agents", AsyncMock(return_value=None)),
    ):
        out = await svc.give_feedback(
            db,
            _user(),
            {"execution_id": str(ex), "rating": -1, "correction": " 8,240 "},
        )
    kw = cap.call_args.kwargs
    assert kw["source"] == "correction" and kw["expected"] == "8,240"
    assert kw["input_text"] == "price?" and kw["agent_config_hash"] == "h"
    assert out["lesson_id"] and out["can_view_lessons"] is True
    fb = db.added[0]
    assert fb.rating == -1 and fb.correction == "8,240" and fb.execution_id == ex


async def test_rating_again_updates_the_same_feedback():
    agent = Agent(id=A, tenant_id=T, name="Pricer", creator_id=uuid.uuid4())
    old = SimpleNamespace(id=uuid.uuid4(), rating=-1, correction=None)
    db = FeedbackDB(agent, existing=old)
    cap = AsyncMock(return_value=uuid.uuid4())
    forget = AsyncMock(return_value=1)
    revise = AsyncMock(return_value=None)
    user, ex = _user(), uuid.uuid4()
    with (
        patch.object(svc, "_execution_target", AsyncMock(return_value={"agent_id": A})),
        patch.object(svc, "capture", cap),
        patch.object(svc, "revise_feedback_lesson", revise),
        patch.object(svc, "forget_feedback_lessons", forget),
        patch.object(svc, "visible_agents", AsyncMock(return_value=set())),
    ):
        out = await svc.give_feedback(db, user, {"execution_id": str(ex), "rating": 1})
    assert db.added == [] and old.rating == 1
    key = L.capture_key("fb", str(ex), user.id)
    # thumbs down to up flips the polarity, so the old lesson is replaced
    revise.assert_awaited_once_with(db, agent, key, "positive", None)
    forget.assert_awaited_once_with(db, T, key)
    assert cap.call_args.kwargs["source"] == "positive"
    assert out["can_view_lessons"] is False


async def test_a_correction_after_a_thumbs_down_keeps_one_lesson():
    agent = Agent(id=A, tenant_id=T, name="Pricer", creator_id=uuid.uuid4())
    old = SimpleNamespace(id=uuid.uuid4(), rating=-1, correction=None)
    db = FeedbackDB(agent, existing=old)
    kept = uuid.uuid4()
    cap = AsyncMock(return_value=uuid.uuid4())
    forget = AsyncMock(return_value=1)
    with (
        patch.object(svc, "_execution_target", AsyncMock(return_value={"agent_id": A})),
        patch.object(svc, "capture", cap),
        patch.object(svc, "revise_feedback_lesson", AsyncMock(return_value=kept)),
        patch.object(svc, "forget_feedback_lessons", forget),
        patch.object(svc, "visible_agents", AsyncMock(return_value=None)),
    ):
        out = await svc.give_feedback(
            db,
            _user(),
            {"execution_id": str(uuid.uuid4()), "rating": -1, "correction": "8,240"},
        )
    assert out["lesson_id"] == str(kept)
    cap.assert_not_awaited()
    forget.assert_not_awaited()


async def test_revise_turns_a_grouped_thumbs_down_into_a_correction(monkeypatch):
    agent = Agent(id=A, tenant_id=T, name="Pricer", creator_id=uuid.uuid4())
    case = EvalCase(
        id=uuid.uuid4(), name="Thumbs down: x", state="suggested", assertions=[]
    )
    c = LessonCluster(
        id=uuid.uuid4(),
        tenant_id=T,
        agent_id=A,
        count=2,
        negative_count=2,
        severity="low",
        state="open",
        trend=[],
        meta={"sources": {"thumbs": 2}, "cases": 1},
    )
    x = _lesson(source="thumbs", expected=None, cluster_id=c.id, case_id=case.id)
    db = ForgetDB([x], {c.id: c, case.id: case})
    monkeypatch.setattr(svc, "tenant_dlp", AsyncMock(return_value=None))
    suggest = AsyncMock(return_value=0)
    monkeypatch.setattr(svc, "_suggest", suggest)
    got = await svc.revise_feedback_lesson(db, agent, "k", "correction", "Say 8,240")
    assert got == x.id and x.source == "correction" and x.expected == "Say 8,240"
    assert c.count == 2 and c.meta["sources"] == {"thumbs": 1, "correction": 1}
    assert c.severity == "medium"
    assert case.reference_output == "Say 8,240" and case not in db.deleted
    suggest.assert_awaited_once()

    # a thumbs up is the other way round, the caller replaces the lesson
    db = ForgetDB([x], {c.id: c})
    assert await svc.revise_feedback_lesson(db, agent, "k", "positive", None) is None


class ForgetDB:
    def __init__(self, lessons, objects):
        self.lessons, self.objects = lessons, objects
        self.deleted: list = []

    async def execute(self, stmt, params=None):
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: list(self.lessons))
        )

    async def get(self, model, key):
        return self.objects.get(key)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        return None


async def test_a_thumbs_down_turned_correction_leaves_its_group():
    day = datetime.now(timezone.utc)
    case = SimpleNamespace(id=uuid.uuid4(), state="suggested")
    c = LessonCluster(
        id=uuid.uuid4(),
        tenant_id=T,
        agent_id=A,
        count=2,
        negative_count=2,
        severity="medium",
        state="open",
        trend=[{"day": day.date().isoformat(), "count": 2}],
        meta={"sources": {"thumbs": 1, "correction": 1}, "cases": 1},
    )
    thumbs = _lesson(source="thumbs", expected=None, cluster_id=c.id, case_id=case.id)
    db = ForgetDB([thumbs], {c.id: c, case.id: case})
    assert await svc.forget_feedback_lessons(db, T, "k") == 1
    assert thumbs in db.deleted and case in db.deleted and c not in db.deleted
    assert c.count == 1 and c.negative_count == 1
    assert c.meta["sources"] == {"correction": 1} and c.meta["cases"] == 0
    assert c.trend == [{"day": day.date().isoformat(), "count": 1}]

    # the last lesson out takes an open group with it
    alone = LessonCluster(
        id=uuid.uuid4(),
        tenant_id=T,
        agent_id=A,
        count=1,
        negative_count=1,
        state="open",
        trend=[],
        meta={"sources": {"thumbs": 1}},
    )
    x = _lesson(source="thumbs", expected=None, cluster_id=alone.id)
    db = ForgetDB([x], {alone.id: alone})
    await svc.forget_feedback_lessons(db, T, "k")
    assert alone in db.deleted and x in db.deleted


@pytest.mark.parametrize(
    "body",
    [{"rating": 0}, {"rating": -1}, {"rating": 1, "execution_id": "not-an-id"}],
)
async def test_feedback_rejects_bad_input(body):
    with pytest.raises(svc.LessonError):
        await svc.give_feedback(FeedbackDB(None), _user(), body)


async def test_someone_elses_run_is_hidden_without_access():
    row = {"id": uuid.uuid4(), "tenant_id": T, "agent_id": A, "user_id": uuid.uuid4()}

    class DB:
        async def execute(self, stmt, params=None):
            return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))

    with patch.object(svc, "visible_agents", AsyncMock(return_value=set())):
        with pytest.raises(svc.LessonError) as e:
            await svc._execution_target(DB(), _user(), row["id"])
    assert e.value.status == 404


async def test_capture_counts_by_source_and_a_broken_metric_is_harmless():
    from app.core import telemetry

    seen = []

    class Metric:
        def labels(self, source):
            seen.append(source)
            return SimpleNamespace(inc=lambda: None)

    with patch.object(
        telemetry, "improvement_lessons_captured_total", Metric(), create=True
    ):
        assert (
            await svc.capture(CaptureDB(), tenant_id=T, agent_id=A, source="harm")
            is not None
        )
    assert seen == ["harm"]
    with patch.object(
        telemetry, "improvement_lessons_captured_total", None, create=True
    ):
        assert (
            await svc.capture(CaptureDB(), tenant_id=T, agent_id=A, source="harm")
            is not None
        )
