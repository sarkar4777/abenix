"""Tenant boundaries for database and file tools, code runs, caches, exports and app flows."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.deps import get_current_user, get_db
from engine import credentials, process_sandbox, tenant_access
from engine.tools.base import ToolResult
from engine.tools.code_executor import CodeExecutorTool, _validate_code
from engine.tools.database_query import DatabaseQueryTool
from engine.tools.database_writer import DatabaseWriterTool
from engine.tools.file_reader import FileReaderTool
from engine.tools.file_system import FileSystemTool
from models.user import UserRole

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = "11111111-1111-1111-1111-111111111111"
SIGNUP = "22222222-2222-2222-2222-222222222222"
OTHER = "33333333-3333-3333-3333-333333333333"
PLATFORM_DSN = "postgresql://abenix:pw@db.internal:5432/abenix"
APPS = (
    "industrial-iot",
    "contractiq",
    "wingman",
    "pharmavigil",
    "resolveai",
    "mideasttourism",
    "claimsiq",
)


@pytest.fixture
def access(monkeypatch):
    async def platform():
        return PLATFORM

    monkeypatch.setattr(tenant_access, "platform_tenant_id", platform)
    monkeypatch.setattr(tenant_access, "_dsn", lambda: PLATFORM_DSN)
    monkeypatch.delenv("CONNECTORS_ALLOW_PRIVATE_TARGETS", raising=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tenant,agent,allowed",
    [
        (PLATFORM, "", True),
        (PLATFORM, "seeded", True),
        (SIGNUP, "seeded", False),
        (SIGNUP, "planted", False),
        (SIGNUP, "", False),
        ("", "", False),
    ],
)
async def test_only_runs_in_the_platform_tenant_get_the_platform_db(
    access, tenant, agent, allowed
):
    tool = DatabaseQueryTool(tenant_id=tenant, agent_id=agent)
    url, refused = await tenant_access.resolve_connection(tool, "")
    assert (url == PLATFORM_DSN) is allowed
    assert (refused is None) is allowed


@pytest.mark.asyncio
async def test_a_tenant_agent_cannot_query_with_no_database_configured(access):
    res = await DatabaseQueryTool(tenant_id=SIGNUP, agent_id="planted").execute(
        {"query": "select email from users"}
    )
    assert res.is_error and "No database is configured" in res.content


@pytest.mark.asyncio
async def test_a_tenant_agent_cannot_write_to_the_platform_db(access):
    res = await DatabaseWriterTool(tenant_id=SIGNUP, agent_id="planted").execute(
        {"operation": "insert", "table": "af_x", "rows": [{"a": 1}]}
    )
    assert res.is_error and "No database is configured" in res.content


@pytest.mark.asyncio
async def test_a_tenant_configured_database_is_used(access, monkeypatch):
    public = "postgresql://u:p@db.example.com:5432/app"

    async def public_ip(_host, _port):
        return ["93.184.216.34"]

    monkeypatch.setattr("engine.url_guard._resolve", public_ip)
    monkeypatch.setitem(
        credentials._tenant_snapshot, (SIGNUP, tenant_access.TENANT_DB_KEY), public
    )
    tool = DatabaseQueryTool(tenant_id=SIGNUP, agent_id="planted")
    assert await tenant_access.resolve_connection(tool, "") == (public, None)


@pytest.mark.asyncio
async def test_connection_string_needs_the_tool_config(access):
    tool = DatabaseQueryTool(tenant_id=SIGNUP)
    _url, refused = await tenant_access.resolve_connection(
        tool, "postgresql://u:p@93.184.216.34/db"
    )
    assert refused and tenant_access.ALLOW_CONNECTION_ARG_KEY in refused


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@127.0.0.1/db",
        "postgresql://u:p@169.254.169.254/db",
        "postgresql://u:p@abenix-postgresql.default.svc.cluster.local/db",
        "postgresql://u:p@localhost/db",
        "mysql://u:p@93.184.216.34/db",
    ],
)
async def test_connection_string_must_pass_the_private_target_guard(access, url):
    tool = DatabaseQueryTool(tenant_id=SIGNUP)
    with credentials.override({tenant_access.ALLOW_CONNECTION_ARG_KEY: "true"}):
        _url, refused = await tenant_access.resolve_connection(tool, url)
    assert refused


@pytest.mark.asyncio
async def test_connection_string_cannot_name_the_platform_db(access, monkeypatch):
    monkeypatch.setenv("CONNECTORS_ALLOW_PRIVATE_TARGETS", "1")
    tool = DatabaseQueryTool(tenant_id=SIGNUP)
    with credentials.override({tenant_access.ALLOW_CONNECTION_ARG_KEY: "true"}):
        _url, refused = await tenant_access.resolve_connection(tool, PLATFORM_DSN)
    assert refused and "platform database" in refused


@pytest.fixture
def jail(tmp_path, monkeypatch, access):
    from engine.storage import service

    uploads = tmp_path / "uploads"
    monkeypatch.setattr(service, "STORAGE_LOCAL_DIR", str(uploads))
    monkeypatch.setenv("UPLOAD_DIR", str(uploads))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    mine = uploads / SIGNUP
    theirs = uploads / OTHER
    mine.mkdir(parents=True)
    theirs.mkdir(parents=True)
    (mine / "note.txt").write_text("mine")
    (theirs / "secret.txt").write_text("theirs")
    (tmp_path / "outside.txt").write_text("outside")
    (mine / "to_other.txt").symlink_to(theirs / "secret.txt")
    (mine / "to_outside").symlink_to(tmp_path)
    token = credentials.set_tenant(SIGNUP)
    yield SimpleNamespace(mine=mine, theirs=theirs, tmp=tmp_path)
    credentials.reset_tenant(token)


def _forbidden_paths(jail):
    return [
        jail.theirs / "secret.txt",
        jail.tmp / "outside.txt",
        jail.mine / "to_other.txt",
        jail.mine / "to_outside" / "outside.txt",
        jail.mine / ".." / OTHER / "secret.txt",
        jail.mine / ".." / ".." / "outside.txt",
        Path("/etc/passwd"),
    ]


@pytest.mark.asyncio
async def test_file_reader_stays_in_the_tenant_folder(jail):
    ok = await FileReaderTool().execute({"file_path": str(jail.mine / "note.txt")})
    assert not ok.is_error and ok.content == "mine"
    for path in _forbidden_paths(jail):
        res = await FileReaderTool().execute({"file_path": str(path)})
        assert res.is_error and "outside this tenant" in res.content, path


@pytest.mark.asyncio
async def test_file_system_stays_in_the_tenant_folder(jail):
    tool = FileSystemTool()
    ok = await tool.execute(
        {"operation": "read_file", "path": str(jail.mine / "note.txt")}
    )
    assert not ok.is_error
    for path in _forbidden_paths(jail):
        res = await tool.execute({"operation": "read_file", "path": str(path)})
        assert res.is_error and "outside this tenant" in res.content, path
    for op in ("list_recursive", "glob", "stat"):
        res = await tool.execute({"operation": op, "path": str(jail.theirs)})
        assert res.is_error and "outside this tenant" in res.content


@pytest.mark.asyncio
async def test_file_tools_refuse_a_run_with_no_tenant(tmp_path):
    token = credentials.set_tenant("")
    try:
        target = tmp_path / "x.txt"
        target.write_text("x")
        res = await FileReaderTool().execute({"file_path": str(target)})
    finally:
        credentials.reset_tenant(token)
    assert res.is_error and "needs a tenant" in res.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module,cls,args",
    [
        ("document_parser", "DocumentParserTool", {"file_path": "{p}"}),
        ("spreadsheet_analyzer", "SpreadsheetAnalyzerTool", {"file_path": "{p}"}),
        ("presentation_analyzer", "PresentationAnalyzerTool", {"file_path": "{p}"}),
        ("csv_analyzer", "CsvAnalyzerTool", {"file_path": "{p}"}),
        ("document_extractor", "DocumentExtractorTool", {"file_path": "{p}"}),
    ],
)
async def test_other_path_tools_stay_in_the_tenant_folder(jail, module, cls, args):
    import importlib

    tool = getattr(importlib.import_module(f"engine.tools.{module}"), cls)()
    target = str(jail.theirs / "secret.txt")
    filled = {k: v.format(p=target) for k, v in args.items()}
    res = await tool.execute(filled)
    assert res.is_error and "outside this tenant" in res.content


@pytest.mark.asyncio
async def test_platform_tenant_keeps_its_configured_upload_root(
    jail, monkeypatch, tmp_path
):
    kyc = tmp_path / "kyc"
    kyc.mkdir()
    pdf = kyc / "a.txt"
    pdf.write_text("x")
    monkeypatch.setenv("KYC_UPLOAD_DIR", str(kyc))
    assert await tenant_access.path_refusal(pdf) is not None
    token = credentials.set_tenant(PLATFORM)
    try:
        assert await tenant_access.path_refusal(pdf) is None
    finally:
        credentials.reset_tenant(token)


@pytest.fixture
def run_code(tmp_path, monkeypatch, access):
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@db/x")
    token = credentials.set_tenant(SIGNUP)
    tool = CodeExecutorTool()

    async def go(code, **extra):
        return await tool.execute({"code": code, **extra})

    yield go
    credentials.reset_tenant(token)


@pytest.mark.asyncio
async def test_code_runs_in_another_process_with_no_secrets(run_code):
    res = await run_code("import json\nresult = {'ok': json.dumps(1)}")
    assert not res.is_error and res.metadata["isolation"] == "process"
    assert "must-not-leak" not in res.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bypass",
    [
        "import builtins",
        "open('/etc/passwd').read()",
        "import pandas\npandas.read_csv('/etc/passwd')",
        "import gzip\ngzip.open('/etc/passwd').read()",
        "import pandas\nresult = pandas.DataFrame({'a': [1]}).to_csv('/tmp/../etc/x')",
    ],
)
async def test_escapes_fail_in_the_subprocess(run_code, bypass):
    res = await run_code(bypass)
    assert res.is_error or "root:" not in res.content
    assert "root:" not in res.content


CHILD_ESCAPES = {
    "subprocess": "import subprocess\nsubprocess.run(['id'])",
    "os_system": "import os\nos.system('id')",
    "socket": "import socket\nsocket.create_connection(('127.0.0.1', 9))",
    "ctypes_libc": "import ctypes\nctypes.CDLL(None).getpid()",
    "ctypes_load": "import ctypes\nctypes.cdll.LoadLibrary('libc.dylib')",
    "secret_read": "import io\nio.open('{secret}').read()",
    "other_write": "import io\nio.open('{outside}', 'w').write('x')",
}


@pytest.mark.parametrize("name", sorted(CHILD_ESCAPES))
def test_child_stops_what_gets_past_the_validator(tmp_path, name):
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    code = CHILD_ESCAPES[name].format(secret=secret, outside=tmp_path / "out.txt")
    request = process_sandbox.code_request(
        code,
        {},
        ["subprocess", "os", "socket", "ctypes", "io"],
        str(tmp_path / "exp"),
        [],
        20,
    )
    with pytest.raises(process_sandbox.SandboxError, match="not allowed|Permission"):
        process_sandbox.run_code(request)
    assert not (tmp_path / "out.txt").exists()


def test_child_has_no_secrets_in_its_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")
    request = process_sandbox.code_request(
        "import os\nresult = sorted(os.environ)",
        {},
        ["os"],
        str(tmp_path / "exp"),
        [],
        20,
    )
    keys = json.loads(process_sandbox.run_code(request)["result"])
    assert "AWS_SECRET_ACCESS_KEY" not in keys and "DATABASE_URL" not in keys


def test_child_stops_at_the_wall_clock(tmp_path):
    request = process_sandbox.code_request(
        "while True:\n    pass", {}, [], str(tmp_path / "exp"), [], 1
    )
    with pytest.raises(process_sandbox.SandboxError):
        process_sandbox.run_code(request)


def test_model_subprocess_blocks_ctypes(tmp_path):
    import pickle

    class UsesLibc:
        def __reduce__(self):
            return (
                eval,
                ("__import__('ctypes').CDLL(None)",),
            )

    path = tmp_path / "evil.pkl"
    path.write_bytes(pickle.dumps(UsesLibc()))
    with pytest.raises(process_sandbox.SandboxError, match="ctypes"):
        process_sandbox.run_isolated("validate", str(path), "sklearn")


def test_kmeans_model_still_predicts_with_ctypes_blocked(tmp_path):
    import joblib
    from sklearn.cluster import KMeans

    model = KMeans(n_clusters=2, n_init=1, random_state=0).fit(
        [[0.0, 0.0], [0.1, 0.1], [5.0, 5.0], [5.1, 5.1]]
    )
    path = tmp_path / "km.joblib"
    joblib.dump(model, path)
    out = process_sandbox.run_isolated("predict", str(path), "sklearn", [[0.0, 0.1]])
    assert len(out["predictions"]) == 1


@pytest.mark.asyncio
async def test_data_libraries_still_work_and_exports_land_in_the_tenant_folder(
    run_code, tmp_path
):
    res = await run_code(
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': [1, 2, 3]})\n"
        "path = save_export('sum.txt', str(int(df['a'].sum())))\n"
        "result = {'total': int(df['a'].sum())}"
    )
    assert not res.is_error, res.content
    assert json.loads(res.content) == {"total": 6}
    assert (tmp_path / "exports" / SIGNUP / "sum.txt").read_text() == "6"


@pytest.mark.asyncio
async def test_code_uses_the_sandboxed_job_when_enabled(
    run_code, monkeypatch, tmp_path
):
    from engine.tools import sandboxed_job

    calls = []

    async def settings(self):
        return {"enabled": True, "allowed_images": {"py:1"}, "allow_network": False}

    async def fake_execute(self, arguments):
        import base64

        calls.append(arguments)
        assert arguments["network"] is False
        reply = {
            "stdout": "from the job\n",
            "result": "1",
            "exports": [
                {"name": "out.txt", "b64": base64.b64encode(b"job file").decode()}
            ],
        }
        return ToolResult(
            content="ok", metadata={"logs": "noise\n" + json.dumps({"result": reply})}
        )

    monkeypatch.setattr(sandboxed_job.SandboxedJobTool, "_resolve_settings", settings)
    monkeypatch.setattr(sandboxed_job.SandboxedJobTool, "execute", fake_execute)
    with credentials.override({"CODE_EXECUTOR_SANDBOX_IMAGE": "py:1"}):
        res = await run_code("result = 1")
    assert calls and res.metadata["isolation"] == "job"
    assert (tmp_path / "exports" / SIGNUP / "out.txt").read_bytes() == b"job file"


@pytest.mark.asyncio
async def test_code_falls_back_to_a_process_when_the_job_is_off(run_code, monkeypatch):
    from engine.tools import sandboxed_job

    async def settings(self):
        return {"enabled": False, "allowed_images": set(), "allow_network": False}

    monkeypatch.setattr(sandboxed_job.SandboxedJobTool, "_resolve_settings", settings)
    with credentials.override({"CODE_EXECUTOR_SANDBOX_IMAGE": "py:1"}):
        res = await run_code("result = 1")
    assert res.metadata["isolation"] == "process"


def _user(role=UserRole.ADMIN, tenant=SIGNUP, email="a@example.com"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant),
        role=role,
        email=email,
        is_admin=False,
    )


class _Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)


class _DB:
    def __init__(self, platform=PLATFORM, rows=()):
        self.platform = platform
        self.rows = rows
        self.statements = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.statements.append(sql)
        if "FROM users WHERE lower(email)" in sql:
            return _Result([(uuid.UUID(self.platform),)])
        return _Result(self.rows)


def _client(router, user, db) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    async def _current():
        return user

    async def _session():
        yield db

    app.dependency_overrides[get_current_user] = _current
    app.dependency_overrides[get_db] = _session
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def exports(tmp_path, monkeypatch):
    from engine.storage import service

    monkeypatch.setenv("EXPORT_DIR", str(tmp_path))
    monkeypatch.setattr(service, "STORAGE_BACKEND", "local")
    for tenant, text in ((SIGNUP, "mine"), (OTHER, "theirs")):
        (tmp_path / tenant).mkdir()
        (tmp_path / tenant / f"{text}.csv").write_text(text)
    (tmp_path / "legacy.csv").write_text("legacy")
    return tmp_path


def test_export_download_is_per_tenant(exports):
    from app.routers import files

    client = _client(files.router, _user(), _DB())
    assert client.get("/api/files/export/mine.csv").text == "mine"
    assert client.get("/api/files/export/theirs.csv").status_code == 404
    assert client.get("/api/files/export/legacy.csv").status_code == 404


def test_platform_tenant_can_still_read_old_flat_exports(exports):
    from app.routers import files

    client = _client(files.router, _user(tenant=PLATFORM), _DB())
    assert client.get("/api/files/export/legacy.csv").text == "legacy"
    assert client.get("/api/files/export/theirs.csv").status_code == 404


def test_tool_cache_key_includes_the_tenant_unless_public():
    from app.core.tool_gate import PUBLIC_DATA_TOOLS, _cache_key

    assert _cache_key("ml_model", "t1", "h", "global") != _cache_key(
        "ml_model", "t2", "h", "global"
    )
    for slug in PUBLIC_DATA_TOOLS:
        assert _cache_key(slug, "t1", "h", "global") == _cache_key(
            slug, "t2", "h", "global"
        )
        assert _cache_key(slug, "t1", "h", "per_tenant") != _cache_key(
            slug, "t2", "h", "per_tenant"
        )


def _request(headers):
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host="9.9.9.9"))


@pytest.mark.asyncio
async def test_each_api_key_gets_its_own_bucket(monkeypatch):
    from app.core import rate_limit

    buckets = []

    async def window(key, limit, window_seconds):
        buckets.append(key)
        return True, limit, 0

    known = {}

    async def fake_lookup(key_hash):
        return known.get(key_hash)

    import hashlib

    known[hashlib.sha256(b"af_one").hexdigest()] = "key-1"
    known[hashlib.sha256(b"af_two").hexdigest()] = "key-2"
    monkeypatch.setattr(rate_limit, "sliding_window_check", window)
    monkeypatch.setattr(rate_limit, "_lookup_api_key_id", fake_lookup)
    monkeypatch.setattr(rate_limit, "_is_dev_bypass", lambda _r: False)
    monkeypatch.setattr(rate_limit, "_API_KEY_IDS", {})

    await rate_limit.rate_limit_user(_request({"x-api-key": "af_one"}))
    await rate_limit.rate_limit_user(_request({"authorization": "Bearer af_two"}))
    await rate_limit.rate_limit_user(_request({"x-api-key": "af_made_up"}))
    assert buckets == ["apikey:key-1", "apikey:key-2", "ip:9.9.9.9"]


def test_key_report_lists_sensitive_keys_and_changes_nothing():
    from app.routers import admin_api_key_report as report
    from models.api_key import ApiKey

    def key(name, scopes):
        return (
            ApiKey(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(SIGNUP),
                user_id=uuid.uuid4(),
                name=name,
                key_hash=name,
                key_prefix="af_",
                scopes=scopes,
            ),
            "owner@example.com",
        )

    rows = [
        key("app", {"allowed_actions": ["can_delegate", "execute"]}),
        key("bool", {"can_delegate": True}),
        key("cmd", ["telemetry.command"]),
        key("plain", {"allowed_actions": ["read"]}),
        key("none", None),
    ]
    db = _DB(rows=rows)
    body = _client(report.router, _user(), db).get("/api/admin/api-keys/privileged")
    data = body.json()["data"]
    assert {k["name"] for k in data["keys"]} == {"app", "bool", "cmd"}
    assert data["keys"][0]["created_by"] == "owner@example.com"
    assert "api_keys.tenant_id" in db.statements[-1]
    assert not any(s.split()[0] in ("UPDATE", "DELETE") for s in db.statements)


@pytest.mark.asyncio
async def test_playground_uses_the_job_when_one_can_take_it(monkeypatch):
    from app.core import playground_access as pa
    from engine.tools import sandboxed_job

    async def settings(self):
        return {
            "enabled": True,
            "allowed_images": {"pg:1"},
            "allow_network": True,
        }

    monkeypatch.setattr(sandboxed_job.SandboxedJobTool, "_resolve_settings", settings)
    monkeypatch.setenv(pa.SANDBOX_IMAGE_ENV, "pg:1")
    assert await pa.sandbox_image(SIGNUP) == "pg:1"

    async def no_network(self):
        return {"enabled": True, "allowed_images": {"pg:1"}, "allow_network": False}

    monkeypatch.setattr(sandboxed_job.SandboxedJobTool, "_resolve_settings", no_network)
    assert await pa.sandbox_image(SIGNUP) == ""


@pytest.mark.asyncio
async def test_playground_stays_gated_with_no_job_outside_dev(monkeypatch):
    from app.core import playground_access as pa

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("IS_LOCAL_DEV", raising=False)
    monkeypatch.delenv(pa.ENABLE_ENV, raising=False)
    monkeypatch.delenv(pa.SANDBOX_IMAGE_ENV, raising=False)
    assert await pa.playground_denial(None, _user()) == pa.DISABLED_MESSAGE


def _seeds():
    for path in sorted((ROOT / "packages/db/seeds/agents").glob("*.yaml")):
        yield path, yaml.safe_load(path.read_text())


def _walk(value):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


def test_seeded_code_still_passes_the_stricter_validator():
    from engine.tools.code_executor import ALLOWED_MODULES

    bad = []
    for path, data in _seeds():
        for node in _walk(data):
            code = node.get("code")
            if isinstance(code, str) and code.strip():
                filled = re.sub(r"\{\{.*?\}\}", "0", code)
                problems = [
                    p
                    for p in _validate_code(filled, set(ALLOWED_MODULES))
                    if "Syntax" not in p
                ]
                if problems:
                    bad.append((path.name, problems))
    assert bad == []


def test_no_seed_or_app_passes_a_connection_string():
    hits = []
    for _path, data in _seeds():
        for node in _walk(data):
            if "connection_string" in node:
                hits.append(_path.name)
    assert hits == []


def test_seeded_http_nodes_call_no_internal_address():
    from engine.url_guard import static_reason

    bad = []
    for path, data in _seeds():
        for node in _walk(data):
            url = node.get("url")
            if (
                isinstance(url, str)
                and url.startswith("http")
                and "{{" not in url
                and static_reason(url)
            ):
                bad.append((path.name, url))
    assert bad == []


def _app_python(app):
    for path in (ROOT / app).rglob("*.py"):
        parts = set(path.parts)
        if parts & {"node_modules", "sdk", "tests", "e2e", "__pycache__", ".next"}:
            continue
        yield path, path.read_text(encoding="utf-8", errors="ignore")


@pytest.mark.parametrize("app", APPS)
def test_apps_call_nothing_a_platform_key_would_lose(app):
    from app.core.tool_access import OPERATOR_ONLY_TOOLS

    wrote_private = []
    for path, text in _app_python(app):
        for slug in re.findall(r"tools\.execute\(\s*[\"']([a-z_]+)[\"']", text):
            wrote_private.append((path.name, slug, slug in OPERATOR_ONLY_TOOLS))
        assert "/api/admin/" not in text or path.name.startswith(
            ("test_", "seed")
        ), path
    assert all(s[2] is False for s in wrote_private), wrote_private


def test_app_keys_are_minted_for_the_platform_admin():
    source = (ROOT / "scripts/seed-standalone-keys.sh").read_text()
    assert "admin@abenix.dev" in source and "can_delegate" in source


@pytest.mark.asyncio
async def test_platform_admin_passes_every_gate_an_app_key_meets(monkeypatch):
    from app.core import platform_features as pf
    from app.core import capabilities
    from app.core.playground_access import PLAYGROUND_EXECUTE
    from app.core.tool_access import OPERATOR_ONLY_TOOLS, TOOLS_EXECUTE, tool_denial
    from app.routers.api_keys import _scope_refusal

    monkeypatch.setattr(capabilities, "_cache", {})
    monkeypatch.delenv("ABENIX_PLATFORM_OPERATORS", raising=False)

    class DB(_DB):
        async def execute(self, stmt, params=None):
            sql = str(stmt)
            if "FROM users WHERE lower(email)" in sql:
                return _Result([(uuid.UUID(PLATFORM),)])
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: []),
                all=lambda: [],
                first=lambda: None,
            )

    admin = _user(tenant=PLATFORM, email="admin@abenix.dev")
    assert await pf.is_platform_operator(DB(), admin)
    for cap in (TOOLS_EXECUTE, PLAYGROUND_EXECUTE, "ml_models.upload_pickle"):
        assert await capabilities.has_capability(DB(), admin, cap)
    for slug in ("country_risk_index", "code_asset", "ml_model", *OPERATOR_ONLY_TOOLS):
        assert await tool_denial(DB(), admin, slug) is None
    assert await _scope_refusal(DB(), admin, {"can_delegate": True}, set()) is None


def test_seeded_database_writer_columns_pass_the_identifier_check():
    from engine.tools.database_writer import _bad_identifier

    for _path, data in _seeds():
        for node in _walk(data):
            if node.get("tool") == "database_writer" and isinstance(
                node.get("input"), dict
            ):
                table = node["input"].get("table")
                if isinstance(table, str) and "{{" not in table:
                    assert _bad_identifier(table) is None, table


def test_process_sandbox_file_runs_by_path_alone():
    assert os.path.isfile(process_sandbox.__file__)
    source = Path(process_sandbox.__file__).read_text()
    assert "from engine" not in source and "import engine" not in source
