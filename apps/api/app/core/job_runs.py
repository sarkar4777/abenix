"""Background job catalogue, run recording in Redis and Run now for the admin jobs page."""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger("abenix.jobs")

PREFIX = "abenix:jobs"
HISTORY_KEEP = 20
# a replica that has not run any job for this long is gone
REPLICA_STALE_SECONDS = 60
# how long a Run now request waits before answering "still running"
RUN_NOW_WAIT_SECONDS = float(os.environ.get("JOB_RUN_NOW_WAIT_SECONDS", "45"))
RUNNING_TTL_SECONDS = 15 * 60

JobFunc = Callable[[], Awaitable[Any]]


@dataclass(frozen=True)
class JobInfo:
    id: str
    title: str
    what: str
    why: str
    group: str
    labels: dict[str, str] = field(default_factory=dict)
    idle: str = "Nothing needed doing."
    confirm: str = ""
    # how several API replicas share it
    sharing: str = "lock"

    @property
    def destructive(self) -> bool:
        return bool(self.confirm)


GROUPS = (
    "Runs and schedules",
    "Approvals and review",
    "Learning and quality",
    "Retention and clean-up",
    "Platform upkeep",
)

SHARING = {
    "lock": "One replica at a time, the others skip that tick.",
    "claim": "Every replica runs it and claims rows, so no item is handled twice.",
    "each": "Every replica runs it for its own process.",
}

