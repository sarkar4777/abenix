"""Earned autonomy: action types, grants and the action ledger, applied on every effect tool call.

Like engine.governance the gate reads an in-memory snapshot refreshed every few
seconds, so a call never waits on the database to learn its level. Ledger
writes are fire and forget, a ledger that is down never breaks a tool call.
"""

from __future__ import annotations

import asyncio
import contextvars
import fnmatch
import json
import logging
import time
import uuid
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

from engine import governance, risk
from engine.tools.base import READ_ONLY, BaseTool, Effect, ToolResult

logger = logging.getLogger(__name__)

LEVELS: dict[int, tuple[str, str, str]] = {
    0: ("off", "Off", "The agent cannot take this action"),
    1: ("watching", "Watching", "The agent says what it would do. Nothing runs"),
    2: (
        "asks_first",
        "Asks first",
        "A person approves, edits or rejects, then it runs",
    ),
    3: (
        "within_limits",
        "Acts within limits",
        "Runs alone inside the limits with a confident prediction, otherwise asks first",
    ),
    4: (
        "acts_reports",
        "Acts and reports",
        "Runs and reports after. Limits and kill switches still apply",
    ),
}

WATCHING_TEXT = (
    "Recorded in watching mode, not executed. A person will compare it with what "
    "they would do. Do not tell the user it was done."
)
LIMITS_TEXT = "An owner can review the limits on the Autonomy page"
DEFAULT_APPROVAL_EXPIRES = 1800
DEFAULT_WORLD_MODEL_TIMEOUT = 10.0
LIMITS_TIMEOUT = 5.0
PREVIEW_CHARS = 500

_ttl = 5.0
# tenant -> action types, most specific match first
_types: dict[str, list[dict[str, Any]]] = {}
# (tenant, agent, action type id) -> grants, scoped first
_grants: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
# (tenant, agent, tool name) -> grants, for the tool description
_by_tool: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
_hashes: dict[str, str] = {}
_loaded_at = 0.0
_lock: asyncio.Lock | None = None
_bg: asyncio.Task | None = None
_loader: Callable[[], Awaitable[tuple | None]] | None = None
_writer: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None
_approver: Any = None
_decider: Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None
_stats: Callable[[str, str], Awaitable[dict[str, Any] | None]] | None = None
_warned: set[str] = set()
_ledger_off_until = 0.0
_tasks: set[asyncio.Task] = set()
_chains: dict[str, asyncio.Task] = {}
_pools: dict[int, Any] = {}

# (the run that set it, tool call id), so a nested run never borrows it
_tool_call: contextvars.ContextVar[tuple[Any, str]] = contextvars.ContextVar(
    "abenix_autonomy_tool_call", default=(None, "")
)


# where a streaming run collects events raised from inside a tool call
_sink: contextvars.ContextVar[asyncio.Queue | None] = contextvars.ContextVar(
    "abenix_autonomy_sink", default=None
)


def emit(event: str, data: dict[str, Any]) -> None:
    sink = _sink.get()
    if sink is not None:
        sink.put_nowait((event, data))


async def stream_call(coro: Any) -> AsyncIterator[tuple[str, Any]]:
    """Run a tool call in its own task, yielding the events it raises and then ("result", result)."""
    sink: asyncio.Queue = asyncio.Queue()
    ctx = contextvars.copy_context()
    ctx.run(_sink.set, sink)
    task = asyncio.get_running_loop().create_task(coro, context=ctx)
    try:
        while not task.done():
            getter = asyncio.ensure_future(sink.get())
            await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
            if getter.done():
                yield getter.result()
            else:
                getter.cancel()
        while not sink.empty():
            yield sink.get_nowait()
        yield "result", task.result()
    finally:
        if not task.done():
            task.cancel()


def managed(tenant: str, run: Any, tool_name: str) -> bool:
    """Whether the run's agent holds a grant on this tool."""
    return _managed(tenant, run, tool_name)


def level_label(level: int | None) -> str:
    return LEVELS.get(int(level), LEVELS[0])[1] if level is not None else ""


def set_tool_call(tool_call_id: Any) -> None:
    """The id of the model's tool call about to run, so the ledger row can be tied to it."""
    run = governance.current()
    _tool_call.set((weakref.ref(run) if run else None, str(tool_call_id or "")))


def _tool_call_for(run: Any) -> str | None:
    owner, call_id = _tool_call.get()
    return call_id if call_id and owner is not None and owner() is run else None


def configure(
    *,
    loader: Callable[[], Awaitable[tuple | None]] | None = None,
    writer: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    approver: Any = None,
    decider: (
        Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]] | None
    ) = None,
    stats: Callable[[str, str], Awaitable[dict[str, Any] | None]] | None = None,
    ttl: float | None = None,
) -> None:
    global _loader, _writer, _approver, _decider, _stats, _ttl, _lock
    global _ledger_off_until
    _loader, _writer, _approver, _decider, _stats = (
        loader,
        writer,
        approver,
        decider,
        stats,
    )
    if ttl is not None:
        _ttl = float(ttl)
    _lock = None
    _ledger_off_until = 0.0
    _warned.clear()
    invalidate()


def invalidate() -> None:
    global _loaded_at
    _loaded_at = 0.0


