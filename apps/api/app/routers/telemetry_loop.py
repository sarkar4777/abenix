"""The closed loop: assets agents can find, governed agent commands, and rule steps that run agents.

The agent-runtime tools asset_search, device_state, signal_history and device_command call these
routes with a short-lived token for the person the run acts for, so every read and write keeps
that person's team scope and permissions. The agent's own policy is read here from its saved
tool configuration, never from what the model sends.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.capabilities import cap_words, require_capability
from app.core.deps import get_db
from app.core.responses import error, success
from app.telemetry import access, reads
from app.telemetry import agent_commands as P
from app.telemetry import assets as A
from models.user import User

router = APIRouter(prefix="/api/telemetry/loop", tags=["telemetry"])

HEADLINE_MAX = 6
HISTORY_MINUTES = 15
APPROVAL_EXPIRES_S = 1800
TEST_KIND = "telemetry_rule_test"


def _redis() -> Any:
    from app.routers.telemetry import redis

    return redis()


def _name(row: dict[str, Any]) -> str:
    if row.get("display_name"):
        return row["display_name"]
    return f"{row['node']}/{row['device']}" if row.get("device") else row["node"]


def _invalid(fields: dict[str, str]) -> JSONResponse:
    return error(
        next(iter(fields.values())),
        422,
        error_code="VALIDATION_ERROR",
        details={"fields": fields},
    )


async def _rows(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    from app.routers.telemetry_assets import collect

    rows, _ = await collect(db, user, parts=True)
    return rows


def _index(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {(r["group"], r["node"], r["device"] or ""): r for r in rows}


def facts_of(
    idx: dict[tuple[str, str, str], dict[str, Any]], g: str, n: str, d: str
) -> tuple[list[str], str | None, str]:
    """Tags, type and display name of a key, the part inheriting from its asset."""
    node = idx.get((g, n, "")) or {}
    part = idx.get((g, n, d)) or {} if d else {}
    tags = sorted(set(node.get("tags") or []) | set(part.get("tags") or []))
    atype = part.get("type") or node.get("type")
    base = node.get("display_name") or n
    name = part.get("display_name") or (f"{base} {d}" if d else base)
    return tags, atype, name


async def registry_index(
    db: AsyncSession, tenant: Any, g: str, n: str, d: str
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """The registry rows of one asset and one part, shaped like _index rows."""
    from models.telemetry_rules import TelemetryAsset

    rows = (
        (
            await db.execute(
                select(TelemetryAsset).where(
                    TelemetryAsset.tenant_id == tenant,
                    TelemetryAsset.grp == g,
                    TelemetryAsset.node == n,
                    TelemetryAsset.device.in_(["", d or ""]),
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        (a.grp, a.node, a.device or ""): {
            "display_name": a.display_name,
            "type": a.asset_type,
            "tags": list(a.tags or []),
        }
        for a in rows
    }


def resolve_refs(
    rows: list[dict[str, Any]], refs: list[str]
) -> tuple[list[dict[str, Any]], list[str], dict[str, list[str]]]:
    """Asset keys or display names to rows. Unknown and ambiguous names come back separately."""
    idx = _index(rows)
    found: list[dict[str, Any]] = []
    unknown: list[str] = []
    ambiguous: dict[str, list[str]] = {}
    seen: set[str] = set()

    def add(r: dict[str, Any]) -> None:
        if r["key"] not in seen:
            seen.add(r["key"])
            found.append(r)

    for raw in refs:
        ref = str(raw or "").strip()
        if not ref:
            continue
        k = P.split_key(ref)
        if k and k in idx:
            add(idx[k])
            continue
        low = ref.lower()
        exact = [r for r in rows if (r.get("display_name") or "").lower() == low]
        if not exact:
            exact = [
                r
                for r in rows
                if not r.get("display_name")
                and (r["node"].lower() == low or r["key"].rstrip("/").lower() == low)
            ]
        if len(exact) == 1:
            add(exact[0])
            continue
        if len(exact) > 1:
            ambiguous[ref] = [r["key"] for r in exact[:10]]
            continue
        part = [
            r
            for r in rows
            if low in (r.get("display_name") or "").lower() or low in r["key"].lower()
        ]
        nodes = [r for r in part if not r["device"]]
        pick = nodes if len(nodes) == 1 else part
        if len(pick) == 1:
            add(pick[0])
        elif pick:
            ambiguous[ref] = [r["key"] for r in pick[:10]]
        else:
            unknown.append(ref)
    return found, unknown, ambiguous


def _filter(
    rows: list[dict[str, Any]],
    *,
    q: str = "",
    type_: str = "",
    tag: str = "",
    group: str = "",
    team: str = "",
    online: str = "",
    parts: bool = False,
) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        if r["device"] and not parts:
            continue
        if not A.matches(r, q=q, type_=type_, tag=tag, group=group, status=""):
            continue
        if team and team not in (r.get("team_id") or "", r.get("team_name") or ""):
            continue
        if online == "yes" and r.get("online") is not True:
            continue
        if online == "no" and r.get("online") is True:
            continue
        out.append(r)
    return out


def headline(
    doc: dict[str, Any] | None, want: list[str], limit: int = HEADLINE_MAX
) -> list[dict[str, Any]]:
    """A few latest readings of an asset and its parts, the asked-for ones first."""
    if not doc:
        return []
    out: list[dict[str, Any]] = []
    parts = [("", doc.get("metrics") or [])] + [
        (x["device"], x.get("metrics") or []) for x in doc.get("devices") or []
    ]
    for d, metrics in parts:
        for m in metrics:
            name = m.get("name") or ""
            if want and not any(
                name.lower().startswith(w.lower().rstrip("*")) for w in want
            ):
                continue
            if not want and not isinstance(m.get("value"), (int, float, bool)):
                continue
            out.append(
                {
                    "signal": name,
                    "part": d,
                    "value": m.get("value"),
                    "unit": m.get("unit"),
                    "ts": m.get("ts"),
                    "quality": m.get("quality"),
                }
            )
            if len(out) >= limit:
                return out
    return out


def _shape(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": r["key"],
        "group": r["group"],
        "node": r["node"],
        "device": r["device"],
        "name": _name(r),
        "display_name": r.get("display_name"),
        "registered": r.get("registered"),
        "type": r.get("type"),
        "tags": r.get("tags") or [],
        "team": r.get("team_name"),
        "online": r.get("online"),
        "last_seen": r.get("last_seen"),
        "parts": r.get("parts") or [],
        "fields": r.get("fields") or {},
        "location": r.get("location"),
    }


# finding assets


@router.get("/assets")
async def search_assets(
    q: str = "",
    type: str = "",
    tag: str = "",
    group: str = "",
    team: str = "",
    online: str = Query("", pattern="^(|yes|no)$"),
    parts: bool = False,
    headline_signals: str = "",
    with_readings: bool = True,
    limit: int = Query(25, ge=1, le=200),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Assets the caller can see, by name, type, tag, team, group or online state."""
    if type and type not in A.ASSET_TYPES:
        return error(
            "type is one of vehicle, machine, sensor, device or system.",
            422,
            error_code="VALIDATION_ERROR",
        )
    rows = await _rows(db, user)
    hits = _filter(
        rows,
        q=q.strip(),
        type_=type,
        tag=tag.strip().lower(),
        group=group.strip(),
        team=team.strip(),
        online=online,
        parts=parts,
    )
    total = len(hits)
    hits = hits[:limit]
    want = [s.strip() for s in headline_signals.split(",") if s.strip()][:20]
    out = []
    r = _redis()
    for h in hits:
        row = _shape(h)
        if with_readings:
            doc = await reads.node_detail(
                r, user.tenant_id, h["group"], h["node"], h["device"] or None
            )
            row["readings"] = headline(doc, want)
            if doc is not None and row["online"] is None:
                row["online"] = doc.get("online")
        out.append(row)
    return success(
        out,
        meta={
            "total": total,
            "truncated": total > len(out),
            "types": list(A.ASSET_TYPES),
        },
    )


