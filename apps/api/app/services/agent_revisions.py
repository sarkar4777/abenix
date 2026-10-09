"""One way to record a change to an agent, and the eval gate every live change passes."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import error
from models.agent_revision import AgentRevision

logger = logging.getLogger("abenix.revisions")

SOURCES = ("edit", "healing", "improvement", "revert", "import")
SOURCE_LABELS = {
    "edit": "Edit",
    "healing": "Healing",
    "improvement": "Improvement",
    "revert": "Revert",
    "import": "Import",
}
# fields that change what the agent does, so the eval gate cares about them
BEHAVIOUR_KEYS = ("system_prompt", "model_config")


class RevisionWriteError(RuntimeError):
    pass


def agent_state(agent: Any) -> dict[str, Any]:
    status = getattr(agent, "status", None)
    state = {
        "name": getattr(agent, "name", None),
        "description": getattr(agent, "description", None),
        "system_prompt": getattr(agent, "system_prompt", None),
        "model_config": getattr(agent, "model_config_", None),
        "category": getattr(agent, "category", None),
        "status": getattr(status, "value", status),
    }
    # a deep copy, later in-place edits of model_config must not leak into the snapshot
    return json.loads(json.dumps(state, default=str))


def behaviour_changed(before: dict[str, Any] | None, after: dict[str, Any]) -> bool:
    before = before or {}
    return any(before.get(k) != after.get(k) for k in BEHAVIOUR_KEYS)


async def next_revision_number(db: AsyncSession, agent_id: Any) -> int:
    top = (
        await db.execute(
            select(func.max(AgentRevision.revision_number)).where(
                AgentRevision.agent_id == agent_id
            )
        )
    ).scalar()
    return int(top or 0) + 1


async def record_revision(
    db: AsyncSession,
    agent: Any,
    *,
    changed_by: Any,
    change_type: str,
    previous_state: dict[str, Any] | None,
    source: str = "edit",
    diff_summary: str | None = None,
    proposal_id: Any = None,
    new_state: dict[str, Any] | None = None,
) -> AgentRevision:
    """Adds the revision to the caller's transaction, so it commits or fails with the change."""
    if source not in SOURCES:
        raise ValueError(f"unknown revision source {source!r}")
    try:
        if getattr(agent, "id", None) is None:
            agent.id = uuid.uuid4()
        rev = AgentRevision(
            id=uuid.uuid4(),
            agent_id=agent.id,
            revision_number=await next_revision_number(db, agent.id),
            changed_by=changed_by,
            change_type=change_type,
            previous_state=previous_state,
            new_state=new_state if new_state is not None else agent_state(agent),
            diff_summary=diff_summary,
            source=source,
            proposal_id=proposal_id,
        )
        db.add(rev)
        await db.flush()
    except Exception as e:  # noqa: BLE001
        logger.error("revision write failed for agent %s: %s", agent.id, e)
        raise RevisionWriteError(str(e)) from e
    return rev


def revision_failed() -> JSONResponse:
    return error(
        "The change was not saved because its history entry could not be written. Try again.",
        500,
        error_code="REVISION_WRITE_FAILED",
    )


def gate_link(suites: list[dict[str, Any]]) -> str | None:
    for s in suites or []:
        if s.get("state") == "passed":
            continue
        if s.get("run_id"):
            return f"/evals/runs/{s['run_id']}"
        if s.get("suite_id"):
            return f"/evals/{s['suite_id']}"
    return None


LIVE_HINT = (
    " This agent is live, so every change to its prompt, model or tools must pass first. "
    "Move it to draft, save the change, run the suite, then publish again."
)


async def eval_gate_refusal(
    db: AsyncSession, agent: Any, *, live_edit: bool = False
) -> JSONResponse | None:
    """409 with the failing suites and a link to the run, or None when the gate allows it."""
    from app.services import eval_runner

    await db.flush()
    gate = await eval_runner.gate_for_agent(db, agent)
    if gate.allowed:
        return None
    suites = list(gate.suites or [])
    msg = gate.message + (LIVE_HINT if live_edit else "")
    return error(
        msg,
        409,
        error_code="EVAL_GATE",
        details={
            "agent_id": str(agent.id),
            "suites": suites,
            "link": gate_link(suites),
        },
    )
