"""Decisions 2.5.7 wave 2: who can approve in plain words, sign-off for retire, archive and restore,
the honest state summary, deny with a reason, safer import, discarding drafts and archived matches."""

from __future__ import annotations

import datetime as dt
import inspect
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.core import approvers as AP
from app.core import capabilities as caps
from app.routers import approvals as approvals_router
from app.routers import decisions as D
from app.routers import inbox
from app.schemas.connectors import ApprovalSignoffRequest
from engine import governance
from models.approval import Approval, ApprovalStatus
from models.decision import DecisionModel, DecisionTest, DecisionVersion
from models.governance import PermissionAssignment, PermissionSet
from models.user import UserRole


@pytest.fixture(autouse=True)
def _default_policies():
    governance.load_for_test()
    yield
    governance.load_for_test()


def _user(role=UserRole.ADMIN, tenant_id=None, email=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        role=role,
        email=email or f"{uuid.uuid4().hex[:6]}@example.com",
        full_name="Someone",
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

    def first(self):
        return self.rows[0] if self.rows else None


def _sql(stmt) -> str:
    from sqlalchemy.dialects import postgresql

    return str(stmt.compile(dialect=postgresql.dialect()))


# 11. plain words


def test_capability_words_never_show_the_id():
    assert caps.cap_words("decisions.review") == 'the "Review decisions" permission'
    assert caps.cap_words("approvals.sign:legal") == 'the "Sign approvals" permission for legal'
    msg = caps.need_words("risk.manage")
    assert "risk.manage" not in msg and "Manage risk policies" in msg


@pytest.mark.asyncio
async def test_a_missing_capability_is_refused_in_plain_words_with_the_id_kept():
    check = caps.require_capability("decisions.publish")
    with patch.object(caps, "capabilities_for", AsyncMock(return_value=frozenset())):
        with pytest.raises(HTTPException) as e:
            await check(user=_user(role=UserRole.USER), db=None)
    d = e.value.detail
    assert e.value.status_code == 403 and d["error_code"] == "MISSING_PERMISSION"
    assert d["details"]["capability"] == "decisions.publish"
    assert "decisions.publish" not in d["message"] and "Publish decisions" in d["message"]


def test_no_router_message_names_a_capability_id():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "apps" / "api" / "app"
    ids = [c.key for c in caps.CATALOG]
    bad = []
    for f in root.rglob("*.py"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith("#") or "Capability(" in s:
                continue
            for k in ids:
                # an id inside a sentence, a string with a space in it
                if re.search(r"[\"'][^\"']*\s[^\"']*\b" + re.escape(k) + r"\b[^\"']*[\"']", s):
                    if '"""' in s or "covers" in s or "Add a suffix" in s:
                        continue
                    bad.append(f"{f.name}:{i}")
    assert not bad, bad


def _row(kind="decision_publish", requested_by=None, policy=None, signoffs=None):
    return dict(
        requested_by=requested_by or uuid.uuid4(),
        policy=policy if policy is not None else {"capability": "approvals.sign", "exclude_requester": True},
        gate_kind=kind,
        signoffs=signoffs or [],
    )


def test_a_member_cannot_sign_decision_approvals_and_does_not_see_them():
    m = _user(role=UserRole.USER)
    granted = caps.ROLE_DEFAULTS["user"]
    for kind in AP.DECISION_KINDS:
        check = AP.sign_check(m, granted, **_row(kind))
        assert check[0] == "NOT_REVIEWER", kind
        assert "decisions.review" not in check[1] and "Decision reviewers" in check[1]
        assert AP.visible_to(m, check, uuid.uuid4()) is False
        assert AP.visible_to(m, check, m.id) is True


def test_a_decision_reviewer_can_sign_and_sees_it():
    r = _user(role=UserRole.USER)
    granted = frozenset(caps.ROLE_DEFAULTS["user"] | {"approvals.sign", "decisions.review"})
    assert AP.can_approve_decisions(granted)
    assert AP.sign_check(r, granted, **_row()) is None
    own = AP.sign_check(r, granted, **_row(requested_by=r.id))
    assert own[0] == "OWN_REQUEST" and AP.visible_to(r, own, r.id)
    signed = AP.sign_check(r, granted, **_row(signoffs=[{"user_id": str(r.id)}]))
    assert signed[0] == "ALREADY_SIGNED" and AP.visible_to(r, signed, uuid.uuid4())


def test_a_member_does_not_see_runtime_gates_of_others():
    m = _user(role=UserRole.USER)
    check = AP.sign_check(
        m, caps.ROLE_DEFAULTS["user"], requested_by=uuid.uuid4(), policy=None, gate_kind="human_approval", signoffs=[]
    )
    assert check[0] == "NOT_SIGNER" and not AP.visible_to(m, check, uuid.uuid4())


def test_needs_you_and_approvals_use_the_same_rule():
    m = _user(role=UserRole.USER)
    granted = caps.ROLE_DEFAULTS["user"]
    for kind in AP.DECISION_KINDS + ("tool_call",):
        r = _row(kind)
        assert inbox.can_sign(m, granted, **r) is (AP.sign_check(m, granted, **r) is None)
    assert "sign_check" in inspect.getsource(inbox.can_sign)
    assert "_check_row" in inspect.getsource(approvals_router._serialize_many)


def test_list_rows_say_whether_the_viewer_can_sign_and_why_not():
    a = Approval(id=uuid.uuid4(), status=ApprovalStatus.pending, gate_kind="decision_publish")
    row = approvals_router._with_viewer({}, a, ("NOT_REVIEWER", caps.REVIEWER_REFUSAL), False)
    assert row["can_sign"] is False and row["cannot_sign_reason"] == caps.REVIEWER_REFUSAL
    row = approvals_router._with_viewer({}, a, None, False)
    assert row["can_sign"] is True and row["cannot_sign_reason"] is None
    row = approvals_router._with_viewer({}, a, ("OWN_REQUEST", "x"), True)
    assert row["can_sign"] is True and row["sign_alone"] is True
    a.status = ApprovalStatus.approved
    row = approvals_router._with_viewer({}, a, None, False)
    assert row["can_sign"] is False and row["cannot_sign_reason"] == "This is already approved."


def test_the_list_filters_unless_an_admin_asks_for_all():
    src = inspect.getsource(approvals_router.list_approvals)
    assert "everything = bool(all) and is_admin(user)" in src
    assert 'r.get("visible", True)' in src


class _SetDb:
    def __init__(self, by_key=None, by_name=None, assigned=None):
        self.by_key, self.by_name, self.assigned = by_key, by_name, assigned
        self.added = []

    async def execute(self, stmt, params=None):
        sql = _sql(stmt)
        if "permission_assignments" in sql:
            return _Res([self.assigned] if self.assigned else [])
        if "builtin_key" in sql.split("WHERE")[-1]:
            return _Res([self.by_key] if self.by_key else [])
        return _Res([self.by_name] if self.by_name else [])

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, PermissionSet):
            obj.id = uuid.uuid4()

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_decision_reviewers_is_created_once_and_adopts_a_set_with_that_name():
    tid = uuid.uuid4()
    db = _SetDb()
    ps = await AP.ensure_decision_reviewers(db, tid)
    assert ps.name == "Decision reviewers" and ps.builtin_key == "decision_reviewers"
    assert sorted(ps.capabilities) == ["approvals.sign", "decisions.review"]
    mine = PermissionSet(id=uuid.uuid4(), tenant_id=tid, name="Decision reviewers", capabilities=[])
    db = _SetDb(by_name=mine)
    assert await AP.ensure_decision_reviewers(db, tid) is mine and mine.builtin_key == "decision_reviewers"
    assert db.added == []


@pytest.mark.asyncio
async def test_adding_a_reviewer_twice_adds_once():
    tid, uid = uuid.uuid4(), uuid.uuid4()
    have = PermissionSet(id=uuid.uuid4(), tenant_id=tid, name="Decision reviewers", builtin_key="decision_reviewers")
    db = _SetDb(by_key=have)
    assert await AP.add_decision_reviewer(db, tid, uid) is True
    assert any(isinstance(o, PermissionAssignment) and o.user_id == uid for o in db.added)
    db = _SetDb(by_key=have, assigned=uuid.uuid4())
    assert await AP.add_decision_reviewer(db, tid, uid) is False


def test_register_seeds_the_set_and_me_says_who_can_approve():
    from app.routers import auth, governance as gov_router, me

    assert "ensure_decision_reviewers" in inspect.getsource(auth.register)
    assert "ensure_decision_reviewers" in inspect.getsource(gov_router.list_permission_sets)
    assert "can_approve_decisions" in inspect.getsource(me.my_permissions)


# 11. Needs you: a new member is not asked to review other people's agents


def test_watching_reviews_are_scoped_to_your_own_agents():
    from app.services.autonomy import review_scope

    assert review_scope(_user(role=UserRole.ADMIN)) == []
    clause = review_scope(_user(role=UserRole.USER))
    assert len(clause) == 1
    sql = _sql(clause[0])
    assert "agents.creator_id" in sql and "autonomy_grants.granted_by" in sql
    assert "review_scope(user)" in inspect.getsource(inbox._watching)


# 14. deny with a reason


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", [None, "", "   ", "nope"])
async def test_deny_needs_a_reason(reason):
    r = await approvals_router.sign_off(
        str(uuid.uuid4()), ApprovalSignoffRequest(decision="deny", reason=reason), _user(), None
    )
    body = json.loads(r.body)
    assert r.status_code == 422 and body["error"]["error_code"] == "REASON_REQUIRED"


@pytest.mark.asyncio
async def test_the_requester_is_told_the_reason():
    requester = uuid.uuid4()
    a = Approval(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        title="Publish x",
        status=ApprovalStatus.denied,
        requested_by=requester,
        gate_kind="decision_publish",
        signoffs=[{"decision": "deny", "user_id": str(uuid.uuid4()), "reason": "Rule 2 cites the old plan"}],
    )

    class Db:
        async def commit(self):
            return None

        async def execute(self, stmt):
            return _Res([SimpleNamespace(settings={})])

    with (
        patch.object(approvals_router, "create_notification", AsyncMock()) as notify,
        patch.object(approvals_router, "_tenant_settings", AsyncMock(return_value={})),
    ):
        await approvals_router._notify_resolved(Db(), a, decider=_user())
    msgs = [c.kwargs["message"] for c in notify.call_args_list]
    assert msgs and all("Reason: Rule 2 cites the old plan" in m for m in msgs)


@pytest.mark.asyncio
async def test_a_denied_publish_keeps_the_reason_on_the_version():
    v = DecisionVersion(id=uuid.uuid4(), version=3, state="proposed", validation=None)
    a = Approval(
        id=uuid.uuid4(),
        status=ApprovalStatus.denied,
        gate_kind="decision_publish",
        signoffs=[{"decision": "deny", "reason": "Cite the 2026 plan", "user_email": "r@x", "at": "t"}],
    )

    class Db:
        async def execute(self, stmt, params=None):
            return _Res([v])

        async def commit(self):
            return None

    await D.on_approval_resolved(Db(), a)
    assert v.state == "rejected"
    assert D._version_summary(v)["denial"]["reason"] == "Cite the 2026 plan"


# 13. the state summary


def _v(n, state, published=False, superseded=False, **kw):
    return DecisionVersion(
        id=uuid.uuid4(),
        version=n,
        state=state,
        published_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc) if published else None,
        superseded_at=dt.datetime(2026, 2, 1, tzinfo=dt.timezone.utc) if superseded else None,
        **kw,
    )


