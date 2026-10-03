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


def _version_summary(v: DecisionVersion) -> dict[str, Any]:
    return {
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


def _version_full(v: DecisionVersion, me: User) -> dict[str, Any]:
    return {
        **_version_summary(v),
        "authoring": v.authoring,
        "content": v.content,
        "required_facts": v.required_facts,
        "fact_types": v.fact_types,
        "reference_versions": v.reference_versions,
        "provenance": v.provenance,
        "validation": v.validation,
        "base_version_id": str(v.base_version_id) if v.base_version_id else None,
        "editing_now": _editors(v, me),
    }


def _model_json(
    m: DecisionModel, versions: list[DecisionVersion] | None = None
) -> dict[str, Any]:
    vs = versions or []
    live = [v for v in vs if v.state == "published" and v.superseded_at is None]
    return {
        "id": str(m.id),
        "key": m.key,
        "name": m.name,
        "description": m.description,
        "risk_tier": m.risk_tier,
        "tags": m.tags or [],
        "log_mode": m.log_mode,
        "created_at": _iso(m.created_at),
        "updated_at": _iso(m.updated_at),
        "published": [
            _version_summary(v) for v in sorted(live, key=lambda v: v.version)
        ],
        "drafts": [_version_summary(v) for v in vs if v.state == "draft"],
        "proposed": [
            _version_summary(v) for v in vs if v.state in ("proposed", "approved")
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
    user: User = Depends(require_capability("decisions.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    stmt = select(DecisionModel).where(
        DecisionModel.tenant_id == user.tenant_id, DecisionModel.archived_at.is_(None)
    )
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            DecisionModel.name.ilike(like) | DecisionModel.key.ilike(like)
        )
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
    return success([_model_json(m, by.get(m.id)) for m in models])


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
    out = _model_json(m, list(vs))
    out["versions"] = [_version_summary(v) for v in vs]
    out["test_count"] = int(tests)
    out["policy"] = governance.policy(str(user.tenant_id), m.risk_tier)
    return success(out)


class UpdateModelBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    risk_tier: str | None = None
    tags: list[str] | None = None
    log_mode: str | None = None


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
    for f in ("name", "description", "risk_tier", "tags", "log_mode"):
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
    return success(
        {"key": m.key, "name": m.name, "risk_tier": m.risk_tier, "log_mode": m.log_mode}
    )


@router.delete("/{key}")
async def archive_model(
    key: str,
    request: Request,
    user: User = Depends(require_capability("decisions.publish")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    if m is None:
        return error(f"There is no decision called {key}.", 404)
    m.archived_at = dt.datetime.now(dt.timezone.utc)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "decision.archived",
        {"key": key},
        request,
        resource_type="decision",
        resource_id=key,
    )
    await db.commit()
    await S.announce(str(user.tenant_id), key)
    return success({"archived": True, "key": key})


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
    return success(_version_full(v, user))


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
    if body.authoring is not None:
        doc = A.normalize(body.authoring)
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
    v.validation = None
    eds = dict(v.editing_by or {})
    eds[str(user.id)] = {
        "email": user.email,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    v.editing_by = eds
    await db.commit()
    await db.refresh(v)
    return success({**_version_full(v, user), "problems": _problems_json(problems)})


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
    sets, versions = await S.reference_values(
        db, str(user.tenant_id), A.referenced_sets(doc)
    )
    problems = A.validate_document(doc, sets)
    out: dict[str, Any] = {"problems": _problems_json(problems)}
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
        "as_of": t.as_of,
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
        parts.append(f"{len(failed)} of {ntests} golden tests fail")
    if conflicts:
        parts.append(
            f"{len(conflicts)} pair{'s' if len(conflicts) != 1 else ''} of rules disagree"
        )
    if not parts:
        parts.append(f"Ready. {ntests} golden test{'s' if ntests != 1 else ''} pass")
    shadow = [o for o in overlaps if o["kind"] == "shadowed"]
    if shadow:
        parts.append(
            f"{len(shadow)} rule{'s are' if len(shadow) != 1 else ' is'} hidden by a rule above"
        )
    if changes:
        parts.append(
            f"{len(changes)} result{'s' if len(changes) != 1 else ''} change compared with the published version"
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
                "changes": len(result["changes"]),
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
            a.status = ApprovalStatus.expired
            a.decided_at = dt.datetime.now(dt.timezone.utc)
    v.state = "draft"
    v.approval_id = None
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
    user: User = Depends(require_capability("decisions.publish")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = await _model(db, user, key)
    v = await _version(db, m, n) if m else None
    if v is None:
        return error(f"{key} has no version {n}.", 404)
    if v.state != "published" or v.superseded_at is not None:
        return error(f"Version {n} is not in force.", 409)
    v.state = "retired"
    v.superseded_at = dt.datetime.now(dt.timezone.utc)
    from app.services.events import emit

    await emit(
        db, user.tenant_id, "decision.retired", {"decision_key": key, "version": n}
    )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "decision.retired",
        {"key": key, "version": n},
        request,
        resource_type="decision",
        resource_id=key,
    )
    await db.commit()
    await S.announce(str(user.tenant_id), key)
    return success(_version_full(v, user))


async def on_approval_resolved(db: AsyncSession, a: Approval) -> None:
    """Called by the approvals service when a decision_publish gate is decided."""
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
