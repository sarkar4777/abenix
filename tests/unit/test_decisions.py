"""Rule documents, typed JSON interchange, evaluation, validation and bitemporal resolution."""

from __future__ import annotations

import asyncio
import copy
import datetime as dt

import pytest

pytest.importorskip("zen")

from engine.decisions import authoring as A  # noqa: E402
from engine.decisions import evaluator as E  # noqa: E402
from engine.decisions import interchange as I  # noqa: E402
from engine.decisions import service as S  # noqa: E402
from engine.decisions import validation as V  # noqa: E402

SAMPLE = {
    "ruleKey": "eu.cbam.import.applicability",
    "version": 4,
    "jurisdiction": "EU",
    "regime": "CBAM",
    "status": "IN_FORCE",
    "validFrom": "2026-01-01",
    "requiresFacts": [
        "import.date",
        "import.cnCode",
        "import.netMassTonnes",
        "importer.annualCbamMassTonnes",
    ],
    "when": {
        "all": [
            {"gte": [{"fact": "import.date"}, "2026-01-01"]},
            {"inReferenceSet": [{"fact": "import.cnCode"}, "EU_CBAM_CN_CODES"]},
            {"gt": [{"fact": "importer.annualCbamMassTonnes"}, 50]},
        ]
    },
    "then": {"obligation": "CBAM_DECLARATION_AND_CERTIFICATE_SURRENDER"},
    "provenance": {
        "sourceSnapshotId": "snapshot-123",
        "citations": ["article-or-guidance-location"],
    },
}
REFS = {"EU_CBAM_CN_CODES": ["31021000", "72011000"]}
FACTS = {
    "import": {"date": "2026-03-01", "cnCode": "31021000", "netMassTonnes": 12.5},
    "importer": {"annualCbamMassTonnes": 120},
}


def run(c):
    return asyncio.run(c)


def compiled():
    doc = I.import_rules(SAMPLE)
    return doc, A.compile_document(doc, REFS)


def ev(c, facts, **kw):
    return run(
        E.evaluate(
            c.content_hash,
            c.jdm,
            facts,
            required=c.required_facts,
            fact_types=c.fact_types,
            **kw,
        )
    )


def test_client_rule_round_trips_exactly():
    doc = I.import_rules(SAMPLE)
    assert I.export_rules(doc) == [SAMPLE]


def test_import_infers_types_and_required_facts():
    doc = I.import_rules(SAMPLE)
    types = {f["path"]: f["type"] for f in doc["facts"]}
    assert types == {
        "import.date": "date",
        "import.cnCode": "string",
        "importer.annualCbamMassTonnes": "number",
        "import.netMassTonnes": "number",
    }
    assert all(f["required"] for f in doc["facts"])


def test_import_merges_by_rule_key():
    doc = I.import_rules(SAMPLE)
    changed = copy.deepcopy(SAMPLE)
    changed["then"] = {"obligation": "NEW"}
    doc2 = I.import_rules(changed, base=doc)
    assert (
        len(doc2["rules"]) == 1
        and doc2["rules"][0]["then"]["obligation"]["value"] == "NEW"
    )


def test_bad_interchange_names_the_place():
    with pytest.raises(I.InterchangeError) as e:
        I.import_rules(
            {
                "ruleKey": "x",
                "when": {"all": [{"zz": [{"fact": "a"}, 1]}]},
                "then": {"o": 1},
            }
        )
    assert "/when/all/0" in e.value.path and "zz" in e.value.message


def test_decides_and_normalises_identifiers():
    _, c = compiled()
    facts = copy.deepcopy(FACTS)
    facts["import"]["cnCode"] = 31021000
    r = ev(c, facts, as_of="2026-03-01")
    assert r.outcome == "decided"
    assert r.result == {"obligation": "CBAM_DECLARATION_AND_CERTIFICATE_SURRENDER"}
    assert r.applied_rules == ["eu.cbam.import.applicability"]
    assert r.normalised[0]["to"] == "31021000"
    assert r.trace[0]["values_seen"]["importer.annualCbamMassTonnes"] == 120


