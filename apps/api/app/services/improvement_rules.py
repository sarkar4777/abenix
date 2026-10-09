"""Pure rules for governed self-improvement: what a proposal may change, the proof bar and the watch."""

from __future__ import annotations

import copy
import difflib
import json
import re
import statistics
from typing import Any, Callable

CHANGE_KINDS = (
    "examples",
    "prompt_edit",
    "tool_config",
    "pipeline_patch",
    "tool_set",
    "model",
)
CHANGE_LABELS = {
    "examples": "Add examples",
    "prompt_edit": "Edit the instructions",
    "tool_config": "Change a tool setting",
    "pipeline_patch": "Patch the pipeline",
    "tool_set": "Change the tools",
    "model": "Switch the model",
}
AGENT_KINDS = ("examples", "prompt_edit", "tool_config", "tool_set", "model")
PIPELINE_KINDS = ("pipeline_patch", "model")

STATES = (
    "drafting",
    "proving",
    "failed_proof",
    "awaiting_approval",
    "approved",
    "rejected",
    "released",
    "kept",
    "rolled_back",
    "superseded",
)
STATE_LABELS = {
    "drafting": "Drafting a fix",
    "proving": "Proving",
    "failed_proof": "Did not pass",
    "awaiting_approval": "Waiting for approval",
    "approved": "Approved, releasing",
    "rejected": "Rejected",
    "released": "Released, being watched",
    "kept": "Kept",
    "rolled_back": "Rolled back",
    "superseded": "Replaced",
}
ACTIVE_STATES = ("drafting", "proving", "awaiting_approval", "approved", "released")
WORK_STATES = ("drafting", "proving")
RISKS = ("low", "medium", "high")

EXAMPLES_HEADER = "Examples of good answers, added by an approved improvement:"
MAX_EXAMPLES = 8
MAX_PROMPT = 50_000
MIN_SPEED_RUNS = 10
TOOL_CONFIG_KEYS = (
    "parameter_defaults",
    "locked_defaults",
    "max_calls",
    "require_approval",
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "tokens_per_day": 400_000,
    "proofs_per_day": 20,
    "replay_sample": 50,
    "cost_margin": 0.2,
    "latency_margin": 0.2,
    "watch_days": 7,
    "watch_runs": 200,
    "watch_min_runs": 10,
    "auto_propose": True,
    "auto_propose_min_count": 5,
}
SETTING_LIMITS: dict[str, tuple[float, float]] = {
    "tokens_per_day": (0, 50_000_000),
    "proofs_per_day": (0, 10_000),
    "replay_sample": (0, 500),
    "cost_margin": (0, 5),
    "latency_margin": (0, 5),
    "watch_days": (1, 90),
    "watch_runs": (1, 100_000),
    "watch_min_runs": (1, 10_000),
    "auto_propose_min_count": (1, 10_000),
}


class ChangeRejected(ValueError):
    """A proposed change outside what the improver may touch."""


def settings_for(
    tenant_settings: dict[str, Any] | None, agent_id: Any
) -> dict[str, Any]:
    """Tenant improvement settings with the agent's own overrides on top."""
    imp = dict((tenant_settings or {}).get("improvements") or {})
    out = dict(DEFAULT_SETTINGS)
    for k in DEFAULT_SETTINGS:
        if k in imp and imp[k] is not None:
            out[k] = imp[k]
    per = ((imp.get("agents") or {}).get(str(agent_id or "")) or {}) if agent_id else {}
    for k in DEFAULT_SETTINGS:
        if k in per and per[k] is not None:
            out[k] = per[k]
    for k, (lo, hi) in SETTING_LIMITS.items():
        try:
            v = float(out[k])
        except (TypeError, ValueError):
            v = float(DEFAULT_SETTINGS[k])
        v = max(lo, min(hi, v))
        out[k] = v if isinstance(DEFAULT_SETTINGS[k], float) else int(v)
    out["auto_propose"] = bool(out.get("auto_propose"))
    return out


