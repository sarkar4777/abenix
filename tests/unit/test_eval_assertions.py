"""Evaluation assertions, case and run scoring, run comparison, the publish gate decision and model-change detection."""

from __future__ import annotations

import asyncio

import pytest

from app.services import eval_assertions as EA
from app.services.eval_scoring import (
    compare_results,
    gate_decision,
    model_changed,
    score_run,
)
from engine import risk

OUT = """Here is the result:
```json
{"decision": "approve", "amount": 1200.5, "flags": ["kyc", "sanctions"],
 "party": {"name": "Acme GmbH", "country": "DE"}, "items": [{"sku": "A1"}, {"sku": "B2"}]}
```
Let me know if you need more."""


def obs(**kw):
    base = dict(
        output=OUT,
        tool_calls=[{"name": "knowledge_search"}, {"name": "calculator"}],
        cost=0.012,
        duration_ms=2400,
        status="completed",
        input_message="Should we approve Acme?",
    )
    base.update(kw)
    return EA.Observed(**base)


def check(a, **kw):
    return EA.check(a, obs(**kw))


def run(c):
    return asyncio.run(c)


def test_fenced_json_and_trailing_prose_parse():
    assert EA.parse_output_json(OUT)["decision"] == "approve"
    assert EA.parse_output_json('Sure. {"a": 1} hope that helps')["a"] == 1
    assert EA.parse_output_json("no json here") is EA._MISSING
    assert EA.parse_output_json("") is EA._MISSING


@pytest.mark.parametrize(
    "path,want",
    [
        ("decision", ["approve"]),
        ("$.party.name", ["Acme GmbH"]),
        ("flags[1]", ["sanctions"]),
        ("flags[-1]", ["sanctions"]),
        ("items[*].sku", ["A1", "B2"]),
        ("['party']['country']", ["DE"]),
        ("missing.deep", []),
    ],
)
def test_json_path_values(path, want):
    assert EA.json_path_values(EA.parse_output_json(OUT), path) == want


def test_bad_path_is_reported():
    with pytest.raises(ValueError):
        EA.path_tokens("a..b")
    assert EA.validate({"type": "json_path_equals", "path": "a..b", "value": 1})


def test_json_path_equals_passes_and_fails_with_reason():
    ok = check({"type": "json_path_equals", "path": "decision", "value": "approve"})
    assert ok["passed"] and ok["score"] == 1.0 and ok["deterministic"]
    bad = check({"type": "json_path_equals", "path": "decision", "value": "reject"})
    assert not bad["passed"] and "expected" in bad["reason"]
    assert check({"type": "json_path_equals", "path": "amount", "value": 1200.5})[
        "passed"
    ]
    assert check(
        {"type": "json_path_equals", "path": "amount", "value": 1200, "tolerance": 1}
    )["passed"]
    assert check(
        {
            "type": "json_path_equals",
            "path": "decision",
            "value": "APPROVE",
            "ignore_case": True,
        }
    )["passed"]
    assert check({"type": "json_path_equals", "path": "items[*].sku", "value": "B2"})[
        "passed"
    ]
    missing = check({"type": "json_path_equals", "path": "nope", "value": 1})
    assert not missing["passed"] and "not in the output" in missing["reason"]
    not_json = check(
        {"type": "json_path_equals", "path": "a", "value": 1}, output="plain text"
    )
    assert not not_json["passed"] and "not JSON" in not_json["reason"]


def test_bool_never_equals_number():
    assert not EA.check(
        {"type": "json_path_equals", "path": "x", "value": 1},
        obs(output='{"x": true}'),
    )["passed"]


def test_json_path_contains_text_list_and_keys():
    assert check({"type": "json_path_contains", "path": "flags", "value": "kyc"})[
        "passed"
    ]
    assert check(
        {
            "type": "json_path_contains",
            "path": "party.name",
            "value": "acme",
            "ignore_case": True,
        }
    )["passed"]
    assert check({"type": "json_path_contains", "path": "party", "value": "country"})[
        "passed"
    ]
    assert not check({"type": "json_path_contains", "path": "flags", "value": "pep"})[
        "passed"
    ]