def _json(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return v


def _warn_once(key: str, msg: str, *args: Any) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(msg, *args)


def _connect_kwargs() -> tuple[str, dict[str, Any]]:
    from engine.credentials import _db_url

    url, ssl = _db_url()
    kwargs: dict[str, Any] = {}
    if ssl:
        kwargs["ssl"] = "require" if ssl in ("true", "1", "require") else ssl
    return url, kwargs


async def _read_db() -> tuple | None:
    if _loader is not None:
        return await _loader()
    url, kwargs = _connect_kwargs()
    if not url:
        return None
    import asyncpg

    conn = await asyncpg.connect(url, timeout=2, **kwargs)
    try:
        try:
            types = await conn.fetch(
                "SELECT id, tenant_id, key, label, description, tool_name, match, effect, "
                "world_model, outcome_probe, limits_decision_key, max_band_width, reversible, "
                "ceiling, policy, is_sample FROM action_types"
            )
            grants = await conn.fetch(
                "SELECT g.id, g.tenant_id, g.agent_id, g.action_type_id, g.scope, g.level, "
                "g.ceiling, g.state, g.agent_config_hash, g.granted_by, a.creator_id, "
                "a.name AS agent_name FROM autonomy_grants g "
                "LEFT JOIN agents a ON a.id = g.agent_id WHERE g.state <> 'removed'"
            )
            hashes = await conn.fetch(
                "SELECT id, encode(sha256(convert_to(coalesce(system_prompt, '') || '|' || "
                "coalesce(model_config::text, ''), 'UTF8')), 'hex') AS h FROM agents "
                "WHERE id IN (SELECT agent_id FROM autonomy_grants)"
            )
        except Exception as exc:  # noqa: BLE001
            if "does not exist" in str(exc):
                _warn_once(
                    "no_tables",
                    "autonomy tables are missing, effect tools run unmanaged until the migration lands",
                )
                return [], [], {}
            raise
    finally:
        await conn.close()
    return (
        [dict(r) for r in types],
        [dict(r) for r in grants],
        {str(r["id"]): r["h"] for r in hashes},
    )


def _norm_type(r: dict[str, Any]) -> dict[str, Any]:
    t = dict(r)
    t["id"] = str(t.get("id") or "")
    t["tenant_id"] = str(t.get("tenant_id") or "")
    for k in ("match", "effect", "world_model", "outcome_probe", "policy"):
        t[k] = _json(t.get(k))
    return t


def _norm_grant(r: dict[str, Any]) -> dict[str, Any]:
    g = dict(r)
    for k in ("id", "tenant_id", "agent_id", "action_type_id"):
        g[k] = str(g.get(k) or "")
    for k in ("granted_by", "creator_id"):
        g[k] = str(g[k]) if g.get(k) else ""
    g["scope"] = _json(g.get("scope")) or None
    g["level"] = int(g.get("level") or 0)
    g["state"] = g.get("state") or "active"
    return g


def _load(types: list, grants: list, hashes: dict | None = None) -> None:
    global _types, _grants, _by_tool, _hashes
    by_tenant: dict[str, list[dict[str, Any]]] = {}
    ids: dict[str, dict[str, Any]] = {}
    for r in types:
        t = _norm_type(r)
        ids[t["id"]] = t
        by_tenant.setdefault(t["tenant_id"], []).append(t)
    for lst in by_tenant.values():
        lst.sort(
            key=lambda t: -len(((t.get("match") or {}).get("glob")) or "")
            - 1000 * bool(t.get("match"))
        )
    g_idx: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    t_idx: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in grants:
        g = _norm_grant(r)
        at = ids.get(g["action_type_id"])
        if at is None or g["state"] == "removed":
            continue
        g_idx.setdefault(
            (g["tenant_id"], g["agent_id"], g["action_type_id"]), []
        ).append(g)
        t_idx.setdefault(
            (g["tenant_id"], g["agent_id"], at.get("tool_name") or ""), []
        ).append(g)
    for idx in (g_idx, t_idx):
        for lst in idx.values():
            lst.sort(key=lambda g: g.get("scope") is None)
    _types, _grants, _by_tool = by_tenant, g_idx, t_idx
    _hashes = {str(k): str(v) for k, v in (hashes or {}).items() if v}


async def _refresh(force: bool) -> None:
    global _loaded_at
    async with _lock:  # type: ignore[union-attr]
        if not force and time.monotonic() - _loaded_at < _ttl:
            return
        try:
            data = await _read_db()
        except Exception as exc:  # noqa: BLE001
            logger.debug("autonomy refresh failed: %s", exc)
            data = None
        if data is not None:
            _load(*data)
        _loaded_at = time.monotonic()


async def ensure_fresh(force: bool = False) -> None:
    """Serve the snapshot and refresh it behind the caller. Only a first load waits."""
    global _lock, _bg
    if not force and time.monotonic() - _loaded_at < _ttl:
        return
    if _lock is None:
        _lock = asyncio.Lock()
    if not force and _loaded_at:
        if not _lock.locked() and (_bg is None or _bg.done()):
            _bg = asyncio.create_task(_refresh(False))
        return
    await _refresh(force)


def load_for_test(
    action_types: list | None = None,
    grants: list | None = None,
    hashes: dict | None = None,
) -> None:
    global _loaded_at
    _load(action_types or [], grants or [], hashes or {})
    _loaded_at = time.monotonic() + 3600


def config_hash(agent_id: Any) -> str:
    return _hashes.get(str(agent_id or ""), "")


# effect resolution and matching


def resolve_effect(tool: Any, arguments: dict[str, Any] | None) -> Effect | None:
    """The effect of this call: the tool's per-call answer, or what an instance declared."""
    args = arguments if isinstance(arguments, dict) else {}
    try:
        own = getattr(tool, "__dict__", {}).get("effect")
        cls_fn = getattr(type(tool), "effect_for", None)
        if own is not None and getattr(cls_fn, "__func__", None) is getattr(
            BaseTool.effect_for, "__func__", None
        ):
            return own
        fn = getattr(tool, "effect_for", None)
        if fn is None:
            return getattr(tool, "effect", None)
        return fn(args)
    except Exception:  # noqa: BLE001
        return getattr(tool, "effect", None)


def _arg(args: dict[str, Any], path: str | None) -> Any:
    if not path:
        return None
    cur: Any = args
    for part in str(path).split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _matches(rule: dict[str, Any] | None, args: dict[str, Any]) -> bool:
    if not rule:
        return True
    val = _arg(args, rule.get("param"))
    if "equals" in rule:
        return val is not None and str(val) == str(rule["equals"])
    if "in" in rule:
        return val is not None and str(val) in {str(x) for x in rule.get("in") or []}
    if "glob" in rule:
        return val is not None and fnmatch.fnmatchcase(str(val), str(rule["glob"]))
    return True


def match_action_type(
    tenant: str, tool_name: str, args: dict[str, Any]
) -> dict[str, Any] | None:
    for t in _types.get(str(tenant), ()):
        if t.get("tool_name") == tool_name and _matches(t.get("match"), args):
            return t
    return None


def match_grant(
    tenant: str, agent_id: str, action_type: dict[str, Any], args: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The grant whose scope covers these arguments, plus every grant the agent has here."""
    grants = _grants.get((str(tenant), str(agent_id), action_type["id"]), [])
    for g in grants:
        if _matches(g.get("scope"), args):
            return g, grants
    return None, grants


def effective_level(
    grant: dict[str, Any], action_type: dict[str, Any], run: Any
) -> tuple[int, str | None]:
    """The level that applies now, and why it is lower than granted, if it is."""
    level = int(grant.get("level") or 0)
    for cap in (grant.get("ceiling"), action_type.get("ceiling")):
        if cap is not None:
            level = min(level, int(cap))
    reason = None
    if grant.get("state") == "paused" and level > 2:
        level, reason = 2, "Autonomy for this action is paused, so it asks first."
    granted_hash = grant.get("agent_config_hash") or ""
    now_hash = (getattr(run, "agent_config_hash", "") or "") or config_hash(
        grant.get("agent_id")
    )
    if granted_hash and now_hash and granted_hash != now_hash and level > 2:
        level, reason = (
            2,
            "The agent changed since this level was granted, so it asks first until it proves itself again.",
        )
    return max(0, min(level, 4)), reason


# limits and predictions


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


async def _evaluate_decision(
    tenant: str, key: str, facts: dict[str, Any]
) -> dict[str, Any]:
    if _decider is not None:
        return await _decider(tenant, key, facts)
    from engine.decisions import db as ddb
    from engine.decisions import service

    async with ddb.session() as s:
        return await service.evaluate(s, tenant, key, facts, want_trace=False)


def _limits_from(out: dict[str, Any], key: str) -> dict[str, Any]:
    outcome = out.get("outcome")
    if outcome == "missing_facts":
        need = ", ".join(str(x) for x in out.get("missing_facts") or [])
        return {
            "ok": False,
            "decision_key": key,
            "reasons": [f"The limits need {need}, which the call did not give"],
        }
    if outcome == "invalid_facts":
        bad = "; ".join(
            f"{x.get('fact', '')} {x.get('reason', '') or x.get('message', '')}".strip()
            for x in out.get("invalid_facts") or []
            if isinstance(x, dict)
        )
        return {
            "ok": False,
            "decision_key": key,
            "reasons": [f"The limits could not read the call: {bad}"],
        }
    res = out.get("result")
    items = res if isinstance(res, list) else [res]
    ok = True
    reasons: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        flag: Any = None
        for k in ("ok", "allowed", "within_limits", "pass", "passed"):
            if k in item:
                flag = bool(item[k])
                break
        for k in ("breach", "blocked", "violation"):
            if k in item and item[k]:
                flag = False
        said = item.get("reasons")
        if isinstance(said, str):
            said = [said]
        said = [str(x) for x in (said or []) if x]
        for k in ("reason", "message"):
            if not said and item.get(k):
                said = [str(item[k])]
        if flag is None and said:
            flag = False
        if flag is False:
            ok = False
            reasons.extend(said or ["The call is outside the limits"])
    return {"ok": ok, "decision_key": key, "reasons": reasons}


def limit_facts(args: dict[str, Any], target: str | None) -> dict[str, Any]:
    """The call's arguments as facts, with JSON text such as an MQTT payload read as an object."""
    facts: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and v.lstrip().startswith("{"):
            parsed = _json(v)
            facts[k] = parsed if isinstance(parsed, dict) else v
        else:
            facts[k] = v
    if target is not None:
        facts.setdefault("target", target)
    return facts


async def check_limits(
    action_type: dict[str, Any], tenant: str, args: dict[str, Any], target: str | None
) -> dict[str, Any] | None:
    key = action_type.get("limits_decision_key")
    if not key:
        return None
    facts = limit_facts(args, target)
    try:
        out = await asyncio.wait_for(
            _evaluate_decision(tenant, key, facts), LIMITS_TIMEOUT
        )
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "decision_key": key,
            "reasons": [f"The limits model {key} did not answer in time"],
        }
    except Exception as exc:  # noqa: BLE001
        msg = getattr(exc, "message", "") or str(exc)
        return {
            "ok": False,
            "decision_key": key,
            "reasons": [f"The limits model {key} could not be checked: {msg}"[:400]],
        }
    return _limits_from(out or {}, key)


def _render(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: _render(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, ctx) for v in value]
    if not isinstance(value, str) or "{{" not in value:
        return value
    s = value.strip()
    if s.startswith("{{") and s.endswith("}}") and s.count("{{") == 1:
        return _arg(ctx, s[2:-2].strip())
    out = value
    while "{{" in out and "}}" in out:
        a = out.index("{{")
        b = out.index("}}", a)
        got = _arg(ctx, out[a + 2 : b].strip())
        out = out[:a] + ("" if got is None else str(got)) + out[b + 2 :]
    return out


def _prediction_from(
    raw: Any, wm: dict[str, Any], source: str
) -> dict[str, Any] | None:
    raw = _json(raw) if isinstance(raw, str) else raw
    if isinstance(raw, list) and raw:
        raw = raw[0]
    metric = wm.get("metric") or ""
    if not isinstance(raw, dict):
        val = _num(raw)
        raw = {"value": val} if val is not None else None
    if not isinstance(raw, dict):
        return None
    value = _num(raw.get("value"))
    if value is None:
        for k in (raw.get("metric"), metric, "prediction", "predicted"):
            if k and _num(raw.get(k)) is not None:
                value = _num(raw.get(k))
                break
    if value is None:
        p = raw.get("prediction")
        if isinstance(p, list) and p:
            value = _num(p[0])
    if value is None:
        return None
    low, high = _num(raw.get("low")), _num(raw.get("high"))
    band = _num(wm.get("band"))
    if (low is None or high is None) and band is not None:
        low, high = value - band, value + band
    if low is None or high is None:
        low = high = value
    return {
        "metric": str(raw.get("metric") or metric or ""),
        "value": value,
        "low": min(low, high),
        "high": max(low, high),
        "horizon_s": _num(raw.get("horizon_s")) or _num(wm.get("horizon_s")),
        "source": source,
        "source_ref": str(wm.get("ref") or ""),
        "note": str(raw.get("note") or ""),
    }


async def _run_world_model(
    wm: dict[str, Any],
    tenant: str,
    args: dict[str, Any],
    stated: Any,
    ctx: dict[str, Any],
) -> dict[str, Any] | None:
    kind = wm.get("kind")
    if kind == "agent_stated":
        return _prediction_from(stated, wm, "agent_stated")
    inputs = _render(wm.get("inputs") or {}, ctx) or {}
    if kind == "decision":
        out = await _evaluate_decision(tenant, str(wm.get("ref") or ""), inputs)
        return _prediction_from(out.get("result"), wm, "decision")
    if kind == "ml_model":
        from engine.tools.ml_model_tool import MLModelTool

        token = governance.enter_tool()
        try:
            res = await MLModelTool(tenant_id=tenant).execute(
                {
                    "operation": "predict",
                    "model_name": str(wm.get("ref") or ""),
                    "input_data": inputs,
                }
            )
        finally:
            governance.exit_tool(token)
        if res.is_error:
            raise RuntimeError(res.content[:300])
        return _prediction_from(res.content, wm, "ml_model")
    return None


async def predict(
    action_type: dict[str, Any],
    tenant: str,
    args: dict[str, Any],
    stated: Any,
    target: str | None,
    intent: str | None,
) -> tuple[dict[str, Any] | None, str]:
    """The prediction for this call and a note when there is none."""
    wm = action_type.get("world_model") or {"kind": "agent_stated"}
    kind = wm.get("kind") or "none"
    if kind == "none":
        return None, "No world model is set for this action"
    timeout = _num(wm.get("timeout_s")) or DEFAULT_WORLD_MODEL_TIMEOUT
    ctx = {"args": args, "target": target, "intent": intent}
    try:
        pred = await asyncio.wait_for(
            _run_world_model(wm, tenant, args, stated, ctx), timeout
        )
    except asyncio.TimeoutError:
        return None, f"The world model did not answer within {timeout:g} s"
    except Exception as exc:  # noqa: BLE001
        return None, f"The world model failed: {exc}"[:300]
    if pred is None:
        if kind == "agent_stated":
            return None, "The agent did not state a prediction"
        return None, "The world model gave no usable prediction"
    return pred, ""


def band_ok(pred: dict[str, Any] | None, max_band_width: Any) -> bool:
    if not pred:
        return False
    value, low, high = pred.get("value"), pred.get("low"), pred.get("high")
    if value is None or low is None or high is None or not (low <= value <= high):
        return False
    limit = _num(max_band_width)
    if limit is None:
        return True
    width = high - low
    return (width / abs(value) if value else width) <= limit


# the ledger


def _uuid(v: Any) -> uuid.UUID | None:
    if not v:
        return None
    try:
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    except (ValueError, AttributeError, TypeError):
        return None


_UUID_COLS = {
    "id",
    "tenant_id",
    "execution_id",
    "agent_id",
    "user_id",
    "action_type_id",
    "grant_id",
    "approval_id",
    "decided_by",
}
_JSON_COLS = {"arguments", "prediction", "limits_result"}
_UPDATABLE = {
    "status",
    "mode",
    "arguments",
    "approval_id",
    "decided_by",
    "decided_at",
    "decision_note",
    "executed_at",
    "result_preview",
    "outcome_due_at",
    "outcome_status",
}


def _param(col: str, v: Any) -> Any:
    if col in _UUID_COLS:
        return _uuid(v)
    if col in _JSON_COLS:
        return None if v is None else json.dumps(v, default=str)
    return v


def _cast(col: str, n: int) -> str:
    if col in _JSON_COLS:
        return f"${n}::jsonb"
    return f"${n}"


async def _pool() -> Any:
    loop_id = id(asyncio.get_running_loop())
    pool = _pools.get(loop_id)
    if pool is None:
        url, kwargs = _connect_kwargs()
        if not url:
            return None
        import asyncpg

        pool = await asyncpg.create_pool(
            url, min_size=0, max_size=4, timeout=3, **kwargs
        )
        _pools[loop_id] = pool
    return pool


async def _db_write(op: str, data: dict[str, Any]) -> None:
    pool = await _pool()
    if pool is None:
        _warn_once("no_db", "DATABASE_URL is not set, the action ledger is not written")
        return
    async with pool.acquire() as conn:
        if op == "insert":
            cols = [c for c in data if c != "created_at"]
            vals = [_param(c, data[c]) for c in cols]
            placeholders = ", ".join(_cast(c, i + 1) for i, c in enumerate(cols))
            await conn.execute(
                f"INSERT INTO agent_actions ({', '.join(cols)}, created_at) "
                f"VALUES ({placeholders}, now()) ON CONFLICT (execution_id, tool_call_id) "
                "WHERE execution_id IS NOT NULL AND tool_call_id IS NOT NULL DO NOTHING",
                *vals,
            )
        elif op == "update":
            cols = [c for c in data if c in _UPDATABLE]
            if not cols:
                return
            sets = ", ".join(f"{c} = {_cast(c, i + 2)}" for i, c in enumerate(cols))
            await conn.execute(
                f"UPDATE agent_actions SET {sets} WHERE id = $1",
                _uuid(data["id"]),
                *[_param(c, data[c]) for c in cols],
            )
        elif op == "notify":
            await conn.execute(
                "INSERT INTO notifications (id, tenant_id, user_id, type, title, message, "
                "is_read, link, metadata, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, false, $7, $8::jsonb, now(), now())",
                uuid.uuid4(),
                _uuid(data["tenant_id"]),
                _uuid(data["user_id"]),
                data["type"],
                data["title"][:255],
                data["message"],
                data.get("link"),
                json.dumps(data.get("metadata") or {}, default=str),
            )


async def _write(op: str, data: dict[str, Any]) -> None:
    global _ledger_off_until
    if time.monotonic() < _ledger_off_until:
        return
    try:
        if _writer is not None:
            await _writer(op, data)
        else:
            await _db_write(op, data)
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if "does not exist" in text:
            _warn_once(
                "ledger_missing",
                "action ledger is not ready (%s), recording is skipped for now",
                text[:200],
            )
            _ledger_off_until = time.monotonic() + 60
        else:
            _warn_once(
                f"ledger:{type(exc).__name__}",
                "action ledger write failed: %s",
                text[:300],
            )


def _queue(action_id: str, op: str, data: dict[str, Any]) -> asyncio.Task | None:
    """Write behind the call, in order per action."""
    prev = _chains.get(action_id)

    async def run() -> None:
        if prev is not None and not prev.done():
            try:
                await prev
            except BaseException:  # noqa: BLE001
                pass
        await _write(op, data)

    try:
        task = asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        return None
    _tasks.add(task)
    _chains[action_id] = task

    def done(t: asyncio.Task) -> None:
        _tasks.discard(t)
        if _chains.get(action_id) is t:
            _chains.pop(action_id, None)

    task.add_done_callback(done)
    return task


async def _write_now(
    action_id: str, op: str, data: dict[str, Any], timeout: float = 3.0
) -> None:
    task = _queue(action_id, op, data)
    if task is None:
        return
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout)
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
        pass


