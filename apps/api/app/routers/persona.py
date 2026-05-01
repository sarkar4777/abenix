"""Persona feed — the UI's hook for adding ring-fenced data to the KB."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.meeting import PersonaItem
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/persona", tags=["persona"])

# Persona chunks live in their own Pinecone namespace per tenant.
_CHUNK_SIZE = 1200   # characters; ~300 tokens
_CHUNK_OVERLAP = 150


def _item_dict(p: PersonaItem) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "persona_scope": p.persona_scope,
        "kind": p.kind,
        "title": p.title,
        "source": p.source,
        "byte_size": p.byte_size,
        "chunk_count": p.chunk_count,
        "status": p.status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("/items")
async def list_items(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    scope: str | None = None,
) -> JSONResponse:
    q = select(PersonaItem).where(PersonaItem.user_id == user.id)
    if scope:
        q = q.where(PersonaItem.persona_scope == scope)
    q = q.order_by(PersonaItem.created_at.desc()).limit(500)
    rows = (await db.execute(q)).scalars().all()
    return success([_item_dict(r) for r in rows])


@router.get("/scopes")
async def list_scopes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    q = select(PersonaItem.persona_scope).where(PersonaItem.user_id == user.id).distinct()
    rows = (await db.execute(q)).scalars().all()
    scopes = sorted({s for s in rows if s})
    if "self" not in scopes:
        scopes.insert(0, "self")
    return success(scopes)


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        iid = uuid.UUID(item_id)
    except Exception:
        return error("invalid id", 400)
    q = await db.execute(
        select(PersonaItem).where(PersonaItem.id == iid, PersonaItem.user_id == user.id)
    )
    p = q.scalars().first()
    if not p:
        return error("not found", 404)
    # Delete vectors from Pinecone first (ring-fencing — don't leave orphans)
    ok = await _pinecone_delete_chunks(
        tenant_id=str(user.tenant_id),
        ids=p.pinecone_ids or [],
    )
    await db.delete(p)
    await db.commit()
    return success({"deleted": True, "pinecone_deleted": ok, "item_id": str(iid)})


@router.post("/notes")
async def add_note(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    title = (body.get("title") or "Untitled Note").strip()
    text = (body.get("text") or "").strip()
    scope = (body.get("persona_scope") or "self").strip()
    if not text:
        return error("text is required", 400)
    if not _valid_scope(scope):
        return error("persona_scope must be alphanumeric, dash, colon, underscore", 400)

    p = PersonaItem(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        persona_scope=scope,
        kind="note",
        title=title[:300],
        source="note",
        byte_size=len(text.encode("utf-8")),
        status="pending",
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)

    chunks = _chunk_text(text)
    ids = await _pinecone_upsert_chunks(
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        item_id=str(p.id),
        persona_scope=scope,
        title=title, filename="note",
        chunks=chunks,
    )
    p.chunk_count = len(ids)
    p.pinecone_ids = ids
    p.status = "indexed" if ids else "failed"
    await db.commit()
    return success(_item_dict(p))


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    title: str = Form(...),
    persona_scope: str = Form("self"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    scope = (persona_scope or "self").strip()
    if not _valid_scope(scope):
        return error("persona_scope must be alphanumeric, dash, colon, underscore", 400)
    raw = await file.read()
    if not raw:
        return error("empty file", 400)

    # Extract text — txt / md / pdf (best-effort). Other formats → return error.
    text = _extract_text(file.filename or "", raw)
    if not text.strip():
        return error(
            "Could not extract text from the uploaded file. Supported: .txt, .md, .pdf",
            400,
        )

    p = PersonaItem(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        persona_scope=scope,
        kind="file",
        title=title[:300],
        source=file.filename or "upload",
        byte_size=len(raw),
        status="pending",
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)

    chunks = _chunk_text(text)
    ids = await _pinecone_upsert_chunks(
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        item_id=str(p.id),
        persona_scope=scope,
        title=title, filename=file.filename or "upload",
        chunks=chunks,
    )
    p.chunk_count = len(ids)
    p.pinecone_ids = ids
    p.status = "indexed" if ids else "failed"
    await db.commit()
    return success(_item_dict(p))


@router.get("/voice")
async def get_voice(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Return the caller's voice-clone state."""
    return success({
        "voice_id": user.voice_id,
        "voice_provider": user.voice_provider,
        "voice_consent_at": (
            user.voice_consent_at.isoformat() if user.voice_consent_at else None
        ),
        "has_clone": bool(user.voice_id and user.voice_consent_at),
        "elevenlabs_configured": bool(os.environ.get("ELEVENLABS_API_KEY", "").strip()),
    })


