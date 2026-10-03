"""Evaluation assertions: pure checks of one run's output, tool calls, cost and duration."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

MAX_SCAN = 200_000
DEFAULT_JUDGE_MODEL = "claude-haiku-4-5-20251001"
SOURCE_TOOLS = (
    "knowledge_search",
    "vector_search",
    "web_search",
    "tavily_search",
    "academic_search",
    "persona_rag",
    "news_feed",
    "edgar_filings",
    "ferc_elibrary",
)
DEFAULT_CITATION = r"https?://\S+|\[\d+\]|\[source[^\]]*\]|\bsources?:"

_FENCE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_MISSING = object()

# what the assertion builder offers, and what validate() enforces
TYPES: dict[str, dict[str, Any]] = {
    "json_path_equals": {
        "label": "JSON field equals",
        "help": "Reads the output as JSON, fenced or not, and compares one field.",
        "fields": [
            {"key": "path", "label": "Path", "kind": "path", "required": True},
            {
                "key": "value",
                "label": "Expected value",
                "kind": "json",
                "required": True,
            },
            {"key": "tolerance", "label": "Number tolerance", "kind": "number"},
            {"key": "ignore_case", "label": "Ignore case", "kind": "bool"},
        ],
    },
    "json_path_contains": {
        "label": "JSON field contains",
        "help": "The field's text includes the value, its list holds it, or its object has it as a key.",
        "fields": [
            {"key": "path", "label": "Path", "kind": "path", "required": True},
            {"key": "value", "label": "Value", "kind": "json", "required": True},
            {"key": "ignore_case", "label": "Ignore case", "kind": "bool"},
        ],
    },
    "regex": {
        "label": "Matches a pattern",
        "help": "A regular expression searched anywhere in the output.",
        "fields": [
            {"key": "pattern", "label": "Pattern", "kind": "regex", "required": True},
            {
                "key": "mode",
                "label": "Expect",
                "kind": "select",
                "options": ["match", "no_match"],
            },
            {"key": "ignore_case", "label": "Ignore case", "kind": "bool"},
        ],
    },
    "contains": {
        "label": "Output contains",
        "help": "The output includes this text.",
        "fields": [
            {"key": "value", "label": "Text", "kind": "text", "required": True},
            {"key": "case_sensitive", "label": "Case sensitive", "kind": "bool"},
        ],
    },
    "not_contains": {
        "label": "Output does not contain",
        "help": "The output never mentions this text.",
        "fields": [
            {"key": "value", "label": "Text", "kind": "text", "required": True},
            {"key": "case_sensitive", "label": "Case sensitive", "kind": "bool"},
        ],
    },
    "schema_valid": {
        "label": "Matches a JSON schema",
        "help": "The output parses as JSON and validates against the schema.",
        "fields": [
            {
                "key": "schema",
                "label": "JSON schema",
                "kind": "schema",
                "required": True,
            }
        ],
    },
    "required_tools_called": {
        "label": "Tools were called",
        "help": "The run called these tools. Partial credit for some of them.",
        "fields": [
            {"key": "tools", "label": "Tools", "kind": "list", "required": True},
            {
                "key": "mode",
                "label": "Needs",
                "kind": "select",
                "options": ["all", "any"],
            },
        ],
    },
    "max_cost": {
        "label": "Costs at most",
        "help": "The run's model and tool cost in US dollars.",
        "fields": [
            {
                "key": "max",
                "label": "Max cost (USD)",
                "kind": "number",
                "required": True,
            }
        ],
    },
    "max_duration_ms": {
        "label": "Finishes within",
        "help": "Wall-clock time of the run.",
        "fields": [
            {
                "key": "max",
                "label": "Max duration (ms)",
                "kind": "number",
                "required": True,
            }
        ],
    },
    "cited_sources_present": {
        "label": "Cites its sources",
        "help": "The output carries citations or links, or the run used a source tool such as knowledge_search.",
        "fields": [
            {"key": "pattern", "label": "Citation pattern", "kind": "regex"},
            {"key": "min_count", "label": "At least", "kind": "number"},
            {
                "key": "accept_source_tools",
                "label": "A source tool call counts",
                "kind": "bool",
            },
        ],
    },
    "judge": {
        "label": "Judged by a model",
        "help": "A model scores the output 0 to 1 against your rubric. Not deterministic, use it alongside exact checks.",
        "deterministic": False,
        "fields": [
            {"key": "rubric", "label": "Rubric", "kind": "textarea", "required": True},
            {"key": "min_score", "label": "Pass at score", "kind": "number"},
            {"key": "model", "label": "Judge model", "kind": "model"},
        ],
    },
}


@dataclass
class Observed:
    """What one run produced, the only thing assertions look at."""

    output: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    cost: float = 0.0
    duration_ms: int | None = None
    status: str = "completed"
    input_message: str = ""


@dataclass
class CaseOutcome:
    passed: bool
    score: float
    results: list[dict[str, Any]]


JudgeFn = Callable[[str, str, str, str], Awaitable[tuple[float, str, float]]]


def parse_output_json(text: Any) -> Any:
    """The output as JSON, tolerant of code fences and prose around the object. _MISSING when there is none."""
    if isinstance(text, (dict, list)):
        return text
    if not isinstance(text, str) or not text.strip():
        return _MISSING
    m = _FENCE.search(text)
    candidate = (m.group(1) if m else text).strip()
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        if start < 0:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(candidate)):
            ch = candidate[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(candidate[start : i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break
    return _MISSING


_TOKEN = re.compile(r"\[(\*|-?\d+)\]|\[['\"]([^'\"]+)['\"]\]|([^.\[\]]+)")


def path_tokens(path: str) -> list[str | int]:
    """a.b[0].c, $.a.b, items[*].name and ['odd key'] into steps. ValueError when it cannot be read."""
    p = (path or "").strip()
    if p.startswith("$"):
        p = p[1:]
    p = p.lstrip(".")
    if not p:
        return []
    out: list[str | int] = []
    pos = 0
    while pos < len(p):
        if p[pos] == ".":
            pos += 1
            if pos >= len(p) or p[pos] == ".":
                raise ValueError("a path step is empty")
            continue
        m = _TOKEN.match(p, pos)
        if not m or m.end() == pos:
            raise ValueError(f"cannot read the path at {p[pos:pos + 10]!r}")
        idx, quoted, name = m.groups()
        if idx is not None:
            out.append("*" if idx == "*" else int(idx))
        elif quoted is not None:
            out.append(quoted)
        else:
            out.append(name.strip())
        pos = m.end()
    return out


def json_path_values(data: Any, path: str) -> list[Any]:
    """Every value the path reaches. A wildcard fans out, a missing step yields nothing."""
    current = [data]
    for tok in path_tokens(path):
        nxt: list[Any] = []
        for node in current:
            if tok == "*":
                if isinstance(node, list):
                    nxt.extend(node)
                elif isinstance(node, dict):
                    nxt.extend(node.values())
            elif isinstance(tok, int):
                if isinstance(node, list) and -len(node) <= tok < len(node):
                    nxt.append(node[tok])
                elif isinstance(node, dict) and str(tok) in node:
                    nxt.append(node[str(tok)])
            elif isinstance(node, dict) and tok in node:
                nxt.append(node[tok])
        current = nxt
        if not current:
            break
    return current


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def _equal(actual: Any, expected: Any, tolerance: float, ignore_case: bool) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual == expected and type(actual) is type(expected)
    a, e = _num(actual), _num(expected)
    both_text = isinstance(actual, str) and isinstance(expected, str)
    if a is not None and e is not None and (not both_text or tolerance > 0):
        return math.isclose(a, e, rel_tol=0, abs_tol=max(tolerance, 1e-9))
    if both_text:
        if ignore_case:
            return actual.strip().lower() == expected.strip().lower()
        return actual.strip() == expected.strip()
    return actual == expected


def _contains(actual: Any, value: Any, ignore_case: bool) -> bool:
    if isinstance(actual, str):
        needle = value if isinstance(value, str) else json.dumps(value)
        return needle.lower() in actual.lower() if ignore_case else needle in actual
    if isinstance(actual, list):
        return any(_equal(x, value, 0.0, ignore_case) for x in actual)
    if isinstance(actual, dict):
        return isinstance(value, str) and value in actual
    return False


def _short(v: Any, n: int = 80) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return s if len(s) <= n else s[: n - 1] + "…"


def _flags(a: dict[str, Any]) -> int:
    return re.IGNORECASE if a.get("ignore_case") else 0


def tool_names(tool_calls: list[Any]) -> list[str]:
    out: list[str] = []
    for t in tool_calls or []:
        if isinstance(t, dict):
            n = t.get("name") or t.get("tool") or t.get("tool_name")
            if n:
                out.append(str(n))
        elif isinstance(t, str):
            out.append(t)
    return out


def validate(a: Any) -> list[str]:
    """Problems with one assertion, worded for the field they belong to. Empty when it is fine."""
    if not isinstance(a, dict):
        return ["An assertion must be an object with a type."]
    t = a.get("type")
    spec = TYPES.get(t or "")
    if spec is None:
        return [f"Pick an assertion type, one of {', '.join(TYPES)}."]
    problems: list[str] = []
    for f in spec["fields"]:
        k = f["key"]
        v = a.get(k)
        missing = v is None or (isinstance(v, str) and not v.strip()) or v == []
        if f.get("required") and missing and not (f["kind"] == "json" and k in a):
            problems.append(f"{f['label']} is required.")
            continue
        if missing:
            continue
        kind = f["kind"]
        if kind == "path":
            try:
                path_tokens(str(v))
            except ValueError as e:
                problems.append(f"{f['label']}: {e}.")
        elif kind == "regex":
            try:
                re.compile(str(v))
            except re.error as e:
                problems.append(f"{f['label']} is not a valid pattern: {e}.")
        elif kind == "number":
            n = _num(v)
            if n is None or n < 0:
                problems.append(f"{f['label']} must be a number of zero or more.")
        elif kind == "list":
            if not isinstance(v, list) or not all(
                isinstance(x, str) and x.strip() for x in v
            ):
                problems.append(f"{f['label']} must be a list of names.")
        elif kind == "select":
            if v not in f["options"]:
                problems.append(
                    f"{f['label']} must be one of {', '.join(f['options'])}."
                )
        elif kind == "schema":
            problems.extend(_schema_problems(v))
    if t == "judge" and a.get("min_score") is not None:
        n = _num(a.get("min_score"))
        if n is None or not 0 <= n <= 1:
            problems.append("Pass at score must be between 0 and 1.")
    if t == "max_duration_ms" and not problems and _num(a.get("max")) == 0:
        problems.append("Max duration must be above zero.")
    return problems


def _schema_problems(schema: Any) -> list[str]:
    if not isinstance(schema, dict):
        return ["The schema must be a JSON object."]
    try:
        import jsonschema
    except ImportError:
        return []
    try:
        jsonschema.validators.validator_for(schema).check_schema(schema)
    except jsonschema.SchemaError as e:
        return [f"The schema is not valid: {e.message}."]
    return []


def _res(
    a: dict[str, Any], passed: bool, reason: str, score: float | None = None
) -> dict[str, Any]:
    t = a.get("type")
    return {
        "type": t,
        "label": a.get("label") or TYPES.get(t or "", {}).get("label") or t,
        "passed": bool(passed),
        "score": float(score if score is not None else (1.0 if passed else 0.0)),
        "reason": reason,
        "deterministic": TYPES.get(t or "", {}).get("deterministic", True),
    }


def check(a: dict[str, Any], obs: Observed) -> dict[str, Any]:
    """One deterministic assertion against one run. judge needs check_async."""
    problems = validate(a)
    if problems:
        return _res(a, False, "This assertion is incomplete: " + " ".join(problems))
    t = a["type"]
    out = (obs.output or "")[:MAX_SCAN]
    if t in ("json_path_equals", "json_path_contains"):
        data = parse_output_json(out)
        if data is _MISSING:
            return _res(
                a, False, "The output is not JSON, so the field could not be read."
            )
        found = json_path_values(data, a["path"])
        if not found:
            return _res(a, False, f"{a['path']} is not in the output.")
        want = a.get("value")
        ic = bool(a.get("ignore_case"))
        if t == "json_path_equals":
            tol = _num(a.get("tolerance")) or 0.0
            ok = any(_equal(v, want, tol, ic) for v in found)
            got = found[0] if len(found) == 1 else found
            return _res(
                a,
                ok,
                (
                    f"{a['path']} is {_short(got)}"
                    if ok
                    else f"{a['path']} is {_short(got)}, expected {_short(want)}"
                ),
            )
        ok = any(_contains(v, want, ic) for v in found)
        return _res(
            a,
            ok,
            (
                f"{a['path']} contains {_short(want)}"
                if ok
                else f"{a['path']} is {_short(found[0] if len(found) == 1 else found)}, which does not contain {_short(want)}"
            ),
        )
    if t == "regex":
        m = re.search(a["pattern"], out, _flags(a) | re.MULTILINE)
        expect_match = (a.get("mode") or "match") == "match"
        if expect_match:
            return _res(
                a,
                bool(m),
                (
                    f"Matched {_short(m.group(0), 60)}"
                    if m
                    else f"Nothing in the output matches {a['pattern']}"
                ),
            )
        return _res(
            a,
            not m,
            (
                f"Matched {_short(m.group(0), 60)}, which should not appear"
                if m
                else "No match, as expected"
            ),
        )
    if t in ("contains", "not_contains"):
        needle = str(a["value"])
        hay = out if a.get("case_sensitive") else out.lower()
        has = (needle if a.get("case_sensitive") else needle.lower()) in hay
        if t == "contains":
            return _res(
                a,
                has,
                (
                    f"Found {_short(needle, 60)}"
                    if has
                    else f"{_short(needle, 60)} is not in the output"
                ),
            )
        return _res(
            a,
            not has,
            (
                f"{_short(needle, 60)} appears in the output"
                if has
                else f"{_short(needle, 60)} does not appear"
            ),
        )
    if t == "schema_valid":
        data = parse_output_json(out)
        if data is _MISSING:
            return _res(
                a, False, "The output is not JSON, so it cannot match the schema."
            )
        try:
            import jsonschema
        except ImportError:
            return _res(
                a, False, "Schema checks need the jsonschema package on the API."
            )
        v = jsonschema.validators.validator_for(a["schema"])(a["schema"])
        errors = sorted(v.iter_errors(data), key=lambda e: list(e.absolute_path))
        if not errors:
            return _res(a, True, "The output matches the schema")
        first = errors[0]
        where = "/".join(str(p) for p in first.absolute_path) or "the top"
        more = f", and {len(errors) - 1} more" if len(errors) > 1 else ""
        return _res(a, False, f"At {where}: {first.message}{more}")
    if t == "required_tools_called":
        called = set(tool_names(obs.tool_calls))
        wanted = [str(x).strip() for x in a["tools"]]
        hit = [w for w in wanted if w in called]
        missing = [w for w in wanted if w not in called]
        if (a.get("mode") or "all") == "any":
            ok = bool(hit)
            return _res(
                a,
                ok,
                (
                    f"Called {', '.join(hit)}"
                    if ok
                    else f"None of {', '.join(wanted)} was called"
                ),
            )
        ok = not missing
        return _res(
            a,
            ok,
            "Called every required tool" if ok else f"Not called: {', '.join(missing)}",
            score=len(hit) / len(wanted) if wanted else 1.0,
        )
    if t == "max_cost":
        limit = float(_num(a["max"]) or 0)
        cost = float(obs.cost or 0)
        ok = cost <= limit + 1e-12
        return _res(
            a,
            ok,
            f"Cost ${cost:.4f} {'within' if ok else 'over'} the ${limit:.4f} limit",
        )
    if t == "max_duration_ms":
        limit = float(_num(a["max"]) or 0)
        if obs.duration_ms is None:
            return _res(a, False, "The run did not record how long it took")
        ok = obs.duration_ms <= limit
        return _res(
            a,
            ok,
            f"Took {obs.duration_ms} ms, {'within' if ok else 'over'} the {int(limit)} ms limit",
        )
    if t == "cited_sources_present":
        pattern = a.get("pattern") or DEFAULT_CITATION
        need = int(_num(a.get("min_count")) or 1)
        hits = re.findall(pattern, out, re.IGNORECASE)
        if len(hits) >= need:
            return _res(
                a, True, f"Found {len(hits)} citation{'s' if len(hits) != 1 else ''}"
            )
        if a.get("accept_source_tools", True):
            used = [n for n in tool_names(obs.tool_calls) if n in SOURCE_TOOLS]
            if used:
                return _res(a, True, f"Grounded through {', '.join(sorted(set(used)))}")
        return _res(
            a,
            False,
            f"Found {len(hits)} citation{'s' if len(hits) != 1 else ''}, needed {need}, and no source tool was used",
        )
    if t == "judge":
        return _res(a, False, "A judged assertion runs only during a suite run")
    return _res(a, False, f"Unknown assertion type {t}")


async def check_async(
    a: dict[str, Any], obs: Observed, judge: JudgeFn | None = None
) -> tuple[dict[str, Any], float]:
    """One assertion including judge. Returns the result and any judge cost."""
    if a.get("type") != "judge":
        return check(a, obs), 0.0
    problems = validate(a)
    if problems:
        return (
            _res(a, False, "This assertion is incomplete: " + " ".join(problems)),
            0.0,
        )
    if judge is None:
        return _res(a, False, "No judge model is available"), 0.0
    model = a.get("model") or DEFAULT_JUDGE_MODEL
    min_score = _num(a.get("min_score"))
    min_score = 0.7 if min_score is None else min_score
    try:
        score, reason, cost = await judge(
            a["rubric"], obs.input_message or "", obs.output or "", model
        )
    except Exception as e:  # noqa: BLE001
        return _res(a, False, f"The judge failed: {str(e)[:200]}"), 0.0
    score = max(0.0, min(1.0, float(score)))
    res = _res(
        a,
        score >= min_score,
        f"Scored {score:.2f} (pass at {min_score:.2f}) by {model}: {reason}",
        score=score,
    )
    res["model"] = model
    return res, float(cost or 0)


async def evaluate_case(
    assertions: list[dict[str, Any]], obs: Observed, judge: JudgeFn | None = None
) -> tuple[CaseOutcome, float]:
    """Every assertion of one case. A case passes when the run finished and every assertion passed."""
    if obs.status != "completed":
        return (
            CaseOutcome(
                False,
                0.0,
                [
                    {
                        "type": "run",
                        "label": "Run finished",
                        "passed": False,
                        "score": 0.0,
                        "reason": f"The run {obs.status}",
                        "deterministic": True,
                    }
                ],
            ),
            0.0,
        )
    results: list[dict[str, Any]] = []
    judge_cost = 0.0
    for a in assertions or []:
        r, c = await check_async(a, obs, judge)
        results.append(r)
        judge_cost += c
    if not results:
        return CaseOutcome(True, 1.0, []), 0.0
    score = sum(r["score"] for r in results) / len(results)
    return (
        CaseOutcome(all(r["passed"] for r in results), round(score, 4), results),
        judge_cost,
    )


def suggest(obs: Observed) -> list[dict[str, Any]]:
    """Starting assertions for a case captured from a past run, all true of that run."""
    out: list[dict[str, Any]] = []
    data = parse_output_json(obs.output)
    if isinstance(data, dict):
        added = 0
        for k, v in data.items():
            if added >= 3:
                break
            if isinstance(v, (str, int, float, bool)) and not (
                isinstance(v, str) and len(v) > 80
            ):
                safe = re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(k))
                path = str(k) if safe else f"['{k}']"
                out.append({"type": "json_path_equals", "path": path, "value": v})
                added += 1
        out.append({"type": "schema_valid", "schema": infer_schema(data)})
    elif (obs.output or "").strip():
        first = next(
            (
                ln.strip()
                for ln in (obs.output or "").splitlines()
                if len(ln.strip()) >= 12
            ),
            "",
        )
        words = re.findall(r"[A-Za-z][A-Za-z0-9-]{5,}", first)
        if words:
            out.append({"type": "contains", "value": words[0]})
    names = list(dict.fromkeys(tool_names(obs.tool_calls)))
    if names:
        out.append({"type": "required_tools_called", "tools": names[:5], "mode": "all"})
    if any(n in SOURCE_TOOLS for n in names) or re.search(
        DEFAULT_CITATION, obs.output or "", re.IGNORECASE
    ):
        out.append({"type": "cited_sources_present", "min_count": 1})
    # loose enough to survive normal model latency and token variance
    if obs.cost:
        out.append(
            {"type": "max_cost", "max": round(max(float(obs.cost) * 3, 0.01), 4)}
        )
    if obs.duration_ms:
        d = obs.duration_ms
        out.append(
            {"type": "max_duration_ms", "max": int(max(d * 3, d + 10_000, 5_000))}
        )
    return out


def infer_schema(data: Any, depth: int = 0) -> dict[str, Any]:
    """A loose schema that the sample satisfies: types and required keys, two levels deep."""
    if isinstance(data, bool):
        return {"type": "boolean"}
    if isinstance(data, int):
        return {"type": "number"}
    if isinstance(data, float):
        return {"type": "number"}
    if isinstance(data, str):
        return {"type": "string"}
    if data is None:
        return {}
    if isinstance(data, list):
        if depth >= 2 or not data:
            return {"type": "array"}
        return {"type": "array", "items": infer_schema(data[0], depth + 1)}
    if isinstance(data, dict):
        if depth >= 2:
            return {"type": "object"}
        return {
            "type": "object",
            "required": [k for k, v in data.items() if v is not None],
            "properties": {k: infer_schema(v, depth + 1) for k, v in data.items()},
        }
    return {}
