"""Connectors of a knowledge collection, add, test, sync, pause and see status."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.services import kb_connectors as svc
from app.services.kb_access import (
    _is_tenant_admin,
    user_can_access_collection,
    user_can_edit_collection,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.kb_connector import KBConnectorItem, KBConnectorSource
from models.knowledge_base import KnowledgeBase
from models.user import User

router = APIRouter(
    prefix="/api/knowledge-bases/{kb_id}/connectors", tags=["knowledge-connectors"]
)
kinds_router = APIRouter(tags=["knowledge-connectors"])


class ConnectorBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(min_length=1, max_length=32)
    values: dict[str, Any] = Field(default_factory=dict)
    cadence_minutes: int = Field(default=1440, ge=svc.MIN_CADENCE, le=43200)


class ConnectorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    values: dict[str, Any] | None = None
    cadence_minutes: int | None = Field(default=None, ge=svc.MIN_CADENCE, le=43200)


class TestBody(BaseModel):
    kind: str
    values: dict[str, Any] = Field(default_factory=dict)


@kinds_router.get("/api/knowledge-connector-kinds")
async def connector_kinds(user: User = Depends(get_current_user)) -> Any:
    from engine.kb_connectors import describe

    return success(describe())


async def _kb(db: AsyncSession, kb_id: uuid.UUID, user: User) -> KnowledgeBase | None:
    return (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()


async def _editable(db: AsyncSession, kb_id: uuid.UUID, user: User) -> Any:
    """(collection, None) or (None, the error to send)."""
    kb = await _kb(db, kb_id, user)
    if kb is None or not await user_can_access_collection(db, user=user, kb=kb):
        return None, error("Knowledge base not found", 404)
    if not await user_can_edit_collection(db, user=user, kb=kb):
        return None, error("You don't have permission to edit this collection", 403)
    return kb, None


async def _source(
    db: AsyncSession, kb_id: uuid.UUID, source_id: uuid.UUID
) -> KBConnectorSource | None:
    return (
        await db.execute(
            select(KBConnectorSource).where(
                KBConnectorSource.id == source_id, KBConnectorSource.kb_id == kb_id
            )
        )
    ).scalar_one_or_none()


async def _validated(
    kind: str, values: dict[str, Any], user: User
) -> tuple[dict, dict, Any]:
    """(config, secrets, error). The same guard a sync applies runs before anything is saved."""
    from engine.kb_connectors import KINDS, build
    from engine.kb_connectors.base import ConnectorError

    cls = KINDS.get(kind)
    if cls is None:
        return (
            {},
            {},
            error(f"Unknown connector {kind}. Choose one of {', '.join(KINDS)}.", 400),
        )
    if cls.needs_admin and not _is_tenant_admin(user):
        return {}, {}, error(f"Only an admin can add a {cls.label} connector.", 403)
    config, secrets = svc.split_fields(kind, values)
    connector = build(kind, config, secrets)
    try:
        cls.check_fields(config, secrets)
        await connector.validate()
    except ConnectorError as e:
        return {}, {}, error(str(e), 400)
    finally:
        await connector.aclose()
    return config, secrets, None


@router.get("")
async def list_connectors(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    kb = await _kb(db, kb_id, user)
    if kb is None or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    rows = (
        (
            await db.execute(
                select(KBConnectorSource)
                .where(KBConnectorSource.kb_id == kb_id)
                .order_by(KBConnectorSource.created_at)
            )
        )
        .scalars()
        .all()
    )
    return success([svc.serialize(s) for s in rows])


@router.post("/test")
async def test_connector(
    kb_id: uuid.UUID,
    body: TestBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    _kb_row, problem = await _editable(db, kb_id, user)
    if problem is not None:
        return problem
    config, secrets, refused = await _validated(body.kind, body.values, user)
    if refused is not None:
        return refused
    return success(await svc.run_test(body.kind, config, secrets))


@router.post("")
async def create_connector(
    kb_id: uuid.UUID,
    body: ConnectorBody,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    kb, problem = await _editable(db, kb_id, user)
    if problem is not None:
        return problem
    config, secrets, refused = await _validated(body.kind, body.values, user)
    if refused is not None:
        return refused
    source_id = uuid.uuid4()
    key = svc.credential_key(source_id) if secrets else None
    if key:
        await svc.save_secrets(db, user.tenant_id, key, secrets, user.id)
    src = KBConnectorSource(
        id=source_id,
        tenant_id=user.tenant_id,
        kb_id=kb.id,
        name=body.name,
        kind=body.kind,
        config=config,
        credential_key=key,
        cadence_minutes=body.cadence_minutes,
        active=True,
        status="queued",
        next_sync_at=datetime.now(timezone.utc),
        created_by=user.id,
        items_seen=0,
        items_ingested=0,
        items_updated=0,
        items_deleted=0,
        items_failed=0,
        items_skipped=0,
        consecutive_failures=0,
        confirm_deletes=False,
    )
    db.add(src)
    await db.flush()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "kb.connector_created",
        {"kb_id": str(kb_id), "connector_id": str(source_id), "kind": body.kind},
        request,
    )
    await db.commit()
    await svc.dispatch_sync(source_id)
    return success(svc.serialize(src), status_code=201)


@router.get("/{source_id}")
async def get_connector(
    kb_id: uuid.UUID,
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    kb = await _kb(db, kb_id, user)
    if kb is None or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    src = await _source(db, kb_id, source_id)
    if src is None:
        return error("Connector not found", 404)
    return success(svc.serialize(src))


@router.get("/{source_id}/items")
async def list_items(
    kb_id: uuid.UUID,
    source_id: uuid.UUID,
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    kb = await _kb(db, kb_id, user)
    if kb is None or not await user_can_access_collection(db, user=user, kb=kb):
        return error("Knowledge base not found", 404)
    if await _source(db, kb_id, source_id) is None:
        return error("Connector not found", 404)
    query = select(KBConnectorItem).where(KBConnectorItem.source_id == source_id)
    if status:
        query = query.where(KBConnectorItem.status == status)
    rows = (
        (
            await db.execute(
                query.order_by(KBConnectorItem.external_id, KBConnectorItem.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return success([svc.serialize_item(i) for i in rows])


@router.put("/{source_id}")
async def update_connector(
    kb_id: uuid.UUID,
    source_id: uuid.UUID,
    body: ConnectorUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    _kb_row, problem = await _editable(db, kb_id, user)
    if problem is not None:
        return problem
    src = await _source(db, kb_id, source_id)
    if src is None:
        return error("Connector not found", 404)
    if body.name:
        src.name = body.name
    if body.cadence_minutes:
        src.cadence_minutes = body.cadence_minutes
    if body.values is not None:
        kept = await svc.load_secrets(db, user.tenant_id, src.credential_key)
        merged = {**(src.config or {}), **kept, **body.values}
        config, secrets, refused = await _validated(src.kind, merged, user)
        if refused is not None:
            return refused
        key = src.credential_key or (svc.credential_key(src.id) if secrets else None)
        if key and secrets:
            await svc.save_secrets(db, user.tenant_id, key, secrets, user.id)
        src.credential_key = key
        src.config = config
    await db.commit()
    return success(svc.serialize(src))


@router.delete("/{source_id}")
async def delete_connector(
    kb_id: uuid.UUID,
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Documents it brought in stay, the collection keeps what it has already indexed."""
    _kb_row, problem = await _editable(db, kb_id, user)
    if problem is not None:
        return problem
    src = await _source(db, kb_id, source_id)
    if src is None:
        return error("Connector not found", 404)
    await svc.drop_secrets(db, user.tenant_id, src.credential_key)
    await db.delete(src)
    await db.commit()
    return success({"id": str(source_id), "deleted": True})


