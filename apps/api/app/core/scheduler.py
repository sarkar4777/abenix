"""Cron Trigger Scheduler — APScheduler-based job runner for scheduled agent trigge"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from croniter import croniter

logger = logging.getLogger("abenix.scheduler")

_scheduler: AsyncIOScheduler | None = None


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


async def _check_due_triggers() -> None:
    """Master job: find and execute all scheduled triggers past their next_run_at."""
    from sqlalchemy import select, and_

    # Lazy imports to avoid circular dependencies
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

    from app.core.deps import async_session
    from models.agent_trigger import AgentTrigger
    from models.agent import Agent, AgentStatus

    now = datetime.now(timezone.utc)

    try:
        async with async_session() as db:
            result = await db.execute(
                select(AgentTrigger, Agent)
                .join(Agent, AgentTrigger.agent_id == Agent.id)
                .where(
                    and_(
                        AgentTrigger.trigger_type == "schedule",
                        AgentTrigger.is_active.is_(True),
                        AgentTrigger.next_run_at.isnot(None),
                        AgentTrigger.next_run_at <= now,
                        Agent.status == AgentStatus.ACTIVE,
                    )
                )
            )
            due_triggers = result.all()

            if due_triggers:
                logger.info("Found %d due scheduled triggers", len(due_triggers))

            for trigger, agent in due_triggers:
                logger.info(
                    "Executing scheduled trigger '%s' (id=%s) for agent '%s'",
                    trigger.name,
                    trigger.id,
                    agent.name,
                )

                # Spawn background execution task
                asyncio.create_task(
                    _run_trigger(trigger, agent, db),
                    name=f"trigger-{trigger.id}",
                )

                # Update next_run_at immediately so we don't re-trigger
                trigger.last_run_at = now
                trigger.run_count = (trigger.run_count or 0) + 1
                if trigger.cron_expression:
                    trigger.next_run_at = next_cron_run(trigger.cron_expression, now)
                else:
                    trigger.is_active = False  # No cron = one-shot, disable

            if due_triggers:
                await db.commit()

    except Exception as e:
        logger.error("Scheduler check failed: %s", e, exc_info=True)


async def _run_trigger(trigger: Any, agent: Any, db: Any) -> None:
    """Execute a single trigger's agent in the background."""
    try:
        from app.routers.triggers import _execute_triggered_agent

        await _execute_triggered_agent(
            trigger_id=str(trigger.id),
            agent_id=str(agent.id),
            message=trigger.default_message or "Scheduled execution",
            context=(
                trigger.default_context
                if isinstance(trigger.default_context, dict)
                else {}
            ),
            tenant_id=str(trigger.tenant_id),
        )

        logger.info("Trigger %s executed successfully", trigger.id)
    except Exception as e:
        logger.error("Trigger %s execution failed: %s", trigger.id, e, exc_info=True)
        # Update last_status via a fresh session
        try:
            from app.core.deps import async_session

            async with async_session() as fresh_db:
                from sqlalchemy import update
                from models.agent_trigger import AgentTrigger

                await fresh_db.execute(
                    update(AgentTrigger)
                    .where(AgentTrigger.id == trigger.id)
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

    max_minutes = int(os.environ.get("STALE_EXECUTION_MAX_MINUTES", "30"))
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_minutes)

    # Postgres advisory lock so only one API replica runs the sweep
    # per interval. Without this, every replica's APScheduler would race
    # to mark the same rows + fire duplicate notifications. Lock is
    # session-scoped — releases when the `async with` exits.
    SWEEP_LOCK_KEY = 0x5354414C  # ASCII "STAL", a stable int4 sentinel
    try:
        async with async_session() as db:
            from sqlalchemy import text as _sql_text

            r = await db.execute(
                _sql_text("SELECT pg_try_advisory_lock(:k)"), {"k": SWEEP_LOCK_KEY}
            )
            if not bool(r.scalar()):
                logger.debug(
                    "sweep_stale_executions: another replica holds the lock; skipping"
                )
                return
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
            stale = r.all()
            if not stale:
                return
            ids = [row[0] for row in stale]
            logger.info(
                "Sweeping %d stale executions (older than %d min)",
                len(ids),
                max_minutes,
            )
            # Emit a Prometheus counter so the Grafana "Stale sweeps
            # (24h)" panel lights up. A healthy cluster has this near
            # zero — spikes indicate pods are crashing silently.
            try:
                from app.core.telemetry import stale_sweeps_total

                stale_sweeps_total.labels(reason="owning_pod_crashed").inc(len(ids))
            except Exception:
                pass

            await db.execute(
                update(Execution)
                .where(Execution.id.in_(ids))
                .values(
                    status=ExecutionStatus.FAILED,
                    error_message=(
                        f"Sweep: execution stuck in RUNNING for >{max_minutes} minutes. "
                        "The owning process likely crashed or was terminated before "
                        "it could update the execution status."
                    )[:2000],
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        # Fire notifications outside the DB transaction so a notification
        # glitch doesn't roll back the sweep.
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
        sweep_stale_executions,
        trigger="interval",
        minutes=5,
        id="sweep_stale_executions",
        name="Mark stale RUNNING executions as FAILED",
        replace_existing=True,
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

    scheduler.start()
    logger.info("Cron trigger scheduler started (checking every 30 seconds)")


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Cron trigger scheduler stopped")
    _scheduler = None
