"""GET/PUT /api/me/journey: done flags per role from real state, scoped to the caller's tenant."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import app.core.platform_features as pf
import app.routers.llm_models as lm
from app.routers import journey as J
from models.agent import AgentStatus
from models.user import UserRole

pytestmark = pytest.mark.asyncio

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _user(role, tenant=TENANT_A, prefs=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant,
        role=role,
        email="x@x.dev",
        notification_settings=prefs,
    )


class Res:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalar(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)


def _tables(stmt) -> set[str]:
    names = set()
    for f in stmt.get_final_froms():
        for t in getattr(f, "_from_objects", [f]):
            n = getattr(t, "name", None)
            if n:
                names.add(n)
    return names


def _bound(stmt) -> list:
    out = []
    for v in stmt.compile().params.values():
        out.extend(v if isinstance(v, (list, tuple)) else [v])
    return out


class FakeDB:
    """Holds rows per tenant and refuses any query that does not bind a tenant."""

    def __init__(self, data):
        self.data = data
        self.statements = []
        self.commits = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        bound = _bound(stmt)
        tenants = [t for t in self.data if t in bound]
        assert len(tenants) == 1, f"query not scoped to exactly one tenant: {stmt}"
        rows = self.data[tenants[0]]
        tables = _tables(stmt)
        # the most specific table answers, joins put the answering one first
        for name in (
            "feedback",
            "improvement_proposals",
            "messages",
            "eval_cases",
            "reviews",
            "agent_actions",
            "autonomy_grants",
            "knowledge_collections",
            "executions",
            "conversations",
            "risk_policies",
            "moderation_policies",
            "users",
            "agents",
        ):
            if name in tables:
                return Res(rows.get(name, []))
        raise AssertionError(f"unexpected tables {tables}")

    async def commit(self):
        self.commits += 1


@pytest.fixture(autouse=True)
def _switches(monkeypatch):
    async def on(db):
        return True

    monkeypatch.setattr(pf, "marketplace_enabled", on)
    yield


def _flags(view):
    return {s["id"]: s["done"] for s in view["steps"]}


async def test_role_mapping():
    assert J.role_of(_user(UserRole.ADMIN)) == "admin"
    assert J.role_of(_user(UserRole.CREATOR)) == "builder"
    assert J.role_of(_user(UserRole.USER)) == "member"


async def test_admin_fresh_tenant(monkeypatch):
    async def none(db):
        return {"anthropic": {"configured": False, "reason": "no key"}}

    monkeypatch.setattr(lm, "_probe_providers", none)
    db = FakeDB({TENANT_A: {"users": [1]}})
    view = await J.journey_view(db, _user(UserRole.ADMIN))
    assert view["role"] == "admin"
    assert _flags(view) == {
        "connect_model": False,
        "invite_team": False,
        "review_risk": False,
        "moderation": False,
    }
    assert view["done"] == 0 and view["total"] == 4 and not view["complete"]


async def test_admin_all_done():
    db = FakeDB(
        {
            TENANT_A: {
                "users": [3],
                "risk_policies": [uuid.uuid4()],
                "moderation_policies": [uuid.uuid4()],
            }
        }
    )
    view = await J.journey_view(db, _user(UserRole.ADMIN))
    assert all(_flags(view).values())
    assert view["complete"]


async def test_admin_risk_done_by_visit():
    db = FakeDB({TENANT_A: {"users": [1]}})
    u = _user(UserRole.ADMIN, prefs={"journey": {"seen": ["risk"]}})
    assert _flags(await J.journey_view(db, u))["review_risk"] is True


async def test_builder_no_agents():
    db = FakeDB({TENANT_A: {}})
    view = await J.journey_view(db, _user(UserRole.CREATOR))
    assert view["role"] == "builder"
    assert not any(_flags(view).values())
    assert [s["id"] for s in view["steps"]][-1] == "list_marketplace"
    # nothing else is asked once there is no agent
    assert len(db.statements) == 1


async def test_builder_progress():
    aid = uuid.uuid4()
    db = FakeDB(
        {
            TENANT_A: {
                "agents": [(aid, False, AgentStatus.ACTIVE)],
                "executions": [uuid.uuid4()],
                "eval_cases": [uuid.uuid4()],
            }
        }
    )
    view = await J.journey_view(db, _user(UserRole.CREATOR))
    assert _flags(view) == {
        "build_agent": True,
        "run_agent": True,
        "add_knowledge": False,
        "add_tests": True,
        "enrol_autonomy": False,
        "review_improvements": False,
        "list_marketplace": False,
    }
    run = next(s for s in view["steps"] if s["id"] == "run_agent")
    assert run["href"] == f"/agents/{aid}/chat"


async def test_builder_pending_review_counts_as_listed():
    aid = uuid.uuid4()
    db = FakeDB(
        {
            TENANT_A: {
                "agents": [(aid, False, AgentStatus.PENDING_REVIEW)],
                "knowledge_collections": [uuid.uuid4()],
                "autonomy_grants": [uuid.uuid4()],
            }
        }
    )
    f = _flags(await J.journey_view(db, _user(UserRole.CREATOR)))
    assert f["list_marketplace"] and f["add_knowledge"] and f["enrol_autonomy"]


async def test_builder_marketplace_off_hides_step(monkeypatch):
    async def off(db):
        return False

    monkeypatch.setattr(pf, "marketplace_enabled", off)
    view = await J.journey_view(FakeDB({TENANT_A: {}}), _user(UserRole.CREATOR))
    assert "list_marketplace" not in _flags(view)
    assert view["total"] == 6


async def test_member_steps():
    first = uuid.uuid4()
    db = FakeDB({TENANT_A: {"conversations": [first]}})
    view = await J.journey_view(db, _user(UserRole.USER))
    assert view["role"] == "member"
    assert _flags(view) == {
        "try_chat": True,
        "follow_up": False,
        "give_feedback": False,
    }
    # follow-up and feedback reopen the newest thread, not a blank chat
    hrefs = {s["id"]: s["href"] for s in view["steps"]}
    assert hrefs["try_chat"] == "/chat"
    assert hrefs["follow_up"] == f"/chat?id={first}"
    assert hrefs["give_feedback"] == f"/chat?id={first}"

    # no thread yet, so the steps open chat itself
    view = await J.journey_view(FakeDB({TENANT_A: {}}), _user(UserRole.USER))
    assert {s["href"] for s in view["steps"]} == {"/chat"}

    # two of the member's messages in one thread
    conv = uuid.uuid4()
    db = FakeDB({TENANT_A: {"conversations": [conv], "messages": [conv]}})
    assert _flags(await J.journey_view(db, _user(UserRole.USER))) == {
        "try_chat": True,
        "follow_up": True,
        "give_feedback": False,
    }

    # one feedback row of their own
    db = FakeDB({TENANT_A: {"feedback": [uuid.uuid4()]}})
    assert _flags(await J.journey_view(db, _user(UserRole.USER)))["give_feedback"]


async def test_builder_improvements_step():
    aid = uuid.uuid4()
    agents = {"agents": [(aid, False, AgentStatus.ACTIVE)]}
    view = await J.journey_view(FakeDB({TENANT_A: agents}), _user(UserRole.CREATOR))
    step = next(s for s in view["steps"] if s["id"] == "review_improvements")
    assert step["href"] == "/improvements" and not step["done"]

    # a proposal they asked for
    db = FakeDB({TENANT_A: {**agents, "improvement_proposals": [uuid.uuid4()]}})
    assert _flags(await J.journey_view(db, _user(UserRole.CREATOR)))[
        "review_improvements"
    ]

    # or the seen marker from opening a group or proposal
    u = _user(UserRole.CREATOR, prefs={"journey": {"seen": ["improvements"]}})
    db = FakeDB({TENANT_A: agents})
    assert _flags(await J.journey_view(db, u))["review_improvements"]
    assert not any("improvement_proposals" in _tables(x) for x in db.statements)


async def test_note_seen_once():
    u = _user(UserRole.CREATOR)
    db = FakeDB({TENANT_A: {}})
    await J.note_seen(db, u, "improvements")
    await J.note_seen(db, u, "improvements")
    await J.note_seen(db, u, "nope")
    assert u.notification_settings["journey"]["seen"] == ["improvements"]
    assert db.commits == 1


async def test_tenant_isolation():
    aid = uuid.uuid4()
    full = {
        "users": [5],
        "risk_policies": [uuid.uuid4()],
        "moderation_policies": [uuid.uuid4()],
        "agents": [(aid, True, AgentStatus.ACTIVE)],
        "executions": [uuid.uuid4()],
        "knowledge_collections": [uuid.uuid4()],
        "eval_cases": [uuid.uuid4()],
        "autonomy_grants": [uuid.uuid4()],
        "conversations": [uuid.uuid4()],
        "agent_actions": [uuid.uuid4()],
        "reviews": [uuid.uuid4()],
        "messages": [uuid.uuid4()],
        "feedback": [uuid.uuid4()],
        "improvement_proposals": [uuid.uuid4()],
    }
    db = FakeDB({TENANT_A: full, TENANT_B: {}})
    for role in (UserRole.ADMIN, UserRole.CREATOR, UserRole.USER):
        mine = await J.journey_view(db, _user(role, tenant=TENANT_A))
        theirs = await J.journey_view(db, _user(role, tenant=TENANT_B))
        assert mine["complete"], role
        flags = _flags(theirs)
        flags.pop("connect_model", None)  # platform wide, not per tenant
        assert not any(flags.values()), (role, flags)
    for stmt in db.statements:
        assert "tenant_id" in str(stmt)


async def test_dismiss_and_bring_back():
    u = _user(UserRole.USER, prefs={"execution_failed": False})
    db = FakeDB({TENANT_A: {}})
    res = await J.set_journey({"dismissed": True}, user=u, db=db)
    assert res.status_code == 200
    assert u.notification_settings["journey"]["dismissed"] is True
    # notification prefs survive
    assert u.notification_settings["execution_failed"] is False
    assert (await J.journey_view(db, u))["dismissed"] is True
    await J.set_journey({"dismissed": False}, user=u, db=db)
    assert (await J.journey_view(db, u))["dismissed"] is False
    assert db.commits == 2


async def test_dismiss_rejects_non_bool():
    res = await J.set_journey(
        {"dismissed": "yes"}, user=_user(UserRole.USER), db=FakeDB({})
    )
    assert res.status_code == 400


async def test_mark_seen():
    u = _user(UserRole.ADMIN)
    db = FakeDB({TENANT_A: {"users": [1]}})
    res = await J.mark_seen({"step": "risk"}, user=u, db=db)
    assert res.status_code == 200
    assert u.notification_settings["journey"]["seen"] == ["risk"]
    await J.mark_seen({"step": "risk"}, user=u, db=db)
    assert db.commits == 1
    bad = await J.mark_seen({"step": "nope"}, user=u, db=db)
    assert bad.status_code == 400
