"""GDPR-compliant cascade delete with audit receipts."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from models.agent import Agent
from models.agent_memory import AgentMemory
from models.gdpr_purge_log import GDPRPurgeLog
from models.meeting import PersonaItem

logger = logging.getLogger(__name__)


STORES = ("postgres", "pinecone", "neo4j", "blob", "trajectory")
_RETRY_DELAYS = (0.5, 2.0, 5.0)
_PINECONE_BATCH = 1000


@dataclass
class Subject:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    requested_by: uuid.UUID | None = None
    emails: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    kb_ids: list[str] = field(default_factory=list)
    persona_vector_ids: list[str] = field(default_factory=list)


async def load_subject(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    subject_user_id: uuid.UUID,
    requested_by: uuid.UUID | None = None,
) -> Subject:
    """Everything the store purgers need, read before postgres scrubs the user row."""
    s = Subject(tenant_id=tenant_id, user_id=subject_user_id, requested_by=requested_by)
    row = (
        await db.execute(
            text(
                "SELECT email, full_name FROM users WHERE id = :uid AND tenant_id = :t"
            ),
            {"uid": str(subject_user_id), "t": str(tenant_id)},
        )
    ).first()
    if row is not None:
        email = (row[0] or "").strip().lower()
        if email and not email.endswith("@purged.local"):
            s.emails.append(email)
        name = " ".join((row[1] or "").split()).lower()
        # a single word matches too many unrelated Person nodes
        if len(name.split()) >= 2 and not name.startswith("deleted-"):
            s.names.append(name)
    s.kb_ids = [
        str(r[0])
        for r in (
            await db.execute(
                text("SELECT id FROM knowledge_collections WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
        ).all()
    ]
    s.persona_vector_ids = [
        str(r[0])
        for r in (
            await db.execute(
                text(
                    "SELECT unnest(pinecone_ids) FROM persona_items "
                    "WHERE user_id = :uid AND tenant_id = :t"
                ),
                {"uid": str(subject_user_id), "t": str(tenant_id)},
            )
        ).all()
        if r[0]
    ]
    return s


async def _log_store(
    db: AsyncSession,
    subject: Subject,
    store: str,
    status: str,
    error: str | None = None,
    retries: int = 0,
    affected: int | None = None,
) -> GDPRPurgeLog:
    row = GDPRPurgeLog(
        tenant_id=subject.tenant_id,
        subject_user_id=subject.user_id,
        requested_by=subject.requested_by,
        store=store,
        status=status,
        error=error,
        retries=retries,
        affected_count=affected,
        completed_at=datetime.now(timezone.utc) if status == "completed" else None,
    )
    db.add(row)
    await db.commit()
    return row


async def _purge_postgres(db: AsyncSession, subject: Subject) -> int:
    now = datetime.now(timezone.utc)
    affected = 0
    result = await db.execute(
        update(PersonaItem)
        .where(
            PersonaItem.user_id == subject.user_id,
            PersonaItem.deleted_at.is_(None),
        )
        .values(deleted_at=now, deleted_by=subject.requested_by)
    )
    affected += result.rowcount or 0
    # erasure means the text itself, not a flag, so chunks go and stored content is blanked
    from sqlalchemy import text as _text

    params = {"uid": str(subject.user_id), "tid": str(subject.tenant_id)}
    result = await db.execute(
        _text(
            "DELETE FROM persona_chunks WHERE user_id = CAST(:uid AS uuid) "
            "AND tenant_id = CAST(:tid AS uuid)"
        ),
        params,
    )
    affected += result.rowcount or 0
    await db.execute(
        _text(
            "UPDATE persona_items SET content = NULL WHERE user_id = CAST(:uid AS uuid) "
            "AND tenant_id = CAST(:tid AS uuid)"
        ),
        params,
    )
    own_agents = select(Agent.id).where(
        Agent.creator_id == subject.user_id,
        Agent.tenant_id == subject.tenant_id,
    )
    result = await db.execute(
        update(AgentMemory)
        .where(
            AgentMemory.tenant_id == subject.tenant_id,
            AgentMemory.agent_id.in_(own_agents),
            AgentMemory.deleted_at.is_(None),
        )
        .values(deleted_at=now, deleted_by=subject.requested_by)
        .execution_options(synchronize_session=False)
    )
    affected += result.rowcount or 0

    sid = str(subject.user_id)
    placeholder_email = f"deleted-{sid}@purged.local"
    placeholder_name = f"deleted-{sid[:8]}"

    r = await db.execute(
        text(
            "UPDATE users SET email=:em, full_name=:fn, is_active=false, "
            "password_hash=NULL, notification_settings='{}'::jsonb, "
            "updated_at=now() WHERE id=:uid"
        ),
        {"em": placeholder_email, "fn": placeholder_name, "uid": sid},
    )
    affected += r.rowcount or 0

    from app.services.audit_chain import NIL_ACTOR, maintenance

    # the chain keeps its salted digest, dropping the salt unlinks the person
    await maintenance(db)
    r = await db.execute(
        text(
            "UPDATE activity_logs SET user_id=:nil, ip_address=NULL, "
            "user_agent=NULL, pii_salt=NULL WHERE user_id=:uid"
        ),
        {"uid": sid, "nil": NIL_ACTOR},
    )
    affected += r.rowcount or 0

    r = await db.execute(
        text("UPDATE api_keys SET is_active=false WHERE user_id=:uid"),
        {"uid": sid},
    )
    affected += r.rowcount or 0

    # user_id stays, it is NOT NULL and now points at the scrubbed user row
    affected += await _erase_authored_content(db, subject)

    await db.commit()
    return affected


ERASED = "[erased]"

_ERASE_MESSAGES = text(
    "UPDATE messages SET content = :erased, blocks = NULL, attachments = NULL, "
    "tool_calls = NULL, updated_at = now() "
    "WHERE conversation_id IN ("
    "SELECT id FROM conversations WHERE user_id = :uid AND tenant_id = :t) "
    "AND (content <> :erased OR blocks IS NOT NULL OR attachments IS NOT NULL "
    "OR tool_calls IS NOT NULL)"
)
_ERASE_CONVERSATIONS = text(
    "UPDATE conversations SET title = :erased, last_message_preview = NULL, "
    "is_shared = false, share_token = NULL, updated_at = now() "
    "WHERE user_id = :uid AND tenant_id = :t "
    "AND (title <> :erased OR last_message_preview IS NOT NULL "
    "OR share_token IS NOT NULL OR is_shared)"
)
_ERASE_RUN_INPUTS = text(
    "UPDATE executions SET input_message = :erased, output_message = NULL, "
    "tool_calls = NULL, node_results = NULL, execution_trace = NULL "
    "WHERE user_id = :uid AND tenant_id = :t AND (input_message <> :erased "
    "OR output_message IS NOT NULL OR tool_calls IS NOT NULL "
    "OR node_results IS NOT NULL OR execution_trace IS NOT NULL)"
)


# held content of theirs still waiting is closed, nobody reviews erased text
_CLOSE_HELD = text(
    "UPDATE moderation_reviews SET status = 'rejected', decided_at = now(), "
    "decision_reason = 'Closed because the author asked for their data to be erased.', "
    "updated_at = now() "
    "WHERE user_id = :uid AND tenant_id = :t AND status = 'pending'"
)
_ERASE_HELD = text(
    "UPDATE moderation_reviews SET held_content = NULL, released_content = NULL, "
    "masked_content = :erased, spans = '[]'::jsonb, "
    "content_purged_at = COALESCE(content_purged_at, now()), updated_at = now() "
    "WHERE user_id = :uid AND tenant_id = :t AND (held_content IS NOT NULL "
    "OR released_content IS NOT NULL OR masked_content IS DISTINCT FROM :erased)"
)
_ERASE_EVENT_PREVIEWS = text(
    "UPDATE moderation_events SET content_preview = NULL "
    "WHERE user_id = :uid AND tenant_id = :t AND content_preview IS NOT NULL"
)


async def _erase_authored_content(db: AsyncSession, subject: Subject) -> int:
    """The person's conversations, both sides, what their runs took in and produced, and moderation copies of it. Rows already erased are not counted again."""
    params = {
        "uid": str(subject.user_id),
        "t": str(subject.tenant_id),
        "erased": ERASED,
    }
    total = 0
    for sql in (
        _ERASE_MESSAGES,
        _ERASE_CONVERSATIONS,
        _ERASE_RUN_INPUTS,
        _CLOSE_HELD,
        _ERASE_HELD,
        _ERASE_EVENT_PREVIEWS,
    ):
        total += (await db.execute(sql, params)).rowcount or 0
    return total