def test_state_says_what_is_true():
    assert D._state_of([_v(1, "published", True)]) == "in_force"
    assert D._state_of([_v(1, "retired", True, True)]) == "retired"
    assert D._state_of([_v(1, "superseded", True, True), _v(2, "draft")]) == "retired"
    assert D._state_of([_v(1, "draft")]) == "draft_only"
    assert D._state_of([_v(1, "proposed")]) == "never_published"
    assert D._state_of([]) == "never_published"


def test_waiting_lists_every_version_waiting():
    p = uuid.uuid4()
    out = D._state_json(
        [_v(1, "published", True), _v(3, "proposed", proposed_by=p), _v(4, "approved"), _v(2, "draft")],
        {str(p): "Rita"},
    )
    assert out["state"] == "in_force" and out["in_force_version"] == 1
    assert [(w["version"], w["state"]) for w in out["waiting"]] == [(3, "proposed"), (4, "approved")]
    assert out["waiting"][0]["proposed_by_name"] == "Rita"


def test_list_and_get_carry_the_summary_and_restore_returns_it():
    m = DecisionModel(id=uuid.uuid4(), key="k", name="K", risk_tier="low")
    a = uuid.uuid4()
    out = D._model_json(m, [_v(1, "draft", author_id=a)], {str(a): "Ana"})
    assert out["state"] == "draft_only" and out["drafts"][0]["author_name"] == "Ana"
    assert "_state_json" in inspect.getsource(D.restore_model)
    assert "archived_matches" in inspect.getsource(D.list_models)


