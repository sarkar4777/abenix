"""Decisions 2.5.7: tier changes, the lock while proposed, publish under the higher tier, sole-operator sign-off,
withdrawn approvals, undated golden tests, file import and the key check."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core import approvers as AP
from app.routers import approvals as approvals_router
from app.routers import decisions as D
from app.schemas.connectors import ApprovalSignoffRequest
from engine import governance
from models.approval import Approval, ApprovalStatus
from models.decision import DecisionModel, DecisionVersion
from models.user import UserRole

GW = Path(__file__).resolve().parent / "fixtures" / "gw.safety.exclusion.json"


@pytest.fixture(autouse=True)
def _default_policies():
    governance.load_for_test()
    yield
    governance.load_for_test()


def _user(role=UserRole.ADMIN, tenant_id=None, email="me@example.com"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        role=role,
        email=email,
        full_name="Me",
        is_active=True,
    )


class _Res:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Db:
    """Answers each select by what it asks for, so the route runs unmodified."""

    def __init__(self, model, proposed=None, pending=None, live=None):
        self.model = model
        self.proposed = proposed
        self.pending = list(pending or [])
        self.live = list(live or [])
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        descs = getattr(stmt, "column_descriptions", None) or [{}]
        ent = getattr(descs[0].get("entity"), "__name__", "")
        name = descs[0].get("name")
        if ent == "DecisionModel":
            return _Res([self.model])
        if ent == "DecisionVersion" and name == "version":
            return _Res([self.proposed] if self.proposed is not None else [])
        if ent == "DecisionVersion":
            return _Res(self.live)
        if ent == "Approval":
            kinds = {v for v in stmt.compile().params.values() if isinstance(v, str)}
            return _Res(
                [
                    a
                    for a in self.pending + self.added
                    if isinstance(a, Approval) and a.status == ApprovalStatus.pending and a.gate_kind in kinds
                ]
            )
        return _Res([])

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def get(self, cls, ident):
        return next((a for a in self.added + self.pending if getattr(a, "id", None) == ident), None)


def _model(tier="high"):
    return DecisionModel(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), key="gw.safety.exclusion", name="Exclusion", risk_tier=tier
    )


async def _patch(db, user, **body):
    with (
        patch.object(D, "log_action", AsyncMock()) as audit,
        patch.object(D.S, "announce", AsyncMock()),
        patch.object(D, "_announce_approval", AsyncMock()),
        patch("app.services.events.emit", AsyncMock()),
    ):
        r = await D.update_model(db.model.key, D.UpdateModelBody(**body), None, user, db)
    return r, json.loads(r.body), [c.args[3] for c in audit.call_args_list]


def test_tier_change_kinds():
    assert D._tier_change("low", "high", 0) == "raise"
    assert D._tier_change("high", "high", 1) == "same"
    assert D._tier_change("high", "low", 1) == "lower_signoff"
    assert D._tier_change("medium", "low", 0) == "lower_now"


@pytest.mark.asyncio
async def test_raising_applies_at_once_and_is_audited():
    m = _model("low")
    r, body, actions = await _patch(_Db(m), _user(), risk_tier="critical")
    assert r.status_code == 200 and m.risk_tier == "critical"
    assert "decision.tier_raised" in actions


@pytest.mark.asyncio
async def test_lowering_under_a_signoff_tier_waits_for_an_approval():
    m = _model("high")
    db = _Db(m)
    user = _user()
    r, body, actions = await _patch(db, user, risk_tier="low", reason="The site no longer runs cranes")
    assert r.status_code == 202
    assert m.risk_tier == "high"
    p = body["data"]["pending_tier_change"]
    assert p["from_tier"] == "high" and p["to_tier"] == "low" and p["required_signoffs"] == 1
    a = next(x for x in db.added if isinstance(x, Approval))
    assert a.gate_kind == "decision_tier_change"
    assert a.payload["kind"] == "decision_tier_change" and a.payload["reason"] == "The site no longer runs cranes"
    assert a.payload["link"] == "/decisions/gw.safety.exclusion"
    assert a.policy["exclude_requester"] is True and a.required_signoffs == 1
    assert a.requested_by == user.id
    assert "decision.tier_change_requested" in actions and "decision.tier_lowered" not in actions


@pytest.mark.asyncio
async def test_lowering_needs_a_reason():
    m = _model("high")
    r, body, _ = await _patch(_Db(m), _user(), risk_tier="low")
    assert r.status_code == 422 and body["error"]["error_code"] == "REASON_REQUIRED"
    r, body, _ = await _patch(_Db(m), _user(), risk_tier="low", reason="   ")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_lowering_from_a_no_signoff_tier_applies_at_once():
    m = _model("medium")
    r, body, actions = await _patch(_Db(m), _user(), risk_tier="low", reason="Only drafts text")
    assert r.status_code == 200 and m.risk_tier == "low"
    assert "decision.tier_lowered" in actions


@pytest.mark.asyncio
@pytest.mark.parametrize("to", ["low", "critical"])
async def test_every_tier_change_is_locked_while_a_version_waits(to):
    m = _model("high")
    r, body, _ = await _patch(_Db(m, proposed=3), _user(), risk_tier=to, reason="trying the bypass")
    assert r.status_code == 409
    assert body["error"]["error_code"] == "TIER_LOCKED"
    assert body["error"]["message"] == (
        "Version 3 is waiting for sign-off. Withdraw it or let it finish before changing the risk tier."
    )
    assert m.risk_tier == "high"


@pytest.mark.asyncio
async def test_a_second_lowering_waits_for_the_first():
    m = _model("high")
    prior = Approval(
        id=uuid.uuid4(), status=ApprovalStatus.pending, gate_kind="decision_tier_change", payload={"to_tier": "medium"}
    )
    r, body, _ = await _patch(_Db(m, pending=[prior]), _user(), risk_tier="low", reason="Lower still")
    assert r.status_code == 409 and body["error"]["error_code"] == "TIER_CHANGE_PENDING"


@pytest.mark.asyncio
async def test_raising_withdraws_a_waiting_lowering():
    m = _model("high")
    prior = Approval(
        id=uuid.uuid4(), status=ApprovalStatus.pending, gate_kind="decision_tier_change", payload={"to_tier": "low"}
    )
    r, _, _ = await _patch(_Db(m, pending=[prior]), _user(), risk_tier="critical")
    assert r.status_code == 200 and m.risk_tier == "critical"
    assert prior.status == ApprovalStatus.withdrawn


def _approval(signoffs, status=ApprovalStatus.approved, requester=None):
    return Approval(
        id=uuid.uuid4(), status=status, signoffs=signoffs, requested_by=requester or uuid.uuid4(), required_signoffs=1
    )


def test_publish_needs_the_higher_of_proposed_and_current_tier():
    tid = str(uuid.uuid4())
    # approved with no sign-off under low, then raised to high
    refused = D._publish_refusal(tid, 2, "low", "high", None)
    assert refused and refused[0] == "TIER_CHANGED"
    assert "low risk" in refused[1] and "high risk" in refused[1]
    other = str(uuid.uuid4())
    ok = _approval([{"decision": "approve", "user_id": other}])
    assert D._publish_refusal(tid, 2, "high", "high", ok) is None
    # a lowering after proposal does not lower what publish needs
    assert D._publish_refusal(tid, 2, "high", "low", None)[0] == "TIER_CHANGED"
    assert D._publish_refusal(tid, 2, "low", "low", None) is None
    assert D._publish_refusal(tid, 2, None, "medium", None) is None


def test_the_authors_own_signoff_does_not_count_where_the_tier_excludes_it():
    tid = str(uuid.uuid4())
    me = uuid.uuid4()
    mine = _approval([{"decision": "approve", "user_id": str(me)}], requester=me)
    assert D._publish_refusal(tid, 1, "high", "high", mine)[0] == "SIGNOFF_INSUFFICIENT"
    sole = _approval([{"decision": "approve", "user_id": str(me), "sole_operator": True}], requester=me)
    assert D._publish_refusal(tid, 1, "high", "high", sole) is None
    assert D._publish_refusal(tid, 1, "critical", "critical", sole) is None
    one = _approval([{"decision": "approve", "user_id": str(uuid.uuid4())}])
    assert D._publish_refusal(tid, 1, "high", "critical", one)[0] == "TIER_CHANGED"
    pending = _approval([], status=ApprovalStatus.pending)
    assert D._publish_refusal(tid, 1, "high", "high", pending)


def test_publish_route_checks_the_tier_before_publishing():
    import inspect

    src = inspect.getsource(D.publish)
    assert "_publish_refusal(" in src and "v.risk_tier_at_proposal" in src
    assert "v.risk_tier_at_proposal = m.risk_tier" in inspect.getsource(D.propose)


def _refusal(**kw):
    base = dict(
        gate_kind="decision_publish",
        decision="approve",
        reason="Installed by the only admin here",
        is_requester=True,
        requester_can_sign=True,
        enabled=True,
        eligible_count=0,
    )
    base.update(kw)
    return AP.sole_operator_refusal(**base)


def test_sole_operator_allowed_when_nobody_else_can():
    assert _refusal() is None
    assert _refusal(gate_kind="decision_tier_change") is None


@pytest.mark.parametrize(
    "kw,status,code",
    [
        ({"reason": "too short"}, 422, "REASON_REQUIRED"),
        ({"reason": None}, 422, "REASON_REQUIRED"),
        ({"reason": "          "}, 422, "REASON_REQUIRED"),
        ({"eligible_count": 2}, 403, "OTHER_APPROVERS_EXIST"),
        ({"enabled": False}, 403, "SOLE_OPERATOR_OFF"),
        ({"gate_kind": "tool_call"}, 403, "SOLE_OPERATOR_NOT_ALLOWED"),
        ({"gate_kind": "autonomy.promote"}, 403, "SOLE_OPERATOR_NOT_ALLOWED"),
        ({"decision": "deny"}, 400, "SOLE_OPERATOR_APPROVE_ONLY"),
        ({"is_requester": False}, 403, "SOLE_OPERATOR_NOT_REQUESTER"),
        ({"requester_can_sign": False}, 403, "CANNOT_SIGN"),
    ],
)
def test_sole_operator_refused(kw, status, code):
    got = _refusal(**kw)
    assert got[0] == status and got[1] == code


def test_ten_characters_is_enough():
    assert _refusal(reason="0123456789") is None
    assert _refusal(reason="012345678")[1] == "REASON_REQUIRED"


def test_refusal_names_how_many_can_approve():
    assert _refusal(eligible_count=2)[2] == "2 people can approve this. Ask one of them."
    assert _refusal(eligible_count=1)[2] == "1 person can approve this. Ask them."


def test_setting_defaults_on():
    assert AP.setting_from({}) is True
    assert AP.setting_from({"governance": {"sole_operator_signoff": False}}) is False
    assert AP.setting_from({"governance": {"sole_operator_signoff": True}}) is True


def _person(role, caps=(), email=None):
    u = _user(role=role, email=email or f"{uuid.uuid4().hex[:6]}@example.com")
    from app.core.capabilities import ROLE_DEFAULTS

    return u, frozenset(set(ROLE_DEFAULTS[role.value]) | set(caps))


def test_eligible_approvers_need_the_capability_and_are_not_the_requester():
    admin = _person(UserRole.ADMIN)
    creator = _person(UserRole.CREATOR)
    reviewer = _person(UserRole.USER, ["approvals.sign", "decisions.review"])
    signer_only = _person(UserRole.USER, ["approvals.sign"])
    people = [admin, creator, reviewer, signer_only]
    pol = {"capability": "approvals.sign", "exclude_requester": True}
    got = AP.eligible_from(people, pol, "decision_publish", admin[0].id)
    assert [u.id for u in got] == [reviewer[0].id]
    got = AP.eligible_from(people, pol, "tool_call", admin[0].id)
    assert {u.id for u in got} == {reviewer[0].id, signer_only[0].id}
    assert AP.eligible_from([admin], pol, "decision_tier_change", admin[0].id) == []


def test_system_account_is_never_an_approver():
    import asyncio

    tid = uuid.uuid4()
    system = _user(email="system@abenix.dev", tenant_id=tid)
    admin = _user(tenant_id=tid)

    class Db:
        def __init__(self):
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            return _Res([system, admin] if self.calls == 1 else [])

    people = asyncio.run(AP.tenant_people(Db(), tid))
    assert [u.id for u, _ in people] == [admin.id]


def test_self_approved_is_shown_on_the_approval():
    a = _approval([{"decision": "approve", "user_id": "x", "sole_operator": True}])
    assert AP.is_self_approved(a) is True
    assert AP.is_self_approved(_approval([{"decision": "approve", "user_id": "x"}])) is False
    assert approvals_router._serialize(a)["self_approved"] is True


class _SignDb:
    def __init__(self, a, people):
        self.a = a
        self.people = people
        self.added = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        descs = getattr(stmt, "column_descriptions", None) or [{}]
        ent = getattr(descs[0].get("entity"), "__name__", "")
        if ent == "Approval":
            return _Res([self.a])
        if ent == "User" and descs[0].get("name") == "User":
            return _Res(self.people)
        if ent == "Tenant":
            return _Res([SimpleNamespace(settings={})])
        return _Res([])

    async def get(self, cls, ident):
        return SimpleNamespace(settings={}) if cls.__name__ == "Tenant" else None

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None


@pytest.mark.asyncio
async def test_sole_operator_signoff_is_recorded_loudly():
    me = _user()
    a = Approval(
        id=uuid.uuid4(),
        tenant_id=me.tenant_id,
        title="Publish Exclusion version 1",
        required_signoffs=2,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=me.id,
        gate_kind="decision_publish",
        policy={"exclude_requester": True, "capability": "approvals.sign"},
    )
    db = _SignDb(a, [me])
    with (
        patch("app.core.audit.log_action", AsyncMock()) as audit,
        patch.object(approvals_router, "_notify_self_approved", AsyncMock()) as notice,
        patch.object(approvals_router, "_notify_resolved", AsyncMock()),
        patch("app.services.events.emit", AsyncMock()),
        patch("app.routers.decisions.on_approval_resolved", AsyncMock()) as resolved,
    ):
        r = await approvals_router.sign_off(
            approval_id=str(a.id),
            body=ApprovalSignoffRequest(
                decision="approve",
                reason="Installed from the Groundwork repo by the only admin in this workspace",
                sole_operator=True,
            ),
            user=me,
            db=db,
        )
    body = json.loads(r.body)
    assert r.status_code == 200, body
    assert a.status == ApprovalStatus.approved
    s = a.signoffs[0]
    assert s["sole_operator"] is True and s["self_approved"] is True and s["reason"].startswith("Installed")
    assert body["data"]["self_approved"] is True
    assert audit.call_args.args[3] == "approval.self_approved"
    notice.assert_awaited_once()
    resolved.assert_awaited_once()


@pytest.mark.asyncio
async def test_sole_operator_signoff_refused_when_someone_else_can_sign():
    me = _user()
    other = _user(tenant_id=me.tenant_id, email="other@example.com")
    a = Approval(
        id=uuid.uuid4(),
        tenant_id=me.tenant_id,
        title="t",
        required_signoffs=1,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=me.id,
        gate_kind="decision_tier_change",
        policy={"exclude_requester": True, "capability": "approvals.sign"},
    )
    db = _SignDb(a, [me, other])
    r = await approvals_router.sign_off(
        approval_id=str(a.id),
        body=ApprovalSignoffRequest(decision="approve", reason="I am the only one here", sole_operator=True),
        user=me,
        db=db,
    )
    body = json.loads(r.body)
    assert r.status_code == 403
    assert body["error"]["message"] == "1 person can approve this. Ask them."
    assert a.signoffs == [] and a.status == ApprovalStatus.pending


@pytest.mark.asyncio
async def test_withdrawing_a_proposal_marks_its_approval_withdrawn():
    m = _model("high")
    a = Approval(id=uuid.uuid4(), status=ApprovalStatus.pending, gate_kind="decision_publish")
    v = DecisionVersion(
        id=uuid.uuid4(), model_id=m.id, version=1, state="proposed", approval_id=a.id, lock_version=1, risk_tier_at_proposal="high"
    )

    class Db:
        async def execute(self, stmt, params=None):
            ent = getattr(stmt.column_descriptions[0].get("entity"), "__name__", "")
            return _Res([m] if ent == "DecisionModel" else [v])

        async def get(self, cls, ident):
            return a

        async def commit(self):
            return None

        async def refresh(self, obj):
            return None

    with patch.object(D, "log_action", AsyncMock()):
        r = await D.withdraw(m.key, 1, None, _user(), Db())
    assert r.status_code == 200
    assert a.status == ApprovalStatus.withdrawn
    assert v.state == "draft" and v.approval_id is None and v.risk_tier_at_proposal is None


def test_withdrawn_is_its_own_status():
    assert ApprovalStatus("withdrawn") is ApprovalStatus.withdrawn
    assert ApprovalStatus.withdrawn != ApprovalStatus.expired


@pytest.mark.parametrize("given,stored", [(None, None), ("", None), ("  ", None), ("2026-01-01", "2026-01-01")])
def test_a_test_without_a_date_has_no_date(given, stored):
    body = D.TestBody(name="t", as_of=given)
    assert D._check_test(body) is None
    assert body.as_of == stored


def test_listed_tests_show_null_for_no_date():
    t = SimpleNamespace(
        id=uuid.uuid4(), name="t", facts={}, expected_outcome="decided", expected=None, match_mode="exact", as_of="", updated_at=None
    )
    assert D._test_json(t)["as_of"] is None


def test_suggested_keys():
    assert D._suggest_key("gw.safety.exclusion", {"gw.safety.exclusion"}) == "gw.safety.exclusion.2"
    taken = {"gw.safety.exclusion", "gw.safety.exclusion.2", "gw.safety.exclusion.3"}
    assert D._suggest_key("gw.safety.exclusion", taken) == "gw.safety.exclusion.4"
    assert D._suggest_key("gw.safety.exclusion.2", taken) == "gw.safety.exclusion.4"


class _KeyDb:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, stmt, params=None):
        return _Res(self.rows)


@pytest.mark.asyncio
async def test_check_key():
    u = _user()
    r = await D.check_key("gw.safety.exclusion", u, _KeyDb([]))
    assert json.loads(r.body)["data"] == {"available": True, "valid": True, "suggestion": None, "archived": False}
    r = await D.check_key("gw.safety.exclusion", u, _KeyDb([("gw.safety.exclusion", None)]))
    d = json.loads(r.body)["data"]
    assert d["available"] is False and d["suggestion"] == "gw.safety.exclusion.2" and d["archived"] is False
    r = await D.check_key("gw.safety.exclusion", u, _KeyDb([("gw.safety.exclusion", dt.datetime.now())]))
    d = json.loads(r.body)["data"]
    assert d["archived"] is True and "Restore" in d["message"]
    r = await D.check_key("GW Safety", u, _KeyDb([]))
    d = json.loads(r.body)["data"]
    assert d["valid"] is False and d["suggestion"] == "gw-safety"


def test_check_key_and_import_are_declared_before_the_key_routes():
    paths = [(r.path, sorted(r.methods)) for r in D.router.routes]
    first_key_get = paths.index(("/api/decisions/{key}", ["GET"]))
    assert paths.index(("/api/decisions/check-key", ["GET"])) < first_key_get
    assert ("/api/decisions/import", ["POST"]) in paths


class _ImportDb:
    def __init__(self):
        self.added = []

    async def execute(self, stmt, params=None):
        return _Res([])

    def add(self, obj):
        self.added.append(obj)


@pytest.mark.asyncio
async def test_import_preview_of_the_groundwork_file_writes_nothing():
    raw = json.loads(GW.read_text())

    class Req:
        async def json(self):
            return raw

    db = _ImportDb()
    with patch.object(D.S, "reference_values", AsyncMock(return_value=({}, {}))):
        r = await D.import_file(Req(), preview=1, as_new_key=None, as_new_name=None, user=_user(), db=db)
    d = json.loads(r.body)["data"]
    assert d["creates"] is True and d["key"] == "gw.safety.exclusion"
    assert d["rules"] == 5 and d["tests"] == 4 and d["risk_tier"] == "high"
    assert [p for p in d["problems"] if p["severity"] == "error"] == []
    assert db.added == []


@pytest.mark.asyncio
async def test_import_preview_reports_an_unreadable_file_as_a_problem():
    class Req:
        async def json(self):
            return {"key": "x", "rules": "nope"}

    r = await D.import_file(Req(), preview=1, as_new_key=None, as_new_name=None, user=_user(), db=_ImportDb())
    d = json.loads(r.body)["data"]
    assert r.status_code == 200 and d["problems"][0]["path"] == "/rules"
    r = await D.import_file(Req(), preview=0, as_new_key=None, as_new_name=None, user=_user(), db=_ImportDb())
    assert r.status_code == 400 and json.loads(r.body)["error"]["error_code"] == "BAD_FILE"


@pytest.mark.asyncio
async def test_tier_change_approval_applies_only_while_the_tier_is_unchanged():
    m = _model("high")
    approver = str(uuid.uuid4())
    a = Approval(
        id=uuid.uuid4(),
        tenant_id=m.tenant_id,
        status=ApprovalStatus.approved,
        gate_kind="decision_tier_change",
        requested_by=uuid.uuid4(),
        payload={"decision_key": m.key, "from_tier": "high", "to_tier": "low", "reason": "r"},
        signoffs=[{"decision": "approve", "user_id": approver}],
    )

    class Db:
        async def execute(self, stmt, params=None):
            ent = getattr(stmt.column_descriptions[0].get("entity"), "__name__", "")
            return _Res([m] if ent == "DecisionModel" else [])

        async def commit(self):
            return None

    with patch.object(D, "log_action", AsyncMock()) as audit, patch.object(D.S, "announce", AsyncMock()):
        await D.on_approval_resolved(Db(), a)
    assert m.risk_tier == "low"
    assert audit.call_args.args[3] == "decision.tier_lowered"
    assert audit.call_args.args[4]["approved_by"] == [approver]

    m.risk_tier = "critical"
    with patch.object(D, "log_action", AsyncMock()), patch.object(D.S, "announce", AsyncMock()):
        await D.on_approval_resolved(Db(), a)
    assert m.risk_tier == "critical"

    m.risk_tier = "high"
    a.status = ApprovalStatus.denied
    with patch.object(D, "log_action", AsyncMock()), patch.object(D.S, "announce", AsyncMock()):
        await D.on_approval_resolved(Db(), a)
    assert m.risk_tier == "high"


@pytest.mark.asyncio
async def test_tier_change_gates_need_decision_review():
    from app.core import capabilities as caps
    from app.core.hitl import approver_denial

    u = _user(role=UserRole.USER)
    with patch.object(caps, "capabilities_for", AsyncMock(return_value=frozenset({"approvals.sign"}))):
        for kind in AP.DECISION_KINDS:
            why = await approver_denial(None, u, uuid.uuid4(), {"capability": "approvals.sign"}, kind)
            assert why and why.capability == "decisions.review", kind


# section 10: a review after a tier raise


def _live_version(n=1, tier_at=None, approval_id=None, validation=None):
    return DecisionVersion(
        id=uuid.uuid4(),
        version=n,
        state="published",
        superseded_at=None,
        risk_tier_at_proposal=tier_at,
        approval_id=approval_id,
        validation=validation,
    )


def test_what_a_live_version_signoff_covers():
    tid = str(uuid.uuid4())
    v = _live_version(tier_at="low")
    assert D._covered(v, None, "medium", tid) is True
    assert D._covered(v, None, "high", tid) is False
    other = _approval([{"decision": "approve", "user_id": str(uuid.uuid4())}])
    assert D._covered(_live_version(tier_at="high"), other, "high", tid) is True
    assert D._covered(_live_version(tier_at="high"), other, "critical", tid) is False
    me = uuid.uuid4()
    alone = _approval([{"decision": "approve", "user_id": str(me), "sole_operator": True}], requester=me)
    assert D._covered(_live_version(tier_at="high"), alone, "high", tid) is True
    assert D._covered(_live_version(tier_at="high"), alone, "critical", tid) is False
    attested = _live_version(tier_at="low", validation={"attested": {"tier": "critical"}})
    assert D._covered(attested, None, "critical", tid) is True
    assert D._attested_under(attested) == "critical"


@pytest.mark.asyncio
async def test_raising_over_a_live_version_opens_a_review_and_keeps_it_in_force():
    m = _model("low")
    v = _live_version(tier_at="low")
    db = _Db(m, live=[v])
    r, body, actions = await _patch(db, _user(), risk_tier="high")
    assert r.status_code == 200 and m.risk_tier == "high"
    assert v.state == "published" and v.superseded_at is None
    a = next(x for x in db.added if isinstance(x, Approval))
    assert a.gate_kind == "decision_reattest"
    assert a.payload == {
        "kind": "decision_reattest",
        "decision_key": m.key,
        "version": 1,
        "from_tier": "low",
        "to_tier": "high",
        "link": f"/decisions/{m.key}?version=1",
    }
    assert a.required_signoffs == 1 and a.policy["risk_tier"] == "high"
    assert body["data"]["reattest"]["approval_id"] == str(a.id)
    assert body["data"]["reattest"]["status"] == "pending"
    assert "decision.reattest_requested" in actions


@pytest.mark.asyncio
async def test_no_review_when_the_signoff_already_covers_the_new_tier():
    m = _model("low")
    db = _Db(m, live=[_live_version(tier_at="low")])
    await _patch(db, _user(), risk_tier="medium")
    assert not [x for x in db.added if isinstance(x, Approval)]


@pytest.mark.asyncio
async def test_raising_again_replaces_the_waiting_review():
    m = _model("high")
    old = Approval(
        id=uuid.uuid4(),
        status=ApprovalStatus.pending,
        gate_kind="decision_reattest",
        payload={"decision_key": m.key, "version": 1, "from_tier": "low", "to_tier": "high"},
    )
    db = _Db(m, pending=[old], live=[_live_version(tier_at="low")])
    r, body, _ = await _patch(db, _user(), risk_tier="critical")
    assert old.status == ApprovalStatus.withdrawn
    new = next(x for x in db.added if isinstance(x, Approval))
    assert new.payload["to_tier"] == "critical" and new.required_signoffs == 2
    assert body["data"]["reattest"]["to_tier"] == "critical"


@pytest.mark.asyncio
async def test_closing_reviews_by_version_and_by_tier():
    m = _model("critical")

    def review(n, to):
        return Approval(
            id=uuid.uuid4(),
            status=ApprovalStatus.pending,
            gate_kind="decision_reattest",
            payload={"decision_key": m.key, "version": n, "to_tier": to},
        )

    a1, a2 = review(1, "high"), review(2, "critical")
    db = _Db(m, pending=[a1, a2])
    assert await D._close_reattests(db, m.tenant_id, m.key, "retired", versions={1}) == 1
    assert a1.status == ApprovalStatus.withdrawn and a2.status == ApprovalStatus.pending
    assert await D._close_reattests(db, m.tenant_id, m.key, "lowered", above="high") == 1
    assert a2.status == ApprovalStatus.withdrawn and a2.payload["withdrawn"] == "lowered"


def test_retire_publish_archive_and_lowering_close_reviews():
    import inspect

    for fn in (D._do_retire, D.publish, D._on_tier_change_resolved, D.update_model):
        assert "_close_reattests(" in inspect.getsource(fn), fn.__name__
    assert "_withdraw_open(" in inspect.getsource(D._do_archive)


class _ResolveDb:
    def __init__(self, v):
        self.v = v
        self.commits = 0

    async def execute(self, stmt, params=None):
        ent = getattr(stmt.column_descriptions[0].get("entity"), "__name__", "")
        return _Res([] if ent == "User" else [self.v])

    async def commit(self):
        self.commits += 1


def _review_approval(status, signoffs=None):
    return Approval(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        status=status,
        gate_kind="decision_reattest",
        requested_by=uuid.uuid4(),
        payload={"decision_key": "k", "version": 1, "from_tier": "low", "to_tier": "high"},
        signoffs=signoffs or [],
    )


@pytest.mark.asyncio
async def test_an_approved_review_records_the_tier_on_the_live_version():
    v = _live_version(tier_at="low", validation={"ok": True})
    me = str(uuid.uuid4())
    a = _review_approval(ApprovalStatus.approved, [{"decision": "approve", "user_id": me, "sole_operator": True}])
    with patch.object(D, "log_action", AsyncMock()) as audit:
        await D.on_approval_resolved(_ResolveDb(v), a)
    att = v.validation["attested"]
    assert att["tier"] == "high" and att["approved_by"] == [me] and att["self_approved"] is True
    assert v.validation["ok"] is True
    assert D._version_summary(v)["attested_under"] == "high"
    assert audit.call_args.args[3] == "decision.reattested"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [ApprovalStatus.denied, ApprovalStatus.returned, ApprovalStatus.withdrawn])
async def test_a_review_not_approved_changes_nothing(status):
    v = _live_version(tier_at="low")
    with patch.object(D, "log_action", AsyncMock()):
        await D.on_approval_resolved(_ResolveDb(v), _review_approval(status))
    assert D._attested_under(v) is None and v.state == "published"


@pytest.mark.asyncio
async def test_an_approved_review_of_a_retired_version_records_nothing():
    v = _live_version(tier_at="low")
    v.state = "retired"
    with patch.object(D, "log_action", AsyncMock()):
        await D.on_approval_resolved(
            _ResolveDb(v), _review_approval(ApprovalStatus.approved, [{"decision": "approve", "user_id": "x"}])
        )
    assert D._attested_under(v) is None


def test_reviews_allow_sole_operator_and_need_decision_review():
    import inspect

    from app.core import hitl

    assert _refusal(gate_kind="decision_reattest") is None
    assert "decision_reattest" in AP.SOLE_OPERATOR_KINDS
    assert "DECISION_KINDS" in inspect.getsource(hitl.approver_denial)


@pytest.mark.asyncio
async def test_improvements_withdraw_marks_the_approval_withdrawn():
    from app.services import improvements

    a = Approval(id=uuid.uuid4(), status=ApprovalStatus.pending, payload={})
    p = SimpleNamespace(approval_id=a.id)

    class Db:
        async def get(self, cls, ident):
            return a

    await improvements._withdraw_approval(Db(), p, "edited")
    assert a.status == ApprovalStatus.withdrawn and a.payload["withdrawn"] == "edited"
    assert p.approval_id is None


def test_retire_reads_the_row_back_before_showing_it():
    import inspect

    src = inspect.getsource(D.retire)
    assert src.index("await db.refresh(v)") > src.index("await db.commit()")
