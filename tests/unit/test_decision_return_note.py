"""A reviewer's return note stays on the draft through edits and checks."""


def test_note_survives_edit_and_check():
    from app.routers.decisions import _keep_returned

    returned = {"ok": False, "summary": "", "returned": {"note": "Cite rule 1", "at": "2026-10-06T10:00:00+00:00"}}
    after_edit = _keep_returned(returned, None)
    assert after_edit == {"returned": returned["returned"]}
    after_check = _keep_returned(after_edit, {"ok": True, "summary": "Ready.", "problems": []})
    assert after_check["ok"] is True
    assert after_check["returned"]["note"] == "Cite rule 1"


def test_nothing_to_keep_passes_the_new_value_through():
    from app.routers.decisions import _keep_returned

    assert _keep_returned(None, None) is None
    fresh = {"ok": True, "summary": "Ready.", "problems": []}
    assert _keep_returned({"ok": False}, fresh) is fresh
