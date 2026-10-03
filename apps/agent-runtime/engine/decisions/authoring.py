"""The rule builder's document, its validation, and its compilation to a ZEN decision model.

A rule document is what authors edit in the builder and table views. It
compiles to one ZEN decision table, so the builder, the table and the flow
editor all describe the same executable model.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

FACT_TYPES = ("string", "number", "boolean", "date", "list")
HIT_POLICIES = ("first", "collect")
PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,159}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ][0-9:.]+(Z|[+-]\d{2}:?\d{2})?)?$")
# facts the platform supplies, never the caller
AS_OF = "_as_of"
RESERVED = {AS_OF, "_rule"}

# operator -> (label, fact types it applies to, value shape)
OPERATORS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "eq": ("is", ("string", "number", "boolean", "date"), "one"),
    "neq": ("is not", ("string", "number", "boolean", "date"), "one"),
    "gt": ("is more than", ("number",), "one"),
    "gte": ("is at least", ("number",), "one"),
    "lt": ("is less than", ("number",), "one"),
    "lte": ("is at most", ("number",), "one"),
    "after": ("is after", ("date",), "one"),
    "on_or_after": ("is on or after", ("date",), "one"),
    "before": ("is before", ("date",), "one"),
    "on_or_before": ("is on or before", ("date",), "one"),
    "between": ("is between", ("number", "date"), "two"),
    "in": ("is one of", ("string", "number"), "many"),
    "not_in": ("is none of", ("string", "number"), "many"),
    "in_reference_set": ("is in reference set", ("string", "number"), "set"),
    "not_in_reference_set": ("is not in reference set", ("string", "number"), "set"),
    "contains": ("contains", ("string", "list"), "one"),
    "not_contains": ("does not contain", ("string", "list"), "one"),
    "starts_with": ("starts with", ("string",), "one"),
    "ends_with": ("ends with", ("string",), "one"),
    "is_true": ("is true", ("boolean",), "none"),
    "is_false": ("is false", ("boolean",), "none"),
    "is_set": ("has a value", FACT_TYPES, "none"),
    "is_not_set": ("has no value", FACT_TYPES, "none"),
}


@dataclass
class Problem:
    """One validation finding, pointing at the exact field."""

    path: str
    message: str
    severity: str = "error"  # error | warning
    code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
            "code": self.code,
        }


@dataclass
class Compiled:
    jdm: dict[str, Any]
    content_hash: str
    required_facts: list[str]
    fact_types: dict[str, str]
    reference_versions: dict[str, int] = field(default_factory=dict)


def canonical_json(obj: Any) -> str:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def content_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def empty_document() -> dict[str, Any]:
    return {
        "kind": "rules",
        "hit_policy": "first",
        "facts": [],
        "outputs": [],
        "rules": [],
    }


def _lit(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _date_lit(value: Any) -> str:
    return f"date({_lit(str(value))})"


def _ref(path: str) -> str:
    return path


def _valid_expr(expr: str) -> str | None:
    import zen

    err = zen.validate_expression(expr)
    if not err:
        return None
    if isinstance(err, dict):
        return str(err.get("source") or err.get("type") or err)
    return str(err)


def condition_expr(
    cond: dict[str, Any],
    fact_types: dict[str, str],
    reference_sets: dict[str, list[Any]],
) -> str:
    """One condition or group as a ZEN boolean expression."""
    if "all" in cond or "any" in cond:
        joiner = " and " if "all" in cond else " or "
        parts = [
            condition_expr(c, fact_types, reference_sets)
            for c in cond.get("all") or cond.get("any") or []
        ]
        parts = [p for p in parts if p]
        if not parts:
            return "true"
        inner = joiner.join(f"({p})" for p in parts)
        return f"not ({inner})" if cond.get("negate") else inner
    path = cond["fact"]
    op = cond["op"]
    t = fact_types.get(path, "string")
    f = _ref(path)
    v = cond.get("value")
    vs = cond.get("values") or []
    if t == "date":
        fv = f"date({f})"
        conv = _date_lit
    else:
        fv = f
        conv = _lit
    if op == "eq":
        return f"{fv} == {conv(v)}"
    if op == "neq":
        return f"{fv} != {conv(v)}"
    if op in ("gt", "after"):
        return f"{fv} > {conv(v)}"
    if op in ("gte", "on_or_after"):
        return f"{fv} >= {conv(v)}"
    if op in ("lt", "before"):
        return f"{fv} < {conv(v)}"
    if op in ("lte", "on_or_before"):
        return f"{fv} <= {conv(v)}"
    if op == "between":
        lo, hi = (vs + [None, None])[:2]
        return f"{fv} >= {conv(lo)} and {fv} <= {conv(hi)}"
    if op in ("in", "not_in"):
        expr = f"{f} in [{', '.join(_lit(x) for x in vs)}]"
        return expr if op == "in" else f"not ({expr})"
    if op in ("in_reference_set", "not_in_reference_set"):
        members = reference_sets.get(str(cond.get("set") or ""), [])
        expr = f"{f} in [{', '.join(_lit(x) for x in members)}]"
        return expr if op == "in_reference_set" else f"not ({expr})"
    if op in ("contains", "not_contains"):
        expr = f"contains({f}, {_lit(v)})"
        return expr if op == "contains" else f"not ({expr})"
    if op == "starts_with":
        return f"startsWith({f}, {_lit(v)})"
    if op == "ends_with":
        return f"endsWith({f}, {_lit(v)})"
    if op == "is_true":
        return f"{f} == true"
    if op == "is_false":
        return f"{f} == false"
    if op == "is_set":
        return f"{f} != null"
    if op == "is_not_set":
        return f"{f} == null"
    raise ValueError(f"unknown operator {op}")


def _validity_expr(rule: dict[str, Any]) -> str:
    parts = []
    if rule.get("valid_from"):
        parts.append(f"date({AS_OF}) >= {_date_lit(rule['valid_from'])}")
    if rule.get("valid_to"):
        parts.append(f"date({AS_OF}) < {_date_lit(rule['valid_to'])}")
    return " and ".join(parts)


def _flat_columns(rule: dict[str, Any]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Split a rule's top-level AND conditions by fact, leaving anything nested aside."""
    when = rule.get("when") or {}
    if "any" in when or when.get("negate"):
        return {}, [when] if when else []
    by_fact: dict[str, list[dict]] = {}
    rest: list[dict] = []
    for c in when.get("all") or []:
        if "fact" in c:
            by_fact.setdefault(c["fact"], []).append(c)
        else:
            rest.append(c)
    return by_fact, rest


