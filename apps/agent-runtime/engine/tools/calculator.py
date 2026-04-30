from __future__ import annotations

import ast
import math
import operator
from typing import Any

from engine.tools.base import BaseTool, ToolResult

SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

SAFE_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "pi": math.pi,
    "e": math.e,
}


def _safe_eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, complex)):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value!r}")
    if isinstance(node, ast.BinOp):
        op_fn = SAFE_OPERATORS.get(type(node.op))
        if not op_fn:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return op_fn(left, right)
    if isinstance(node, ast.UnaryOp):
        op_fn = SAFE_OPERATORS.get(type(node.op))
        if not op_fn:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op_fn(_safe_eval(node.operand))
    if isinstance(node, ast.Name):
        if node.id in SAFE_FUNCTIONS:
            val = SAFE_FUNCTIONS[node.id]
            if isinstance(val, (int, float)):
                return val
        raise ValueError(f"Unknown variable: {node.id}")
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in SAFE_FUNCTIONS:
            fn = SAFE_FUNCTIONS[node.func.id]
            if callable(fn):
                args = [_safe_eval(a) for a in node.args]
                return fn(*args)
        raise ValueError(f"Unsupported function call")
    raise ValueError(f"Unsupported expression: {type(node).__name__}")


class CalculatorTool(BaseTool):
    name = "calculator"
    description = (
        "Evaluate a mathematical expression safely. Supports basic arithmetic, "
        "exponentiation, and math functions (sqrt, log, sin, cos, etc.)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The mathematical expression to evaluate, e.g. '(2 + 3) * 4'",
            },
        },
        "required": ["expression"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        expression = arguments.get("expression", "")
        if not expression:
            return ToolResult(content="Error: expression is required", is_error=True)

        try:
            tree = ast.parse(expression.strip(), mode="eval")
            result = _safe_eval(tree)
            return ToolResult(
                content=str(result),
                metadata={"expression": expression, "result": result},
            )
        except (ValueError, SyntaxError, TypeError, ZeroDivisionError) as e:
            return ToolResult(content=f"Evaluation error: {str(e)}", is_error=True)