def _delete_persona_vectors(tenant_id: str, ids: list[str]) -> int:
    from pinecone import Pinecone

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index(os.environ.get("PINECONE_INDEX_NAME", "agentforge-knowledge"))
    for i in range(0, len(ids), _PINECONE_BATCH):
        index.delete(ids=ids[i : i + _PINECONE_BATCH], namespace=f"persona:{tenant_id}")
    return len(ids)


async def _purge_pinecone(db: AsyncSession, subject: Subject) -> int:
    ids = subject.persona_vector_ids
    if not ids:
        return 0
    if not os.environ.get("PINECONE_API_KEY", "").strip():
        raise RuntimeError(
            f"{len(ids)} persona vectors are in Pinecone but PINECONE_API_KEY is not set"
        )
    last_error: Exception | None = None
    for delay in _RETRY_DELAYS + (None,):
        try:
            return await asyncio.to_thread(
                _delete_persona_vectors, str(subject.tenant_id), ids
            )
        except Exception as e:
            last_error = e
            if delay is not None:
                await asyncio.sleep(delay)
    raise last_error  # type: ignore[misc]


# Entities that name the person: the e-mail anywhere, the full name on Person nodes.
NEO4J_PURGE_CYPHER = """
MATCH (e:Entity)
WHERE e.kb_id IN $kb_ids AND (
    toLower(e.canonical_name) IN $emails
    OR any(a IN coalesce(e.aliases, []) WHERE toLower(a) IN $emails)
    OR (toLower(coalesce(e.entity_type, '')) = 'person' AND (
        toLower(e.canonical_name) IN $names
        OR any(a IN coalesce(e.aliases, []) WHERE toLower(a) IN $names)))
)
WITH e, e.kb_id AS kb_id, e.canonical_name AS name
DETACH DELETE e
RETURN kb_id, name
"""

