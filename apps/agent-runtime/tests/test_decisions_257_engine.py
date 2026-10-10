"""Outcome types, the whole-decision file, golden tests without a date, and the tier policy sentence."""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
import json
from pathlib import Path

import pytest

pytest.importorskip("zen")

from engine import risk  # noqa: E402
from engine.decisions import authoring as A  # noqa: E402
from engine.decisions import interchange as I  # noqa: E402
from engine.decisions import validation as V  # noqa: E402

GW = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "unit"
    / "fixtures"
    / "gw.safety.exclusion.json"
)


def _doc(out_type, value):
    return A.normalize(
        {
            "facts": [{"path": "x", "type": "number"}],
            "outputs": [{"field": "fee", "type": out_type, "label": "fee"}],
            "rules": [
                {
                    "key": "a",
                    "when": {"all": [{"fact": "x", "op": "gt", "value": 1}]},
                    "then": {"fee": {"value": value}},
                }
            ],
        }
    )


def _codes(doc):
    return [p for p in A.validate_document(doc) if p.code == "OUTCOME_TYPE"]


@pytest.mark.parametrize(
    "out_type,value,ok",
    [
        ("number", 4, True),
        ("number", 4.5, True),
        ("number", "four", False),
        ("number", True, False),
        ("boolean", True, True),
        ("boolean", "yes", False),
        ("date", "2026-03-01", True),
        ("date", "next week", False),
        ("object", {"a": 1}, True),
        ("object", [1, 2], True),
        ("object", "x", False),
        ("string", "stop", True),
    ],
)
def test_outcome_value_must_match_its_type(out_type, value, ok):
    found = _codes(_doc(out_type, value))
    assert (not found) is ok
    if not ok:
        p = found[0].to_dict()
        assert p["field"] == "rules[0].then.fee"
        assert p["code"] == "OUTCOME_TYPE"
        assert out_type in p["message"] and "Found" in p["message"]


def test_a_formula_is_not_type_checked():
    doc = _doc("number", 1)
    doc["rules"][0]["then"]["fee"] = {"formula": "x * 2"}
    assert not _codes(doc)


def test_numeric_text_in_a_number_outcome_becomes_a_number():
    doc = _doc("number", "4")
    doc["rules"].append(
        {
            "key": "b",
            "when": {"all": []},
            "then": {"fee": " 2.5 "},
            "enabled": True,
            "id": "r2",
        }
    )
    changes = A.tidy_outcomes(doc)
    assert doc["rules"][0]["then"]["fee"] == {"value": 4}
    assert doc["rules"][1]["then"]["fee"] == 2.5
    assert {"field": "rules[0].then.fee", "from": "4", "to": 4} in changes
    assert {"field": "rules[1].then.fee", "from": " 2.5 ", "to": 2.5} in changes
    assert not _codes(doc)


def test_text_that_is_not_a_number_is_left_and_flagged():
    doc = _doc("number", "about four")
    assert A.tidy_outcomes(doc) == []
    assert _codes(doc)


def test_boolean_text_is_coerced():
    doc = _doc("boolean", "TRUE")
    A.tidy_outcomes(doc)
    assert doc["rules"][0]["then"]["fee"]["value"] is True


def test_outcomes_saved_as_string_by_default_read_as_what_they_hold():
    # every outcome used to be saved as string, numbers in them must not turn into errors
    doc = _doc("string", 4)
    assert not _codes(doc)
    changes = A.tidy_outcomes(doc)
    assert doc["outputs"][0]["type"] == "number"
    assert changes == [{"field": "outcomes[0].type", "from": "string", "to": "number"}]


def test_a_mixed_string_outcome_flags_the_odd_value():
    doc = _doc("string", "stop")
    doc["rules"].append(
        {
            "key": "b",
            "when": {"all": []},
            "then": {"fee": 4},
            "id": "r2",
            "enabled": True,
        }
    )
    found = _codes(doc)
    assert len(found) == 1 and found[0].field == "rules[1].then.fee"


def test_unknown_outcome_type_is_refused():
    doc = _doc("money", 4)
    assert any(p.path == "/outputs/0/type" for p in A.validate_document(doc))


def test_import_infers_outcome_types_from_values():
    doc = I.import_rules(json.loads(GW.read_text()))
    types = {o["field"]: o["type"] for o in doc["outputs"]}
    assert types == {"action": "string", "margin_m": "number", "reason": "string"}
    assert not [p for p in A.validate_document(doc) if p.severity == "error"]


