"""Iterative AI agent/pipeline builder."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Awaitable

from engine.pipeline_validator import BUILTIN_TOOLS

logger = logging.getLogger(__name__)


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    """Make the generated config internally consistent."""
    if not isinstance(config, dict):
        return config
    declared = list(config.get("tools") or [])
    declared_set = {t for t in declared if isinstance(t, str)}
    nodes = (config.get("pipeline_config") or {}).get("nodes") or []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        name = n.get("tool_name") or n.get("tool")
        if not isinstance(name, str) or not name:
            continue
        if name in declared_set:
            continue
        declared.append(name)
        declared_set.add(name)
    config["tools"] = declared
    return config


@dataclass
class IterationState:
    iteration: int
    config: dict[str, Any] | None = None
    tier1_errors: list[dict[str, Any]] = field(default_factory=list)
    tier2_errors: list[dict[str, Any]] = field(default_factory=list)
    tier2_warnings: list[dict[str, Any]] = field(default_factory=list)
    dry_run_failures: list[dict[str, Any]] = field(default_factory=list)
    judge_passed: bool = False
    judge_score: int = 0
    judge_suggestions: list[str] = field(default_factory=list)
    judge_missing: list[str] = field(default_factory=list)
    # Adversarial critic review after judge passes
    critic_concerns: list[str] = field(default_factory=list)
    critic_severity: str = ""  # "" | "minor" | "major" | "blocker"
    # Real-execution smoke test results after critic clears
    test_ran: bool = False
    test_ok: bool = False
    test_error: str = ""

    def error_signature(self) -> str:
        """Stable fingerprint of failures — used to detect 'same error twice'."""
        parts: list[str] = []
        for e in self.tier1_errors + self.tier2_errors:
            parts.append(f"{e.get('node_id', '')}::{e.get('field', '')}::{e.get('message', '')[:120]}")
        for f in self.dry_run_failures:
            parts.append(f"dry::{f.get('node_id', '')}::{f.get('reason', '')[:120]}")
        for c in self.critic_concerns:
            parts.append(f"critic::{c[:120]}")
        if self.test_error:
            parts.append(f"test::{self.test_error[:120]}")
        return "|".join(sorted(parts))


_JUDGE_SYSTEM = """\
You are a senior engineer evaluating whether a freshly generated Abenix
agent/pipeline config would satisfy the user's request.

Be blunt. If the config is good enough for a first production pass, pass it.
Don't demand perfection. Only fail if there is a real gap that will cause
the user visible harm (missing core step, wrong tool, broken DAG).

IMPORTANT — DO NOT FLAG THESE AS UNDECLARED:
{builtins_line}
These are platform built-in nodes/tools. They are always resolvable by the
runtime even if they are not present in the config's `tools` array. Never
say "undeclared tool" about any of them.

Also: a tool_name inside a node is treated as declared as long as it
appears in the config's `tools` array OR is in the list above OR is
declared in `custom_tools`. If unsure whether a name is real, don't
fabricate an "undeclared" verdict — focus on logical / DAG issues.

Respond with ONLY a JSON object:
{{
  "passed": bool,
  "score": 1..10,
  "missing_steps": ["..."],
  "wrong_nodes": [{{"node_id": "...", "reason": "..."}}],
  "suggestions": ["specific, small fixes"],
  "summary": "one sentence verdict"
}}
""".format(builtins_line=", ".join(sorted(BUILTIN_TOOLS)))


async def _judge(
    llm: Any,
    user_request: str,
    config: dict[str, Any],
    dry_run_trace: str = "",
) -> dict[str, Any]:
    """Ask the LLM whether the generated config satisfies the user's request."""
    payload = {
        "user_request": user_request,
        "config": config,
    }
    if dry_run_trace:
        payload["dry_run_trace"] = dry_run_trace[:4000]
    try:
        resp = await llm.complete(
            messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
            system=_JUDGE_SYSTEM,
            model="claude-sonnet-4-5-20250929",
            temperature=0.0,
        )
    except Exception as e:
        return {
            "passed": False, "score": 0, "missing_steps": [],
            "wrong_nodes": [], "suggestions": [], "summary": f"judge failed: {e}",
            "error": str(e),
        }
    text = resp.content.strip()
    if "{" not in text:
        return {"passed": False, "score": 0, "missing_steps": [], "wrong_nodes": [],
                "suggestions": [], "summary": f"judge returned no JSON: {text[:200]}"}
    try:
        data = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except Exception as e:
        return {"passed": False, "score": 0, "missing_steps": [], "wrong_nodes": [],
                "suggestions": [], "summary": f"judge returned bad JSON: {e}"}
    data.setdefault("passed", False)
    data.setdefault("score", 0)
    data.setdefault("missing_steps", [])
    data.setdefault("wrong_nodes", [])
    data.setdefault("suggestions", [])
    data.setdefault("summary", "")
    return data


