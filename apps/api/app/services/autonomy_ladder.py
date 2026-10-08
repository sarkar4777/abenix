"""Earned autonomy scoring and ladder rules. Pure functions, no database."""

from __future__ import annotations

import copy
import math
from datetime import datetime, timezone
from typing import Any, Iterable

LEVELS: dict[int, dict[str, str]] = {
    0: {"key": "off", "label": "Off", "help": "The agent cannot take this action"},
    1: {
        "key": "watching",
        "label": "Watching",
        "help": "The agent says what it would do. Nothing runs",
    },
    2: {
        "key": "asks_first",
        "label": "Asks first",
        "help": "A person approves, edits or rejects, then it runs",
    },
    3: {
        "key": "within_limits",
        "label": "Acts within limits",
        "help": "Runs alone inside the limits with a confident prediction, otherwise asks first",
    },
    4: {
        "key": "acts_reports",
        "label": "Acts and reports",
        "help": "Runs and reports after. Limits and kill switches still apply",
    },
}
MAX_LEVEL = 4

DEFAULT_POLICY: dict[str, Any] = {
    "to_asks_first": {"min_reviews": 20, "min_agreement_lb": 0.70},
    "to_within_limits": {
        "min_executed": 50,
        "min_accuracy_lb": 0.85,
        "min_no_edit_rate": 0.80,
        "harm_free_days": 30,
        "min_days_at_level": 14,
        "max_unknown_rate": 0.20,
        "max_reject_rate": 0.30,
    },
    "to_acts_reports": {
        "min_executed": 200,
        "min_accuracy_lb": 0.95,
        "harm_free_days": 60,
        "min_days_at_level": 14,
        "max_unknown_rate": 0.20,
        "max_reject_rate": 0.20,
    },
    "window": 50,
    "demote_margin": 0.10,
    "revision_recheck": 10,
}

# the policy section that governs the step up from each level
STEP_FOR_LEVEL = {1: "to_asks_first", 2: "to_within_limits", 3: "to_acts_reports"}

TIER_CEILING = {"critical": 2, "high": 3, "medium": 4, "low": 4}

# fewer scored actions than this never triggers an accuracy demotion
MIN_DEMOTE_SAMPLE = 5


def level_label(level: Any) -> str:
    try:
        return LEVELS[int(level)]["label"]
    except (KeyError, TypeError, ValueError):
        return "Unknown"


def level_help(level: Any) -> str:
    try:
        return LEVELS[int(level)]["help"]
    except (KeyError, TypeError, ValueError):
        return ""


def merge_policy(*layers: dict[str, Any] | None) -> dict[str, Any]:
    out = copy.deepcopy(DEFAULT_POLICY)
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        for k, v in layer.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = {**out[k], **v}
            elif v is not None:
                out[k] = v
    return out


def tier_ceiling(tier: Any) -> int:
    return TIER_CEILING.get(str(tier or "low").strip().lower(), 4)


def effective_ceiling(
    tier: Any, action_type_ceiling: Any = None, grant_ceiling: Any = None
) -> int:
    """The lowest of the tier ceiling, the action type's and the grant's own."""
    caps = [tier_ceiling(tier)]
    for c in (action_type_ceiling, grant_ceiling):
        if c is not None:
            try:
                caps.append(int(c))
            except (TypeError, ValueError):
                continue
    return max(0, min(min(caps), MAX_LEVEL))