_PG_MATCH = """
    kb_id = ANY(CAST(:kb_ids AS uuid[])) AND (
        lower(canonical_name) = ANY(:emails)
        OR EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(
                CASE WHEN jsonb_typeof(aliases) = 'array' THEN aliases ELSE '[]'::jsonb END
            ) a WHERE lower(a) = ANY(:emails))
        OR (lower(entity_type) = 'person' AND (
            lower(canonical_name) = ANY(:names)
            OR EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(
                    CASE WHEN jsonb_typeof(aliases) = 'array' THEN aliases ELSE '[]'::jsonb END
                ) a WHERE lower(a) = ANY(:names))))
    )
"""


async def _mirror_graph_delete(
    db: AsyncSession, deleted: list[tuple[str, str]]
) -> None:
    by_kb: dict[str, list[str]] = {}
    for kb_id, name in deleted:
        by_kb.setdefault(kb_id, []).append(name)
    for kb_id, names in by_kb.items():
        ids = "SELECT id FROM graph_entities WHERE kb_id = CAST(:kb AS uuid) AND canonical_name = ANY(:names)"
        params = {"kb": kb_id, "names": names}
        await db.execute(
            text(
                f"DELETE FROM graph_relationships WHERE source_entity_id IN ({ids}) "
                f"OR target_entity_id IN ({ids})"
            ),
            params,
        )
        await db.execute(
            text(
                "DELETE FROM graph_entities WHERE kb_id = CAST(:kb AS uuid) "
                "AND canonical_name = ANY(:names)"
            ),
            params,
        )
        await db.execute(
            text(
                "UPDATE knowledge_collections SET "
                "entity_count = (SELECT count(*) FROM graph_entities WHERE kb_id = CAST(:kb AS uuid)), "
                "relationship_count = (SELECT count(*) FROM graph_relationships WHERE kb_id = CAST(:kb AS uuid)) "
                "WHERE id = CAST(:kb AS uuid)"
            ),
            {"kb": kb_id},
        )
    await db.commit()


