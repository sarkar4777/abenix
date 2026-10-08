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
from sqlalchemy import delete, desc, select
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
        from app.core.notifications import user_wants_notification
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
            if not await user_wants_notification(
                db, user_id, NotificationType.EXECUTION_FAILED
            ):
                return
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


LIVEKIT_KEYS = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
LIVEKIT_MISSING = (
    "Live audio needs a LiveKit server. An admin sets the server URL, API key "
    "and API secret under Admin, Tool configuration, LiveKit."
)


VOICE_KEYS = ("OPENAI_API_KEY", "ELEVENLABS_API_KEY")
STT_MISSING = (
    "The bot cannot hear speech yet: speech to text needs an OpenAI API key. "
    "Typed chat in the room still reaches it."
)
TTS_MISSING = (
    "The bot cannot speak aloud yet: voice needs an OpenAI or ElevenLabs API key. "
    "It posts its replies in the room chat instead."
)
REHEARSAL_TTL = 2 * 3600


async def _livekit_settings(tenant_id: Any) -> dict[str, str]:
    """The LiveKit and voice keys as the meeting tools see them, tenant row first."""
    from engine import credentials

    try:
        await credentials.ensure_fresh()
    except Exception:
        pass  # env and file defaults still answer
    tid = str(tenant_id or "")
    return {k: credentials.get(k, tenant_id=tid) for k in LIVEKIT_KEYS + VOICE_KEYS}


def readiness_report(values: dict[str, str], is_admin: bool) -> dict[str, Any]:
    missing = [k for k in LIVEKIT_KEYS if not values.get(k)]
    stt = bool(values.get("OPENAI_API_KEY"))
    tts = stt or bool(values.get("ELEVENLABS_API_KEY"))
    return {
        "livekit_ready": not missing,
        "missing": missing,
        "message": None if not missing else LIVEKIT_MISSING,
        "configure_url": "/admin/tool-config#LIVEKIT_URL" if is_admin else None,
        "stt_ready": stt,
        "stt_message": None if stt else STT_MISSING,
        "tts_ready": tts,
        "tts_message": None if tts else TTS_MISSING,
        "voice_configure_url": (
            "/admin/tool-config#OPENAI_API_KEY" if is_admin else None
        ),
        "rehearsal_ready": bool(os.environ.get("REDIS_URL", "").strip()),
        "works_without_keys": [
            "create a meeting",
            "set the topics the bot may answer and the ones it must hand back to you",
            "rehearse with typed turns",
        ],
    }


