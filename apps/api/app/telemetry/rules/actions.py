"""What a rule does when it fires. Each action returns {kind, status, message, ref} in plain words."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("telemetry.rules.actions")

ALERTS_KEY = "tel:rules:alerts"
COMMAND_LIMIT_PER_SEC = 20


# {steps.2.output.action} or {{steps.2.output}}, steps counted from 1
STEP_REF = re.compile(r"\{\{?\s*steps\.(\d+)\.([A-Za-z0-9_.\-]+?)\s*\}\}?")
OUTPUT_TEXT_MAX = 20_000
RUN_WAIT_S = 600
RUN_WAIT_MAX_S = 3600


def step_value(ctx: dict[str, Any], n: int, path: str) -> tuple[bool, Any]:
    steps = ctx.get("steps") or []
    if n < 1 or n > len(steps):
        return False, None
    cur: Any = steps[n - 1]
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return False, None
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def render(template: str, ctx: dict[str, Any]) -> str:
    out = template or ""
    for k, v in ctx.items():
        if isinstance(v, (dict, list)):
            continue
        out = out.replace("{{" + k + "}}", "" if v is None else str(v))
    return STEP_REF.sub(
        lambda m: _text(step_value(ctx, int(m.group(1)), m.group(2))[1]), out
    )


def resolve_value(v: Any, ctx: dict[str, Any]) -> Any:
    """A value that is one step reference keeps its type, other text is filled in."""
    if not isinstance(v, str):
        return v
    m = STEP_REF.fullmatch(v.strip())
    if m:
        return step_value(ctx, int(m.group(1)), m.group(2))[1]
    return render(v, ctx) if ("{" in v) else v


def step_refs(text: Any) -> set[int]:
    return {int(m.group(1)) for m in STEP_REF.finditer(_text(text))}


def parse_output(text: str | None) -> Any:
    """An agent's answer, as JSON when it is JSON (fenced or not), else the text."""
    if text is None:
        return None
    s = text.strip()
    for cand in (s, _fenced(s)):
        if cand and cand[:1] in "{[":
            try:
                return json.loads(cand)
            except ValueError:
                continue
    return s[:OUTPUT_TEXT_MAX]


def _fenced(s: str) -> str | None:
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", s, re.S)
    return m.group(1) if m else None


def run_message(act: dict[str, Any], ctx: dict[str, Any]) -> str:
    """What the agent is told when a rule runs it."""
    if (act.get("message") or "").strip():
        return render(act["message"], ctx)
    key = f"{ctx.get('group')}/{ctx.get('node')}/{ctx.get('device') or ''}"
    lines = [
        f"Signal rule {ctx.get('rule')} fired: {ctx.get('detail')}",
        f"Asset: {ctx.get('asset')} (key {key})",
    ]
    if ctx.get("signal"):
        lines.append(f"Signal: {ctx.get('signal')} = {_text(ctx.get('value'))}")
    hist = ctx.get("history") or {}
    summ = hist.get("summary") if isinstance(hist, dict) else None
    if summ:
        lines.append(
            f"Last {hist.get('minutes')} minutes: first {summ.get('first')}, last {summ.get('last')}, "
            f"min {summ.get('min')}, max {summ.get('max')}"
        )
    for i, st in enumerate(ctx.get("steps") or [], start=1):
        if st.get("output") is not None:
            lines.append(
                f"Step {i} ({st.get('kind')}) said: {_text(st.get('output'))[:2000]}"
            )
    lines.append("The full firing is in your context under telemetry.")
    return "\n".join(lines)


def context(doc: dict[str, Any], asset: dict[str, Any] | None) -> dict[str, Any]:
    """What an agent, a decision or a message template sees about the firing."""
    a = asset or {}
    return {
        "rule": doc.get("rule"),
        "rule_id": doc.get("rule_id"),
        "severity": doc.get("severity"),
        "detail": doc.get("detail"),
        "group": doc.get("group"),
        "node": doc.get("node"),
        "device": doc.get("device"),
        "asset": doc.get("asset"),
        "asset_type": a.get("type"),
        "tags": a.get("tags") or [],
        "fields": a.get("fields") or {},
        "location": a.get("location"),
        "signal": doc.get("signal"),
        "value": doc.get("value"),
        "at": datetime.fromtimestamp(
            (doc.get("ts") or doc.get("at") or 0) / 1000.0, tz=timezone.utc
        ).isoformat(),
        "firing_id": doc.get("id"),
        "window_s": doc.get("window_s"),
    }


