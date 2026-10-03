"""Deterministic evaluation of compiled decisions, safe for many concurrent callers.

Facts are checked before the engine runs, because the engine treats a missing
or mistyped fact as a rule that did not match. A wrong input must never look
like "no obligation".
"""

from __future__ import annotations

import asyncio
import copy
import datetime as _dt
import hashlib
import json
import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from engine.decisions.authoring import AS_OF, DATE_RE, canonical_json

_CACHE_SIZE = int(os.environ.get("DECISION_CACHE_SIZE", "512"))
_engine: Any = None
_cache: "OrderedDict[str, Any]" = OrderedDict()
_lock = threading.Lock()


@dataclass
class Evaluation:
    outcome: str  # decided | no_match | missing_facts | invalid_facts
    result: Any = None
    applied_rules: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    invalid_facts: list[dict[str, str]] = field(default_factory=list)
    normalised: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    trace_hash: str = ""
    duration_us: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "result": self.result,
            "applied_rules": self.applied_rules,
            "missing_facts": self.missing_facts,
            "invalid_facts": self.invalid_facts,
            "normalised": self.normalised,
            "trace": self.trace,
            "trace_hash": self.trace_hash,
            "duration_us": self.duration_us,
        }


def _get_engine() -> Any:
    global _engine
    if _engine is None:
        import zen

        _engine = zen.ZenEngine()
    return _engine


def compiled(content_hash: str, jdm: dict[str, Any]) -> Any:
    """The compiled decision for this content, compiled once per process."""
    with _lock:
        d = _cache.get(content_hash)
        if d is not None:
            _cache.move_to_end(content_hash)
            return d
    d = _get_engine().create_decision(json.dumps(jdm))
    with _lock:
        _cache[content_hash] = d
        _cache.move_to_end(content_hash)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return d


def cache_size() -> int:
    return len(_cache)


def forget(content_hash: str | None = None) -> None:
    with _lock:
        if content_hash is None:
            _cache.clear()
        else:
            _cache.pop(content_hash, None)


