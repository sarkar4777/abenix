"""G0 foundations: a revision on every change path, the eval gate on live edits,
the autonomy eval check on the current version, and joined trajectory recall."""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.routers import agents as agents_router
from app.routers import pipeline_healing as healing
from app.schemas.agents import UpdateAgentRequest
from app.services import agent_revisions as revs
from app.services import autonomy as auto_svc
from app.services import eval_runner as R
from app.services.eval_scoring import GateResult
from models.agent import AgentStatus, AgentType
from models.agent_revision import AgentRevision
from models.pipeline_healing import PipelinePatchStatus

pytestmark = pytest.mark.asyncio

TENANT = uuid.uuid4()
ROOT = Path(__file__).resolve().parents[2]


class Res:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self.value or []))

    def all(self):
        return list(self.value or [])

    def first(self):
        v = list(self.value or [])
        return v[0] if v else None


class Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class DB:
    def __init__(self, *results, fail_flush=False):
        self.results = list(results)
        self.added: list = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_flush = fail_flush

    async def execute(self, stmt, params=None):
        return Res(self.results.pop(0) if self.results else None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        if self.fail_flush:
            raise RuntimeError("db down")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, obj):
        return None

    def begin_nested(self):
        return Nested()

    def revisions(self):
        return [o for o in self.added if isinstance(o, AgentRevision)]


def _user(role="creator"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        role=SimpleNamespace(value=role) if role != "admin" else "admin",
        full_name="Ana",
        email="a@x",
    )


def _agent(user, *, status=AgentStatus.ACTIVE, mode=None):
    mc = {"model": "claude-sonnet-4-5-20250929", "risk_tier": "high", "tools": []}
    if mode:
        mc["mode"] = mode
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        creator_id=user.id,
        agent_type=AgentType.CUSTOM,
        name="Underwriter",
        slug="underwriter",
        description="d",
        system_prompt="old prompt",
        model_config_=mc,
        category="finance",
        icon_url=None,
        version="1",
        status=status,
        is_published=False,
        marketplace_price=None,
    )


def _body(resp) -> dict:
    return json.loads(resp.body)


# ── the one helper ────────────────────────────────────────────────────


async def test_record_revision_numbers_after_the_highest_and_keeps_source():
    u = _user()
    a = _agent(u)
    db = DB(7)
    pid = uuid.uuid4()
    rev = await revs.record_revision(
        db,
        a,
        changed_by=u.id,
        change_type="config_update",
        previous_state={"system_prompt": "x"},
        source="improvement",
        proposal_id=pid,
    )
    assert rev.revision_number == 8
    assert rev.source == "improvement" and rev.proposal_id == pid
    assert rev.new_state["system_prompt"] == "old prompt"
    assert db.revisions() == [rev]


async def test_record_revision_failure_is_raised_not_swallowed():
    u = _user()
    with pytest.raises(revs.RevisionWriteError):
        await revs.record_revision(
            DB(0, fail_flush=True),
            _agent(u),
            changed_by=u.id,
            change_type="x",
            previous_state=None,
        )
    with pytest.raises(ValueError):
        await revs.record_revision(
            DB(0),
            _agent(u),
            changed_by=u.id,
            change_type="x",
            previous_state=None,
            source="magic",
        )


async def test_agent_state_is_a_snapshot_not_a_reference():
    a = _agent(_user())
    snap = revs.agent_state(a)
    a.model_config_["tools"].append("web_search")
    assert snap["model_config"]["tools"] == []
    assert revs.behaviour_changed(snap, revs.agent_state(a))
    assert not revs.behaviour_changed(snap, {**snap, "name": "other"})


async def test_gate_link_points_at_the_failing_run_or_the_suite():
    run, suite = uuid.uuid4(), uuid.uuid4()
    assert (
        revs.gate_link(
            [
                {"state": "passed", "run_id": "p"},
                {"state": "failed", "run_id": str(run)},
            ]
        )
        == f"/evals/runs/{run}"
    )
    assert (
        revs.gate_link([{"state": "not_run", "suite_id": str(suite), "run_id": None}])
        == f"/evals/{suite}"
    )
    assert revs.gate_link([]) is None


async def test_gate_refusal_on_a_live_edit_says_how_to_proceed():
    blocked = GateResult(
        False,
        "Golden scored 50%",
        required=True,
        suites=[
            {"name": "Golden", "state": "failed", "run_id": "r1", "suite_id": "s1"}
        ],
    )
    a = _agent(_user())
    with patch.object(R, "gate_for_agent", AsyncMock(return_value=blocked)):
        resp = await revs.eval_gate_refusal(DB(), a, live_edit=True)
    err = _body(resp)["error"]
    assert resp.status_code == 409 and err["error_code"] == "EVAL_GATE"
    assert err["details"]["link"] == "/evals/runs/r1"
    assert "Move it to draft" in err["message"]