def window_of(condition: dict[str, Any] | None) -> int | None:
    c = condition or {}
    for k in ("window_s", "for_s", "stale_s", "recent_s", "baseline_s"):
        v = c.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return None


async def add_history(ctx: dict[str, Any], tenant: Any) -> None:
    """A short look back at the signal, so an agent sees the trend without a tool call."""
    if not ctx.get("signal") or ctx.get("history"):
        return
    from app.routers.telemetry_loop import recent_history

    minutes = max(15, int((ctx.get("window_s") or 0) / 60) * 3)
    ctx["history"] = await recent_history(
        tenant,
        ctx["group"],
        ctx["node"],
        ctx.get("device") or "",
        ctx["signal"],
        min(minutes, 240),
    )


def _ok(kind: str, message: str, ref: Any = None) -> dict[str, Any]:
    return {"kind": kind, "status": "ok", "message": message, "ref": ref}


def _failed(kind: str, message: str, ref: Any = None) -> dict[str, Any]:
    return {"kind": kind, "status": "failed", "message": message, "ref": ref}


def _skipped(kind: str, message: str) -> dict[str, Any]:
    return {"kind": kind, "status": "skipped", "message": message, "ref": None}


async def _owner(db: AsyncSession, rule: Any) -> Any:
    from models.user import User

    if not rule.created_by:
        return None
    u = (
        await db.execute(select(User).where(User.id == rule.created_by))
    ).scalar_one_or_none()
    return u if u is not None and u.is_active else None


# alert


def alert_body(
    doc: dict[str, Any], rule: Any, severity: str, firing: bool
) -> dict[str, Any]:
    return {
        "labels": {
            "alertname": "TelemetryRule",
            "severity": severity,
            "tenant_id": str(doc["tenant"]),
            "rule": rule.name if rule is not None else doc.get("rule"),
            "rule_id": str(doc["rule_id"]),
            "group": doc["group"],
            "node": doc["node"],
            "device": doc.get("device") or "-",
            "source": "telemetry",
        },
        "annotations": {
            "summary": doc.get("detail") or doc.get("rule"),
            "description": (
                f"Signal rule {doc.get('rule')} fired on {doc.get('asset')}. "
                "It resolves when the condition clears."
            ),
        },
        "at": doc.get("ts") or int(time.time() * 1000),
        "firing": firing,
    }