def compile_document(
    doc: dict[str, Any],
    reference_sets: dict[str, list[Any]] | None = None,
    reference_versions: dict[str, int] | None = None,
) -> Compiled:
    """Compile a validated rule document into a ZEN decision model."""
    reference_sets = reference_sets or {}
    fact_types = {f["path"]: f.get("type", "string") for f in doc.get("facts") or []}
    fact_types[AS_OF] = "date"
    rules = [r for r in doc.get("rules") or [] if r.get("enabled", True)]

    columns: list[str] = []
    for r in rules:
        by_fact, _ = _flat_columns(r)
        for p in by_fact:
            if p not in columns:
                columns.append(p)
    labels = {f["path"]: f.get("label") or f["path"] for f in doc.get("facts") or []}
    inputs = [{"id": f"c{i}", "name": labels.get(p, p)} for i, p in enumerate(columns)]
    other_id = f"c{len(columns)}"
    inputs.append({"id": other_id, "name": "Other conditions"})
    valid_id = f"c{len(columns) + 1}"
    inputs.append({"id": valid_id, "name": "In force"})

    outputs = [
        {"id": f"o{i}", "name": o.get("label") or o["field"], "field": o["field"]}
        for i, o in enumerate(doc.get("outputs") or [])
    ]
    rule_out = f"o{len(outputs)}"
    outputs.append({"id": rule_out, "name": "Rule", "field": "_rule"})

    table_rules = []
    for idx, r in enumerate(rules):
        by_fact, rest = _flat_columns(r)
        row: dict[str, Any] = {
            "_id": r.get("id") or f"r{idx}",
            "_description": r.get("description") or "",
        }
        for i, p in enumerate(columns):
            conds = by_fact.get(p, [])
            row[f"c{i}"] = (
                " and ".join(
                    f"({condition_expr(c, fact_types, reference_sets)})" for c in conds
                )
                if conds
                else ""
            )
        row[other_id] = " and ".join(
            f"({condition_expr(c, fact_types, reference_sets)})" for c in rest
        )
        row[valid_id] = _validity_expr(r)
        then = r.get("then") or {}
        for i, o in enumerate(doc.get("outputs") or []):
            cell = then.get(o["field"])
            if cell is None:
                row[f"o{i}"] = ""
            elif isinstance(cell, dict) and "formula" in cell:
                row[f"o{i}"] = str(cell["formula"])
            else:
                row[f"o{i}"] = _lit(
                    cell.get("value") if isinstance(cell, dict) else cell
                )
        row[rule_out] = _lit(r.get("key") or row["_id"])
        table_rules.append(row)

    jdm = {
        "contentType": "application/vnd.gorules.decision",
        "nodes": [
            {
                "id": "request",
                "type": "inputNode",
                "name": "Facts",
                "position": {"x": 80, "y": 200},
            },
            {
                "id": "rules",
                "type": "decisionTableNode",
                "name": "Rules",
                "position": {"x": 380, "y": 200},
                "content": {
                    "hitPolicy": doc.get("hit_policy", "first"),
                    "inputs": inputs,
                    "outputs": outputs,
                    "rules": table_rules,
                },
            },
            {
                "id": "response",
                "type": "outputNode",
                "name": "Decision",
                "position": {"x": 760, "y": 200},
            },
        ],
        "edges": [
            {
                "id": "e-request-rules",
                "sourceId": "request",
                "targetId": "rules",
                "type": "edge",
            },
            {
                "id": "e-rules-response",
                "sourceId": "rules",
                "targetId": "response",
                "type": "edge",
            },
        ],
    }
    required = sorted(
        {f["path"] for f in doc.get("facts") or [] if f.get("required")}
        | {p for r in rules for p in r.get("requires") or []}
    )
    return Compiled(
        jdm=jdm,
        content_hash=content_hash(jdm),
        required_facts=required,
        fact_types={k: v for k, v in fact_types.items() if k != AS_OF},
        reference_versions=dict(reference_versions or {}),
    )


