"""What a rule may say: validation with plain errors per field, and a plain description."""

from __future__ import annotations

import math
import re
from typing import Any

from app.telemetry.rules.conditions import fmt

SEVERITIES = ("info", "warning", "critical")
ASSET_TYPES = ("vehicle", "machine", "sensor", "device", "system")
CONDITION_KINDS = (
    "threshold",
    "range",
    "rate",
    "stale",
    "state",
    "geofence",
    "count",
    "deviation",
)
ACTION_KINDS = ("alert", "notify", "run", "decision", "command")
CHANNELS = ("in_app", "email", "slack")
MAX_ACTIONS = 8
MAX_POLYGON = 200
TEMPLATE_MAX = 2000
_KEY = re.compile(r"^[A-Za-z0-9_.\-:/ ]{1,255}$")


class RuleInvalid(ValueError):
    def __init__(self, fields: dict[str, str]) -> None:
        super().__init__(next(iter(fields.values())) if fields else "Invalid rule")
        self.fields = fields


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _signal(v: Any) -> str:
    return str(v or "").strip()


def clean_scope(s: Any, err: dict[str, str]) -> dict[str, Any]:
    s = s if isinstance(s, dict) else {}
    kind = s.get("kind") or "asset"
    out: dict[str, Any] = {"kind": kind}
    grp = str(s.get("group") or "").strip()
    if kind == "asset":
        node = str(s.get("node") or "").strip()
        dev = s.get("device")
        dev = "*" if dev is None else str(dev).strip()
        if not grp:
            err["scope.group"] = "Pick the group the asset is in."
        if not node:
            err["scope.node"] = "Pick the asset this rule watches."
        out.update({"group": grp, "node": node, "device": dev})
    elif kind == "type":
        t = str(s.get("type") or "").strip()
        if t not in ASSET_TYPES:
            err["scope.type"] = (
                "Pick an asset type: vehicle, machine, sensor, device or system."
            )
        out.update({"type": t, "group": grp})
    elif kind == "tag":
        tag = str(s.get("tag") or "").strip().lower()
        if not tag:
            err["scope.tag"] = "Pick a tag. Tags are set on the Assets page."
        out.update({"tag": tag, "group": grp})
    else:
        err["scope.kind"] = "Choose one asset, an asset type or a tag."
    return out


