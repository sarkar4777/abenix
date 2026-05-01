"""Tests for confidence scoring."""

from engine.confidence import ConfidenceFactors, ExecutionTrace, calculate_confidence


class TestCalculateConfidence:
    def test_perfect_execution(self):
        factors = ConfidenceFactors()
        score = calculate_confidence(factors)
        assert score == 1.0

    def test_tool_failures_reduce_confidence(self):
        factors = ConfidenceFactors(total_tool_calls=10, failed_tool_calls=5)
        score = calculate_confidence(factors)
        assert score < 1.0
        assert score >= 0.7  # 50% failure rate * 0.3 penalty

    def test_all_tools_fail(self):
        factors = ConfidenceFactors(total_tool_calls=5, failed_tool_calls=5)
        score = calculate_confidence(factors)
        assert score == 0.7  # 100% failure * 0.3

    def test_retries_reduce_confidence(self):
        factors = ConfidenceFactors(retry_count=3)
        score = calculate_confidence(factors)
        assert score == 0.85  # 3 * 0.05

    def test_max_iterations_penalty(self):
        factors = ConfidenceFactors(max_iterations_hit=True)
        score = calculate_confidence(factors)
        assert score == 0.75

    def test_error_penalty(self):
        factors = ConfidenceFactors(error_occurred=True)
        score = calculate_confidence(factors)
        assert score == 0.7

    def test_pipeline_failures(self):
        factors = ConfidenceFactors(
            pipeline_nodes_total=10,
            pipeline_nodes_failed=3,
        )
        score = calculate_confidence(factors)
        assert score < 1.0
        assert score == 0.88  # 3/10 * 0.4 = 0.12

    def test_combined_penalties(self):
        factors = ConfidenceFactors(
            total_tool_calls=10,
            failed_tool_calls=2,
            retry_count=1,
            error_occurred=True,
        )
        score = calculate_confidence(factors)
        assert 0.0 <= score <= 1.0
        assert score < 0.7

    def test_score_never_below_zero(self):
        factors = ConfidenceFactors(
            total_tool_calls=10,
            failed_tool_calls=10,
            retry_count=10,
            max_iterations_hit=True,
            error_occurred=True,
            pipeline_nodes_total=10,
            pipeline_nodes_failed=10,
        )
        score = calculate_confidence(factors)
        assert score == 0.0

    def test_short_output_penalty(self):
        factors = ConfidenceFactors(input_length=500, output_length=10)
        score = calculate_confidence(factors)
        assert score == 0.85


class TestExecutionTrace:
    def test_add_step(self):
        trace = ExecutionTrace(execution_id="test-1", agent_id="agent-1")
        trace.add_step("llm_call", name="initial", output_data="Hello")
        assert len(trace.steps) == 1
        assert trace.steps[0]["step_number"] == 1
        assert trace.steps[0]["type"] == "llm_call"

    def test_tool_call_tracking(self):
        trace = ExecutionTrace()
        trace.add_step("tool_call", name="web_search")
        trace.add_step("tool_call", name="calculator", error="Division by zero")
        assert trace.confidence_factors.total_tool_calls == 2
        assert trace.confidence_factors.failed_tool_calls == 1

    def test_to_dict(self):
        trace = ExecutionTrace(execution_id="e1", agent_id="a1")
        trace.add_step("llm_call", name="init")
        result = trace.to_dict()
        assert result["execution_id"] == "e1"
        assert result["total_steps"] == 1
        assert "confidence_score" in result
