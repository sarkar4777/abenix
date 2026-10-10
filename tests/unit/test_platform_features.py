"""Marketplace and monetization switches: defaults, admin overrides and enforcement."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.core import platform_features as pf
from app.core.deps import get_current_user, get_db
from models.user import UserRole

TENANT = uuid.uuid4()


class _Res:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def all(self):
        return list(self._rows)

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar

    def first(self):
        return self._rows[0] if self._rows else None


class SwitchDB:
    """Answers the switch query from `stored`, records writes."""

    def __init__(self, stored: dict[str, str] | None = None, platform_tenant=TENANT):
        self.stored = dict(stored or {})
        self.writes: list[dict] = []
        self.commits = 0
        self.platform_tenant = platform_tenant

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "INSERT INTO platform_settings" in sql:
            self.writes.append(dict(params))
            self.stored[params["key"]] = params["value"]
            return _Res()
        if "FROM platform_settings" in sql:
            return _Res(rows=list(self.stored.items()))
        if "FROM users" in sql:
            rows = [(self.platform_tenant,)] if self.platform_tenant else []
            return _Res(rows=rows)
        return _Res()

    async def commit(self):
        self.commits += 1

    def add(self, _):
        pass


def _user(role=UserRole.ADMIN):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        email="someone@example.com",
        role=role,
        full_name="Someone",
    )


def _body(resp: JSONResponse) -> dict:
    return json.loads(resp.body)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("MARKETPLACE_ENABLED", raising=False)
    monkeypatch.delenv("MONETIZATION_ENABLED", raising=False)
    monkeypatch.delenv("ABENIX_PLATFORM_OPERATORS", raising=False)


# ── reading ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_defaults_are_marketplace_on_and_monetization_off():
    got = await pf.read_features(SwitchDB())
    assert got["marketplace"] is True
    assert got["monetization"] is False
    assert got["source"] == {"marketplace": "default", "monetization": "default"}


@pytest.mark.asyncio
async def test_env_sets_the_default(monkeypatch):
    monkeypatch.setenv("MARKETPLACE_ENABLED", "false")
    monkeypatch.setenv("MONETIZATION_ENABLED", "yes")
    got = await pf.read_features(SwitchDB())
    assert got["marketplace"] is False and got["monetization"] is True
    assert got["defaults"] == {"marketplace": False, "monetization": True}


@pytest.mark.asyncio
async def test_admin_value_wins_over_env(monkeypatch):
    monkeypatch.setenv("MONETIZATION_ENABLED", "true")
    db = SwitchDB({pf.MONETIZATION_KEY: "false", pf.MARKETPLACE_KEY: "garbage"})
    got = await pf.read_features(db)
    assert got["monetization"] is False
    assert got["source"]["monetization"] == "admin"
    # an unreadable stored value falls back to the default
    assert got["marketplace"] is True
    assert got["source"]["marketplace"] == "default"


@pytest.mark.asyncio
async def test_a_broken_database_falls_back_to_env():
    class Broken:
        async def execute(self, *a, **k):
            raise RuntimeError("no table")

    got = await pf.read_features(Broken())
    assert got["marketplace"] is True and got["monetization"] is False


@pytest.mark.asyncio
async def test_require_helpers_raise_plain_404():
    off = SwitchDB({pf.MARKETPLACE_KEY: "false"})
    with pytest.raises(HTTPException) as exc:
        await pf.require_marketplace(off)
    assert exc.value.status_code == 404
    assert exc.value.detail["message"] == pf.MARKETPLACE_OFF
    with pytest.raises(HTTPException) as exc:
        await pf.require_monetization(SwitchDB())
    assert exc.value.detail["error_code"] == "MONETIZATION_OFF"
    await pf.require_marketplace(SwitchDB())


# ── the endpoints ────────────────────────────────────────────────────


def _client(user, db, *modules):
    from app.main import _http_exception_handler

    app = FastAPI()
    app.add_exception_handler(HTTPException, _http_exception_handler)
    for m in modules:
        app.include_router(m.router)

    async def _u():
        return user

    async def _d():
        yield db

    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[get_db] = _d
    return TestClient(app)


def test_features_endpoint_reports_both_switches():
    from app.routers import platform_features as router

    c = _client(_user(UserRole.USER), SwitchDB({pf.MARKETPLACE_KEY: "off"}), router)
    data = c.get("/api/platform/features").json()["data"]
    assert data["marketplace"] is False and data["monetization"] is False


def test_only_an_admin_can_flip_a_switch():
    from app.routers import platform_features as router

    db = SwitchDB()
    c = _client(_user(UserRole.CREATOR), db, router)
    r = c.put("/api/admin/platform-features", json={"monetization": True})
    assert r.status_code == 403
    assert db.writes == []


def test_an_admin_of_another_tenant_cannot_flip_a_switch():
    from app.routers import platform_features as router

    db = SwitchDB(platform_tenant=uuid.uuid4())
    c = _client(_user(), db, router)
    r = c.put("/api/admin/platform-features", json={"marketplace": False})
    assert r.status_code == 403
    assert r.json()["error"]["error_code"] == "PLATFORM_OPERATOR_REQUIRED"
    assert db.writes == []
    got = c.get("/api/admin/platform-features").json()["data"]
    assert got["can_change"] is False and "platform tenant" in got["operator_rule"]


def test_operator_list_overrides_the_platform_tenant(monkeypatch):
    from app.routers import platform_features as router

    monkeypatch.setenv(
        "ABENIX_PLATFORM_OPERATORS", "ops@example.com, Someone@Example.com"
    )
    db = SwitchDB(platform_tenant=uuid.uuid4())
    c = _client(_user(), db, router)
    assert c.get("/api/admin/platform-features").json()["data"]["can_change"] is True
    with patch("app.routers.platform_features.log_action", AsyncMock()):
        r = c.put("/api/admin/platform-features", json={"monetization": True})
    assert r.status_code == 200

    # listed but not an admin is still refused
    c = _client(_user(UserRole.USER), SwitchDB(), router)
    r = c.put("/api/admin/platform-features", json={"monetization": True})
    assert r.status_code == 403

    # an admin of the platform tenant who is not listed is refused
    monkeypatch.setenv("ABENIX_PLATFORM_OPERATORS", "ops@example.com")
    c = _client(_user(), SwitchDB(), router)
    assert (
        c.put("/api/admin/platform-features", json={"marketplace": True}).status_code
        == 403
    )


def test_secret_storage_status_is_for_admins(monkeypatch):
    from app.routers import platform_features as router

    monkeypatch.delenv("ABENIX_DATA_KEY_KEK_BASE64", raising=False)
    c = _client(_user(UserRole.USER), SwitchDB(), router)
    assert c.get("/api/admin/secret-storage").status_code == 403
    data = (
        _client(_user(), SwitchDB(), router)
        .get("/api/admin/secret-storage")
        .json()["data"]
    )
    assert data["encrypted_at_rest"] is False
    assert "ABENIX_DATA_KEY_KEK_BASE64" in data["message"]


def test_admin_flips_and_bad_values_are_refused():
    from app.routers import platform_features as router

    db = SwitchDB()
    c = _client(_user(), db, router)
    assert c.put("/api/admin/platform-features", json={}).status_code == 400
    bad = c.put("/api/admin/platform-features", json={"marketplace": "maybe"})
    assert bad.status_code == 400
    with patch("app.routers.platform_features.log_action", AsyncMock()):
        r = c.put(
            "/api/admin/platform-features",
            json={"marketplace": False, "monetization": True},
        )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["marketplace"] is False and data["monetization"] is True
    assert {w["key"]: w["value"] for w in db.writes} == {
        pf.MARKETPLACE_KEY: "false",
        pf.MONETIZATION_KEY: "true",
    }


def test_marketplace_routes_answer_404_when_off():
    from app.routers import marketplace, reviews

    c = _client(_user(), SwitchDB({pf.MARKETPLACE_KEY: "false"}), marketplace, reviews)
    for method, path in [
        ("GET", "/api/marketplace"),
        ("GET", f"/api/marketplace/{uuid.uuid4()}"),
        ("POST", f"/api/marketplace/subscribe/{uuid.uuid4()}"),
        ("GET", f"/api/agents/{uuid.uuid4()}/reviews"),
    ]:
        r = c.request(method, path, json={"plan_type": "free"})
        assert r.status_code == 404, path
        assert r.json()["error"]["message"] == pf.MARKETPLACE_OFF


def test_monetized_routes_answer_404_when_off():
    from app.routers import billing, creator

    c = _client(_user(), SwitchDB(), billing, creator)
    for method, path in [
        ("GET", "/api/billing/plans"),
        ("POST", "/api/billing/checkout"),
        ("POST", "/api/billing/portal"),
        ("POST", "/api/billing/webhook"),
        ("POST", "/api/creator/onboard"),
        ("GET", "/api/creator/status"),
        ("GET", "/api/creator/dashboard"),
        ("GET", "/api/creator/login-link"),
    ]:
        r = c.request(method, path, json={})
        assert r.status_code == 404, path
        assert r.json()["error"]["message"] == pf.MONETIZATION_OFF


def test_billing_usage_stays_open_and_reads_zero_on_the_subscription():
    from app.routers import billing

    stats = {"total_cost": 4.2, "by_agent": [{"agent_id": "a", "cost": 4.2}]}
    with patch.object(billing, "get_usage_stats", AsyncMock(return_value=stats)), patch(
        "app.routers.llm_models._subscription_state",
        AsyncMock(return_value={"active": True}),
    ):
        r = _client(_user(), SwitchDB(), billing).get("/api/billing/usage")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["billing_mode"] == "claude_subscription"
    assert data["total_cost"] == 0 and data["by_agent"][0]["cost"] == 0
    assert data["monetization"] is False


# ── publish and review ───────────────────────────────────────────────


def _agent():
    from models.agent import AgentStatus, AgentType

    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        creator_id=uuid.uuid4(),
        name="Helper",
        system_prompt="help",
        model_config_={},
        agent_type=AgentType.CUSTOM,
        status=AgentStatus.ACTIVE,
        is_published=False,
        marketplace_price=None,
        category=None,
    )


class AgentDB(SwitchDB):
    def __init__(self, agent, stored=None):
        super().__init__(stored)
        self.agent = agent

    async def execute(self, stmt, params=None):
        if "platform_settings" in str(stmt):
            return await super().execute(stmt, params)
        if "agent_revisions" in str(stmt):
            return _Res(scalar=None)
        return _Res(scalar=self.agent)

    async def refresh(self, _):
        pass

    async def flush(self):
        pass

    async def rollback(self):
        pass


async def _publish(agent, db, body):
    from app.routers import agents as agents_router
    from app.schemas.agents import PublishAgentRequest

    with patch(
        "app.core.permissions.can_publish_agent", return_value=(True, "")
    ), patch.object(
        agents_router, "_risk_activation_problem", AsyncMock(return_value=None)
    ), patch.object(
        agents_router, "_eval_gate_problem", AsyncMock(return_value=None)
    ), patch.object(
        agents_router, "log_action", AsyncMock()
    ), patch.object(
        agents_router, "_serialize_agent", lambda a: {"status": str(a.status)}
    ):
        return await agents_router.publish_agent(
            agent.id, PublishAgentRequest(**body), _user(), db
        )


@pytest.mark.asyncio
async def test_public_publish_is_refused_while_the_marketplace_is_off():
    agent = _agent()
    db = AgentDB(agent, {pf.MARKETPLACE_KEY: "false"})
    resp = await _publish(agent, db, {"visibility": "public"})
    assert resp.status_code == 409
    assert _body(resp)["error"]["error_code"] == "MARKETPLACE_OFF"
    assert db.commits == 0


@pytest.mark.asyncio
async def test_a_price_is_refused_while_monetization_is_off():
    agent = _agent()
    db = AgentDB(agent)
    resp = await _publish(agent, db, {"visibility": "public", "marketplace_price": 9})
    assert resp.status_code == 409
    assert _body(resp)["error"]["error_code"] == "MONETIZATION_OFF"


@pytest.mark.asyncio
async def test_free_listing_goes_to_review_and_drops_an_old_price():
    from models.agent import AgentStatus

    agent = _agent()
    agent.marketplace_price = 12
    resp = await _publish(agent, AgentDB(agent), {"visibility": "public"})
    assert resp.status_code == 200
    assert agent.status == AgentStatus.PENDING_REVIEW
    assert agent.marketplace_price is None
    assert agent.is_published is False


@pytest.mark.asyncio
async def test_approval_is_refused_while_the_marketplace_is_off():
    from app.routers import agents as agents_router
    from app.schemas.agents import ReviewAgentRequest
    from models.agent import AgentStatus

    agent = _agent()
    agent.status = AgentStatus.PENDING_REVIEW
    db = AgentDB(agent, {pf.MARKETPLACE_KEY: "false"})
    resp = await agents_router.review_agent(
        agent.id, ReviewAgentRequest(action="approve"), _user(), db
    )
    assert resp.status_code == 409
    assert agent.status == AgentStatus.PENDING_REVIEW


# ── plan caps ────────────────────────────────────────────────────────


class LimitDB(SwitchDB):
    def __init__(self, plan, today, stored=None):
        super().__init__(stored)
        self.plan = plan
        self.today = today

    async def execute(self, stmt, params=None):
        if "platform_settings" in str(stmt):
            return await super().execute(stmt, params)
        if "tenants" in str(stmt):
            return _Res(scalar=SimpleNamespace(plan=self.plan))
        return _Res(scalar=self.today)


@pytest.mark.asyncio
async def test_plan_cap_does_not_apply_without_monetization():
    from app.core.usage import check_limit
    from app.core.stripe import get_daily_limit

    cap = get_daily_limit("free")
    ok, msg = await check_limit(LimitDB("free", cap + 5), TENANT)
    assert ok and msg == ""
    ok, msg = await check_limit(
        LimitDB("free", cap + 5, {pf.MONETIZATION_KEY: "true"}), TENANT
    )
    assert not ok and "Upgrade" in msg


# ── creator hub ──────────────────────────────────────────────────────


class ListingsDB(SwitchDB):
    def __init__(self, agents, *rows):
        super().__init__()
        self.agents = agents
        self.rows = list(rows)

    async def execute(self, stmt, params=None):
        if "platform_settings" in str(stmt):
            return await super().execute(stmt, params)
        if self.agents is not None:
            agents, self.agents = self.agents, None
            res = _Res()
            res.scalars = lambda: SimpleNamespace(all=lambda: agents)
            return res
        return _Res(rows=self.rows.pop(0) if self.rows else [])


@pytest.mark.asyncio
async def test_creator_listings_show_state_installs_and_usage_without_money():
    from app.routers import creator
    from models.agent import AgentStatus

    live, pending, draft = _agent(), _agent(), _agent()
    live.status, live.is_published, live.marketplace_price = AgentStatus.ACTIVE, True, 5
    pending.status = AgentStatus.PENDING_REVIEW
    draft.status, draft.name = AgentStatus.DRAFT, "Draft one"
    for a in (live, pending, draft):
        a.description, a.rejection_reason, a.updated_at = None, None, None
    db = ListingsDB(
        [live, pending, draft],
        [(live.id, 3)],
        [(live.id, 7, 2)],
        [(live.id, 4.5, 2)],
    )
    resp = await creator.creator_listings(_user(UserRole.CREATOR), db)
    data = _body(resp)["data"]
    assert data["can_list"] is True and data["monetization"] is False
    by_state = {r["state"]: r for r in data["listings"]}
    assert set(by_state) == {"live", "pending"}
    assert by_state["live"]["installs"] == 3 and by_state["live"]["runs_30d"] == 7
    assert "price" not in by_state["live"]
    assert [e["name"] for e in data["eligible"]] == ["Draft one"]
    assert data["totals"] == {"live": 1, "pending": 1, "installs": 3, "runs_30d": 7}