def clean_condition(c: Any, err: dict[str, str]) -> dict[str, Any]:
    c = c if isinstance(c, dict) else {}
    kind = c.get("kind")
    if kind not in CONDITION_KINDS:
        err["condition.kind"] = "Choose what the rule watches for."
        return {"kind": kind}
    out: dict[str, Any] = {"kind": kind}
    h = _num(c.get("hysteresis")) or 0.0
    if h < 0:
        err["condition.hysteresis"] = "The margin cannot be negative."
    if kind != "geofence":
        sig = _signal(c.get("signal"))
        if kind != "stale" and not sig:
            err["condition.signal"] = "Pick the signal to watch."
        if sig and not _KEY.match(sig):
            err["condition.signal"] = (
                "Signal names are letters, digits and _ . - : / only."
            )
        out["signal"] = sig
    if kind == "threshold":
        op = c.get("op") or ">"
        if op not in (">", ">=", "<", "<="):
            err["condition.op"] = "Choose above or below."
        v = _num(c.get("value"))
        if v is None:
            err["condition.value"] = "Enter the number to compare with."
        out.update({"op": op, "value": v, "hysteresis": h})
    elif kind == "range":
        lo, hi = _num(c.get("min")), _num(c.get("max"))
        if lo is None:
            err["condition.min"] = "Enter the lowest normal value."
        if hi is None:
            err["condition.max"] = "Enter the highest normal value."
        if lo is not None and hi is not None:
            if lo >= hi:
                err["condition.max"] = "The highest value must be above the lowest."
            elif lo + h > hi - h:
                err["condition.hysteresis"] = "The margin is wider than half the range."
        out.update({"min": lo, "max": hi, "hysteresis": h})
    elif kind == "rate":
        limit = _num(c.get("limit"))
        if limit is None or limit <= 0:
            err["condition.limit"] = "Enter how fast a change is too fast, above zero."
        per = c.get("per") or "s"
        if per not in ("s", "min", "h"):
            err["condition.per"] = "Choose per second, minute or hour."
        d = c.get("direction") or "either"
        if d not in ("up", "down", "either"):
            err["condition.direction"] = "Choose rising, falling or either."
        w = _num(c.get("window_s"))
        w = 10.0 if w is None else w
        if not 1 <= w <= 3600:
            err["condition.window_s"] = "Measure over 1 to 3600 seconds."
        if limit is not None and limit > 0 and h >= limit:
            err["condition.hysteresis"] = "The margin must be smaller than the limit."
        out.update(
            {"limit": limit, "per": per, "direction": d, "window_s": w, "hysteresis": h}
        )
    elif kind == "stale":
        secs = _num(c.get("seconds"))
        if secs is None or not 1 <= secs <= 86400:
            err["condition.seconds"] = "Enter 1 to 86400 seconds."
        out.update({"seconds": secs})
    elif kind == "state":
        if "equals" not in c or c.get("equals") in (None, ""):
            err["condition.equals"] = "Enter the value to look for."
        eq = c.get("equals")
        if isinstance(eq, (dict, list)):
            err["condition.equals"] = (
                "Compare with one value, text, a number or true or false."
            )
        op = c.get("op") or "equals"
        if op not in ("equals", "not_equals"):
            err["condition.op"] = "Choose is or is not."
        out.update({"equals": eq, "op": op})
    elif kind == "geofence":
        frame = c.get("frame") or "site"
        if frame not in ("gnss", "site"):
            err["condition.frame"] = (
                "Choose GPS latitude and longitude, or site x and y."
            )
        xs, ys = _signal(c.get("x_signal")), _signal(c.get("y_signal"))
        what = ("longitude", "latitude") if frame == "gnss" else ("x", "y")
        if not xs:
            err["condition.x_signal"] = f"Pick the {what[0]} signal."
        if not ys:
            err["condition.y_signal"] = f"Pick the {what[1]} signal."
        if xs and xs == ys:
            err["condition.y_signal"] = (
                f"The {what[1]} signal must differ from the {what[0]} signal."
            )
        poly_in = c.get("polygon") if isinstance(c.get("polygon"), list) else []
        poly: list[list[float]] = []
        bad = False
        for p in poly_in:
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                bad = True
                break
            px, py = _num(p[0]), _num(p[1])
            if px is None or py is None:
                bad = True
                break
            if frame == "gnss" and not (-180 <= px <= 180 and -90 <= py <= 90):
                bad = True
                break
            poly.append([px, py])
        if bad:
            err["condition.polygon"] = (
                "Each corner needs a longitude from -180 to 180 and a latitude from -90 to 90."
                if frame == "gnss"
                else "Each corner needs an x and a y number."
            )
        elif len(poly) < 3:
            err["condition.polygon"] = "Draw the zone with at least 3 corners."
        elif len(poly) > MAX_POLYGON:
            err["condition.polygon"] = f"A zone can have at most {MAX_POLYGON} corners."
        on = c.get("on") or "enter"
        if on not in ("enter", "exit"):
            err["condition.on"] = "Choose enters or leaves."
        zone = str(c.get("zone") or "").strip()[:60]
        out.update(
            {
                "frame": frame,
                "x_signal": xs,
                "y_signal": ys,
                "polygon": poly,
                "on": on,
                "zone": zone,
                "hysteresis": h,
            }
        )
    elif kind == "deviation":
        w = _num(c.get("window_s"))
        w = 300.0 if w is None else w
        b = _num(c.get("baseline_s"))
        b = 1800.0 if b is None else b
        if not 10 <= w <= 86400:
            err["condition.window_s"] = (
                "Take the recent window over 10 to 86400 seconds."
            )
        if not w < b <= 7 * 86400:
            err["condition.baseline_s"] = (
                "The baseline must be longer than the recent window, and at most 7 days."
            )
        mode = c.get("mode") or "ratio"
        if mode not in ("ratio", "zscore"):
            err["condition.mode"] = "Compare as a percentage or in standard deviations."
        d = c.get("direction") or "up"
        if d not in ("up", "down", "either"):
            err["condition.direction"] = "Choose above, below or either way."
        t = _num(c.get("threshold"))
        if t is None or t <= 0:
            err["condition.threshold"] = (
                "Enter how far is too far, like 1.15 for 15% above or 3 for three standard deviations."
            )
        elif mode == "ratio" and d == "up" and t <= 1:
            err["condition.threshold"] = (
                "Above its baseline means more than 1, like 1.15 for 15% above."
            )
        elif mode == "ratio" and d == "down" and t >= 1:
            err["condition.threshold"] = (
                "Below its baseline means less than 1, like 0.85 for 15% below."
            )
        elif mode == "ratio" and d == "either" and t <= 1:
            err["condition.threshold"] = (
                "Either way takes a factor above 1, like 1.15 for 15%."
            )
        if t is not None and t > 0 and mode == "zscore" and h >= t:
            err["condition.hysteresis"] = "The margin must be smaller than the limit."
        out.update(
            {
                "window_s": w,
                "baseline_s": b,
                "mode": mode,
                "direction": d,
                "threshold": t,
                "hysteresis": h,
            }
        )
    elif kind == "count":
        n = _num(c.get("count"))
        if n is None or not 1 <= n <= 10000 or not float(n).is_integer():
            err["condition.count"] = "Enter a whole number from 1 to 10000."
        w = _num(c.get("window_s"))
        if w is None or not 1 <= w <= 86400:
            err["condition.window_s"] = "Enter a window of 1 to 86400 seconds."
        when = c.get("when") if isinstance(c.get("when"), dict) else None
        wout = None
        if when:
            if "equals" in when:
                wout = {"equals": when.get("equals")}
            else:
                op = when.get("op") or ">"
                v = _num(when.get("value"))
                if op not in (">", ">=", "<", "<=") or v is None:
                    err["condition.when"] = (
                        "Enter the reading that counts, like above 300."
                    )
                wout = {"op": op, "value": v}
        if n is not None and h >= n:
            err["condition.hysteresis"] = "The margin must be smaller than the count."
        out.update(
            {
                "count": int(n) if n is not None else None,
                "window_s": w,
                "when": wout,
                "hysteresis": float(int(h)),
            }
        )
    return out