def _facts_in(cond: dict[str, Any]) -> list[str]:
    if "all" in cond or "any" in cond:
        return [
            p for c in cond.get("all") or cond.get("any") or [] for p in _facts_in(c)
        ]
    return [cond["fact"]] if cond.get("fact") else []


def _value_ok(t: str, v: Any) -> bool:
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "date":
        return isinstance(v, str) and bool(DATE_RE.match(v))
    if t == "list":
        return isinstance(v, (str, int, float))
    return isinstance(v, str)


def _check_condition(
    cond: Any,
    at: str,
    fact_types: dict[str, str],
    reference_sets: dict[str, list[Any]] | None,
    out: list[Problem],
    depth: int = 0,
) -> None:
    if not isinstance(cond, dict):
        out.append(
            Problem(at, "Each condition must be an object.", code="bad_condition")
        )
        return
    if "all" in cond or "any" in cond:
        if depth > 6:
            out.append(
                Problem(at, "Groups can nest at most six deep.", code="too_deep")
            )
            return
        key = "all" if "all" in cond else "any"
        items = cond.get(key)
        if not isinstance(items, list) or not items:
            out.append(
                Problem(
                    f"{at}/{key}",
                    "A group needs at least one condition.",
                    code="empty_group",
                )
            )
            return
        for i, c in enumerate(items):
            _check_condition(
                c, f"{at}/{key}/{i}", fact_types, reference_sets, out, depth + 1
            )
        return
    path = cond.get("fact")
    op = cond.get("op")
    if not path:
        out.append(
            Problem(
                f"{at}/fact", "Pick the fact this condition checks.", code="no_fact"
            )
        )
        return
    if not PATH_RE.match(str(path)):
        out.append(
            Problem(
                f"{at}/fact",
                f"{path} is not a valid fact path. Use letters, digits and _ separated by dots.",
                code="bad_path",
            )
        )
        return
    if path not in fact_types:
        out.append(
            Problem(
                f"{at}/fact",
                f"{path} is not one of this decision's facts. Add it to the facts list.",
                code="unknown_fact",
            )
        )
        return
    t = fact_types[path]
    if op not in OPERATORS:
        out.append(Problem(f"{at}/op", "Pick a comparison.", code="no_op"))
        return
    label, types, shape = OPERATORS[op]
    if t not in types:
        out.append(
            Problem(
                f"{at}/op", f"'{label}' does not apply to a {t} fact.", code="op_type"
            )
        )
        return
    if shape == "one":
        v = cond.get("value")
        if v is None or v == "":
            out.append(Problem(f"{at}/value", "Enter a value.", code="no_value"))
        elif not _value_ok(t, v):
            want = {
                "number": "a number",
                "boolean": "true or false",
                "date": "a date like 2026-01-01",
                "list": "a value",
                "string": "text",
            }[t]
            out.append(
                Problem(
                    f"{at}/value",
                    f"{path} is a {t} fact, so the value must be {want}.",
                    code="value_type",
                )
            )
    elif shape == "two":
        vs = cond.get("values") or []
        if len(vs) != 2 or any(x is None or x == "" for x in vs):
            out.append(
                Problem(
                    f"{at}/values", "Enter both ends of the range.", code="no_value"
                )
            )
        elif not all(_value_ok(t, x) for x in vs):
            out.append(
                Problem(
                    f"{at}/values",
                    f"Both ends must be {'numbers' if t == 'number' else 'dates like 2026-01-01'}.",
                    code="value_type",
                )
            )
        elif str(vs[0]) > str(vs[1]) if t == "date" else vs[0] > vs[1]:
            out.append(
                Problem(
                    f"{at}/values",
                    "The lower end is above the upper end.",
                    code="range_order",
                )
            )
    elif shape == "many":
        vs = cond.get("values") or []
        if not vs:
            out.append(
                Problem(f"{at}/values", "Add at least one value.", code="no_value")
            )
        elif not all(_value_ok(t, x) for x in vs):
            out.append(
                Problem(
                    f"{at}/values",
                    f"Every value must match the {t} type of {path}.",
                    code="value_type",
                )
            )
    elif shape == "set":
        name = cond.get("set")
        if not name:
            out.append(Problem(f"{at}/set", "Pick a reference set.", code="no_set"))
        elif reference_sets is not None and name not in reference_sets:
            out.append(
                Problem(
                    f"{at}/set",
                    f"There is no reference set called {name}.",
                    code="unknown_set",
                )
            )