CATALOGUE: dict[str, JobInfo] = {
    j.id: j
    for j in (
        JobInfo(
            "check_due_triggers",
            "Scheduled triggers",
            "Starts an agent run for every schedule trigger whose time has come.",
            "Without it nothing on the Triggers page runs on its own.",
            "Runs and schedules",
            {"fired": "trigger started|triggers started"},
            "No trigger was due.",
            sharing="claim",
        ),
        JobInfo(
            "eval_schedules",
            "Scheduled evaluations",
            "Starts evaluation suites on their schedule or when an agent's model changes, and closes runs that stopped reporting.",
            "Quality checks keep running without anyone pressing Run.",
            "Runs and schedules",
            {
                "schedule": "suite started on schedule|suites started on schedule",
                "model_change": "suite rerun after a model change|suites rerun after a model change",
                "stale": "stuck evaluation run closed|stuck evaluation runs closed",
            },
            "No suite was due.",
        ),
        JobInfo(
            "watch_sources",
            "Source Watch checks",
            "Fetches every watched source whose check interval has passed and records what changed.",
            "This is how a changed regulation or price list reaches you without anyone looking.",
            "Runs and schedules",
            {"checked": "source checked|sources checked"},
            "No source was due.",
            sharing="claim",
        ),
        JobInfo(
            "announce_finished_runs",
            "Run notifications",
            "Tells people when a run they started on a runtime pool finished or failed, in the bell, Slack and email.",
            "Pool runs finish outside the API, so nobody would hear that they failed.",
            "Runs and schedules",
            {"announced": "run announced|runs announced"},
            "Every finished run was already announced.",
        ),
        JobInfo(
            "sweep_stale_executions",
            "Stuck run sweep",
            "Marks runs still shown as running past the time limit, with no live worker holding them, as failed and tells their owners.",
            "A crashed worker would otherwise leave runs spinning forever and counts on dashboards wrong.",
            "Runs and schedules",
            {"swept": "stuck run marked failed|stuck runs marked failed"},
            "No run was stuck.",
            confirm="Runs stuck in running past the time limit are marked failed and their owners are told. Runs a live worker still holds are left alone.",
        ),
        JobInfo(
            "reconcile_active_executions_gauge",
            "Running count correction",
            "Sets the running-now metric back to the true count from the database.",
            "Keeps Grafana and the dashboards honest after a crash.",
            "Runs and schedules",
            {"tenants": "tenant synced|tenants synced"},
            "Nothing to correct.",
            sharing="each",
        ),
        JobInfo(
            "dispatch_events",
            "Event delivery",
            "Turns new platform events into deliveries and sends them to webhooks and subscribed agents.",
            "Outbound webhooks and event-started agents depend on it.",
            "Runs and schedules",
            {
                "queued": "delivery queued|deliveries queued",
                "delivered": "delivery sent|deliveries sent",
            },
            "Nothing to send.",
            sharing="claim",
        ),
        JobInfo(
            "escalate_approvals",
            "Approval escalation",
            "Tells a tenant's admins once when a tiered approval has waited longer than its risk tier allows.",
            "High-risk approvals do not sit unnoticed.",
            "Approvals and review",
            {"escalated": "approval escalated|approvals escalated"},
            "No approval was overdue.",
        ),
        JobInfo(
            "moderation_review_tick",
            "Held content reminders",
            "Tells reviewers about newly held content and applies each policy's review time limit.",
            "Held messages would otherwise wait with nobody told.",
            "Approvals and review",
            {
                "expired": "held item decided by the time limit|held items decided by the time limit"
            },
            "Nothing held needed attention.",
        ),
        JobInfo(
            "observe_actions",
            "Action outcomes",
            "Reads the outcome of actions that are due, scores them and moves agents up or down the autonomy ladder.",
            "Earned autonomy only changes when this runs.",
            "Approvals and review",
            {
                "settled": "outcome scored|outcomes scored",
                "grants": "autonomy grant checked|autonomy grants checked",
            },
            "No outcome was due.",
        ),
        JobInfo(
            "group_lessons",
            "Lesson grouping",
            "Turns new failures and feedback into lessons and groups similar ones.",
            "Improvements start from these groups.",
            "Learning and quality",
            {
                "run_failed": "failed run turned into a lesson|failed runs turned into lessons",
                "drift": "drift alert turned into a lesson|drift alerts turned into lessons",
                "pipeline_failed": "failed pipeline turned into a lesson|failed pipelines turned into lessons",
                "eval_failed": "failed evaluation turned into a lesson|failed evaluations turned into lessons",
                "lessons": "lesson grouped|lessons grouped",
                "clusters_opened": "new group|new groups",
                "cases": "test case suggested|test cases suggested",
                "titled": "group titled|groups titled",
            },
            "No new failures or feedback.",
        ),
        JobInfo(
            "improvements_tick",
            "Improvement proposals",
            "Proposes fixes for lesson groups over the threshold and works through the proof queue.",
            "Agents get better from what went wrong, with proof before anything changes.",
            "Learning and quality",
            {
                "proposed": "fix proposed|fixes proposed",
                "claimed": "proof started|proofs started",
                "drained": "proof run|proofs run",
            },
            "No group needed a fix.",
        ),
        JobInfo(
            "improvements_watch",
            "Released fix watch",
            "Compares released fixes with the old revision and keeps or rolls back each one when its watch ends.",
            "A fix that made things worse is rolled back without anyone watching.",
            "Learning and quality",
            {
                "kept": "fix kept|fixes kept",
                "rolled_back": "fix rolled back|fixes rolled back",
                "watching": "fix still watched|fixes still watched",
                "stopped": "watch stopped|watches stopped",
            },
            "No released fix was being watched.",
            confirm="Fixes whose watch period is over are kept or rolled back now, based on the results so far.",
        ),
        JobInfo(
            "score_drift_backlog",
            "Drift scoring",
            "Scores finished runs that the live drift checks missed.",
            "Drift charts and pipeline healing need every run scored.",
            "Learning and quality",
            {"scored": "run scored|runs scored"},
            "Every finished run was already scored.",
        ),
        JobInfo(
            "moderation_retention",
            "Moderation retention",
            "Removes held text, decision records and event previews older than each tenant's moderation retention.",
            "Sensitive content is kept only as long as your policy says.",
            "Retention and clean-up",
            {
                "held_text": "held text removed|held texts removed",
                "records": "decision record deleted|decision records deleted",
                "previews": "event preview cleared|event previews cleared",
            },
            "Nothing was past its retention.",
            confirm="Held text, decision records and event previews older than each tenant's moderation retention are removed for good.",
        ),
        JobInfo(
            "lesson_retention",
            "Lesson retention",
            "Deletes lessons, feedback and closed groups older than each tenant's lesson retention.",
            "Failure examples can hold customer text, so they are not kept forever.",
            "Retention and clean-up",
            {
                "lessons": "lesson deleted|lessons deleted",
                "feedback": "feedback deleted|feedback deleted",
                "clusters": "closed group deleted|closed groups deleted",
            },
            "Nothing was past its retention.",
            confirm="Lessons, feedback and closed groups older than each tenant's lesson retention are deleted for good.",
        ),
        JobInfo(
            "prune_events",
            "Event clean-up",
            "Deletes delivered webhook attempts after 30 days and sent events after 7 days.",
            "Keeps the event tables small. Failed deliveries are kept for the Events page.",
            "Retention and clean-up",
            {
                "deliveries": "delivered attempt deleted|delivered attempts deleted",
                "events": "sent event deleted|sent events deleted",
            },
            "Nothing was old enough to delete.",
            confirm="Delivered webhook attempts older than 30 days and sent events older than 7 days are deleted for good.",
        ),
        JobInfo(
            "nightly_archive",
            "Nightly archive",
            "Moves rows older than each table's retention policy into compressed archive files and removes them from the live tables.",
            "Keeps the database small. Archived rows can be restored from Admin, Archives.",
            "Retention and clean-up",
            {
                "rows": "row archived|rows archived",
                "runs": "table archive run|table archives run",
            },
            "No table had rows past its retention.",
            confirm="Rows older than each tenant's retention policy are written to archive files and removed from the live tables. They can be restored from Admin, Archives.",
        ),
        JobInfo(
            "pinecone_vacuum",
            "Vector clean-up",
            "Queues the removal of vectors whose documents were deleted.",
            "Deleted documents stop turning up in search.",
            "Retention and clean-up",
            {"queued": "clean-up queued"},
            "The clean-up was not queued.",
            confirm="Vectors whose documents no longer exist are deleted from the vector store by the worker.",
        ),
        JobInfo(
            "reset_monthly_quotas",
            "Monthly quota reset",
            "Sets every user's and API key's monthly token and cost usage back to zero.",
            "Without it people hit their monthly limit once and stay blocked.",
            "Platform upkeep",
            {
                "users": "user reset|users reset",
                "api_keys": "API key reset|API keys reset",
            },
            "Nobody had usage to reset.",
            confirm="Every user's and API key's usage this month goes back to zero, in every tenant. Limits start counting again from now.",
        ),
        JobInfo(
            "ping_models",
            "Model availability check",
            "Sends a tiny request to every active model and records which ones answer.",
            "Model pickers and fallbacks avoid models that are down.",
            "Platform upkeep",
            {
                "checked": "model checked|models checked",
                "transitions": "status change|status changes",
            },
            "No active model to check.",
            sharing="each",
        ),
        JobInfo(
            "link_audit_chain",
            "Audit chain linking",
            "Links new audit log rows into the tamper-evident hash chain.",
            "A changed or deleted audit row can be detected.",
            "Platform upkeep",
            {"linked": "audit row linked|audit rows linked"},
            "No new audit rows.",
        ),
        JobInfo(
            "verify_audit_chain",
            "Audit chain check",
            "Re-checks every tenant's audit chain and alerts admins when a row was changed.",
            "Proves the audit log has not been tampered with.",
            "Platform upkeep",
            {
                "tenants": "tenant checked|tenants checked",
                "broken": "broken chain found|broken chains found",
            },
            "No tenant to check.",
        ),
    )
}

