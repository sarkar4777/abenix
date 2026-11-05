"""Keep a knowledge collection in step with an external source, in resumable slices.

The connector lists pages, this engine does the rest. Each page commits its
cursor with its results, so a crash resumes at the page in hand and a fetch
that fails stays due for the next pass. A full listing finds deletes by what a
finished pass did not see, a delta feed reports them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from worker.celery_app import celery_app
from worker.tasks import document_processor as dp
from worker.tasks import kb_delete, kb_quota

logger = logging.getLogger(__name__)

TASK_NAME = "worker.tasks.kb_connector_sync.run"
SLICE_SECONDS = int(os.environ.get("KB_CONNECTOR_SLICE_SECONDS", "600"))
# the document queue may hold this many of a source's files before listing waits
MAX_BACKLOG = int(os.environ.get("KB_CONNECTOR_MAX_BACKLOG", "500"))
MAX_ITEM_BYTES = int(os.environ.get("KB_CONNECTOR_MAX_ITEM_BYTES", str(200 * 1024**2)))
# more than this share gone in one pass stops and asks, usually a wrong prefix
MAX_DELETE_FRACTION = float(os.environ.get("KB_CONNECTOR_MAX_DELETE_FRACTION", "0.5"))
DELETE_BATCH = 200
MAX_ITEM_FAILURES = 5
FILE_TYPES = {"pdf", "docx", "txt", "csv", "md", "json"}
_LISTED = ", ".join(sorted(FILE_TYPES))
_ARCHIVES = {"zip", "tar", "tgz", "gz", "bz2", "xz", "7z", "rar"}


class _Stop(Exception):
    """End this slice in the given state, the cursor stays for later."""

    def __init__(self, status: str, message: str | None = None) -> None:
        super().__init__(message or status)
        self.status = status
        self.message = message


def _load_secrets(cur: Any, tenant_id: str, key: str | None) -> dict[str, str]:
    if not key:
        return {}
    from engine import credentials

    cur.execute(
        "SELECT value FROM tenant_tool_credentials WHERE tenant_id = %s AND key = %s",
        (tenant_id, key),
    )
    row = cur.fetchone()
    if not row:
        return {}
    return json.loads(credentials.decode_stored(row[0]) or "{}")


class _Sync:
    def __init__(
        self,
        conn: Any,
        source: dict[str, Any],
        kb: dict[str, Any],
        connector: Any,
        loop: asyncio.AbstractEventLoop,
        dispatch: Callable[..., None],
    ) -> None:
        self.conn = conn
        self.cur = conn.cursor()
        self.source = source
        self.kb = kb
        self.connector = connector
        self.loop = loop
        self.dispatch = dispatch
        self.id = source["id"]
        self.kb_id = source["kb_id"]
        self.counts = dict.fromkeys(
            ("seen", "ingested", "updated", "deleted", "failed", "skipped"), 0
        )

    def _flush(self, **columns: Any) -> None:
        """Counters and cursor in one commit with what they describe."""
        sets = [f"items_{k} = items_{k} + %s" for k in self.counts]
        values: list[Any] = list(self.counts.values())
        sets += ["heartbeat_at = now()", "updated_at = now()"]
        for k, v in columns.items():
            sets.append(f"{k} = %s")
            values.append(
                json.dumps(v) if k.endswith("_cursor") and v is not None else v
            )
        self.cur.execute(
            f"UPDATE kb_connector_sources SET {', '.join(sets)} WHERE id = %s",
            (*values, self.id),
        )
        self.conn.commit()
        self.counts = dict.fromkeys(self.counts, 0)

    def _item_row(self, external_id: str) -> dict[str, Any] | None:
        self.cur.execute(
            "SELECT id::text, version, document_id::text, status, acl FROM "
            "kb_connector_items WHERE source_id = %s AND external_id = %s",
            (self.id, external_id),
        )
        row = self.cur.fetchone()
        if not row:
            return None
        return dict(zip(("id", "version", "document_id", "status", "acl"), row))

    def _record(
        self,
        item: Any,
        status: str,
        error: str | None = None,
        document_id: str | None = None,
        version: str | None = None,
        keep_version: bool = False,
    ) -> None:
        self.cur.execute(
            "INSERT INTO kb_connector_items (id, source_id, external_id, name, version, "
            "document_id, size_bytes, modified_at, acl, status, error, failures, "
            "last_seen_run) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, "
            "%s, %s) ON CONFLICT (source_id, external_id) DO UPDATE SET "
            "name = EXCLUDED.name, size_bytes = EXCLUDED.size_bytes, "
            "modified_at = EXCLUDED.modified_at, acl = EXCLUDED.acl, "
            "status = EXCLUDED.status, error = EXCLUDED.error, "
            "last_seen_run = EXCLUDED.last_seen_run, updated_at = now(), "
            "failures = CASE WHEN EXCLUDED.status = 'failed' "
            "THEN kb_connector_items.failures + 1 ELSE 0 END, "
            "document_id = COALESCE(EXCLUDED.document_id, kb_connector_items.document_id), "
            + (
                "version = kb_connector_items.version"
                if keep_version
                else "version = EXCLUDED.version"
            ),
            (
                str(uuid.uuid4()),
                self.id,
                item.external_id,
                (item.name or "")[:500],
                None if keep_version else version,
                document_id,
                item.size,
                item.modified_at,
                json.dumps(item.acl) if item.acl is not None else None,
                status,
                error,
                1 if status == "failed" else 0,
                self.source["run_id"],
            ),
        )

    def _apply_acl(self, document_id: str, acl: dict[str, Any] | None) -> None:
        """Restricted at the source stays restricted here, an unmapped group means nobody."""
        if acl is None or acl.get("public") is None:
            return
        self.cur.execute(
            "DELETE FROM document_grants WHERE document_id = %s", (document_id,)
        )
        if acl.get("public") is True:
            return
        emails = sorted(
            {
                str(p["email"]).strip().lower()
                for p in acl.get("principals") or []
                if p.get("email")
            }
        )
        subjects = set()
        if emails:
            self.cur.execute(
                "SELECT id::text FROM users WHERE tenant_id = %s AND lower(email) = ANY(%s)",
                (self.source["tenant_id"], emails),
            )
            subjects = {r[0] for r in self.cur.fetchall()}
        if self.source.get("created_by"):
            subjects.add(self.source["created_by"])
        # one grant keeps the document restricted, no grant at all would open it to everyone
        if not subjects:
            subjects.add(str(uuid.UUID(int=0)))
        for subject in sorted(subjects):
            self.cur.execute(
                "INSERT INTO document_grants (id, document_id, tenant_id, subject_type, "
                "subject_id, permission, granted_by) VALUES (%s, %s, %s, 'user', %s, "
                "'read', %s) ON CONFLICT DO NOTHING",
                (
                    str(uuid.uuid4()),
                    document_id,
                    self.source["tenant_id"],
                    subject,
                    self.source.get("created_by"),
                ),
            )

    def _skip(self, item: Any, reason: str) -> None:
        self._record(item, "skipped", reason, version=item.version)
        self.counts["skipped"] += 1

    def _check_quota(self, item: Any, existing: dict | None) -> None:
        import knowledge_quota as kq

        try:
            kb_quota.enforce(
                self.cur,
                self.source["tenant_id"],
                add_documents=0 if existing and existing["document_id"] else 1,
                add_bytes=int(item.size or 0),
            )
        except kq.KnowledgeQuotaExceeded as e:
            self.conn.rollback()
            raise _Stop("quota_exceeded", e.message) from e

    def _store(self, doc_id: str, ext: str, data: bytes) -> str:
        from engine.storage import get_storage

        return self.loop.run_until_complete(
            get_storage().upload(
                tenant_id=self.source["tenant_id"],
                path=f"kb/{self.kb_id}/{doc_id}-{uuid.uuid4().hex[:8]}.{ext}",
                data=data,
                content_type="application/octet-stream",
            )
        )

    def _check_container(self, ext: str, data: bytes) -> None:
        if ext != "docx":
            return
        from engine.archive_guard import check_zip

        with tempfile.NamedTemporaryFile(suffix=".docx") as fh:
            fh.write(data)
            fh.flush()
            check_zip(fh.name, "This document")

    def handle_item(self, item: Any) -> None:
        from engine.archive_guard import UnsafeArchive
        from engine.kb_connectors.base import AuthError, ConnectorError, TooLarge

        self.counts["seen"] += 1
        existing = self._item_row(item.external_id)
        unchanged = (
            existing
            and existing["version"] == item.version
            and item.version is not None
            and existing["status"] in ("ok", "skipped")
        )
        if unchanged:
            self.cur.execute(
                "UPDATE kb_connector_items SET last_seen_run = %s, acl = %s::jsonb "
                "WHERE id = %s",
                (
                    self.source["run_id"],
                    json.dumps(item.acl) if item.acl is not None else None,
                    existing["id"],
                ),
            )
            # permissions can change while the file does not
            if existing["document_id"] and existing["acl"] != item.acl:
                self._apply_acl(existing["document_id"], item.acl)
            return
        ext = Path(item.name or "").suffix.lower().lstrip(".")
        if ext in _ARCHIVES:
            self._skip(item, "Archives are not ingested, unpack it at the source.")
            return
        if ext not in FILE_TYPES:
            self._skip(
                item,
                f"The .{ext or 'unknown'} type is not ingested. Allowed: {_LISTED}.",
            )
            return
        if item.size is not None and item.size > MAX_ITEM_BYTES:
            self._skip(item, f"It is larger than the limit of {MAX_ITEM_BYTES} bytes.")
            return
        self._check_quota(item, existing)
        try:
            data = self.loop.run_until_complete(
                self.connector.fetch(item, MAX_ITEM_BYTES)
            )
        except TooLarge as e:
            self._skip(item, str(e))
            return
        except AuthError:
            raise
        except ConnectorError as e:
            self._record(item, "failed", str(e)[:500], keep_version=True)
            self.counts["failed"] += 1
            logger.info(
                "connector %s: fetch failed for %s: %s", self.id, item.external_id, e
            )
            return
        if not data:
            self._skip(item, "The file is empty.")
            return
        try:
            self._check_container(ext, data)
        except UnsafeArchive as e:
            self._skip(item, str(e))
            return
        doc_id = (existing or {}).get("document_id") or str(uuid.uuid4())
        is_update = bool(existing and existing["document_id"])
        url = self._store(doc_id, ext, data)
        old_url = None
        if is_update:
            self.cur.execute(
                "SELECT storage_url FROM documents WHERE id = %s", (doc_id,)
            )
            row = self.cur.fetchone()
            old_url = row[0] if row else None
            self.cur.execute(
                "UPDATE documents SET storage_url = %s, filename = %s, file_type = %s, "
                "file_size = %s, status = 'PROCESSING', error_message = NULL, "
                "cognified_at = NULL, ingest_checkpoint = 0, ingest_attempts = 0, "
                "ingest_fingerprint = NULL, content_sha256 = NULL WHERE id = %s",
                (url, (item.name or "")[:500], ext, len(data), doc_id),
            )
        if not is_update or old_url is None:
            is_update = False
            self.cur.execute(
                "INSERT INTO documents (id, kb_id, filename, file_type, file_size, "
                "chunk_count, status, storage_url, version_number, is_current) "
                "VALUES (%s, %s, %s, %s, %s, 0, 'PROCESSING', %s, 1, true) "
                "ON CONFLICT (id) DO NOTHING",
                (doc_id, self.kb_id, (item.name or "")[:500], ext, len(data), url),
            )
        self._apply_acl(doc_id, item.acl)
        self._record(item, "ok", None, document_id=doc_id, version=item.version)
        self.conn.commit()
        self.dispatch(
            doc_id,
            self.kb_id,
            url,
            item.name,
            ext,
            self.kb["chunk_size"] or 1000,
            self.kb["chunk_overlap"] or 200,
        )
        if old_url and old_url != url:
            kb_delete.remove_file(old_url)
        self.counts["updated" if is_update else "ingested"] += 1

    def delete_items(self, rows: list[tuple[str, str | None]]) -> None:
        """(item id, document id). Vectors and the file go first, a retry finds them gone."""
        docs = [d for _i, d in rows if d]
        if docs:
            self.cur.execute(
                "SELECT id::text, storage_url, chunk_count FROM documents "
                "WHERE id = ANY(%s::uuid[])",
                (docs,),
            )
            found = self.cur.fetchall()
            targets = kb_delete.live_target_generations(self.cur, self.kb_id)
            for doc_id, url, count in found:
                kb_delete.remove_document_vectors(
                    self.kb_id,
                    doc_id,
                    count or 0,
                    self.kb["generation"],
                    self.kb["backend"],
                    also=targets,
                )
                kb_delete.remove_file(url or "")
            kb_delete.delete_document_rows(self.cur, self.kb_id, docs)
        self.cur.execute(
            "DELETE FROM kb_connector_items WHERE id = ANY(%s::uuid[])",
            ([i for i, _d in rows],),
        )
        self.counts["deleted"] += len(rows)
        self._flush()

    def delete_by_external(self, external_ids: list[str]) -> None:
        if not external_ids:
            return
        self.cur.execute(
            "SELECT id::text, document_id::text FROM kb_connector_items "
            "WHERE source_id = %s AND external_id = ANY(%s)",
            (self.id, external_ids),
        )
        rows = self.cur.fetchall()
        if rows:
            self.delete_items(rows)

    def _gone_query(self) -> tuple[int, int]:
        self.cur.execute(
            "SELECT count(*), count(*) FILTER (WHERE last_seen_run IS DISTINCT FROM %s) "
            "FROM kb_connector_items WHERE source_id = %s",
            (self.source["run_id"], self.id),
        )
        return self.cur.fetchone()

    def sweep_missing(self, deadline: float) -> bool:
        """True when finished. A pass that would remove most of the source asks first."""
        known, gone = self._gone_query()
        if (
            gone
            and not self.source["confirm_deletes"]
            and (gone == known or (known >= 10 and gone / known > MAX_DELETE_FRACTION))
        ):
            self.conn.rollback()
            raise _Stop(
                "needs_confirmation",
                f"This pass did not find {gone} of {known} known items, so nothing was "
                "deleted. Check the source settings. If they really are gone, press "
                "Sync and confirm the deletes.",
            )
        while True:
            self.cur.execute(
                "SELECT id::text, document_id::text FROM kb_connector_items "
                "WHERE source_id = %s AND last_seen_run IS DISTINCT FROM %s LIMIT %s",
                (self.id, self.source["run_id"], DELETE_BATCH),
            )
            rows = self.cur.fetchall()
            if not rows:
                return True
            self.delete_items(rows)
            if time.monotonic() >= deadline:
                return False

    def backlog(self) -> int:
        self.cur.execute(
            "SELECT count(*) FROM documents WHERE kb_id = %s AND status = 'PROCESSING'",
            (self.kb_id,),
        )
        return self.cur.fetchone()[0]

    def requested_status(self) -> tuple[str, bool]:
        self.cur.execute(
            "SELECT status, active FROM kb_connector_sources WHERE id = %s", (self.id,)
        )
        row = self.cur.fetchone()
        self.conn.commit()
        return (row[0], row[1]) if row else ("deleted", False)

    def run_pages(self, deadline: float) -> str:
        """Returns finished, or continuing when the slice or the backlog says stop."""
        from engine.kb_connectors.base import AuthError, ConnectorError, with_retries

        cursor = self.source["page_cursor"]
        sync_cursor = self.source["sync_cursor"]
        if (cursor or {}).get("__sweeping__"):
            done = self.sweep_missing(deadline)
            return "finished" if done else "continuing"
        while True:
            status, _active = self.requested_status()
            if status == "pausing":
                raise _Stop("paused")
            if status == "deleted":
                raise _Stop("deleted")
            if self.backlog() > MAX_BACKLOG:
                self.conn.commit()
                return "backlog"
            self.conn.commit()

            async def page_call() -> Any:
                return await self.connector.list_page(cursor, sync_cursor)

            try:
                page = self.loop.run_until_complete(with_retries(page_call))
            except (AuthError, ConnectorError):
                raise
            for item in page.items:
                self.handle_item(item)
            if page.seen:
                self.cur.execute(
                    "UPDATE kb_connector_items SET last_seen_run = %s "
                    "WHERE source_id = %s AND external_id = ANY(%s)",
                    (self.source["run_id"], self.id, page.seen),
                )
                self.counts["seen"] += len(page.seen)
            if page.deleted:
                self.delete_by_external(page.deleted)
            if page.finished:
                self.source["new_sync_cursor"] = page.sync_cursor
                if not self.connector.complete_listing:
                    # a delta feed never lists a failed file again, so stay on the old token
                    self.cur.execute(
                        "SELECT count(*) FROM kb_connector_items WHERE source_id = %s "
                        "AND status = 'failed' AND failures < %s",
                        (self.id, MAX_ITEM_FAILURES),
                    )
                    if self.cur.fetchone()[0]:
                        self.source["new_sync_cursor"] = None
                    self._flush(page_cursor=None)
                    return "finished"
                cursor = {"__sweeping__": True}
                self._flush(
                    page_cursor=cursor, sync_cursor=page.sync_cursor or sync_cursor
                )
                done = self.sweep_missing(deadline)
                return "finished" if done else "continuing"
            cursor = page.next_cursor
            self._flush(page_cursor=cursor)
            if time.monotonic() >= deadline:
                return "continuing"


def _again(source_id: str, countdown: int = 0) -> None:
    celery_app.send_task(
        TASK_NAME,
        kwargs={"source_id": source_id},
        queue="documents",
        countdown=countdown,
    )


def _dispatch_document(*args: Any) -> None:
    celery_app.send_task(
        "worker.tasks.document_processor.process_document",
        args=list(args),
        queue="documents",
    )


_SOURCE_COLUMNS = (
    "id::text",
    "tenant_id::text",
    "kb_id::text",
    "kind",
    "config",
    "credential_key",
    "cadence_minutes",
    "active",
    "status",
    "run_id::text",
    "page_cursor",
    "sync_cursor",
    "confirm_deletes",
    "created_by::text",
    "consecutive_failures",
)
_SOURCE_KEYS = (
    "id",
    "tenant_id",
    "kb_id",
    "kind",
    "config",
    "credential_key",
    "cadence_minutes",
    "active",
    "status",
    "run_id",
    "page_cursor",
    "sync_cursor",
    "confirm_deletes",
    "created_by",
    "consecutive_failures",
)


def _finish(
    cur: Any, conn: Any, source: dict[str, Any], status: str, error: str | None
) -> None:
    failures = (
        (source.get("consecutive_failures") or 0) + 1 if status == "failed" else 0
    )
    # a source that keeps failing backs off instead of hammering, up to a day
    delay = (
        source["cadence_minutes"]
        if status != "failed"
        else min(source["cadence_minutes"] * 2 ** min(failures, 6), 1440)
    )
    cur.execute(
        "UPDATE kb_connector_sources SET status = %s, last_error = %s, run_id = NULL, "
        "page_cursor = NULL, confirm_deletes = false, consecutive_failures = %s, "
        "last_finished_at = now(), heartbeat_at = now(), updated_at = now(), "
        "next_sync_at = now() + make_interval(mins => %s) WHERE id = %s",
        (status, error, failures, delay, source["id"]),
    )
    conn.commit()


def sync_slice(
    source_id: str,
    slice_seconds: float | None = None,
    requeue: Callable[..., None] = _again,
    dispatch: Callable[..., None] = _dispatch_document,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import psycopg2

    url = dp._sync_db_url()
    lock_conn = psycopg2.connect(url)
    lock_conn.autocommit = True
    conn = psycopg2.connect(url)
    loop = asyncio.new_event_loop()
    connector = None
    deadline = time.monotonic() + (
        SLICE_SECONDS if slice_seconds is None else slice_seconds
    )
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {', '.join(_SOURCE_COLUMNS)} FROM kb_connector_sources WHERE id = %s",
            (source_id,),
        )
        row = cur.fetchone()
        if row is None:
            return {"status": "missing", "source_id": source_id}
        source = dict(zip(_SOURCE_KEYS, row))
        with lock_conn.cursor() as lc:
            lc.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s))",
                (f"kb_connector:{source_id}",),
            )
            if not lc.fetchone()[0]:
                return {"status": "skipped", "source_id": source_id}
        if source["status"] == "paused":
            return {"status": "paused", "source_id": source_id}
        cur.execute(
            "SELECT chunk_size, chunk_overlap, embedding_generation, vector_backend, "
            "deleted_at FROM knowledge_collections WHERE id = %s",
            (source["kb_id"],),
        )
        k = cur.fetchone()
        if k is None or k[4] is not None:
            return {"status": "deleted", "source_id": source_id}
        kb = {
            "chunk_size": k[0],
            "chunk_overlap": k[1],
            "generation": k[2] or 0,
            "backend": k[3] or "pinecone",
        }
        if not source["run_id"]:
            source["run_id"] = str(uuid.uuid4())
            source["page_cursor"] = None
            cur.execute(
                "UPDATE kb_connector_sources SET run_id = %s, page_cursor = NULL, "
                "last_started_at = now(), items_seen = 0, items_ingested = 0, "
                "items_updated = 0, items_deleted = 0, items_failed = 0, "
                "items_skipped = 0 WHERE id = %s",
                (source["run_id"], source_id),
            )
        cur.execute(
            "UPDATE kb_connector_sources SET status = 'running', last_error = NULL, "
            "heartbeat_at = now() WHERE id = %s AND status <> 'pausing'",
            (source_id,),
        )
        conn.commit()

        from engine.kb_connectors import build

        secrets = _load_secrets(cur, source["tenant_id"], source["credential_key"])
        conn.commit()
        connector = build(source["kind"], source["config"], secrets, **(options or {}))
        loop.run_until_complete(connector.validate())
        engine = _Sync(conn, source, kb, connector, loop, dispatch)
        try:
            outcome = engine.run_pages(deadline)
        except _Stop as stop:
            conn.rollback()
            if stop.status == "paused":
                cur.execute(
                    "UPDATE kb_connector_sources SET status = 'paused', updated_at = now() "
                    "WHERE id = %s",
                    (source_id,),
                )
                conn.commit()
                engine._flush()
                return {"status": "paused", "source_id": source_id}
            if stop.status == "deleted":
                return {"status": "deleted", "source_id": source_id}
            engine._flush()
            _finish(cur, conn, source, stop.status, stop.message)
            return {
                "status": stop.status,
                "source_id": source_id,
                "error": stop.message,
            }
        if outcome == "backlog":
            engine._flush()
            requeue(source_id, countdown=60)
            return {"status": "waiting", "source_id": source_id}
        if outcome == "continuing":
            engine._flush()
            requeue(source_id)
            return {"status": "continuing", "source_id": source_id}
        engine._flush(
            sync_cursor=source.get("new_sync_cursor") or source.get("sync_cursor")
        )
        _finish(cur, conn, source, "idle", None)
        return {"status": "idle", "source_id": source_id}
    except Exception as e:
        conn.rollback()
        logger.warning("connector %s failed: %s", source_id, e)
        with conn.cursor() as c2:
            c2.execute(
                "SELECT consecutive_failures, cadence_minutes FROM kb_connector_sources "
                "WHERE id = %s",
                (source_id,),
            )
            row = c2.fetchone()
            if row:
                # the run and its cursor stay, the next attempt carries on from them
                failures = (row[0] or 0) + 1
                c2.execute(
                    "UPDATE kb_connector_sources SET status = 'failed', last_error = %s, "
                    "consecutive_failures = %s, heartbeat_at = now(), updated_at = now(), "
                    "next_sync_at = now() + make_interval(mins => %s) WHERE id = %s",
                    (
                        str(e)[:1000],
                        failures,
                        min((row[1] or 60) * 2 ** min(failures, 6), 1440),
                        source_id,
                    ),
                )
        conn.commit()
        return {"status": "failed", "source_id": source_id, "error": str(e)}
    finally:
        if connector is not None:
            try:
                loop.run_until_complete(connector.aclose())
            except Exception:
                pass
        loop.close()
        conn.close()
        lock_conn.close()


@celery_app.task(
    name=TASK_NAME,
    bind=True,
    max_retries=0,
    soft_time_limit=int(os.environ.get("KB_CONNECTOR_SOFT_LIMIT", "1500")),
    time_limit=int(os.environ.get("KB_CONNECTOR_TIME_LIMIT", "1800")),
)
def run(self: Any, *, source_id: str) -> dict:
    return sync_slice(source_id)


__all__ = ["run", "sync_slice", "TASK_NAME"]