def validate_document(
    doc: Any, reference_sets: dict[str, list[Any]] | None = None
) -> list[Problem]:
    """Every problem in a rule document, each pointing at the field to fix."""
    out: list[Problem] = []
    if not isinstance(doc, dict):
        return [Problem("", "The rules must be an object.", code="bad_document")]
    if doc.get("hit_policy", "first") not in HIT_POLICIES:
        out.append(
            Problem(
                "/hit_policy",
                "Choose first match or all matches.",
                code="bad_hit_policy",
            )
        )

    fact_types: dict[str, str] = {}
    for i, f in enumerate(doc.get("facts") or []):
        p = f.get("path") if isinstance(f, dict) else None
        if not p or not PATH_RE.match(str(p)):
            out.append(
                Problem(
                    f"/facts/{i}/path",
                    "A fact needs a path such as shipment.postcode.",
                    code="bad_path",
                )
            )
            continue
        if p in RESERVED:
            out.append(
                Problem(
                    f"/facts/{i}/path",
                    f"{p} is reserved by the platform.",
                    code="reserved",
                )
            )
            continue
        if p in fact_types:
            out.append(
                Problem(
                    f"/facts/{i}/path", f"{p} is listed twice.", code="duplicate_fact"
                )
            )
        t = f.get("type", "string")
        if t not in FACT_TYPES:
            out.append(
                Problem(
                    f"/facts/{i}/type",
                    f"Type must be one of {', '.join(FACT_TYPES)}.",
                    code="bad_type",
                )
            )
            t = "string"
        fact_types[p] = t

    out_fields: set[str] = set()
    for i, o in enumerate(doc.get("outputs") or []):
        fld = o.get("field") if isinstance(o, dict) else None
        if not fld or not PATH_RE.match(str(fld)):
            out.append(
                Problem(
                    f"/outputs/{i}/field",
                    "An outcome needs a name such as obligation.",
                    code="bad_output",
                )
            )
            continue
        if fld in RESERVED or fld.startswith("_"):
            out.append(
                Problem(
                    f"/outputs/{i}/field",
                    "Outcome names cannot start with _.",
                    code="reserved",
                )
            )
        if fld in out_fields:
            out.append(
                Problem(
                    f"/outputs/{i}/field",
                    f"{fld} is listed twice.",
                    code="duplicate_output",
                )
            )
        out_fields.add(fld)
    if not out_fields:
        out.append(
            Problem(
                "/outputs",
                "Add at least one outcome, for example obligation.",
                code="no_outputs",
            )
        )

    rules = doc.get("rules") or []
    if not rules:
        out.append(
            Problem(
                "/rules", "Add at least one rule.", severity="warning", code="no_rules"
            )
        )
    keys: dict[str, int] = {}
    for i, r in enumerate(rules):
        at = f"/rules/{i}"
        if not isinstance(r, dict):
            out.append(Problem(at, "Each rule must be an object.", code="bad_rule"))
            continue
        k = r.get("key")
        if k:
            if not KEY_RE.match(str(k)):
                out.append(
                    Problem(
                        f"{at}/key",
                        "Use lowercase letters, digits, dots, dashes or underscores.",
                        code="bad_key",
                    )
                )
            elif k in keys:
                out.append(
                    Problem(
                        f"{at}/key",
                        f"Rule {keys[k] + 1} already uses this key.",
                        code="duplicate_key",
                    )
                )
            else:
                keys[k] = i
        when = r.get("when")
        # an empty top-level group is a catch-all rule, which is allowed
        if when and not (
            set(when) <= {"all", "any"} and not (when.get("all") or when.get("any"))
        ):
            _check_condition(when, f"{at}/when", fact_types, reference_sets, out)
        then = r.get("then") or {}
        if not then:
            out.append(
                Problem(f"{at}/then", "Say what this rule decides.", code="no_then")
            )
        for fld, cell in then.items():
            if fld not in out_fields:
                out.append(
                    Problem(
                        f"{at}/then/{fld}",
                        f"{fld} is not one of the outcomes. Add it to the outcomes list.",
                        code="unknown_output",
                    )
                )
                continue
            if isinstance(cell, dict) and "formula" in cell:
                err = _valid_expr(str(cell["formula"]))
                if err:
                    out.append(
                        Problem(
                            f"{at}/then/{fld}/formula",
                            f"The formula does not parse: {err}",
                            code="bad_formula",
                        )
                    )
                else:
                    unknown = [
                        name
                        for name in re.findall(
                            r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+",
                            str(cell["formula"]),
                        )
                        if name not in fact_types
                    ]
                    if unknown:
                        out.append(
                            Problem(
                                f"{at}/then/{fld}/formula",
                                f"{', '.join(sorted(set(unknown)))} is not one of this decision's facts.",
                                code="unknown_fact",
                            )
                        )
        for p in r.get("requires") or []:
            if p not in fact_types:
                out.append(
                    Problem(
                        f"{at}/requires",
                        f"{p} is not one of this decision's facts.",
                        code="unknown_fact",
                    )
                )
        vf, vt = r.get("valid_from"), r.get("valid_to")
        for name, v in (("valid_from", vf), ("valid_to", vt)):
            if v and not DATE_RE.match(str(v)):
                out.append(
                    Problem(
                        f"{at}/{name}", "Use a date like 2026-01-01.", code="bad_date"
                    )
                )
        if (
            vf
            and vt
            and DATE_RE.match(str(vf))
            and DATE_RE.match(str(vt))
            and str(vf) >= str(vt)
        ):
            out.append(
                Problem(
                    f"{at}/valid_to",
                    "The end must be after the start.",
                    code="range_order",
                )
            )
    return out


