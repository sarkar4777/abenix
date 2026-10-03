"""Triggers refuse a high tier draft with 409 and a clear reason."""

from types import SimpleNamespace


def test_trigger_refusal_maps_to_409():
    import json

    from app.routers.triggers import _not_dispatched_error

    ex = SimpleNamespace(
        failure_code="DRAFT_NOT_RELEASED", error_message="publish it first", id="e1"
    )
    resp = _not_dispatched_error(ex)
    assert resp.status_code == 409
    assert json.loads(resp.body)["error"]["error_code"] == "DRAFT_NOT_RELEASED"
