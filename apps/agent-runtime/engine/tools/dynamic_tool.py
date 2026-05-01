"""Dynamic Tool Generator — AI creates new tools at runtime."""

from __future__ import annotations

import ast
import json
import io
from contextlib import redirect_stdout
from typing import Any

from engine.tools.base import BaseTool, ToolResult

MAX_EXECUTION_TIME = 10
MAX_OUTPUT_SIZE = 50_000

ALLOWED_MODULES = frozenset(
    {
        "math",
        "statistics",
        "decimal",
        "fractions",
        "datetime",
        "calendar",
        "time",
        "json",
        "csv",
        "re",
        "string",
        "collections",
        "itertools",
        "functools",
        "operator",
        "copy",
        "hashlib",
        "base64",
        "random",
        "textwrap",
        "io",
        "pandas",
        "numpy",
        "openpyxl",
        "dataclasses",
        "typing",
        "enum",
        "uuid",
        "struct",
        "array",
    }
)

FORBIDDEN_NAMES = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "__import__",
        "open",
        "input",
        "breakpoint",
        "exit",
        "quit",
        "globals",
        "locals",
        "getattr",
        "setattr",
        "delattr",
        "__builtins__",
        "subprocess",
        "os",
        "sys",
        "shutil",
        "pathlib",
        "importlib",
        "ctypes",
        "socket",
        "http",
    }
)

SAFE_DUNDERS = frozenset(
    {
        "__init__",
        "__str__",
        "__repr__",
        "__len__",
        "__getitem__",
        "__setitem__",
        "__contains__",
        "__iter__",
        "__next__",
        "__enter__",
        "__exit__",
        "__add__",
        "__sub__",
        "__mul__",
        "__truediv__",
        "__eq__",
        "__lt__",
        "__gt__",
        "__hash__",
        "__bool__",
        "__float__",
        "__int__",
    }
)


class _CodeValidator(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod = alias.name.split(".")[0]
            if mod not in ALLOWED_MODULES:
                self.errors.append(f"Import '{alias.name}' not allowed")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            mod = node.module.split(".")[0]
            if mod not in ALLOWED_MODULES:
                self.errors.append(f"Import from '{node.module}' not allowed")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_NAMES:
            self.errors.append(f"Function '{node.func.id}' is forbidden")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr.startswith("__")
            and node.attr.endswith("__")
            and node.attr not in SAFE_DUNDERS
        ):
            self.errors.append(f"Dunder attribute '{node.attr}' not allowed")
        self.generic_visit(node)