# ── PUT ───────────────────────────────────────────────────────────────


async def _put(a, user, body, db, gate=None):
    with patch.object(
        agents_router, "_serialize_agent", lambda x: {"id": str(x.id)}
    ), patch.object(
        agents_router, "_risk_activation_problem", AsyncMock(return_value=None)
    ), patch.object(
        agents_router, "_eval_gate_problem", gate or AsyncMock(return_value=None)
    ), patch.object(
        agents_router, "_sync_kb_grants", AsyncMock(return_value=[])
    ), patch.object(
        agents_router, "_apply_scaling", lambda *a, **k: None
    ):
        return await agents_router.update_agent(a.id, body, user, db)


async def test_put_writes_an_edit_revision_in_the_same_commit():
    u = _user()
    a = _agent(u, status=AgentStatus.DRAFT)
    db = DB(a, 2, [])
    resp = await _put(a, u, UpdateAgentRequest(system_prompt="new prompt"), db)
    assert resp.status_code == 200
    [rev] = db.revisions()
    assert rev.source == "edit" and rev.revision_number == 3
    assert rev.previous_state["system_prompt"] == "old prompt"
    assert rev.new_state["system_prompt"] == "new prompt"


async def test_put_refuses_when_the_revision_cannot_be_written():
    u = _user()
    a = _agent(u, status=AgentStatus.DRAFT)
    db = DB(a, 0, fail_flush=True)
    resp = await _put(a, u, UpdateAgentRequest(system_prompt="new"), db)
    assert resp.status_code == 500
    assert _body(resp)["error"]["error_code"] == "REVISION_WRITE_FAILED"
    assert db.commits == 0 and db.rollbacks == 1


async def test_put_on_a_live_agent_runs_the_gate_when_the_prompt_changes():
    u = _user()
    a = _agent(u)
    refused = agents_router.error("blocked", 409, error_code="EVAL_GATE")
    gate = AsyncMock(return_value=refused)
    db = DB(a)
    resp = await _put(a, u, UpdateAgentRequest(system_prompt="new"), db, gate)
    assert resp.status_code == 409
    assert gate.await_args.kwargs == {"live_edit": True}
    assert db.commits == 0 and db.revisions() == []


async def test_put_on_a_live_agent_skips_the_gate_for_a_rename():
    u = _user()
    a = _agent(u)
    gate = AsyncMock(return_value=None)
    db = DB(a, 0, [])
    resp = await _put(a, u, UpdateAgentRequest(name="Renamed"), db, gate)
    assert resp.status_code == 200
    gate.assert_not_awaited()
    assert db.revisions()[0].source == "edit"


async def test_put_activating_a_draft_still_runs_the_gate():
    u = _user()
    a = _agent(u, status=AgentStatus.DRAFT)
    gate = AsyncMock(return_value=None)
    await _put(a, u, UpdateAgentRequest(status="active"), DB(a, 0, []), gate)
    assert gate.await_args.kwargs == {"live_edit": False}


# ── publish, revert, import, duplicate ────────────────────────────────


async def test_publish_writes_a_publish_revision():
    u = _user()
    a = _agent(u, status=AgentStatus.DRAFT)
    db = DB(a, 4)
    with patch(
        "app.core.permissions.can_publish_agent", return_value=(True, "")
    ), patch.object(
        agents_router, "_risk_activation_problem", AsyncMock(return_value=None)
    ), patch.object(
        agents_router, "_eval_gate_problem", AsyncMock(return_value=None)
    ), patch.object(
        agents_router, "log_action", AsyncMock()
    ), patch.object(
        agents_router, "_serialize_agent", lambda x: {}
    ):
        resp = await agents_router.publish_agent(a.id, None, u, db)
    assert resp.status_code == 200
    [rev] = db.revisions()
    assert rev.change_type == "publish" and rev.revision_number == 5
    assert rev.previous_state["status"] == "draft"
    assert rev.new_state["status"] == "active"


