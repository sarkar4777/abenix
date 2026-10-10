"""Python SDK: ML model and code asset uploads, kill switches, API keys and golden test edits."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "packages" / "sdk" / "python")
)

from abenix_sdk import Abenix, AbenixDecisionError, AbenixError  # noqa: E402

MID = "11111111-2222-3333-4444-555555555555"
OLD = "11111111-2222-3333-4444-000000000000"
AID = "aaaaaaaa-2222-3333-4444-555555555555"


def _client(handler) -> tuple[Abenix, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    sdk = Abenix(api_key="af_test", base_url="http://abenix.test")
    sdk._http = httpx.AsyncClient(
        base_url="http://abenix.test",
        headers={"X-API-Key": "af_test"},
        transport=httpx.MockTransport(wrapped),
    )
    sdk.http = sdk._http
    return sdk, seen


def _ok(data, status=200):
    return httpx.Response(status, json={"data": data, "error": None})


def _err(status, message, code=None, details=None):
    return httpx.Response(
        status,
        json={
            "data": None,
            "error": {"message": message, "error_code": code, "details": details},
        },
    )


def _form(req: httpx.Request) -> tuple[dict, bytes, str]:
    """metadata JSON, file bytes and file name out of a multipart body."""
    ctype = req.headers["content-type"]
    boundary = ctype.split("boundary=", 1)[1].encode()
    meta: dict = {}
    content, fname = b"", ""
    for part in req.content.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, body = part.split(b"\r\n\r\n", 1)
        body = body.rsplit(b"\r\n", 1)[0]
        if b'name="metadata"' in head:
            meta = json.loads(body)
        elif b'name="file"' in head:
            content = body
            fname = head.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
    return meta, content, fname


def run(coro):
    return asyncio.run(coro)


def test_ml_upload_sends_metadata_and_file(tmp_path):
    f = tmp_path / "churn.joblib"
    f.write_bytes(b"model-bytes")
    sdk, seen = _client(
        lambda r: _ok({"id": MID, "name": "churn", "is_active": True}, 201)
    )
    out = run(
        sdk.ml_models.upload(
            "churn",
            str(f),
            framework="sklearn",
            version="2.0.0",
            description="Churn risk",
            feature_names=["tenure", "spend"],
            output_schema={"type": "object"},
            tags=["groundwork"],
        )
    )
    assert out["id"] == MID
    req = seen[0]
    assert req.method == "POST" and req.url.path == "/api/ml-models"
    meta, content, fname = _form(req)
    assert content == b"model-bytes" and fname == "churn.joblib"
    assert meta["name"] == "churn" and meta["framework"] == "sklearn"
    assert meta["version"] == "2.0.0" and meta["tags"] == ["groundwork"]
    assert meta["input_schema"]["features"] == ["tenure", "spend"]
    items = meta["input_schema"]["properties"]["input_data"]["items"]
    assert items["minItems"] == 2 and items["maxItems"] == 2
    # a name lookup after upload needs no list call
    run(sdk.ml_models.get("churn"))
    assert seen[-1].url.path == f"/api/ml-models/{MID}"


def test_ml_upload_bytes_need_a_name_or_framework():
    sdk, seen = _client(lambda r: _ok({"id": MID, "is_active": True}, 201))
    with pytest.raises(ValueError):
        run(sdk.ml_models.upload("m", b"raw"))
    assert seen == []
    run(sdk.ml_models.upload("m", b"raw", framework="onnx"))
    assert _form(seen[0])[2] == "m.onnx"


def test_ml_feature_names_merge_into_a_given_schema():
    sdk, seen = _client(lambda r: _ok({"id": MID}, 201))
    run(
        sdk.ml_models.upload(
            "m",
            b"x",
            filename="m.pkl",
            input_schema={"type": "object", "title": "mine"},
            feature_names=["a"],
        )
    )
    meta = _form(seen[0])[0]
    assert meta["input_schema"] == {
        "type": "object",
        "title": "mine",
        "features": ["a"],
    }


def test_ml_load_failure_raises_with_the_stored_row():
    sdk, _ = _client(
        lambda r: _err(
            422,
            "Not a model",
            "MODEL_LOAD_FAILED",
            {"model": {"id": MID, "status": "error"}},
        )
    )
    with pytest.raises(AbenixError) as e:
        run(sdk.ml_models.upload("m", b"x", filename="m.pkl"))
    assert e.value.status == 422 and e.value.code == "MODEL_LOAD_FAILED"
    assert str(e.value) == "Not a model"
    assert e.value.details["model"]["id"] == MID


def test_ml_name_resolves_to_the_active_version():
    rows = [
        {"id": OLD, "name": "churn", "is_active": False},
        {"id": MID, "name": "churn", "is_active": True},
    ]

    def h(r):
        if r.url.path == "/api/ml-models":
            return _ok(rows)
        return _ok({"id": MID})

    sdk, seen = _client(h)
    run(sdk.ml_models.get("churn"))
    assert seen[-1].url.path == f"/api/ml-models/{MID}"
    with pytest.raises(AbenixError) as e:
        run(sdk.ml_models.get("nope"))
    assert e.value.status == 404 and e.value.code == "NOT_FOUND"


def test_ml_delete_one_or_all_versions():
    rows = [
        {"id": MID, "name": "churn", "is_active": True},
        {"id": OLD, "name": "churn", "is_active": False},
    ]

    def h(r):
        if r.method == "GET":
            return _ok(rows)
        return _ok({"deleted": True})

    sdk, seen = _client(h)
    assert run(sdk.ml_models.delete("churn")) == {"deleted": [MID]}
    deletes = [r.url.path for r in seen if r.method == "DELETE"]
    assert deletes == [f"/api/ml-models/{MID}"]
    seen.clear()
    assert run(sdk.ml_models.delete("churn", all_versions=True)) == {
        "deleted": [MID, OLD]
    }
    assert [r.url.path for r in seen if r.method == "DELETE"] == [
        f"/api/ml-models/{MID}",
        f"/api/ml-models/{OLD}",
    ]


def test_ml_predict_raises_abenix_error():
    sdk, _ = _client(lambda r: _err(422, "This model expects 2 features, you sent 3."))
    with pytest.raises(AbenixError) as e:
        run(sdk.ml_models.predict(MID, [[1, 2, 3]]))
    assert "expects 2 features" in str(e.value)


def test_code_asset_create_zips_a_folder(tmp_path):
    (tmp_path / "main.py").write_text("print('hi')")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "util.py").write_text("X = 1")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.pyc").write_bytes(b"\0")
    sdk, seen = _client(lambda r: _ok({"id": AID, "status": "ready"}, 201))
    out = run(sdk.code_assets.create("scorer", tmp_path, description="Scores rows"))
    assert out["status"] == "ready"
    meta, content, fname = _form(seen[0])
    assert seen[0].url.path == "/api/code-assets"
    assert meta == {"name": "scorer", "description": "Scores rows"}
    assert fname.endswith(".zip")
    names = sorted(zipfile.ZipFile(io.BytesIO(content)).namelist())
    assert names == ["main.py", "pkg/util.py"]


def test_code_asset_from_git_and_from_bytes():
    sdk, seen = _client(lambda r: _ok({"id": AID}, 201))
    run(sdk.code_assets.create("s", git_url="https://github.com/a/b", git_ref="main"))
    meta, content, _ = _form(seen[0])
    assert meta["git_url"] == "https://github.com/a/b" and meta["git_ref"] == "main"
    assert content == b""
    run(sdk.code_assets.create("s", b"PK\x03\x04zip"))
    assert _form(seen[1])[1:] == (b"PK\x03\x04zip", "code.zip")
    with pytest.raises(ValueError):
        run(sdk.code_assets.create("s"))


def test_code_asset_new_version_by_name_and_refusal(tmp_path):
    archive = tmp_path / "v2.tar.gz"
    archive.write_bytes(b"\x1f\x8bgz")

    def h(r):
        if r.method == "GET":
            return _ok([{"id": AID, "name": "scorer"}])
        return _err(422, "Version not applied, version 1 is still live. no entrypoint")

    sdk, seen = _client(h)
    with pytest.raises(AbenixError) as e:
        run(sdk.code_assets.new_version("scorer", archive))
    assert e.value.status == 422 and "still live" in str(e.value)
    post = seen[-1]
    assert post.url.path == f"/api/code-assets/{AID}/versions"
    assert _form(post)[1:] == (b"\x1f\x8bgz", "v2.tar.gz")


def test_code_asset_get_by_id():
    sdk, seen = _client(lambda r: _ok({"id": AID}))
    run(sdk.code_assets.get(AID))
    assert len(seen) == 1 and seen[0].url.path == f"/api/code-assets/{AID}"


def test_kill_switches():
    def h(r):
        if r.method == "GET":
            return _ok(
                {"switches": [{"id": "k1", "scope": "agent"}], "scopes": ["all"]}
            )
        return _ok({"id": "k1", "active": r.url.path.endswith("/clear") is False}, 201)

    sdk, seen = _client(h)
    assert run(sdk.kill_switches.list()) == [{"id": "k1", "scope": "agent"}]
    assert "include_cleared" not in str(seen[0].url)
    run(sdk.kill_switches.list(include_cleared=True))
    assert seen[1].url.params["include_cleared"] == "true"
    run(sdk.kill_switches.set("agent", "groundwork-trainer", "Bad outputs"))
    assert json.loads(seen[2].content) == {
        "scope": "agent",
        "target": "groundwork-trainer",
        "reason": "Bad outputs",
    }
    run(sdk.kill_switches.clear("k1"))
    assert seen[3].method == "POST"
    assert seen[3].url.path == "/api/governance/kill-switches/k1/clear"


def test_kill_switch_refusal_is_readable():
    sdk, _ = _client(lambda r: _err(403, "This needs the killswitch.manage capability"))
    with pytest.raises(AbenixError) as e:
        run(sdk.kill_switches.set("all", "*", "Incident"))
    assert e.value.status == 403 and "killswitch.manage" in str(e.value)


def test_api_keys():
    sdk, seen = _client(lambda r: _ok({"id": "k", "raw_key": "af_x"}, 201))
    out = run(
        sdk.api_keys.create("groundwork", ["can_delegate"], max_monthly_tokens=1000)
    )
    assert out["raw_key"] == "af_x"
    assert json.loads(seen[0].content) == {
        "name": "groundwork",
        "scopes": {"allowed_actions": ["can_delegate"]},
        "max_monthly_tokens": 1000,
    }
    run(sdk.api_keys.create("plain"))
    assert json.loads(seen[1].content) == {"name": "plain", "scopes": None}
    with pytest.raises(ValueError):
        run(sdk.api_keys.create("bad", {"admin": True}))
    run(sdk.api_keys.revoke("k"))
    assert seen[2].method == "DELETE" and seen[2].url.path == "/api/api-keys/k"
    run(sdk.api_keys.list())
    assert seen[3].method == "GET" and seen[3].url.path == "/api/api-keys"


def test_add_test_sends_match():
    sdk, seen = _client(lambda r: _ok({"id": "t1"}, 201))
    run(
        sdk.decisions.add_test(
            "k", "gold", {"a": 1}, expected={"tier": "gold"}, match="subset"
        )
    )
    assert json.loads(seen[0].content)["match"] == "subset"
    run(sdk.decisions.add_test("k", "gold", {"a": 1}))
    assert json.loads(seen[1].content)["match"] == "exact"


def test_update_test_merges_over_the_current_test():
    current = {
        "id": "t1",
        "name": "gold",
        "facts": {"a": 1},
        "expected_outcome": "decided",
        "expected": {"tier": "gold"},
        "match": "exact",
        "as_of": "2026-01-01",
    }

    def h(r):
        if r.method == "GET":
            return _ok([current])
        return _ok({**current, **json.loads(r.content)})

    sdk, seen = _client(h)
    run(sdk.decisions.update_test("k", "t1", match="subset", as_of=None))
    put = seen[-1]
    assert put.method == "PUT" and put.url.path == "/api/decisions/k/tests/t1"
    assert json.loads(put.content) == {
        "name": "gold",
        "facts": {"a": 1},
        "expected": {"tier": "gold"},
        "expected_outcome": "decided",
        "as_of": None,
        "match": "subset",
    }
    with pytest.raises(ValueError):
        run(sdk.decisions.update_test("k", "t1", colour="red"))
    with pytest.raises(AbenixDecisionError) as e:
        run(sdk.decisions.update_test("k", "missing", name="x"))
    assert e.value.status == 404


def test_delete_test():
    sdk, seen = _client(lambda r: _ok({"deleted": True}))
    assert run(sdk.decisions.delete_test("k", "t1")) == {"deleted": True}
    assert (
        seen[0].method == "DELETE" and seen[0].url.path == "/api/decisions/k/tests/t1"
    )
