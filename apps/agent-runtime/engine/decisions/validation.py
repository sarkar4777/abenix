"""Checks run before a version can be proposed: golden tests, regression, and rule overlap."""

from __future__ import annotations

import datetime as dt
from typing import Any

from engine.decisions import evaluator
from engine.decisions.authoring import AS_OF, Compiled, condition_expr, canonical_json


def _bump(t: str, v: Any, up: bool) -> Any:
    if t == "number" and isinstance(v, (int, float)):
        return v + (1 if up else -1)
    if t == "date" and isinstance(v, str):
        try:
            d = dt.date.fromisoformat(v[:10])
            return (d + dt.timedelta(days=1 if up else -1)).isoformat()
        except ValueError:
            return v
    return v


def _sample(t: str) -> Any:
    return {"number": 1, "boolean": True, "date": "2026-01-01", "list": ["x"]}.get(
        t, "x"
    )


def _set(facts: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = facts
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def witness(
    rule: dict[str, Any], fact_types: dict[str, str], ref_sets: dict[str, list[Any]]
) -> dict[str, Any] | None:
    """Facts that satisfy the rule's top-level conditions, or None when it has nested groups."""
    when = rule.get("when") or {}
    if "any" in when or when.get("negate"):
        return None
    facts: dict[str, Any] = {}
    for c in when.get("all") or []:
        if "fact" not in c:
            return None
        t = fact_types.get(c["fact"], "string")
        op, v, vs = c.get("op"), c.get("value"), c.get("values") or []
        if op in (
            "eq",
            "gte",
            "lte",
            "on_or_after",
            "on_or_before",
            "contains",
            "starts_with",
            "ends_with",
        ):
            val = v
            if op == "contains" and t == "list":
                val = [v]
        elif op in ("gt", "after"):
            val = _bump(t, v, True)
        elif op in ("lt", "before"):
            val = _bump(t, v, False)
        elif op == "between":
            val = vs[0] if vs else _sample(t)
        elif op == "in":
            val = vs[0] if vs else _sample(t)
        elif op == "in_reference_set":
            members = ref_sets.get(str(c.get("set")), [])
            val = members[0] if members else _sample(t)
        elif op == "is_true":
            val = True
        elif op == "is_false":
            val = False
        elif op == "is_set":
            val = _sample(t)
        elif op == "is_not_set":
            continue
        elif op == "neq":
            val = _bump(t, v, True) if t in ("number", "date") else f"{v}_other"
        else:
            val = _sample(t)
        _set(facts, c["fact"], val)
    return facts


def _matches(
    rule: dict[str, Any],
    facts: dict[str, Any],
    fact_types: dict[str, str],
    ref_sets: dict[str, list[Any]],
) -> bool:
    import zen

    expr = (
        condition_expr(
            rule.get("when") or {"all": []}, {**fact_types, AS_OF: "date"}, ref_sets
        )
        or "true"
    )
    try:
        return bool(zen.evaluate_expression(expr, facts))
    except Exception:  # noqa: BLE001
        return False


def overlaps(
    doc: dict[str, Any], ref_sets: dict[str, list[Any]] | None = None
) -> list[dict[str, Any]]:
    """Rules another rule hides under first match, or that disagree when both apply."""
    ref_sets = ref_sets or {}
    fact_types = {f["path"]: f.get("type", "string") for f in doc.get("facts") or []}
    rules = [r for r in doc.get("rules") or [] if r.get("enabled", True)]
    first = doc.get("hit_policy", "first") == "first"
    found: list[dict[str, Any]] = []
    for j, rj in enumerate(rules):
        w = witness(rj, fact_types, ref_sets)
        if w is None:
            continue
        for i, ri in enumerate(rules):
            if i == j or (first and i > j):
                continue
            if not _matches(ri, w, fact_types, ref_sets):
                continue
            if first:
                found.append(
                    {
                        "rule": rj.get("key") or rj.get("id"),
                        "other": ri.get("key") or ri.get("id"),
                        "kind": "shadowed",
                        "example": w,
                        "message": (
                            f"Rule {rj.get('key') or rj.get('id')} is not reached for inputs like this one, "
                            f"because rule {ri.get('key') or ri.get('id')} above it matches first."
                        ),
                    }
                )
                break
            then_i, then_j = ri.get("then") or {}, rj.get("then") or {}
            clash = [
                k
                for k in set(then_i) & set(then_j)
                if canonical_json(then_i[k]) != canonical_json(then_j[k])
            ]
            if clash and i < j:
                found.append(
                    {
                        "rule": rj.get("key") or rj.get("id"),
                        "other": ri.get("key") or ri.get("id"),
                        "kind": "conflict",
                        "fields": sorted(clash),
                        "example": w,
                        "message": (
                            f"Rules {ri.get('key') or ri.get('id')} and {rj.get('key') or rj.get('id')} both apply "
                            f"to inputs like this one and give different {', '.join(sorted(clash))}."
                        ),
                    }
                )
    return found


def _same(a: Any, b: Any) -> bool:
    return canonical_json(a) == canonical_json(b)


async def run_tests(
    compiled: Compiled, tests: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Each golden case against a compiled version."""
    out = []
    for t in tests:
        ev = await evaluator.evaluate(
            compiled.content_hash,
            compiled.jdm,
            t.get("facts") or {},
            required=compiled.required_facts,
            fact_types=compiled.fact_types,
            as_of=t.get("as_of"),
            want_trace=False,
        )
        want_outcome = t.get("expected_outcome") or "decided"
        ok = ev.outcome == want_outcome and (
            want_outcome != "decided"
            or t.get("expected") is None
            or _same(ev.result, t.get("expected"))
        )
        out.append(
            {
                "test_id": t.get("id"),
                "name": t.get("name"),
                "passed": ok,
                "expected_outcome": want_outcome,
                "expected": t.get("expected"),
                "outcome": ev.outcome,
                "result": ev.result,
                "missing_facts": ev.missing_facts,
                "invalid_facts": ev.invalid_facts,
                "applied_rules": ev.applied_rules,
            }
        )
    return out


async def regression(
    proposed: Compiled,
    published: Compiled | None,
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Inputs whose result changes between the published version and the proposed one."""
    if published is None:
        return []
    changed = []
    for c in cases:
        facts = c.get("facts") or {}
        before = await evaluator.evaluate(
            published.content_hash,
            published.jdm,
            facts,
            required=published.required_facts,
            fact_types=published.fact_types,
            as_of=c.get("as_of"),
            want_trace=False,
        )
        after = await evaluator.evaluate(
            proposed.content_hash,
            proposed.jdm,
            facts,
            required=proposed.required_facts,
            fact_types=proposed.fact_types,
            as_of=c.get("as_of"),
            want_trace=False,
        )
        if before.outcome != after.outcome or not _same(before.result, after.result):
            changed.append(
                {
                    "source": c.get("source", "test"),
                    "name": c.get("name"),
                    "facts": facts,
                    "before": {
                        "outcome": before.outcome,
                        "result": before.result,
                        "rules": before.applied_rules,
                    },
                    "after": {
                        "outcome": after.outcome,
                        "result": after.result,
                        "rules": after.applied_rules,
                    },
                }
            )
    return changed