def clean_actions(a: Any, err: dict[str, str]) -> list[dict[str, Any]]:
    items = a if isinstance(a, list) else []
    if len(items) > MAX_ACTIONS:
        err["actions"] = f"A rule can do at most {MAX_ACTIONS} things."
    out = []
    for i, x in enumerate(items[:MAX_ACTIONS]):
        x = x if isinstance(x, dict) else {}
        kind = x.get("kind")
        p = f"actions.{i}"
        if kind not in ACTION_KINDS:
            err[f"{p}.kind"] = "Choose what to do."
            continue
        if kind == "alert":
            sev = x.get("severity") or None
            if sev is not None and sev not in SEVERITIES:
                err[f"{p}.severity"] = "Choose info, warning or critical."
            out.append({"kind": "alert", "severity": sev})
        elif kind == "notify":
            ch = x.get("channel") or "in_app"
            if ch not in CHANNELS:
                err[f"{p}.channel"] = (
                    "Choose in Abenix, email or the workspace Slack channel."
                )
            to = [str(u) for u in (x.get("to") or []) if u][:50]
            msg = str(x.get("message") or "")[:TEMPLATE_MAX]
            out.append({"kind": "notify", "channel": ch, "to": to, "message": msg})
        elif kind == "run":
            aid = str(x.get("agent_id") or "").strip()
            if not aid:
                err[f"{p}.agent_id"] = "Pick the agent or pipeline to run."
            msg = str(x.get("message") or "")[:TEMPLATE_MAX]
            run: dict[str, Any] = {"kind": "run", "agent_id": aid, "message": msg}
            run["wait"] = x.get("wait") is not False
            if x.get("wait_s") not in (None, ""):
                w = _num(x.get("wait_s"))
                if w is None or not 5 <= w <= 3600:
                    err[f"{p}.wait_s"] = "Wait from 5 seconds to an hour."
                else:
                    run["wait_s"] = int(w)
            out.append(run)
        elif kind == "decision":
            key = str(x.get("key") or "").strip()
            if not key:
                err[f"{p}.key"] = "Pick the decision table to evaluate."
            facts = x.get("facts") if isinstance(x.get("facts"), dict) else {}
            facts = {str(k)[:80]: str(v)[:500] for k, v in list(facts.items())[:40]}
            out.append({"kind": "decision", "key": key, "facts": facts})
        elif kind == "command":
            sig = _signal(x.get("signal"))
            if not sig:
                err[f"{p}.signal"] = "Pick the signal to write, like Safety/Hold."
            if "value" not in x or x.get("value") in (None, ""):
                err[f"{p}.value"] = "Enter the value to send."
            tgt = {
                k: str(x.get(k)).strip()
                for k in ("group", "node", "device")
                if x.get(k) not in (None, "")
            }
            out.append(
                {"kind": "command", "signal": sig, "value": x.get("value"), **tgt}
            )
    for i, x in enumerate(out):
        bad = step_ref_problem(x, i)
        if bad:
            err.setdefault(f"actions.{i}.{bad[0]}", bad[1])
    return out


