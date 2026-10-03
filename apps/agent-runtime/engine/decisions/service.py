"""Resolving, evaluating and publishing decision versions, shared by the API and agent tools."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine import governance
from engine.decisions import evaluator
from engine.decisions.authoring import Compiled, compile_document, referenced_sets

logger = logging.getLogger(__name__)

CHANNEL = "abenix:decisions:changed"
_TTL = float(os.environ.get("DECISION_RESOLVE_TTL", "30"))
_cache: dict[tuple[str, str], tuple[float, "ModelSnapshot"]] = {}
_listener: asyncio.Task | None = None


class DecisionError(Exception):
    def __init__(
        self, code: str, message: str, status: int = 400, **extra: Any
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


@dataclass
class VersionRef:
    id: str
    version: int
    state: str
    content: dict[str, Any]
    content_hash: str
    required_facts: list[str]
    fact_types: dict[str, str]
    valid_from: dt.datetime | None
    valid_to: dt.datetime | None
    valid_to_history: list[dict[str, Any]]
    published_at: dt.datetime | None
    superseded_at: dt.datetime | None

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "state": self.state,
            "content_hash": self.content_hash,
            "valid_from": _iso(self.valid_from),
            "valid_to": _iso(self.valid_to),
            "published_at": _iso(self.published_at),
        }


@dataclass
class ModelSnapshot:
    id: str
    key: str
    name: str
    risk_tier: str
    log_mode: str
    versions: list[VersionRef] = field(default_factory=list)


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _as_dt(v: Any, end_of_day: bool = False) -> dt.datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day, tzinfo=dt.timezone.utc)
    s = str(v).strip()
    if len(s) == 10:
        d = dt.date.fromisoformat(s)
        return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)
    parsed = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def valid_to_at(v: VersionRef, known_at: dt.datetime) -> dt.datetime | None:
    """The end of v's valid period as it was recorded at known_at."""
    end = v.valid_to
    for change in sorted(
        v.valid_to_history or [], key=lambda c: c.get("at") or "", reverse=True
    ):
        at = _as_dt(change.get("at"))
        if at is not None and at > known_at:
            end = _as_dt(change.get("from"))
    return end


def pick(
    snapshot: ModelSnapshot, as_of: dt.datetime, known_at: dt.datetime
) -> VersionRef | None:
    """The version that applied on as_of, as the platform knew it at known_at."""
    best: VersionRef | None = None
    for v in snapshot.versions:
        if v.published_at is None or v.published_at > known_at:
            continue
        if v.superseded_at is not None and v.superseded_at <= known_at:
            continue
        if v.valid_from is not None and as_of < v.valid_from:
            continue
        end = valid_to_at(v, known_at)
        if end is not None and as_of >= end:
            continue
        if best is None or (v.published_at or known_at) > (
            best.published_at or known_at
        ):
            best = v
    return best


@dataclass
class PublishPlan:
    supersede: list[str] = field(default_factory=list)
    close: list[tuple[str, dt.datetime]] = field(default_factory=list)
    block: str | None = None


def plan_publish(
    current: list[VersionRef], new_from: dt.datetime | None, new_to: dt.datetime | None
) -> PublishPlan:
    """What publishing a version valid over [new_from, new_to) does to the versions in force now."""
    plan = PublishPlan()
    lo = new_from or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    hi = new_to or dt.datetime.max.replace(tzinfo=dt.timezone.utc)
    for v in current:
        vlo = v.valid_from or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
        vhi = v.valid_to or dt.datetime.max.replace(tzinfo=dt.timezone.utc)
        if vhi <= lo or vlo >= hi:
            continue
        if vlo >= lo and vhi <= hi:
            plan.supersede.append(v.id)
        elif vlo < lo and vhi > lo and vhi <= hi:
            plan.close.append((v.id, lo))
        elif vlo < lo and vhi > hi:
            plan.block = (
                f"Version {v.version} applies from {_iso(v.valid_from) or 'the start'} with no end inside this "
                f"version's period, so publishing would split it in two. Leave this version's end date open, "
                f"or end it on {_iso(v.valid_to) or 'the same day as version ' + str(v.version)}."
            )
            return plan
        else:
            plan.block = (
                f"Version {v.version} starts on {_iso(v.valid_from)}, inside this version's period, and runs past "
                f"its end. End this version on {_iso(v.valid_from)}, or extend it to cover version {v.version}."
            )
            return plan
    return plan


