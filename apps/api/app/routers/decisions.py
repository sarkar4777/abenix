"""Decision service API: versioned business rules, authored without code and evaluated by the ZEN engine."""

from __future__ import annotations

import copy
import datetime as dt
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvers import (
    can_sign,
    eligible_from,
    is_self_approved,
    person_json,
    sole_operator_enabled,
    tenant_people,
)
from app.core.audit import log_action
from app.core.capabilities import require_capability
from app.core.deps import async_session, get_db
from app.core.principal import Principal, principal_with
from app.core.responses import error, success
from engine import governance, risk
from engine.decisions import authoring as A
from engine.decisions import interchange as I
from engine.decisions import service as S
from engine.decisions import validation as V
from engine.decisions.evaluator import evaluate as run_compiled
from models.approval import Approval, ApprovalStatus
from models.decision import (
    DecisionEvaluation,
    DecisionModel,
    DecisionTest,
    DecisionVersion,
    ReferenceSet,
    ReferenceSetVersion,
)
from models.user import User

router = APIRouter(prefix="/api/decisions", tags=["decisions"])
refs_router = APIRouter(prefix="/api/decision-reference-sets", tags=["decisions"])

MAX_BATCH = 1000
MAX_FACTS_BYTES = 256_000
PRESENCE_SECONDS = 60
EDITABLE = ("draft",)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", text.strip().lower()).strip("-.")
    return (s or "decision")[:120]


def _iso(v: Any) -> str | None:
    return (
        v.isoformat()
        if v is not None and hasattr(v, "isoformat")
        else (str(v) if v else None)
    )


def _err(e: S.DecisionError) -> JSONResponse:
    return error(e.message, e.status, error_code=e.code, details=e.extra or None)


def _caller(user: User) -> dict[str, Any]:
    return {"user_id": str(user.id), "email": user.email}


async def _model(db: AsyncSession, user: User, key: str) -> DecisionModel | None:
    return (
        await db.execute(
            select(DecisionModel).where(
                DecisionModel.tenant_id == user.tenant_id,
                DecisionModel.key == key,
                DecisionModel.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _archived_model(
    db: AsyncSession, user: User, key: str
) -> DecisionModel | None:
    return (
        await db.execute(
            select(DecisionModel).where(
                DecisionModel.tenant_id == user.tenant_id,
                DecisionModel.key == key,
                DecisionModel.archived_at.is_not(None),
            )
        )
    ).scalar_one_or_none()


async def _version(
    db: AsyncSession, model: DecisionModel, n: int
) -> DecisionVersion | None:
    return (
        await db.execute(
            select(DecisionVersion).where(
                DecisionVersion.model_id == model.id, DecisionVersion.version == n
            )
        )
    ).scalar_one_or_none()


def _keep_returned(old: Any, new: Any) -> Any:
    """Carry a reviewer's return note across edits and checks until the version is proposed again."""
    note = (old or {}).get("returned") if isinstance(old, dict) else None
    if not note:
        return new
    return {**(new or {}), "returned": note}


def _version_summary(
    v: DecisionVersion, names: dict[str, str] | None = None
) -> dict[str, Any]:
    author = str(v.author_id) if v.author_id else None
    return {
        "author_name": ((names or {}).get(author) if author else None)
        or getattr(v, "_author_name", None),
        "id": str(v.id),
        "version": v.version,
        "state": v.state,
        "content_hash": v.content_hash,
        "valid_from": _iso(v.valid_from),
        "valid_to": _iso(v.valid_to),
        "recorded_at": _iso(v.recorded_at),
        "published_at": _iso(v.published_at),
        "superseded_at": _iso(v.superseded_at),
        "change_note": v.change_note,
        "author_id": str(v.author_id) if v.author_id else None,
        "proposed_at": _iso(v.proposed_at),
        "risk_tier_at_proposal": v.risk_tier_at_proposal,
        "attested_under": _attested_under(v),
        "denial": (v.validation or {}).get("denied") if v.state == "rejected" else None,
        "approval_id": str(v.approval_id) if v.approval_id else None,
        "has_builder": v.authoring is not None,
        "etag": str(v.lock_version),
        "updated_at": _iso(v.updated_at),
    }


def _editors(v: DecisionVersion, me: User) -> list[dict[str, Any]]:
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for uid, info in (v.editing_by or {}).items():
        if uid == str(me.id):
            continue
        try:
            at = dt.datetime.fromisoformat(info.get("at"))
        except (TypeError, ValueError):
            continue
        if (now - at).total_seconds() <= PRESENCE_SECONDS:
            out.append(
                {"user_id": uid, "email": info.get("email"), "at": info.get("at")}
            )
    return out


def _fix_wording(text: Any) -> Any:
    from app.routers.approvals import fix_wording

    return fix_wording(text)


def _version_full(v: DecisionVersion, me: User) -> dict[str, Any]:
    return {
        **_version_summary(v),
        "authoring": v.authoring,
        "content": v.content,
        "required_facts": v.required_facts,
        "fact_types": v.fact_types,
        "reference_versions": v.reference_versions,
        "provenance": v.provenance,
        "validation": (
            {**v.validation, "summary": _fix_wording(v.validation.get("summary"))}
            if isinstance(v.validation, dict) and "summary" in v.validation
            else v.validation
        ),
        "base_version_id": str(v.base_version_id) if v.base_version_id else None,
        "editing_now": _editors(v, me),
    }


def _state_of(vs: list[DecisionVersion]) -> str:
    """in_force, retired, draft_only or never_published, from the versions alone."""
    if any(v.state == "published" and v.superseded_at is None for v in vs):
        return "in_force"
    if any(v.published_at is not None for v in vs):
        return "retired"
    if vs and all(v.state in ("draft", "rejected") for v in vs):
        return "draft_only"
    return "never_published"


def _name_of(names: dict[str, str], uid: Any) -> str | None:
    return names.get(str(uid)) if uid else None


def _state_json(
    vs: list[DecisionVersion], names: dict[str, str] | None = None
) -> dict[str, Any]:
    names = names or {}
    live = [v for v in vs if v.state == "published" and v.superseded_at is None]
    return {
        "state": _state_of(vs),
        "in_force_version": max((v.version for v in live), default=None),
        "waiting": [
            {
                "version": v.version,
                "state": v.state,
                "approval_id": str(v.approval_id) if v.approval_id else None,
                "proposed_by_name": _name_of(names, v.proposed_by),
                "proposed_at": _iso(v.proposed_at),
            }
            for v in sorted(vs, key=lambda x: x.version)
            if v.state in ("proposed", "approved")
        ],
    }


async def _names(db: AsyncSession, vs: list[DecisionVersion]) -> dict[str, str]:
    ids = {u for v in vs for u in (v.author_id, v.proposed_by) if u is not None}
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.full_name, User.email).where(User.id.in_(ids))
        )
    ).all()
    return {str(i): (n or e) for i, n, e in rows}


def _model_json(
    m: DecisionModel,
    versions: list[DecisionVersion] | None = None,
    names: dict[str, str] | None = None,
) -> dict[str, Any]:
    vs = versions or []
    live = [v for v in vs if v.state == "published" and v.superseded_at is None]
    names = names or {}
    return {
        **_state_json(vs, names),
        "id": str(m.id),
        "key": m.key,
        "name": m.name,
        "description": m.description,
        "risk_tier": m.risk_tier,
        "tags": m.tags or [],
        "log_mode": m.log_mode,
        "created_at": _iso(m.created_at),
        "updated_at": _iso(m.updated_at),
        "archived_at": _iso(m.archived_at),
        "published": [
            _version_summary(v, names) for v in sorted(live, key=lambda v: v.version)
        ],
        "drafts": [_version_summary(v, names) for v in vs if v.state == "draft"],
        "proposed": [
            _version_summary(v, names)
            for v in vs
            if v.state in ("proposed", "approved")
        ],
        "latest_version": max((v.version for v in vs), default=0),
        "required_facts": (
            max(live, key=lambda v: v.version).required_facts or [] if live else []
        ),
    }


class CreateModelBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    key: str | None = Field(default=None, max_length=160)
    description: str = ""
    risk_tier: str = "low"
    tags: list[str] = Field(default_factory=list)
    rules: Any = None  # optional typed JSON rules to start from