def _build_repair_context(state: IterationState) -> str:
    """Turn the previous iteration's failures into a repair prompt section."""
    if state.iteration == 0:
        return ""
    lines = [
        f"\n\n--- PREVIOUS ATTEMPT (iteration {state.iteration}) FAILED — FIX THESE SPECIFIC ISSUES ---"
    ]
    if state.tier1_errors:
        lines.append("Structural errors:")
        for e in state.tier1_errors[:8]:
            lines.append(f"  • {e.get('node_id', '')}/{e.get('field', '')}: {e.get('message', '')}")
    if state.tier2_errors:
        lines.append("Semantic errors:")
        for e in state.tier2_errors[:8]:
            lines.append(f"  • {e.get('node_id', '')}/{e.get('field', '')}: {e.get('message', '')}")
    if state.dry_run_failures:
        lines.append("Dry-run failures:")
        for f in state.dry_run_failures[:6]:
            lines.append(f"  • {f.get('node_id', '')}: {f.get('reason', '')}")
    if state.judge_missing:
        lines.append("Judge said these steps are missing:")
        for m in state.judge_missing[:6]:
            lines.append(f"  • {m}")
    if state.judge_suggestions:
        lines.append("Judge suggestions:")
        for s in state.judge_suggestions[:6]:
            lines.append(f"  • {s}")
    if state.critic_concerns:
        lines.append(f"Adversarial critic ({state.critic_severity or 'minor'}) still concerned about:")
        for c in state.critic_concerns[:8]:
            lines.append(f"  • {c}")
    if state.test_error:
        lines.append("Auto-execution smoke test FAILED with:")
        lines.append(f"  • {state.test_error[:500]}")
    lines.append("Produce a revised config that fixes ALL of the above.")
    return "\n".join(lines)


_CRITIC_SYSTEM = """\
You are an adversarial senior engineer doing a second-pass review of an
Abenix agent/pipeline config the judge already passed.

Your job is to find what the judge MISSED. Pretend you're on-call when this
pipeline runs in production. Ask yourself:

  - What happens at the edge? Empty input, huge input, wrong schema, null
    values, the LLM returning nothing, a tool timing out, a template field
    not resolving?
  - Are any templates {{foo.bar}} referencing keys that may not exist on
    the upstream node's actual output shape?
  - Does the DAG have silent dead-ends (node's output consumed by nothing)
    or branches that don't merge where they should?
  - Are there hardcoded values that should be input_variables?
  - Are any tool calls missing required arguments or using values outside
    declared enums?
  - For agent mode: does the system_prompt actually tell the LLM WHEN to
    call each tool, or does it just list tool names and hope?

Be specific and actionable. Do NOT repeat what the judge already said.

Severity ladder:
  minor    — nice-to-have, won't cause production issues
  major    — will cause user-visible degradation under normal load
  blocker  — will cause failures on the first real run

Respond with ONLY a JSON object:
{
  "severity": "minor" | "major" | "blocker",
  "concerns": ["specific, actionable concern"],
  "verdict": "one sentence summary"
}
"""


async def _critic(
    llm: Any,
    user_request: str,
    config: dict[str, Any],
    judge_summary: str,
) -> dict[str, Any]:
    """Second-pass adversarial critic. Returns severity + list of concerns."""
    payload = {
        "user_request": user_request,
        "judge_summary": judge_summary,
        "config": config,
    }
    try:
        resp = await llm.complete(
            messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
            system=_CRITIC_SYSTEM,
            model="claude-sonnet-4-5-20250929",
            temperature=0.1,
        )
    except Exception as e:
        return {"severity": "minor", "concerns": [], "verdict": f"critic failed: {e}"}
    text = resp.content.strip()
    if "{" not in text:
        return {"severity": "minor", "concerns": [], "verdict": "critic returned no JSON"}
    try:
        data = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except Exception as e:
        return {"severity": "minor", "concerns": [], "verdict": f"critic bad JSON: {e}"}
    data.setdefault("severity", "minor")
    data.setdefault("concerns", [])
    data.setdefault("verdict", "")
    # Normalise severity values
    sev = str(data["severity"]).strip().lower()
    if sev not in ("minor", "major", "blocker"):
        sev = "minor"
    data["severity"] = sev
    return data


