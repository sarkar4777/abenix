"""ml_model_register publishes a model file from the run through the registry, as the caller."""

from __future__ import annotations

import base64
import json
import uuid

import httpx
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from engine import autonomy
from engine.tools import code_executor, data_exporter
from engine.tools import ml_model_register as reg
from engine.tools.ml_model_register import MLModelRegisterTool

TENANT = str(uuid.uuid4())
USER = str(uuid.uuid4())
MODEL = str(uuid.uuid4())
_REAL_CLIENT = httpx.AsyncClient

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
PUBLIC_PEM = (
    _KEY.public_key()
    .public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    .decode()
)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("JWT_ALGORITHM", "RS256")
    monkeypatch.setenv("JWT_PRIVATE_KEY", PRIVATE_PEM)
    exports = tmp_path / "exports"
    exports.mkdir()
    # a run reads only its own workspace folder
    (exports / TENANT).mkdir()
    monkeypatch.setattr(code_executor, "EXPORT_DIR", str(exports))
    monkeypatch.setattr(data_exporter, "EXPORT_DIR", str(exports))
    return exports


@pytest_asyncio.fixture(autouse=True)
async def _ledger_writes_finish():
    # the medium tier call queues ledger writes on this test's loop
    yield
    await autonomy.flush()


def _install(monkeypatch, status=201, body=None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if body is not None:
            return httpx.Response(status, json=body)
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": MODEL,
                    "name": "churn",
                    "version": "1.1.0",
                    "framework": "sklearn",
                    "status": "ready",
                    "is_active": True,
                    "input_schema": {"features": ["a", "b"]},
                    "output_schema": None,
                }
            },
        )

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_CLIENT(*args, **kwargs)

    monkeypatch.setattr(reg.httpx, "AsyncClient", factory)
    return seen


def _parts(req: httpx.Request) -> tuple[dict, bytes, str]:
    boundary = req.headers["content-type"].split("boundary=", 1)[1].encode()
    meta, content, fname = {}, b"", ""
    for part in req.content.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, data = part.split(b"\r\n\r\n", 1)
        data = data.rsplit(b"\r\n", 1)[0]
        if b'name="metadata"' in head:
            meta = json.loads(data)
        elif b'name="file"' in head:
            content = data
            fname = head.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
    return meta, content, fname


def _tool(**kw):
    base = dict(
        tenant_id=TENANT,
        execution_id=str(uuid.uuid4()),
        user_id=USER,
        user_role="creator",
        api_base="http://api.test",
    )
    base.update(kw)
    return MLModelRegisterTool(**base)


@pytest.mark.asyncio
async def test_registers_an_exported_file_as_the_caller(monkeypatch, _env):
    (_env / TENANT / "churn.joblib").write_bytes(b"model-bytes")
    seen = _install(monkeypatch)
    res = await _tool().execute(
        {
            "model_name": "churn",
            "file_path": "churn.joblib",
            "feature_names": ["a", "b"],
            "description": "Weekly retrain",
            "tags": ["groundwork"],
        }
    )
    assert not res.is_error, res.content
    out = json.loads(res.content)
    assert out["model_id"] == MODEL and out["version"] == "1.1.0"
    assert res.metadata["model_name"] == "churn"
    req = seen[0]
    assert req.url.path == "/api/ml-models"
    claims = jwt.decode(
        req.headers["authorization"].split(" ", 1)[1], PUBLIC_PEM, algorithms=["RS256"]
    )
    assert claims["sub"] == USER and claims["tenant_id"] == TENANT
    meta, content, fname = _parts(req)
    assert content == b"model-bytes" and fname == "churn.joblib"
    assert meta["name"] == "churn" and meta["tags"] == ["groundwork"]
    assert meta["input_schema"]["features"] == ["a", "b"]
    assert meta["input_schema"]["properties"]["input_data"]["x-feature-order"] == [
        "a",
        "b",
    ]


@pytest.mark.asyncio
async def test_absolute_path_inside_the_export_folder(monkeypatch, _env):
    f = _env / TENANT / "sub" / "m.onnx"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"onnx")
    seen = _install(monkeypatch)
    res = await _tool().execute({"model_name": "m", "file_path": str(f)})
    assert not res.is_error, res.content
    assert _parts(seen[0])[2] == "m.onnx"


@pytest.mark.asyncio
async def test_paths_outside_the_export_folder_are_refused(monkeypatch, _env, tmp_path):
    secret = tmp_path / "secret.pkl"
    secret.write_bytes(b"x")
    seen = _install(monkeypatch)
    for path in (str(secret), "../secret.pkl", str(_env), "missing.pkl"):
        res = await _tool().execute({"model_name": "m", "file_path": path})
        assert res.is_error and "export folder" in res.content, path
    assert seen == []


