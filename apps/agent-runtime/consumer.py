"""Wave-2 per-pool consumer — pulls agent-execution jobs off the queue"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("agent-runtime.consumer")
logging.basicConfig(
    # Python's logging.basicConfig needs an uppercase level name or an
    # int. Helm/K8s idiomatically set lowercase ("info") — normalise so
    # we don't crash on boot.
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
# Make the shared packages importable the same way the API does
sys.path.insert(0, str(_REPO / "apps" / "api"))
sys.path.insert(0, str(_REPO / "packages" / "db"))
sys.path.insert(0, str(_HERE))


_engine = None
_session_factory = None
_engine_lock = asyncio.Lock()


async def _get_session_factory():
    global _engine, _session_factory
    if _session_factory is not None:
        return _session_factory
    async with _engine_lock:
        if _session_factory is not None:
            return _session_factory
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker

        db_url = os.environ.get("DATABASE_URL") or os.environ.get(
            "DATABASE_URL_ASYNC",
            "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
        )
        pool_size = int(os.environ.get("CONSUMER_DB_POOL_SIZE", "10"))
        max_overflow = int(os.environ.get("CONSUMER_DB_MAX_OVERFLOW", "5"))
        _engine = create_async_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=3600,
            connect_args=(
                {
                    "server_settings": {
                        "idle_in_transaction_session_timeout": os.environ.get(
                            "DB_IDLE_TXN_TIMEOUT_MS", "300000"
                        )
                    }
                }
                if "asyncpg" in db_url
                else {}
            ),
        )
        _session_factory = sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
        return _session_factory


async def _load_execution(execution_id: str) -> dict[str, Any] | None:
    from sqlalchemy import select

    from models.agent import Agent  # type: ignore
    from models.execution import Execution  # type: ignore

    Session = await _get_session_factory()
    async with Session() as db:
        res = await db.execute(
            select(Execution).where(Execution.id == uuid.UUID(execution_id))
        )
        execution = res.scalar_one_or_none()
        if execution is None:
            return None
        res = await db.execute(select(Agent).where(Agent.id == execution.agent_id))
        agent = res.scalar_one_or_none()
        if agent is None:
            return None
        model_cfg = agent.model_config_ or {}
        # Two bugs lived here and each hid the other. The module is
        # models.collection_grant, not models.agent_collection_grant, so the
        # import raised and the bare except set kb_ids empty — and the filter
        # asked for lowercase "read" while the column stores "READ". The
        # result was that no queue-routed agent ever received a collection:
        # knowledge_search was left out of the registry, the model narrated a
        # tool call as prose, and the answer was that it could not look
        # anything up. Nothing logged it.
        kb_ids: list[str] = []
        try:
            from sqlalchemy import select as _select

            from models.collection_grant import (  # type: ignore
                AgentCollectionGrant,
                CollectionPermission,
            )

            grants = await db.execute(
                _select(AgentCollectionGrant.collection_id).where(
                    AgentCollectionGrant.agent_id == agent.id,
                    AgentCollectionGrant.permission.in_(
                        [
                            CollectionPermission.READ,
                            CollectionPermission.WRITE,
                            CollectionPermission.ADMIN,
                        ]
                    ),
                )
            )
            kb_ids = [str(row[0]) for row in grants.all()]
        except Exception:
            logger.exception(
                "Could not resolve collection grants for agent %s — "
                "knowledge_search will not be available to this run",
                agent.id,
            )
            kb_ids = []
        return {
            "execution": execution,
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            # slug drives the per-agent post-processor lookup; without it
            # the canonical-anchor guardrail can't bind to fairvalue runs.
            "agent_slug": getattr(agent, "slug", "") or "",
            "agent_status": getattr(agent, "status", None),
            "is_pipeline": model_cfg.get("mode") == "pipeline",
            "model_cfg": model_cfg,
            "system_prompt": agent.system_prompt or "",
            "tool_names": model_cfg.get("tools", []) or [],
            "pipeline_config": model_cfg.get("pipeline_config"),
            "tenant_id": str(execution.tenant_id),
            "kb_ids": kb_ids,
            "per_execution_cost_limit": getattr(
                agent, "per_execution_cost_limit", None
            ),
        }


def _run_cost_cap(loaded: dict[str, Any], payload: dict[str, Any]) -> float | None:
    """The agent's per-run cap, tightened by a cost_limit the caller sent."""
    from engine.agent_budget import run_cost_limit

    return run_cost_limit(
        loaded.get("per_execution_cost_limit"), payload.get("cost_limit")
    )


def _moderation_sink(events: list[dict[str, Any]]) -> Any:
    """Collect gate decisions so queue-routed runs leave events like inline runs do."""

    def _sink(**kw: Any) -> None:
        decision = kw.get("decision")
        if decision is None:
            return
        events.append(
            {
                "source": kw.get("source") or "pre_llm",
                "outcome": getattr(decision, "outcome", "allowed"),
                "content_preview": (kw.get("content_preview") or "")[:500],
                "content_sha256": kw.get("content_sha256"),
                "acted_categories": list(
                    getattr(decision, "triggered_categories", None) or []
                ),
                "category_scores": dict(
                    getattr(decision, "category_scores", None) or {}
                ),
                "provider_response": getattr(decision, "provider_response", None) or {},
                "latency_ms": int(getattr(decision, "latency_ms", 0) or 0),
                "hold": kw.get("hold"),
                "consumed_review_id": kw.get("consumed_review_id"),
            }
        )

    return _sink


async def _persist_moderation_events(
    gate: Any, events: list[dict[str, Any]], execution_id: str, user_id: str | None
) -> None:
    """Write the collected events. Never fails the run."""
    if gate is None or not events:
        return
    try:
        from models.moderation_policy import (  # type: ignore
            ModerationEvent,
            ModerationEventOutcome,
        )

        from engine.moderation_hold import persist_gate_event

        Session = await _get_session_factory()
        async with Session() as db:
            for e in events:
                try:
                    outcome = ModerationEventOutcome(e["outcome"])
                except ValueError:
                    outcome = ModerationEventOutcome.ERROR
                ev = ModerationEvent(
                    id=uuid.uuid4(),
                    tenant_id=uuid.UUID(gate.tenant_id),
                    policy_id=uuid.UUID(gate.policy_id) if gate.policy_id else None,
                    user_id=uuid.UUID(user_id) if user_id else None,
                    execution_id=uuid.UUID(execution_id),
                    source=e["source"],
                    outcome=outcome,
                    content_sha256=e.get("content_sha256"),
                    content_preview=e.get("content_preview"),
                    provider_response=e.get("provider_response") or {},
                    acted_categories=e.get("acted_categories") or [],
                    latency_ms=e.get("latency_ms") or 0,
                )
                db.add(ev)
                # held content goes to the review inbox, the API announces it to reviewers
                await persist_gate_event(
                    db,
                    event=ev,
                    payload=e,
                    tenant_id=gate.tenant_id,
                    user_id=user_id,
                    policy_id=gate.policy_id,
                    execution_id=execution_id,
                    redaction_mask=getattr(gate, "redaction_mask", "█████"),
                )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("moderation events not saved for %s: %s", execution_id, exc)