async def test_revert_writes_a_revert_revision_without_the_gate():
    u = _user()
    a = _agent(u)
    old = SimpleNamespace(
        id=uuid.uuid4(),
        revision_number=2,
        previous_state={"system_prompt": "v1"},
        new_state={"system_prompt": "v2", "model_config": a.model_config_},
    )
    db = DB(a, old, 3)
    gate = AsyncMock()
    with patch.object(agents_router, "log_action", AsyncMock()), patch.object(
        agents_router, "_sync_kb_grants", AsyncMock(return_value=[])
    ), patch.object(agents_router, "_eval_gate_problem", gate):
        resp = await agents_router.revert_to_revision(
            a.id, old.id, SimpleNamespace(), "after", u, db
        )
    assert resp.status_code == 200
    [rev] = db.revisions()
    assert rev.source == "revert" and rev.revision_number == 4
    assert rev.new_state["system_prompt"] == "v2"
    gate.assert_not_awaited()


async def test_duplicate_and_import_start_history_with_an_import_revision():
    u = _user()
    src = _agent(u)
    db = DB(src, 0)
    with patch(
        "app.services.agent_share.resolve_agent_access", AsyncMock(return_value=True)
    ), patch.object(agents_router, "_serialize_agent", lambda x: {}):
        resp = await agents_router.duplicate_agent(src.id, u, db)
    assert resp.status_code == 201
    [rev] = db.revisions()
    assert rev.source == "import" and rev.change_type == "duplicate"
    assert rev.agent_id == db.added[0].id

    db = DB(0)
    with patch.object(agents_router, "log_action", AsyncMock()), patch.object(
        agents_router, "_serialize_agent", lambda x: {}
    ):
        resp = await agents_router.import_agent(
            {
                "agent": {
                    "name": "Imp",
                    "system_prompt": "p",
                    "model_config": {"model": "m"},
                }
            },
            SimpleNamespace(),
            u,
            db,
        )
    assert resp.status_code == 201
    assert db.revisions()[0].source == "import"


async def test_list_revisions_returns_source_and_proposal():
    u = _user()
    pid = uuid.uuid4()
    rows = [
        SimpleNamespace(
            id=uuid.uuid4(),
            revision_number=2,
            changed_by=u.id,
            change_type="config_update",
            source="improvement",
            proposal_id=pid,
            diff_summary="x",
            created_at=None,
        )
    ]
    resp = await agents_router.list_revisions(uuid.uuid4(), u, DB(uuid.uuid4(), rows))
    row = _body(resp)["data"][0]
    assert row["source"] == "improvement" and row["proposal_id"] == str(pid)


# ── healing ───────────────────────────────────────────────────────────


def _pipeline_and_patch(user, status=AgentStatus.ACTIVE):
    p = _agent(user, status=status, mode="pipeline")
    before = {"nodes": [{"id": "a", "tool_name": "web_search"}]}
    after = {"nodes": [{"id": "a", "tool_name": "web_search", "on_error": "continue"}]}
    p.model_config_["pipeline_config"] = before
    prop = SimpleNamespace(
        id=uuid.uuid4(),
        title="Continue on error",
        status=PipelinePatchStatus.PENDING,
        dsl_before={"pipeline_config": before},
        dsl_after={"pipeline_config": after},
        dsl_before_sha256=healing.config_hash(before),
        risk_level="low",
        confidence=0.9,
        applied_snapshot=None,
        decided_by=None,
        decided_at=None,
        rolled_back_at=None,
        rolled_back_by=None,
    )
    return p, prop


async def test_healing_apply_writes_a_healing_revision():
    u = _user("admin")
    p, prop = _pipeline_and_patch(u)
    db = DB(p, prop, 1)
    with patch.object(healing, "log_action", AsyncMock()), patch.object(
        revs, "eval_gate_refusal", AsyncMock(return_value=None)
    ) as gate:
        resp = await healing.apply_patch(
            str(p.id), str(prop.id), SimpleNamespace(), u, db
        )
    assert resp.status_code == 200
    gate.assert_awaited_once()
    [rev] = db.revisions()
    assert rev.source == "healing" and rev.change_type == "healing_patch"
    assert (
        rev.new_state["model_config"]["pipeline_config"]["nodes"][0]["on_error"]
        == "continue"
    )
    assert (
        "on_error"
        not in rev.previous_state["model_config"]["pipeline_config"]["nodes"][0]
    )


async def test_healing_apply_is_refused_by_the_gate_on_a_live_pipeline():
    u = _user("admin")
    p, prop = _pipeline_and_patch(u)
    refused = agents_router.error("blocked", 409, error_code="EVAL_GATE")
    db = DB(p, prop)
    with patch.object(healing, "log_action", AsyncMock()), patch.object(
        revs, "eval_gate_refusal", AsyncMock(return_value=refused)
    ):
        resp = await healing.apply_patch(
            str(p.id), str(prop.id), SimpleNamespace(), u, db
        )
    assert resp.status_code == 409
    assert db.commits == 0 and db.revisions() == []
    assert prop.status == PipelinePatchStatus.PENDING


