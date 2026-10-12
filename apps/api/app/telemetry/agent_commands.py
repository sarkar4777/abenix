"""What an agent's device_command may do: the policy on its tool configuration, checked in plain words.

The policy lives on the agent at tool_config.device_command.parameter_defaults.policy:
{"assets": ["groundwork/ipc-ex1", "tag:haul"], "signals": ["Mode/Set"], "approval": "always",
 "tier": "high", "rate_per_minute": 6, "confirm_timeout_ms": 3000}
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any

TOOL = "device_command"
APPROVAL_MODES = ("never", "tier", "always")
TIERS = ("low", "medium", "high", "critical")
DEFAULT_RATE = 6
MAX_RATE = 600
DEFAULT_CONFIRM_MS = 3000
MAX_CONFIRM_MS = 10000
MAX_PATTERNS = 100
GATE_KIND = "telemetry.command"
_PATTERN = re.compile(r"^[^\s#+]{1,300}$")

NO_POLICY = (
    "This agent has no command policy yet, so device_command cannot send anything. "
    "Its owner picks the assets and signals it may command in the agent builder: "
    "open the agent, click device_command and fill in What it may touch."
)


def policy_of(agent: Any) -> dict[str, Any] | None:
    """The stored policy of an agent row, or None when it has none."""
    mc = getattr(agent, "model_config_", None) or {}
    tc = (mc.get("tool_config") or {}).get(TOOL) or {}
    pol = (tc.get("parameter_defaults") or {}).get("policy")
    return pol if isinstance(pol, dict) else None


def clean(raw: Any) -> tuple[dict[str, Any], dict[str, str]]:
    """The policy as stored, plus a plain message per field that is wrong."""
    err: dict[str, str] = {}
    raw = raw if isinstance(raw, dict) else {}

    def patterns(key: str, what: str) -> list[str]:
        v = raw.get(key) or []
        if isinstance(v, str):
            v = re.split(r"[\n,]", v)
        if not isinstance(v, list):
            err[key] = f"List the {what} one per line."
            return []
        out: list[str] = []
        for x in v:
            s = str(x or "").strip()
            if not s:
                continue
            if not _PATTERN.match(s):
                err[key] = (
                    f"{s[:40]!r} cannot be used, patterns have no spaces, # or +."
                )
                continue
            if s not in out:
                out.append(s)
        if len(out) > MAX_PATTERNS:
            err[key] = f"Keep it to {MAX_PATTERNS} {what} or fewer."
        return out[:MAX_PATTERNS]

    assets = patterns("assets", "assets")
    signals = patterns("signals", "signals")
    mode = str(raw.get("approval") or "always").strip().lower()
    if mode not in APPROVAL_MODES:
        err["approval"] = "Choose never, by risk tier, or always."
        mode = "always"
    tier = str(raw.get("tier") or "high").strip().lower()
    if tier not in TIERS:
        err["tier"] = "Choose low, medium, high or critical."
        tier = "high"
    rate = _int(raw.get("rate_per_minute"), DEFAULT_RATE)
    if rate < 1 or rate > MAX_RATE:
        err["rate_per_minute"] = f"Allow from 1 to {MAX_RATE} commands a minute."
        rate = max(1, min(MAX_RATE, rate))
    confirm = _int(raw.get("confirm_timeout_ms"), DEFAULT_CONFIRM_MS)
    if confirm < 0 or confirm > MAX_CONFIRM_MS:
        err["confirm_timeout_ms"] = (
            f"Wait from 0 to {MAX_CONFIRM_MS} ms for the asset to confirm."
        )
        confirm = max(0, min(MAX_CONFIRM_MS, confirm))
    return {
        "assets": assets,
        "signals": signals,
        "approval": mode,
        "tier": tier,
        "rate_per_minute": rate,
        "confirm_timeout_ms": confirm,
    }, err


def _int(v: Any, default: int) -> int:
    if v in (None, ""):
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return -1


def key(g: str, n: str, d: str = "") -> str:
    return f"{g}/{n}/{d or ''}"


def split_key(s: str) -> tuple[str, str, str] | None:
    parts = str(s or "").strip().strip("/").split("/")
    if len(parts) < 2 or not parts[0] or not parts[1] or len(parts) > 3:
        return None
    return parts[0], parts[1], parts[2] if len(parts) == 3 else ""


def asset_matches(
    pattern: str, g: str, n: str, d: str, tags: list[str], atype: str | None
) -> bool:
    p = pattern.strip()
    low = p.lower()
    if low.startswith("tag:"):
        return low[4:].strip() in {t.lower() for t in tags or []}
    if low.startswith("type:"):
        return (atype or "") == low[5:].strip()
    segs = p.strip("/").split("/")
    if len(segs) == 1:
        segs = [segs[0], "*", "*"]
    elif len(segs) == 2:
        segs = [segs[0], segs[1], "*"]
    elif len(segs) > 3:
        return False
    return all(fnmatch.fnmatchcase(v, s) for v, s in zip((g, n, d or ""), segs))


def asset_allowed(
    policy: dict[str, Any],
    g: str,
    n: str,
    d: str,
    tags: list[str] | None = None,
    atype: str | None = None,
) -> bool:
    return any(
        asset_matches(p, g, n, d, tags or [], atype) for p in policy.get("assets") or []
    )


def signal_allowed(policy: dict[str, Any], signal: str) -> bool:
    return any(fnmatch.fnmatchcase(signal, p) for p in policy.get("signals") or [] if p)


def words_list(items: list[str], empty: str = "nothing") -> str:
    items = [str(x) for x in items or []]
    if not items:
        return empty
    if len(items) <= 4:
        return ", ".join(items)
    return ", ".join(items[:4]) + f" and {len(items) - 4} more"


def refusal_asset(policy: dict[str, Any], where: str) -> str:
    return (
        f"Not sent. This agent may not command {where}. Its owner allows "
        f"{words_list(policy.get('assets') or [])}. Change it in the agent builder, "
        "device_command, What it may touch."
    )


def refusal_signal(policy: dict[str, Any], signal: str, where: str) -> str:
    return (
        f"Not sent. This agent may not set {signal} on {where}. Its owner allows the signals "
        f"{words_list(policy.get('signals') or [])}. Change it in the agent builder, "
        "device_command, What it may touch."
    )


def approval_words(policy: dict[str, Any]) -> str:
    mode = policy.get("approval")
    if mode == "never":
        return "sends without asking"
    if mode == "tier":
        return f"follows the workspace rule for {policy.get('tier', 'high')} risk"
    return "asks a person every time"


def describe(policy: dict[str, Any] | None) -> str:
    """One plain sentence, for the agent's prompt and the builder."""
    if not policy:
        return NO_POLICY
    return (
        f"May command {words_list(policy.get('assets') or [])}, signals "
        f"{words_list(policy.get('signals') or [])}. It {approval_words(policy)}, "
        f"at most {policy.get('rate_per_minute', DEFAULT_RATE)} commands a minute."
    )


