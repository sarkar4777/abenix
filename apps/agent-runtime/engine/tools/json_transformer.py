"""Query and transform structured JSON data - filtering, mapping, aggregation, flattening."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class JsonTransformerTool(BaseTool):
    name = "json_transformer"
    description = (
        "Transform, query, and manipulate structured JSON data. Operations include: "
        "query (extract nested values by path), filter (select items matching conditions), "
        "flatten (convert nested structures to flat key-value), aggregate (sum, count, avg "
        "over arrays), reshape (pivot, group, transpose), merge (combine multiple objects), "
        "and diff (compare two JSON structures)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "data": {
                "description": "JSON data to transform (object, array, or JSON string)",
            },
            "operation": {
                "type": "string",
                "enum": ["query", "filter", "flatten", "aggregate", "reshape", "merge", "diff", "schema"],
                "description": "Transformation operation",
            },
            "path": {
                "type": "string",
                "description": "Dot-notation path for query (e.g. 'users.0.name', 'items[*].price')",
            },
            "condition": {
                "type": "object",
                "description": "Filter condition: {field: value} or {field: {op: value}}",
            },
            "second_data": {
                "description": "Second dataset for merge/diff operations",
            },
            "group_by": {
                "type": "string",
                "description": "Field name to group by for reshape",
            },
            "agg_field": {
                "type": "string",
                "description": "Field to aggregate",
            },
            "agg_func": {
                "type": "string",
                "enum": ["sum", "count", "avg", "min", "max", "list"],
                "description": "Aggregation function",
                "default": "sum",
            },
        },
        "required": ["data", "operation"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        data = arguments.get("data")
        operation = arguments.get("operation", "")

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return ToolResult(content="Error: invalid JSON string", is_error=True)

        if data is None:
            return ToolResult(content="Error: data is required", is_error=True)

        ops = {
            "query": self._query,
            "filter": self._filter,
            "flatten": self._flatten,
            "aggregate": self._aggregate,
            "reshape": self._reshape,
            "merge": self._merge,
            "diff": self._diff,
            "schema": self._schema,
        }

        fn = ops.get(operation)
        if not fn:
            return ToolResult(content=f"Unknown operation: {operation}", is_error=True)

        try:
            result = fn(data, arguments)
            output = json.dumps(result, indent=2, default=str)
            return ToolResult(content=output, metadata={"operation": operation})
        except Exception as e:
            return ToolResult(content=f"Transform error: {e}", is_error=True)

    def _query(self, data: Any, args: dict[str, Any]) -> Any:
        path = args.get("path", "")
        if not path:
            return data

        parts = []
        for segment in path.replace("[", ".").replace("]", "").split("."):
            if segment:
                parts.append(segment)

        current = data
        for part in parts:
            if part == "*" and isinstance(current, list):
                remaining = ".".join(parts[parts.index(part) + 1:])
                if remaining:
                    return [self._query(item, {"path": remaining}) for item in current]
                return current

            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (IndexError, ValueError):
                    return None
            else:
                return None

            if current is None:
                return None

        return current

    def _filter(self, data: Any, args: dict[str, Any]) -> Any:
        condition = args.get("condition", {})
        if not isinstance(data, list):
            return {"error": "filter requires array data"}
        if not condition:
            return data

        filtered = []
        for item in data:
            if not isinstance(item, dict):
                continue
            match = True
            for field, expected in condition.items():
                val = item.get(field)
                if isinstance(expected, dict):
                    for op, cmp_val in expected.items():
                        if op == "gt" and not (val is not None and val > cmp_val):
                            match = False
                        elif op == "lt" and not (val is not None and val < cmp_val):
                            match = False
                        elif op == "gte" and not (val is not None and val >= cmp_val):
                            match = False
                        elif op == "lte" and not (val is not None and val <= cmp_val):
                            match = False
                        elif op == "ne" and val == cmp_val:
                            match = False
                        elif op == "contains" and str(cmp_val).lower() not in str(val).lower():
                            match = False
                        elif op == "in" and val not in cmp_val:
                            match = False
                else:
                    if val != expected:
                        match = False
            if match:
                filtered.append(item)

        return {"matched": len(filtered), "total": len(data), "results": filtered}

    def _flatten(self, data: Any, args: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        self._flatten_recursive(data, "", result)
        return result

    def _flatten_recursive(self, obj: Any, prefix: str, result: dict[str, Any]) -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                new_key = f"{prefix}.{key}" if prefix else key
                self._flatten_recursive(val, new_key, result)
        elif isinstance(obj, list):
            for i, val in enumerate(obj):
                new_key = f"{prefix}[{i}]"
                self._flatten_recursive(val, new_key, result)
        else:
            result[prefix] = obj

    def _aggregate(self, data: Any, args: dict[str, Any]) -> dict[str, Any]:
        agg_field = args.get("agg_field", "")
        agg_func = args.get("agg_func", "sum")
        group_by = args.get("group_by")

        if not isinstance(data, list):
            return {"error": "aggregate requires array data"}

        if group_by:
            groups: dict[str, list[Any]] = defaultdict(list)
            for item in data:
                if isinstance(item, dict):
                    key = str(item.get(group_by, "(null)"))
                    val = item.get(agg_field)
                    if val is not None:
                        groups[key].append(val)

            result_groups = {}
            for key, vals in groups.items():
                result_groups[key] = self._apply_agg(vals, agg_func)

            return {"grouped_by": group_by, "field": agg_field, "function": agg_func, "results": result_groups}

        values = []
        for item in data:
            if isinstance(item, dict) and agg_field:
                val = item.get(agg_field)
                if val is not None:
                    values.append(val)
            elif isinstance(item, (int, float)):
                values.append(item)

        return {
            "field": agg_field,
            "function": agg_func,
            "count": len(values),
            "result": self._apply_agg(values, agg_func),
        }

    def _apply_agg(self, values: list[Any], func: str) -> Any:
        nums = [v for v in values if isinstance(v, (int, float))]
        if func == "sum":
            return round(sum(nums), 4) if nums else 0
        elif func == "count":
            return len(values)
        elif func == "avg":
            return round(sum(nums) / len(nums), 4) if nums else 0
        elif func == "min":
            return min(nums) if nums else None
        elif func == "max":
            return max(nums) if nums else None
        elif func == "list":
            return values
        return None

    def _reshape(self, data: Any, args: dict[str, Any]) -> dict[str, Any]:
        group_by = args.get("group_by", "")
        if not isinstance(data, list):
            return {"error": "reshape requires array data"}
        if not group_by:
            return {"error": "group_by field is required"}

        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in data:
            if isinstance(item, dict):
                key = str(item.get(group_by, "(null)"))
                groups[key].append(item)

        return {
            "grouped_by": group_by,
            "group_count": len(groups),
            "groups": {k: {"count": len(v), "items": v} for k, v in groups.items()},
        }

    def _merge(self, data: Any, args: dict[str, Any]) -> Any:
        second = args.get("second_data")
        if second is None:
            return {"error": "second_data is required for merge"}

        if isinstance(second, str):
            try:
                second = json.loads(second)
            except json.JSONDecodeError:
                return {"error": "second_data is not valid JSON"}

        if isinstance(data, dict) and isinstance(second, dict):
            merged = {**data, **second}
            return {
                "merged": merged,
                "keys_from_first": list(data.keys()),
                "keys_from_second": list(second.keys()),
                "overlapping_keys": list(set(data.keys()) & set(second.keys())),
            }

        if isinstance(data, list) and isinstance(second, list):
            return {
                "merged": data + second,
                "first_count": len(data),
                "second_count": len(second),
                "total": len(data) + len(second),
            }

        return {"error": "Both data and second_data must be same type (both objects or both arrays)"}

    def _diff(self, data: Any, args: dict[str, Any]) -> dict[str, Any]:
        second = args.get("second_data")
        if second is None:
            return {"error": "second_data is required for diff"}

        if isinstance(second, str):
            try:
                second = json.loads(second)
            except json.JSONDecodeError:
                return {"error": "second_data is not valid JSON"}

        if isinstance(data, dict) and isinstance(second, dict):
            added = {k: second[k] for k in second if k not in data}
            removed = {k: data[k] for k in data if k not in second}
            changed = {}
            for k in data:
                if k in second and data[k] != second[k]:
                    changed[k] = {"old": data[k], "new": second[k]}

            return {
                "added": added,
                "removed": removed,
                "changed": changed,
                "unchanged_count": len(data) - len(removed) - len(changed),
            }

        return {"equal": data == second}

    def _schema(self, data: Any, args: dict[str, Any]) -> dict[str, Any]:
        return self._infer_schema(data)

    def _infer_schema(self, data: Any, depth: int = 0) -> dict[str, Any]:
        if depth > 10:
            return {"type": "..."}

        if isinstance(data, dict):
            properties = {}
            for key, val in data.items():
                properties[key] = self._infer_schema(val, depth + 1)
            return {"type": "object", "properties": properties}
        elif isinstance(data, list):
            if not data:
                return {"type": "array", "items": {}}
            item_schema = self._infer_schema(data[0], depth + 1)
            return {"type": "array", "length": len(data), "items": item_schema}
        elif isinstance(data, bool):
            return {"type": "boolean"}
        elif isinstance(data, int):
            return {"type": "integer"}
        elif isinstance(data, float):
            return {"type": "number"}
        elif isinstance(data, str):
            return {"type": "string", "length": len(data)}
        elif data is None:
            return {"type": "null"}
        else:
            return {"type": str(type(data).__name__)}