@router.get("/readiness")
async def meetings_readiness(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """What live meetings need that is not set yet. Booleans only, never values."""
    from app.core.permissions import is_admin

    return success(
        readiness_report(await _livekit_settings(user.tenant_id), is_admin(user))
    )


@router.get("/livekit-token")
async def mint_livekit_token(
    room: str,
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Mint a token for the HUMAN user to join the same LiveKit room as"""
    lk = await _livekit_settings(user.tenant_id)
    api_key = lk["LIVEKIT_API_KEY"]
    api_secret = lk["LIVEKIT_API_SECRET"]
    url = lk["LIVEKIT_URL"]
    if not (api_key and api_secret and url):
        return error(LIVEKIT_MISSING, 400)
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
    live_deferrals: list[dict] = []
    bot_status = None
    r = await _redis()
    if r:
        try:
            transcript_raw = await r.lrange(f"meeting:{meeting_id}:transcript", 0, -1)
            decisions_raw = await r.lrange(f"meeting:{meeting_id}:decisions", 0, -1)
            transcript = _loads_all(transcript_raw)
            decisions = _loads_all(decisions_raw)
            live_deferrals = await _redis_deferrals(r, meeting_id)
            bot_status = await r.hget(f"meeting:{meeting_id}:session", "status")
        except Exception:
            pass
        finally:
            try:
                await r.aclose()
            except Exception:
                pass
    # Redis keeps history for a week, the row keeps it after that
    notes = m.notes or {}
    if not transcript:
        transcript = list(notes.get("transcript") or [])
    if not decisions:
        decisions = list(notes.get("decisions") or [])
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
    known = {d["id"] for d in deferrals}
    deferrals.extend(d for d in live_deferrals if d["id"] not in known)
    return success(
        {
            **_meeting_dict(m),
            "transcript": transcript,
            "decisions": decisions,
            "deferrals": deferrals,
            "bot_status": bot_status,
            "finalized": bool(notes.get("finalized_at")),
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
    over = await _meeting_budget_error(db, m, user)
    if over is not None:
        return over
    # without a server the bot cannot join, so do not leave a fake live meeting
    if getattr(m, "provider", None) == MeetingProvider.LIVEKIT.value:
        lk = await _livekit_settings(user.tenant_id)
        if not all(lk[k] for k in LIVEKIT_KEYS):
            return error(LIVEKIT_MISSING, 400)
    if not (m.scope_allow or []):
        return error(
            "Add at least one topic the bot may answer before starting it.", 400
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

    over = await _meeting_budget_error(db, m, user)
    if over is not None:
        return over

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


@router.delete("/{meeting_id}")
async def delete_meeting(
    meeting_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Remove a meeting that is not live, with its deferrals and transcript."""
    m = await _load(meeting_id, user, db)
    if not m:
        return error("Meeting not found", 404)
    if m.status == MeetingStatus.LIVE.value:
        return error("The bot is still in this meeting. Kick it out first.", 409)
    await db.execute(delete(MeetingDeferral).where(MeetingDeferral.meeting_id == m.id))
    await db.delete(m)
    await db.commit()
    r = await _redis()
    if r is not None:
        try:
            await r.delete(
                *(
                    f"meeting:{meeting_id}:{k}"
                    for k in (
                        "transcript",
                        "decisions",
                        "scope",
                        "rehearsal",
                        "deferrals",
                    )
                )
            )
        except Exception:
            pass
        finally:
            try:
                await r.aclose()
            except Exception:
                pass
    return success({"id": meeting_id, "deleted": True})


@router.post("/{meeting_id}/end")
async def end_meeting(
    meeting_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Wrap up: the bot writes its summary and leaves, the meeting is done."""
    m = await _load(meeting_id, user, db)
    if not m:
        return error("Meeting not found", 404)
    if m.status != MeetingStatus.LIVE.value:
        return error(f"This meeting is {m.status}, so there is nothing to end.", 409)
    transcript, decisions = await _redis_history(meeting_id)
    apply_snapshot(m, transcript, decisions, None)
    await db.commit()
    r = await _redis()
    if r is not None:
        try:
            # the listen loop sees this, and the bot leaves with a summary
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
    return success(_meeting_dict(m))


@router.get("/{meeting_id}/participants")
async def room_participants(
    meeting_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Who is in the LiveKit room right now, straight from the server."""
    m = await _load(meeting_id, user, db)
    if not m:
        return error("Meeting not found", 404)
    if m.provider != MeetingProvider.LIVEKIT.value:
        return success({"available": False, "participants": [], "message": None})
    lk = await _livekit_settings(user.tenant_id)
    if not all(lk[k] for k in LIVEKIT_KEYS):
        return success(
            {"available": False, "participants": [], "message": LIVEKIT_MISSING}
        )
    try:
        from livekit import api

        lkapi = api.LiveKitAPI(
            _http_url(lk["LIVEKIT_URL"]),
            lk["LIVEKIT_API_KEY"],
            lk["LIVEKIT_API_SECRET"],
        )
        try:
            res = await asyncio.wait_for(
                lkapi.room.list_participants(api.ListParticipantsRequest(room=m.room)),
                timeout=5,
            )
        finally:
            await lkapi.aclose()
    except Exception as e:
        return success(
            {
                "available": False,
                "participants": [],
                "message": f"Could not ask the LiveKit server who is in the room ({str(e)[:160] or type(e).__name__}).",
            }
        )
    people = [
        {
            "identity": p.identity,
            "name": p.name or p.identity,
            "is_bot": p.identity.startswith("bot-"),
            "is_you": p.identity == f"user-{user.id}",
        }
        for p in getattr(res, "participants", []) or []
    ]
    return success({"available": True, "participants": people, "message": None})


def _http_url(url: str) -> str:
    if url.startswith("wss://"):
        return "https://" + url[6:]
    if url.startswith("ws://"):
        return "http://" + url[5:]
    return url


# Rehearsal: the same agent, tools and scope, with typed turns and no room.


def _rehearsal_ptr(meeting_id: str) -> str:
    return f"meeting:{meeting_id}:rehearsal"


async def _rehearsal_id(r: Any, meeting_id: str) -> str | None:
    rid = await r.get(_rehearsal_ptr(meeting_id))
    return rid or None


async def _rehearsal_status(r: Any, rid: str) -> str:
    status = await r.hget(f"meeting:{rid}:session", "status") or "starting"
    if status != "closed" and await r.get(f"meeting:{rid}:kill"):
        return "ending"
    return status


async def _rehearsal_state(r: Any, rid: str) -> dict[str, Any]:
    t = await r.lrange(f"meeting:{rid}:transcript", 0, -1)
    dl = await r.lrange(f"meeting:{rid}:decisions", 0, -1)
    queued = await r.llen(f"meeting:{rid}:rehearsal:turns")
    return {
        "active": True,
        "rehearsal_id": rid,
        "status": await _rehearsal_status(r, rid),
        "transcript": _loads_all(t),
        "decisions": _loads_all(dl),
        "deferrals": await _redis_deferrals(r, rid),
        "queued_turns": int(queued or 0),
    }


def _redis_missing() -> JSONResponse:
    return error(
        "Rehearsal needs Redis, and this deployment has no REDIS_URL set. "
        "Ask an admin to configure it.",
        503,
    )


@router.post("/{meeting_id}/rehearsal")
async def start_rehearsal(
    meeting_id: str,
    body: dict | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Start a rehearsal: the meeting agent runs exactly as live, minus the room."""
    m = await _load(meeting_id, user, db)
    if not m:
        return error("Meeting not found", 404)
    if m.status == MeetingStatus.LIVE.value:
        return error(
            "The bot is in the live meeting right now. Rehearse before or after it.",
            409,
        )
    if not (m.scope_allow or []):
        return error(
            "Add at least one topic the bot may answer, then rehearse. "
            "Use Edit under Bot scope.",
            400,
        )
    over = await _meeting_budget_error(db, m, user)
    if over is not None:
        return over
    r = await _redis()
    if r is None:
        return _redis_missing()
    try:
        old = await _rehearsal_id(r, meeting_id)
        if old and await _rehearsal_status(r, old) in ("starting", "live"):
            if not (body or {}).get("restart"):
                return success(await _rehearsal_state(r, old))
            await r.set(f"meeting:{old}:kill", "1", ex=3600)
        rid = f"rehearsal-{uuid.uuid4().hex[:12]}"
        await r.hset(
            f"meeting:{rid}:scope",
            mapping={
                "authorized": "1",
                "allow": "|".join(m.scope_allow or []),
                "defer": "|".join(m.scope_defer or []),
                "persona_scopes": "|".join(m.persona_scopes or ["self"]),
                "user_id": str(user.id),
                "tenant_id": str(user.tenant_id),
                "room": rid,
                "provider": "rehearsal",
                "display_name": m.display_name or "Abenix Assistant",
                "rehearsal_of": str(m.id),
            },
        )
        await r.hset(f"meeting:{rid}:session", mapping={"status": "starting"})
        for k in ("scope", "session"):
            await r.expire(f"meeting:{rid}:{k}", REHEARSAL_TTL)
        await r.set(_rehearsal_ptr(meeting_id), rid, ex=REHEARSAL_TTL)
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    asyncio.create_task(_run_meeting_agent(m, user, {}, key=rid, rehearsal=True))
    return success(
        {
            "active": True,
            "rehearsal_id": rid,
            "status": "starting",
            "transcript": [],
            "decisions": [],
            "deferrals": [],
            "queued_turns": 0,
        }
    )


@router.get("/{meeting_id}/rehearsal")
async def get_rehearsal(
    meeting_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _load(meeting_id, user, db)
    if not m:
        return error("Meeting not found", 404)
    r = await _redis()
    if r is None:
        return success({"active": False, "available": False})
    try:
        rid = await _rehearsal_id(r, meeting_id)
        if not rid:
            return success({"active": False, "available": True})
        return success(await _rehearsal_state(r, rid))
    finally:
        try:
            await r.aclose()
        except Exception:
            pass


@router.post("/{meeting_id}/rehearsal/turn")
async def rehearsal_turn(
    meeting_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Say something in the rehearsal as another participant."""
    m = await _load(meeting_id, user, db)
    if not m:
        return error("Meeting not found", 404)
    text = str(body.get("text") or "").strip()
    speaker = str(body.get("speaker") or "").strip()[:80] or "Participant"
    if not text:
        return error("Type what the participant says.", 400)
    if len(text) > 1000:
        return error("Keep a turn under 1000 characters.", 400)
    r = await _redis()
    if r is None:
        return _redis_missing()
    try:
        rid = await _rehearsal_id(r, meeting_id)
        if not rid or await _rehearsal_status(r, rid) not in ("starting", "live"):
            return error("This rehearsal has ended. Start a new one.", 409)
        ts = int(time.time() * 1000)
        key = f"meeting:{rid}:rehearsal:turns"
        await r.rpush(key, json.dumps({"speaker": speaker, "text": text, "ts_ms": ts}))
        await r.expire(key, REHEARSAL_TTL)
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    return success({"queued": True, "speaker": speaker, "text": text, "ts_ms": ts})


@router.post("/{meeting_id}/rehearsal/deferrals/{deferral_id}/answer")
async def rehearsal_answer(
    meeting_id: str,
    deferral_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Answer a question the rehearsal bot handed back to you."""
    m = await _load(meeting_id, user, db)
    if not m:
        return error("Meeting not found", 404)
    answer_text = str(body.get("answer") or "").strip()
    if not answer_text:
        return error("Type the answer the bot should give.", 400)
    r = await _redis()
    if r is None:
        return _redis_missing()
    try:
        rid = await _rehearsal_id(r, meeting_id)
        if not rid:
            return error("No rehearsal is running for this meeting.", 409)
        h = f"meeting:{rid}:deferral:{deferral_id}"
        if not await r.exists(h):
            return error("That question is no longer waiting on you.", 404)
        await r.publish(
            f"deferral:{deferral_id}:answer",
            json.dumps({"answer": answer_text, "user_id": str(user.id)}),
        )
        await r.hset(h, mapping={"status": "answered", "answer": answer_text})
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    return success({"deferral_id": deferral_id, "status": "answered"})


@router.post("/{meeting_id}/rehearsal/end")
async def end_rehearsal(
    meeting_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _load(meeting_id, user, db)
    if not m:
        return error("Meeting not found", 404)
    r = await _redis()
    if r is None:
        return _redis_missing()
    try:
        rid = await _rehearsal_id(r, meeting_id)
        if not rid:
            return error("No rehearsal is running for this meeting.", 409)
        await r.set(f"meeting:{rid}:kill", "1", ex=3600)
        await r.publish(
            f"meeting:{rid}:events", json.dumps({"type": "kill", "meeting_id": rid})
        )
        return success(await _rehearsal_state(r, rid))
    finally:
        try:
            await r.aclose()
        except Exception:
            pass


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
    transcript, decisions = await _redis_history(meeting_id)
    apply_snapshot(m, transcript, decisions, None)
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
    await db.close()
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
        raised: dict = {}
        r2 = await _redis()
        if r2 is not None:
            try:
                raised = await r2.hgetall(
                    f"meeting:{meeting_id}:deferral:{deferral_id}"
                )
            except Exception:
                raised = {}
            finally:
                try:
                    await r2.aclose()
                except Exception:
                    pass
        existing = MeetingDeferral(
            id=did,
            tenant_id=user.tenant_id,
            meeting_id=m.id,
            user_id=user.id,
            question=body.get("question")
            or (raised or {}).get("question")
            or "(see live transcript)",
            context=body.get("context") or (raised or {}).get("context"),
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


async def _meeting_agent(db: AsyncSession, m: Meeting) -> Any:
    """The agent a meeting runs, its own or the built-in Meeting Representative."""
    from models.agent import Agent

    agent = await db.get(Agent, m.agent_id) if m.agent_id else None
    if agent is None:
        agent = (
            (
                await db.execute(
                    select(Agent).where(Agent.slug == "meeting-representative")
                )
            )
            .scalars()
            .first()
        )
    return agent


async def _meeting_budget_error(
    db: AsyncSession, m: Meeting, user: User
) -> JSONResponse | None:
    from app.core.budget_gate import budget_error

    agent = await _meeting_agent(db, m)
    if agent is None:
        return None
    return await budget_error(db, agent, user.tenant_id)


async def _run_meeting_agent(
    m: Meeting,
    user: User,
    body: dict,
    *,
    key: str | None = None,
    rehearsal: bool = False,
) -> None:
    """Run the meeting agent in-process. A rehearsal runs the same agent under its own key."""
    import logging as _logging

    log = _logging.getLogger(__name__)
    mid = key or str(m.id)
    leave_summary = ""

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
            mid, "leave", "Bot startup failed: no DATABASE_URL"
        )
        return

    # Open our own sessionmaker — the FastAPI request-scoped one is gone
    # by the time this background task runs.
    try:
        engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=2)
        Session = async_sessionmaker(engine, expire_on_commit=False)
    except Exception as e:
        await sessmod.append_decision(
            mid, "leave", f"Bot startup: DB engine failed ({e})"
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
                    mid,
                    "leave",
                    "Bot startup failed: no agent found. Run packages/db/seeds/seed_agents.py to install the OOB Meeting Representative.",
                )
                return

            from app.core.budget_gate import budget_breach, per_run_cost_limit

            breach = await budget_breach(db2, agent, user.tenant_id)
            if breach is not None:
                await sessmod.append_decision(
                    mid, "leave", f"Bot not started: {breach.message}"
                )
                await engine.dispose()
                return
            cost_limit = per_run_cost_limit(agent)

            mc = agent.model_config_ or {}
            model = mc.get("model", "claude-sonnet-4-5-20250929")
            temperature = mc.get("temperature", 0.2)
            tool_names = mc.get("tools", [])
            max_iter = int(mc.get("max_iterations", 40))
            system_prompt = agent.system_prompt or ""

            # Persist an Execution row so the UI's executions view sees this
            from app.core.acting_subject import subject_columns_for

            _sid, _stype = subject_columns_for(user)
            execution = Execution(
                tenant_id=user.tenant_id,
                agent_id=agent.id,
                user_id=user.id,
                subject_id=_sid,
                subject_type=_stype,
                input_message=f"meeting_id={mid}",
                status=ExecutionStatus.RUNNING,
                trigger_kind="meeting",
                model_used=model,
            )
            db2.add(execution)
            await db2.commit()
            await db2.refresh(execution)
            execution_id = str(execution.id)
    except Exception as e:
        log.warning("meeting agent: agent lookup failed — %s", e)
        await sessmod.append_decision(mid, "leave", f"Bot startup failed: {e}")
        await engine.dispose()
        return

    await sessmod.append_decision(
        mid,
        "join",
        f"Bot dispatched: agent={agent.name}, tools={len(tool_names)}",
        detail={"execution_id": execution_id, "model": model},
    )

    final_done: dict[str, Any] = {}
    steps_after_kill = 0
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
            execution_id=execution_id,
            tenant_id=str(user.tenant_id),
            cost_limit=cost_limit,
        )
        # every step the agent takes lands in the decision log, so the live
        # view and the rehearsal show exactly what it did
        async for evt in executor.stream(f"meeting_id={mid}"):
            try:
                if evt.event == "tool_call":
                    d = evt.data if isinstance(evt.data, dict) else {}
                    if d.get("name") == "meeting_leave":
                        leave_summary = str(
                            (d.get("arguments") or {}).get("summary") or ""
                        ).strip()
                elif evt.event == "done":
                    d = evt.data if isinstance(evt.data, dict) else {}
                    final_done.update(d)
                for kind, text, detail in meeting_decisions(evt.event, evt.data):
                    await sessmod.append_decision(mid, kind, text, detail=detail)
            except Exception as _e:
                # Don't let logging break the agent
                log.warning("decision log mirror failed: %s", _e)
            # after an end or kill the bot gets a few steps to say goodbye and summarise, no more
            if evt.event == "tool_result" and await sessmod.is_killed(mid):
                steps_after_kill += 1
                if steps_after_kill > 5:
                    await sessmod.append_decision(
                        mid, "leave", "Stopped the bot after it was asked to leave"
                    )
                    break
    except Exception as e:
        log.warning("meeting agent execution failed: %s", e)
        await sessmod.append_decision(mid, "error", f"Agent crashed: {e}")
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
                if ex and final_done:
                    _record_meeting_done(ex, final_done)
                if ex and ex.status == ExecutionStatus.RUNNING:
                    ex.status = ExecutionStatus.COMPLETED
                    ex.completed_at = datetime.now(timezone.utc)
                if ex:
                    await db3.commit()
        except Exception:
            pass
        # a bot that stopped without meeting_leave must still leave the room
        sess = sessmod.get(execution_id)
        if sess is not None:
            try:
                if sess.adapter is not None:
                    await sess.adapter.leave(reason="agent_stopped")
            except Exception:
                pass
            sess.status = "closed"
            try:
                await sessmod.publish_session(sess)
            except Exception:
                pass
            sessmod.drop(execution_id)
        if rehearsal:
            await sessmod.append_decision(mid, "leave", "Rehearsal ended")
            await _mark_session_closed(mid)
        else:
            summary = leave_summary or str(final_done.get("output") or "").strip()
            try:
                await _finalize_meeting(Session, m.id, mid, summary)
            except Exception as e:
                log.warning("meeting finalize failed: %s", e)
        try:
            await engine.dispose()
        except Exception:
            pass


def _record_meeting_done(ex: Any, done: dict[str, Any]) -> None:
    """Spend and outcome from the executor's done event onto the meeting's execution row."""
    from models.execution import ExecutionStatus

    ex.cost = float(done.get("cost") or 0.0)
    ex.input_tokens = int(done.get("input_tokens") or 0)
    ex.output_tokens = int(done.get("output_tokens") or 0)
    if done.get("duration_ms") is not None:
        ex.duration_ms = int(done["duration_ms"])
    code = done.get("failure_code") or (
        "MODERATION_BLOCKED" if done.get("moderation_blocked") else None
    )
    if ex.status == ExecutionStatus.RUNNING and (code or done.get("error")):
        ex.status = ExecutionStatus.FAILED
        ex.failure_code = code
        ex.error_message = str(done.get("error") or code)[:2000]
        ex.completed_at = datetime.now(timezone.utc)


# tools that write their own decision line, so their results are not repeated
_SELF_LOGGING = {
    "meeting_join",
    "meeting_speak",
    "meeting_post_chat",
    "meeting_leave",
    "defer_to_human",
}


def _json_or_none(text: Any) -> dict | None:
    try:
        v = json.loads(text) if isinstance(text, str) else None
    except Exception:
        return None
    return v if isinstance(v, dict) else None


def meeting_decisions(event: str, data: Any) -> list[tuple[str, str, dict]]:
    """Decision-log lines for one executor event."""
    d = data if isinstance(data, dict) else {}
    name = str(d.get("name") or "?")
    if event == "tool_call":
        if name in ("meeting_listen", "scope_gate", "persona_rag"):
            return []
        args = d.get("arguments") or {}
        return [
            (
                "step",
                f"→ {name}({json.dumps(args)[:120]})",
                {"tool": name, "args": args},
            )
        ]
    if event == "tool_result":
        content = d.get("content") or d.get("result") or ""
        payload = _json_or_none(content) or {}
        if d.get("is_error") or d.get("isError"):
            # leaving after End or Kick is the expected way out, not a failure
            if "Kill-switch active" in str(content):
                return []
            if payload.get("scope_denied"):
                return [
                    (
                        "decline",
                        f"Persona scope '{payload.get('requested_scope')}' is not "
                        "authorized for this meeting",
                        {"tool": name, **payload},
                    )
                ]
            return [
                (
                    "error",
                    f"{name} failed: {str(content)[:200]}",
                    {"tool": name, "is_error": True, "result": str(content)[:500]},
                )
            ]
        # meeting_listen logs the scope decision for every question itself
        if name == "scope_gate":
            return []
        if name == "persona_rag":
            results = payload.get("results") or []
            citations = [
                {
                    "title": r.get("title") or r.get("source") or "untitled",
                    "source": r.get("source") or "",
                    "score": r.get("score"),
                    "snippet": str(r.get("text") or "")[:240],
                }
                for r in results[:5]
                if isinstance(r, dict)
            ]
            n = len(citations)
            text = (
                f"Persona search found {n} source{'s' if n != 1 else ''}"
                if n
                else "Persona search found nothing on this"
            )
            return [
                (
                    "cite",
                    text,
                    {
                        "tool": name,
                        "scope": payload.get("scope"),
                        "query": payload.get("query"),
                        "citations": citations,
                        "warnings": payload.get("warnings") or [],
                    },
                )
            ]
        if name == "meeting_listen" or name in _SELF_LOGGING:
            return []
        return [
            (
                "step",
                f"✓ {name} → {str(content)[:120]}",
                {"tool": name, "result": str(content)[:200]},
            )
        ]
    if event == "error":
        msg = d.get("message") if d else str(data)
        return [("error", f"Agent error: {str(msg or data)[:200]}", {})]
    if event == "done":
        out: list[tuple[str, str, dict]] = []
        if d.get("failure_code") == "BUDGET_EXCEEDED":
            out.append(("leave", str(d.get("error") or "")[:300], {}))
        elif d.get("error"):
            out.append(("error", f"Agent stopped: {str(d.get('error'))[:200]}", {}))
        o = str(d.get("output") or "")[:200]
        if o:
            out.append(("leave", f"Agent finished. Final output: {o}", {}))
        return out
    return []


async def _redis_history(mid: str) -> tuple[list[dict], list[dict]]:
    r = await _redis()
    if r is None:
        return [], []
    try:
        t = await r.lrange(f"meeting:{mid}:transcript", 0, -1)
        dl = await r.lrange(f"meeting:{mid}:decisions", 0, -1)
    except Exception:
        return [], []
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    return _loads_all(t), _loads_all(dl)


def _loads_all(raw: list[str]) -> list[dict]:
    out = []
    for x in raw or []:
        v = _json_or_none(x)
        if v is not None:
            out.append(v)
    return out


async def _redis_deferrals(r: Any, mid: str) -> list[dict]:
    """Deferrals the bot raised, straight from the defer_to_human records."""
    out: list[dict] = []
    try:
        ids = await r.lrange(f"meeting:{mid}:deferrals", 0, -1)
        for did in ids or []:
            h = await r.hgetall(f"meeting:{mid}:deferral:{did}")
            if not h:
                continue
            created = int(h.get("created_at_ms") or 0)
            out.append(
                {
                    "id": did,
                    "question": h.get("question") or "",
                    "context": h.get("context") or None,
                    "answer": h.get("answer") or None,
                    "status": h.get("status") or "pending",
                    "created_at": (
                        datetime.fromtimestamp(created / 1000, timezone.utc).isoformat()
                        if created
                        else None
                    ),
                    "created_at_ms": created,
                    "answered_at": None,
                }
            )
    except Exception:
        return out
    return out


def apply_snapshot(
    m: Any,
    transcript: list[dict],
    decisions: list[dict],
    summary: str | None,
) -> None:
    """Copy the meeting's history onto its row so it outlives Redis."""
    if transcript or decisions:
        notes = dict(m.notes or {})
        notes["transcript"] = transcript[-2000:]
        notes["decisions"] = decisions[-500:]
        m.notes = notes
        m.transcript_count = len(transcript)
        m.decision_count = len(decisions)
    if summary and not m.summary:
        m.summary = summary[:4000]
    if m.status == MeetingStatus.LIVE.value:
        m.status = MeetingStatus.DONE.value
        m.ended_at = datetime.now(timezone.utc)


async def _finalize_meeting(
    session_factory: Any, meeting_id: Any, mid: str, summary: str | None
) -> None:
    transcript, decisions = await _redis_history(mid)
    async with session_factory() as db:
        m = await db.get(Meeting, meeting_id)
        if m is None:
            return
        apply_snapshot(m, transcript, decisions, summary)
        # the bot is done, so the page can stop waiting for a summary
        m.notes = {
            **(m.notes or {}),
            "finalized_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.commit()


async def _mark_session_closed(mid: str) -> None:
    r = await _redis()
    if r is None:
        return
    try:
        await r.hset(f"meeting:{mid}:session", mapping={"status": "closed"})
        await r.expire(f"meeting:{mid}:session", REHEARSAL_TTL)
    except Exception:
        pass
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
