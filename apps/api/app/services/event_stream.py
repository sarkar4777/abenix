"""Platform events as a live stream for apps: replay from the outbox, then live through Redis.

fan_out publishes each event once on one Redis channel after it is recorded. Every API
process keeps one subscriber and hands each event to the viewers of that tenant who may
see it, so a viewer costs the same at 2 or 2,000. A viewer that comes back with the last
event id it saw gets what it missed from the outbox first.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

CHANNEL = "abenix:events"
QUEUE_MAX = 1000
REPLAY_MAX = 1000
OUTPUT_MAX = 20_000
SEEN_MAX = 5000

# what a viewer needs to see each family, admins see everything
NEEDS: tuple[tuple[str, str], ...] = (
    ("telemetry.", "telemetry.view"),
    ("decision.", "decisions.view"),
    ("action.", "autonomy.view"),
    ("autonomy.", "autonomy.view"),
    ("moderation.", "moderation.review"),
    ("lesson.", "improvements.view"),
    ("cluster.", "improvements.view"),
    ("improvement.", "improvements.view"),
    ("kill_switch.", "risk.view"),
    ("eval.", "evals.run"),
    ("source.", "sources.manage"),
)


def decider(
    data: dict[str, Any], signoffs: list[Any], decided_at: Any
) -> dict[str, Any]:
    """Who decided and when, from the sign-offs when the event left it out. Email for admins only."""
    signed = [x for x in signoffs if isinstance(x, dict) and x.get("decision")]
    last = signed[-1] if signed else None
    who = data.get("decided_by") if isinstance(data.get("decided_by"), dict) else None
    if who is None and last is not None:
        who = {
            "id": last.get("user_id"),
            "name": last.get("user_name") or last.get("user_email"),
        }
    if who is not None:
        match = next(
            (
                x
                for x in reversed(signed)
                if str(x.get("user_id")) == str(who.get("id"))
            ),
            last,
        )
        if match and match.get("user_email"):
            who = {**who, "email": match["user_email"]}
        data["decided_by"] = who
    if not data.get("decided_at") and decided_at is not None:
        data["decided_at"] = (
            decided_at.isoformat()
            if hasattr(decided_at, "isoformat")
            else str(decided_at)
        )
    return data


def type_matches(patterns: list[str], event_type: str) -> bool:
    if not patterns:
        return True
    return any(p == "*" or fnmatch.fnmatchcase(event_type, p) for p in patterns)


def parse_types(
    raw: str | None, catalog: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """The patterns asked for, and the ones that match no known event."""
    pats = [p.strip() for p in (raw or "").split(",") if p.strip()]
    bad = [
        p
        for p in pats
        if p != "*" and not any(fnmatch.fnmatchcase(t, p) for t in catalog)
    ]
    return pats, bad


@dataclass(eq=False)
class Viewer:
    tenant: str
    user_id: str
    admin: bool
    caps: frozenset[str]
    scope: Any = None
    types: list[str] = field(default_factory=list)
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(QUEUE_MAX))
    dropped: int = 0

    def holds(self, cap: str) -> bool:
        from app.core.capabilities import holds

        return holds(self.caps, cap)

    def may_see(self, env: dict[str, Any]) -> bool:
        t = str(env.get("type") or "")
        if not type_matches(self.types, t):
            return False
        if self.admin:
            return True
        data = env.get("data") or {}
        if t.startswith("execution."):
            return str(data.get("user_id") or "") == self.user_id
        if t.startswith("approval."):
            return (
                self.holds("approvals.sign")
                or str(data.get("requested_by") or "") == self.user_id
            )
        for prefix, cap in NEEDS:
            if t.startswith(prefix):
                if not self.holds(cap):
                    return False
                if prefix == "telemetry." and self.scope is not None:
                    conn = data.get("connection_id")
                    return not conn or self.scope.sees(str(conn))
                return True
        return False

    def shape(self, env: dict[str, Any]) -> dict[str, Any]:
        """What this viewer gets of an event they may see: no one else's email unless admin."""
        data = env.get("data") or {}
        who = data.get("decided_by")
        if self.admin or not isinstance(who, dict) or "email" not in who:
            return env
        if str(who.get("id") or "") == self.user_id:
            return env
        return {
            **env,
            "data": {
                **data,
                "decided_by": {k: v for k, v in who.items() if k != "email"},
            },
        }

    def offer(self, env: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(env)
        except asyncio.QueueFull:
            # a slow reader loses the oldest, it can resume from the outbox
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self.dropped += 1
            try:
                self.queue.put_nowait(env)
            except asyncio.QueueFull:
                pass


class Seen:
    """Ids already sent to one viewer, so replay and live never repeat an event."""

    def __init__(self, cap: int = SEEN_MAX) -> None:
        self.ids: set[int] = set()
        self.order: deque[int] = deque()
        self.cap = cap

    def add(self, i: int) -> bool:
        if i in self.ids:
            return False
        self.ids.add(i)
        self.order.append(i)
        if len(self.order) > self.cap:
            self.ids.discard(self.order.popleft())
        return True


def sse(env: dict[str, Any]) -> str:
    body = json.dumps(
        {
            "id": env.get("id"),
            "type": env.get("type"),
            "occurred_at": env.get("occurred_at"),
            "data": env.get("data") or {},
        },
        default=str,
    )
    return f"id: {env.get('id')}\nevent: {env.get('type')}\ndata: {body}\n\n"


def envelope(row: Any) -> dict[str, Any]:
    at = row["occurred_at"]
    return {
        "id": int(row["id"]),
        "tenant": str(row["tenant_id"]),
        "type": row["event_type"],
        "occurred_at": (at.isoformat() if isinstance(at, datetime) else str(at or ""))
        or datetime.now(timezone.utc).isoformat(),
        "data": dict(row["payload"] or {}),
    }


def _output(text_: str | None) -> Any:
    from app.telemetry.rules.actions import parse_output

    out = parse_output(text_)
    if isinstance(out, str) and len(out) > OUTPUT_MAX:
        return out[:OUTPUT_MAX]
    return out


async def enrich(db: Any, envs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add what an app needs and the payload leaves out: a run's answer and who it ran for."""
    from app.core import run_origin

    exec_ids = [
        e["data"].get("execution_id")
        for e in envs
        if e["type"].startswith("execution.") and e["data"].get("execution_id")
    ]
    if exec_ids:
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT e.id, e.user_id, e.output_message, e.error_message, e.trigger_kind, "
                        "e.trigger_name, a.name AS agent_name FROM executions e "
                        "LEFT JOIN agents a ON a.id = e.agent_id WHERE e.id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": [str(i) for i in exec_ids]},
                )
            )
            .mappings()
            .all()
        )
        by_id = {str(r["id"]): r for r in rows}
        for e in envs:
            r = by_id.get(str(e["data"].get("execution_id") or ""))
            if r is None:
                continue
            e["data"].update(
                {
                    "user_id": str(r["user_id"]) if r["user_id"] else None,
                    "agent_name": r["agent_name"],
                    "output": _output(r["output_message"]),
                    "error": (r["error_message"] or None)
                    and str(r["error_message"])[:2000],
                    "started_by": run_origin.started_by(
                        r["trigger_kind"], r["trigger_name"]
                    ),
                    "trigger_kind": r["trigger_kind"],
                }
            )
    appr_ids = [
        e["data"].get("approval_id")
        for e in envs
        if e["type"].startswith("approval.") and e["data"].get("approval_id")
    ]
    if appr_ids:
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT id, requested_by, agent_id, agent_execution_id, payload, "
                        "signoffs, decided_at FROM approvals WHERE id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": [str(i) for i in appr_ids]},
                )
            )
            .mappings()
            .all()
        )
        by_id = {str(r["id"]): r for r in rows}
        for e in envs:
            r = by_id.get(str(e["data"].get("approval_id") or ""))
            if r is None:
                continue
            p = r["payload"] or {}
            e["data"].update(
                {
                    "requested_by": (
                        str(r["requested_by"]) if r["requested_by"] else None
                    ),
                    "agent_id": str(r["agent_id"]) if r["agent_id"] else None,
                    "execution_id": (
                        str(r["agent_execution_id"])
                        if r["agent_execution_id"]
                        else None
                    ),
                    **(
                        {"command": p["command"]}
                        if isinstance(p, dict) and p.get("command")
                        else {}
                    ),
                }
            )
            if e["type"] == "approval.resolved":
                decider(e["data"], r["signoffs"] or [], r["decided_at"])
    return envs