async def _released_for(tenant_id: str, user_id: str | None) -> dict[str, str]:
    """Messages a reviewer released for this person, so a resend goes through once."""
    if not user_id:
        return {}
    try:
        from engine.moderation_hold import load_released

        Session = await _get_session_factory()
        async with Session() as db:
            return await load_released(db, tenant_id, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("released reviews not loaded: %s", exc)
        return {}


async def _load_moderation_gate(
    tenant_id: str,
) -> Any:
    """Build a GateConfig for the tenant's active moderation policy.

    Queue-routed runs don't pass through the API-side build_gate_context
    helper, so the consumer recreates the same shape here. Returns None
    when there's no active policy (gate-off path stays a no-op).
    """
    try:
        from sqlalchemy import desc, select

        from engine.moderation_gate import GateConfig
        from models.moderation_policy import (  # type: ignore
            ModerationAction,
            ModerationPolicy,
        )
    except Exception:
        return None
    try:
        Session = await _get_session_factory()
        async with Session() as db:
            res = await db.execute(
                select(ModerationPolicy)
                .where(ModerationPolicy.tenant_id == uuid.UUID(tenant_id))
                .where(ModerationPolicy.is_active.is_(True))
                .order_by(desc(ModerationPolicy.updated_at))
                .limit(1)
            )
            policy = res.scalars().first()
            if policy is None:
                return None
            return GateConfig(
                policy_id=str(policy.id),
                tenant_id=str(policy.tenant_id),
                user_id="",
                pre_llm=bool(policy.pre_llm),
                post_llm=bool(policy.post_llm),
                on_tool_output=bool(policy.on_tool_output),
                provider_model=str(policy.provider_model or "omni-moderation-latest"),
                thresholds=dict(policy.thresholds or {}),
                default_threshold=float(policy.default_threshold),
                category_actions=dict(policy.category_actions or {}),
                default_action=(
                    policy.default_action.value
                    if isinstance(policy.default_action, ModerationAction)
                    else str(policy.default_action)
                ),
                custom_patterns=list(policy.custom_patterns or []),
                redaction_mask=str(policy.redaction_mask or "█████"),
                fail_closed=bool(getattr(policy, "fail_closed", False)),
                event_sink=None,
                hold_timeout_minutes=int(
                    getattr(policy, "hold_timeout_minutes", 60) or 60
                ),
                hold_timeout_action=str(
                    getattr(policy, "hold_timeout_action", "reject") or "reject"
                ),
            )
    except Exception as e:
        logger.warning("could not load moderation gate for tenant %s: %s", tenant_id, e)
        return None


async def _update_usage_counters(
    api_key_id: str | None,
    user_id: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cost: float | None,
) -> None:
    """Debit api_keys + users monthly counters after a queue-routed run.

    Mirrors the inline path's app.core.usage.update_user_usage so customer
    quotas stay enforced when the API hands the execution off to NATS/Redis.
    Best-effort: a usage-write failure must never break the execution.
    """
    if not api_key_id and not user_id:
        return
    total_tokens = int((input_tokens or 0) + (output_tokens or 0))
    cost_delta = float(cost or 0)
    if total_tokens == 0 and cost_delta == 0:
        return
    try:
        from sqlalchemy import text

        Session = await _get_session_factory()
        async with Session() as side:
            if api_key_id:
                await side.execute(
                    text(
                        "UPDATE api_keys SET tokens_used = COALESCE(tokens_used, 0) + :n, "
                        "cost_used = COALESCE(cost_used, 0) + :c WHERE id = :id"
                    ),
                    {"n": total_tokens, "c": cost_delta, "id": uuid.UUID(api_key_id)},
                )
            if user_id:
                await side.execute(
                    text(
                        "UPDATE users SET tokens_used_this_month = COALESCE(tokens_used_this_month, 0) + :n, "
                        "cost_used_this_month = COALESCE(cost_used_this_month, 0) + :c WHERE id = :uid"
                    ),
                    {"n": total_tokens, "c": cost_delta, "uid": uuid.UUID(user_id)},
                )
            await side.commit()
    except Exception as _ue:
        logger.warning("consumer: usage counter update skipped for execution: %s", _ue)


async def _mark_started(execution_id: str) -> None:
    """Stamp started_at when the consumer picks up the row. No-op if already set."""
    from datetime import datetime, timezone
    from sqlalchemy import update
    from models.execution import Execution  # type: ignore

    Session = await _get_session_factory()
    async with Session() as db:
        await db.execute(
            update(Execution)
            .where(Execution.id == uuid.UUID(execution_id))
            .where(Execution.started_at.is_(None))
            .values(started_at=datetime.now(timezone.utc))
        )
        await db.commit()


LEASE_SECONDS = max(6, int(os.environ.get("CONSUMER_LEASE_SECONDS", "25")))
MAX_ATTEMPTS = max(1, int(os.environ.get("CONSUMER_MAX_ATTEMPTS", "3")))
RUNNER_ID = (
    f"{os.environ.get('HOSTNAME') or 'runtime'}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
)


async def _claim(execution_id: str) -> tuple[str, float]:
    """Take the run's lease. Returns (claimed|done|owned|missing|exhausted, seconds left on another lease)."""
    from datetime import timedelta

    from sqlalchemy import func, or_, select, update

    from models.execution import Execution, ExecutionStatus  # type: ignore

    eid = uuid.UUID(execution_id)
    Session = await _get_session_factory()
    async with Session() as db:
        got = (
            await db.execute(
                update(Execution)
                .where(
                    Execution.id == eid,
                    Execution.status == ExecutionStatus.RUNNING,
                    Execution.delivery_attempts < MAX_ATTEMPTS,
                    or_(
                        Execution.lease_expires_at.is_(None),
                        Execution.lease_expires_at < func.now(),
                        Execution.runner_id == RUNNER_ID,
                    ),
                )
                .values(
                    runner_id=RUNNER_ID,
                    lease_expires_at=func.now() + timedelta(seconds=LEASE_SECONDS),
                    delivery_attempts=Execution.delivery_attempts + 1,
                )
                .returning(Execution.delivery_attempts)
                .execution_options(synchronize_session=False)
            )
        ).first()
        if got is not None:
            await db.commit()
            return "claimed", 0.0
        cur = (
            await db.execute(
                select(
                    Execution.status,
                    Execution.runner_id,
                    func.extract("epoch", Execution.lease_expires_at - func.now()),
                ).where(Execution.id == eid)
            )
        ).first()
        await db.commit()
    if cur is None:
        return "missing", 0.0
    status, runner, left = cur
    if status != ExecutionStatus.RUNNING:
        return "done", 0.0
    left = float(left) if left is not None else 0.0
    if left > 0 and runner != RUNNER_ID:
        return "owned", left
    return "exhausted", 0.0


async def _renew(execution_id: str) -> bool:
    """Extend our lease. False only when another runner has taken the run over."""
    from datetime import timedelta

    from sqlalchemy import func, select, update

    from models.execution import Execution, ExecutionStatus  # type: ignore

    eid = uuid.UUID(execution_id)
    Session = await _get_session_factory()
    async with Session() as db:
        res = await db.execute(
            update(Execution)
            .where(
                Execution.id == eid,
                Execution.runner_id == RUNNER_ID,
                Execution.status == ExecutionStatus.RUNNING,
            )
            .values(lease_expires_at=func.now() + timedelta(seconds=LEASE_SECONDS))
            .execution_options(synchronize_session=False)
        )
        if res.rowcount:
            await db.commit()
            return True
        runner = (
            await db.execute(select(Execution.runner_id).where(Execution.id == eid))
        ).scalar()
        await db.commit()
    return runner in (None, RUNNER_ID)


async def _heartbeat(qm: Any, execution_id: str, run: dict[str, Any]) -> None:
    """Keep the delivery and the lease alive while the run is queued or running."""
    every = LEASE_SECONDS / 3
    while True:
        await asyncio.sleep(every)
        try:
            await qm.in_progress()
        except Exception as e:
            logger.debug("consumer: in_progress failed for %s: %s", execution_id, e)
        task = run.get("task")
        if task is None:
            continue
        try:
            if not await _renew(execution_id):
                logger.warning(
                    "consumer: %s was taken over by another runner, stopping here",
                    execution_id,
                )
                run["lost"] = True
                task.cancel()
                return
        except Exception as e:
            logger.warning("consumer: lease renew failed for %s: %s", execution_id, e)


async def _give_up(execution_id: str, trigger_id: str | None) -> None:
    msg = (
        f"The run was picked up {MAX_ATTEMPTS} times and the worker stopped each "
        "time before it finished, so it was not retried again."
    )
    await _mark_done(
        execution_id,
        "failed",
        None,
        msg,
        failure_code="STALE_SWEEP",
        trigger_id=trigger_id,
    )
    await _publish(execution_id, {"event": "error", "error": msg})


async def _run_traced(payload: dict, carrier: dict | None) -> None:
    from engine.tracing import extract_carrier, get_tracer

    ctx = extract_carrier(carrier) if carrier else None
    with get_tracer("abenix.consumer").start_as_current_span(
        "agent_runtime.run",
        context=ctx,
        attributes={
            "abenix.execution_id": str(payload.get("execution_id") or ""),
            "abenix.pool": os.environ.get("RUNTIME_POOL", "default"),
        },
    ):
        await _run_one(payload)


async def _handle_delivery(qm: Any, gate: asyncio.Semaphore) -> None:
    """Run one queued execution and ack only once it is finished, skipped or given up."""
    data = qm.data if isinstance(qm.data, dict) else {}
    payload = data.get("payload") or data
    execution_id = str(payload.get("execution_id") or "")
    if not execution_id:
        logger.error("consumer: payload missing execution_id: %s", payload)
        await qm.ack()
        return
    run: dict[str, Any] = {}
    hb = asyncio.create_task(_heartbeat(qm, execution_id, run))
    try:
        async with gate:
            state, left = await _claim(execution_id)
            if state == "claimed":
                if qm.num_delivered > 1:
                    logger.warning(
                        "consumer: taking over %s on delivery %d",
                        execution_id,
                        qm.num_delivered,
                    )
                run["task"] = asyncio.create_task(
                    _run_traced(payload, data.get("trace"))
                )
                try:
                    await run["task"]
                except asyncio.CancelledError:
                    if not run.get("lost"):
                        raise
            elif state == "owned":
                # the owner may be dead, look again once its lease has run out
                await qm.nak(delay=left + 1)
                return
            elif state == "exhausted":
                await _give_up(execution_id, payload.get("trigger_id"))
            elif state == "missing":
                logger.warning(
                    "consumer: execution %s not found; skipping", execution_id
                )
                await _publish(
                    execution_id, {"event": "error", "error": "execution row missing"}
                )
            else:
                logger.info(
                    "consumer: %s already finished, dropping duplicate", execution_id
                )
        await qm.ack()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("consumer: delivery for %s failed, will retry", execution_id)
        try:
            await qm.nak(delay=10)
        except Exception:
            pass
    finally:
        hb.cancel()


async def _pipeline_timeout() -> int:
    """Admin-configurable pipeline budget, falling back to the engine default.

    Settings live in the API package, which is present in this image, but the
    runtime must never fail a run because the settings table is unreachable.
    """
    from engine.pipeline import DEFAULT_PIPELINE_TIMEOUT_SECONDS

    try:
        from engine.runtime_settings import get_int_setting

        return await get_int_setting(
            "pipeline.timeout_seconds", DEFAULT_PIPELINE_TIMEOUT_SECONDS
        )
    except Exception:
        return DEFAULT_PIPELINE_TIMEOUT_SECONDS


def _merge_tool_trace(tool_calls: list[dict[str, Any]], trace: dict[str, Any]) -> None:
    """Attach a node_trace's result to the tool_call entry it belongs to."""
    if (trace.get("node_type") or "") != "tool_call":
        return
    name = trace.get("tool") or ""
    for tc in tool_calls:
        if tc.get("name") == name and "duration_ms" not in tc:
            tc["result_preview"] = trace.get("output_preview") or ""
            if trace.get("output"):
                tc["result"] = trace["output"]
            tc["is_error"] = bool(trace.get("is_error"))
            tc["duration_ms"] = trace.get("duration_ms")
            if trace.get("output_summary"):
                tc["output_summary"] = trace["output_summary"]
            record = (trace.get("metadata") or {}).get("decision_record")
            if record:
                tc["decision_record"] = record
            auto = (trace.get("metadata") or {}).get("autonomy")
            if auto:
                tc["autonomy"] = auto
            return


def _pipeline_tool_calls(node_results: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Tool nodes as tool_call entries so the Flight Recorder renders a pipeline like an agent run."""
    out: list[dict[str, Any]] = []
    for nid, nr in (node_results or {}).items():
        if not isinstance(nr, dict) or not nr.get("tool_name"):
            continue
        preview = nr.get("output")
        if not isinstance(preview, str):
            preview = json.dumps(preview, default=str) if preview is not None else ""
        entry = {
            "name": nr["tool_name"],
            "node_id": nid,
            "arguments": nr.get("resolved_arguments") or {},
            "result_preview": preview[:500],
            "result": preview[:8000],
            "label": nr.get("label") or "",
            "is_error": nr.get("status") == "failed",
            "duration_ms": nr.get("duration_ms"),
        }
        record = (nr.get("metadata") or {}).get("decision_record")
        if record:
            entry["decision_record"] = record
        auto = (nr.get("metadata") or {}).get("autonomy")
        if auto:
            entry["autonomy"] = auto
        out.append(entry)
    return out


async def _mark_done(
    execution_id: str,
    status: str,
    output: str | None,
    error: str | None,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost: float | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    trace_id: str | None = None,
    node_results: dict[str, Any] | None = None,
    execution_trace: dict[str, Any] | list[Any] | None = None,
    duration_ms: int | None = None,
    failure_code: str | None = None,
    model_used: str | None = None,
    confidence_score: float | None = None,
    trigger_id: str | None = None,
    risk_tier: str | None = None,
    risk_reasons: list[dict[str, Any]] | None = None,
) -> None:
    from datetime import datetime, timezone
    from sqlalchemy import select, update
    from models.execution import Execution, ExecutionStatus  # type: ignore

    Session = await _get_session_factory()

    target_status = (
        ExecutionStatus.COMPLETED if status == "completed" else ExecutionStatus.FAILED
    )
    completed_at = datetime.now(timezone.utc)
    values: dict[str, Any] = {
        "status": target_status,
        "output_message": output,
        "error_message": error,
        "completed_at": completed_at,
    }
    if input_tokens is not None:
        values["input_tokens"] = input_tokens
    if output_tokens is not None:
        values["output_tokens"] = output_tokens
    # Write a known cost even when zero — skipping 0.0 left the column NULL,
    # which reads as "never recorded" rather than "free".
    if cost is not None:
        values["cost"] = round(float(cost), 6)
    if tool_calls is not None:
        values["tool_calls"] = tool_calls
    if node_results is not None:
        values["node_results"] = node_results
    if execution_trace is not None:
        values["execution_trace"] = execution_trace
    if duration_ms is not None:
        values["duration_ms"] = duration_ms
    if model_used:
        values["model_used"] = model_used
    if confidence_score is not None:
        values["confidence_score"] = confidence_score
    if failure_code:
        values["failure_code"] = failure_code
    # the database stamped the starting tier, this is where the run ended up
    if risk_tier:
        values["risk_tier"] = risk_tier
    if risk_reasons:
        values["risk_reasons"] = risk_reasons
    if trace_id:
        values["trace_id"] = trace_id
    else:
        try:
            from engine.tracing import current_trace_id

            _tid = current_trace_id()
            if _tid:
                values["trace_id"] = _tid
        except Exception:
            pass
    # On failure, classify the error_message into a stable failure_code so
    # /alerts can group it and the Surgeon has something to act on.
    if target_status == ExecutionStatus.FAILED and error and not failure_code:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
            from app.core.failure_codes import classify_exception  # type: ignore

            values["failure_code"] = classify_exception(Exception(error))
        except Exception:
            # Fallback: a generic code so /alerts at least groups by something.
            values["failure_code"] = "PIPELINE_NODE_FAILED"
    async with Session() as db:
        # Backfill started_at + derive duration_ms when the runtime didn't
        # supply one. Without this, /executions surfaces null duration_ms
        # for every row this consumer touched.
        row = (
            await db.execute(
                select(Execution.started_at, Execution.created_at).where(
                    Execution.id == uuid.UUID(execution_id)
                )
            )
        ).one_or_none()
        if row is not None:
            started_at, created_at = row
            if started_at is None:
                started_at = created_at or completed_at
                values["started_at"] = started_at
            if "duration_ms" not in values and started_at is not None:
                values["duration_ms"] = int(
                    (completed_at - started_at).total_seconds() * 1000
                )
        await db.execute(
            update(Execution)
            .where(Execution.id == uuid.UUID(execution_id))
            .values(**values)
        )
        await db.commit()
    try:
        await _after_terminal(execution_id, status, error, trigger_id)
    except Exception as e:
        logger.warning(
            "consumer: terminal follow-ups failed for %s: %s", execution_id, e
        )


async def _write_trigger_outcome_fallback(
    Session: Any, status: str, trigger_id: str
) -> None:
    """Same columns write_trigger_outcome touches, for the slim runtime image."""
    from datetime import datetime, timezone
    from sqlalchemy import text

    async with Session() as db:
        await db.execute(
            text(
                "UPDATE agent_triggers SET last_status = :s, last_run_at = :t "
                "WHERE id = :id"
            ),
            {
                "s": "completed" if status == "completed" else "failed",
                "t": datetime.now(timezone.utc),
                "id": uuid.UUID(str(trigger_id)),
            },
        )
        await db.commit()


async def _trigger_of(Session: Any, execution_id: str) -> str | None:
    """The trigger recorded on the row, for a message that came without one."""
    from sqlalchemy import text

    try:
        async with Session() as db:
            tid = (
                await db.execute(
                    text("SELECT trigger_id FROM executions WHERE id = :id"),
                    {"id": uuid.UUID(str(execution_id))},
                )
            ).scalar()
        return str(tid) if tid else None
    except Exception as e:
        logger.debug("consumer: trigger lookup skipped for %s: %s", execution_id, e)
        return None


async def _after_terminal(
    execution_id: str, status: str, error: str | None, trigger_id: str | None
) -> None:
    """Best-effort follow-ups once the row is terminal: drift scoring, trigger status."""
    Session = await _get_session_factory()
    record = None
    try:
        from app.services.execution_hooks import record_terminal_by_id as record
    except Exception:
        # Runtime image ships without app.services, the scheduler backlog scan covers it
        logger.debug("consumer: execution_hooks unavailable for %s", execution_id)
    if record is not None:
        try:
            await record(Session, execution_id)
        except Exception as e:
            logger.warning("consumer: drift record skipped for %s: %s", execution_id, e)
    if not trigger_id:
        trigger_id = await _trigger_of(Session, execution_id)
    if not trigger_id:
        return
    writer = None
    try:
        from app.routers.triggers import write_trigger_outcome as writer
    except Exception:
        writer = None
    try:
        if writer is not None:
            await writer(Session, execution_id, status, error, trigger_id=trigger_id)
        else:
            await _write_trigger_outcome_fallback(Session, status, trigger_id)
    except Exception as e:
        logger.warning("consumer: trigger %s outcome write failed: %s", trigger_id, e)


_redis_pool: Any = None


def _emit_outcome(
    *,
    outcome: str,
    failure_code: str = "",
    agent_type: str = "agent",
    tenant_id: str = "",
) -> None:
    """Forward the runtime-side terminal outcome to the same Prometheus
    counters the API path emits to. Without this, executions that ran
    out-of-process (Wave-2 remote runtime) never hit
    executions_completed_total / executions_failed_total and never
    decremented active_executions, leaving both counters dead and the
    gauge drifting up by N for every runtime-completed run."""
    try:
        from app.core.failure_codes import emit_outcome_metric  # type: ignore

        emit_outcome_metric(
            outcome=outcome,
            failure_code=failure_code,
            agent_type=agent_type,
            tenant_id=tenant_id,
        )
    except Exception as e:
        logger.warning("consumer _emit_outcome failed: %s", e)


async def _publish(execution_id: str, event: dict) -> None:
    """Fire an event onto Redis pub/sub + append to the bounded replay log"""
    global _redis_pool
    try:
        import redis.asyncio as aioredis
        import json as _json

        if _redis_pool is None:
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            _redis_pool = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        payload = _json.dumps(event, default=str)
        channel = f"exec:events:{execution_id}"
        log_key = f"{channel}:log"
        pipe = _redis_pool.pipeline()
        pipe.publish(channel, payload)
        pipe.rpush(log_key, payload)
        pipe.ltrim(log_key, -500, -1)
        pipe.expire(log_key, 3600)
        await pipe.execute()
    except Exception as e:
        logger.debug("execution_bus.publish failed: %s", e)


async def _run_one(payload: dict) -> None:
    """Run a single execution. Publishes start/node/done/error events."""
    execution_id = payload.get("execution_id")
    if not execution_id:
        logger.error("consumer: payload missing execution_id: %s", payload)
        return

    message = payload.get("message", "")
    context = payload.get("context") or {}
    api_key_id = payload.get("api_key_id") or None
    user_id = payload.get("user_id") or None
    trigger_id = payload.get("trigger_id") or None

    loaded = await _load_execution(execution_id)
    if loaded is None:
        logger.warning("consumer: execution %s not found; skipping", execution_id)
        await _publish(
            execution_id, {"event": "error", "error": "execution row missing"}
        )
        return

    # First real work on this row — stamp started_at so duration_ms can be
    # computed at _mark_done time. No-op if the API path already stamped it.
    try:
        await _mark_started(execution_id)
    except Exception as _ms_err:
        logger.debug("consumer: _mark_started failed: %s", _ms_err)

    agent_name = loaded["agent_name"]
    tenant_id = loaded["tenant_id"]
    from engine.credentials import set_tenant as _set_credential_tenant

    _set_credential_tenant(tenant_id)
    is_pipeline = loaded["is_pipeline"]

    await _publish(
        execution_id,
        {
            "event": "start",
            "execution_id": execution_id,
            "agent": agent_name,
            "pool": os.environ.get("RUNTIME_POOL", "default"),
            "mode": "pipeline" if is_pipeline else "agent",
        },
    )

    _agg_tool_calls: list[dict[str, Any]] = []
    _mcp_clients: list[Any] = []
    try:
        if is_pipeline:
            from engine.pipeline import (
                PipelineExecutor,
                parse_pipeline_nodes,
                serialize_pipeline_result,
            )
            from engine.agent_executor import build_tool_registry

            _labels: dict[str, str] = {}

            async def on_node_start(node_id: str, tool_name: str) -> None:
                await _publish(
                    execution_id,
                    {
                        "event": "node_start",
                        "node_id": node_id,
                        "tool_name": tool_name,
                        "label": _labels.get(node_id, ""),
                    },
                )

            async def on_node_complete(
                node_id: str,
                status: str,
                duration_ms: int,
                output: Any,
                error_message: str | None = None,
                error_type: str | None = None,
            ) -> None:
                evt: dict[str, Any] = {
                    "event": "node_complete",
                    "node_id": node_id,
                    "status": status,
                    "duration_ms": duration_ms,
                }
                if status == "failed" and error_message:
                    evt["error"] = error_message[:2000]
                    if error_type:
                        evt["error_type"] = error_type
                elif output is not None:
                    out_text = str(output) if not isinstance(output, str) else output
                    evt["output_preview"] = out_text[:500]
                    # Provenance: surface the top-level JSON keys this node
                    # produced so the OracleNet provenance tab can render
                    # real lineage instead of static layout. Best-effort —
                    # if output isn't JSON we just skip the field map.
                    try:
                        from engine.post_process import _extract_json  # type: ignore

                        parsed = (
                            output
                            if isinstance(output, dict)
                            else _extract_json(out_text)
                        )
                        if isinstance(parsed, dict):
                            evt["produced_fields"] = sorted(list(parsed.keys()))[:50]
                    except Exception:
                        pass
                await _publish(execution_id, evt)

            pipeline_config = loaded["pipeline_config"] or {}
            raw_nodes = pipeline_config.get("nodes", [])
            nodes = parse_pipeline_nodes(raw_nodes)
            _labels.update({n.id: n.label for n in nodes if n.label})
            for node in nodes:
                if node.tool_name == "web_search" and "query" not in node.arguments:
                    node.arguments["query"] = message

            registry = build_tool_registry(
                loaded["tool_names"],
                agent_id=loaded.get("agent_id"),
                tenant_id=loaded.get("tenant_id"),
                kb_ids=loaded.get("kb_ids") or [],
                execution_id=execution_id,
                agent_name=agent_name,
                user_id=user_id or "",
                user_role=payload.get("role") or "",
                delegation_depth=int(payload.get("delegation_depth") or 0),
            )
            executor = PipelineExecutor(
                tool_registry=registry,
                timeout_seconds=await _pipeline_timeout(),
                on_node_start=on_node_start,
                on_node_complete=on_node_complete,
                agent_id=loaded["agent_id"],
                tenant_id=tenant_id,
                db_url=os.environ.get("DATABASE_URL", ""),
                cost_limit=_run_cost_cap(loaded, payload),
            )
            # Inject execution_id into context so the executor's healing
            # capture path can attribute the diff back to this run.
            # declared input_variables defaults sit under what the caller sent
            _defaults = {
                v["name"]: v["default"]
                for v in ((loaded.get("model_cfg") or {}).get("input_variables") or [])
                if isinstance(v, dict)
                and v.get("name")
                and v.get("default") not in (None, "")
            }
            result = await executor.execute(
                nodes,
                {
                    "user_message": message,
                    "__execution_id": execution_id,
                    **_defaults,
                    **context,
                },
            )
            serialized = serialize_pipeline_result(result)
            final_text = ""
            # Generic post-process for pipeline final_output: same logic as
            # the agent path. Drives OracleNet's strict-enum guarantees.
            _pipeline_warnings: list[str] = []
            try:
                _output_schema = (loaded.get("model_cfg") or {}).get("output_schema")
                if _output_schema and result.final_output is not None:
                    from engine.post_process import post_process  # type: ignore

                    _normalized, _pipeline_warnings = post_process(
                        result.final_output, _output_schema
                    )
                    if isinstance(_normalized, (dict, list)):
                        result.final_output = _normalized
                    if _pipeline_warnings:
                        logger.info(
                            "pipeline post_process: %s warnings",
                            len(_pipeline_warnings),
                        )
            except Exception as _e:
                logger.warning("pipeline post_process skipped: %s", _e)

            if result.final_output:
                # 50 KB cap matches the DB output_message column.
                final_text = (
                    result.final_output
                    if isinstance(result.final_output, str)
                    else json.dumps(result.final_output, default=str)[:50_000]
                )

            # Translate the executor's status to the DB row's status.
            # Without this, every pipeline run shows status=completed even
            # when one or more nodes failed — masking real failures from
            # /executions, /alerts, and the Surgeon's failure-diff capture.
            pipeline_status = "completed" if result.status == "completed" else "failed"
            failed_nodes = serialized.get("failed_nodes") or []
            err_text = None
            if pipeline_status == "failed":
                node_errs = []
                for nid, nr in (serialized.get("node_results") or {}).items():
                    if (nr.get("status") == "failed") and nr.get("error"):
                        node_errs.append(f"{nid}: {nr['error']}")
                err_text = (
                    "; ".join(node_errs) or f"failed nodes: {','.join(failed_nodes)}"
                )[:2000]

            await _mark_done(
                execution_id,
                pipeline_status,
                final_text,
                err_text,
                input_tokens=serialized["input_tokens"] or None,
                output_tokens=serialized["output_tokens"] or None,
                cost=serialized["cost"],
                node_results=serialized.get("node_results"),
                tool_calls=_pipeline_tool_calls(serialized.get("node_results")) or None,
                execution_trace={
                    "pipeline_status": serialized.get("status"),
                    "execution_path": serialized.get("execution_path"),
                    "failed_nodes": serialized.get("failed_nodes"),
                    "skipped_nodes": serialized.get("skipped_nodes"),
                    "node_results": serialized.get("node_results"),
                    "steps": serialized.get("steps") or [],
                },
                duration_ms=serialized.get("total_duration_ms"),
                failure_code=(
                    None
                    if pipeline_status == "completed"
                    else serialized.get("failure_code") or "PIPELINE_NODE_FAILED"
                ),
                trigger_id=trigger_id,
                risk_tier=serialized.get("risk_tier") or None,
                risk_reasons=serialized.get("risk_reasons") or None,
            )
            # failed steps spent real money, so quotas are debited either way
            await _update_usage_counters(
                api_key_id,
                user_id,
                serialized["input_tokens"],
                serialized["output_tokens"],
                serialized["cost"],
            )
            _emit_outcome(
                outcome="SUCCESS" if pipeline_status == "completed" else "FAILED",
                failure_code=(
                    "" if pipeline_status == "completed" else "PIPELINE_NODE_FAILED"
                ),
                agent_type="pipeline",
                tenant_id=str(tenant_id) if tenant_id else "",
            )
            _pipe_evt: dict[str, Any] = {
                "event": "done" if pipeline_status == "completed" else "error",
                "execution_id": execution_id,
                "output": final_text,
                "summary": serialized,
            }
            if err_text:
                _pipe_evt["error"] = err_text
            if _pipeline_warnings:
                _pipe_evt["validation_warnings"] = _pipeline_warnings[:20]
            await _publish(execution_id, _pipe_evt)
        else:
            from engine.agent_executor import (
                AgentExecutor,
                build_tool_registry,
                resolve_asset_schemas,
            )
            from engine.llm_router import LLMRouter

            from engine.tool_config_prompt import (
                append_mcp_warnings,
                build_tool_config_prompt,
            )
            from engine.tool_resolver import (
                load_agent_mcp_connections,
                resolve_tools,
            )

            _registry_kwargs: dict[str, Any] = dict(
                agent_id=loaded["agent_id"],
                tenant_id=tenant_id,
                execution_id=execution_id,
                agent_name=agent_name,
                db_url=os.environ.get("DATABASE_URL", ""),
                model_config=loaded.get("model_cfg") or {},
                user_id=user_id or "",
                user_role=payload.get("role") or "",
                delegation_depth=int(payload.get("delegation_depth") or 0),
            )
            # Same MCP resolution as the inline API path, read straight from the DB.
            _mcp_conns: list[dict[str, Any]] = []
            try:
                _Session = await _get_session_factory()
                async with _Session() as _mcp_db:
                    _mcp_conns = await load_agent_mcp_connections(
                        _mcp_db, loaded["agent_id"], tenant_id
                    )
            except Exception:
                logger.exception(
                    "Could not load MCP connections for agent %s", loaded["agent_id"]
                )
            if _mcp_conns:
                registry, _mcp_clients, _ = await resolve_tools(
                    loaded["tool_names"],
                    _mcp_conns,
                    kb_ids=loaded.get("kb_ids") or [],
                    **_registry_kwargs,
                )
            else:
                registry = build_tool_registry(
                    loaded["tool_names"],
                    kb_ids=loaded.get("kb_ids") or [],
                    **_registry_kwargs,
                )
            _system_prompt = append_mcp_warnings(
                build_tool_config_prompt(
                    loaded["system_prompt"],
                    loaded["model_cfg"].get("tool_config") or {},
                ),
                getattr(registry, "mcp_warnings", []),
            )
            llm_router = LLMRouter()
            _tool_cfg = loaded["model_cfg"].get("tool_config") or {}
            _asset_schemas = await resolve_asset_schemas(
                _tool_cfg, tenant_id=str(tenant_id or "")
            )
            # Pull the grounded-response contract and the moderation gate
            # for queue-routed runs too. Without this, RUNTIME_MODE=remote
            # plus QUEUE_BACKEND=nats silently bypassed both controls.
            _require_kb = bool(
                loaded["model_cfg"].get("require_knowledge_search", False)
            )
            _moderation_gate = await _load_moderation_gate(tenant_id)
            _mod_events: list[dict[str, Any]] = []
            if _moderation_gate is not None:
                _moderation_gate.event_sink = _moderation_sink(_mod_events)
                _moderation_gate.user_id = str(user_id or "")
                _moderation_gate.conversation_id = str(
                    payload.get("conversation_id") or ""
                )
                _moderation_gate.agent_id = str(loaded.get("agent_id") or "")
                _moderation_gate.released = await _released_for(tenant_id, user_id)
            executor = AgentExecutor(
                llm_router=llm_router,
                tool_registry=registry,
                system_prompt=_system_prompt,
                model=payload.get("model_override")
                or loaded["model_cfg"].get("model", "claude-sonnet-4-5-20250929"),
                temperature=loaded["model_cfg"].get("temperature", 0.7),
                max_iterations=loaded["model_cfg"].get("max_iterations", 10),
                max_tokens=loaded["model_cfg"].get("max_tokens", 4096),
                agent_id=loaded["agent_id"],
                execution_id=execution_id,
                tenant_id=str(loaded.get("tenant_id") or ""),
                # Apply tool-schema injection here too so the NATS
                # consumer path behaves the same as the inline path.
                tool_config=_tool_cfg,
                asset_schemas=_asset_schemas,
                require_knowledge_search=_require_kb,
                require_tools=list(loaded["model_cfg"].get("require_tools") or []),
                moderation_gate=_moderation_gate,
                cost_limit=_run_cost_cap(loaded, payload),
                history=payload.get("history") or [],
            )
            # Stream so per-iteration events reach Redis pub/sub live; invoke() only emits start+done.
            from types import SimpleNamespace

            _full_text_parts: list[str] = []
            _agg_tool_calls: list[dict[str, Any]] = []
            # _tool_runs pairs each tool invocation with a compact summary of
            # its result (status, metadata, etc) so per-agent post-processors
            # can recompute against canonical data without going back to the
            # tool. Filled from `node_trace` events, which carry the full
            # ToolResult.metadata.
            _tool_runs: list[dict[str, Any]] = []
            _node_traces: list[dict[str, Any]] = []
            _last_done: dict[str, Any] = {}
            async for _ev in executor.stream(message):
                if _ev.event == "done" and isinstance(_ev.data, dict):
                    _last_done = _ev.data
                    continue
                _evt: dict[str, Any] = {"event": _ev.event}
                if isinstance(_ev.data, dict):
                    _evt.update(_ev.data)
                else:
                    _evt["data"] = _ev.data
                await _publish(execution_id, _evt)
                if (
                    _ev.event == "moderation"
                    and isinstance(_ev.data, dict)
                    and _ev.data.get("source") == "post_llm"
                    and _ev.data.get("content") is not None
                ):
                    _full_text_parts[:] = [str(_ev.data["content"])]
                if _ev.event == "token":
                    _tok = (
                        _ev.data
                        if isinstance(_ev.data, str)
                        else (_ev.data or {}).get("content")
                        or (_ev.data or {}).get("text")
                        or ""
                    )
                    if _tok:
                        _full_text_parts.append(_tok)
                elif _ev.event == "tool_call" and isinstance(_ev.data, dict):
                    _agg_tool_calls.append(_ev.data)
                    try:
                        from app.core.execution_state import append_tool_call as _append_tc  # type: ignore

                        await _append_tc(execution_id, _ev.data)
                    except Exception as _ape:
                        logger.debug("append_tool_call failed: %s", _ape)
                elif _ev.event == "node_trace" and isinstance(_ev.data, dict):
                    _merge_tool_trace(_agg_tool_calls, _ev.data)
                    _node_traces.append(_ev.data)
                    # node_trace fires per tool with the real result.metadata
                    # attached — exactly what the post-processor needs to
                    # reconstruct the canonical anchor. Prefer the new
                    # output_summary field; fall back to a metadata projection
                    # for compatibility with older executor builds.
                    if (_ev.data.get("node_type") or "") == "tool_call":
                        _meta = _ev.data.get("metadata") or {}
                        _summary = _ev.data.get("output_summary") or {
                            "status": (
                                "ok"
                                if not _ev.data.get("is_error")
                                and _meta.get("status", "ok") == "ok"
                                else _meta.get("status") or "error"
                            ),
                            "resolved_symbol": _meta.get("resolved_symbol")
                            or _meta.get("symbol")
                            or "",
                            "symbol": _meta.get("symbol") or "",
                            "closes": _meta.get("closes") or [],
                            "prices_count": int(
                                _meta.get("price_count")
                                or len(_meta.get("closes") or [])
                            ),
                            "latest_close": _meta.get("latest_close"),
                            "fetched_at": _meta.get("fetched_at")
                            or _meta.get("last_refresh")
                            or "",
                            "currency": _meta.get("currency") or "",
                        }
                        _tool_runs.append(
                            {
                                "tool": _ev.data.get("tool") or "",
                                "input": _ev.data.get("input") or {},
                                "output_summary": _summary,
                            }
                        )
            await _persist_moderation_events(
                _moderation_gate, _mod_events, execution_id, user_id
            )
            result = SimpleNamespace(
                output="".join(_full_text_parts),
                tool_calls=_agg_tool_calls,
                input_tokens=int(_last_done.get("input_tokens", 0)),
                output_tokens=int(_last_done.get("output_tokens", 0)),
                cost=float(_last_done.get("cost", 0.0)),
                duration_ms=int(_last_done.get("duration_ms", 0)),
                model=_last_done.get("model", loaded["model_cfg"].get("model", "")),
            )
            output = result.output or str(result)

            # Generic post-process: if the agent's model_config declares an
            # output_schema, validate + normalize obvious enum drift before
            # the result lands in the DB. Warnings ride on the SSE event so
            # the UI can render them in a "validation" affordance.
            _validation_warnings: list[str] = []
            try:
                _output_schema = (loaded.get("model_cfg") or {}).get("output_schema")
                if _output_schema:
                    from engine.post_process import post_process  # type: ignore

                    _normalized, _validation_warnings = post_process(
                        output, _output_schema
                    )
                    if _validation_warnings:
                        logger.info(
                            "post_process: %s warnings for %s",
                            len(_validation_warnings),
                            agent_name,
                        )
                    # If we successfully parsed + normalized, persist the
                    # cleaned JSON string so the UI doesn't have to do its
                    # own enum coercion.
                    if isinstance(_normalized, (dict, list)):
                        output = json.dumps(_normalized, default=str)
            except Exception as _e:
                logger.warning("consumer: post_process skipped: %s", _e)

            # Per-agent deterministic post-processor — runs AFTER the generic
            # schema walker so domain knowledge (e.g. "TTF anchor must trump
            # the agent's fabricated decay") overrides whatever the LLM said.
            # No-op for agents that haven't registered one.
            try:
                _slug = loaded.get("agent_slug") or ""
                if _slug:
                    from engine.post_processors import get as _get_pp, run as _run_pp  # type: ignore
                    from engine.post_process import _extract_json as _xj  # type: ignore

                    if _get_pp(_slug) is not None:
                        _parsed = (
                            json.loads(output)
                            if isinstance(output, str)
                            and output.strip().startswith("{")
                            else None
                        )
                        if _parsed is None and isinstance(output, str):
                            _parsed = _xj(output)
                        if isinstance(_parsed, dict):
                            _rewritten = _run_pp(_slug, _parsed, _tool_runs, output)
                            if isinstance(_rewritten, dict):
                                output = json.dumps(_rewritten, default=str)
            except Exception as _ppe:
                logger.warning("consumer: per-agent post_processor skipped: %s", _ppe)
            # 50 KB cap matches /apps/api routers/agents.py and the DB
            # Text column. Bumped from 4_000 — the old cap silently
            # truncated long synthesizer briefs (OracleNet, executive
            # briefing) and produced invalid partial JSON in the UI.
            _AGENT_OUTPUT_CAP = 50_000
            full_output_str = str(output)[:_AGENT_OUTPUT_CAP]
            _tid_done = (
                _last_done.get("trace_id") if isinstance(_last_done, dict) else None
            )
            if not _tid_done:
                _tid_done = getattr(executor, "_trace_id_for_log", None)
            _exec_trace: dict[str, Any] | None = {
                "steps": _node_traces,
                "tool_calls": _agg_tool_calls,
                "warnings": list(_last_done.get("warnings") or []),
                "model": _last_done.get("effective_model") or _last_done.get("model"),
            }
            # a done payload carrying an error is a failed run, not a completed one
            _rt_error = _last_done.get("error")
            _final_status = "completed"
            _final_error: str | None = None
            _final_code: str | None = None
            if _rt_error == "grounding_required_violation" or _last_done.get(
                "grounding_violation"
            ):
                _final_status = "failed"
                _final_code = (
                    _last_done.get("failure_code") or "GROUNDING_REQUIRED_VIOLATION"
                )
                _final_error = "required tools not called: " + ", ".join(
                    _last_done.get("missing_tools") or ["knowledge_search"]
                )
            elif _rt_error == "moderation_blocked" or _last_done.get(
                "moderation_blocked"
            ):
                _final_status = "failed"
                _final_code = (
                    "MODERATION_HELD"
                    if _last_done.get("moderation_held")
                    else "MODERATION_BLOCKED"
                )
                _final_error = (
                    full_output_str[:2000] or "Moderation policy blocked the request"
                )
            elif _rt_error:
                _final_status = "failed"
                _final_error = str(_rt_error)[:2000]
                _final_code = _last_done.get("failure_code") or (
                    "SANDBOX_TIMEOUT" if "timed out" in str(_rt_error).lower() else None
                )
            await _mark_done(
                execution_id,
                _final_status,
                full_output_str,
                _final_error,
                input_tokens=getattr(result, "input_tokens", None),
                output_tokens=getattr(result, "output_tokens", None),
                cost=getattr(result, "cost", None),
                tool_calls=_agg_tool_calls or None,
                trace_id=_tid_done,
                execution_trace=_exec_trace,
                duration_ms=getattr(result, "duration_ms", None) or None,
                failure_code=_final_code,
                model_used=_last_done.get("effective_model") or _last_done.get("model"),
                confidence_score=_last_done.get("confidence_score"),
                trigger_id=trigger_id,
                risk_tier=_last_done.get("risk_tier") or None,
                risk_reasons=_last_done.get("risk_reasons") or None,
            )
            # Debit api_keys / users counters — the inline path does this
            # via app.core.usage.update_user_usage; queue-routed runs need
            # the same write or customer quotas silently never enforce.
            await _update_usage_counters(
                api_key_id,
                user_id,
                int(getattr(result, "input_tokens", 0) or 0),
                int(getattr(result, "output_tokens", 0) or 0),
                float(getattr(result, "cost", 0.0) or 0.0),
            )
            _emit_outcome(
                outcome="SUCCESS" if _final_status == "completed" else "FAILED",
                failure_code=_final_code
                or ("" if _final_status == "completed" else "UNKNOWN_ERROR"),
                agent_type="agent",
                tenant_id=str(tenant_id) if tenant_id else "",
            )
            _done_evt: dict[str, Any] = {
                "event": "done" if _final_status == "completed" else "error",
                "error": _final_error,
                "failure_code": _final_code,
                "execution_id": execution_id,
                "output": full_output_str,
                "input_tokens": getattr(result, "input_tokens", None),
                "output_tokens": getattr(result, "output_tokens", None),
                "cost": getattr(result, "cost", None),
                "duration_ms": getattr(result, "duration_ms", None),
                "model": _last_done.get("effective_model") or _last_done.get("model"),
            }
            if _validation_warnings:
                _done_evt["validation_warnings"] = _validation_warnings[:20]
            await _publish(execution_id, _done_evt)
    except Exception as e:
        logger.exception("consumer: execution %s failed: %s", execution_id, e)
        _tid_fail = None
        try:
            _tid_fail = getattr(executor, "_trace_id_for_log", None)  # type: ignore[name-defined]
        except Exception:
            pass
        await _mark_done(
            execution_id,
            "failed",
            None,
            str(e)[:2000],
            trace_id=_tid_fail,
            tool_calls=_agg_tool_calls or None,
            trigger_id=trigger_id,
        )
        # Classify + emit the runtime-side terminal outcome. Without this,
        # every remote-runtime failure left active_executions stuck +1
        # and never bumped executions_failed_total.
        _failure_code = "UNKNOWN_ERROR"
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
            from app.core.failure_codes import classify_exception  # type: ignore

            _failure_code = classify_exception(e)
        except Exception:
            pass
        try:
            from app.services.dlq import dead_letter  # type: ignore

            async with (await _get_session_factory())() as _db:
                await dead_letter(
                    _db,
                    execution_id,
                    reason=str(e)[:2000],
                    failure_code=_failure_code,
                    payload={
                        "message": message,
                        "context": context,
                        "is_pipeline": is_pipeline,
                        "api_key_id": api_key_id,
                        "runtime_pool": os.environ.get("RUNTIME_POOL", ""),
                    },
                )
                await _db.commit()
        except Exception as _dlq_exc:  # noqa: BLE001
            logger.warning(
                "dead letter write failed for %s: %s", execution_id, _dlq_exc
            )
        _emit_outcome(
            outcome="FAILED",
            failure_code=_failure_code,
            agent_type="pipeline" if is_pipeline else "agent",
            tenant_id=str(tenant_id) if tenant_id else "",
        )
        await _publish(execution_id, {"event": "error", "error": str(e)[:2000]})
    finally:
        for _c in _mcp_clients:
            try:
                await _c.close()
            except Exception:  # noqa: BLE001
                pass


async def _serve_health(port: int = 8001) -> None:
    """Tiny asyncio HTTP server on /health and /metrics."""
    # Touch engine.metrics to ensure all counters are registered in the
    # default registry before Prometheus asks for them.
    try:
        import engine.metrics  # type: ignore  # noqa: F401
    except Exception as e:
        logger.warning("engine.metrics not importable; /metrics will be empty: %s", e)
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    except Exception as e:
        logger.warning("prometheus_client unavailable; /metrics disabled: %s", e)
        generate_latest = None  # type: ignore
        CONTENT_TYPE_LATEST = "text/plain; charset=utf-8"  # type: ignore

    async def _handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request_line = await reader.readline()
            # Drain headers
            while True:
                line = await reader.readline()
                if not line or line in (b"\r\n", b"\n"):
                    break
        except Exception:
            request_line = b""

        path = b"/health"
        try:
            parts = request_line.split(b" ")
            if len(parts) >= 2:
                path = parts[1].split(b"?")[0]
        except Exception:
            pass

        if path == b"/metrics" and generate_latest is not None:
            try:
                payload = generate_latest()
                ctype = (
                    CONTENT_TYPE_LATEST.encode()
                    if isinstance(CONTENT_TYPE_LATEST, str)
                    else CONTENT_TYPE_LATEST
                )
            except Exception as e:
                payload = f"# metrics render failed: {e}".encode()
                ctype = b"text/plain; charset=utf-8"
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: " + ctype + b"\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + payload
            )
        else:
            body = b'{"ok":true,"mode":"consumer"}'
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + body
            )
        await writer.drain()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    server = await asyncio.start_server(_handle, "0.0.0.0", port)
    async with server:
        await server.serve_forever()


async def main() -> None:
    mode = os.environ.get("RUNTIME_MODE", "embedded").lower()
    pool = os.environ.get("RUNTIME_POOL", "default")
    backend_name = os.environ.get("QUEUE_BACKEND", "celery").lower()

    if mode != "remote":
        logger.info("consumer: RUNTIME_MODE=%s — not a remote consumer, exiting.", mode)
        return

    try:
        from engine.tracing import init_tracing

        init_tracing(f"agent-runtime-{pool}")
    except Exception as e:
        logger.warning("consumer: tracing init failed (continuing without): %s", e)

    if backend_name != "nats":
        from engine.queue_backend import CELERY_UNSUPPORTED  # type: ignore

        logger.error("consumer: %s", CELERY_UNSUPPORTED)
        raise SystemExit(1)

    logger.info("consumer: starting pool=%s backend=%s", pool, backend_name)

    health_port = int(os.environ.get("HEALTH_PORT", "8001"))
    health_task = asyncio.create_task(_serve_health(health_port))

    # Keep a module-level reference to the tool_stream_consumer task so it
    # is not garbage-collected — the variable is intentionally unused
    # after assignment. Prefix with `_` so ruff F841 stays quiet.
    _tool_worker_task: asyncio.Task | None = None
    if os.environ.get("TOOL_WORKER_ENABLED", "1") == "1":
        try:
            from tool_stream_consumer import consumer_loop as _tool_consumer_loop  # type: ignore

            _tool_worker_task = asyncio.create_task(_tool_consumer_loop())
            logger.info("tool_stream_consumer task launched alongside NATS consumer")
        except Exception as e:
            logger.warning("tool_stream_consumer launch failed: %s", e)

    from engine.queue_backend import get_queue_backend  # type: ignore

    backend = get_queue_backend()

    stop = asyncio.Event()

    def _stop(*_a: Any) -> None:
        logger.info("consumer: shutdown signal received")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except Exception:
            pass

    max_concurrency = int(
        os.environ.get("AGENT_CONCURRENCY")
        or os.environ.get("CONSUMER_MAX_CONCURRENCY")
        or "8"
    )
    concurrency_gate = asyncio.Semaphore(max_concurrency)
    in_flight: set[asyncio.Task[Any]] = set()
    logger.info("consumer: concurrency cap = %d", max_concurrency)

    try:
        async for qm in backend.stream(pool):
            if stop.is_set():
                break
            data = qm.data if isinstance(qm.data, dict) else {}
            await concurrency_gate.acquire()
            concurrency_gate.release()
            logger.info(
                "consumer: picked task %s from agents.%s",
                data.get("task_id", "?"),
                pool,
            )
            t = asyncio.create_task(_handle_delivery(qm, concurrency_gate))
            in_flight.add(t)
            t.add_done_callback(in_flight.discard)
    except Exception as e:
        logger.exception("consumer: stream loop crashed: %s", e)
        raise
    finally:
        health_task.cancel()
        try:
            await health_task
        except (asyncio.CancelledError, Exception):
            pass


if __name__ == "__main__":
    asyncio.run(main())
