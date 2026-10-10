"""Decisions 2.5.7 round 2: approver rights from Team, archiving what was never live,
telling the author, and approvals rows that say who asked, why and how much changed."""

from __future__ import annotations

import datetime as dt
import inspect
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core import approvers as AP
from app.core import capabilities as caps
from app.routers import approvals as approvals_router
from app.routers import decisions as D
from app.routers import team
from engine import governance
from models.approval import Approval, ApprovalStatus
from models.decision import DecisionModel, DecisionVersion
from models.user import UserRole


@pytest.fixture(autouse=True)
def _default_policies():
    governance.load_for_test()
    yield
    governance.load_for_test()


def _user(role=UserRole.ADMIN, email=None, tenant_id=None, active=True):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        role=role,
        email=email or f"{uuid.uuid4().hex[:6]}@example.com",
        full_name="Someone",
        is_active=active,
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


# 19. approver rights


def test_system_and_erased_accounts_are_not_people():
    assert AP.real_person(_user(email="system@abenix.dev")) is False
    assert AP.real_person(_user(email="deleted-ab12@purged.local")) is False
    assert AP.real_person(_user(email="ana@example.com")) is True


@pytest.mark.asyncio
async def test_tenant_people_leaves_out_erased_accounts():
    tid = uuid.uuid4()
    purged = _user(email="deleted-1@purged.local", tenant_id=tid)
    ana = _user(tenant_id=tid)

    class Db:
        def __init__(self):
            self.n = 0

        async def execute(self, stmt):
            self.n += 1
            return _Res([purged, ana] if self.n == 1 else [])

    assert [u.id for u, _ in await AP.tenant_people(Db(), tid)] == [ana.id]


def _person(role, extra=()):
    u = _user(role=role)
    return u, frozenset(set(caps.ROLE_DEFAULTS[role.value]) | set(extra))


def test_candidates_are_people_who_cannot_approve_yet_and_not_the_author():
    admin = _person(UserRole.ADMIN)
    reviewer = _person(UserRole.USER, ["approvals.sign", "decisions.review"])
    member = _person(UserRole.USER)
    author = _person(UserRole.CREATOR)
    got = AP.approver_candidates(
        [admin, reviewer, member, author], exclude=[author[0].id]
    )
    assert [u.id for u in got] == [member[0].id]
    assert len(AP.decision_approvers([admin, reviewer, member, author])) == 2


class _TeamDb:
    def __init__(self, member):
        self.member = member

    async def get(self, cls, ident):
        return self.member if ident == self.member.id else None

    async def commit(self):
        return None


async def _set(member, on, people, changed=True):
    admin = _user(tenant_id=member.tenant_id)
    with (
        patch.object(
            AP, "add_decision_reviewer", AsyncMock(return_value=changed)
        ) as add,
        patch.object(
            AP, "remove_decision_reviewer", AsyncMock(return_value=changed)
        ) as rem,
        patch.object(AP, "tenant_people", AsyncMock(return_value=people)),
        patch("app.core.audit.log_action", AsyncMock()),
        patch.object(caps, "invalidate") as inv,
    ):
        r = await team.set_approver(
            member.id,
            team.ApproverRequest(can_approve_decisions=on),
            None,
            admin,
            _TeamDb(member),
        )
    return r, json.loads(r.body)["data"], add, rem, inv


@pytest.mark.asyncio
async def test_team_turns_approving_on_and_clears_the_cache():
    m = _user(role=UserRole.USER)
    granted = frozenset(
        caps.ROLE_DEFAULTS["user"] | {"approvals.sign", "decisions.review"}
    )
    other = _person(UserRole.ADMIN)
    r, d, add, rem, inv = await _set(m, True, [(m, granted), other])
    assert (
        r.status_code == 200
        and d["can_approve_decisions"] is True
        and d["warning"] is None
    )
    add.assert_awaited_once()
    rem.assert_not_awaited()
    inv.assert_called_once_with(m.id)


@pytest.mark.asyncio
async def test_taking_away_the_last_approver_warns():
    m = _user(role=UserRole.USER)
    r, d, add, rem, _ = await _set(m, False, [(m, caps.ROLE_DEFAULTS["user"])])
    assert r.status_code == 200 and d["can_approve_decisions"] is False
    assert d["warning"].startswith("Nobody in this workspace can approve decisions now")
    rem.assert_awaited_once()
    admin = _person(UserRole.ADMIN)
    _, d, _, _, _ = await _set(m, False, [(m, caps.ROLE_DEFAULTS["user"]), admin])
    assert d["warning"].startswith("Only one person")


@pytest.mark.asyncio
async def test_someone_who_approves_by_role_is_told_so():
    m = _user(role=UserRole.ADMIN)
    _, d, _, _, _ = await _set(
        m, False, [(m, frozenset({"*"})), _person(UserRole.ADMIN)]
    )
    assert d["can_approve_decisions"] is True and "through their role" in d["warning"]


