import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_json import parse_agent_json  # noqa: E402

SCAN = {
    "verdict": "dislocated",
    "observed_spread_usd_mt": 116.87,
    "fair_value_spread_usd_mt": -36.82,
    "residual_sigma": 6.98,
    "feature_vector": {"origin_spot_z": 0.79},
}


def test_plain_json():
    assert parse_agent_json(json.dumps(SCAN)) == SCAN


def test_empty_and_junk():
    assert parse_agent_json("") == {}
    assert parse_agent_json(None) == {}
    assert parse_agent_json("no json here") == {}


def test_prose_with_braces_then_fenced_block():
    raw = (
        "Let me compute z = (x - mean) / std for {origin, dest}.\n"
        'Feature vector so far {"origin_spot_z": 0.79}\n'
        "Now the final answer:\n\n```json\n" + json.dumps(SCAN, indent=2) + "\n```\n"
    )
    assert parse_agent_json(raw) == SCAN


def test_last_fenced_block_wins():
    raw = (
        '```json\n{"draft": true}\n```\nrevised:\n```json\n'
        + json.dumps(SCAN)
        + "\n```"
    )
    assert parse_agent_json(raw) == SCAN


def test_unfenced_object_after_prose_braces():
    raw = "Inputs {origin, dest} gathered. Result: " + json.dumps(SCAN) + " Done {ok}."
    assert parse_agent_json(raw) == SCAN