async def publish(db: Any, rows: list[Any]) -> None:
    """Called by fan_out once the events are recorded. Best effort, the outbox is the record."""
    try:
        envs = await enrich(db, [envelope(r) for r in rows])
        from app.routers.telemetry import redis

        r = redis()
        pipe = r.pipeline(transaction=False)
        for e in envs:
            pipe.publish(CHANNEL, json.dumps(e, default=str))
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("event stream publish skipped: %s", exc)


async def replay(
    db: Any,
    tenant: str,
    after_id: int | None,
    after_time: datetime | None,
    limit: int = REPLAY_MAX,
) -> tuple[list[dict[str, Any]], bool]:
    """Events recorded after an id or a time, oldest first, and whether there were more."""
    where = ["tenant_id = CAST(:t AS uuid)", "dispatched_at IS NOT NULL"]
    params: dict[str, Any] = {"t": tenant, "n": limit + 1}
    if after_id is not None:
        where.append("id > :a")
        params["a"] = after_id
    if after_time is not None:
        where.append("occurred_at > :at")
        params["at"] = after_time
    rows = (
        (
            await db.execute(
                text(
                    "SELECT id, tenant_id, event_type, payload, occurred_at FROM event_outbox "
                    f"WHERE {' AND '.join(where)} ORDER BY id LIMIT :n"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    more = len(rows) > limit
    envs = await enrich(db, [envelope(r) for r in rows[:limit]])
    return envs, more


def parse_since(raw: str | None) -> tuple[int | None, datetime | None]:
    """An event id like 4211 or evt_4211, or an ISO time. Raises ValueError otherwise."""
    if raw is None or not str(raw).strip():
        return None, None
    s = str(raw).strip()
    if s.startswith("evt_"):
        s = s[4:]
    if s.isdigit():
        return int(s), None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return None, dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Hub:
    def __init__(self) -> None:
        self.viewers: dict[str, set[Viewer]] = defaultdict(set)
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.delivered = 0

    async def add(self, v: Viewer) -> None:
        async with self.lock:
            self.viewers[v.tenant].add(v)
            if self.task is None or self.task.done():
                self.task = asyncio.create_task(self._read())

    async def remove(self, v: Viewer) -> None:
        async with self.lock:
            vs = self.viewers.get(v.tenant)
            if vs is not None:
                vs.discard(v)
                if not vs:
                    self.viewers.pop(v.tenant, None)

    def dispatch(self, env: dict[str, Any]) -> None:
        for v in list(self.viewers.get(str(env.get("tenant") or ""), ())):
            if v.may_see(env):
                v.offer(env)
                self.delivered += 1

    async def _read(self) -> None:
        import redis.asyncio as aioredis

        from app.core.config import settings

        while True:
            ps = None
            try:
                client = aioredis.from_url(settings.redis_url, decode_responses=True)
                ps = client.pubsub()
                await ps.subscribe(CHANNEL)
                async for msg in ps.listen():
                    if msg.get("type") != "message":
                        continue
                    try:
                        self.dispatch(json.loads(msg["data"]))
                    except (TypeError, ValueError):
                        continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("event stream subscriber restarting: %s", exc)
                await asyncio.sleep(2)
            finally:
                if ps is not None:
                    try:
                        await ps.aclose()
                    except Exception:  # noqa: BLE001
                        pass


hub = Hub()