_STEP_REF = re.compile(r"\{\{?\s*steps\.(\d+)\.")


def step_ref_problem(a: dict[str, Any], i: int) -> tuple[str, str] | None:
    """A {steps.N.output} in step i+1 must name an earlier step."""
    fields = {"message": a.get("message"), "value": a.get("value")}
    fields["facts"] = " ".join(str(v) for v in (a.get("facts") or {}).values())
    for field, text in fields.items():
        for m in _STEP_REF.finditer(str(text or "")):
            n = int(m.group(1))
            if n < 1 or n > i:
                where = "an earlier step" if i else "a step, and this is the first"
                return (
                    field,
                    f"{{steps.{n}...}} must name {where}. Steps count from 1 in the order shown.",
                )
    return None


def clean(body: dict[str, Any]) -> dict[str, Any]:
    """The rule as stored. Raises RuleInvalid with a message per field."""
    err: dict[str, str] = {}
    name = str(body.get("name") or "").strip()
    if not name:
        err["name"] = "Give the rule a name people will recognise."
    elif len(name) > 160:
        err["name"] = "Keep the name under 160 characters."
    desc = str(body.get("description") or "").strip()
    if len(desc) > 1000:
        err["description"] = "Keep the description under 1000 characters."
    sev = body.get("severity") or "warning"
    if sev not in SEVERITIES:
        err["severity"] = "Choose info, warning or critical."
    cd = _num(body.get("cooldown_s"))
    cd = 60.0 if cd is None else cd
    if not 0 <= cd <= 86400:
        err["cooldown_s"] = "Wait 0 to 86400 seconds between firings."
    scope = clean_scope(body.get("scope"), err)
    cond = clean_condition(body.get("condition"), err)
    actions = clean_actions(body.get("actions"), err)
    if err:
        raise RuleInvalid(err)
    return {
        "name": name,
        "description": desc or None,
        "severity": sev,
        "enabled": bool(body.get("enabled", True)),
        "cooldown_s": int(cd),
        "scope": scope,
        "condition": cond,
        "actions": actions,
    }


# plain words


def _per(per: str) -> str:
    return {"s": "second", "min": "minute", "h": "hour"}.get(per, "second")


