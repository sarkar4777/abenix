"""Cron Trigger Scheduler — APScheduler-based job runner for scheduled agent trigge"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from croniter import croniter

logger = logging.getLogger("abenix.scheduler")

_BACKGROUND_TASKS: set = set()

_scheduler: AsyncIOScheduler | None = None

# Max triggers one replica claims per tick, the rest wait for the next tick
# or another replica.
TRIGGER_CLAIM_BATCH = 100

# pg advisory lock keys (int4, ASCII sentinels) for the singleton jobs.
QUOTA_LOCK_KEY = 0x51554F54  # "QUOT"
ARCHIVE_LOCK_KEY = 0x41524348  # "ARCH"
SWEEP_LOCK_KEY = 0x5354414C  # "STAL"
DRIFT_LOCK_KEY = 0x44524654  # "DRFT"
ESCALATE_LOCK_KEY = 0x45534341  # "ESCA"
ACTION_LOCK_KEY = 0x4143544E  # "ACTN"
VACUUM_LOCK_KEY = 0x56414355  # "VACU"
HOLD_LOCK_KEY = 0x484F4C44  # "HOLD"
RETAIN_LOCK_KEY = 0x52455441  # "RETA"
IMPROVE_LOCK_KEY = 0x494D5050  # "IMPP"
IMPROVE_WATCH_LOCK_KEY = 0x494D5057  # "IMPW"
PRUNE_EVENTS_LOCK_KEY = 0x45565052  # "EVPR"


def drift_scan_interval_seconds() -> int:
    return max(30, int(os.environ.get("DRIFT_SCAN_INTERVAL_SECONDS", "300")))


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the singleton scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            job_defaults={"coalesce": True, "max_instances": 1},
            timezone="UTC",
        )
    return _scheduler


def next_cron_run(cron_expr: str, base_time: datetime | None = None) -> datetime | None:
    """Calculate the next run time from a cron expression using croniter."""
    try:
        if not croniter.is_valid(cron_expr):
            return None
        base = base_time or datetime.now(timezone.utc)
        # croniter needs a naive datetime or will handle tz itself
        cron = croniter(cron_expr, base)
        next_dt = cron.get_next(datetime)
        # Ensure UTC timezone
        if next_dt.tzinfo is None:
            next_dt = next_dt.replace(tzinfo=timezone.utc)
        return next_dt
    except Exception as e:
        logger.warning("Invalid cron expression '%s': %s", cron_expr, e)
        return None


def is_valid_cron(cron_expr: str) -> bool:
    """Check if a cron expression is valid."""
    try:
        return croniter.is_valid(cron_expr)
    except Exception:
        return False


@contextlib.asynccontextmanager
async def advisory_lock(key: int) -> AsyncIterator[bool]:
    """Transaction-scoped pg advisory lock, released when the block exits.

    Yields whether this replica holds the lock. Transaction-scoped on
    purpose: a session-scoped lock survives the connection going back to
    the pool and ends up pinned to one pooled connection.
    """
    from sqlalchemy import text

    from app.core.deps import async_session

    async with async_session() as db:
        async with db.begin():
            r = await db.execute(
                text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key}
            )
            # this session sits idle on purpose while the guarded job runs
            await db.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))
            held = bool(r.scalar())
            from app.core.job_runs import note_lock

            note_lock(held)
            yield held


def due_trigger_claim_stmt(now: datetime):
    """Row-locked claim so three API replicas never fire the same trigger."""
    from sqlalchemy import and_, select

    from models.agent_trigger import AgentTrigger

    return (
        select(AgentTrigger)
        .where(
            and_(
                AgentTrigger.trigger_type == "schedule",
                AgentTrigger.is_active.is_(True),
                AgentTrigger.next_run_at.isnot(None),
                AgentTrigger.next_run_at <= now,
            )
        )
        .order_by(AgentTrigger.next_run_at)
        .limit(TRIGGER_CLAIM_BATCH)
        .with_for_update(skip_locked=True)
    )


def claim_trigger(trigger, now: datetime) -> None:
    """Advance a locked trigger so no other replica sees it as due."""
    trigger.last_run_at = now
    trigger.run_count = (trigger.run_count or 0) + 1
    if trigger.cron_expression:
        trigger.next_run_at = next_cron_run(trigger.cron_expression, now)
    else:
        trigger.is_active = False  # No cron = one-shot, disable


async def _check_due_triggers() -> dict[str, int] | None:
    """Master job: claim due scheduled triggers under row locks, then fire them."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

    from app.core.deps import async_session

    now = datetime.now(timezone.utc)
    claimed: list[tuple[str, str]] = []

    try:
        async with async_session() as db:
            # Locks are held until this transaction commits, which also
            # publishes the new next_run_at before any other replica can read.
            async with db.begin():
                result = await db.execute(due_trigger_claim_stmt(now))
                for trigger in result.scalars().all():
                    claim_trigger(trigger, now)
                    claimed.append((str(trigger.id), str(trigger.agent_id)))
    except Exception as e:
        logger.error("Scheduler check failed: %s", e, exc_info=True)
        return None

    if not claimed:
        return {"fired": 0}
    logger.info("Claimed %d due scheduled triggers", len(claimed))
    await asyncio.gather(
        *(_run_trigger(tid, aid) for tid, aid in claimed), return_exceptions=True
    )
    return {"fired": len(claimed)}


