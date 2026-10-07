"""Persona feed, the UI's hook for adding ring-fenced data to the persona KB."""

from __future__ import annotations

import logging
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

import persona_vectors as pv
from models.meeting import PersonaItem
from models.persona_chunk import PersonaChunk
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/persona", tags=["persona"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_UPLOAD_EXTS = (".txt", ".md", ".pdf")
_SCOPE_MSG = (
    "persona_scope must be letters, digits, dash, colon, underscore or dot (max 80)"
)


def _item_dict(p: PersonaItem, *, with_content: bool = False) -> dict[str, Any]:
    out = {
        "id": str(p.id),
        "persona_scope": p.persona_scope,
        "kind": p.kind,
        "title": p.title,
        "source": p.source,
        "byte_size": p.byte_size,
        "chunk_count": p.chunk_count,
        "status": p.status,
        "last_error": p.last_error,
        "embedding_model": p.embedding_model,
        "has_content": bool(p.content),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
    if with_content:
        out["content"] = p.content
    return out


def _saved(p: PersonaItem, reason: str | None) -> JSONResponse:
    data = _item_dict(p)
    if reason:
        data["warning"] = f"Saved but not searchable yet: {reason}"
    return success(data)


async def _credential(key: str, tenant_id: Any) -> str:
    """The same resolver the tools read with, so Admin, Tool Configuration applies here too."""
    try:
        from engine import credentials

        await credentials.ensure_fresh()
        return credentials.get(key, tenant_id=str(tenant_id)).strip()
    except Exception:  # noqa: BLE001
        return os.environ.get(key, "").strip()


async def _openai_key(tenant_id: Any) -> str:
    return await _credential("OPENAI_API_KEY", tenant_id)


async def _index(db: AsyncSession, p: PersonaItem) -> str | None:
    """Embed the item's content into persona_chunks. Returns the failure reason, or None."""
    item_id, tenant_id, user_id, scope = p.id, p.tenant_id, p.user_id, p.persona_scope
    chunks = pv.chunk_text(p.content or "")
    reason: str | None = None
    model = ""
    if not chunks:
        reason = "there is no text to index"
    else:
        key = await _openai_key(tenant_id)
        model = pv.default_model(key)
        try:
            vectors = await pv.embed_texts(chunks, model, openai_key=key)
            n = await pv.write_chunks(
                db,
                item_id=item_id,
                tenant_id=tenant_id,
                user_id=user_id,
                persona_scope=scope,
                chunks=chunks,
                vectors=vectors,
                model=model,
            )
            p.chunk_count = n
            p.status = "indexed"
            p.last_error = None
            p.embedding_model = model
            await db.commit()
            await db.refresh(p)
            return None
        except pv.PersonaIndexError as e:
            reason = str(e)
        except Exception as e:  # noqa: BLE001
            logger.exception("persona index write failed for %s", item_id)
            reason = (
                f"the vector store write failed ({str(e)[:200] or type(e).__name__})"
            )
    await db.rollback()
    await db.refresh(p)
    await db.execute(delete(PersonaChunk).where(PersonaChunk.item_id == item_id))
    p.chunk_count = 0
    p.status = "failed"
    p.last_error = reason
    await db.commit()
    await db.refresh(p)
    logger.warning("persona item %s not indexed: %s", item_id, reason)
    return reason


async def _create(
    db: AsyncSession,
    user: User,
    *,
    scope: str,
    kind: str,
    title: str,
    source: str,
    byte_size: int,
    content: str,
) -> tuple[PersonaItem, str | None]:
    p = PersonaItem(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        persona_scope=scope,
        kind=kind,
        title=title[:300],
        source=source[:500],
        byte_size=byte_size,
        status="pending",
        content=content,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p, await _index(db, p)


async def _own_item(db: AsyncSession, user: User, item_id: str) -> PersonaItem | None:
    try:
        iid = uuid.UUID(item_id)
    except Exception:
        return None
    q = await db.execute(
        select(PersonaItem).where(
            PersonaItem.id == iid,
            PersonaItem.user_id == user.id,
            PersonaItem.tenant_id == user.tenant_id,
            PersonaItem.deleted_at.is_(None),
        )
    )
    return q.scalars().first()


def _too_long(text: str) -> str | None:
    if len(text) > pv.MAX_TEXT_CHARS:
        return (
            f"The text is {len(text):,} characters, the limit is "
            f"{pv.MAX_TEXT_CHARS:,}. Split it into smaller pieces."
        )
    return None


@router.get("/status")
async def store_status(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Whether persona items can be indexed and searched right now."""
    from app.core.deps import engine

    st = await pv.store_status(engine)
    key = await _openai_key(user.tenant_id)
    model = pv.default_model(key)
    semantic = model != pv.local_model_id()
    return success(
        {
            "backend": "pgvector" if st.get("pgvector") else "postgres",
            "ready": bool(st.get("table")),
            "pgvector": bool(st.get("pgvector")),
            "embedding_model": model,
            "semantic": semantic,
            "error": st.get("error"),
        }
    )


@router.get("/items")
async def list_items(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    scope: str | None = None,
) -> JSONResponse:
    q = select(PersonaItem).where(
        PersonaItem.user_id == user.id,
        PersonaItem.tenant_id == user.tenant_id,
        PersonaItem.deleted_at.is_(None),
    )
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
    q = (
        select(PersonaItem.persona_scope)
        .where(
            PersonaItem.user_id == user.id,
            PersonaItem.tenant_id == user.tenant_id,
            PersonaItem.deleted_at.is_(None),
        )
        .distinct()
    )
    rows = (await db.execute(q)).scalars().all()
    scopes = sorted({s for s in rows if s})
    if "self" not in scopes:
        scopes.insert(0, "self")
    return success(scopes)


@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await _own_item(db, user, item_id)
    if not p:
        return error("not found", 404)
    return success(_item_dict(p, with_content=True))


@router.patch("/items/{item_id}")
async def update_item(
    item_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Edit title, text or scope. Any change re-indexes the item."""
    p = await _own_item(db, user, item_id)
    if not p:
        return error("not found", 404)
    if "title" in body:
        title = str(body.get("title") or "").strip()
        if not title:
            return error("title cannot be empty", 400)
        p.title = title[:300]
    if "persona_scope" in body:
        scope = str(body.get("persona_scope") or "").strip()
        if not _valid_scope(scope):
            return error(_SCOPE_MSG, 400)
        p.persona_scope = scope
    if "text" in body:
        if p.kind == "file":
            return error(
                "the text of an uploaded file cannot be edited, upload it again", 400
            )
        text = str(body.get("text") or "").strip()
        if not text:
            return error("text is required", 400)
        if msg := _too_long(text):
            return error(msg, 413)
        p.content = text
        p.byte_size = len(text.encode("utf-8"))
    p.status = "pending"
    await db.commit()
    await db.refresh(p)
    return _saved(p, await _index(db, p))


@router.post("/items/{item_id}/reindex")
async def reindex_item(
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await _own_item(db, user, item_id)
    if not p:
        return error("not found", 404)
    if not p.content:
        # items from before text was kept can still be rebuilt from their chunks
        rows = (
            (
                await db.execute(
                    select(PersonaChunk.content)
                    .where(PersonaChunk.item_id == p.id)
                    .order_by(PersonaChunk.chunk_index)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return error(
                "The original text of this item was not kept. Delete it and add it again.",
                409,
            )
        p.content = "\n".join(rows)
    p.status = "pending"
    await db.commit()
    await db.refresh(p)
    return _saved(p, await _index(db, p))


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await _own_item(db, user, item_id)
    if not p:
        return error("not found", 404)
    iid = p.id
    legacy_ids = list(p.pinecone_ids or [])
    await db.execute(delete(PersonaChunk).where(PersonaChunk.item_id == iid))
    await db.delete(p)
    await db.commit()
    legacy_deleted = await _pinecone_delete_chunks(
        tenant_id=str(user.tenant_id), ids=legacy_ids
    )
    return success(
        {"deleted": True, "legacy_vectors_deleted": legacy_deleted, "item_id": str(iid)}
    )


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
        return error(_SCOPE_MSG, 400)
    if msg := _too_long(text):
        return error(msg, 413)
    p, reason = await _create(
        db,
        user,
        scope=scope,
        kind="note",
        title=title,
        source="note",
        byte_size=len(text.encode("utf-8")),
        content=text,
    )
    return _saved(p, reason)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    title: str = Form(""),
    persona_scope: str = Form("self"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    scope = (persona_scope or "self").strip()
    if not _valid_scope(scope):
        return error(_SCOPE_MSG, 400)
    filename = file.filename or "upload"
    if not filename.lower().endswith(_UPLOAD_EXTS):
        return error("Unsupported file type. Upload a .txt, .md or .pdf file.", 400)
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        return error("The file is empty.", 400)
    if len(raw) > MAX_UPLOAD_BYTES:
        return error(
            f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB. "
            "Split it or upload the relevant part.",
            413,
        )
    text = _extract_text(filename, raw).strip()
    if not text:
        return error(
            "Could not extract text from the file. A scanned PDF has no text layer, "
            "use a .txt, .md or text-based .pdf.",
            400,
        )
    if msg := _too_long(text):
        return error(msg, 413)
    p, reason = await _create(
        db,
        user,
        scope=scope,
        kind="file",
        title=(title or "").strip() or filename,
        source=filename,
        byte_size=len(raw),
        content=text,
    )
    return _saved(p, reason)


@router.get("/voice")
async def get_voice(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Return the caller's voice-clone state."""
    return success(
        {
            "voice_id": user.voice_id,
            "voice_provider": user.voice_provider,
            "voice_consent_at": (
                user.voice_consent_at.isoformat() if user.voice_consent_at else None
            ),
            "has_clone": bool(user.voice_id and user.voice_consent_at),
            "elevenlabs_configured": bool(
                await _credential("ELEVENLABS_API_KEY", user.tenant_id)
            ),
        }
    )


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
    return success(
        {
            "voice_consent_at": user.voice_consent_at.isoformat(),
            "voice_id": user.voice_id,
            "voice_provider": user.voice_provider,
        }
    )


@router.post("/voice/revoke")
async def revoke_voice(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Revoke consent AND delete the voice from the provider side. No agent
    can use it after this call even if the user_id -> voice_id mapping leaks."""
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
    return success(
        {
            "revoked": True,
            "provider_deleted": provider_deleted,
            "old_voice_id": old_voice_id,
        }
    )


@router.post("/voice/upload")
async def upload_voice_clip(
    file: UploadFile = File(...),
    name: str = Form("My cloned voice"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Upload a 30-120s reference audio clip -> ElevenLabs clone -> register"""
    api_key = await _credential("ELEVENLABS_API_KEY", user.tenant_id)
    if not api_key:
        return error(
            "Voice cloning needs an ElevenLabs key. An admin can add "
            "ELEVENLABS_API_KEY under Admin, Tool Configuration.",
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
            description=f"Abenix user {user.id}, consent required before use",
            labels={"abenix_user": str(user.id), "tenant": str(user.tenant_id)},
        )
    except RuntimeError as e:
        # The voice-clone helper packs the provider error into the
        # exception message as JSON so we can forward useful detail,
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
            if (
                "instant_voice_cloning" in str(code)
                or "paid_plan" in str(code)
                or sc == 401
            ):
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
        return error("clone failed, check ELEVENLABS_API_KEY validity + quota", 500)
    user.voice_id = voice_id
    user.voice_provider = "elevenlabs"
    # consent remains NULL until the user explicitly calls /voice/consent
    await db.commit()
    return success(
        {
            "voice_id": voice_id,
            "voice_provider": "elevenlabs",
            "consent_required": True,
            "message": (
                "Voice cloned. The bot CANNOT use it until you record consent "
                "via POST /api/persona/voice/consent."
            ),
        }
    )


@router.post("/meeting-context")
async def add_meeting_context(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Seed context specific to an upcoming meeting, saved under scope meeting:<id>."""
    meeting_id = (body.get("meeting_id") or "").strip()
    text = (body.get("text") or "").strip()
    title = (body.get("title") or f"Meeting context {meeting_id[:8]}").strip()
    if not (meeting_id and text):
        return error("meeting_id and text are required", 400)
    try:
        uuid.UUID(meeting_id)
    except Exception:
        return error("invalid meeting_id", 400)
    if msg := _too_long(text):
        return error(msg, 413)
    p, reason = await _create(
        db,
        user,
        scope=f"meeting:{meeting_id}",
        kind="meeting_context",
        title=title,
        source=f"meeting:{meeting_id}",
        byte_size=len(text.encode("utf-8")),
        content=text,
    )
    return _saved(p, reason)


def _valid_scope(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9:_\-\.]+", s or "")) and len(s) <= 80


def _extract_text(filename: str, raw: bytes) -> str:
    lower = (filename or "").lower()
    if lower.endswith((".txt", ".md")):
        return raw.decode("utf-8", errors="ignore")
    if lower.endswith(".pdf"):
        try:
            from io import BytesIO

            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            logger.warning("pdf extract failed: %s", e)
            return ""
    return ""


async def _pinecone_delete_chunks(*, tenant_id: str, ids: list[str]) -> bool:
    """Clean up vectors written before persona moved to Postgres. Best effort."""
    if not ids:
        return True
    pinecone_key = os.environ.get("PINECONE_API_KEY", "").strip()
    index_name = os.environ.get("PINECONE_INDEX_NAME", "agentforge-knowledge")
    if not pinecone_key:
        return False
    try:
        from pinecone import Pinecone

        pc = Pinecone(api_key=pinecone_key)
        pc.Index(index_name).delete(ids=ids, namespace=f"persona:{tenant_id}")
        return True
    except Exception as e:
        logger.warning("persona legacy pinecone delete failed: %s", e)
        return False