# 12. retire, archive and restore at high and critical


class _ActDb:
    def __init__(self, model=None, archived=None, version=None, pending=None):
        self.model, self.archived, self.version = model, archived, version
        self.pending = list(pending or [])
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        descs = getattr(stmt, "column_descriptions", None) or [{}]
        ent = getattr(descs[0].get("entity"), "__name__", "")
        sql = _sql(stmt)
        if ent == "DecisionModel":
            if "archived_at IS NOT NULL" in sql:
                return _Res([self.archived] if self.archived else [])
            return _Res([self.model] if self.model else [])
        if ent == "DecisionVersion":
            return _Res([self.version] if self.version else [])
        if ent == "Approval":
            return _Res([a for a in self.pending + self.added if isinstance(a, Approval) and a.status == ApprovalStatus.pending])
        return _Res([])

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None


def _model(tier):
    return DecisionModel(id=uuid.uuid4(), tenant_id=uuid.uuid4(), key="gw.truck.speed", name="Truck", risk_tier=tier)


async def _call(fn, *a, **kw):
    with (
        patch.object(D, "log_action", AsyncMock()) as audit,
        patch.object(D.S, "announce", AsyncMock()),
        patch.object(D, "_announce_approval", AsyncMock()),
        patch("app.services.events.emit", AsyncMock()),
    ):
        r = await fn(*a, **kw)
    return r, json.loads(r.body), [c.args[3] for c in audit.call_args_list]