def test_regex_match_and_no_match():
    assert check({"type": "regex", "pattern": r"\d{4}\.5"})["passed"]
    assert check({"type": "regex", "pattern": "ACME", "ignore_case": True})["passed"]
    r = check({"type": "regex", "pattern": "reject", "mode": "no_match"})
    assert r["passed"] and "as expected" in r["reason"]
    r = check({"type": "regex", "pattern": "approve", "mode": "no_match"})
    assert not r["passed"]
    assert EA.validate({"type": "regex", "pattern": "("})


def test_contains_and_not_contains():
    assert check({"type": "contains", "value": "acme gmbh"})["passed"]
    assert not check(
        {"type": "contains", "value": "acme gmbh", "case_sensitive": True}
    )["passed"]
    assert check({"type": "not_contains", "value": "as an AI"})["passed"]
    assert not check({"type": "not_contains", "value": "Approve"})["passed"]


def test_schema_valid():
    schema = {
        "type": "object",
        "required": ["decision", "amount"],
        "properties": {
            "decision": {"enum": ["approve", "reject"]},
            "amount": {"type": "number"},
        },
    }
    assert check({"type": "schema_valid", "schema": schema})["passed"]
    bad = check(
        {"type": "schema_valid", "schema": schema}, output='{"decision": "maybe"}'
    )
    assert not bad["passed"] and "At" in bad["reason"]
    assert EA.validate({"type": "schema_valid", "schema": {"type": "nonsense"}})
    assert EA.validate({"type": "schema_valid", "schema": "x"})


def test_required_tools_called_all_any_and_partial_credit():
    r = check(
        {"type": "required_tools_called", "tools": ["knowledge_search", "web_search"]}
    )
    assert not r["passed"] and r["score"] == 0.5 and "web_search" in r["reason"]
    assert check(
        {
            "type": "required_tools_called",
            "tools": ["web_search", "calculator"],
            "mode": "any",
        }
    )["passed"]
    assert check({"type": "required_tools_called", "tools": ["calculator"]})["passed"]
    # pipeline tool calls carry the tool under "tool"
    assert EA.check(
        {"type": "required_tools_called", "tools": ["llm_call"]},
        obs(tool_calls=[{"tool": "llm_call", "node": "n1"}]),
    )["passed"]


def test_max_cost_and_duration():
    assert check({"type": "max_cost", "max": 0.02})["passed"]
    assert not check({"type": "max_cost", "max": 0.01})["passed"]
    assert check({"type": "max_duration_ms", "max": 3000})["passed"]
    r = check({"type": "max_duration_ms", "max": 1000})
    assert not r["passed"] and "over" in r["reason"]
    assert not check({"type": "max_duration_ms", "max": 1000}, duration_ms=None)[
        "passed"
    ]
    assert EA.validate({"type": "max_cost", "max": -1})


def test_cited_sources_by_link_or_source_tool():
    assert check(
        {"type": "cited_sources_present", "min_count": 1},
        output="See https://eur-lex.europa.eu/x",
        tool_calls=[],
    )["passed"]
    r = check(
        {"type": "cited_sources_present"},
        output="no links",
        tool_calls=[{"name": "knowledge_search"}],
    )
    assert r["passed"] and "knowledge_search" in r["reason"]
    assert not check(
        {"type": "cited_sources_present", "accept_source_tools": False},
        output="no links",
    )["passed"]
    assert not check(
        {"type": "cited_sources_present"}, output="no links", tool_calls=[]
    )["passed"]
    assert check(
        {"type": "cited_sources_present", "pattern": r"\[\d+\]", "min_count": 2},
        output="a [1] b [2]",
        tool_calls=[],
    )["passed"]


def test_incomplete_and_unknown_assertions_fail_with_a_reason():
    r = EA.check({"type": "contains"}, obs())
    assert not r["passed"] and "incomplete" in r["reason"]
    assert EA.validate({"type": "bogus"})
    assert EA.validate("x")
    assert EA.validate({"type": "json_path_equals", "path": "a", "value": None}) == []
    assert EA.validate({"type": "judge", "rubric": "be nice", "min_score": 2})


