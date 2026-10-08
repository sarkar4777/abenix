"""/api/autonomy routes, capabilities, SoD on promotions, the action gate round trip and the observe job."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse

from app.core import capabilities as caps
from app.core import notifications as notif
from app.core import scheduler
from app.routers import approvals as approvals_router
from app.routers import autonomy as router
from app.schemas.connectors import ApprovalSignoffRequest
from app.services import autonomy as svc
from app.services import autonomy_ladder as L
from app.services import events
from engine import governance
from models.approval import Approval, ApprovalStatus
from models.autonomy import ActionType, AgentAction, AutonomyChange, AutonomyGrant
from models.user import UserRole

pytestmark = pytest.mark.asyncio

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


def _user(role=UserRole.ADMIN, tenant=TENANT, name="Ana"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant,
        role=role,
        email=f"{name.lower()}@x.dev",
        full_name=name,
    )


class Res:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self.rows), first=self.first)

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)


class Store:
    def __init__(self):
        self.types: list = []
        self.grants: list = []
        self.changes: list = []
        self.actions: list = []
        self.approvals: list = []
        self.agents: dict = {}
        self.users: dict = {}
        self.events: list = []
        self.notes: list = []
        self.limits = lambda facts: {"ok": True, "decision_key": "k", "reasons": []}

    def put(self, obj):
        bucket = {
            ActionType: self.types,
            AutonomyGrant: self.grants,
            AutonomyChange: self.changes,
            AgentAction: self.actions,
            Approval: self.approvals,
        }.get(type(obj))
        if bucket is not None and obj not in bucket:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            bucket.append(obj)


class FakeSession:
    def __init__(self, store: Store):
        self.store = store
        self.commits = 0

    def add(self, obj):
        self.store.put(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None

    async def refresh(self, obj):
        return None

    async def get(self, model, key):
        if model is Approval:
            return next((a for a in self.store.approvals if a.id == key), None)
        return None

    async def execute(self, stmt, params=None):
        descs = getattr(stmt, "column_descriptions", None) or []
        entity = descs[0].get("entity") if descs else None
        if entity is Approval:
            try:
                vals = {str(v) for v in stmt.compile().params.values()}
            except Exception:
                vals = set()
            hits = [
                a
                for a in self.store.approvals
                if str(a.id) in vals
                or (
                    a.gate_kind == svc.PROMOTE_GATE
                    and a.status == ApprovalStatus.pending
                    and str((a.payload or {}).get("grant_id")) in vals
                )
            ]
            return Res(hits)
        return Res([])


@pytest.fixture
def store(monkeypatch):
    s = Store()
    # a teammate who can approve exists unless a test says otherwise
    monkeypatch.setattr(svc, "someone_else_can_grant", AsyncMock(return_value=True))
    governance.load_for_test()

    def live(g):
        return g.state != "removed"

    async def get_grant(db, tid, gid):
        return next(
            (
                g
                for g in s.grants
                if str(g.id) == str(gid) and g.tenant_id == tid and live(g)
            ),
            None,
        )

    async def get_action(db, tid, aid):
        return next(
            (a for a in s.actions if str(a.id) == str(aid) and a.tenant_id == tid),
            None,
        )

    async def get_action_type(db, tid, type_id):
        return next(
            (t for t in s.types if str(t.id) == str(type_id) and t.tenant_id == tid),
            None,
        )

    async def by_key(db, tid, key):
        return next((t for t in s.types if t.key == key and t.tenant_id == tid), None)

    async def list_types(db, tid):
        return [t for t in s.types if t.tenant_id == tid]

    async def get_agent(db, tid, aid):
        a = s.agents.get(str(aid))
        return a if a is not None and a.tenant_id == tid else None

    async def agents_by_id(db, ids):
        return {str(i): s.agents[str(i)] for i in ids if str(i) in s.agents}

    async def types_by_id(db, ids):
        return {str(t.id): t for t in s.types if t.id in ids}

    async def users_by_id(db, ids):
        return {str(i): s.users[str(i)] for i in ids if str(i) in s.users}

    async def list_grants(db, tid, *, agent_id=None, action_type_id=None):
        return [
            g
            for g in s.grants
            if g.tenant_id == tid
            and live(g)
            and (agent_id is None or str(g.agent_id) == str(agent_id))
            and (action_type_id is None or str(g.action_type_id) == str(action_type_id))
        ]

    async def find_grant(db, tid, agent_id, type_id, shash):
        return next(
            (
                g
                for g in s.grants
                if g.tenant_id == tid
                and str(g.agent_id) == str(agent_id)
                and str(g.action_type_id) == str(type_id)
                and g.scope_hash == shash
            ),
            None,
        )

    async def grant_actions(db, tid, gid, limit=1000):
        rows = [
            a for a in s.actions if a.tenant_id == tid and str(a.grant_id) == str(gid)
        ]
        return sorted(rows, key=lambda a: a.created_at, reverse=True)[:limit]

    async def action_page(db, tid, gid, status, limit, before):
        rows = await grant_actions(db, tid, gid)
        if status:
            rows = [a for a in rows if a.status in status.split(",")]
        return rows[:limit]

    async def list_changes(db, gid, limit=200):
        return [c for c in s.changes if str(c.grant_id) == str(gid)][::-1]

    async def recent_demotions(db, tid, days=14):
        return [
            c for c in s.changes if c.tenant_id == tid and c.to_level < c.from_level
        ]

    async def counts(db, tid):
        rows = [a for a in s.actions if a.tenant_id == tid]
        return {
            "actions_7d": len(rows),
            "auto_7d": sum(1 for a in rows if a.mode in ("auto", "reported")),
            "harm_7d": sum(1 for a in rows if a.harm),
            "pending_reviews": sum(
                1 for a in rows if a.status == "watching" and not a.reviewer_answer
            ),
            "pending_approvals": sum(1 for a in rows if a.status == "pending"),
        }

    async def unmanaged(db, tid):
        return []

    async def pending(db, tid, limit):
        return [
            a
            for a in s.actions
            if a.tenant_id == tid and a.status == "watching" and not a.reviewer_answer
        ][:limit]

    async def emit(db, tenant_id, event_type, payload):
        s.events.append((event_type, payload))

    async def create_notification(db, **kw):
        s.notes.append(kw)

    async def limits(db, tid, key, facts):
        return {**s.limits(facts), "decision_key": key}

    for name, fn in {
        "get_grant": get_grant,
        "get_action": get_action,
        "get_action_type": get_action_type,
        "get_action_type_by_key": by_key,
        "list_action_types": list_types,
        "get_agent": get_agent,
        "agents_by_id": agents_by_id,
        "types_by_id": types_by_id,
        "users_by_id": users_by_id,
        "list_grants": list_grants,
        "find_grant": find_grant,
        "grant_actions": grant_actions,
        "action_page": action_page,
        "list_changes": list_changes,
        "recent_demotions": recent_demotions,
        "overview_counts": counts,
        "unmanaged_rows": unmanaged,
        "pending_reviews": pending,
        "execution_inputs": AsyncMock(return_value={}),
        "config_hash": AsyncMock(return_value="h1"),
        "eval_passing": AsyncMock(return_value=None),
        "tenant_settings": AsyncMock(return_value={}),
        "validate_limits_key": AsyncMock(return_value=None),
        "evaluate_limits": limits,
    }.items():
        monkeypatch.setattr(svc, name, fn)
    monkeypatch.setattr(events, "emit", emit)
    monkeypatch.setattr(notif, "create_notification", create_notification)
    monkeypatch.setattr(approvals_router, "create_notification", create_notification)
    yield s
    governance.load_for_test()


def _agent(store, creator, *, tools=("sample_plant",), tier="low", tenant=TENANT):
    a = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant,
        name="Plant operator (sample)",
        slug="sample-plant-operator",
        creator_id=creator.id,
        model_config_={"tools": list(tools), "risk_tier": tier},
    )
    store.agents[str(a.id)] = a
    store.users[str(creator.id)] = creator.full_name
    return a


def _body(resp: JSONResponse) -> dict:
    return json.loads(bytes(resp.body))


async def _enrolled(store, creator, *, policy=None, limits_key=None, tier="low"):
    agent = _agent(store, creator, tier=tier)
    spec = svc.sample_action_type_spec()
    spec["policy"] = policy if policy is not None else svc.SAMPLE_POLICY
    spec["limits_decision_key"] = limits_key
    db = FakeSession(store)
    with patch.object(svc, "tool_effect", return_value=(None, "low")):
        row = await svc.enrol(
            db, creator, agent.id, "sample_plant", spec, key=svc.SAMPLE_ACTION_KEY
        )
    return agent, store.grants[-1], row, db


def _action(store, grant, *, status="watching", mode="watching", level=None, **kw):
    a = AgentAction(
        id=uuid.uuid4(),
        tenant_id=grant.tenant_id,
        agent_id=grant.agent_id,
        agent_name="Plant operator (sample)",
        agent_config_hash="h1",
        action_type_id=grant.action_type_id,
        grant_id=grant.id,
        tool_name="sample_plant",
        level_at_time=grant.level if level is None else level,
        mode=mode,
        status=status,
        arguments={"operation": "set_setpoint", "setpoint_bar": 4.8},
        intent="Pressure is low",
        prediction={"metric": "pressure_bar", "value": 4.4, "low": 4.2, "high": 4.7},
        outcome_status="none",
        harm=False,
        created_at=kw.pop("created_at", _now()),
    )
    for k, v in kw.items():
        setattr(a, k, v)
    store.actions.append(a)
    return a


# routes and capabilities

CONTRACT_ROUTES = {
    ("GET", "/api/autonomy/overview"): "autonomy.view",
    ("GET", "/api/autonomy/grants/{grant_id}"): "autonomy.view",
    ("GET", "/api/autonomy/grants/{grant_id}/actions"): "autonomy.view",
    ("POST", "/api/autonomy/grants/{grant_id}/promote"): "autonomy.grant",
    ("POST", "/api/autonomy/grants/{grant_id}/demote"): "autonomy.manage",
    ("PATCH", "/api/autonomy/grants/{grant_id}"): "autonomy.manage",
    ("DELETE", "/api/autonomy/grants/{grant_id}"): "autonomy.manage",
    ("GET", "/api/autonomy/action-types"): "autonomy.view",
    ("GET", "/api/autonomy/action-types/{type_id}"): "autonomy.view",
    ("PATCH", "/api/autonomy/action-types/{type_id}"): "autonomy.manage",
    ("POST", "/api/autonomy/action-types/{type_id}/test"): "autonomy.manage",
    ("GET", "/api/autonomy/enrol/options"): "autonomy.manage",
    ("POST", "/api/autonomy/enrol"): "autonomy.manage",
    ("POST", "/api/autonomy/sample"): "autonomy.manage",
    ("POST", "/api/autonomy/sample/run"): "autonomy.manage",
    ("GET", "/api/autonomy/reviews"): "actions.review",
    ("POST", "/api/autonomy/actions/{action_id}/review"): "actions.review",
    ("POST", "/api/autonomy/actions/{action_id}/outcome"): "actions.review",
    ("POST", "/api/autonomy/actions/{action_id}/harm"): "actions.review",
    ("GET", "/api/autonomy/actions/{action_id}"): "autonomy.view",
    ("POST", "/api/autonomy/actions/propose"): None,
    ("GET", "/api/autonomy/actions/{action_id}/wait"): None,
    ("POST", "/api/autonomy/actions/{action_id}/executed"): None,
}


def _route_cap(route) -> str | None:
    for dep in route.dependant.dependencies:
        for cell in getattr(dep.call, "__closure__", None) or ():
            v = cell.cell_contents
            if isinstance(v, str) and v in caps.KEYS:
                return v
    return None


async def test_every_contract_route_exists_with_its_capability():
    got = {}
    for r in router.router.routes:
        for m in r.methods:
            got[(m, r.path)] = _route_cap(r)
    assert got == CONTRACT_ROUTES


async def test_router_is_registered_in_main():
    from pathlib import Path

    main = Path(svc.__file__).resolve().parents[1] / "main.py"
    assert "app.include_router(autonomy_router.router)" in main.read_text(
        encoding="utf-8"
    )


async def test_capabilities_and_role_defaults():
    for k in ("autonomy.view", "autonomy.manage", "autonomy.grant", "actions.review"):
        assert k in caps.KEYS
        assert caps.holds(caps.ROLE_DEFAULTS["admin"], k)
    assert caps.ROLE_DEFAULTS["creator"] >= {
        "autonomy.view",
        "autonomy.manage",
        "actions.review",
    }
    assert "autonomy.grant" not in caps.ROLE_DEFAULTS["creator"]
    assert caps.ROLE_DEFAULTS["user"] >= {"autonomy.view", "actions.review"}
    assert not caps.ROLE_DEFAULTS["user"] & {"autonomy.manage", "autonomy.grant"}


async def test_events_notifications_and_scheduler_are_wired():
    for e in (
        "action.proposed",
        "action.executed",
        "action.outcome_recorded",
        "autonomy.recommended",
        "autonomy.promoted",
        "autonomy.demoted",
    ):
        assert e in events.CATALOG
    for t in ("autonomy_recommended", "autonomy_demoted", "action_pending_review"):
        assert notif.pref_key_for(t) == "autonomy_updates"
    assert not notif._settings_allows(
        {"autonomy_updates": False}, "autonomy_demoted", ""
    )
    assert scheduler.ACTION_LOCK_KEY == int.from_bytes(b"ACTN", "big")
    keys = {
        scheduler.QUOTA_LOCK_KEY,
        scheduler.ARCHIVE_LOCK_KEY,
        scheduler.SWEEP_LOCK_KEY,
        scheduler.DRIFT_LOCK_KEY,
        scheduler.ESCALATE_LOCK_KEY,
        scheduler.VACUUM_LOCK_KEY,
        scheduler.ACTION_LOCK_KEY,
    }
    assert len(keys) == 7
    import inspect

    assert "observe_actions" in inspect.getsource(scheduler.start_scheduler)


async def test_observe_job_runs_only_under_its_lock():
    seen: list[int] = []

    def lock(held):
        @asynccontextmanager
        async def _l(key):
            seen.append(key)
            yield held

        return _l

    tick = AsyncMock(return_value={"settled": 0})
    with patch.object(scheduler, "advisory_lock", lock(False)), patch.object(
        svc, "observe_tick", tick
    ):
        await scheduler.observe_actions()
    tick.assert_not_awaited()
    assert seen == [scheduler.ACTION_LOCK_KEY]


# tenant isolation


class Capture:
    def __init__(self):
        self.stmts = []

    async def execute(self, stmt, params=None):
        self.stmts.append(stmt)
        return Res([])


@pytest.mark.parametrize(
    "fn",
    ["get_grant", "get_action", "get_action_type", "get_agent"],
)
async def test_lookups_are_scoped_to_the_tenant(fn):
    db = Capture()
    got = await getattr(svc, fn)(db, TENANT, uuid.uuid4())
    assert got is None
    sql = str(db.stmts[0])
    assert "tenant_id" in sql
    assert TENANT in db.stmts[0].compile().params.values()


async def test_other_tenant_sees_nothing(store):
    owner = _user(name="Owner")
    _, grant, _, _ = await _enrolled(store, owner)
    act = _action(store, grant)
    outsider = _user(tenant=OTHER, name="Eve")
    db = FakeSession(store)
    for call in (
        router.get_grant(str(grant.id), outsider, db),
        router.get_action(str(act.id), outsider, db),
        router.review(str(act.id), router.ReviewBody(answer="agree"), outsider, db),
        router.promote(str(grant.id), outsider, db),
    ):
        resp = await call
        assert resp.status_code == 404
    data = _body(await router.overview(outsider, db))["data"]
    assert data["grants"] == [] and data["counts"]["actions_7d"] == 0


# enrolment


async def test_enrol_creates_watching_grant_and_is_idempotent(store):
    owner = _user(role=UserRole.CREATOR, name="Owner")
    agent, grant, row, db = await _enrolled(store, owner)
    assert row["level"] == 1 and row["level_label"] == "Watching"
    assert row["action_type"]["key"] == svc.SAMPLE_ACTION_KEY
    assert grant.agent_config_hash == "h1"
    assert [(c.from_level, c.to_level, c.actor_type) for c in store.changes] == [
        (0, 1, "user")
    ]
    with patch.object(svc, "tool_effect", return_value=(None, "low")):
        again = await svc.enrol(
            db,
            owner,
            agent.id,
            "sample_plant",
            svc.sample_action_type_spec(),
            key=svc.SAMPLE_ACTION_KEY,
        )
    assert again["id"] == row["id"] and len(store.grants) == 1


async def test_enrol_refuses_bad_input_in_plain_words(store):
    owner = _user(name="Owner")
    agent = _agent(store, owner, tools=("email_sender",))
    db = FakeSession(store)
    body = router.EnrolBody(
        agent_id=str(agent.id),
        tool_name="sample_plant",
        action_type=router.ActionTypeSpec(label="Set it"),
    )
    resp = await router.enrol(body, owner, db)
    assert resp.status_code == 400
    assert _body(resp)["error"]["error_code"] == "TOOL_NOT_ON_AGENT"
    body = router.EnrolBody(
        agent_id=str(agent.id),
        tool_name="email_sender",
        action_type=router.ActionTypeSpec(
            label="Send", world_model={"kind": "crystal"}
        ),
    )
    with patch.object(svc, "tool_effect", return_value=(None, "low")):
        resp = await router.enrol(body, owner, db)
    assert resp.status_code == 400 and "kind" in _body(resp)["error"]["message"]


async def test_enrol_options_lists_effect_tools_with_prefill(store):
    owner = _user(name="Owner")
    agent = _agent(store, owner, tools=("sample_plant", "calculator"))
    db = FakeSession(store)
    effects = {
        "sample_plant": ({"kind": "control", "label": "Change it"}, "low"),
        "calculator": ({"kind": "read", "label": "Read only"}, "low"),
    }
    with patch.object(svc, "tool_effect", side_effect=lambda n: effects[n]):
        data = _body(await router.enrol_options(str(agent.id), owner, db))["data"]
    assert [t["tool_name"] for t in data["tools"]] == ["sample_plant"]
    pre = data["tools"][0]["prefill"]
    assert pre["outcome_probe"]["tool"] == "sample_plant"
    assert pre["limits_decision_key"] == svc.SAMPLE_LIMITS_KEY


# reviews and recommendation


async def test_reviews_show_the_card_unless_an_admin_hides_it(store, monkeypatch):
    owner = _user(name="Owner")
    _, grant, _, db = await _enrolled(store, owner)
    _action(store, grant)
    data = _body(await router.reviews(20, owner, db))["data"]
    item = data["items"][0]
    assert data["hide_until_answered"] is False
    assert item["card"]["arguments"]["setpoint_bar"] == 4.8
    assert item["situation"].endswith("Would you have done the same?")
    monkeypatch.setattr(
        svc,
        "tenant_settings",
        AsyncMock(return_value={"autonomy": {"hide_until_answered": True}}),
    )
    item = _body(await router.reviews(20, owner, db))["data"]["items"][0]
    assert item["card"] is None and item["arguments"] is None
    assert item["proposal_hidden"] is True
    assert item["situation"].endswith("What would you have done?")


async def test_review_rules_and_recommendation_once_per_level(store):
    owner = _user(name="Owner")
    reviewer = _user(role=UserRole.USER, name="Rita")
    _, grant, _, db = await _enrolled(store, owner)
    acts = [_action(store, grant) for _ in range(6)]
    resp = await router.review(
        str(acts[0].id), router.ReviewBody(answer="different"), reviewer, db
    )
    assert resp.status_code == 400
    assert _body(resp)["error"]["error_code"] == "ALTERNATIVE_REQUIRED"
    for a in acts[:5]:
        resp = await router.review(
            str(a.id), router.ReviewBody(answer="agree"), reviewer, db
        )
        assert resp.status_code == 200
    row = _body(resp)["data"]
    assert row["reviewer_answer"] == "agree" and row["card"]["action_id"] == str(a.id)
    resp = await router.review(
        str(acts[0].id), router.ReviewBody(answer="agree"), reviewer, db
    )
    assert resp.status_code == 409
    recs = [e for e in store.events if e[0] == "autonomy.recommended"]
    assert len(recs) == 1 and recs[0][1]["to_level"] == 2
    assert grant.recommended_level == 2
    assert any(n["type"] == "autonomy_recommended" for n in store.notes)
    await router.review(
        str(acts[5].id), router.ReviewBody(answer="agree"), reviewer, db
    )
    assert len([e for e in store.events if e[0] == "autonomy.recommended"]) == 1
    executed = _action(store, grant, status="executed", mode="auto")
    resp = await router.review(
        str(executed.id), router.ReviewBody(answer="agree"), reviewer, db
    )
    assert resp.status_code == 409


# promotion and separation of duties


async def _ready_watching(store, owner):
    agent, grant, _, db = await _enrolled(store, owner)
    for _ in range(6):
        _action(store, grant, reviewer_answer="agree", score={"agreement": 1.0})
    return agent, grant, db


async def test_author_cannot_promote(store):
    owner = _user(name="Owner")
    _, grant, db = await _ready_watching(store, owner)
    resp = await router.promote(str(grant.id), owner, db)
    assert resp.status_code == 403
    err = _body(resp)["error"]
    assert err["error_code"] == "AUTHOR_CANNOT_GRANT"
    assert err["message"] == (
        "You built this agent, so someone else has to approve its promotion."
    )


async def test_solo_author_self_approves_with_a_label(store, monkeypatch):
    monkeypatch.setattr(svc, "someone_else_can_grant", AsyncMock(return_value=False))
    owner = _user(name="Owner")
    _, grant, db = await _ready_watching(store, owner)
    resp = await router.promote(str(grant.id), owner, db)
    assert resp.status_code == 201, _body(resp)
    appr = _body(resp)["data"]
    assert appr["payload"]["self_approval"] == svc.SOLO_SELF_APPROVAL
    resp = await approvals_router.sign_off(
        appr["id"], ApprovalSignoffRequest(decision="approve"), owner, db
    )
    assert resp.status_code == 200, _body(resp)
    assert grant.level == 2
    last = store.changes[-1]
    assert last.reason.startswith("Self-approved by")
    assert last.evidence["self_approved"] is True


async def test_teammate_joining_ends_self_approval(store, monkeypatch):
    lone = AsyncMock(return_value=False)
    monkeypatch.setattr(svc, "someone_else_can_grant", lone)
    owner = _user(name="Owner")
    _, grant, db = await _ready_watching(store, owner)
    appr = _body(await router.promote(str(grant.id), owner, db))["data"]
    lone.return_value = True
    resp = await approvals_router.sign_off(
        appr["id"], ApprovalSignoffRequest(decision="approve"), owner, db
    )
    assert resp.status_code == 403
    assert _body(resp)["error"]["error_code"] == "AUTHOR_CANNOT_GRANT"
    assert grant.level == 1


async def test_sample_author_self_approves(store):
    owner = _user(name="Owner")
    _, grant, db = await _ready_watching(store, owner)
    at = next(a for a in store.types if a.id == grant.action_type_id)
    at.is_sample = True
    resp = await router.promote(str(grant.id), owner, db)
    assert resp.status_code == 201, _body(resp)
    assert _body(resp)["data"]["payload"]["self_approval"] == svc.SAMPLE_SELF_APPROVAL


async def test_not_ready_lists_requirements(store):
    owner = _user(name="Owner")
    _, grant, _, db = await _enrolled(store, owner)
    resp = await router.promote(str(grant.id), _user(name="Grace"), db)
    assert resp.status_code == 409
    err = _body(resp)["error"]
    assert err["error_code"] == "NOT_READY"
    reqs = err["details"]["requirements"]
    assert reqs and any(r["label"] == "0 of 5 reviews" for r in reqs)
    assert "0 of 5 reviews" in err["message"]


async def test_promotion_through_approval_with_sod(store, monkeypatch):
    owner = _user(name="Owner")
    granter = _user(name="Grace")
    store.users[str(granter.id)] = "Grace"
    _, grant, db = await _ready_watching(store, owner)
    resp = await router.promote(str(grant.id), granter, db)
    assert resp.status_code == 201
    appr = _body(resp)["data"]
    assert appr["gate_kind"] == "autonomy.promote"
    assert appr["payload"]["from"] == 1 and appr["payload"]["to"] == 2
    again = _body(await router.promote(str(grant.id), granter, db))["data"]
    assert again["id"] == appr["id"] and len(store.approvals) == 1
    caps.invalidate()
    resp = await approvals_router.sign_off(
        appr["id"], ApprovalSignoffRequest(decision="approve"), owner, db
    )
    assert resp.status_code == 403
    assert _body(resp)["error"]["error_code"] == "AUTHOR_CANNOT_GRANT"
    assert grant.level == 1
    resp = await approvals_router.sign_off(
        appr["id"], ApprovalSignoffRequest(decision="approve"), granter, db
    )
    assert resp.status_code == 200, _body(resp)
    assert grant.level == 2 and grant.granted_by == granter.id
    last = store.changes[-1]
    assert (last.from_level, last.to_level, last.actor_type) == (1, 2, "user")
    assert last.actor_id == granter.id
    assert any(e[0] == "autonomy.promoted" for e in store.events)


async def test_promotion_needs_the_grant_capability_to_sign(store):
    owner = _user(name="Owner")
    granter = _user(name="Grace")
    _, grant, db = await _ready_watching(store, owner)
    appr = _body(await router.promote(str(grant.id), granter, db))["data"]
    plain = _user(role=UserRole.CREATOR, name="Carl")
    caps.invalidate()
    resp = await approvals_router.sign_off(
        appr["id"], ApprovalSignoffRequest(decision="approve"), plain, db
    )
    assert (
        resp.status_code == 403 and "autonomy.grant" in _body(resp)["error"]["message"]
    )


async def test_turning_back_on_from_off_needs_no_approval(store):
    owner = _user(name="Owner")
    _, grant, _, db = await _enrolled(store, owner)
    await router.demote(str(grant.id), router.DemoteBody(to_level=0), owner, db)
    assert grant.level == 0
    data = _body(await router.promote(str(grant.id), _user(name="Grace"), db))["data"]
    assert data["applied"] is True and grant.level == 1 and not store.approvals


# demote, patch, unenrol


async def test_demote_is_immediate_and_only_downwards(store):
    owner = _user(name="Owner")
    _, grant, _, db = await _enrolled(store, owner)
    grant.level = 3
    resp = await router.demote(str(grant.id), router.DemoteBody(to_level=3), owner, db)
    assert resp.status_code == 400
    resp = await router.demote(
        str(grant.id), router.DemoteBody(to_level=1, reason="Night shift"), owner, db
    )
    data = _body(resp)["data"]
    assert data["level"] == 1 and grant.level == 1 and not store.approvals
    change = store.changes[-1]
    assert change.actor_type == "user" and change.reason == "Night shift"
    assert any(e[0] == "autonomy.demoted" for e in store.events)


async def test_ceiling_can_only_be_lowered(store):
    owner = _user(name="Owner")
    _, grant, _, db = await _enrolled(store, owner, tier="high")
    grant.level = 3
    resp = await router.patch_grant(
        str(grant.id), router.GrantPatch(ceiling=4), owner, db
    )
    assert resp.status_code == 400
    assert _body(resp)["error"]["error_code"] == "CEILING_RAISE"
    resp = await router.patch_grant(
        str(grant.id), router.GrantPatch(ceiling=2, state="paused"), owner, db
    )
    data = _body(resp)["data"]
    assert data["ceiling"] == 2 and data["state"] == "paused" and grant.level == 2


async def test_unenrol_keeps_history(store):
    owner = _user(name="Owner")
    _, grant, _, db = await _enrolled(store, owner)
    _action(store, grant)
    resp = await router.delete_grant(str(grant.id), owner, db)
    assert _body(resp)["data"]["removed"] is True
    assert grant.state == "removed" and grant.level == 0
    assert store.actions and store.changes
    assert (await router.get_grant(str(grant.id), owner, db)).status_code == 404


# outcomes and harm


async def test_manual_outcome_scores_the_action(store):
    owner = _user(name="Owner")
    _, grant, _, db = await _enrolled(store, owner)
    grant.level = 2
    act = _action(
        store, grant, status="executed", mode="proposed", score={"agreement": 1.0}
    )
    resp = await router.record_outcome(
        str(act.id), router.OutcomeBody(value=4.5, note="gauge"), owner, db
    )
    row = _body(resp)["data"]
    assert row["outcome_status"] == "manual"
    assert row["score"] == {
        "within_band": True,
        "band_ok": True,
        "agreement": 1.0,
        "harm": False,
    }
    assert row["outcome"]["value"] == 4.5 and row["outcome"]["source"] == "manual"
    assert any(e[0] == "action.outcome_recorded" for e in store.events)
    watching = _action(store, grant)
    resp = await router.record_outcome(
        str(watching.id), router.OutcomeBody(value=4.5), owner, db
    )
    assert resp.status_code == 409


async def test_harm_demotes_to_asks_first_and_notifies(store):
    owner = _user(name="Owner")
    flagger = _user(role=UserRole.USER, name="Rita")
    agent, grant, _, db = await _enrolled(store, owner)
    grant.level = 4
    act = _action(store, grant, status="executed", mode="reported")
    resp = await router.flag_harm(str(act.id), router.HarmBody(note=""), flagger, db)
    assert resp.status_code == 400
    resp = await router.flag_harm(
        str(act.id), router.HarmBody(note="Pressure spiked"), flagger, db
    )
    assert resp.status_code == 200
    assert grant.level == 2
    change = store.changes[-1]
    assert (change.from_level, change.to_level, change.actor_type) == (4, 2, "system")
    assert "Pressure spiked" in change.reason
    demoted = [e for e in store.events if e[0] == "autonomy.demoted"]
    assert demoted and demoted[-1][1]["to_level"] == 2
    assert {n["user_id"] for n in store.notes if n["type"] == "autonomy_demoted"} == {
        owner.id
    }
    resp = await router.flag_harm(
        str(act.id), router.HarmBody(note="again"), flagger, db
    )
    assert resp.status_code == 409


# external proposals


async def _propose(store, user, grant_level, **body):
    db = FakeSession(store)
    if grant_level is not None:
        store.grants[-1].level = grant_level
    payload = {
        "agent_id": body.pop("agent_id", None),
        "action_key": svc.SAMPLE_ACTION_KEY,
        "arguments": {"operation": "set_setpoint", "setpoint_bar": 4.8},
        "target": "plant-1",
        "intent": "Pressure is low",
        "prediction": {"metric": "pressure_bar", "value": 4.4, "low": 4.2, "high": 4.7},
    }
    payload.update(body)
    resp = await router.propose(router.ProposeBody(**payload), user, db)
    return resp, _body(resp)


@pytest.mark.parametrize(
    "level,decision,status,mode",
    [
        (0, "blocked", "blocked", "external"),
        (1, "watching", "watching", "watching"),
        (2, "wait", "pending", "proposed"),
        (3, "run", "approved", "auto"),
        (4, "run", "approved", "reported"),
    ],
)
async def test_external_propose_at_each_level(store, level, decision, status, mode):
    owner = _user(name="Owner")
    agent, grant, _, _ = await _enrolled(store, owner)
    resp, body = await _propose(store, owner, level, agent_id=str(agent.id))
    assert resp.status_code == 201, body
    data = body["data"]
    assert data["decision"] == decision and data["message"]
    act = store.actions[-1]
    assert (act.status, act.mode, act.level_at_time) == (status, mode, level)
    if decision == "wait":
        appr = store.approvals[-1]
        assert data["approval_id"] == str(appr.id)
        assert appr.gate_kind == f"action:{svc.SAMPLE_ACTION_KEY}"
        assert appr.payload["action_id"] == str(act.id)
        assert appr.payload["level_label"] == "Asks first"
        assert appr.payload["editable_arguments"] is True
    if level == 4:
        assert any(n["type"] == "action_reported" for n in store.notes)
    assert any(e[0] == "action.proposed" for e in store.events)


async def test_external_level_three_falls_back_without_a_prediction(store):
    owner = _user(name="Owner")
    agent, grant, _, _ = await _enrolled(store, owner)
    _, body = await _propose(store, owner, 3, agent_id=str(agent.id), prediction=None)
    assert body["data"]["decision"] == "wait"
    assert store.approvals[-1].payload["fallback_reason"].startswith("No prediction")
    _, body = await _propose(
        store,
        owner,
        3,
        agent_id=str(agent.id),
        prediction={"metric": "pressure_bar", "value": 4.4, "low": 1, "high": 9},
    )
    assert body["data"]["decision"] == "wait"
    assert "too wide" in store.approvals[-1].payload["fallback_reason"]


async def test_external_limit_breach_blocks_at_every_level(store):
    owner = _user(name="Owner")
    agent, grant, _, _ = await _enrolled(store, owner, limits_key="sample_plant_limits")
    store.limits = lambda facts: {
        "ok": facts.get("setpoint_bar", 0) <= 6,
        "reasons": ["The setpoint is above the 6 bar maximum"],
    }
    for level in (1, 2, 3, 4):
        _, body = await _propose(
            store,
            owner,
            level,
            agent_id=str(agent.id),
            arguments={"operation": "set_setpoint", "setpoint_bar": 7.2},
        )
        assert body["data"]["decision"] == "blocked"
        assert "6 bar maximum" in body["data"]["message"]
        assert store.actions[-1].limits_result["ok"] is False


async def test_external_unknown_action_and_unenrolled(store):
    owner = _user(name="Owner")
    resp, body = await _propose(store, owner, None)
    assert resp.status_code == 404 and body["error"]["error_code"] == "UNKNOWN_ACTION"
    agent, grant, _, _ = await _enrolled(store, owner)
    grant.state = "removed"
    _, body = await _propose(store, owner, None, agent_id=str(agent.id))
    assert body["data"]["decision"] == "run"
    assert store.actions[-1].mode == "external"


async def test_action_gate_round_trip_with_edited_arguments(store):
    owner = _user(name="Owner")
    approver = _user(name="Grace")
    store.users[str(approver.id)] = "Grace"
    agent, grant, _, db = await _enrolled(store, owner)
    _, body = await _propose(store, owner, 2, agent_id=str(agent.id))
    aid, appr_id = body["data"]["action_id"], body["data"]["approval_id"]
    bad = await approvals_router.sign_off(
        appr_id,
        ApprovalSignoffRequest(decision="approve", edited_arguments={"valve": 1}),
        approver,
        db,
    )
    assert bad.status_code == 400
    assert _body(bad)["error"]["error_code"] == "BAD_EDITED_ARGUMENTS"
    caps.invalidate()
    resp = await approvals_router.sign_off(
        appr_id,
        ApprovalSignoffRequest(
            decision="approve", edited_arguments={"setpoint_bar": 4.6}
        ),
        approver,
        db,
    )
    assert resp.status_code == 200, _body(resp)
    appr = store.approvals[-1]
    assert appr.payload["edited_arguments"] == {
        "operation": "set_setpoint",
        "setpoint_bar": 4.6,
    }
    act = store.actions[-1]
    assert act.status == "edited" and act.decided_by == approver.id
    assert act.score["agreement"] == 0.5
    waited = _body(await router.wait_action(aid, 1, owner, db))["data"]
    assert waited["decision"] == "run" and waited["arguments"]["setpoint_bar"] == 4.6
    assert waited["decided_by_name"] == "Grace"
    data = _body(
        await router.mark_executed(
            aid, router.ExecutedBody(ok=True, result_preview="x" * 900), owner, db
        )
    )["data"]
    assert data["status"] == "executed" and data["outcome_status"] == "pending"
    assert len(act.result_preview) == 500 and act.outcome_due_at is not None
    assert any(e[0] == "action.executed" for e in store.events)


async def test_edited_arguments_only_for_action_gates(store):
    owner = _user(name="Owner")
    granter = _user(name="Grace")
    _, grant, db = await _ready_watching(store, owner)
    appr = _body(await router.promote(str(grant.id), granter, db))["data"]
    resp = await approvals_router.sign_off(
        appr["id"],
        ApprovalSignoffRequest(decision="approve", edited_arguments={"a": 1}),
        granter,
        db,
    )
    assert resp.status_code == 400


async def test_rejected_gate_marks_the_action(store):
    owner = _user(name="Owner")
    approver = _user(name="Grace")
    store.users[str(approver.id)] = "Grace"
    agent, grant, _, db = await _enrolled(store, owner)
    _, body = await _propose(store, owner, 2, agent_id=str(agent.id))
    caps.invalidate()
    await approvals_router.sign_off(
        body["data"]["approval_id"],
        ApprovalSignoffRequest(decision="deny", reason="Too high for the night"),
        approver,
        db,
    )
    act = store.actions[-1]
    assert act.status == "rejected" and act.decision_note == "Too high for the night"
    waited = _body(await router.wait_action(str(act.id), 1, owner, db))["data"]
    assert waited["decision"] == "blocked" and "Grace" in waited["message"]
    resp = await router.mark_executed(
        str(act.id), router.ExecutedBody(ok=True), owner, db
    )
    assert resp.status_code == 409


# the observe job


async def test_observe_tool_probe_scores_and_unknown_after_retries(store):
    owner = _user(name="Owner")
    _, grant, _, db = await _enrolled(store, owner)
    act = _action(
        store,
        grant,
        status="executed",
        mode="auto",
        outcome_status="pending",
        outcome_due_at=_now() - timedelta(seconds=1),
    )
    with patch.object(svc, "probe_user", AsyncMock(return_value=owner)), patch.object(
        svc, "run_tool", AsyncMock(return_value=(True, {"pressure_bar": 4.5}, ""))
    ) as run:
        assert await svc.observe_one(db, act) is True
    assert run.await_args.args[2:] == ("sample_plant", {"operation": "read"})
    assert act.outcome_status == "observed" and act.outcome["value"] == 4.5
    assert act.score["within_band"] is True
    miss = _action(
        store,
        grant,
        status="executed",
        mode="auto",
        outcome_status="pending",
        outcome_due_at=_now() - timedelta(seconds=1),
        outcome_attempts=0,
    )
    with patch.object(svc, "probe_user", AsyncMock(return_value=owner)), patch.object(
        svc, "run_tool", AsyncMock(return_value=(False, None, "timeout"))
    ):
        assert await svc.observe_one(db, miss) is False
        assert await svc.observe_one(db, miss) is False
        assert await svc.observe_one(db, miss) is True
    assert miss.outcome_status == "unknown"


async def test_reevaluate_applies_accuracy_demotion(store):
    owner = _user(name="Owner")
    _, grant, _, db = await _enrolled(store, owner)
    grant.level = 3
    for i in range(20):
        _action(
            store,
            grant,
            status="executed",
            mode="auto",
            outcome_status="observed",
            score={"within_band": i % 4 == 0, "band_ok": True},
            created_at=_now() - timedelta(minutes=i),
        )
    await svc.reevaluate(db, grant)
    assert grant.level == 2
    assert store.changes[-1].actor_type == "system"


async def test_path_extraction_and_templates():
    obj = {"a": {"b": [{"c": 3}]}, "pressure_bar": 4.4}
    assert svc.extract_path(obj, "pressure_bar") == 4.4
    assert svc.extract_path(obj, "$.a.b[0].c") == 3
    assert svc.extract_path(obj, "a.x") is None
    assert svc.parse_content('{"pressure_bar": 4.1}') == {"pressure_bar": 4.1}
    ctx = {"args": {"setpoint": 5}}
    assert svc.render(
        {"x": "{{args.setpoint}}", "y": "at {{ args.setpoint }}"}, ctx
    ) == {
        "x": 5,
        "y": "at 5",
    }


async def test_limits_from_decision_reads_ok_and_reason():
    ok = svc.limits_from_decision(
        {"outcome": "decided", "result": {"ok": True, "reason": ""}}, "k"
    )
    assert ok == {"ok": True, "decision_key": "k", "reasons": []}
    bad = svc.limits_from_decision(
        {"outcome": "decided", "result": {"ok": False, "reason": "Too high"}}, "k"
    )
    assert bad["ok"] is False and bad["reasons"] == ["Too high"]
    miss = svc.limits_from_decision(
        {"outcome": "missing_facts", "missing_facts": ["setpoint_bar"]}, "k"
    )
    assert miss["ok"] is False and "setpoint_bar" in miss["reasons"][0]


# the sample plant


async def test_sample_limits_document_is_a_real_zen_model():
    from engine.decisions import authoring as A
    from engine.decisions.evaluator import evaluate

    doc = svc.sample_limits_document()
    assert not A.has_errors(A.validate_document(doc))
    c = A.compile_document(doc)
    for name, facts, expected in svc.SAMPLE_LIMIT_TESTS:
        ev = await evaluate(
            c.content_hash,
            c.jdm,
            facts,
            required=c.required_facts,
            fact_types=c.fact_types,
        )
        assert ev.outcome == "decided", name
        assert ev.result["ok"] is expected["ok"], name
    # the same golden-test runner the publish check uses, exact results
    from engine.decisions.validation import run_tests

    ran = await run_tests(
        c,
        [
            {"name": n, "facts": f, "expected_outcome": "decided", "expected": e}
            for n, f, e in svc.SAMPLE_LIMIT_TESTS
        ],
    )
    assert all(r["passed"] for r in ran), ran
    out = svc.limits_from_decision(
        (
            await evaluate(
                c.content_hash,
                c.jdm,
                {"setpoint_bar": 7.2},
                required=c.required_facts,
                fact_types=c.fact_types,
            )
        ).to_dict(),
        svc.SAMPLE_LIMITS_KEY,
    )
    assert out["ok"] is False and "6 bar" in out["reasons"][0]


async def test_install_sample_is_idempotent(store):
    owner = _user(name="Owner")
    agent = _agent(store, owner)
    db = FakeSession(store)
    with patch.object(
        svc, "_sample_agent", AsyncMock(return_value=agent)
    ), patch.object(
        svc, "_sample_limits", AsyncMock(return_value={"ready": True, "message": None})
    ), patch.object(
        svc, "tool_effect", return_value=(None, "low")
    ):
        first = _body(await router.install_sample(owner, db))["data"]
        second = _body(await router.install_sample(owner, db))["data"]
    assert first["grant"]["id"] == second["grant"]["id"]
    assert first["agent_id"] == str(agent.id) and first["limits_ready"] is True
    at = store.types[0]
    assert at.key == svc.SAMPLE_ACTION_KEY and at.is_sample is True
    assert at.limits_decision_key == "sample_plant_limits"
    assert at.outcome_probe["after_s"] == 30
    pol = L.merge_policy(at.policy)
    assert pol["to_asks_first"] == {"min_reviews": 5, "min_agreement_lb": 0.3}
    assert pol["to_within_limits"]["min_executed"] == 8
    assert first["grant"]["level_label"] == "Watching"


async def test_sample_agent_goes_through_the_agent_create_route(store):
    owner = _user(name="Owner")
    db = FakeSession(store)
    agent_id = uuid.uuid4()
    created = AsyncMock(
        return_value=JSONResponse(
            {"data": {"id": str(agent_id)}, "error": None}, status_code=201
        )
    )
    store.agents[str(agent_id)] = SimpleNamespace(id=agent_id, tenant_id=TENANT)
    with patch("app.routers.agents.create_agent", created), patch.object(
        svc, "default_model", AsyncMock(return_value="claude-haiku-4-5-20251001")
    ):
        got = await svc._sample_agent(db, owner)
    assert got.id == agent_id
    body = created.await_args.args[0]
    assert body.slug == "sample-plant-operator"
    assert body.name == "Plant operator (sample)"
    cfg = body.agent_model_config.model_dump()
    assert cfg["tools"] == ["sample_plant"]
    assert "_prediction" in body.system_prompt and "4.5" in body.system_prompt


async def test_sample_prompt_predicts_from_demand():
    p = svc.SAMPLE_PROMPT
    assert "_prediction" in p and "_intent" in p
    assert "setpoint_bar x demand" in p and "30 seconds" in p
    assert "4.5 / demand" in p
    assert '"low": v - 0.25' in p and '"high": v + 0.25' in p
    # the band fits the action type's relative limit at 4.5 bar
    spec = svc.sample_action_type_spec()
    assert L.band_ok({"value": 4.5, "low": 4.25, "high": 4.75}, spec["max_band_width"])
    assert svc.SAMPLE_POLICY["window"] == 20


async def test_existing_sample_is_brought_up_to_date_once(store):
    owner = _user(name="Owner")
    agent = _agent(store, owner)
    agent.system_prompt = "old prompt"
    at = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        key=svc.SAMPLE_ACTION_KEY,
        is_sample=True,
        policy={"to_asks_first": {"min_reviews": 3}},
    )
    store.types.append(at)
    db = FakeSession(store)
    assert await svc.sync_sample(db, agent) is True
    assert agent.system_prompt == svc.SAMPLE_PROMPT
    # an owner's own threshold stays, the window is added
    assert at.policy == {"to_asks_first": {"min_reviews": 3}, "window": 20}
    assert db.commits == 1
    assert await svc.sync_sample(db, agent) is False
    assert db.commits == 1


async def test_sample_agent_lookup_updates_the_installed_prompt(store):
    owner = _user(name="Owner")
    agent = _agent(store, owner)
    agent.system_prompt = "old prompt"

    class Found(FakeSession):
        async def execute(self, stmt, params=None):
            return Res([agent])

    created = AsyncMock()
    with patch("app.routers.agents.create_agent", created):
        got = await svc._sample_agent(Found(store), owner)
    assert got is agent and agent.system_prompt == svc.SAMPLE_PROMPT
    created.assert_not_awaited()


async def test_run_sample_queues_through_execute(store, monkeypatch):
    owner = _user(name="Owner")
    agent = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT)

    class One(FakeSession):
        async def execute(self, stmt, params=None):
            return Res([agent])

    calls = []

    async def execute_agent(agent_id, body, request, user, db):
        calls.append(body)
        return JSONResponse(
            {"data": {"execution_id": str(uuid.uuid4())}, "error": None}
        )

    monkeypatch.setattr("app.routers.agents.execute_agent", execute_agent)
    resp = await router.run_sample(router.SampleRunBody(count=3), owner, One(store))
    data = _body(resp)["data"]
    assert resp.status_code == 202 and len(data["execution_ids"]) == 3
    assert all(c.stream is False and c.wait is False for c in calls)
    assert calls[0].message == "Check the plant and act if needed."


# pages


async def test_overview_and_grant_page_shapes(store):
    owner = _user(name="Owner")
    granter = _user(name="Grace")
    _, grant, db = await _ready_watching(store, owner)
    data = _body(await router.overview(owner, db))["data"]
    assert set(data) == {
        "counts",
        "grants",
        "ready_to_promote",
        "recently_demoted",
        "unmanaged",
    }
    row = data["grants"][0]
    assert set(row) >= {
        "id",
        "agent",
        "action_type",
        "scope",
        "level",
        "level_label",
        "ceiling",
        "state",
        "level_since",
        "stats",
        "next",
        "spark",
        "attention",
    }
    assert set(row["stats"]) >= {
        "scored",
        "held",
        "accuracy_pct",
        "accuracy_lb_pct",
        "reviews",
        "agreement_pct",
        "executed",
        "rejected",
        "unknown",
        "harm_30d",
    }
    assert [r["id"] for r in data["ready_to_promote"]] == [str(grant.id)]
    assert row["attention"] == "Ready to move to Asks first"
    await router.demote(str(grant.id), router.DemoteBody(to_level=0), owner, db)
    data = _body(await router.overview(owner, db))["data"]
    assert data["ready_to_promote"] == []
    assert data["recently_demoted"][0]["change"]["to_label"] == "Off"
    detail = _body(await router.get_grant(str(grant.id), granter, db))["data"]
    assert detail["action_type"]["outcome_probe"]["tool"] == "sample_plant"
    assert [c["to_level"] for c in detail["changes"]] == [0, 1]
    assert isinstance(detail["chart"], list)
    page = _body(await router.grant_actions(str(grant.id), None, 2, None, granter, db))[
        "data"
    ]
    assert len(page["items"]) == 2 and page["next_before"]
    assert page["items"][0]["card"]["record"]["text"].startswith("People agreed")


async def test_action_type_patch_validates_and_marks_world_model_change(store):
    owner = _user(name="Owner")
    _, grant, _, db = await _enrolled(store, owner)
    at = store.types[0]
    resp = await router.patch_action_type(
        str(at.id), router.ActionTypePatch(outcome_probe={"kind": "psychic"}), owner, db
    )
    assert resp.status_code == 400
    resp = await router.patch_action_type(
        str(at.id),
        router.ActionTypePatch(world_model={"kind": "decision", "ref": "plant_model"}),
        owner,
        db,
    )
    assert _body(resp)["data"]["world_model"]["kind"] == "decision"
    mark = store.changes[-1]
    assert mark.from_level == mark.to_level == 1
    assert mark.reason == "How we predict changed"
    listed = _body(await router.list_action_types(owner, db))["data"]
    assert [t["key"] for t in listed] == [svc.SAMPLE_ACTION_KEY]


async def test_action_type_test_button_runs_the_probe(store):
    owner = _user(name="Owner")
    _, grant, _, db = await _enrolled(store, owner)
    at = store.types[0]
    with patch.object(
        svc, "run_tool", AsyncMock(return_value=(True, {"pressure_bar": 4.2}, ""))
    ):
        data = _body(
            await router.test_action_type(
                str(at.id), router.PartTestBody(part="outcome_probe"), owner, db
            )
        )["data"]
    assert data["ok"] is True and data["result"]["value"] == 4.2
    resp = await router.test_action_type(
        str(at.id), router.PartTestBody(part="nonsense"), owner, db
    )
    assert resp.status_code == 400


async def test_policy_patch_is_checked_and_recorded(store):
    owner = _user(name="Owner")
    _, grant, _, db = await _enrolled(store, owner)
    at = store.types[0]
    for bad in (
        {"to_asks_first": {"min_reviews": 0}},
        {"to_asks_first": {"min_agreement_lb": 70}},
        {"to_within_limits": {"min_executed": 2.5}},
        {"to_within_limits": "fast"},
        {"window": 1},
    ):
        resp = await router.patch_action_type(
            str(at.id), router.ActionTypePatch(policy=bad), owner, db
        )
        assert resp.status_code == 400, bad
    policy = {
        "to_asks_first": {"min_reviews": 5, "min_agreement_lb": 0.5},
        "to_within_limits": {"min_executed": 2, "min_accuracy_lb": 0.3},
    }
    resp = await router.patch_action_type(
        str(at.id), router.ActionTypePatch(policy=policy), owner, db
    )
    assert resp.status_code == 200
    assert at.policy == policy
    mark = store.changes[-1]
    assert mark.from_level == mark.to_level == grant.level
    assert mark.reason == "Thresholds changed by Owner"
    assert mark.evidence == {"policy": policy}
    before = len(store.changes)
    await router.patch_action_type(
        str(at.id), router.ActionTypePatch(policy=policy), owner, db
    )
    assert len(store.changes) == before


async def test_enrol_options_list_every_action_of_a_tool(store):
    owner = _user(name="Owner")
    agent = _agent(store, owner, tools=("mqtt_publish",))
    db = FakeSession(store)
    effect = (
        {"kind": "publish", "label": "Publish", "target_param": "topic"},
        "medium",
    )
    spec = {
        "label": "Battery command",
        "match": {"param": "topic", "glob": "controls.battery.x1"},
        "world_model": {"kind": "agent_stated"},
        "outcome_probe": {"kind": "manual", "after_s": 60},
    }
    with patch.object(svc, "tool_effect", return_value=effect):
        await svc.enrol(db, owner, agent.id, "mqtt_publish", spec)
        data = _body(await router.enrol_options(str(agent.id), owner, db))["data"]
    row = data["tools"][0]
    assert row["prefill"]["match_param"] == "topic"
    assert [t["key"] for t in row["existing_action_types"]] == [
        "mqtt_publish:controls.battery.x1"
    ]
    assert row["existing_action_type"] is None
    assert len(row["grants"]) == 1 and row["grant"]["id"] == row["grants"][0]["id"]


async def test_enrol_refuses_to_drop_settings_on_an_existing_action(store):
    owner = _user(name="Owner")
    first = _agent(store, owner, tools=("mqtt_publish",))
    second = _agent(store, owner, tools=("mqtt_publish",))
    db = FakeSession(store)
    spec = {
        "label": "Battery command",
        "match": {"param": "topic", "glob": "controls.b"},
        "world_model": {"kind": "agent_stated"},
        "outcome_probe": {"kind": "manual", "after_s": 60},
        "limits_decision_key": "battery.limits",
    }
    with patch.object(svc, "tool_effect", return_value=(None, "medium")):
        await svc.enrol(db, owner, first.id, "mqtt_publish", spec)
        with pytest.raises(svc.AutonomyError) as e:
            await svc.enrol(
                db,
                owner,
                second.id,
                "mqtt_publish",
                {**spec, "limits_decision_key": None},
            )
        assert e.value.code == "TYPE_EXISTS" and "hard limits" in e.value.message
        # the same settings reuse the action
        await svc.enrol(db, owner, second.id, "mqtt_publish", spec)
    assert len(store.types) == 1 and len(store.grants) == 2


def test_limit_facts_read_json_text_arguments():
    facts = svc.limit_facts({"payload": '{"mw": 60}', "note": "{oops"}, "controls.b")
    assert facts == {"payload": {"mw": 60}, "note": "{oops", "target": "controls.b"}