@router.get("")
async def list_models(
    q: str = "",
    archived: int = Query(0, ge=0, le=1),
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    stmt = select(DecisionModel).where(
        DecisionModel.tenant_id == user.tenant_id,
        (
            DecisionModel.archived_at.is_not(None)
            if archived
            else DecisionModel.archived_at.is_(None)
        ),
    )
    if q.strip():
        stmt = stmt.where(*search_terms(q))
    models = (await db.execute(stmt.order_by(DecisionModel.name))).scalars().all()
    ids = [m.id for m in models]
    versions = (
        (
            await db.execute(
                select(DecisionVersion).where(DecisionVersion.model_id.in_(ids))
            )
        )
        .scalars()
        .all()
        if ids
        else []
    )
    by: dict[uuid.UUID, list[DecisionVersion]] = {}
    for v in versions:
        by.setdefault(v.model_id, []).append(v)
    names = await _names(db, list(versions))
    rows = [_model_json(m, by.get(m.id), names) for m in models]
    pending = await _pending_actions(db, user.tenant_id)
    for r in rows:
        r["pending_action"] = pending.get(r["key"])
    meta: dict[str, Any] | None = None
    if q.strip() and not archived:
        n = (
            await db.execute(
                select(func.count()).where(
                    DecisionModel.tenant_id == user.tenant_id,
                    DecisionModel.archived_at.is_not(None),
                    *search_terms(q),
                )
            )
        ).scalar() or 0
        meta = {"archived_matches": int(n)}
    return success(rows, meta=meta)


def search_terms(q: str) -> list[Any]:
    """Every word must appear in the name, key or description, any case. machine stop finds machine-stop."""
    words = [w for w in re.split(r"[\s._-]+", q.strip()) if w][:8]
    out = []
    for w in words:
        like = f"%{w.replace('%', '').replace('_', ' ').strip()}%"
        if like == "%%":
            continue
        out.append(
            DecisionModel.name.ilike(like)
            | DecisionModel.key.ilike(like)
            | DecisionModel.description.ilike(like)
        )
    return out


def _suggest_key(key: str, taken: set[str]) -> str:
    """The next free key in the key.2, key.3 style."""
    base = re.sub(r"\.\d+$", "", key)[:150] or "decision"
    if base not in taken and base != key:
        return base
    i = 2
    while f"{base}.{i}" in taken:
        i += 1
    return f"{base}.{i}"


async def _keys_like(db: AsyncSession, user: User, key: str) -> dict[str, bool]:
    """Keys in the tenant that start like this one, mapped to whether they are archived."""
    base = re.sub(r"\.\d+$", "", key)
    rows = (
        await db.execute(
            select(DecisionModel.key, DecisionModel.archived_at).where(
                DecisionModel.tenant_id == user.tenant_id,
                DecisionModel.key.like(f"{base}%"),
            )
        )
    ).all()
    return {k: a is not None for k, a in rows}


@router.get("/check-key")
async def check_key(
    key: str = Query(..., min_length=1, max_length=200),
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    k = key.strip()
    if not A.KEY_RE.match(k):
        slug = _slug(k)
        taken = await _keys_like(db, user, slug)
        return success(
            {
                "available": False,
                "valid": False,
                "message": "The key can use lowercase letters, digits, dots, dashes and underscores, and starts with a letter or digit.",
                "suggestion": (
                    slug if slug not in taken else _suggest_key(slug, set(taken))
                ),
            }
        )
    taken = await _keys_like(db, user, k)
    if k not in taken:
        return success(
            {"available": True, "valid": True, "suggestion": None, "archived": False}
        )
    return success(
        {
            "available": False,
            "valid": True,
            "archived": taken[k],
            "message": (
                f"{k} belongs to an archived decision. Restore it or use another key."
                if taken[k]
                else f"{k} is already used by another decision."
            ),
            "suggestion": _suggest_key(k, set(taken)),
        }
    )


@router.post("")
async def create_model(
    body: CreateModelBody,
    request: Request,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    key = body.key.strip() if body.key else _slug(body.name)
    if not A.KEY_RE.match(key):
        return error(
            "The key can use lowercase letters, digits, dots, dashes and underscores.",
            400,
        )
    if body.risk_tier not in risk.TIERS:
        return error(f"risk_tier must be one of {', '.join(risk.TIERS)}", 400)
    if await _model(db, user, key) is not None:
        return error(
            f"A decision with the key {key} already exists. Pick another key.", 409
        )
    # an archived decision still holds its key, the insert below used to fail with a 500
    if await _archived_model(db, user, key) is not None:
        return error(
            f"A decision with the key {key} was archived. Restore it or pick another key.",
            409,
            error_code="ARCHIVED",
        )
    doc = A.empty_document()
    if body.rules is not None:
        try:
            doc = I.import_rules(body.rules)
        except I.InterchangeError as e:
            return error(
                f"The rules could not be read at {e.path or 'the top'}: {e.message}",
                400,
            )
    m = DecisionModel(
        tenant_id=user.tenant_id,
        key=key,
        name=body.name.strip(),
        description=body.description,
        risk_tier=body.risk_tier,
        tags=body.tags,
        created_by=user.id,
    )
    db.add(m)
    await db.flush()
    v = await _new_draft(db, user, m, doc, version=1, note="First draft")
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "decision.created",
        {"key": key},
        request,
        resource_type="decision",
        resource_id=key,
    )
    await db.commit()
    await db.refresh(m)
    return success(
        {**_model_json(m, [v]), "draft": _version_full(v, user)}, status_code=201
    )


def _file_problem(path: str, message: str, code: str = "BAD_FILE") -> dict[str, Any]:
    return {"path": path, "message": message, "severity": "error", "code": code}


@router.post("/import")
async def import_file(
    request: Request,
    preview: int = Query(0, ge=0, le=1),
    as_new_key: str | None = Query(None, max_length=160),
    as_new_name: str | None = Query(None, max_length=255),
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """A decision file, ours or Groundwork's {key, name, rules, tests}, into a new decision or a new draft."""
    try:
        payload = await request.json()
    except ValueError:
        return error("The file is not valid JSON.", 400, error_code="BAD_FILE")
    try:
        parts = I.read_file(payload)
    except I.InterchangeError as e:
        msg = f"The file could not be read at {e.path or 'the top'}: {e.message}"
        if preview:
            return success(
                {
                    "creates": False,
                    "key": as_new_key
                    or (payload.get("key") if isinstance(payload, dict) else None),
                    "rules": 0,
                    "tests": 0,
                    "problems": [_file_problem(e.path, msg)],
                }
            )
        return error(msg, 400, error_code="BAD_FILE")
    key = (as_new_key or parts["key"] or "").strip()
    file_problems: list[dict[str, Any]] = []
    blocking: tuple[int, str, str] | None = None
    if not key:
        blocking = (400, "NO_KEY", "The file has no key. Give one to import it under.")
    elif not A.KEY_RE.match(key):
        blocking = (
            400,
            "BAD_KEY",
            "The key can use lowercase letters, digits, dots, dashes and underscores.",
        )
    existing = await _model(db, user, key) if key else None
    archived = (
        await _archived_model(db, user, key) if key and existing is None else None
    )
    if blocking is None and as_new_key and (existing or archived):
        blocking = (
            409,
            "KEY_TAKEN",
            f"{key} is already used. Pick another key to import under.",
        )
    if blocking is None and archived is not None:
        blocking = (
            409,
            "ARCHIVED",
            f"A decision with the key {key} was archived. Restore it, or import under another key.",
        )
    tier = parts["risk_tier"] or (existing.risk_tier if existing else "low")
    if blocking is None and tier not in risk.TIERS:
        blocking = (
            400,
            "BAD_TIER",
            f"risk_tier must be one of {', '.join(risk.TIERS)}",
        )
    doc = parts["doc"]
    normalized: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    sets: dict[str, list[Any]] = {}
    if doc is not None:
        normalized = A.tidy_outcomes(doc)
        sets, _ = await S.reference_values(
            db, str(user.tenant_id), A.referenced_sets(doc)
        )
        problems = _problems_json(A.validate_document(doc, sets))
    tier_note = None
    if existing is not None and tier != existing.risk_tier:
        if risk.above(tier, existing.risk_tier):
            tier_note = f"The decision moves up from {existing.risk_tier} to {tier} risk, as the file says."
        else:
            tier_note = (
                f"The file says {tier} risk, the decision stays {existing.risk_tier}. "
                "Lowering a tier needs sign-off, change it on the decision page."
            )
    if blocking is not None:
        file_problems.append(_file_problem("/key", blocking[2], blocking[1]))
    name = (
        (as_new_name or "").strip()
        or parts["name"]
        or (existing.name if existing else key)
    )
    identical = False
    latest: DecisionVersion | None = None
    have: dict[str, DecisionTest] = {}
    if existing is not None:
        latest = (
            await db.execute(
                select(DecisionVersion)
                .where(DecisionVersion.model_id == existing.id)
                .order_by(desc(DecisionVersion.version))
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest is not None and not A.has_errors(
            A.validate_document(doc, sets) if doc is not None else []
        ):
            if doc is not None:
                incoming = (
                    await S.compile_for(db, str(user.tenant_id), doc)
                ).content_hash
            else:
                incoming = A.content_hash(parts["content"])
            identical = incoming == latest.content_hash
        have = {
            t.name: t
            for t in (
                await db.execute(
                    select(DecisionTest).where(DecisionTest.model_id == existing.id)
                )
            )
            .scalars()
            .all()
        }
    to_add, to_update = _test_changes(have, parts["tests"])
    raises_tier = existing is not None and risk.above(tier, existing.risk_tier)
    if preview:
        taken = key and (existing is not None or archived is not None)
        return success(
            {
                "creates": existing is None,
                "target": "existing" if existing is not None else "new",
                "key": key or None,
                "name": name,
                "name_taken": await _name_taken(db, user, name, key),
                "suggested_key": (
                    await _free_copy_key(db, user, key) if taken else None
                ),
                "identical_to_latest": identical,
                "latest_version": latest.version if latest else None,
                "in_force_version": (
                    _state_json(await _versions_of(db, existing))["in_force_version"]
                    if existing is not None
                    else None
                ),
                "tests_to_add": len(to_add),
                "tests_to_update": len(to_update),
                "risk_tier": tier,
                "rules": len((doc or {}).get("rules") or []),
                "tests": len(parts["tests"]),
                "problems": file_problems + problems,
                "normalized": normalized,
                "tier_note": tier_note,
            }
        )
    if blocking is not None:
        return error(blocking[2], blocking[0], error_code=blocking[1])
    if identical and not to_add and not to_update and not raises_tier:
        return success(
            {
                "created": False,
                "no_changes": True,
                "key": key,
                "version": latest.version if latest else None,
                "draft": None,
                "message": f"Nothing changed. Version {latest.version if latest else ''} of {key} already has these rules and tests.",
            }
        )
    created = existing is None
    reattests: list[dict[str, Any]] = []
    if created:
        m = DecisionModel(
            tenant_id=user.tenant_id,
            key=key,
            name=name[:255],
            description=parts["description"],
            risk_tier=tier,
            tags=parts["tags"],
            created_by=user.id,
        )
        db.add(m)
        await db.flush()
        nxt, base = 1, None
    else:
        m = existing
        vs = (
            (
                await db.execute(
                    select(DecisionVersion).where(DecisionVersion.model_id == m.id)
                )
            )
            .scalars()
            .all()
        )
        nxt = max((x.version for x in vs), default=0) + 1
        live = [x for x in vs if x.state == "published" and x.superseded_at is None]
        base = max(live, key=lambda x: x.version) if live else None
        if risk.above(tier, m.risk_tier):
            locked = any(x.state == "proposed" for x in vs)
            if locked:
                tier_note = f"The file says {tier} risk. A version is waiting for sign-off, so the tier stays {m.risk_tier} for now."
            else:
                await log_action(
                    db,
                    user.tenant_id,
                    user.id,
                    "decision.tier_raised",
                    {"key": key, "from": m.risk_tier, "to": tier, "source": "import"},
                    request,
                    resource_type="decision",
                    resource_id=key,
                    old_value={"risk_tier": m.risk_tier},
                    new_value={"risk_tier": tier},
                )
                was = m.risk_tier
                m.risk_tier = tier
                reattests = await _open_reattests(db, user, m, was, tier)
    note = "Imported from a file"
    v: DecisionVersion | None = None
    if identical:
        # same rules as the latest version, only the tests or the tier move
        pass
    elif doc is not None:
        v = await _new_draft(db, user, m, doc, version=nxt, note=note, base=base)
    else:
        try:
            S.evaluator.compiled(A.content_hash(parts["content"]), parts["content"])
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            return error(
                f"The flow in the file does not compile: {str(exc)[:300]}",
                400,
                error_code="BAD_FLOW",
            )
        v = await _new_draft(
            db,
            user,
            m,
            None,
            version=nxt,
            note=note,
            content=parts["content"],
            base=base,
        )
    for t in to_add:
        db.add(
            DecisionTest(
                tenant_id=user.tenant_id,
                model_id=m.id,
                name=t["name"],
                facts=t["facts"],
                expected_outcome=t["expected_outcome"],
                expected=t["expected"],
                match_mode=t["match"],
                as_of=t["as_of"],
                created_by=user.id,
            )
        )
    for row, t in to_update:
        row.facts, row.expected, row.expected_outcome = (
            t["facts"],
            t["expected"],
            t["expected_outcome"],
        )
        row.match_mode, row.as_of = t["match"], t["as_of"]
    added, updated = len(to_add), len(to_update)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "decision.imported",
        {
            "key": key,
            "version": nxt if v is not None else None,
            "created": created,
            "rules": len((doc or {}).get("rules") or []),
            "tests_added": added,
            "tests_updated": updated,
        },
        request,
        resource_type="decision",
        resource_id=key,
    )
    await db.commit()
    if v is not None:
        await db.refresh(v)
    await S.announce(str(user.tenant_id), key)
    for r in reattests:
        await _announce_approval(db, user, r["approval_id"])
    return success(
        {
            "created": created,
            "no_changes": False,
            "reattests": reattests,
            "key": key,
            "name": m.name,
            "version": nxt if v is not None else (latest.version if latest else None),
            "draft": nxt if v is not None else None,
            "draft_detail": _version_full(v, user) if v is not None else None,
            "risk_tier": m.risk_tier,
            "tests_added": added,
            "tests_updated": updated,
            "problems": problems,
            "normalized": normalized,
            "tier_note": tier_note,
        },
        status_code=201 if v is not None or created else 200,
    )


def _test_changes(
    have: dict[str, Any], tests: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[tuple[Any, dict[str, Any]]]]:
    """Tests a file adds, and existing tests it changes, matched by name."""
    add: list[dict[str, Any]] = []
    upd: list[tuple[Any, dict[str, Any]]] = []
    for t in tests:
        row = have.get(t["name"])
        if row is None:
            add.append(t)
        elif (
            row.facts != t["facts"]
            or row.expected != t["expected"]
            or row.expected_outcome != t["expected_outcome"]
            or (row.match_mode or "exact") != t["match"]
            or (row.as_of or None) != t["as_of"]
        ):
            upd.append((row, t))
    return add, upd


async def _name_taken(db: AsyncSession, user: User, name: str, key: str) -> bool:
    if not name:
        return False
    return bool(
        (
            await db.execute(
                select(DecisionModel.id)
                .where(
                    DecisionModel.tenant_id == user.tenant_id,
                    func.lower(DecisionModel.name) == name.strip().lower(),
                    DecisionModel.key != key,
                )
                .limit(1)
            )
        ).scalar()
    )


async def _free_copy_key(db: AsyncSession, user: User, key: str) -> str:
    base = f"{key}.copy"[:150]
    taken = set(await _keys_like(db, user, base))
    if base not in taken:
        return base
    i = 2
    while f"{base}.{i}" in taken:
        i += 1
    return f"{base}.{i}"


async def _new_draft(
    db: AsyncSession,
    user: User,
    m: DecisionModel,
    doc: dict[str, Any] | None,
    *,
    version: int,
    note: str,
    content: dict[str, Any] | None = None,
    base: DecisionVersion | None = None,
) -> DecisionVersion:
    doc = A.normalize(doc) if doc is not None else None
    if doc is not None:
        A.tidy_outcomes(doc)
        compiled = await S.compile_for(db, str(user.tenant_id), doc)
        content, chash = compiled.jdm, compiled.content_hash
        req, types, refv = (
            compiled.required_facts,
            compiled.fact_types,
            compiled.reference_versions,
        )
    else:
        content = content or {"nodes": [], "edges": []}
        chash = A.content_hash(content)
        req, types, refv = [], {}, {}
    v = DecisionVersion(
        tenant_id=user.tenant_id,
        model_id=m.id,
        version=version,
        state="draft",
        authoring=doc,
        content=content,
        content_hash=chash,
        required_facts=req,
        fact_types=types,
        reference_versions=refv,
        valid_from=base.valid_from if base else None,
        valid_to=base.valid_to if base else None,
        provenance=copy.deepcopy(base.provenance) if base else None,
        change_note=note,
        author_id=user.id,
        base_version_id=base.id if base else None,
        lock_version=1,
    )
    db.add(v)
    await db.flush()
    return v


@router.get("/{key}")
async def get_model(
    key: str,
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    vs = (
        (
            await db.execute(
                select(DecisionVersion)
                .where(DecisionVersion.model_id == m.id)
                .order_by(DecisionVersion.version)
            )
        )
        .scalars()
        .all()
    )
    tests = (
        await db.execute(
            select(func.count())
            .select_from(DecisionTest)
            .where(DecisionTest.model_id == m.id)
        )
    ).scalar() or 0
    names = await _names(db, list(vs))
    out = _model_json(m, list(vs), names)
    out["versions"] = [_version_summary(v, names) for v in vs]
    out["pending_action"] = (await _pending_actions(db, user.tenant_id, key)).get(key)
    out["last_denial"] = await _last_denial(db, user.tenant_id, key)
    out["test_count"] = int(tests)
    out["policy"] = governance.policy(str(user.tenant_id), m.risk_tier)
    out["pending_tier_change"] = await _pending_tier_json(db, user, key)
    out["reattest"] = await _reattest_json(db, user.tenant_id, key)
    return success(out)


REATTEST = "decision_reattest"


def _attested_under(v: DecisionVersion) -> str | None:
    return ((v.validation or {}).get("attested") or {}).get("tier")


def _covered(v: DecisionVersion, a: Approval | None, tier: str, tenant_id: str) -> bool:
    """Whether the sign-off a version already has is enough for this tier."""
    att = _attested_under(v)
    if att and risk.rank(att) >= risk.rank(tier):
        return True
    pa = governance.policy(tenant_id, tier).get("publish_approvals") or {}
    if int(pa.get("min_approvers") or 0) <= 0:
        return True
    if a is None or a.status != ApprovalStatus.approved:
        return False
    yes = [s for s in (a.signoffs or []) if s.get("decision") == "approve"]
    if any(s.get("sole_operator") for s in yes):
        # a sign-off made alone counts for the tier it was made under, never above
        at = v.risk_tier_at_proposal
        return bool(at) and risk.rank(at) >= risk.rank(tier)
    return _signoff_satisfies(a, pa)


async def _pending_reattests(
    db: AsyncSession, tenant_id: Any, key: str
) -> list[Approval]:
    return list(
        (
            await db.execute(
                select(Approval)
                .where(
                    Approval.tenant_id == tenant_id,
                    Approval.gate_kind == REATTEST,
                    Approval.status == ApprovalStatus.pending,
                    Approval.payload["decision_key"].astext == key,
                )
                .order_by(desc(Approval.created_at))
            )
        )
        .scalars()
        .all()
    )


def _reattest_row(a: Approval) -> dict[str, Any]:
    p = a.payload or {}
    status = a.status.value if hasattr(a.status, "value") else str(a.status)
    return {
        "approval_id": str(a.id),
        "version": p.get("version"),
        "from_tier": p.get("from_tier"),
        "to_tier": p.get("to_tier"),
        "status": status,
        "required_signoffs": a.required_signoffs,
        "link": "/approvals",
    }


async def _reattest_json(
    db: AsyncSession, tenant_id: Any, key: str, version: int | None = None
) -> dict[str, Any] | None:
    rows = [
        a
        for a in await _pending_reattests(db, tenant_id, key)
        if version is None or (a.payload or {}).get("version") == version
    ]
    if not rows:
        return None
    return _reattest_row(
        max(rows, key=lambda a: int((a.payload or {}).get("version") or 0))
    )


async def _close_reattests(
    db: AsyncSession,
    tenant_id: Any,
    key: str,
    why: str,
    versions: set[int] | None = None,
    above: str | None = None,
    by: Any = None,
) -> int:
    """Withdraw waiting reviews, for some versions or above a tier."""
    from app.core.approvers import mark_withdrawn

    n = 0
    for a in await _pending_reattests(db, tenant_id, key):
        p = a.payload or {}
        if versions is not None and p.get("version") not in versions:
            continue
        if above is not None and not risk.above(p.get("to_tier"), above):
            continue
        mark_withdrawn(a, why, by)
        n += 1
    return n


async def _open_reattests(
    db: AsyncSession, user: User, m: DecisionModel, from_tier: str, to_tier: str
) -> list[dict[str, Any]]:
    """After a raise, every version in force whose sign-off falls short gets a review at the new tier."""
    from app.services.events import emit

    tid = str(user.tenant_id)
    live = (
        (
            await db.execute(
                select(DecisionVersion)
                .where(S.current_versions_filter(m.id))
                .order_by(DecisionVersion.version)
            )
        )
        .scalars()
        .all()
    )
    pa = governance.policy(tid, to_tier).get("publish_approvals") or {}
    need = int(pa.get("min_approvers") or 0)
    out: list[dict[str, Any]] = []
    for v in live:
        a = await db.get(Approval, v.approval_id) if v.approval_id else None
        if _covered(v, a, to_tier, tid):
            continue
        await _close_reattests(
            db,
            user.tenant_id,
            m.key,
            f"Replaced by a review at {to_tier} risk.",
            versions={v.version},
            by=user.id,
        )
        was = _attested_under(v) or v.risk_tier_at_proposal or from_tier
        r = Approval(
            tenant_id=user.tenant_id,
            title=f"Review {m.name} version {v.version} for {to_tier} risk"[:255],
            payload={
                "kind": REATTEST,
                "decision_key": m.key,
                "version": v.version,
                "from_tier": was,
                "to_tier": to_tier,
                "link": f"/decisions/{m.key}?version={v.version}",
            },
            required_signoffs=max(1, need),
            signoffs=[],
            status=ApprovalStatus.pending,
            requested_by=user.id,
            gate_kind=REATTEST,
            policy={
                "exclude_requester": bool(pa.get("exclude_author")),
                "capability": pa.get("capability") or "approvals.sign",
                "risk_tier": to_tier,
                "escalate_after_hours": int(pa.get("escalate_after_hours") or 0),
                "escalate_after_minutes": risk.escalate_minutes(pa),
            },
        )
        db.add(r)
        await db.flush()
        await emit(
            db,
            user.tenant_id,
            "approval.requested",
            {
                "approval_id": str(r.id),
                "title": r.title,
                "gate_kind": REATTEST,
                "required_signoffs": r.required_signoffs,
            },
        )
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "decision.reattest_requested",
            {
                "key": m.key,
                "version": v.version,
                "from": was,
                "to": to_tier,
                "approval_id": str(r.id),
            },
            None,
            resource_type="decision",
            resource_id=m.key,
        )
        out.append(_reattest_row(r))
    return out


async def _pending_tier_change(
    db: AsyncSession, tenant_id: Any, key: str
) -> Approval | None:
    now = dt.datetime.now(dt.timezone.utc)
    return (
        await db.execute(
            select(Approval)
            .where(
                Approval.tenant_id == tenant_id,
                Approval.gate_kind == "decision_tier_change",
                Approval.status == ApprovalStatus.pending,
                Approval.payload["decision_key"].astext == key,
                (Approval.expires_at.is_(None)) | (Approval.expires_at > now),
            )
            .order_by(desc(Approval.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()


async def _pending_tier_json(
    db: AsyncSession, user: User, key: str
) -> dict[str, Any] | None:
    a = await _pending_tier_change(db, user.tenant_id, key)
    if a is None:
        return None
    who = await db.get(User, a.requested_by) if a.requested_by else None
    p = a.payload or {}
    return {
        "approval_id": str(a.id),
        "from_tier": p.get("from_tier"),
        "to_tier": p.get("to_tier"),
        "reason": p.get("reason"),
        "required_signoffs": a.required_signoffs,
        "requested_by_name": (who.full_name or who.email) if who else None,
        "requested_at": _iso(a.created_at),
    }


def _tier_change(current: str, new: str, need_now: int) -> str:
    """What a tier change does: same, raise, lower_now, or lower_signoff."""
    if risk.normalize(new) == risk.normalize(current):
        return "same"
    if risk.above(new, current):
        return "raise"
    return "lower_now" if need_now <= 0 else "lower_signoff"


def _lock_message(n: int) -> str:
    return f"Version {n} is waiting for sign-off. Withdraw it or let it finish before changing the risk tier."


async def _withdraw_tier_change(
    db: AsyncSession, a: Approval, why: str, by: Any = None
) -> None:
    from app.core.approvers import mark_withdrawn

    mark_withdrawn(a, why, by)


class UpdateModelBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    risk_tier: str | None = None
    tags: list[str] | None = None
    log_mode: str | None = None
    # why the tier goes down, required for a lowering
    reason: str | None = Field(default=None, max_length=1000)


@router.patch("/{key}")
async def update_model(
    key: str,
    body: UpdateModelBody,
    request: Request,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    if body.risk_tier is not None and body.risk_tier not in risk.TIERS:
        return error(f"risk_tier must be one of {', '.join(risk.TIERS)}", 400)
    if body.log_mode is not None and body.log_mode not in ("none", "sampled", "all"):
        return error("log_mode must be none, sampled or all", 400)
    old = {"name": m.name, "risk_tier": m.risk_tier, "log_mode": m.log_mode}
    pending: dict[str, Any] | None = None
    reattests: list[dict[str, Any]] = []
    if body.risk_tier is not None and body.risk_tier != m.risk_tier:
        waiting = (
            await db.execute(
                select(DecisionVersion.version)
                .where(
                    DecisionVersion.model_id == m.id,
                    DecisionVersion.state == "proposed",
                )
                .order_by(DecisionVersion.version)
                .limit(1)
            )
        ).scalar()
        if waiting is not None:
            return error(
                _lock_message(waiting),
                409,
                error_code="TIER_LOCKED",
                details={"version": waiting},
            )
        await governance.ensure_fresh()
        pol = (
            governance.policy(str(user.tenant_id), m.risk_tier).get("publish_approvals")
            or {}
        )
        need = int(pol.get("min_approvers") or 0)
        change = _tier_change(m.risk_tier, body.risk_tier, need)
        reason = (body.reason or "").strip()
        if change in ("lower_now", "lower_signoff") and not reason:
            return error(
                f"Say why {key} should move down from {m.risk_tier} to {body.risk_tier} risk. The reason goes on the record.",
                422,
                error_code="REASON_REQUIRED",
            )
        prior = await _pending_tier_change(db, user.tenant_id, key)
        if change == "lower_signoff" and prior is not None:
            return error(
                f"A change to {(prior.payload or {}).get('to_tier')} risk is already waiting for sign-off. Withdraw it first.",
                409,
                error_code="TIER_CHANGE_PENDING",
                details={"approval_id": str(prior.id)},
            )
        if change == "raise":
            if prior is not None:
                await _withdraw_tier_change(
                    db, prior, f"The tier was raised to {body.risk_tier}.", user.id
                )
            await log_action(
                db,
                user.tenant_id,
                user.id,
                "decision.tier_raised",
                {"key": key, "from": m.risk_tier, "to": body.risk_tier},
                request,
                resource_type="decision",
                resource_id=key,
                old_value={"risk_tier": m.risk_tier},
                new_value={"risk_tier": body.risk_tier},
            )
            was = m.risk_tier
            m.risk_tier = body.risk_tier
            reattests = await _open_reattests(db, user, m, was, body.risk_tier)
        elif change == "lower_now":
            if prior is not None:
                await _withdraw_tier_change(
                    db, prior, f"The tier was set to {body.risk_tier}.", user.id
                )
            await log_action(
                db,
                user.tenant_id,
                user.id,
                "decision.tier_lowered",
                {
                    "key": key,
                    "from": m.risk_tier,
                    "to": body.risk_tier,
                    "reason": reason,
                    "approved_by": [],
                    "needed_signoff": False,
                },
                request,
                resource_type="decision",
                resource_id=key,
                old_value={"risk_tier": m.risk_tier},
                new_value={"risk_tier": body.risk_tier},
            )
            m.risk_tier = body.risk_tier
            await _close_reattests(
                db,
                user.tenant_id,
                key,
                f"The tier was lowered to {body.risk_tier}.",
                above=body.risk_tier,
                by=user.id,
            )
        elif change == "lower_signoff":
            pending = await _request_tier_change(
                db, user, m, body.risk_tier, reason, need, pol
            )
    for f in ("name", "description", "tags", "log_mode"):
        val = getattr(body, f)
        if val is not None:
            setattr(m, f, val)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "decision.updated",
        None,
        request,
        resource_type="decision",
        resource_id=key,
        old_value=old,
        new_value={"name": m.name, "risk_tier": m.risk_tier, "log_mode": m.log_mode},
    )
    await db.commit()
    await S.announce(str(user.tenant_id), key)
    out = {
        "key": m.key,
        "name": m.name,
        "risk_tier": m.risk_tier,
        "log_mode": m.log_mode,
    }
    for r in reattests:
        await _announce_approval(db, user, r["approval_id"])
    if reattests:
        out["reattest"] = max(reattests, key=lambda r: r["version"])
    if pending is not None:
        await _announce_approval(db, user, pending["approval_id"])
        return success({**out, "pending_tier_change": pending}, status_code=202)
    return success(out)


async def _request_tier_change(
    db: AsyncSession,
    user: User,
    m: DecisionModel,
    to_tier: str,
    reason: str,
    need: int,
    pol: dict[str, Any],
) -> dict[str, Any]:
    """A lowering waits for the sign-off the current tier asks of a publish."""
    from app.services.events import emit

    now = dt.datetime.now(dt.timezone.utc)
    title = f"Lower {m.name} from {m.risk_tier} to {to_tier} risk"
    a = Approval(
        tenant_id=user.tenant_id,
        title=title[:255],
        payload={
            "kind": "decision_tier_change",
            "decision_key": m.key,
            "from_tier": m.risk_tier,
            "to_tier": to_tier,
            "reason": reason,
            "link": f"/decisions/{m.key}",
        },
        required_signoffs=need,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=user.id,
        gate_kind="decision_tier_change",
        policy={
            "exclude_requester": True,
            "capability": pol.get("capability") or "approvals.sign",
            "risk_tier": m.risk_tier,
            "escalate_after_hours": int(pol.get("escalate_after_hours") or 0),
            "escalate_after_minutes": risk.escalate_minutes(pol),
        },
        expires_at=now + dt.timedelta(days=14),
    )
    db.add(a)
    await db.flush()
    await emit(
        db,
        user.tenant_id,
        "approval.requested",
        {
            "approval_id": str(a.id),
            "title": a.title,
            "gate_kind": "decision_tier_change",
            "required_signoffs": need,
        },
    )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "decision.tier_change_requested",
        {
            "key": m.key,
            "from": m.risk_tier,
            "to": to_tier,
            "reason": reason,
            "approval_id": str(a.id),
            "required_signoffs": need,
        },
        None,
        resource_type="decision",
        resource_id=m.key,
    )
    return {
        "approval_id": str(a.id),
        "from_tier": m.risk_tier,
        "to_tier": to_tier,
        "required_signoffs": need,
    }


async def _announce_approval(db: AsyncSession, user: User, approval_id: str) -> None:
    """Signers hear about it the way every other approval request reaches them."""
    try:
        from app.routers.approvals import _notify_pending

        approval = await db.get(Approval, uuid.UUID(approval_id))
        if approval is not None:
            await _notify_pending(db, approval, requester=user)
    except Exception as e:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "decision approval notification failed: %s", e
        )


@router.delete("/{key}/tier-change")
async def withdraw_tier_change(
    key: str,
    request: Request,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    a = await _pending_tier_change(db, user.tenant_id, key)
    if a is None:
        return error(f"{key} has no tier change waiting for sign-off.", 404)
    await _withdraw_tier_change(
        db, a, "The person who asked for it took it back.", user.id
    )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "decision.tier_change_withdrawn",
        {
            "key": key,
            "approval_id": str(a.id),
            **{k: (a.payload or {}).get(k) for k in ("from_tier", "to_tier")},
        },
        request,
        resource_type="decision",
        resource_id=key,
    )
    await db.commit()
    return success(
        {"withdrawn": True, "approval_id": str(a.id), "risk_tier": m.risk_tier}
    )


ACTION_KINDS = {
    "decision_retire": "retire",
    "decision_archive": "archive",
    "decision_restore": "restore",
}


class ActionBody(BaseModel):
    # why, required where the tier asks for sign-off
    reason: str | None = Field(default=None, max_length=1000)


def _needs_signoff(tenant_id: Any, tier: str) -> tuple[int, dict[str, Any]]:
    pa = governance.policy(str(tenant_id), tier).get("publish_approvals") or {}
    return int(pa.get("min_approvers") or 0), pa


async def _pending_actions(
    db: AsyncSession, tenant_id: Any, key: str | None = None
) -> dict[str, dict[str, Any]]:
    """Retire, archive or restore requests waiting for sign-off, by decision key."""
    now = dt.datetime.now(dt.timezone.utc)
    stmt = select(Approval).where(
        Approval.tenant_id == tenant_id,
        Approval.gate_kind.in_(tuple(ACTION_KINDS)),
        Approval.status == ApprovalStatus.pending,
        (Approval.expires_at.is_(None)) | (Approval.expires_at > now),
    )
    if key is not None:
        stmt = stmt.where(Approval.payload["decision_key"].astext == key)
    rows = (await db.execute(stmt.order_by(desc(Approval.created_at)))).scalars().all()
    ids = {a.requested_by for a in rows if a.requested_by}
    names: dict[str, str] = {}
    if ids:
        for i, n, e in (
            await db.execute(
                select(User.id, User.full_name, User.email).where(User.id.in_(ids))
            )
        ).all():
            names[str(i)] = n or e
    out: dict[str, dict[str, Any]] = {}
    for a in rows:
        p = a.payload or {}
        k = p.get("decision_key")
        if k in out:
            continue
        out[k] = {
            "approval_id": str(a.id),
            "kind": ACTION_KINDS.get(a.gate_kind or "", a.gate_kind),
            "version": p.get("version"),
            "reason": p.get("reason"),
            "tier": p.get("tier"),
            "required_signoffs": a.required_signoffs,
            "requested_by_name": names.get(str(a.requested_by)),
            "requested_at": _iso(a.created_at),
        }
    return out


async def _last_denial(
    db: AsyncSession, tenant_id: Any, key: str
) -> dict[str, Any] | None:
    from app.core.approvers import DECISION_KINDS

    a = (
        await db.execute(
            select(Approval)
            .where(
                Approval.tenant_id == tenant_id,
                Approval.gate_kind.in_(DECISION_KINDS),
                Approval.status == ApprovalStatus.denied,
                Approval.payload["decision_key"].astext == key,
            )
            .order_by(desc(Approval.decided_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if a is None:
        return None
    s = next((x for x in reversed(a.signoffs or []) if x.get("decision") == "deny"), {})
    who = None
    if s.get("user_id"):
        try:
            u = await db.get(User, uuid.UUID(str(s["user_id"])))
        except ValueError:
            u = None
        who = (u.full_name or u.email) if u else s.get("user_email")
    return {
        "approval_id": str(a.id),
        "kind": a.gate_kind,
        "version": (a.payload or {}).get("version"),
        "reason": s.get("reason") or None,
        "by_name": who,
        "at": _iso(a.decided_at),
    }


async def _request_action(
    db: AsyncSession,
    user: User,
    m: DecisionModel,
    gate_kind: str,
    reason: str,
    need: int,
    pa: dict[str, Any],
    version: int | None = None,
) -> dict[str, Any]:
    """Retire, archive or restore at a tier that asks for sign-off waits for it."""
    from app.services.events import emit

    verb = ACTION_KINDS[gate_kind]
    what = f"version {version} of {m.name}" if version else m.name
    payload: dict[str, Any] = {
        "kind": gate_kind,
        "decision_key": m.key,
        "tier": m.risk_tier,
        "reason": reason,
        "link": f"/decisions/{m.key}" if verb != "restore" else "/decisions?archived=1",
    }
    if version is not None:
        payload["version"] = version
    a = Approval(
        tenant_id=user.tenant_id,
        title=f"{verb.capitalize()} {what} ({m.risk_tier} risk)"[:255],
        payload=payload,
        required_signoffs=need,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=user.id,
        gate_kind=gate_kind,
        policy={
            "exclude_requester": bool(pa.get("exclude_author")),
            "capability": pa.get("capability") or "approvals.sign",
            "risk_tier": m.risk_tier,
            "escalate_after_hours": int(pa.get("escalate_after_hours") or 0),
            "escalate_after_minutes": risk.escalate_minutes(pa),
        },
        expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=14),
    )
    db.add(a)
    await db.flush()
    await emit(
        db,
        user.tenant_id,
        "approval.requested",
        {
            "approval_id": str(a.id),
            "title": a.title,
            "gate_kind": gate_kind,
            "required_signoffs": need,
        },
    )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        f"decision.{verb}_requested",
        {"key": m.key, "version": version, "reason": reason, "approval_id": str(a.id)},
        None,
        resource_type="decision",
        resource_id=m.key,
    )
    return {"approval_id": str(a.id), "kind": verb, "required_signoffs": need}


def _pending_words(m: DecisionModel, waiting: dict[str, Any]) -> str:
    """Who already asked to retire, archive or restore this decision, and when."""
    what = {"retire": "retire a version of", "archive": "archive", "restore": "restore"}
    verb = what.get(waiting.get("kind") or "", waiting.get("kind") or "change")
    who = waiting.get("requested_by_name") or "Someone"
    when = ""
    at = waiting.get("requested_at")
    if at:
        try:
            when = " on " + dt.datetime.fromisoformat(at).strftime(
                "%d %b %Y at %H:%M UTC"
            )
        except ValueError:
            when = ""
    return (
        f"{who} already asked{when} to {verb} {m.name}, and it is waiting for sign-off. "
        "It can be approved or denied on Approvals."
    )


async def _guard_action(
    db: AsyncSession, user: User, m: DecisionModel, reason: str
) -> tuple[JSONResponse | None, int, dict[str, Any]]:
    """None to act at once, an error, or the sign-off a request needs."""
    await governance.ensure_fresh()
    need, pa = _needs_signoff(user.tenant_id, m.risk_tier)
    if need <= 0:
        return None, 0, pa
    if not reason:
        return (
            error(
                f"{m.key} is {m.risk_tier} risk, so this needs sign-off. Say why, the approvers see the reason.",
                422,
                error_code="REASON_REQUIRED",
            ),
            need,
            pa,
        )
    waiting = (await _pending_actions(db, user.tenant_id, m.key)).get(m.key)
    if waiting:
        return (
            error(
                _pending_words(m, waiting),
                409,
                error_code="ACTION_PENDING",
                details={
                    "approval_id": waiting["approval_id"],
                    "kind": waiting["kind"],
                    "requested_by_name": waiting.get("requested_by_name"),
                    "requested_at": waiting.get("requested_at"),
                },
            ),
            need,
            pa,
        )
    return None, need, pa


ARCHIVED_WITHDRAWN = "The decision was archived."
ARCHIVED_REFUSAL = (
    "This decision was archived, so there is nothing to approve. It has been withdrawn."
)


async def _withdraw_open(
    db: AsyncSession,
    tenant_id: Any,
    key: str,
    why: str,
    *,
    kinds: tuple[str, ...] | None = None,
    versions: set[int] | None = None,
    keep: Any = None,
    by: Any = None,
) -> list[Approval]:
    """Withdraw a decision's open approvals, the ones of these kinds and versions, except keep."""
    from app.core.approvers import DECISION_KINDS, mark_withdrawn

    rows = (
        (
            await db.execute(
                select(Approval).where(
                    Approval.tenant_id == tenant_id,
                    Approval.gate_kind.in_(kinds or DECISION_KINDS),
                    Approval.status == ApprovalStatus.pending,
                    Approval.payload["decision_key"].astext == key,
                )
            )
        )
        .scalars()
        .all()
    )
    out = []
    for a in rows:
        p = a.payload or {}
        if keep is not None and str(a.id) == str(keep):
            continue
        if versions is not None and p.get("version") not in versions:
            continue
        mark_withdrawn(a, why, by)
        out.append(a)
    return out


async def _versions_back_to_draft(db: AsyncSession, m: DecisionModel) -> list[int]:
    """Proposed or approved versions of an archived decision go back to drafts."""
    vs = (
        (
            await db.execute(
                select(DecisionVersion).where(
                    DecisionVersion.model_id == m.id,
                    DecisionVersion.state.in_(("proposed", "approved")),
                )
            )
        )
        .scalars()
        .all()
    )
    for v in vs:
        v.state = "draft"
        v.approval_id = None
        v.risk_tier_at_proposal = None
        v.lock_version = (v.lock_version or 1) + 1
    return [v.version for v in vs]


async def tell_withdrawn(db: AsyncSession, rows: list[Approval], why: str) -> None:
    """The person who asked hears that their request was withdrawn and why."""
    if not rows:
        return
    from app.core.notifications import create_notification

    for a in rows:
        if not a.requested_by:
            continue
        try:
            await create_notification(
                db,
                tenant_id=a.tenant_id,
                user_id=a.requested_by,
                type="approval_resolved",
                title=(a.title or "Approval withdrawn")[:80],
                message=f"Your request was withdrawn. {why}",
                link=(a.payload or {}).get("link") or "/approvals",
                metadata={
                    "approval_id": str(a.id),
                    "status": "withdrawn",
                    "gate_kind": a.gate_kind,
                },
            )
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning("withdrawal notice failed: %s", e)
    # notifications are only flushed, the caller's work is already committed
    await db.commit()


async def sweep_archived(db: AsyncSession, tenant_id: Any) -> int:
    """Withdraw approvals still open for decisions that were archived. Commits when it changes anything."""
    from app.core.approvers import DECISION_KINDS

    kinds = tuple(k for k in DECISION_KINDS if k != "decision_restore")
    archived = select(DecisionModel.key).where(
        DecisionModel.tenant_id == tenant_id, DecisionModel.archived_at.is_not(None)
    )
    rows = (
        (
            await db.execute(
                select(Approval).where(
                    Approval.tenant_id == tenant_id,
                    Approval.gate_kind.in_(kinds),
                    Approval.status == ApprovalStatus.pending,
                    Approval.payload["decision_key"].astext.in_(archived),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0
    from app.core.approvers import mark_withdrawn

    keys = set()
    for a in rows:
        mark_withdrawn(a, ARCHIVED_WITHDRAWN, None)
        keys.add((a.payload or {}).get("decision_key"))
    for m in (
        (
            await db.execute(
                select(DecisionModel).where(
                    DecisionModel.tenant_id == tenant_id,
                    DecisionModel.key.in_(keys),
                    DecisionModel.archived_at.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    ):
        await _versions_back_to_draft(db, m)
    await db.commit()
    await tell_withdrawn(db, list(rows), ARCHIVED_WITHDRAWN)
    return len(rows)


async def archived_key(db: AsyncSession, tenant_id: Any, key: str | None) -> bool:
    if not key:
        return False
    return bool(
        (
            await db.execute(
                select(DecisionModel.id)
                .where(
                    DecisionModel.tenant_id == tenant_id,
                    DecisionModel.key == key,
                    DecisionModel.archived_at.is_not(None),
                )
                .limit(1)
            )
        ).scalar()
    )


async def _do_archive(
    db: AsyncSession,
    tenant_id: Any,
    actor: Any,
    m: DecisionModel,
    request: Request | None,
    extra: dict[str, Any],
    keep: Any = None,
) -> list[Approval]:
    m.archived_at = dt.datetime.now(dt.timezone.utc)
    # nothing about an archived decision is left for anyone to approve
    withdrawn = await _withdraw_open(
        db, tenant_id, m.key, ARCHIVED_WITHDRAWN, keep=keep, by=actor
    )
    drafts = await _versions_back_to_draft(db, m)
    extra = {
        **extra,
        "withdrawn_approvals": [str(a.id) for a in withdrawn],
        "back_to_draft": drafts,
    }
    await log_action(
        db,
        tenant_id,
        actor,
        "decision.archived",
        {"key": m.key, **extra},
        request,
        resource_type="decision",
        resource_id=m.key,
    )
    return withdrawn


async def _do_restore(
    db: AsyncSession,
    tenant_id: Any,
    actor: Any,
    m: DecisionModel,
    request: Request | None,
    extra: dict[str, Any],
) -> None:
    m.archived_at = None
    await log_action(
        db,
        tenant_id,
        actor,
        "decision.restored",
        {"key": m.key, **extra},
        request,
        resource_type="decision",
        resource_id=m.key,
    )


async def _do_retire(
    db: AsyncSession,
    tenant_id: Any,
    actor: Any,
    m: DecisionModel,
    v: DecisionVersion,
    request: Request | None,
    extra: dict[str, Any],
) -> None:
    from app.services.events import emit

    v.state = "retired"
    v.superseded_at = dt.datetime.now(dt.timezone.utc)
    await _close_reattests(
        db,
        tenant_id,
        m.key,
        f"Version {v.version} was retired.",
        versions={v.version},
        by=actor,
    )
    # a second retire request for the same version has nothing left to do
    await _withdraw_open(
        db,
        tenant_id,
        m.key,
        f"Version {v.version} was retired.",
        kinds=("decision_retire",),
        versions={v.version},
        keep=extra.get("approval_id"),
        by=actor,
    )
    await emit(
        db, tenant_id, "decision.retired", {"decision_key": m.key, "version": v.version}
    )
    await log_action(
        db,
        tenant_id,
        actor,
        "decision.retired",
        {"key": m.key, "version": v.version, **extra},
        request,
        resource_type="decision",
        resource_id=m.key,
    )


NEVER_PUBLISHED = "Nothing was ever published, so no sign-off was needed."


async def _ever_published(db: AsyncSession, m: DecisionModel) -> bool:
    """Whether any version of this decision was ever in force."""
    return bool(
        (
            await db.execute(
                select(DecisionVersion.id)
                .where(
                    DecisionVersion.model_id == m.id,
                    DecisionVersion.published_at.is_not(None),
                )
                .limit(1)
            )
        ).scalar()
    )


async def _versions_of(db: AsyncSession, m: DecisionModel) -> list[DecisionVersion]:
    return list(
        (
            await db.execute(
                select(DecisionVersion)
                .where(DecisionVersion.model_id == m.id)
                .order_by(DecisionVersion.version)
            )
        )
        .scalars()
        .all()
    )


@router.delete("/{key}")
async def archive_model(
    key: str,
    request: Request,
    body: ActionBody | None = None,
    reason: str | None = Query(None, max_length=1000),
    user: User = Depends(require_capability("decisions.publish")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    why = ((body.reason if body else None) or reason or "").strip()
    never = not await _ever_published(db, m)
    if not never:
        refused, need, pa = await _guard_action(db, user, m, why)
        if refused is not None:
            return refused
        if need > 0:
            pending = await _request_action(
                db, user, m, "decision_archive", why, need, pa
            )
            await db.commit()
            await _announce_approval(db, user, pending["approval_id"])
            return success({"pending": pending}, status_code=202)
    withdrawn = await _do_archive(
        db,
        user.tenant_id,
        user.id,
        m,
        request,
        {"reason": why or None, "never_published": never},
    )
    await db.commit()
    await tell_withdrawn(db, withdrawn, ARCHIVED_WITHDRAWN)
    await S.announce(str(user.tenant_id), key)
    out: dict[str, Any] = {"archived": True, "key": key}
    if never:
        out["reason"] = NEVER_PUBLISHED
    return success(out)


@router.post("/{key}/restore")
async def restore_model(
    key: str,
    request: Request,
    body: ActionBody | None = None,
    user: User = Depends(require_capability("decisions.publish")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if await _model(db, user, key) is not None:
        return error(f"{key} is not archived.", 409)
    m = await _archived_model(db, user, key)
    if m is None:
        return error(f"There is no archived decision called {key}.", 404)
    why = ((body.reason if body else None) or "").strip()
    never = not await _ever_published(db, m)
    if not never:
        refused, need, pa = await _guard_action(db, user, m, why)
        if refused is not None:
            return refused
        if need > 0:
            pending = await _request_action(
                db, user, m, "decision_restore", why, need, pa
            )
            await db.commit()
            await _announce_approval(db, user, pending["approval_id"])
            return success({"pending": pending}, status_code=202)
    await _do_restore(
        db,
        user.tenant_id,
        user.id,
        m,
        request,
        {"reason": why or None, "never_published": never},
    )
    await db.commit()
    await S.announce(str(user.tenant_id), key)
    out = {"restored": True, "key": key, **_state_json(await _versions_of(db, m))}
    if never:
        out["reason"] = NEVER_PUBLISHED
    return success(out)


@router.get("/{key}/versions/{n}")
async def get_version(
    key: str,
    n: int,
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    v = await _version(db, m, n) if m else None
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    v._author_name = (await _names(db, [v])).get(str(v.author_id))
    out = _version_full(v, user)
    attested = (out.get("validation") or {}).get("attested")
    if isinstance(attested, dict):
        out["validation"] = {
            **out["validation"],
            "attested": await _with_approver_names(db, attested),
        }
    return success(out)


async def _user_names(db: AsyncSession, ids: list[Any]) -> dict[str, str]:
    wanted = set()
    for i in ids:
        try:
            wanted.add(uuid.UUID(str(i)))
        except (TypeError, ValueError):
            continue
    if not wanted:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.full_name, User.email).where(User.id.in_(wanted))
        )
    ).all()
    return {str(i): (n or e) for i, n, e in rows}


async def _with_approver_names(
    db: AsyncSession, attested: dict[str, Any]
) -> dict[str, Any]:
    """The review's approvers by name as well as by id."""
    if attested.get("approved_by_names"):
        return attested
    ids = list(attested.get("approved_by") or [])
    names = await _user_names(db, ids)
    return {**attested, "approved_by_names": [names.get(str(i)) or str(i) for i in ids]}


@router.delete("/{key}/versions/{n}")
async def discard_draft(
    key: str,
    n: int,
    request: Request,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.capabilities import has_capability

    m = await _model(db, user, key)
    v = await _version(db, m, n) if m else None
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    if v.state not in ("draft", "rejected"):
        return error(
            f"Version {n} is {v.state}. Only a draft can be discarded, withdraw a proposal first.",
            409,
            error_code="NOT_A_DRAFT",
        )
    if str(v.author_id) != str(user.id) and not await has_capability(
        db, user, "decisions.publish"
    ):
        return error(
            "Only the person who wrote this draft, or someone who can publish decisions, can discard it.",
            403,
            error_code="NOT_YOUR_DRAFT",
        )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "decision.draft_discarded",
        {
            "key": key,
            "version": n,
            "author_id": str(v.author_id) if v.author_id else None,
        },
        request,
        resource_type="decision",
        resource_id=key,
    )
    await db.delete(v)
    await db.commit()
    return success({"discarded": True, "key": key, "version": n})


class NewDraftBody(BaseModel):
    from_version: int | None = None
    note: str = ""


@router.post("/{key}/versions")
async def new_draft(
    key: str,
    body: NewDraftBody,
    request: Request,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    vs = (
        (
            await db.execute(
                select(DecisionVersion).where(DecisionVersion.model_id == m.id)
            )
        )
        .scalars()
        .all()
    )
    base: DecisionVersion | None = None
    if body.from_version is not None:
        base = next((v for v in vs if v.version == body.from_version), None)
        if base is None:
            return error(f"{key} has no version {body.from_version}.", 404)
    else:
        live = [v for v in vs if v.state == "published" and v.superseded_at is None]
        base = (
            max(live, key=lambda v: v.version)
            if live
            else (max(vs, key=lambda v: v.version) if vs else None)
        )
    nxt = max((v.version for v in vs), default=0) + 1
    v = await _new_draft(
        db,
        user,
        m,
        (
            copy.deepcopy(base.authoring)
            if base and base.authoring is not None
            else (None if base else A.empty_document())
        ),
        version=nxt,
        note=body.note
        or (f"Draft from version {base.version}" if base else "New draft"),
        content=copy.deepcopy(base.content) if base else None,
        base=base,
    )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "decision.draft_created",
        {"key": key, "version": nxt},
        request,
        resource_type="decision",
        resource_id=key,
    )
    await db.commit()
    await db.refresh(v)
    return success(_version_full(v, user), status_code=201)


class SaveBody(BaseModel):
    authoring: dict[str, Any] | None = None
    content: dict[str, Any] | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    change_note: str | None = None
    provenance: dict[str, Any] | None = None
    clear_valid_to: bool = False
    clear_valid_from: bool = False


def _problems_json(problems: list[A.Problem]) -> list[dict[str, Any]]:
    return [p.to_dict() for p in problems]


@router.put("/{key}/versions/{n}")
async def save_draft(
    key: str,
    n: int,
    body: SaveBody,
    request: Request,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    v = await _version(db, m, n) if m else None
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    if v.state not in EDITABLE:
        return error(
            f"Version {n} is {v.state} and can no longer change. Start a new draft from it to make changes.",
            409,
            error_code="NOT_EDITABLE",
        )
    if if_match is not None and if_match.strip('"') != str(v.lock_version):
        return error(
            "Someone saved this draft after you opened it. Your changes were not saved. "
            "Review their version, then apply your changes again.",
            409,
            error_code="STALE_DRAFT",
            details={"current": _version_full(v, user)},
        )
    problems: list[A.Problem] = []
    normalized: list[dict[str, Any]] = []
    if body.authoring is not None:
        doc = A.normalize(body.authoring)
        normalized = A.tidy_outcomes(doc)
        sets, versions = await S.reference_values(
            db, str(user.tenant_id), A.referenced_sets(doc)
        )
        problems = A.validate_document(doc, sets)
        v.authoring = doc
        if not A.has_errors(problems):
            c = A.compile_document(doc, sets, versions)
            v.content, v.content_hash = c.jdm, c.content_hash
            v.required_facts, v.fact_types, v.reference_versions = (
                c.required_facts,
                c.fact_types,
                c.reference_versions,
            )
    elif body.content is not None:
        try:
            S.evaluator.compiled(A.content_hash(body.content), body.content)
        except Exception as exc:  # noqa: BLE001
            return error(
                f"The flow could not be compiled: {str(exc)[:300]}",
                400,
                error_code="BAD_FLOW",
            )
        v.content = body.content
        v.content_hash = A.content_hash(body.content)
        # the flow view owns this version now, the builder document no longer describes it
        v.authoring = None
    try:
        if body.valid_from is not None or body.clear_valid_from:
            v.valid_from = None if body.clear_valid_from else S._as_dt(body.valid_from)
        if body.valid_to is not None or body.clear_valid_to:
            v.valid_to = None if body.clear_valid_to else S._as_dt(body.valid_to)
    except ValueError:
        return error("Use dates like 2026-01-01 for the valid period.", 400)
    if v.valid_from and v.valid_to and v.valid_to <= v.valid_from:
        problems.append(
            A.Problem(
                "/valid_to", "The end of the valid period must be after the start."
            )
        )
    if body.change_note is not None:
        v.change_note = body.change_note
    if body.provenance is not None:
        v.provenance = body.provenance
    v.lock_version = (v.lock_version or 1) + 1
    v.validation = _keep_returned(v.validation, None)
    eds = dict(v.editing_by or {})
    eds[str(user.id)] = {
        "email": user.email,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    v.editing_by = eds
    await db.commit()
    await db.refresh(v)
    return success(
        {
            **_version_full(v, user),
            "problems": _problems_json(problems),
            "normalized": normalized,
        }
    )


@router.post("/{key}/versions/{n}/presence")
async def presence(
    key: str,
    n: int,
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    v = await _version(db, m, n) if m else None
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    eds = dict(v.editing_by or {})
    eds[str(user.id)] = {
        "email": user.email,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    v.editing_by = eds
    await db.commit()
    return success({"editing_now": _editors(v, user), "etag": str(v.lock_version)})


class CheckBody(BaseModel):
    authoring: dict[str, Any]


@router.post("/{key}/check")
async def check_document(
    key: str,
    body: CheckBody,
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Validation as the author types, without saving."""
    doc = A.normalize(body.authoring)
    normalized = A.tidy_outcomes(doc)
    sets, versions = await S.reference_values(
        db, str(user.tenant_id), A.referenced_sets(doc)
    )
    problems = A.validate_document(doc, sets)
    out: dict[str, Any] = {
        "problems": _problems_json(problems),
        "normalized": normalized,
    }
    if not A.has_errors(problems):
        out["overlaps"] = V.overlaps(doc, sets)
        c = A.compile_document(doc, sets, versions)
        out["required_facts"] = c.required_facts
        out["fact_types"] = c.fact_types
    return success(out)


class TryBody(BaseModel):
    facts: dict[str, Any] = Field(default_factory=dict)
    as_of: str | None = None
    authoring: dict[str, Any] | None = None


@router.post("/{key}/versions/{n}/try")
async def try_version(
    key: str,
    n: int,
    body: TryBody,
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Evaluate any version, or unsaved builder content, against sample facts."""
    m = await _model(db, user, key)
    v = await _version(db, m, n) if m else None
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    if body.authoring is not None:
        doc = A.normalize(body.authoring)
        sets, versions = await S.reference_values(
            db, str(user.tenant_id), A.referenced_sets(doc)
        )
        problems = A.validate_document(doc, sets)
        if A.has_errors(problems):
            return success(
                {"outcome": "not_ready", "problems": _problems_json(problems)}
            )
        c = A.compile_document(doc, sets, versions)
        jdm, chash, req, types = c.jdm, c.content_hash, c.required_facts, c.fact_types
    else:
        jdm, chash, req, types = (
            v.content,
            v.content_hash,
            v.required_facts,
            v.fact_types,
        )
    try:
        ev = await run_compiled(
            chash,
            jdm,
            body.facts,
            required=req,
            fact_types=types,
            as_of=body.as_of or None,
        )
    except Exception as exc:  # noqa: BLE001
        return error(
            f"The decision could not run: {str(exc)[:300]}",
            400,
            error_code="ENGINE_ERROR",
        )
    return success({**ev.to_dict(), "required_facts": req, "fact_types": types})


async def _compiled_of(v: DecisionVersion) -> A.Compiled:
    return A.Compiled(
        jdm=v.content,
        content_hash=v.content_hash,
        required_facts=list(v.required_facts or []),
        fact_types=dict(v.fact_types or {}),
        reference_versions=dict(v.reference_versions or {}),
    )


async def _tests_of(db: AsyncSession, m: DecisionModel) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(DecisionTest)
                .where(DecisionTest.model_id == m.id)
                .order_by(DecisionTest.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_test_json(t) for t in rows]


def _test_json(t: DecisionTest) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "name": t.name,
        "facts": t.facts,
        "expected_outcome": t.expected_outcome,
        "expected": t.expected,
        "match": t.match_mode or "exact",
        "as_of": t.as_of or None,
        "updated_at": _iso(t.updated_at),
    }


async def _validate(
    db: AsyncSession, user: User, m: DecisionModel, v: DecisionVersion
) -> dict[str, Any]:
    problems: list[A.Problem] = []
    overlaps: list[dict[str, Any]] = []
    if v.authoring is not None:
        sets, _ = await S.reference_values(
            db, str(user.tenant_id), A.referenced_sets(v.authoring)
        )
        problems = A.validate_document(v.authoring, sets)
        if not A.has_errors(problems):
            overlaps = V.overlaps(v.authoring, sets)
    else:
        try:
            S.evaluator.compiled(v.content_hash, v.content)
        except Exception as exc:  # noqa: BLE001
            problems.append(
                A.Problem("/content", f"The flow does not compile: {str(exc)[:300]}")
            )
    if v.valid_from and v.valid_to and v.valid_to <= v.valid_from:
        problems.append(
            A.Problem(
                "/valid_to", "The end of the valid period must be after the start."
            )
        )
    tests = await _tests_of(db, m)
    test_results: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    if not A.has_errors(problems):
        mine = await _compiled_of(v)
        test_results = await V.run_tests(mine, tests)
        live = (
            await db.execute(
                select(DecisionVersion)
                .where(S.current_versions_filter(m.id))
                .order_by(desc(DecisionVersion.version))
                .limit(1)
            )
        ).scalar_one_or_none()
        if live is not None and live.id != v.id:
            recent = (
                (
                    await db.execute(
                        select(DecisionEvaluation)
                        .where(DecisionEvaluation.model_id == m.id)
                        .order_by(desc(DecisionEvaluation.created_at))
                        .limit(200)
                    )
                )
                .scalars()
                .all()
            )
            cases = [{**t, "source": "test"} for t in tests] + [
                {
                    "facts": e.facts,
                    "as_of": e.as_of,
                    "name": f"stored evaluation {e.public_id}",
                    "source": "stored",
                }
                for e in recent
            ]
            changes = await V.regression(mine, await _compiled_of(live), cases)
    failed = [t for t in test_results if not t["passed"]]
    blocking = [p for p in problems if p.severity == "error"]
    blocking_overlaps = [o for o in overlaps if o["kind"] == "conflict"]
    result = {
        "ok": not blocking and not failed and not blocking_overlaps,
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "content_hash": v.content_hash,
        "problems": _problems_json(problems),
        "overlaps": overlaps,
        "tests": test_results,
        "tests_failed": len(failed),
        "changes": changes,
        "summary": _summary(
            blocking, failed, blocking_overlaps, overlaps, changes, len(test_results)
        ),
    }
    return result


def _summary(blocking, failed, conflicts, overlaps, changes, ntests) -> str:
    parts = []
    if blocking:
        parts.append(
            f"{len(blocking)} problem{'s' if len(blocking) != 1 else ''} to fix"
        )
    if failed:
        if ntests == 1:
            parts.append("The golden test fails")
        else:
            parts.append(
                f"{len(failed)} of {ntests} golden tests {'fails' if len(failed) == 1 else 'fail'}"
            )
    if conflicts:
        n = len(conflicts)
        parts.append(
            f"{n} pair{'s' if n != 1 else ''} of rules {'disagree' if n != 1 else 'disagrees'}"
        )
    if not parts:
        if ntests == 0:
            parts.append("Ready. There are no golden tests yet")
        else:
            parts.append(
                f"Ready. {ntests} golden test{'s pass' if ntests != 1 else ' passes'}"
            )
    shadow = [o for o in overlaps if o["kind"] == "shadowed"]
    if shadow:
        parts.append(
            f"{len(shadow)} rule{'s are' if len(shadow) != 1 else ' is'} hidden by a rule above"
        )
    if changes:
        parts.append(
            f"{len(changes)} result{'s change' if len(changes) != 1 else ' changes'} compared with the published version"
        )
    return ". ".join(parts) + "."


@router.post("/{key}/versions/{n}/validate")
async def validate_version(
    key: str,
    n: int,
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    v = await _version(db, m, n) if m else None
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    result = await _validate(db, user, m, v)
    if v.state == "draft":
        result = _keep_returned(v.validation, result)
        v.validation = result
        await db.commit()
    return success(result)


class ProposeBody(BaseModel):
    note: str = ""


@router.post("/{key}/versions/{n}/propose")
async def propose(
    key: str,
    n: int,
    body: ProposeBody,
    request: Request,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    v = await _version(db, m, n) if m else None
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    if v.state != "draft":
        return error(f"Version {n} is already {v.state}.", 409)
    result = await _validate(db, user, m, v)
    v.validation = result
    if not result["ok"]:
        await db.commit()
        return error(
            f"Not ready to propose. {result['summary']}",
            422,
            error_code="VALIDATION_FAILED",
            details=result,
        )
    pol = (
        governance.policy(str(user.tenant_id), m.risk_tier).get("publish_approvals")
        or {}
    )
    need = int(pol.get("min_approvers") or 0)
    now = dt.datetime.now(dt.timezone.utc)
    v.state = "proposed"
    v.proposed_by = user.id
    v.proposed_at = now
    v.risk_tier_at_proposal = m.risk_tier
    if body.note:
        v.change_note = body.note
    if need > 0:
        a = Approval(
            tenant_id=user.tenant_id,
            title=f"Publish {m.name} version {n}",
            payload={
                "kind": "decision_publish",
                "decision_key": key,
                "version": n,
                "risk_tier": m.risk_tier,
                "summary": result["summary"],
                "changes": rule_changes(
                    v,
                    (
                        await db.get(DecisionVersion, v.base_version_id)
                        if v.base_version_id
                        else None
                    ),
                ),
                "result_changes": len(result["changes"]),
                "change_note": v.change_note or "",
                "link": f"/decisions/{key}?version={n}",
            },
            required_signoffs=need,
            signoffs=[],
            status=ApprovalStatus.pending,
            requested_by=user.id,
            gate_kind="decision_publish",
            policy={
                "exclude_requester": bool(pol.get("exclude_author")),
                "capability": pol.get("capability") or "approvals.sign",
            },
            expires_at=now + dt.timedelta(days=14),
        )
        db.add(a)
        await db.flush()
        v.approval_id = a.id
    else:
        v.state = "approved"
    from app.services.events import emit

    await emit(
        db,
        user.tenant_id,
        "decision.proposed",
        {
            "decision_key": key,
            "version": n,
            "approvals_needed": need,
            "approval_id": str(v.approval_id) if v.approval_id else None,
        },
    )
    if v.approval_id:
        await emit(
            db,
            user.tenant_id,
            "approval.requested",
            {
                "approval_id": str(v.approval_id),
                "title": f"Publish {m.name} version {n}",
                "gate_kind": "decision_publish",
                "required_signoffs": need,
            },
        )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "decision.proposed",
        {
            "key": key,
            "version": n,
            "approvals_needed": need,
            "summary": result["summary"],
        },
        request,
        resource_type="decision",
        resource_id=key,
    )
    await db.commit()
    await db.refresh(v)
    if v.approval_id:
        # signers hear about it the way every other approval request reaches them
        try:
            from app.routers.approvals import _notify_pending

            approval = await db.get(Approval, v.approval_id)
            if approval is not None:
                await _notify_pending(db, approval, requester=user)
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning(
                "decision approval notification failed: %s", e
            )
    return success({**_version_full(v, user), "approvals_needed": need})


@router.post("/{key}/versions/{n}/withdraw")
async def withdraw(
    key: str,
    n: int,
    request: Request,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    v = await _version(db, m, n) if m else None
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    if v.state not in ("proposed", "approved", "rejected"):
        return error(
            f"Version {n} is {v.state}, only a proposed version can be withdrawn.", 409
        )
    if v.approval_id:
        a = await db.get(Approval, v.approval_id)
        if a is not None and a.status == ApprovalStatus.pending:
            from app.core.approvers import mark_withdrawn

            mark_withdrawn(
                a, f"Version {n} was taken back to a draft before sign-off.", user.id
            )
    v.state = "draft"
    v.approval_id = None
    v.risk_tier_at_proposal = None
    v.lock_version = (v.lock_version or 1) + 1
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "decision.withdrawn",
        {"key": key, "version": n},
        request,
        resource_type="decision",
        resource_id=key,
    )
    await db.commit()
    await db.refresh(v)
    return success(_version_full(v, user))


class PublishBody(BaseModel):
    # the version the caller believes is in force now, so two publishers cannot cross
    expected_current: int | None = None


@router.post("/{key}/versions/{n}/publish")
async def publish(
    key: str,
    n: int,
    body: PublishBody,
    request: Request,
    user: User = Depends(require_capability("decisions.publish")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    # one publisher per decision at a time
    await db.execute(
        select(DecisionModel.id).where(DecisionModel.id == m.id).with_for_update()
    )
    v = await _version(db, m, n)
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    if v.state == "proposed":
        a = await db.get(Approval, v.approval_id) if v.approval_id else None
        if a is not None and a.status == ApprovalStatus.denied:
            return error(
                "This version was rejected. Start a new draft to change it.",
                409,
                error_code="REJECTED",
            )
        got = (
            len([s for s in (a.signoffs or []) if s.get("decision") == "approve"])
            if a
            else 0
        )
        need = a.required_signoffs if a else 0
        return error(
            f"Version {n} is waiting for sign-off, {got} of {need} so far. It can be published once approved.",
            409,
            error_code="AWAITING_APPROVAL",
        )
    if v.state != "approved":
        return error(
            f"Version {n} is {v.state}. Only an approved version can be published.",
            409,
            error_code="NOT_APPROVED",
        )
    await governance.ensure_fresh()
    a = await db.get(Approval, v.approval_id) if v.approval_id else None
    refused = _publish_refusal(
        str(user.tenant_id), n, v.risk_tier_at_proposal, m.risk_tier, a
    )
    if refused:
        return error(refused[1], 409, error_code=refused[0])
    live = (
        (
            await db.execute(
                select(DecisionVersion).where(S.current_versions_filter(m.id))
            )
        )
        .scalars()
        .all()
    )
    current_n = max((x.version for x in live), default=None)
    if body.expected_current is not None and body.expected_current != (current_n or 0):
        return error(
            f"Version {current_n} was published since you looked. Review it, then publish again.",
            409,
            error_code="PUBLISH_CONFLICT",
        )
    plan = S.plan_publish(
        [S._ref(x) for x in live], S._as_dt(v.valid_from), S._as_dt(v.valid_to)
    )
    if plan.block:
        return error(plan.block, 409, error_code="VALID_PERIOD_CONFLICT")
    now = dt.datetime.now(dt.timezone.utc)
    by_id = {str(x.id): x for x in live}
    for vid in plan.supersede:
        x = by_id[vid]
        x.state = "superseded"
        x.superseded_at = now
    if plan.supersede:
        await _close_reattests(
            db,
            user.tenant_id,
            key,
            f"Version {n} replaced it.",
            versions={by_id[i].version for i in plan.supersede},
            by=user.id,
        )
    for vid, end in plan.close:
        x = by_id[vid]
        x.valid_to_history = list(x.valid_to_history or []) + [
            {
                "from": _iso(x.valid_to),
                "to": end.isoformat(),
                "at": now.isoformat(),
                "by_version": n,
            }
        ]
        x.valid_to = end
    v.state = "published"
    v.published_at = now
    v.published_by = user.id
    v.editing_by = None
    from app.services.events import emit

    await emit(
        db,
        user.tenant_id,
        "decision.published",
        {
            "decision_key": key,
            "version": n,
            "content_hash": v.content_hash,
            "valid_from": _iso(v.valid_from),
            "valid_to": _iso(v.valid_to),
            "superseded": [by_id[i].version for i in plan.supersede],
            "closed": [by_id[i].version for i, _ in plan.close],
        },
    )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "decision.published",
        {
            "key": key,
            "version": n,
            "content_hash": v.content_hash,
            "superseded": [by_id[i].version for i in plan.supersede],
            "closed": [by_id[i].version for i, _ in plan.close],
        },
        request,
        resource_type="decision",
        resource_id=key,
    )
    await db.commit()
    await S.announce(str(user.tenant_id), key)
    await db.refresh(v)
    return success(
        {
            **_version_full(v, user),
            "superseded": [by_id[i].version for i in plan.supersede],
            "closed": [
                {"version": by_id[i].version, "valid_to": e.isoformat()}
                for i, e in plan.close
            ],
        }
    )


def _signoff_satisfies(a: Approval | None, pa: dict[str, Any]) -> bool:
    need = int(pa.get("min_approvers") or 0)
    if need <= 0:
        return True
    if a is None or a.status != ApprovalStatus.approved:
        return False
    yes = [s for s in (a.signoffs or []) if s.get("decision") == "approve"]
    if any(s.get("sole_operator") for s in yes):
        return True
    if pa.get("exclude_author"):
        yes = [s for s in yes if str(s.get("user_id")) != str(a.requested_by)]
    return len({s.get("user_id") for s in yes}) >= need


def _publish_refusal(
    tenant_id: str,
    n: int,
    tier_at_proposal: str | None,
    current: str,
    a: Approval | None,
) -> tuple[str, str] | None:
    """Publishing needs the sign-off of the higher of the tier it was proposed under and the tier now."""
    proposed = tier_at_proposal or current
    tier = risk.highest([proposed, current])
    pa = governance.policy(tenant_id, tier).get("publish_approvals") or {}
    if _signoff_satisfies(a, pa):
        return None
    rule = risk.publish_policy_text(tier, pa)
    if risk.normalize(proposed) != risk.normalize(current):
        return (
            "TIER_CHANGED",
            f"Version {n} was approved as {proposed} risk, and the decision is now {current} risk. {rule} "
            "Withdraw it and propose it again so it gets that sign-off.",
        )
    return (
        "SIGNOFF_INSUFFICIENT",
        f"Version {n} does not have the sign-off its tier needs now. {rule} Withdraw it and propose it again.",
    )


class ApproverBody(BaseModel):
    user_id: uuid.UUID


@router.post("/{key}/approvers")
async def add_approver(
    key: str,
    body: ApproverBody,
    request: Request,
    user: User = Depends(require_capability("permissions.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Put a person in Decision reviewers, from the decision page."""
    from app.core.approvers import REVIEWERS_NAME, add_decision_reviewer

    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    from app.core.approvers import real_person

    who = await db.get(User, body.user_id)
    if (
        who is None
        or who.tenant_id != user.tenant_id
        or not who.is_active
        or not real_person(who)
    ):
        return error("That person is not an active member of this workspace.", 404)
    added = await add_decision_reviewer(db, user.tenant_id, who.id, by=user.id)
    if added:
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "permission_set.member_added",
            {"set": REVIEWERS_NAME, "member": who.email, "from_decision": key},
            request,
            resource_type="decision",
            resource_id=key,
        )
    await db.commit()
    from app.core import capabilities as caps

    caps.invalidate(who.id)
    return success({"added": added, "person": person_json(who), "set": REVIEWERS_NAME})


@router.get("/{key}/approver-candidates")
async def approver_candidates(
    key: str,
    user: User = Depends(require_capability("permissions.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Teammates who could be made approvers: real, active, and not able to approve already."""
    from app.core.approvers import approver_candidates as pick

    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    # whoever proposed the waiting version could never sign it
    authors = (
        (
            await db.execute(
                select(DecisionVersion.proposed_by).where(
                    DecisionVersion.model_id == m.id,
                    DecisionVersion.state.in_(("proposed", "approved")),
                )
            )
        )
        .scalars()
        .all()
    )
    people = await tenant_people(db, user.tenant_id)
    return success([person_json(u) for u in pick(people, exclude=authors)])


@router.get("/{key}/versions/{n}/sign-off")
async def sign_off_info(
    key: str,
    n: int,
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Who has to sign this version, who has, and who could."""
    m = await _model(db, user, key)
    v = await _version(db, m, n) if m else None
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    await governance.ensure_fresh()
    a = await db.get(Approval, v.approval_id) if v.approval_id else None
    current = a is not None
    if a is None:
        a = (
            await db.execute(
                select(Approval)
                .where(
                    Approval.tenant_id == user.tenant_id,
                    Approval.gate_kind == "decision_publish",
                    Approval.payload["decision_key"].astext == key,
                    Approval.payload["version"].astext == str(n),
                )
                .order_by(desc(Approval.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()
    in_review = v.state in ("proposed", "approved", "rejected")
    tier = (
        risk.highest([v.risk_tier_at_proposal or m.risk_tier, m.risk_tier])
        if in_review
        else m.risk_tier
    )
    pa = governance.policy(str(user.tenant_id), tier).get("publish_approvals") or {}
    need = int(pa.get("min_approvers") or 0)
    if a is not None and a.requested_by:
        requester_id = a.requested_by
    elif in_review and v.proposed_by:
        requester_id = v.proposed_by
    else:
        requester_id = user.id
    pol = (
        a.policy
        if current and a is not None and a.policy
        else {
            "exclude_requester": bool(pa.get("exclude_author")),
            "capability": pa.get("capability") or "approvals.sign",
        }
    )
    people = await tenant_people(db, user.tenant_id)
    by_id = {str(u.id): (u, c) for u, c in people}
    eligible = eligible_from(people, pol, "decision_publish", requester_id)
    from app.core.capabilities import _role, has_capability

    req = by_id.get(str(requester_id))
    requester_signs = req is not None and can_sign(
        _role(req[0]), req[1], pol, "decision_publish"
    )
    names: dict[str, str] = {}
    ids = [
        s.get("user_id") for s in ((a.signoffs or []) if a else []) if s.get("user_id")
    ]
    for uid in ids:
        if uid in by_id:
            names[uid] = by_id[uid][0].full_name or by_id[uid][0].email
        else:
            try:
                u = await db.get(User, uuid.UUID(uid))
            except ValueError:
                u = None
            if u is not None:
                names[uid] = u.full_name or u.email
    status = (
        a.status.value
        if a is not None and hasattr(a.status, "value")
        else (str(a.status) if a else None)
    )
    open_now = (a is None and v.state == "draft") or (
        current and a is not None and a.status == ApprovalStatus.pending
    )
    return success(
        {
            "required": (a.required_signoffs if current and a is not None else need),
            "tier": tier,
            "tier_at_proposal": v.risk_tier_at_proposal,
            "attested_under": _attested_under(v),
            "attestation": (
                await _with_approver_names(db, (v.validation or {}).get("attested"))
                if isinstance((v.validation or {}).get("attested"), dict)
                else None
            ),
            "reattest": await _reattest_json(db, user.tenant_id, key, n),
            "current_tier": m.risk_tier,
            "policy_text": risk.publish_policy_text(tier, pa),
            "approval_id": str(a.id) if a else None,
            "status": status,
            "current": current,
            "signoffs": [
                {
                    "user_id": s.get("user_id"),
                    "name": names.get(str(s.get("user_id"))) or s.get("user_email"),
                    "user_name": names.get(str(s.get("user_id")))
                    or s.get("user_name")
                    or s.get("user_email"),
                    "user_email": s.get("user_email"),
                    "at": s.get("at"),
                    "decision": s.get("decision"),
                    "sole_operator": bool(s.get("sole_operator")),
                    "reason": s.get("reason") or None,
                }
                for s in ((a.signoffs or []) if a else [])
            ],
            "self_approved": bool(a is not None and is_self_approved(a)),
            "missing_hint": {
                "can_grant": await has_capability(db, user, "permissions.manage"),
                "permissions_link": "/admin/permissions",
            },
            "eligible_approvers": [person_json(u) for u in eligible],
            "author_can_approve": bool(
                not pol.get("exclude_requester") and requester_signs
            ),
            "sole_operator_available": bool(
                need > 0
                and open_now
                and not eligible
                and requester_signs
                and await sole_operator_enabled(db, user.tenant_id)
            ),
        }
    )


@router.get("/{key}/versions/{n}/publish-plan")
async def publish_plan(
    key: str,
    n: int,
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """What publishing this version would do, before anyone presses the button."""
    m = await _model(db, user, key)
    v = await _version(db, m, n) if m else None
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    live = (
        (
            await db.execute(
                select(DecisionVersion).where(S.current_versions_filter(m.id))
            )
        )
        .scalars()
        .all()
    )
    plan = S.plan_publish(
        [S._ref(x) for x in live], S._as_dt(v.valid_from), S._as_dt(v.valid_to)
    )
    by_id = {str(x.id): x for x in live}
    return success(
        {
            "current": max((x.version for x in live), default=None),
            "blocked": plan.block,
            "supersede": [by_id[i].version for i in plan.supersede],
            "close": [
                {"version": by_id[i].version, "valid_to": e.isoformat()}
                for i, e in plan.close
            ],
            "valid_from": _iso(v.valid_from),
            "valid_to": _iso(v.valid_to),
        }
    )


@router.post("/{key}/versions/{n}/retire")
async def retire(
    key: str,
    n: int,
    request: Request,
    body: ActionBody | None = None,
    user: User = Depends(require_capability("decisions.publish")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    v = await _version(db, m, n) if m else None
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    if v.state != "published" or v.superseded_at is not None:
        return error(f"Version {n} is not in force.", 409)
    why = ((body.reason if body else None) or "").strip()
    refused, need, pa = await _guard_action(db, user, m, why)
    if refused is not None:
        return refused
    if need > 0:
        pending = await _request_action(
            db, user, m, "decision_retire", why, need, pa, version=n
        )
        await db.commit()
        await _announce_approval(db, user, pending["approval_id"])
        return success({"pending": pending}, status_code=202)
    await _do_retire(
        db, user.tenant_id, user.id, m, v, request, {"reason": why or None}
    )
    await db.commit()
    await S.announce(str(user.tenant_id), key)
    # updated_at is set by the database, so the row must be read back before it is shown
    await db.refresh(v)
    return success(_version_full(v, user))


async def _on_tier_change_resolved(db: AsyncSession, a: Approval) -> None:
    if a.status != ApprovalStatus.approved:
        return
    p = a.payload or {}
    key = p.get("decision_key")
    m = (
        await db.execute(
            select(DecisionModel).where(
                DecisionModel.tenant_id == a.tenant_id,
                DecisionModel.key == key,
                DecisionModel.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    import logging

    if m is None or m.risk_tier != p.get("from_tier"):
        # the tier moved since it was asked for, an approved lowering must not undo that
        logging.getLogger(__name__).info(
            "tier change %s for %s not applied, the tier is no longer %s",
            a.id,
            key,
            p.get("from_tier"),
        )
        return
    to_tier = risk.normalize(p.get("to_tier"))
    approvers = [
        s.get("user_id")
        for s in (a.signoffs or [])
        if s.get("decision") == "approve" and s.get("user_id")
    ]
    actor = (
        approvers[-1]
        if approvers
        else (str(a.requested_by) if a.requested_by else None)
    )
    m.risk_tier = to_tier
    await _close_reattests(
        db,
        a.tenant_id,
        key,
        f"The tier was lowered to {to_tier}.",
        above=to_tier,
        by=actor,
    )
    if actor:
        await log_action(
            db,
            a.tenant_id,
            uuid.UUID(str(actor)),
            "decision.tier_lowered",
            {
                "key": key,
                "from": p.get("from_tier"),
                "to": to_tier,
                "reason": p.get("reason"),
                "approval_id": str(a.id),
                "approved_by": approvers,
                "requested_by": str(a.requested_by) if a.requested_by else None,
                "self_approved": is_self_approved(a),
                "needed_signoff": True,
            },
            resource_type="decision",
            resource_id=key,
            old_value={"risk_tier": p.get("from_tier")},
            new_value={"risk_tier": to_tier},
        )
    await db.commit()
    await S.announce(str(a.tenant_id), key)


async def _on_reattest_resolved(db: AsyncSession, a: Approval) -> None:
    if a.status != ApprovalStatus.approved:
        return
    p = a.payload or {}
    key = p.get("decision_key")
    v = (
        await db.execute(
            select(DecisionVersion)
            .join(DecisionModel, DecisionModel.id == DecisionVersion.model_id)
            .where(
                DecisionModel.tenant_id == a.tenant_id,
                DecisionModel.key == key,
                DecisionVersion.version == p.get("version"),
            )
        )
    ).scalar_one_or_none()
    if v is None or v.state != "published" or v.superseded_at is not None:
        return
    approvers = [
        s.get("user_id")
        for s in (a.signoffs or [])
        if s.get("decision") == "approve" and s.get("user_id")
    ]
    tier = risk.normalize(p.get("to_tier"))
    who = await _user_names(db, approvers)
    v.validation = {
        **(v.validation or {}),
        "attested": {
            "tier": tier,
            "approval_id": str(a.id),
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "approved_by": approvers,
            "approved_by_names": [who.get(str(i)) or str(i) for i in approvers],
            "self_approved": is_self_approved(a),
        },
    }
    actor = approvers[-1] if approvers else a.requested_by
    if actor:
        await log_action(
            db,
            a.tenant_id,
            uuid.UUID(str(actor)),
            "decision.reattested",
            {
                "key": key,
                "version": v.version,
                "from": p.get("from_tier"),
                "to": tier,
                "approval_id": str(a.id),
                "approved_by": approvers,
                "self_approved": is_self_approved(a),
            },
            resource_type="decision",
            resource_id=key,
        )
    await db.commit()


async def _on_action_resolved(db: AsyncSession, a: Approval) -> None:
    if a.status != ApprovalStatus.approved:
        return
    p = a.payload or {}
    key = p.get("decision_key")
    approvers = [
        s.get("user_id")
        for s in (a.signoffs or [])
        if s.get("decision") == "approve" and s.get("user_id")
    ]
    actor = approvers[-1] if approvers else a.requested_by
    actor = uuid.UUID(str(actor)) if actor else None
    extra = {
        "reason": p.get("reason"),
        "approval_id": str(a.id),
        "approved_by": approvers,
        "requested_by": str(a.requested_by) if a.requested_by else None,
        "self_approved": is_self_approved(a),
    }
    archived = a.gate_kind == "decision_restore"
    m = (
        await db.execute(
            select(DecisionModel).where(
                DecisionModel.tenant_id == a.tenant_id,
                DecisionModel.key == key,
                (
                    DecisionModel.archived_at.is_not(None)
                    if archived
                    else DecisionModel.archived_at.is_(None)
                ),
            )
        )
    ).scalar_one_or_none()
    if m is None or actor is None:
        return
    withdrawn: list[Approval] = []
    if a.gate_kind == "decision_archive":
        withdrawn = await _do_archive(db, a.tenant_id, actor, m, None, extra, keep=a.id)
    elif a.gate_kind == "decision_restore":
        await _do_restore(db, a.tenant_id, actor, m, None, extra)
    else:
        v = (
            await db.execute(
                select(DecisionVersion).where(
                    DecisionVersion.model_id == m.id,
                    DecisionVersion.version == p.get("version"),
                )
            )
        ).scalar_one_or_none()
        if v is None or v.state != "published" or v.superseded_at is not None:
            return
        await _do_retire(db, a.tenant_id, actor, m, v, None, extra)
    await db.commit()
    await tell_withdrawn(db, withdrawn, ARCHIVED_WITHDRAWN)
    await S.announce(str(a.tenant_id), key)


async def on_approval_resolved(db: AsyncSession, a: Approval) -> None:
    """Called by the approvals service when a decision_publish or decision_tier_change gate is decided."""
    if a.gate_kind == "decision_tier_change":
        await _on_tier_change_resolved(db, a)
        return
    if a.gate_kind == REATTEST:
        await _on_reattest_resolved(db, a)
        return
    if a.gate_kind in ACTION_KINDS:
        await _on_action_resolved(db, a)
        return
    v = (
        await db.execute(
            select(DecisionVersion).where(DecisionVersion.approval_id == a.id)
        )
    ).scalar_one_or_none()
    if v is None or v.state != "proposed":
        return
    if a.status == ApprovalStatus.returned:
        # back to the author as a draft, with the reviewer's note on it
        note = next(
            (
                s.get("reason")
                for s in reversed(a.signoffs or [])
                if s.get("decision") == "return"
            ),
            "",
        )
        v.state = "draft"
        v.approval_id = None
        v.risk_tier_at_proposal = None
        v.lock_version = (v.lock_version or 1) + 1
        v.validation = {
            **(v.validation or {}),
            "returned": {
                "note": note,
                "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
        }
    else:
        v.state = "approved" if a.status == ApprovalStatus.approved else "rejected"
        if a.status == ApprovalStatus.denied:
            s = next(
                (x for x in reversed(a.signoffs or []) if x.get("decision") == "deny"),
                {},
            )
            v.validation = {
                **(v.validation or {}),
                "denied": {
                    "reason": s.get("reason") or None,
                    "by": s.get("user_email"),
                    "by_id": s.get("user_id"),
                    "at": s.get("at"),
                },
            }
    await db.commit()


class EvaluateBody(BaseModel):
    facts: dict[str, Any] = Field(default_factory=dict)
    as_of: str | None = None
    known_at: str | None = None
    version: int | None = None
    trace: bool = True
    persist: bool = False
    idempotency_key: str | None = Field(default=None, max_length=200)


def _too_big(obj: Any) -> bool:
    return len(A.canonical_json(obj)) > MAX_FACTS_BYTES


@router.post("/{key}/evaluate")
async def evaluate(
    key: str,
    body: EvaluateBody,
    user: Principal = Depends(principal_with("decisions.evaluate")),
) -> JSONResponse:
    async with async_session() as db:
        return await _evaluate_impl(key, body, user, db)


async def _evaluate_impl(
    key: str, body: Any, user: Any, db: AsyncSession
) -> JSONResponse:
    if _too_big(body.facts):
        return error(f"Facts are larger than {MAX_FACTS_BYTES // 1000} KB.", 413)
    try:
        out = await S.evaluate(
            db,
            str(user.tenant_id),
            key,
            body.facts,
            as_of=body.as_of,
            known_at=body.known_at,
            version=body.version,
            want_trace=body.trace,
            persist=body.persist,
            idempotency_key=body.idempotency_key,
            caller=_caller(user),
        )
    except S.DecisionError as e:
        return _err(e)
    except ValueError:
        return error("Use dates like 2026-01-01 for as_of and known_at.", 400)
    return success(out)


class BatchBody(BaseModel):
    items: list[dict[str, Any]]
    as_of: str | None = None
    known_at: str | None = None
    version: int | None = None


@router.post("/{key}/evaluate-batch")
async def evaluate_batch(
    key: str,
    body: BatchBody,
    user: Principal = Depends(principal_with("decisions.evaluate")),
) -> JSONResponse:
    async with async_session() as db:
        return await _evaluate_batch_impl(key, body, user, db)


async def _evaluate_batch_impl(
    key: str, body: Any, user: Any, db: AsyncSession
) -> JSONResponse:
    if len(body.items) > MAX_BATCH:
        return error(
            f"A batch holds at most {MAX_BATCH} items. Split it into smaller batches.",
            413,
        )
    if _too_big(body.items):
        return error("The batch is too large.", 413)
    # one session serves the whole batch, so items run in order, each well under a millisecond
    results = []
    for i, item in enumerate(body.items):
        facts = item.get("facts", item)
        try:
            r = await S.evaluate(
                db,
                str(user.tenant_id),
                key,
                facts,
                as_of=item.get("as_of", body.as_of),
                known_at=item.get("known_at", body.known_at),
                version=body.version,
                want_trace=False,
            )
            results.append({"index": i, **r})
        except S.DecisionError as e:
            if e.code in ("NOT_FOUND", "KILL_SWITCH"):
                return _err(e)
            results.append(
                {
                    "index": i,
                    "outcome": "error",
                    "error": e.message,
                    "error_code": e.code,
                }
            )
        except ValueError:
            results.append(
                {"index": i, "outcome": "error", "error": "Use dates like 2026-01-01."}
            )
    counts: dict[str, int] = {}
    for r in results:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    return success({"results": results, "counts": counts})


class CompareTarget(BaseModel):
    label: str | None = None
    version: int | None = None
    as_of: str | None = None
    known_at: str | None = None


class CompareBody(BaseModel):
    facts: dict[str, Any] = Field(default_factory=dict)
    targets: list[CompareTarget] = Field(min_length=2, max_length=10)


@router.post("/{key}/compare")
async def compare(
    key: str,
    body: CompareBody,
    user: Principal = Depends(principal_with("decisions.evaluate")),
) -> JSONResponse:
    async with async_session() as db:
        return await _compare_impl(key, body, user, db)


async def _compare_impl(
    key: str, body: Any, user: Any, db: AsyncSession
) -> JSONResponse:
    rows = []
    for t in body.targets:
        try:
            r = await S.evaluate(
                db,
                str(user.tenant_id),
                key,
                body.facts,
                as_of=t.as_of,
                known_at=t.known_at,
                version=t.version,
                want_trace=False,
            )
            rows.append({"label": t.label or _target_label(t), **r})
        except S.DecisionError as e:
            rows.append(
                {
                    "label": t.label or _target_label(t),
                    "outcome": "error",
                    "error": e.message,
                }
            )
    base = rows[0]
    for r in rows[1:]:
        r["differs"] = A.canonical_json(
            [r.get("outcome"), r.get("result")]
        ) != A.canonical_json([base.get("outcome"), base.get("result")])
    return success(
        {"results": rows, "any_difference": any(r.get("differs") for r in rows[1:])}
    )


def _target_label(t: CompareTarget) -> str:
    if t.version is not None:
        return f"version {t.version}"
    bits = [f"on {t.as_of}" if t.as_of else "today"]
    if t.known_at:
        bits.append(f"as known on {t.known_at}")
    return " ".join(bits)


EVAL_OUTCOMES = ("decided", "no_match", "missing_facts", "invalid_facts")


def _eval_row(e: DecisionEvaluation, number: int | None) -> dict[str, Any]:
    caller = e.caller or {}
    return {
        "id": str(e.public_id),
        "outcome": e.outcome,
        "version": number,
        "version_id": str(e.version_id),
        "facts": e.facts,
        "result": e.result,
        "applied_rules": e.applied_rules,
        "trace_hash": e.trace_hash,
        "as_of": e.as_of,
        "known_at": _iso(e.known_at),
        "content_hash": e.content_hash,
        "caller": caller,
        "execution_id": caller.get("execution_id") or None,
        "created_at": _iso(e.created_at),
    }


async def _version_numbers(db: AsyncSession, model_id: Any) -> dict[str, int]:
    rows = (
        await db.execute(
            select(DecisionVersion.id, DecisionVersion.version).where(
                DecisionVersion.model_id == model_id
            )
        )
    ).all()
    return {str(r[0]): r[1] for r in rows}


@router.get("/{key}/evaluations")
async def list_evaluations(
    key: str,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    outcome: str | None = Query(None),
    execution_id: str | None = Query(None, max_length=64),
    version: int | None = Query(None, ge=1),
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    if outcome and outcome not in EVAL_OUTCOMES:
        return error(
            "outcome must be decided, no_match, missing_facts or invalid_facts", 400
        )
    numbers = await _version_numbers(db, m.id)
    base = [
        DecisionEvaluation.tenant_id == user.tenant_id,
        DecisionEvaluation.model_id == m.id,
    ]
    if execution_id:
        base.append(DecisionEvaluation.caller["execution_id"].astext == execution_id)
    if version is not None:
        vid = next((k for k, n in numbers.items() if n == version), None)
        if vid is None:
            return error(f"{key} has no version {version}.", 404)
        base.append(DecisionEvaluation.version_id == uuid.UUID(vid))
    counts = {
        o: n
        for o, n in (
            await db.execute(
                select(DecisionEvaluation.outcome, func.count())
                .where(*base)
                .group_by(DecisionEvaluation.outcome)
            )
        ).all()
    }
    where = base + ([DecisionEvaluation.outcome == outcome] if outcome else [])
    rows = (
        (
            await db.execute(
                select(DecisionEvaluation)
                .where(*where)
                .order_by(
                    desc(DecisionEvaluation.created_at), desc(DecisionEvaluation.id)
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    total = counts.get(outcome, 0) if outcome else sum(counts.values())
    return success(
        [_eval_row(e, numbers.get(str(e.version_id))) for e in rows],
        meta={
            "total": total,
            "limit": limit,
            "offset": offset,
            "counts": counts,
            "log_mode": m.log_mode,
        },
    )


@router.get("/{key}/evaluations/{evaluation_id}")
async def get_evaluation(
    key: str,
    evaluation_id: str,
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    try:
        pid = uuid.UUID(evaluation_id)
    except ValueError:
        return error("That is not an evaluation id.", 404)
    e = (
        await db.execute(
            select(DecisionEvaluation).where(
                DecisionEvaluation.tenant_id == user.tenant_id,
                DecisionEvaluation.model_id == m.id,
                DecisionEvaluation.public_id == pid,
            )
        )
    ).scalar_one_or_none()
    if e is None:
        return error(f"{key} has no evaluation {evaluation_id}.", 404)
    v = (
        await db.execute(
            select(DecisionVersion).where(DecisionVersion.id == e.version_id)
        )
    ).scalar_one_or_none()
    out = _eval_row(e, v.version if v else None)
    rules = [r for r in ((v.authoring or {}).get("rules") or [])] if v else []
    replay: dict[str, Any] = {}
    # the stored version and facts give the same trace again, which proves the record
    if v is not None:
        try:
            r = await run_compiled(
                v.content_hash,
                v.content,
                e.facts,
                required=list(v.required_facts or []),
                fact_types=dict(v.fact_types or {}),
                as_of=e.as_of,
                want_trace=True,
            )
            replay = r.to_dict()
            replay["reproduced"] = (
                r.trace_hash == e.trace_hash and r.outcome == e.outcome
            )
        except Exception as exc:  # noqa: BLE001
            replay = {"error": f"The evaluation could not be repeated: {exc}"}
    out["applied"] = S.applied_rule_details(
        rules, e.applied_rules or [], replay.get("trace")
    )
    out["replay"] = replay
    return success(out)


class TestBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    facts: dict[str, Any] = Field(default_factory=dict)
    expected_outcome: str = "decided"
    expected: Any = None
    # exact or subset, left as it is on an update that does not send it
    match: str | None = None
    as_of: str | None = None


@router.get("/{key}/tests")
async def list_tests(
    key: str,
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    return success(await _tests_of(db, m))


def _check_test(body: TestBody) -> str | None:
    # a blank date means the day the tests run, never a stored empty string
    body.as_of = (body.as_of or "").strip() or None
    if body.expected_outcome not in (
        "decided",
        "no_match",
        "missing_facts",
        "invalid_facts",
    ):
        return (
            "expected_outcome must be decided, no_match, missing_facts or invalid_facts"
        )
    if body.as_of and not A.DATE_RE.match(body.as_of):
        return "Use a date like 2026-01-01 for as_of."
    if body.match is not None and body.match not in V.MATCH_MODES:
        return "match must be exact or subset"
    if (
        body.match == "subset"
        and body.expected_outcome == "decided"
        and body.expected is not None
        and not isinstance(body.expected, dict)
    ):
        return "A subset match needs the expected result as a JSON object."
    return None


@router.post("/{key}/tests")
async def add_test(
    key: str,
    body: TestBody,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    problem = _check_test(body)
    if problem:
        return error(problem, 400)
    t = DecisionTest(
        tenant_id=user.tenant_id,
        model_id=m.id,
        name=body.name,
        facts=body.facts,
        expected_outcome=body.expected_outcome,
        expected=body.expected,
        match_mode=body.match or "exact",
        as_of=body.as_of,
        created_by=user.id,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return success(_test_json(t), status_code=201)


@router.put("/{key}/tests/{test_id}")
async def update_test(
    key: str,
    test_id: uuid.UUID,
    body: TestBody,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    t = await db.get(DecisionTest, test_id) if m else None
    if t is None or t.model_id != m.id:
        return error("Test not found", 404)
    problem = _check_test(body)
    if problem:
        return error(problem, 400)
    t.name, t.facts, t.expected_outcome, t.expected, t.as_of = (
        body.name,
        body.facts,
        body.expected_outcome,
        body.expected,
        body.as_of,
    )
    if body.match is not None:
        t.match_mode = body.match
    await db.commit()
    await db.refresh(t)
    return success(_test_json(t))


@router.delete("/{key}/tests/{test_id}")
async def delete_test(
    key: str,
    test_id: uuid.UUID,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    t = await db.get(DecisionTest, test_id) if m else None
    if t is None or t.model_id != m.id:
        return error("Test not found", 404)
    await db.delete(t)
    await db.commit()
    return success({"deleted": True})


@router.get("/{key}/export")
async def export_rules(
    key: str,
    version: int | None = None,
    full: int = Query(0, ge=0, le=1),
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    if version is None:
        v = (
            await db.execute(
                select(DecisionVersion)
                .where(DecisionVersion.model_id == m.id)
                .order_by(desc(DecisionVersion.version))
                .limit(1)
            )
        ).scalar_one_or_none()
    else:
        v = await _version(db, m, version)
    if v is None:
        return error("Nothing to export yet.", 404)
    if full:
        return success(
            I.export_file(
                {
                    "key": m.key,
                    "name": m.name,
                    "description": m.description,
                    "risk_tier": m.risk_tier,
                    "tags": m.tags,
                },
                v.authoring,
                v.content,
                await _tests_of(db, m),
                v.version,
            )
        )
    if v.authoring is None:
        return success({"format": "jdm", "version": v.version, "content": v.content})
    return success(
        {
            "format": "rules",
            "version": v.version,
            "rules": I.export_rules(v.authoring),
            "content": v.content,
        }
    )


class ImportBody(BaseModel):
    payload: Any
    mode: str = "merge"  # merge | replace
    version: int


@router.post("/{key}/import")
async def import_into_draft(
    key: str,
    body: ImportBody,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    v = await _version(db, m, body.version) if m else None
    if v is None:
        return error(f"{key} has no version {body.version}.", 404)
    if v.state != "draft":
        return error(f"Version {body.version} is {v.state}. Import into a draft.", 409)
    if if_match is not None and if_match.strip('"') != str(v.lock_version):
        return error(
            "Someone saved this draft after you opened it. Reload it, then import again.",
            409,
            error_code="STALE_DRAFT",
        )
    payload = body.payload
    if (
        isinstance(payload, dict)
        and payload.get("nodes") is not None
        and payload.get("edges") is not None
    ):
        doc = None
        content = payload
    else:
        try:
            doc = I.import_rules(
                payload, base=None if body.mode == "replace" else v.authoring
            )
        except I.InterchangeError as e:
            return error(
                f"The rules could not be read at {e.path or 'the top'}: {e.message}",
                400,
                error_code="BAD_RULES",
            )
        content = None
    if doc is None:
        save = SaveBody(content=content)
    else:
        save = SaveBody(authoring=doc)
    return await save_draft(key, body.version, save, None, str(v.lock_version), user, db)  # type: ignore[arg-type]


@router.get("/{key}/diff")
async def diff_versions(
    key: str,
    a: int,
    b: int,
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    va = await _version(db, m, a) if m else None
    vb = await _version(db, m, b) if m else None
    if va is None or vb is None:
        return error("Both versions must exist.", 404)
    return success(_diff(va, vb))


def rule_changes(v: Any, base: Any) -> int | None:
    """Rules added, removed or changed against the version it came from. A first version counts every rule."""
    if v is None or v.authoring is None:
        return None
    if base is None or base.authoring is None:
        return len([r for r in v.authoring.get("rules") or [] if isinstance(r, dict)])
    d = _diff(base, v)
    return (
        len(d.get("added", [])) + len(d.get("removed", [])) + len(d.get("changed", []))
    )


def _diff(va: DecisionVersion, vb: DecisionVersion) -> dict[str, Any]:
    out: dict[str, Any] = {
        "from": va.version,
        "to": vb.version,
        "same_content": va.content_hash == vb.content_hash,
    }
    if va.authoring is None or vb.authoring is None:
        out["mode"] = "content"
        return out
    ra = {r.get("key") or r.get("id"): r for r in va.authoring.get("rules") or []}
    rb = {r.get("key") or r.get("id"): r for r in vb.authoring.get("rules") or []}
    out["mode"] = "rules"
    out["added"] = [k for k in rb if k not in ra]
    out["removed"] = [k for k in ra if k not in rb]
    out["changed"] = [
        {
            "rule": k,
            "fields": sorted(
                f
                for f in set(ra[k]) | set(rb[k])
                if A.canonical_json(ra[k].get(f)) != A.canonical_json(rb[k].get(f))
            ),
        }
        for k in ra
        if k in rb and A.canonical_json(ra[k]) != A.canonical_json(rb[k])
    ]
    fa = {f["path"]: f for f in va.authoring.get("facts") or []}
    fb = {f["path"]: f for f in vb.authoring.get("facts") or []}
    out["facts_added"] = [p for p in fb if p not in fa]
    out["facts_removed"] = [p for p in fa if p not in fb]
    out["valid_period"] = {
        "from": [_iso(va.valid_from), _iso(vb.valid_from)],
        "to": [_iso(va.valid_to), _iso(vb.valid_to)],
    }
    return out


class RefSetBody(BaseModel):
    key: str | None = Field(default=None, max_length=160)
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    values: list[Any] = Field(default_factory=list)


def _refset_json(r: ReferenceSet, full: bool = True) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "key": r.key,
        "name": r.name,
        "description": r.description,
        "version": r.version,
        "count": len(r.values or []),
        "values": (r.values or []) if full else None,
        "updated_at": _iso(r.updated_at),
    }


@refs_router.get("")
async def list_refsets(
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        (
            await db.execute(
                select(ReferenceSet)
                .where(ReferenceSet.tenant_id == user.tenant_id)
                .order_by(ReferenceSet.name)
            )
        )
        .scalars()
        .all()
    )
    return success([_refset_json(r, full=False) for r in rows])


@refs_router.get("/{key}")
async def get_refset(
    key: str,
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    r = (
        await db.execute(
            select(ReferenceSet).where(
                ReferenceSet.tenant_id == user.tenant_id, ReferenceSet.key == key
            )
        )
    ).scalar_one_or_none()
    if r is None:
        return error(f"There is no reference set called {key}.", 404)
    return success(_refset_json(r))


def _clean_values(values: list[Any]) -> list[Any]:
    out, seen = [], set()
    for v in values:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                continue
        k = A.canonical_json(v)
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out


@refs_router.post("")
async def create_refset(
    body: RefSetBody,
    request: Request,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    key = (body.key or _slug(body.name)).upper().replace("-", "_").replace(".", "_")
    if not re.match(r"^[A-Z0-9_]{1,160}$", key):
        return error(
            "Reference set keys use capital letters, digits and underscores.", 400
        )
    exists = (
        await db.execute(
            select(ReferenceSet.id).where(
                ReferenceSet.tenant_id == user.tenant_id, ReferenceSet.key == key
            )
        )
    ).scalar()
    if exists:
        return error(f"A reference set called {key} already exists.", 409)
    vals = _clean_values(body.values)
    r = ReferenceSet(
        tenant_id=user.tenant_id,
        key=key,
        name=body.name,
        description=body.description,
        version=1,
        values=vals,
        content_hash=A.content_hash(vals),
        updated_by=user.id,
    )
    db.add(r)
    await db.flush()
    db.add(
        ReferenceSetVersion(
            set_id=r.id,
            version=1,
            values=vals,
            content_hash=r.content_hash,
            created_by=user.id,
        )
    )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "reference_set.created",
        {"key": key, "count": len(vals)},
        request,
    )
    await db.commit()
    await db.refresh(r)
    return success(_refset_json(r), status_code=201)


@refs_router.put("/{key}")
async def update_refset(
    key: str,
    body: RefSetBody,
    request: Request,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    r = (
        await db.execute(
            select(ReferenceSet).where(
                ReferenceSet.tenant_id == user.tenant_id, ReferenceSet.key == key
            )
        )
    ).scalar_one_or_none()
    if r is None:
        return error(f"There is no reference set called {key}.", 404)
    vals = _clean_values(body.values)
    h = A.content_hash(vals)
    r.name, r.description = body.name, body.description
    if h != r.content_hash:
        r.version += 1
        r.values, r.content_hash, r.updated_by = vals, h, user.id
        db.add(
            ReferenceSetVersion(
                set_id=r.id,
                version=r.version,
                values=vals,
                content_hash=h,
                created_by=user.id,
            )
        )
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "reference_set.updated",
            {"key": key, "version": r.version, "count": len(vals)},
            request,
        )
    await db.commit()
    await db.refresh(r)
    return success(
        {
            **_refset_json(r),
            "note": "Published decisions keep the values they were compiled with. Save a new draft to pick up this version.",
        }
    )


@refs_router.delete("/{key}")
async def delete_refset(
    key: str,
    request: Request,
    user: User = Depends(require_capability("decisions.author")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    r = (
        await db.execute(
            select(ReferenceSet).where(
                ReferenceSet.tenant_id == user.tenant_id, ReferenceSet.key == key
            )
        )
    ).scalar_one_or_none()
    if r is None:
        return error(f"There is no reference set called {key}.", 404)
    rows = (
        await db.execute(
            select(DecisionModel.key, DecisionVersion.reference_versions)
            .join(DecisionVersion, DecisionVersion.model_id == DecisionModel.id)
            .where(
                DecisionModel.tenant_id == user.tenant_id,
                DecisionModel.archived_at.is_(None),
                DecisionVersion.superseded_at.is_(None),
                DecisionVersion.state != "retired",
            )
        )
    ).all()
    users = sorted({k for k, refs in rows if key in (refs or {})})
    if users:
        return error(
            f"{key} is used by {', '.join(users)}. Remove it from those rules or archive the decisions first.",
            409,
        )
    await db.delete(r)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "reference_set.deleted",
        {"key": key},
        request,
    )
    await db.commit()
    return success({"deleted": True, "key": key})