def test_judge_is_scored_by_the_model_and_marked_non_deterministic():
    seen = {}

    async def fake(rubric, inp, out, model):
        seen.update(rubric=rubric, inp=inp, model=model)
        return 0.8, "mostly grounded", 0.0003

    a = {"type": "judge", "rubric": "No unsupported claims"}
    res, cost = run(EA.check_async(a, obs(), fake))
    assert res["passed"] and res["score"] == 0.8 and not res["deterministic"]
    assert seen["model"] == EA.DEFAULT_JUDGE_MODEL and seen["inp"].startswith("Should")
    assert cost == 0.0003
    res, _ = run(EA.check_async({**a, "min_score": 0.9}, obs(), fake))
    assert not res["passed"]

    async def broken(*_):
        raise RuntimeError("quota")

    res, _ = run(EA.check_async(a, obs(), broken))
    assert not res["passed"] and "quota" in res["reason"]
    res, _ = run(EA.check_async(a, obs(), None))
    assert not res["passed"]


def test_case_passes_only_when_every_assertion_passes():
    good = {"type": "contains", "value": "approve"}
    bad = {"type": "contains", "value": "reject"}
    out, _ = run(EA.evaluate_case([good, good], obs()))
    assert out.passed and out.score == 1.0
    out, _ = run(EA.evaluate_case([good, bad], obs()))
    assert not out.passed and out.score == 0.5
    out, _ = run(EA.evaluate_case([], obs()))
    assert out.passed
    out, _ = run(EA.evaluate_case([good], obs(status="failed")))
    assert not out.passed and out.score == 0.0 and "failed" in out.results[0]["reason"]


def test_suggestions_hold_for_the_run_they_came_from():
    o = obs()
    sugg = EA.suggest(o)
    types = {a["type"] for a in sugg}
    assert {
        "json_path_equals",
        "schema_valid",
        "required_tools_called",
        "cited_sources_present",
        "max_cost",
        "max_duration_ms",
    } <= types
    for a in sugg:
        assert EA.validate(a) == [], a
        assert EA.check(a, o)["passed"], a
    text_only = EA.suggest(
        obs(output="The applicant qualifies under section four.", tool_calls=[])
    )
    assert text_only[0]["type"] == "contains"


def test_run_score_is_weighted_and_compared_to_threshold():
    cases = [
        {"weight": 3, "passed": True, "status": "completed"},
        {"weight": 1, "passed": False, "status": "completed"},
    ]
    s = score_run(cases, 0.75)
    assert s["score"] == 0.75 and s["threshold_met"] and s["passed"] == 1
    assert not score_run(cases, 0.8)["threshold_met"]
    s = score_run(cases + [{"weight": 1, "passed": True, "status": "error"}], 0.5)
    assert s["errored"] == 1 and s["failed"] == 2 and s["score"] == 0.6
    assert score_run([], 0.5)["score"] is None
    assert not score_run([], 0.0)["threshold_met"]
    # zero weights fall back to the plain pass rate
    assert (
        score_run([{"weight": 0, "passed": True}, {"weight": 0, "passed": False}], 0.5)[
            "score"
        ]
        == 0.5
    )


def test_compare_finds_regressions_and_improvements():
    base = [
        {"case_id": "a", "case_name": "A", "passed": True, "score": 1.0},
        {"case_id": "b", "case_name": "B", "passed": False, "score": 0.5},
        {"case_id": "c", "case_name": "C", "passed": True, "score": 1.0},
        {"case_id": "d", "case_name": "D", "passed": False, "score": 0.0},
        {"case_id": "gone", "case_name": "Gone", "passed": True, "score": 1.0},
    ]
    new = [
        {"case_id": "a", "case_name": "A", "passed": False, "score": 0.5},
        {"case_id": "b", "case_name": "B", "passed": True, "score": 1.0},
        {"case_id": "c", "case_name": "C", "passed": True, "score": 1.0},
        {"case_id": "d", "case_name": "D", "passed": False, "score": 0.0},
        {"case_id": "new", "case_name": "New", "passed": True, "score": 1.0},
    ]
    c = compare_results(base, new)
    assert [r["case_id"] for r in c["regressions"]] == ["a"]
    assert c["regressions"][0]["score_delta"] == -0.5
    assert [r["case_id"] for r in c["improvements"]] == ["b"]
    assert c["counts"] == {
        "regressions": 1,
        "improvements": 1,
        "still_failing": 1,
        "still_passing": 1,
        "added": 1,
        "removed": 1,
    }