def has_errors(problems: list[Problem]) -> bool:
    return any(p.severity == "error" for p in problems)


def referenced_sets(doc: dict[str, Any]) -> set[str]:
    out: set[str] = set()

    def walk(c: Any) -> None:
        if isinstance(c, dict):
            if "all" in c or "any" in c:
                for x in c.get("all") or c.get("any") or []:
                    walk(x)
            elif c.get("op") in ("in_reference_set", "not_in_reference_set") and c.get(
                "set"
            ):
                out.add(str(c["set"]))

    for r in doc.get("rules") or []:
        walk(r.get("when"))
    return out


def facts_used(doc: dict[str, Any]) -> set[str]:
    return {p for r in doc.get("rules") or [] for p in _facts_in(r.get("when") or {})}


def normalize(doc: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and give every rule an id, without changing meaning."""
    d = copy.deepcopy(doc) if doc else empty_document()
    d.setdefault("kind", "rules")
    d.setdefault("hit_policy", "first")
    d.setdefault("facts", [])
    d.setdefault("outputs", [])
    d.setdefault("rules", [])
    for i, r in enumerate(d["rules"]):
        r.setdefault("id", f"r{i + 1}")
        r.setdefault("enabled", True)
        r.setdefault("when", {"all": []})
        r.setdefault("then", {})
    return d