def describe_condition(c: dict[str, Any]) -> str:
    k = c.get("kind")
    sig = c.get("signal") or ""
    h = float(c.get("hysteresis") or 0)
    if k == "threshold":
        op = c.get("op") or ">"
        v = c.get("value")
        word = {
            ">": "goes above",
            ">=": "reaches",
            "<": "drops below",
            "<=": "drops to",
        }[op]
        s = f"{sig} {word} {fmt(v)}"
        if h:
            back = float(v) - h if op in (">", ">=") else float(v) + h
            s += f" (clears {'at or below' if op in ('>', '>=') else 'at or above'} {fmt(back)})"
        return s
    if k == "range":
        s = f"{sig} leaves the range {fmt(c.get('min'))} to {fmt(c.get('max'))}"
        return s + (f" (clears {fmt(h)} inside it)" if h else "")
    if k == "rate":
        d = {"up": "rises", "down": "falls", "either": "changes"}[
            c.get("direction") or "either"
        ]
        return (
            f"{sig} {d} faster than {fmt(c.get('limit'))} a {_per(c.get('per') or 's')}"
            f" over {fmt(c.get('window_s'))} s"
        )
    if k == "stale":
        return f"no {sig or 'data'} arrives for {fmt(c.get('seconds'))} s"
    if k == "state":
        neg = (c.get("op") or "equals") == "not_equals"
        return f"{sig} {'is not' if neg else 'is'} {fmt(c.get('equals'))}"
    if k == "geofence":
        zone = c.get("zone") or "the drawn zone"
        frame = "GPS position" if c.get("frame") == "gnss" else "site position"
        verb = "enters" if (c.get("on") or "enter") == "enter" else "leaves"
        return f"the {frame} {verb} {zone}"
    if k == "deviation":
        win = fmt(float(c.get("window_s") or 300) / 60)
        base = fmt(float(c.get("baseline_s") or 1800) / 60)
        t = float(c.get("threshold") or 0)
        d = c.get("direction") or "up"
        if (c.get("mode") or "ratio") == "ratio":
            pct = fmt(round(abs(t - 1) * 100, 1))
            how = {
                "up": f"{pct}% above",
                "down": f"{pct}% below",
                "either": f"{pct}% either way from",
            }[d]
        else:
            how = {
                "up": f"more than {fmt(t)} standard deviations above",
                "down": f"more than {fmt(t)} standard deviations below",
                "either": f"more than {fmt(t)} standard deviations either way from",
            }[d]
        return f"the last {win} min of {sig} run {how} the last {base} min"
    if k == "count":
        w = c.get("when")
        what = sig
        if w and "equals" in w:
            what += f" is {fmt(w.get('equals'))}"
        elif w:
            what += f" {w.get('op')} {fmt(w.get('value'))}"
        return (
            f"{what} happens {c.get('count')} times within {fmt(c.get('window_s'))} s"
        )
    return "the condition is met"


def describe_scope(s: dict[str, Any], names: dict[str, str] | None = None) -> str:
    names = names or {}
    k = s.get("kind")
    gtail = f" in {s['group']}" if s.get("group") and k != "asset" else ""
    if k == "asset":
        base = names.get(f"{s.get('group')}/{s.get('node')}/") or s.get("node") or "?"
        dev = s.get("device")
        if dev == "*":
            return f"{base} or any of its parts"
        if dev:
            return f"{base} part {dev}"
        return base
    if k == "type":
        return f"any {s.get('type')}{gtail}"
    if k == "tag":
        return f"assets tagged {s.get('tag')}{gtail}"
    return "?"


def describe_action(a: dict[str, Any], labels: dict[str, str] | None = None) -> str:
    labels = labels or {}
    k = a.get("kind")
    if k == "alert":
        return "raise an alert"
    if k == "notify":
        ch = {"in_app": "in Abenix", "email": "by email", "slack": "on Slack"}[
            a.get("channel") or "in_app"
        ]
        who = f"{len(a['to'])} people" if a.get("to") else "the workspace admins"
        if a.get("channel") == "slack":
            return "post to the workspace Slack channel"
        return f"tell {who} {ch}"
    if k == "run":
        return f"run {labels.get(a.get('agent_id') or '', 'an agent')}"
    if k == "decision":
        return f"evaluate the decision {a.get('key')}"
    if k == "command":
        return f"set {a.get('signal')} to {fmt(a.get('value'))}"
    return k or "?"


def describe(
    rule: dict[str, Any],
    names: dict[str, str] | None = None,
    labels: dict[str, str] | None = None,
) -> str:
    acts = [describe_action(a, labels) for a in rule.get("actions") or []]
    then = (
        ", ".join(acts[:-1]) + (" and " if len(acts) > 1 else "") + acts[-1]
        if acts
        else "record it"
    )
    return f"When {describe_condition(rule.get('condition') or {})} on {describe_scope(rule.get('scope') or {}, names)}, {then}."
