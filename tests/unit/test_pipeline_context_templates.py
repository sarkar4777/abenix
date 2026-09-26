"""A node's `context:` block must have its templates resolved.

_resolve_templates only walked string values, and a node's context arrives as a
dict. Every `{{input.x}}` inside it reached the agent verbatim, so ClaimsIQ's
policy matcher was handed the literal text `{{input.policy_number}}`, found no
policy, answered in prose instead of JSON, and collapsed every node downstream
of it into "[not available]".
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "apps" / "agent-runtime", ROOT / "apps" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from engine.pipeline import _resolve_templates  # noqa: E402

OUTPUTS = {
    "input": {"policy_number": "POL-4471-AUTO", "channel": "web"},
    "fnol": {"claim_type": "auto", "parties": [{"role": "claimant"}]},
}


def test_context_dict_is_resolved():
    args = {
        "__context__": {
            "policy_number": "{{input.policy_number}}",
            "claim_type": "{{fnol.claim_type}}",
        }
    }
    out = _resolve_templates(args, OUTPUTS)
    assert out["__context__"] == {
        "policy_number": "POL-4471-AUTO",
        "claim_type": "auto",
    }


def test_nested_lists_and_dicts_are_resolved():
    args = {
        "cfg": {
            "outer": [{"p": "{{input.policy_number}}"}, "{{input.channel}}"],
        }
    }
    out = _resolve_templates(args, OUTPUTS)
    assert out["cfg"]["outer"] == [{"p": "POL-4471-AUTO"}, "web"]


def test_whole_value_template_keeps_the_object():
    out = _resolve_templates({"parties": "{{fnol.parties}}"}, OUTPUTS)
    assert out["parties"] == [{"role": "claimant"}]


def test_unknown_reference_is_marked_unavailable():
    out = _resolve_templates(
        {"__context__": {"x": "{{nosuch.field}}"}, "s": "v={{nosuch.field}}"},
        OUTPUTS,
    )
    assert out["__context__"]["x"] == "[not available]"
    assert out["s"] == "v=[not available]"


def test_non_template_values_pass_through():
    args = {"n": 7, "b": True, "none": None, "plain": "no braces here"}
    assert _resolve_templates(args, OUTPUTS) == args
