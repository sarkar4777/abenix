"""decision_evaluate inside a run: always recorded, linked to the run, and summarised on the tool call."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

_RUNTIME = Path(__file__).resolve().parents[1]
_DB = str(Path(__file__).resolve().parents[3] / "packages" / "db")
for _p in (str(_RUNTIME), _DB):
    if _p not in sys.path:
        sys.path.append(_p)

from engine import governance  # noqa: E402
from engine.decisions import db as ddb  # noqa: E402
from engine.decisions import service as S  # noqa: E402
from engine.pipeline import (
    NodeResult,
    PipelineResult,
    serialize_pipeline_result,
)  # noqa: E402
from engine.tools.base import ToolResult  # noqa: E402
from engine.tools.decision_tools import DecisionEvaluateTool  # noqa: E402

TENANT = str(uuid.uuid4())
VERSION_ID = str(uuid.uuid4())
RULES = [
    {
        "id": "r1",
        "key": "freight.remote.surcharge",
        "description": "Remote postcodes above 50 kg",
        "provenance": {"citations": ["Carrier tariff 2026, section 4.2"]},
    }
]
FACTS = {"shipment": {"postcode": "IV27", "weightKg": 120}}


def _out(outcome="decided", **kw):
    base = {
        "decision": {
            "key": "freight.surcharge",
            "name": "Surcharge",
            "risk_tier": "low",
        },
        "version": {"id": VERSION_ID, "version": 3},
        "as_of": "2026-03-14",
        "known_at": None,
        "outcome": outcome,
        "result": {"surcharge": "REMOTE_AREA_SURCHARGE"},
        "applied_rules": ["freight.remote.surcharge"],
        "missing_facts": [],
        "invalid_facts": [],
        "normalised": [],
        "trace": [
            {
                "rule_id": "r1",
                "description": "Remote postcodes above 50 kg",
                "values_seen": {},
            }
        ],
        "trace_hash": "a" * 64,
        "duration_us": 42,
    }
    base.update(kw)
    return base


@pytest.fixture
def calls(monkeypatch):
    seen: list[dict] = []

    async def fake_evaluate(db, tenant, key, facts, **kw):
        seen.append({"tenant": tenant, "key": key, "facts": facts, **kw})
        out = _out()
        if kw.get("persist"):
            out["evaluation_id"] = "e-1"
        return out

    async def fake_rules(db, vid):
        return RULES

    @asynccontextmanager
    async def fake_session():
        yield object()

    monkeypatch.setattr(S, "evaluate", fake_evaluate)
    monkeypatch.setattr(S, "version_rules", fake_rules)
    monkeypatch.setattr(ddb, "session", fake_session)
    return seen


def _run(tool, args):
    return asyncio.run(tool.execute(args))


def test_in_a_run_the_evaluation_is_always_recorded_and_linked(calls):
    tool = DecisionEvaluateTool(
        tenant_id=TENANT,
        execution_id="exec-9",
        user_id="u-1",
        agent_name="Surcharge Desk",
    )
    res = _run(tool, {"decision": "freight.surcharge", "facts": FACTS})
    assert not res.is_error
    assert calls[0]["persist"] is True
    assert calls[0]["caller"] == {
        "execution_id": "exec-9",
        "agent": "Surcharge Desk",
        "user_id": "u-1",
        "tool": "decision_evaluate",
    }
    assert res.metadata["evaluation_id"] == "e-1"
    assert res.metadata["decision_record"]["evaluation_id"] == "e-1"


def test_outside_a_run_nothing_is_recorded_unless_asked(calls):
    tool = DecisionEvaluateTool(tenant_id=TENANT)
    _run(tool, {"decision": "freight.surcharge", "facts": FACTS})
    _run(tool, {"decision": "freight.surcharge", "facts": FACTS, "record": True})
    assert [c["persist"] for c in calls] == [False, True]


def test_an_explicit_record_false_still_wins_in_a_run(calls):
    tool = DecisionEvaluateTool(tenant_id=TENANT, execution_id="exec-9")
    res = _run(tool, {"decision": "freight.surcharge", "facts": FACTS, "record": False})
    assert calls[0]["persist"] is False
    assert res.metadata["decision_record"]["evaluation_id"] is None


def test_the_run_context_supplies_the_execution_when_the_tool_was_built_without_one(
    calls,
):
    ctx = governance.RunContext(
        tenant_id=TENANT,
        execution_id="exec-p",
        agent_name="pipeline p1",
        scope="pipeline",
    )
    token = governance.begin_run(ctx)
    try:
        _run(
            DecisionEvaluateTool(tenant_id=TENANT),
            {"decision": "freight.surcharge", "facts": FACTS},
        )
    finally:
        governance.end_run(token)
    assert calls[0]["persist"] is True
    assert calls[0]["caller"]["execution_id"] == "exec-p"
    assert calls[0]["caller"]["source"] == "pipeline"
    assert calls[0]["caller"]["agent"] == "pipeline p1"


def test_metadata_carries_an_untruncated_summary(calls):
    res = _run(
        DecisionEvaluateTool(tenant_id=TENANT, execution_id="x"),
        {"decision": "freight.surcharge", "facts": FACTS, "as_of": "2026-03-14"},
    )
    rec = res.metadata["decision_record"]
    assert rec["key"] == "freight.surcharge" and rec["name"] == "Surcharge"
    assert rec["version"] == 3 and rec["version_id"] == VERSION_ID
    assert rec["outcome"] == "decided"
    assert rec["result"] == {"surcharge": "REMOTE_AREA_SURCHARGE"}
    assert rec["applied_rules"] == [
        {
            "key": "freight.remote.surcharge",
            "id": "r1",
            "description": "Remote postcodes above 50 kg",
            "citations": ["Carrier tariff 2026, section 4.2"],
        }
    ]
    assert rec["trace_hash"] == "a" * 64 and rec["duration_us"] == 42
    assert rec["as_of"] == "2026-03-14" and rec["facts"] == FACTS
    # the old flat keys stay for existing readers
    assert (
        res.metadata["decision"] == "freight.surcharge" and res.metadata["version"] == 3
    )


def test_summary_is_bounded():
    big = {"rows": ["x" * 100] * 200}
    rec = S.evaluation_summary(_out(result=big), RULES, {"blob": "y" * 10_000})
    assert rec["result_truncated"] is True and len(rec["result"]) == S.SUMMARY_CAP
    assert rec["facts"] is None and rec["facts_truncated"] is True
    assert len(json.dumps(rec)) < 3 * S.SUMMARY_CAP


def test_summary_explains_missing_facts():
    out = _out(
        "missing_facts",
        result=None,
        applied_rules=[],
        trace=[],
        trace_hash="",
        missing_facts=["shipment.weightKg"],
        next_step="Gather these facts and call decision_evaluate again: shipment.weightKg",
    )
    rec = S.evaluation_summary(out, RULES, FACTS)
    assert rec["missing_facts"] == ["shipment.weightKg"]
    assert "shipment.weightKg" in rec["explanation"]
    assert rec["applied_rules"] == []


def test_rule_details_fall_back_to_the_trace_for_flow_authored_versions():
    got = S.applied_rule_details(
        [], ["r9"], [{"rule_id": "r9", "description": "From the flow"}]
    )
    assert got == [
        {"key": "r9", "id": "", "description": "From the flow", "citations": []}
    ]


def test_executor_puts_the_record_on_the_tool_call():
    from engine.agent_executor import _attach_decision_record

    tc: dict = {"name": "decision_evaluate"}
    _attach_decision_record(
        tc, ToolResult(content="{}", metadata={"decision_record": {"key": "k"}})
    )
    assert tc["decision_record"] == {"key": "k"}
    other: dict = {"name": "web_search"}
    _attach_decision_record(other, ToolResult(content="{}", metadata={}))
    assert "decision_record" not in other


def test_consumer_keeps_the_record_for_agent_and_pipeline_tool_calls():
    import consumer

    tcs = [{"name": "decision_evaluate", "arguments": {}}]
    consumer._merge_tool_trace(
        tcs,
        {
            "node_type": "tool_call",
            "tool": "decision_evaluate",
            "duration_ms": 3,
            "metadata": {"decision_record": {"key": "k"}},
        },
    )
    assert tcs[0]["decision_record"] == {"key": "k"}

    result = PipelineResult(status="completed")
    result.node_results["decide"] = NodeResult(
        node_id="decide",
        status="completed",
        output={"outcome": "decided"},
        tool_name="decision_evaluate",
        resolved_arguments={"decision": "k", "facts": FACTS},
        metadata={"decision_record": {"key": "k"}},
    )
    result.execution_path = ["decide"]
    ser = serialize_pipeline_result(result)
    assert ser["node_results"]["decide"]["resolved_arguments"]["facts"] == FACTS
    assert ser["steps"][0]["metadata"]["decision_record"] == {"key": "k"}
    pcs = consumer._pipeline_tool_calls(ser["node_results"])
    assert pcs[0]["decision_record"] == {"key": "k"}
    assert pcs[0]["arguments"]["decision"] == "k"


def test_explain_in_a_run_is_recorded_too(calls, monkeypatch):
    from engine.tools import decision_tools as DT

    async def no_details(*a, **kw):
        return {}

    monkeypatch.setattr(DT, "_rule_details", no_details)
    res = _run(
        DT.DecisionExplainTool(tenant_id=TENANT, execution_id="exec-9"),
        {"decision": "freight.surcharge", "facts": FACTS},
    )
    assert calls[0]["persist"] is True
    assert calls[0]["caller"]["tool"] == "decision_explain"
    assert res.metadata["decision_record"]["evaluation_id"] == "e-1"
    assert "REMOTE_AREA_SURCHARGE" in res.content