def test_missing_and_invalid_facts_never_look_like_no_match():
    _, c = compiled()
    r = ev(c, {"import": {"date": "2026-03-01"}})
    assert (
        r.outcome == "missing_facts"
        and "importer.annualCbamMassTonnes" in r.missing_facts
    )
    bad = copy.deepcopy(FACTS)
    bad["importer"]["annualCbamMassTonnes"] = "lots"
    r = ev(c, bad)
    assert (
        r.outcome == "invalid_facts"
        and r.invalid_facts[0]["fact"] == "importer.annualCbamMassTonnes"
    )


def test_rule_validity_follows_as_of():
    _, c = compiled()
    assert ev(c, FACTS, as_of="2025-12-31").outcome == "no_match"
    assert ev(c, FACTS, as_of="2026-01-01").outcome == "decided"


def test_trace_hash_is_deterministic_and_sensitive():
    _, c = compiled()
    a = ev(c, FACTS, as_of="2026-03-01")
    b = ev(c, copy.deepcopy(FACTS), as_of="2026-03-01")
    assert a.trace_hash == b.trace_hash and len(a.trace_hash) == 64
    other = copy.deepcopy(FACTS)
    other["importer"]["annualCbamMassTonnes"] = 121
    assert ev(c, other, as_of="2026-03-01").trace_hash != a.trace_hash


def test_compile_is_deterministic():
    d1 = I.import_rules(SAMPLE)
    d2 = I.import_rules(copy.deepcopy(SAMPLE))
    assert (
        A.compile_document(d1, REFS).content_hash
        == A.compile_document(d2, REFS).content_hash
    )
    assert (
        A.compile_document(d1, {"EU_CBAM_CN_CODES": ["1"]}).content_hash
        != A.compile_document(d1, REFS).content_hash
    )


def test_nested_groups_and_formulas():
    doc = {
        "hit_policy": "first",
        "facts": [
            {"path": "a", "type": "number"},
            {"path": "b", "type": "string"},
            {"path": "c", "type": "string"},
        ],
        "outputs": [{"field": "score"}],
        "rules": [
            {
                "key": "x",
                "when": {
                    "any": [
                        {
                            "all": [
                                {"fact": "a", "op": "gt", "value": 1},
                                {"fact": "b", "op": "eq", "value": "x"},
                            ]
                        },
                        {"fact": "c", "op": "in", "values": ["p", "q"]},
                    ]
                },
                "then": {"score": {"formula": "a * 10"}},
            },
            {"key": "fallback", "when": {"all": []}, "then": {"score": {"value": 0}}},
        ],
    }
    assert A.validate_document(doc) == []
    c = A.compile_document(doc)
    assert ev(c, {"a": 2, "b": "x"}).result == {"score": 20}
    assert ev(c, {"a": 0, "c": "q"}).result == {"score": 0}
    assert ev(c, {"a": 0, "c": "z"}).applied_rules == ["fallback"]


