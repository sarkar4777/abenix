"""Pure evaluation logic: run scores, run comparison, the publish gate decision and model-change detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


def score_run(cases: Iterable[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """Weighted share of cases that passed. A case that could not run counts as failed."""
    total_w = 0.0
    pass_w = 0.0
    passed = failed = errored = total = 0
    for c in cases:
        total += 1
        w = max(float(c.get("weight") or 0), 0.0)
        total_w += w
        if c.get("status") not in (None, "completed"):
            errored += 1
            failed += 1
        elif c.get("passed"):
            passed += 1
            pass_w += w
        else:
            failed += 1
    if total == 0:
        return {
            "score": None,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errored": 0,
            "threshold_met": False,
        }
    score = pass_w / total_w if total_w > 0 else passed / total
    score = round(score, 4)
    return {
        "score": score,
        "total": total,
        "passed": passed,
        "failed": failed,
        "errored": errored,
        "threshold_met": score + 1e-9 >= float(threshold),
    }


def _key(r: dict[str, Any]) -> str:
    return str(r.get("case_id") or f"name:{r.get('case_name') or ''}")


def compare_results(
    base: list[dict[str, Any]], new: list[dict[str, Any]]
) -> dict[str, Any]:
    """Per case between two runs: what broke, what got fixed, what stayed, what was added or removed."""
    b = {_key(r): r for r in base}
    n = {_key(r): r for r in new}
    out: dict[str, list[dict[str, Any]]] = {
        "regressions": [],
        "improvements": [],
        "still_failing": [],
        "still_passing": [],
        "added": [],
        "removed": [],
    }
    for k, nr in n.items():
        row = {
            "case_id": nr.get("case_id"),
            "case_name": nr.get("case_name"),
            "after": {"passed": bool(nr.get("passed")), "score": nr.get("score")},
        }
        br = b.get(k)
        if br is None:
            out["added"].append(row)
            continue
        row["before"] = {"passed": bool(br.get("passed")), "score": br.get("score")}
        row["score_delta"] = round(
            float(nr.get("score") or 0) - float(br.get("score") or 0), 4
        )
        if br.get("passed") and not nr.get("passed"):
            out["regressions"].append(row)
        elif not br.get("passed") and nr.get("passed"):
            out["improvements"].append(row)
        elif nr.get("passed"):
            out["still_passing"].append(row)
        else:
            out["still_failing"].append(row)
    for k, br in b.items():
        if k not in n:
            out["removed"].append(
                {
                    "case_id": br.get("case_id"),
                    "case_name": br.get("case_name"),
                    "before": {
                        "passed": bool(br.get("passed")),
                        "score": br.get("score"),
                    },
                }
            )
    return {
        **out,
        "counts": {k: len(v) for k, v in out.items()},
    }


@dataclass
class GateResult:
    allowed: bool
    message: str = ""
    required: bool = False
    suites: list[dict[str, Any]] = field(default_factory=list)


def gate_decision(
    *,
    required: bool,
    tier: str,
    config_hash: str | None,
    suites: list[dict[str, Any]],
) -> GateResult:
    """Whether this agent version may be published.

    suites: gating suites, each {id, name, threshold, run}, where run is the latest finished
    baseline run against config_hash (no model override) with its failing case names, or None.
    """
    if not required or not suites:
        return GateResult(True, required=required, suites=[])
    rows: list[dict[str, Any]] = []
    blocked: list[str] = []
    for s in suites:
        run = s.get("run")
        row = {
            "suite_id": str(s.get("id")),
            "name": s.get("name"),
            "threshold": s.get("threshold"),
            "run_id": str(run["id"]) if run else None,
            "score": run.get("score") if run else None,
            "failing_cases": list((run or {}).get("failing_cases") or []),
        }
        if run is None or (config_hash and run.get("config_hash") != config_hash):
            row["state"] = "not_run"
            blocked.append(f"{s.get('name')} has not been run against this version")
        elif not run.get("threshold_met"):
            row["state"] = "failed"
            failing = row["failing_cases"]
            listed = ", ".join(failing[:8]) + (
                f" and {len(failing) - 8} more" if len(failing) > 8 else ""
            )
            pct = round(float(run.get("score") or 0) * 100)
            need = round(float(s.get("threshold") or 0) * 100)
            blocked.append(
                f"{s.get('name')} scored {pct}%, below the {need}% it needs"
                + (f". Failing: {listed}" if listed else "")
            )
        else:
            row["state"] = "passed"
        rows.append(row)
    if not blocked:
        return GateResult(True, required=True, suites=rows)
    msg = (
        f"This is {tier} risk work, so its evaluation suites must pass before a new version is published. "
        + ". ".join(blocked)
        + ". Run the suite on the Evaluations page, fix what fails, then publish again."
    )
    return GateResult(False, msg, required=True, suites=rows)


def model_changed(last_run_model: str | None, current_model: str | None) -> bool:
    """A baseline run exists and the agent now uses a different model than it ran on."""
    if not last_run_model or not current_model:
        return False
    if current_model == "pipeline" or last_run_model == "pipeline":
        return False
    return last_run_model.strip().lower() != current_model.strip().lower()
