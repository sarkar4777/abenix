"""Runs evaluation suites through the normal execution path, scores them, gates publishing and schedules reruns."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import eval_assertions as EA
from app.services.eval_scoring import (
    GateResult,
    gate_decision,
    model_changed,
    score_run,
)
from models.agent import Agent
from models.evals import EvalCase, EvalResult, EvalRun, EvalSuite
from models.execution import Execution
from models.user import User

logger = logging.getLogger("abenix.evals")

EVAL_LOCK_KEY = 0x4556414C  # "EVAL"
ACTIVE = ("queued", "running")
MAX_CONCURRENCY = 16
CASE_TIMEOUT = int(os.environ.get("EVAL_CASE_TIMEOUT_SECONDS", "300"))
STALE_MINUTES = int(os.environ.get("EVAL_STALE_MINUTES", "180"))
EXCERPT = 4000

_TASKS: set[asyncio.Task] = set()
_global = asyncio.Semaphore(int(os.environ.get("EVAL_MAX_PARALLEL_CASES", "8")))


def _session():
    from app.core.deps import async_session

    return async_session()


def agent_model(agent: Agent) -> str:
    mc = agent.model_config_ or {}
    if mc.get("mode") == "pipeline":
        return "pipeline"
    return mc.get("model") or "claude-sonnet-4-5-20250929"


async def current_config_hash(db: AsyncSession, agent_id: Any) -> str | None:
    """The hash the executions_provenance trigger would stamp on a run of this agent right now."""
    return (
        await db.execute(
            text(
                "SELECT encode(sha256(convert_to(coalesce(system_prompt, '') || '|' || "
                "coalesce(model_config::text, ''), 'UTF8')), 'hex') FROM agents WHERE id = :a"
            ),
            {"a": str(agent_id)},
        )
    ).scalar()


async def _failing_names(db: AsyncSession, run_id: Any) -> list[str]:
    rows = (
        await db.execute(
            select(EvalResult.case_name)
            .where(EvalResult.run_id == run_id, EvalResult.passed.is_(False))
            .order_by(EvalResult.case_name)
        )
    ).all()
    return [r[0] for r in rows]


async def gate_for_agent(db: AsyncSession, agent: Agent) -> GateResult:
    """Whether the tenant's tier policy lets this agent version be published, judged by its gating suites."""
    from engine import governance, risk

    mc = agent.model_config_ or {}
    tier = risk.normalize(mc.get("risk_tier"))
    await governance.ensure_fresh()
    required = bool(
        governance.policy(str(agent.tenant_id), tier).get("require_eval_pass")
    )
    if not required:
        return GateResult(True, required=False)
    suites = (
        (
            await db.execute(
                select(EvalSuite).where(
                    EvalSuite.tenant_id == agent.tenant_id,
                    EvalSuite.agent_id == agent.id,
                    EvalSuite.gating.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    if not suites:
        return GateResult(True, required=True)
    chash = await current_config_hash(db, agent.id)
    rows: list[dict[str, Any]] = []
    for s in suites:
        run = (
            await db.execute(
                select(EvalRun)
                .where(
                    EvalRun.suite_id == s.id,
                    EvalRun.status == "completed",
                    EvalRun.model_override.is_(False),
                    EvalRun.config_hash == chash,
                )
                .order_by(EvalRun.completed_at.desc().nulls_last())
                .limit(1)
            )
        ).scalar_one_or_none()
        rows.append(
            {
                "id": s.id,
                "name": s.name,
                "threshold": s.pass_threshold,
                "run": (
                    {
                        "id": run.id,
                        "score": run.score,
                        "threshold_met": run.threshold_met,
                        "config_hash": run.config_hash,
                        "failing_cases": await _failing_names(db, run.id),
                    }
                    if run
                    else None
                ),
            }
        )
    return gate_decision(required=True, tier=tier, config_hash=chash, suites=rows)


async def model_allowed_for(agent: Agent, model: str) -> bool:
    from engine import governance, risk

    tier = risk.normalize((agent.model_config_ or {}).get("risk_tier"))
    await governance.ensure_fresh()
    return risk.model_allowed(governance.policy(str(agent.tenant_id), tier), model)


async def start_run(
    db: AsyncSession,
    suite: EvalSuite,
    user_id: Any,
    *,
    triggered_by: str = "manual",
    model: str | None = None,
    launch: bool = True,
) -> EvalRun:
    """Queue a run and start it in the background. An identical run already in flight is returned instead."""
    agent = await db.get(Agent, suite.agent_id)
    base_model = agent_model(agent) if agent else None
    override = bool(model) and model != base_model
    existing = (
        await db.execute(
            select(EvalRun)
            .where(
                EvalRun.suite_id == suite.id,
                EvalRun.status.in_(ACTIVE),
                EvalRun.model_override.is_(override),
                EvalRun.model == (model if override else base_model),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    total = (
        await db.execute(
            select(func.count())
            .select_from(EvalCase)
            .where(EvalCase.suite_id == suite.id)
        )
    ).scalar() or 0
    run = EvalRun(
        id=uuid.uuid4(),
        tenant_id=suite.tenant_id,
        suite_id=suite.id,
        agent_id=suite.agent_id,
        model=model if override else base_model,
        model_override=override,
        status="queued",
        threshold=suite.pass_threshold,
        total=int(total),
        triggered_by=triggered_by,
        triggered_by_user=user_id,
        config_hash=await current_config_hash(db, suite.agent_id),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    if launch:
        launch_run(run.id)
    return run


def launch_run(run_id: Any) -> None:
    t = asyncio.create_task(execute_run(run_id))
    _TASKS.add(t)
    t.add_done_callback(_TASKS.discard)


def _scope(agent_id: Any, body: dict[str, Any], model: str | None) -> Any:
    from starlette.requests import Request

    raw = json.dumps(body).encode()
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "path": f"/api/agents/{agent_id}/execute",
        "raw_path": f"/api/agents/{agent_id}/execute".encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 0),
        "server": ("evals", 0),
        "state": {"eval_model": model} if model else {},
    }
    return Request(scope, receive)


async def _execute(
    agent_id: Any,
    user_id: Any,
    message: str,
    context: dict[str, Any],
    model: str | None,
) -> tuple[str | None, str | None]:
    """One case through POST /api/agents/{id}/execute with wait, as the user. Returns (execution_id, error)."""
    from app.routers import agents as agents_router
    from app.schemas.agents import ExecuteRequest

    body = {
        "message": message or "",
        "stream": False,
        "wait": True,
        "context": context or None,
        "wait_timeout_seconds": max(5, min(CASE_TIMEOUT, 1800)),
    }
    async with _session() as db:
        user = await db.get(User, user_id)
        if user is None or not getattr(user, "is_active", True):
            return None, "The user this suite runs as no longer exists or is inactive"
        resp = await agents_router.execute_agent(
            str(agent_id),
            ExecuteRequest(**body),
            _scope(agent_id, body, model),
            user,
            db,
        )
    try:
        payload = json.loads(resp.body)
    except Exception:  # noqa: BLE001
        return None, f"The execute call answered {getattr(resp, 'status_code', '?')}"
    data = payload.get("data") or {}
    err = payload.get("error") or {}
    ex_id = data.get("execution_id") if isinstance(data, dict) else None
    if ex_id:
        return str(ex_id), None
    msg = err.get("message") if isinstance(err, dict) else str(err)
    return None, msg or f"The execute call answered {resp.status_code}"


async def _settled(execution_id: str) -> Execution | None:
    """The execution row once it is terminal, waiting briefly for the runtime's final write."""
    for i in range(60):
        async with _session() as db:
            row = await db.get(Execution, uuid.UUID(execution_id))
            st = _status(row)
            if row is None or st != "running":
                return row
        await asyncio.sleep(0.5 if i < 10 else 1.0)
    return row


def _status(row: Execution | None) -> str:
    if row is None:
        return "missing"
    s = row.status
    return str(getattr(s, "value", s) or "").lower()


def observed_from(row: Execution | None, message: str) -> EA.Observed:
    if row is None:
        return EA.Observed(status="missing", input_message=message)
    calls = row.tool_calls
    if isinstance(calls, dict):
        calls = calls.get("calls") or list(calls.values())
    return EA.Observed(
        output=row.output_message or "",
        tool_calls=calls if isinstance(calls, list) else [],
        cost=float(row.cost or 0),
        duration_ms=row.duration_ms,
        status=_status(row),
        input_message=message,
    )


async def judge(
    rubric: str, input_message: str, output: str, model: str
) -> tuple[float, str, float]:
    from engine.llm_router import LLMRouter

    system = (
        "You grade an AI agent's answer against a rubric. Be strict and literal. "
        'Reply with JSON only: {"score": <number from 0 to 1>, "reason": "<one sentence>"}.'
    )
    prompt = (
        f"RUBRIC:\n{rubric}\n\nINPUT GIVEN TO THE AGENT:\n{input_message[:6000]}\n\n"
        f"AGENT'S ANSWER:\n{output[:20000]}"
    )
    resp = await LLMRouter().complete(
        messages=[{"role": "user", "content": prompt}],
        system=system,
        model=model,
        temperature=0.0,
        max_tokens=300,
    )
    parsed = EA.parse_output_json(resp.content)
    if not isinstance(parsed, dict) or "score" not in parsed:
        raise ValueError(f"the judge did not answer with a score: {resp.content[:120]}")
    return (
        float(parsed["score"]),
        str(parsed.get("reason") or ""),
        float(resp.cost or 0),
    )


async def _cancelled(run_id: Any) -> bool:
    async with _session() as db:
        st = (
            await db.execute(select(EvalRun.status).where(EvalRun.id == run_id))
        ).scalar()
    return st == "cancelled"


async def run_case(
    run: EvalRun, case: EvalCase, user_id: Any, judge_model: str | None
) -> dict[str, Any]:
    """Execute one case, score it and store its result."""
    started = datetime.now(timezone.utc)
    async with _global:
        ex_id, err = await _execute(
            run.agent_id,
            user_id,
            case.input_message,
            case.context or {},
            run.model if run.model_override else None,
        )
        row = await _settled(ex_id) if ex_id else None
    obs = observed_from(row, case.input_message)
    if err:
        obs.status = "error"
    assertions = [
        (
            {**a, "model": a.get("model") or judge_model}
            if a.get("type") == "judge" and judge_model
            else a
        )
        for a in (case.assertions or [])
        if isinstance(a, dict)
    ]
    outcome, judge_cost = await EA.evaluate_case(assertions, obs, judge)
    status = "completed" if obs.status == "completed" else "error"
    reason = err or (
        row.error_message if row is not None and status == "error" else None
    )
    result = EvalResult(
        id=uuid.uuid4(),
        tenant_id=run.tenant_id,
        run_id=run.id,
        case_id=case.id,
        case_name=case.name,
        execution_id=uuid.UUID(ex_id) if ex_id else None,
        status=status,
        passed=outcome.passed,
        score=outcome.score,
        assertion_results=outcome.results,
        output_excerpt=(obs.output or "")[:EXCERPT] or None,
        duration_ms=obs.duration_ms
        or int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
        cost=float(obs.cost or 0) + judge_cost,
        error=(reason or None) and str(reason)[:2000],
    )
    async with _session() as db:
        db.add(result)
        await db.commit()
    return {
        "case_id": case.id,
        "weight": case.weight,
        "passed": outcome.passed,
        "status": status,
        "score": outcome.score,
        "cost": float(result.cost or 0),
        "config_hash": (
            (row.provenance or {}).get("config_hash") if row is not None else None
        ),
        "agent_revision": row.agent_revision if row is not None else None,
    }


async def execute_run(run_id: Any) -> None:
    """Run every case of a queued run with bounded concurrency, then score it and emit eval.completed."""
    try:
        async with _session() as db:
            run = await db.get(EvalRun, run_id)
            if run is None or run.status != "queued":
                return
            suite = await db.get(EvalSuite, run.suite_id)
            cases = (
                (
                    await db.execute(
                        select(EvalCase)
                        .where(EvalCase.suite_id == run.suite_id)
                        .order_by(EvalCase.created_at)
                    )
                )
                .scalars()
                .all()
            )
            user_id = run.triggered_by_user or (suite.created_by if suite else None)
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            run.total = len(cases)
            await db.commit()
            await db.refresh(run)
        if suite is None or user_id is None:
            await _finish(run_id, [], error="No user to run the suite as")
            return
        if not cases:
            await _finish(run_id, [], error="The suite has no cases yet")
            return
        sem = asyncio.Semaphore(
            max(1, min(int(suite.concurrency or 4), MAX_CONCURRENCY))
        )

        async def one(c: EvalCase) -> dict[str, Any] | None:
            async with sem:
                if await _cancelled(run_id):
                    return None
                try:
                    return await run_case(run, c, user_id, suite.judge_model)
                except Exception as e:  # noqa: BLE001
                    logger.exception("eval case %s failed to run", c.id)
                    async with _session() as db:
                        db.add(
                            EvalResult(
                                id=uuid.uuid4(),
                                tenant_id=run.tenant_id,
                                run_id=run_id,
                                case_id=c.id,
                                case_name=c.name,
                                status="error",
                                passed=False,
                                score=0.0,
                                assertion_results=[],
                                error=f"The case could not run: {str(e)[:500]}",
                            )
                        )
                        await db.commit()
                    return {
                        "case_id": c.id,
                        "weight": c.weight,
                        "passed": False,
                        "status": "error",
                        "score": 0.0,
                        "cost": 0.0,
                    }

        outcomes = [o for o in await asyncio.gather(*(one(c) for c in cases)) if o]
        await _finish(run_id, outcomes)
    except Exception as e:  # noqa: BLE001
        logger.exception("eval run %s crashed", run_id)
        try:
            await _finish(run_id, [], error=f"The run stopped: {str(e)[:500]}")
        except Exception:  # noqa: BLE001
            logger.exception("eval run %s could not be closed", run_id)


async def _finish(
    run_id: Any, outcomes: list[dict[str, Any]], *, error: str | None = None
) -> None:
    from app.services.events import emit

    async with _session() as db:
        run = await db.get(EvalRun, run_id)
        if run is None:
            return
        cancelled = run.status == "cancelled"
        sc = score_run(outcomes, run.threshold)
        hashes = [o.get("config_hash") for o in outcomes if o.get("config_hash")]
        if hashes:
            run.config_hash = max(set(hashes), key=hashes.count)
        revs = [o.get("agent_revision") for o in outcomes if o.get("agent_revision")]
        if revs:
            run.agent_revision = max(revs)
        run.score = sc["score"]
        run.passed, run.failed, run.errored = sc["passed"], sc["failed"], sc["errored"]
        run.threshold_met = (
            sc["threshold_met"] if not error and not cancelled else False
        )
        run.cost = round(sum(float(o.get("cost") or 0) for o in outcomes), 6)
        run.completed_at = datetime.now(timezone.utc)
        if error:
            run.error = error
        if not cancelled:
            run.status = "failed" if error else "completed"
        await emit(
            db,
            run.tenant_id,
            "eval.completed",
            {
                "suite_id": str(run.suite_id),
                "run_id": str(run.id),
                "agent_id": str(run.agent_id) if run.agent_id else None,
                "status": run.status,
                "score": run.score,
                "threshold": run.threshold,
                "threshold_met": run.threshold_met,
                "passed": run.passed,
                "failed": run.failed,
                "model": run.model,
                "model_override": run.model_override,
                "config_hash": run.config_hash,
                "triggered_by": run.triggered_by,
            },
        )
        await db.commit()


async def cancel_run(db: AsyncSession, run: EvalRun) -> None:
    if run.status in ACTIVE:
        run.status = "cancelled"
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()


def next_cron(expr: str, base: datetime | None = None) -> datetime | None:
    from app.core.scheduler import next_cron_run

    return next_cron_run(expr, base)


async def scheduler_tick() -> dict[str, int]:
    """Close abandoned runs, start due scheduled runs, and rerun suites whose agent changed model."""
    now = datetime.now(timezone.utc)
    started = {"stale": 0, "schedule": 0, "model_change": 0}
    async with _session() as db:
        r = await db.execute(
            update(EvalRun)
            .where(
                EvalRun.status.in_(ACTIVE),
                func.coalesce(EvalRun.started_at, EvalRun.created_at)
                < now - timedelta(minutes=STALE_MINUTES),
            )
            .values(
                status="failed",
                error="The run stopped reporting, most likely its API pod restarted. Run it again.",
                completed_at=now,
            )
        )
        started["stale"] = int(getattr(r, "rowcount", 0) or 0)
        await db.commit()

        due = (
            (
                await db.execute(
                    select(EvalSuite).where(
                        EvalSuite.schedule_cron.isnot(None),
                        (EvalSuite.next_run_at.is_(None))
                        | (EvalSuite.next_run_at <= now),
                    )
                )
            )
            .scalars()
            .all()
        )
        for s in due:
            first = s.next_run_at is None
            s.next_run_at = next_cron(s.schedule_cron or "", now)
            await db.commit()
            if first or s.created_by is None:
                continue
            await start_run(db, s, s.created_by, triggered_by="schedule")
            started["schedule"] += 1

        watch = (
            (
                await db.execute(
                    select(EvalSuite).where(EvalSuite.rerun_on_model_change.is_(True))
                )
            )
            .scalars()
            .all()
        )
        for s in watch:
            agent = await db.get(Agent, s.agent_id)
            if agent is None or s.created_by is None:
                continue
            last = (
                await db.execute(
                    select(EvalRun.model)
                    .where(
                        EvalRun.suite_id == s.id,
                        EvalRun.model_override.is_(False),
                    )
                    .order_by(EvalRun.created_at.desc())
                    .limit(1)
                )
            ).scalar()
            if model_changed(last, agent_model(agent)):
                await start_run(db, s, s.created_by, triggered_by="model_change")
                started["model_change"] += 1
    return started
