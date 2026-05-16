"""Generate Plotly chart spec (JSON) from structured data."""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult

_LAYOUT_DEFAULTS = {
    "template": "plotly_dark",
    "margin": {"l": 50, "r": 30, "t": 60, "b": 50},
    "font": {"family": "Inter, sans-serif", "size": 12},
}


def _line_or_bar(kind: str, args: dict[str, Any]) -> dict[str, Any]:
    series = args.get("series") or []
    if not series:
        raise ValueError(f"{kind} requires series[]")
    traces = []
    for s in series:
        traces.append(
            {
                "type": "scatter" if kind == "line" else "bar",
                "mode": "lines+markers" if kind == "line" else None,
                "name": s.get("name", "series"),
                "x": s.get("x", []),
                "y": s.get("y", []),
                **(
                    {"line": {"shape": "spline"}}
                    if kind == "line" and s.get("smooth")
                    else {}
                ),
            }
        )
        # Drop None values from inserted dict keys so Plotly doesn't choke.
        traces[-1] = {k: v for k, v in traces[-1].items() if v is not None}
    return {"data": traces}


def _scatter(args: dict[str, Any]) -> dict[str, Any]:
    points = args.get("points") or []
    if not points:
        raise ValueError("scatter requires points[]")
    xs = [p.get("x") for p in points]
    ys = [p.get("y") for p in points]
    text = [p.get("label", "") for p in points]
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "markers+text",
                "x": xs,
                "y": ys,
                "text": text,
                "textposition": "top center",
            }
        ]
    }


def _pie(args: dict[str, Any]) -> dict[str, Any]:
    slices = args.get("slices") or []
    if not slices:
        raise ValueError("pie requires slices[]")
    return {
        "data": [
            {
                "type": "pie",
                "labels": [s.get("label") for s in slices],
                "values": [s.get("value", 0) for s in slices],
                "hole": 0.4 if args.get("donut") else 0.0,
            }
        ]
    }


def _heatmap(args: dict[str, Any]) -> dict[str, Any]:
    z = args.get("z")
    if not z:
        raise ValueError("heatmap requires z (2D array)")
    return {
        "data": [
            {
                "type": "heatmap",
                "z": z,
                "x": args.get("x"),
                "y": args.get("y"),
                "colorscale": args.get("colorscale", "Viridis"),
            }
        ]
    }


class PlotlyChartTool(BaseTool):
    name = "plotly_chart"
    description = (
        "Build a Plotly figure spec (JSON) from structured data — line, "
        "bar, scatter, pie/donut, heatmap. Returns the spec; the UI / "
        "notebook / exporter renders it. Use this when an agent needs to "
        "show a trend visually rather than as a number table."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": ["line", "bar", "scatter", "pie", "heatmap"],
                "default": "line",
            },
            "title": {"type": "string"},
            "x_label": {"type": "string"},
            "y_label": {"type": "string"},
            "series": {
                "type": "array",
                "description": "line/bar: [{name, x:[], y:[], smooth?}]",
                "items": {"type": "object"},
            },
            "points": {
                "type": "array",
                "description": "scatter: [{x, y, label?}]",
                "items": {"type": "object"},
            },
            "slices": {
                "type": "array",
                "description": "pie: [{label, value}]",
                "items": {"type": "object"},
            },
            "donut": {"type": "boolean", "description": "pie only — render as donut."},
            "z": {"description": "heatmap: 2D array of values."},
            "x": {"description": "heatmap x labels (optional)."},
            "y": {"description": "heatmap y labels (optional)."},
            "colorscale": {"type": "string", "description": "heatmap colorscale name."},
        },
        "required": ["chart_type"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        kind = arguments.get("chart_type", "line")
        try:
            if kind in ("line", "bar"):
                fig = _line_or_bar(kind, arguments)
            elif kind == "scatter":
                fig = _scatter(arguments)
            elif kind == "pie":
                fig = _pie(arguments)
            elif kind == "heatmap":
                fig = _heatmap(arguments)
            else:
                return ToolResult(content=f"Unknown chart_type: {kind}", is_error=True)
        except ValueError as e:
            return ToolResult(content=str(e), is_error=True)

        layout = {**_LAYOUT_DEFAULTS}
        if arguments.get("title"):
            layout["title"] = arguments["title"]
        if arguments.get("x_label"):
            layout["xaxis"] = {"title": arguments["x_label"]}
        if arguments.get("y_label"):
            layout["yaxis"] = {"title": arguments["y_label"]}
        fig["layout"] = layout

        spec = json.dumps(fig)
        # Trace count summary so an LLM can verify quickly.
        trace_count = len(fig.get("data", []))
        return ToolResult(
            content=(
                f"Plotly {kind} chart — {trace_count} trace(s), "
                f"{len(spec):,} bytes. Spec JSON in metadata.figure."
            ),
            metadata={"figure": fig, "chart_type": kind, "spec_bytes": len(spec)},
        )