@router.post("/{source_id}/sync")
async def sync_connector(
    kb_id: uuid.UUID,
    source_id: uuid.UUID,
    confirm_deletes: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    _kb_row, problem = await _editable(db, kb_id, user)
    if problem is not None:
        return problem
    src = await _source(db, kb_id, source_id)
    if src is None:
        return error("Connector not found", 404)
    if src.status == "running":
        return error("This connector is already syncing.", 409)
    src.status = "queued"
    src.active = True
    src.confirm_deletes = confirm_deletes
    await db.commit()
    queued = await svc.dispatch_sync(source_id)
    return success({**svc.serialize(src), "queued": queued}, status_code=202)


@router.post("/{source_id}/pause")
async def pause_connector(
    kb_id: uuid.UUID,
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    _kb_row, problem = await _editable(db, kb_id, user)
    if problem is not None:
        return problem
    src = await _source(db, kb_id, source_id)
    if src is None:
        return error("Connector not found", 404)
    src.active = False
    src.status = "pausing" if src.status == "running" else "paused"
    await db.commit()
    return success(svc.serialize(src))


@router.post("/{source_id}/resume")
async def resume_connector(
    kb_id: uuid.UUID,
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    _kb_row, problem = await _editable(db, kb_id, user)
    if problem is not None:
        return problem
    src = await _source(db, kb_id, source_id)
    if src is None:
        return error("Connector not found", 404)
    src.active = True
    src.status = "queued"
    await db.commit()
    await svc.dispatch_sync(source_id)
    return success(svc.serialize(src))
