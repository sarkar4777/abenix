"""Decision tools: agents and pipelines evaluate published business rules and can propose changes."""

from __future__ import annotations

import json
from typing import Any

from engine import credentials
from engine.tools.base import BaseTool, ToolResult


class _DecisionTool(BaseTool):
    input_schema: dict[str, Any] = {"type": "object"}

    def __init__(
        self,
        tenant_id: str = "",
        execution_id: str = "",
        user_id: str = "",
        agent_name: str = "",
    ) -> None:
        self.tenant_id = tenant_id
        self._execution_id = execution_id
        self._user_id = user_id
        self._agent_name = agent_name

    def _tenant(self) -> str:
        return str(self.tenant_id or credentials.current_tenant() or "")

    def _run_ctx(self) -> Any:
        from engine import governance

        return governance.current()

    def _execution(self) -> str:
        ctx = self._run_ctx()
        return str(self._execution_id or (ctx.execution_id if ctx else "") or "")

    def _caller(self) -> dict[str, Any]:
        ctx = self._run_ctx()
        caller = {
            "execution_id": self._execution(),
            "agent": self._agent_name or (ctx.agent_name if ctx else "") or "",
            "user_id": self._user_id,
            "tool": self.name,
        }
        if ctx is not None:
            caller["source"] = "pipeline" if ctx.scope == "pipeline" else "agent"
        return caller

    def _should_record(self, arguments: dict[str, Any]) -> bool:
        record = arguments.get("record")
        # every evaluation inside a run is kept, so the Flight Recorder can point at it
        return bool(self._execution()) if record is None else bool(record)

    @staticmethod
    def _ok(payload: Any, **meta: Any) -> ToolResult:
        return ToolResult(
            content=json.dumps(payload, default=str, ensure_ascii=False), metadata=meta
        )

    @staticmethod
    def _fail(message: str, **meta: Any) -> ToolResult:
        return ToolResult(content=message, is_error=True, metadata=meta)

    async def _run(self, fn) -> ToolResult:
        from engine.decisions import db as ddb
        from engine.decisions.service import DecisionError

        if not self._tenant():
            return self._fail("No tenant in context, decisions cannot be read.")
        try:
            async with ddb.session() as s:
                return await fn(s)
        except DecisionError as e:
            return self._fail(e.message, error_code=e.code)


_FACTS_DOC = 'Facts as a nested object. Paths such as shipment.postcode mean {"shipment": {"postcode": ...}}.'