async def flush() -> None:
    """Wait for pending ledger writes. For tests and shutdown."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def _record_stats(tenant: str, grant_id: str) -> dict[str, Any]:
    empty = {
        "held": 0,
        "scored": 0,
        "agreement_pct": None,
        "text": "No track record yet",
    }
    if not grant_id:
        return empty
    try:
        if _stats is not None:
            got = await _stats(tenant, grant_id)
        else:
            got = await asyncio.wait_for(_db_stats(grant_id), 2.0)
    except Exception:  # noqa: BLE001
        return empty
    if not got:
        return empty
    held, scored = int(got.get("held") or 0), int(got.get("scored") or 0)
    agree = got.get("agreement_pct")
    text = f"Held {held} of {scored} times" if scored else "No scored actions yet"
    return {"held": held, "scored": scored, "agreement_pct": agree, "text": text}


async def _db_stats(grant_id: str) -> dict[str, Any] | None:
    pool = await _pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "WITH recent AS (SELECT score, status, reviewer_answer FROM agent_actions "
            "WHERE grant_id = $1 ORDER BY created_at DESC LIMIT 50) "
            "SELECT count(*) FILTER (WHERE score->>'within_band' = 'true') AS held, "
            "count(*) FILTER (WHERE score->>'within_band' IN ('true', 'false')) AS scored, "
            "count(*) FILTER (WHERE reviewer_answer = 'agree' OR status IN ('approved', 'executed')) AS agreed, "
            "count(*) FILTER (WHERE reviewer_answer IN ('agree', 'different') "
            "OR status IN ('approved', 'edited', 'rejected', 'executed')) AS judged FROM recent",
            _uuid(grant_id),
        )
    if row is None:
        return None
    judged = int(row["judged"] or 0)
    return {
        "held": int(row["held"] or 0),
        "scored": int(row["scored"] or 0),
        "agreement_pct": (
            round(100 * int(row["agreed"] or 0) / judged) if judged else None
        ),
    }


# the gate


def _lower_first(label: str) -> str:
    if len(label) > 1 and label[0].isupper() and not label[1].isupper():
        return label[0].lower() + label[1:]
    return label


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Action:
    """One effect call the gate let through, closed after the tool runs."""

    id: str
    tenant_id: str
    tool_name: str
    arguments: dict[str, Any]
    mode: str = "unmanaged"
    level: int | None = None
    grant: dict[str, Any] | None = None
    action_type: dict[str, Any] | None = None
    approved_by: str = ""
    result: ToolResult | None = None
    meta: dict[str, Any] | None = None
    notify: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def _probe(self) -> dict[str, Any] | None:
        return (self.action_type or {}).get("outcome_probe") or None

    def finished(self, result: Any) -> Any:
        if isinstance(result, dict):
            ok = not result.get("error")
        else:
            ok = not getattr(result, "is_error", False)
        now = _now()
        update: dict[str, Any] = {
            "id": self.id,
            "status": "executed" if ok else "failed",
            "executed_at": now,
            "result_preview": _preview(result),
            "outcome_status": "none",
        }
        probe = self._probe()
        if ok and probe and probe.get("kind") not in (None, "none"):
            after = _num(probe.get("after_s")) or 0
            update["outcome_due_at"] = now + timedelta(seconds=after)
            update["outcome_status"] = "pending"
        _queue(self.id, "update", update)
        if ok and self.notify:
            _queue(self.id, "notify", self.notify)
        if self.meta is not None and isinstance(result, ToolResult):
            md = dict(getattr(result, "metadata", None) or {})
            md["autonomy"] = {**self.meta, "status": update["status"]}
            result.metadata = md
        return result

    def failed(self, exc: BaseException) -> None:
        _queue(
            self.id,
            "update",
            {
                "id": self.id,
                "status": "failed",
                "executed_at": _now(),
                "result_preview": f"{type(exc).__name__}: {exc}"[:PREVIEW_CHARS],
                "outcome_status": "none",
            },
        )

    def refused(self, result: ToolResult) -> None:
        _queue(
            self.id,
            "update",
            {
                "id": self.id,
                "status": "blocked",
                "decision_note": str(result.content or "")[:PREVIEW_CHARS],
                "outcome_status": "none",
            },
        )


def _preview(result: Any) -> str:
    if isinstance(result, ToolResult):
        return str(result.content or "")[:PREVIEW_CHARS]
    try:
        return json.dumps(result, default=str)[:PREVIEW_CHARS]
    except (TypeError, ValueError):
        return str(result)[:PREVIEW_CHARS]


def agent_display_name(run: Any, grant: dict[str, Any] | None) -> str:
    """The name people gave the agent or pipeline, the run only knows a placeholder for pipelines."""
    return str(
        (grant or {}).get("agent_name")
        or (getattr(run, "agent_name", "") if run else "")
        or ""
    )


def _row(
    action_id: str,
    tenant: str,
    run: Any,
    tool_name: str,
    args: dict[str, Any],
    *,
    mode: str,
    status: str,
    target: str | None = None,
    intent: Any = None,
    prediction: dict[str, Any] | None = None,
    limits: dict[str, Any] | None = None,
    action_type: dict[str, Any] | None = None,
    grant: dict[str, Any] | None = None,
    level: int | None = None,
) -> dict[str, Any]:
    agent_id = getattr(run, "agent_id", "") if run else ""
    return {
        "id": action_id,
        "tenant_id": tenant,
        "execution_id": getattr(run, "execution_id", "") if run else None,
        "tool_call_id": _tool_call_for(run),
        "agent_id": agent_id or None,
        "agent_name": agent_display_name(run, grant),
        "agent_config_hash": (
            (getattr(run, "agent_config_hash", "") or config_hash(agent_id))
            if run
            else ""
        )
        or None,
        "user_id": (getattr(run, "user_id", "") if run else "") or None,
        "action_type_id": (action_type or {}).get("id") or None,
        "grant_id": (grant or {}).get("id") or None,
        "tool_name": tool_name,
        "level_at_time": level,
        "mode": mode,
        "target": target,
        "arguments": args,
        "intent": None if intent is None else str(intent)[:4000],
        "prediction": prediction,
        "limits_result": limits,
        "approval_id": None,
        "status": status,
        "outcome_status": "none",
        "harm": False,
    }


def _mode_for(level: int) -> str:
    return {1: "watching", 3: "auto", 4: "reported"}.get(level, "proposed")


# tools that change state without declaring an effect, held during a proof replay too
REPLAY_HOLD = frozenset(
    {
        "approval_gate",
        "human_approval",
        "defer_to_human",
        "memory_store",
        "memory_forget",
        "file_system",
        "redis_stream_publisher",
        "invoke_agent",
        "meeting_leave",
        "decision_propose",
    }
)
REPLAY_TEXT = (
    "Recorded during a proof replay, not executed. Nothing changed in the world. "
    "Answer as if the action is waiting for a person."
)


def replay_hold(tool: Any, arguments: Any, run: Any) -> Action | None:
    """In a proof replay every effect is recorded and never run, whatever the grant says."""
    root = governance.replay_root(run)
    if root is None:
        return None
    args_in = arguments if isinstance(arguments, dict) else {}
    name = getattr(tool, "name", "")
    eff = resolve_effect(tool, args_in)
    is_effect = eff is not None and eff.kind != READ_ONLY.kind
    if not is_effect and name not in REPLAY_HOLD:
        return None
    args = {k: v for k, v in args_in.items() if k not in ("_intent", "_prediction")}
    root.replay_held.append(
        {"tool": name, "kind": eff.kind if is_effect else "state", "arguments": args}
    )
    return Action(
        id=str(uuid.uuid4()),
        tenant_id=str(getattr(root, "tenant_id", "") or ""),
        tool_name=name,
        arguments=args,
        mode="watching",
        level=1,
        result=ToolResult(
            content=REPLAY_TEXT,
            is_error=False,
            metadata={
                "autonomy": {"mode": "replay", "status": "watching"},
                "tool": name,
            },
        ),
    )


async def gate(tool: Any, arguments: Any, run: Any, tenant: str) -> Action | None:
    """Apply the agent's level for this action. None means the call is not an effect."""
    held = replay_hold(tool, arguments, run)
    if held is not None:
        return held
    args_in = arguments if isinstance(arguments, dict) else {}
    merge = getattr(tool, "merged_arguments", None)
    eff = resolve_effect(tool, args_in)
    if eff is None or eff.kind == READ_ONLY.kind or not tenant:
        return None
    try:
        return await _gate(tool, eff, args_in, run, str(tenant), merge)
    except Exception:  # noqa: BLE001
        # a gate fault must not change what an unmanaged call does
        logger.exception("autonomy gate failed for %s", getattr(tool, "name", ""))
        if _managed(tenant, run, getattr(tool, "name", "")):
            return Action(
                id=str(uuid.uuid4()),
                tenant_id=str(tenant),
                tool_name=getattr(tool, "name", ""),
                arguments=args_in,
                result=ToolResult(
                    content="The autonomy check for this action failed, so it did not run. Try again shortly.",
                    is_error=True,
                    metadata={"autonomy": {"status": "blocked"}},
                ),
            )
        return None


