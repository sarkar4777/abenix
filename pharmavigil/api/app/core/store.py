"""Case store for PharmaVigil.

Postgres when DATABASE_URL is set, otherwise an in-memory dict so the app
runs from a clone with no infrastructure. Same split the other standalone
apps use.

Only case rows and review decisions live here. Nothing in this module talks
to Abenix — every assessment goes through the SDK from the routers.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

TERMINAL = {"assessed", "submitted", "rejected", "merged", "failed"}


_BG_CACHE: dict[str, Any] | None = None


def _background_counts() -> dict[str, Any]:
    """Reference frequency table shipped with the app, cached after first read."""
    global _BG_CACHE
    if _BG_CACHE is not None:
        return _BG_CACHE
    from pathlib import Path

    here = Path(__file__).resolve()
    for base in (here.parents[2], here.parents[3]):
        candidate = base / "test-data" / "background_counts.json"
        if candidate.is_file():
            try:
                _BG_CACHE = json.loads(candidate.read_text(encoding="utf-8"))
                return _BG_CACHE
            except Exception:
                break
    _BG_CACHE = {}
    return _BG_CACHE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CaseStore:
    """In-memory store. Swapped for the Postgres one when a URL is present."""

    def __init__(self) -> None:
        self._cases: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    # ── writes ────────────────────────────────────────────────────────────
    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            case_id = payload.get("id") or str(uuid.uuid4())
            row = {
                "id": case_id,
                "status": "received",
                "created_at": _now(),
                "updated_at": _now(),
                "execution_id": None,
                "error_message": None,
                **payload,
            }
            self._cases[case_id] = row
            self._events[case_id] = [
                {"at": _now(), "type": "received", "summary": "Case received"}
            ]
            return dict(row)

    async def update(self, case_id: str, **fields: Any) -> dict[str, Any] | None:
        async with self._lock:
            row = self._cases.get(case_id)
            if row is None:
                return None
            event_type = fields.pop("_event_type", None)
            event_summary = fields.pop("_event_summary", None)
            row.update(fields)
            row["updated_at"] = _now()
            if event_type:
                self._events.setdefault(case_id, []).append(
                    {"at": _now(), "type": event_type, "summary": event_summary or ""}
                )
            return dict(row)

    async def record_review(
        self, case_id: str, decision: str, reviewer: str, notes: str
    ) -> dict[str, Any] | None:
        status = {"approve": "submitted", "reject": "rejected",
                  "merge": "merged"}.get(decision, "assessed")
        return await self.update(
            case_id,
            review_decision=decision,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=_now(),
            status=status,
            _event_type="reviewed",
            _event_summary=f"{reviewer} chose {decision}",
        )

    # ── reads ─────────────────────────────────────────────────────────────
    async def get(self, case_id: str) -> dict[str, Any] | None:
        row = self._cases.get(case_id)
        return dict(row) if row else None

    async def list(self, limit: int = 100, status: str | None = None) -> list[dict]:
        rows = list(self._cases.values())
        if status:
            rows = [r for r in rows if r.get("status") == status]
        # Queue order: priority first, then oldest, so a P1 never sits behind
        # a pile of P4s that happened to arrive earlier.
        order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
        rows.sort(key=lambda r: (order.get(r.get("priority") or "P4", 3),
                                 r.get("created_at") or ""))
        return [dict(r) for r in rows[:limit]]

    async def events(self, case_id: str) -> list[dict[str, Any]]:
        return list(self._events.get(case_id, []))

    async def stats(self) -> dict[str, Any]:
        rows = list(self._cases.values())
        by_status: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        for r in rows:
            by_status[r.get("status") or "unknown"] = by_status.get(r.get("status") or "unknown", 0) + 1
            p = r.get("priority")
            if p:
                by_priority[p] = by_priority.get(p, 0) + 1
        serious = sum(1 for r in rows if r.get("serious"))
        expedited = sum(1 for r in rows if r.get("expedited"))
        signals = sum(1 for r in rows if r.get("signal"))
        awaiting = sum(1 for r in rows if r.get("status") == "assessed")
        return {
            "total_cases": len(rows),
            "by_status": by_status,
            "by_priority": by_priority,
            "serious": serious,
            "expedited": expedited,
            "signals": signals,
            "awaiting_review": awaiting,
        }

    async def frequency_snapshot(self) -> dict[str, Any]:
        """Counts the signal node needs to build a 2x2 contingency table.

        The app owns the case history, so the app supplies the frequencies.
        The alternative — letting the agent guess them — is how a
        disproportionality figure ends up with no data behind it.

        A live database of a handful of demo cases would make every ratio
        meaningless, so a background frequency table ships alongside and is
        added in. It is labelled as such in the payload: these are reference
        counts for the demonstration, not reports this instance received.
        """
        by_drug: dict[str, int] = {}
        by_pt: dict[str, int] = {}
        by_pair: dict[str, int] = {}
        live = 0
        for r in self._cases.values():
            drug = (r.get("suspect_drug") or "").strip()
            pt = (r.get("primary_pt") or "").strip()
            if not drug:
                continue
            live += 1
            by_drug[drug] = by_drug.get(drug, 0) + 1
            if pt:
                by_pt[pt] = by_pt.get(pt, 0) + 1
                key = f"{drug}|{pt}"
                by_pair[key] = by_pair.get(key, 0) + 1

        bg = _background_counts()
        total = live + int(bg.get("total_reports", 0))
        for k, v in (bg.get("by_drug") or {}).items():
            by_drug[k] = by_drug.get(k, 0) + int(v)
        for k, v in (bg.get("by_pt") or {}).items():
            by_pt[k] = by_pt.get(k, 0) + int(v)
        for k, v in (bg.get("by_pair") or {}).items():
            by_pair[k] = by_pair.get(k, 0) + int(v)

        return {
            "total_reports": total,
            "live_cases": live,
            "background_reports": int(bg.get("total_reports", 0)),
            "by_drug": by_drug,
            "by_pt": by_pt,
            "by_pair": by_pair,
            "note": (
                "by_drug/by_pt/by_pair combine this instance's assessed cases "
                "with a shipped background frequency table so the ratios have a "
                "denominator. Background counts are reference data for the "
                "demonstration, not reports received here."
            ),
        }

    async def signal_board(self) -> list[dict[str, Any]]:
        """Drug-event pairs across the case history, worst first."""
        pairs: dict[tuple[str, str], dict[str, Any]] = {}
        for r in self._cases.values():
            drug = (r.get("suspect_drug") or "unknown").strip()
            pt = (r.get("primary_pt") or "").strip()
            if not pt:
                continue
            key = (drug, pt)
            agg = pairs.setdefault(key, {
                "drug": drug, "pt": pt, "cases": 0, "serious": 0,
                "prr": None, "eb05": None, "signal": False,
            })
            agg["cases"] += 1
            agg["serious"] += 1 if r.get("serious") else 0
            for field in ("prr", "eb05"):
                val = r.get(field)
                if val is not None:
                    try:
                        cur = agg[field]
                        agg[field] = max(float(val), float(cur)) if cur is not None else float(val)
                    except (TypeError, ValueError):
                        pass
            agg["signal"] = agg["signal"] or bool(r.get("signal"))
        out = list(pairs.values())
        out.sort(key=lambda p: (not p["signal"], -(p["prr"] or 0), -p["cases"]))
        return out


class PostgresCaseStore(CaseStore):
    """Same surface, persisted. Falls back to memory if the table is absent."""

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
                    CREATE TABLE IF NOT EXISTS pv_cases (
                        id          TEXT PRIMARY KEY,
                        payload     JSONB NOT NULL,
                        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            await self._rehydrate()
        except Exception:
            # A missing database must not stop the app booting — the
            # in-memory store behind us is a working fallback.
            self._pool = None

    async def _rehydrate(self) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, payload FROM pv_cases")
        for r in rows:
            try:
                self._cases[r["id"]] = json.loads(r["payload"])
            except Exception:
                continue

    async def _persist(self, case_id: str) -> None:
        if self._pool is None:
            return
        row = self._cases.get(case_id)
        if row is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO pv_cases (id, payload) VALUES ($1, $2::jsonb)
                    ON CONFLICT (id) DO UPDATE
                      SET payload = EXCLUDED.payload, updated_at = now()
                    """,
                    case_id, json.dumps(row, default=str),
                )
        except Exception:
            pass

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = await super().create(payload)
        await self._persist(row["id"])
        return row

    async def update(self, case_id: str, **fields: Any) -> dict[str, Any] | None:
        row = await super().update(case_id, **fields)
        if row:
            await self._persist(case_id)
        return row


def build_store() -> CaseStore:
    dsn = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "")
    return PostgresCaseStore(dsn) if dsn else CaseStore()
