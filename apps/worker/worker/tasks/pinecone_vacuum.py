"""Pinecone vacuum: delete vectors no live Postgres row accounts for.

Enqueued daily by the API scheduler (one replica, advisory lock). Removes:
  - every vector in a namespace whose knowledge collection no longer exists
  - the stale tail of a document, ids `<doc>_<i>` with i >= its chunk_count
    (left behind when a re-processed document shrank)
  - persona vectors `<item>:<i>` whose persona item is gone or soft-deleted,
    or that the item no longer lists in pinecone_ids

Vectors whose document id has no row are kept: knowledge_store writes
vectors without a documents row, so absence proves nothing. Namespaces in
any other shape are left alone.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Iterable

from worker.celery_app import celery_app
from worker.tasks import document_processor as dp

from engine.knowledge.kb_state import parse_namespace

logger = logging.getLogger(__name__)

DELETE_BATCH = 1000
_DOC_VEC = re.compile(r"^([0-9a-fA-F-]{36})_(\d+)$")


def _is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False


def _namespaces(index: Any) -> list[str]:
    stats = index.describe_index_stats()
    ns = getattr(stats, "namespaces", None)
    if ns is None and isinstance(stats, dict):
        ns = stats.get("namespaces")
    return list((ns or {}).keys())


def _list_ids(index: Any, namespace: str) -> Iterable[str]:
    for page in index.list(namespace=namespace):
        if isinstance(page, (list, tuple)):
            yield from page
        else:
            yield page


def doc_orphans(ids: Iterable[str], docs: dict[str, tuple[int, str]]) -> list[str]:
    """Ids past their document's chunk_count. docs: id -> (chunk_count, status)."""
    out = []
    for vid in ids:
        m = _DOC_VEC.match(vid)
        if not m:
            continue
        doc = docs.get(m.group(1).lower())
        if doc is None:
            continue
        count, status = doc
        if status == "PROCESSING":
            continue
        if int(m.group(2)) >= count:
            out.append(vid)
    return out


def persona_orphans(
    ids: Iterable[str], items: dict[str, tuple[bool, set[str]]]
) -> list[str]:
    """items: item id -> (deleted, pinecone_ids)."""
    out = []
    for vid in ids:
        item_id = vid.split(":", 1)[0].lower()
        item = items.get(item_id)
        if item is None or item[0]:
            out.append(vid)
        elif item[1] and vid not in item[1]:
            out.append(vid)
    return out


def _load_state(
    cur: Any,
) -> tuple[
    dict[str, tuple[int, bool]],
    dict[str, dict[str, tuple[int, str]]],
    dict[str, tuple[bool, set[str]]],
]:
    # a re-embed writes past each document's count until its flip, leave those alone
    cur.execute(
        "SELECT k.id::text, k.embedding_generation, EXISTS (SELECT 1 FROM "
        "kb_reembed_jobs j WHERE j.kb_id = k.id AND j.status NOT IN "
        "('completed', 'cancelled', 'failed')) FROM knowledge_collections k"
    )
    kbs = {}
    for kb_id, generation, busy in cur.fetchall():
        kbs[kb_id.lower()] = (generation or 0, bool(busy))
    cur.execute(
        "SELECT kb_id::text, id::text, chunk_count, status::text FROM documents"
    )
    docs: dict[str, dict[str, tuple[int, str]]] = {}
    for kb_id, doc_id, count, status in cur.fetchall():
        docs.setdefault(kb_id.lower(), {})[doc_id.lower()] = (count or 0, status or "")
    cur.execute(
        "SELECT id::text, deleted_at IS NOT NULL, pinecone_ids FROM persona_items"
    )
    items = {r[0].lower(): (bool(r[1]), set(r[2] or [])) for r in cur.fetchall()}
    return kbs, docs, items


def _delete(index: Any, namespace: str, ids: list[str]) -> int:
    for i in range(0, len(ids), DELETE_BATCH):
        index.delete(ids=ids[i : i + DELETE_BATCH], namespace=namespace)
    return len(ids)


def vacuum(index: Any, cur: Any) -> dict[str, Any]:
    kbs, docs, items = _load_state(cur)
    deleted = 0
    scanned = 0
    dropped_namespaces = 0
    unlistable: list[str] = []
    for ns in _namespaces(index):
        if ns.startswith("persona:"):
            try:
                orphans = persona_orphans(_list_ids(index, ns), items)
            except Exception as e:
                unlistable.append(ns)
                logger.warning("vacuum: cannot list %s: %s", ns, e)
                continue
            scanned += 1
            deleted += _delete(index, ns, orphans)
        elif _is_uuid(parse_namespace(ns)[0]):
            scanned += 1
            kb_id, generation = parse_namespace(ns)
            kb = kbs.get(kb_id.lower())
            if kb is None:
                index.delete(delete_all=True, namespace=ns)
                dropped_namespaces += 1
                continue
            if kb[1]:
                continue
            if generation != kb[0]:
                index.delete(delete_all=True, namespace=ns)
                dropped_namespaces += 1
                continue
            try:
                orphans = doc_orphans(_list_ids(index, ns), docs.get(kb_id.lower(), {}))
            except Exception as e:
                unlistable.append(ns)
                logger.warning("vacuum: cannot list %s: %s", ns, e)
                continue
            deleted += _delete(index, ns, orphans)
    return {
        "status": "ok",
        "deleted": deleted,
        "namespaces": scanned,
        "namespaces_dropped": dropped_namespaces,
        "unlistable": unlistable,
    }


@celery_app.task(name="worker.tasks.pinecone_vacuum.run", bind=True, max_retries=0)
def run(self: Any) -> dict:
    if not dp.PINECONE_API_KEY:
        return {"status": "skipped", "reason": "PINECONE_API_KEY not set"}
    import psycopg2
    from pinecone import Pinecone

    index = Pinecone(api_key=dp.PINECONE_API_KEY).Index(dp.PINECONE_INDEX_NAME)
    conn = psycopg2.connect(dp._sync_db_url())
    try:
        with conn.cursor() as cur:
            result = vacuum(index, cur)
    finally:
        conn.close()
    logger.info("pinecone_vacuum %s", result)
    return result


@celery_app.task(name="worker.tasks.pinecone_vacuum.stamp_superseded", max_retries=0)
def stamp_superseded(
    kb_id: str, doc_id: str, chunk_count: int, generation: int = 0
) -> dict:
    """Search filters on this flag, so its $nin list does not grow with every replaced file."""
    if not dp.PINECONE_API_KEY:
        return {"status": "skipped", "reason": "PINECONE_API_KEY not set"}
    from engine.knowledge.kb_state import pinecone_namespace
    from pinecone import Pinecone

    index = Pinecone(api_key=dp.PINECONE_API_KEY).Index(dp.PINECONE_INDEX_NAME)
    namespace = pinecone_namespace(kb_id, generation)
    for i in range(chunk_count):
        index.update(
            id=f"{doc_id}_{i}", set_metadata={"superseded": True}, namespace=namespace
        )
    return {"status": "ok", "stamped": chunk_count}


__all__ = ["run", "stamp_superseded", "vacuum", "doc_orphans", "persona_orphans"]
