"""LLM JSON extraction must survive trailing prose.

Models routinely emit a fenced config and then a prose summary after it. Three
separate parsers used text[index("{"):rindex("}")+1], which swallows that prose
whenever it contains a brace and then dies with "Extra data":

  - ai_builder._parse_builder_json  → killed Build-with-AI outright
  - ai_builder_loop._judge          → wasted a whole build iteration
  - ai_builder_loop._critic         → same

All three now take the first complete JSON object instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "apps" / "agent-runtime", ROOT / "apps" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from engine.ai_builder_loop import _first_json_object as loop_extract  # noqa: E402

# The exact shape observed in the failing build: fenced config, then a summary.
FENCED_THEN_PROSE = """```json
{"name": "LNG Risk", "nodes": [{"id": "search"}, {"id": "score"}]}
```

---

## Pipeline Summary

This **12-node DAG** assesses risk. Thresholds are {high: 80, low: 20}.
"""

BARE_THEN_PROSE = """{"passed": true, "score": 8, "suggestions": []}

The config is solid. Minor note: consider {retry} semantics.
"""


def test_extract_from_fenced_then_prose() -> None:
    got = loop_extract(FENCED_THEN_PROSE)
    assert got is not None, "trailing prose defeated the extractor"
    assert got["name"] == "LNG Risk"
    assert len(got["nodes"]) == 2


def test_extract_from_bare_then_prose() -> None:
    got = loop_extract(BARE_THEN_PROSE)
    assert got is not None
    assert got["passed"] is True
    assert got["score"] == 8


def test_extract_plain_object() -> None:
    assert loop_extract('{"a": 1}') == {"a": 1}


def test_extract_skips_leading_prose() -> None:
    got = loop_extract('Sure, here you go:\n{"a": 1}\nHope that helps.')
    assert got == {"a": 1}


@pytest.mark.parametrize("text", ["", "no braces here", "just prose, nothing structured"])
def test_extract_returns_none_without_json(text: str) -> None:
    assert loop_extract(text) is None


def test_extract_ignores_a_broken_first_brace() -> None:
    """A brace that starts nothing valid must not stop the search."""
    got = loop_extract('{ not json at all\nthen later: {"real": true}')
    assert got == {"real": True}


def test_builder_parser_handles_trailing_prose() -> None:
    """The API-side parser is a separate implementation — cover it too."""
    from app.routers.ai_builder import _parse_builder_json

    got = _parse_builder_json(FENCED_THEN_PROSE)
    assert got["name"] == "LNG Risk"


def test_builder_parser_still_rejects_all_prose() -> None:
    from app.routers.ai_builder import _parse_builder_json

    with pytest.raises(ValueError, match="all prose"):
        _parse_builder_json("I cannot help with that request.")