def state_of(agent: Any) -> dict[str, Any]:
    return {
        "system_prompt": getattr(agent, "system_prompt", None) or "",
        "model_config": copy.deepcopy(getattr(agent, "model_config_", None) or {}),
    }


def kinds_for(state: dict[str, Any]) -> tuple[str, ...]:
    mc = state.get("model_config") or {}
    return PIPELINE_KINDS if mc.get("mode") == "pipeline" else AGENT_KINDS


def _text(v: Any, field: str, limit: int) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ChangeRejected(f"{field} must be some text.")
    if len(v) > limit:
        raise ChangeRejected(f"{field} is longer than {limit} characters.")
    return v


def _apply_examples(prompt: str, diff: dict[str, Any]) -> str:
    items = diff.get("examples")
    if not isinstance(items, list) or not 1 <= len(items) <= 5:
        raise ChangeRejected("Give between 1 and 5 examples.")
    new = []
    for i, ex in enumerate(items, 1):
        if not isinstance(ex, dict):
            raise ChangeRejected(f"Example {i} must have an input and an output.")
        new.append(
            (
                _text(ex.get("input"), f"Example {i} input", 2000).strip(),
                _text(ex.get("output"), f"Example {i} output", 2000).strip(),
            )
        )
    base, old = prompt, []
    if EXAMPLES_HEADER in prompt:
        base, block = prompt.split(EXAMPLES_HEADER, 1)
        old = re.findall(
            r"Input: (.*?)\nGood answer: (.*?)(?:\n\n|\Z)", block.strip() + "\n\n", re.S
        )
    merged = [tuple(x) for x in old] + new
    seen: set[str] = set()
    kept = []
    for inp, out in reversed(merged):
        if inp in seen:
            continue
        seen.add(inp)
        kept.append((inp, out))
    kept = list(reversed(kept))[-MAX_EXAMPLES:]
    block = "\n\n".join(f"Input: {i}\nGood answer: {o}" for i, o in kept)
    return base.rstrip() + "\n\n" + EXAMPLES_HEADER + "\n\n" + block


def _apply_prompt_edit(prompt: str, diff: dict[str, Any]) -> str:
    edits = diff.get("edits")
    append = diff.get("append")
    if edits is None and append is None:
        raise ChangeRejected(
            "A prompt edit needs edits, each a find and a replace, or text to append."
        )
    out = prompt
    changed = 0
    for i, e in enumerate(edits or [], 1):
        if not isinstance(e, dict):
            raise ChangeRejected(f"Edit {i} must have find and replace.")
        find = e.get("find")
        repl = e.get("replace")
        if not isinstance(find, str) or not find:
            raise ChangeRejected(f"Edit {i} has nothing to find.")
        if not isinstance(repl, str):
            raise ChangeRejected(
                f"Edit {i} has no replacement text, use an empty one to delete."
            )
        if find == repl:
            raise ChangeRejected(f"Edit {i} changes nothing.")
        n = out.count(find)
        if n != 1:
            raise ChangeRejected(
                f"Edit {i} must match the instructions exactly once, it matches {n} times."
            )
        out = out.replace(find, repl, 1)
        changed += len(find) + len(repl)
    if len(edits or []) > 5:
        raise ChangeRejected("At most 5 edits in one proposal, keep it small.")
    if append is not None:
        out = out.rstrip() + "\n\n" + _text(append, "Text to append", 3000).strip()
        changed += len(append)
    if changed > max(2000, int(len(prompt) * 0.6)):
        raise ChangeRejected(
            "This rewrites most of the instructions. A proposal edits, it never rewrites."
        )
    if not out.strip():
        raise ChangeRejected("The instructions would be empty.")
    return out


