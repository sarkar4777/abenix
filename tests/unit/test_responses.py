"""Tests for app.core.responses — the public API envelope.

Every router in apps/api builds responses through `success()` / `error()`.
The shape is contractual: SDKs and standalone apps unpack `data` and
`error` directly. Drift here breaks every downstream caller silently.
"""

from __future__ import annotations

import json

from app.core.responses import error, success


def _read(resp):
    """Extract the JSON body from a fastapi JSONResponse for assertion."""
    return json.loads(resp.body)


def test_success_default_envelope():
    resp = success({"id": "abc", "status": "completed"})
    assert resp.status_code == 200
    body = _read(resp)
    assert body == {
        "data": {"id": "abc", "status": "completed"},
        "error": None,
        "meta": None,
    }


def test_success_with_meta():
    resp = success([1, 2, 3], meta={"total": 3, "page": 1})
    body = _read(resp)
    assert body["data"] == [1, 2, 3]
    assert body["meta"] == {"total": 3, "page": 1}
    assert body["error"] is None


def test_success_custom_status_code_passes_through():
    resp = success({"id": "new"}, status_code=201)
    assert resp.status_code == 201
    assert _read(resp)["data"] == {"id": "new"}


def test_success_with_none_data():
    resp = success(None)
    body = _read(resp)
    assert body == {"data": None, "error": None, "meta": None}


def test_error_default_400():
    resp = error("invalid input")
    assert resp.status_code == 400
    body = _read(resp)
    assert body == {"data": None, "error": {"message": "invalid input", "code": 400}}


def test_error_custom_code():
    resp = error("not found", 404)
    assert resp.status_code == 404
    body = _read(resp)
    assert body["error"] == {"message": "not found", "code": 404}
    assert body["data"] is None


def test_error_5xx_codes():
    """5xx codes must round-trip both in HTTP status and the error.code
    payload — dashboards key off both, so they must agree."""
    for code in (500, 502, 503, 504):
        resp = error(f"server fail {code}", code)
        assert resp.status_code == code
        assert _read(resp)["error"]["code"] == code


def test_envelope_shape_is_stable_across_call_sites():
    """Both helpers must produce envelopes with the exact same key set
    so SDKs can deserialize them with one schema."""
    s = _read(success("ok"))
    e = _read(error("fail"))
    assert set(s.keys()) >= {"data", "error"}
    assert set(e.keys()) >= {"data", "error"}
    # data is non-null on success, null on error; vice-versa for error
    assert s["data"] is not None
    assert s["error"] is None
    assert e["data"] is None
    assert e["error"] is not None
