"""Agent evaluation suites: golden cases, scored runs, comparisons across versions and models, and the publish gate."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.capabilities import require_capability
from app.core.deps import get_db
from app.core.responses import error, success
from app.services import eval_assertions as EA
from app.services import eval_runner as R
from app.services.eval_scoring import compare_results
from models.agent import Agent
from models.evals import EvalCase, EvalResult, EvalRun, EvalSuite
from models.execution import Execution
from models.resource_share import SharePermission
from models.user import User

router = APIRouter(prefix="/api/evals", tags=["evals"])

MAX_CASES = 500
MAX_ASSERTIONS = 25
TREND = 12


class SuiteBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    agent_id: uuid.UUID
    gating: bool = False
    pass_threshold: float = Field(default=0.9, ge=0, le=1)
    schedule_cron: str | None = None
    rerun_on_model_change: bool = False
    concurrency: int = Field(default=4, ge=1, le=R.MAX_CONCURRENCY)
    judge_model: str | None = None


class SuitePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    gating: bool | None = None
    pass_threshold: float | None = Field(default=None, ge=0, le=1)
    schedule_cron: str | None = None
    rerun_on_model_change: bool | None = None
    concurrency: int | None = Field(default=None, ge=1, le=R.MAX_CONCURRENCY)
    judge_model: str | None = None


class CaseBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    input_message: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    weight: float = Field(default=1.0, ge=0, le=100)
    tags: list[str] = Field(default_factory=list)
    reference_output: str | None = None


class CasePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    input_message: str | None = None
    context: dict[str, Any] | None = None
    assertions: list[dict[str, Any]] | None = None
    weight: float | None = Field(default=None, ge=0, le=100)
    tags: list[str] | None = None
    reference_output: str | None = None


class FromExecutionBody(BaseModel):
    execution_id: uuid.UUID
    name: str | None = Field(default=None, max_length=255)


class RunBody(BaseModel):
    model: str | None = Field(default=None, max_length=100)


class CheckBody(BaseModel):
    assertions: list[dict[str, Any]]
    output: str | None = None
    case_id: uuid.UUID | None = None
    tool_calls: list[Any] | None = None
    cost: float | None = None
    duration_ms: int | None = None


def _iso(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else None


def _agent_brief(a: Agent | None) -> dict[str, Any] | None:
    if a is None:
        return None
    mc = a.model_config_ or {}
    return {
        "id": str(a.id),
        "name": a.name,
        "slug": a.slug,
        "kind": "pipeline" if mc.get("mode") == "pipeline" else "agent",
        "model": R.agent_model(a),
        "risk_tier": mc.get("risk_tier") or "low",
        "status": getattr(a.status, "value", a.status),
    }


def _suite_json(s: EvalSuite) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "description": s.description or "",
        "agent_id": str(s.agent_id),
        "gating": bool(s.gating),
        "pass_threshold": s.pass_threshold,
        "schedule_cron": s.schedule_cron,
        "next_run_at": _iso(s.next_run_at),
        "rerun_on_model_change": bool(s.rerun_on_model_change),
        "concurrency": s.concurrency,
        "judge_model": s.judge_model,
        "created_by": str(s.created_by) if s.created_by else None,
        "created_at": _iso(s.created_at),
        "updated_at": _iso(s.updated_at),
    }


def _case_json(c: EvalCase) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "suite_id": str(c.suite_id),
        "name": c.name,
        "input_message": c.input_message or "",
        "context": c.context or {},
        "assertions": c.assertions or [],
        "weight": c.weight,
        "tags": c.tags or [],
        "source_execution_id": (
            str(c.source_execution_id) if c.source_execution_id else None
        ),
        "reference_output": c.reference_output,
        "created_at": _iso(c.created_at),
        "updated_at": _iso(c.updated_at),
    }


def _run_json(r: EvalRun) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "suite_id": str(r.suite_id),
        "agent_id": str(r.agent_id) if r.agent_id else None,
        "config_hash": r.config_hash,
        "agent_revision": r.agent_revision,
        "model": r.model,
        "model_override": bool(r.model_override),
        "status": r.status,
        "score": r.score,
        "threshold": r.threshold,
        "threshold_met": r.threshold_met,
        "total": r.total,
        "passed": r.passed,
        "failed": r.failed,
        "errored": r.errored,
        "triggered_by": r.triggered_by,
        "triggered_by_user": str(r.triggered_by_user) if r.triggered_by_user else None,
        "cost": float(r.cost or 0),
        "error": r.error,
        "created_at": _iso(r.created_at),
        "started_at": _iso(r.started_at),
        "completed_at": _iso(r.completed_at),
    }


def _result_json(x: EvalResult) -> dict[str, Any]:
    return {
        "id": str(x.id),
        "case_id": str(x.case_id) if x.case_id else None,
        "case_name": x.case_name,
        "execution_id": str(x.execution_id) if x.execution_id else None,
        "status": x.status,
        "passed": bool(x.passed),
        "score": x.score,
        "assertion_results": x.assertion_results or [],
        "output_excerpt": x.output_excerpt,
        "duration_ms": x.duration_ms,
        "cost": float(x.cost or 0),
        "error": x.error,
    }


def _assertion_problems(assertions: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for i, a in enumerate(assertions):
        p = EA.validate(a)
        if p:
            out[str(i)] = p
    return out


def _cron_problem(expr: str | None) -> str | None:
    if not expr:
        return None
    from app.core.scheduler import is_valid_cron

    if not is_valid_cron(expr):
        return "The schedule is not a valid cron expression, for example 0 6 * * 1 for Mondays at 06:00 UTC."
    return None


async def _visible_agent(db: AsyncSession, user: User, agent_id: Any) -> Agent | None:
    from app.services.agent_share import resolve_agent_access, visible_agent_clause

    agent = (
        await db.execute(
            select(Agent).where(Agent.id == agent_id, visible_agent_clause(user))
        )
    ).scalar_one_or_none()
    if agent is None:
        return None
    if not await resolve_agent_access(
        db, user, agent, permission_required=SharePermission.EXECUTE
    ):
        return None
    return agent


async def _suite(db: AsyncSession, user: User, suite_id: Any) -> EvalSuite | None:
    return (
        await db.execute(
            select(EvalSuite).where(
                EvalSuite.id == suite_id, EvalSuite.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()


async def _run(db: AsyncSession, user: User, run_id: Any) -> EvalRun | None:
    return (
        await db.execute(
            select(EvalRun).where(
                EvalRun.id == run_id, EvalRun.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()


async def _config_hashes(db: AsyncSession, agent_ids: list[Any]) -> dict[str, str]:
    if not agent_ids:
        return {}
    rows = (
        await db.execute(
            text(
                "SELECT id::text, encode(sha256(convert_to(coalesce(system_prompt, '') || '|' || "
                "coalesce(model_config::text, ''), 'UTF8')), 'hex') FROM agents "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": [str(a) for a in agent_ids]},
        )
    ).all()
    return {r[0]: r[1] for r in rows}


async def _previous_baseline(db: AsyncSession, run: EvalRun) -> EvalRun | None:
    return (
        await db.execute(
            select(EvalRun)
            .where(
                EvalRun.suite_id == run.suite_id,
                EvalRun.id != run.id,
                EvalRun.status == "completed",
                EvalRun.model_override.is_(False),
                EvalRun.created_at < run.created_at,
            )
            .order_by(EvalRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _results(db: AsyncSession, run_id: Any) -> list[EvalResult]:
    return list(
        (
            await db.execute(
                select(EvalResult)
                .where(EvalResult.run_id == run_id)
                .order_by(EvalResult.case_name)
            )
        )
        .scalars()
        .all()
    )


@router.get("/assertion-types")
async def assertion_types(
    user: User = Depends(require_capability("evals.run")),
) -> JSONResponse:
    return success(
        {
            "types": [{"type": k, **v} for k, v in EA.TYPES.items()],
            "default_judge_model": EA.DEFAULT_JUDGE_MODEL,
            "source_tools": list(EA.SOURCE_TOOLS),
        }
    )


@router.get("/suites")
async def list_suites(
    agent_id: uuid.UUID | None = None,
    user: User = Depends(require_capability("evals.run")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    stmt = select(EvalSuite).where(EvalSuite.tenant_id == user.tenant_id)
    if agent_id:
        stmt = stmt.where(EvalSuite.agent_id == agent_id)
    suites = list((await db.execute(stmt.order_by(EvalSuite.name))).scalars().all())
    if not suites:
        return success([])
    ids = [s.id for s in suites]
    agent_ids = list({s.agent_id for s in suites})
    agents = {
        a.id: a
        for a in (await db.execute(select(Agent).where(Agent.id.in_(agent_ids))))
        .scalars()
        .all()
    }
    counts = dict(
        (
            await db.execute(
                select(EvalCase.suite_id, func.count())
                .where(EvalCase.suite_id.in_(ids))
                .group_by(EvalCase.suite_id)
            )
        ).all()
    )
    ranked = (
        select(
            EvalRun,
            func.row_number()
            .over(partition_by=EvalRun.suite_id, order_by=EvalRun.created_at.desc())
            .label("rn"),
        )
        .where(EvalRun.suite_id.in_(ids), EvalRun.model_override.is_(False))
        .subquery()
    )
    recent = (
        (
            await db.execute(
                select(EvalRun)
                .join(ranked, ranked.c.id == EvalRun.id)
                .where(ranked.c.rn <= TREND)
                .order_by(EvalRun.created_at)
            )
        )
        .scalars()
        .all()
    )
    by: dict[uuid.UUID, list[EvalRun]] = {}
    for r in recent:
        by.setdefault(r.suite_id, []).append(r)
    hashes = await _config_hashes(db, agent_ids)
    out = []
    for s in suites:
        runs = by.get(s.id, [])
        done = [r for r in runs if r.status == "completed"]
        last = done[-1] if done else None
        active = next((r for r in reversed(runs) if r.status in R.ACTIVE), None)
        current = hashes.get(str(s.agent_id))
        out.append(
            {
                **_suite_json(s),
                "agent": _agent_brief(agents.get(s.agent_id)),
                "case_count": int(counts.get(s.id, 0)),
                "last_run": _run_json(last) if last else None,
                "active_run": _run_json(active) if active else None,
                "trend": [
                    {"run_id": str(r.id), "score": r.score, "at": _iso(r.created_at)}
                    for r in done
                ],
                "current_version_evaluated": bool(
                    last and current and last.config_hash == current
                ),
            }
        )
    return success(out)


@router.post("/suites")
async def create_suite(
    body: SuiteBody,
    request: Request,
    user: User = Depends(require_capability("evals.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    agent = await _visible_agent(db, user, body.agent_id)
    if agent is None:
        return error("Pick an agent or pipeline you can run.", 404)
    cron = (body.schedule_cron or "").strip() or None
    problem = _cron_problem(cron)
    if problem:
        return error(problem, 400)
    s = EvalSuite(
        tenant_id=user.tenant_id,
        name=body.name.strip(),
        description=body.description,
        agent_id=agent.id,
        gating=body.gating,
        pass_threshold=body.pass_threshold,
        schedule_cron=cron,
        next_run_at=R.next_cron(cron) if cron else None,
        rerun_on_model_change=body.rerun_on_model_change,
        concurrency=body.concurrency,
        judge_model=(body.judge_model or "").strip() or None,
        created_by=user.id,
    )
    db.add(s)
    await db.flush()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "eval.suite_created",
        {"suite_id": str(s.id), "agent_id": str(agent.id), "gating": s.gating},
        request,
        resource_type="eval_suite",
        resource_id=str(s.id),
    )
    await db.commit()
    await db.refresh(s)
    return success(
        {**_suite_json(s), "agent": _agent_brief(agent), "cases": []}, status_code=201
    )


@router.get("/suites/{suite_id}")
async def get_suite(
    suite_id: uuid.UUID,
    user: User = Depends(require_capability("evals.run")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _suite(db, user, suite_id)
    if s is None:
        return error("Suite not found", 404)
    agent = await db.get(Agent, s.agent_id)
    cases = (
        (
            await db.execute(
                select(EvalCase)
                .where(EvalCase.suite_id == s.id)
                .order_by(EvalCase.created_at)
            )
        )
        .scalars()
        .all()
    )
    runs = (
        (
            await db.execute(
                select(EvalRun)
                .where(EvalRun.suite_id == s.id)
                .order_by(EvalRun.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    latest_by_case: dict[str, dict[str, Any]] = {}
    last_done = next((r for r in runs if r.status == "completed"), None)
    if last_done is not None:
        for x in await _results(db, last_done.id):
            if x.case_id:
                latest_by_case[str(x.case_id)] = {
                    "passed": bool(x.passed),
                    "score": x.score,
                    "status": x.status,
                    "run_id": str(last_done.id),
                    "execution_id": str(x.execution_id) if x.execution_id else None,
                }
    current = (await _config_hashes(db, [s.agent_id])).get(str(s.agent_id))
    gate = await R.gate_for_agent(db, agent) if agent is not None else None
    return success(
        {
            **_suite_json(s),
            "agent": _agent_brief(agent),
            "cases": [
                {**_case_json(c), "last_result": latest_by_case.get(str(c.id))}
                for c in cases
            ],
            "runs": [_run_json(r) for r in runs],
            "current_config_hash": current,
            "gate": (
                {
                    "allowed": gate.allowed,
                    "required": gate.required,
                    "message": gate.message,
                    "suites": gate.suites,
                }
                if gate is not None
                else None
            ),
        }
    )


@router.patch("/suites/{suite_id}")
async def update_suite(
    suite_id: uuid.UUID,
    body: SuitePatch,
    request: Request,
    user: User = Depends(require_capability("evals.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _suite(db, user, suite_id)
    if s is None:
        return error("Suite not found", 404)
    fields = body.model_dump(exclude_unset=True)
    if "schedule_cron" in fields:
        cron = (fields["schedule_cron"] or "").strip() or None
        problem = _cron_problem(cron)
        if problem:
            return error(problem, 400)
        s.schedule_cron = cron
        s.next_run_at = R.next_cron(cron) if cron else None
    for k in (
        "name",
        "description",
        "gating",
        "pass_threshold",
        "rerun_on_model_change",
        "concurrency",
    ):
        if k in fields and fields[k] is not None:
            setattr(s, k, fields[k].strip() if k == "name" else fields[k])
    if "judge_model" in fields:
        s.judge_model = (fields["judge_model"] or "").strip() or None
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "eval.suite_updated",
        {"suite_id": str(s.id), "changed": sorted(fields)},
        request,
        resource_type="eval_suite",
        resource_id=str(s.id),
    )
    await db.commit()
    await db.refresh(s)
    return success(_suite_json(s))


@router.delete("/suites/{suite_id}")
async def delete_suite(
    suite_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_capability("evals.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _suite(db, user, suite_id)
    if s is None:
        return error("Suite not found", 404)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "eval.suite_deleted",
        {"suite_id": str(s.id), "name": s.name, "gating": s.gating},
        request,
        resource_type="eval_suite",
        resource_id=str(s.id),
    )
    await db.delete(s)
    await db.commit()
    return success({"deleted": str(suite_id)})


async def _case_count(db: AsyncSession, suite_id: Any) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(EvalCase)
                .where(EvalCase.suite_id == suite_id)
            )
        ).scalar()
        or 0
    )


def _check_case_fields(assertions: list[dict[str, Any]] | None) -> JSONResponse | None:
    if assertions is None:
        return None
    if len(assertions) > MAX_ASSERTIONS:
        return error(f"A case can hold up to {MAX_ASSERTIONS} assertions.", 400)
    problems = _assertion_problems(assertions)
    if problems:
        first = next(iter(problems.items()))
        return error(
            f"Assertion {int(first[0]) + 1}: {' '.join(first[1])}",
            400,
            error_code="INVALID_ASSERTION",
            details={"assertions": problems},
        )
    return None


@router.post("/suites/{suite_id}/cases")
async def create_case(
    suite_id: uuid.UUID,
    body: CaseBody,
    user: User = Depends(require_capability("evals.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _suite(db, user, suite_id)
    if s is None:
        return error("Suite not found", 404)
    if await _case_count(db, s.id) >= MAX_CASES:
        return error(f"A suite can hold up to {MAX_CASES} cases.", 400)
    bad = _check_case_fields(body.assertions)
    if bad:
        return bad
    c = EvalCase(
        tenant_id=user.tenant_id,
        suite_id=s.id,
        name=body.name.strip(),
        input_message=body.input_message,
        context=body.context,
        assertions=body.assertions,
        weight=body.weight,
        tags=[t.strip() for t in body.tags if t.strip()],
        reference_output=body.reference_output,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return success(_case_json(c), status_code=201)


@router.post("/suites/{suite_id}/cases/from-execution")
async def case_from_execution(
    suite_id: uuid.UUID,
    body: FromExecutionBody,
    user: User = Depends(require_capability("evals.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Turn a past run's input and output into a case, with assertions that hold for that run."""
    s = await _suite(db, user, suite_id)
    if s is None:
        return error("Suite not found", 404)
    ex = (
        await db.execute(
            select(Execution).where(
                Execution.id == body.execution_id,
                Execution.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if ex is None:
        return error("Execution not found", 404)
    if await _case_count(db, s.id) >= MAX_CASES:
        return error(f"A suite can hold up to {MAX_CASES} cases.", 400)
    obs = R.observed_from(ex, ex.input_message or "")
    first_line = (ex.input_message or "").strip().splitlines()[0:1]
    name = (body.name or "").strip() or (
        (first_line[0][:80] if first_line and first_line[0] else "")
        or f"Run {str(ex.id)[:8]}"
    )
    c = EvalCase(
        tenant_id=user.tenant_id,
        suite_id=s.id,
        name=name,
        input_message=ex.input_message or "",
        context={},
        assertions=EA.suggest(obs) if obs.status == "completed" else [],
        weight=1.0,
        tags=["from-run"],
        source_execution_id=ex.id,
        reference_output=(ex.output_message or "")[:20000] or None,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return success(
        {**_case_json(c), "same_agent": ex.agent_id == s.agent_id}, status_code=201
    )


async def _case(db: AsyncSession, user: User, case_id: Any) -> EvalCase | None:
    return (
        await db.execute(
            select(EvalCase).where(
                EvalCase.id == case_id, EvalCase.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()


@router.patch("/cases/{case_id}")
async def update_case(
    case_id: uuid.UUID,
    body: CasePatch,
    user: User = Depends(require_capability("evals.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    c = await _case(db, user, case_id)
    if c is None:
        return error("Case not found", 404)
    fields = body.model_dump(exclude_unset=True)
    bad = _check_case_fields(fields.get("assertions"))
    if bad:
        return bad
    for k, v in fields.items():
        if v is None and k != "reference_output":
            continue
        if k == "name":
            v = v.strip()
        if k == "tags":
            v = [t.strip() for t in v if t.strip()]
        setattr(c, k, v)
    await db.commit()
    await db.refresh(c)
    return success(_case_json(c))


@router.delete("/cases/{case_id}")
async def delete_case(
    case_id: uuid.UUID,
    user: User = Depends(require_capability("evals.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    c = await _case(db, user, case_id)
    if c is None:
        return error("Case not found", 404)
    await db.delete(c)
    await db.commit()
    return success({"deleted": str(case_id)})


@router.post("/assertions/check")
async def check_assertions(
    body: CheckBody,
    user: User = Depends(require_capability("evals.run")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Validate assertions and try them on an output: the one given, or the case's last result, or its captured run."""
    output, source = body.output, "given"
    tool_calls, cost, duration = body.tool_calls or [], body.cost, body.duration_ms
    if output is None and body.case_id:
        c = await _case(db, user, body.case_id)
        if c is None:
            return error("Case not found", 404)
        last = (
            await db.execute(
                select(EvalResult)
                .where(EvalResult.case_id == c.id, EvalResult.status == "completed")
                .order_by(EvalResult.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        ex_id = last.execution_id if last else c.source_execution_id
        ex = await db.get(Execution, ex_id) if ex_id else None
        if ex is not None and ex.tenant_id == user.tenant_id:
            obs = R.observed_from(ex, ex.input_message or "")
            output, tool_calls = obs.output, obs.tool_calls
            cost, duration = obs.cost, obs.duration_ms
            source = "last run" if last else "captured run"
        elif last is not None:
            output, source = last.output_excerpt or "", "last run"
            cost, duration = float(last.cost or 0), last.duration_ms
        elif c.reference_output:
            output, source = c.reference_output, "captured run"
    if output is None:
        return success(
            {
                "source": None,
                "problems": _assertion_problems(body.assertions),
                "results": [],
            }
        )
    obs = EA.Observed(
        output=output,
        tool_calls=tool_calls if isinstance(tool_calls, list) else [],
        cost=float(cost or 0),
        duration_ms=duration,
    )
    results = []
    for a in body.assertions[:MAX_ASSERTIONS]:
        if isinstance(a, dict) and a.get("type") == "judge":
            results.append(
                {
                    "type": "judge",
                    "label": EA.TYPES["judge"]["label"],
                    "passed": None,
                    "skipped": True,
                    "reason": "A model judges this during a suite run",
                    "deterministic": False,
                }
            )
        else:
            results.append(EA.check(a, obs))
    return success(
        {
            "source": source,
            "output_excerpt": (output or "")[:4000],
            "problems": _assertion_problems(body.assertions),
            "results": results,
        }
    )


@router.post("/suites/{suite_id}/run")
async def run_suite(
    suite_id: uuid.UUID,
    request: Request,
    body: RunBody | None = None,
    user: User = Depends(require_capability("evals.run")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _suite(db, user, suite_id)
    if s is None:
        return error("Suite not found", 404)
    agent = await _visible_agent(db, user, s.agent_id)
    if agent is None:
        return error(
            "The agent behind this suite is gone or you cannot run it.",
            409,
        )
    if await _case_count(db, s.id) == 0:
        return error("Add at least one case before running the suite.", 400)
    model = ((body.model if body else None) or "").strip() or None
    if model:
        if R.agent_model(agent) == "pipeline":
            return error(
                "Model comparison applies to agents. A pipeline's steps choose their own models.",
                400,
            )
        if not await R.model_allowed_for(agent, model):
            return error(
                f"{model} is not on the allowed model list for this agent's risk tier.",
                400,
            )
    run = await R.start_run(db, s, user.id, triggered_by="manual", model=model)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "eval.run_started",
        {"suite_id": str(s.id), "run_id": str(run.id), "model": run.model},
        request,
        resource_type="eval_run",
        resource_id=str(run.id),
    )
    await db.commit()
    return success(_run_json(run), status_code=202)


@router.get("/suites/{suite_id}/runs")
async def list_runs(
    suite_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_capability("evals.run")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _suite(db, user, suite_id)
    if s is None:
        return error("Suite not found", 404)
    runs = (
        (
            await db.execute(
                select(EvalRun)
                .where(EvalRun.suite_id == s.id)
                .order_by(EvalRun.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return success([_run_json(r) for r in runs])


@router.get("/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    user: User = Depends(require_capability("evals.run")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    run = await _run(db, user, run_id)
    if run is None:
        return error("Run not found", 404)
    suite = await db.get(EvalSuite, run.suite_id)
    agent = await db.get(Agent, run.agent_id) if run.agent_id else None
    results = await _results(db, run.id)
    prev = await _previous_baseline(db, run)
    comparison = None
    if prev is not None and run.status in ("completed", "cancelled"):
        comparison = {
            "base_run": _run_json(prev),
            **compare_results(
                [_result_json(x) for x in await _results(db, prev.id)],
                [_result_json(x) for x in results],
            ),
        }
    return success(
        {
            **_run_json(run),
            "suite": {"id": str(suite.id), "name": suite.name} if suite else None,
            "agent": _agent_brief(agent),
            "done": len(results),
            "results": [_result_json(x) for x in results],
            "comparison": comparison,
        }
    )


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: uuid.UUID,
    user: User = Depends(require_capability("evals.run")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    run = await _run(db, user, run_id)
    if run is None:
        return error("Run not found", 404)
    if run.status not in R.ACTIVE:
        return error("This run has already finished.", 409)
    await R.cancel_run(db, run)
    return success(_run_json(run))


@router.get("/runs/{run_id}/compare/{other_id}")
async def compare_runs(
    run_id: uuid.UUID,
    other_id: uuid.UUID,
    user: User = Depends(require_capability("evals.run")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Two runs side by side. run_id is the base, other_id the one compared against it."""
    a = await _run(db, user, run_id)
    b = await _run(db, user, other_id)
    if a is None or b is None:
        return error("Run not found", 404)
    ra = [_result_json(x) for x in await _results(db, a.id)]
    rb = [_result_json(x) for x in await _results(db, b.id)]
    by_a = {r["case_id"] or f"name:{r['case_name']}": r for r in ra}
    by_b = {r["case_id"] or f"name:{r['case_name']}": r for r in rb}
    keys = list(dict.fromkeys([*by_a.keys(), *by_b.keys()]))
    rows = [
        {
            "case_id": (by_a.get(k) or by_b.get(k) or {}).get("case_id"),
            "case_name": (by_a.get(k) or by_b.get(k) or {}).get("case_name"),
            "a": by_a.get(k),
            "b": by_b.get(k),
        }
        for k in keys
    ]
    rows.sort(key=lambda r: (r["case_name"] or "").lower())
    return success(
        {
            "a": _run_json(a),
            "b": _run_json(b),
            "same_suite": a.suite_id == b.suite_id,
            "rows": rows,
            **compare_results(ra, rb),
        }
    )


@router.get("/gate/{agent_id}")
async def gate_status(
    agent_id: uuid.UUID,
    user: User = Depends(require_capability("evals.run")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Whether publishing this agent now would pass its evaluation gate."""
    agent = (
        await db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if agent is None:
        return error("Agent not found", 404)
    gate = await R.gate_for_agent(db, agent)
    return success(
        {
            "agent": _agent_brief(agent),
            "allowed": gate.allowed,
            "required": gate.required,
            "message": gate.message,
            "suites": gate.suites,
            "current_config_hash": (await _config_hashes(db, [agent.id])).get(
                str(agent.id)
            ),
        }
    )