def _managed(tenant: str, run: Any, tool_name: str) -> bool:
    agent = getattr(run, "agent_id", "") if run else ""
    return bool(agent and _by_tool.get((str(tenant), str(agent), tool_name)))


async def _gate(
    tool: Any,
    eff: Effect,
    args_in: dict[str, Any],
    run: Any,
    tenant: str,
    merge: Any,
) -> Action:
    args = {k: v for k, v in args_in.items() if k not in ("_intent", "_prediction")}
    intent = args_in.get("_intent")
    stated = args_in.get("_prediction")
    full = merge(args) if callable(merge) else args
    name = getattr(tool, "name", "")
    agent_id = str(getattr(run, "agent_id", "") or "") if run else ""
    raw_target = _arg(full, eff.target_param)
    target = None if raw_target is None else str(raw_target)[:500]
    at = match_action_type(tenant, name, full)
    grant, grants = (
        (None, [])
        if (at is None or not agent_id)
        else match_grant(tenant, agent_id, at, full)
    )
    action_id = str(uuid.uuid4())

    if at is None or not grants:
        stated_pred = _prediction_from(stated, {}, "agent_stated") if stated else None
        _queue(
            action_id,
            "insert",
            _row(
                action_id,
                tenant,
                run,
                name,
                args,
                mode="unmanaged",
                status="recorded",
                target=target,
                intent=intent,
                prediction=stated_pred,
                action_type=at,
            ),
        )
        return Action(id=action_id, tenant_id=tenant, tool_name=name, arguments=args)

    fallback: str | None = None
    if grant is None:
        # outside every scope the agent is trusted with: ask, never more
        level = min(2, max(effective_level(g, at, run)[0] for g in grants))
        if level == 2:
            fallback = "This target is outside the scope the agent is trusted with, so it asks first."
    else:
        level, fallback = effective_level(grant, at, run)
    label = str(at.get("label") or name)
    key = str(at.get("key") or name)
    link = f"/autonomy/{grant['id']}" if grant else "/autonomy"
    meta: dict[str, Any] = {
        "action_id": action_id,
        "level": level,
        "level_label": level_label(level),
        "grant_id": (grant or {}).get("id"),
        "action_type": {"key": key, "label": label},
        "action_key": key,
        "action_label": label,
        "link": link,
    }
    common = {
        "target": target,
        "intent": intent,
        "action_type": at,
        "grant": grant,
        "level": level,
    }

    def blocked(text: str, mode: str, **row_extra: Any) -> Action:
        # keep what the agent expected, so a reviewer sees it next to the block
        if "prediction" not in row_extra and stated:
            row_extra["prediction"] = _prediction_from(stated, {}, "agent_stated")
        _queue(
            action_id,
            "insert",
            _row(
                action_id,
                tenant,
                run,
                name,
                args,
                mode=mode,
                status="blocked",
                **common,
                **row_extra,
            ),
        )
        return Action(
            id=action_id,
            tenant_id=tenant,
            tool_name=name,
            arguments=args,
            result=ToolResult(
                content=text,
                is_error=True,
                metadata={
                    "autonomy": {**meta, "mode": mode, "status": "blocked"},
                    "tool": name,
                },
            ),
        )

    if level == 0:
        return blocked(
            f"This agent is not allowed to {_lower_first(label)} (Off). "
            f"An owner can change this on the Autonomy page: {link}",
            "proposed",
        )

    limits = await check_limits(at, tenant, full, target)
    if limits is not None and not limits.get("ok"):
        why = (
            ". ".join(r.rstrip(". ") for r in limits.get("reasons") or [])
            or "The call is outside the limits"
        )
        return blocked(
            f"Not done. {why}. {LIMITS_TEXT}: {link}",
            _mode_for(level),
            limits=limits,
        )

    prediction, pred_note = await predict(at, tenant, full, stated, target, intent)
    if prediction is None and pred_note:
        prediction_row: dict[str, Any] | None = {
            "metric": (at.get("world_model") or {}).get("metric") or "",
            "value": None,
            "low": None,
            "high": None,
            "source": "none",
            "note": pred_note,
        }
    else:
        prediction_row = prediction
    proposed = {
        "tool": name,
        "action_key": key,
        "label": label,
        "target": target,
        "arguments": args,
        "intent": intent,
        "prediction": prediction_row,
    }
    if level == 1:
        _queue(
            action_id,
            "insert",
            _row(
                action_id,
                tenant,
                run,
                name,
                args,
                mode="watching",
                status="watching",
                prediction=prediction_row,
                limits=limits,
                **common,
            ),
        )
        return Action(
            id=action_id,
            tenant_id=tenant,
            tool_name=name,
            arguments=args,
            mode="watching",
            level=1,
            result=ToolResult(
                content=WATCHING_TEXT,
                is_error=False,
                metadata={
                    "autonomy": {
                        **meta,
                        "mode": "watching",
                        "status": "watching",
                        "proposed": proposed,
                    },
                    "tool": name,
                },
            ),
        )

    if level == 3:
        if prediction is None:
            fallback = (
                f"No confident prediction: {pred_note}"
                if pred_note
                else "No confident prediction"
            )
        elif not band_ok(prediction, at.get("max_band_width")):
            fallback = (
                "The predicted band is wider than this action allows, so it asks first."
            )
        if fallback is None:
            _queue(
                action_id,
                "insert",
                _row(
                    action_id,
                    tenant,
                    run,
                    name,
                    args,
                    mode="auto",
                    status="approved",
                    prediction=prediction_row,
                    limits=limits,
                    **common,
                ),
            )
            return Action(
                id=action_id,
                tenant_id=tenant,
                tool_name=name,
                arguments=args,
                mode="auto",
                level=3,
                grant=grant,
                action_type=at,
                meta={**meta, "mode": "auto"},
            )

    if level == 4:
        _queue(
            action_id,
            "insert",
            _row(
                action_id,
                tenant,
                run,
                name,
                args,
                mode="reported",
                status="approved",
                prediction=prediction_row,
                limits=limits,
                **common,
            ),
        )
        owner = (grant or {}).get("granted_by") or (grant or {}).get("creator_id")
        agent_name = agent_display_name(run, grant) or "The agent"
        notify = None
        if owner:
            notify = {
                "tenant_id": tenant,
                "user_id": owner,
                "type": "action_reported",
                "title": f"{agent_name} acted: {label}",
                "message": f"{agent_name} ran {_lower_first(label)}"
                + (f" on {target}" if target else "")
                + ". It acts and reports at this level.",
                "link": link,
                "metadata": {
                    "action_id": action_id,
                    "grant_id": (grant or {}).get("id"),
                },
            }
        return Action(
            id=action_id,
            tenant_id=tenant,
            tool_name=name,
            arguments=args,
            mode="reported",
            level=4,
            grant=grant,
            action_type=at,
            meta={**meta, "mode": "reported"},
            notify=notify,
        )

    return await _ask_first(
        tool,
        action_id=action_id,
        tenant=tenant,
        run=run,
        name=name,
        args=args,
        at=at,
        grant=grant,
        level=level,
        target=target,
        intent=intent,
        prediction_row=prediction_row,
        limits=limits,
        fallback=fallback,
        meta=meta,
    )