async def post_alert(db: AsyncSession, a: dict[str, Any], firing: bool) -> str:
    import httpx

    starts = datetime.fromtimestamp(a["at"] / 1000.0, tz=timezone.utc).isoformat()
    base = (os.environ.get("ALERTMANAGER_URL") or "").strip().rstrip("/")
    if base:
        body = {
            "labels": a["labels"],
            "annotations": a["annotations"],
            "startsAt": starts,
            "generatorURL": f"/telemetry/rules?rule={a['labels']['rule_id']}",
        }
        if not firing:
            body["endsAt"] = datetime.now(timezone.utc).isoformat()
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post(f"{base}/api/v2/alerts", json=[body])
            r.raise_for_status()
        return "alertmanager"
    # no Alertmanager, so the workspace admins get it in Abenix
    from app.core import notifications as notif
    from models.notification import NotificationType
    from models.user import User, UserRole

    admins = (
        (
            await db.execute(
                select(User.id).where(
                    User.tenant_id == uuid.UUID(a["labels"]["tenant_id"]),
                    User.role == UserRole.ADMIN,
                    User.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    title = ("" if firing else "[RESOLVED] ") + f"{a['labels']['rule']}"
    for uid in admins:
        await notif.create_notification(
            db,
            tenant_id=uuid.UUID(a["labels"]["tenant_id"]),
            user_id=uid,
            type=NotificationType.SYSTEM_ALERT.value,
            title=title[:255],
            message=a["annotations"]["summary"],
            link=f"/telemetry/rules?rule={a['labels']['rule_id']}",
            metadata={
                "source": "telemetry_rule",
                "status": "firing" if firing else "resolved",
                "labels": a["labels"],
            },
        )
    return "notifications"


async def do_alert(
    db: AsyncSession, r: Any, rule: Any, doc: dict[str, Any], act: dict[str, Any]
) -> dict[str, Any]:
    sev = act.get("severity") or rule.severity or "warning"
    a = alert_body(doc, rule, sev, True)
    key = f"{doc['tenant']}|{doc['rule_id']}|{doc['group']}/{doc['node']}/{doc.get('device') or ''}"
    try:
        where = await post_alert(db, a, True)
    except Exception as exc:  # noqa: BLE001
        return _failed(
            "alert",
            f"The alert could not be raised: {exc}. It is retried on the next firing.",
        )
    try:
        await r.hset(ALERTS_KEY, key, json.dumps(a))
    except Exception:  # noqa: BLE001
        pass
    if where == "alertmanager":
        return _ok(
            "alert",
            f"Raised a {sev} alert on the Alerts page.",
            {"alertname": "TelemetryRule", "link": "/alerts"},
        )
    return _ok(
        "alert",
        f"Alertmanager is not set up, so the workspace admins were told in Abenix ({sev}).",
    )


async def resolve_alert(db: AsyncSession, r: Any, doc: dict[str, Any]) -> bool:
    key = f"{doc['tenant']}|{doc['rule_id']}|{doc['group']}/{doc['node']}/{doc.get('device') or ''}"
    raw = await r.hget(ALERTS_KEY, key)
    if not raw:
        return False
    await r.hdel(ALERTS_KEY, key)
    try:
        await post_alert(db, json.loads(raw), False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("alert resolve failed: %s", exc)
    return True


async def close_rule(db: AsyncSession, r: Any, tenant: Any, rule_id: Any) -> int:
    """A rule turned off, changed or deleted: its open firings clear and its alerts resolve."""
    from sqlalchemy import update

    from models.telemetry_rules import TelemetryRuleFiring

    await db.execute(
        update(TelemetryRuleFiring)
        .where(
            TelemetryRuleFiring.rule_id == uuid.UUID(str(rule_id)),
            TelemetryRuleFiring.status == "firing",
            TelemetryRuleFiring.cleared_at.is_(None),
        )
        .values(cleared_at=datetime.now(timezone.utc), status="cleared")
    )
    prefix = f"{tenant}|{rule_id}|"
    n = 0
    try:
        for key, raw in (await r.hgetall(ALERTS_KEY)).items():
            if not key.startswith(prefix):
                continue
            await r.hdel(ALERTS_KEY, key)
            n += 1
            try:
                await post_alert(db, json.loads(raw), False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("alert resolve failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("alert lookup failed: %s", exc)
    return n


async def refresh_alerts(db: AsyncSession, r: Any) -> int:
    """Alertmanager drops an alert nobody repeats, so firing ones are posted again."""
    n = 0
    for raw in (await r.hgetall(ALERTS_KEY)).values():
        try:
            await post_alert(db, json.loads(raw), True)
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("alert refresh failed: %s", exc)
    return n


# notify


async def do_notify(
    db: AsyncSession,
    r: Any,
    rule: Any,
    doc: dict[str, Any],
    act: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    from app.core import notifications as notif
    from models.notification import NotificationType
    from models.user import User, UserRole

    ch = act.get("channel") or "in_app"
    tenant = uuid.UUID(str(doc["tenant"]))
    title = f"Rule fired: {rule.name}"[:255]
    message = render(act.get("message") or "", ctx) or doc.get("detail") or rule.name
    link = f"/telemetry/rules?rule={rule.id}"
    if ch == "slack":
        ok = await notif.post_once_to_tenant_slack(
            db, tenant, title=title, message=message, link=link
        )
        if ok:
            return _ok("notify", "Posted to the workspace Slack channel.")
        return _failed(
            "notify",
            "The workspace has no working Slack webhook. An admin sets it under Settings, Notifications.",
        )
    to = []
    for u in act.get("to") or []:
        try:
            to.append(uuid.UUID(str(u)))
        except ValueError:
            continue
    q = select(User).where(User.tenant_id == tenant, User.is_active.is_(True))
    q = q.where(User.id.in_(to)) if to else q.where(User.role == UserRole.ADMIN)
    people = (await db.execute(q)).scalars().all()
    if not people:
        return _skipped(
            "notify",
            "Nobody to tell, the people picked are no longer in the workspace.",
        )
    sent = 0
    for u in people:
        if ch == "email":
            if await notif._send_email(
                to=u.email, subject=title, body=notif._email_body(title, message, link)
            ):
                sent += 1
        else:
            n = await notif.create_notification(
                db,
                tenant_id=tenant,
                user_id=u.id,
                type=NotificationType.SYSTEM_ALERT.value,
                title=title,
                message=message,
                link=link,
                metadata={
                    "source": "telemetry_rule",
                    "rule_id": str(rule.id),
                    "firing_id": doc.get("id"),
                },
                slack=False,
            )
            sent += 1 if n is not None else 0
    how = "by email" if ch == "email" else "in Abenix"
    if not sent:
        return _failed(
            "notify",
            f"Nothing could be sent {how}. Check the mail settings, or that these people have notifications on.",
        )
    return _ok("notify", f"Told {sent} {'person' if sent == 1 else 'people'} {how}.")


# run an agent or pipeline


async def do_run(
    db: AsyncSession,
    r: Any,
    rule: Any,
    doc: dict[str, Any],
    act: dict[str, Any],
    ctx: dict[str, Any],
    started: Any = None,
) -> dict[str, Any]:
    from app.routers.triggers import dispatch_execution
    from models.agent import Agent

    try:
        aid = uuid.UUID(str(act.get("agent_id")))
    except ValueError:
        return _failed("run", "The rule names no valid agent or pipeline.")
    agent = (
        await db.execute(select(Agent).where(Agent.id == aid))
    ).scalar_one_or_none()
    if agent is None or (
        agent.tenant_id
        and str(agent.tenant_id) != str(doc["tenant"])
        and getattr(agent.agent_type, "value", agent.agent_type) != "oob"
    ):
        return _failed(
            "run",
            "The agent or pipeline to run no longer exists. Edit the rule and pick another.",
        )
    owner = await _owner(db, rule)
    if owner is None:
        return _failed(
            "run",
            "The person who made this rule is no longer active, so nothing can run as them. Save the rule again as yourself.",
        )
    message = run_message(act, ctx)
    test = bool(doc.get("test"))
    steps = [
        {k: v for k, v in st.items() if k in ("kind", "status", "message", "output")}
        for st in ctx.get("steps") or []
    ]
    try:
        execution, dispatched = await dispatch_execution(
            db,
            agent=agent,
            user=owner,
            message=message,
            context={
                "telemetry": {k: v for k, v in ctx.items() if k != "steps"},
                "steps": steps,
                **({"test": True} if test else {}),
            },
            trigger_kind="telemetry_rule_test" if test else "telemetry_rule",
            trigger_name=rule.name,
        )
    except Exception as exc:  # noqa: BLE001
        return _failed("run", f"{agent.name} could not start: {exc}")
    kind = (
        "pipeline" if (agent.model_config_ or {}).get("mode") == "pipeline" else "agent"
    )
    ref = {
        "execution_id": str(execution.id),
        "agent_id": str(agent.id),
        "agent": agent.name,
        "link": f"/executions/{execution.id}",
    }
    if not dispatched:
        return _failed(
            "run",
            getattr(execution, "error_message", None) or f"{agent.name} did not start.",
            ref,
        )
    if started is not None:
        try:
            await started(ref)
        except Exception as exc:  # noqa: BLE001
            logger.debug("run start note skipped: %s", exc)
    if act.get("wait") is False:
        return _ok("run", f"Started the {kind} {agent.name}.", ref)
    try:
        wait_s = int(act.get("wait_s") or RUN_WAIT_S)
    except (TypeError, ValueError):
        wait_s = RUN_WAIT_S
    done = await wait_for_run(execution.id, max(5, min(wait_s, RUN_WAIT_MAX_S)))
    if done is None:
        out = _ok(
            "run",
            f"Started the {kind} {agent.name}. It was still running after {wait_s} seconds, "
            "so later steps that use its answer were skipped.",
            ref,
        )
        out["status"] = "running"
        return out
    status, text, err, ms = done
    ref["duration_ms"] = ms
    if status != "completed":
        return _failed(
            "run",
            f"The {kind} {agent.name} {status}: {(err or 'no reason given')[:300]}",
            ref,
        )
    out = _ok("run", f"The {kind} {agent.name} answered.", ref)
    out["output"] = parse_output(text)
    return out


async def wait_for_run(
    execution_id: Any, wait_s: int, every: float = 1.0
) -> tuple[str, str | None, str | None, int | None] | None:
    """Poll the run until it ends. None when it is still going at the deadline."""
    from app.core.deps import async_session
    from models.execution import Execution

    deadline = time.monotonic() + wait_s
    while True:
        async with async_session() as db:
            row = (
                await db.execute(
                    select(
                        Execution.status,
                        Execution.output_message,
                        Execution.error_message,
                        Execution.duration_ms,
                    ).where(Execution.id == execution_id)
                )
            ).first()
        if row is not None:
            st = getattr(row[0], "value", row[0])
            if str(st).lower() != "running":
                return str(st).lower(), row[1], row[2], row[3]
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(every)


# decision table


def _fact(v: str) -> Any:
    s = v.strip()
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    try:
        f = float(s)
        return int(f) if f.is_integer() and "." not in s else f
    except ValueError:
        return s


async def do_decision(
    db: AsyncSession,
    r: Any,
    rule: Any,
    doc: dict[str, Any],
    act: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    from engine.decisions import service as S

    facts: dict[str, Any] = {
        "signal": ctx["signal"],
        "value": ctx["value"],
        "group": ctx["group"],
        "node": ctx["node"],
        "device": ctx["device"],
        "asset": ctx["asset"],
        "asset_type": ctx["asset_type"],
        "tags": ctx["tags"],
        "rule": ctx["rule"],
        "severity": ctx["severity"],
        **(ctx.get("fields") or {}),
    }
    for k, tmpl in (act.get("facts") or {}).items():
        v = resolve_value(str(tmpl), ctx)
        facts[k] = _fact(v) if isinstance(v, str) else v
    key = act.get("key") or ""
    try:
        out = await S.evaluate(
            db,
            str(doc["tenant"]),
            key,
            facts,
            want_trace=False,
            persist=True,
            idempotency_key=f"telrule:{doc.get('id')}:{key}",
            caller={
                "kind": "telemetry_rule",
                "rule_id": str(rule.id),
                "firing_id": doc.get("id"),
            },
        )
    except S.DecisionError as e:
        return _failed("decision", str(getattr(e, "message", None) or e))
    except Exception as exc:  # noqa: BLE001
        return _failed("decision", f"The decision {key} could not be evaluated: {exc}")
    result = out.get("result")
    shown = json.dumps(result, default=str)
    if len(shown) > 300:
        shown = shown[:300] + "..."
    ref = {
        "key": key,
        "evaluation_id": out.get("evaluation_id"),
        "result": result,
        "outcome": out.get("outcome"),
        "link": f"/decisions/{key}",
    }
    if out.get("missing_facts"):
        return _failed(
            "decision",
            f"{key} needs facts the firing does not have: {', '.join(out['missing_facts'][:5])}. Map them in the rule's decision step.",
            ref,
        )
    done = _ok("decision", f"{key} returned {shown}.", ref)
    done["output"] = result
    return done


# governed write-back


async def do_command(
    db: AsyncSession,
    r: Any,
    rule: Any,
    doc: dict[str, Any],
    act: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    from app.core.audit import log_action
    from app.core.capabilities import capabilities_for, holds
    from app.telemetry import access, pipeline, registry
    from app.telemetry import keys as K
    from app.telemetry import sparkplug as sp
    from models.telemetry import TelemetryConnection

    owner = await _owner(db, rule)
    if owner is None:
        return _failed(
            "command",
            "The person who made this rule is no longer active, so no command was sent.",
        )
    if not holds(await capabilities_for(db, owner), "telemetry.command"):
        return _failed(
            "command",
            f"{owner.email} no longer has Send machine commands, so no command was sent.",
        )
    t = str(doc["tenant"])
    g = act.get("group") or doc["group"]
    n = act.get("node") or doc["node"]
    d = act.get("device") if act.get("device") is not None else doc.get("device") or ""
    if act.get("node") and act.get("device") is None:
        d = ""
    name = act.get("signal") or ""
    reason = f"Rule {rule.name}: {doc.get('detail')}"[:500]
    if step_refs(act.get("value")):
        found = [step_value(ctx, n, "output") for n in step_refs(act.get("value"))]
        if not all(ok for ok, _ in found):
            return _skipped(
                "command",
                "The step this value comes from gave no answer, so nothing was sent.",
            )
    pipe = r.pipeline(transaction=False)
    pipe.hmget(K.device(t, g, n, ""), "_online", "_conn")
    pipe.hmget(K.device(t, g, n, d), "_online", K.metric_field(name))
    (online, conn_id), (d_online, hint_raw) = await pipe.execute()
    if not conn_id:
        return _failed(
            "command",
            f"No asset called {n} in group {g} is streaming, so nothing was sent.",
        )
    if online != "1" or (d and d_online != "1"):
        return _failed(
            "command",
            f"{n}{' part ' + d if d else ''} is offline, so the command was not sent.",
        )
    conn = (
        await db.execute(
            select(TelemetryConnection).where(
                TelemetryConnection.id == uuid.UUID(conn_id),
                TelemetryConnection.tenant_id == uuid.UUID(t),
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        return _failed(
            "command", "The source for this asset was removed, so nothing was sent."
        )
    scope = await access.scope_for(db, owner, fresh=True)
    if not scope.may_command(conn_id):
        return _failed(
            "command",
            f"{owner.email} cannot command assets on {conn.name}, so nothing was sent.",
        )
    sec = int(time.time())
    rk = K.command_rate(t, g, n, sec)
    p2 = r.pipeline(transaction=False)
    p2.incr(rk)
    p2.expire(rk, 3)
    used, _ = await p2.execute()
    if int(used) > COMMAND_LIMIT_PER_SEC:
        return _failed(
            "command",
            f"More than {COMMAND_LIMIT_PER_SEC} commands a second to {n}, this one was not sent.",
        )
    row = pipeline.connection_row(conn)
    value = resolve_value(act.get("value"), ctx)
    now_ms = int(time.time() * 1000)
    if row["decoder"] == "sparkplug_b":
        hint = None
        if hint_raw:
            try:
                hint = json.loads(hint_raw).get("t")
            except (TypeError, ValueError):
                hint = None
        dtype = sp.datatype_for(
            value, hint if hint and hint in sp.TYPE_IDS and hint != "Unknown" else None
        )
        try:
            value = sp.coerce(value, dtype)
        except (TypeError, ValueError):
            return _failed(
                "command",
                f"{name} takes a {sp.TYPE_NAMES.get(dtype, 'value')}, {value!r} does not fit.",
            )
        topic = sp.command_topic(g, n, d)
        payload = sp.encode(
            [{"name": name, "value": value, "datatype": dtype, "timestamp": now_ms}],
            timestamp=now_ms,
        )
        target: dict[str, Any] = {"topic": topic, "payload": payload}
    else:
        from app.routers.telemetry import _render_target, _writable

        spec = _writable(row["mapping"], name, g, n, d)
        if spec is None:
            return _failed(
                "command",
                f"{name} is not a writable signal of {conn.name}. Declare it in the source's mapping.",
            )
        target = _render_target(spec.get("target") or {}, value, name, g, n, d)
        topic = target.get("topic")
    try:
        connector = registry.connector(row["transport"])
        if not connector.capabilities.get("write"):
            return _failed(
                "command", f"{connector.label} sources cannot take commands."
            )
        target["connection_id"] = row["id"]
        await connector.write(
            {**row["config"], "_connection_id": row["id"]},
            row["secrets"],
            target,
            value,
        )
    except Exception as exc:  # noqa: BLE001
        return _failed("command", f"The command could not be sent: {exc}")
    await log_action(
        db,
        owner.tenant_id,
        owner.id,
        "telemetry.command",
        {
            "group": g,
            "node": n,
            "device": d,
            "signal": name,
            "metric": name,
            "value": value if not isinstance(value, bytes) else value.hex(),
            "reason": reason,
            "topic": topic,
            "transport": row["transport"],
            "connection_id": conn_id,
            "rule_id": str(rule.id),
            "firing_id": doc.get("id"),
        },
        None,
        resource_type=access.KIND,
        resource_id=conn_id,
    )
    where = f"{n}/{d}" if d else n
    done = _ok(
        "command",
        f"Set {name} to {value} on {where}, with the rule as the reason.",
        {"topic": topic, "at": now_ms},
    )
    done["output"] = {
        "published": True,
        "group": g,
        "node": n,
        "device": d,
        "signal": name,
        "value": value if not isinstance(value, bytes) else value.hex(),
        "at": now_ms,
    }
    return done


def step_input(act: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """What a step was given, shown on the firing next to what it gave back."""
    kind = act.get("kind")
    if kind == "run":
        return {"agent_id": act.get("agent_id"), "message": run_message(act, ctx)}
    if kind == "notify":
        return {
            "channel": act.get("channel") or "in_app",
            "message": render(act.get("message") or "", ctx) or ctx.get("detail"),
        }
    if kind == "decision":
        return {
            "key": act.get("key"),
            "facts": {
                k: resolve_value(str(v), ctx)
                for k, v in (act.get("facts") or {}).items()
            },
        }
    if kind == "command":
        return {
            "group": act.get("group") or ctx.get("group"),
            "node": act.get("node") or ctx.get("node"),
            "device": act.get("device") if act.get("node") else ctx.get("device"),
            "signal": act.get("signal"),
            "value": resolve_value(act.get("value"), ctx),
        }
    return {"severity": act.get("severity")}


async def run_action(
    db: AsyncSession,
    r: Any,
    rule: Any,
    doc: dict[str, Any],
    act: dict[str, Any],
    ctx: dict[str, Any],
    on_started: Any = None,
) -> dict[str, Any]:
    started = time.time()
    try:
        given = step_input(act, ctx)
    except Exception:  # noqa: BLE001
        given = {}
    out = await _dispatch(db, r, rule, doc, act, ctx, on_started)
    out.setdefault("output", None)
    out["input"] = given
    out["started_at"] = int(started * 1000)
    out["duration_ms"] = int((time.time() - started) * 1000)
    return out


async def _dispatch(
    db: AsyncSession,
    r: Any,
    rule: Any,
    doc: dict[str, Any],
    act: dict[str, Any],
    ctx: dict[str, Any],
    on_started: Any = None,
) -> dict[str, Any]:
    kind = act.get("kind")
    try:
        if kind == "alert":
            return await do_alert(db, r, rule, doc, act)
        if kind == "notify":
            return await do_notify(db, r, rule, doc, act, ctx)
        if kind == "run":
            return await do_run(db, r, rule, doc, act, ctx, on_started)
        if kind == "decision":
            return await do_decision(db, r, rule, doc, act, ctx)
        if kind == "command":
            return await do_command(db, r, rule, doc, act, ctx)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rule action %s failed: %s", kind, exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return _failed(str(kind), f"This step failed: {exc}")
    return _skipped(str(kind), "Unknown step, it was skipped.")