async def _run_trigger(trigger_id: str, agent_id: str) -> None:
    """Fire one claimed trigger: eligibility check, then dispatch.

    Opens its OWN session so concurrent triggers never share a connection.
    run_count / last_run_at were already advanced by the claim.
    """
    try:
        from sqlalchemy import select as _select

        from app.core.deps import fresh_session
        from app.routers.triggers import (
            check_trigger_eligibility,
            deactivate_trigger,
            dispatch_execution,
            trigger_stopped,
        )
        from models.agent import Agent  # type: ignore
        from models.agent_trigger import AgentTrigger  # type: ignore
        from models.user import User as UserModel  # type: ignore

        async with fresh_session() as db:
            trigger = (
                await db.execute(
                    _select(AgentTrigger).where(AgentTrigger.id == trigger_id)
                )
            ).scalar_one_or_none()
            if trigger is None:
                logger.warning("trigger %s vanished between claim and fire", trigger_id)
                return
            stopped = await trigger_stopped(trigger)
            if stopped:
                # this run is skipped, the schedule carries on once resumed
                logger.info("trigger %s skipped: %s", trigger_id, stopped)
                return
            agent = (
                await db.execute(_select(Agent).where(Agent.id == agent_id))
            ).scalar_one_or_none()
            owner = (
                await db.execute(
                    _select(UserModel).where(UserModel.id == trigger.created_by)
                )
            ).scalar_one_or_none()

            reason = await check_trigger_eligibility(db, trigger, agent, owner)
            if reason:
                logger.info("trigger %s deactivated: %s", trigger_id, reason)
                await deactivate_trigger(db, trigger, reason, owner=owner)
                return

            logger.info(
                "Executing scheduled trigger '%s' (id=%s) for agent '%s'",
                trigger.name,
                trigger.id,
                agent.name,
            )
            _execution, dispatched = await dispatch_execution(
                db,
                agent=agent,
                user=owner,
                message=trigger.default_message or "Scheduled execution",
                context=(
                    trigger.default_context
                    if isinstance(trigger.default_context, dict)
                    else {}
                ),
                trigger_id=str(trigger.id),
                trigger_kind="schedule",
                trigger_name=trigger.name,
            )
            if not dispatched:
                trigger.last_status = "failed"
                await db.commit()
                return
        logger.info("Trigger %s dispatched", trigger_id)
    except Exception as e:
        logger.error("Trigger %s execution failed: %s", trigger_id, e, exc_info=True)
        try:
            from sqlalchemy import update

            from app.core.deps import async_session
            from models.agent_trigger import AgentTrigger

            async with async_session() as fresh_db:
                await fresh_db.execute(
                    update(AgentTrigger)
                    .where(AgentTrigger.id == trigger_id)
                    .values(last_status="failed")
                )
                await fresh_db.commit()
        except Exception:
            pass


