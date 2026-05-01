"""Talk-to-workflow shell — formal verb grammar."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ArgSpec:
    """Single argument to a verb."""
    name: str
    typ: str                    # "string", "ident", "number", "any", "json", "node_ref", "duration", "expr"
    required: bool = True
    default: Any = None
    help: str = ""


@dataclass
class VerbSpec:
    """Declarative description of one shell verb."""
    name: str
    intent: str                 # INSPECT | MUTATE | EXECUTE | GOVERN | LEARN
    summary: str
    args: list[ArgSpec] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    risk: str = "safe"          # safe | low | medium | high


# ── INSPECT ─────────────────────────────────────────────────────────────
INSPECT_VERBS: list[VerbSpec] = [
    VerbSpec(
        name="show",
        intent="INSPECT",
        summary="Show a top-level workflow object: workflow, runs, failures, nodes, costs, schedule, patches, history, replays, branches.",
        args=[ArgSpec("object", "ident", help="workflow | runs | failures | nodes | costs | schedule | patches | history | replays | branches")],
        examples=["show workflow", "show runs", "show failures", "show nodes", "show costs", "show patches"],
    ),
    VerbSpec(
        name="describe",
        intent="INSPECT",
        summary="Describe a single node — its IO shape, model, tool, recent stats.",
        args=[ArgSpec("node", "node_ref", help="node id, e.g. extractor")],
        examples=["describe extractor"],
    ),
    VerbSpec(
        name="diff",
        intent="INSPECT",
        summary="Diff two runs side-by-side (by id, or relative: last, last-2, last-3, ...).",
        args=[
            ArgSpec("a", "string", help="run-id or 'last' / 'last-2'"),
            ArgSpec("b", "string", help="run-id or 'last' / 'last-2'"),
        ],
        examples=["diff last last-2", "diff abc-123 def-456"],
    ),
    VerbSpec(
        name="why",
        intent="INSPECT",
        summary="Explain why a run failed or succeeded (LLM-assisted; uses captured diffs + traces).",
        args=[ArgSpec("run", "string", help="run-id or 'last'")],
        examples=["why last", "why abc-123"],
        aliases=["explain"],
    ),
    VerbSpec(
        name="list",
        intent="INSPECT",
        summary="Tabular listing — patches, history, replays, branches, runs.",
        args=[ArgSpec("category", "ident", help="patches | history | replays | branches | runs")],
        examples=["list patches", "list runs", "list branches"],
    ),
]


# ── MUTATE ──────────────────────────────────────────────────────────────
MUTATE_VERBS: list[VerbSpec] = [
    VerbSpec(
        name="add",
        intent="MUTATE",
        summary="Add a node to the pipeline (agent | tool | switch | map | reduce | http).",
        args=[
            ArgSpec("kind", "ident", help="agent | tool | switch | map | reduce | http"),
            ArgSpec("name", "string", help="new node id"),
            ArgSpec("after", "node_ref", required=False, default=None, help="optional: which node to insert after"),
        ],
        examples=["add tool web_search", "add agent triage after intake"],
        risk="medium",
    ),
    VerbSpec(
        name="remove",
        intent="MUTATE",
        summary="Remove a node.  Refuses if it has dependents — fix the chain first.",
        args=[ArgSpec("node", "node_ref")],
        examples=["remove unused-step"],
        risk="high",
    ),
    VerbSpec(
        name="rename",
        intent="MUTATE",
        summary="Rename a node id; updates all depends_on references.",
        args=[
            ArgSpec("old", "node_ref"),
            ArgSpec("new", "string"),
        ],
        examples=["rename extractor extractor-v2"],
        risk="low",
    ),
    VerbSpec(
        name="set",
        intent="MUTATE",
        summary="Set a field on a node (or workflow root). Path is dot-separated: <node>.<field> or .<workflow_field>.",
        args=[
            ArgSpec("path", "string", help="e.g. extractor.timeout_seconds or .description"),
            ArgSpec("value", "any"),
        ],
        examples=["set extractor.timeout_seconds 60", "set extractor.on_error continue"],
        risk="low",
    ),
    VerbSpec(
        name="swap-model",
        intent="MUTATE",
        summary="Swap the LLM model on an agent_step node.",
        args=[
            ArgSpec("node", "node_ref"),
            ArgSpec("model", "string", help="claude-sonnet-4-5-20250929 | gemini-2.5-pro | gpt-4o | ..."),
        ],
        examples=["swap-model extractor gemini-2.5-pro"],
        risk="medium",
    ),
    VerbSpec(
        name="add-fallback",
        intent="MUTATE",
        summary="Add a fallback default for a missing field on a node's input mapping.",
        args=[
            ArgSpec("node", "node_ref"),
            ArgSpec("field", "string"),
            ArgSpec("default", "any"),
        ],
        examples=["add-fallback extractor counterparty UNKNOWN"],
        risk="low",
    ),
    VerbSpec(
        name="attach",
        intent="MUTATE",
        summary="Attach a Knowledge Base, Atlas graph, or tool to a node.",
        args=[
            ArgSpec("kind", "ident", help="kb | atlas | tool"),
            ArgSpec("ref", "string", help="kb id / atlas id / tool name"),
            ArgSpec("node", "node_ref"),
        ],
        examples=["attach kb fin-glossary to extractor", "attach tool web_search to research"],
        risk="medium",
    ),
]


# ── EXECUTE ─────────────────────────────────────────────────────────────
EXECUTE_VERBS: list[VerbSpec] = [
    VerbSpec(
        name="run",
        intent="EXECUTE",
        summary="Run the workflow with an inline payload.",
        args=[ArgSpec("input", "any", help="JSON or quoted string")],
        examples=['run {"contract_id": "abc"}'],
    ),
    VerbSpec(
        name="replay",
        intent="EXECUTE",
        summary="Re-run a past execution (optionally with a draft patch applied).",
        args=[
            ArgSpec("run", "string"),
            ArgSpec("with_patch", "string", required=False, default=None, help="patch id to apply for the replay"),
        ],
        examples=["replay last", "replay abc-123 with-patch p9d1"],
    ),
    VerbSpec(
        name="simulate",
        intent="EXECUTE",
        summary="Dry-run against a dataset (last-N runs, uploaded CSV, or named fixture). Idempotent — no external side-effects.",
        args=[
            ArgSpec("source", "string", help="last-100 | csv:<file> | fixture:<name>"),
        ],
        examples=["simulate last-100", "simulate fixture:weekend-batch"],
    ),
    VerbSpec(
        name="branch",
        intent="EXECUTE",
        summary="Create a sandbox branch from a run for safe experimentation.",
        args=[
            ArgSpec("name", "string"),
            ArgSpec("from_run", "string", required=False, default="last"),
        ],
        examples=["branch fix-extractor from last", "branch experiment-1"],
    ),
    VerbSpec(
        name="merge",
        intent="EXECUTE",
        summary="Merge a branch back to main, optionally gated on simulation pass.",
        args=[
            ArgSpec("branch", "string"),
            ArgSpec("if_pass", "ident", required=False, default=None, help="pass to require simulate to be green first"),
        ],
        examples=["merge fix-extractor", "merge experiment-1 if-pass"],
        risk="medium",
    ),
    VerbSpec(
        name="rollback",
        intent="EXECUTE",
        summary="Roll back the workflow to a prior run, applied patch, or version.",
        args=[ArgSpec("target", "string", help="run-id | patch:<id> | v<n>")],
        examples=["rollback patch:p9d1", "rollback v3"],
        risk="medium",
    ),
]


# ── GOVERN ──────────────────────────────────────────────────────────────
GOVERN_VERBS: list[VerbSpec] = [
    VerbSpec(
        name="watch",
        intent="GOVERN",
        summary="Add an alert: emit when an expression over recent runs fires.",
        args=[
            ArgSpec("metric", "ident", help="cost | latency | error-rate | drift"),
            ArgSpec("expr", "expr", help="e.g. > 5/run, > 2s p95, > 10%/h"),
        ],
        examples=['watch cost alert if > 5/run', 'watch error-rate alert if > 10%/h'],
        risk="safe",
    ),
    VerbSpec(
        name="budget",
        intent="GOVERN",
        summary="Set a hard cost budget on a node or the whole workflow.",
        args=[
            ArgSpec("scope", "string", help="<node-id> or 'workflow'"),
            ArgSpec("amount", "string", help="$5/run, $100/day, $5000/mo"),
        ],
        examples=["budget extractor $0.10/run", "budget workflow $100/day"],
        risk="low",
    ),
    VerbSpec(
        name="pin",
        intent="GOVERN",
        summary="Pin a model or version to a node — protects against accidental drift.",
        args=[
            ArgSpec("kind", "ident", help="model | version"),
            ArgSpec("node", "node_ref"),
            ArgSpec("ref", "string"),
        ],
        examples=["pin model extractor claude-sonnet-4-5-20250929"],
        risk="low",
    ),
    VerbSpec(
        name="unpin",
        intent="GOVERN",
        summary="Remove a pin on a node.",
        args=[ArgSpec("node", "node_ref")],
        examples=["unpin extractor"],
        risk="low",
    ),
    VerbSpec(
        name="approve",
        intent="GOVERN",
        summary="Approve a Pipeline-Surgeon patch proposal.  Same as the Apply button.",
        args=[ArgSpec("patch_id", "string")],
        examples=["approve p9d1"],
        risk="medium",
    ),
    VerbSpec(
        name="reject",
        intent="GOVERN",
        summary="Reject a patch proposal.",
        args=[ArgSpec("patch_id", "string")],
        examples=["reject p9d1"],
        risk="safe",
    ),
]


# ── LEARN ──────────────────────────────────────────────────────────────
LEARN_VERBS: list[VerbSpec] = [
    VerbSpec(
        name="suggest",
        intent="LEARN",
        summary="Ask the shell for ideas.  Categories: improvements | cheaper-equivalent | faster-equivalent.",
        args=[ArgSpec("category", "ident", help="improvements | cheaper-equivalent | faster-equivalent")],
        examples=["suggest improvements", "suggest cheaper-equivalent"],
    ),
    VerbSpec(
        name="diagnose",
        intent="LEARN",
        summary="Run the Pipeline Surgeon against the latest failure (alias for clicking 'Diagnose latest failure').",
        args=[],
        examples=["diagnose"],
    ),
    VerbSpec(
        name="explain",
        intent="LEARN",
        summary="Explain costs, latency, or routing for the last 100 runs (per-node breakdown).",
        args=[ArgSpec("dimension", "ident", help="costs | latency | routing")],
        examples=["explain costs", "explain latency"],
    ),
    VerbSpec(
        name="help",
        intent="LEARN",
        summary="Print the cheat sheet of all verbs, or details for one verb.",
        args=[ArgSpec("verb", "string", required=False, default=None)],
        examples=["help", "help simulate"],
    ),
]


# ── Registry ───────────────────────────────────────────────────────────
GRAMMAR: dict[str, VerbSpec] = {}
for spec_list in (INSPECT_VERBS, MUTATE_VERBS, EXECUTE_VERBS, GOVERN_VERBS, LEARN_VERBS):
    for spec in spec_list:
        GRAMMAR[spec.name] = spec
        for alias in spec.aliases:
            GRAMMAR[alias] = spec


# Words that show up between args but aren't part of the actual values.
_NOISE = {"to", "from", "with", "if", "alert", "as", "the", "a", "an"}


def _shlex_split(text: str) -> list[str]:
    """A tiny shlex that respects quotes and JSON-looking braces."""
    out: list[str] = []
    buf: list[str] = []
    in_q = ""
    depth = 0
    for ch in text.strip():
        if in_q:
            buf.append(ch)
            if ch == in_q:
                in_q = ""
                out.append("".join(buf))
                buf = []
            continue
        if ch in ("'", '"'):
            if buf:
                out.append("".join(buf))
                buf = []
            in_q = ch
            buf.append(ch)
            continue
        if ch in ("{", "["):
            depth += 1
            buf.append(ch)
            continue
        if ch in ("}", "]"):
            depth -= 1
            buf.append(ch)
            if depth <= 0 and buf:
                out.append("".join(buf))
                buf = []
                depth = 0
            continue
        if ch.isspace() and depth == 0:
            if buf:
                out.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        out.append("".join(buf))
    return [t for t in out if t]


def parse_command(text: str) -> dict[str, Any]:
    """Parse a single shell line into a structured invocation."""
    tokens = _shlex_split(text)
    if not tokens:
        return {"ok": False, "error": "empty input"}

    head = tokens[0].lower()
    if head not in GRAMMAR:
        # Suggest closest by edit distance over verb keys
        suggestion = _closest(head, list(GRAMMAR.keys()))
        return {"ok": False, "error": f"unknown verb '{head}'", "suggestion": suggestion}

    spec = GRAMMAR[head]

    # Strip noise words; merge multi-word values for `expr`.
    rest = [t for t in tokens[1:] if t.lower() not in _NOISE]

    args: dict[str, Any] = {}
    for i, argspec in enumerate(spec.args):
        if i >= len(rest):
            if argspec.required:
                return {
                    "ok": False,
                    "error": f"missing argument '{argspec.name}'",
                    "verb": spec.name,
                    "expected": [a.name for a in spec.args],
                }
            args[argspec.name] = argspec.default
            continue
        # The last expression-typed arg slurps everything remaining.
        if argspec.typ == "expr" and i == len(spec.args) - 1:
            args[argspec.name] = " ".join(rest[i:])
            break
        args[argspec.name] = _coerce(rest[i], argspec.typ)

    return {"ok": True, "verb": spec.name, "args": args, "spec": spec}


def _coerce(raw: str, typ: str) -> Any:
    s = raw.strip()
    if typ == "string" or typ == "any":
        if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
            return s[1:-1]
        return s
    if typ == "ident":
        return s.lower()
    if typ == "number":
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return s
    if typ == "node_ref":
        return s
    if typ == "json":
        import json
        try:
            return json.loads(s)
        except Exception:
            return s
    if typ == "duration":
        return s  # parsed downstream
    if typ == "expr":
        return s
    return s


def _closest(needle: str, candidates: list[str]) -> str | None:
    """Cheap Damerau-Levenshtein-ish best match."""
    if not needle:
        return None
    best = None
    best_score = 1e9
    for c in candidates:
        score = _edit_distance(needle, c)
        if score < best_score:
            best, best_score = c, score
    if best_score > max(2, len(needle) // 2):
        return None
    return best


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            ins = curr[j - 1] + 1
            dele = prev[j] + 1
            sub = prev[j - 1] + (ca != cb)
            curr[j] = min(ins, dele, sub)
        prev = curr
    return prev[-1]


def verb_doc_md(verb: str | None = None) -> str:
    """Produce a markdown cheat sheet — full registry, or a single verb."""
    if verb and verb in GRAMMAR:
        s = GRAMMAR[verb]
        lines = [
            f"## `{s.name}` — {s.summary}",
            "",
            f"**Intent:** `{s.intent}`   **Risk:** `{s.risk}`",
            "",
            "### Arguments",
        ]
        if not s.args:
            lines.append("(none)")
        for a in s.args:
            req = "required" if a.required else f"optional, default `{a.default}`"
            lines.append(f"- `{a.name}` *({a.typ})* — {a.help or ''}  _{req}_")
        if s.examples:
            lines.append("\n### Examples")
            for e in s.examples:
                lines.append(f"- `{e}`")
        if s.aliases:
            lines.append(f"\n**Aliases:** {', '.join(f'`{a}`' for a in s.aliases)}")
        return "\n".join(lines)

    # Full sheet
    by_intent: dict[str, list[VerbSpec]] = {}
    seen: set[str] = set()
    for spec in GRAMMAR.values():
        if spec.name in seen:
            continue
        seen.add(spec.name)
        by_intent.setdefault(spec.intent, []).append(spec)

    out: list[str] = ["# Talk-to-workflow shell — verb cheat sheet", ""]
    for intent in ("INSPECT", "MUTATE", "EXECUTE", "GOVERN", "LEARN"):
        out.append(f"## {intent}")
        for spec in by_intent.get(intent, []):
            sig = " ".join(
                f"<{a.name}>" if a.required else f"[{a.name}]"
                for a in spec.args
            )
            out.append(f"- `{spec.name} {sig}` — {spec.summary}")
        out.append("")
    return "\n".join(out)


def list_verbs() -> list[dict[str, Any]]:
    """JSON-serialisable summary of the grammar (for the UI autocomplete)."""
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for spec in GRAMMAR.values():
        if spec.name in seen:
            continue
        seen.add(spec.name)
        rows.append({
            "name": spec.name,
            "intent": spec.intent,
            "summary": spec.summary,
            "args": [
                {"name": a.name, "typ": a.typ, "required": a.required,
                 "default": a.default, "help": a.help}
                for a in spec.args
            ],
            "examples": spec.examples,
            "aliases": spec.aliases,
            "risk": spec.risk,
        })
    return rows