def test_groundwork_file_reads_and_round_trips():
    raw = json.loads(GW.read_text())
    parts = I.read_file(raw)
    assert parts["key"] == "gw.safety.exclusion"
    assert parts["risk_tier"] == "high"
    assert len(parts["doc"]["rules"]) == 5
    assert [t["name"] for t in parts["tests"]] == [t["name"] for t in raw["tests"]]
    assert all(t["as_of"] is None and t["match"] == "exact" for t in parts["tests"])
    assert not A.has_errors(A.validate_document(parts["doc"]))

    model = {k: raw[k] for k in ("key", "name", "description", "risk_tier")}
    out = I.export_file(model, parts["doc"], None, parts["tests"], 1)
    assert out["format"] == I.FILE_FORMAT
    assert out["exported_from_version"] == 1
    # the rules come back exactly as the Groundwork file has them
    assert out["rules"] == raw["rules"]
    for got, want in zip(out["tests"], raw["tests"]):
        assert got["facts"] == want["facts"] and got["expected"] == want["expected"]

    again = I.read_file(json.loads(json.dumps(out)))
    assert again["doc"]["facts"] == parts["doc"]["facts"]
    assert again["doc"]["outputs"] == parts["doc"]["outputs"]
    assert again["doc"]["hit_policy"] == parts["doc"]["hit_policy"]
    second = I.export_file(model, again["doc"], None, again["tests"], 1)
    assert second == out


def test_round_trip_keeps_disabled_rules_types_and_hit_policy():
    doc = _doc("number", 3)
    doc["hit_policy"] = "collect"
    doc["facts"][0]["label"] = "Size"
    doc["rules"][0]["enabled"] = False
    tests = [
        {
            "name": "t",
            "facts": {"x": 2},
            "expected_outcome": "no_match",
            "match": "subset",
            "as_of": "2026-01-01",
        }
    ]
    out = I.export_file(
        {"key": "k", "name": "K", "risk_tier": "medium", "tags": ["a"]},
        doc,
        None,
        tests,
        3,
    )
    assert out["rules"][0]["enabled"] is False
    back = I.read_file(out)
    assert back["doc"]["rules"][0]["enabled"] is False
    assert back["doc"]["hit_policy"] == "collect"
    assert back["doc"]["facts"][0]["label"] == "Size"
    assert back["doc"]["outputs"][0]["type"] == "number"
    assert back["tests"][0] == {**tests[0], "expected": None}
    assert back["tags"] == ["a"]


def test_an_api_envelope_is_unwrapped():
    raw = json.loads(GW.read_text())
    assert I.read_file({"data": raw})["key"] == raw["key"]


def test_flow_only_versions_travel_as_content():
    flow = {"nodes": [{"id": "n"}], "edges": []}
    out = I.export_file({"key": "k", "name": "K"}, None, flow, [], 2)
    assert out["content"] == flow and out["rules"] == []
    back = I.read_file(out)
    assert back["doc"] is None and back["content"] == flow


@pytest.mark.parametrize(
    "bad,path",
    [
        ([], ""),
        ({"key": "k"}, "/rules"),
        ({"rules": "x"}, "/rules"),
        ({"rules": [], "tests": [{"facts": {}}]}, "/tests/0"),
        ({"rules": [], "tests": [{"name": "t", "as_of": "soon"}]}, "/tests/0/as_of"),
        ({"rules": [], "hit_policy": "best"}, "/hit_policy"),
        ({"rules": [], "format": "other-v9"}, "/format"),
    ],
)
def test_a_bad_file_names_the_place(bad, path):
    with pytest.raises(I.InterchangeError) as e:
        I.read_file(bad)
    assert e.value.path == path


def _compiled_with_window(valid_to: str):
    doc = A.normalize(
        {
            "facts": [{"path": "x", "type": "number"}],
            "outputs": [{"field": "ok", "type": "boolean"}],
            "rules": [
                {
                    "key": "a",
                    "when": {"all": [{"fact": "x", "op": "gt", "value": 0}]},
                    "then": {"ok": {"value": True}},
                    "valid_from": "2020-01-01",
                    "valid_to": valid_to,
                }
            ],
        }
    )
    return A.compile_document(doc)


def test_a_test_without_as_of_runs_as_of_today():
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    c = _compiled_with_window(tomorrow)
    tests = [
        {"name": "today", "facts": {"x": 1}, "expected": {"ok": True}, "as_of": None},
        {
            "name": "pinned",
            "facts": {"x": 1},
            "expected": {"ok": True},
            "as_of": "2019-06-01",
        },
    ]
    res = asyncio.run(V.run_tests(c, tests))
    assert res[0]["passed"] is True
    assert res[1]["passed"] is False and res[1]["outcome"] == "no_match"


def test_policy_sentence_reads_plainly():
    assert risk.publish_policy_text(
        "high", risk.DEFAULT_POLICIES["high"]["publish_approvals"]
    ) == ("High risk: one person who did not author it must approve.")
    assert risk.publish_policy_text(
        "critical", risk.DEFAULT_POLICIES["critical"]["publish_approvals"]
    ) == ("Critical risk: two people who did not author it must approve.")
    assert "no sign-off" in risk.publish_policy_text(
        "low", risk.DEFAULT_POLICIES["low"]["publish_approvals"]
    )
    assert "author may be one" in risk.publish_policy_text(
        "medium", {"min_approvers": 1}
    )