async def _purge_neo4j(db: AsyncSession, subject: Subject) -> int:
    if not subject.kb_ids or not (subject.emails or subject.names):
        return 0
    from engine.knowledge.neo4j_client import get_neo4j_session, is_neo4j_available

    params = {
        "kb_ids": subject.kb_ids,
        "emails": subject.emails,
        "names": subject.names,
    }
    if not await is_neo4j_available():
        left = (
            await db.execute(
                text(f"SELECT count(*) FROM graph_entities WHERE {_PG_MATCH}"), params
            )
        ).scalar() or 0
        if left:
            raise RuntimeError(
                f"Neo4j is unreachable and {left} graph entities naming this user are in it"
            )
        return 0

    session = await get_neo4j_session()
    async with session:
        result = await session.run(NEO4J_PURGE_CYPHER, **params)
        deleted = [(str(r["kb_id"]), str(r["name"])) async for r in result]
    if deleted:
        await _mirror_graph_delete(db, deleted)
    logger.info(
        "gdpr neo4j purge removed %d entities across %d collections",
        len(deleted),
        len({k for k, _ in deleted}),
    )
    return len(deleted)


async def _remove_file(path: str) -> bool:
    """Delete a stored file and its object-storage copy, True when either existed."""
    from app.core import artifact_store
    from app.core.object_storage import get_object_storage

    existed = Path(path).is_file()
    if not existed and artifact_store.remote_enabled():
        existed = await get_object_storage().exists(artifact_store.key_for(path))
    await artifact_store.remove(path)
    return existed


async def _shared(db: AsyncSession, kind: str, resource_id: uuid.UUID) -> bool:
    from models.resource_share import ResourceShare

    row = (
        await db.execute(
            select(ResourceShare.id)
            .where(
                ResourceShare.resource_type == kind,
                ResourceShare.resource_id == resource_id,
            )
            .limit(1)
        )
    ).first()
    return row is not None


async def _code_asset_in_use(db: AsyncSession, subject: Subject, a: Any) -> bool:
    from app.services.dependents import code_asset_dependents, count

    deps = await code_asset_dependents(db, subject.tenant_id, a.id, a.name)
    return bool(count(deps)) or await _shared(db, "code_asset", a.id)


async def _ml_model_in_use(db: AsyncSession, subject: Subject, m: Any) -> bool:
    from app.services.dependents import _agents_mentioning
    from models.ml_model import DeploymentStatus, MLModelDeployment

    live = (
        await db.execute(
            select(MLModelDeployment.id)
            .where(
                MLModelDeployment.model_id == m.id,
                MLModelDeployment.status.in_(
                    [DeploymentStatus.DEPLOYING, DeploymentStatus.RUNNING]
                ),
            )
            .limit(1)
        )
    ).first()
    if live is not None:
        return True
    if await _agents_mentioning(db, subject.tenant_id, [str(m.id)], None):
        return True
    return await _shared(db, "ml_model", m.id)


async def _purge_owned_uploads(db: AsyncSession, subject: Subject) -> int:
    """Code asset archives and ML model files the user uploaded, unless something still uses them."""
    from models.code_asset import CodeAsset, CodeAssetStatus
    from models.ml_model import MLModel, MLModelStatus

    removed = kept = 0
    assets = (
        (
            await db.execute(
                select(CodeAsset).where(
                    CodeAsset.tenant_id == subject.tenant_id,
                    CodeAsset.created_by == subject.user_id,
                    CodeAsset.status != CodeAssetStatus.DELETED,
                )
            )
        )
        .scalars()
        .all()
    )
    for a in assets:
        if await _code_asset_in_use(db, subject, a):
            kept += 1
            continue
        paths = {a.storage_uri} | {
            h.get("storage_uri")
            for h in (a.version_history or [])
            if isinstance(h, dict)
        }
        for p in sorted(p for p in paths if p):
            removed += int(await _remove_file(p))
        a.status = CodeAssetStatus.DELETED
        a.storage_uri = None
        a.version_history = None
    models = (
        (
            await db.execute(
                select(MLModel).where(
                    MLModel.tenant_id == subject.tenant_id,
                    MLModel.created_by == subject.user_id,
                    MLModel.status != MLModelStatus.DELETED,
                )
            )
        )
        .scalars()
        .all()
    )
    for m in models:
        if await _ml_model_in_use(db, subject, m):
            kept += 1
            continue
        if m.file_uri:
            removed += int(await _remove_file(m.file_uri))
        m.status = MLModelStatus.DELETED
    await db.commit()
    if kept:
        logger.info(
            "gdpr blob purge kept %d uploads still used by agents or shared", kept
        )
    return removed


async def _purge_user_namespace(subject: Subject) -> int:
    """Files written under the user's own prefix in the tenant's storage namespace."""
    from engine.storage import get_storage

    storage = get_storage()
    removed = 0
    for f in await storage.list_files(
        str(subject.tenant_id), f"users/{subject.user_id}/"
    ):
        uri = f.get("uri")
        if uri and await storage.delete(uri):
            removed += 1
    return removed