def wilson_lower_bound(successes: float, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = max(0.0, min(1.0, successes / n))
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def band_ok(prediction: dict[str, Any] | None, max_band_width: Any) -> bool:
    """A band wider than the allowed relative width counts as no prediction."""
    if not isinstance(prediction, dict):
        return False
    value = prediction.get("value")
    lo, hi, val = (
        _num(prediction.get("low")),
        _num(prediction.get("high")),
        _num(value),
    )
    if val is None:
        # categorical, nothing to measure
        return value is not None
    if lo is None or hi is None:
        return True
    if hi < lo:
        return False
    limit = _num(max_band_width)
    if limit is None:
        return True
    if val == 0:
        return (hi - lo) <= limit
    return (hi - lo) / abs(val) <= limit + 1e-9


def within_band(prediction: dict[str, Any] | None, actual: Any) -> bool | None:
    """True when the outcome lands inside the band, categorical values must match."""
    if not isinstance(prediction, dict) or actual is None:
        return None
    a = _num(actual)
    lo, hi, val = (
        _num(prediction.get("low")),
        _num(prediction.get("high")),
        _num(prediction.get("value")),
    )
    if a is None or (val is None and lo is None and hi is None):
        want = prediction.get("value")
        if want is None:
            return None
        return str(want).strip().lower() == str(actual).strip().lower()
    if lo is None and hi is None:
        return a == val
    if lo is not None and a < lo:
        return False
    if hi is not None and a > hi:
        return False
    return True


def agreement_for(status: str | None, reviewer_answer: str | None) -> float | None:
    """Watching: agree 1, different 0, unsure left out. Asks first: approve 1, edit 0.5, reject 0."""
    if reviewer_answer == "agree":
        return 1.0
    if reviewer_answer == "different":
        return 0.0
    if reviewer_answer == "unsure":
        return None
    if status in ("approved",):
        return 1.0
    if status == "edited":
        return 0.5
    if status == "rejected":
        return 0.0
    return None


def score_action(
    prediction: dict[str, Any] | None,
    actual: Any,
    max_band_width: Any = None,
    *,
    status: str | None = None,
    reviewer_answer: str | None = None,
    harm: bool = False,
) -> dict[str, Any]:
    return {
        "within_band": within_band(prediction, actual),
        "band_ok": band_ok(prediction, max_band_width),
        "agreement": agreement_for(status, reviewer_answer),
        "harm": bool(harm),
    }


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _aware(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


def held(action: Any) -> bool:
    s = _get(action, "score") or {}
    return bool(s.get("within_band") is True and s.get("band_ok") is not False)


def is_scored(action: Any) -> bool:
    return _get(action, "outcome_status") in ("observed", "manual") and isinstance(
        _get(action, "score"), dict
    )


def compute_stats(
    actions: Iterable[Any],
    *,
    now: datetime | None = None,
    window: int = 50,
    level_since: Any = None,
    created_at: Any = None,
    current_config_hash: str | None = None,
    eval_passing: bool | None = None,
) -> dict[str, Any]:
    """Track record numbers for one grant from its ledger rows, newest first or not."""
    now = _aware(now) or datetime.now(timezone.utc)
    rows = sorted(
        list(actions),
        key=lambda a: _aware(_get(a, "created_at")) or now,
        reverse=True,
    )
    scored_rows = [a for a in rows if is_scored(a)]
    win = scored_rows[: max(1, int(window or 50))]
    held_n = sum(1 for a in win if held(a))
    reviews = [
        a
        for a in rows
        if _get(a, "reviewer_answer") in ("agree", "different")
        and _get(a, "mode") in ("watching", None)
    ]
    review_win = reviews[: max(1, int(window or 50))]
    agree_n = sum(1 for a in review_win if _get(a, "reviewer_answer") == "agree")
    # a proposal keeps the person's answer in score.agreement after it runs
    approved = edited = rejected = 0
    for a in rows:
        if _get(a, "reviewer_answer"):
            continue
        agr = (_get(a, "score") or {}).get("agreement")
        if agr is None:
            agr = agreement_for(_get(a, "status"), None)
        if agr is None:
            continue
        if agr >= 1:
            approved += 1
        elif agr > 0:
            edited += 1
        else:
            rejected += 1
    executed = sum(1 for a in rows if _get(a, "status") == "executed")
    unknown = sum(1 for a in rows if _get(a, "outcome_status") == "unknown")
    harm_rows = [a for a in rows if _get(a, "harm")]
    last_harm = max(
        (_aware(_get(a, "created_at")) or now for a in harm_rows), default=None
    )
    since = _aware(level_since)
    harm_since_level = sum(
        1
        for a in harm_rows
        if since is None or (_aware(_get(a, "created_at")) or now) >= since
    )
    harm_30d = sum(
        1
        for a in harm_rows
        if (now - (_aware(_get(a, "created_at")) or now)).total_seconds() <= 30 * 86400
    )
    record_start = _aware(created_at) or (
        _aware(_get(rows[-1], "created_at")) if rows else None
    )
    if last_harm is not None:
        harm_free_days = max(0, (now - last_harm).days)
    elif record_start is not None:
        harm_free_days = max(0, (now - record_start).days)
    else:
        harm_free_days = 0
    decided = approved + edited + rejected
    revision_rows = [
        a
        for a in scored_rows
        if current_config_hash and _get(a, "agent_config_hash") == current_config_hash
    ]
    spark: list[int | None] = []
    for a in scored_rows[:20][::-1]:
        wb = (_get(a, "score") or {}).get("within_band")
        spark.append(None if wb is None else (1 if held(a) else 0))
    acc = held_n / len(win) if win else None
    agr = agree_n / len(review_win) if review_win else None
    return {
        "scored": len(scored_rows),
        "held": sum(1 for a in scored_rows if held(a)),
        "window_scored": len(win),
        "window_held": held_n,
        "accuracy_pct": round(acc * 100) if acc is not None else None,
        "accuracy_lb": wilson_lower_bound(held_n, len(win)) if win else 0.0,
        "accuracy_lb_pct": (
            round(wilson_lower_bound(held_n, len(win)) * 100) if win else None
        ),
        "reviews": len(reviews),
        "agreement_pct": round(agr * 100) if agr is not None else None,
        "agreement_lb": (
            wilson_lower_bound(agree_n, len(review_win)) if review_win else 0.0
        ),
        "executed": executed,
        "pending_reviews": sum(
            1
            for a in rows
            if _get(a, "status") == "watching" and not _get(a, "reviewer_answer")
        ),
        "approved": approved,
        "edited": edited,
        "rejected": rejected,
        "no_edit_rate": (approved / (approved + edited)) if approved + edited else None,
        "reject_rate": (rejected / decided) if decided else 0.0,
        "unknown": unknown,
        "unknown_rate": (
            unknown / (unknown + len(scored_rows))
            if unknown + len(scored_rows)
            else 0.0
        ),
        "harm_30d": harm_30d,
        "harm_since_level": harm_since_level,
        "harm_free_days": harm_free_days,
        "last_harm_at": last_harm.isoformat() if last_harm else None,
        "days_at_level": max(0, (now - since).days) if since else 0,
        "current_config_hash": current_config_hash,
        "revision_scored": len(revision_rows),
        "revision_correct": sum(1 for a in revision_rows if held(a)),
        "eval_passing": eval_passing,
        "spark": spark,
    }


def _pct(v: float | None) -> str:
    return f"{round((v or 0) * 100)}%"


def _req(
    key: str, label: str, current: Any, needed: Any, met: bool, fix: dict | None = None
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "current": current,
        "needed": needed,
        "met": bool(met),
        "fix": fix if not met else None,
    }


def revision_changed(grant: Any, stats: dict[str, Any]) -> bool:
    cur = stats.get("current_config_hash")
    was = _get(grant, "agent_config_hash")
    return bool(cur and was and cur != was)


def requirements_for(
    grant: Any, stats: dict[str, Any], policy: dict[str, Any], next_level: int
) -> list[dict[str, Any]]:
    gid = str(_get(grant, "id") or "")
    page = f"/autonomy/{gid}" if gid else "/autonomy"
    step = policy.get(STEP_FOR_LEVEL.get(next_level - 1, ""), {}) or {}
    out: list[dict[str, Any]] = []
    if next_level == 1:
        return out
    if next_level == 2:
        need = int(step.get("min_reviews", 20))
        have = int(stats.get("reviews") or 0)
        out.append(
            _req(
                "min_reviews",
                f"{have} of {need} reviews",
                have,
                need,
                have >= need,
                {"label": "Answer watching reviews", "href": "/approvals?tab=reviews"},
            )
        )
        lb = float(stats.get("agreement_lb") or 0.0)
        thr = float(step.get("min_agreement_lb", 0.7))
        out.append(
            _req(
                "min_agreement_lb",
                f"Agreement {_pct(lb)} (needs {_pct(thr)})",
                round(lb * 100),
                round(thr * 100),
                have > 0 and lb >= thr - 1e-9,
                {"label": "See where people disagreed", "href": f"{page}#timeline"},
            )
        )
        return out
    need = int(step.get("min_executed", 50))
    have = int(stats.get("scored") or 0)
    out.append(
        _req(
            "min_executed",
            f"{have} of {need} scored actions",
            have,
            need,
            have >= need,
            {
                "label": "See the actions waiting for an outcome",
                "href": f"{page}#timeline",
            },
        )
    )
    lb = float(stats.get("accuracy_lb") or 0.0)
    thr = float(step.get("min_accuracy_lb", 0.85))
    out.append(
        _req(
            "min_accuracy_lb",
            f"Accuracy {_pct(lb)} (needs {_pct(thr)})",
            round(lb * 100),
            round(thr * 100),
            have > 0 and lb >= thr - 1e-9,
            {"label": "See the misses", "href": f"{page}#chart"},
        )
    )
    if "min_no_edit_rate" in step:
        rate = stats.get("no_edit_rate")
        thr = float(step["min_no_edit_rate"])
        out.append(
            _req(
                "min_no_edit_rate",
                (
                    f"Approved without edits {_pct(rate)} (needs {_pct(thr)})"
                    if rate is not None
                    else f"No approvals yet (needs {_pct(thr)} approved without edits)"
                ),
                round(rate * 100) if rate is not None else None,
                round(thr * 100),
                rate is not None and rate >= thr - 1e-9,
                {"label": "Open approvals", "href": "/approvals"},
            )
        )
    days = int(step.get("harm_free_days", 0))
    free = int(stats.get("harm_free_days") or 0)
    harmed = bool(stats.get("last_harm_at"))
    out.append(
        _req(
            "harm_free_days",
            (
                f"No harm for {free} days (needs {days})"
                if harmed or days
                else "No harm flagged"
            ),
            free,
            days,
            (free >= days) and not (days == 0 and stats.get("harm_since_level")),
            {"label": "See the harm flag", "href": f"{page}#timeline"},
        )
    )
    days_needed = int(step.get("min_days_at_level", 0))
    at = int(stats.get("days_at_level") or 0)
    out.append(
        _req(
            "min_days_at_level",
            f"{min(at, days_needed)} of {days_needed} days at this level",
            at,
            days_needed,
            at >= days_needed,
        )
    )
    max_unknown = float(step.get("max_unknown_rate", 0.2))
    ur = float(stats.get("unknown_rate") or 0.0)
    out.append(
        _req(
            "max_unknown_rate",
            f"Outcomes missing for {_pct(ur)} (at most {_pct(max_unknown)})",
            round(ur * 100),
            round(max_unknown * 100),
            ur <= max_unknown + 1e-9,
            {"label": "Connect a source for outcomes", "href": f"{page}#outcome"},
        )
    )
    max_rej = float(step.get("max_reject_rate", 0.3))
    rr = float(stats.get("reject_rate") or 0.0)
    out.append(
        _req(
            "max_reject_rate",
            f"Rejected {_pct(rr)} of proposals (at most {_pct(max_rej)})",
            round(rr * 100),
            round(max_rej * 100),
            rr <= max_rej + 1e-9,
            {"label": "See the rejected proposals", "href": f"{page}#timeline"},
        )
    )
    if next_level == 3 and stats.get("eval_passing") is not None:
        ok = bool(stats["eval_passing"])
        out.append(
            _req(
                "eval_passing",
                (
                    "Evaluation suite passing"
                    if ok
                    else "The latest evaluation run did not pass"
                ),
                ok,
                True,
                ok,
                {"label": "Open evaluations", "href": "/evals"},
            )
        )
    if next_level > 2 and revision_changed(grant, stats):
        recheck = int(policy.get("revision_recheck", 10))
        got = int(stats.get("revision_correct") or 0)
        out.append(
            _req(
                "revision_recheck",
                f"{min(got, recheck)} of {recheck} correct actions since the agent changed",
                got,
                recheck,
                got >= recheck,
                {"label": "See recent actions", "href": f"{page}#timeline"},
            )
        )
    return out


def evaluate(
    grant: Any,
    stats: dict[str, Any],
    policy: dict[str, Any] | None,
    now: datetime | None = None,
    *,
    ceiling: int | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    """What the next step needs, whether it is met, and any demotion that applies now."""
    policy = merge_policy(policy) if policy is not None else merge_policy()
    level = int(_get(grant, "level") or 0)
    cap = (
        int(ceiling)
        if ceiling is not None
        else effective_ceiling(tier, None, _get(grant, "ceiling"))
    )
    demote_to, demote_reason = demotion_for(grant, stats, policy, cap)
    next_level = level + 1 if level < MAX_LEVEL else None
    out: dict[str, Any] = {
        "level": level,
        "level_label": level_label(level),
        "next_level": next_level,
        "next_label": level_label(next_level) if next_level is not None else None,
        "requirements": [],
        "ready": False,
        "blocked_by_ceiling": False,
        "ceiling": cap,
        "demote_to": demote_to,
        "demote_reason": demote_reason,
    }
    if next_level is None:
        return out
    reqs = requirements_for(grant, stats, policy, next_level)
    if next_level > cap:
        out["blocked_by_ceiling"] = True
        agent_id = str(_get(grant, "agent_id") or "")
        reqs.append(
            _req(
                "ceiling",
                f"This agent stops at {level_label(cap)} for this action",
                cap,
                next_level,
                False,
                {
                    "label": "Review the agent's risk tier",
                    "href": f"/agents/{agent_id}/info" if agent_id else "/agents",
                },
            )
        )
    if str(_get(grant, "state") or "active") != "active":
        reqs.append(
            _req(
                "state",
                "Paused, resume it before promoting",
                False,
                True,
                False,
                {
                    "label": "Resume",
                    "href": f"/autonomy/{_get(grant, 'id') or ''}",
                },
            )
        )
    out["requirements"] = reqs
    out["ready"] = (
        demote_to is None
        and not out["blocked_by_ceiling"]
        and all(r["met"] for r in reqs)
    )
    return out


def demotion_for(
    grant: Any, stats: dict[str, Any], policy: dict[str, Any], ceiling: int
) -> tuple[int | None, str | None]:
    """The level the grant must drop to now and why, the strictest rule winning."""
    level = int(_get(grant, "level") or 0)
    if level <= 0:
        return None, None
    found: list[tuple[int, str]] = []
    if level > ceiling:
        found.append(
            (ceiling, f"The ceiling for this agent is now {level_label(ceiling)}")
        )
    if level > 2 and int(stats.get("harm_since_level") or 0) > 0:
        found.append((2, "Harm was flagged on one of its actions"))
    if level > 2 and revision_changed(grant, stats):
        recheck = int(policy.get("revision_recheck", 10))
        if int(stats.get("revision_correct") or 0) < recheck:
            found.append(
                (
                    2,
                    "The agent's prompt, model or tools changed, so it asks first until "
                    f"{recheck} actions on the new version score correctly",
                )
            )
    if level >= 3:
        step = policy.get(STEP_FOR_LEVEL[level - 1], {}) or {}
        thr = float(step.get("min_accuracy_lb", 0.85))
        margin = float(policy.get("demote_margin", 0.10))
        if (
            int(stats.get("window_scored") or 0) >= MIN_DEMOTE_SAMPLE
            and float(stats.get("accuracy_lb") or 0.0) < thr - margin - 1e-9
        ):
            found.append(
                (
                    level - 1,
                    f"Accuracy fell to {_pct(stats.get('accuracy_lb'))}, more than "
                    f"{round(margin * 100)} points under the {_pct(thr)} it was promoted on",
                )
            )
    if not found:
        return None, None
    return min(found, key=lambda f: f[0])


def harm_demotion(level: int) -> int:
    """Any harm drops the action type to Asks first at once."""
    return min(int(level), 2)


def attention_for(
    grant: Any, result: dict[str, Any], stats: dict[str, Any]
) -> str | None:
    if int(_get(grant, "level") or 0) == 0:
        return "Turned off"
    if result.get("demote_to") is not None:
        return result.get("demote_reason")
    if result.get("ready"):
        return f"Ready to move to {result.get('next_label')}"
    if float(stats.get("unknown_rate") or 0) > 0.2:
        return "Many outcomes are missing. Connect a source for outcomes"
    return None