class _ApiApprover:
    """Creates and waits on approvals through the internal API, as approval_gate does."""

    async def create(
        self, body: dict[str, Any], *, user_id: str, tenant_id: str
    ) -> tuple[dict[str, Any] | None, str]:
        from engine.tools import approval_gate as ag

        headers = ag.auth_headers(ag.run_token(user_id, tenant_id))
        self._headers = headers
        return await ag.create_approval(body, headers)

    async def wait(
        self, approval_id: str, *, expires_s: int, execution_id: str | None
    ) -> dict[str, Any]:
        from engine.tools import approval_gate as ag

        return await ag.wait_for_approval(
            approval_id, getattr(self, "_headers", {}), expires_s, execution_id
        )


def _decider_of(approval: dict[str, Any], decision: str) -> dict[str, Any]:
    for s in reversed(approval.get("signoffs") or []):
        if isinstance(s, dict) and s.get("decision") == decision:
            return s
    return {}


async def _ask_first(
    tool: Any,
    *,
    action_id: str,
    tenant: str,
    run: Any,
    name: str,
    args: dict[str, Any],
    at: dict[str, Any],
    grant: dict[str, Any] | None,
    level: int,
    target: str | None,
    intent: Any,
    prediction_row: dict[str, Any] | None,
    limits: dict[str, Any] | None,
    fallback: str | None,
    meta: dict[str, Any],
) -> Action:
    label = str(at.get("label") or name)
    key = str(at.get("key") or name)
    agent_id = str(getattr(run, "agent_id", "") or "") if run else ""
    agent_name = agent_display_name(run, grant) or "The agent"
    execution_id = (getattr(run, "execution_id", "") if run else "") or None
    row = _row(
        action_id,
        tenant,
        run,
        name,
        args,
        mode="proposed",
        status="pending",
        target=target,
        intent=intent,
        prediction=prediction_row,
        limits=limits,
        action_type=at,
        grant=grant,
        level=level,
    )
    await _write_now(action_id, "insert", row)
    card = {
        "action_id": action_id,
        "action_type": {
            "key": key,
            "label": label,
            "reversible": bool(at.get("reversible")),
        },
        "agent": {"id": agent_id or None, "name": agent_name},
        "level": level,
        "level_label": level_label(level),
        "target": target,
        "arguments": args,
        "intent": intent,
        "prediction": prediction_row,
        "limits": limits,
        "fallback_reason": fallback,
        "record": await _record_stats(tenant, (grant or {}).get("id") or ""),
        "editable_arguments": True,
    }
    policy = at.get("policy") or {}
    expires = int(_num(policy.get("approval_expires_s")) or DEFAULT_APPROVAL_EXPIRES)
    tier = risk.highest(
        [
            getattr(run, "tier", "low") if run else "low",
            risk.normalize(getattr(tool, "risk_tier", "low")),
        ]
    )
    body: dict[str, Any] = {
        "title": f"{agent_name} wants to {_lower_first(label)}",
        "payload": card,
        "required_signoffs": 1,
        "expires_seconds": expires,
        "agent_execution_id": execution_id,
        "agent_id": agent_id or None,
        "gate_kind": f"action:{key}",
    }
    if tier != "low":
        body["risk_tier"] = tier
    meta = {
        **meta,
        "mode": "proposed",
        "level": level,
        "level_label": level_label(level),
    }
    approver = _approver or _ApiApprover()
    approval, err = await approver.create(
        body,
        user_id=str(getattr(run, "user_id", "") or "") if run else "",
        tenant_id=tenant,
    )
    if approval is None:
        _queue(
            action_id,
            "update",
            {
                "id": action_id,
                "status": "blocked",
                "decision_note": err[:PREVIEW_CHARS],
            },
        )
        return Action(
            id=action_id,
            tenant_id=tenant,
            tool_name=name,
            arguments=args,
            result=ToolResult(
                content=f"Not done. This action needs a person's approval and the approval could not be created: {err}",
                is_error=True,
                metadata={"autonomy": {**meta, "status": "blocked"}, "tool": name},
            ),
        )
    approval_id = str(approval.get("id"))
    meta["approval_id"] = approval_id
    _queue(action_id, "update", {"id": action_id, "approval_id": approval_id})
    await _progress(execution_id, name, meta)
    emit("action_pending", {"name": name, "autonomy": {**meta, "status": "pending"}})
    try:
        final = await approver.wait(
            approval_id, expires_s=expires, execution_id=execution_id
        )
    except BaseException:
        _queue(
            action_id,
            "update",
            {
                "id": action_id,
                "status": "expired",
                "decided_at": _now(),
                "decision_note": "The run stopped while waiting for approval",
            },
        )
        raise
    status = final.get("status") or "expired"
    if status == "approved":
        signer = _decider_of(final, "approve")
        edited = (final.get("payload") or {}).get("edited_arguments")
        if not isinstance(edited, dict):
            edited = signer.get("edited_arguments")
        new_args = dict(args)
        if isinstance(edited, dict) and edited:
            new_args = {
                k: v
                for k, v in {**args, **edited}.items()
                if k not in ("_intent", "_prediction")
            }
        was_edited = new_args != args
        _queue(
            action_id,
            "update",
            {
                "id": action_id,
                "status": "edited" if was_edited else "approved",
                "arguments": new_args,
                "decided_by": signer.get("user_id"),
                "decided_at": _parse_time(final.get("decided_at")) or _now(),
                "decision_note": signer.get("reason") or None,
            },
        )
        who = signer.get("user_email") or signer.get("user_id") or "a reviewer"
        return Action(
            id=action_id,
            tenant_id=tenant,
            tool_name=name,
            arguments=new_args,
            mode="proposed",
            level=level,
            grant=grant,
            action_type=at,
            approved_by=str(who),
            meta={**meta, "decided_by": who, "edited": was_edited},
        )
    if status in ("denied", "returned", "rejected"):
        signer = _decider_of(final, "deny") or _decider_of(final, "return")
        who = signer.get("user_email") or signer.get("user_id") or "A reviewer"
        reason = (signer.get("reason") or "").strip().rstrip(".")
        _queue(
            action_id,
            "update",
            {
                "id": action_id,
                "status": "rejected",
                "decided_by": signer.get("user_id"),
                "decided_at": _parse_time(final.get("decided_at")) or _now(),
                "decision_note": reason or None,
            },
        )
        text = f"Not done. {who} rejected this action" + (
            f": {reason}." if reason else "."
        )
        text += " Do not tell the user it was done."
        return Action(
            id=action_id,
            tenant_id=tenant,
            tool_name=name,
            arguments=args,
            result=ToolResult(
                content=text,
                is_error=True,
                metadata={
                    "autonomy": {**meta, "status": "rejected", "decided_by": who},
                    "tool": name,
                },
            ),
        )
    _queue(
        action_id,
        "update",
        {"id": action_id, "status": "expired", "decided_at": _now()},
    )
    minutes = max(1, round(expires / 60))
    return Action(
        id=action_id,
        tenant_id=tenant,
        tool_name=name,
        arguments=args,
        result=ToolResult(
            content=(
                f"Not done. Nobody approved this action within {minutes} minutes, so it expired. "
                "Do not tell the user it was done."
            ),
            is_error=True,
            metadata={"autonomy": {**meta, "status": "expired"}, "tool": name},
        ),
    )


