"""Tamper-evident audit: activity_logs rows linked into one hash chain per tenant."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CHAIN_LOCK_KEY = 0x41554449
SETTLE_SECONDS = 15
BATCH = 2000
# actor recorded for platform writes and for erased users
NIL_ACTOR = uuid.UUID(int=0)

_COLS = (
    "id, tenant_id, user_id, action, details, ip_address, user_agent, "
    "created_at, audit_seq, pii_salt, pii_digest"
)


def pii_digest(salt: str, row: dict[str, Any]) -> str:
    """Salted commitment to who did it, so erasure keeps the chain intact."""
    ip = row["ip_address"] or ""
    ua = row["user_agent"] or ""
    return hashlib.sha256(f"{salt}|{row['user_id']}|{ip}|{ua}".encode()).hexdigest()


def row_digest(prev_hash: str | None, row: dict[str, Any]) -> str:
    created = row.get("created_at")
    body = json.dumps(
        {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "pii": row["pii_digest"],
            "action": row["action"],
            "details": row["details"],
            "created_at": created.isoformat() if created else None,
            "audit_seq": int(row["audit_seq"]),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(f"{prev_hash or ''}|{body}".encode()).hexdigest()


async def maintenance(db: AsyncSession) -> None:
    """Lift the append-only guard for the rest of the current transaction."""
    await db.execute(text("SET LOCAL abenix.audit_maintenance = 'on'"))


async def chain_pending(db: AsyncSession, limit: int = BATCH) -> int:
    """Link settled unlinked rows. The caller holds the chain lock."""
    rows = (
        (
            await db.execute(
                text(
                    f"SELECT {_COLS} FROM activity_logs WHERE row_hash IS NULL "
                    "AND created_at < now() - make_interval(secs => :settle) "
                    "ORDER BY audit_seq LIMIT :lim"
                ),
                {"settle": SETTLE_SECONDS, "lim": limit},
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return 0
    tenants = list({r["tenant_id"] for r in rows})
    heads: dict[Any, tuple[str | None, int]] = {}
    for t, h, p in (
        await db.execute(
            text(
                "SELECT DISTINCT ON (tenant_id) tenant_id, row_hash, chain_pos "
                "FROM activity_logs WHERE chain_pos IS NOT NULL AND tenant_id = ANY(:t) "
                "ORDER BY tenant_id, chain_pos DESC"
            ),
            {"t": tenants},
        )
    ).all():
        heads[t] = (h, int(p or 0))
    for r in rows:
        row = dict(r)
        salt = secrets.token_hex(16)
        row["pii_digest"] = pii_digest(salt, row)
        prev, pos = heads.get(r["tenant_id"], (None, 0))
        digest = row_digest(prev, row)
        await db.execute(
            text(
                "UPDATE activity_logs SET prev_hash = :p, row_hash = :h, chain_pos = :c, "
                "pii_salt = :s, pii_digest = :d WHERE id = :id AND row_hash IS NULL"
            ),
            {
                "p": prev,
                "h": digest,
                "c": pos + 1,
                "s": salt,
                "d": row["pii_digest"],
                "id": r["id"],
            },
        )
        heads[r["tenant_id"]] = (digest, pos + 1)
    return len(rows)


async def run_chainer() -> int:
    """Scheduler entry point. Only the replica holding the lock does the work."""
    from app.core.deps import async_session

    linked = 0
    try:
        async with async_session() as db:
            async with db.begin():
                held = (
                    await db.execute(
                        text("SELECT pg_try_advisory_xact_lock(:k)"),
                        {"k": CHAIN_LOCK_KEY},
                    )
                ).scalar()
                if not held:
                    return 0
                linked = await chain_pending(db)
    except Exception:
        logger.exception("audit chainer failed")
    if linked:
        logger.info("audit chainer linked %d rows", linked)
    return linked


async def write_prune_anchor(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    last_row_hash: str,
    last_chain_pos: int,
    rows: int,
    reason: str,
    actor: uuid.UUID | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Record where a removed prefix ended, so verification can start after it."""
    await db.execute(
        text(
            "INSERT INTO activity_logs (id, tenant_id, user_id, action, details, created_at) "
            "VALUES (:id, :t, :u, 'audit.pruned', CAST(:d AS jsonb), now())"
        ),
        {
            "id": uuid.uuid4(),
            "t": tenant_id,
            "u": actor or NIL_ACTOR,
            "d": json.dumps(
                {
                    "last_row_hash": last_row_hash,
                    "last_chain_pos": last_chain_pos,
                    "rows": rows,
                    "reason": reason,
                    **(extra or {}),
                }
            ),
        },
    )