async def _purge_voice_clone(db: AsyncSession, subject: Subject) -> int:
    """The cloned voice held by the voice provider, then the user's link to it."""
    row = (
        await db.execute(
            text(
                "SELECT voice_id, voice_provider FROM users "
                "WHERE id = :uid AND tenant_id = :t"
            ),
            {"uid": str(subject.user_id), "t": str(subject.tenant_id)},
        )
    ).first()
    if row is None or not row[0]:
        return 0
    voice_id, provider = str(row[0]), (row[1] or "").lower()
    if provider == "elevenlabs":
        from engine.tools._voice_clone import elevenlabs_delete_voice

        if not await elevenlabs_delete_voice(voice_id=voice_id):
            raise RuntimeError(
                f"could not delete cloned voice {voice_id} at ElevenLabs, "
                "check ELEVENLABS_API_KEY and retry the purge"
            )
    await db.execute(
        text(
            "UPDATE users SET voice_id = NULL, voice_provider = NULL, "
            "voice_consent_at = NULL WHERE id = :uid"
        ),
        {"uid": str(subject.user_id)},
    )
    await db.commit()
    return 1


async def _purge_blob(db: AsyncSession, subject: Subject) -> int:
    removed = await _purge_owned_uploads(db, subject)
    removed += await _purge_user_namespace(subject)
    return removed + await _purge_voice_clone(db, subject)


def _trajectory_roots() -> list[Path]:
    roots = [
        os.environ.get("TRAJECTORY_DIR") or "/data/trajectories",
        os.environ.get("WINGMAN_TRAJECTORY_DIR") or "/data/wingman-trajectories",
    ]
    return [Path(r) for r in dict.fromkeys(roots)]


def _delete_trajectory_files(
    folders: list[Path], user_id: str, execution_ids: set[str]
) -> int:
    removed = 0
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.glob("*.json"):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(entry, dict):
                continue
            owner = str(entry.get("user_id") or entry.get("created_by") or "")
            if (
                owner != user_id
                and str(entry.get("execution_id") or "") not in execution_ids
            ):
                continue
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                pass
    return removed


async def _purge_trajectory(db: AsyncSession, subject: Subject) -> int:
    """Trajectory records written from the person's runs, matched by user or execution id."""
    execution_ids = {
        str(r[0])
        for r in (
            await db.execute(
                text(
                    "SELECT id FROM executions WHERE user_id = :uid AND tenant_id = :t"
                ),
                {"uid": str(subject.user_id), "t": str(subject.tenant_id)},
            )
        ).all()
    }
    folders = [
        root / name
        for root in _trajectory_roots()
        for name in (str(subject.tenant_id), "shared")
    ]
    return await asyncio.to_thread(
        _delete_trajectory_files, folders, str(subject.user_id), execution_ids
    )


_PURGERS = {
    "postgres": _purge_postgres,
    "pinecone": _purge_pinecone,
    "neo4j": _purge_neo4j,
    "blob": _purge_blob,
    "trajectory": _purge_trajectory,
}


async def purge_user(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    subject_user_id: uuid.UUID,
    requested_by: uuid.UUID | None = None,
) -> dict[str, dict]:
    subject = await load_subject(db, tenant_id, subject_user_id, requested_by)
    receipt: dict[str, dict] = {}
    for store in STORES:
        purger = _PURGERS[store]
        await _log_store(db, subject, store, "started")
        try:
            count = await purger(db, subject)
            await _log_store(db, subject, store, "completed", affected=count)
            receipt[store] = {"status": "completed", "affected": count}
        except Exception as e:
            logger.exception("gdpr purge failed for store=%s", store)
            await db.rollback()
            await _log_store(db, subject, store, "failed", error=str(e)[:1000])
            receipt[store] = {"status": "failed", "error": str(e)[:300]}
    return receipt


async def list_receipts(
    db: AsyncSession,
    subject_user_id: uuid.UUID,
    limit: int = 100,
) -> list[GDPRPurgeLog]:
    res = await db.execute(
        select(GDPRPurgeLog)
        .where(GDPRPurgeLog.subject_user_id == subject_user_id)
        .order_by(GDPRPurgeLog.attempted_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


__all__ = ["purge_user", "list_receipts", "load_subject", "STORES"]
