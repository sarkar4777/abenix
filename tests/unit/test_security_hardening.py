"""Regression tests for the tenant isolation and privilege fixes in the API."""

from __future__ import annotations

import ast
import json
import os
import pickle
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import platform_features as pf
from app.core.deps import get_current_user, get_db
from models.user import UserRole

ROOT = Path(__file__).resolve().parents[2]
ROUTERS = ROOT / "apps/api/app/routers"
TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _user(role=UserRole.ADMIN, tenant=TENANT_A, email="tenant-admin@example.com"):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant, role=role, email=email, is_admin=False
    )


class _Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)


class _DB:
    def __init__(self, rows=()):
        self.rows = rows
        self.statements: list[str] = []
        self.added: list = []

    async def execute(self, stmt, params=None):
        self.statements.append(str(stmt))
        return _Result(self.rows)

    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None

    def add(self, obj):
        self.added.append(obj)

    async def close(self):
        return None


def _client(router, user, db=None) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    async def _current():
        return user

    async def _session():
        yield db or _DB()

    app.dependency_overrides[get_current_user] = _current
    app.dependency_overrides[get_db] = _session
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _no_capability_cache(monkeypatch):
    from app.core import capabilities

    monkeypatch.setattr(capabilities, "_cache", {})
    monkeypatch.delenv("ABENIX_PLATFORM_OPERATORS", raising=False)