@pytest.mark.asyncio
async def test_an_erased_or_inactive_account_cannot_be_made_an_approver():
    m = _user(role=UserRole.USER, email="deleted-1@purged.local")
    r, *_ = await _set(m, True, [])
    assert r.status_code == 400


def test_team_rows_and_routes():
    assert "can_approve_decisions" in inspect.getsource(team.list_members)
    paths = [(r.path, sorted(r.methods)) for r in D.router.routes]
    assert ("/api/decisions/{key}/approver-candidates", ["GET"]) in paths
    assert "real_person" in inspect.getsource(D.add_approver)


# 20. never live, so no sign-off


class _ActDb:
    def __init__(self, model=None, archived=None, published=None):
        self.model, self.archived, self.published = model, archived, published

    async def execute(self, stmt, params=None):
        from sqlalchemy.dialects import postgresql

        ent = getattr(stmt.column_descriptions[0].get("entity"), "__name__", "")
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        if ent == "DecisionModel":
            return _Res(
                [self.archived]
                if "archived_at IS NOT NULL" in sql
                else ([self.model] if self.model else [])
            )
        if ent == "DecisionVersion":
            return _Res([self.published] if self.published else [])
        return _Res([])

    def add(self, obj):
        obj.id = uuid.uuid4()

    async def flush(self):
        return None

    async def commit(self):
        return None


async def _call(fn, *a):
    with (
        patch.object(D, "log_action", AsyncMock()),
        patch.object(D.S, "announce", AsyncMock()),
        patch.object(D, "_announce_approval", AsyncMock()),
        patch("app.services.events.emit", AsyncMock()),
    ):
        r = await fn(*a)
    return r, json.loads(r.body)


@pytest.mark.asyncio
async def test_archiving_a_high_decision_never_published_acts_at_once():
    m = DecisionModel(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), key="k", name="K", risk_tier="critical"
    )
    r, body = await _call(D.archive_model, m.key, None, None, None, _user(), _ActDb(m))
    assert r.status_code == 200 and m.archived_at is not None
    assert (
        body["data"]["reason"]
        == "Nothing was ever published, so no sign-off was needed."
    )


@pytest.mark.asyncio
async def test_restoring_it_acts_at_once_too():
    m = DecisionModel(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), key="k", name="K", risk_tier="high"
    )
    m.archived_at = dt.datetime.now(dt.timezone.utc)
    r, body = await _call(
        D.restore_model, m.key, None, None, _user(), _ActDb(None, archived=m)
    )
    assert r.status_code == 200 and m.archived_at is None
    assert body["data"]["reason"].startswith("Nothing was ever published")


@pytest.mark.asyncio
async def test_once_published_it_still_needs_signoff():
    m = DecisionModel(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), key="k", name="K", risk_tier="high"
    )
    r, body = await _call(
        D.archive_model,
        m.key,
        None,
        None,
        None,
        _user(),
        _ActDb(m, published=uuid.uuid4()),
    )
    assert r.status_code == 422 and body["error"]["error_code"] == "REASON_REQUIRED"


# 21. telling the author


def _doc(n):
    return {
        "rules": [
            {"key": f"r{i}", "id": f"r{i}", "when": {"all": []}, "then": {"x": i}}
            for i in range(n)
        ],
        "facts": [],
    }


def test_rule_changes_counts_a_first_version_in_full():
    v = DecisionVersion(id=uuid.uuid4(), version=1, authoring=_doc(4))
    assert D.rule_changes(v, None) == 4
    base = DecisionVersion(
        id=uuid.uuid4(), version=1, authoring=_doc(3), content_hash="a"
    )
    v2 = DecisionVersion(
        id=uuid.uuid4(), version=2, authoring=_doc(4), content_hash="b"
    )
    v2.authoring["rules"][0]["then"] = {"x": 99}
    assert D.rule_changes(v2, base) == 2
    assert D.rule_changes(DecisionVersion(authoring=None), None) is None


def test_new_proposals_carry_the_note_and_the_rule_count():
    src = inspect.getsource(D.propose)
    assert (
        '"change_note": v.change_note' in src
        and "rule_changes(" in src
        and '"result_changes"' in src
    )


@pytest.mark.asyncio
async def test_rows_say_who_asked_why_and_how_much_changed():
    tid = uuid.uuid4()
    asker = uuid.uuid4()
    v = DecisionVersion(
        id=uuid.uuid4(),
        version=1,
        authoring=_doc(4),
        change_note="First cut of the limits",
        base_version_id=None,
    )
    a = Approval(
        id=uuid.uuid4(),
        tenant_id=tid,
        gate_kind="decision_publish",
        requested_by=asker,
        payload={"decision_key": "k", "version": 1, "changes": 0},
        status=ApprovalStatus.pending,
    )

    class Db:
        async def execute(self, stmt):
            descs = stmt.column_descriptions
            if descs[0].get("name") == "key":
                return _Res([("k", v)])
            return _Res([(asker, "Ana Author", "ana@example.com")])

    names = await approvals_router._requester_names(Db(), [a], {})
    assert names[str(asker)] == "Ana Author"
    details = await approvals_router._decision_details(Db(), [a])
    assert details[str(a.id)] == {
        "change_note": "First cut of the limits",
        "changes": 4,
    }