@pytest.mark.asyncio
async def test_archiving_at_high_needs_a_reason_and_waits_for_signoff():
    m = _model("high")
    live = _v(1, "published", True)
    r, body, _ = await _call(D.archive_model, m.key, None, None, None, _user(), _ActDb(m, version=live))
    assert r.status_code == 422 and body["error"]["error_code"] == "REASON_REQUIRED"
    db = _ActDb(m, version=live)
    r, body, actions = await _call(D.archive_model, m.key, None, D.ActionBody(reason="Site closed"), None, _user(), db)
    assert r.status_code == 202 and m.archived_at is None
    p = body["data"]["pending"]
    a = next(x for x in db.added if isinstance(x, Approval))
    assert p["kind"] == "archive" and p["approval_id"] == str(a.id) and p["required_signoffs"] == 1
    assert a.gate_kind == "decision_archive"
    assert a.payload["reason"] == "Site closed" and a.payload["tier"] == "high"
    assert a.policy["exclude_requester"] is True
    assert "decision.archive_requested" in actions


@pytest.mark.asyncio
async def test_a_second_request_waits_for_the_first():
    m = _model("critical")
    prior = Approval(
        id=uuid.uuid4(), status=ApprovalStatus.pending, gate_kind="decision_retire", payload={"decision_key": m.key}
    )
    r, body, _ = await _call(D.archive_model, m.key, None, D.ActionBody(reason="again"), None, _user(), _ActDb(m, pending=[prior], version=_v(1, "published", True)))
    assert r.status_code == 409 and body["error"]["error_code"] == "ACTION_PENDING"