def _parse_time(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


async def _progress(
    execution_id: str | None, tool_name: str, meta: dict[str, Any]
) -> None:
    if not execution_id:
        return
    try:
        from engine import progress

        await progress.publish(
            execution_id,
            {
                "phase": "autonomy_waiting",
                "tool": tool_name,
                "autonomy": {**meta, "status": "pending"},
            },
        )
    except Exception:  # noqa: BLE001
        pass


# what the model sees


INTENT_SCHEMA = {
    "type": "string",
    "description": "Why you are taking this action, in one sentence",
}
PREDICTION_SCHEMA = {
    "type": "object",
    "description": "What you expect to happen: metric, value, low and high",
    "properties": {
        "metric": {"type": "string"},
        "value": {"type": "number"},
        "low": {"type": "number"},
        "high": {"type": "number"},
        "horizon_s": {"type": "number"},
    },
}


def describe(d: dict[str, Any], tool: Any) -> dict[str, Any]:
    """Add the autonomy line and the _intent / _prediction inputs when the agent holds a grant."""
    run = governance.current()
    agent = str(getattr(run, "agent_id", "") or "") if run else ""
    if not agent:
        return d
    grants = _by_tool.get((str(run.tenant_id or ""), agent, str(d.get("name") or "")))
    if not grants:
        return d
    g = next((x for x in grants if not x.get("scope")), grants[0])
    at = next(
        (
            t
            for t in _types.get(str(run.tenant_id or ""), ())
            if t["id"] == g["action_type_id"]
        ),
        None,
    )
    if at is None:
        return d
    level, _ = effective_level(g, at, run)
    _, label, help_text = LEVELS[level]
    out = dict(d)
    out["description"] = (
        f"{d.get('description') or ''}\nAutonomy for this action: {label}. {help_text}. "
        "Pass _intent (why) and _prediction {metric,value,low,high} with the call."
    )
    schema = dict(d.get("input_schema") or {"type": "object"})
    props = dict(schema.get("properties") or {})
    props.setdefault("_intent", INTENT_SCHEMA)
    props.setdefault("_prediction", PREDICTION_SCHEMA)
    schema["properties"] = props
    out["input_schema"] = schema
    return out