# filled by scheduler._tracked as jobs are registered
_FUNCS: dict[str, JobFunc] = {}

_RUN: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "job_run", default=None
)


def register(job_id: str, func: JobFunc) -> None:
    _FUNCS[job_id] = func


def registered(job_id: str) -> JobFunc | None:
    return _FUNCS.get(job_id)


def replica() -> str:
    return os.environ.get("HOSTNAME") or socket.gethostname() or "local"


def note_lock(held: bool) -> None:
    """Called by advisory_lock so a run that lost the lock reads as skipped."""
    run = _RUN.get()
    if run is not None and not held:
        run["lock_missed"] = True


class _Capture(logging.Handler):
    """Collects errors logged while a job runs, the jobs swallow their own exceptions."""

    def emit(self, record: logging.LogRecord) -> None:
        run = _RUN.get()
        if run is None or record.levelno < logging.ERROR:
            return
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            msg = str(record.msg)
        detail = msg
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            detail = f"{msg}: {type(exc).__name__}: {exc}"
        run["errors"].append(detail[:2000])


_capture = _Capture(level=logging.ERROR)


def install_capture() -> None:
    root = logging.getLogger()
    if _capture not in root.handlers:
        root.addHandler(_capture)


# plain words for what went wrong

_PLAIN = (
    (
        (
            "connection was closed",
            "connection is closed",
            "server closed the connection",
            "connectionreset",
            "connection reset",
        ),
        "It lost its database connection partway through, usually during a restart. It tries again on its next run.",
    ),
    (
        (
            "connection refused",
            "could not connect",
            "connectionrefused",
            "name or service not known",
            "temporary failure in name resolution",
        ),
        "It could not reach a service it needs, usually the database or Redis. Check Cluster Health.",
    ),
    (
        ("timeout", "timed out"),
        "It took too long and was stopped. It tries again on its next run.",
    ),
    (
        ("does not exist", "undefinedtable", "undefinedcolumn", "no such table"),
        "The database is missing a table or column it needs. The migrations have not been run on this database.",
    ),
    (
        ("permission denied", "insufficientprivilege"),
        "The database refused the change because the app's user lacks permission.",
    ),
    (
        ("401", "unauthorized", "invalid api key", "authentication", "revoked"),
        "A provider rejected the credentials. Check the keys under Admin, Model Selection.",
    ),
    (
        ("deadlock",),
        "It collided with another change to the same rows. It tries again on its next run.",
    ),
    (
        ("out of memory", "memoryerror"),
        "It ran out of memory.",
    ),
    (
        ("no space left",),
        "The disk is full.",
    ),
)