def _kwargs_of_assignment(path: Path, name: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if (
            isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", "") == name
            and isinstance(node.value, ast.Call)
        ):
            found |= {k.arg for k in node.value.keywords if k.arg}
    return found


def test_inline_executors_carry_the_tenant():
    agents = ROUTERS / "agents.py"
    assert "tenant_id" in _kwargs_of_assignment(agents, "_exec_kwargs")
    assert "tenant_id" in _kwargs_of_assignment(agents, "_exec_kwargs2")
    assert "tenant_id" in _kwargs_of_assignment(ROUTERS / "triggers.py", "executor")


@pytest.mark.parametrize("path", ["tools", "tool_presets"])
def test_caller_config_cannot_set_server_owned_fields(path):
    from app.core.tool_access import caller_config

    got = caller_config(
        {
            "tenant_id": str(TENANT_B),
            "db_url": "postgresql://evil",
            "default_connection": "postgresql://evil",
            "user_role": "admin",
            "kb_ids": ["x"],
            "api_key": "stolen",
            "thresholds": {"hate": 0.2},
        },
        path,
    )
    assert got == {"thresholds": {"hate": 0.2}}


def test_direct_tool_execute_needs_the_capability():
    from app.routers import tools

    client = _client(tools.router, _user(UserRole.USER))
    res = client.post("/api/tools/calculator/execute", json={"arguments": {}})
    assert res.status_code == 403
    assert res.json()["error"]["error_code"] == "MISSING_PERMISSION"


@pytest.mark.parametrize(
    "slug", ["database_query", "file_system", "file_reader", "code_executor"]
)
def test_dangerous_tools_are_refused_for_a_tenant_admin(slug):
    from app.routers import tools

    res = _client(tools.router, _user()).post(
        f"/api/tools/{slug}/execute", json={"arguments": {}}
    )
    assert res.status_code == 403
    assert res.json()["error"]["error_code"] == "PLATFORM_OPERATOR_REQUIRED"


def test_download_is_jailed_to_the_tenants_folder(tmp_path, monkeypatch):
    from engine.storage import service
    from app.routers import files

    monkeypatch.setattr(service, "STORAGE_LOCAL_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(service, "STORAGE_S3_BUCKET", "abenix-files")
    mine = tmp_path / "uploads" / str(TENANT_A) / "kb" / "report.pdf"
    mine.parent.mkdir(parents=True)
    mine.write_bytes(b"mine")
    theirs = tmp_path / "uploads" / str(TENANT_B) / "secret.pdf"
    theirs.parent.mkdir(parents=True)
    theirs.write_bytes(b"theirs")
    outside = tmp_path / "secrets.env"
    outside.write_text("KEY=1")
    link = mine.parent / "link.env"
    link.symlink_to(outside)

    client = _client(files.router, _user())
    ok = client.get("/api/files/download", params={"uri": f"file://{mine}"})
    assert ok.status_code == 200 and ok.content == b"mine"
    for uri in (
        f"file://{theirs}",
        str(theirs),
        str(outside),
        f"file://{link}",
        f"{mine.parent}/../../secrets.env",
        "/etc/passwd",
        f"s3://abenix-files/{TENANT_B}/secret.pdf",
        f"s3://another-bucket/{TENANT_A}/secret.pdf",
        f"s3://abenix-files/{TENANT_A}/../{TENANT_B}/secret.pdf",
    ):
        assert client.get("/api/files/download", params={"uri": uri}).status_code == 404


@pytest.mark.parametrize(
    "env,expected",
    [
        ({"ENVIRONMENT": "production"}, False),
        ({"ENVIRONMENT": "staging"}, False),
        ({"ENVIRONMENT": "local"}, True),
        ({"ENVIRONMENT": "production", "PLAYGROUND_EXECUTE_ENABLED": "true"}, True),
        ({"ENVIRONMENT": "local", "PLAYGROUND_EXECUTE_ENABLED": "false"}, False),
    ],
)
def test_playground_is_off_outside_dev(monkeypatch, env, expected):
    from app.core.playground_access import execute_enabled

    for key in ("ENVIRONMENT", "IS_LOCAL_DEV", "PLAYGROUND_EXECUTE_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert execute_enabled() is expected


@pytest.mark.parametrize(
    "module,path,body",
    [
        (
            "sdk_playground",
            "/api/sdk-playground/execute",
            {"code": "print(1)", "language": "python"},
        ),
        ("load_playground", "/api/load-playground/execute", {"code": "print(1)"}),
    ],
)
def test_plain_user_cannot_run_playground_code(monkeypatch, module, path, body):
    import importlib

    monkeypatch.setenv("ENVIRONMENT", "local")
    router = importlib.import_module(f"app.routers.{module}").router
    res = _client(router, _user(UserRole.USER)).post(path, json=body)
    assert res.status_code == 403
    assert "Run playground code" in res.text


class _Payload:
    def __init__(self, marker):
        self.marker = marker

    def __reduce__(self):
        return (os.system, (f"touch {self.marker}",))


def test_pickle_upload_does_not_run_code_in_this_process(tmp_path):
    from engine import process_sandbox as model_sandbox

    marker = tmp_path / "pwned"
    path = tmp_path / "evil.pkl"
    path.write_bytes(pickle.dumps(_Payload(marker)))

    with pytest.raises(model_sandbox.ModelSandboxError, match="os.system"):
        model_sandbox.run_isolated("validate", str(path), "sklearn")
    assert not marker.exists()


def test_isolated_process_sees_no_secrets_and_no_other_files(tmp_path, monkeypatch):
    from engine import process_sandbox as model_sandbox

    monkeypatch.setenv("SECRET_KEY", "must-not-leak")
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("x")

    class ReadsEnv:
        def __reduce__(self):
            code = (
                "1/0 if __import__('os').environ.get('SECRET_KEY') else int('absent')"
            )
            return (eval, (code,))

    class ReadsFile:
        def __reduce__(self):
            return (open, (str(secret_file),))

    env_path = tmp_path / "env.pkl"
    env_path.write_bytes(pickle.dumps(ReadsEnv()))
    with pytest.raises(model_sandbox.ModelSandboxError, match="absent"):
        model_sandbox.run_isolated("validate", str(env_path), "sklearn")

    file_path = tmp_path / "file.pkl"
    file_path.write_bytes(pickle.dumps(ReadsFile()))
    with pytest.raises(model_sandbox.ModelSandboxError, match="not allowed"):
        model_sandbox.run_isolated("validate", str(file_path), "sklearn")


def test_real_sklearn_model_validates_and_predicts_in_isolation(tmp_path):
    import joblib
    from sklearn.linear_model import LinearRegression

    from engine import process_sandbox as model_sandbox

    model = LinearRegression().fit(
        [[0.0, 1.0], [1.0, 0.0], [2.0, 2.0]], [0.0, 1.0, 2.0]
    )
    path = tmp_path / "ok.joblib"
    joblib.dump(model, path)

    info = model_sandbox.run_isolated("validate", str(path), "sklearn")
    assert info["type"] == "LinearRegression" and info["n_features"] == 2
    out = model_sandbox.run_isolated("predict", str(path), "sklearn", [[1.0, 1.0]])
    assert len(out["predictions"]) == 1
    with pytest.raises(model_sandbox.ModelInputError, match="expects 2 features"):
        model_sandbox.run_isolated("predict", str(path), "sklearn", [[1.0]])


@pytest.mark.asyncio
async def test_plain_user_cannot_upload_a_pickle(tmp_path):
    from io import BytesIO

    from fastapi import UploadFile

    from app.routers import ml_models as mm

    res = await mm.upload_model(
        UploadFile(file=BytesIO(b"x"), filename="m.joblib"),
        "{}",
        _user(UserRole.USER),
        _DB(),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_explain_refuses_a_pickle_outside_the_platform_tenant():
    from app.routers import ml_models as mm
    from models.ml_model import MLModel, MLModelFramework, MLModelStatus

    user = _user()
    model = MLModel(
        tenant_id=user.tenant_id,
        name="m",
        version="1.0.0",
        framework=MLModelFramework.SKLEARN,
        file_uri="/nope/m.joblib",
        status=MLModelStatus.READY,
        created_by=user.id,
    )
    db = _ScopeDB(platform=TENANT_B, rows=[model])
    res = await mm.explain(uuid.uuid4(), {"input_data": [1.0]}, user, db)
    assert res.status_code == 422
    assert json.loads(res.body)["error"]["error_code"] == "EXPLAIN_NEEDS_ONNX"


class _ScopeDB(_DB):
    """Answers the platform tenant lookup, records every other statement."""

    def __init__(self, platform=None, rows=()):
        super().__init__(rows)
        self.platform = platform

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.statements.append(sql)
        if "FROM users WHERE lower(email)" in sql:
            return _Result([(self.platform,)] if self.platform else [])
        return _Result(self.rows)


@pytest.mark.asyncio
async def test_scaling_list_is_scoped_to_the_callers_tenant():
    from app.routers import admin_scaling as scaling

    assert await scaling._agent_scope(_ScopeDB(platform=TENANT_B), _user())
    assert not await scaling._agent_scope(
        _ScopeDB(platform=TENANT_A), _user(tenant=TENANT_A)
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("patch", f"/api/admin/scaling/agents/{uuid.uuid4()}", {"min_replicas": 1}),
        ("post", f"/api/admin/scaling/agents/{uuid.uuid4()}/pause", None),
        ("post", f"/api/admin/scaling/agents/{uuid.uuid4()}/resume", None),
    ],
)
def test_scaling_cannot_reach_another_tenants_agent(method, path, body):
    from app.routers import admin_scaling as scaling

    db = _ScopeDB(platform=TENANT_B)
    client = _client(scaling.router, _user(), db)
    kwargs = {"json": body} if body is not None else {}
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code == 404
    agent_query = next(s for s in db.statements if "FROM agents" in s)
    assert "agents.tenant_id" in agent_query


def test_tenant_spend_is_refused_for_another_tenant():
    from app.routers import admin_scaling as scaling

    db = _ScopeDB(platform=TENANT_B)
    res = _client(scaling.router, _user(), db).get(
        f"/api/admin/scaling/tenants/{TENANT_B}/spend"
    )
    assert res.status_code == 403


@pytest.mark.parametrize(
    "module,method,path,body",
    [
        ("admin_settings", "patch", "/api/admin/settings/llm.default", {"value": "x"}),
        ("admin_settings", "post", "/api/admin/settings/reset", None),
        ("admin_pricing", "post", "/api/admin/llm-pricing/seed", None),
        ("admin_pricing", "delete", f"/api/admin/llm-pricing/{uuid.uuid4()}", None),
        (
            "admin_model_availability",
            "post",
            "/api/admin/model-availability/force-status",
            {"model": "m", "status": "ok"},
        ),
        ("tool_runtime", "post", "/api/admin/tool-runtime", {"slug": "calculator"}),
        ("admin_cluster", "get", "/api/admin/cluster/pods/x/logs", None),
    ],
)
def test_a_tenant_admin_cannot_change_platform_state(module, method, path, body):
    import importlib

    router = importlib.import_module(f"app.routers.{module}").router
    client = _client(router, _user(), _ScopeDB(platform=TENANT_B))
    kwargs = {"json": body} if body is not None else {}
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code == 403
    assert "platform operator" in res.text


@pytest.mark.asyncio
async def test_platform_tenant_admin_is_an_operator_and_a_signup_is_not():
    seed_admin = _user(tenant=TENANT_A, email="admin@abenix.dev")
    signup = _user(tenant=TENANT_B, email="someone@example.com")
    db = _ScopeDB(platform=TENANT_A)
    assert await pf.is_platform_operator(db, seed_admin)
    assert not await pf.is_platform_operator(db, signup)


@pytest.mark.asyncio
async def test_tenant_admin_cannot_plant_or_review_shipped_agents():
    from app.routers import agents as agents_router
    from app.schemas.agents import CreateAgentRequest, ReviewAgentRequest

    db = _ScopeDB(platform=TENANT_B)
    res = await agents_router.review_agent(
        uuid.uuid4(), ReviewAgentRequest(action="approve"), _user(), db
    )
    assert res.status_code == 403
    planted = await agents_router.create_agent(
        CreateAgentRequest(name="Planted", agent_type="oob"),
        SimpleNamespace(),
        _user(),
        _ScopeDB(platform=TENANT_B),
    )
    assert planted.status_code == 403


@pytest.mark.parametrize(
    "new_scopes",
    [
        {"can_delegate": True},
        {"allowed_actions": ["read", "can_delegate"]},
        ["can_delegate"],
        {"allowed_actions": ["telemetry.command"]},
    ],
)
@pytest.mark.asyncio
async def test_an_api_key_cannot_raise_its_own_scopes(new_scopes):
    from app.routers import api_keys
    from models.api_key import ApiKey

    user = _user()
    user._api_key_id = uuid.uuid4()
    user._api_key_scopes = {"allowed_actions": ["read"]}
    key = ApiKey(
        id=user._api_key_id,
        tenant_id=user.tenant_id,
        user_id=user.id,
        name="k",
        key_hash="h",
        key_prefix="p",
        scopes={"allowed_actions": ["read"]},
    )
    res = await api_keys.update_api_key(
        key.id, {"scopes": new_scopes}, user, _DB([key])
    )
    assert res.status_code == 403
    assert key.scopes == {"allowed_actions": ["read"]}


@pytest.mark.asyncio
async def test_a_plain_user_cannot_grant_delegation_at_all(monkeypatch):
    from app.routers import api_keys

    refused = await api_keys._scope_refusal(
        _DB(), _user(UserRole.USER), {"can_delegate": True}, set()
    )
    assert refused and "admin" in refused


@pytest.mark.asyncio
async def test_an_admin_session_can_still_grant_delegation():
    from app.routers import api_keys

    assert (
        await api_keys._scope_refusal(_DB(), _user(), {"can_delegate": True}, set())
        is None
    )


@pytest.mark.asyncio
async def test_a_key_may_drop_a_scope_it_already_holds():
    from app.routers import api_keys

    user = _user(UserRole.USER)
    user._api_key_id = uuid.uuid4()
    user._api_key_scopes = {"allowed_actions": ["read", "can_delegate"]}
    assert (
        await api_keys._scope_refusal(
            _DB(), user, {"allowed_actions": ["read"]}, {"read", "can_delegate"}
        )
        is None
    )


@pytest.mark.asyncio
async def test_slug_lookup_prefers_own_tenant_then_shipped_only():
    from app.core.agent_lookup import find_agent_by_slug

    db = _DB()
    await find_agent_by_slug(db, "oraclenet-pipeline", TENANT_A)
    sql = db.statements[0]
    assert "agents.tenant_id" in sql and "agents.agent_type" in sql
    assert "ORDER BY" in sql


@pytest.mark.parametrize(
    "router,needle",
    [
        ("oraclenet.py", 'Agent.slug == "oraclenet-pipeline"'),
        ("bpm_analyzer.py", "Agent.slug == AGENT_SLUG"),
        ("meetings.py", 'Agent.slug == "meeting-representative"'),
    ],
)
def test_no_feature_resolves_a_slug_globally(router, needle):
    assert needle not in (ROUTERS / router).read_text()


@pytest.mark.parametrize(
    "kind",
    [
        "autonomy.promote",
        "improvement.release",
        "decision_publish",
        "decision_retire",
        "telemetry.command",
        "action:refund",
    ],
)
def test_public_approval_create_rejects_reserved_kinds(kind):
    from app.routers import approvals

    client = _client(approvals.router, _user())
    res = client.post("/api/approvals", json={"title": "x", "gate_kind": kind})
    assert res.status_code == 422
    assert res.json()["error"]["error_code"] == "RESERVED_GATE_KIND"


@pytest.mark.parametrize("kind", ["uat.test", "e2e-audit", "broker.acknowledge", None])
def test_custom_approval_kinds_stay_allowed(kind):
    from app.routers import approvals

    assert approvals._reserved_gate_kind(kind) is False


@pytest.mark.asyncio
async def test_promotion_ignores_a_dummy_creator_in_the_payload(monkeypatch):
    from app.services import autonomy

    author = _user()

    async def grant(*_a):
        return SimpleNamespace(agent_id=uuid.uuid4(), action_type_id=uuid.uuid4())

    async def agent(*_a):
        return SimpleNamespace(creator_id=author.id)

    async def reason(*_a):
        return None

    monkeypatch.setattr(autonomy, "get_grant", grant)
    monkeypatch.setattr(autonomy, "get_agent", agent)
    monkeypatch.setattr(autonomy, "self_approval_reason", reason)

    class Db:
        async def get(self, *_a):
            return None

    approval = SimpleNamespace(
        tenant_id=TENANT_A, payload={"agent_creator_id": "dummy", "grant_id": "g"}
    )
    assert await autonomy.promotion_denial(Db(), author, approval)


@pytest.mark.asyncio
async def test_release_ignores_a_dummy_creator_in_the_payload(monkeypatch):
    from app.services import improvements

    author = _user()

    async def agent(*_a):
        return SimpleNamespace(creator_id=author.id)

    async def reason(*_a):
        return None

    monkeypatch.setattr(improvements, "get_agent", agent)
    monkeypatch.setattr(improvements, "self_approval_reason", reason)
    approval = SimpleNamespace(
        tenant_id=TENANT_A,
        payload={"agent_creator_id": "dummy", "agent": {"id": "a"}},
    )
    assert await improvements.release_denial(None, author, approval)


def test_gateway_register_cannot_take_over_another_tenant():
    from app.routers import edge

    existing = SimpleNamespace(
        tenant_id=TENANT_B, name="theirs", endpoint_url="https://theirs.example"
    )
    client = _client(edge.router, _user(), _DB([existing]))
    res = client.post(
        "/api/edge/gateways/register",
        json={"gateway_id": "gw-1", "endpoint_url": "https://evil.example"},
    )
    assert res.status_code == 409
    assert existing.endpoint_url == "https://theirs.example"


def test_card_only_serves_published_agents():
    from app.routers import a2a

    db = _DB()
    res = _client(a2a.router, _user(), db).get(f"/api/a2a/agents/{uuid.uuid4()}/card")
    assert res.status_code == 404
    assert "agents.is_published IS true" in db.statements[0]


def test_kb_query_stream_refuses_another_tenant():
    from app.routers import invocations

    res = _client(invocations.router, _user(), _DB([TENANT_B])).get(
        f"/api/knowledge-collections/{uuid.uuid4()}/queries/stream"
    )
    assert "not_found" in res.text


def test_execution_detail_hides_the_prompt_from_other_members(monkeypatch):
    from app.routers import executions, llm_models

    async def sub_state(_db):
        return {"active": False}

    monkeypatch.setattr(llm_models, "_subscription_state", sub_state)
    monkeypatch.setattr(executions, "_serialize_execution", lambda _e: {"id": "x"})
    row = (
        SimpleNamespace(),
        "Agent",
        "the secret prompt",
        {"tool_config": {"k": "v"}},
        uuid.uuid4(),
    )
    member = _user(UserRole.USER)
    body = (
        _client(executions.router, member, _DB([row]))
        .get(f"/api/executions/{uuid.uuid4()}")
        .json()["data"]
    )
    assert "system_prompt" not in body and "tool_config" not in body

    owner = _user(UserRole.USER)
    owner_row = (*row[:4], owner.id)
    body = (
        _client(executions.router, owner, _DB([owner_row]))
        .get(f"/api/executions/{uuid.uuid4()}")
        .json()["data"]
    )
    assert body["system_prompt"] == "the secret prompt"


@pytest.mark.parametrize(
    "peer,forwarded,expected",
    [
        ("10.0.0.5", "1.2.3.4, 9.9.9.9", "9.9.9.9"),
        ("10.0.0.5", "9.9.9.9", "9.9.9.9"),
        ("10.0.0.5", "9.9.9.9, 10.0.0.9", "9.9.9.9"),
        ("8.8.8.8", "1.2.3.4", "8.8.8.8"),
        ("10.0.0.5", None, "10.0.0.5"),
    ],
)
def test_client_ip_cannot_be_chosen_by_the_caller(peer, forwarded, expected):
    from app.core.rate_limit import client_ip_from

    assert client_ip_from(peer, forwarded) == expected


@pytest.mark.asyncio
async def test_rate_limit_lets_requests_through_when_redis_is_down(monkeypatch):
    import redis.asyncio as aioredis

    from app.core import rate_limit

    async def down():
        raise aioredis.ConnectionError("refused")

    monkeypatch.setattr(rate_limit, "_get_redis", down)
    allowed, _remaining, retry = await rate_limit.sliding_window_check("k", 5, 60)
    assert allowed is True and retry == 0


@pytest.mark.parametrize("module", ["sso", "sso_oidc"])
def test_sso_state_never_uses_a_public_literal(monkeypatch, module):
    import importlib

    mod = importlib.import_module(f"app.routers.{module}")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    assert mod._state_secret() == mod.settings.secret_key
    assert "dev-secret-do-not-use-in-prod" not in Path(mod.__file__).read_text()


def _checkout_body():
    return {
        "plan": "pro",
        "success_url": "https://x.example/ok",
        "cancel_url": "https://x.example/no",
    }


def test_member_cannot_change_the_plan_in_mock_mode(monkeypatch):
    from app.routers import billing

    monkeypatch.setattr(billing, "is_mock_mode", lambda: True)
    app = FastAPI()
    app.include_router(billing.router)
    user = _user(UserRole.USER)

    async def _current():
        return user

    async def _session():
        yield _ScopeDB(platform=TENANT_B)

    async def _paid():
        return None

    app.dependency_overrides[get_current_user] = _current
    app.dependency_overrides[get_db] = _session
    app.dependency_overrides[pf.require_monetization] = _paid
    res = TestClient(app).post("/api/billing/checkout", json=_checkout_body())
    assert res.status_code == 403


def test_signup_admin_cannot_self_upgrade_in_mock_mode(monkeypatch):
    from app.routers import billing

    monkeypatch.setattr(billing, "is_mock_mode", lambda: True)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("IS_LOCAL_DEV", raising=False)
    app = FastAPI()
    app.include_router(billing.router)
    user = _user()

    async def _current():
        return user

    async def _session():
        yield _ScopeDB(platform=TENANT_B)

    async def _paid():
        return None

    app.dependency_overrides[get_current_user] = _current
    app.dependency_overrides[get_db] = _session
    app.dependency_overrides[pf.require_monetization] = _paid
    res = TestClient(app).post("/api/billing/checkout", json=_checkout_body())
    assert res.status_code == 409


def test_tmpaudit_is_gone_and_ignored():
    assert not (ROOT / ".tmpaudit").exists()
    assert ".tmpaudit/" in (ROOT / ".gitignore").read_text()


def test_only_a_runtime_token_may_raise_an_action_approval():
    from types import SimpleNamespace

    from app.routers import approvals

    runtime = SimpleNamespace(_runtime_token=True)
    person = SimpleNamespace()
    assert approvals._refused_gate_kind("action:refund", person) is True
    assert approvals._refused_gate_kind("action:refund", runtime) is False
    # the runtime gets no other reserved kind
    assert approvals._refused_gate_kind("autonomy.promote", runtime) is True


@pytest.mark.asyncio
async def test_readiness_runs_one_check_for_a_burst_of_callers(monkeypatch):
    import asyncio

    from app import main

    calls = 0

    async def checks():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {"status": "ok"}

    monkeypatch.setattr(main, "_run_readiness_checks", checks)
    monkeypatch.setattr(main, "_ready_cached", None)
    results = await asyncio.gather(*(main.readiness_check() for _ in range(50)))
    assert calls == 1
    assert all(r == {"status": "ok"} for r in results)
