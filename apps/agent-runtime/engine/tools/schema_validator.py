"""Schema Validator Tool — validate data against JSON Schema, generate schemas, coerce types.

Ensures pipeline outputs match expected format before sending to external systems.
"""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class SchemaValidatorTool(BaseTool):
    name = "schema_validator"
    description = (
        "Validate JSON data against a schema, generate schema from sample data, "
        "or coerce data to match a schema. Ensures pipeline outputs are well-formed."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["validate", "generate_schema", "coerce"],
                "description": "Operation to perform",
            },
            "data": {
                "description": "The data to validate or analyze",
            },
            "schema": {
                "type": "object",
                "description": "JSON Schema to validate against (for 'validate' and 'coerce')",
            },
        },
        "required": ["operation", "data"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        operation = arguments.get("operation", "")
        data = arguments.get("data")
        schema = arguments.get("schema")

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                pass

        if operation == "validate":
            return self._validate(data, schema)
        elif operation == "generate_schema":
            return self._generate_schema(data)
        elif operation == "coerce":
            return self._coerce(data, schema)
        else:
            return ToolResult(
                content=f"Error: Unknown operation: {operation}", is_error=True
            )

    def _validate(self, data: Any, schema: dict | None) -> ToolResult:
        if not schema:
            return ToolResult(
                content="Error: schema required for validate operation", is_error=True
            )

        errors = []
        self._check_schema(data, schema, "", errors)

        return ToolResult(
            content=json.dumps(
                {
                    "valid": len(errors) == 0,
                    "error_count": len(errors),
                    "errors": errors[:20],  # Cap at 20 errors
                }
            )
        )

    def _check_schema(self, data: Any, schema: dict, path: str, errors: list) -> None:
        """Recursive schema validation (simplified JSON Schema subset)."""
        expected_type = schema.get("type")

        if expected_type == "object" and isinstance(data, dict):
            props = schema.get("properties", {})
            required = schema.get("required", [])

            for req in required:
                if req not in data:
                    errors.append(
                        {"path": f"{path}.{req}", "error": "required field missing"}
                    )

            for key, prop_schema in props.items():
                if key in data:
                    self._check_schema(data[key], prop_schema, f"{path}.{key}", errors)

        elif expected_type == "array" and isinstance(data, list):
            items_schema = schema.get("items", {})
            for i, item in enumerate(data[:100]):  # Check first 100 items
                self._check_schema(item, items_schema, f"{path}[{i}]", errors)

        elif expected_type == "string" and not isinstance(data, str):
            errors.append(
                {
                    "path": path,
                    "error": f"expected string, got {type(data).__name__}",
                    "value": str(data)[:50],
                }
            )

        elif expected_type == "number" and not isinstance(data, (int, float)):
            errors.append(
                {"path": path, "error": f"expected number, got {type(data).__name__}"}
            )

        elif expected_type == "boolean" and not isinstance(data, bool):
            errors.append(
                {"path": path, "error": f"expected boolean, got {type(data).__name__}"}
            )

    def _generate_schema(self, data: Any) -> ToolResult:
        """Infer JSON Schema from sample data."""
        schema = self._infer_type(data)
        return ToolResult(
            content=json.dumps({"status": "success", "schema": schema}, indent=2)
        )

    def _infer_type(self, value: Any, depth: int = 0) -> dict:
        if depth > 10:
            return {"type": "object"}

        if isinstance(value, dict):
            properties = {}
            for k, v in value.items():
                properties[k] = self._infer_type(v, depth + 1)
            return {
                "type": "object",
                "properties": properties,
                "required": list(value.keys()),
            }
        elif isinstance(value, list):
            if value:
                return {"type": "array", "items": self._infer_type(value[0], depth + 1)}
            return {"type": "array", "items": {}}
        elif isinstance(value, bool):
            return {"type": "boolean"}
        elif isinstance(value, int):
            return {"type": "number"}
        elif isinstance(value, float):
            return {"type": "number"}
        elif isinstance(value, str):
            return {"type": "string"}
        elif value is None:
            return {"type": "string", "nullable": True}
        return {"type": "string"}

    def _coerce(self, data: Any, schema: dict | None) -> ToolResult:
        """Attempt to fix data to match schema (type casting, defaults)."""
        if not schema:
            return ToolResult(
                content="Error: schema required for coerce", is_error=True
            )

        coerced = self._coerce_value(data, schema)
        return ToolResult(
            content=json.dumps({"status": "success", "coerced": coerced}, default=str)
        )

    def _coerce_value(self, value: Any, schema: dict) -> Any:
        expected = schema.get("type")
        if expected == "string" and not isinstance(value, str):
            return str(value) if value is not None else schema.get("default", "")
        elif expected == "number" and not isinstance(value, (int, float)):
            try:
                return float(value)
            except (ValueError, TypeError):
                return schema.get("default", 0)
        elif expected == "boolean" and not isinstance(value, bool):
            return bool(value)
        elif expected == "object" and isinstance(value, dict):
            props = schema.get("properties", {})
            result = {}
            for key, prop_schema in props.items():
                if key in value:
                    result[key] = self._coerce_value(value[key], prop_schema)
                elif "default" in prop_schema:
                    result[key] = prop_schema["default"]
            return result
        elif expected == "array" and isinstance(value, list):
            items_schema = schema.get("items", {})
            return [self._coerce_value(item, items_schema) for item in value]
        return value
