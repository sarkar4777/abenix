from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MAX_TOOL_CALLS = 50
DEFAULT_MAX_OUTPUT_CHARS = 250_000

WHITELISTED_DOMAINS = [
    "api.anthropic.com",
    "api.openai.com",
    "generativelanguage.googleapis.com",
    "api.duckduckgo.com",
    "html.duckduckgo.com",
    "lite.duckduckgo.com",
    "www.alphavantage.co",
    "api.eia.gov",
    "api.airtable.com",
    "api.notion.com",
    "hooks.slack.com",
    "sheets.googleapis.com",
    "api.github.com",
]


@dataclass
class SandboxPolicy:
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS
    allowed_domains: list[str] = field(
        default_factory=lambda: list(WHITELISTED_DOMAINS)
    )
    allow_all_domains: bool = False


@dataclass
class SandboxViolation:
    violation_type: str
    message: str
    timestamp: float = field(default_factory=time.time)


class ExecutionSandbox:
    """Enforces resource limits and network policy for a single agent execution."""

    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self.policy = policy or SandboxPolicy()
        self.start_time: float | None = None
        self.tool_call_count = 0
        self.total_output_chars = 0
        self.violations: list[SandboxViolation] = []

    def start(self) -> None:
        self.start_time = time.monotonic()

    def check_timeout(self) -> bool:
        if self.start_time is None:
            return True
        elapsed = time.monotonic() - self.start_time
        if elapsed > self.policy.timeout_seconds:
            self.violations.append(
                SandboxViolation(
                    violation_type="timeout",
                    message="Execution exceeded {}s timeout (elapsed: {:.1f}s)".format(
                        self.policy.timeout_seconds, elapsed
                    ),
                )
            )
            return False
        return True

    def check_tool_call(self) -> bool:
        if self.tool_call_count >= self.policy.max_tool_calls:
            self.violations.append(
                SandboxViolation(
                    violation_type="tool_limit",
                    message="Exceeded max tool calls ({})".format(
                        self.policy.max_tool_calls
                    ),
                )
            )
            return False
        self.tool_call_count += 1
        return True

    def check_output_size(self, new_output: str) -> bool:
        self.total_output_chars += len(new_output)
        if self.total_output_chars > self.policy.max_output_chars:
            self.violations.append(
                SandboxViolation(
                    violation_type="output_limit",
                    message="Output exceeded {} chars".format(
                        self.policy.max_output_chars
                    ),
                )
            )
            return False
        return True

    def check_domain(self, url: str) -> bool:
        if self.policy.allow_all_domains:
            return True
        parsed = urlparse(url)
        host = parsed.hostname or ""
        for allowed in self.policy.allowed_domains:
            if host == allowed or host.endswith("." + allowed):
                return True
        self.violations.append(
            SandboxViolation(
                violation_type="network_policy",
                message="Domain '{}' not in allowlist".format(host),
            )
        )
        return False

    def add_domain(self, domain: str) -> None:
        if domain not in self.policy.allowed_domains:
            self.policy.allowed_domains.append(domain)

    def get_elapsed_seconds(self) -> float:
        if self.start_time is None:
            return 0.0
        return time.monotonic() - self.start_time

    def get_violations(self) -> list[dict[str, Any]]:
        return [
            {
                "type": v.violation_type,
                "message": v.message,
                "timestamp": v.timestamp,
            }
            for v in self.violations
        ]


async def run_with_timeout(coro: Any, timeout: int) -> Any:
    """Run an async coroutine with a timeout, raising TimeoutError if exceeded."""
    return await asyncio.wait_for(coro, timeout=timeout)
