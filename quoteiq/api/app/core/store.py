"""The QuoteIQ email store.

Postgres when DATABASE_URL is set, otherwise an in-memory dict so the app
runs from a clone with no infrastructure. Same split the other standalone
apps use. One record per example email holds everything the app knows about
it: status, the run, the lines, every draft and its review, and the history.

Nothing here talks to Abenix.

Background work (a pipeline run, a redraft) carries a job token. Retry and
reset replace the record's token, so a run that finishes after them can't
write over what replaced it.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

logger = logging.getLogger("quoteiq.store")

STATUSES = ("success", "clarification", "escalated", "system_error")
PROCESSED = set(STATUSES)
# The fields of an email as received, from its file.
RECEIVED_FIELDS = ("id", "from_name", "from_email", "subject", "received_text")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_job() -> str:
    return uuid.uuid4().hex


class StaleJob(Exception):
    """The record moved on (retry or reset) since this job started."""


def blank_record(email: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: email[k] for k in RECEIVED_FIELDS},
        "status": "waiting",
        "review": None,
        "error_step": None,
        "error": None,
        "job": None,
        "run": None,
        "redraft": None,
        "processed_at": None,
        "outcome": None,
        "reason": None,
        "sender": None,
        "email_brief": None,
        "lines": [],
        "escalation": None,
        "drafts": [],
        "history": [],
    }


def add_event(record: dict[str, Any], kind: str, summary: str) -> None:
    record["history"].append({"at": now(), "type": kind, "summary": summary})


def current_draft(record: dict[str, Any]) -> dict[str, Any] | None:
    return record["drafts"][-1] if record.get("drafts") else None


def new_draft(record: dict[str, Any], kind: str, execution_id: str | None, email: dict[str, str],
              note: str | None = None) -> dict[str, Any]:
    return {
        "n": len(record["drafts"]) + 1,
        "kind": kind,
        "note": note,
        "execution_id": execution_id,
        "created_at": now(),
        "ai": email,
        "edited": None,
        "approval": None,
        "approval_error": None,
        "raises": 0,
        "decision": None,
        "sent": None,
    }


def open_approval_ids(record: dict[str, Any]) -> list[str]:
    """Approvals of this email still waiting for a decision."""
    return [
        d["approval"]["id"]
        for d in record.get("drafts") or []
        if d.get("approval") and d["approval"].get("id") and d["approval"].get("status") in {"pending", "signing"}
    ]


class EmailStore:
    """In-memory store. Swapped for the Postgres one when a URL is present."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def load(self, emails: list[dict[str, Any]]) -> None:
        """Make the store hold exactly these emails, keeping what is known about them."""
        async with self._lock:
            known = self._records
            self._records = {}
            for email in emails:
                record = known.get(email["id"]) or blank_record(email)
                record.update({k: email[k] for k in RECEIVED_FIELDS})
                self._records[email["id"]] = record
        await self._persist_all()

    # ── reads ─────────────────────────────────────────────────────────────
    async def list(self) -> list[dict[str, Any]]:
        """Every email in queue order: the order of the example files."""
        return [copy.deepcopy(self._records[k]) for k in sorted(self._records)]

    async def get(self, email_id: str) -> dict[str, Any] | None:
        record = self._records.get(email_id)
        return copy.deepcopy(record) if record else None

    async def stats(self) -> dict[str, Any]:
        records = list(self._records.values())
        by_status = {s: {"count": 0, "awaiting_review": 0} for s in STATUSES}
        for r in records:
            if r["status"] in by_status:
                by_status[r["status"]]["count"] += 1
                if r.get("review") == "awaiting_review":
                    by_status[r["status"]]["awaiting_review"] += 1
        return {
            "emails": len(records),
            "processed": sum(1 for r in records if r["status"] in PROCESSED),
            "processing": sum(1 for r in records if r["status"] == "processing"),
            "waiting": sum(1 for r in records if r["status"] == "waiting"),
            "awaiting_review": sum(1 for r in records if r.get("review") == "awaiting_review"),
            "by_status": by_status,
        }

    # ── writes ────────────────────────────────────────────────────────────
    @asynccontextmanager
    async def edit(self, email_id: str, job: str | None = None) -> AsyncIterator[dict[str, Any]]:
        """Change one record in place, under the store lock.

        With a job, the change only applies while that job is still the
        record's current one; otherwise StaleJob is raised. Never await
        anything but the store inside the block.
        """
        async with self._lock:
            record = self._records.get(email_id)
            if record is None:
                raise KeyError(email_id)
            if job is not None and record.get("job") != job:
                raise StaleJob(email_id)
            working = copy.deepcopy(record)
            yield working
            self._records[email_id] = working
        await self._persist(email_id)

    async def claim_next(self) -> dict[str, Any] | None:
        """Take the next waiting email for processing, or None when none is left."""
        async with self._lock:
            waiting = [k for k in sorted(self._records) if self._records[k]["status"] == "waiting"]
            if not waiting:
                return None
            claimed = self._claim(waiting[0])
        await self._persist(claimed["id"])
        return claimed

    async def claim(self, email_id: str) -> dict[str, Any] | None:
        """Take this email for processing; None when it isn't waiting.

        Raises KeyError for an unknown email.
        """
        async with self._lock:
            record = self._records.get(email_id)
            if record is None:
                raise KeyError(email_id)
            if record["status"] != "waiting":
                return None
            claimed = self._claim(email_id)
        await self._persist(email_id)
        return claimed

    def _claim(self, email_id: str) -> dict[str, Any]:
        record = self._records[email_id]
        record["status"] = "processing"
        record["job"] = new_job()
        add_event(record, "processing", "Sent to the RFQ pipeline")
        return copy.deepcopy(record)

    async def reset(self) -> list[str]:
        """Clear every result. Returns the approvals that were still open."""
        async with self._lock:
            open_ids = [aid for r in self._records.values() for aid in open_approval_ids(r)]
            self._records = {k: blank_record(r) for k, r in self._records.items()}
        await self._persist_all()
        return open_ids

    # ── persistence hooks (no-ops in memory) ─────────────────────────────
    async def _persist(self, email_id: str) -> None:
        return None

    async def _persist_all(self) -> None:
        return None


