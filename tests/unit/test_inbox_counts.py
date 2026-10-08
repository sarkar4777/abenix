"""/api/me/inbox-counts: per-capability tabs, signable approvals, tenant isolation, the per-user cache."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.core.capabilities import ROLE_DEFAULTS
from app.routers import inbox
from models.user import UserRole

pytestmark = pytest.mark.asyncio

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()


def _user(role=UserRole.USER, tenant=TENANT, settings=None):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant, role=role, notification_settings=settings
    )


def _approval(tenant=TENANT, **kw):
    row = {
        "tenant": tenant,
        "requested_by": None,
        "policy": None,
        "gate_kind": None,
        "signoffs": [],
        "creator": None,
        "self_approval": None,
    }
    row.update(kw)
    return row


class Res:
    def __init__(self, rows=None, scalar=None):
        self.rows = rows or []
        self._scalar = scalar

    def all(self):
        return list(self.rows)

    def scalar(self):
        return self._scalar


class FakeDB:
    """Answers each source query from rows, keeping only those in the tenant the query names."""

    def __init__(self, **rows):
        self.rows = {
            k: rows.get(k, [])
            for k in (
                "approvals",
                "agent_actions",
                "moderation_reviews",
                "agents",
                "executions",
            )
        }
        self.statements: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail: set[str] = set()

    def _tenants(self, params: dict) -> set:
        return {v for v in params.values() if isinstance(v, uuid.UUID)}

    async def execute(self, stmt, *a, **k):
        compiled = stmt.compile(dialect=postgresql.dialect())
        sql, params = str(compiled), dict(compiled.params)
        self.statements.append((sql, params))
        tenants = self._tenants(params)
        table = next(t for t in self.rows if f"FROM {t}" in sql)
        if table in self.fail:
            raise RuntimeError(f"{table} is down")
        mine = (
            [r for r in self.rows[table] if r["tenant"] in tenants]
            if tenants
            else self.rows[table]
        )
        if table == "approvals":
            return Res(
                rows=[
                    (
                        r["requested_by"],
                        r["policy"],
                        r["gate_kind"],
                        r["signoffs"],
                        r["creator"],
                        r["self_approval"],
                    )
                    for r in mine
                ]
            )
        if table == "executions":
            return Res(
                rows=[
                    (
                        r["code"],
                        r["today"],
                        r["before"],
                        datetime.now(timezone.utc),
                        "boom",
                    )
                    for r in mine
                ]
            )
        return Res(scalar=len(mine))

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _caps(user, extra=()):
    role = user.role.value
    return frozenset(ROLE_DEFAULTS.get(role, ROLE_DEFAULTS["user"]) | set(extra))


async def _counts(user, db, *, extra=(), marketplace=True, hitl=()):
    with (
        patch.object(
            inbox, "capabilities_for", AsyncMock(return_value=_caps(user, extra))
        ),
        patch(
            "app.core.platform_features.marketplace_enabled",
            AsyncMock(return_value=marketplace),
        ),
        patch("app.core.hitl.list_pending_hitl", AsyncMock(return_value=list(hitl))),
    ):
        res = await inbox.inbox_counts(fresh=True, user=user, db=db)
    return json.loads(res.body)["data"]


@pytest.fixture(autouse=True)
def _clear_cache():
    inbox.invalidate()
    yield
    inbox.invalidate()


def _everything(tenant=TENANT):
    return {
        "approvals": [_approval(tenant), _approval(tenant)],
        "agent_actions": [{"tenant": tenant}] * 3,
        "moderation_reviews": [{"tenant": tenant}] * 4,
        "agents": [{"tenant": tenant}] * 5,
        "executions": [
            {"tenant": tenant, "code": "TOOL_ERROR", "today": 4, "before": 1}
        ],
    }


async def test_member_sees_only_their_tabs():
    db = FakeDB(**_everything())
    data = await _counts(_user(UserRole.USER), db)
    # members review watching actions and see alerts, they cannot sign plain approvals
    assert data["available"] == ["approvals", "watching", "alerts"]
    assert data["counts"] == {"approvals": 0, "watching": 3, "alerts": 1}
    assert data["total"] == 4


async def test_moderation_review_grant_adds_held_tab():
    db = FakeDB(**_everything())
    data = await _counts(_user(UserRole.USER), db, extra={"moderation.review"})
    assert "held" in data["available"]
    assert data["counts"]["held"] == 4


async def test_admin_sees_every_tab_when_marketplace_is_on():
    db = FakeDB(**_everything())
    data = await _counts(_user(UserRole.ADMIN), db)
    assert data["available"] == list(inbox.TABS)
    assert data["counts"] == {
        "approvals": 2,
        "watching": 3,
        "held": 4,
        "marketplace": 5,
        "alerts": 1,
    }
    assert data["total"] == 15


async def test_marketplace_tab_needs_the_switch_and_admin():
    db = FakeDB(**_everything())
    off = await _counts(_user(UserRole.ADMIN), db, marketplace=False)
    assert "marketplace" not in off["available"]
    creator = await _counts(_user(UserRole.CREATOR), db, marketplace=True)
    assert "marketplace" not in creator["available"]


async def test_hitl_gates_count_for_signers_only():
    gates = [{"execution_id": "e", "gate_id": "g"}]
    db = FakeDB()
    assert (await _counts(_user(UserRole.CREATOR), db, hitl=gates))["counts"][
        "approvals"
    ] == 1
    assert (await _counts(_user(UserRole.USER), db, hitl=gates))["counts"][
        "approvals"
    ] == 0
    signer = await _counts(
        _user(UserRole.USER), db, extra={"approvals.sign"}, hitl=gates
    )
    assert signer["counts"]["approvals"] == 1


async def test_signable_rules():
    me = _user(UserRole.CREATOR)
    mine = str(me.id)
    db = FakeDB(
        approvals=[
            _approval(),  # plain, creators sign
            _approval(
                signoffs=[{"user_id": mine, "decision": "approve"}]
            ),  # already signed
            _approval(gate_kind="decision_publish"),  # needs decisions.review
            _approval(gate_kind="autonomy.promote", creator=mine),  # own agent
            _approval(
                gate_kind="autonomy.promote", creator=mine, self_approval="Only builder"
            ),
            _approval(
                policy={"capability": "approvals.sign:legal"}
            ),  # missing capability
            _approval(
                policy={"exclude_requester": True, "capability": "approvals.sign"},
                requested_by=me.id,
            ),
        ]
    )
    data = await _counts(me, db)
    assert data["counts"]["approvals"] == 2
    data = await _counts(me, db, extra={"decisions.review", "approvals.sign"})
    # decision publish and the legal policy open up, own request stays excluded
    assert data["counts"]["approvals"] == 4


async def test_other_tenant_rows_never_count():
    db = FakeDB(
        **{k: v + _everything(OTHER)[k] for k, v in _everything().items()},
    )
    data = await _counts(_user(UserRole.ADMIN), db)
    assert data["counts"] == {
        "approvals": 2,
        "watching": 3,
        "held": 4,
        "marketplace": 5,
        "alerts": 1,
    }
    # every source query is bound to the caller's tenant and never the other one
    for sql, params in db.statements:
        tenants = {v for v in params.values() if isinstance(v, uuid.UUID)}
        assert tenants == {TENANT}, sql
    other = await _counts(_user(UserRole.ADMIN, tenant=OTHER), FakeDB(**_everything()))
    assert other["total"] == 0


async def test_alerts_count_new_or_rising_only():
    db = FakeDB(
        executions=[
            {"tenant": TENANT, "code": "NEW", "today": 2, "before": 0},
            {"tenant": TENANT, "code": "UP", "today": 5, "before": 3},
            {"tenant": TENANT, "code": "FLAT", "today": 3, "before": 3},
            {"tenant": TENANT, "code": "DOWN", "today": 0, "before": 9},
        ]
    )
    groups = await inbox.rising_failures(db, _user())
    assert [(g["failure_code"], g["trend"]) for g in groups] == [
        ("UP", "rising"),
        ("NEW", "new"),
    ]


async def test_one_broken_source_does_not_blank_the_rest():
    db = FakeDB(**_everything())
    db.fail = {"moderation_reviews"}
    data = await _counts(_user(UserRole.ADMIN), db)
    assert data["unavailable"] == ["held"]
    assert data["counts"]["held"] == 0
    assert data["counts"]["watching"] == 3
    assert db.rollbacks == 1


async def test_cache_is_per_user_and_fresh_skips_it():
    a, b = _user(UserRole.ADMIN), _user(UserRole.USER)
    db = FakeDB(**_everything())
    caps = AsyncMock(side_effect=lambda _db, u: _caps(u))
    with (
        patch.object(inbox, "capabilities_for", caps),
        patch(
            "app.core.platform_features.marketplace_enabled",
            AsyncMock(return_value=True),
        ),
        patch("app.core.hitl.list_pending_hitl", AsyncMock(return_value=[])),
    ):
        first = json.loads((await inbox.inbox_counts(fresh=False, user=a, db=db)).body)[
            "data"
        ]
        n = len(db.statements)
        again = json.loads((await inbox.inbox_counts(fresh=False, user=a, db=db)).body)[
            "data"
        ]
        assert again["cached"] is True and again["total"] == first["total"]
        assert len(db.statements) == n
        other = json.loads((await inbox.inbox_counts(fresh=False, user=b, db=db)).body)[
            "data"
        ]
        assert other["cached"] is False and "held" not in other["available"]
        fresh = json.loads((await inbox.inbox_counts(fresh=True, user=a, db=db)).body)[
            "data"
        ]
        assert fresh["cached"] is False


async def test_ui_prefs_default_and_save():
    u = _user(settings={"email_on_failure": True})
    assert json.loads((await inbox.get_ui_prefs(user=u)).body)["data"] == {
        "sidebar_mode": "essentials"
    }
    db = FakeDB()
    bad = await inbox.put_ui_prefs(body={"sidebar_mode": "everything"}, user=u, db=db)
    assert bad.status_code == 400
    ok = await inbox.put_ui_prefs(body={"sidebar_mode": "all"}, user=u, db=db)
    assert json.loads(ok.body)["data"] == {"sidebar_mode": "all"}
    # notification choices stay untouched
    assert u.notification_settings["email_on_failure"] is True
    assert u.notification_settings["ui"] == {"sidebar_mode": "all"}
    assert db.commits == 1


async def test_alerts_list_needs_view_alerts():
    u = _user()
    with patch.object(inbox, "features_for", lambda _u: {"view_alerts": False}):
        res = await inbox.inbox_alerts(user=u, db=FakeDB())
    assert res.status_code == 403