@pytest.mark.asyncio
async def test_low_and_medium_act_at_once():
    for tier in ("low", "medium"):
        m = _model(tier)
        r, body, actions = await _call(D.archive_model, m.key, None, None, None, _user(), _ActDb(m))
        assert r.status_code == 200 and m.archived_at is not None and "decision.archived" in actions


@pytest.mark.asyncio
async def test_retiring_at_high_waits_and_keeps_the_version_in_force():
    m = _model("high")
    v = _v(2, "published", True, model_id=m.id)
    db = _ActDb(m, version=v)
    r, body, _ = await _call(D.retire, m.key, 2, None, D.ActionBody(reason="Rule replaced on site"), _user(), db)
    assert r.status_code == 202 and v.state == "published"
    a = next(x for x in db.added if isinstance(x, Approval))
    assert a.gate_kind == "decision_retire" and a.payload["version"] == 2


@pytest.mark.asyncio
async def test_restoring_at_high_waits():
    m = _model("high")
    m.archived_at = dt.datetime.now(dt.timezone.utc)
    db = _ActDb(None, archived=m, version=_v(1, "retired", True, True))
    r, body, _ = await _call(D.restore_model, m.key, None, D.ActionBody(reason="Needed for the audit"), _user(), db)
    assert r.status_code == 202 and m.archived_at is not None
    assert next(x for x in db.added if isinstance(x, Approval)).gate_kind == "decision_restore"


def _resolved(kind, model, status=ApprovalStatus.approved, version=None):
    return Approval(
        id=uuid.uuid4(),
        tenant_id=model.tenant_id,
        status=status,
        gate_kind=kind,
        requested_by=uuid.uuid4(),
        payload={"decision_key": model.key, "version": version, "reason": "why"},
        signoffs=[{"decision": "approve", "user_id": str(uuid.uuid4())}],
    )


@pytest.mark.asyncio
async def test_an_approved_request_does_the_action():
    m = _model("high")
    with patch.object(D, "log_action", AsyncMock()) as audit, patch.object(D.S, "announce", AsyncMock()):
        await D.on_approval_resolved(_ActDb(m), _resolved("decision_archive", m))
    assert m.archived_at is not None and audit.call_args.args[3] == "decision.archived"
    assert audit.call_args.args[4]["approval_id"]

    v = _v(2, "published", True, model_id=m.id)
    m2 = _model("high")
    with (
        patch.object(D, "log_action", AsyncMock()) as audit,
        patch.object(D.S, "announce", AsyncMock()),
        patch("app.services.events.emit", AsyncMock()),
    ):
        await D.on_approval_resolved(_ActDb(m2, version=v), _resolved("decision_retire", m2, version=2))
    assert v.state == "retired" and audit.call_args.args[3] == "decision.retired"

    m3 = _model("high")
    m3.archived_at = dt.datetime.now(dt.timezone.utc)
    with patch.object(D, "log_action", AsyncMock()), patch.object(D.S, "announce", AsyncMock()):
        await D.on_approval_resolved(_ActDb(None, archived=m3), _resolved("decision_restore", m3))
    assert m3.archived_at is None