async def test_healing_rollback_writes_a_revert_revision():
    u = _user("admin")
    p, prop = _pipeline_and_patch(u)
    after = prop.dsl_after["pipeline_config"]
    p.model_config_["pipeline_config"] = after
    prop.status = PipelinePatchStatus.ACCEPTED
    prop.applied_snapshot = prop.dsl_before["pipeline_config"]
    db = DB(p, prop, 2)
    with patch.object(healing, "log_action", AsyncMock()):
        resp = await healing.rollback_patch(
            str(p.id), str(prop.id), SimpleNamespace(), u, db
        )
    assert resp.status_code == 200
    [rev] = db.revisions()
    assert rev.source == "revert" and rev.change_type == "healing_rollback"


# ── autonomy eval check ───────────────────────────────────────────────


async def test_latest_verdict_uses_newest_run_per_suite_and_prefers_gating():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    assert auto_svc.latest_verdict([]) is None
    assert auto_svc.latest_verdict([(s1, True, False), (s1, False, False)]) is True
    assert auto_svc.latest_verdict([(s1, True, True), (s2, False, False)]) is True
    assert auto_svc.latest_verdict([(s1, False, True), (s2, True, False)]) is False


async def test_eval_passing_judges_the_current_version_only():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    assert await auto_svc.eval_passing(DB([(sid, True, True)]), aid, "h1") is True
    # the suites ran, but only on an older version
    assert await auto_svc.eval_passing(DB([], [(uuid.uuid4(),)]), aid, "h1") is False
    assert await auto_svc.eval_passing(DB([], []), aid, "h1") is None


async def test_eval_passing_filters_on_hash_and_baseline_model():
    seen = []

    class Spy(DB):
        async def execute(self, stmt, params=None):
            seen.append((str(stmt), stmt.compile().params))
            return await super().execute(stmt, params)

    await auto_svc.eval_passing(Spy([(uuid.uuid4(), True, True)]), uuid.uuid4(), "abc")
    sql, binds = seen[0]
    assert "eval_runs.config_hash = :config_hash_1" in sql
    assert "model_override IS false" in sql
    assert binds["config_hash_1"] == "abc" and "completed" in binds.values()


# ── trajectories ──────────────────────────────────────────────────────


def _write(folder: Path, name: str, **rec):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(rec), encoding="utf-8")


async def test_recall_reads_trajectory_dir_and_ranks_by_outcome_then_overlap(
    tmp_path, monkeypatch
):
    from engine.tools.recall_trajectory import RecallTrajectoryTool

    monkeypatch.setenv("TRAJECTORY_DIR", str(tmp_path))
    shared = tmp_path / "shared"
    q = "brent wti spread arbitrage today"
    _write(
        shared,
        "a",
        id="a",
        execution_id="e1",
        intent="brent wti spread arbitrage today",
        created_at_epoch=3,
    )
    _write(
        shared,
        "b",
        id="b",
        execution_id="e2",
        intent="brent wti spread",
        success_signal=0.9,
        created_at_epoch=1,
    )
    _write(
        shared,
        "c",
        id="c",
        execution_id="e3",
        intent="brent wti spread arbitrage",
        success_signal=-1,
        created_at_epoch=5,
    )
    _write(
        tmp_path / "t1",
        "a2",
        id="a2",
        execution_id="e1",
        intent="brent wti spread arbitrage today",
        created_at_epoch=9,
    )
    out = await RecallTrajectoryTool(tenant_id="t1").execute({"query": q, "top_k": 5})
    ids = [m["trajectory_id"] for m in json.loads(out.content)["matches"]]
    # graded good first, ungraded next, negative last, one row per execution
    assert ids == ["b", "a2", "c"]


async def test_wingman_writes_one_trajectory_per_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAJECTORY_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        "wingman_trajectories_test", ROOT / "wingman" / "api" / "trajectories.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    first = mod.write_trajectory({"intent": "brent spread", "execution_id": "exec-1"})
    mod.attach_outcome(first, success_signal=0.8)
    again = mod.write_trajectory({"intent": "brent spread", "execution_id": "exec-1"})
    assert first == again
    files = list((tmp_path / "shared").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["success_signal"] == 0.8
    other = mod.write_trajectory({"intent": "x", "execution_id": "exec-2"})
    assert other != first and len(list((tmp_path / "shared").glob("*.json"))) == 2