def test_old_summaries_read_right():
    f = approvals_router.fix_wording
    assert f("Ready. 1 golden test pass.") == "Ready. 1 golden test passes."
    assert f("1 of 3 golden tests fail") == "1 of 3 golden tests fails"
    assert f("Ready. 2 golden tests pass.") == "Ready. 2 golden tests pass."
    assert f(
        "1 pair of rules disagree. 1 result change compared with the published version"
    ) == (
        "1 pair of rules disagrees. 1 result changes compared with the published version"
    )
    a = Approval(
        id=uuid.uuid4(),
        payload={"summary": "Ready. 1 golden test pass."},
        status=ApprovalStatus.pending,
    )
    assert (
        approvals_router._serialize(a)["payload"]["summary"]
        == "Ready. 1 golden test passes."
    )


@pytest.mark.asyncio
async def test_the_author_is_sent_to_the_decision_and_emailed():
    asker, signer = uuid.uuid4(), uuid.uuid4()
    a = Approval(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        title="Publish K version 2",
        status=ApprovalStatus.denied,
        requested_by=asker,
        gate_kind="decision_publish",
        payload={"decision_key": "k", "version": 2, "link": "/decisions/k?version=2"},
        signoffs=[
            {"decision": "deny", "user_id": str(signer), "reason": "Cite the plan"}
        ],
    )

    class Db:
        async def commit(self):
            return None

    decider = SimpleNamespace(id=uuid.uuid4(), full_name="Rita", email="r@x")
    with (
        patch.object(approvals_router, "create_notification", AsyncMock()) as notify,
        patch.object(approvals_router, "_tenant_settings", AsyncMock(return_value={})),
    ):
        await approvals_router._notify_resolved(Db(), a, decider=decider)
    calls = {c.kwargs["user_id"]: c.kwargs for c in notify.call_args_list}
    assert (
        calls[asker]["link"] == "/decisions/k?version=2"
        and calls[asker]["email"] is True
    )
    assert calls[signer]["email"] is False
    assert "Reason: Cite the plan" in calls[asker]["message"]


def test_notifications_can_ask_for_the_email_copy():
    from app.core import notifications

    src = inspect.getsource(notifications.create_notification)
    assert "email: bool = False" in src and "email\n        or severity" in src


# frontend additions


def test_signoffs_carry_the_signers_name():
    uid = str(uuid.uuid4())
    rows = approvals_router._signoff_rows(
        [{"user_id": uid, "user_email": "r@x"}], {uid: "Rita Reviewer"}
    )
    assert rows[0]["user_name"] == "Rita Reviewer" and rows[0]["user_email"] == "r@x"
    assert (
        approvals_router._signoff_rows([{"user_id": "u", "user_email": "r@x"}], None)[
            0
        ]["user_name"]
        == "r@x"
    )
    a = Approval(
        id=uuid.uuid4(),
        status=ApprovalStatus.approved,
        signoffs=[{"user_id": uid, "user_email": "r@x"}],
    )
    assert (
        approvals_router._serialize(a, {uid: "Rita"})["signoffs"][0]["user_name"]
        == "Rita"
    )
    assert "_serialize(a, names, agents)" in inspect.getsource(approvals_router._serialize_many)
    assert '"user_name": user.full_name or user.email' in inspect.getsource(
        approvals_router.sign_off
    )
    assert '"user_name"' in inspect.getsource(D.sign_off_info)


def test_every_version_says_who_wrote_it():
    a = uuid.uuid4()
    v = DecisionVersion(id=uuid.uuid4(), version=3, state="published", author_id=a)
    assert D._version_summary(v, {str(a): "Ana"})["author_name"] == "Ana"
    v._author_name = "Ana"
    assert D._version_summary(v)["author_name"] == "Ana"
    m = DecisionModel(id=uuid.uuid4(), key="k", name="K", risk_tier="low")
    out = D._model_json(m, [v], {str(a): "Ana"})
    assert out["published"][0]["author_name"] == "Ana"
    assert "_version_summary(v, names) for v in vs" in inspect.getsource(D.get_model)


@pytest.mark.asyncio
async def test_a_review_names_who_approved_it():
    rid = uuid.uuid4()

    class Db:
        async def execute(self, stmt):
            return _Res([(rid, "Rita Reviewer", "r@x")])

    out = await D._with_approver_names(
        Db(), {"tier": "high", "approved_by": [str(rid)]}
    )
    assert out["approved_by_names"] == ["Rita Reviewer"]
    assert '"approved_by_names"' in inspect.getsource(D._on_reattest_resolved)


def test_old_payloads_get_the_right_changes_count():
    src = inspect.getsource(approvals_router._serialize_many)
    assert 'row["payload"] = {**row["payload"], "changes": row["changes"]}' in src