@router.post("/voice/consent")
async def record_voice_consent(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Record explicit voice-clone consent. MUST be called separately from"""
    if not body.get("agree"):
        return error("Must agree to consent text", 400)
    from datetime import datetime as _dt, timezone as _tz
    user.voice_consent_at = _dt.now(_tz.utc)
    await db.commit()
    return success({
        "voice_consent_at": user.voice_consent_at.isoformat(),
        "voice_id": user.voice_id,
        "voice_provider": user.voice_provider,
    })


@router.post("/voice/revoke")
async def revoke_voice(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Revoke consent AND delete the voice from the provider side. No agent
    can use it after this call even if the user_id → voice_id mapping leaks."""
    old_voice_id = user.voice_id
    old_provider = (user.voice_provider or "").lower()
    user.voice_id = None
    user.voice_provider = None
    user.voice_consent_at = None
    await db.commit()
    provider_deleted = False
    if old_voice_id and old_provider == "elevenlabs":
        from engine.tools._voice_clone import elevenlabs_delete_voice  # type: ignore
        try:
            provider_deleted = await elevenlabs_delete_voice(voice_id=old_voice_id)
        except Exception:
            pass
    return success({
        "revoked": True,
        "provider_deleted": provider_deleted,
        "old_voice_id": old_voice_id,
    })


@router.post("/voice/upload")
async def upload_voice_clip(
    file: UploadFile = File(...),
    name: str = Form("My cloned voice"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Upload a 30-120s reference audio clip → ElevenLabs clone → register"""
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        return error(
            "Voice cloning requires ELEVENLABS_API_KEY on the server. "
            "Set it in abenix-secrets and roll the deployment.",
            400,
        )
    raw = await file.read()
    if not raw:
        return error("empty file", 400)
    if len(raw) > 50 * 1024 * 1024:
        return error("reference clip must be <= 50 MB", 400)
    from engine.tools._voice_clone import elevenlabs_clone_voice  # type: ignore
    try:
        voice_id = await elevenlabs_clone_voice(
            name=(name or f"Abenix-{user.id}")[:60],
            reference_audio_bytes=raw,
            reference_filename=file.filename or "voice.wav",
            description=f"Abenix user {user.id} — consent required before use",
            labels={"abenix_user": str(user.id), "tenant": str(user.tenant_id)},
        )
    except RuntimeError as e:
        # The voice-clone helper packs the provider error into the
        # exception message as JSON so we can forward useful detail —
        # commonly "paid_plan_required" for free-tier ElevenLabs accounts.
        try:
            import json as _json
            packed = _json.loads(str(e))
            pe = packed.get("provider_error") or {}
            msg = pe.get("message") or "voice clone provider rejected the upload"
            code = pe.get("status") or pe.get("code") or "provider_error"
            sc = packed.get("status_code") or 502
            # Map the common upgrade-required case to 402 so the UI can
            # render an actionable message instead of "internal error".
            if "instant_voice_cloning" in str(code) or "paid_plan" in str(code) or sc == 401:
                return error(
                    f"ElevenLabs: {msg} (your account plan does not include voice cloning).",
                    402,
                )
            return error(f"ElevenLabs ({code}): {msg}", sc if sc < 600 else 502)
        except Exception:
            return error(f"clone failed: {e}", 500)
    except Exception as e:
        return error(f"clone failed: {e}", 500)
    if not voice_id:
        return error("clone failed — check ELEVENLABS_API_KEY validity + quota", 500)
    user.voice_id = voice_id
    user.voice_provider = "elevenlabs"
    # consent remains NULL until the user explicitly calls /voice/consent
    await db.commit()
    return success({
        "voice_id": voice_id,
        "voice_provider": "elevenlabs",
        "consent_required": True,
        "message": (
            "Voice cloned. The bot CANNOT use it until you record consent "
            "via POST /api/persona/voice/consent."
        ),
    })


@router.post("/meeting-context")
async def add_meeting_context(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Seed context specific to an upcoming meeting. Saved under"""
    meeting_id = (body.get("meeting_id") or "").strip()
    text = (body.get("text") or "").strip()
    title = (body.get("title") or f"Meeting context {meeting_id[:8]}").strip()
    if not (meeting_id and text):
        return error("meeting_id and text are required", 400)
    try:
        uuid.UUID(meeting_id)
    except Exception:
        return error("invalid meeting_id", 400)
    scope = f"meeting:{meeting_id}"
    p = PersonaItem(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        persona_scope=scope,
        kind="meeting_context",
        title=title[:300],
        source=f"meeting:{meeting_id}",
        byte_size=len(text.encode("utf-8")),
        status="pending",
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    chunks = _chunk_text(text)
    ids = await _pinecone_upsert_chunks(
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        item_id=str(p.id),
        persona_scope=scope,
        title=title, filename=f"meeting:{meeting_id}",
        chunks=chunks,
    )
    p.chunk_count = len(ids)
    p.pinecone_ids = ids
    p.status = "indexed" if ids else "failed"
    await db.commit()
    return success(_item_dict(p))


def _valid_scope(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9:_\-\.]+", s)) and len(s) <= 80


def _chunk_text(text: str) -> list[str]:
    """Simple character-window chunker with overlap. Fine for notes and"""
    text = text.strip()
    if len(text) <= _CHUNK_SIZE:
        return [text]
    out: list[str] = []
    step = _CHUNK_SIZE - _CHUNK_OVERLAP
    i = 0
    while i < len(text):
        out.append(text[i : i + _CHUNK_SIZE])
        i += step
    return out


def _extract_text(filename: str, raw: bytes) -> str:
    lower = (filename or "").lower()
    if lower.endswith((".txt", ".md", ".log", ".json", ".yaml", ".yml")):
        try:
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    if lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            from io import BytesIO
            reader = PdfReader(BytesIO(raw))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            logger.warning("pdf extract failed: %s", e)
            return ""
    # docx support would go here
    return ""


async def _pinecone_upsert_chunks(
    *, tenant_id: str, user_id: str, item_id: str, persona_scope: str,
    title: str, filename: str, chunks: list[str],
) -> list[str]:
    if not chunks:
        return []
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    pinecone_key = os.environ.get("PINECONE_API_KEY", "").strip()
    index_name = os.environ.get("PINECONE_INDEX_NAME", "abenix-knowledge")
    if not (api_key and pinecone_key):
        logger.warning("persona upsert skipped — missing OPENAI_API_KEY or PINECONE_API_KEY")
        return []
    try:
        from openai import AsyncOpenAI
        from pinecone import Pinecone
    except ImportError:
        return []

    # The entire upsert path is best-effort — any failure (bad Pinecone
    # key, quota exceeded, OpenAI rate limit) must NOT bring down the
    # /api/persona/notes endpoint. The DB row is saved regardless with
    # status='failed' so the UI shows an actionable state to the admin.
    try:
        client = AsyncOpenAI(api_key=api_key)
        pc = Pinecone(api_key=pinecone_key)
        index = pc.Index(index_name)
    except Exception as e:
        logger.warning("persona pinecone init failed: %s", e)
        return []

    try:
        resp = await client.embeddings.create(
            model="text-embedding-3-small", input=chunks,
        )
        vectors = [d.embedding for d in resp.data]
    except Exception as e:
        logger.warning("persona embed failed: %s", e)
        return []

    ns = f"persona:{tenant_id}"
    ids: list[str] = []
    to_upsert: list[dict[str, Any]] = []
    for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
        pid = f"{item_id}:{i}"
        ids.append(pid)
        to_upsert.append({
            "id": pid,
            "values": vec,
            "metadata": {
                "text": chunk,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "persona_scope": persona_scope,
                "item_id": item_id,
                "title": title[:200],
                "filename": filename[:300],
                "chunk_index": i,
            },
        })
    try:
        index.upsert(vectors=to_upsert, namespace=ns)
    except Exception as e:
        logger.warning("persona pinecone upsert failed: %s", e)
        return []
    return ids


async def _pinecone_delete_chunks(*, tenant_id: str, ids: list[str]) -> bool:
    if not ids:
        return True
    pinecone_key = os.environ.get("PINECONE_API_KEY", "").strip()
    index_name = os.environ.get("PINECONE_INDEX_NAME", "abenix-knowledge")
    if not pinecone_key:
        return False
    try:
        from pinecone import Pinecone
    except ImportError:
        return False
    try:
        pc = Pinecone(api_key=pinecone_key)
        index = pc.Index(index_name)
        index.delete(ids=ids, namespace=f"persona:{tenant_id}")
        return True
    except Exception as e:
        logger.warning("persona pinecone delete failed: %s", e)
        return False
