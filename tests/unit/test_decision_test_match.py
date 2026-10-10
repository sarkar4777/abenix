"""Golden tests can match the expected result exactly or as a subset."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from app.routers import decisions as D
from engine.decisions import validation as V


def run(coro):
    return asyncio.run(coro)


def test_exact_needs_the_whole_result():
    got = {"tier": "gold", "limit": 5000, "reason": "long tenure"}
    assert V.result_matches(
        {"tier": "gold", "limit": 5000, "reason": "long tenure"}, got
    )
    assert not V.result_matches({"tier": "gold"}, got)
    assert not V.result_matches({"tier": "gold"}, got, "exact")


def test_subset_ignores_extra_keys_but_not_wrong_values():
    got = {"tier": "gold", "limit": 5000, "meta": {"src": "rule-a", "score": 0.9}}
    assert V.result_matches({"tier": "gold"}, got, "subset")
    assert V.result_matches({"meta": {"src": "rule-a"}}, got, "subset")
    assert V.result_matches({}, got, "subset")
    assert not V.result_matches({"tier": "silver"}, got, "subset")
    assert not V.result_matches({"missing": None}, got, "subset")
    assert not V.result_matches({"meta": {"src": "rule-b"}}, got, "subset")


def test_subset_compares_lists_and_scalars_exactly():
    assert V.result_matches({"codes": [1, 2]}, {"codes": [1, 2], "x": 1}, "subset")
    assert not V.result_matches({"codes": [1]}, {"codes": [1, 2]}, "subset")
    assert V.result_matches([1, 2], [1, 2], "subset")
    assert not V.result_matches({"a": 1}, [1], "subset")


class _Ev:
    def __init__(self, outcome, result):
        self.outcome = outcome
        self.result = result
        self.missing_facts = []
        self.invalid_facts = []
        self.applied_rules = ["r1"]


def test_run_tests_honours_each_tests_match(monkeypatch):
    async def fake_eval(*a, **k):
        return _Ev("decided", {"tier": "gold", "limit": 5000})

    monkeypatch.setattr(V.evaluator, "evaluate", fake_eval)
    compiled = SimpleNamespace(
        content_hash="h", jdm={}, required_facts=[], fact_types={}
    )
    tests = [
        {
            "id": "a",
            "name": "exact old style",
            "facts": {},
            "expected": {"tier": "gold"},
        },
        {
            "id": "b",
            "name": "subset",
            "facts": {},
            "expected": {"tier": "gold"},
            "match": "subset",
        },
        {
            "id": "c",
            "name": "subset wrong",
            "facts": {},
            "expected": {"tier": "x"},
            "match": "subset",
        },
    ]
    res = run(V.run_tests(compiled, tests))
    by = {r["test_id"]: r for r in res}
    assert by["a"]["passed"] is False and by["a"]["match"] == "exact"
    assert by["b"]["passed"] is True and by["b"]["match"] == "subset"
    assert by["c"]["passed"] is False


class _DB:
    def __init__(self, existing=None):
        self.added = []
        self.existing = existing

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass

    async def get(self, cls, ident):
        return self.existing


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())


def _body(resp):
    return json.loads(bytes(resp.body))


@pytest.fixture
def model(monkeypatch):
    m = SimpleNamespace(id=uuid.uuid4())

    async def fake_model(db, user, key):
        return m

    monkeypatch.setattr(D, "_model", fake_model)
    return m


def test_new_tests_default_to_exact(model):
    db = _DB()
    resp = run(
        D.add_test(
            "k", D.TestBody(name="t", facts={"a": 1}, expected={"x": 1}), _user(), db
        )
    )
    assert resp.status_code == 201
    assert db.added[0].match_mode == "exact"
    assert _body(resp)["data"]["match"] == "exact"


def test_create_with_subset(model):
    db = _DB()
    body = D.TestBody(name="t", facts={}, expected={"x": 1}, match="subset")
    resp = run(D.add_test("k", body, _user(), db))
    assert resp.status_code == 201
    assert db.added[0].match_mode == "subset"


@pytest.mark.parametrize(
    "fields, msg",
    [
        ({"match": "fuzzy", "expected": {"x": 1}}, "match must be exact or subset"),
        ({"match": "subset", "expected": [1, 2]}, "JSON object"),
    ],
)
def test_bad_match_refused(model, fields, msg):
    resp = run(D.add_test("k", D.TestBody(name="t", **fields), _user(), _DB()))
    assert resp.status_code == 400
    assert msg in json.dumps(_body(resp))


def test_subset_with_another_outcome_ignores_the_expected_shape(model):
    body = D.TestBody(
        name="t", expected_outcome="no_match", expected=[1], match="subset"
    )
    assert run(D.add_test("k", body, _user(), _DB())).status_code == 201


def test_update_keeps_match_unless_sent(model):
    t = SimpleNamespace(
        id=uuid.uuid4(),
        model_id=model.id,
        name="t",
        facts={},
        expected_outcome="decided",
        expected={"x": 1},
        match_mode="subset",
        as_of=None,
        updated_at=None,
    )
    db = _DB(existing=t)
    resp = run(
        D.update_test(
            "k", t.id, D.TestBody(name="renamed", expected={"x": 2}), _user(), db
        )
    )
    assert resp.status_code == 200
    assert t.match_mode == "subset" and t.name == "renamed"
    resp = run(
        D.update_test(
            "k",
            t.id,
            D.TestBody(name="renamed", expected={"x": 2}, match="exact"),
            _user(),
            db,
        )
    )
    assert t.match_mode == "exact"
    assert _body(resp)["data"]["match"] == "exact"