def plain_error(detail: str | None) -> str | None:
    if not detail:
        return None
    low = detail.lower()
    for needles, words in _PLAIN:
        if any(n in low for n in needles):
            return words
    first = detail.strip().splitlines()[0][:240]
    return f"It stopped with an error: {first}"


def _jsonable(result: Any) -> Any:
    if result is None or isinstance(result, (bool, int, float, str)):
        return result
    if isinstance(result, dict):
        return {str(k): _jsonable(v) for k, v in result.items()}
    if isinstance(result, (list, tuple)):
        return [_jsonable(v) for v in result]
    return str(result)


def summarize(job_id: str, result: Any) -> str:
    info = CATALOGUE.get(job_id)
    idle = info.idle if info else "Nothing needed doing."
    if not isinstance(result, dict):
        return idle
    parts: list[str] = []
    labels = info.labels if info else {}
    for k, v in result.items():
        label = labels.get(k, k.replace("_", " "))
        one, _, many = label.partition("|")
        many = many or one
        if isinstance(v, bool):
            if v:
                parts.append(one[:1].upper() + one[1:])
            continue
        if isinstance(v, (int, float)) and v:
            parts.append(f"{v:g} {one if v == 1 else many}")
    return ", ".join(parts) + "." if parts else idle


# Redis


_client: Any = None


