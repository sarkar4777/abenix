"""Per-execution meeting session state."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from engine.tools.meeting_adapter import MeetingAdapter

logger = logging.getLogger(__name__)


@dataclass
class MeetingSession:
    execution_id: str
    meeting_id: str
    tenant_id: str
    user_id: str
    provider: str
    room: str
    display_name: str
    adapter: Optional[MeetingAdapter] = None
    started_at: float = field(default_factory=lambda: time.time())
    status: str = "joining"  # joining | live | leaving | closed | error
    kill_flag: asyncio.Event = field(default_factory=asyncio.Event)

    # Declared scope — populated by the API before the bot joins.
    # Contains topics the bot is allowed to answer unprompted on.
    scope_allow: list[str] = field(default_factory=list)
    # Topics that MUST defer no matter what.
    scope_defer: list[str] = field(default_factory=list)
    # Persona KB scope — which persona_scope values this meeting may see.
    persona_scopes: list[str] = field(default_factory=list)


_SESSIONS: dict[str, MeetingSession] = {}


def register(sess: MeetingSession) -> None:
    _SESSIONS[sess.execution_id] = sess


def get(execution_id: str) -> Optional[MeetingSession]:
    return _SESSIONS.get(execution_id)


def drop(execution_id: str) -> None:
    _SESSIONS.pop(execution_id, None)


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "").strip()


_REDIS_POOL: dict[str, Any] = {}
_REDIS_LOCK = asyncio.Lock()


async def _redis() -> Any:
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return None
    url = _redis_url()
    if not url:
        return None
    # Key pool by (url, loop) so different event loops in tests don't
    # share a connection bound to a closed loop.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    pool_key = f"{url}|{id(loop)}"
    existing = _REDIS_POOL.get(pool_key)
    if existing is not None:
        return existing
    async with _REDIS_LOCK:
        existing = _REDIS_POOL.get(pool_key)
        if existing is not None:
            return existing
        try:
            client = aioredis.from_url(
                url,
                decode_responses=True,
                max_connections=20,
                socket_keepalive=True,
                health_check_interval=30,
            )
        except Exception:
            return None
        _REDIS_POOL[pool_key] = client
        return client


def _keys(meeting_id: str) -> dict[str, str]:
    return {
        "session": f"meeting:{meeting_id}:session",
        "transcript": f"meeting:{meeting_id}:transcript",
        "decisions": f"meeting:{meeting_id}:decisions",
        "deferrals": f"meeting:{meeting_id}:deferrals",
        "kill": f"meeting:{meeting_id}:kill",
        "pubsub": f"meeting:{meeting_id}:events",
    }


async def publish_session(sess: MeetingSession) -> None:
    r = await _redis()
    if r is None:
        return
    try:
        k = _keys(sess.meeting_id)
        await r.hset(
            k["session"],
            mapping={
                "execution_id": sess.execution_id,
                "tenant_id": sess.tenant_id,
                "user_id": sess.user_id,
                "provider": sess.provider,
                "room": sess.room,
                "display_name": sess.display_name,
                "status": sess.status,
                "started_at": str(int(sess.started_at)),
            },
        )
        await r.expire(k["session"], 86400)
    finally:
        # Do NOT close — `r` is the shared pool client, closing would
        # break every other caller in this pod. The pool manages its
        # own lifecycle via connection health checks.
        pass


async def append_transcript(
    meeting_id: str, participant: str, text: str, *, ts_ms: int = 0
) -> None:
    r = await _redis()
    if r is None:
        return
    try:
        k = _keys(meeting_id)
        entry = json.dumps(
            {
                "participant": participant,
                "text": text,
                "ts_ms": ts_ms or int(time.time() * 1000),
            }
        )
        await r.rpush(k["transcript"], entry)
        await r.ltrim(k["transcript"], -2000, -1)  # cap history
        await r.expire(k["transcript"], 86400 * 7)
        await r.publish(k["pubsub"], json.dumps({"type": "transcript", "entry": entry}))
    finally:
        # Do NOT close — `r` is the shared pool client, closing would
        # break every other caller in this pod. The pool manages its
        # own lifecycle via connection health checks.
        pass


async def append_decision(
    meeting_id: str,
    kind: str,  # "answer" | "defer" | "decline" | "leave" | "join"
    summary: str,
    *,
    detail: dict | None = None,
) -> None:
    r = await _redis()
    if r is None:
        return
    try:
        k = _keys(meeting_id)
        entry = json.dumps(
            {
                "kind": kind,
                "summary": summary,
                "detail": detail or {},
                "ts_ms": int(time.time() * 1000),
            }
        )
        await r.rpush(k["decisions"], entry)
        await r.ltrim(k["decisions"], -500, -1)
        await r.expire(k["decisions"], 86400 * 7)
        await r.publish(k["pubsub"], json.dumps({"type": "decision", "entry": entry}))
    finally:
        # Do NOT close — `r` is the shared pool client, closing would
        # break every other caller in this pod. The pool manages its
        # own lifecycle via connection health checks.
        pass


async def is_killed(meeting_id: str) -> bool:
    r = await _redis()
    if r is None:
        return False
    try:
        k = _keys(meeting_id)
        v = await r.get(k["kill"])
        return v in ("1", "true", "yes")
    finally:
        # Do NOT close — `r` is the shared pool client, closing would
        # break every other caller in this pod. The pool manages its
        # own lifecycle via connection health checks.
        pass


async def set_kill(meeting_id: str) -> None:
    r = await _redis()
    if r is None:
        return
    try:
        k = _keys(meeting_id)
        await r.set(k["kill"], "1", ex=3600)
        await r.publish(
            k["pubsub"], json.dumps({"type": "kill", "meeting_id": meeting_id})
        )
    finally:
        # Do NOT close — `r` is the shared pool client, closing would
        # break every other caller in this pod. The pool manages its
        # own lifecycle via connection health checks.
        pass