def approval_needed(
    policy: dict[str, Any], tier_action: str | None, earned: bool
) -> tuple[bool, str, str | None]:
    """Whether a person must approve, why, and a refusal when the workspace blocks it."""
    if earned:
        return (
            False,
            "Earned Autonomy governs this agent's commands, its level decides.",
            None,
        )
    mode = policy.get("approval") or "always"
    if mode == "always":
        return True, "The agent's policy asks a person before every command.", None
    if mode == "tier":
        tier = policy.get("tier") or "high"
        act = tier_action or "allow"
        if act == "block":
            return (
                False,
                "",
                f"Not sent. The workspace blocks {tier} risk tool calls. "
                "An admin can change it under Admin, Risk tiers.",
            )
        if act == "approval":
            return (
                True,
                f"The workspace asks a person before {tier} risk tool calls.",
                None,
            )
        return (
            False,
            f"The workspace lets {tier} risk tool calls run without asking.",
            None,
        )
    return False, "The agent's policy sends commands without asking.", None


def rate_key(tenant: Any, agent_id: Any, minute: int) -> str:
    return f"tel:agentcmd:{tenant}:{agent_id}:{minute}"


def same_command(payload: dict[str, Any], want: dict[str, Any]) -> bool:
    """An approval only covers the exact command it showed."""
    a = payload.get("command") or {}
    for k in ("group", "node", "device", "signal"):
        if str(a.get(k) or "") != str(want.get(k) or ""):
            return False
    return norm_value(a.get("value")) == norm_value(want.get("value"))


def norm_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        f = float(v)
        return str(int(f)) if f.is_integer() else repr(f)
    s = str(v if v is not None else "").strip()
    if s.lower() in ("true", "false"):
        return s.lower()
    try:
        f = float(s)
        return str(int(f)) if f.is_integer() else repr(f)
    except ValueError:
        return s
