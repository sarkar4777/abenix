"""Tests for cost guardrails and prediction."""

from engine.cost_guardrails import CostPrediction, predict_cost, MODEL_PRICING


class TestCostPrediction:
    def test_predict_known_model(self):
        result = predict_cost(
            model="claude-sonnet-4-5-20250929",
            estimated_input_tokens=1000,
            estimated_output_tokens=500,
        )
        assert isinstance(result, CostPrediction)
        assert result.estimated_cost > 0
        assert result.model == "claude-sonnet-4-5-20250929"
        assert result.within_budget is True

    def test_predict_unknown_model_uses_default(self):
        result = predict_cost(model="unknown-model-xyz")
        assert result.estimated_cost > 0

    def test_predict_with_per_execution_limit_within(self):
        result = predict_cost(
            model="gpt-4o-mini",
            estimated_input_tokens=100,
            estimated_output_tokens=100,
            per_execution_limit=10.0,
        )
        assert result.within_budget is True
        assert result.budget_remaining is not None
        assert result.budget_remaining > 0

    def test_predict_with_per_execution_limit_exceeded(self):
        result = predict_cost(
            model="claude-sonnet-4-5-20250929",
            estimated_input_tokens=1_000_000,
            estimated_output_tokens=500_000,
            max_iterations=10,
            per_execution_limit=0.001,
        )
        assert result.within_budget is False
        assert result.warning is not None
        assert "exceeds" in result.warning

    def test_predict_with_tools_increases_cost(self):
        without_tools = predict_cost(model="gpt-4o", tool_count=0)
        with_tools = predict_cost(model="gpt-4o", tool_count=10)
        assert with_tools.estimated_cost > without_tools.estimated_cost

    def test_predict_with_iterations_increases_cost(self):
        single = predict_cost(model="gpt-4o", max_iterations=1)
        multi = predict_cost(model="gpt-4o", max_iterations=10)
        assert multi.estimated_cost > single.estimated_cost

    def test_model_pricing_completeness(self):
        expected_models = [
            "claude-sonnet-4-5-20250929",
            "claude-haiku-3-5",
            "gpt-4o",
            "gpt-4o-mini",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
        ]
        for model in expected_models:
            assert model in MODEL_PRICING
            input_price, output_price = MODEL_PRICING[model]
            assert input_price > 0
            assert output_price > 0

    def test_predict_near_limit_warning(self):
        # Cost of ~0.00045. Limit of 0.0005 means cost is 90% of limit → warning
        result = predict_cost(
            model="gpt-4o-mini",
            estimated_input_tokens=1000,
            estimated_output_tokens=500,
            per_execution_limit=0.0005,
        )
        assert result.warning is not None  # 90% > 80% threshold triggers warning
