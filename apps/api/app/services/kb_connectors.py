"""API side of knowledge connectors, secrets go to tenant_tool_credentials encrypted."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.kb_connector import KBConnectorItem, KBConnectorSource

from app.core import tool_secrets
from app.services.kb_lifecycle import STALE_AFTER, send_task

logger = logging.getLogger(__name__)

SYNC_TASK = "worker.tasks.kb_connector_sync.run"
MIN_CADENCE = 5
CLAIM_BATCH = 50


def credential_key(source_id: uuid.UUID) -> str:
    return f"KBCONN_{source_id.hex}"


async def save_secrets(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    key: str,
    secrets: dict[str, str],
    user_id: uuid.UUID | None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO tenant_tool_credentials (tenant_id, key, value, updated_by) "
            "VALUES (:t, :k, :v, :u) ON CONFLICT (tenant_id, key) DO UPDATE "
            "SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, "
            "updated_at = now()"
        ),
        {
            "t": str(tenant_id),
            "k": key,
            "v": tool_secrets.encode_for_storage(json.dumps(secrets)),
            "u": str(user_id) if user_id else None,
        },
    )


async def load_secrets(
    db: AsyncSession, tenant_id: uuid.UUID, key: str | None
) -> dict[str, str]:
    if not key:
        return {}
    row = (
        await db.execute(
            text(
                "SELECT value FROM tenant_tool_credentials "
                "WHERE tenant_id = :t AND key = :k"
            ),
            {"t": str(tenant_id), "k": key},
        )
    ).first()
    return json.loads(tool_secrets.decode_stored(row[0]) or "{}") if row else {}


async def drop_secrets(db: AsyncSession, tenant_id: uuid.UUID, key: str | None) -> None:
    if key:
        await db.execute(
            text(
                "DELETE FROM tenant_tool_credentials WHERE tenant_id = :t AND key = :k"
            ),
            {"t": str(tenant_id), "k": key},
        )


def split_fields(kind: str, values: dict[str, Any]) -> tuple[dict, dict]:
    """Secret fields never reach the config column, whatever the client sends."""
    from engine.kb_connectors import KINDS

    cls = KINDS[kind]
    known = {f.name: f for f in cls.fields}
    config = {k: v for k, v in values.items() if k in known and not known[k].secret}
    secrets = {
        k: str(v) for k, v in values.items() if k in known and known[k].secret and v
    }
    return config, secrets


def serialize(src: KBConnectorSource) -> dict[str, Any]:
    from engine.kb_connectors import KINDS

    cls = KINDS.get(src.kind)
    return {
        "id": str(src.id),
        "kb_id": str(src.kb_id),
        "name": src.name,
        "kind": src.kind,
        "label": cls.label if cls else src.kind,
        "verified_live": cls.verified_live if cls else False,
        "config": src.config or {},
        "has_credentials": bool(src.credential_key),
        "encrypted_at_rest": tool_secrets.encrypted_at_rest(),
        "cadence_minutes": src.cadence_minutes,
        "active": src.active,
        "status": src.status,
        "last_error": src.last_error,
        "next_sync_at": src.next_sync_at.isoformat() if src.next_sync_at else None,
        "last_started_at": (
            src.last_started_at.isoformat() if src.last_started_at else None
        ),
        "last_finished_at": (
            src.last_finished_at.isoformat() if src.last_finished_at else None
        ),
        "items": {
            "seen": src.items_seen,
            "ingested": src.items_ingested,
            "updated": src.items_updated,
            "deleted": src.items_deleted,
            "failed": src.items_failed,
            "skipped": src.items_skipped,
        },
    }


def serialize_item(i: KBConnectorItem) -> dict[str, Any]:
    return {
        "external_id": i.external_id,
        "name": i.name,
        "status": i.status,
        "error": i.error,
        "failures": i.failures,
        "document_id": str(i.document_id) if i.document_id else None,
        "size_bytes": i.size_bytes,
        "modified_at": i.modified_at.isoformat() if i.modified_at else None,
        "acl": i.acl,
    }


async def dispatch_sync(source_id: uuid.UUID) -> bool:
    try:
        await asyncio.to_thread(send_task, SYNC_TASK, {"source_id": str(source_id)})
        return True
    except Exception as e:
        logger.warning("could not queue connector %s: %s", source_id, e)
        return False


async def run_test(kind: str, config: dict, secrets: dict) -> dict[str, Any]:
    """Lists one page with the same guards a sync uses, nothing is stored."""
    from engine.kb_connectors import build
    from engine.kb_connectors.base import ConnectorError

    connector = build(kind, config, secrets)
    try:
        await connector.validate()
        page = await asyncio.wait_for(connector.list_page(None, None), timeout=30)
    except ConnectorError as e:
        return {"ok": False, "error": str(e)}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "The source did not answer within 30 seconds."}
    except ModuleNotFoundError as e:
        return {
            "ok": False,
            "error": f"The API has no {e.name} driver to test with. Save it and run a sync, the worker has the drivers.",
        }
    finally:
        await connector.aclose()
    return {
        "ok": True,
        "sample": [i.name for i in page.items[:5]],
        "more": not page.finished,
    }


async def claim_due(db: AsyncSession, now: datetime) -> list[uuid.UUID]:
    """Row locks so replicas never start the same source twice."""
    rows = (
        (
            await db.execute(
                select(KBConnectorSource)
                .where(
                    KBConnectorSource.active.is_(True),
                    KBConnectorSource.next_sync_at.isnot(None),
                    KBConnectorSource.next_sync_at <= now,
                    KBConnectorSource.status.notin_(("running", "queued", "pausing")),
                )
                .order_by(KBConnectorSource.next_sync_at)
                .limit(CLAIM_BATCH)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for s in rows:
        s.status = "queued"
        s.next_sync_at = now + timedelta(minutes=s.cadence_minutes or 1440)
    return [s.id for s in rows]


async def stuck_sources(db: AsyncSession, now: datetime) -> list[uuid.UUID]:
    before = now - STALE_AFTER
    rows = (
        (
            await db.execute(
                select(KBConnectorSource)
                .where(
                    KBConnectorSource.status.in_(("running", "queued")),
                    KBConnectorSource.updated_at < before,
                )
                .limit(CLAIM_BATCH)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for s in rows:
        s.updated_at = now
    return [s.id for s in rows]


async def knowledge_ops_tick() -> dict[str, int]:
    """Due connector syncs, plus any delete, re-embed or sync whose worker went away."""
    from app.core.deps import async_session
    from app.services.kb_lifecycle import sweep_stuck_jobs

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        async with db.begin():
            due = await claim_due(db, now)
            stuck = await stuck_sources(db, now)
    for sid in (*due, *stuck):
        await dispatch_sync(sid)
    async with async_session() as db:
        swept = await sweep_stuck_jobs(db)
    return {"synced": len(due), "resumed": len(stuck) + sum(swept.values())}
