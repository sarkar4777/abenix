"""Risk tiers: what they are, what each one requires by default, how they combine."""

from __future__ import annotations

import copy
from typing import Any, Iterable

TIERS: tuple[str, ...] = ("low", "medium", "high", "critical")
_RANK = {t: i for i, t in enumerate(TIERS)}

TIER_GUIDE: dict[str, str] = {
    "low": "Reads public or internal data and drafts text a person will read anyway. Mistakes are cheap and visible.",
    "medium": "Writes to internal systems or produces output other teams rely on. Mistakes cost time to unwind.",
    "high": "Affects customers, money, compliance positions or regulated records. Mistakes need a second pair of eyes.",
    "critical": "Irreversible or legally binding actions, filings, payments, or anything a regulator would ask about.",
}

# what a tenant gets before it changes anything
DEFAULT_POLICIES: dict[str, dict[str, Any]] = {
    "low": {
        "publish_approvals": {
            "min_approvers": 0,
            "exclude_author": False,
            "capability": "approvals.sign",
            "escalate_after_hours": 0,
        },
        "tool_call_action": "allow",
        "allowed_models": [],
        "require_output_schema": False,
        "require_eval_pass": False,
    },
    "medium": {
        "publish_approvals": {
            "min_approvers": 0,
            "exclude_author": False,
            "capability": "approvals.sign",
            "escalate_after_hours": 0,
        },
        "tool_call_action": "allow",
        "allowed_models": [],
        "require_output_schema": False,
        "require_eval_pass": False,
    },
    "high": {
        "publish_approvals": {
            "min_approvers": 1,
            "exclude_author": True,
            "capability": "approvals.sign",
            "escalate_after_hours": 24,
        },
        "tool_call_action": "approval",
        "allowed_models": [],
        "require_output_schema": True,
        "require_eval_pass": True,
    },
    "critical": {
        "publish_approvals": {
            "min_approvers": 2,
            "exclude_author": True,
            "capability": "approvals.sign",
            "escalate_after_hours": 4,
        },
        "tool_call_action": "approval",
        "allowed_models": [],
        "require_output_schema": True,
        "require_eval_pass": True,
    },
}

TOOL_CALL_ACTIONS = ("allow", "approval", "block")

# escalation can be set in minutes, 0 is off
ESCALATE_MINUTES_MIN = 1
ESCALATE_MINUTES_MAX = 720 * 60


def escalate_minutes(publish_approvals: dict[str, Any] | None) -> int:
    """Minutes an approval may wait before admins are told, minutes win over hours."""
    pa = publish_approvals or {}
    m = pa.get("escalate_after_minutes")
    if isinstance(m, int) and not isinstance(m, bool) and m > 0:
        return m
    try:
        return max(0, int(pa.get("escalate_after_hours") or 0)) * 60
    except (TypeError, ValueError):
        return 0


def wait_words(minutes: int) -> str:
    if minutes % 60 == 0:
        h = minutes // 60
        return f"{h}h"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60}h {minutes % 60} min"


def normalize(tier: Any, default: str = "low") -> str:
    t = str(tier or "").strip().lower()
    return t if t in _RANK else default


def rank(tier: Any) -> int:
    return _RANK[normalize(tier)]


def highest(tiers: Iterable[Any]) -> str:
    best = "low"
    for t in tiers:
        if t and rank(t) > rank(best):
            best = normalize(t)
    return best


def above(a: Any, b: Any) -> bool:
    return rank(a) > rank(b)


def merged_policy(tier: str, override: dict[str, Any] | None) -> dict[str, Any]:
    """The default for the tier with a tenant's stored changes laid over it."""
    base = copy.deepcopy(DEFAULT_POLICIES[normalize(tier)])
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


def validate_policy(policy: dict[str, Any]) -> list[str]:
    """Problems with a policy a tenant is about to store, empty when it is fine."""
    problems: list[str] = []
    # autonomy holds earned-autonomy thresholds for the tier, see autonomy_ladder
    allowed = set(DEFAULT_POLICIES["low"].keys()) | {"autonomy"}
    for k in policy:
        if k not in allowed:
            problems.append(
                f"{k} is not a policy setting, expected one of {', '.join(sorted(allowed))}"
            )
    pa = policy.get("publish_approvals")
    if pa is not None:
        if not isinstance(pa, dict):
            problems.append("publish_approvals must be an object")
        else:
            n = pa.get("min_approvers", 0)
            if not isinstance(n, int) or n < 0 or n > 10:
                problems.append(
                    "publish_approvals.min_approvers must be a whole number from 0 to 10"
                )
            h = pa.get("escalate_after_hours", 0)
            if not isinstance(h, int) or h < 0 or h > 720:
                problems.append(
                    "publish_approvals.escalate_after_hours must be a whole number from 0 to 720"
                )
            if "escalate_after_minutes" in pa:
                m = pa.get("escalate_after_minutes")
                if (
                    not isinstance(m, int)
                    or isinstance(m, bool)
                    or (
                        m != 0 and not ESCALATE_MINUTES_MIN <= m <= ESCALATE_MINUTES_MAX
                    )
                ):
                    problems.append(
                        "publish_approvals.escalate_after_minutes must be 0, or a whole number "
                        f"from {ESCALATE_MINUTES_MIN} to {ESCALATE_MINUTES_MAX} (30 days)"
                    )
    act = policy.get("tool_call_action")
    if act is not None and act not in TOOL_CALL_ACTIONS:
        problems.append(
            f"tool_call_action must be one of {', '.join(TOOL_CALL_ACTIONS)}"
        )
    rep = policy.get("require_eval_pass")
    if rep is not None and not isinstance(rep, bool):
        problems.append("require_eval_pass must be true or false")
    auto = policy.get("autonomy")
    if auto is not None and not isinstance(auto, dict):
        problems.append("autonomy must be an object of ladder thresholds")
    models = policy.get("allowed_models")
    if models is not None and (
        not isinstance(models, list) or not all(isinstance(m, str) for m in models)
    ):
        problems.append("allowed_models must be a list of model ids")
    return problems


def model_allowed(policy: dict[str, Any], model: str) -> bool:
    allowed = policy.get("allowed_models") or []
    if not allowed:
        return True
    m = (model or "").lower()
    return any(
        m == a.lower() or (a.endswith("*") and m.startswith(a[:-1].lower()))
        for a in allowed
    )


RELEASE_REQUIRED_TIERS = ("high", "critical")
DRAFT_NOT_RELEASED = "DRAFT_NOT_RELEASED"


def draft_needs_release(status: Any, tier: Any) -> bool:
    """A high or critical tier draft has not passed its release checks, so only people testing it may run it."""
    s = str(getattr(status, "value", status) or "").lower()
    return s == "draft" and normalize(tier) in RELEASE_REQUIRED_TIERS


def draft_release_message(name: str, tier: Any) -> str:
    return (
        f"{name} is a {normalize(tier)} risk draft. Publish it first, so it passes the "
        "tier's release checks, before pipelines, triggers, other agents or API keys call it. "
        "You can still test it from the builder and chat."
    )
