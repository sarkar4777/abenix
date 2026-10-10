"""Python SDK: ml_models.explain posts the row and optional baseline to the explain route."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "packages" / "sdk" / "python")
)

from abenix_sdk import Abenix, AbenixError  # noqa: E402

MID = "11111111-2222-3333-4444-555555555555"


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


def test_explain_by_name_sends_row_and_baseline():
    def handler(req):
        if req.method == "GET":
            return httpx.Response(
                200,
                json={"data": [{"id": MID, "name": "churn", "is_active": True}]},
            )
        return httpx.Response(200, json={"data": {"method": "linear"}})

    sdk, seen = _client(handler)
    out = asyncio.run(sdk.ml_models.explain("churn", {"a": 1}, baseline={"a": 0}))
    assert out == {"method": "linear"}
    post = seen[-1]
    assert post.url.path == f"/api/ml-models/{MID}/explain"
    assert json.loads(post.content) == {"input_data": {"a": 1}, "baseline": {"a": 0}}


def test_explain_leaves_baseline_out_when_not_given():
    sdk, seen = _client(lambda req: httpx.Response(200, json={"data": {}}))
    asyncio.run(sdk.ml_models.explain(MID, [1, 2]))
    assert json.loads(seen[-1].content) == {"input_data": [1, 2]}


def test_explain_error_is_raised_with_the_message():
    sdk, _ = _client(
        lambda req: httpx.Response(
            422,
            json={
                "data": None,
                "error": {"message": "Explain takes one row at a time, you sent 2."},
            },
        )
    )
    with pytest.raises(AbenixError) as e:
        asyncio.run(sdk.ml_models.explain(MID, [[1], [2]]))
    assert e.value.status == 422
    assert "one row at a time" in str(e.value)