@pytest.mark.asyncio
async def test_a_denied_request_changes_nothing():
    m = _model("high")
    with patch.object(D, "log_action", AsyncMock()):
        await D.on_approval_resolved(_ActDb(m), _resolved("decision_archive", m, ApprovalStatus.denied))
    assert m.archived_at is None


def test_these_requests_are_decision_gates_with_sole_operator():
    for k in ("decision_retire", "decision_archive", "decision_restore"):
        assert k in AP.SOLE_OPERATOR_KINDS and k in AP.DECISION_KINDS


# 15. safer import


def test_test_changes_by_name():
    have = {"a": DecisionTest(name="a", facts={"x": 1}, expected={"y": 1}, expected_outcome="decided", match_mode="exact", as_of=None)}
    same = {"name": "a", "facts": {"x": 1}, "expected": {"y": 1}, "expected_outcome": "decided", "match": "exact", "as_of": None}
    add, upd = D._test_changes(have, [same])
    assert add == [] and upd == []
    add, upd = D._test_changes(have, [{**same, "expected": {"y": 2}}, {**same, "name": "b"}])
    assert [t["name"] for t in add] == ["b"] and upd[0][0] is have["a"]


class _ImportDb:
    """An existing decision whose latest version holds the Groundwork rules."""

    def __init__(self, model, latest, tests, taken_keys=()):
        self.model, self.latest, self.tests, self.taken_keys = model, latest, tests, taken_keys
        self.added: list = []

    async def execute(self, stmt, params=None):
        descs = getattr(stmt, "column_descriptions", None) or [{}]
        ent = getattr(descs[0].get("entity"), "__name__", "")
        sql = _sql(stmt)
        if ent == "DecisionModel" and descs[0].get("name") == "key":
            return _Res([(k, None) for k in self.taken_keys])
        if ent == "DecisionModel" and descs[0].get("name") == "id":
            return _Res([])
        if ent == "DecisionModel":
            return _Res([] if "archived_at IS NOT NULL" in sql else [self.model])
        if ent == "DecisionVersion":
            return _Res([self.latest])
        if ent == "DecisionTest":
            return _Res(self.tests)
        return _Res([])

    def add(self, obj):
        self.added.append(obj)


async def _gw_setup():
    from engine.decisions import interchange as I

    raw = json.loads((__import__("pathlib").Path(__file__).parent / "fixtures" / "gw.safety.exclusion.json").read_text())
    parts = I.read_file(json.loads(json.dumps(raw)))
    doc = parts["doc"]
    D.A.tidy_outcomes(doc)
    with patch.object(D.S, "reference_values", AsyncMock(return_value=({}, {}))):
        c = await D.S.compile_for(None, "t", D.A.normalize(doc))
    m = DecisionModel(id=uuid.uuid4(), tenant_id=uuid.uuid4(), key=raw["key"], name=raw["name"], risk_tier="high")
    latest = DecisionVersion(id=uuid.uuid4(), version=4, state="published", content_hash=c.content_hash)
    tests = [
        DecisionTest(
            name=t["name"], facts=t["facts"], expected=t["expected"], expected_outcome="decided", match_mode="exact", as_of=None
        )
        for t in raw["tests"]
    ]
    return raw, m, latest, tests


class _Req:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


@pytest.mark.asyncio
async def test_preview_says_where_it_lands_and_that_nothing_changed():
    raw, m, latest, tests = await _gw_setup()
    db = _ImportDb(m, latest, tests, taken_keys=[m.key])
    with patch.object(D.S, "reference_values", AsyncMock(return_value=({}, {}))):
        r = await D.import_file(_Req(raw), preview=1, as_new_key=None, as_new_name=None, user=_user(), db=db)
    d = json.loads(r.body)["data"]
    assert d["target"] == "existing" and d["identical_to_latest"] is True
    assert d["suggested_key"] == "gw.safety.exclusion.copy"
    assert d["tests_to_add"] == 0 and d["tests_to_update"] == 0
    assert d["name_taken"] is False