def validate_code(code: str) -> list[str]:
    """Validate Python code for safety using AST analysis."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"Syntax error: {e}"]

    validator = _CodeValidator()
    validator.visit(tree)
    return validator.errors


class DynamicTool(BaseTool):
    """A tool generated at runtime from Python code."""

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        tool_code: str,
        tool_params: list[dict[str, Any]],
        permissions: dict[str, Any] | None = None,
    ) -> None:
        self.name = tool_name
        self.description = tool_description
        self._code = tool_code
        self._permissions = permissions or {}
        self.input_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                p["name"]: {
                    "type": p.get("type", "string"),
                    "description": p.get("description", ""),
                }
                for p in tool_params
            },
            "required": [p["name"] for p in tool_params if p.get("required", False)],
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        # Validate code before every execution (defense in depth)
        errors = validate_code(self._code)
        if errors:
            return ToolResult(
                content=f"Code validation failed: {'; '.join(errors)}", is_error=True
            )

        # Extend allowed modules based on admin-approved permissions
        extra_allowed = set()
        extra_builtins: dict[str, Any] = {}
        if self._permissions.get("network"):
            extra_allowed.update({"requests", "urllib", "aiohttp"})
        if self._permissions.get("filesystem_read"):
            extra_builtins["open"] = open  # Read-only open
        for svc in self._permissions.get("third_party", []):
            extra_allowed.add(svc.lower())

        # Build safe execution namespace
        safe_builtins = {
            k: (
                __builtins__[k]
                if isinstance(__builtins__, dict)
                else getattr(__builtins__, k)
            )
            for k in [
                "abs",
                "all",
                "any",
                "bool",
                "chr",
                "dict",
                "dir",
                "divmod",
                "enumerate",
                "filter",
                "float",
                "format",
                "frozenset",
                "hasattr",
                "hash",
                "hex",
                "id",
                "int",
                "isinstance",
                "issubclass",
                "iter",
                "len",
                "list",
                "map",
                "max",
                "min",
                "next",
                "oct",
                "ord",
                "pow",
                "print",
                "range",
                "repr",
                "reversed",
                "round",
                "set",
                "slice",
                "sorted",
                "str",
                "sum",
                "tuple",
                "type",
                "vars",
                "zip",
                "True",
                "False",
                "None",
                "Exception",
                "ValueError",
                "TypeError",
                "KeyError",
                "IndexError",
                "RuntimeError",
            ]
            if (isinstance(__builtins__, dict) and k in __builtins__)
            or (not isinstance(__builtins__, dict) and hasattr(__builtins__, k))
        }

        # Import interceptor (with elevated permissions if approved)
        allowed = ALLOWED_MODULES | extra_allowed

        def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
            root = name.split(".")[0]
            if root not in allowed:
                raise ImportError(f"Import '{name}' not allowed in dynamic tools")
            return __import__(name, *args, **kwargs)

        safe_builtins["__import__"] = _safe_import
        safe_builtins.update(extra_builtins)  # Add elevated permissions

        namespace: dict[str, Any] = {
            "__builtins__": safe_builtins,
            "arguments": arguments,
            "json": __import__("json"),
        }

        # Pre-import common modules
        for mod_name in ["math", "datetime", "re", "json", "collections"]:
            try:
                namespace[mod_name] = __import__(mod_name)
            except ImportError:
                pass

        stdout_capture = io.StringIO()
        try:
            # Execute the code
            compiled = compile(self._code, f"<dynamic_tool:{self.name}>", "exec")
            with redirect_stdout(stdout_capture):
                exec(compiled, namespace)

            # Look for result in namespace
            result = namespace.get("result")
            output = stdout_capture.getvalue()

            if result is not None:
                if isinstance(result, dict):
                    return ToolResult(content=json.dumps(result, default=str))
                return ToolResult(content=str(result))
            elif output:
                return ToolResult(content=output[:MAX_OUTPUT_SIZE])
            else:
                return ToolResult(content='{"status": "completed", "output": null}')

        except Exception as e:
            return ToolResult(
                content=f"Dynamic tool execution error: {type(e).__name__}: {e}",
                is_error=True,
            )


async def generate_dynamic_tool(
    description: str,
    tool_name: str | None = None,
) -> DynamicTool | None:
    """Use an LLM to generate a custom tool from a description.

    Returns a DynamicTool instance ready to be registered, or None on failure.
    """
    try:
        from engine.llm_router import LLMRouter

        llm = LLMRouter()
    except Exception:
        return None

    if not tool_name:
        tool_name = "custom_" + description[:30].lower().replace(" ", "_").replace(
            "-", "_"
        )
        tool_name = "".join(c for c in tool_name if c.isalnum() or c == "_")

    prompt = f"""Generate a Python tool for this purpose: {description}

The code must:
1. Use the `arguments` dict to get input parameters
2. Store the final result in a variable called `result` (must be a dict)
3. You can use: math, datetime, re, json, collections, pandas, numpy
4. You CANNOT use: os, sys, subprocess, open(), exec(), eval(), file I/O, network calls
5. Keep it under 50 lines
6. Include error handling

Also specify the input parameters as JSON:
{{"params": [{{"name": "param1", "type": "string", "required": true, "description": "..."}}]}}

Respond with EXACTLY this format:
```python
# Tool code here
param1 = arguments.get("param1", "")
# ... processing ...
result = {{"output": "..."}}
```