def _apply_tool_config(mc: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    tool = diff.get("tool")
    tools = list(mc.get("tools") or [])
    if not isinstance(tool, str) or tool not in tools:
        raise ChangeRejected(
            "Tool settings can only change for a tool the agent already uses."
        )
    sets = diff.get("set")
    if not isinstance(sets, dict) or not sets:
        raise ChangeRejected("Say which tool setting to change.")
    bad = [k for k in sets if k not in TOOL_CONFIG_KEYS]
    if bad:
        raise ChangeRejected(
            "Only these tool settings can change: " + ", ".join(TOOL_CONFIG_KEYS) + "."
        )
    tc = copy.deepcopy(mc.get("tool_config") or {})
    cur = dict(tc.get(tool) or {})
    if "require_approval" in sets:
        if not isinstance(sets["require_approval"], bool):
            raise ChangeRejected("require_approval is true or false.")
        if cur.get("require_approval") and not sets["require_approval"]:
            raise ChangeRejected("An improvement never removes an approval step.")
    if "max_calls" in sets:
        v = sets["max_calls"]
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 100:
            raise ChangeRejected("max_calls must be a whole number from 1 to 100.")
    if "locked_defaults" in sets:
        if not isinstance(sets["locked_defaults"], bool):
            raise ChangeRejected("locked_defaults is true or false.")
        if cur.get("locked_defaults", True) and not sets["locked_defaults"]:
            raise ChangeRejected("An improvement never unlocks a locked value.")
    if "parameter_defaults" in sets:
        pd = sets["parameter_defaults"]
        if not isinstance(pd, dict) or len(json.dumps(pd, default=str)) > 4000:
            raise ChangeRejected("parameter_defaults must be a small set of values.")
        cur["parameter_defaults"] = {**(cur.get("parameter_defaults") or {}), **pd}
    for k in ("require_approval", "max_calls", "locked_defaults"):
        if k in sets:
            cur[k] = sets[k]
    tc[tool] = cur
    out = copy.deepcopy(mc)
    out["tool_config"] = tc
    return out


def _apply_tool_set(
    mc: dict[str, Any], diff: dict[str, Any], read_only_tools: set[str] | None
) -> dict[str, Any]:
    add = diff.get("add") or []
    remove = diff.get("remove") or []
    if not isinstance(add, list) or not isinstance(remove, list) or not (add or remove):
        raise ChangeRejected("Say which tool to add or remove.")
    if len(add) + len(remove) > 1:
        raise ChangeRejected("One tool per proposal, so cause and effect stay clear.")
    tools = list(mc.get("tools") or [])
    for t in remove:
        if t not in tools:
            raise ChangeRejected(f"The agent does not use {t}.")
        tools.remove(t)
    for t in add:
        if not isinstance(t, str) or t in tools:
            raise ChangeRejected(f"{t} is already one of the agent's tools.")
        if read_only_tools is None or t not in read_only_tools:
            raise ChangeRejected(
                f"{t} is not a read-only tool this agent can use. Tools that act need a person to add them."
            )
        tools.append(t)
    out = copy.deepcopy(mc)
    out["tools"] = tools
    return out


def _apply_model(
    mc: dict[str, Any], diff: dict[str, Any], model_ok: Callable[[str], bool] | None
) -> dict[str, Any]:
    model = diff.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ChangeRejected("Name the model to switch to.")
    if model == mc.get("model"):
        raise ChangeRejected("The agent already uses that model.")
    if model_ok is not None and not model_ok(model):
        raise ChangeRejected(f"{model} is not allowed for this agent's risk tier.")
    out = copy.deepcopy(mc)
    out["model"] = model
    return out


def _apply_pipeline_patch(
    mc: dict[str, Any], diff: dict[str, Any], registry: list[dict[str, Any]] | None
) -> dict[str, Any]:
    from engine.pipeline_surgeon import validate_patch

    ops = diff.get("patch")
    if not isinstance(ops, list) or not ops:
        raise ChangeRejected("A pipeline patch needs JSON-Patch operations.")
    try:
        after = validate_patch(
            {"pipeline_config": mc.get("pipeline_config") or {}}, ops, registry
        )
    except ValueError as e:
        raise ChangeRejected(f"The pipeline patch is not allowed: {e}") from e
    out = copy.deepcopy(mc)
    out["pipeline_config"] = after["pipeline_config"]
    return out


# what each kind may differ in, everything else must stay byte for byte the same
_ALLOWED_DIFF = {
    "examples": ("system_prompt",),
    "prompt_edit": ("system_prompt",),
    "tool_config": ("model_config.tool_config",),
    "tool_set": ("model_config.tools",),
    "model": ("model_config.model",),
    "pipeline_patch": ("model_config.pipeline_config", "model_config.tools"),
}


def guard(base: dict[str, Any], new: dict[str, Any], kind: str) -> None:
    """Refuse a candidate that touches anything outside its kind: limits, tier, grants, sharing."""
    allowed = _ALLOWED_DIFF.get(kind, ())
    if "system_prompt" not in allowed and base.get("system_prompt") != new.get(
        "system_prompt"
    ):
        raise ChangeRejected("This kind of change may not edit the instructions.")
    b = copy.deepcopy(base.get("model_config") or {})
    n = copy.deepcopy(new.get("model_config") or {})
    for path in allowed:
        if path.startswith("model_config."):
            key = path.split(".", 1)[1]
            b.pop(key, None)
            n.pop(key, None)
    if b != n:
        changed = sorted(k for k in set(b) | set(n) if b.get(k) != n.get(k))
        raise ChangeRejected(
            "An improvement may not change "
            + ", ".join(changed)
            + ". Only a person changes those."
        )


def apply_change(
    base: dict[str, Any],
    kind: str,
    diff: dict[str, Any],
    *,
    model_ok: Callable[[str], bool] | None = None,
    read_only_tools: set[str] | None = None,
    registry: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The candidate state, or ChangeRejected with a plain reason."""
    if kind not in CHANGE_KINDS:
        raise ChangeRejected(f"Unknown change kind {kind}.")
    if kind not in kinds_for(base):
        raise ChangeRejected(
            f"{CHANGE_LABELS[kind]} does not apply to this kind of agent."
        )
    if not isinstance(diff, dict):
        raise ChangeRejected("The change must be an object.")
    prompt = base.get("system_prompt") or ""
    mc = base.get("model_config") or {}
    new = {"system_prompt": prompt, "model_config": copy.deepcopy(mc)}
    if kind == "examples":
        new["system_prompt"] = _apply_examples(prompt, diff)
    elif kind == "prompt_edit":
        new["system_prompt"] = _apply_prompt_edit(prompt, diff)
    elif kind == "tool_config":
        new["model_config"] = _apply_tool_config(mc, diff)
    elif kind == "tool_set":
        new["model_config"] = _apply_tool_set(mc, diff, read_only_tools)
    elif kind == "model":
        new["model_config"] = _apply_model(mc, diff, model_ok)
    elif kind == "pipeline_patch":
        new["model_config"] = _apply_pipeline_patch(mc, diff, registry)
    if len(new["system_prompt"]) > MAX_PROMPT:
        raise ChangeRejected("The instructions would be too long.")
    if new == {"system_prompt": prompt, "model_config": mc}:
        raise ChangeRejected("The change leaves the agent as it is.")
    guard(base, new, kind)
    return new


def clean_diff(diff: Any) -> dict[str, Any]:
    """The diff without the preview the API adds for display."""
    if not isinstance(diff, dict):
        return {}
    return {k: v for k, v in diff.items() if k != "preview"}


def preview(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Before and after of what changed, with line marks for the diff view."""
    if base.get("system_prompt") != new.get("system_prompt"):
        before = base.get("system_prompt") or ""
        after = new.get("system_prompt") or ""
        what = "instructions"
    else:
        b = base.get("model_config") or {}
        n = new.get("model_config") or {}
        keys = sorted(k for k in set(b) | set(n) if b.get(k) != n.get(k))
        before = json.dumps({k: b.get(k) for k in keys}, indent=2, default=str)
        after = json.dumps({k: n.get(k) for k in keys}, indent=2, default=str)
        what = ", ".join(keys) or "settings"
    lines = []
    for op in difflib.ndiff(before.splitlines(), after.splitlines()):
        tag = op[:1]
        if tag == "?":
            continue
        lines.append(
            {"op": {"+": "add", "-": "remove"}.get(tag, "same"), "text": op[2:]}
        )
    return {"what": what, "lines": lines[:400]}


# the proof bar


def bar(
    *,
    fixed: int,
    broken: int,
    before: dict[str, Any],
    after: dict[str, Any],
    gating_ok: bool | None,
    cost_margin: float,
    latency_margin: float,
) -> tuple[bool, list[str]]:
    """Whether a person ever sees this proposal, and the reasons in plain words."""
    reasons: list[str] = []
    if fixed < 1:
        reasons.append("It did not fix any of the lessons it was meant to fix.")
    if broken > 0:
        reasons.append(
            f"It broke {broken} case{'s' if broken != 1 else ''} that passed before."
        )
    cb, ca = float(before.get("cost_usd") or 0), float(after.get("cost_usd") or 0)
    if cb > 0 and ca > cb * (1 + cost_margin):
        reasons.append(
            f"It costs {pct(ca / cb - 1)} more per run, the limit is {pct(cost_margin)}."
        )
    # speed is noisy, judge it only on enough runs timed side by side in this proof
    lb = before.get("timed_latency_ms", before.get("latency_ms"))
    la = after.get("timed_latency_ms", after.get("latency_ms"))
    enough = (
        min(
            int(before.get("timed_runs", before.get("runs")) or 0),
            int(after.get("timed_runs", after.get("runs")) or 0),
        )
        >= MIN_SPEED_RUNS
    )
    if enough and lb and la and float(la) > float(lb) * (1 + latency_margin):
        reasons.append(
            f"It is {pct(float(la) / float(lb) - 1)} slower, the limit is {pct(latency_margin)}."
        )
    if gating_ok is False:
        reasons.append("It does not pass the agent's release tests.")
    return (not reasons), reasons


def pct(x: float) -> str:
    return f"{round(x * 100)}%"


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Scores for one side of a proof from its runs."""
    cases = [r for r in rows if r.get("kind") == "case"]
    done = [r for r in rows if r.get("status") == "completed"]
    lat = [float(r["duration_ms"]) for r in done if r.get("duration_ms")]
    # cached and historical answers ran at another time, under another load
    timed = [
        float(r["duration_ms"])
        for r in done
        if r.get("duration_ms") and r.get("timed", True)
    ]
    return {
        "runs": len(rows),
        "pass_rate": (
            round(sum(1 for r in cases if r.get("passed")) / len(cases), 4)
            if cases
            else None
        ),
        "quality": (
            round(sum(float(r.get("score") or 0) for r in cases) / len(cases), 4)
            if cases
            else None
        ),
        "cost_usd": (
            round(sum(float(r.get("cost") or 0) for r in rows) / len(rows), 6)
            if rows
            else 0.0
        ),
        "latency_ms": int(statistics.median(lat)) if lat else None,
        "timed_latency_ms": int(statistics.median(timed)) if timed else None,
        "timed_runs": len(timed),
        "tool_calls": (
            round(sum(int(r.get("tool_calls") or 0) for r in rows) / len(rows), 2)
            if rows
            else 0.0
        ),
    }


def changed(before: str | None, after: str | None) -> bool:
    a = re.sub(r"\s+", " ", (before or "").strip().lower())[:4000]
    b = re.sub(r"\s+", " ", (after or "").strip().lower())[:4000]
    if a == b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() < 0.9


def stratify(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """Up to n distinct inputs, round robin over input shape so one kind never fills the sample."""
    if n <= 0:
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for r in rows:
        text = (r.get("input") or "").strip()
        if not text:
            continue
        key = re.sub(r"\s+", " ", text.lower())
        if key in seen:
            continue
        seen.add(key)
        size = "s" if len(text) < 80 else "m" if len(text) < 400 else "l"
        first = (re.findall(r"[a-z]+", key) or [""])[0]
        groups.setdefault(f"{size}:{first}", []).append(r)
    out: list[dict[str, Any]] = []
    order = sorted(groups, key=lambda k: -len(groups[k]))
    while len(out) < n and any(groups[k] for k in order):
        for k in order:
            if groups[k] and len(out) < n:
                out.append(groups[k].pop(0))
    return out


# the watch


def rate(n: float, d: float) -> float | None:
    return (n / d) if d else None


def watch_reasons(
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    min_runs: int,
    cost_margin: float,
) -> list[str]:
    """Why the new revision is worse than the old one, empty when it is not."""
    out: list[str] = []
    nr, orr = int(new.get("runs") or 0), int(old.get("runs") or 0)
    nf = int(new.get("failures") or 0)
    if nr >= min_runs and nf >= 2:
        fo = rate(old.get("failures") or 0, orr) or 0.0
        fn = rate(nf, nr) or 0.0
        if fn > fo + 0.10:
            out.append(f"Failed runs rose from {pct(fo)} to {pct(fn)}.")
    nt, nd = int(new.get("thumbs_total") or 0), int(new.get("thumbs_down") or 0)
    if nt >= 3 and nd >= 2:
        do = rate(old.get("thumbs_down") or 0, old.get("thumbs_total") or 0) or 0.0
        dn = rate(nd, nt) or 0.0
        if dn > do + 0.15:
            out.append(f"Thumbs down rose from {pct(do)} to {pct(dn)} ({nd} of {nt}).")
    co, cn = float(old.get("cost_avg") or 0), float(new.get("cost_avg") or 0)
    if nr >= min_runs and orr and co > 0 and cn > co * (1 + cost_margin):
        out.append(f"Cost per run rose from ${co:.4f} to ${cn:.4f}.")
    drift = new.get("drift") or []
    if drift:
        names = ", ".join(sorted({str(d) for d in drift}))
        out.append(f"A drift alert fired during the watch period ({names}).")
    ns, os_ = int(new.get("scored") or 0), int(old.get("scored") or 0)
    if ns >= 3 and os_ >= 3:
        ao = rate(old.get("accurate") or 0, os_) or 0.0
        an = rate(new.get("accurate") or 0, ns) or 0.0
        if an < ao - 0.15:
            out.append(f"Autonomy accuracy fell from {pct(ao)} to {pct(an)}.")
    nl = int(new.get("cluster_lessons") or 0)
    if nl >= 2:
        lo = rate(old.get("cluster_lessons") or 0, orr) or 0.0
        ln = rate(nl, max(nr, 1)) or 0.0
        if ln > lo:
            out.append(
                f"The mistake it should fix came back: {nl} new lesson{'s' if nl != 1 else ''} since the release."
            )
    return out


def watch_done(new_runs: int, target_runs: int, now: Any, until: Any) -> bool:
    if until is not None and now >= until:
        return True
    return target_runs > 0 and new_runs >= target_runs


# progress


STEP_LABELS = (
    ("draft", "Drafting the change"),
    ("test_set", "Test set"),
    ("replay", "Replay of real inputs"),
    ("comparing", "Comparing"),
    ("done", "Done"),
)


def new_progress(skip_draft: bool = False) -> dict[str, Any]:
    steps = []
    for key, label in STEP_LABELS:
        if key == "draft" and skip_draft:
            continue
        steps.append(
            {"key": key, "label": label, "state": "pending", "done": 0, "total": 0}
        )
    return {
        "phase": "queued",
        "steps": steps,
        "message": "Waiting for a free proof worker.",
        "tokens": 0,
    }


def step(progress: dict[str, Any], key: str, **kw: Any) -> dict[str, Any]:
    p = copy.deepcopy(progress or new_progress())
    for s in p.get("steps") or []:
        if s["key"] == key:
            s.update(kw)
    if kw.get("state") == "running":
        p["phase"] = key
    return p
