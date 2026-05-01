"""Structured what-if scenario planning with parameter sweeps and sensitivity analysis."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class ScenarioPlannerTool(BaseTool):
    name = "scenario_planner"
    description = (
        "Run structured what-if scenario analysis with parameter sweeps. "
        "Define base values and variations for any set of numeric parameters, "
        "then compute outcomes across all combinations. Use for pricing "
        "sensitivity, budget planning, risk assessment, or strategic option "
        "evaluation."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "parameters": {
                "type": "object",
                "description": (
                    "Parameter definitions. Each key is a parameter name, value "
                    "is an object with: base (number, required), range ([low, high], "
                    "optional), steps (int, optional, default 5), unit (string, optional). "
                    'Example: {"revenue": {"base": 1000000, "range": [800000, 1200000], '
                    '"steps": 5, "unit": "USD"}}'
                ),
            },
            "formula": {
                "type": "string",
                "description": (
                    "Expression using parameter names and basic math operators "
                    "(+, -, *, /, **, min, max, abs). "
                    'Example: "revenue * (1 - tax_rate) - costs"'
                ),
            },
            "output_name": {
                "type": "string",
                "description": "Label for the computed value (default: 'outcome')",
            },
            "scenarios": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "overrides": {"type": "object"},
                    },
                },
                "description": (
                    "Named scenario presets with parameter overrides. "
                    'Example: [{"name": "bull", "overrides": {"revenue": 1500000}}]'
                ),
            },
        },
        "required": ["parameters", "formula"],
    }

    # Safe expression evaluator — NO eval(). Tokenize and compute via
    # a simple recursive-descent parser supporting:
    #   + - * / ** ( ) and functions: min, max, abs, sqrt, log, exp

    # Token types
    _TOKEN_NUM = "NUM"
    _TOKEN_OP = "OP"
    _TOKEN_LPAREN = "LPAREN"
    _TOKEN_RPAREN = "RPAREN"
    _TOKEN_COMMA = "COMMA"
    _TOKEN_FUNC = "FUNC"
    _TOKEN_EOF = "EOF"

    _ALLOWED_FUNCS = {"min", "max", "abs", "sqrt", "log", "exp", "round"}

    _TOKEN_RE = re.compile(
        r"""
        (?P<number>[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?) |
        (?P<func>min|max|abs|sqrt|log|exp|round)(?=\s*\()     |
        (?P<ident>[a-zA-Z_][a-zA-Z_0-9]*)                     |
        (?P<op>\*\*|[+\-*/])                                   |
        (?P<lparen>\()                                          |
        (?P<rparen>\))                                          |
        (?P<comma>,)                                            |
        (?P<ws>\s+)
        """,
        re.VERBOSE,
    )

    class _ParseError(Exception):
        pass

    def _tokenize(
        self,
        expr: str,
        variables: dict[str, float],
    ) -> list[tuple[str, Any]]:
        tokens: list[tuple[str, Any]] = []
        pos = 0
        while pos < len(expr):
            m = self._TOKEN_RE.match(expr, pos)
            if not m:
                raise self._ParseError(
                    f"Unexpected character at position {pos}: '{expr[pos]}'"
                )
            pos = m.end()
            if m.group("ws"):
                continue
            if m.group("number") is not None:
                tokens.append((self._TOKEN_NUM, float(m.group("number"))))
            elif m.group("func"):
                tokens.append((self._TOKEN_FUNC, m.group("func")))
            elif m.group("ident"):
                name = m.group("ident")
                if name not in variables:
                    raise self._ParseError(
                        f"Unknown variable '{name}'. "
                        f"Available: {sorted(variables.keys())}"
                    )
                tokens.append((self._TOKEN_NUM, variables[name]))
            elif m.group("op"):
                tokens.append((self._TOKEN_OP, m.group("op")))
            elif m.group("lparen"):
                tokens.append((self._TOKEN_LPAREN, "("))
            elif m.group("rparen"):
                tokens.append((self._TOKEN_RPAREN, ")"))
            elif m.group("comma"):
                tokens.append((self._TOKEN_COMMA, ","))
        tokens.append((self._TOKEN_EOF, None))
        return tokens

    # Recursive descent parser
    class _Parser:
        def __init__(self, tokens: list[tuple[str, Any]], tool: "ScenarioPlannerTool"):
            self.tokens = tokens
            self.pos = 0
            self.tool = tool

        def peek(self) -> tuple[str, Any]:
            return self.tokens[self.pos]

        def consume(self, expected_type: str | None = None) -> tuple[str, Any]:
            tok = self.tokens[self.pos]
            if expected_type and tok[0] != expected_type:
                raise ScenarioPlannerTool._ParseError(
                    f"Expected {expected_type}, got {tok[0]} ('{tok[1]}')"
                )
            self.pos += 1
            return tok

        def parse(self) -> float:
            result = self.expr()
            if self.peek()[0] != ScenarioPlannerTool._TOKEN_EOF:
                raise ScenarioPlannerTool._ParseError(
                    f"Unexpected token after expression: {self.peek()}"
                )
            return result

        def expr(self) -> float:
            return self.add_sub()

        def add_sub(self) -> float:
            left = self.mul_div()
            while self.peek()[0] == ScenarioPlannerTool._TOKEN_OP and self.peek()[
                1
            ] in ("+", "-"):
                op = self.consume()[1]
                right = self.mul_div()
                if op == "+":
                    left += right
                else:
                    left -= right
            return left

        def mul_div(self) -> float:
            left = self.power()
            while self.peek()[0] == ScenarioPlannerTool._TOKEN_OP and self.peek()[
                1
            ] in ("*", "/"):
                op = self.consume()[1]
                right = self.power()
                if op == "*":
                    left *= right
                else:
                    if right == 0:
                        raise ScenarioPlannerTool._ParseError("Division by zero")
                    left /= right
            return left

        def power(self) -> float:
            base = self.unary()
            if (
                self.peek()[0] == ScenarioPlannerTool._TOKEN_OP
                and self.peek()[1] == "**"
            ):
                self.consume()
                exp = self.unary()
                return base**exp
            return base

        def unary(self) -> float:
            if (
                self.peek()[0] == ScenarioPlannerTool._TOKEN_OP
                and self.peek()[1] == "-"
            ):
                self.consume()
                return -self.atom()
            if (
                self.peek()[0] == ScenarioPlannerTool._TOKEN_OP
                and self.peek()[1] == "+"
            ):
                self.consume()
                return self.atom()
            return self.atom()

        def atom(self) -> float:
            tok_type, tok_val = self.peek()

            # Function call
            if tok_type == ScenarioPlannerTool._TOKEN_FUNC:
                return self.func_call()

            # Number (or resolved variable)
            if tok_type == ScenarioPlannerTool._TOKEN_NUM:
                self.consume()
                return float(tok_val)

            # Parenthesized expression
            if tok_type == ScenarioPlannerTool._TOKEN_LPAREN:
                self.consume()
                val = self.expr()
                self.consume(ScenarioPlannerTool._TOKEN_RPAREN)
                return val

            raise ScenarioPlannerTool._ParseError(
                f"Unexpected token: {tok_type} '{tok_val}'"
            )

        def func_call(self) -> float:
            _, func_name = self.consume(ScenarioPlannerTool._TOKEN_FUNC)
            self.consume(ScenarioPlannerTool._TOKEN_LPAREN)

            args: list[float] = []
            if self.peek()[0] != ScenarioPlannerTool._TOKEN_RPAREN:
                args.append(self.expr())
                while self.peek()[0] == ScenarioPlannerTool._TOKEN_COMMA:
                    self.consume()
                    args.append(self.expr())

            self.consume(ScenarioPlannerTool._TOKEN_RPAREN)

            func_map = {
                "min": lambda a: min(a),
                "max": lambda a: max(a),
                "abs": lambda a: abs(a[0]) if len(a) == 1 else None,
                "sqrt": lambda a: math.sqrt(a[0]) if len(a) == 1 else None,
                "log": lambda a: math.log(a[0]) if len(a) == 1 else None,
                "exp": lambda a: math.exp(a[0]) if len(a) == 1 else None,
                "round": lambda a: (
                    round(a[0])
                    if len(a) == 1
                    else round(a[0], int(a[1])) if len(a) == 2 else None
                ),
            }

            fn = func_map.get(func_name)
            if not fn:
                raise ScenarioPlannerTool._ParseError(f"Unknown function: {func_name}")

            result = fn(args)
            if result is None:
                raise ScenarioPlannerTool._ParseError(
                    f"Invalid argument count for {func_name}: got {len(args)}"
                )
            return float(result)

    def _safe_eval(self, formula: str, variables: dict[str, float]) -> float:
        tokens = self._tokenize(formula, variables)
        parser = self._Parser(tokens, self)
        return parser.parse()

    # Main execute
    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        params_def = arguments.get("parameters")
        formula = arguments.get("formula", "").strip()
        output_name = arguments.get("output_name", "outcome")
        named_scenarios = arguments.get("scenarios") or []

        if not params_def or not isinstance(params_def, dict):
            return ToolResult(
                content="Error: 'parameters' must be a non-empty object",
                is_error=True,
            )
        if not formula:
            return ToolResult(content="Error: 'formula' is required", is_error=True)

        # Validate and normalize parameter definitions
        validated: dict[str, dict[str, Any]] = {}
        for name, spec in params_def.items():
            if not isinstance(spec, dict):
                return ToolResult(
                    content=f"Error: parameter '{name}' must be an object with at least 'base'",
                    is_error=True,
                )
            if "base" not in spec:
                return ToolResult(
                    content=f"Error: parameter '{name}' is missing 'base' value",
                    is_error=True,
                )
            validated[name] = {
                "base": float(spec["base"]),
                "range": spec.get("range"),
                "steps": int(spec.get("steps", 5)),
                "unit": spec.get("unit", ""),
            }

        try:
            # 1. Compute base case
            base_vars = {name: spec["base"] for name, spec in validated.items()}
            base_outcome = self._safe_eval(formula, base_vars)
            base_case = {
                "params": {
                    name: {"value": spec["base"], "unit": spec["unit"]}
                    for name, spec in validated.items()
                },
                output_name: round(base_outcome, 4),
            }

            # 2. Parameter sweeps (one-at-a-time)
            parameter_sweep = []
            for param_name, spec in validated.items():
                rng = spec.get("range")
                if not rng or not isinstance(rng, (list, tuple)) or len(rng) < 2:
                    # Default: +/- 20% around base
                    low = spec["base"] * 0.8
                    high = spec["base"] * 1.2
                else:
                    low, high = float(rng[0]), float(rng[1])

                steps = max(2, min(spec["steps"], 50))
                step_size = (high - low) / (steps - 1) if steps > 1 else 0

                values_list = []
                for i in range(steps):
                    val = low + i * step_size
                    sweep_vars = {**base_vars, param_name: val}
                    outcome = self._safe_eval(formula, sweep_vars)
                    values_list.append(
                        {
                            "value": round(val, 4),
                            output_name: round(outcome, 4),
                        }
                    )

                parameter_sweep.append(
                    {
                        "param": param_name,
                        "unit": spec["unit"],
                        "base_value": spec["base"],
                        "sweep_range": [round(low, 4), round(high, 4)],
                        "steps": steps,
                        "values": values_list,
                    }
                )

            # 3. Named scenarios
            named_results = []
            for scenario in named_scenarios:
                if not isinstance(scenario, dict):
                    continue
                name = scenario.get("name", "unnamed")
                overrides = scenario.get("overrides", {})
                scenario_vars = {**base_vars}
                for k, v in overrides.items():
                    if k in scenario_vars:
                        scenario_vars[k] = float(v)
                outcome = self._safe_eval(formula, scenario_vars)
                named_results.append(
                    {
                        "name": name,
                        "params": {
                            k: {"value": v, "unit": validated[k]["unit"]}
                            for k, v in scenario_vars.items()
                            if k in validated
                        },
                        output_name: round(outcome, 4),
                        "delta_from_base": round(outcome - base_outcome, 4),
                        "delta_pct": (
                            round((outcome - base_outcome) / abs(base_outcome) * 100, 2)
                            if base_outcome != 0
                            else None
                        ),
                    }
                )

            # 4. Sensitivity analysis (elasticity)
            sensitivity = []
            for param_name, spec in validated.items():
                base_val = spec["base"]
                if base_val == 0:
                    sensitivity.append(
                        {
                            "param": param_name,
                            "elasticity": 0.0,
                            "direction": "neutral",
                            "note": "Base value is zero; elasticity undefined",
                        }
                    )
                    continue

                # Compute elasticity: % change in outcome / % change in input
                delta_pct = 0.01  # 1% perturbation
                perturbed_val = base_val * (1 + delta_pct)
                perturbed_vars = {**base_vars, param_name: perturbed_val}
                perturbed_outcome = self._safe_eval(formula, perturbed_vars)

                if base_outcome != 0:
                    outcome_pct_change = (perturbed_outcome - base_outcome) / abs(
                        base_outcome
                    )
                    elasticity = outcome_pct_change / delta_pct
                else:
                    elasticity = 0.0

                direction = (
                    "positive"
                    if elasticity > 0.01
                    else "negative" if elasticity < -0.01 else "neutral"
                )

                sensitivity.append(
                    {
                        "param": param_name,
                        "unit": spec["unit"],
                        "elasticity": round(elasticity, 4),
                        "direction": direction,
                        "interpretation": (
                            f"A 1% increase in {param_name} causes a "
                            f"{abs(elasticity) * 100:.2f}% "
                            f"{'increase' if elasticity > 0 else 'decrease'} in {output_name}"
                        ),
                    }
                )

            # Sort sensitivity by absolute elasticity (most sensitive first)
            sensitivity.sort(key=lambda x: abs(x.get("elasticity", 0)), reverse=True)

            output = {
                "formula": formula,
                "output_name": output_name,
                "base_case": base_case,
                "parameter_sweep": parameter_sweep,
                "named_scenarios": named_results,
                "sensitivity": sensitivity,
            }

            return ToolResult(
                content=json.dumps(output, indent=2),
                metadata={"output_name": output_name, "params": list(validated.keys())},
            )
        except self._ParseError as e:
            return ToolResult(content=f"Formula error: {e}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Scenario planning error: {e}", is_error=True)
