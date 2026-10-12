"""Telemetry asset registry: name, type, tag and locate what streams in, by hand or from a CSV."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.capabilities import cap_words, require_capability
from app.core.deps import get_db
from app.core.responses import error, success
from app.telemetry import access, reads
from app.telemetry import assets as A
from models.governance import PermissionAssignment, PermissionSet
from models.telemetry_rules import TelemetryAsset
from models.user import User

router = APIRouter(prefix="/api/telemetry/assets", tags=["telemetry"])


def _redis() -> Any:
    from app.routers.telemetry import redis

    return redis()


async def bump_version() -> None:
    from app.telemetry.rules.evaluator import VERSION_KEY

    try:
        await _redis().incr(VERSION_KEY)
    except Exception:  # noqa: BLE001
        pass


def _manage_refusal() -> JSONResponse:
    return error(
        f"Naming assets needs {cap_words('telemetry.manage')}. An admin can grant it under Admin, Permissions.",
        403,
        error_code="FORBIDDEN",
    )


def _invalid(fields: dict[str, str]) -> JSONResponse:
    return error(
        next(iter(fields.values())),
        422,
        error_code="VALIDATION_ERROR",
        details={"fields": fields},
    )


async def my_teams(db: AsyncSession, user: User) -> set[str]:
    rows = (
        await db.execute(
            select(PermissionAssignment.permission_set_id).where(
                PermissionAssignment.user_id == user.id,
                PermissionAssignment.tenant_id == user.tenant_id,
            )
        )
    ).all()
    return {str(r[0]) for r in rows}


async def _team_names(db: AsyncSession, tenant_id: Any) -> dict[str, str]:
    rows = (
        await db.execute(
            select(PermissionSet.id, PermissionSet.name).where(
                PermissionSet.tenant_id == tenant_id
            )
        )
    ).all()
    return {str(i): n for i, n in rows}


async def collect(
    db: AsyncSession,
    user: User,
    *,
    parts: bool,
    only: tuple[str, str, str] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Visible assets, live and registered, as AssetRows. Second value is whether the caller can edit."""
    scope = await access.scope_for(db, user)
    can_edit = scope.everything or await access.has(db, user, "telemetry.manage")
    live_rows = await reads.all_devices(_redis(), user.tenant_id)
    live: dict[tuple[str, str, str], dict[str, Any]] = {}
    hidden: set[tuple[str, str]] = set()
    node_parts: dict[tuple[str, str], list[str]] = {}
    for r in live_rows:
        k = (r["group"], r["node"], r["device"] or "")
        if not scope.sees(r.get("connection_id")):
            hidden.add(k[:2])
            continue
        live[k] = r
        if k[2]:
            node_parts.setdefault(k[:2], []).append(k[2])
    q = select(TelemetryAsset).where(TelemetryAsset.tenant_id == user.tenant_id)
    if only:
        q = q.where(
            TelemetryAsset.grp == only[0],
            TelemetryAsset.node == only[1],
            TelemetryAsset.device == only[2],
        )
    reg = {
        (a.grp, a.node, a.device or ""): a
        for a in (await db.execute(q)).scalars().all()
    }
    teams = await _team_names(db, user.tenant_id)
    mine = set() if scope.everything else await my_teams(db, user)
    for g, n, d in reg:
        if d:
            parts_of = node_parts.setdefault((g, n), [])
            if d not in parts_of:
                parts_of.append(d)
    keys = set(live) | set(reg)
    if only:
        keys = {k for k in keys if k == only}
    out = []
    for k in sorted(keys):
        if not parts and k[2]:
            continue
        if k[:2] in hidden and k not in live:
            continue
        a = reg.get(k)
        if (
            a is not None
            and a.team_id
            and not scope.everything
            and k not in live
            and str(a.team_id) not in mine
        ):
            continue
        lv = live.get(k)
        out.append(
            A.row_json(
                a,
                live=lv,
                teams=teams,
                can_edit=can_edit,
                parts=sorted(node_parts.get(k[:2], [])) if not k[2] else None,
                key=k,
            )
        )
    # a node that only has parts streaming still shows as an asset
    if not parts and not only:
        have = {(r["group"], r["node"]) for r in out}
        for (g, n), ps in node_parts.items():
            if (g, n) not in have and (g, n) not in hidden:
                out.append(
                    A.row_json(
                        None,
                        live={"online": None},
                        teams=teams,
                        can_edit=can_edit,
                        parts=sorted(ps),
                        key=(g, n, ""),
                    )
                )
        out.sort(key=lambda r: (r["group"], r["node"], r["device"]))
    return out, can_edit


