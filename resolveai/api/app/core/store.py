"""CaseStore — abstraction over case persistence."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from . import db as db_module


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class CaseStore(Protocol):
    """Duck-typed interface every store implements."""

    async def ingest(self, payload: dict[str, Any], tenant_id: str) -> dict[str, Any]: ...
    async def get(self, case_id: str) -> dict[str, Any] | None: ...
    async def list(
        self, status: str | None = None, limit: int = 50, tenant_id: str | None = None,
    ) -> list[dict[str, Any]]: ...
    async def update_status(
        self, case_id: str, status: str, **fields: Any,
    ) -> dict[str, Any] | None: ...
    async def append_event(
        self, case_id: str, event: dict[str, Any],
    ) -> dict[str, Any] | None: ...
    async def record_action(
        self, case_id: str, action_audit_data: dict[str, Any],
    ) -> dict[str, Any] | None: ...
    async def metrics(self, tenant_id: str | None = None) -> dict[str, Any]: ...


# In-memory store — zero-dep, good for local dev and unit tests.

class InMemoryStore:
    """Dict-backed store; behaviour matches the Phase-1 walking skeleton."""

    def __init__(self) -> None:
        self._cases: dict[str, dict[str, Any]] = {}
        self._actions: dict[str, list[dict[str, Any]]] = {}   # case_id → list
        self._csat: dict[str, list[dict[str, Any]]] = {}       # case_id → list
        self._sla_breaches: dict[str, list[dict[str, Any]]] = {}
        self._voc: list[dict[str, Any]] = []
        self._tenant_settings: dict[str, dict[str, Any]] = {}

    @property
    def raw_cases(self) -> dict[str, dict[str, Any]]:
        """Escape hatch for legacy main.py paths (e.g. metrics summary)."""
        return self._cases

    async def ingest(self, payload: dict[str, Any], tenant_id: str) -> dict[str, Any]:
        case_id = str(uuid.uuid4())
        ts = _iso(_now())
        case: dict[str, Any] = {
            "id": case_id,
            "tenant_id": tenant_id,
            "status": "ingested",
            "customer_id": payload["customer_id"],
            "customer_tier": payload.get("customer_tier", "standard"),
            "channel": payload.get("channel", "chat"),
            "subject": payload["subject"],
            "body": payload["body"],
            "order_id": payload.get("order_id"),
            "sku": payload.get("sku"),
            "jurisdiction": payload.get("jurisdiction", "US"),
            "locale": payload.get("locale", "en"),
            "intent": None,
            "ticket_category": None,
            "urgency": None,
            "sentiment": None,
            "deflection_score": None,
            "resolution": None,
            "citations": [],
            "action_plan": {},
            "cost_usd": 0.0,
            "duration_ms": 0,
            "assigned_human": None,
            "closed_at": None,
            "sla_deadline_at": payload.get("sla_deadline_at"),
            "pii_flags": [],
            "risk_flags": [],
            "created_at": ts,
            "updated_at": ts,
            "events": [
                {
                    "ts": ts,
                    "type": "ticket_ingested",
                    "actor": "system",
                    "summary": payload["subject"],
                    "payload": {},
                }
            ],
        }
        self._cases[case_id] = case
        self._actions.setdefault(case_id, [])
        self._csat.setdefault(case_id, [])
        self._sla_breaches.setdefault(case_id, [])
        return case

    async def get(self, case_id: str) -> dict[str, Any] | None:
        return self._cases.get(case_id)

    async def list(
        self, status: str | None = None, limit: int = 50, tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = list(self._cases.values())
        if status:
            rows = [c for c in rows if c.get("status") == status]
        if tenant_id:
            rows = [c for c in rows if c.get("tenant_id") == tenant_id]
        rows.sort(key=lambda c: c.get("created_at", ""), reverse=True)
        return rows[:limit]

    async def update_status(
        self, case_id: str, status: str, **fields: Any,
    ) -> dict[str, Any] | None:
        case = self._cases.get(case_id)
        if not case:
            return None
        case["status"] = status
        case["updated_at"] = _iso(_now())
        for k, v in fields.items():
            case[k] = v
        event_summary = fields.pop("_event_summary", f"status → {status}")
        event_type = fields.pop("_event_type", "status_changed")
        case["events"].append({
            "ts": case["updated_at"],
            "type": event_type,
            "actor": fields.pop("_event_actor", "system"),
            "summary": event_summary,
            "payload": {"new_status": status},
        })
        return case

    async def append_event(
        self, case_id: str, event: dict[str, Any],
    ) -> dict[str, Any] | None:
        case = self._cases.get(case_id)
        if not case:
            return None
        ev = {
            "ts": event.get("ts") or _iso(_now()),
            "type": event.get("type", "event"),
            "actor": event.get("actor", "system"),
            "summary": event.get("summary", ""),
            "payload": event.get("payload") or {},
        }
        case["events"].append(ev)
        case["updated_at"] = ev["ts"]
        return ev

    async def record_action(
        self, case_id: str, action_audit_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        if case_id not in self._cases:
            return None
        row = {
            "id": str(uuid.uuid4()),
            "case_id": case_id,
            "action_type": action_audit_data.get("action_type", "other"),
            "amount_usd": action_audit_data.get("amount_usd", 0.0),
            "rationale": action_audit_data.get("rationale", ""),
            "policy_citations": action_audit_data.get("policy_citations", []),
            "requires_approval": action_audit_data.get("requires_approval", False),
            "approval_tier": action_audit_data.get("approval_tier"),
            "approved_by": action_audit_data.get("approved_by"),
            "approved_at": action_audit_data.get("approved_at"),
            "executed_at": action_audit_data.get("executed_at"),
            "executor": action_audit_data.get("executor", "pipeline"),
            "external_id": action_audit_data.get("external_id"),
            "status": action_audit_data.get("status", "pending_approval"),
            "created_at": _iso(_now()),
        }
        self._actions.setdefault(case_id, []).append(row)
        await self.append_event(case_id, {
            "type": "action_recorded",
            "actor": row["executor"],
            "summary": f"{row['action_type']} ${row['amount_usd']:.2f} ({row['status']})",
            "payload": {"action_id": row["id"]},
        })
        return row

    async def metrics(self, tenant_id: str | None = None) -> dict[str, Any]:
        rows = list(self._cases.values())
        if tenant_id:
            rows = [r for r in rows if r.get("tenant_id") == tenant_id]
        total = len(rows)
        auto = sum(1 for r in rows if r.get("status") == "auto_resolved")
        human = sum(1 for r in rows if r.get("status") == "handed_to_human")
        closed = sum(1 for r in rows if r.get("status") == "closed")
        total_cost = round(sum((r.get("cost_usd") or 0.0) for r in rows), 4)
        return {
            "total_cases": total,
            "auto_resolved": auto,
            "handed_to_human": human,
            "closed": closed,
            "deflection_rate": (auto / total) if total else 0.0,
            "total_cost_usd": total_cost,
            "avg_cost_per_case": (total_cost / total) if total else 0.0,
        }

    # Helpers used by routers that need direct access to sibling tables.
    def list_actions(self, case_id: str) -> list[dict[str, Any]]:
        return list(self._actions.get(case_id, []))

    def get_action(self, action_id: str) -> dict[str, Any] | None:
        for rows in self._actions.values():
            for row in rows:
                if row["id"] == action_id:
                    return row
        return None

    def pending_approvals(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for case_id, rows in self._actions.items():
            case = self._cases.get(case_id)
            if tenant_id and case and case.get("tenant_id") != tenant_id:
                continue
            for row in rows:
                if row["status"] == "pending_approval":
                    out.append(row)
        return out

    def record_csat(self, case_id: str, score: int, source: str, **extra: Any) -> dict[str, Any]:
        row = {
            "id": str(uuid.uuid4()),
            "case_id": case_id,
            "score": score,
            "source": source,
            "predicted_nps_bucket": extra.get("predicted_nps_bucket"),
            "red_flags": extra.get("red_flags", []),
            "created_at": _iso(_now()),
        }
        self._csat.setdefault(case_id, []).append(row)
        return row

    def list_csat(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        out = []
        for case_id, rows in self._csat.items():
            case = self._cases.get(case_id)
            if tenant_id and case and case.get("tenant_id") != tenant_id:
                continue
            for r in rows:
                out.append(r)
        return out

    def record_sla_breach(self, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        row = {
            "id": str(uuid.uuid4()),
            "case_id": case_id,
            "sla_type": payload.get("sla_type", "resolution"),
            "breached_at": payload.get("breached_at") or _iso(_now()),
            "minutes_overdue": payload.get("minutes_overdue", 0),
            "escalated_to": payload.get("escalated_to"),
            "resolved_at": payload.get("resolved_at"),
        }
        self._sla_breaches.setdefault(case_id, []).append(row)
        return row

    def open_sla_candidates(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or _now()
        out = []
        for case in self._cases.values():
            deadline = case.get("sla_deadline_at")
            if not deadline or case.get("status") in ("closed", "auto_resolved"):
                continue
            try:
                dl = datetime.fromisoformat(deadline) if isinstance(deadline, str) else deadline
            except ValueError:
                continue
            if dl and dl < now:
                out.append(case)
        return out

    def list_voc(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        rows = list(self._voc)
        if tenant_id:
            rows = [r for r in rows if r.get("tenant_id") == tenant_id]
        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return rows

    def record_voc(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": payload.get("tenant_id"),
            "cluster_id": payload.get("cluster_id", "cluster-unknown"),
            "signal": payload.get("signal", ""),
            "case_count": payload.get("case_count", 0),
            "anomaly_score": payload.get("anomaly_score", 0.0),
            "example_case_ids": payload.get("example_case_ids", []),
            "suggested_action": payload.get("suggested_action", ""),
            "status": payload.get("status", "open"),
            "created_at": _iso(_now()),
        }
        self._voc.append(row)
        return row

    def get_tenant_settings(self, tenant_id: str) -> dict[str, Any]:
        row = self._tenant_settings.get(tenant_id)
        if row:
            return row
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "approval_tiers": {
                "auto_ceiling_usd": 25.0,
                "t1_ceiling_usd": 250.0,
                "manager_ceiling_usd": 5000.0,
            },
            "sla_first_response_minutes": 15,
            "sla_resolution_minutes": 1440,
            "slack_escalation_url": None,
            "moderation_policy_id": None,
            "integrations": {
                "stripe_mode": "mock",
                "shopify_mode": "mock",
                "zendesk_mode": "mock",
                "shipengine_mode": "mock",
            },
            "created_at": _iso(_now()),
            "updated_at": _iso(_now()),
        }
        self._tenant_settings[tenant_id] = row
        return row

    def update_tenant_settings(self, tenant_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        row = self.get_tenant_settings(tenant_id)
        for k, v in patch.items():
            if v is not None:
                row[k] = v
        row["updated_at"] = _iso(_now())
        return row


# Postgres store

class PostgresStore:
    """SQLAlchemy-backed CaseStore."""

    def __init__(self, sessionmaker) -> None:
        self._sm = sessionmaker

    async def _session(self):
        return self._sm()

    async def ingest(self, payload: dict[str, Any], tenant_id: str) -> dict[str, Any]:
        from app.models import Case, CaseEvent, CaseStatus

        now = _now()
        async with self._sm() as session:
            case = Case(
                tenant_id=uuid.UUID(tenant_id),
                customer_id=payload["customer_id"],
                customer_tier=payload.get("customer_tier", "standard"),
                channel=payload.get("channel", "chat"),
                subject=payload["subject"],
                body=payload["body"],
                order_id=payload.get("order_id"),
                sku=payload.get("sku"),
                jurisdiction=payload.get("jurisdiction", "US"),
                locale=payload.get("locale", "en"),
                status=CaseStatus.INGESTED,
                citations=[],
                action_plan={},
                pii_flags=[],
                risk_flags=[],
                sla_deadline_at=payload.get("sla_deadline_at"),
            )
            session.add(case)
            await session.flush()

            event = CaseEvent(
                case_id=case.id,
                ts=now,
                type="ticket_ingested",
                actor="system",
                summary=payload["subject"],
                payload={},
            )
            session.add(event)
            await session.commit()
            await session.refresh(case)

            dto = case.to_dict()
            dto["events"] = [event.to_dict()]
            return dto

    async def get(self, case_id: str) -> dict[str, Any] | None:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models import Case

        async with self._sm() as session:
            result = await session.execute(
                select(Case)
                .where(Case.id == uuid.UUID(case_id))
                .options(selectinload(Case.events))
            )
            case = result.scalar_one_or_none()
            if not case:
                return None
            dto = case.to_dict()
            dto["events"] = [e.to_dict() for e in sorted(case.events, key=lambda e: e.ts)]
            return dto

    async def list(
        self, status: str | None = None, limit: int = 50, tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from app.models import Case, CaseStatus

        async with self._sm() as session:
            stmt = select(Case).order_by(Case.created_at.desc()).limit(limit)
            if status:
                try:
                    stmt = stmt.where(Case.status == CaseStatus(status))
                except ValueError:
                    return []
            if tenant_id:
                stmt = stmt.where(Case.tenant_id == uuid.UUID(tenant_id))
            result = await session.execute(stmt)
            return [c.to_dict() for c in result.scalars().all()]

    async def update_status(
        self, case_id: str, status: str, **fields: Any,
    ) -> dict[str, Any] | None:
        from sqlalchemy import select
        from app.models import Case, CaseEvent, CaseStatus

        event_summary = fields.pop("_event_summary", f"status → {status}")
        event_type = fields.pop("_event_type", "status_changed")
        event_actor = fields.pop("_event_actor", "system")

        async with self._sm() as session:
            result = await session.execute(
                select(Case).where(Case.id == uuid.UUID(case_id))
            )
            case = result.scalar_one_or_none()
            if not case:
                return None

            try:
                case.status = CaseStatus(status)
            except ValueError:
                return None

            # Map common fields back onto the ORM model.
            field_map = {
                "resolution": "resolution_summary",
            }
            for key, value in fields.items():
                col = field_map.get(key, key)
                if hasattr(case, col):
                    setattr(case, col, value)

            session.add(CaseEvent(
                case_id=case.id,
                ts=_now(),
                type=event_type,
                actor=event_actor,
                summary=event_summary,
                payload={"new_status": status},
            ))
            await session.commit()
            return await self.get(case_id)

    async def append_event(
        self, case_id: str, event: dict[str, Any],
    ) -> dict[str, Any] | None:
        from sqlalchemy import select
        from app.models import Case, CaseEvent

        async with self._sm() as session:
            result = await session.execute(
                select(Case).where(Case.id == uuid.UUID(case_id))
            )
            case = result.scalar_one_or_none()
            if not case:
                return None

            row = CaseEvent(
                case_id=case.id,
                ts=_now(),
                type=event.get("type", "event"),
                actor=event.get("actor", "system"),
                summary=event.get("summary", ""),
                payload=event.get("payload") or {},
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def record_action(
        self, case_id: str, action_audit_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        from sqlalchemy import select
        from app.models import ActionAudit, Case, CaseEvent

        async with self._sm() as session:
            result = await session.execute(
                select(Case).where(Case.id == uuid.UUID(case_id))
            )
            case = result.scalar_one_or_none()
            if not case:
                return None

            row = ActionAudit(
                case_id=case.id,
                action_type=action_audit_data.get("action_type", "other"),
                amount_usd=action_audit_data.get("amount_usd", 0.0),
                rationale=action_audit_data.get("rationale", ""),
                policy_citations=action_audit_data.get("policy_citations", []),
                requires_approval=action_audit_data.get("requires_approval", False),
                approval_tier=action_audit_data.get("approval_tier"),
                approved_by=action_audit_data.get("approved_by"),
                approved_at=action_audit_data.get("approved_at"),
                executed_at=action_audit_data.get("executed_at"),
                executor=action_audit_data.get("executor", "pipeline"),
                external_id=action_audit_data.get("external_id"),
                status=action_audit_data.get("status", "pending_approval"),
                created_at=_now(),
            )
            session.add(row)
            session.add(CaseEvent(
                case_id=case.id,
                ts=_now(),
                type="action_recorded",
                actor=row.executor,
                summary=f"{row.action_type} ${row.amount_usd:.2f} ({row.status})",
                payload={"action_type": row.action_type},
            ))
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def metrics(self, tenant_id: str | None = None) -> dict[str, Any]:
        from sqlalchemy import func, select
        from app.models import Case, CaseStatus

        async with self._sm() as session:
            base = select(Case)
            if tenant_id:
                base = base.where(Case.tenant_id == uuid.UUID(tenant_id))

            total_row = await session.execute(
                select(func.count()).select_from(base.subquery())
            )
            total = int(total_row.scalar_one() or 0)

            async def _count_status(s: CaseStatus) -> int:
                q = select(func.count()).select_from(Case).where(Case.status == s)
                if tenant_id:
                    q = q.where(Case.tenant_id == uuid.UUID(tenant_id))
                return int((await session.execute(q)).scalar_one() or 0)

            auto = await _count_status(CaseStatus.AUTO_RESOLVED)
            human = await _count_status(CaseStatus.HANDED_TO_HUMAN)
            closed = await _count_status(CaseStatus.CLOSED)

            cost_q = select(func.coalesce(func.sum(Case.cost_usd), 0.0))
            if tenant_id:
                cost_q = cost_q.where(Case.tenant_id == uuid.UUID(tenant_id))
            total_cost = float((await session.execute(cost_q)).scalar_one() or 0.0)

        return {
            "total_cases": total,
            "auto_resolved": auto,
            "handed_to_human": human,
            "closed": closed,
            "deflection_rate": (auto / total) if total else 0.0,
            "total_cost_usd": round(total_cost, 4),
            "avg_cost_per_case": (total_cost / total) if total else 0.0,
        }

    # ── PG helpers (parallel to InMemoryStore's helper methods) ──────

    async def list_actions(self, case_id: str) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from app.models import ActionAudit

        async with self._sm() as session:
            result = await session.execute(
                select(ActionAudit)
                .where(ActionAudit.case_id == uuid.UUID(case_id))
                .order_by(ActionAudit.created_at)
            )
            return [r.to_dict() for r in result.scalars().all()]

    async def get_action(self, action_id: str) -> dict[str, Any] | None:
        from sqlalchemy import select
        from app.models import ActionAudit

        async with self._sm() as session:
            result = await session.execute(
                select(ActionAudit).where(ActionAudit.id == uuid.UUID(action_id))
            )
            row = result.scalar_one_or_none()
            return row.to_dict() if row else None

    async def update_action(
        self, action_id: str, **fields: Any,
    ) -> dict[str, Any] | None:
        from sqlalchemy import select
        from app.models import ActionAudit

        async with self._sm() as session:
            result = await session.execute(
                select(ActionAudit).where(ActionAudit.id == uuid.UUID(action_id))
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            for k, v in fields.items():
                if hasattr(row, k):
                    setattr(row, k, v)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def pending_approvals(
        self, tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from app.models import ActionAudit, Case

        async with self._sm() as session:
            stmt = (
                select(ActionAudit)
                .join(Case, Case.id == ActionAudit.case_id)
                .where(ActionAudit.status == "pending_approval")
                .order_by(ActionAudit.created_at.desc())
            )
            if tenant_id:
                stmt = stmt.where(Case.tenant_id == uuid.UUID(tenant_id))
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars().all()]

    async def record_csat(
        self, case_id: str, score: int, source: str, **extra: Any,
    ) -> dict[str, Any]:
        from app.models import CSATScore

        async with self._sm() as session:
            row = CSATScore(
                case_id=uuid.UUID(case_id),
                score=score,
                source=source,
                predicted_nps_bucket=extra.get("predicted_nps_bucket"),
                red_flags=extra.get("red_flags", []),
                created_at=_now(),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def list_csat(
        self, tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from app.models import Case, CSATScore

        async with self._sm() as session:
            stmt = (
                select(CSATScore)
                .join(Case, Case.id == CSATScore.case_id)
                .order_by(CSATScore.created_at.desc())
            )
            if tenant_id:
                stmt = stmt.where(Case.tenant_id == uuid.UUID(tenant_id))
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars().all()]

    async def record_sla_breach(
        self, case_id: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        from app.models import SLABreach

        async with self._sm() as session:
            row = SLABreach(
                case_id=uuid.UUID(case_id),
                sla_type=payload.get("sla_type", "resolution"),
                breached_at=payload.get("breached_at") or _now(),
                minutes_overdue=payload.get("minutes_overdue", 0),
                escalated_to=payload.get("escalated_to"),
                resolved_at=payload.get("resolved_at"),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def open_sla_candidates(
        self, now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from app.models import Case, CaseStatus

        now = now or _now()
        async with self._sm() as session:
            result = await session.execute(
                select(Case)
                .where(Case.sla_deadline_at.isnot(None))
                .where(Case.sla_deadline_at < now)
                .where(~Case.status.in_([CaseStatus.CLOSED, CaseStatus.AUTO_RESOLVED]))
            )
            return [c.to_dict() for c in result.scalars().all()]

    async def list_voc(
        self, tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from app.models import VoCInsight

        async with self._sm() as session:
            stmt = select(VoCInsight).order_by(VoCInsight.created_at.desc())
            if tenant_id:
                stmt = stmt.where(VoCInsight.tenant_id == uuid.UUID(tenant_id))
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars().all()]

    async def record_voc(self, payload: dict[str, Any]) -> dict[str, Any]:
        from app.models import VoCInsight

        async with self._sm() as session:
            row = VoCInsight(
                tenant_id=uuid.UUID(payload["tenant_id"]),
                cluster_id=payload.get("cluster_id", "cluster-unknown"),
                signal=payload.get("signal", ""),
                case_count=payload.get("case_count", 0),
                anomaly_score=payload.get("anomaly_score", 0.0),
                example_case_ids=payload.get("example_case_ids", []),
                suggested_action=payload.get("suggested_action", ""),
                status=payload.get("status", "open"),
                created_at=_now(),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def get_tenant_settings(self, tenant_id: str) -> dict[str, Any]:
        from sqlalchemy import select
        from app.models import TenantSettings

        async with self._sm() as session:
            result = await session.execute(
                select(TenantSettings).where(TenantSettings.tenant_id == uuid.UUID(tenant_id))
            )
            row = result.scalar_one_or_none()
            if row:
                return row.to_dict()

            row = TenantSettings(tenant_id=uuid.UUID(tenant_id))
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def update_tenant_settings(
        self, tenant_id: str, patch: dict[str, Any],
    ) -> dict[str, Any]:
        from sqlalchemy import select
        from app.models import TenantSettings

        async with self._sm() as session:
            result = await session.execute(
                select(TenantSettings).where(TenantSettings.tenant_id == uuid.UUID(tenant_id))
            )
            row = result.scalar_one_or_none()
            if not row:
                row = TenantSettings(tenant_id=uuid.UUID(tenant_id))
                session.add(row)
                await session.flush()

            for k, v in patch.items():
                if v is not None and hasattr(row, k):
                    setattr(row, k, v)

            await session.commit()
            await session.refresh(row)
            return row.to_dict()


def build_store() -> CaseStore:
    """Factory used by main.py — picks Postgres when available."""
    if db_module.db_enabled and db_module.get_sessionmaker() is not None:
        return PostgresStore(db_module.get_sessionmaker())
    return InMemoryStore()
