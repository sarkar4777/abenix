"""Time-Series Analyzer — statistical analysis, anomaly detection, and forecasting."""
from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class TimeSeriesAnalyzerTool(BaseTool):
    name = "time_series_analyzer"
    description = "Analyze time-series data: moving averages, anomaly detection (z-score), linear forecasting, trend decomposition, and correlation analysis."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "data": {"type": "array", "items": {"type": "number"}, "description": "Array of numeric values (time-ordered)"},
            "timestamps": {"type": "array", "items": {"type": "string"}, "description": "Optional ISO timestamps for each data point"},
            "operation": {"type": "string", "enum": ["moving_average", "anomaly_detection", "forecast", "statistics", "correlation"], "description": "Analysis to perform"},
            "window": {"type": "integer", "default": 7, "description": "Window size for moving average"},
            "forecast_periods": {"type": "integer", "default": 10, "description": "Number of periods to forecast"},
            "z_threshold": {"type": "number", "default": 2.0, "description": "Z-score threshold for anomaly detection"},
            "compare_data": {"type": "array", "items": {"type": "number"}, "description": "Second series for correlation analysis"},
        },
        "required": ["data", "operation"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        data = arguments.get("data", [])
        operation = arguments.get("operation", "statistics")

        if not data:
            return ToolResult(content="No data points provided", is_error=True)

        import numpy as np
        arr = np.array(data, dtype=float)

        if len(data) < 2 and operation != "statistics":
            return ToolResult(content=f"Operation '{operation}' needs at least 2 data points, got {len(data)}", is_error=True)

        try:
            if operation == "statistics":
                result = {
                    "count": len(arr),
                    "mean": float(np.mean(arr)),
                    "median": float(np.median(arr)),
                    "std": float(np.std(arr)),
                    "min": float(np.min(arr)),
                    "max": float(np.max(arr)),
                    "trend": "increasing" if arr[-1] > arr[0] else "decreasing",
                    "change_pct": float((arr[-1] - arr[0]) / arr[0] * 100) if arr[0] != 0 else 0,
                }

            elif operation == "moving_average":
                window = min(arguments.get("window", 7), len(arr))
                ma = np.convolve(arr, np.ones(window)/window, mode="valid")
                result = {"moving_average": [round(float(v), 4) for v in ma], "window": window}

            elif operation == "anomaly_detection":
                z_threshold = arguments.get("z_threshold", 2.0)
                mean, std = float(np.mean(arr)), float(np.std(arr))
                if std == 0:
                    result = {"anomalies": [], "z_scores": [0.0] * len(arr)}
                else:
                    z_scores = ((arr - mean) / std).tolist()
                    anomalies = [{"index": i, "value": float(arr[i]), "z_score": round(z, 2)} for i, z in enumerate(z_scores) if abs(z) > z_threshold]
                    result = {"anomalies": anomalies, "anomaly_count": len(anomalies), "mean": mean, "std": std, "threshold": z_threshold}

            elif operation == "forecast":
                periods = arguments.get("forecast_periods", 10)
                x = np.arange(len(arr))
                coeffs = np.polyfit(x, arr, 1)
                slope, intercept = float(coeffs[0]), float(coeffs[1])
                future_x = np.arange(len(arr), len(arr) + periods)
                forecast = (slope * future_x + intercept).tolist()
                result = {"forecast": [round(float(v), 4) for v in forecast], "slope": round(slope, 4), "intercept": round(intercept, 4), "trend": "up" if slope > 0 else "down"}

            elif operation == "correlation":
                compare = arguments.get("compare_data", [])
                if not compare or len(compare) != len(data):
                    return ToolResult(content="compare_data must have same length as data", is_error=True)
                corr = float(np.corrcoef(arr, np.array(compare, dtype=float))[0, 1])
                result = {"correlation": round(corr, 4), "strength": "strong" if abs(corr) > 0.7 else "moderate" if abs(corr) > 0.4 else "weak"}

            else:
                return ToolResult(content=f"Unknown operation: {operation}", is_error=True)

            return ToolResult(content=json.dumps(result, default=str))

        except Exception as e:
            return ToolResult(content=f"Analysis failed: {e}", is_error=True)
