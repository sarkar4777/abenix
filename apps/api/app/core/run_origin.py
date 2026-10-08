"""What started a run: a trigger, a chat, an API call, a parent run and so on."""

from __future__ import annotations

import uuid
from typing import Any

# kind -> the words the UI and SDK show after "Started by"
KINDS: dict[str, str] = {
    "schedule": "Schedule",
    "webhook": "Webhook",
    "manual": "Run by hand",
    "event": "Event subscription",
    "source_watch": "Source watch",
    "chat": "Chat",
    "api": "API",
    "playground": "SDK playground",
    "pipeline": "Pipeline",
    "agent": "Another agent",
    "autonomy_sample": "Autonomy sample",
    "eval": "Evaluation",
    "replay": "Replay",
    "a2a": "Agent to agent",
    "batch": "Batch",
    "meeting": "Meeting",
    "builder": "Builder test",
}

# what a browser may claim for itself, anything else is decided server side
CLIENT_SOURCES = {"chat", "playground", "builder"}

NAME_MAX = 255


def label(kind: str | None) -> str | None:
    if not kind:
        return None
    return KINDS.get(kind, kind.replace("_", " ").capitalize())


def started_by(kind: str | None, name: str | None) -> str | None:
    """One line for lists and the SDK, e.g. "Schedule: Nightly report"."""
    base = label(kind)
    if not base:
        return None
    return f"{base}: {name}" if name else base


def stamp(
    execution: Any,
    kind: str | None,
    *,
    trigger_id: Any = None,
    name: str | None = None,
) -> Any:
    """Write the three origin columns, never clearing what a caller already set."""
    if kind and not getattr(execution, "trigger_kind", None):
        execution.trigger_kind = kind[:32]
    if trigger_id and not getattr(execution, "trigger_id", None):
        try:
            execution.trigger_id = (
                trigger_id
                if isinstance(trigger_id, uuid.UUID)
                else uuid.UUID(str(trigger_id))
            )
        except (TypeError, ValueError):
            pass
    if name and not getattr(execution, "trigger_name", None):
        execution.trigger_name = str(name)[:NAME_MAX]
    return execution


def from_request(request: Any) -> dict[str, Any] | None:
    """An in-process caller (autonomy, evals) sets request.state.run_origin."""
    state = getattr(request, "state", None)
    origin = getattr(state, "run_origin", None) if state is not None else None
    return origin if isinstance(origin, dict) and origin.get("kind") else None


def is_api_key(user: Any) -> bool:
    return (
        getattr(user, "_api_key_id", None) is not None
        or getattr(user, "_api_key_scopes", None) is not None
    )


def caller_kind(user: Any, default: str = "manual") -> str:
    """API for a key holder, otherwise what the page that called says it is."""
    return "api" if is_api_key(user) else default


def for_execute(
    *,
    api_key: bool,
    source: str | None,
    conversation_id: str | None,
) -> str:
    """Kind for a direct POST /execute with no parent run and no in-process origin."""
    if api_key:
        return "api"
    if source in CLIENT_SOURCES:
        return source
    if conversation_id:
        return "chat"
    return "manual"


async def parent_origin(db: Any, parent_execution_id: Any) -> tuple[str, str | None]:
    """A child run is started by its parent, a pipeline or another agent."""
    from sqlalchemy import select

    from models.agent import Agent
    from models.execution import Execution

    row = (
        await db.execute(
            select(Agent.name, Agent.model_config_)
            .join(Execution, Execution.agent_id == Agent.id)
            .where(Execution.id == parent_execution_id)
        )
    ).first()
    if row is None:
        return "agent", None
    mode = (row[1] or {}).get("mode") if isinstance(row[1], dict) else None
    return ("pipeline" if mode == "pipeline" else "agent"), row[0]


def event_origin(sub: dict[str, Any], envelope: dict[str, Any]) -> tuple[str, str]:
    """An event subscription run, or a source watch change delivered through one."""
    etype = str(envelope.get("type") or "")
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    if etype.startswith("source."):
        return "source_watch", str(data.get("name") or sub.get("name") or etype)
    return "event", str(sub.get("name") or etype or "event")