@router.get("")
async def list_assets(
    q: str = "",
    type: str = "",
    tag: str = "",
    group: str = "",
    status: str = "",
    parts: bool = False,
    limit: int = Query(500, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if status and status not in ("registered", "unregistered"):
        return error(
            "status must be registered or unregistered",
            422,
            error_code="VALIDATION_ERROR",
        )
    if type and type not in A.ASSET_TYPES:
        return error(
            "type must be vehicle, machine, sensor, device or system",
            422,
            error_code="VALIDATION_ERROR",
        )
    rows, can_edit = await collect(db, user, parts=parts)
    fac = A.facets(rows)
    hits = [
        r
        for r in rows
        if A.matches(
            r, q=q.strip(), type_=type, tag=tag.strip(), group=group, status=status
        )
    ]
    return success(
        hits[offset : offset + limit],
        meta={
            "total": len(hits),
            "limit": limit,
            "offset": offset,
            "registered": fac["registered"],
            "unregistered": fac["unregistered"],
            "types": fac["types"],
            "tags": fac["tags"],
            "can_edit": can_edit,
            "type_hints": A.TYPE_HINTS,
        },
    )


@router.get("/facets")
async def asset_facets(
    parts: bool = False,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows, _ = await collect(db, user, parts=parts)
    fac = A.facets(rows)
    return success(
        {
            "types": [
                {"type": t, "count": fac["types"].get(t, 0)} for t in A.ASSET_TYPES
            ],
            "tags": fac["tags"],
            "registered": fac["registered"],
            "unregistered": fac["unregistered"],
        }
    )


@router.get("/template.csv")
async def csv_template(
    user: User = Depends(require_capability("telemetry.view")),
) -> PlainTextResponse:
    return PlainTextResponse(
        A.template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="abenix-assets.csv"'},
    )


@router.post("/import")
async def import_csv(
    request: Request,
    body: dict[str, Any] = Body(...),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return _manage_refusal()
    text = body.get("csv")
    if not isinstance(text, str):
        return error("Send the CSV text as csv.", 422, error_code="VALIDATION_ERROR")
    dry = bool(body.get("dry_run", True))
    teams = await _team_names(db, user.tenant_id)
    rows, problem = A.parse_csv(
        text, {n.lower(): i for i, n in teams.items()}, set(teams)
    )
    if problem:
        return error(
            problem, 422, error_code="VALIDATION_ERROR", details={"rows": rows[:50]}
        )
    existing = {
        (a.grp, a.node, a.device or ""): a
        for a in (
            await db.execute(
                select(TelemetryAsset).where(TelemetryAsset.tenant_id == user.tenant_id)
            )
        )
        .scalars()
        .all()
    }
    summary = {"create": 0, "update": 0, "unchanged": 0, "error": 0}
    for r in rows:
        if r["errors"]:
            r["action"] = "error"
        else:
            a = existing.get((r["group"], r["node"], r["device"]))
            r["action"] = (
                "create" if a is None else "unchanged" if A.same(a, r) else "update"
            )
        summary[r["action"]] += 1
    applied = False
    if not dry and not summary["error"]:
        for r in rows:
            if r["action"] in ("unchanged", "error"):
                continue
            a = existing.get((r["group"], r["node"], r["device"]))
            if a is None:
                a = TelemetryAsset(
                    tenant_id=user.tenant_id,
                    grp=r["group"],
                    node=r["node"],
                    device=r["device"],
                    created_by=user.id,
                )
                db.add(a)
            a.display_name = r["display_name"]
            a.asset_type = r["type"]
            a.tags = r["tags"]
            a.location = r["location"]
            a.fields = r["fields"]
            a.team_id = uuid.UUID(r["team_id"]) if r["team_id"] else None
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "telemetry.assets.import",
            {"created": summary["create"], "updated": summary["update"]},
            request,
            resource_type="telemetry_asset",
        )
        await db.commit()
        await bump_version()
        applied = True
    return success({"rows": rows, "summary": summary, "applied": applied})


def _key(group: str, node: str, device: str | None) -> tuple[str, str, str]:
    return group, node, device or ""


@router.get("/{group}/{node}")
async def get_asset(
    group: str,
    node: str,
    device: str | None = None,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    k = _key(group, node, device)
    rows, _ = await collect(db, user, parts=True, only=k)
    if not rows:
        what = f"{node} part {k[2]}" if k[2] else node
        return error(
            f"No asset called {what} in group {group}. Assets appear when they send data, or name one with PUT.",
            404,
            error_code="NOT_FOUND",
        )
    return success(rows[0])


@router.put("/{group}/{node}")
async def put_asset(
    group: str,
    node: str,
    request: Request,
    device: str | None = None,
    body: dict[str, Any] = Body(...),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return _manage_refusal()
    err: dict[str, str] = {}
    g, n, d = A.clean_key(group, node, device or "", err)
    try:
        row = A.clean(body)
    except A.AssetInvalid as e:
        err.update(e.fields)
        row = {}
    team_id = None
    if body.get("team_id"):
        try:
            team_id = uuid.UUID(str(body["team_id"]))
        except ValueError:
            err["team_id"] = "Pick a team from the list."
        else:
            ok = await db.scalar(
                select(PermissionSet.id).where(
                    PermissionSet.id == team_id,
                    PermissionSet.tenant_id == user.tenant_id,
                )
            )
            if not ok:
                err["team_id"] = "That team does not exist in this workspace."
    if err:
        return _invalid(err)
    a = (
        await db.execute(
            select(TelemetryAsset).where(
                TelemetryAsset.tenant_id == user.tenant_id,
                TelemetryAsset.grp == g,
                TelemetryAsset.node == n,
                TelemetryAsset.device == d,
            )
        )
    ).scalar_one_or_none()
    old = None
    if a is None:
        a = TelemetryAsset(
            tenant_id=user.tenant_id, grp=g, node=n, device=d, created_by=user.id
        )
        db.add(a)
    else:
        old = {"display_name": a.display_name, "type": a.asset_type, "tags": a.tags}
    a.display_name = row["display_name"]
    a.asset_type = row["asset_type"]
    a.tags = row["tags"]
    a.location = row["location"]
    a.fields = row["fields"]
    a.team_id = team_id
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.asset.save",
        {"key": f"{g}/{n}/{d}", "name": row["display_name"]},
        request,
        resource_type="telemetry_asset",
        resource_id=f"{g}/{n}/{d}",
        old_value=old,
        new_value={
            "display_name": a.display_name,
            "type": a.asset_type,
            "tags": a.tags,
        },
    )
    await db.commit()
    await bump_version()
    rows, _ = await collect(db, user, parts=True, only=(g, n, d))
    return success(rows[0] if rows else None)


@router.delete("/{group}/{node}")
async def delete_asset(
    group: str,
    node: str,
    request: Request,
    device: str | None = None,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return _manage_refusal()
    g, n, d = _key(group, node, device)
    a = (
        await db.execute(
            select(TelemetryAsset).where(
                TelemetryAsset.tenant_id == user.tenant_id,
                TelemetryAsset.grp == g,
                TelemetryAsset.node == n,
                TelemetryAsset.device == d,
            )
        )
    ).scalar_one_or_none()
    if a is None:
        return error(
            "That asset has no name or details to remove.", 404, error_code="NOT_FOUND"
        )
    await db.delete(a)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.asset.remove",
        {"key": f"{g}/{n}/{d}"},
        request,
        resource_type="telemetry_asset",
        resource_id=f"{g}/{n}/{d}",
    )
    await db.commit()
    await bump_version()
    return success({"removed": True})