async def run_iterative_build(
    *,
    user_request: str,
    mode: str,
    max_iterations: int,
    llm: Any,
    generator_fn: Callable[[str, str, str], Awaitable[dict[str, Any]]],
    validator_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    dry_run_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    critic_fn: Callable[[dict[str, Any], str], Awaitable[dict[str, Any]]] | None = None,
    execute_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run the iterative build. Yields event dicts the caller streams to the UI."""
    previous_sig: str | None = None
    previous_state: IterationState | None = None

    for i in range(1, max_iterations + 1):
        state = IterationState(iteration=i)
        yield {"event": "iteration_start", "iteration": i}

        # Build repair context from whatever the previous iteration left behind.
        repair = _build_repair_context(previous_state) if previous_state else ""

        try:
            config = await generator_fn(user_request, mode, repair)
        except Exception as e:
            yield {"event": "final_blocked", "reason": f"generation_failed: {e}", "iteration": i}
            return
        state.config = config
        yield {
            "event": "generated",
            "iteration": i,
            "name": config.get("name"),
            "mode": config.get("mode"),
            "node_count": len((config.get("pipeline_config") or {}).get("nodes") or []),
            "tool_count": len(config.get("tools") or []),
        }

        yield {"event": "validating", "iteration": i}
        try:
            val = await validator_fn(config)
        except Exception as e:
            yield {"event": "final_blocked", "reason": f"validator_failed: {e}", "iteration": i}
            return
        tier1 = val.get("tier1") or {}
        tier2 = val.get("tier2") or {}
        state.tier1_errors = tier1.get("errors") or []
        state.tier2_errors = tier2.get("errors") or []
        state.tier2_warnings = tier2.get("warnings") or []
        yield {"event": "validation_result", "iteration": i, "tier1": tier1, "tier2": tier2}

        if dry_run_fn is not None and config.get("mode") == "pipeline" and not state.tier1_errors:
            yield {"event": "dry_running", "iteration": i}
            try:
                dry = await dry_run_fn(config)
            except Exception as e:
                dry = {"ok": False, "failures": [{"node_id": "", "reason": str(e)}], "trace": ""}
            state.dry_run_failures = dry.get("failures") or []
            yield {"event": "dry_run_result", "iteration": i,
                   "ok": bool(dry.get("ok")),
                   "failures": state.dry_run_failures,
                   "trace_excerpt": (dry.get("trace") or "")[:2000]}
        else:
            dry = {"ok": True, "trace": ""}

        has_blocking = bool(state.tier1_errors) or bool(state.tier2_errors) or bool(state.dry_run_failures)

        if not has_blocking:
            yield {"event": "judging", "iteration": i}
            judge = await _judge(llm, user_request, config, dry.get("trace", ""))
            state.judge_passed = bool(judge.get("passed"))
            state.judge_score = int(judge.get("score") or 0)
            state.judge_suggestions = [str(s) for s in judge.get("suggestions") or []]
            state.judge_missing = [str(s) for s in judge.get("missing_steps") or []]
            yield {"event": "judge_result", "iteration": i, **judge}

            if state.judge_passed:
                if critic_fn is not None:
                    yield {"event": "critiquing", "iteration": i}
                    try:
                        crit = await critic_fn(config, judge.get("summary", ""))
                    except Exception as e:
                        crit = {"severity": "minor", "concerns": [], "verdict": f"critic error: {e}"}
                    state.critic_severity = crit.get("severity", "minor")
                    state.critic_concerns = [str(c) for c in (crit.get("concerns") or [])]
                    yield {"event": "critic_result", "iteration": i, **crit}
                    if state.critic_severity in ("major", "blocker"):
                        # Don't accept yet — feed concerns into repair context
                        previous_sig = state.error_signature()
                        previous_state = state
                        yield {"event": "iteration_end", "iteration": i,
                               "has_blocking": True, "judge_passed": True,
                               "judge_score": state.judge_score,
                               "critic_severity": state.critic_severity}
                        continue

                if execute_fn is not None:
                    yield {"event": "auto_testing", "iteration": i}
                    try:
                        test = await execute_fn(config)
                    except Exception as e:
                        test = {"ok": False, "error": str(e)}
                    state.test_ran = True
                    state.test_ok = bool(test.get("ok"))
                    state.test_error = str(test.get("error") or "")
                    yield {"event": "auto_test_result", "iteration": i, **test}
                    if not state.test_ok:
                        previous_sig = state.error_signature()
                        previous_state = state
                        yield {"event": "iteration_end", "iteration": i,
                               "has_blocking": True, "judge_passed": True,
                               "test_ran": True, "test_ok": False}
                        continue

                # All gates passed.
                yield {"event": "final_success", "iteration": i, "config": config,
                       "summary": judge.get("summary", ""), "score": state.judge_score,
                       "critic_severity": state.critic_severity,
                       "test_ran": state.test_ran, "test_ok": state.test_ok}
                return

        sig = state.error_signature()
        if previous_sig is not None and sig == previous_sig and sig != "":
            yield {
                "event": "final_blocked",
                "iteration": i,
                "reason": "same_errors_twice",
                "config": config,
                "tier1_errors": state.tier1_errors,
                "tier2_errors": state.tier2_errors,
                "dry_run_failures": state.dry_run_failures,
            }
            return
        previous_sig = sig

        yield {"event": "iteration_end", "iteration": i,
               "has_blocking": has_blocking,
               "judge_passed": state.judge_passed,
               "judge_score": state.judge_score}
        previous_state = state

    # Max iterations exhausted.
    yield {"event": "final_blocked", "iteration": max_iterations,
           "reason": "max_iterations_exhausted",
           "config": state.config}