class PostgresEmailStore(EmailStore):
    """Same surface, persisted. Falls back to memory if the database is unreachable."""

    def __init__(self, dsn: str) -> None:
        super().__init__()
        self._dsn = dsn
        self._pool: Any = None

    async def connect(self) -> None:
        try:
            import asyncpg  # noqa: PLC0415

            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS qq_emails (
                        id          TEXT PRIMARY KEY,
                        payload     JSONB NOT NULL,
                        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                rows = await conn.fetch("SELECT id, payload FROM qq_emails")
            for row in rows:
                try:
                    payload = row["payload"]
                    self._records[row["id"]] = json.loads(payload) if isinstance(payload, str) else payload
                except Exception:  # noqa: BLE001
                    continue
        except Exception as exc:  # noqa: BLE001
            # A missing database must not stop the app booting; memory works.
            logger.warning("Postgres unavailable, keeping emails in memory: %s", exc)
            self._pool = None

    async def _persist(self, email_id: str) -> None:
        if self._pool is None:
            return
        record = self._records.get(email_id)
        if record is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO qq_emails (id, payload) VALUES ($1, $2::jsonb)
                    ON CONFLICT (id) DO UPDATE
                      SET payload = EXCLUDED.payload, updated_at = now()
                    """,
                    email_id,
                    json.dumps(record, default=str),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not save %s: %s", email_id, exc)

    async def _persist_all(self) -> None:
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM qq_emails WHERE NOT (id = ANY($1::text[]))", list(self._records)
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not prune removed emails: %s", exc)
        for email_id in list(self._records):
            await self._persist(email_id)


async def fail(store: EmailStore, email_id: str, job: str, step: str, message: str) -> None:
    """Record a System error in the pipeline or the redraft. Retry runs that step again."""
    async with store.edit(email_id, job) as r:
        r.update(status="system_error", review=None, error_step=step, error=message[:1000])
        r["processed_at"] = r["processed_at"] or now()
        if step == "pipeline" and r.get("run"):
            r["run"]["finished_at"] = r["run"].get("finished_at") or now()
        add_event(r, "error", f"System error in the {'redraft' if step == 'redraft' else 'pipeline run'}: {message[:200]}")
    logger.warning("%s: %s failed: %s", email_id, step, message)


def build_store() -> EmailStore:
    dsn = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "")
    return PostgresEmailStore(dsn) if dsn else EmailStore()
