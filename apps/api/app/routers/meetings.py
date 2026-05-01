"""Meeting lifecycle routes."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.meeting import Meeting, MeetingDeferral, MeetingProvider, MeetingStatus
from models.user import User

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _meeting_dict(m: Meeting) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "title": m.title,
        "provider": m.provider,
        "room": m.room,
        "join_url": m.join_url,
        "status": m.status,
        "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
        "started_at": m.started_at.isoformat() if m.started_at else None,
        "ended_at": m.ended_at.isoformat() if m.ended_at else None,
        "scope_allow": m.scope_allow or [],
        "scope_defer": m.scope_defer or [],
        "persona_scopes": m.persona_scopes or [],
        "display_name": m.display_name,
        "summary": m.summary,
        "transcript_count": m.transcript_count,
        "decision_count": m.decision_count,
        "deferral_count": m.deferral_count,
        "agent_id": str(m.agent_id) if m.agent_id else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def _notify_execution_failure(
    *,
    tenant_id: Any,
    user_id: Any,
    execution_id: Any,
    agent_id: Any = None,
    error: str = "",
    meeting_id: str | None = None,
) -> None:
    """Persist + push an execution_failed notification."""
    try:
        from models.notification import Notification, NotificationType
        from app.core.deps import async_session
        from app.core.ws_manager import ws_manager

        title = "Agent run failed"
        msg = (error or "The agent encountered an error during execution.")[:1000]
        link = f"/executions/{execution_id}"
        if meeting_id:
            link = f"/meetings/{meeting_id}"
        metadata = {
            "execution_id": str(execution_id),
            "agent_id": str(agent_id) if agent_id else None,
            "meeting_id": meeting_id,
        }
        async with async_session() as db:
            n = Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type=NotificationType.EXECUTION_FAILED,
                title=title,
                message=msg,
                link=link,
                metadata_=metadata,
            )
            db.add(n)
            await db.commit()
            await db.refresh(n)
        # Real-time push
        try:
            await ws_manager.send_to_user(
                user_id,
                "notification",
                {
                    "id": str(n.id),
                    "type": "execution_failed",
                    "title": title,
                    "message": msg,
                    "link": link,
                    "metadata": metadata,
                    "created_at": n.created_at.isoformat() if n.created_at else None,
                },
            )
        except Exception:
            pass
    except Exception:
        # Intentionally silent — the failure notification should never
        # mask the real failure by throwing its own.
        pass


async def _redis():
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return None
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return None
    try:
        return aioredis.from_url(url, decode_responses=True)
    except Exception:
        return None


@router.post("")
async def create_meeting(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    title = (body.get("title") or "Untitled Meeting").strip()
    provider = (body.get("provider") or MeetingProvider.LIVEKIT.value).lower()
    if provider not in ("livekit", "teams", "zoom"):
        return error("provider must be one of: livekit, teams, zoom", 400)
    room = (body.get("room") or f"af-{uuid.uuid4().hex[:10]}").strip()
    scheduled_raw = body.get("scheduled_at")
    scheduled_at = None
    if scheduled_raw:
        try:
            scheduled_at = datetime.fromisoformat(
                str(scheduled_raw).replace("Z", "+00:00")
            )
        except Exception:
            pass

    m = Meeting(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        title=title,
        provider=provider,
        room=room,
        scheduled_at=scheduled_at,
        display_name=(body.get("display_name") or "Abenix Assistant").strip(),
        agent_id=uuid.UUID(body["agent_id"]) if body.get("agent_id") else None,
    )
    # Derive join_url hint for LiveKit rooms so the UI can show a "Join as
    # human" button pointing to LiveKit Meet. For Teams/Zoom the user
    # supplies the join_url on create.
    if provider == "livekit":
        lk_ui = os.environ.get("LIVEKIT_MEET_URL", "").strip()
        if lk_ui:
            m.join_url = f"{lk_ui.rstrip('/')}/?room={room}"
    elif body.get("join_url"):
        m.join_url = str(body.get("join_url"))

    db.add(m)
    await db.commit()
    await db.refresh(m)
    return success(_meeting_dict(m))


@router.get("")
async def list_meetings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    limit: int = 50,
) -> JSONResponse:
    q = select(Meeting).where(Meeting.user_id == user.id)
    if status:
        q = q.where(Meeting.status == status)
    q = q.order_by(desc(Meeting.created_at)).limit(max(1, min(200, limit)))
    result = await db.execute(q)
    return success([_meeting_dict(m) for m in result.scalars().all()])


@router.get("/livekit-token")
async def mint_livekit_token(
    room: str,
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Mint a token for the HUMAN user to join the same LiveKit room as"""
    api_key = os.environ.get("LIVEKIT_API_KEY", "").strip()
    api_secret = os.environ.get("LIVEKIT_API_SECRET", "").strip()
    url = os.environ.get("LIVEKIT_URL", "").strip()
    if not (api_key and api_secret and url):
        return error("LiveKit server not configured on this deployment", 400)
    browser_url = os.environ.get(
        "LIVEKIT_PUBLIC_URL", ""
    ).strip() or _browser_url_from_internal(url)
    try:
        from livekit import api
    except ImportError:
        return error("livekit SDK not installed on server", 500)
    grant = api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )
    from datetime import timedelta

    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(f"user-{user.id}")
        .with_name(user.full_name or user.email or "User")
        .with_grants(grant)
        .with_ttl(timedelta(seconds=3600))
        .to_jwt()
    )
    # Build a one-click LiveKit Meet deep-link that auto-fills both fields.
    # https://meet.livekit.io/custom?liveKitUrl=<url>&token=<jwt>
    from urllib.parse import quote as _q

    deep_link = (
        f"https://meet.livekit.io/custom?liveKitUrl={_q(browser_url, safe='')}"
        f"&token={_q(token, safe='')}"
    )
    return success(
        {
            "url": url,
            "browser_url": browser_url,
            "token": token,
            "identity": f"user-{user.id}",
            "deep_link": deep_link,
        }
    )


