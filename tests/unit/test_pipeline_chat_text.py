"""The chat relay shows a pipeline's answer, which arrives only on done."""

from __future__ import annotations

import json

from app.routers.agents import _final_text


def test_unwraps_response_from_json_string():
    assert _final_text(json.dumps({"response": "BRIEFING\nBrno"})) == "BRIEFING\nBrno"


def test_unwraps_dict_and_plain_text():
    assert _final_text({"content": "hello"}) == "hello"
    assert _final_text("just text") == "just text"


def test_falls_back_to_json_and_empty():
    assert json.loads(_final_text({"a": 1})) == {"a": 1}
    assert _final_text(None) == ""
    assert _final_text("[1, 2]") == "[1, 2]"
