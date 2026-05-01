"""Quantitative risk analysis: Monte Carlo, sensitivity analysis, scenario modeling."""

from __future__ import annotations

import json
import math
import random
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class RiskAnalyzerTool(BaseTool):
    name = "risk_analyzer"
    description = (
        "Perform quantitative risk analysis including Monte Carlo simulation, "
        "sensitivity analysis (tornado diagrams), scenario modeling (best/base/worst), "
        "risk scoring matrices, probability distributions, and Value at Risk (VaR). "
        "Useful for evaluating financial risks, project risks, and contract exposures."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "analysis_type": {
                "type": "string",
                "enum": [
                    "monte_carlo", "sensitivity", "scenario", "risk_matrix",
                    "var", "expected_value",
                ],
                "description": "Type of risk analysis to perform",
            },
            "params": {
                "type": "object",
                "description": "Analysis-specific parameters",
            },
        },
        "required": ["analysis_type", "params"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        analysis_type = arguments.get("analysis_type", "")
        params = arguments.get("params", {})

        if not analysis_type:
            return ToolResult(content="Error: analysis_type is required", is_error=True)

        analyzers = {
            "monte_carlo": self._monte_carlo,
            "sensitivity": self._sensitivity,
            "scenario": self._scenario,
            "risk_matrix": self._risk_matrix,
            "var": self._value_at_risk,
            "expected_value": self._expected_value,
        }

        fn = analyzers.get(analysis_type)
        if not fn:
            return ToolResult(
                content=f"Unknown analysis: {analysis_type}",
                is_error=True,
            )

        try:
            result = fn(params)
            output = json.dumps(result, indent=2, default=str)
            return ToolResult(content=output, metadata={"analysis_type": analysis_type})
        except Exception as e:
            return ToolResult(content=f"Analysis error: {e}", is_error=True)

    def _monte_carlo(self, params: dict[str, Any]) -> dict[str, Any]:
        variables = params.get("variables", {})
        formula = params.get("formula", "")
        iterations = min(params.get("iterations", 10000), 100000)
        seed = params.get("seed")

        if not variables:
            return {"error": "variables dict is required with distribution params"}
        if not formula:
            return {"error": "formula is required (use variable names, e.g. 'revenue - costs')"}

        if seed is not None:
            random.seed(seed)

        samples: dict[str, list[float]] = {}
        for var_name, dist in variables.items():
            dist_type = dist.get("distribution", "normal")
            n = iterations

            if dist_type == "normal":
                mean = dist.get("mean", 0)
                std = dist.get("std", 1)
                samples[var_name] = [random.gauss(mean, std) for _ in range(n)]
            elif dist_type == "uniform":
                low = dist.get("min", 0)
                high = dist.get("max", 1)
                samples[var_name] = [random.uniform(low, high) for _ in range(n)]
            elif dist_type == "triangular":
                low = dist.get("min", 0)
                mode = dist.get("mode", 0.5)
                high = dist.get("max", 1)
                samples[var_name] = [random.triangular(low, high, mode) for _ in range(n)]
            elif dist_type == "lognormal":
                mean = dist.get("mean", 0)
                std = dist.get("std", 1)
                samples[var_name] = [random.lognormvariate(mean, std) for _ in range(n)]
            elif dist_type == "fixed":
                val = dist.get("value", 0)
                samples[var_name] = [val] * n
            else:
                return {"error": f"Unknown distribution: {dist_type}"}

        results = []
        for i in range(iterations):
            local_vars = {name: vals[i] for name, vals in samples.items()}
            try:
                val = self._eval_formula(formula, local_vars)
                results.append(val)
            except Exception:
                continue

        if not results:
            return {"error": "All iterations failed. Check your formula."}

        results.sort()
        n = len(results)

        percentiles = {}
        for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
            idx = int(n * p / 100)
            percentiles[f"p{p}"] = round(results[min(idx, n - 1)], 2)

        mean = sum(results) / n
        variance = sum((x - mean) ** 2 for x in results) / n
        std = math.sqrt(variance)
        prob_positive = sum(1 for x in results if x > 0) / n
        prob_negative = 1 - prob_positive

        histogram = self._build_histogram(results, bins=20)

        return {
            "iterations": n,
            "mean": round(mean, 2),
            "median": round(results[n // 2], 2),
            "std_dev": round(std, 2),
            "min": round(results[0], 2),
            "max": round(results[-1], 2),
            "percentiles": percentiles,
            "probability_positive": round(prob_positive * 100, 1),
            "probability_negative": round(prob_negative * 100, 1),
            "histogram": histogram,
            "confidence_interval_90": [percentiles["p5"], percentiles["p95"]],
            "confidence_interval_95": [percentiles.get("p2.5", percentiles["p1"]), percentiles.get("p97.5", percentiles["p99"])],
        }

    def _sensitivity(self, params: dict[str, Any]) -> dict[str, Any]:
        base_values = params.get("base_values", {})
        formula = params.get("formula", "")
        variation_pct = params.get("variation_pct", 20)

        if not base_values or not formula:
            return {"error": "base_values dict and formula are required"}

        base_result = self._eval_formula(formula, base_values)

        sensitivities = []
        for var_name, base_val in base_values.items():
            if base_val == 0:
                continue
            low_val = base_val * (1 - variation_pct / 100)
            high_val = base_val * (1 + variation_pct / 100)

            low_vars = {**base_values, var_name: low_val}
            high_vars = {**base_values, var_name: high_val}

            low_result = self._eval_formula(formula, low_vars)
            high_result = self._eval_formula(formula, high_vars)

            swing = abs(high_result - low_result)
            sensitivities.append({
                "variable": var_name,
                "base_value": round(base_val, 4),
                "low_value": round(low_val, 4),
                "high_value": round(high_val, 4),
                "result_at_low": round(low_result, 2),
                "result_at_high": round(high_result, 2),
                "result_at_base": round(base_result, 2),
                "swing": round(swing, 2),
                "elasticity": round((high_result - low_result) / (2 * base_result) / (variation_pct / 100), 4) if base_result != 0 else 0,
            })

        sensitivities.sort(key=lambda x: x["swing"], reverse=True)

        return {
            "base_result": round(base_result, 2),
            "variation_pct": variation_pct,
            "tornado": sensitivities,
            "most_sensitive": sensitivities[0]["variable"] if sensitivities else None,
            "least_sensitive": sensitivities[-1]["variable"] if sensitivities else None,
        }

    def _scenario(self, params: dict[str, Any]) -> dict[str, Any]:
        scenarios = params.get("scenarios", {})
        formula = params.get("formula", "")
        probabilities = params.get("probabilities", {})

        if not scenarios or not formula:
            return {"error": "scenarios dict and formula are required"}

        results = []
        for name, values in scenarios.items():
            result = self._eval_formula(formula, values)
            prob = probabilities.get(name, 1 / len(scenarios))
            results.append({
                "scenario": name,
                "inputs": values,
                "result": round(result, 2),
                "probability": prob,
                "weighted_result": round(result * prob, 2),
            })

        expected = sum(r["weighted_result"] for r in results)
        result_values = [r["result"] for r in results]
        spread = max(result_values) - min(result_values) if result_values else 0

        return {
            "scenarios": results,
            "expected_value": round(expected, 2),
            "best_case": round(max(result_values), 2) if result_values else 0,
            "worst_case": round(min(result_values), 2) if result_values else 0,
            "range": round(spread, 2),
        }

    def _risk_matrix(self, params: dict[str, Any]) -> dict[str, Any]:
        risks = params.get("risks", [])

        if not risks:
            return {"error": "risks array is required [{name, likelihood, impact, ...}]"}

        scored = []
        for risk in risks:
            name = risk.get("name", "Unknown")
            likelihood = risk.get("likelihood", 3)
            impact = risk.get("impact", 3)
            score = likelihood * impact

            if score >= 15:
                level = "critical"
            elif score >= 10:
                level = "high"
            elif score >= 5:
                level = "medium"
            else:
                level = "low"

            scored.append({
                "name": name,
                "likelihood": likelihood,
                "impact": impact,
                "risk_score": score,
                "risk_level": level,
                "mitigation": risk.get("mitigation", ""),
                "category": risk.get("category", ""),
            })

        scored.sort(key=lambda x: x["risk_score"], reverse=True)

        summary = {
            "critical": sum(1 for r in scored if r["risk_level"] == "critical"),
            "high": sum(1 for r in scored if r["risk_level"] == "high"),
            "medium": sum(1 for r in scored if r["risk_level"] == "medium"),
            "low": sum(1 for r in scored if r["risk_level"] == "low"),
        }

        return {
            "risks": scored,
            "summary": summary,
            "total_risks": len(scored),
            "average_score": round(sum(r["risk_score"] for r in scored) / len(scored), 1),
            "highest_risk": scored[0]["name"] if scored else None,
        }

    def _value_at_risk(self, params: dict[str, Any]) -> dict[str, Any]:
        returns = params.get("returns", [])
        portfolio_value = params.get("portfolio_value", 1000000)
        confidence_levels = params.get("confidence_levels", [0.95, 0.99])
        holding_period_days = params.get("holding_period_days", 1)

        if not returns:
            mean = params.get("mean_return", 0.0005)
            std = params.get("std_return", 0.02)
            returns = [random.gauss(mean, std) for _ in range(1000)]

        returns_sorted = sorted(returns)
        n = len(returns_sorted)
        mean_return = sum(returns_sorted) / n
        variance = sum((r - mean_return) ** 2 for r in returns_sorted) / n
        std_return = math.sqrt(variance)

        var_results = {}
        for cl in confidence_levels:
            idx = int(n * (1 - cl))
            var_return = returns_sorted[max(0, idx)]
            var_dollar = abs(var_return) * portfolio_value * math.sqrt(holding_period_days)
            var_results[f"{int(cl * 100)}%"] = {
                "var_return": round(var_return * 100, 4),
                "var_dollar": round(var_dollar, 2),
                "interpretation": f"With {int(cl*100)}% confidence, max loss over {holding_period_days} day(s) is ${var_dollar:,.2f}",
            }

        return {
            "portfolio_value": portfolio_value,
            "holding_period_days": holding_period_days,
            "observations": n,
            "mean_daily_return": round(mean_return * 100, 4),
            "daily_volatility": round(std_return * 100, 4),
            "annualized_volatility": round(std_return * math.sqrt(252) * 100, 2),
            "var": var_results,
        }

    def _expected_value(self, params: dict[str, Any]) -> dict[str, Any]:
        outcomes = params.get("outcomes", [])

        if not outcomes:
            return {"error": "outcomes array is required [{name, value, probability}]"}

        total_prob = sum(o.get("probability", 0) for o in outcomes)
        if abs(total_prob - 1.0) > 0.01:
            for o in outcomes:
                o["probability"] = o.get("probability", 0) / total_prob if total_prob > 0 else 0

        ev = sum(o.get("value", 0) * o.get("probability", 0) for o in outcomes)

        variance = sum(
            o.get("probability", 0) * (o.get("value", 0) - ev) ** 2
            for o in outcomes
        )
        std = math.sqrt(variance)

        detailed = []
        for o in outcomes:
            detailed.append({
                "name": o.get("name", ""),
                "value": o.get("value", 0),
                "probability": round(o.get("probability", 0), 4),
                "weighted_value": round(o.get("value", 0) * o.get("probability", 0), 2),
            })

        return {
            "expected_value": round(ev, 2),
            "standard_deviation": round(std, 2),
            "coefficient_of_variation": round(std / abs(ev), 4) if ev != 0 else None,
            "outcomes": detailed,
        }

    def _eval_formula(self, formula: str, variables: dict[str, float]) -> float:
        safe_dict = {
            "__builtins__": {},
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "round": round,
            "sqrt": math.sqrt,
            "log": math.log,
            "exp": math.exp,
            "pow": pow,
        }
        safe_dict.update(variables)
        return float(eval(formula, safe_dict))

    def _build_histogram(self, values: list[float], bins: int = 20) -> list[dict[str, Any]]:
        if not values:
            return []
        lo = values[0]
        hi = values[-1]
        if lo == hi:
            return [{"range": f"{lo:.2f}", "count": len(values), "pct": 100.0}]

        width = (hi - lo) / bins
        counts = [0] * bins
        for v in values:
            idx = min(int((v - lo) / width), bins - 1)
            counts[idx] += 1

        total = len(values)
        return [
            {
                "range": f"{lo + i * width:.2f} - {lo + (i + 1) * width:.2f}",
                "count": c,
                "pct": round(c / total * 100, 1),
            }
            for i, c in enumerate(counts)
        ]