def _browser_url_from_internal(url: str) -> str:
    """Translate pod-internal LiveKit URLs to host-browser-reachable ones."""
    try:
        from urllib.parse import urlparse, urlunparse

        u = urlparse(url)
        host = (u.hostname or "").lower()
        DEV_HOSTS = {
            "host.minikube.internal",
            "host.docker.internal",
            "kubernetes.docker.internal",
        }
        if host in DEV_HOSTS or ("." not in host and host not in {"localhost"}):
            new_netloc = "localhost"
            if u.port:
                new_netloc = f"localhost:{u.port}"
            return urlunparse(
                (u.scheme, new_netloc, u.path, u.params, u.query, u.fragment)
            )
        return url
    except Exception:
        return url


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _load(meeting_id, user, db)
    if not m:
        return error("not found", 404)
    transcript, decisions, deferrals = [], [], []
    r = await _redis()
    if r:
        try:
            transcript_raw = await r.lrange(f"meeting:{meeting_id}:transcript", 0, -1)
            decisions_raw = await r.lrange(f"meeting:{meeting_id}:decisions", 0, -1)
            transcript = [json.loads(x) for x in transcript_raw]
            decisions = [json.loads(x) for x in decisions_raw]
        finally:
            try:
                await r.aclose()
            except Exception:
                pass
    # Always include db-persisted deferrals so the history view survives Redis eviction
    q = await db.execute(
        select(MeetingDeferral)
        .where(MeetingDeferral.meeting_id == m.id)
        .order_by(MeetingDeferral.created_at)
    )
    for d in q.scalars().all():
        deferrals.append(
            {
                "id": str(d.id),
                "question": d.question,
                "context": d.context,
                "answer": d.answer,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "answered_at": d.answered_at.isoformat() if d.answered_at else None,
            }
        )
    return success(
        {
            **_meeting_dict(m),
            "transcript": transcript,
            "decisions": decisions,
            "deferrals": deferrals,
        }
    )