def _get(facts: dict[str, Any], path: str) -> Any:
    cur: Any = facts
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set(facts: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = facts
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _coerce(t: str, v: Any) -> tuple[bool, Any]:
    """(ok, value) with the value in the engine's canonical form for the type."""
    if t == "number":
        if isinstance(v, bool):
            return False, v
        if isinstance(v, (int, float)):
            return True, v
        if isinstance(v, str):
            try:
                n = float(v.strip().replace(",", ""))
                return True, int(n) if n.is_integer() else n
            except ValueError:
                return False, v
        return False, v
    if t == "date":
        if isinstance(v, _dt.datetime):
            return True, v.date().isoformat()
        if isinstance(v, _dt.date):
            return True, v.isoformat()
        if isinstance(v, str) and DATE_RE.match(v.strip()):
            return True, v.strip()[:10] if len(v.strip()) >= 10 else v.strip()
        return False, v
    if t == "boolean":
        if isinstance(v, bool):
            return True, v
        if isinstance(v, str) and v.strip().lower() in ("true", "false", "yes", "no"):
            return True, v.strip().lower() in ("true", "yes")
        return False, v
    if t == "list":
        return (True, v) if isinstance(v, list) else (True, [v])
    if isinstance(v, str):
        return True, v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        # identifiers such as product codes often arrive as numbers
        return True, str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
    return False, v


def prepare(
    facts: Any, required: list[str], fact_types: dict[str, str]
) -> tuple[dict[str, Any], list[str], list[dict[str, str]], list[dict[str, Any]]]:
    """Copy, check and normalise facts. Returns (facts, missing, invalid, normalised)."""
    data = copy.deepcopy(facts) if isinstance(facts, dict) else {}
    missing = [p for p in required if _get(data, p) in (None, "")]
    invalid: list[dict[str, str]] = []
    normalised: list[dict[str, Any]] = []
    for path, t in fact_types.items():
        v = _get(data, path)
        if v is None:
            continue
        ok, nv = _coerce(t, v)
        if not ok:
            invalid.append(
                {
                    "fact": path,
                    "expected": t,
                    "got": type(v).__name__,
                    "value": str(v)[:120],
                }
            )
        elif nv != v or type(nv) is not type(v):
            normalised.append({"fact": path, "from": v, "to": nv})
            _set(data, path, nv)
    return data, missing, invalid, normalised


def _as_of_str(as_of: Any) -> str:
    if as_of is None:
        return _dt.date.today().isoformat()
    if isinstance(as_of, _dt.datetime):
        return as_of.date().isoformat()
    if isinstance(as_of, _dt.date):
        return as_of.isoformat()
    return str(as_of)[:10]


def trace_hash(
    facts: dict[str, Any], content_hash: str, result: Any, applied: list[str]
) -> str:
    body = canonical_json(
        {"facts": facts, "decision": content_hash, "result": result, "rules": applied}
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_NOT_FACTS = {
    "date",
    "and",
    "or",
    "not",
    "in",
    "true",
    "false",
    "null",
    "contains",
    "startsWith",
    "endsWith",
    "len",
}


def _rule_cells(jdm: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for n in jdm.get("nodes") or []:
        if n.get("type") == "decisionTableNode":
            ins = [i["id"] for i in (n.get("content") or {}).get("inputs") or []]
            for r in (n.get("content") or {}).get("rules") or []:
                out[str(r.get("_id"))] = [str(r.get(i) or "") for i in ins]
    return out


def _values_seen(cells: list[str], facts: dict[str, Any]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for cell in cells:
        for name in _IDENT.findall(cell.replace('\\"', "")):
            if name in _NOT_FACTS:
                continue
            v = _get(facts, name)
            if v is not None or "." in name:
                seen[name] = v
    return seen


def _readable_trace(
    raw: dict[str, Any],
    descriptions: dict[str, str],
    cells: dict[str, list[str]],
    facts: dict[str, Any],
) -> list[dict[str, Any]]:
    steps = []
    for node in sorted((raw or {}).values(), key=lambda n: n.get("order", 0)):
        data = node.get("traceData")
        if isinstance(data, list):
            for hit in data:
                rule = hit.get("rule") or {}
                rid = rule.get("_id", "")
                steps.append(
                    {
                        "node": node.get("name"),
                        "rule_id": rid,
                        "description": descriptions.get(rid, ""),
                        "values_seen": hit.get("reference_map")
                        or _values_seen(cells.get(rid, []), facts),
                        "matched": True,
                    }
                )
        elif isinstance(data, dict) and data.get("rule"):
            rule = data.get("rule") or {}
            steps.append(
                {
                    "node": node.get("name"),
                    "rule_id": rule.get("_id", ""),
                    "description": descriptions.get(rule.get("_id", ""), ""),
                    "values_seen": data.get("reference_map")
                    or _values_seen(cells.get(rule.get("_id", ""), []), facts),
                    "matched": True,
                }
            )
    return steps


def _descriptions(jdm: dict[str, Any]) -> dict[str, str]:
    out = {}
    for n in jdm.get("nodes") or []:
        if n.get("type") == "decisionTableNode":
            for r in (n.get("content") or {}).get("rules") or []:
                out[str(r.get("_id"))] = str(r.get("_description") or "")
    return out


def _split_result(result: Any) -> tuple[Any, list[str]]:
    applied: list[str] = []

    def strip(d: Any) -> Any:
        if isinstance(d, dict):
            rule = d.pop("_rule", None)
            if rule:
                applied.append(str(rule))
        return d

    if isinstance(result, list):
        return [strip(dict(x)) if isinstance(x, dict) else x for x in result], applied
    if isinstance(result, dict):
        return strip(dict(result)), applied
    return result, applied


def _empty(result: Any) -> bool:
    return result is None or result == {} or result == []


async def evaluate(
    content_hash: str,
    jdm: dict[str, Any],
    facts: Any,
    *,
    required: list[str] | None = None,
    fact_types: dict[str, str] | None = None,
    as_of: Any = None,
    want_trace: bool = True,
) -> Evaluation:
    """Check facts, run the decision, and describe what happened."""
    data, missing, invalid, normalised = prepare(
        facts, list(required or []), dict(fact_types or {})
    )
    if missing:
        return Evaluation(
            outcome="missing_facts", missing_facts=missing, normalised=normalised
        )
    if invalid:
        return Evaluation(
            outcome="invalid_facts", invalid_facts=invalid, normalised=normalised
        )
    data[AS_OF] = _as_of_str(as_of)
    decision = compiled(content_hash, jdm)
    raw = await decision.async_evaluate(data, {"trace": bool(want_trace)})
    result, applied = _split_result(raw.get("result"))
    perf = str(raw.get("performance") or "")
    duration_us = 0
    try:
        if perf.endswith("µs"):
            duration_us = int(float(perf[:-2]))
        elif perf.endswith("ms"):
            duration_us = int(float(perf[:-2]) * 1000)
    except ValueError:
        pass
    checked = {k: v for k, v in data.items()}
    return Evaluation(
        outcome="no_match" if _empty(result) else "decided",
        result=result,
        applied_rules=applied,
        normalised=normalised,
        trace=(
            _readable_trace(
                raw.get("trace") or {}, _descriptions(jdm), _rule_cells(jdm), data
            )
            if want_trace
            else []
        ),
        trace_hash=trace_hash(checked, content_hash, result, applied),
        duration_us=duration_us,
    )


async def evaluate_many(
    content_hash: str,
    jdm: dict[str, Any],
    items: list[Any],
    *,
    required: list[str] | None = None,
    fact_types: dict[str, str] | None = None,
    as_of: Any = None,
    want_trace: bool = False,
    concurrency: int = 64,
) -> list[Evaluation]:
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(f: Any) -> Evaluation:
        async with sem:
            return await evaluate(
                content_hash,
                jdm,
                f,
                required=required,
                fact_types=fact_types,
                as_of=as_of,
                want_trace=want_trace,
            )

    return list(await asyncio.gather(*(one(f) for f in items)))
