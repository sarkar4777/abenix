"""Getting file bytes into storage without holding them in memory, and once per collection."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import shutil
import sys
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.knowledge_base import Document, DocumentStatus, KBStatus, KnowledgeBase

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "./data/uploads")
HASH_BLOCK = 1024 * 1024

ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-outlook": "msg",
    "text/html": "html",
    "text/plain": "txt",
    "text/csv": "csv",
    "text/tab-separated-values": "tsv",
    "text/markdown": "md",
    "application/json": "json",
}
ALLOWED_EXTENSIONS = (
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "html",
    "htm",
    "msg",
    "txt",
    "csv",
    "tsv",
    "md",
    "json",
    "log",
)
ALLOWED_LABEL = "PDF, DOCX, PPTX, XLSX, HTML, MSG, TXT, CSV, TSV, MD, JSON, LOG"


def max_upload_bytes() -> int:
    return int(os.environ.get("KB_MAX_UPLOAD_BYTES", str(20 * 1024**3)))


def direct_upload_min_bytes() -> int:
    return int(os.environ.get("KB_DIRECT_UPLOAD_MIN_BYTES", str(64 * 1024**2)))


def bulk_max_files() -> int:
    return int(os.environ.get("KB_BULK_MAX_FILES", "200"))


def file_type_for(content_type: str | None, filename: str | None) -> str | None:
    found = ALLOWED_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if found:
        return found
    name = filename or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext if ext in ALLOWED_EXTENSIONS else None


def size_error(size: int) -> str | None:
    if size <= 0:
        return "Empty file"
    limit = max_upload_bytes()
    if size > limit:
        return f"File too large. The limit is {limit // (1024 * 1024)} MB"
    return None


def clean_sha256(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    valid = len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    return value if valid else None


def _sha256_of(fileobj: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    fileobj.seek(0)
    while block := fileobj.read(HASH_BLOCK):
        digest.update(block)
        size += len(block)
    fileobj.seek(0)
    return digest.hexdigest(), size


async def hash_spooled(fileobj: BinaryIO) -> tuple[str, int]:
    return await asyncio.to_thread(_sha256_of, fileobj)


def _storage():
    from engine.storage import get_storage

    return get_storage()


async def store_fileobj(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    stored_name: str,
    fileobj: BinaryIO,
    content_type: str | None,
) -> str:
    try:
        storage = _storage()
    except ImportError:
        upload_dir = Path(UPLOAD_DIR) / str(tenant_id) / str(kb_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        target = upload_dir / stored_name
        with open(target, "wb") as out:
            await asyncio.to_thread(shutil.copyfileobj, fileobj, out, HASH_BLOCK)
        return str(target)
    return await storage.upload_fileobj(
        str(tenant_id),
        f"kb/{kb_id}/{stored_name}",
        fileobj,
        content_type or "application/octet-stream",
    )


class TooLarge(Exception):
    pass


class HashingStream:
    """Counts and hashes a request body as it passes, and stops it at the limit."""

    def __init__(self, source: AsyncIterator[bytes], limit: int) -> None:
        self.source = source
        self.limit = limit
        self.size = 0
        self.digest = hashlib.sha256()

    async def chunks(self) -> AsyncIterator[bytes]:
        async for chunk in self.source:
            self.size += len(chunk)
            if self.size > self.limit:
                raise TooLarge()
            self.digest.update(chunk)
            yield chunk


async def existing_document(
    db: AsyncSession, kb_id: uuid.UUID, sha256: str
) -> Document | None:
    return (
        await db.execute(
            select(Document).where(
                Document.kb_id == kb_id,
                Document.content_sha256 == sha256,
                Document.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()


def can_resume(doc: Document) -> bool:
    value = doc.status.value if hasattr(doc.status, "value") else doc.status
    return str(value).lower() == DocumentStatus.FAILED.value


async def resume_failed(db: AsyncSession, kb: KnowledgeBase, doc: Document) -> None:
    """The same file failed before, so go on from its checkpoint with what is already paid for."""
    doc.status = DocumentStatus.PROCESSING
    doc.error_message = None
    doc.ingest_attempts = 0
    kb.status = KBStatus.PROCESSING
    await db.commit()
    await db.refresh(doc)


async def register_document(
    db: AsyncSession,
    kb: KnowledgeBase,
    *,
    doc_id: uuid.UUID,
    filename: str,
    file_type: str,
    file_size: int,
    storage_url: str,
    sha256: str | None,
    uploaded_by: uuid.UUID | None,
) -> tuple[Document, bool]:
    """(document, created). The unique index settles two uploads of one file racing."""
    doc = Document(
        id=doc_id,
        kb_id=kb.id,
        filename=filename,
        file_type=file_type,
        file_size=file_size,
        chunk_count=0,
        status=DocumentStatus.PROCESSING,
        storage_url=storage_url,
        uploaded_by=uploaded_by,
        content_sha256=sha256,
    )
    db.add(doc)
    kb.status = KBStatus.PROCESSING
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        twin = await existing_document(db, kb.id, sha256) if sha256 else None
        if twin is None:
            raise
        return twin, False
    await db.refresh(doc)
    return doc, True


def _token_key() -> bytes:
    return hashlib.sha256(settings.secret_key.encode() + b":kb-upload").digest()


def sign_upload(claims: dict[str, Any], ttl_seconds: int = 7 * 86400) -> str:
    body = {**claims, "exp": int(time.time()) + ttl_seconds}
    raw = base64.urlsafe_b64encode(json.dumps(body).encode()).decode().rstrip("=")
    mac = hmac.new(_token_key(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{mac}"


def read_upload(token: str) -> dict[str, Any] | None:
    raw, _, mac = token.partition(".")
    want = hmac.new(_token_key(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, want):
        return None
    try:
        body = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except ValueError:
        return None
    return body if body.get("exp", 0) >= time.time() else None