def _suite(run=None, name="Golden", threshold=0.9):
    return {"id": "s1", "name": name, "threshold": threshold, "run": run}


def test_gate_allows_when_not_required_or_no_gating_suite():
    assert gate_decision(
        required=False, tier="high", config_hash="h", suites=[_suite()]
    ).allowed
    assert gate_decision(required=True, tier="high", config_hash="h", suites=[]).allowed


def test_gate_needs_a_run_against_this_exact_version():
    g = gate_decision(required=True, tier="high", config_hash="h2", suites=[_suite()])
    assert not g.allowed and "has not been run" in g.message
    stale = {"id": "r", "score": 1.0, "threshold_met": True, "config_hash": "h1"}
    g = gate_decision(
        required=True, tier="high", config_hash="h2", suites=[_suite(stale)]
    )
    assert not g.allowed and g.suites[0]["state"] == "not_run"


def test_gate_lists_failing_cases_and_passes_a_green_run():
    red = {
        "id": "r",
        "score": 0.5,
        "threshold_met": False,
        "config_hash": "h",
        "failing_cases": ["Sanctions hit", "Missing KYC"],
    }
    g = gate_decision(
        required=True, tier="critical", config_hash="h", suites=[_suite(red)]
    )
    assert not g.allowed
    assert "critical risk" in g.message and "50%" in g.message and "90%" in g.message
    assert "Sanctions hit" in g.message and "Missing KYC" in g.message
    assert g.suites[0]["failing_cases"] == ["Sanctions hit", "Missing KYC"]
    green = {**red, "score": 0.95, "threshold_met": True, "failing_cases": []}
    g = gate_decision(
        required=True, tier="high", config_hash="h", suites=[_suite(green)]
    )
    assert g.allowed and g.suites[0]["state"] == "passed"
    # one red suite blocks even when another is green
    g = gate_decision(
        required=True,
        tier="high",
        config_hash="h",
        suites=[_suite(green), _suite(red, name="Edge")],
    )
    assert not g.allowed and "Edge" in g.message


def test_model_change_detection():
    assert model_changed("claude-sonnet-4-5-20250929", "claude-opus-4-1")
    assert not model_changed("gpt-4o", "GPT-4o")
    assert not model_changed(None, "gpt-4o")
    assert not model_changed("gpt-4o", None)
    assert not model_changed("pipeline", "pipeline")


def test_tier_policy_requires_evals_for_high_and_critical():
    assert not risk.merged_policy("low", None)["require_eval_pass"]
    assert not risk.merged_policy("medium", None)["require_eval_pass"]
    assert risk.merged_policy("high", None)["require_eval_pass"]
    assert risk.merged_policy("critical", None)["require_eval_pass"]
    assert risk.merged_policy("low", {"require_eval_pass": True})["require_eval_pass"]
    assert risk.validate_policy({"require_eval_pass": True}) == []
    assert risk.validate_policy({"require_eval_pass": "yes"})


def test_suggested_limits_leave_room_for_latency() -> None:
    import asyncio

    obs = EA.Observed(output="PONG", cost=0.0004, duration_ms=948)
    got = EA.suggest(obs)
    by_type = {a["type"]: a for a in got}
    assert by_type["max_duration_ms"]["max"] >= 10_948
    assert by_type["max_cost"]["max"] >= 0.01
    rerun = EA.Observed(output="PONG", cost=0.0009, duration_ms=1984)
    outcome, _ = asyncio.run(EA.evaluate_case(got, rerun))
    assert outcome.passed
