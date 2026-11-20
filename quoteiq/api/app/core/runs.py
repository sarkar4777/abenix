"""Running the RFQ pipeline for one email, retry and restart.

The pipeline is started without waiting, so the email holds its run id at
once and the run can be opened in Abenix while it goes. The app then follows
the run's events for progress and reads the run when it ends. Business
outcomes (quote, clarification, escalation) come from the pipeline. The app
calls a run a System error only when it fails, times out or can't be read.

The redraft after "Ask the customer" belongs to the review, in reviews.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from abenix_sdk import Abenix

from app.core.abenix import acting_subject, describe, new_sdk, spawn, transient
from app.core.config import settings
from app.core.results import (
    STEPS,
    TERMINAL_RUN,
    RunUnreadable,
    apply_event,
    new_progress,
    read_run,
    step_state,
)
from app.core.reviews import raise_review, start_redraft
from app.core.store import EmailStore, StaleJob, add_event, current_draft, fail, new_draft, new_job, now

logger = logging.getLogger("quoteiq.runs")

RESULT_FIELDS = ("outcome", "reason", "sender", "email_brief", "escalation")

# How often the run is checked when its event stream isn't available.
POLL_SECONDS = 2.0


class RunTimeout(Exception):
    """The run didn't finish by its deadline. The message, if any, is why it
    couldn't be checked."""


# ── the pipeline ─────────────────────────────────────────────────────────


async def process_email(store: EmailStore, email_id: str, job: str) -> None:
    """Start the pipeline for a claimed email and see it through."""
    record = await store.get(email_id)
    if record is None:
        return
    sdk = new_sdk()
    try:
        try:
            started = await sdk.execute(
                settings.pipeline_slug,
                record["received_text"],
                act_as=acting_subject(),
                wait="submitted",
                context={
                    "email_id": email_id,
                    "staff_name": settings.staff_name,
                    "sender_email": record["from_email"],
                    "subject": record["subject"],
                },
            )
            execution_id = started.execution_id
            if not execution_id:
                raise RuntimeError("Abenix started the run but returned no run id")
        except Exception as exc:  # noqa: BLE001
            await fail(store, email_id, job, "pipeline", f"Could not start the run. {describe(exc)}")
            return
        async with store.edit(email_id, job) as r:
            r["run"] = {
                "execution_id": execution_id,
                "started_at": now(),
                "finished_at": None,
                "cost": None,
                "duration_ms": None,
                **new_progress(),
            }
            add_event(r, "run_started", "Run started in Abenix")
        await finish_pipeline(sdk, store, email_id, job, execution_id)
    except StaleJob:
        logger.info("%s: result dropped, the email was reset or retried meanwhile", email_id)
    finally:
        await sdk.close()


async def finish_pipeline(sdk: Abenix, store: EmailStore, email_id: str, job: str, execution_id: str) -> None:
    """Follow a started run to its end and record its result."""
    try:
        run = await follow_run(sdk, store, email_id, job, execution_id)
    except StaleJob:
        raise
    except RunTimeout as exc:
        message = f"The run did not finish within {settings.run_timeout_seconds} seconds"
        if str(exc):
            message = f"Abenix couldn't be read for the run's result within {settings.run_timeout_seconds} seconds. {exc}"
        await fail(store, email_id, job, "pipeline", message)
        return
    except Exception as exc:  # noqa: BLE001
        await fail(store, email_id, job, "pipeline", f"Lost track of the run. {describe(exc)}")
        return

    record = await store.get(email_id)
    if record is None:
        return
    try:
        result = read_run(run, to=record["from_email"])
    except RunUnreadable as exc:
        message = str(exc)
        await fail(store, email_id, job, "pipeline", message[:1].upper() + message[1:])
        return

    node_results = run.get("node_results") or {}
    async with store.edit(email_id, job) as r:
        r["run"].update(finished_at=now(), cost=run.get("cost"), duration_ms=run.get("duration_ms"))
        for step in STEPS:
            node = node_results.get(step)
            if isinstance(node, dict) and node.get("status"):
                r["run"]["steps"][step] = step_state(node["status"])
        r["run"]["lines_done"] = len(result["lines"])
        r.update({k: result[k] for k in RESULT_FIELDS})
        r.update(status=result["status"], lines=result["lines"], processed_at=now(), error=None, error_step=None)
        matched = sum(1 for line in result["lines"] if line["outcome"] == "matched")
        count = len(result["lines"])
        summary = f"{count} line{'' if count == 1 else 's'}, {matched} matched"
        if result["email"]:
            r["drafts"].append(new_draft(r, result["outcome"], execution_id, result["email"]))
            r["review"] = "awaiting_review"
            add_event(r, "processed", f"{summary}. {result['outcome'].capitalize()} drafted for review")
        else:
            r["review"] = None
            add_event(r, "processed", f"{summary}. Escalated to staff")
    if result["email"]:
        await raise_review(sdk, store, email_id, job, agent_id=run.get("agent_id"))