@router.put("/{meeting_id}/authorize")
async def authorize_meeting(
    meeting_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _load(meeting_id, user, db)
    if not m:
        return error("not found", 404)
    scope_allow = [s.strip() for s in (body.get("scope_allow") or []) if str(s).strip()]
    scope_defer = [s.strip() for s in (body.get("scope_defer") or []) if str(s).strip()]
    persona_scopes = [
        s.strip() for s in (body.get("persona_scopes") or ["self"]) if str(s).strip()
    ]
    m.scope_allow = scope_allow
    m.scope_defer = scope_defer
    m.persona_scopes = persona_scopes
    if m.status == MeetingStatus.SCHEDULED.value:
        m.status = MeetingStatus.AUTHORIZED.value
    await db.commit()

    # Mirror to Redis so the agent runtime sees scope even before DB reload.
    # We also write the meeting's authoritative room + provider here so
    # meeting_join can use them server-side (the LLM can't pick its own
    # room name and end up in the wrong LiveKit channel).
    r = await _redis()
    if r:
        try:
            await r.hset(
                f"meeting:{meeting_id}:scope",
                mapping={
                    "authorized": "1",
                    "allow": "|".join(scope_allow),
                    "defer": "|".join(scope_defer),
                    "persona_scopes": "|".join(persona_scopes),
                    "user_id": str(user.id),
                    "tenant_id": str(user.tenant_id),
                    "room": m.room or "",
                    "provider": m.provider or "livekit",
                    "display_name": m.display_name or "Abenix Assistant",
                },
            )
            await r.expire(f"meeting:{meeting_id}:scope", 86400 * 2)
        finally:
            try:
                await r.aclose()
            except Exception:
                pass
    return success(_meeting_dict(m))


@router.post("/{meeting_id}/start")
async def start_meeting(
    meeting_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Execute the Meeting Representative agent against this meeting."""
    m = await _load(meeting_id, user, db)
    if not m:
        return error("not found", 404)
    if m.status not in (MeetingStatus.AUTHORIZED.value, MeetingStatus.SCHEDULED.value):
        return error(f"meeting not startable in status '{m.status}'", 400)
    if not (m.scope_allow is not None):
        return error(
            "Authorize the bot with a topic allow-list before starting.",
            400,
        )
    m.status = MeetingStatus.LIVE.value
    m.started_at = datetime.now(timezone.utc)
    await db.commit()

    # Dispatch to the Meeting Representative agent in a background task.
    # We don't await — this POST returns immediately and the UI tails
    # /api/meetings/{id}/stream for live updates.
    asyncio.create_task(_run_meeting_agent(m, user, body))
    return success(_meeting_dict(m))


@router.post("/{meeting_id}/redispatch")
async def redispatch_bot(
    meeting_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Re-spawn the bot agent for an already-live meeting."""
    m = await _load(meeting_id, user, db)
    if not m:
        return error("not found", 404)
    if m.status in (MeetingStatus.SCHEDULED.value,):
        return error(
            "Authorize the meeting first (set scope_allow), then redispatch.",
            400,
        )
    # Allow redispatch from live, killed, done, failed, or authorized.
    # Killed especially is the whole reason this endpoint exists — bring
    # the bot back without losing the existing transcript/decisions.
    if not (m.scope_allow is not None):
        return error("Authorize the bot with a scope allow-list first.", 400)

    # Optional override: switch to a different agent
    new_agent_id = (body or {}).get("agent_id")
    if new_agent_id:
        try:
            m.agent_id = uuid.UUID(new_agent_id)
        except Exception:
            return error("invalid agent_id", 400)

    # Bump status back to live + clear ended_at if it was killed
    m.status = MeetingStatus.LIVE.value
    if m.ended_at is not None:
        m.ended_at = None
    if m.started_at is None:
        m.started_at = datetime.now(timezone.utc)
    await db.commit()

    # Clear any stale kill flag so the new agent can actually join
    r = await _redis()
    if r:
        try:
            await r.delete(f"meeting:{meeting_id}:kill")
            await r.publish(
                f"meeting:{meeting_id}:events",
                json.dumps({"type": "redispatch", "meeting_id": meeting_id}),
            )
        finally:
            try:
                await r.aclose()
            except Exception:
                pass

    asyncio.create_task(_run_meeting_agent(m, user, body or {}))
    return success(
        {
            **_meeting_dict(m),
            "redispatched": True,
            "message": "Bot agent re-dispatched. New decisions will appear in the log shortly.",
        }
    )


@router.post("/{meeting_id}/inject-turn")
async def inject_turn(
    meeting_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Inject a synthetic participant utterance into the live transcript."""
    m = await _load(meeting_id, user, db)
    if not m:
        return error("not found", 404)
    if m.status != MeetingStatus.LIVE.value:
        return error(f"meeting is {m.status}, not live", 400)
    speaker = (body.get("speaker") or "test-participant").strip()[:80]
    text = (body.get("text") or "").strip()
    if not text:
        return error("text is required", 400)

    r = await _redis()
    if r is None:
        return error("redis unavailable", 500)
    try:
        import time as _t

        entry = {
            "participant": speaker,
            "text": text,
            "ts_ms": int(_t.time() * 1000),
            "injected": True,
        }
        await r.rpush(f"meeting:{meeting_id}:transcript", json.dumps(entry))
        await r.publish(
            f"meeting:{meeting_id}:events",
            json.dumps({"type": "transcript", "entry": json.dumps(entry)}),
        )
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    return success({"injected": True, "speaker": speaker, "text": text})


@router.post("/{meeting_id}/kill")
async def kill_meeting(
    meeting_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _load(meeting_id, user, db)
    if not m:
        return error("not found", 404)
    m.status = MeetingStatus.KILLED.value
    m.ended_at = datetime.now(timezone.utc)
    await db.commit()
    r = await _redis()
    if r:
        try:
            await r.set(f"meeting:{meeting_id}:kill", "1", ex=3600)
            await r.publish(
                f"meeting:{meeting_id}:events",
                json.dumps({"type": "kill", "meeting_id": meeting_id}),
            )
        finally:
            try:
                await r.aclose()
            except Exception:
                pass
    return success({"killed": True, "meeting_id": meeting_id})


@router.get("/{meeting_id}/stream")
async def stream_meeting(
    meeting_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream of live transcript + decisions for the UI's Live view."""
    m = await _load(meeting_id, user, db)
    if not m:
        raise HTTPException(status_code=404, detail="not found")
    return StreamingResponse(
        _sse_events(meeting_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _sse_events(meeting_id: str):
    r = await _redis()
    if r is None:
        yield "event: error\ndata: redis_unavailable\n\n"
        return
    pubsub = r.pubsub()
    channel = f"meeting:{meeting_id}:events"
    try:
        await pubsub.subscribe(channel)
        # Replay recent transcript + decisions so late subscribers see history
        for key, kind in (("transcript", "transcript"), ("decisions", "decision")):
            raw = await r.lrange(f"meeting:{meeting_id}:{key}", -50, -1)
            for item in raw:
                yield f"event: {kind}\ndata: {item}\n\n"
        # Keepalive ticker
        last_keepalive = time.monotonic()
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
            if msg:
                data = msg.get("data", "")
                if data:
                    try:
                        payload = json.loads(data) if isinstance(data, str) else {}
                    except Exception:
                        payload = {}
                    etype = payload.get("type", "event")
                    yield f"event: {etype}\ndata: {data}\n\n"
            if time.monotonic() - last_keepalive > 15:
                yield ": keepalive\n\n"
                last_keepalive = time.monotonic()
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            await r.aclose()
        except Exception:
            pass


@router.get("/{meeting_id}/deferrals")
async def list_deferrals(
    meeting_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _load(meeting_id, user, db)
    if not m:
        return error("not found", 404)
    q = await db.execute(
        select(MeetingDeferral)
        .where(MeetingDeferral.meeting_id == m.id)
        .order_by(MeetingDeferral.created_at)
    )
    out = []
    for d in q.scalars().all():
        out.append(
            {
                "id": str(d.id),
                "question": d.question,
                "context": d.context,
                "answer": d.answer,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "answered_at": d.answered_at.isoformat() if d.answered_at else None,
            }
        )
    return success(out)


@router.post("/{meeting_id}/deferrals/{deferral_id}/answer")
async def answer_deferral(
    meeting_id: str,
    deferral_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _load(meeting_id, user, db)
    if not m:
        return error("not found", 404)
    answer_text = (body.get("answer") or "").strip()
    if not answer_text:
        return error("answer is required", 400)

    # Publish to Redis so the waiting defer_to_human tool wakes up
    r = await _redis()
    if r:
        try:
            await r.publish(
                f"deferral:{deferral_id}:answer",
                json.dumps({"answer": answer_text, "user_id": str(user.id)}),
            )
            # Update pending entry status
            await r.hset(
                f"meeting:{meeting_id}:deferral:{deferral_id}",
                mapping={"status": "answered", "answer": answer_text},
            )
        finally:
            try:
                await r.aclose()
            except Exception:
                pass

    # Persist / upsert into meeting_deferrals
    try:
        did = uuid.UUID(deferral_id)
    except Exception:
        did = uuid.uuid4()
    # Try to find an existing pending row; if not, insert one so history is preserved.
    existing = (
        (await db.execute(select(MeetingDeferral).where(MeetingDeferral.id == did)))
        .scalars()
        .first()
    )
    if existing is None:
        existing = MeetingDeferral(
            id=did,
            tenant_id=user.tenant_id,
            meeting_id=m.id,
            user_id=user.id,
            question=body.get("question") or "(see live transcript)",
            context=body.get("context"),
        )
        db.add(existing)
    existing.answer = answer_text
    existing.status = "answered"
    existing.answered_at = datetime.now(timezone.utc)
    m.deferral_count = (m.deferral_count or 0) + 1
    await db.commit()
    return success({"deferral_id": str(existing.id), "status": "answered"})


async def _load(meeting_id: str, user: User, db: AsyncSession) -> Meeting | None:
    try:
        mid = uuid.UUID(meeting_id)
    except Exception:
        return None
    q = await db.execute(
        select(Meeting).where(Meeting.id == mid, Meeting.user_id == user.id)
    )
    return q.scalars().first()


async def _run_meeting_agent(m: Meeting, user: User, body: dict) -> None:
    """Run the Meeting Representative agent in-process for this meeting."""
    import logging as _logging

    log = _logging.getLogger(__name__)

    # Lazy imports to avoid import-time loops
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
    sys.path.insert(
        0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime")
    )
    try:
        from sqlalchemy import select as _sel
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from models.agent import Agent  # noqa: E402
        from models.execution import Execution, ExecutionStatus  # noqa: E402
        from engine.llm_router import LLMRouter  # type: ignore
        from engine.agent_executor import AgentExecutor, build_tool_registry  # type: ignore
        from engine.tools import _meeting_session as sessmod  # type: ignore
    except Exception as e:
        log.warning("meeting agent: import failed — %s", e)
        # Can't write to decision log without sessmod — just log to stderr
        return

    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        await sessmod.append_decision(
            str(m.id), "leave", "Bot startup failed: no DATABASE_URL"
        )
        return

    # Open our own sessionmaker — the FastAPI request-scoped one is gone
    # by the time this background task runs.
    try:
        engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=2)
        Session = async_sessionmaker(engine, expire_on_commit=False)
    except Exception as e:
        await sessmod.append_decision(
            str(m.id), "leave", f"Bot startup: DB engine failed ({e})"
        )
        return

    agent = None
    try:
        async with Session() as db2:
            if m.agent_id:
                agent = (
                    (await db2.execute(_sel(Agent).where(Agent.id == m.agent_id)))
                    .scalars()
                    .first()
                )
            if not agent:
                agent = (
                    (
                        await db2.execute(
                            _sel(Agent).where(Agent.slug == "meeting-representative")
                        )
                    )
                    .scalars()
                    .first()
                )
            if not agent:
                await sessmod.append_decision(
                    str(m.id),
                    "leave",
                    "Bot startup failed: no agent found. Run packages/db/seeds/seed_agents.py to install the OOB Meeting Representative.",
                )
                return

            mc = agent.model_config_ or {}
            model = mc.get("model", "claude-sonnet-4-5-20250929")
            temperature = mc.get("temperature", 0.2)
            tool_names = mc.get("tools", [])
            max_iter = int(mc.get("max_iterations", 40))
            system_prompt = agent.system_prompt or ""

            # Persist an Execution row so the UI's executions view sees this
            execution = Execution(
                tenant_id=user.tenant_id,
                agent_id=agent.id,
                user_id=user.id,
                input_message=f"meeting_id={m.id}",
                status=ExecutionStatus.RUNNING,
                model_used=model,
            )
            db2.add(execution)
            await db2.commit()
            await db2.refresh(execution)
            execution_id = str(execution.id)
    except Exception as e:
        log.warning("meeting agent: agent lookup failed — %s", e)
        await sessmod.append_decision(str(m.id), "leave", f"Bot startup failed: {e}")
        await engine.dispose()
        return

    await sessmod.append_decision(
        str(m.id),
        "join",
        f"Bot dispatched: agent={agent.name}, tools={len(tool_names)}",
        detail={"execution_id": execution_id, "model": model},
    )

    try:
        tool_registry = build_tool_registry(
            tool_names,
            kb_ids=[],
            agent_id=str(agent.id),
            tenant_id=str(user.tenant_id),
            execution_id=execution_id,
            agent_name=agent.name,
            db_url=db_url,
            acting_subject={"user_id": str(user.id), "sub": str(user.id)},
        )
        llm = LLMRouter()
        executor = AgentExecutor(
            llm_router=llm,
            tool_registry=tool_registry,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            agent_id=str(agent.id),
            max_iterations=max_iter,
        )
        # Run the agent — will block until it terminates (leave or kill).
        # We mirror EVERY tool call + tool result into the decision log so
        # the /meetings/<id> live view shows exactly what the agent did,
        # not just a "Bot dispatched" line followed by silence.
        async for evt in executor.stream(f"meeting_id={m.id}"):
            try:
                if evt.event == "tool_call":
                    d = evt.data if isinstance(evt.data, dict) else {}
                    name = d.get("name", "?")
                    args_preview = json.dumps(d.get("arguments") or {})[:120]
                    await sessmod.append_decision(
                        str(m.id),
                        "answer",
                        f"→ {name}({args_preview})",
                        detail={"tool": name, "args": d.get("arguments")},
                    )
                elif evt.event == "tool_result":
                    d = evt.data if isinstance(evt.data, dict) else {}
                    is_err = d.get("is_error") or d.get("isError")
                    name = d.get("name", "?")
                    content = str(d.get("content") or d.get("result") or "")[:200]
                    if is_err:
                        await sessmod.append_decision(
                            str(m.id),
                            "leave",
                            f"✗ {name} failed: {content}",
                            detail={"tool": name, "is_error": True, "result": content},
                        )
                    else:
                        await sessmod.append_decision(
                            str(m.id),
                            "answer",
                            f"✓ {name} → {content[:120]}",
                            detail={"tool": name, "result": content},
                        )
                elif evt.event == "error":
                    em = (
                        evt.data
                        if isinstance(evt.data, dict)
                        else {"message": str(evt.data)}
                    )
                    await sessmod.append_decision(
                        str(m.id),
                        "leave",
                        f"Agent error: {str(em.get('message') or em)[:200]}",
                    )
                elif evt.event == "done":
                    d = evt.data if isinstance(evt.data, dict) else {}
                    out = (d.get("output") or "")[:200]
                    if out:
                        await sessmod.append_decision(
                            str(m.id),
                            "leave",
                            f"Agent finished. Final output: {out}",
                        )
            except Exception as _e:
                # Don't let logging break the agent
                log.warning("decision log mirror failed: %s", _e)
    except Exception as e:
        log.warning("meeting agent execution failed: %s", e)
        await sessmod.append_decision(str(m.id), "leave", f"Agent crashed: {e}")
        # Persist the failure on the execution row so the dashboard
        # stops showing this as "active", AND so a notification fires
        # via _notify_execution_failure below.
        try:
            async with Session() as db3:
                ex = await db3.get(Execution, execution.id)
                if ex and ex.status == ExecutionStatus.RUNNING:
                    ex.status = ExecutionStatus.FAILED
                    ex.error_message = f"Meeting agent crashed: {e}"[:2000]
                    ex.completed_at = datetime.now(timezone.utc)
                    await db3.commit()
            # Fire an in-app notification so the user doesn't have to
            # monitor the dashboard — they hear about failures actively.
            await _notify_execution_failure(
                tenant_id=m.tenant_id,
                user_id=user.id,
                execution_id=execution.id,
                agent_id=m.agent_id,
                error=str(e)[:500],
                meeting_id=str(m.id),
            )
        except Exception:
            pass
    finally:
        try:
            async with Session() as db3:
                ex = await db3.get(Execution, execution.id)
                if ex and ex.status == ExecutionStatus.RUNNING:
                    ex.status = ExecutionStatus.COMPLETED
                    ex.completed_at = datetime.now(timezone.utc)
                    await db3.commit()
        except Exception:
            pass
        try:
            await engine.dispose()
        except Exception:
            pass
