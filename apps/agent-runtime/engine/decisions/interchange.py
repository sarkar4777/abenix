"""Typed JSON rules in the ruleKey / requiresFacts / when / then shape, to and from rule documents.

Conditions use the form {"op": [{"fact": "path"}, value]} inside "all" or
"any" groups, with "not" for negation. Keys the builder does not model are
carried in each rule's meta, so an export reproduces what was imported.
"""

from __future__ import annotations

import copy
from typing import Any

from engine.decisions.authoring import (
    DATE_RE,
    HIT_POLICIES,
    effective_output_type,
    empty_document,
    normalize,
)

FILE_FORMAT = "abenix-decision-v1"

# interchange operator -> builder operator, by fact type where it differs
_IN = {
    "eq": "eq",
    "==": "eq",
    "equals": "eq",
    "neq": "neq",
    "!=": "neq",
    "notEquals": "neq",
    "in": "in",
    "notIn": "not_in",
    "inReferenceSet": "in_reference_set",
    "notInReferenceSet": "not_in_reference_set",
    "contains": "contains",
    "notContains": "not_contains",
    "startsWith": "starts_with",
    "endsWith": "ends_with",
    "between": "between",
    "isSet": "is_set",
    "exists": "is_set",
    "isNotSet": "is_not_set",
    "isTrue": "is_true",
    "isFalse": "is_false",
}
_ORDER_NUMBER = {
    "gt": "gt",
    ">": "gt",
    "gte": "gte",
    ">=": "gte",
    "lt": "lt",
    "<": "lt",
    "lte": "lte",
    "<=": "lte",
}
_ORDER_DATE = {
    "gt": "after",
    ">": "after",
    "gte": "on_or_after",
    ">=": "on_or_after",
    "lt": "before",
    "<": "before",
    "lte": "on_or_before",
    "<=": "on_or_before",
}
_OUT = {
    "eq": "eq",
    "neq": "neq",
    "in": "in",
    "not_in": "notIn",
    "in_reference_set": "inReferenceSet",
    "not_in_reference_set": "notInReferenceSet",
    "contains": "contains",
    "not_contains": "notContains",
    "starts_with": "startsWith",
    "ends_with": "endsWith",
    "between": "between",
    "is_set": "isSet",
    "is_not_set": "isNotSet",
    "is_true": "isTrue",
    "is_false": "isFalse",
    "gt": "gt",
    "gte": "gte",
    "lt": "lt",
    "lte": "lte",
    "after": "gt",
    "on_or_after": "gte",
    "before": "lt",
    "on_or_before": "lte",
}
_RULE_KEYS = {
    "ruleKey",
    "requiresFacts",
    "when",
    "then",
    "provenance",
    "validFrom",
    "validTo",
    "description",
    "enabled",
}
_FORMULA_KEYS = ("formula", "expression", "expr")


class InterchangeError(ValueError):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


def _infer_type(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, list):
        return _infer_type(v[0]) if v else "string"
    if isinstance(v, str) and DATE_RE.match(v):
        return "date"
    return "string"


_NUMBER_HINTS = (
    "tonnes",
    "tons",
    "mass",
    "weight",
    "amount",
    "price",
    "cost",
    "rate",
    "count",
    "qty",
    "quantity",
    "value",
    "volume",
    "percent",
    "share",
    "emissions",
)
_DATE_HINTS = ("date", "day", "_at", "since", "until")


def _type_from_name(path: str) -> str:
    leaf = path.rsplit(".", 1)[-1].lower()
    if any(leaf.endswith(h) or leaf.startswith(h) for h in _DATE_HINTS):
        return "date"
    if any(h in leaf for h in _NUMBER_HINTS):
        return "number"
    return "string"