@pytest.mark.asyncio
async def test_base64_with_framework_or_filename(monkeypatch):
    seen = _install(monkeypatch)
    b64 = base64.b64encode(b"model-bytes").decode()
    res = await _tool().execute(
        {"model_name": "churn", "file_base64": b64, "framework": "xgboost"}
    )
    assert not res.is_error, res.content
    meta, content, fname = _parts(seen[0])
    assert content == b"model-bytes" and fname == "churn.joblib"
    assert meta["framework"] == "xgboost"

    res = await _tool().execute(
        {
            "model_name": "churn",
            "file_base64": "data:application/octet-stream;base64," + b64,
            "filename": "c.pkl",
        }
    )
    assert not res.is_error
    assert _parts(seen[1])[1:] == (b"model-bytes", "c.pkl")


@pytest.mark.asyncio
async def test_bad_inputs_never_reach_the_registry(monkeypatch, _env):
    (_env / TENANT / "m.pkl").write_bytes(b"x")
    seen = _install(monkeypatch)
    cases = [
        ({"file_path": "m.pkl"}, "model_name is required"),
        ({"model_name": "m"}, "one of the two"),
        (
            {"model_name": "m", "file_path": "m.pkl", "file_base64": "eA=="},
            "one of the two",
        ),
        ({"model_name": "m", "file_base64": "not base64!"}, "not valid base64"),
        ({"model_name": "m", "file_base64": "eA=="}, "filename"),
        (
            {"model_name": "m", "file_path": "m.pkl", "input_schema": "x"},
            "JSON object",
        ),
    ]
    for args, msg in cases:
        res = await _tool().execute(args)
        assert res.is_error and msg in res.content, (args, res.content)
    assert seen == []


@pytest.mark.asyncio
async def test_no_caller_no_registration(monkeypatch, _env):
    (_env / TENANT / "m.pkl").write_bytes(b"x")
    seen = _install(monkeypatch)
    res = await _tool(user_id="").execute({"model_name": "m", "file_path": "m.pkl"})
    assert res.is_error and "owner" in res.content
    monkeypatch.setattr("engine.tools.invoke_agent.mint_user_token", lambda *a, **k: "")
    res = await _tool().execute({"model_name": "m", "file_path": "m.pkl"})
    assert res.is_error and "Could not sign" in res.content
    assert seen == []


@pytest.mark.asyncio
async def test_load_failure_is_reported_with_the_stored_version(monkeypatch, _env):
    (_env / TENANT / "m.pkl").write_bytes(b"not a model")
    _install(
        monkeypatch,
        status=422,
        body={
            "data": None,
            "error": {
                "message": "The file is not a pickled model.",
                "error_code": "MODEL_LOAD_FAILED",
                "details": {"model": {"version": "1.2.0", "status": "error"}},
            },
        },
    )
    res = await _tool().execute({"model_name": "m", "file_path": "m.pkl"})
    assert res.is_error
    assert "did not load" in res.content and "1.2.0" in res.content
    assert res.metadata["failure_code"] == "MODEL_LOAD_FAILED"


@pytest.mark.asyncio
async def test_registry_refusal_passes_the_message_through(monkeypatch, _env):
    (_env / TENANT / "m.pkl").write_bytes(b"x")
    _install(
        monkeypatch,
        status=409,
        body={
            "error": {
                "message": "m already has a version 1.0.0.",
                "error_code": "VERSION_EXISTS",
            }
        },
    )
    res = await _tool().execute(
        {"model_name": "m", "file_path": "m.pkl", "version": "1.0.0"}
    )
    assert res.is_error and res.content == "m already has a version 1.0.0."
    assert res.metadata["status"] == 409


def test_registered_with_the_executor_and_carries_the_caller():
    from engine.agent_executor import build_tool_registry

    registry = build_tool_registry(
        ["ml_model_register"],
        tenant_id=TENANT,
        user_id=USER,
        user_role="creator",
        execution_id="e1",
    )
    tool = registry.get("ml_model_register")
    assert tool is not None
    inner = getattr(tool, "_inner", tool)
    assert inner._user_id == USER and inner.tenant_id == TENANT
    assert MLModelRegisterTool.risk_tier == "medium"
    assert MLModelRegisterTool.effect is not None


@pytest.mark.asyncio
async def test_another_workspaces_export_is_refused(monkeypatch, _env):
    other = _env / "another-tenant"
    other.mkdir()
    (other / "theirs.joblib").write_bytes(b"model-bytes")
    for path in (
        "theirs.joblib",
        "../another-tenant/theirs.joblib",
        str(other / "theirs.joblib"),
    ):
        res = await _tool().execute({"model_name": "m", "file_path": path})
        assert res.is_error, path