async def chained_prefix_end(
    db: AsyncSession, tenant_id: uuid.UUID, cutoff: datetime
) -> int:
    """Highest chain position that can go while the rest stays one contiguous chain."""
    first_kept = (
        await db.execute(
            text(
                "SELECT min(chain_pos) FROM activity_logs WHERE tenant_id = :t "
                "AND chain_pos IS NOT NULL AND created_at >= :c"
            ),
            {"t": tenant_id, "c": cutoff},
        )
    ).scalar()
    if first_kept is not None:
        return int(first_kept) - 1
    last = (
        await db.execute(
            text("SELECT max(chain_pos) FROM activity_logs WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    ).scalar()
    return int(last or 0)


async def head_at(db: AsyncSession, tenant_id: uuid.UUID, pos: int) -> str | None:
    return (
        await db.execute(
            text(
                "SELECT row_hash FROM activity_logs WHERE tenant_id = :t AND chain_pos = :p"
            ),
            {"t": tenant_id, "p": pos},
        )
    ).scalar()


async def prune_before(
    db: AsyncSession, tenant_id: uuid.UUID, cutoff: datetime, reason: str
) -> int:
    """Delete the chained rows older than cutoff and leave an anchor. Caller commits."""
    end = await chained_prefix_end(db, tenant_id, cutoff)
    if end <= 0:
        return 0
    last = await head_at(db, tenant_id, end)
    await maintenance(db)
    res = await db.execute(
        text("DELETE FROM activity_logs WHERE tenant_id = :t AND chain_pos <= :p"),
        {"t": tenant_id, "p": end},
    )
    n = res.rowcount or 0
    if n and last:
        await write_prune_anchor(
            db,
            tenant_id,
            last_row_hash=last,
            last_chain_pos=end,
            rows=n,
            reason=reason,
            extra={"cutoff": cutoff.isoformat()},
        )
    return n


async def verify_tenant(
    db: AsyncSession, tenant_id: uuid.UUID, batch: int = 5000
) -> dict[str, Any]:
    """Walk the tenant's chain in order and report the first break, if any."""
    anchors = {
        a
        for (a,) in (
            await db.execute(
                text(
                    "SELECT details->>'last_row_hash' FROM activity_logs "
                    "WHERE tenant_id = :t AND action = 'audit.pruned'"
                ),
                {"t": tenant_id},
            )
        ).all()
        if a
    }
    checked = 0
    redacted = 0
    expected_prev: str | None = None
    first = True
    last_pos = 0
    while True:
        rows = (
            (
                await db.execute(
                    text(
                        f"SELECT {_COLS}, prev_hash, row_hash, chain_pos FROM activity_logs "
                        "WHERE tenant_id = :t AND chain_pos > :p ORDER BY chain_pos LIMIT :lim"
                    ),
                    {"t": tenant_id, "p": last_pos, "lim": batch},
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            break
        for r in rows:
            pos = int(r["chain_pos"])
            if first:
                # starts at the beginning, or right after a recorded prune
                if r["prev_hash"] is not None and r["prev_hash"] not in anchors:
                    return _broken(
                        r,
                        checked,
                        "rows before this one were removed without an anchor",
                    )
                expected_prev = r["prev_hash"]
                first = False
            elif pos != last_pos + 1:
                return _broken(
                    r, checked, f"rows {last_pos + 1} to {pos - 1} are missing"
                )
            if r["prev_hash"] != expected_prev:
                return _broken(r, checked, "the link to the previous row is broken")
            if r["pii_salt"] is None:
                redacted += 1
            elif pii_digest(r["pii_salt"], dict(r)) != r["pii_digest"]:
                return _broken(
                    r, checked, "the actor, address or user agent was changed"
                )
            if row_digest(r["prev_hash"], dict(r)) != r["row_hash"]:
                return _broken(r, checked, "the row no longer matches its hash")
            expected_prev = r["row_hash"]
            checked += 1
            last_pos = pos
    pending = (
        await db.execute(
            text(
                "SELECT count(*) FROM activity_logs WHERE tenant_id = :t AND row_hash IS NULL"
            ),
            {"t": tenant_id},
        )
    ).scalar() or 0
    return {
        "ok": True,
        "checked": checked,
        "redacted": redacted,
        "pending": int(pending),
        "head": expected_prev,
        "head_pos": last_pos,
    }


def _broken(row: Any, checked: int, why: str) -> dict[str, Any]:
    created = row["created_at"]
    return {
        "ok": False,
        "checked": checked,
        "broken_at": {
            "id": str(row["id"]),
            "chain_pos": row["chain_pos"],
            "action": row["action"],
            "created_at": created.isoformat() if created else None,
        },
        "reason": why,
    }


async def verify_all() -> list[dict[str, Any]]:
    """Verify every tenant's chain. Breaks raise a metric, an audit entry and a notice to admins."""
    from app.core.deps import async_session
    from app.core.telemetry import _safe_counter

    breaks = _safe_counter(
        "abenix_audit_chain_breaks_total",
        "Audit chain verifications that found a break",
        ["tenant"],
    )
    checks = _safe_counter(
        "abenix_audit_chain_verified_total",
        "Audit chain verifications run",
        ["outcome"],
    )
    out = []
    async with async_session() as db:
        tenants = [
            t
            for (t,) in (
                await db.execute(text("SELECT DISTINCT tenant_id FROM activity_logs"))
            ).all()
        ]
    for tid in tenants:
        async with async_session() as db:
            res = await verify_tenant(db, tid)
            out.append({"tenant_id": str(tid), **res})
            checks.labels(outcome="ok" if res["ok"] else "broken").inc()
            if res["ok"]:
                continue
            breaks.labels(tenant=str(tid)).inc()
            logger.error(
                "audit chain broken for tenant %s: %s at %s",
                tid,
                res.get("reason"),
                res.get("broken_at"),
            )
            await db.execute(
                text(
                    "INSERT INTO activity_logs (id, tenant_id, user_id, action, details, created_at) "
                    "VALUES (:id, :t, :u, 'audit.chain_broken', CAST(:d AS jsonb), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "t": tid,
                    "u": NIL_ACTOR,
                    "d": json.dumps(
                        {"reason": res.get("reason"), "broken_at": res.get("broken_at")}
                    ),
                },
            )
            await db.commit()
            await _notify_admins(db, tid, res)
    return out


async def _notify_admins(db: AsyncSession, tenant_id: Any, res: dict[str, Any]) -> None:
    try:
        from app.core.notifications import create_notification

        admins = (
            (
                await db.execute(
                    text(
                        "SELECT id FROM users WHERE tenant_id = :t AND role = 'admin' AND is_active"
                    ),
                    {"t": tenant_id},
                )
            )
            .scalars()
            .all()
        )
        for uid in admins:
            await create_notification(
                db,
                tenant_id=tenant_id,
                user_id=uid,
                type="system_alert",
                title="The activity log failed its integrity check",
                message=f"{res.get('reason', 'A break was found')}. Treat the log from that point as untrusted and compare it with archived copies.",
                link="/admin/risk#audit",
                metadata={"broken_at": res.get("broken_at")},
            )
    except Exception:  # noqa: BLE001
        logger.exception("could not notify admins about the audit chain")


async def run_nightly_verify() -> dict[str, int] | None:
    from app.core.scheduler import advisory_lock

    try:
        async with advisory_lock(CHAIN_LOCK_KEY + 1) as held:
            if not held:
                return None
            results = await verify_all()
            broken = sum(1 for r in results if not r["ok"])
            logger.info(
                "audit chain verified for %d tenants, %d broken",
                len(results),
                broken,
            )
            return {"tenants": len(results), "broken": broken}
    except Exception:
        logger.exception("nightly audit verification failed")
        return None