class DecisionListTool(_DecisionTool):
    name = "decision_list"
    risk_tier = "low"
    description = (
        "List the business rule decisions this tenant has published, with the facts each one needs and "
        "their types. Call this first to find the right decision key and the facts to gather."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional words to filter by name or key",
            }
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from sqlalchemy import select

        from models.decision import DecisionModel, DecisionVersion

        q = str(arguments.get("query") or "").strip().lower()

        async def go(s):
            import uuid

            rows = (
                (
                    await s.execute(
                        select(DecisionModel).where(
                            DecisionModel.tenant_id == uuid.UUID(self._tenant()),
                            DecisionModel.archived_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            out = []
            for m in rows:
                if q and q not in m.name.lower() and q not in m.key.lower():
                    continue
                live = (
                    (
                        await s.execute(
                            select(DecisionVersion)
                            .where(
                                DecisionVersion.model_id == m.id,
                                DecisionVersion.state == "published",
                                DecisionVersion.superseded_at.is_(None),
                            )
                            .order_by(DecisionVersion.version.desc())
                        )
                    )
                    .scalars()
                    .all()
                )
                if not live:
                    continue
                v = live[0]
                out.append(
                    {
                        "key": m.key,
                        "name": m.name,
                        "description": m.description,
                        "risk_tier": m.risk_tier,
                        "version": v.version,
                        "required_facts": v.required_facts,
                        "fact_types": v.fact_types,
                        "outputs": [
                            o.get("field")
                            for o in ((v.authoring or {}).get("outputs") or [])
                        ],
                    }
                )
            return self._ok({"decisions": out, "count": len(out)})

        return await self._run(go)


class DecisionEvaluateTool(_DecisionTool):
    name = "decision_evaluate"
    risk_tier = "low"
    description = (
        "Evaluate a published business rule decision against facts and get a deterministic result, the rules "
        "that applied, and a trace. If facts are missing or have the wrong type it says which, instead of "
        "guessing. Use as_of for a past or future date and known_at to see what was in force as known then."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "description": "The decision key, from decision_list",
            },
            "facts": {"type": "object", "description": _FACTS_DOC},
            "as_of": {
                "type": "string",
                "description": "The date the activity happens, like 2026-03-01. Default today.",
            },
            "known_at": {
                "type": "string",
                "description": "Optional. Evaluate with the rules as they were known on this date.",
            },
            "record": {
                "type": "boolean",
                "description": "Keep an auditable record of this evaluation. Inside an agent or pipeline run it is kept unless this is false.",
            },
        },
        "required": ["decision", "facts"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from engine.decisions import service as S

        key = str(arguments.get("decision") or "").strip()
        if not key:
            return self._fail(
                "Say which decision to evaluate. decision_list shows the keys."
            )

        persist = self._should_record(arguments)
        facts = arguments.get("facts") or {}

        async def go(s):
            out = await S.evaluate(
                s,
                self._tenant(),
                key,
                facts,
                as_of=arguments.get("as_of"),
                known_at=arguments.get("known_at"),
                persist=persist,
                caller=self._caller(),
            )
            if out["outcome"] == "missing_facts":
                out["next_step"] = (
                    "Gather these facts and call decision_evaluate again: "
                    + ", ".join(out["missing_facts"])
                )
            elif out["outcome"] == "invalid_facts":
                out["next_step"] = (
                    "Correct the types of these facts and call again: "
                    + ", ".join(
                        f"{x['fact']} should be {x['expected']}"
                        for x in out["invalid_facts"]
                    )
                )
            rules = await S.version_rules(s, out["version"]["id"])
            return self._ok(
                out,
                decision=key,
                outcome=out["outcome"],
                trace_hash=out.get("trace_hash"),
                version=out["version"]["version"],
                evaluation_id=out.get("evaluation_id"),
                decision_record=S.evaluation_summary(out, rules, facts),
            )

        return await self._run(go)


class DecisionCompareTool(_DecisionTool):
    name = "decision_compare"
    risk_tier = "low"
    description = (
        "Evaluate the same facts under several rule versions or dates and report what changes, for example "
        "this year's rules against next year's, or a planning version against the assured one."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "decision": {"type": "string"},
            "facts": {"type": "object", "description": _FACTS_DOC},
            "targets": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "version": {"type": "integer"},
                        "as_of": {"type": "string"},
                        "known_at": {"type": "string"},
                    },
                },
            },
        },
        "required": ["decision", "facts", "targets"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from engine.decisions import service as S

        key = str(arguments.get("decision") or "")
        targets = arguments.get("targets") or []
        if len(targets) < 2:
            return self._fail("Give at least two targets to compare.")

        async def go(s):
            rows = []
            for t in targets[:10]:
                label = t.get("label") or (
                    f"version {t['version']}"
                    if t.get("version")
                    else f"on {t.get('as_of') or 'today'}"
                )
                try:
                    r = await S.evaluate(
                        s,
                        self._tenant(),
                        key,
                        arguments.get("facts") or {},
                        as_of=t.get("as_of"),
                        known_at=t.get("known_at"),
                        version=t.get("version"),
                        want_trace=False,
                    )
                    rows.append(
                        {
                            "label": label,
                            "outcome": r["outcome"],
                            "result": r["result"],
                            "applied_rules": r["applied_rules"],
                            "version": r["version"]["version"],
                            "missing_facts": r["missing_facts"],
                        }
                    )
                except S.DecisionError as e:
                    rows.append(
                        {"label": label, "outcome": "error", "error": e.message}
                    )
            base = json.dumps(
                [rows[0].get("outcome"), rows[0].get("result")],
                sort_keys=True,
                default=str,
            )
            for r in rows[1:]:
                r["differs_from_first"] = (
                    json.dumps(
                        [r.get("outcome"), r.get("result")], sort_keys=True, default=str
                    )
                    != base
                )
            return self._ok({"decision": key, "results": rows})

        return await self._run(go)


class DecisionExplainTool(_DecisionTool):
    name = "decision_explain"
    risk_tier = "low"
    description = (
        "Explain in plain words why a decision came out the way it did for these facts: which rules applied, "
        "the values they looked at, and the sources cited for each rule."
    )
    input_schema = DecisionEvaluateTool.input_schema

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from engine.decisions import service as S

        key = str(arguments.get("decision") or "")
        facts = arguments.get("facts") or {}
        persist = self._should_record(arguments)

        async def go(s):
            r = await S.evaluate(
                s,
                self._tenant(),
                key,
                facts,
                as_of=arguments.get("as_of"),
                known_at=arguments.get("known_at"),
                persist=persist,
                caller=self._caller(),
            )
            lines = [
                f"{r['decision']['name']} version {r['version']['version']}, for {r['as_of']}."
            ]
            if r["outcome"] == "missing_facts":
                lines.append(
                    "It cannot decide yet. Missing facts: "
                    + ", ".join(r["missing_facts"])
                    + "."
                )
            elif r["outcome"] == "invalid_facts":
                lines.append(
                    "It cannot decide. These facts have the wrong type: "
                    + ", ".join(
                        f"{x['fact']} (expected {x['expected']})"
                        for x in r["invalid_facts"]
                    )
                    + "."
                )
            elif r["outcome"] == "no_match":
                lines.append(
                    "No rule applies to these facts, so nothing is required by this decision."
                )
            else:
                lines.append(f"Result: {json.dumps(r['result'], ensure_ascii=False)}.")
                rules = await _rule_details(
                    s, self._tenant(), key, r["version"]["version"]
                )
                for step in r["trace"]:
                    rd = rules.get(step["rule_id"], {})
                    seen = ", ".join(
                        f"{k} = {json.dumps(v, ensure_ascii=False)}"
                        for k, v in step["values_seen"].items()
                    )
                    text = f"Rule {rd.get('key') or step['rule_id']} applied"
                    if rd.get("description"):
                        text += f" ({rd['description']})"
                    if seen:
                        text += f", looking at {seen}"
                    cites = (rd.get("provenance") or {}).get("citations") or []
                    if cites:
                        text += f". Sources: {', '.join(map(str, cites))}"
                    lines.append(text + ".")
            for n in r.get("normalised") or []:
                lines.append(f"Note: {n['fact']} was read as {json.dumps(n['to'])}.")
            lines.append(
                f"Trace hash {r['trace_hash']}." if r.get("trace_hash") else ""
            )
            return ToolResult(
                content="\n".join(x for x in lines if x),
                metadata={
                    "decision": key,
                    "outcome": r["outcome"],
                    "evaluation_id": r.get("evaluation_id"),
                    "decision_record": S.evaluation_summary(
                        r, await S.version_rules(s, r["version"]["id"]), facts
                    ),
                },
            )

        return await self._run(go)


async def _rule_details(
    s, tenant_id: str, key: str, version: int
) -> dict[str, dict[str, Any]]:
    import uuid

    from sqlalchemy import select

    from models.decision import DecisionModel, DecisionVersion

    v = (
        await s.execute(
            select(DecisionVersion)
            .join(DecisionModel, DecisionModel.id == DecisionVersion.model_id)
            .where(
                DecisionModel.tenant_id == uuid.UUID(tenant_id),
                DecisionModel.key == key,
                DecisionVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    rules = ((v.authoring or {}).get("rules") or []) if v else []
    return {r.get("id"): r for r in rules}


class DecisionTestTool(_DecisionTool):
    name = "decision_test"
    risk_tier = "low"
    description = (
        "Run a decision's golden test cases against a version and report which pass."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "decision": {"type": "string"},
            "version": {
                "type": "integer",
                "description": "Default is the latest version",
            },
        },
        "required": ["decision"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        import uuid

        from sqlalchemy import select

        from engine.decisions import validation as V
        from engine.decisions.authoring import Compiled
        from engine.decisions.service import DecisionError
        from models.decision import DecisionModel, DecisionTest, DecisionVersion

        key = str(arguments.get("decision") or "")

        async def go(s):
            m = (
                await s.execute(
                    select(DecisionModel).where(
                        DecisionModel.tenant_id == uuid.UUID(self._tenant()),
                        DecisionModel.key == key,
                    )
                )
            ).scalar_one_or_none()
            if m is None:
                raise DecisionError(
                    "NOT_FOUND", f"There is no decision called {key}.", 404
                )
            q = select(DecisionVersion).where(DecisionVersion.model_id == m.id)
            if arguments.get("version"):
                q = q.where(DecisionVersion.version == int(arguments["version"]))
            v = (
                await s.execute(q.order_by(DecisionVersion.version.desc()).limit(1))
            ).scalar_one_or_none()
            if v is None:
                raise DecisionError("NOT_FOUND", f"{key} has no such version.", 404)
            tests = (
                (
                    await s.execute(
                        select(DecisionTest).where(DecisionTest.model_id == m.id)
                    )
                )
                .scalars()
                .all()
            )
            res = await V.run_tests(
                Compiled(
                    jdm=v.content,
                    content_hash=v.content_hash,
                    required_facts=v.required_facts,
                    fact_types=v.fact_types,
                ),
                [
                    {
                        "id": str(t.id),
                        "name": t.name,
                        "facts": t.facts,
                        "expected_outcome": t.expected_outcome,
                        "expected": t.expected,
                        "as_of": t.as_of,
                    }
                    for t in tests
                ],
            )
            return self._ok(
                {
                    "decision": key,
                    "version": v.version,
                    "total": len(res),
                    "failed": [r for r in res if not r["passed"]],
                    "passed": sum(r["passed"] for r in res),
                }
            )

        return await self._run(go)


class DecisionProposeTool(_DecisionTool):
    name = "decision_propose"
    # writes a proposal that people must approve, it never publishes
    risk_tier = "medium"
    description = (
        "Propose new or changed business rules for a decision, as typed JSON rules with ruleKey, requiresFacts, "
        'when (all/any conditions such as {"gte": [{"fact": "shipment.date"}, "2026-01-01"]}), then and '
        "provenance with citations. The proposal is validated and golden tested, then waits for people to "
        "approve it. Agents cannot publish."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "decision": {"type": "string"},
            "rules": {
                "description": "One rule or a list of rules in the typed JSON format"
            },
            "note": {
                "type": "string",
                "description": "What changed and why, with the source",
            },
        },
        "required": ["decision", "rules", "note"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from engine.decisions import service as S

        key = str(arguments.get("decision") or "")

        async def go(s):
            out = await S.create_proposal(
                s,
                self._tenant(),
                key,
                arguments.get("rules"),
                note=str(arguments.get("note") or ""),
                actor_id=self._user_id or None,
                actor_label=f"agent {self._agent_name or 'unknown'}",
            )
            if out["tests_failed"]:
                out["message"] = (
                    f"Saved as draft version {out['version']}, not proposed, because "
                    f"{out['tests_failed']} golden tests fail: {', '.join(out['failed_tests'])}."
                )
            else:
                out["message"] = (
                    f"Proposed as version {out['version']}. It needs {out['approvals_needed']} approval(s) "
                    "on the Approvals page before anyone can publish it."
                )
            return self._ok(out, decision=key, version=out["version"])

        return await self._run(go)


DECISION_TOOLS = {
    t.name: t
    for t in (
        DecisionListTool,
        DecisionEvaluateTool,
        DecisionCompareTool,
        DecisionExplainTool,
        DecisionTestTool,
        DecisionProposeTool,
    )
}