def _cond_in(c: Any, at: str, types: dict[str, str]) -> dict[str, Any]:
    if not isinstance(c, dict) or len(c) != 1:
        raise InterchangeError(
            at, "each condition must be an object with exactly one operator"
        )
    ((op, args),) = c.items()
    if op in ("all", "any"):
        if not isinstance(args, list):
            raise InterchangeError(at, f"{op} must hold a list of conditions")
        return {op: [_cond_in(x, f"{at}/{op}/{i}", types) for i, x in enumerate(args)]}
    if op == "not":
        inner = _cond_in(args, f"{at}/not", types)
        group = inner if ("all" in inner or "any" in inner) else {"all": [inner]}
        return {**group, "negate": True}
    if (
        not isinstance(args, list)
        or not args
        or not isinstance(args[0], dict)
        or "fact" not in args[0]
    ):
        raise InterchangeError(
            at, f'{op} needs a list starting with {{"fact": "path"}}'
        )
    path = str(args[0]["fact"])
    rest = args[1:]
    sample = rest[0] if rest else None
    if path not in types and sample is not None:
        types[path] = _infer_type(sample)
    t = types.get(path, "string")
    if op in _ORDER_NUMBER:
        bop = (_ORDER_DATE if t == "date" else _ORDER_NUMBER)[op]
        return {"fact": path, "op": bop, "value": sample}
    if op not in _IN:
        raise InterchangeError(at, f"{op} is not a supported operator")
    bop = _IN[op]
    if bop in ("in", "not_in"):
        vals = sample if isinstance(sample, list) else rest
        return {"fact": path, "op": bop, "values": list(vals)}
    if bop in ("in_reference_set", "not_in_reference_set"):
        return {"fact": path, "op": bop, "set": str(sample)}
    if bop == "between":
        vals = sample if isinstance(sample, list) else rest
        return {"fact": path, "op": bop, "values": list(vals)[:2]}
    if bop in ("is_set", "is_not_set", "is_true", "is_false"):
        if bop in ("is_true", "is_false"):
            types[path] = "boolean"
        return {"fact": path, "op": bop}
    return {"fact": path, "op": bop, "value": sample}


def _cond_out(c: dict[str, Any]) -> dict[str, Any]:
    if "all" in c or "any" in c:
        key = "all" if "all" in c else "any"
        group = {key: [_cond_out(x) for x in c[key]]}
        if c.get("negate"):
            items = group[key]
            return {"not": items[0] if key == "all" and len(items) == 1 else group}
        return group
    fact = {"fact": c["fact"]}
    op = _OUT[c["op"]]
    bop = c["op"]
    if bop in ("in", "not_in", "between"):
        return {op: [fact, list(c.get("values") or [])]}
    if bop in ("in_reference_set", "not_in_reference_set"):
        return {op: [fact, c.get("set")]}
    if bop in ("is_set", "is_not_set", "is_true", "is_false"):
        return {op: [fact]}
    return {op: [fact, c.get("value")]}


def _then_in(then: Any, at: str) -> dict[str, Any]:
    if not isinstance(then, dict) or not then:
        raise InterchangeError(at, "then must be an object naming at least one outcome")
    out: dict[str, Any] = {}
    for k, v in then.items():
        if isinstance(v, dict) and len(v) == 1 and next(iter(v)) in _FORMULA_KEYS:
            out[k] = {"formula": str(next(iter(v.values()))), "_as": next(iter(v))}
        else:
            out[k] = {"value": v}
    return out