def test_file_tests_keep_their_shape_after_copying():
    raw = json.loads(GW.read_text())
    before = copy.deepcopy(raw)
    I.read_file(raw)
    assert raw == before


# an agent keeps working on its own draft


def test_an_agent_finds_its_own_open_draft_only():
    import uuid
    from types import SimpleNamespace

    from engine.decisions import service as S

    me = uuid.uuid4()

    def v(n, state, label, author):
        return SimpleNamespace(
            version=n, state=state, provenance={"proposed_by": label}, author_id=author
        )

    vs = [
        v(2, "draft", "agent Safety Officer", me),
        v(3, "draft", "agent Safety Officer", me),
        v(4, "proposed", "agent Safety Officer", me),
        v(5, "draft", "agent Crane Coordinator", me),
        v(6, "draft", "agent Safety Officer", uuid.uuid4()),
    ]
    assert S.own_open_draft(vs, "agent Safety Officer", str(me)).version == 3
    assert S.own_open_draft(vs, "agent Planner", str(me)) is None


def test_change_notes_only_grow():
    from engine.decisions import service as S

    when = dt.datetime(2026, 10, 10, 14, 1, tzinfo=dt.timezone.utc)
    assert S.append_note(None, "First", when) == "First"
    assert (
        S.append_note("First", "Tightened stop.any to 2 m", when)
        == "First\n2026-10-10 14:01 UTC: Tightened stop.any to 2 m"
    )


def test_rule_change_count():
    from engine.decisions import service as S

    def doc(*rules):
        return {"rules": [{"key": k, "then": {"x": x}} for k, x in rules]}

    assert S.rule_change_count(doc(("a", 1), ("b", 2)), None) == 2
    assert S.rule_change_count(doc(("a", 1), ("c", 3)), doc(("a", 2), ("b", 2))) == 3


def test_create_proposal_updates_the_agents_draft():
    import inspect

    from engine.decisions import service as S

    src = inspect.getsource(S.create_proposal)
    assert "own_open_draft(versions, actor_label, actor_id)" in src
    assert "append_note(v.change_note, note, now)" in src
    assert "v.risk_tier_at_proposal = m.risk_tier" in src
    assert '"updated_own_draft": own is not None' in src


def test_a_second_proposal_from_the_same_agent_updates_its_draft():
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from engine.decisions import service as S
    from models.decision import DecisionVersion

    me = str(uuid.uuid4())
    model = SimpleNamespace(
        id=uuid.uuid4(), key="gw.safety.exclusion", name="Exclusion", risk_tier="high"
    )
    draft = DecisionVersion(
        id=uuid.uuid4(),
        version=2,
        state="draft",
        provenance={"proposed_by": "agent Safety Officer"},
        author_id=uuid.UUID(me),
        change_note="First try",
        lock_version=1,
    )
    published = DecisionVersion(
        id=uuid.uuid4(),
        version=1,
        state="published",
        superseded_at=None,
        authoring=None,
    )

    class Db:
        def __init__(self):
            self.added = []

        async def execute(self, stmt):
            ent = getattr(stmt.column_descriptions[0].get("entity"), "__name__", "")
            rows = {
                "DecisionModel": [model],
                "DecisionVersion": [published, draft],
            }.get(ent, [])
            return SimpleNamespace(
                scalar_one_or_none=lambda: rows[0] if rows else None,
                scalars=lambda: SimpleNamespace(all=lambda: rows),
            )

        def add(self, obj):
            self.added.append(obj)

        async def flush(self):
            for o in self.added:
                if getattr(o, "id", None) is None:
                    o.id = uuid.uuid4()

        async def commit(self):
            return None

    rules = [
        {
            "ruleKey": "stop.any",
            "when": {"all": [{"lt": [{"fact": "worker.clearance_m"}, 2]}]},
            "then": {"action": "stop"},
        }
    ]
    db = Db()
    with patch.object(S, "reference_values", AsyncMock(return_value=({}, {}))):
        out = asyncio.run(
            S.create_proposal(
                db,
                str(uuid.uuid4()),
                "gw.safety.exclusion",
                rules,
                note="Tightened stop.any to 2 m",
                actor_id=me,
                actor_label="agent Safety Officer",
            )
        )
    assert out["updated_own_draft"] is True and out["version"] == 2
    assert not [o for o in db.added if isinstance(o, DecisionVersion)]
    assert draft.change_note.startswith("First try\n") and draft.change_note.endswith(
        "Tightened stop.any to 2 m"
    )
    assert (
        draft.state == "proposed"
        and draft.risk_tier_at_proposal == "high"
        and draft.lock_version == 2
    )
    approval = next(o for o in db.added if o.__class__.__name__ == "Approval")
    assert (
        approval.payload["change_note"] == draft.change_note
        and approval.payload["changes"] == 1
    )
