"""Governed self-improvement: allow list, proof bar, watch rules, release, rollback, SoD, budget, kill switch."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core import capabilities as caps
from app.core import notifications as notif
from app.core import scheduler
from app.routers import approvals as approvals_router
from app.routers import improvements_proposals as router
from app.schemas.connectors import ApprovalSignoffRequest
from app.services import events
from app.services import improvement_rules as R
from app.services import improvements as svc
from models.approval import Approval, ApprovalStatus
from models.user import UserRole

pytestmark = pytest.mark.asyncio

TENANT = uuid.uuid4()
PROMPT = (
    "You are a friendly temperature conversion helper.\n"
    "Always give the answer in degrees Fahrenheit, whatever unit the user asks for.\n"
    "Keep every answer to one short sentence."
)


def _now():
    return datetime.now(timezone.utc)


def _user(role=UserRole.ADMIN, name="Ana"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        role=role,
        email=f"{name.lower()}@x.dev",
        full_name=name,
    )


def _state(**mc):
    return {
        "system_prompt": PROMPT,
        "model_config": {
            "model": "claude-haiku-4-5-20251001",
            "tools": ["calculator", "email_sender"],
            "risk_tier": "low",
            "tool_config": {"email_sender": {"require_approval": True}},
            **mc,
        },
    }


def _body(resp):
    return json.loads(resp.body)


# allow list


async def test_prompt_edit_changes_only_the_instructions():
    base = _state()
    new = R.apply_change(
        base,
        "prompt_edit",
        {
            "edits": [
                {
                    "find": "Always give the answer in degrees Fahrenheit, whatever unit the user asks for.",
                    "replace": "Give the answer in the unit the user asks for.",
                }
            ]
        },
    )
    assert "unit the user asks for" in new["system_prompt"]
    assert new["model_config"] == base["model_config"]


@pytest.mark.parametrize(
    "diff, msg",
    [
        ({"edits": [{"find": "not there", "replace": "x"}]}, "exactly once"),
        ({"edits": [{"find": "a", "replace": "b"}]}, "exactly once"),
        ({"edits": [{"find": PROMPT, "replace": "x" * 3000}]}, "never rewrites"),
        ({}, "needs edits"),
    ],
)
async def test_prompt_edit_refuses_rewrites_and_ambiguous_edits(diff, msg):
    with pytest.raises(R.ChangeRejected, match=msg):
        R.apply_change(_state(), "prompt_edit", diff)


async def test_examples_are_appended_and_merged_not_duplicated():
    base = _state()
    one = R.apply_change(
        base, "examples", {"examples": [{"input": "0 C in K", "output": "273.15 K"}]}
    )
    two = R.apply_change(
        one,
        "examples",
        {
            "examples": [
                {"input": "0 C in K", "output": "273.15 K."},
                {"input": "100 C in K", "output": "373.15 K"},
            ]
        },
    )
    assert two["system_prompt"].count(R.EXAMPLES_HEADER) == 1
    assert two["system_prompt"].count("Input: 0 C in K") == 1
    assert "373.15 K" in two["system_prompt"]


async def test_tool_config_never_removes_an_approval_or_unlocks():
    with pytest.raises(R.ChangeRejected, match="never removes an approval"):
        R.apply_change(
            _state(),
            "tool_config",
            {"tool": "email_sender", "set": {"require_approval": False}},
        )
    with pytest.raises(R.ChangeRejected, match="already uses"):
        R.apply_change(
            _state(), "tool_config", {"tool": "web_search", "set": {"max_calls": 2}}
        )
    with pytest.raises(R.ChangeRejected, match="Only these"):
        R.apply_change(
            _state(), "tool_config", {"tool": "calculator", "set": {"credentials": "x"}}
        )
    new = R.apply_change(
        _state(), "tool_config", {"tool": "calculator", "set": {"max_calls": 3}}
    )
    assert new["model_config"]["tool_config"]["calculator"] == {"max_calls": 3}


async def test_tool_set_adds_only_read_only_tools_one_at_a_time():
    ro = {"web_search"}
    new = R.apply_change(
        _state(), "tool_set", {"add": ["web_search"]}, read_only_tools=ro
    )
    assert "web_search" in new["model_config"]["tools"]
    with pytest.raises(R.ChangeRejected, match="Tools that act"):
        R.apply_change(
            _state(), "tool_set", {"add": ["twilio_sms"]}, read_only_tools=ro
        )
    with pytest.raises(R.ChangeRejected, match="One tool"):
        R.apply_change(
            _state(),
            "tool_set",
            {"add": ["web_search"], "remove": ["calculator"]},
            read_only_tools=ro,
        )


async def test_model_switch_stays_inside_the_tier():
    ok = R.apply_change(
        _state(),
        "model",
        {"model": "gpt-4o-mini"},
        model_ok=lambda m: m.startswith("gpt"),
    )
    assert ok["model_config"]["model"] == "gpt-4o-mini"
    with pytest.raises(R.ChangeRejected, match="risk tier"):
        R.apply_change(
            _state(), "model", {"model": "claude-opus"}, model_ok=lambda m: False
        )


async def test_guard_refuses_touching_limits_tier_or_anything_else():
    base = _state()
    sneaky = {
        "system_prompt": PROMPT,
        "model_config": {
            **base["model_config"],
            "risk_tier": "low",
            "max_iterations": 99,
        },
    }
    with pytest.raises(R.ChangeRejected, match="max_iterations"):
        R.guard(base, sneaky, "tool_config")
    other = {"system_prompt": PROMPT + " more", "model_config": base["model_config"]}
    with pytest.raises(R.ChangeRejected, match="may not edit the instructions"):
        R.guard(base, other, "model")


async def test_kinds_depend_on_the_agent_type():
    pipe = {
        "system_prompt": "",
        "model_config": {"mode": "pipeline", "pipeline_config": {"nodes": []}},
    }
    with pytest.raises(R.ChangeRejected, match="does not apply"):
        R.apply_change(pipe, "prompt_edit", {"append": "x"})
    with pytest.raises(R.ChangeRejected, match="Unknown"):
        R.apply_change(_state(), "limits", {})


async def test_preview_marks_added_and_removed_lines():
    base = _state()
    new = R.apply_change(base, "prompt_edit", {"append": "Use Kelvin when asked."})
    pv = R.preview(base, new)
    assert pv["what"] == "instructions"
    assert {"op": "add", "text": "Use Kelvin when asked."} in pv["lines"]


# the proof bar


def _scores(cost=0.01, lat=1000, runs=20):
    return {"cost_usd": cost, "latency_ms": lat, "runs": runs}


async def test_bar_passes_a_clean_fix():
    ok, reasons = R.bar(
        fixed=2,
        broken=0,
        before=_scores(),
        after=_scores(),
        gating_ok=True,
        cost_margin=0.2,
        latency_margin=0.2,
    )
    assert ok and reasons == []


@pytest.mark.parametrize(
    "kw, word",
    [
        ({"fixed": 0}, "did not fix"),
        ({"broken": 1}, "broke 1 case"),
        ({"after": _scores(cost=0.013)}, "more per run"),
        ({"after": _scores(lat=1300)}, "slower"),
        ({"gating_ok": False}, "release tests"),
    ],
)
async def test_bar_refuses_anything_worse(kw, word):
    args = dict(
        fixed=1,
        broken=0,
        before=_scores(),
        after=_scores(),
        gating_ok=None,
        cost_margin=0.2,
        latency_margin=0.2,
    )
    args.update(kw)
    ok, reasons = R.bar(**args)
    assert not ok and any(word in r for r in reasons)


async def test_speed_is_not_judged_on_a_handful_of_runs():
    ok, _ = R.bar(
        fixed=1,
        broken=0,
        before=_scores(runs=6),
        after=_scores(lat=3000, runs=6),
        gating_ok=None,
        cost_margin=0.2,
        latency_margin=0.2,
    )
    assert ok


async def test_speed_is_judged_only_on_runs_timed_side_by_side():
    fresh = [
        {"status": "completed", "duration_ms": 1000, "kind": "case"} for _ in range(4)
    ]
    cached = [
        {"status": "completed", "duration_ms": 400, "kind": "case", "timed": False}
        for _ in range(8)
    ]
    s = R.summarise(fresh + cached)
    assert s["runs"] == 12 and s["timed_runs"] == 4
    assert s["timed_latency_ms"] == 1000 and s["latency_ms"] == 400

    # cached answers made the old version look a third faster, that is not judged
    before = {"runs": 11, "latency_ms": 1500, "timed_runs": 4, "timed_latency_ms": 1900}
    after = {"runs": 11, "latency_ms": 1997, "timed_runs": 4, "timed_latency_ms": 1990}
    ok, reasons = R.bar(
        fixed=4,
        broken=0,
        before=before,
        after=after,
        gating_ok=None,
        cost_margin=0.2,
        latency_margin=0.2,
    )
    assert ok, reasons

    # enough side by side runs that really are slower still fail
    before = {**before, "timed_runs": 12, "timed_latency_ms": 1000}
    after = {**after, "timed_runs": 12, "timed_latency_ms": 1400}
    ok, reasons = R.bar(
        fixed=4,
        broken=0,
        before=before,
        after=after,
        gating_ok=None,
        cost_margin=0.2,
        latency_margin=0.2,
    )
    assert not ok and "40% slower" in reasons[0]


def _res(item, bpass, apass, out_b="F", out_a="K"):
    return {
        "item": item,
        "before": {
            "passed": bpass,
            "score": 1.0 if bpass else 0.0,
            "kind": "case",
            "status": "completed",
            "cost": 0.001,
            "duration_ms": 900,
            "output": out_b,
        },
        "after": {
            "passed": apass,
            "score": 1.0 if apass else 0.0,
            "kind": "case",
            "status": "completed",
            "cost": 0.001,
            "duration_ms": 900,
            "output": out_a,
        },
        "why": None if apass else "Output does not contain 273.15",
    }


def _lesson(text="0 C in K"):
    return SimpleNamespace(id=uuid.uuid4(), input_text=text)


async def test_proof_counts_fixed_and_is_never_shown_when_anything_breaks():
    lsn = _lesson()
    fix = {
        "id": "c1",
        "name": "Kelvin",
        "input": "0 C in K",
        "lesson_ids": [str(lsn.id)],
        "suite_id": "s",
    }
    good = {
        "id": "c2",
        "name": "Good",
        "input": "212 F",
        "lesson_ids": [],
        "suite_id": "s",
    }
    s = R.settings_for({}, None)
    proof = svc.build_proof(
        [_res(fix, False, True), _res(good, True, True)], [], [lsn], {}, s
    )
    assert proof["passed_bar"] and len(proof["fixed"]) == 1 and proof["broken"] == []
    assert proof["examples"][0]["verdict"] == "fixed"
    broke = svc.build_proof(
        [_res(fix, False, True), _res(good, True, False)], [], [lsn], {}, s
    )
    assert not broke["passed_bar"]
    assert broke["broken"][0]["name"] == "Good"


async def test_a_replay_that_fails_where_it_worked_counts_as_broken():
    lsn = _lesson()
    fix = {
        "id": "c1",
        "name": "Kelvin",
        "input": "x",
        "lesson_ids": [str(lsn.id)],
        "suite_id": "s",
    }
    rp = [
        {
            "input": {
                "input": "real input",
                "output": "fine",
                "cost": 0.001,
                "duration_ms": 800,
                "tool_calls": 1,
            },
            "after": {
                "status": "failed",
                "error": "boom",
                "held": [{"tool": "valve"}],
                "cost": 0.0,
                "duration_ms": 10,
            },
        }
    ]
    proof = svc.build_proof(
        [_res(fix, False, True)], rp, [lsn], {}, R.settings_for({}, None)
    )
    assert not proof["passed_bar"]
    assert proof["replay"] == {"sampled": 1, "changed": 0, "watching_effects": 1}
    assert proof["broken"][0]["case_id"] is None


async def test_gating_suite_below_threshold_fails_the_bar():
    lsn = _lesson()
    fix = {
        "id": "c1",
        "name": "Kelvin",
        "input": "x",
        "lesson_ids": [str(lsn.id)],
        "suite_id": "g",
    }
    bad = {"id": "c2", "name": "Gate", "input": "y", "lesson_ids": [], "suite_id": "g"}
    results = [_res(fix, False, True), _res(bad, False, False)]
    proof = svc.build_proof(results, [], [lsn], {"g": 0.9}, R.settings_for({}, None))
    assert proof["gating"]["passed"] is False and not proof["passed_bar"]


# watch rules


def _m(**kw):
    base = {
        "runs": 50,
        "failures": 1,
        "thumbs_total": 10,
        "thumbs_down": 1,
        "cost_avg": 0.01,
        "scored": 0,
        "accurate": 0,
        "cluster_lessons": 0,
    }
    base.update(kw)
    return base


async def test_watch_is_quiet_when_nothing_got_worse():
    assert R.watch_reasons(_m(), _m(), min_runs=10, cost_margin=0.2) == []


@pytest.mark.parametrize(
    "new, word",
    [
        (_m(failures=10), "Failed runs"),
        (_m(thumbs_total=3, thumbs_down=3), "Thumbs down"),
        (_m(cost_avg=0.02), "Cost per run"),
        (_m(drift=["latency"]), "drift alert"),
        (_m(cluster_lessons=3), "came back"),
        (_m(scored=10, accurate=2), "accuracy"),
    ],
)
async def test_watch_names_what_got_worse(new, word):
    old = _m(scored=10, accurate=9)
    reasons = R.watch_reasons(old, new, min_runs=10, cost_margin=0.2)
    assert any(word in r for r in reasons), reasons


async def test_watch_needs_enough_runs_before_judging_failures_and_cost():
    new = _m(runs=3, failures=2, cost_avg=0.5)
    assert R.watch_reasons(_m(), new, min_runs=10, cost_margin=0.2) == []


async def test_watch_ends_on_time_or_run_count():
    now = _now()
    assert R.watch_done(5, 200, now, now - timedelta(seconds=1))
    assert R.watch_done(200, 200, now, now + timedelta(days=1))
    assert not R.watch_done(5, 200, now, now + timedelta(days=1))


async def test_settings_merge_tenant_then_agent_and_clamp():
    s = R.settings_for(
        {
            "improvements": {
                "proofs_per_day": 5,
                "cost_margin": 9,
                "agents": {"a": {"watch_runs": 7}},
            }
        },
        "a",
    )
    assert s["proofs_per_day"] == 5 and s["cost_margin"] == 5 and s["watch_runs"] == 7
    assert R.settings_for({}, "b")["watch_runs"] == 200


async def test_replay_sample_is_stratified_and_distinct():
    rows = [{"input": f"price of gold {i}"} for i in range(20)] + [
        {"input": "weather in Oslo"}
    ] * 3
    rows += [{"input": "x " * 300}]
    got = R.stratify(rows, 5)
    texts = [r["input"] for r in got]
    assert len(got) == 5 and "weather in Oslo" in texts and ("x " * 300) in texts


async def test_budget_reason_is_plain():
    s = R.settings_for(
        {"improvements": {"proofs_per_day": 2, "tokens_per_day": 100}}, None
    )
    assert svc.budget_reason({"proofs": 1, "tokens": 0}, s) is None
    assert "2 proofs a day" in svc.budget_reason({"proofs": 2, "tokens": 0}, s)
    assert "tokens" in svc.budget_reason({"proofs": 0, "tokens": 100}, s)


async def test_automatic_proposals_leave_half_the_budget_for_people():
    s = R.settings_for(
        {"improvements": {"proofs_per_day": 20, "tokens_per_day": 400_000}}, None
    )
    # automatic proofs spent far past the limit, a person's fix still has the other half
    used = {
        "proofs": 9,
        "tokens": 2_879_136,
        "auto_proofs": 8,
        "auto_tokens": 2_875_896,
    }
    assert svc.room(used, s) == {
        "proofs": 20 - 1 - 8,
        "tokens": 400_000 - 3_240 - 200_000,
    }
    assert svc.budget_reason(used, s) is None
    why = svc.budget_reason(used, s, automatic=True)
    assert "Automatic proposals have used their half" in why
    assert "Fixes a person asks for still run" in why

    # automatic proofs under their half count in full against everyone
    used = {"proofs": 3, "tokens": 150_000, "auto_proofs": 3, "auto_tokens": 150_000}
    assert svc.room(used, s, automatic=True) == {"proofs": 7, "tokens": 50_000}
    assert svc.room(used, s) == {"proofs": 17, "tokens": 250_000}

    # people use the rest, then everyone waits
    used = {"proofs": 20, "tokens": 300_000, "auto_proofs": 10, "auto_tokens": 100_000}
    assert "20 proofs a day" in svc.budget_reason(used, s)


async def test_a_proof_stops_when_the_day_is_spent(monkeypatch):
    s = R.settings_for({"improvements": {"tokens_per_day": 1000}}, None)

    class DB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(svc, "_session", lambda: DB())
    monkeypatch.setattr(svc, "settings_for", AsyncMock(return_value=s))
    monkeypatch.setattr(
        svc,
        "usage_today",
        AsyncMock(
            return_value={
                "proofs": 1,
                "tokens": 999,
                "auto_proofs": 0,
                "auto_tokens": 0,
            }
        ),
    )
    assert await svc._budget_stop(uuid.uuid4(), uuid.uuid4(), False) is None
    svc.usage_today.return_value = {
        "proofs": 1,
        "tokens": 1000,
        "auto_proofs": 0,
        "auto_tokens": 0,
    }
    assert await svc._budget_stop(uuid.uuid4(), uuid.uuid4(), False) == svc.BUDGET_STOP


# service flows with a fake store


class Res:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self.rows))

    def first(self):
        return self.rows[0] if self.rows else None


class FakeDB:
    def __init__(self):
        self.added = []
        self.objs = {}
        self.commits = 0
        self.answer = lambda stmt: []

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        self.objs[obj.id] = obj

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None

    async def refresh(self, obj):
        return None

    async def get(self, model, key):
        return self.objs.get(key)

    async def execute(self, stmt, params=None):
        return Res(self.answer(stmt))


class Obj(SimpleNamespace):
    def __init__(self, **kw):
        kw.setdefault("id", uuid.uuid4())
        super().__init__(**kw)


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    author = _user(role=UserRole.CREATOR, name="Author")
    agent = Obj(
        tenant_id=TENANT,
        name="Temp helper",
        slug="temp-helper",
        creator_id=author.id,
        system_prompt=PROMPT,
        model_config_={"model": "m", "tools": []},
        status="active",
    )
    cluster = Obj(
        tenant_id=TENANT,
        agent_id=agent.id,
        title="Fahrenheit for Kelvin",
        state="open",
        count=4,
        severity="medium",
    )
    emitted, notes = [], []
    monkeypatch.setattr(svc, "model", lambda table: Obj)
    monkeypatch.setattr(svc, "get_agent", AsyncMock(return_value=agent))
    monkeypatch.setattr(svc, "get_cluster", AsyncMock(return_value=cluster))
    monkeypatch.setattr(svc, "current_hash", AsyncMock(return_value="h1"))
    monkeypatch.setattr(svc, "stopped", AsyncMock(return_value=None))
    monkeypatch.setattr(
        svc, "settings_for", AsyncMock(return_value=R.settings_for({}, None))
    )
    monkeypatch.setattr(svc, "kick", lambda: None)

    async def emit(db_, tenant_id, event_type, payload):
        emitted.append((event_type, payload))

    async def note(db_, **kw):
        notes.append(kw)

    monkeypatch.setattr(events, "emit", emit)
    monkeypatch.setattr(notif, "create_notification", note)
    return SimpleNamespace(
        db=db, author=author, agent=agent, cluster=cluster, events=emitted, notes=notes
    )


def _proposal(w, **kw):
    p = Obj(
        tenant_id=TENANT,
        agent_id=w.agent.id,
        cluster_id=w.cluster.id,
        base_config_hash="h1",
        change_kind="prompt_edit",
        diff={"append": "Use the unit the user asks for."},
        rationale="It answered in Fahrenheit.",
        risk="low",
        state="awaiting_approval",
        progress={},
        proof={
            "fixed": [{"lesson_id": "l", "title": "t"}],
            "broken": [],
            "passed_bar": True,
            "bar_reasons": [],
        },
        approval_id=None,
        released_revision_id=None,
        watch_until=None,
        watch_runs_target=0,
        watch_result=None,
        error=None,
        created_by=w.author.id,
        created_at=_now(),
        updated_at=_now(),
    )
    for k, v in kw.items():
        setattr(p, k, v)
    w.db.objs[p.id] = p
    return p


async def test_propose_refused_by_the_kill_switch(world, monkeypatch):
    monkeypatch.setattr(svc, "stopped", AsyncMock(return_value=svc.KILL_SWITCH_TEXT))
    monkeypatch.setattr(svc, "_has", AsyncMock(return_value=True))
    with pytest.raises(svc.ImprovementError) as e:
        await svc.propose(world.db, world.author, world.cluster.id)
    assert e.value.code == "KILL_SWITCH" and "kill switch" in e.value.message


async def test_propose_needs_the_capability_and_is_idempotent(world, monkeypatch):
    monkeypatch.setattr(svc, "_has", AsyncMock(return_value=False))
    with pytest.raises(svc.ImprovementError) as e:
        await svc.propose(world.db, world.author, world.cluster.id)
    assert e.value.status == 403
    monkeypatch.setattr(svc, "_has", AsyncMock(return_value=True))
    monkeypatch.setattr(svc, "active_proposal", AsyncMock(return_value=None))
    row = await svc.propose(world.db, world.author, world.cluster.id)
    assert row["state"] == "drafting" and row["progress"]["phase"] == "queued"
    assert world.cluster.state == "proposing"
    existing = world.db.added[-1]
    monkeypatch.setattr(svc, "active_proposal", AsyncMock(return_value=existing))
    again = await svc.propose(world.db, world.author, world.cluster.id)
    assert again["id"] == row["id"] and len(world.db.added) == 1


async def test_a_failing_proposal_never_goes_for_approval(world):
    p = _proposal(
        world,
        state="failed_proof",
        proof={
            "passed_bar": False,
            "bar_reasons": ["It broke 1 case that passed before."],
        },
    )
    with pytest.raises(svc.ImprovementError) as e:
        await svc.request_approval(world.db, p)
    assert e.value.code == "NOT_PROVEN" and "broke 1 case" in e.value.message
    assert not any(isinstance(x, Approval) for x in world.db.added)


async def test_request_approval_is_idempotent_and_labels_self_approval(
    world, monkeypatch
):
    world.db.objs[world.author.id] = world.author
    monkeypatch.setattr(svc, "someone_else_can_approve", AsyncMock(return_value=False))
    p = _proposal(world)
    out = await svc.request_approval(world.db, p)
    a = world.db.objs[uuid.UUID(out["approval_id"])]
    assert a.gate_kind == "improvement.release"
    assert a.policy == {
        "exclude_requester": False,
        "capability": "improvements.approve",
    }
    assert a.payload["self_approval"] == svc.SOLO_SELF_APPROVAL
    assert a.payload["proof"]["passed_bar"] is True
    again = await svc.request_approval(world.db, p)
    assert again == {"approval_id": out["approval_id"], "created": False}
    assert any(n["type"] == "improvement_ready" for n in world.notes)


async def test_author_refused_solo_and_sample_self_approve(world, monkeypatch):
    a = SimpleNamespace(
        tenant_id=TENANT,
        payload={
            "agent": {"id": str(world.agent.id)},
            "agent_creator_id": str(world.author.id),
        },
    )
    monkeypatch.setattr(svc, "someone_else_can_approve", AsyncMock(return_value=True))
    assert await svc.release_denial(world.db, world.author, a) == svc.AUTHOR_REFUSED
    other = _user(name="Grace")
    assert await svc.release_denial(world.db, other, a) is None
    monkeypatch.setattr(svc, "someone_else_can_approve", AsyncMock(return_value=False))
    assert await svc.release_denial(world.db, world.author, a) is None
    assert (
        await svc.self_approval_reason(world.db, world.author, world.agent)
        == svc.SOLO_SELF_APPROVAL
    )
    world.agent.slug = svc.SAMPLE_SLUG
    monkeypatch.setattr(svc, "someone_else_can_approve", AsyncMock(return_value=True))
    assert (
        await svc.self_approval_reason(world.db, world.author, world.agent)
        == svc.SAMPLE_SELF_APPROVAL
    )


async def test_signoff_route_refuses_the_author(world, monkeypatch):
    approval = Approval(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        title="Release a fix",
        payload={
            "proposal_id": "x",
            "agent": {"id": str(world.agent.id)},
            "agent_creator_id": str(world.author.id),
        },
        required_signoffs=1,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=world.author.id,
        gate_kind="improvement.release",
        policy={"exclude_requester": False, "capability": "improvements.approve"},
    )
    world.db.answer = lambda stmt: [approval]
    monkeypatch.setattr(svc, "someone_else_can_approve", AsyncMock(return_value=True))
    resp = await approvals_router.sign_off(
        str(approval.id),
        ApprovalSignoffRequest(decision="approve"),
        world.author,
        world.db,
    )
    assert resp.status_code == 403
    assert _body(resp)["error"]["error_code"] == "AUTHOR_CANNOT_APPROVE"
    assert "someone else" in _body(resp)["error"]["message"]
    assert approval.status == ApprovalStatus.pending

    resolved = AsyncMock()
    monkeypatch.setattr(svc, "on_release_resolved", resolved)
    monkeypatch.setattr(approvals_router, "_notify_resolved", AsyncMock())
    grace = _user(role=UserRole.CREATOR, name="Grace")

    async def has(db, user, cap):
        return user is not grace or cap != "improvements.approve"

    monkeypatch.setattr(caps, "has_capability", has)
    resp = await approvals_router.sign_off(
        str(approval.id), ApprovalSignoffRequest(decision="approve"), grace, world.db
    )
    err = _body(resp)["error"]
    assert resp.status_code == 403
    assert err["details"]["capability"] == "improvements.approve"
    assert "Approve improvements" in err["message"]

    async def has_all(db, user, cap):
        return True

    monkeypatch.setattr(caps, "has_capability", has_all)
    resp = await approvals_router.sign_off(
        str(approval.id), ApprovalSignoffRequest(decision="approve"), grace, world.db
    )
    assert resp.status_code == 200
    resolved.assert_awaited_once()


async def test_release_writes_an_improvement_revision_and_starts_the_watch(
    world, monkeypatch
):
    approver = _user(name="Grace")
    p = _proposal(world, state="approved")
    world.db.answer = lambda stmt: [world.agent]
    recorded = []

    async def record(db, agent, **kw):
        recorded.append(kw)
        return Obj()

    monkeypatch.setattr(svc, "_record", record)
    monkeypatch.setattr(svc, "_change_ctx", AsyncMock(return_value={}))
    monkeypatch.setattr(svc, "_start_gate_runs", AsyncMock())
    monkeypatch.setattr("app.core.audit.log_action", AsyncMock())
    await svc.release(world.db, p, approver)
    assert world.agent.system_prompt.endswith("Use the unit the user asks for.")
    assert recorded[0]["source"] == "improvement" and recorded[0]["proposal_id"] == p.id
    assert recorded[0]["previous"]["system_prompt"] == PROMPT
    assert p.state == "released" and p.watch_runs_target == 200
    assert p.watch_until > _now() + timedelta(days=6)
    assert p.watch_result["outcome"] == "watching"
    assert "improvement.released" in [e[0] for e in world.events]


async def test_release_refused_when_the_agent_changed_since_the_proof(
    world, monkeypatch
):
    p = _proposal(world, state="approved", base_config_hash="old")
    world.db.answer = lambda stmt: [world.agent]
    with pytest.raises(svc.ImprovementError) as e:
        await svc.release(world.db, p, _user())
    assert e.value.code == "AGENT_CHANGED"


async def test_worse_watch_rolls_back_and_tells_approver_and_owner(world, monkeypatch):
    approver = _user(name="Grace")
    p = _proposal(
        world,
        state="released",
        released_revision_id=uuid.uuid4(),
        watch_until=_now() + timedelta(days=7),
        watch_runs_target=200,
        watch_result={
            "outcome": "watching",
            "started_at": _now().isoformat(),
            "base_hash": "h0",
            "new_hash": "h1",
            "approved_by": str(approver.id),
        },
    )
    approval = Obj(signoffs=[{"user_id": str(approver.id), "decision": "approve"}])
    p.approval_id = approval.id
    world.db.objs[approval.id] = approval
    world.db.objs[p.released_revision_id] = Obj(
        previous_state={"system_prompt": "old prompt", "model_config": {"model": "m"}}
    )
    world.db.answer = lambda stmt: [world.agent]
    world.agent.system_prompt = "new prompt"

    async def measures(db, agent_id, chash, since, until, cluster_id):
        if chash == "h1":
            return _m(runs=3, thumbs_total=3, thumbs_down=3)
        return _m(thumbs_total=10, thumbs_down=0)

    recorded = []

    async def record(db, agent, **kw):
        recorded.append(kw)
        return Obj()

    monkeypatch.setattr(svc, "measures", measures)
    monkeypatch.setattr(svc, "_record", record)
    monkeypatch.setattr("app.core.audit.log_action", AsyncMock())
    out = await svc.check_watch(world.db, p)
    assert out == "rolled_back" and p.state == "rolled_back"
    assert world.agent.system_prompt == "old prompt"
    assert recorded[0]["source"] == "revert"
    assert (
        "Thumbs down rose" in p.watch_result["reason"] and p.watch_result["automatic"]
    )
    told = {
        str(n["user_id"]) for n in world.notes if n["type"] == "improvement_rolled_back"
    }
    assert told == {str(world.author.id), str(approver.id)}
    assert all(
        "Thumbs down" in n["message"]
        for n in world.notes
        if n["type"] == "improvement_rolled_back"
    )
    assert world.cluster.state == "open"
    assert "improvement.rolled_back" in [e[0] for e in world.events]


async def test_clean_watch_is_kept_at_the_end(world, monkeypatch):
    p = _proposal(
        world,
        state="released",
        watch_until=_now() - timedelta(minutes=1),
        watch_runs_target=200,
        watch_result={
            "outcome": "watching",
            "started_at": (_now() - timedelta(days=7)).isoformat(),
            "base_hash": "h0",
            "new_hash": "h1",
        },
    )
    monkeypatch.setattr(svc, "measures", AsyncMock(return_value=_m()))
    assert await svc.check_watch(world.db, p) == "kept"
    assert p.state == "kept" and world.cluster.state == "fixed"
    assert any(n["type"] == "improvement_kept" for n in world.notes)


async def test_watch_stops_when_someone_edits_the_agent(world, monkeypatch):
    p = _proposal(
        world,
        state="released",
        watch_result={
            "outcome": "watching",
            "started_at": _now().isoformat(),
            "base_hash": "h0",
            "new_hash": "h9",
        },
    )
    assert await svc.check_watch(world.db, p) == "stopped"
    assert p.state == "superseded"


async def test_manual_rollback_needs_no_approval_and_only_while_watching(
    world, monkeypatch
):
    p = _proposal(world, state="kept")
    with pytest.raises(svc.ImprovementError) as e:
        await svc.rollback(world.db, p, world.author, "no")
    assert e.value.code == "WRONG_STATE"


async def test_rejection_with_a_note_becomes_a_lesson(world):
    p = _proposal(world)
    approval = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        payload={"proposal_id": str(p.id)},
        status=ApprovalStatus.denied,
        signoffs=[{"decision": "deny", "reason": "Kelvin needs the K symbol"}],
    )
    p.approval_id = approval.id
    world.cluster.state = "proposed"

    async def gp(db, t, pid):
        return p

    svc_get = svc.get_proposal
    svc.get_proposal = gp
    try:
        await svc.on_release_resolved(world.db, approval, _user(name="Grace"))
    finally:
        svc.get_proposal = svc_get
    assert p.state == "rejected" and "K symbol" in p.error
    lesson = world.db.added[-1]
    assert lesson.source == "note" and "K symbol" in lesson.note
    assert lesson.meta["proposal_id"] == str(p.id)
    assert world.cluster.state == "open"


# wiring


async def test_routes_exist():
    paths = {(m, r.path) for r in router.router.routes for m in r.methods}
    for want in (
        ("POST", "/api/improvements/clusters/{cluster_id}/propose"),
        ("GET", "/api/improvements/proposals/{proposal_id}"),
        ("POST", "/api/improvements/proposals/{proposal_id}/rerun"),
        ("POST", "/api/improvements/proposals/{proposal_id}/request-approval"),
        ("POST", "/api/improvements/proposals/{proposal_id}/rollback"),
        ("GET", "/api/improvements/budget"),
        ("POST", "/api/improvements/sample"),
        ("GET", "/api/improvements/proposals"),
    ):
        assert want in paths, want


async def test_router_is_registered_in_main():
    import inspect

    import app.main as main

    assert "improvements_proposals" in inspect.getsource(main)


async def test_capabilities_events_notifications_and_locks():
    for c in (
        "improvements.view",
        "improvements.propose",
        "improvements.approve",
        "feedback.give",
    ):
        assert c in caps.KEYS
    assert "feedback.give" in caps.ROLE_DEFAULTS["user"]
    assert "improvements.approve" not in caps.ROLE_DEFAULTS["creator"]
    for e in (
        "improvement.proposed",
        "improvement.proved",
        "improvement.released",
        "improvement.rolled_back",
        "improvement.kept",
    ):
        assert e in events.CATALOG
    for t in ("improvement_ready", "improvement_kept", "improvement_rolled_back"):
        assert notif.pref_key_for(t) == "improvement_updates"
    assert (
        scheduler.IMPROVE_LOCK_KEY
        == int.from_bytes(b"IMPP", "big")
        == svc.PROPOSE_LOCK_KEY
    )
    assert (
        scheduler.IMPROVE_WATCH_LOCK_KEY
        == int.from_bytes(b"IMPW", "big")
        == svc.WATCH_LOCK_KEY
    )
    import inspect

    src = inspect.getsource(scheduler.start_scheduler)
    assert "improvements_tick" in src and "improvements_watch" in src


async def test_watch_job_runs_only_under_its_lock(monkeypatch):
    from contextlib import asynccontextmanager

    seen = []

    @asynccontextmanager
    async def lock(key):
        seen.append(key)
        yield False

    tick = AsyncMock()
    monkeypatch.setattr(scheduler, "advisory_lock", lock)
    monkeypatch.setattr(svc, "watch_tick", tick)
    await scheduler.improvements_watch()
    tick.assert_not_awaited()
    assert seen == [scheduler.IMPROVE_WATCH_LOCK_KEY]


async def test_proposal_row_has_the_contract_shape(world):
    p = _proposal(world)
    row = svc.proposal_row(p, world.agent, world.cluster)
    for k in (
        "id",
        "agent",
        "cluster",
        "change_kind",
        "change_label",
        "diff",
        "rationale",
        "risk",
        "state",
        "state_label",
        "progress",
        "proof",
        "approval_id",
        "released_revision_id",
        "watch_until",
        "watch_result",
        "created_at",
    ):
        assert k in row
    assert row["state_label"] == "Waiting for approval"
    assert row["change_label"] == "Edit the instructions"


async def test_proposal_rows_read_updated_at_without_a_lazy_load():
    from models.improvement import ImprovementProposal

    # finish_proof serialises the row right after an update, a lazy load there fails the proof
    assert ImprovementProposal.__mapper__.eager_defaults is True


async def test_notifications_are_committed(world):
    p = _proposal(world, created_by=None)
    before = world.db.commits
    await svc._notify(
        world.db, p, world.agent, type="improvement_kept", title="t", message="m"
    )
    assert [n["type"] for n in world.notes] == ["improvement_kept"]
    assert world.db.commits == before + 1