@pytest.mark.parametrize(
    "rule,code,path",
    [
        (
            {
                "when": {"all": [{"fact": "nope", "op": "eq", "value": 1}]},
                "then": {"o": {"value": 1}},
            },
            "unknown_fact",
            "/rules/0/when/all/0/fact",
        ),
        (
            {
                "when": {"all": [{"fact": "n", "op": "starts_with", "value": "x"}]},
                "then": {"o": {"value": 1}},
            },
            "op_type",
            "/rules/0/when/all/0/op",
        ),
        (
            {
                "when": {"all": [{"fact": "n", "op": "gt", "value": "ten"}]},
                "then": {"o": {"value": 1}},
            },
            "value_type",
            "/rules/0/when/all/0/value",
        ),
        (
            {
                "when": {"all": [{"fact": "n", "op": "between", "values": [5, 1]}]},
                "then": {"o": {"value": 1}},
            },
            "range_order",
            "/rules/0/when/all/0/values",
        ),
        (
            {"when": {"all": []}, "then": {"o": {"formula": "n +"}}},
            "bad_formula",
            "/rules/0/then/o/formula",
        ),
        (
            {"when": {"all": []}, "then": {"o": {"formula": "n + missing.fact"}}},
            "unknown_fact",
            "/rules/0/then/o/formula",
        ),
        (
            {"when": {"all": []}, "then": {"zz": {"value": 1}}},
            "unknown_output",
            "/rules/0/then/zz",
        ),
        ({"when": {"all": []}, "then": {}}, "no_then", "/rules/0/then"),
        (
            {
                "when": {"all": []},
                "then": {"o": {"value": 1}},
                "valid_from": "2026-02-01",
                "valid_to": "2026-01-01",
            },
            "range_order",
            "/rules/0/valid_to",
        ),
        (
            {"key": "Bad Key", "when": {"all": []}, "then": {"o": {"value": 1}}},
            "bad_key",
            "/rules/0/key",
        ),
    ],
)
def test_validation_points_at_the_field(rule, code, path):
    doc = {
        "facts": [{"path": "n", "type": "number"}],
        "outputs": [{"field": "o"}],
        "rules": [rule],
    }
    probs = A.validate_document(doc)
    assert any(p.code == code and p.path == path for p in probs), [
        p.to_dict() for p in probs
    ]


def test_unknown_reference_set_is_flagged():
    doc = I.import_rules(SAMPLE)
    probs = A.validate_document(doc, {})
    assert any(p.code == "unknown_set" for p in probs)


def test_shadowed_rule_is_found_under_first_match():
    doc = {
        "hit_policy": "first",
        "facts": [{"path": "n", "type": "number"}],
        "outputs": [{"field": "o"}],
        "rules": [
            {
                "key": "broad",
                "when": {"all": [{"fact": "n", "op": "gt", "value": 10}]},
                "then": {"o": {"value": "A"}},
            },
            {
                "key": "narrow",
                "when": {"all": [{"fact": "n", "op": "gt", "value": 100}]},
                "then": {"o": {"value": "B"}},
            },
        ],
    }
    found = V.overlaps(doc)
    assert found and found[0]["kind"] == "shadowed" and found[0]["rule"] == "narrow"


def test_conflict_is_found_under_collect():
    doc = {
        "hit_policy": "collect",
        "facts": [{"path": "n", "type": "number"}],
        "outputs": [{"field": "o"}],
        "rules": [
            {
                "key": "a",
                "when": {"all": [{"fact": "n", "op": "gt", "value": 10}]},
                "then": {"o": {"value": "A"}},
            },
            {
                "key": "b",
                "when": {"all": [{"fact": "n", "op": "gte", "value": 50}]},
                "then": {"o": {"value": "B"}},
            },
        ],
    }
    found = V.overlaps(doc)
    assert any(f["kind"] == "conflict" and f["fields"] == ["o"] for f in found)


def test_golden_tests_and_regression():
    doc, c = compiled()
    tests = [
        {
            "id": "t1",
            "name": "large importer",
            "facts": FACTS,
            "as_of": "2026-03-01",
            "expected": {"obligation": "CBAM_DECLARATION_AND_CERTIFICATE_SURRENDER"},
        },
        {
            "id": "t2",
            "name": "missing",
            "facts": {},
            "expected_outcome": "missing_facts",
        },
    ]
    res = run(V.run_tests(c, tests))
    assert all(r["passed"] for r in res)
    doc2 = copy.deepcopy(doc)
    doc2["rules"][0]["when"]["all"][2]["value"] = 150
    c2 = A.compile_document(doc2, REFS)
    changed = run(V.regression(c2, c, tests))
    assert len(changed) == 1 and changed[0]["after"]["outcome"] == "no_match"


