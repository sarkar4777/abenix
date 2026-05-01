"""Fan-in data merger tool for combining multiple pipeline inputs."""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class DataMergerTool(BaseTool):
    name = "data_merger"
    description = (
        "Merge multiple data inputs into a single unified structure. Supports three "
        "strategies: 'flat' merges all inputs into one dictionary, 'nested' preserves "
        "each input under its original key, and 'comparison' creates a side-by-side "
        "labeled view. Ideal for fan-in pipeline steps that combine results from "
        "parallel branches."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "merge_strategy": {
                "type": "string",
                "enum": ["flat", "nested", "comparison"],
                "description": "Strategy for merging inputs: flat (single dict), nested (keyed), or comparison (labeled side-by-side)",
                "default": "nested",
            },
            "labels": {
                "type": "object",
                "description": "Display labels for each input key (used with comparison strategy). Keys should match input keys, values are human-readable labels.",
            },
        },
        "additionalProperties": True,
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        merge_strategy = arguments.get("merge_strategy", "nested")
        labels = arguments.get("labels", {})

        # Separate control parameters from data inputs
        reserved_keys = {"merge_strategy", "labels", "sources"}
        data_inputs: dict[str, Any] = {
            k: v for k, v in arguments.items() if k not in reserved_keys
        }

        # Backwards compat: accept a `sources` list argument (seed YAML style)
        # and treat each entry as an auto-keyed input
        sources = arguments.get("sources")
        if isinstance(sources, list):
            for idx, val in enumerate(sources):
                # Try to parse JSON strings to dicts for cleaner merging
                if isinstance(val, str):
                    try:
                        import json as _j
                        parsed = _j.loads(val)
                        data_inputs[f"source_{idx}"] = parsed
                    except Exception:
                        data_inputs[f"source_{idx}"] = val
                else:
                    data_inputs[f"source_{idx}"] = val

        try:
            if merge_strategy == "flat":
                result = self._merge_flat(data_inputs)
            elif merge_strategy == "nested":
                result = self._merge_nested(data_inputs)
            elif merge_strategy == "comparison":
                result = self._merge_comparison(data_inputs, labels)
            else:
                return ToolResult(
                    content=f"Unknown merge strategy: {merge_strategy}",
                    is_error=True,
                )

            return ToolResult(
                content=json.dumps(result, indent=2, default=str),
                metadata={
                    "strategy": merge_strategy,
                    "input_count": len(data_inputs),
                },
            )
        except Exception as e:
            return ToolResult(content=f"Merge failed: {e}", is_error=True)

    def _merge_flat(self, data_inputs: dict[str, Any]) -> dict[str, Any]:
        """Merge all inputs into a single flat dictionary."""
        merged: dict[str, Any] = {}
        for key, value in data_inputs.items():
            if isinstance(value, dict):
                merged.update(value)
            else:
                merged[key] = value
        return merged

    def _merge_nested(self, data_inputs: dict[str, Any]) -> dict[str, Any]:
        """Place each input under its key name."""
        return {key: value for key, value in data_inputs.items()}

    def _merge_comparison(
        self, data_inputs: dict[str, Any], labels: dict[str, str]
    ) -> dict[str, Any]:
        """Create a side-by-side comparison structure with labels."""
        items: list[dict[str, Any]] = []
        for key, value in data_inputs.items():
            label = labels.get(key, key)
            items.append({
                "label": label,
                "key": key,
                "data": value,
            })
        return {"items": items}