async def redis() -> Any:
    global _client
    if _client is None:
        import redis.asyncio as aioredis

        from app.core.execution_state import _redis_url

        _client = aioredis.from_url(
            _redis_url(),
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    return _client


def _key(job_id: str, part: str = "") -> str:
    return f"{PREFIX}:{job_id}{':' + part if part else ''}"


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _local_next(job_id: str) -> datetime | None:
    try:
        from app.core.scheduler import get_scheduler

        job = get_scheduler().get_job(job_id)
        return job.next_run_time if job else None
    except Exception:  # noqa: BLE001
        return None


async def _claim_running(r: Any, job_id: str, entry: dict) -> bool:
    try:
        return bool(
            await r.set(
                _key(job_id, "running"),
                json.dumps(entry),
                nx=True,
                ex=RUNNING_TTL_SECONDS,
            )
        )
    except Exception:  # noqa: BLE001
        return False


async def _release_running(r: Any, job_id: str, run_id: str) -> None:
    try:
        raw = await r.get(_key(job_id, "running"))
        if raw and json.loads(raw).get("run_id") == run_id:
            await r.delete(_key(job_id, "running"))
    except Exception:  # noqa: BLE001
        pass


async def _store(r: Any, job_id: str, rec: dict) -> None:
    now = rec["finished_at"]
    host = rec["replica"]
    await r.hset(f"{PREFIX}:replicas", host, now)
    nxt = _local_next(job_id)
    if nxt is not None:
        await r.hset(_key(job_id, "next"), host, _iso(nxt))
    if rec["outcome"] == "skipped":
        await r.hincrby(_key(job_id), "skip_count", 1)
        await r.hset(_key(job_id), mapping={"last_skipped_at": now})
        return
    fields = {
        "last_started_at": rec["started_at"],
        "last_finished_at": now,
        "last_outcome": rec["outcome"],
        "last_duration_ms": rec["duration_ms"],
        "last_summary": rec["summary"],
        "last_result": json.dumps(rec["result"]),
        "last_error": rec["error"] or "",
        "last_error_detail": rec["error_detail"] or "",
        "last_trigger": rec["trigger"],
        "last_by": rec["by"] or "",
        "last_replica": host,
    }
    if rec["outcome"] == "failed":
        fields["last_failed_at"] = now
        fields["last_failed_error"] = rec["error"] or ""
    else:
        fields["last_ok_at"] = now
    await r.hset(_key(job_id), mapping=fields)
    await r.hincrby(_key(job_id), "run_count", 1)
    if rec["outcome"] == "failed":
        await r.hincrby(_key(job_id), "fail_count", 1)
    if rec["trigger"] == "manual":
        await r.hincrby(_key(job_id), "manual_count", 1)
    # busy jobs tick every few seconds, history keeps runs that did or meant something
    worth = (
        rec["outcome"] == "failed"
        or rec["trigger"] == "manual"
        or rec["summary"] != (CATALOGUE[job_id].idle if job_id in CATALOGUE else "")
    )
    if worth:
        await r.lpush(_key(job_id, "history"), json.dumps(rec))
        await r.ltrim(_key(job_id, "history"), 0, HISTORY_KEEP - 1)


async def execute(
    job_id: str,
    func: JobFunc,
    *,
    trigger: str = "schedule",
    by: str | None = None,
) -> dict[str, Any]:
    """Run one job, never raise, record the outcome. Returns the run record."""
    run: dict[str, Any] = {"errors": [], "lock_missed": False}
    token = _RUN.set(run)
    run_id = uuid.uuid4().hex
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    r = None
    owns = False
    try:
        r = await redis()
        owns = await _claim_running(
            r,
            job_id,
            {
                "run_id": run_id,
                "started_at": _iso(started),
                "trigger": trigger,
                "by": by,
                "replica": replica(),
            },
        )
    except Exception:  # noqa: BLE001
        r = None
    result: Any = None
    try:
        result = await func()
    except Exception as e:  # noqa: BLE001
        run["errors"].append(f"{type(e).__name__}: {e}"[:2000])
        logger.warning("job %s raised: %s", job_id, e)
    finally:
        _RUN.reset(token)
    duration = int((time.monotonic() - t0) * 1000)
    if run["errors"]:
        outcome = "failed"
    elif run["lock_missed"] and result is None:
        outcome = "skipped"
    else:
        outcome = "ok"
    detail = run["errors"][-1] if run["errors"] else None
    rec = {
        "run_id": run_id,
        "job_id": job_id,
        "started_at": _iso(started),
        "finished_at": _iso(datetime.now(timezone.utc)),
        "duration_ms": duration,
        "outcome": outcome,
        "result": _jsonable(result),
        "summary": (
            "Another replica held the lock, so this one skipped."
            if outcome == "skipped"
            else summarize(job_id, result)
        ),
        "error": plain_error(detail),
        "error_detail": detail,
        "trigger": trigger,
        "by": by,
        "replica": replica(),
    }
    if r is not None:
        try:
            await _store(r, job_id, rec)
            if owns:
                await _release_running(r, job_id, run_id)
        except Exception as e:  # noqa: BLE001
            logger.debug("job %s run not recorded: %s", job_id, e)
    return rec


def tracked(job_id: str, func: JobFunc) -> JobFunc:
    register(job_id, func)

    async def run() -> None:
        await execute(job_id, func)

    run.__name__ = f"tracked_{job_id}"
    run.__qualname__ = run.__name__
    return run


# what the page reads


def describe_schedule(trigger: Any) -> str:
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    if isinstance(trigger, IntervalTrigger):
        return _every(trigger.interval)
    if isinstance(trigger, CronTrigger):
        f = {x.name: str(x) for x in trigger.fields}
        hm = None
        if f.get("hour", "*").isdigit() and f.get("minute", "*").isdigit():
            hm = f"{int(f['hour']):02d}:{int(f['minute']):02d} UTC"
        if hm and f.get("day") != "*" and f.get("day", "").isdigit():
            return f"Monthly on day {f['day']} at {hm}"
        if hm and f.get("day_of_week", "*") == "*" and f.get("day", "*") == "*":
            return f"Daily at {hm}"
        return f"Cron {trigger}"
    return str(trigger)


def _every(delta: timedelta) -> str:
    s = int(delta.total_seconds())
    if s % 3600 == 0:
        h = s // 3600
        return "Every hour" if h == 1 else f"Every {h} hours"
    if s % 60 == 0:
        m = s // 60
        return "Every minute" if m == 1 else f"Every {m} minutes"
    return f"Every {s} seconds"


def _interval_seconds(trigger: Any) -> int | None:
    from apscheduler.triggers.interval import IntervalTrigger

    if isinstance(trigger, IntervalTrigger):
        return int(trigger.interval.total_seconds())
    return None


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


async def _next_across_replicas(
    r: Any, job_id: str, local: datetime | None
) -> datetime | None:
    """Earliest next run any live replica has, a replica that stopped reporting is ignored."""
    best = local
    try:
        beats = await r.hgetall(f"{PREFIX}:replicas")
        nexts = await r.hgetall(_key(job_id, "next"))
    except Exception:  # noqa: BLE001
        return best
    now = datetime.now(timezone.utc)
    for host, iso in (nexts or {}).items():
        beat = beats.get(host)
        try:
            if (
                not beat
                or (now - datetime.fromisoformat(beat)).total_seconds()
                > REPLICA_STALE_SECONDS
            ):
                continue
            t = datetime.fromisoformat(iso)
        except ValueError:
            continue
        # a time already past means that replica ran it since, its own entry is newer
        if t < now - timedelta(seconds=5):
            continue
        if best is None or t < best:
            best = t
    return best


async def job_row(job: Any, r: Any) -> dict[str, Any]:
    info = CATALOGUE.get(job.id)
    stored: dict[str, str] = {}
    running = None
    history: list[dict] = []
    if r is not None:
        try:
            stored = await r.hgetall(_key(job.id)) or {}
            raw = await r.get(_key(job.id, "running"))
            running = json.loads(raw) if raw else None
            history = [
                json.loads(x)
                for x in await r.lrange(_key(job.id, "history"), 0, HISTORY_KEEP - 1)
            ]
        except Exception:  # noqa: BLE001
            pass
    local_next = job.next_run_time
    nxt = (
        await _next_across_replicas(r, job.id, local_next)
        if r is not None
        else local_next
    )
    try:
        result = (
            json.loads(stored["last_result"]) if stored.get("last_result") else None
        )
    except ValueError:
        result = None
    return {
        "id": job.id,
        "title": info.title if info else job.name,
        "what": info.what if info else job.name,
        "why": info.why if info else "",
        "group": info.group if info else "Platform upkeep",
        "destructive": bool(info and info.destructive),
        "confirm": info.confirm if info else "",
        "sharing": SHARING[info.sharing if info else "lock"],
        "schedule": describe_schedule(job.trigger),
        "interval_seconds": _interval_seconds(job.trigger),
        "paused": job.next_run_time is None,
        "next_run_at": _iso(nxt),
        "last_run_at": stored.get("last_finished_at") or None,
        "last_started_at": stored.get("last_started_at") or None,
        "last_outcome": stored.get("last_outcome") or None,
        "last_duration_ms": (
            _int(stored.get("last_duration_ms"))
            if stored.get("last_duration_ms")
            else None
        ),
        "last_summary": stored.get("last_summary") or None,
        "last_result": result,
        "last_error": stored.get("last_error") or None,
        "last_error_detail": stored.get("last_error_detail") or None,
        "last_trigger": stored.get("last_trigger") or None,
        "last_by": stored.get("last_by") or None,
        "last_replica": stored.get("last_replica") or None,
        "last_ok_at": stored.get("last_ok_at") or None,
        "last_failed_at": stored.get("last_failed_at") or None,
        "last_failed_error": stored.get("last_failed_error") or None,
        "last_skipped_at": stored.get("last_skipped_at") or None,
        "run_count": _int(stored.get("run_count")),
        "fail_count": _int(stored.get("fail_count")),
        "skip_count": _int(stored.get("skip_count")),
        "manual_count": _int(stored.get("manual_count")),
        "running": running,
        "history": history,
        "can_run": job.id in _FUNCS,
    }


async def list_jobs() -> dict[str, Any]:
    from app.core.scheduler import get_scheduler

    sched = get_scheduler()
    try:
        r = await redis()
        await r.ping()
        replicas_raw = await r.hgetall(f"{PREFIX}:replicas")
    except Exception:  # noqa: BLE001
        r = None
        replicas_raw = {}
    order = {g: i for i, g in enumerate(GROUPS)}
    rows = [await job_row(j, r) for j in sched.get_jobs()]
    # catalogue order puts the job people look for first in each group
    rank = {jid: i for i, jid in enumerate(CATALOGUE)}
    rows.sort(key=lambda x: (order.get(x["group"], 99), rank.get(x["id"], 999)))
    now = datetime.now(timezone.utc)
    replicas = []
    for host, beat in sorted(replicas_raw.items()):
        try:
            age = (now - datetime.fromisoformat(beat)).total_seconds()
        except ValueError:
            continue
        if age <= REPLICA_STALE_SECONDS:
            replicas.append({"name": host, "last_seen_at": beat})
    return {
        "jobs": rows,
        "groups": list(GROUPS),
        "scheduler_running": bool(sched.running),
        "recording": r is not None,
        "replica": replica(),
        "replicas": replicas,
        "now": _iso(now),
    }


_BACKGROUND: set[asyncio.Task] = set()


class RunNowError(Exception):
    def __init__(
        self, message: str, status: int = 400, code: str = "JOB_ERROR", data: Any = None
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.data = data


async def run_now(job_id: str, *, by: str, confirmed: bool) -> dict[str, Any]:
    from app.core.scheduler import get_scheduler

    info = CATALOGUE.get(job_id)
    func = _FUNCS.get(job_id)
    job = get_scheduler().get_job(job_id)
    if func is None or job is None:
        raise RunNowError(
            "There is no background job with that name on this server.",
            404,
            "JOB_NOT_FOUND",
        )
    if info and info.destructive and not confirmed:
        raise RunNowError(
            f"{info.title} removes or changes data. Confirm to run it now.",
            400,
            "CONFIRM_REQUIRED",
        )
    task = asyncio.create_task(execute(job_id, func, trigger="manual", by=by))
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    try:
        rec = await asyncio.wait_for(asyncio.shield(task), timeout=RUN_NOW_WAIT_SECONDS)
    except asyncio.TimeoutError:
        return {
            "status": "running",
            "message": "Still running. It carries on in the background and the page shows the result when it finishes.",
        }
    if rec["outcome"] == "skipped":
        rec["summary"] = (
            "Another replica was running it at that moment, so nothing was done twice. "
            "Its result shows here when it finishes."
        )
    return {"status": rec["outcome"], "run": rec}


__all__ = [
    "CATALOGUE",
    "GROUPS",
    "JobInfo",
    "RunNowError",
    "describe_schedule",
    "execute",
    "install_capture",
    "list_jobs",
    "note_lock",
    "plain_error",
    "register",
    "run_now",
    "summarize",
    "tracked",
]