def _v(n, f, t, pub, sup=None, hist=None):
    d = lambda s: S._as_dt(s)  # noqa: E731
    return S.VersionRef(
        id=str(n),
        version=n,
        state="published",
        content={},
        content_hash=str(n),
        required_facts=[],
        fact_types={},
        valid_from=d(f),
        valid_to=d(t),
        valid_to_history=hist or [],
        published_at=d(pub),
        superseded_at=d(sup),
    )


def test_bitemporal_pick_uses_both_time_axes():
    v1 = _v(
        1,
        "2026-01-01",
        "2027-01-01",
        "2025-11-01",
        hist=[{"from": None, "to": "2027-01-01", "at": "2026-06-01"}],
    )
    v2 = _v(2, "2027-01-01", None, "2026-06-01")
    snap = S.ModelSnapshot(
        id="m", key="k", name="k", risk_tier="low", log_mode="none", versions=[v1, v2]
    )
    now = S._as_dt("2026-09-01")
    assert S.pick(snap, S._as_dt("2026-05-01"), now).version == 1
    assert S.pick(snap, S._as_dt("2027-03-01"), now).version == 2
    # before v2 was published, v1 was thought to run on with no end
    assert S.pick(snap, S._as_dt("2027-03-01"), S._as_dt("2026-03-01")).version == 1
    assert S.pick(snap, S._as_dt("2025-06-01"), now) is None


def test_superseded_version_still_answers_for_the_past():
    v1 = _v(1, "2026-01-01", None, "2025-11-01", sup="2026-02-01")
    v2 = _v(2, "2026-01-01", None, "2026-02-01")
    snap = S.ModelSnapshot(
        id="m", key="k", name="k", risk_tier="low", log_mode="none", versions=[v1, v2]
    )
    assert S.pick(snap, S._as_dt("2026-01-15"), S._as_dt("2026-03-01")).version == 2
    assert S.pick(snap, S._as_dt("2026-01-15"), S._as_dt("2026-01-20")).version == 1


def test_publish_plan_supersedes_closes_and_blocks():
    cur = [_v(1, "2026-01-01", None, "2025-11-01")]
    p = S.plan_publish(cur, S._as_dt("2026-01-01"), None)
    assert p.supersede == ["1"] and not p.block
    p = S.plan_publish(cur, S._as_dt("2027-01-01"), None)
    assert p.close == [("1", S._as_dt("2027-01-01"))] and not p.block
    p = S.plan_publish(cur, S._as_dt("2027-01-01"), S._as_dt("2028-01-01"))
    assert p.block and "split" in p.block
    p = S.plan_publish(
        [_v(1, "2027-06-01", None, "2025-11-01")],
        S._as_dt("2027-01-01"),
        S._as_dt("2028-01-01"),
    )
    assert p.block and "starts on" in p.block
    assert (
        S.plan_publish(
            [_v(1, "2026-01-01", "2027-01-01", "2025-11-01")],
            S._as_dt("2027-01-01"),
            None,
        ).supersede
        == []
    )


def test_cache_compiles_each_content_once():
    _, c = compiled()
    E.forget()
    ev(c, FACTS)
    ev(c, FACTS)
    assert E.cache_size() == 1


def test_many_concurrent_evaluations_agree():
    _, c = compiled()

    async def go():
        return await E.evaluate_many(
            c.content_hash,
            c.jdm,
            [FACTS] * 300,
            required=c.required_facts,
            fact_types=c.fact_types,
            as_of="2026-03-01",
        )

    res = run(go())
    assert len({r.trace_hash for r in res}) == 1 and all(
        r.outcome == "decided" for r in res
    )


def test_date_facts_accept_datetimes():
    _, c = compiled()
    facts = copy.deepcopy(FACTS)
    facts["import"]["date"] = dt.datetime(2026, 3, 1, 12, 0)
    assert ev(c, facts, as_of="2026-03-01").outcome == "decided"
