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
            yield bool(r.scalar())


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


async def _check_due_triggers() -> None:
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
        return

    if not claimed:
        return
    logger.info("Claimed %d due scheduled triggers", len(claimed))
    await asyncio.gather(
        *(_run_trigger(tid, aid) for tid, aid in claimed), return_exceptions=True
    )


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


async def sweep_stale_executions() -> None:
    """Mark executions still in RUNNING past the max allowed window as FAILED."""
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

    from sqlalchemy import select, update
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
                return
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
                    )
                )
                found = r.all()
                if not found:
                    return
                # Runs parked on a HITL gate are alive, not stale
                try:
                    from app.core.hitl import waiting_execution_ids

                    waiting = await waiting_execution_ids(
                        [str(row[0]) for row in found]
                    )
                except Exception as e:
                    logger.warning("hitl waiting lookup failed, skipping sweep: %s", e)
                    return
                stale = [row for row in found if str(row[0]) not in waiting]
                if not stale:
                    return
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
            from app.core.ws_manager import ws_manager

            async with async_session() as db:
                for ex_id, uid, tid, agent_id, created in stale:
                    if not uid:
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
                if not uid:
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


async def reconcile_active_executions_gauge() -> None:
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
    except Exception as e:
        logger.error("reconcile_active_executions_gauge failed: %s", e, exc_info=True)


async def reset_monthly_quotas():
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
                return
            async with async_session() as db:
                await db.execute(
                    update(User).values(
                        tokens_used_this_month=0,
                        cost_used_this_month=0,
                        quota_reset_at=datetime.now(timezone.utc),
                    )
                )
                await db.execute(update(ApiKey).values(tokens_used=0, cost_used=0))
                await db.commit()
        logger.info("Monthly token quotas reset successfully")
    except Exception as e:
        logger.error("Failed to reset monthly quotas: %s", e, exc_info=True)


async def ping_models() -> None:
    """Hourly availability probe across every active LLM model."""
    try:
        from app.services.model_availability import run_pings

        await run_pings()
    except Exception as exc:
        logger.exception("ping_models failed: %s", exc)


async def score_drift_backlog() -> None:
    """Score finished executions the inline hooks missed, one replica at a time."""
    try:
        from app.core.deps import async_session
        from app.services.execution_hooks import scan_backlog

        async with advisory_lock(DRIFT_LOCK_KEY) as held:
            if not held:
                logger.debug("score_drift_backlog: another replica holds the lock")
                return
            recorded = await scan_backlog(
                async_session, interval_seconds=drift_scan_interval_seconds()
            )
        if recorded:
            logger.info("score_drift_backlog: recorded %d executions", recorded)
    except Exception as e:
        logger.error("score_drift_backlog failed: %s", e, exc_info=True)


def start_scheduler() -> None:
    """Start the APScheduler with the trigger check job."""
    scheduler = get_scheduler()
    if scheduler.running:
        return

    scheduler.add_job(
        _check_due_triggers,
        trigger="interval",
        seconds=30,
        id="check_due_triggers",
        name="Check and execute due scheduled triggers",
        replace_existing=True,
    )

    scheduler.add_job(
        ping_models,
        trigger="interval",
        minutes=60,
        id="ping_models",
        name="Hourly LLM availability probes",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45),
    )

    scheduler.add_job(
        sweep_stale_executions,
        trigger="interval",
        minutes=5,
        id="sweep_stale_executions",
        name="Mark stale RUNNING executions as FAILED",
        replace_existing=True,
    )

    scheduler.add_job(
        reconcile_active_executions_gauge,
        trigger="interval",
        minutes=5,
        id="reconcile_active_executions_gauge",
        name="Re-sync abenix_active_executions gauge to DB truth",
        replace_existing=True,
    )

    scheduler.add_job(
        score_drift_backlog,
        trigger="interval",
        seconds=drift_scan_interval_seconds(),
        id="score_drift_backlog",
        name="Score finished executions the drift hooks missed",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=120),
    )

    # Monthly token quota reset (runs on the 1st of each month at midnight UTC)
    scheduler.add_job(
        reset_monthly_quotas,
        trigger="cron",
        day=1,
        hour=0,
        minute=0,
        id="reset_monthly_quotas",
        name="Reset monthly token and cost quotas",
        replace_existing=True,
    )

    scheduler.add_job(
        _nightly_archive,
        trigger="cron",
        hour=2,
        minute=0,
        id="nightly_archive",
        name="Nightly archive of recording tables",
        replace_existing=True,
    )

    # Platform alerts arrive by Alertmanager webhook (routers/admin_alerts.py),
    # the Prometheus poller that used to run here is gone.

    scheduler.start()
    logger.info("Cron trigger scheduler started (checking every 30 seconds)")


async def _nightly_archive() -> None:
    try:
        from app.services.archiver import run_all_archives
        from app.core.deps import async_session

        async with advisory_lock(ARCHIVE_LOCK_KEY) as held:
            if not held:
                logger.debug("nightly archive: another replica holds the lock")
                return
            await run_all_archives(async_session)
    except Exception as e:
        logger.exception("nightly archive failed: %s", e)


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Cron trigger scheduler stopped")
    _scheduler = None