async def sweep_stale_executions() -> dict[str, int] | None:
    """Mark executions still in RUNNING past the max allowed window as FAILED."""
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

    from sqlalchemy import func, or_, select, update
    from app.core.deps import async_session

    from models.execution import Execution, ExecutionStatus

    max_minutes = int(os.environ.get("STALE_EXECUTION_MAX_MINUTES", "10"))
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_minutes)

    stale: list = []
    try:
        # One replica per interval, the lock drops with the helper's transaction
        async with advisory_lock(SWEEP_LOCK_KEY) as held:
            if not held:
                logger.debug("sweep_stale_executions: another replica holds the lock")
                return None
            async with async_session() as db:
                # Find the stale rows first so we can notify the owning users.
                r = await db.execute(
                    select(
                        Execution.id,
                        Execution.user_id,
                        Execution.tenant_id,
                        Execution.agent_id,
                        Execution.created_at,
                    ).where(
                        Execution.status == ExecutionStatus.RUNNING,
                        Execution.created_at < cutoff,
                        # a runtime pod still renewing its lease is alive
                        or_(
                            Execution.lease_expires_at.is_(None),
                            Execution.lease_expires_at < func.now(),
                        ),
                    )
                )
                found = r.all()
                if not found:
                    return {"swept": 0}
                # Runs parked on a HITL gate are alive, not stale
                try:
                    from app.core.hitl import waiting_execution_ids

                    waiting = await waiting_execution_ids(
                        [str(row[0]) for row in found]
                    )
                except Exception as e:
                    logger.error("hitl waiting lookup failed, skipping sweep: %s", e)
                    return {"swept": 0}
                stale = [row for row in found if str(row[0]) not in waiting]
                if not stale:
                    return {"swept": 0}
                ids = [row[0] for row in stale]
                logger.info(
                    "Sweeping %d stale executions (older than %d min)",
                    len(ids),
                    max_minutes,
                )
                # Feeds the Grafana "Stale sweeps (24h)" panel
                try:
                    from app.core.telemetry import stale_sweeps_total

                    stale_sweeps_total.labels(reason="owning_pod_crashed").inc(len(ids))
                except Exception:
                    pass

                await db.execute(
                    update(Execution)
                    .where(
                        Execution.id.in_(ids),
                        Execution.status == ExecutionStatus.RUNNING,
                        or_(
                            Execution.lease_expires_at.is_(None),
                            Execution.lease_expires_at < func.now(),
                        ),
                    )
                    .values(
                        status=ExecutionStatus.FAILED,
                        failure_code="STALE_SWEEP",
                        error_message=(
                            f"Sweep: execution stuck in RUNNING for >{max_minutes} minutes. "
                            "The owning process likely crashed or was terminated before "
                            "it could update the execution status."
                        )[:2000],
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()

        # Notifications run after the lock and the sweep transaction so a
        # notification glitch cannot roll back the sweep.
        try:
            from models.notification import Notification, NotificationType
            from app.core.notifications import user_wants_notification
            from app.core.ws_manager import ws_manager

            muted: set = set()
            async with async_session() as db:
                for ex_id, uid, tid, agent_id, created in stale:
                    if not uid:
                        continue
                    if not await user_wants_notification(
                        db, uid, NotificationType.EXECUTION_FAILED
                    ):
                        muted.add(uid)
                        continue
                    n = Notification(
                        tenant_id=tid,
                        user_id=uid,
                        type=NotificationType.EXECUTION_FAILED,
                        title="Agent run abandoned",
                        message=(
                            "An agent run was still marked RUNNING after "
                            f"{max_minutes} minutes and has been marked FAILED. "
                            "The underlying process likely crashed."
                        ),
                        link=f"/executions/{ex_id}",
                        metadata_={
                            "execution_id": str(ex_id),
                            "agent_id": str(agent_id) if agent_id else None,
                            "reason": "stale_sweep",
                            "age_minutes": max_minutes,
                        },
                    )
                    db.add(n)
                await db.commit()
            # WS fan-out to any users online
            for ex_id, uid, _, agent_id, _ in stale:
                if not uid or uid in muted:
                    continue
                try:
                    await ws_manager.send_to_user(
                        uid,
                        "notification",
                        {
                            "type": "execution_failed",
                            "title": "Agent run abandoned",
                            "message": "Stale execution swept.",
                            "link": f"/executions/{ex_id}",
                            "metadata": {
                                "execution_id": str(ex_id),
                                "reason": "stale_sweep",
                            },
                        },
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.warning("sweep notification failed: %s", e)

    except Exception as e:
        logger.error("sweep_stale_executions failed: %s", e, exc_info=True)
        return None
    return {"swept": len(stale)}


async def reconcile_active_executions_gauge() -> dict[str, int] | None:
    """Re-sync abenix_active_executions to the true RUNNING count per
    tenant. The gauge drifts whenever an inc/dec pair gets split across
    a crashed worker or a swallowed exception in the emit path. Run
    every 5 min so drift never exceeds one window."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

    from sqlalchemy import func, select
    from app.core.deps import async_session
    from app.core.telemetry import active_executions
    from models.execution import Execution, ExecutionStatus

    try:
        async with async_session() as db:
            # True per-tenant RUNNING count.
            r = await db.execute(
                select(Execution.tenant_id, func.count(Execution.id))
                .where(Execution.status == ExecutionStatus.RUNNING)
                .group_by(Execution.tenant_id)
            )
            counts = {str(tid): int(n) for tid, n in r.all() if tid is not None}

            # Every tenant that has ever had work — we need to touch
            # ALL of them to zero the gauge for tenants whose last
            # RUNNING row just terminated. Reading from active_executions
            # ._metrics is unreliable under prometheus multiprocess mode
            # (per-worker dicts that don't share), so source-of-truth is
            # the DB.
            r2 = await db.execute(select(Execution.tenant_id).distinct())
            all_tenants = {str(tid) for (tid,) in r2.all() if tid is not None}

        # Set every known tenant's gauge to its true RUNNING count
        # (defaulting to 0 for tenants whose last RUNNING just finished).
        for tid in all_tenants:
            active_executions.labels(tenant_id=tid).set(counts.get(tid, 0))

        if counts:
            logger.debug(
                "reconcile_active_executions_gauge: synced %d tenants", len(counts)
            )
        return {"tenants": len(all_tenants)}
    except Exception as e:
        logger.error("reconcile_active_executions_gauge failed: %s", e, exc_info=True)
        return None


async def reset_monthly_quotas() -> dict[str, int] | None:
    """Reset all users' and API keys' monthly usage counters."""
    from app.core.deps import async_session
    from sqlalchemy import update

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

    from models.user import User
    from models.api_key import ApiKey

    try:
        async with advisory_lock(QUOTA_LOCK_KEY) as held:
            if not held:
                logger.debug("reset_monthly_quotas: another replica holds the lock")
                return None
            async with async_session() as db:
                users = await db.execute(
                    update(User).values(
                        tokens_used_this_month=0,
                        cost_used_this_month=0,
                        quota_reset_at=datetime.now(timezone.utc),
                    )
                )
                keys = await db.execute(
                    update(ApiKey).values(tokens_used=0, cost_used=0)
                )
                await db.commit()
        logger.info("Monthly token quotas reset successfully")
        return {
            "users": int(getattr(users, "rowcount", 0) or 0),
            "api_keys": int(getattr(keys, "rowcount", 0) or 0),
        }
    except Exception as e:
        logger.error("Failed to reset monthly quotas: %s", e, exc_info=True)
        return None


async def ping_models() -> dict | None:
    """Hourly availability probe across every active LLM model."""
    try:
        from app.services.model_availability import run_pings

        out = await run_pings() or {}
        trans = out.get("transitions") or 0
        return {
            "checked": int(out.get("checked") or 0),
            "transitions": (
                len(trans) if isinstance(trans, (list, tuple)) else int(trans)
            ),
        }
    except Exception as exc:
        logger.exception("ping_models failed: %s", exc)
        return None


async def score_drift_backlog() -> dict[str, int] | None:
    """Score finished executions the inline hooks missed, one replica at a time."""
    try:
        from app.core.deps import async_session
        from app.services.execution_hooks import scan_backlog

        async with advisory_lock(DRIFT_LOCK_KEY) as held:
            if not held:
                logger.debug("score_drift_backlog: another replica holds the lock")
                return None
            recorded = await scan_backlog(
                async_session, interval_seconds=drift_scan_interval_seconds()
            )
        if recorded:
            logger.info("score_drift_backlog: recorded %d executions", recorded)
        return {"scored": int(recorded or 0)}
    except Exception as e:
        logger.error("score_drift_backlog failed: %s", e, exc_info=True)
        return None


ANNOUNCE_LOCK_KEY = 0x414E4E43  # "ANNC"


async def announce_finished_runs() -> dict[str, int] | None:
    """Notify owners of runs a runtime pool finished, one replica at a time."""
    try:
        from app.core.deps import async_session
        from app.services.run_announcer import announce_backlog

        async with advisory_lock(ANNOUNCE_LOCK_KEY) as held:
            if not held:
                return None
            sent = await announce_backlog(async_session)
        return {"announced": int(sent or 0)}
    except Exception as e:
        logger.error("announce_finished_runs failed: %s", e, exc_info=True)
        return None


def _tracked(job_id: str, func):
    """Record every run in Redis for the Background jobs page."""
    from app.core.job_runs import tracked

    return tracked(job_id, func)


def start_scheduler() -> None:
    """Start the APScheduler with the trigger check job."""
    scheduler = get_scheduler()
    if scheduler.running:
        return
    from app.core.job_runs import install_capture

    install_capture()

    scheduler.add_job(
        _tracked("check_due_triggers", _check_due_triggers),
        trigger="interval",
        seconds=30,
        id="check_due_triggers",
        name="Check and execute due scheduled triggers",
        replace_existing=True,
    )

    scheduler.add_job(
        _tracked("ping_models", ping_models),
        trigger="interval",
        minutes=60,
        id="ping_models",
        name="Hourly LLM availability probes",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45),
    )

    scheduler.add_job(
        _tracked("sweep_stale_executions", sweep_stale_executions),
        trigger="interval",
        minutes=5,
        id="sweep_stale_executions",
        name="Mark stale RUNNING executions as FAILED",
        replace_existing=True,
    )

    scheduler.add_job(
        _tracked("eval_schedules", _run_eval_schedules),
        trigger="interval",
        seconds=60,
        id="eval_schedules",
        name="Scheduled and model-change evaluation suite runs",
        replace_existing=True,
    )

    scheduler.add_job(
        _tracked(
            "reconcile_active_executions_gauge", reconcile_active_executions_gauge
        ),
        trigger="interval",
        minutes=5,
        id="reconcile_active_executions_gauge",
        name="Re-sync abenix_active_executions gauge to DB truth",
        replace_existing=True,
    )

    scheduler.add_job(
        _tracked("score_drift_backlog", score_drift_backlog),
        trigger="interval",
        seconds=drift_scan_interval_seconds(),
        id="score_drift_backlog",
        name="Score finished executions the drift hooks missed",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=120),
    )

    scheduler.add_job(
        _tracked("announce_finished_runs", announce_finished_runs),
        trigger="interval",
        seconds=15,
        id="announce_finished_runs",
        name="Tell owners about runs a runtime pool finished",
        replace_existing=True,
    )

    # Monthly token quota reset (runs on the 1st of each month at midnight UTC)
    scheduler.add_job(
        _tracked("reset_monthly_quotas", reset_monthly_quotas),
        trigger="cron",
        day=1,
        hour=0,
        minute=0,
        id="reset_monthly_quotas",
        name="Reset monthly token and cost quotas",
        replace_existing=True,
    )

    scheduler.add_job(
        _tracked("link_audit_chain", _link_audit_chain),
        trigger="interval",
        seconds=30,
        id="link_audit_chain",
        name="Link new audit rows into the tamper-evident chain",
        replace_existing=True,
    )

    scheduler.add_job(
        _tracked("dispatch_events", _dispatch_events),
        trigger="interval",
        seconds=2,
        id="dispatch_events",
        name="Fan out platform events and deliver them",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        _tracked("watch_sources", _watch_sources),
        trigger="interval",
        seconds=30,
        id="watch_sources",
        name="Check watched sources that are due",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=60),
    )

    scheduler.add_job(
        _tracked("prune_events", _prune_events),
        trigger="cron",
        hour=4,
        minute=5,
        id="prune_events",
        name="Drop delivered events past retention",
        replace_existing=True,
    )

    scheduler.add_job(
        _tracked("verify_audit_chain", _verify_audit_chain),
        trigger="cron",
        hour=3,
        minute=15,
        id="verify_audit_chain",
        name="Verify every tenant's audit chain",
        replace_existing=True,
    )

    scheduler.add_job(
        _tracked("escalate_approvals", _escalate_approvals),
        trigger="interval",
        minutes=1,
        id="escalate_approvals",
        name="Escalate tiered approvals nobody has acted on",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        _tracked("observe_actions", observe_actions),
        trigger="interval",
        seconds=30,
        id="observe_actions",
        name="Read due action outcomes, score them and move autonomy levels",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20),
    )

    scheduler.add_job(
        _tracked("nightly_archive", _nightly_archive),
        trigger="cron",
        hour=2,
        minute=0,
        id="nightly_archive",
        name="Nightly archive of recording tables",
        replace_existing=True,
    )

    scheduler.add_job(
        _tracked("pinecone_vacuum", enqueue_pinecone_vacuum),
        trigger="cron",
        hour=2,
        minute=30,
        id="pinecone_vacuum",
        name="Queue the daily Pinecone orphan vacuum",
        replace_existing=True,
    )

    scheduler.add_job(
        _tracked("moderation_review_tick", moderation_review_tick),
        trigger="interval",
        seconds=15,
        id="moderation_review_tick",
        name="Tell reviewers about held content and apply review time limits",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        _tracked("moderation_retention", moderation_retention),
        trigger="interval",
        minutes=60,
        id="moderation_retention",
        name="Purge moderation data past each tenant's retention",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=90),
    )

    scheduler.add_job(
        _tracked("improvements_tick", improvements_tick),
        trigger="interval",
        seconds=15,
        id="improvements_tick",
        name="Propose fixes for lesson groups over the threshold and drain the proof queue",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=40),
    )

    scheduler.add_job(
        _tracked("improvements_watch", improvements_watch),
        trigger="interval",
        minutes=5,
        id="improvements_watch",
        name="Compare released fixes with the old revision, keep or roll back",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=150),
    )

    scheduler.add_job(
        _tracked("group_lessons", group_lessons),
        trigger="interval",
        minutes=2,
        id="group_lessons",
        name="Turn new failures and feedback into lessons and group them",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45),
    )

    scheduler.add_job(
        _tracked("lesson_retention", lesson_retention),
        trigger="interval",
        minutes=60,
        id="lesson_retention",
        name="Purge lessons and feedback past each tenant's retention",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=120),
    )

    # Platform alerts arrive by Alertmanager webhook (routers/admin_alerts.py),
    # the Prometheus poller that used to run here is gone.

    scheduler.start()
    logger.info("Cron trigger scheduler started (checking every 30 seconds)")


async def _link_audit_chain() -> dict[str, int]:
    from app.services.audit_chain import run_chainer

    # drain the backlog in one tick, the lock keeps it to one replica
    linked = 0
    for _ in range(25):
        n = await run_chainer()
        linked += n
        if n == 0:
            break
    return {"linked": linked}


async def _dispatch_events() -> dict[str, int] | None:
    from app.services.events import dispatch_once

    return await dispatch_once()


async def _watch_sources() -> dict[str, int] | None:
    from app.services.source_watch import run_due

    try:
        return {"checked": int(await run_due() or 0)}
    except Exception:
        logger.exception("source watch failed")
        return None


async def _prune_events() -> dict[str, int] | None:
    from app.services.events import prune

    try:
        async with advisory_lock(PRUNE_EVENTS_LOCK_KEY) as held:
            if not held:
                return None
            return await prune()
    except Exception:
        logger.exception("event prune failed")
        return None


async def _run_eval_schedules() -> dict[str, int] | None:
    from app.services.eval_runner import EVAL_LOCK_KEY, scheduler_tick

    try:
        async with advisory_lock(EVAL_LOCK_KEY) as held:
            if held:
                return await scheduler_tick()
    except Exception:
        logger.exception("eval schedule tick failed")
    return None


async def _verify_audit_chain() -> dict[str, int] | None:
    from app.services.audit_chain import run_nightly_verify

    return await run_nightly_verify()


async def _escalate_approvals() -> dict[str, int] | None:
    from app.core.deps import async_session
    from app.routers.approvals import escalate_overdue

    try:
        async with advisory_lock(ESCALATE_LOCK_KEY) as held:
            if not held:
                return None
            async with async_session() as db:
                n = await escalate_overdue(db)
            if n:
                logger.info("escalated %d overdue approvals", n)
            return {"escalated": n}
    except Exception:
        logger.exception("approval escalation failed")
        return None


async def observe_actions() -> dict | None:
    from app.core.deps import async_session
    from app.services.autonomy import observe_tick

    try:
        async with advisory_lock(ACTION_LOCK_KEY) as held:
            if not held:
                return None
            async with async_session() as db:
                out = await observe_tick(db)
            if out.get("settled"):
                logger.info("observe_actions settled %d outcomes", out["settled"])
            # grants are checked every tick, only settled outcomes are news
            return {"settled": int(out.get("settled") or 0)}
    except Exception:
        logger.exception("observe_actions failed")
        return None


async def _nightly_archive() -> dict[str, int] | None:
    try:
        from app.services.archiver import run_all_archives
        from app.core.deps import async_session

        async with advisory_lock(ARCHIVE_LOCK_KEY) as held:
            if not held:
                logger.debug("nightly archive: another replica holds the lock")
                return None
            runs = await run_all_archives(async_session)
        rows = sum(int(getattr(r, "rows_archived", 0) or 0) for r in runs or [])
        return {"rows": rows, "runs": len(runs or [])}
    except Exception as e:
        logger.exception("nightly archive failed: %s", e)
        return None


async def enqueue_pinecone_vacuum() -> dict[str, bool] | None:
    """Hand the vacuum to the worker's documents queue, from one replica."""
    try:
        from app.workers.kb_reembed import enqueue_pinecone_vacuum as _enqueue

        async with advisory_lock(VACUUM_LOCK_KEY) as held:
            if not held:
                logger.debug("pinecone vacuum: another replica holds the lock")
                return None
            queued = bool(await _enqueue())
            if queued:
                logger.info("pinecone vacuum queued")
            return {"queued": queued}
    except Exception as e:
        logger.exception("pinecone vacuum enqueue failed: %s", e)
        return None


async def moderation_review_tick() -> dict[str, int] | None:
    from app.core.deps import async_session
    from app.services.moderation_review import announce_pending, expire_due

    try:
        async with advisory_lock(HOLD_LOCK_KEY) as held:
            if not held:
                return None
            async with async_session() as db:
                await announce_pending(db)
            async with async_session() as db:
                n = await expire_due(db)
            if n:
                logger.info("review time limit applied to %d held items", n)
            return {"expired": int(n or 0)}
    except Exception:
        logger.exception("moderation review tick failed")
        return None


async def moderation_retention() -> dict[str, int] | None:
    from app.core.deps import async_session
    from app.services.moderation_review import purge_retention

    try:
        async with advisory_lock(RETAIN_LOCK_KEY) as held:
            if not held:
                return None
            async with async_session() as db:
                out = await purge_retention(db)
            if any(out.values()):
                logger.info("moderation retention purge: %s", out)
            return out
    except Exception:
        logger.exception("moderation retention purge failed")
        return None


async def improvements_tick() -> dict[str, int] | None:
    """Enqueue under IMPP on one replica. Draining claims rows, so every proof worker drains."""
    from app.services import improvements

    try:
        async with advisory_lock(IMPROVE_LOCK_KEY) as held:
            if held:
                return await improvements.propose_tick()
        if improvements.drains_here():
            return {"drained": int(await improvements.drain_once() or 0)}
    except Exception:
        logger.exception("improvements tick failed")
    return None


async def improvements_watch() -> dict[str, int] | None:
    from app.services import improvements

    try:
        async with advisory_lock(IMPROVE_WATCH_LOCK_KEY) as held:
            if not held:
                return None
            out = await improvements.watch_tick()
            if out.get("rolled_back") or out.get("kept"):
                logger.info("improvement watch: %s", out)
            return out
    except Exception:
        logger.exception("improvements watch failed")
        return None


async def group_lessons() -> dict | None:
    from app.core.deps import async_session
    from app.services.lessons import CLUSTER_LOCK_KEY, run_tick

    try:
        async with advisory_lock(CLUSTER_LOCK_KEY) as held:
            if not held:
                return None
            out = await run_tick(async_session)
            if out.get("lessons"):
                logger.info("lessons grouped: %s", out)
            return out
    except Exception:
        logger.exception("lesson grouping failed")
        return None


async def lesson_retention() -> dict[str, int] | None:
    from app.core.deps import async_session
    from app.services.lessons import RETAIN_LOCK_KEY, purge_retention

    try:
        async with advisory_lock(RETAIN_LOCK_KEY) as held:
            if not held:
                return None
            async with async_session() as db:
                out = await purge_retention(db)
            if any(out.values()):
                logger.info("lesson retention purge: %s", out)
            return out
    except Exception:
        logger.exception("lesson retention purge failed")
        return None


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Cron trigger scheduler stopped")
    _scheduler = None