@pytest.mark.asyncio
async def test_an_identical_import_creates_nothing():
    raw, m, latest, tests = await _gw_setup()
    db = _ImportDb(m, latest, tests)
    with patch.object(D.S, "reference_values", AsyncMock(return_value=({}, {}))):
        r = await D.import_file(_Req(raw), preview=0, as_new_key=None, as_new_name=None, user=_user(), db=db)
    d = json.loads(r.body)["data"]
    assert r.status_code == 200 and d["created"] is False and d["no_changes"] is True
    assert db.added == []


def test_import_returns_the_draft_number_and_takes_a_new_name():
    src = inspect.getsource(D.import_file)
    assert '"draft": nxt if v is not None else None' in src
    assert "as_new_name" in src and "name[:255]" in src


# 16. discard a draft


class _DraftDb:
    def __init__(self, model, version):
        self.model, self.version = model, version
        self.deleted: list = []

    async def execute(self, stmt, params=None):
        ent = getattr(stmt.column_descriptions[0].get("entity"), "__name__", "")
        return _Res([self.model] if ent == "DecisionModel" else [self.version])

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_the_author_discards_their_draft():
    me = _user(role=UserRole.CREATOR)
    m = _model("high")
    v = _v(5, "draft", author_id=me.id)
    db = _DraftDb(m, v)
    r, body, actions = await _call(D.discard_draft, m.key, 5, None, me, db)
    assert r.status_code == 200 and db.deleted == [v] and "decision.draft_discarded" in actions


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["proposed", "approved", "published", "superseded", "retired"])
async def test_only_drafts_can_be_discarded(state):
    me = _user()
    db = _DraftDb(_model("low"), _v(2, state, author_id=me.id))
    r, body, _ = await _call(D.discard_draft, "k", 2, None, me, db)
    assert r.status_code == 409 and body["error"]["error_code"] == "NOT_A_DRAFT" and db.deleted == []


@pytest.mark.asyncio
async def test_someone_else_needs_publish_rights_to_discard():
    other = _user(role=UserRole.CREATOR)
    db = _DraftDb(_model("low"), _v(2, "draft", author_id=uuid.uuid4()))
    with patch.object(caps, "capabilities_for", AsyncMock(return_value=caps.ROLE_DEFAULTS["creator"])):
        r, body, _ = await _call(D.discard_draft, "k", 2, None, other, db)
    assert r.status_code == 403 and body["error"]["error_code"] == "NOT_YOUR_DRAFT"
    admin = _user(role=UserRole.ADMIN)
    with patch.object(caps, "capabilities_for", AsyncMock(return_value=frozenset({"*"}))):
        r, _, _ = await _call(D.discard_draft, "k", 2, None, admin, db)
    assert r.status_code == 200


# 11. someone missing


def test_the_decision_page_can_add_an_approver():
    paths = [(r.path, sorted(r.methods)) for r in D.router.routes]
    assert ("/api/decisions/{key}/approvers", ["POST"]) in paths
    assert "add_decision_reviewer" in inspect.getsource(D.add_approver)
    assert "missing_hint" in inspect.getsource(D.sign_off_info)


# 18. tests show what they pin


def test_listed_tests_carry_facts_and_expected():
    t = SimpleNamespace(
        id=uuid.uuid4(), name="t", facts={"x": 1}, expected_outcome="decided", expected={"y": 2}, match_mode="exact", as_of=None, updated_at=None
    )
    row = D._test_json(t)
    assert row["facts"] == {"x": 1} and row["expected"] == {"y": 2} and row["expected_outcome"] == "decided"


# profile


def test_password_message_matches_what_happens():
    from app.routers import settings

    src = inspect.getsource(settings.change_password)
    assert "This device stays signed in" in src and "sessions.revoke" in src