async def follow_run(sdk: Abenix, store: EmailStore, email_id: str, job: str, execution_id: str) -> dict[str, Any]:
    """Update the email's progress from the run's events; return the finished run.

    The event stream replays what already happened, then follows. A run that
    ends between the replay and the follow would leave the stream waiting, so
    the run itself is checked on every heartbeat, and polled if the stream
    isn't available at all.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.run_timeout_seconds
    record = await store.get(email_id)
    run_so_far = (record or {}).get("run") or {}
    progress = {k: run_so_far.get(k) for k in ("steps", "searched", "lines_done")}
    if not progress["steps"]:
        progress = new_progress()

    last_error: list[BaseException] = []

    async def run_if_finished() -> dict[str, Any] | None:
        """The run if it has ended. A transient error reads as not yet, so
        one failed check doesn't fail the email. Anything else is raised."""
        try:
            run = await sdk.executions.get(execution_id)
        except (StaleJob, asyncio.CancelledError):
            raise
        except Exception as exc:  # noqa: BLE001
            if not transient(exc):
                raise
            logger.info("%s: checking the run failed, trying again: %s", email_id, describe(exc))
            last_error[:] = [exc]
            return None
        last_error.clear()
        return run if str((run or {}).get("status") or "").lower() in TERMINAL_RUN else None

    async def stream() -> None:
        last_check = loop.time()
        async with sdk.http.stream(
            "GET",
            f"/api/executions/{execution_id}/stream",
            headers={"Accept": "text/event-stream"},
            timeout=httpx.Timeout(10.0, read=60.0),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("event") in {"done", "error"}:
                    return
                if event.get("event") == "heartbeat" or loop.time() - last_check > 15:
                    last_check = loop.time()
                    if await run_if_finished():
                        return
                if apply_event(progress, event):
                    async with store.edit(email_id, job) as r:
                        r["run"].update(progress)

    try:
        await asyncio.wait_for(stream(), timeout=max(1.0, deadline - loop.time()))
    except (StaleJob, asyncio.CancelledError):
        raise
    except asyncio.TimeoutError as exc:
        raise RunTimeout() from exc
    except Exception as exc:  # noqa: BLE001
        logger.info("%s: no event stream (%s), polling the run", email_id, describe(exc))

    # The run row is written just after the last event, so allow it a moment.
    while True:
        run = await run_if_finished()
        if run is not None:
            return run
        if loop.time() > deadline:
            raise RunTimeout(describe(last_error[0]) if last_error else "")
        await asyncio.sleep(POLL_SECONDS)


# ── retry and restart ────────────────────────────────────────────────────


async def retry(store: EmailStore, email_id: str) -> dict[str, Any]:
    """Run the failed step again: the pipeline, or the redraft with the same note."""
    async with store.edit(email_id) as r:
        if r["status"] != "system_error":
            raise ValueError(f"only a System error can be retried, and this email is {r['status']}")
        step = r.get("error_step") or "pipeline"
        r["job"] = job = new_job()
        r.update(error=None, error_step=None)
        if step == "redraft" and r.get("redraft"):
            r.update(status="clarification", review="redrafting")
            add_event(r, "retry", "Redraft started again")
        else:
            step = "pipeline"
            r.update(status="processing", review=None, run=None, lines=[], drafts=[], processed_at=None,
                     **{k: None for k in RESULT_FIELDS})
            add_event(r, "retry", "Sent to the RFQ pipeline again")
        updated = dict(r)
    if step == "redraft":
        start_redraft(store, email_id, job)
    else:
        spawn(process_email(store, email_id, job), name=f"process:{email_id}")
    return updated


async def resume(store: EmailStore) -> None:
    """Pick up work a restart interrupted. Only matters with Postgres."""
    for record in await store.list():
        email_id, job = record["id"], record.get("job")
        draft = current_draft(record)
        if draft and (draft.get("approval") or {}).get("status") == "signing":
            async with store.edit(email_id) as r:
                current_draft(r)["approval"]["status"] = "pending"
        if record["status"] == "processing" and job:
            execution_id = (record.get("run") or {}).get("execution_id")
            if execution_id:
                spawn(_resume_pipeline(store, email_id, job, execution_id), name=f"resume:{email_id}")
            else:
                await fail(store, email_id, job, "pipeline", "The app restarted before the run started")
        elif record.get("review") == "redrafting" and job:
            start_redraft(store, email_id, job)


async def _resume_pipeline(store: EmailStore, email_id: str, job: str, execution_id: str) -> None:
    sdk = new_sdk()
    try:
        await finish_pipeline(sdk, store, email_id, job, execution_id)
    except StaleJob:
        pass
    finally:
        await sdk.close()