class ResolveIn(BaseModel):
    refs: list[str] = Field(default_factory=list, max_length=200)
    type: str = ""
    tag: str = ""
    group: str = ""
    q: str = ""
    online: str = ""
    limit: int = Field(default=50, ge=1, le=200)


@router.post("/resolve")
async def resolve(
    body: ResolveIn,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Asset keys or names to keys, or every asset matching a type, tag, group or search."""
    rows = await _rows(db, user)
    found, unknown, ambiguous = resolve_refs(rows, body.refs)
    if not body.refs and (body.type or body.tag or body.group or body.q):
        found = _filter(
            rows,
            q=body.q.strip(),
            type_=body.type.strip(),
            tag=body.tag.strip().lower(),
            group=body.group.strip(),
            online=body.online,
        )
    total = len(found)
    return success(
        {
            "assets": [_shape(r) for r in found[: body.limit]],
            "unknown": unknown,
            "ambiguous": ambiguous,
            "total": total,
            "truncated": total > body.limit,
        }
    )


# what a device_command policy can name


@router.get("/command-targets")
async def command_targets(
    q: str = "",
    limit: int = Query(200, ge=1, le=2000),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Assets, tags and types for the policy editor, plus what the workspace does at each risk tier."""
    rows = await _rows(db, user)
    nodes = _filter(rows, q=q.strip())
    fac = A.facets(rows)
    return success(
        {
            "assets": [_shape(r) for r in nodes[:limit]],
            "total": len(nodes),
            "tags": fac["tags"],
            "types": list(A.ASSET_TYPES),
            "tiers": await tier_actions(db, user.tenant_id),
            "can_command": await access.has(db, user, "telemetry.command"),
        }
    )


@router.get("/command-targets/signals")
async def command_target_signals(
    group: str,
    node: str,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Signals an asset can be sent: declared writable ones, or every Sparkplug metric."""
    from app.telemetry import pipeline

    scope = await access.scope_for(db, user)
    doc = await reads.node_detail(_redis(), user.tenant_id, group, node, None)
    if doc is None or not scope.sees(doc.get("connection_id")):
        return error(
            f"No asset called {node} in group {group} is streaming. Assets appear when their source sends data.",
            404,
            error_code="NOT_FOUND",
        )
    conn = next(
        (c for c in scope.connections if str(c.id) == doc.get("connection_id")), None
    )
    row = pipeline.connection_row(conn) if conn is not None else None
    sparkplug = bool(row and row["decoder"] == "sparkplug_b")
    declared = (row or {}).get("mapping", {}).get("writable") or []
    out: list[dict[str, Any]] = []
    parts = [("", doc.get("metrics") or [])] + [
        (x["device"], x.get("metrics") or []) for x in doc.get("devices") or []
    ]
    for d, metrics in parts:
        for m in metrics:
            name = m.get("name") or ""
            writable = sparkplug or any(
                isinstance(s, dict)
                and s.get("signal") == name
                and s.get("device") in (None, "", d)
                for s in declared
            )
            out.append(
                {
                    "signal": name,
                    "part": d,
                    "value": m.get("value"),
                    "type": m.get("type"),
                    "writable": writable,
                }
            )
    for s in declared:
        if isinstance(s, dict) and s.get("signal"):
            if not any(o["signal"] == s["signal"] for o in out):
                out.append(
                    {
                        "signal": s["signal"],
                        "part": s.get("device") or "",
                        "value": None,
                        "type": None,
                        "writable": True,
                    }
                )
    return success(
        out,
        meta={
            "sparkplug": sparkplug,
            "note": (
                "Sparkplug assets take a command on any metric they report."
                if sparkplug
                else "Only signals declared writable in the source's mapping take a command."
            ),
        },
    )


async def tier_actions(db: AsyncSession, tenant_id: Any) -> dict[str, str]:
    from engine import risk
    from models.governance import RiskPolicy

    stored = {
        p.tier: p.policy
        for p in (
            await db.execute(
                select(RiskPolicy).where(RiskPolicy.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    }
    return {
        t: str(risk.merged_policy(t, stored.get(t)).get("tool_call_action") or "allow")
        for t in risk.TIERS
    }


# governed agent commands


class ReadSignal(BaseModel):
    group: str = Field(max_length=255)
    node: str = Field(max_length=255)
    device: str = Field(default="", max_length=255)
    signal: str = Field(max_length=512)


class AgentCommandIn(BaseModel):
    agent_id: uuid.UUID
    execution_id: uuid.UUID | None = None
    asset: str | None = Field(default=None, max_length=600)
    group: str | None = Field(default=None, max_length=255)
    node: str | None = Field(default=None, max_length=255)
    part: str | None = Field(default=None, max_length=255)
    device: str | None = Field(default=None, max_length=255)
    signal: str = Field(min_length=1, max_length=512)
    value: Any = None
    reason: str = Field(default="", max_length=2000)
    approval_id: uuid.UUID | None = None
    # signals the agent read in this run, charted for the approver when no rule fired
    read: list[ReadSignal] = Field(default_factory=list, max_length=20)


class _Refused(Exception):
    def __init__(self, resp: JSONResponse) -> None:
        self.resp = resp


def _refuse(msg: str, code: int, ecode: str, **details: Any) -> _Refused:
    return _Refused(error(msg, code, error_code=ecode, details=details or None))


async def _earned(db: AsyncSession, tenant_id: Any, agent_id: Any) -> bool:
    from models.autonomy import ActionType, AutonomyGrant

    hit = await db.scalar(
        select(AutonomyGrant.id)
        .join(ActionType, ActionType.id == AutonomyGrant.action_type_id)
        .where(
            AutonomyGrant.tenant_id == tenant_id,
            AutonomyGrant.agent_id == agent_id,
            AutonomyGrant.state != "removed",
            ActionType.tool_name == P.TOOL,
        )
        .limit(1)
    )
    return hit is not None


async def _prepare(
    db: AsyncSession, user: User, body: AgentCommandIn
) -> dict[str, Any]:
    """Every check a command goes through before an approval or a send. Raises _Refused."""
    from models.agent import Agent
    from models.execution import Execution

    reason = (body.reason or "").strip()
    if len(reason) < 3:
        raise _refuse(
            "Say why you want this command, in a sentence. It is shown to the approver and kept in the audit log.",
            422,
            "VALIDATION_ERROR",
        )
    agent = (
        await db.execute(
            select(Agent).where(
                Agent.id == body.agent_id, Agent.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if agent is None:
        raise _refuse("No agent with that id in this workspace.", 404, "NOT_FOUND")
    execution = None
    if body.execution_id:
        execution = (
            await db.execute(
                select(Execution).where(
                    Execution.id == body.execution_id,
                    Execution.tenant_id == user.tenant_id,
                )
            )
        ).scalar_one_or_none()
        if execution is None or execution.agent_id != agent.id:
            raise _refuse(
                "That run does not belong to this agent.", 409, "RUN_MISMATCH"
            )
    raw = P.policy_of(agent)
    if not raw:
        raise _refuse(P.NO_POLICY, 403, "NO_COMMAND_POLICY")
    policy, _ = P.clean(raw)
    if body.asset:
        rows = await _rows(db, user)
        idx = _index(rows)
        found, unknown, ambiguous = resolve_refs(rows, [body.asset])
        if ambiguous:
            keys = next(iter(ambiguous.values()))
            raise _refuse(
                f"More than one asset is called {body.asset}: {', '.join(keys)}. Use the key.",
                409,
                "AMBIGUOUS_ASSET",
                candidates=keys,
            )
        if not found:
            raise _refuse(
                f"No asset called {body.asset} that you can see. Use asset_search to find its key.",
                404,
                "NOT_FOUND",
            )
        g, n, d = found[0]["group"], found[0]["node"], found[0]["device"] or ""
        part = body.part if body.part is not None else body.device
        if part:
            d = part.strip()
    else:
        g, n = (body.group or "").strip(), (body.node or "").strip()
        d = (body.part if body.part is not None else body.device or "").strip()
        if not g or not n:
            raise _refuse(
                "Name the asset, by its key such as groundwork/ipc-ex1 or its display name.",
                422,
                "VALIDATION_ERROR",
            )
        # a key needs only its registry rows, the send after an approval stays quick
        idx = await registry_index(db, user.tenant_id, g, n, d)
    tags, atype, name = facts_of(idx, g, n, d)
    where = f"{name} ({P.key(g, n, d)})"
    if not P.asset_allowed(policy, g, n, d, tags, atype):
        raise _refuse(P.refusal_asset(policy, where), 403, "NOT_ALLOWED")
    signal = body.signal.strip()
    if not P.signal_allowed(policy, signal):
        raise _refuse(P.refusal_signal(policy, signal, where), 403, "NOT_ALLOWED")
    if not await access.has(db, user, "telemetry.command"):
        raise _refuse(
            f"{user.email}, who this agent runs for, does not have {cap_words('telemetry.command')}, "
            "so it cannot command anything. An admin can add them to Machine operators under Admin, Permissions.",
            403,
            "FORBIDDEN",
        )
    if body.approval_id is not None:
        # a send that carries an approval only needs that approval checked, which the send does
        earned, needs, why = False, True, "A person approved it."
    else:
        earned = await _earned(db, user.tenant_id, agent.id)
        tiers = await tier_actions(db, user.tenant_id)
        needs, why, blocked = P.approval_needed(
            policy, tiers.get(policy.get("tier") or "high"), earned
        )
        if blocked:
            raise _refuse(blocked, 403, "TIER_BLOCKED")
    return {
        "agent": agent,
        "execution": execution,
        "policy": policy,
        "group": g,
        "node": n,
        "device": d,
        "signal": signal,
        "value": body.value,
        "reason": reason,
        "name": name,
        "type": atype,
        "tags": tags,
        "needs_approval": needs,
        "why": why,
        "earned": earned,
        "test": bool(execution is not None and execution.trigger_kind == TEST_KIND),
    }


async def _dry_run(
    request: Request, db: AsyncSession, user: User, c: dict[str, Any]
) -> dict[str, Any]:
    from app.routers.telemetry import CommandIn, send_command

    resp = await send_command(
        CommandIn(
            group=c["group"],
            node=c["node"],
            device=c["device"],
            signal=c["signal"],
            value=c["value"],
            reason=c["reason"],
            dry_run=True,
        ),
        request,
        user,
        db,
    )
    doc = json.loads(resp.body or b"{}")
    if resp.status_code >= 300:
        err = doc.get("error") or {}
        raise _Refused(
            error(
                "Not sent. " + str(err.get("message") or "The command was refused."),
                resp.status_code,
                error_code=err.get("error_code") or "REFUSED",
                details=err.get("details"),
            )
        )
    return doc.get("data") or {}


async def _current(user: User, c: dict[str, Any]) -> dict[str, Any] | None:
    from app.telemetry import keys as K

    raw = await _redis().hget(
        K.device(user.tenant_id, c["group"], c["node"], c["device"]),
        K.metric_field(c["signal"]),
    )
    if not raw:
        return None
    try:
        m = json.loads(raw)
    except ValueError:
        return None
    return {"value": m.get("v"), "ts": m.get("ts"), "quality": m.get("q") or "good"}


async def recent_history(
    tenant: Any, g: str, n: str, d: str, signal: str, minutes: int = HISTORY_MINUTES
) -> dict[str, Any] | None:
    """A short bucketed look back at one signal, or None when history is not set up."""
    import asyncio

    from app.routers.telemetry import tsdb
    from app.telemetry import history

    to = datetime.now(timezone.utc)
    frm = to - timedelta(minutes=minutes)
    try:
        pool = await asyncio.wait_for(tsdb(), timeout=2)
        res = await asyncio.wait_for(
            history.query(pool, str(tenant), g, n, d, [signal], frm, to, 30),
            timeout=3,
        )
    except Exception:  # noqa: BLE001
        return None
    pts = (res.get("series") or [{}])[0].get("points") or []
    nums = [p for p in pts if p.get("avg") is not None]
    summary = None
    if nums:
        summary = {
            "first": nums[0]["avg"],
            "last": nums[-1]["avg"],
            "min": min(p["min"] for p in nums),
            "max": max(p["max"] for p in nums),
        }
    return {
        "signal": signal,
        "minutes": minutes,
        "step_seconds": res.get("step_seconds"),
        "points": [
            {
                "t": p["t"],
                "avg": p.get("avg"),
                "min": p.get("min"),
                "max": p.get("max"),
                **({"txt": p["txt"]} if p.get("txt") is not None else {}),
            }
            for p in pts
        ][-60:],
        "summary": summary,
    }


def _target(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": P.key(c["group"], c["node"], c["device"]),
        "group": c["group"],
        "node": c["node"],
        "device": c["device"],
        "name": c["name"],
        "type": c["type"],
        "tags": c["tags"],
    }


def _command(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "group": c["group"],
        "node": c["node"],
        "device": c["device"],
        "signal": c["signal"],
        "value": c["value"],
    }


EVIDENCE_MAX = 2


def is_state(value: Any, current: dict[str, Any] | None) -> bool:
    """Text and on/off signals are states, numbers are charted."""
    v = (current or {}).get("value", value)
    if v is None:
        v = value
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        return False
    try:
        float(str(v))
        return False
    except (TypeError, ValueError):
        return True


def state_timeline(
    points: list[dict[str, Any]], current: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """When the signal changed, as [{t, value}], the reading now last."""
    out: list[dict[str, Any]] = []
    on_off = isinstance((current or {}).get("value"), bool)
    for p in points:
        if p.get("txt") is not None:
            v: Any = p["txt"]
        elif p.get("avg") is not None:
            v = bool(p["avg"] >= 0.5) if on_off else p["avg"]
        else:
            continue
        if not out or out[-1]["value"] != v:
            out.append({"t": p["t"], "value": v})
            if len(out) == 1:
                # it may have held this value before the window began, the time is a bound
                out[-1]["before"] = True
    if current is not None and current.get("value") is not None:
        if not out or out[-1]["value"] != current["value"]:
            out.append({"t": current.get("ts"), "value": current["value"]})
    return out[-30:]


def words(signal: str) -> str:
    """Hydraulics/OilTemp_C reads Hydraulics oil temp."""
    import re

    parts = [p for p in str(signal or "").split("/") if p]
    if not parts:
        return str(signal or "")
    last = re.sub(r"_[A-Za-z%]+$", "", parts[-1])
    last = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", last).replace("_", " ").lower()
    head = " ".join(parts[:-1])
    return f"{head} {last}".strip() if head else last[:1].upper() + last[1:]


def unit_of(signal: str) -> str | None:
    import re

    m = re.search(r"_([A-Za-z%]+)$", str(signal or ""))
    return m.group(1) if m else None


_MEANS = re.compile(r"mean (-?[\d.]+) against (-?[\d.]+)")
_OPS = {">": "above", ">=": "at or above", "<": "below", "<=": "at or below"}


def unit_words(unit: str | None) -> str:
    if not unit:
        return ""
    return {"C": " °C", "F": " °F", "pct": " %"}.get(unit, f" {unit}")


def _n(v: Any) -> str:
    """A number as people read it: whole when whole, one decimal past 10, two below."""
    f = float(v)
    if f.is_integer():
        return str(int(f))
    digits = 0 if abs(f) >= 1000 else 1 if abs(f) >= 10 else 2
    return f"{f:.{digits}f}".rstrip("0").rstrip(".")


def _mins(seconds: Any, default: float) -> str:
    try:
        m = float(seconds or default) / 60
    except (TypeError, ValueError):
        m = default / 60
    return f"{_n(round(m, 1))} min"


def rule_lines(
    condition: dict[str, Any] | None,
    value: Any = None,
    detail: str = "",
    fired_at_ms: int | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    """What to draw next to the readings for the rule that fired: lines, a caption, a gap.

    Every number comes from the rule as saved and the firing as recorded, nothing is
    worked out again from history.
    """
    c = condition or {}
    kind = c.get("kind")
    u = unit_words(unit)
    marks: list[dict[str, Any]] = []
    caption = None
    gap = None

    def limit(v: Any, words: str) -> None:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            marks.append(
                {"label": f"fires {words} {_n(v)}{u}", "value": v, "kind": "limit"}
            )

    if kind == "threshold":
        limit(c.get("value"), _OPS.get(str(c.get("op") or ">"), "past"))
    elif kind == "range":
        limit(c.get("min"), "below")
        limit(c.get("max"), "above")
    elif kind == "deviation":
        m = _MEANS.search(detail or "")
        base_w = _mins(c.get("baseline_s"), 1800)
        if m:
            recent, base = float(m.group(1)), float(m.group(2))
            marks.append(
                {
                    "label": f"normal {_n(base)}{u}, last {base_w}",
                    "value": base,
                    "kind": "normal",
                }
            )
            t = c.get("threshold")
            d = c.get("direction") or "up"
            if isinstance(t, (int, float)):
                if (c.get("mode") or "ratio") == "ratio":
                    if d in ("up", "either"):
                        limit(base * t, "above")
                    if d == "down":
                        limit(base * t, "below")
                    if d == "either" and t:
                        limit(base / t, "below")
                else:
                    z = value if isinstance(value, (int, float)) else None
                    sd = (recent - base) / z if z else None
                    if sd:
                        sd = abs(sd)
                        if d in ("up", "either"):
                            limit(base + t * sd, "above")
                        if d in ("down", "either"):
                            limit(base - t * sd, "below")
        caption = (
            f"Fires when the last {_mins(c.get('window_s'), 300)} run "
            f"{'a factor of ' + _n(c.get('threshold')) if (c.get('mode') or 'ratio') == 'ratio' else _n(c.get('threshold')) + ' standard deviations'} "
            f"away from the {base_w} before."
        )
    elif kind == "rate":
        caption = (
            f"Fires when it changes faster than {_n(c.get('limit') or 0)}{u} a "
            f"{ {'s': 'second', 'm': 'minute', 'h': 'hour'}.get(str(c.get('per') or 's'), 'second') }, "
            f"over {_n(c.get('window_s') or 10)} s. There is no level to draw."
        )
    elif kind == "stale":
        secs = c.get("seconds")
        caption = f"Fires when nothing arrives for {_n(secs or 0)} s. The shaded end is the silence."
        if fired_at_ms and secs:
            gap = {
                "from": int(fired_at_ms - float(secs) * 1000),
                "to": int(fired_at_ms),
                "label": f"no data for {_n(secs)} s",
            }
    elif kind == "state":
        caption = (
            f"Fires when it {'is not' if c.get('op') == 'not_equals' else 'is'} "
            f"{c.get('equals')}. There is no level to draw."
        )
    elif kind == "geofence":
        on = "leaves" if (c.get("on") or "exit") == "exit" else "enters"
        caption = f"Fires when it {on} {c.get('zone') or 'the zone'}. The position is on the Telemetry map."
    elif kind == "count":
        caption = (
            f"Fires when it happens more than {_n(c.get('count') or 0)} times in "
            f"{_mins(c.get('window_s'), 60)}."
        )
    elif kind:
        caption = "This rule has no level to draw."
    return {"marks": marks, "caption": caption, "gap": gap}


def marks_of(condition: dict[str, Any] | None) -> list[dict[str, Any]]:
    return rule_lines(condition)["marks"]


def _numeric(hist: dict[str, Any] | None) -> bool:
    return bool(hist) and any(
        p.get("avg") is not None for p in (hist or {}).get("points") or []
    )


async def firing_of(db: AsyncSession, tenant: Any, execution_id: Any) -> Any:
    """The rule firing that started this run, if a rule did."""
    from models.telemetry_rules import TelemetryRuleFiring

    if not execution_id:
        return None
    return (
        (
            await db.execute(
                select(TelemetryRuleFiring)
                .where(
                    TelemetryRuleFiring.tenant_id == tenant,
                    TelemetryRuleFiring.actions.contains(
                        [{"ref": {"execution_id": str(execution_id)}}]
                    ),
                )
                .order_by(TelemetryRuleFiring.fired_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def gather_evidence(
    db: AsyncSession, user: User, c: dict[str, Any], body: Any
) -> list[dict[str, Any]]:
    """What made the agent ask: the signal that fired the rule, else what it read."""
    from models.telemetry_rules import TelemetryRule

    out: list[dict[str, Any]] = []
    try:
        f = await firing_of(db, user.tenant_id, body.execution_id)
    except Exception:  # noqa: BLE001
        f = None
    if f is not None:
        rule = await db.get(TelemetryRule, f.rule_id) if f.rule_id else None
        hist = (
            await recent_history(
                user.tenant_id, f.grp, f.node, f.device or "", f.signal
            )
            if f.signal
            else None
        )
        lines = rule_lines(
            rule.condition if rule is not None else None,
            f.value,
            f.detail or "",
            int(f.fired_at.timestamp() * 1000) if f.fired_at else None,
            unit_of(f.signal or ""),
        )
        numeric = _numeric(hist)
        if numeric or lines["caption"]:
            minutes = (hist or {}).get("minutes") or HISTORY_MINUTES
            out.append(
                {
                    "source": "firing",
                    "title": (
                        f"Why it asked: {words(f.signal)}, last {minutes} minutes"
                        if f.signal
                        else f"Why it asked: {f.rule_name}"
                    ),
                    "signal": f.signal,
                    "unit": unit_of(f.signal or ""),
                    "key": P.key(f.grp, f.node, f.device or ""),
                    "rule": f.rule_name,
                    "detail": f.detail,
                    **lines,
                    "points": hist["points"] if numeric else [],
                    "summary": (hist or {}).get("summary"),
                }
            )
    if out:
        return out
    seen = set()
    for r in body.read or []:
        k = (r.group, r.node, r.device or "", r.signal)
        if k in seen or r.signal == c["signal"]:
            continue
        seen.add(k)
        hist = await recent_history(
            user.tenant_id, r.group, r.node, r.device or "", r.signal
        )
        if not _numeric(hist):
            continue
        out.append(
            {
                "source": "read",
                "title": f"What it read: {words(r.signal)}, last {hist['minutes']} minutes",
                "signal": r.signal,
                "unit": unit_of(r.signal),
                "key": P.key(r.group, r.node, r.device or ""),
                "marks": [],
                "caption": None,
                "gap": None,
                "points": hist["points"],
                "summary": hist.get("summary"),
            }
        )
        if len(out) >= EVIDENCE_MAX:
            break
    return out


def command_summary(
    agent: str, signal: str, before: Any, value: Any, where: str, reason: str
) -> str:
    return (
        f"{agent} proposes setting {signal} from {_show(before)} to {_show(value)} "
        f"on {where}. Its reason: {reason}"
    )


def _show(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)


@router.post("/commands/propose")
async def propose_command(
    body: AgentCommandIn,
    request: Request,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Check an agent's command against its policy and, when a person must approve, ask for it."""
    t0 = time.time()
    try:
        c = await _prepare(db, user, body)
        preview = await _dry_run(request, db, user, c)
    except _Refused as r:
        return r.resp
    current = await _current(user, c)
    out: dict[str, Any] = {
        "target": _target(c),
        "command": _command(c),
        "preview": {k: preview.get(k) for k in ("topic", "payload", "target")},
        "current": current,
        "needs_approval": c["needs_approval"],
        "why": c["why"],
        "governed_by": "autonomy" if c["earned"] else "policy",
        "test": c["test"],
        "approval": None,
        "checks_ms": int((time.time() - t0) * 1000),
    }
    if c["test"]:
        out["message"] = (
            f"Test run: nothing was sent. It would set {c['signal']} to {_show(c['value'])} on {c['name']}."
        )
        return success(out)
    if not c["needs_approval"]:
        return success(out)
    hist = await recent_history(
        user.tenant_id, c["group"], c["node"], c["device"], c["signal"]
    )
    states = None
    if is_state(c["value"], current):
        # a text or on/off signal reads as states, never as a chart
        states = state_timeline((hist or {}).get("points") or [], current)
        hist = None
    evidence = await gather_evidence(db, user, c, body)
    agent = c["agent"]
    title = f"{agent.name} wants to set {c['signal']} to {_show(c['value'])} on {c['name']}"[
        :255
    ]
    payload = {
        "summary": command_summary(
            agent.name,
            c["signal"],
            (current or {}).get("value", "unknown"),
            c["value"],
            c["name"],
            c["reason"],
        ),
        "command": _command(c),
        "asset": _target(c),
        "reason": c["reason"],
        "agent": {"id": str(agent.id), "name": agent.name},
        "execution_id": str(body.execution_id) if body.execution_id else None,
        "current": current,
        "preview": out["preview"],
        "history": hist,
        "states": states,
        "evidence": evidence,
        "policy": P.describe(c["policy"]),
        "why": c["why"],
        "requested_at": int(time.time() * 1000),
    }
    from app.schemas.connectors import ApprovalCreate

    tier = c["policy"].get("tier") if c["policy"].get("approval") == "tier" else None
    try:
        a = await open_approval(
            db,
            user,
            ApprovalCreate(
                title=title,
                payload=payload,
                required_signoffs=1,
                expires_seconds=APPROVAL_EXPIRES_S,
                agent_id=agent.id,
                agent_execution_id=body.execution_id,
                gate_kind=P.GATE_KIND,
                risk_tier=tier,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return error(
            f"The approval could not be created: {exc}",
            502,
            error_code="APPROVAL_FAILED",
        )
    out["approval"] = {
        "id": str(a.id),
        "link": f"/approvals?id={a.id}",
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "expires_seconds": APPROVAL_EXPIRES_S,
    }
    return success(out)


async def open_approval(db: AsyncSession, user: User, body: Any) -> Any:
    """The approval row and its approval.requested event, as POST /api/approvals makes them.

    Telling people about it runs after the reply, so the agent starts waiting at once
    and an approval given in the first seconds is acted on straight away.
    """
    from app.routers.approvals import _tier_floor
    from app.services.events import emit
    from models.approval import Approval, ApprovalStatus

    required, policy = await _tier_floor(db, user, body)
    a = Approval(
        tenant_id=user.tenant_id,
        agent_id=body.agent_id,
        agent_execution_id=body.agent_execution_id,
        title=body.title,
        payload=body.payload,
        required_signoffs=required,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=user.id,
        expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=body.expires_seconds or APPROVAL_EXPIRES_S),
        gate_kind=body.gate_kind,
        policy=policy,
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
            "gate_kind": a.gate_kind,
            "required_signoffs": a.required_signoffs,
        },
    )
    await db.commit()
    await db.refresh(a)
    from app.routers.approvals import notify_pending_later

    notify_pending_later(a.id, user.id)
    return a


def settle_confirmation(
    data: dict[str, Any], before: dict[str, Any] | None, value: Any, signal: str
) -> dict[str, Any]:
    """An asset that already reported the value counts as confirmed, it may not report it again."""
    from app.routers.telemetry import _same

    if data.get("confirmed") or not data.get("published") or not before:
        return data
    if before.get("value") is None or not _same(before.get("value"), value):
        return data
    return {
        **data,
        "confirmed": True,
        "already_at_value": True,
        "confirm_note": (
            f"{signal} already read {P.norm_value(value)} before the command, so it was sent "
            "and the current reading counts as the confirmation."
        ),
    }


def _approver(a: Any) -> dict[str, Any]:
    for s in reversed(a.signoffs or []):
        if isinstance(s, dict) and s.get("decision") == "approve":
            return s
    return {}


@router.post("/commands/send")
async def send_agent_command(
    body: AgentCommandIn,
    request: Request,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Send an agent's command after its policy, the approval it needed and its rate allow it."""
    from app.routers.telemetry import CommandIn, send_command
    from app.services.events import emit
    from models.approval import Approval, ApprovalStatus

    received = int(time.time() * 1000)
    try:
        c = await _prepare(db, user, body)
    except _Refused as r:
        return r.resp
    agent = c["agent"]
    if c["test"]:
        return success(
            {
                "published": False,
                "test": True,
                "message": f"Test run: nothing was sent. It would set {c['signal']} to {_show(c['value'])} on {c['name']}.",
            }
        )
    approval = None
    if c["needs_approval"]:
        if body.approval_id is None:
            return error(
                f"Not sent. {c['why']} Propose it first so a person can approve it.",
                409,
                error_code="APPROVAL_REQUIRED",
            )
        approval = (
            await db.execute(
                select(Approval).where(
                    Approval.id == body.approval_id,
                    Approval.tenant_id == user.tenant_id,
                )
            )
        ).scalar_one_or_none()
        status = getattr(getattr(approval, "status", None), "value", None)
        if (
            approval is None
            or approval.gate_kind != P.GATE_KIND
            or approval.agent_id != agent.id
            or (body.execution_id and approval.agent_execution_id != body.execution_id)
        ):
            return error(
                "Not sent. That approval is not for this agent's command.",
                409,
                error_code="APPROVAL_MISMATCH",
            )
        if status != ApprovalStatus.approved.value:
            return error(
                f"Not sent. The approval is {status or 'missing'}, not approved.",
                409,
                error_code="NOT_APPROVED",
            )
        payload = dict(approval.payload or {})
        if not P.same_command(payload, _command(c)):
            return error(
                "Not sent. The approval was for a different asset, signal or value.",
                409,
                error_code="APPROVAL_MISMATCH",
            )
        if payload.get("sent_at"):
            return error(
                "Not sent. That approval was already used for a command. Propose it again.",
                409,
                error_code="APPROVAL_USED",
            )
    r = _redis()
    rk = P.rate_key(user.tenant_id, agent.id, int(time.time() // 60))
    pipe = r.pipeline(transaction=False)
    pipe.incr(rk)
    pipe.expire(rk, 120)
    used, _ = await pipe.execute()
    limit = int(c["policy"].get("rate_per_minute") or P.DEFAULT_RATE)
    if int(used) > limit:
        return error(
            f"Not sent. {agent.name} may send at most {limit} commands a minute. Wait a minute and try again.",
            429,
            error_code="RATE_LIMITED",
        )
    before = await _current(user, c)
    resp = await send_command(
        CommandIn(
            group=c["group"],
            node=c["node"],
            device=c["device"],
            signal=c["signal"],
            value=c["value"],
            reason=f"{agent.name}: {c['reason']}"[:2000],
            confirm_timeout_ms=int(c["policy"].get("confirm_timeout_ms") or 0),
        ),
        request,
        user,
        db,
    )
    doc = json.loads(resp.body or b"{}")
    if resp.status_code >= 300:
        err = doc.get("error") or {}
        return error(
            "Not sent. " + str(err.get("message") or "The command was refused."),
            resp.status_code,
            error_code=err.get("error_code") or "REFUSED",
            details=err.get("details"),
        )
    data = settle_confirmation(doc.get("data") or {}, before, c["value"], c["signal"])
    if approval is not None:
        # one approval covers one command
        approval.payload = {**(approval.payload or {}), "sent_at": received}
    signer = _approver(approval) if approval is not None else {}
    timings = {
        "approval_requested_at": (
            (approval.payload or {}).get("requested_at")
            if approval is not None
            else None
        ),
        "approved_at": (
            int(approval.decided_at.timestamp() * 1000)
            if approval is not None and approval.decided_at
            else None
        ),
        "received_at": received,
        "published_at": data.get("published_at"),
        "checks_ms": (data.get("published_at") or received) - received,
        "confirm_ms": data.get("confirm_ms"),
    }
    exec_id = str(body.execution_id) if body.execution_id else None
    details = {
        "agent_id": str(agent.id),
        "agent": agent.name,
        "execution_id": exec_id,
        "for_user": user.email,
        "group": c["group"],
        "node": c["node"],
        "device": c["device"],
        "asset": c["name"],
        "signal": c["signal"],
        "value": c["value"],
        "reason": c["reason"],
        "approval_id": str(approval.id) if approval is not None else None,
        "approved_by": signer.get("user_email"),
        "approved_by_name": signer.get("user_name") or signer.get("user_email"),
        "governed_by": "autonomy" if c["earned"] else "policy",
        "policy": P.describe(c["policy"]),
        "published": bool(data.get("published")),
        "confirmed": data.get("confirmed"),
        "already_at_value": bool(data.get("already_at_value")),
        "topic": data.get("topic"),
        "timings": timings,
    }
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.agent_command",
        details,
        request,
        resource_type="agent",
        resource_id=str(agent.id),
    )
    await emit(db, user.tenant_id, "telemetry.command_sent", details)
    await db.commit()
    return success(
        {
            "published": bool(data.get("published")),
            "confirmed": data.get("confirmed"),
            "confirm_ms": data.get("confirm_ms"),
            "confirm_note": data.get("confirm_note"),
            "already_at_value": bool(data.get("already_at_value")),
            "confirmed_by": data.get("confirmed_by"),
            "at": data.get("at"),
            "topic": data.get("topic"),
            "target": _target(c),
            "command": _command(c),
            "approval_id": details["approval_id"],
            # a name, not an email, so the agent never repeats personal data in its answer
            "approved_by": details["approved_by_name"],
            "timings": timings,
        }
    )


# the rule builder's run step


class RunPreviewIn(BaseModel):
    rule_id: uuid.UUID | None = None
    firing_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    message: str = Field(default="", max_length=4000)
    scope: dict[str, Any] | None = None
    condition: dict[str, Any] | None = None
    name: str = Field(default="", max_length=160)


async def _firing_for(
    db: AsyncSession, user: User, body: RunPreviewIn
) -> tuple[dict[str, Any] | None, str]:
    """The firing to test with: the one named, else the rule's last, else a reading now."""
    from models.telemetry_rules import TelemetryRuleFiring

    q = select(TelemetryRuleFiring).where(
        TelemetryRuleFiring.tenant_id == user.tenant_id
    )
    if body.firing_id:
        q = q.where(TelemetryRuleFiring.id == body.firing_id)
    elif body.rule_id:
        q = q.where(TelemetryRuleFiring.rule_id == body.rule_id)
    else:
        q = None
    if q is not None:
        f = (
            (await db.execute(q.order_by(TelemetryRuleFiring.fired_at.desc()).limit(1)))
            .scalars()
            .first()
        )
        if f is not None:
            return dict(f.context or {}), "firing"
    s = body.scope or {}
    sig = (body.condition or {}).get("signal")
    if s.get("kind") == "asset" and s.get("group") and s.get("node"):
        g, n = s["group"], s["node"]
        d = "" if s.get("device") in (None, "*") else s.get("device") or ""
        doc = await reads.node_detail(_redis(), user.tenant_id, g, n, None)
        value = None
        if doc and sig:
            for part in [
                {"device": "", "metrics": doc.get("metrics") or []},
                *(doc.get("devices") or []),
            ]:
                for m in part.get("metrics") or []:
                    if m["name"] == sig and (not d or part["device"] == d):
                        value, d = m.get("value"), part["device"]
        rows = await _rows(db, user)
        tags, atype, name = facts_of(_index(rows), g, n, d)
        rule = body.name or "This rule"
        return {
            "rule": rule,
            "rule_id": str(body.rule_id) if body.rule_id else None,
            "severity": "warning",
            "detail": f"Test of {rule} on {name}"
            + (f", {sig} is {value}" if sig and value is not None else "")
            + ".",
            "group": g,
            "node": n,
            "device": d,
            "asset": name,
            "asset_type": atype,
            "tags": tags,
            "fields": {},
            "location": None,
            "signal": sig,
            "value": value,
            "at": datetime.now(timezone.utc).isoformat(),
            "firing_id": None,
        }, "latest"
    return None, "none"


@router.post("/run-preview")
async def run_preview(
    body: RunPreviewIn,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """What a rule's run step hands the agent: the message and the context, from the last firing."""
    from app.telemetry.rules import actions as X

    ctx, source = await _firing_for(db, user, body)
    if ctx is None:
        return success(
            {
                "source": "none",
                "message": None,
                "context": None,
                "note": "This rule has not fired yet and has no single asset to read now. "
                "Pick one asset in Watch, or wait for a firing.",
            }
        )
    if "history" not in ctx and ctx.get("signal"):
        ctx["history"] = await recent_history(
            user.tenant_id,
            ctx["group"],
            ctx["node"],
            ctx.get("device") or "",
            ctx["signal"],
        )
    message = X.run_message({"message": body.message}, ctx)
    return success(
        {
            "source": source,
            "message": message,
            "context": {"telemetry": ctx},
            "note": (
                "From the rule's last firing."
                if source == "firing"
                else "The rule has not fired yet, so this uses the asset's reading now."
            ),
        }
    )


@router.post("/run-test")
async def run_test(
    body: RunPreviewIn,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run the step's agent once with the last firing. Its commands are checked, never sent."""
    from app.routers.triggers import dispatch_execution
    from app.services.agent_share import resolve_agent_access
    from app.telemetry.rules import actions as X
    from models.agent import Agent, AgentType
    from models.resource_share import SharePermission
    from sqlalchemy import or_

    if not body.agent_id:
        return _invalid({"agent_id": "Pick the agent or pipeline to test."})
    agent = (
        await db.execute(
            select(Agent).where(
                Agent.id == body.agent_id,
                or_(
                    Agent.tenant_id == user.tenant_id,
                    Agent.agent_type == AgentType.OOB,
                ),
            )
        )
    ).scalar_one_or_none()
    if agent is None:
        return error(
            "That agent or pipeline does not exist in this workspace.",
            404,
            error_code="NOT_FOUND",
        )
    if not await resolve_agent_access(
        db, user, agent, permission_required=SharePermission.EXECUTE
    ):
        return error(
            f"You cannot run {agent.name}. Ask its owner to share it with you with run rights.",
            403,
            error_code="FORBIDDEN",
        )
    ctx, source = await _firing_for(db, user, body)
    if ctx is None:
        return error(
            "Nothing to test with yet: the rule has not fired and watches more than one asset. "
            "Pick one asset in Watch, or wait for a firing.",
            422,
            error_code="NO_FIRING",
        )
    if "history" not in ctx and ctx.get("signal"):
        ctx["history"] = await recent_history(
            user.tenant_id,
            ctx["group"],
            ctx["node"],
            ctx.get("device") or "",
            ctx["signal"],
        )
    message = X.run_message({"message": body.message}, ctx)
    execution, dispatched = await dispatch_execution(
        db,
        agent=agent,
        user=user,
        message=message,
        context={"telemetry": ctx, "test": True},
        trigger_kind=TEST_KIND,
        trigger_name=f"Test of {body.name or 'a signal rule'}"[:255],
    )
    if not dispatched:
        return error(
            getattr(execution, "error_message", None) or f"{agent.name} did not start.",
            502,
            error_code="NOT_STARTED",
            details={"execution_id": str(execution.id)},
        )
    return success(
        {
            "execution_id": str(execution.id),
            "link": f"/executions/{execution.id}",
            "source": source,
            "message": message,
        }
    )
