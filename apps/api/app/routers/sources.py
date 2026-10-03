"""Source Watch API: the tenant's watched sources, their snapshots and detected changes."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.audit import log_action
from app.core.capabilities import require_capability
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.services import source_watch as SW
from engine.sources import normalize as N
from models.knowledge_base import KnowledgeBase
from models.source_watch import SourceChange, SourceSnapshot, WatchSource
from models.tenant import Tenant
from models.user import User

router = APIRouter(prefix="/api/sources", tags=["sources"])

Kind = Literal["html", "pdf", "xlsx", "csv", "json", "rss"]
Tier = Literal["low", "medium", "high", "critical"]
_HEADER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
_SECRET_HEADERS = {"authorization", "cookie", "proxy-authorization", "x-api-key"}
_ALLOWLIST_HOST = re.compile(
    r"^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$"
)


def _iso(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else None


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url or "").hostname or "").lower()


def health(s: WatchSource) -> str:
    if s.last_status == "stopped":
        return "stopped"
    if not s.active:
        return "paused"
    if s.consecutive_failures:
        return "failing"
    if s.last_checked_at is None:
        return "new"
    return "ok"


def source_json(s: WatchSource, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "id": str(s.id),
        "name": s.name,
        "description": s.description or "",
        "url": s.url,
        "host": _host(s.url),
        "kind": s.kind,
        "cadence_minutes": s.cadence_minutes,
        "active": bool(s.active),
        "paused_reason": s.paused_reason,
        "credentials_key": s.credentials_key,
        "headers": dict(s.headers or {}),
        "selector": s.selector,
        "jurisdiction": s.jurisdiction,
        "tags": list(s.tags or []),
        "risk_tier": s.risk_tier,
        "ingest_to_kb": str(s.ingest_to_kb) if s.ingest_to_kb else None,
        "kb_document_id": str(s.kb_document_id) if s.kb_document_id else None,
        "created_by": str(s.created_by) if s.created_by else None,
        "created_at": _iso(s.created_at),
        "updated_at": _iso(s.updated_at),
        "next_check_at": _iso(s.next_check_at),
        "last_checked_at": _iso(s.last_checked_at),
        "last_changed_at": _iso(s.last_changed_at),
        "last_status": s.last_status,
        "last_error": s.last_error,
        "consecutive_failures": s.consecutive_failures or 0,
        "etag": s.etag,
        "last_modified": s.last_modified,
        "current_snapshot_id": (
            str(s.current_snapshot_id) if s.current_snapshot_id else None
        ),
        "check_count": s.check_count or 0,
        "health": health(s),
    }
    if extra:
        out.update(extra)
    return out


def snapshot_json(p: SourceSnapshot, *, text: bool = False) -> dict[str, Any]:
    out = {
        "id": str(p.id),
        "source_id": str(p.source_id),
        "url": p.url,
        "kind": p.kind,
        "content_sha256": p.content_sha256,
        "text_sha256": p.text_sha256,
        "content_type": p.content_type,
        "bytes": p.bytes,
        "http_status": p.http_status,
        "http_headers": dict(p.http_headers or {}),
        "fetched_at": _iso(p.fetched_at),
        "parser_version": p.parser_version,
        "title": p.title,
        "text_truncated": bool(p.text_truncated),
        "notes": list(p.notes or []),
    }
    if text:
        out["text"] = p.normalized_text or ""
        out["tables"] = p.tables
    return out


def change_json(c: SourceChange, *, diff: bool = False) -> dict[str, Any]:
    out = {
        "id": str(c.id),
        "source_id": str(c.source_id),
        "from_snapshot_id": str(c.from_snapshot_id) if c.from_snapshot_id else None,
        "to_snapshot_id": str(c.to_snapshot_id),
        "detected_at": _iso(c.detected_at),
        "summary": c.summary,
        "stats": dict(c.stats or {}),
        "materiality_hint": c.materiality_hint,
    }
    if diff:
        out["diff"] = c.diff or {}
    return out


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2000)
    kind: Kind = "html"
    description: str = Field(default="", max_length=4000)
    cadence_minutes: int = Field(
        default=1440, ge=SW.MIN_CADENCE_MINUTES, le=SW.MAX_CADENCE_MINUTES
    )
    selector: str | None = Field(default=None, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    credentials_key: str | None = None
    jurisdiction: str | None = Field(default=None, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=20)
    risk_tier: Tier = "low"
    ingest_to_kb: uuid.UUID | None = None
    active: bool = True


class SourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    kind: Kind | None = None
    description: str | None = Field(default=None, max_length=4000)
    cadence_minutes: int | None = Field(
        default=None, ge=SW.MIN_CADENCE_MINUTES, le=SW.MAX_CADENCE_MINUTES
    )
    selector: str | None = Field(default=None, max_length=2000)
    headers: dict[str, str] | None = None
    credentials_key: str | None = None
    jurisdiction: str | None = Field(default=None, max_length=64)
    tags: list[str] | None = Field(default=None, max_length=20)
    risk_tier: Tier | None = None
    ingest_to_kb: uuid.UUID | None = None


class PreviewIn(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    kind: Kind | None = None
    selector: str | None = Field(default=None, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    credentials_key: str | None = None


class UrlIn(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class PauseIn(BaseModel):
    reason: str = Field(default="", max_length=1000)


class SettingsIn(BaseModel):
    host_allowlist: list[str] = Field(default_factory=list, max_length=500)
    pause_after_failures: int = Field(default=5, ge=1, le=100)


def check_headers(headers: dict[str, str]) -> str | None:
    if len(headers) > 20:
        return "Use at most 20 request headers."
    for k, v in headers.items():
        if not _HEADER_NAME.match(k or ""):
            return f"{k!r} is not a valid header name."
        if k.lower() in _SECRET_HEADERS:
            return f"Put {k} in a source credential, so it is stored encrypted, not as a plain header."
        if len(v or "") > 2000 or "\n" in (v or "") or "\r" in (v or ""):
            return f"The value of {k} is too long or has a line break."
    return None


def check_selector(kind: str, selector: str | None) -> str | None:
    if not selector or not selector.strip():
        return None
    if kind == "html":
        try:
            N.parse_css(selector)
        except N.NormalizeError as e:
            return str(e)
    elif kind == "json":
        if not selector.strip().startswith("/"):
            return (
                "For JSON sources the selector is a JSON pointer, such as /data/items."
            )
    elif kind not in ("xlsx",):
        return f"{kind} sources do not take a selector."
    return None


def clean_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = str(t).strip()[:64]
        if t and t not in out:
            out.append(t)
    return out


async def _kb_ok(db: AsyncSession, user: User, kb_id: uuid.UUID | None) -> str | None:
    if kb_id is None:
        return None
    from app.services.kb_access import user_can_edit_collection

    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if kb is None:
        return "That knowledge base does not exist in this tenant."
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return "You cannot add documents to that knowledge base."
    return None


async def _validate(
    db: AsyncSession,
    user: User,
    *,
    url: str,
    kind: str,
    selector: str | None,
    headers: dict[str, str],
    credentials_key: str | None,
    kb_id: uuid.UUID | None,
) -> str | None:
    settings = await SW.tenant_settings(db, user.tenant_id)
    for problem in (
        await SW.blocked_reason(url.strip(), settings["host_allowlist"]),
        check_headers(headers),
        check_selector(kind, selector),
        (
            None
            if not credentials_key or credentials_key in SW.CREDENTIAL_KEYS
            else f"Pick one of the source credentials: {', '.join(SW.CREDENTIAL_KEYS)}."
        ),
        await _kb_ok(db, user, kb_id),
    ):
        if problem:
            return problem
    return None


async def _own(
    db: AsyncSession, user: User, source_id: uuid.UUID
) -> WatchSource | None:
    return (
        await db.execute(
            select(WatchSource).where(
                WatchSource.id == source_id, WatchSource.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()


async def _name_taken(
    db: AsyncSession, user: User, name: str, but: uuid.UUID | None = None
) -> bool:
    q = select(WatchSource.id).where(
        WatchSource.tenant_id == user.tenant_id, WatchSource.name == name
    )
    if but is not None:
        q = q.where(WatchSource.id != but)
    return (await db.execute(q)).first() is not None


# Tenant settings


@router.get("/settings")
async def get_settings(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from engine import credentials

    settings = await SW.tenant_settings(db, user.tenant_id)
    await credentials.ensure_fresh()
    return success(
        {
            **settings,
            "credential_keys": [
                {
                    "key": k,
                    "set": bool(credentials.get(k, tenant_id=str(user.tenant_id))),
                }
                for k in SW.CREDENTIAL_KEYS
            ],
            "private_targets_allowed": SW.private_allowed(),
            "limits": {
                "max_bytes": SW.max_bytes(),
                "timeout_seconds": SW.fetch_timeout(),
                "host_interval_seconds": SW.host_interval(),
                "min_cadence_minutes": SW.MIN_CADENCE_MINUTES,
                "max_cadence_minutes": SW.MAX_CADENCE_MINUTES,
            },
            "kinds": list(N.KINDS),
        }
    )


@router.put("/settings")
async def put_settings(
    body: SettingsIn,
    request: Request,
    user: User = Depends(require_capability("risk.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    bad = [
        h for h in body.host_allowlist if not _ALLOWLIST_HOST.match(h.strip().lower())
    ]
    if bad:
        return error(
            f"These are not host names: {', '.join(bad[:5])}. Use names such as europa.eu.",
            400,
        )
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None:
        return error("Tenant not found", 404)
    cleaned = SW.clean_settings(body.model_dump())
    settings = dict(tenant.settings or {})
    old = settings.get("source_watch")
    settings["source_watch"] = cleaned
    tenant.settings = settings
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "sources.settings_updated",
        cleaned,
        request,
        resource_type="source_watch_settings",
        old_value=old,
        new_value=cleaned,
    )
    await db.commit()
    return success(cleaned)


@router.post("/validate-url")
async def validate_url(
    body: UrlIn,
    user: User = Depends(require_capability("sources.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    settings = await SW.tenant_settings(db, user.tenant_id)
    url = body.url.strip()
    reason = await SW.blocked_reason(url, settings["host_allowlist"])
    return success(
        {
            "ok": reason is None,
            "reason": reason,
            "host": _host(url),
            "suggested_kind": N.guess_kind("", url),
        }
    )


@router.post("/preview")
async def preview_source(
    body: PreviewIn,
    user: User = Depends(require_capability("sources.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    problem = check_headers(body.headers) or (
        check_selector(body.kind, body.selector) if body.kind else None
    )
    if problem:
        return error(problem, 400)
    settings = await SW.tenant_settings(db, user.tenant_id)
    await db.close()
    out = await SW.preview(
        user.tenant_id,
        url=body.url.strip(),
        kind=body.kind,
        selector=body.selector,
        headers=body.headers,
        credentials_key=body.credentials_key,
        settings=settings,
    )
    return success(out)


# Feeds across sources


@router.get("/changes")
async def recent_changes(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(SourceChange, WatchSource.name)
            .join(WatchSource, WatchSource.id == SourceChange.source_id)
            .where(SourceChange.tenant_id == user.tenant_id)
            .order_by(SourceChange.detected_at.desc())
            .limit(limit)
            .options(defer(SourceChange.diff))
        )
    ).all()
    return success([{**change_json(c), "source_name": n} for c, n in rows])


@router.get("/changes/{change_id}")
async def get_change(
    change_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    c = (
        await db.execute(
            select(SourceChange).where(
                SourceChange.id == change_id, SourceChange.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if c is None:
        return error("Change not found", 404)
    src = await db.get(WatchSource, c.source_id)
    snaps = {
        p.id: p
        for p in (
            await db.execute(
                select(SourceSnapshot)
                .where(
                    SourceSnapshot.id.in_(
                        [x for x in (c.from_snapshot_id, c.to_snapshot_id) if x]
                    )
                )
                .options(
                    defer(SourceSnapshot.normalized_text), defer(SourceSnapshot.tables)
                )
            )
        ).scalars()
    }
    before = snaps.get(c.from_snapshot_id) if c.from_snapshot_id else None
    after = snaps.get(c.to_snapshot_id)
    return success(
        {
            **change_json(c, diff=True),
            "source": (
                {"id": str(src.id), "name": src.name, "url": src.url, "kind": src.kind}
                if src
                else None
            ),
            "from_snapshot": snapshot_json(before) if before else None,
            "to_snapshot": snapshot_json(after) if after else None,
        }
    )


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot(
    snapshot_id: uuid.UUID,
    full: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = (
        await db.execute(
            select(SourceSnapshot).where(
                SourceSnapshot.id == snapshot_id,
                SourceSnapshot.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        return error("Snapshot not found", 404)
    out = snapshot_json(p, text=True)
    if full and p.text_truncated and p.normalized_text_key:
        try:
            chunks = [
                c
                async for c in SW.get_source_storage().get_stream(p.normalized_text_key)
            ]
            out["text"] = b"".join(chunks).decode("utf-8", "replace")
            out["text_truncated"] = False
        except Exception:  # noqa: BLE001
            out["full_text_error"] = "The full text is not available from storage."
    src = await db.get(WatchSource, p.source_id)
    out["source"] = {"id": str(src.id), "name": src.name} if src else None
    return success(out)


@router.get("/snapshots/{snapshot_id}/raw")
async def get_snapshot_raw(
    snapshot_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = (
        await db.execute(
            select(SourceSnapshot)
            .where(
                SourceSnapshot.id == snapshot_id,
                SourceSnapshot.tenant_id == user.tenant_id,
            )
            .options(
                defer(SourceSnapshot.normalized_text), defer(SourceSnapshot.tables)
            )
        )
    ).scalar_one_or_none()
    if p is None:
        return error("Snapshot not found", 404)
    key, ctype, size, sha, kind = (
        p.storage_key,
        p.content_type,
        p.bytes,
        p.content_sha256,
        p.kind,
    )
    await db.close()
    storage = SW.get_source_storage()
    if not await storage.exists(key):
        return error("The stored copy is gone from storage", 410)
    ext = {
        "html": "html",
        "pdf": "pdf",
        "xlsx": "xlsx",
        "csv": "csv",
        "json": "json",
        "rss": "xml",
    }.get(kind, "bin")
    headers = {
        "Content-Disposition": f'attachment; filename="snapshot-{sha[:12]}.{ext}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
        "X-Content-SHA256": sha,
    }
    if size:
        headers["Content-Length"] = str(size)
    return StreamingResponse(
        storage.get_stream(key),
        media_type=ctype or "application/octet-stream",
        headers=headers,
    )


# Sources


@router.get("")
async def list_sources(
    q: str = Query("", max_length=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    stmt = select(WatchSource).where(WatchSource.tenant_id == user.tenant_id)
    needle = q.strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(
                WatchSource.name.ilike(like),
                WatchSource.url.ilike(like),
                WatchSource.jurisdiction.ilike(like),
            )
        )
    rows = (await db.execute(stmt.order_by(WatchSource.name))).scalars().all()
    ids = [s.id for s in rows]
    snaps: dict[uuid.UUID, int] = {}
    changes: dict[uuid.UUID, int] = {}
    latest: dict[uuid.UUID, SourceChange] = {}
    if ids:
        snaps = dict(
            (
                await db.execute(
                    select(SourceSnapshot.source_id, func.count())
                    .where(SourceSnapshot.source_id.in_(ids))
                    .group_by(SourceSnapshot.source_id)
                )
            ).all()
        )
        changes = dict(
            (
                await db.execute(
                    select(SourceChange.source_id, func.count())
                    .where(SourceChange.source_id.in_(ids))
                    .group_by(SourceChange.source_id)
                )
            ).all()
        )
        last = (
            select(
                SourceChange.id,
                func.row_number()
                .over(
                    partition_by=SourceChange.source_id,
                    order_by=SourceChange.detected_at.desc(),
                )
                .label("rn"),
            )
            .where(SourceChange.source_id.in_(ids))
            .subquery()
        )
        for c in (
            await db.execute(
                select(SourceChange)
                .join(last, last.c.id == SourceChange.id)
                .where(last.c.rn == 1)
                .options(defer(SourceChange.diff))
            )
        ).scalars():
            latest[c.source_id] = c
    return success(
        [
            source_json(
                s,
                {
                    "snapshot_count": int(snaps.get(s.id, 0)),
                    "change_count": int(changes.get(s.id, 0)),
                    "latest_change": (
                        change_json(latest[s.id]) if s.id in latest else None
                    ),
                },
            )
            for s in rows
        ],
        meta={"count": len(rows)},
    )


@router.post("")
async def create_source(
    body: SourceIn,
    request: Request,
    user: User = Depends(require_capability("sources.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    name = body.name.strip()
    if await _name_taken(db, user, name):
        return error(f"A source called {name!r} already exists.", 409)
    problem = await _validate(
        db,
        user,
        url=body.url,
        kind=body.kind,
        selector=body.selector,
        headers=body.headers,
        credentials_key=body.credentials_key,
        kb_id=body.ingest_to_kb,
    )
    if problem:
        return error(problem, 400)
    s = WatchSource(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        name=name,
        description=body.description.strip(),
        url=body.url.strip(),
        kind=body.kind,
        cadence_minutes=body.cadence_minutes,
        active=body.active,
        selector=(body.selector or "").strip() or None,
        headers=body.headers,
        credentials_key=body.credentials_key or None,
        jurisdiction=(body.jurisdiction or "").strip() or None,
        tags=clean_tags(body.tags),
        risk_tier=body.risk_tier,
        ingest_to_kb=body.ingest_to_kb,
        created_by=user.id,
        consecutive_failures=0,
        check_count=0,
        next_check_at=SW.now_utc() if body.active else None,
    )
    db.add(s)
    await db.flush()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "source.created",
        {"name": s.name, "url": s.url, "kind": s.kind},
        request,
        resource_type="watch_source",
        resource_id=str(s.id),
    )
    await db.commit()
    await db.refresh(s)
    return success(source_json(s), status_code=201)


@router.get("/{source_id}")
async def get_source(
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _own(db, user, source_id)
    if s is None:
        return error("Source not found", 404)
    snaps = (
        await db.execute(
            select(func.count())
            .select_from(SourceSnapshot)
            .where(SourceSnapshot.source_id == s.id)
        )
    ).scalar() or 0
    changes = (
        await db.execute(
            select(func.count())
            .select_from(SourceChange)
            .where(SourceChange.source_id == s.id)
        )
    ).scalar() or 0
    kb_name = None
    if s.ingest_to_kb:
        kb_name = (
            await db.execute(
                select(KnowledgeBase.name).where(KnowledgeBase.id == s.ingest_to_kb)
            )
        ).scalar_one_or_none()
    return success(
        source_json(
            s, {"snapshot_count": snaps, "change_count": changes, "kb_name": kb_name}
        )
    )


@router.patch("/{source_id}")
async def update_source(
    source_id: uuid.UUID,
    body: SourcePatch,
    request: Request,
    user: User = Depends(require_capability("sources.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _own(db, user, source_id)
    if s is None:
        return error("Source not found", 404)
    sent = body.model_dump(exclude_unset=True)
    if "name" in sent:
        sent["name"] = (sent["name"] or "").strip()
        if not sent["name"]:
            return error("The name cannot be empty.", 400)
        if await _name_taken(db, user, sent["name"], but=s.id):
            return error(f"A source called {sent['name']!r} already exists.", 409)
    url = (sent.get("url") or s.url).strip()
    kind = sent.get("kind") or s.kind
    selector = sent["selector"] if "selector" in sent else s.selector
    headers = (
        sent["headers"] if sent.get("headers") is not None else dict(s.headers or {})
    )
    cred = sent["credentials_key"] if "credentials_key" in sent else s.credentials_key
    kb_id = sent["ingest_to_kb"] if "ingest_to_kb" in sent else None
    problem = await _validate(
        db,
        user,
        url=url,
        kind=kind,
        selector=selector,
        headers=headers,
        credentials_key=cred,
        kb_id=kb_id,
    )
    if problem:
        return error(problem, 400)
    before = source_json(s)
    refetch = any(
        k in sent for k in ("url", "kind", "selector", "headers", "credentials_key")
    )
    for k, v in sent.items():
        if k == "tags":
            v = clean_tags(v or [])
        elif k in ("selector", "jurisdiction", "credentials_key"):
            v = (v or "").strip() or None
        elif k in ("url", "description") and isinstance(v, str):
            v = v.strip()
        elif k == "headers" and v is None:
            continue
        setattr(s, k, v)
    if "ingest_to_kb" in sent and sent["ingest_to_kb"] != before["ingest_to_kb"]:
        s.kb_document_id = None
    if refetch:
        # what is fetched changed, so a conditional request could wrongly say nothing did
        s.etag = None
        s.last_modified = None
        if s.active:
            s.next_check_at = SW.now_utc()
    elif "cadence_minutes" in sent and s.active and s.last_checked_at:
        from datetime import timedelta

        s.next_check_at = s.last_checked_at + timedelta(minutes=s.cadence_minutes)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "source.updated",
        {"fields": sorted(sent)},
        request,
        resource_type="watch_source",
        resource_id=str(s.id),
        old_value={k: before.get(k) for k in sent},
        new_value={k: source_json(s).get(k) for k in sent},
    )
    await db.commit()
    await db.refresh(s)
    return success(source_json(s))


@router.delete("/{source_id}")
async def delete_source(
    source_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_capability("sources.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _own(db, user, source_id)
    if s is None:
        return error("Source not found", 404)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "source.deleted",
        {"name": s.name, "url": s.url},
        request,
        resource_type="watch_source",
        resource_id=str(s.id),
    )
    await db.delete(s)
    await db.commit()
    return success({"id": str(source_id), "deleted": True})


@router.post("/{source_id}/pause")
async def pause_source(
    source_id: uuid.UUID,
    body: PauseIn,
    request: Request,
    user: User = Depends(require_capability("sources.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _own(db, user, source_id)
    if s is None:
        return error("Source not found", 404)
    s.active = False
    s.paused_reason = body.reason.strip() or f"Paused by {user.email}"
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "source.paused",
        {"reason": s.paused_reason},
        request,
        resource_type="watch_source",
        resource_id=str(s.id),
    )
    await db.commit()
    await db.refresh(s)
    return success(source_json(s))


@router.post("/{source_id}/resume")
async def resume_source(
    source_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_capability("sources.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _own(db, user, source_id)
    if s is None:
        return error("Source not found", 404)
    s.active = True
    s.paused_reason = None
    s.consecutive_failures = 0
    s.next_check_at = SW.now_utc()
    if s.last_status == "stopped":
        s.last_status = None
        s.last_error = None
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "source.resumed",
        {},
        request,
        resource_type="watch_source",
        resource_id=str(s.id),
    )
    await db.commit()
    await db.refresh(s)
    return success(source_json(s))


@router.post("/{source_id}/check-now")
async def check_now(
    source_id: uuid.UUID,
    user: User = Depends(require_capability("sources.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _own(db, user, source_id)
    if s is None:
        return error("Source not found", 404)
    await db.close()
    try:
        outcome = await asyncio.wait_for(
            SW.check_source(source_id, manual=True), timeout=SW.fetch_timeout() * 2 + 45
        )
    except asyncio.TimeoutError:
        return error(
            "The check is taking too long. It carries on in the background, refresh in a minute.",
            504,
        )
    if outcome.get("status") == "stopped":
        return error(
            outcome.get("error") or "A kill switch stops this source.",
            409,
            error_code="KILL_SWITCH",
        )
    s = await _own(db, user, source_id)
    return success({"outcome": outcome, "source": source_json(s) if s else None})


@router.get("/{source_id}/snapshots")
async def list_snapshots(
    source_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _own(db, user, source_id)
    if s is None:
        return error("Source not found", 404)
    rows = (
        await db.execute(
            select(SourceSnapshot, func.length(SourceSnapshot.normalized_text))
            .where(SourceSnapshot.source_id == s.id)
            .order_by(SourceSnapshot.fetched_at.desc())
            .limit(limit)
            .options(
                defer(SourceSnapshot.normalized_text), defer(SourceSnapshot.tables)
            )
        )
    ).all()
    led_by = {
        c.to_snapshot_id: c
        for c in (
            await db.execute(
                select(SourceChange)
                .where(SourceChange.source_id == s.id)
                .options(defer(SourceChange.diff))
            )
        ).scalars()
    }
    out = []
    for p, chars in rows:
        c = led_by.get(p.id)
        out.append(
            {
                **snapshot_json(p),
                "text_chars": int(chars or 0),
                "current": p.id == s.current_snapshot_id,
                "change": change_json(c) if c else None,
            }
        )
    return success(out, meta={"count": len(out)})


@router.get("/{source_id}/changes")
async def list_changes(
    source_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    s = await _own(db, user, source_id)
    if s is None:
        return error("Source not found", 404)
    rows = (
        (
            await db.execute(
                select(SourceChange)
                .where(SourceChange.source_id == s.id)
                .order_by(SourceChange.detected_at.desc())
                .limit(limit)
                .options(defer(SourceChange.diff))
            )
        )
        .scalars()
        .all()
    )
    return success([change_json(c) for c in rows], meta={"count": len(rows)})
