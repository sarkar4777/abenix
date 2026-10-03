"""GET /api/decisions/{key}/evaluations and the evaluation detail with its replayed trace."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import uuid
from types import SimpleNamespace

import pytest

pytest.importorskip("zen")

from app.routers import decisions as R  # noqa: E402
from engine.decisions import authoring as A  # noqa: E402
from engine.decisions import evaluator as E  # noqa: E402
from engine.decisions import interchange as I  # noqa: E402

TENANT = uuid.uuid4()
MODEL = SimpleNamespace(id=uuid.uuid4(), key="freight.surcharge", log_mode="none")
V3 = uuid.uuid4()
RULE = {
    "ruleKey": "freight.remote.surcharge",
    "requiresFacts": ["shipment.postcode", "shipment.weightKg"],
    "when": {
        "all": [
            {"inReferenceSet": [{"fact": "shipment.postcode"}, "REMOTE"]},
            {"gt": [{"fact": "shipment.weightKg"}, 50]},
        ]
    },
    "then": {"surcharge": "REMOTE_AREA_SURCHARGE"},
    "provenance": {"citations": ["Carrier tariff 2026, section 4.2"]},
}
FACTS = {"shipment": {"postcode": "IV27", "weightKg": 120}}


class Result:
    def __init__(self, value=None, rows=None):
        self.value = value
        self.rows = rows or []

    def scalar_one_or_none(self):
        return self.value

    def all(self):
        return self.rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.statements: list = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return self.results.pop(0) if self.results else Result()


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT, email="a@b.test")


def _row(**kw):
    base = dict(
        id=1,
        public_id=uuid.uuid4(),
        version_id=V3,
        outcome="decided",
        facts=FACTS,
        result={"surcharge": "REMOTE_AREA_SURCHARGE"},
        applied_rules=["freight.remote.surcharge"],
        trace_hash="h",
        as_of="2026-03-14",
        known_at=None,
        content_hash="c",
        caller={
            "execution_id": "exec-1",
            "agent": "Surcharge Desk",
            "tool": "decision_evaluate",
        },
        created_at=dt.datetime(2026, 10, 3, 9, 0, tzinfo=dt.timezone.utc),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _body(resp):
    return json.loads(resp.body)


def _list(db, **kw):
    params = dict(limit=25, offset=0, outcome=None, execution_id=None, version=None)
    params.update(kw)
    return asyncio.run(
        R.list_evaluations("freight.surcharge", user=_user(), db=db, **params)
    )


def test_lists_with_version_numbers_counts_and_run_links():
    db = FakeSession(
        Result(MODEL),
        Result(rows=[(V3, 3)]),
        Result(rows=[("decided", 4), ("missing_facts", 1)]),
        Result(rows=[_row()]),
    )
    body = _body(_list(db))
    row = body["data"][0]
    assert row["version"] == 3 and row["execution_id"] == "exec-1"
    assert row["caller"]["agent"] == "Surcharge Desk"
    assert body["meta"]["total"] == 5
    assert body["meta"]["counts"] == {"decided": 4, "missing_facts": 1}


def test_filters_by_outcome_run_and_version_inside_the_tenant():
    db = FakeSession(
        Result(MODEL),
        Result(rows=[(V3, 3)]),
        Result(rows=[("decided", 4), ("missing_facts", 1)]),
        Result(rows=[]),
    )
    body = _body(_list(db, outcome="missing_facts", execution_id="exec-1", version=3))
    assert body["meta"]["total"] == 1
    sql = str(db.statements[-1].compile(compile_kwargs={"literal_binds": False}))
    assert "decision_evaluations.tenant_id" in sql
    assert "decision_evaluations.caller ->>" in sql
    assert "decision_evaluations.version_id" in sql
    assert "decision_evaluations.outcome" in sql


def test_refuses_an_unknown_outcome_and_version():
    resp = _list(FakeSession(Result(MODEL)), outcome="maybe")
    assert resp.status_code == 400
    resp = _list(FakeSession(Result(MODEL), Result(rows=[(V3, 3)])), version=9)
    assert resp.status_code == 404


def test_an_unknown_decision_is_404():
    assert _list(FakeSession(Result(None))).status_code == 404


def _version():
    doc = I.import_rules(RULE)
    c = A.compile_document(doc, {"REMOTE": ["IV27", "HS2"]})
    return (
        SimpleNamespace(
            id=V3,
            version=3,
            authoring=doc,
            content=c.jdm,
            content_hash=c.content_hash,
            required_facts=c.required_facts,
            fact_types=c.fact_types,
        ),
        c,
    )


def test_detail_replays_the_trace_and_proves_the_record():
    v, c = _version()
    ev = asyncio.run(
        E.evaluate(
            c.content_hash,
            c.jdm,
            FACTS,
            required=c.required_facts,
            fact_types=c.fact_types,
            as_of="2026-03-14",
        )
    )
    row = _row(
        trace_hash=ev.trace_hash, applied_rules=ev.applied_rules, result=ev.result
    )
    db = FakeSession(Result(MODEL), Result(row), Result(v))
    body = _body(
        asyncio.run(
            R.get_evaluation(
                "freight.surcharge", str(row.public_id), user=_user(), db=db
            )
        )
    )["data"]
    assert body["version"] == 3 and body["execution_id"] == "exec-1"
    assert body["replay"]["reproduced"] is True
    assert body["replay"]["trace"]
    assert body["applied"][0]["key"] == "freight.remote.surcharge"
    assert body["applied"][0]["citations"] == ["Carrier tariff 2026, section 4.2"]


def test_detail_says_when_the_replay_differs():
    v, _ = _version()
    row = _row(trace_hash="not-the-same")
    db = FakeSession(Result(MODEL), Result(row), Result(v))
    body = _body(
        asyncio.run(
            R.get_evaluation(
                "freight.surcharge", str(row.public_id), user=_user(), db=db
            )
        )
    )["data"]
    assert body["replay"]["reproduced"] is False


def test_detail_of_a_missing_or_malformed_id_is_404():
    resp = asyncio.run(
        R.get_evaluation(
            "freight.surcharge", "nope", user=_user(), db=FakeSession(Result(MODEL))
        )
    )
    assert resp.status_code == 404
    resp = asyncio.run(
        R.get_evaluation(
            "freight.surcharge",
            str(uuid.uuid4()),
            user=_user(),
            db=FakeSession(Result(MODEL), Result(None)),
        )
    )
    assert resp.status_code == 404
