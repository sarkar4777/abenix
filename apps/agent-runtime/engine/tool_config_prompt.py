"""Prompt text derived from an agent's tool_config. Shared by the API inline path and the consumer."""

from __future__ import annotations

from typing import Any


def build_tool_config_prompt(
    base_prompt: str,
    tool_config: dict[str, Any] | None,
) -> str:
    """Append per-tool usage guidelines to the system prompt when tool_config is set."""
    if not tool_config:
        return base_prompt or ""

    lines: list[str] = []
    for tool_name, tc in tool_config.items():
        if not isinstance(tc, dict):
            continue
        parts: list[str] = []
        instructions = (tc.get("usage_instructions") or "").strip()
        if instructions:
            parts.append(instructions)
        max_calls = tc.get("max_calls") or 0
        if isinstance(max_calls, (int, float)) and max_calls > 0:
            parts.append(f"Maximum {int(max_calls)} calls per execution.")
        if tc.get("require_approval"):
            parts.append(
                "Requires human approval before each call — explain why you need it."
            )
        defaults = dict(tc.get("parameter_defaults") or {})
        policy = defaults.pop("policy", None) if tool_name == "device_command" else None
        if tool_name == "device_command":
            parts.append(f"Command policy: {command_policy_words(policy)}")
        if defaults:
            defaults_str = ", ".join(f"{k}={v}" for k, v in defaults.items())
            parts.append(f"Default parameters: {defaults_str}")
        if parts:
            lines.append(f"- **{tool_name}**: {' '.join(parts)}")

    if not lines:
        return base_prompt or ""

    section = "\n\n## Tool Usage Guidelines\n" + "\n".join(lines)
    return (base_prompt or "").rstrip() + section


def command_policy_words(policy: Any) -> str:
    """device_command's policy in words the model can follow."""
    if not isinstance(policy, dict) or not policy.get("assets"):
        return "none set yet, so every command is refused until the owner sets one."
    mode = policy.get("approval") or "always"
    ask = {
        "always": "A person approves every command first.",
        "never": "Commands go out without asking.",
        "tier": f"The workspace rule for {policy.get('tier') or 'high'} risk decides whether a person approves.",
    }.get(mode, "")
    return (
        f"may command {', '.join(map(str, policy.get('assets') or []))}; "
        f"signals {', '.join(map(str, policy.get('signals') or [])) or 'none'}. {ask} "
        f"At most {policy.get('rate_per_minute') or 6} commands a minute."
    )


def append_mcp_warnings(prompt: str, warnings: list[str] | None) -> str:
    """Tell the model which MCP servers did not come up this run."""
    if not warnings:
        return prompt or ""
    section = "\n\n## Tool availability\n" + "\n".join(f"- {w}" for w in warnings)
    return (prompt or "").rstrip() + section