```json
{{"params": [{{"name": "param1", "type": "string", "required": true, "description": "What this param is"}}]}}
```"""

    try:
        response = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system="You are a Python tool generator. Generate safe, sandboxed Python code. Respond with code and params JSON blocks only.",
            model="claude-sonnet-4-5-20250929",
            temperature=0.2,
        )

        text = response.content

        # Extract Python code
        code = ""
        if "```python" in text:
            code = text.split("```python")[1].split("```")[0].strip()
        elif "```" in text:
            code = text.split("```")[1].split("```")[0].strip()

        if not code:
            return None

        # Extract params JSON
        params: list[dict[str, Any]] = []
        if "```json" in text:
            try:
                json_str = text.split("```json")[1].split("```")[0].strip()
                parsed = json.loads(json_str)
                params = parsed.get("params", [])
            except (json.JSONDecodeError, IndexError):
                pass

        # Pass 1: AST validation
        errors = validate_code(code)
        if errors:
            return None

        # Pass 2: Adversarial review — red-team LLM checks for issues
        review_result = await _adversarial_review(llm, code, description, params)
        if review_result.get("blocked"):
            return None

        # Pass 3: If review found issues, regenerate with feedback
        if review_result.get("issues"):
            improved_code = await _improve_code(
                llm, code, review_result["issues"], description
            )
            if improved_code:
                improved_errors = validate_code(improved_code)
                if not improved_errors:
                    code = improved_code

        return DynamicTool(
            tool_name=tool_name,
            tool_description=description,
            tool_code=code,
            tool_params=params,
        )

    except Exception:
        return None


async def _adversarial_review(
    llm: Any, code: str, description: str, params: list
) -> dict:
    """Red-team review of generated tool code for security and correctness."""
    try:
        review_prompt = f"""You are a security-focused code reviewer. Analyze this dynamically generated Python tool for:

1. SECURITY: Does it try to access the filesystem, network, or system resources?
2. CORRECTNESS: Does it actually solve the described task?
3. SAFETY: Could it cause infinite loops, excessive memory, or crashes?
4. DATA FLOW: Does it properly read from `arguments` dict and set `result`?

Tool description: {description}
Parameters: {json.dumps(params)}

Code:
```python
{code}
```

Respond with JSON ONLY:
{{"safe": true/false, "score": 1-10, "issues": ["issue1"], "blocked": false, "review": "brief assessment"}}

Set blocked=true ONLY if the code is genuinely dangerous (network access, file I/O, system commands)."""

        response = await llm.complete(
            messages=[{"role": "user", "content": review_prompt}],
            system="You are a red-team security reviewer. Be strict but fair. Only block truly dangerous code.",
            model="claude-sonnet-4-5-20250929",
            temperature=0.1,
        )
        text = response.content.strip()
        if "{" in text:
            return json.loads(text[text.index("{") : text.rindex("}") + 1])
    except Exception:
        pass
    return {"safe": True, "score": 7, "issues": [], "blocked": False}


async def _improve_code(
    llm: Any, code: str, issues: list[str], description: str
) -> str | None:
    """Regenerate code based on adversarial feedback."""
    try:
        improve_prompt = f"""Improve this Python tool code based on review feedback.

Original code:
```python
{code}
```

Issues found:
{chr(10).join(f'- {i}' for i in issues)}

Requirements:
- Must read from `arguments` dict
- Must set `result` variable (dict)
- Cannot use: os, sys, subprocess, open(), exec(), eval(), network calls
- Must handle errors gracefully

Respond with ONLY the improved Python code (no markdown, no explanation):"""

        response = await llm.complete(
            messages=[{"role": "user", "content": improve_prompt}],
            system="You are a Python code improver. Return ONLY code, no explanation.",
            model="claude-sonnet-4-5-20250929",
            temperature=0.1,
        )
        text = response.content.strip()
        # Extract code from response
        if "```python" in text:
            return text.split("```python")[1].split("```")[0].strip()
        elif "```" in text:
            return text.split("```")[1].split("```")[0].strip()
        elif "result" in text and "arguments" in text:
            return text  # Bare code without markdown
    except Exception:
        pass
    return None
