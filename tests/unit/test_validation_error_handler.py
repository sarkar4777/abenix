"""A validation failure is always a serialisable 422, whatever pydantic put in the error."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError, field_validator


class _Node(BaseModel):
    id: str

    @field_validator("id")
    @classmethod
    def _bad(cls, v):
        raise ValueError("node id is not valid")


def _pydantic_errors():
    with pytest.raises(ValidationError) as err:
        _Node(id="x")
    return err.value.errors()


async def _handle(errors):
    from app.main import _validation_exception_handler

    request = SimpleNamespace(headers={})
    return await _validation_exception_handler(
        request, RequestValidationError(errors=errors)
    )


@pytest.mark.asyncio
async def test_a_value_error_in_ctx_gives_a_422():
    errors = _pydantic_errors()
    assert isinstance(errors[0]["ctx"]["error"], ValueError)
    resp = await _handle(errors)
    assert resp.status_code == 422
    body = json.loads(resp.body)
    assert body["error"]["error_code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["errors"][0]["ctx"]["error"] == (
        "node id is not valid"
    )


@pytest.mark.parametrize(
    "bad_input",
    [b"\xff\xfe", object(), {1, 2}, "\ud800", {("a", "b"): 1}],
    ids=["bytes", "object", "set", "lone_surrogate", "tuple_key"],
)
@pytest.mark.asyncio
async def test_unserialisable_input_still_gives_a_422(bad_input):
    resp = await _handle([{"type": "value_error", "loc": ["body"], "input": bad_input}])
    assert resp.status_code == 422
    assert json.loads(resp.body)["error"]["code"] == 422
