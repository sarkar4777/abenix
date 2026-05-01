from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from engine.mcp_client import MCPClient, MCPTool, MCPToolResult

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS_PER_EXECUTION = 10
TOOL_CALL_TIMEOUT_SECONDS = 30.0


@dataclass
class ToolCallRecord:
    tool_name: str
    arguments: dict[str, Any]
    result: str
    is_error: bool
    duration_ms: int
    required_approval: bool
    annotations: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


@dataclass
class MCPSecurityPolicy:
    max_calls_per_execution: int = MAX_TOOL_CALLS_PER_EXECUTION
    call_timeout: float = TOOL_CALL_TIMEOUT_SECONDS
    auto_approve_read_only: bool = True
    block_unapproved_destructive: bool = True
    allowed_domains: list[str] = field(default_factory=list)


class MCPSecurityContext:
    """Tracks and enforces security policies for MCP tool calls within a single execution."""

    def __init__(self, policy: MCPSecurityPolicy | None = None) -> None:
        self.policy = policy or MCPSecurityPolicy()
        self.call_count = 0
        self.audit_log: list[ToolCallRecord] = []
        self._approved_tools: set[str] = set()

    def is_destructive(self, tool: MCPTool) -> bool:
        return bool(tool.annotations.get("destructiveHint"))

    def is_read_only(self, tool: MCPTool) -> bool:
        return bool(tool.annotations.get("readOnlyHint"))

    def requires_approval(self, tool: MCPTool) -> bool:
        if self.is_read_only(tool) and self.policy.auto_approve_read_only:
            return False
        if self.is_destructive(tool):
            return True
        return False

    def approve_tool(self, tool_name: str) -> None:
        self._approved_tools.add(tool_name)

    def check_call_allowed(self, tool: MCPTool) -> tuple[bool, str]:
        if self.call_count >= self.policy.max_calls_per_execution:
            return False, "MCP tool call limit ({}) exceeded for this execution".format(
                self.policy.max_calls_per_execution
            )

        if self.requires_approval(tool) and tool.name not in self._approved_tools:
            if self.policy.block_unapproved_destructive:
                return False, "Tool '{}' is destructive and requires approval".format(tool.name)

        return True, ""

    async def execute_tool(
        self,
        client: MCPClient,
        tool: MCPTool,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        allowed, reason = self.check_call_allowed(tool)
        if not allowed:
            record = ToolCallRecord(
                tool_name=tool.name,
                arguments=arguments,
                result=reason,
                is_error=True,
                duration_ms=0,
                required_approval=self.requires_approval(tool),
                annotations=tool.annotations,
            )
            self.audit_log.append(record)
            return MCPToolResult(content=reason, is_error=True)

        start = time.monotonic()
        try:
            import asyncio
            result = await asyncio.wait_for(
                client.call_tool(tool.name, arguments),
                timeout=self.policy.call_timeout,
            )
        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            record = ToolCallRecord(
                tool_name=tool.name,
                arguments=arguments,
                result="Tool call timed out after {}s".format(self.policy.call_timeout),
                is_error=True,
                duration_ms=duration_ms,
                required_approval=self.requires_approval(tool),
                annotations=tool.annotations,
            )
            self.audit_log.append(record)
            self.call_count += 1
            return MCPToolResult(
                content="Tool call timed out after {}s".format(self.policy.call_timeout),
                is_error=True,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            record = ToolCallRecord(
                tool_name=tool.name,
                arguments=arguments,
                result=str(exc),
                is_error=True,
                duration_ms=duration_ms,
                required_approval=self.requires_approval(tool),
                annotations=tool.annotations,
            )
            self.audit_log.append(record)
            self.call_count += 1
            raise

        duration_ms = int((time.monotonic() - start) * 1000)
        self.call_count += 1

        record = ToolCallRecord(
            tool_name=tool.name,
            arguments=arguments,
            result=result.content[:500],
            is_error=result.is_error,
            duration_ms=duration_ms,
            required_approval=self.requires_approval(tool),
            annotations=tool.annotations,
        )
        self.audit_log.append(record)

        logger.info(
            "MCP tool call: %s (destructive=%s, duration=%dms, error=%s)",
            tool.name,
            self.is_destructive(tool),
            duration_ms,
            result.is_error,
        )

        return result

    def get_audit_records(self) -> list[dict[str, Any]]:
        return [
            {
                "tool_name": r.tool_name,
                "arguments": r.arguments,
                "result_preview": r.result[:200],
                "is_error": r.is_error,
                "duration_ms": r.duration_ms,
                "required_approval": r.required_approval,
                "destructive": r.annotations.get("destructiveHint", False),
                "read_only": r.annotations.get("readOnlyHint", False),
                "timestamp": r.timestamp,
            }
            for r in self.audit_log
        ]


def validate_tool_annotations(tool: MCPTool) -> list[str]:
    """Validate MCP tool annotations and return any warnings."""
    warnings: list[str] = []
    ann = tool.annotations

    if ann.get("destructiveHint") and ann.get("readOnlyHint"):
        warnings.append(
            "Tool '{}' has both destructiveHint and readOnlyHint".format(tool.name)
        )

    if not ann:
        warnings.append(
            "Tool '{}' has no annotations; treating as potentially dangerous".format(tool.name)
        )

    return warnings