async def _load(db: AsyncSession, tenant_id: str, key: str) -> ModelSnapshot | None:
    from models.decision import DecisionModel, DecisionVersion

    m = (
        await db.execute(
            select(DecisionModel).where(
                DecisionModel.tenant_id == uuid.UUID(str(tenant_id)),
                DecisionModel.key == key,
                DecisionModel.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if m is None:
        return None
    rows = (
        (
            await db.execute(
                select(DecisionVersion).where(
                    DecisionVersion.model_id == m.id,
                    DecisionVersion.published_at.isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )
    snap = ModelSnapshot(
        id=str(m.id), key=m.key, name=m.name, risk_tier=m.risk_tier, log_mode=m.log_mode
    )
    for r in rows:
        snap.versions.append(_ref(r))
    return snap


def _ref(r: Any) -> VersionRef:
    return VersionRef(
        id=str(r.id),
        version=r.version,
        state=r.state,
        content=r.content,
        content_hash=r.content_hash,
        required_facts=list(r.required_facts or []),
        fact_types=dict(r.fact_types or {}),
        valid_from=_as_dt(r.valid_from),
        valid_to=_as_dt(r.valid_to),
        valid_to_history=list(r.valid_to_history or []),
        published_at=_as_dt(r.published_at),
        superseded_at=_as_dt(r.superseded_at),
    )


async def snapshot(
    db: AsyncSession, tenant_id: str, key: str, fresh: bool = False
) -> ModelSnapshot | None:
    _ensure_listener()
    ck = (str(tenant_id), key)
    hit = _cache.get(ck)
    if hit and not fresh and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    snap = await _load(db, str(tenant_id), key)
    if snap is not None:
        _cache[ck] = (time.monotonic(), snap)
    else:
        _cache.pop(ck, None)
    return snap


def invalidate(tenant_id: str | None = None, key: str | None = None) -> None:
    if tenant_id is None:
        _cache.clear()
    else:
        _cache.pop((str(tenant_id), str(key)), None)


async def announce(tenant_id: str, key: str) -> None:
    """Tell every process to drop its cached view of this decision."""
    invalidate(tenant_id, key)
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        try:
            await r.publish(CHANNEL, f"{tenant_id}|{key}")
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.debug("decision change broadcast failed: %s", exc)


async def _listen() -> None:
    import redis.asyncio as aioredis

    while True:
        try:
            r = aioredis.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            )
            ps = r.pubsub()
            await ps.subscribe(CHANNEL)
            async for msg in ps.listen():
                if msg.get("type") != "message":
                    continue
                data = msg.get("data")
                text = data.decode() if isinstance(data, bytes) else str(data)
                tenant, _, key = text.partition("|")
                invalidate(tenant, key)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("decision change listener restarting: %s", exc)
            await asyncio.sleep(5)


def _ensure_listener() -> None:
    global _listener
    if _listener is not None and not _listener.done():
        return
    if not os.environ.get("REDIS_URL"):
        return
    try:
        _listener = asyncio.get_running_loop().create_task(_listen())
    except RuntimeError:
        _listener = None


async def reference_values(
    db: AsyncSession, tenant_id: str, keys: set[str]
) -> tuple[dict[str, list[Any]], dict[str, int]]:
    from models.decision import ReferenceSet

    if not keys:
        return {}, {}
    rows = (
        (
            await db.execute(
                select(ReferenceSet).where(
                    ReferenceSet.tenant_id == uuid.UUID(str(tenant_id)),
                    ReferenceSet.key.in_(sorted(keys)),
                )
            )
        )
        .scalars()
        .all()
    )
    return {r.key: list(r.values or []) for r in rows}, {r.key: r.version for r in rows}


async def compile_for(
    db: AsyncSession, tenant_id: str, doc: dict[str, Any]
) -> Compiled:
    sets, versions = await reference_values(db, tenant_id, referenced_sets(doc))
    return compile_document(doc, sets, versions)


async def evaluate(
    db: AsyncSession,
    tenant_id: str,
    key: str,
    facts: Any,
    *,
    as_of: Any = None,
    known_at: Any = None,
    version: int | None = None,
    want_trace: bool = True,
    persist: bool = False,
    idempotency_key: str | None = None,
    caller: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the decision that applies, and describe the version and result."""
    await governance.ensure_fresh()
    try:
        governance.check(tenant_id, "decision", key)
    except governance.Stopped as s:
        raise DecisionError("KILL_SWITCH", s.message(), 423) from None
    snap = await snapshot(db, tenant_id, key)
    if snap is None:
        raise DecisionError("NOT_FOUND", await _not_found(db, tenant_id, key), 404)
    as_of_dt = _as_dt(as_of) or dt.datetime.now(dt.timezone.utc)
    known_dt = _as_dt(known_at) or dt.datetime.now(dt.timezone.utc)
    if version is not None:
        chosen = next((v for v in snap.versions if v.version == int(version)), None)
        if chosen is None:
            chosen = await _version_by_number(db, snap.id, int(version))
        if chosen is None:
            raise DecisionError("NOT_FOUND", f"{key} has no version {version}.", 404)
    else:
        chosen = pick(snap, as_of_dt, known_dt)
    if chosen is None:
        raise DecisionError(
            "NO_VERSION_IN_FORCE",
            f"No published version of {key} applies on {as_of_dt.date().isoformat()}"
            + (f" as known on {known_dt.date().isoformat()}" if known_at else "")
            + ".",
            404,
        )
    ev = await evaluator.evaluate(
        chosen.content_hash,
        chosen.content,
        facts,
        required=chosen.required_facts,
        fact_types=chosen.fact_types,
        as_of=as_of_dt,
        want_trace=want_trace,
    )
    out = {
        "decision": {"key": snap.key, "name": snap.name, "risk_tier": snap.risk_tier},
        "version": chosen.summary(),
        "as_of": as_of_dt.date().isoformat(),
        "known_at": _iso(known_dt) if known_at else None,
        **ev.to_dict(),
    }
    should_log = (
        persist
        or idempotency_key
        or snap.log_mode == "all"
        or (snap.log_mode == "sampled" and int(ev.trace_hash[:2] or "0", 16) < 26)
    )
    if should_log:
        out["evaluation_id"] = await _persist(
            db,
            tenant_id,
            snap.id,
            chosen,
            facts,
            ev,
            out,
            idempotency_key,
            caller,
            known_dt if known_at else None,
        )
    return out


async def _not_found(db: AsyncSession, tenant_id: str, key: str) -> str:
    import difflib

    from models.decision import DecisionModel

    keys = (
        (
            await db.execute(
                select(DecisionModel.key).where(
                    DecisionModel.tenant_id == uuid.UUID(str(tenant_id)),
                    DecisionModel.archived_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    close = difflib.get_close_matches(key, keys, n=3, cutoff=0.5)
    if close:
        return f"There is no decision called {key}. Did you mean {' or '.join(close)}?"
    return f"There is no decision called {key}."


async def _version_by_number(
    db: AsyncSession, model_id: str, number: int
) -> VersionRef | None:
    from models.decision import DecisionVersion

    r = (
        await db.execute(
            select(DecisionVersion).where(
                DecisionVersion.model_id == uuid.UUID(model_id),
                DecisionVersion.version == number,
            )
        )
    ).scalar_one_or_none()
    return _ref(r) if r is not None else None


async def _persist(
    db: AsyncSession,
    tenant_id: str,
    model_id: str,
    v: VersionRef,
    facts: Any,
    ev: evaluator.Evaluation,
    out: dict[str, Any],
    idempotency_key: str | None,
    caller: dict[str, Any] | None,
    known_at: dt.datetime | None,
) -> str:
    from sqlalchemy.dialects.postgresql import insert

    from models.decision import DecisionEvaluation

    pid = uuid.uuid4()
    stmt = (
        insert(DecisionEvaluation)
        .values(
            public_id=pid,
            tenant_id=uuid.UUID(str(tenant_id)),
            model_id=uuid.UUID(model_id),
            version_id=uuid.UUID(v.id),
            content_hash=v.content_hash,
            outcome=ev.outcome,
            facts=facts if isinstance(facts, dict) else {},
            result=ev.result,
            applied_rules=ev.applied_rules,
            trace_hash=ev.trace_hash,
            as_of=out.get("as_of"),
            known_at=known_at,
            idempotency_key=idempotency_key,
            caller=caller,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "idempotency_key"],
            index_where=DecisionEvaluation.idempotency_key.isnot(None),
        )
        .returning(DecisionEvaluation.public_id)
    )
    got = (await db.execute(stmt)).scalar()
    if got is None and idempotency_key:
        prev = (
            await db.execute(
                select(DecisionEvaluation).where(
                    DecisionEvaluation.tenant_id == uuid.UUID(str(tenant_id)),
                    DecisionEvaluation.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one()
        if prev.trace_hash != ev.trace_hash:
            raise DecisionError(
                "IDEMPOTENCY_CONFLICT",
                "This idempotency key was already used for a different evaluation.",
                409,
                evaluation_id=str(prev.public_id),
            )
        await db.commit()
        return str(prev.public_id)
    await db.commit()
    return str(got or pid)


def current_versions_filter(model_id: Any) -> Any:
    from models.decision import DecisionVersion

    return and_(
        DecisionVersion.model_id == model_id,
        DecisionVersion.state == "published",
        or_(DecisionVersion.superseded_at.is_(None)),
    )


async def create_proposal(
    db: AsyncSession,
    tenant_id: str,
    key: str,
    rules_payload: Any,
    *,
    note: str,
    actor_id: str | None,
    actor_label: str,
) -> dict[str, Any]:
    """A new version from typed JSON rules, validated and proposed under the decision's tier."""
    from models.approval import Approval, ApprovalStatus
    from models.decision import DecisionModel, DecisionTest, DecisionVersion

    from engine.decisions import authoring as A
    from engine.decisions import interchange as I
    from engine.decisions import validation as V

    tid = uuid.UUID(str(tenant_id))
    m = (
        await db.execute(
            select(DecisionModel).where(
                DecisionModel.tenant_id == tid,
                DecisionModel.key == key,
                DecisionModel.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise DecisionError("NOT_FOUND", f"There is no decision called {key}.", 404)
    versions = (
        (
            await db.execute(
                select(DecisionVersion).where(DecisionVersion.model_id == m.id)
            )
        )
        .scalars()
        .all()
    )
    live = [v for v in versions if v.state == "published" and v.superseded_at is None]
    base = max(live, key=lambda v: v.version) if live else None
    try:
        doc = I.import_rules(
            rules_payload, base=base.authoring if base and base.authoring else None
        )
    except I.InterchangeError as e:
        raise DecisionError(
            "BAD_RULES",
            f"The rules could not be read at {e.path or 'the top'}: {e.message}",
        ) from None
    sets, refv = await reference_values(db, str(tenant_id), A.referenced_sets(doc))
    problems = A.validate_document(doc, sets)
    if A.has_errors(problems):
        raise DecisionError(
            "VALIDATION_FAILED",
            "The proposed rules have problems: "
            + "; ".join(
                f"{p.path}: {p.message}" for p in problems if p.severity == "error"
            ),
            422,
        )
    c = compile_document(doc, sets, refv)
    tests = (
        (await db.execute(select(DecisionTest).where(DecisionTest.model_id == m.id)))
        .scalars()
        .all()
    )
    results = await V.run_tests(
        c,
        [
            {
                "id": str(t.id),
                "name": t.name,
                "facts": t.facts,
                "expected_outcome": t.expected_outcome,
                "expected": t.expected,
                "as_of": t.as_of,
            }
            for t in tests
        ],
    )
    failed = [r for r in results if not r["passed"]]
    now = dt.datetime.now(dt.timezone.utc)
    v = DecisionVersion(
        tenant_id=tid,
        model_id=m.id,
        version=max((x.version for x in versions), default=0) + 1,
        state="draft" if failed else "proposed",
        authoring=doc,
        content=c.jdm,
        content_hash=c.content_hash,
        required_facts=c.required_facts,
        fact_types=c.fact_types,
        reference_versions=c.reference_versions,
        valid_from=base.valid_from if base else None,
        valid_to=base.valid_to if base else None,
        change_note=note or f"Proposed by {actor_label}",
        provenance={"proposed_by": actor_label},
        author_id=uuid.UUID(actor_id) if actor_id else None,
        base_version_id=base.id if base else None,
        proposed_by=uuid.UUID(actor_id) if actor_id and not failed else None,
        proposed_at=None if failed else now,
        validation={"tests": results, "tests_failed": len(failed)},
    )
    db.add(v)
    await db.flush()
    need = 0
    if not failed:
        pol = (
            governance.policy(str(tenant_id), m.risk_tier).get("publish_approvals")
            or {}
        )
        # an agent's proposal always needs a person to sign
        need = max(1, int(pol.get("min_approvers") or 0))
        a = Approval(
            tenant_id=tid,
            title=f"Publish {m.name} version {v.version}",
            payload={
                "kind": "decision_publish",
                "decision_key": key,
                "version": v.version,
                "risk_tier": m.risk_tier,
                "proposed_by": actor_label,
                "link": f"/decisions/{key}?version={v.version}",
            },
            required_signoffs=need,
            signoffs=[],
            status=ApprovalStatus.pending,
            requested_by=uuid.UUID(actor_id) if actor_id else None,
            gate_kind="decision_publish",
            policy={
                "exclude_requester": bool(pol.get("exclude_author", True)),
                "capability": pol.get("capability") or "approvals.sign",
            },
            expires_at=now + dt.timedelta(days=14),
        )
        db.add(a)
        await db.flush()
        v.approval_id = a.id
    await db.commit()
    return {
        "decision": key,
        "version": v.version,
        "state": v.state,
        "approvals_needed": need,
        "tests_failed": len(failed),
        "failed_tests": [r["name"] for r in failed],
        "link": f"/decisions/{key}?version={v.version}",
    }