def _then_out(then: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, cell in then.items():
        if isinstance(cell, dict) and "formula" in cell:
            out[k] = {cell.get("_as", "formula"): cell["formula"]}
        elif isinstance(cell, dict) and "value" in cell:
            out[k] = cell["value"]
        else:
            out[k] = cell
    return out


def _rules_of(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("rules"), list):
        return payload["rules"]
    if isinstance(payload, dict) and "ruleKey" in payload:
        return [payload]
    raise InterchangeError(
        "",
        "expected a rule with ruleKey, a list of rules, or an object with a rules list",
    )


def import_rules(payload: Any, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Turn typed JSON rules into a rule document, merging into base when given."""
    doc = normalize(base or {})
    doc["hit_policy"] = doc.get("hit_policy") or "collect"
    types = {f["path"]: f.get("type", "string") for f in doc["facts"]}
    required: set[str] = {f["path"] for f in doc["facts"] if f.get("required")}
    outputs = {o["field"] for o in doc["outputs"]}
    existing = {r.get("key"): i for i, r in enumerate(doc["rules"]) if r.get("key")}
    for i, raw in enumerate(_rules_of(payload)):
        at = (
            f"/rules/{i}"
            if not (isinstance(payload, dict) and "ruleKey" in payload)
            else ""
        )
        if not isinstance(raw, dict) or not raw.get("ruleKey"):
            raise InterchangeError(at, "each rule needs a ruleKey")
        for p in raw.get("requiresFacts") or []:
            required.add(str(p))
        when = raw.get("when")
        cond = _cond_in(when, f"{at}/when", types) if when else {"all": []}
        if "fact" in cond:
            cond = {"all": [cond]}
        then = _then_in(raw.get("then"), f"{at}/then")
        for k, cell in then.items():
            outputs.add(k)
        rule = {
            "id": f"r{len(doc['rules']) + 1}",
            "key": str(raw["ruleKey"]),
            "description": raw.get("description") or "",
            "enabled": raw.get("enabled") is not False,
            "requires": [str(p) for p in raw.get("requiresFacts") or []],
            "when": cond,
            "then": then,
            "valid_from": raw.get("validFrom"),
            "valid_to": raw.get("validTo"),
            "provenance": (
                copy.deepcopy(raw.get("provenance"))
                if raw.get("provenance") is not None
                else None
            ),
            "meta": {
                k: copy.deepcopy(v) for k, v in raw.items() if k not in _RULE_KEYS
            },
        }
        if rule["key"] in existing:
            rule["id"] = doc["rules"][existing[rule["key"]]]["id"]
            doc["rules"][existing[rule["key"]]] = rule
        else:
            existing[rule["key"]] = len(doc["rules"])
            doc["rules"].append(rule)
    for p in required:
        types.setdefault(p, _type_from_name(p))
    known = {f["path"] for f in doc["facts"]}
    for p, t in types.items():
        if p not in known:
            doc["facts"].append(
                {"path": p, "type": t, "label": p, "required": p in required}
            )
        else:
            for f in doc["facts"]:
                if f["path"] == p and p in required:
                    f["required"] = True
    have = {o["field"] for o in doc["outputs"]}
    for o in sorted(outputs - have):
        out = {"field": o, "label": o}
        out["type"] = effective_output_type(doc, out) or "string"
        doc["outputs"].append(out)
    return doc


def export_rules(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The rule document as typed JSON rules, one per rule, in order."""
    out = []
    for r in doc.get("rules") or []:
        item: dict[str, Any] = {"ruleKey": r.get("key") or r.get("id")}
        meta = r.get("meta") or {}
        item.update({k: v for k, v in meta.items()})
        if r.get("description"):
            item["description"] = r["description"]
        if r.get("enabled") is False:
            item["enabled"] = False
        if r.get("valid_from"):
            item["validFrom"] = r["valid_from"]
        if r.get("valid_to"):
            item["validTo"] = r["valid_to"]
        if r.get("requires"):
            item["requiresFacts"] = list(r["requires"])
        when = r.get("when") or {"all": []}
        if when.get("all") or when.get("any"):
            item["when"] = _cond_out(when)
        item["then"] = _then_out(r.get("then") or {})
        if r.get("provenance") is not None:
            item["provenance"] = r["provenance"]
        out.append(item)
    return out


TEST_OUTCOMES = ("decided", "no_match", "missing_facts", "invalid_facts")


def export_file(
    model: dict[str, Any],
    doc: dict[str, Any] | None,
    content: dict[str, Any] | None,
    tests: list[dict[str, Any]],
    version: int | None,
) -> dict[str, Any]:
    """A whole decision as one JSON file that read_file takes back."""
    out: dict[str, Any] = {
        "format": FILE_FORMAT,
        "key": model.get("key"),
        "name": model.get("name"),
        "description": model.get("description") or "",
        "risk_tier": model.get("risk_tier") or "low",
        "hit_policy": (doc or {}).get("hit_policy") or "first",
        "tags": list(model.get("tags") or []),
        "facts": copy.deepcopy((doc or {}).get("facts") or []),
        "outcomes": copy.deepcopy((doc or {}).get("outputs") or []),
        "rules": export_rules(doc) if doc is not None else [],
        "tests": [
            {
                "name": t.get("name"),
                "facts": t.get("facts") or {},
                "expected": t.get("expected"),
                "expected_outcome": t.get("expected_outcome") or "decided",
                "match": t.get("match") or "exact",
                "as_of": t.get("as_of") or None,
            }
            for t in tests
        ],
        "exported_from_version": version,
    }
    if doc is None and content is not None:
        # a version built in the flow view has no rules list, its flow travels instead
        out["content"] = copy.deepcopy(content)
    return out


def _merge_by(
    declared: Any, inferred: list[dict[str, Any]], key: str, at: str
) -> list[dict[str, Any]]:
    if declared is None:
        return inferred
    if not isinstance(declared, list):
        raise InterchangeError(at, "must be a list")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(declared):
        if not isinstance(item, dict) or not item.get(key):
            raise InterchangeError(f"{at}/{i}", f"each entry needs a {key}")
        out.append(copy.deepcopy(item))
        seen.add(str(item[key]))
    out.extend(x for x in inferred if str(x.get(key)) not in seen)
    return out


def _tests_in(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise InterchangeError("/tests", "tests must be a list")
    out = []
    for i, t in enumerate(raw):
        at = f"/tests/{i}"
        if not isinstance(t, dict) or not str(t.get("name") or "").strip():
            raise InterchangeError(at, "each test needs a name")
        facts = t.get("facts") or {}
        if not isinstance(facts, dict):
            raise InterchangeError(f"{at}/facts", "facts must be an object")
        outcome = t.get("expected_outcome") or "decided"
        if outcome not in TEST_OUTCOMES:
            raise InterchangeError(
                f"{at}/expected_outcome", f"must be one of {', '.join(TEST_OUTCOMES)}"
            )
        match = t.get("match") or "exact"
        if match not in ("exact", "subset"):
            raise InterchangeError(f"{at}/match", "must be exact or subset")
        as_of = t.get("as_of") or None
        if as_of is not None and not DATE_RE.match(str(as_of)):
            raise InterchangeError(f"{at}/as_of", "use a date like 2026-01-01")
        out.append(
            {
                "name": str(t["name"]).strip()[:255],
                "facts": facts,
                "expected": t.get("expected"),
                "expected_outcome": outcome,
                "match": match,
                "as_of": as_of,
            }
        )
    return out


def read_file(payload: Any) -> dict[str, Any]:
    """A decision file, ours or the plain {key, name, rules, tests} shape, as parts ready to save."""
    if (
        isinstance(payload, dict)
        and isinstance(payload.get("data"), dict)
        and "rules" not in payload
        and "key" not in payload
    ):
        payload = payload["data"]
    if not isinstance(payload, dict):
        raise InterchangeError("", "the file must be a JSON object")
    fmt = payload.get("format")
    if fmt not in (None, FILE_FORMAT, "rules"):
        raise InterchangeError("/format", f"{fmt} is not a decision file this can read")
    rules = payload.get("rules")
    content = payload.get("content")
    has_flow = (
        isinstance(content, dict)
        and content.get("nodes") is not None
        and content.get("edges") is not None
    )
    if rules is None and not has_flow:
        raise InterchangeError("/rules", "the file has no rules")
    if rules is not None and not isinstance(rules, list):
        raise InterchangeError("/rules", "rules must be a list")
    doc: dict[str, Any] | None = None
    if rules or not has_flow:
        doc = import_rules({"rules": rules or []}) if rules else empty_document()
        doc = normalize(doc)
        doc["facts"] = _merge_by(payload.get("facts"), doc["facts"], "path", "/facts")
        doc["outputs"] = _merge_by(
            payload.get("outcomes", payload.get("outputs")),
            doc["outputs"],
            "field",
            "/outcomes",
        )
        hp = payload.get("hit_policy")
        if hp is not None:
            if hp not in HIT_POLICIES:
                raise InterchangeError(
                    "/hit_policy", f"must be one of {', '.join(HIT_POLICIES)}"
                )
            doc["hit_policy"] = hp
    tags = payload.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise InterchangeError("/tags", "tags must be a list of words")
    return {
        "key": (str(payload["key"]).strip() if payload.get("key") else None),
        "name": str(payload.get("name") or "").strip() or None,
        "description": str(payload.get("description") or ""),
        "risk_tier": payload.get("risk_tier"),
        "tags": tags,
        "doc": doc,
        "content": copy.deepcopy(content) if doc is None else None,
        "tests": _tests_in(payload.get("tests")),
    }
