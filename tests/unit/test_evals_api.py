"""/api/evals routes, the publish gate on agents, model overrides and the runner's execute call."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.routers import agents as agents_router
from app.routers import evals
from app.services import eval_runner as R
from app.services.eval_scoring import GateResult
from engine import governance

pytestmark = pytest.mark.asyncio

TENANT = uuid.uuid4()


class Res:
    def __init__(self, value):
        self.value = value

    @property
    def rowcount(self):
        return getattr(self.value, "rowcount", 0)

    def scalar_one_or_none(self):
        return self.value

    def scalar(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self.value or []))

    def all(self):
        return list(self.value or [])


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.statements: list = []
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.statements.append(stmt)
        return Res(self.results.pop(0) if self.results else None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for o in self.added:
            if getattr(o, "id", None) is None:
                o.id = uuid.uuid4()

    async def commit(self):
        self.commits += 1
        await self.flush()

    async def refresh(self, obj):
        return None

    async def rollback(self):
        return None

    async def delete(self, obj):
        return None

    async def get(self, model, key):
        return None


def _user():
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        role=SimpleNamespace(value="creator"),
        email="c@x",
    )


def _agent(mode=None, tier="high", model="claude-sonnet-4-5-20250929"):
    mc = {"model": model, "risk_tier": tier}
    if mode:
        mc["mode"] = mode
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name="Underwriter",
        slug="underwriter",
        model_config_=mc,
        status=SimpleNamespace(value="draft"),
    )


def _body(resp) -> dict:
    return json.loads(resp.body)


@pytest.fixture(autouse=True)
def _snapshot():
    governance.load_for_test()
    yield
    governance.load_for_test()


async def test_assertion_catalogue_lists_every_type():
    data = _body(await evals.assertion_types(_user()))["data"]
    types = {t["type"] for t in data["types"]}
    assert {
        "json_path_equals",
        "regex",
        "schema_valid",
        "judge",
        "cited_sources_present",
    } <= types
    assert data["default_judge_model"] == "claude-haiku-4-5-20251001"


async def test_create_suite_rejects_a_bad_schedule():
    body = evals.SuiteBody(
        name="Golden", agent_id=uuid.uuid4(), schedule_cron="every day"
    )
    with patch.object(evals, "_visible_agent", AsyncMock(return_value=_agent())):
        resp = await evals.create_suite(body, None, _user(), FakeSession())
    assert resp.status_code == 400 and "cron" in _body(resp)["error"]["message"]


async def test_create_suite_for_an_agent_the_caller_cannot_run_is_404():
    body = evals.SuiteBody(name="Golden", agent_id=uuid.uuid4())
    with patch.object(evals, "_visible_agent", AsyncMock(return_value=None)):
        resp = await evals.create_suite(body, None, _user(), FakeSession())
    assert resp.status_code == 404


async def test_create_suite_stores_gate_and_schedule():
    agent = _agent()
    body = evals.SuiteBody(
        name=" Golden ",
        agent_id=agent.id,
        gating=True,
        pass_threshold=0.8,
        schedule_cron="0 6 * * 1",
    )
    db = FakeSession()
    with patch.object(
        evals, "_visible_agent", AsyncMock(return_value=agent)
    ), patch.object(evals, "log_action", AsyncMock()):
        resp = await evals.create_suite(body, None, _user(), db)
    assert resp.status_code == 201
    s = db.added[0]
    assert s.name == "Golden" and s.gating and s.pass_threshold == 0.8
    assert s.tenant_id == TENANT and s.next_run_at is not None


async def test_case_with_a_broken_assertion_is_refused_with_the_field():
    suite = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT)
    body = evals.CaseBody(
        name="c",
        input_message="hi",
        assertions=[
            {"type": "contains", "value": "x"},
            {"type": "regex", "pattern": "("},
        ],
    )
    db = FakeSession(0)
    with patch.object(evals, "_suite", AsyncMock(return_value=suite)):
        resp = await evals.create_case(suite.id, body, _user(), db)
    assert resp.status_code == 400
    err = _body(resp)["error"]
    assert err["error_code"] == "INVALID_ASSERTION" and "Assertion 2" in err["message"]
    assert "1" in err["details"]["assertions"]


async def test_check_assertions_against_a_given_output():
    body = evals.CheckBody(
        output='```json\n{"decision": "approve"}\n```',
        assertions=[
            {"type": "json_path_equals", "path": "decision", "value": "approve"},
            {"type": "contains", "value": "reject"},
            {"type": "judge", "rubric": "polite"},
            {"type": "regex"},
        ],
    )
    data = _body(await evals.check_assertions(body, _user(), FakeSession()))["data"]
    res = data["results"]
    assert res[0]["passed"] and not res[1]["passed"]
    assert res[2]["skipped"] and res[2]["passed"] is None
    assert data["problems"] == {"3": ["Pattern is required."]}


async def test_case_from_execution_suggests_assertions_that_hold():
    suite = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT, agent_id=uuid.uuid4())
    ex = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        agent_id=suite.agent_id,
        input_message="Score Acme\nmore",
        output_message='{"score": 7, "band": "B"}',
        tool_calls=[{"name": "kyc_scorer"}],
        cost=0.002,
        duration_ms=1500,
        status=SimpleNamespace(value="completed"),
        error_message=None,
        provenance=None,
        agent_revision=None,
    )
    db = FakeSession(ex, 0)
    with patch.object(evals, "_suite", AsyncMock(return_value=suite)):
        resp = await evals.case_from_execution(
            suite.id, evals.FromExecutionBody(execution_id=ex.id), _user(), db
        )
    assert resp.status_code == 201
    case = db.added[0]
    assert case.name == "Score Acme" and case.source_execution_id == ex.id
    assert case.reference_output.startswith('{"score"')
    types = [a["type"] for a in case.assertions]
    assert "json_path_equals" in types and "required_tools_called" in types
    c = db.statements[0].compile(dialect=postgresql.dialect())
    assert "executions.tenant_id" in str(c)


async def test_run_refuses_model_override_on_pipelines_and_disallowed_models():
    suite = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT, agent_id=uuid.uuid4())
    start = AsyncMock()
    with patch.object(evals, "_suite", AsyncMock(return_value=suite)), patch.object(
        evals, "_visible_agent", AsyncMock(return_value=_agent(mode="pipeline"))
    ), patch.object(evals, "_case_count", AsyncMock(return_value=3)), patch.object(
        R, "start_run", start
    ):
        resp = await evals.run_suite(
            suite.id, None, evals.RunBody(model="gpt-4o"), _user(), FakeSession()
        )
    assert resp.status_code == 400 and "pipeline" in _body(resp)["error"]["message"]

    governance.load_for_test([(str(TENANT), "high", {"allowed_models": ["claude-*"]})])
    with patch.object(evals, "_suite", AsyncMock(return_value=suite)), patch.object(
        evals, "_visible_agent", AsyncMock(return_value=_agent())
    ), patch.object(evals, "_case_count", AsyncMock(return_value=3)), patch.object(
        R, "start_run", start
    ):
        resp = await evals.run_suite(
            suite.id, None, evals.RunBody(model="gpt-4o"), _user(), FakeSession()
        )
    assert (
        resp.status_code == 400 and "allowed model" in _body(resp)["error"]["message"]
    )
    start.assert_not_awaited()


async def test_run_with_a_model_override_starts_a_run():
    suite = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT, agent_id=uuid.uuid4())
    run = SimpleNamespace(
        id=uuid.uuid4(),
        suite_id=suite.id,
        agent_id=suite.agent_id,
        config_hash="h",
        agent_revision=1,
        model="claude-opus-4-1",
        model_override=True,
        status="queued",
        score=None,
        threshold=0.9,
        threshold_met=None,
        total=3,
        passed=0,
        failed=0,
        errored=0,
        triggered_by="manual",
        triggered_by_user=None,
        cost=0,
        error=None,
        created_at=None,
        started_at=None,
        completed_at=None,
    )
    start = AsyncMock(return_value=run)
    user = _user()
    with patch.object(evals, "_suite", AsyncMock(return_value=suite)), patch.object(
        evals, "_visible_agent", AsyncMock(return_value=_agent())
    ), patch.object(evals, "_case_count", AsyncMock(return_value=3)), patch.object(
        R, "start_run", start
    ), patch.object(
        evals, "log_action", AsyncMock()
    ):
        resp = await evals.run_suite(
            suite.id, None, evals.RunBody(model="claude-opus-4-1"), user, FakeSession()
        )
    assert resp.status_code == 202 and _body(resp)["data"]["model_override"]
    assert start.await_args.kwargs["model"] == "claude-opus-4-1"
    assert start.await_args.args[2] == user.id


async def test_run_needs_cases():
    suite = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT, agent_id=uuid.uuid4())
    with patch.object(evals, "_suite", AsyncMock(return_value=suite)), patch.object(
        evals, "_visible_agent", AsyncMock(return_value=_agent())
    ), patch.object(evals, "_case_count", AsyncMock(return_value=0)):
        resp = await evals.run_suite(suite.id, None, None, _user(), FakeSession())
    assert resp.status_code == 400


async def test_suite_lookup_is_tenant_scoped():
    db = FakeSession(None)
    resp = await evals.get_suite(uuid.uuid4(), _user(), db)
    assert resp.status_code == 404
    c = db.statements[0].compile(dialect=postgresql.dialect())
    assert "eval_suites.tenant_id" in str(c) and TENANT in c.params.values()


async def test_gate_not_required_for_low_tier_skips_the_database():
    db = FakeSession()
    g = await R.gate_for_agent(db, _agent(tier="low"))
    assert g.allowed and not g.required and db.statements == []


async def test_gate_blocks_high_tier_without_a_passing_run_for_this_config():
    agent = _agent(tier="high")
    suite = SimpleNamespace(id=uuid.uuid4(), name="Golden", pass_threshold=0.9)
    red = SimpleNamespace(
        id=uuid.uuid4(), score=0.5, threshold_met=False, config_hash="h1"
    )
    db = FakeSession([suite], "h1", red, [("Sanctions hit",)])
    g = await R.gate_for_agent(db, agent)
    assert not g.allowed and "Sanctions hit" in g.message
    db = FakeSession([suite], "h1", None)
    g = await R.gate_for_agent(db, agent)
    assert not g.allowed and "has not been run" in g.message
    green = SimpleNamespace(
        id=uuid.uuid4(), score=1.0, threshold_met=True, config_hash="h1"
    )
    g = await R.gate_for_agent(FakeSession([suite], "h1", green, []), agent)
    assert g.allowed


async def test_tenant_can_turn_the_gate_on_for_low_tier():
    governance.load_for_test([(str(TENANT), "low", {"require_eval_pass": True})])
    g = await R.gate_for_agent(FakeSession([], "h"), _agent(tier="low"))
    assert g.allowed and g.required


async def test_publish_gate_helper_answers_409_with_the_suites():
    blocked = GateResult(
        False,
        "Golden scored 50%",
        required=True,
        suites=[{"name": "Golden", "state": "failed"}],
    )
    with patch.object(R, "gate_for_agent", AsyncMock(return_value=blocked)):
        resp = await agents_router._eval_gate_problem(FakeSession(), _agent())
    assert resp.status_code == 409
    err = _body(resp)["error"]
    assert (
        err["error_code"] == "EVAL_GATE"
        and err["details"]["suites"][0]["name"] == "Golden"
    )
    with patch.object(R, "gate_for_agent", AsyncMock(return_value=GateResult(True))):
        assert await agents_router._eval_gate_problem(FakeSession(), _agent()) is None


async def test_publish_is_refused_when_the_gate_blocks():
    from models.agent import AgentType

    agent = _agent()
    agent.agent_type = AgentType.CUSTOM
    agent.system_prompt = "x"
    db = FakeSession(agent)
    blocked = agents_router.error("blocked", 409, error_code="EVAL_GATE")
    with patch(
        "app.core.permissions.can_publish_agent", return_value=(True, "")
    ), patch.object(
        agents_router, "_risk_activation_problem", AsyncMock(return_value=None)
    ), patch.object(
        agents_router, "_eval_gate_problem", AsyncMock(return_value=blocked)
    ):
        resp = await agents_router.publish_agent(agent.id, None, _user(), db)
    assert resp.status_code == 409
    assert db.commits == 0


async def test_runner_executes_through_the_agent_execute_route_with_the_override():
    seen = {}

    async def fake_execute(agent_id, body, request, user, db):
        seen.update(
            agent_id=agent_id,
            body=body,
            model=getattr(request.state, "eval_model", None),
        )
        seen["raw"] = await request.json()
        return agents_router.success(
            {"execution_id": "11111111-1111-1111-1111-111111111111"}
        )

    user = SimpleNamespace(id=uuid.uuid4(), is_active=True)

    class S(FakeSession):
        async def get(self, model, key):
            return user

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    with patch.object(R, "_session", lambda: S()), patch.object(
        agents_router, "execute_agent", fake_execute
    ):
        ex_id, err = await R._execute(
            uuid.uuid4(), user.id, "hello", {"k": 1}, "claude-opus-4-1"
        )
    assert ex_id == "11111111-1111-1111-1111-111111111111" and err is None
    assert seen["model"] == "claude-opus-4-1"
    assert seen["body"].wait is True and seen["body"].stream is False
    assert seen["raw"]["context"] == {"k": 1}

    async def refusing(agent_id, body, request, user, db):
        assert getattr(request.state, "eval_model", None) is None
        return agents_router.error("You do not have access to this agent", 403)

    with patch.object(R, "_session", lambda: S()), patch.object(
        agents_router, "execute_agent", refusing
    ):
        ex_id, err = await R._execute(uuid.uuid4(), user.id, "hello", {}, None)
    assert ex_id is None and "access" in err


def test_observed_reads_the_execution_row():
    row = SimpleNamespace(
        output_message="ok",
        tool_calls=[{"name": "web_search"}],
        cost=0.5,
        duration_ms=10,
        status=SimpleNamespace(value="completed"),
    )
    o = R.observed_from(row, "q")
    assert (
        o.status == "completed"
        and o.cost == 0.5
        and o.tool_calls[0]["name"] == "web_search"
    )
    assert R.observed_from(None, "q").status == "missing"


class Ctx(FakeSession):
    def __init__(self, *results, got=None):
        super().__init__(*results)
        self.got = got

    async def get(self, model, key):
        return self.got

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None


async def test_run_case_scores_and_stores_the_result():
    run = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        agent_id=uuid.uuid4(),
        model="m",
        model_override=False,
    )
    case = SimpleNamespace(
        id=uuid.uuid4(),
        name="Approve Acme",
        input_message="go",
        context={},
        weight=2.0,
        assertions=[{"type": "contains", "value": "approve"}],
    )
    row = SimpleNamespace(
        output_message="I approve",
        tool_calls=[],
        cost=0.01,
        duration_ms=900,
        status=SimpleNamespace(value="completed"),
        provenance={"config_hash": "h9"},
        agent_revision=4,
        error_message=None,
    )
    store = Ctx()
    with patch.object(
        R, "_execute", AsyncMock(return_value=(str(uuid.uuid4()), None))
    ) as ex, patch.object(R, "_settled", AsyncMock(return_value=row)), patch.object(
        R, "_session", lambda: store
    ):
        out = await R.run_case(run, case, uuid.uuid4(), None)
    assert ex.await_args.args[4] is None
    assert out["passed"] and out["config_hash"] == "h9" and out["weight"] == 2.0
    stored = store.added[0]
    assert (
        stored.passed
        and stored.case_name == "Approve Acme"
        and stored.status == "completed"
    )


async def test_run_case_records_an_execute_refusal_as_an_error():
    run = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        agent_id=uuid.uuid4(),
        model="gpt-4o",
        model_override=True,
    )
    case = SimpleNamespace(
        id=uuid.uuid4(),
        name="c",
        input_message="go",
        context={},
        weight=1.0,
        assertions=[],
    )
    store = Ctx()
    with patch.object(
        R, "_execute", AsyncMock(return_value=(None, "rate limited"))
    ) as ex, patch.object(R, "_session", lambda: store):
        out = await R.run_case(run, case, uuid.uuid4(), None)
    assert ex.await_args.args[4] == "gpt-4o"
    assert not out["passed"] and out["status"] == "error"
    assert store.added[0].error == "rate limited"


def _run_row(**kw):
    base = dict(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        suite_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        status="running",
        threshold=0.5,
        model="m",
        model_override=False,
        config_hash=None,
        agent_revision=None,
        triggered_by="manual",
        error=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_finish_scores_the_run_and_emits_eval_completed():
    run = _run_row()
    emit = AsyncMock()
    with patch.object(R, "_session", lambda: Ctx(got=run)), patch(
        "app.services.events.emit", emit
    ):
        await R._finish(
            run.id,
            [
                {
                    "weight": 1,
                    "passed": True,
                    "status": "completed",
                    "cost": 0.1,
                    "config_hash": "h",
                },
                {
                    "weight": 1,
                    "passed": False,
                    "status": "completed",
                    "cost": 0.2,
                    "config_hash": "h",
                },
            ],
        )
    assert run.status == "completed" and run.score == 0.5 and run.threshold_met
    assert run.config_hash == "h" and abs(run.cost - 0.3) < 1e-9
    assert emit.await_args.args[2] == "eval.completed"
    assert (
        emit.await_args.args[3]["passed"] == 1
        and emit.await_args.args[3]["failed"] == 1
    )


async def test_cancelled_run_stays_cancelled_and_never_meets_the_threshold():
    run = _run_row(status="cancelled", threshold=0.1)
    with patch.object(R, "_session", lambda: Ctx(got=run)), patch(
        "app.services.events.emit", AsyncMock()
    ):
        await R._finish(run.id, [{"weight": 1, "passed": True, "status": "completed"}])
    assert run.status == "cancelled" and run.threshold_met is False


async def test_scheduler_reruns_a_suite_when_the_agent_model_changed():
    agent = _agent(model="claude-opus-4-1")
    suite = SimpleNamespace(id=uuid.uuid4(), agent_id=agent.id, created_by=uuid.uuid4())
    db = Ctx(
        SimpleNamespace(rowcount=0),
        [],
        [suite],
        "claude-sonnet-4-5-20250929",
        got=agent,
    )
    start = AsyncMock()
    with patch.object(R, "_session", lambda: db), patch.object(R, "start_run", start):
        out = await R.scheduler_tick()
    assert out["model_change"] == 1
    assert start.await_args.kwargs["triggered_by"] == "model_change"

    db = Ctx(SimpleNamespace(rowcount=0), [], [suite], "claude-opus-4-1", got=agent)
    start = AsyncMock()
    with patch.object(R, "_session", lambda: db), patch.object(R, "start_run", start):
        out = await R.scheduler_tick()
    assert out["model_change"] == 0
    start.assert_not_awaited()


async def test_scheduler_starts_due_cron_suites_and_schedules_new_ones():
    due = SimpleNamespace(
        id=uuid.uuid4(),
        schedule_cron="0 6 * * *",
        next_run_at=R.datetime(2020, 1, 1, tzinfo=R.timezone.utc),
        created_by=uuid.uuid4(),
    )
    fresh = SimpleNamespace(
        id=uuid.uuid4(),
        schedule_cron="0 6 * * *",
        next_run_at=None,
        created_by=uuid.uuid4(),
    )
    db = Ctx(SimpleNamespace(rowcount=2), [due, fresh], [])
    start = AsyncMock()
    with patch.object(R, "_session", lambda: db), patch.object(R, "start_run", start):
        out = await R.scheduler_tick()
    assert out == {"stale": 2, "schedule": 1, "model_change": 0}
    assert (
        start.await_args.args[1] is due
        and start.await_args.kwargs["triggered_by"] == "schedule"
    )
    assert fresh.next_run_at is not None and due.next_run_at.year > 2020
