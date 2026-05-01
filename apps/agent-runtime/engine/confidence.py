"""Confidence Scoring — calculates a 0.0-1.0 confidence score for agent outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConfidenceFactors:
    total_tool_calls: int = 0
    failed_tool_calls: int = 0
    retry_count: int = 0
    max_iterations_hit: bool = False
    iterations_used: int = 0
    max_iterations: int = 10
    output_length: int = 0
    input_length: int = 0
    error_occurred: bool = False
    pipeline_nodes_total: int = 0
    pipeline_nodes_failed: int = 0
    pipeline_nodes_skipped: int = 0


def calculate_confidence(factors: ConfidenceFactors) -> float:
    """Calculate confidence score from 0.0 to 1.0."""
    score = 1.0

    # Tool failure penalty: each failure reduces confidence
    if factors.total_tool_calls > 0:
        failure_rate = factors.failed_tool_calls / factors.total_tool_calls
        score -= failure_rate * 0.3  # Up to -0.3

    # Retry penalty: each retry reduces confidence slightly
    if factors.retry_count > 0:
        score -= min(factors.retry_count * 0.05, 0.2)  # Up to -0.2

    # Max iterations penalty: hitting the limit suggests incompleteness
    if factors.max_iterations_hit:
        score -= 0.25

    # Iteration usage: using most iterations is a mild concern
    if factors.max_iterations > 0:
        usage_ratio = factors.iterations_used / factors.max_iterations
        if usage_ratio > 0.8 and not factors.max_iterations_hit:
            score -= 0.1

    # Output too short relative to input
    if factors.input_length > 100 and factors.output_length < 20:
        score -= 0.15

    # Error occurred
    if factors.error_occurred:
        score -= 0.3

    # Pipeline-specific penalties
    if factors.pipeline_nodes_total > 0:
        failed_ratio = factors.pipeline_nodes_failed / factors.pipeline_nodes_total
        skipped_ratio = factors.pipeline_nodes_skipped / factors.pipeline_nodes_total
        score -= failed_ratio * 0.4
        score -= skipped_ratio * 0.15

    return round(max(0.0, min(1.0, score)), 2)


@dataclass
class ExecutionTrace:
    """Full trace of an execution for replay and debugging."""
    execution_id: str = ""
    agent_id: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    confidence_factors: ConfidenceFactors = field(default_factory=ConfidenceFactors)

    def add_step(
        self,
        step_type: str,
        *,
        name: str = "",
        input_data: Any = None,
        output_data: Any = None,
        duration_ms: int = 0,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.steps.append({
            "step_number": len(self.steps) + 1,
            "type": step_type,  # "llm_call", "tool_call", "pipeline_node", "decision"
            "name": name,
            "input": _safe_serialize(input_data),
            "output": _safe_serialize(output_data),
            "duration_ms": duration_ms,
            "error": error,
            "metadata": metadata or {},
        })

        # Update confidence factors
        if step_type == "tool_call":
            self.confidence_factors.total_tool_calls += 1
            if error:
                self.confidence_factors.failed_tool_calls += 1
        if step_type == "pipeline_node":
            self.confidence_factors.pipeline_nodes_total += 1
            if error:
                self.confidence_factors.pipeline_nodes_failed += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "agent_id": self.agent_id,
            "steps": self.steps,
            "confidence_score": calculate_confidence(self.confidence_factors),
            "total_steps": len(self.steps),
        }


def _safe_serialize(data: Any) -> Any:
    """Safely serialize data for storage, truncating large values."""
    if data is None:
        return None
    if isinstance(data, str):
        return data[:5000] if len(data) > 5000 else data
    if isinstance(data, dict):
        return {k: _safe_serialize(v) for k, v in list(data.items())[:50]}
    if isinstance(data, list):
        return [_safe_serialize(v) for v in data[:20]]
    return str(data)[:1000]
