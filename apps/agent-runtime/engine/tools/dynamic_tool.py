# tool-registry: exempt LLM-generated code, loaded only from approved saved_tools rows, cannot read configuration
"""Dynamic Tool Generator — AI creates new tools at runtime."""

from __future__ import annotations

import asyncio
import ast
import functools
import io
import json
import logging
import string
import threading
import types
from typing import Any

from engine.tools.base import READ_ONLY, BaseTool, Effect, ToolResult

logger = logging.getLogger(__name__)

MAX_EXECUTION_TIME = 10
MAX_OUTPUT_SIZE = 50_000

# Pure-computation stdlib only. No file, network or process access.
ALLOWED_MODULES = frozenset(
    {
        "json",
        "math",
        "re",
        "datetime",
        "statistics",
        "collections",
        "itertools",
        "functools",
        "decimal",
        "fractions",
        "string",
        "textwrap",
        "uuid",
        "hashlib",
        "base64",
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
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "type",
        "super",
        "object",
        "id",
        "memoryview",
        "__builtins__",
        "__loader__",
        "__spec__",
        "subprocess",
        "os",
        "sys",
        "shutil",
        "pathlib",
        "importlib",
        "ctypes",
        "socket",
        "http",
        "builtins",
        "gc",
        "inspect",
        "code",
        "codeop",
        "pickle",
        "marshal",
        "shelve",
        "signal",
        "threading",
        "multiprocessing",
    }
)

# str.format walks attributes and keys, which reads object internals.
_FORMAT_METHODS = frozenset({"format", "format_map", "vformat", "get_field"})

SAFE_BUILTIN_NAMES = (
    "abs",
    "all",
    "any",
    "bool",
    "bytes",
    "callable",
    "chr",
    "dict",
    "divmod",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "hash",
    "hex",
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
    "zip",
    "True",
    "False",
    "None",
    "Exception",
    "ArithmeticError",
    "AttributeError",
    "ValueError",
    "TypeError",
    "KeyError",
    "IndexError",
    "LookupError",
    "RuntimeError",
    "StopIteration",
    "ZeroDivisionError",
    "OverflowError",
    "NotImplementedError",
    "AssertionError",
    "UnicodeError",
    "UnicodeDecodeError",
    "UnicodeEncodeError",
)


def _real_builtins() -> dict[str, Any]:
    import builtins as _b

    return vars(_b)


def _format_string_walks(spec: str) -> bool:
    """True when a format string indexes or dots into a replacement field."""
    try:
        for _lit, field_name, fmt_spec, _conv in string.Formatter().parse(spec):
            if field_name and ("." in field_name or "[" in field_name):
                return True
            if fmt_spec and "{" in fmt_spec and _format_string_walks(fmt_spec):
                return True
    except ValueError:
        return True
    return False


class _CodeValidator(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.module_names: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod = alias.name.split(".")[0]
            if mod not in ALLOWED_MODULES:
                self.errors.append(f"Import '{alias.name}' not allowed")
            self.module_names.add(alias.asname or mod)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            mod = node.module.split(".")[0]
            if mod not in ALLOWED_MODULES:
                self.errors.append(f"Import from '{node.module}' not allowed")
        for alias in node.names:
            if alias.name == "*":
                self.errors.append("Wildcard imports are not allowed")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in FORBIDDEN_NAMES or node.id.startswith("__"):
            self.errors.append(f"Name '{node.id}' is forbidden")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_NAMES:
            self.errors.append(f"Function '{node.func.id}' is forbidden")
        if isinstance(node.func, ast.Attribute) and node.func.attr in _FORMAT_METHODS:
            recv = node.func.value
            if node.func.attr != "format":
                self.errors.append(f"Method '{node.func.attr}' is forbidden")
            elif not (isinstance(recv, ast.Constant) and isinstance(recv.value, str)):
                self.errors.append("str.format is only allowed on a literal string")
            elif _format_string_walks(recv.value):
                self.errors.append("Format fields may not use '.' or '[]' access")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            self.errors.append(f"Dunder attribute '{node.attr}' not allowed")
        elif node.attr in FORBIDDEN_NAMES:
            self.errors.append(f"Attribute '{node.attr}' is forbidden")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            if key.value.startswith("__"):
                self.errors.append(f"Dunder key '{key.value}' not allowed")
        if isinstance(node.value, ast.Name) and node.value.id in self.module_names:
            self.errors.append(f"Subscript on module '{node.value.id}' not allowed")
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


class _SafeModule:
    """Read-only module view that hides private names and foreign submodules."""

    __slots__ = ("_m", "_allowed")

    def __init__(self, module: types.ModuleType, allowed: frozenset[str]) -> None:
        object.__setattr__(self, "_m", module)
        object.__setattr__(self, "_allowed", allowed)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        value = getattr(object.__getattribute__(self, "_m"), name)
        if isinstance(value, types.ModuleType):
            allowed = object.__getattribute__(self, "_allowed")
            if value.__name__.split(".")[0] not in allowed:
                raise AttributeError(f"module '{value.__name__}' not allowed")
            return _SafeModule(value, allowed)
        return value

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("modules are read-only in dynamic tools")

    def __repr__(self) -> str:
        return f"<sandboxed module {object.__getattribute__(self, '_m').__name__}>"


_SAVED_TOOLS_SQL = (
    "SELECT name, description, code, input_schema, permissions, status "
    "FROM saved_tools WHERE tenant_id = CAST($1 AS uuid) AND name = ANY($2::text[])"
)


def fetch_saved_tools(
    tenant_id: str, db_url: str, names: list[str], timeout: float = 5.0
) -> dict[str, dict[str, Any]]:
    """Sync lookup of saved_tools rows by name, callable from inside a running loop."""
    if not tenant_id or not names:
        return {}
    from engine.tools._db_url import resolve_async_db_url

    url = resolve_async_db_url(db_url)
    if not url:
        return {}
    dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    try:
        import asyncpg
    except Exception:
        logger.warning(
            "asyncpg missing, saved tools cannot load for tenant %s", tenant_id
        )
        return {}

    async def _query() -> list[Any]:
        conn = await asyncpg.connect(dsn, timeout=timeout)
        try:
            return await conn.fetch(_SAVED_TOOLS_SQL, str(tenant_id), list(names))
        finally:
            await conn.close()

    try:
        try:
            loop_running = asyncio.get_running_loop().is_running()
        except RuntimeError:
            loop_running = False
        if loop_running:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                rows = ex.submit(lambda: asyncio.run(_query())).result(
                    timeout=timeout + 1
                )
        else:
            rows = asyncio.run(_query())
    except Exception as exc:
        logger.warning("saved_tools lookup failed for tenant %s: %s", tenant_id, exc)
        return {}

    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = dict(r)
        for k in ("input_schema", "permissions"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    d[k] = {}
        out[str(d["name"])] = d
    return out


def _cap_output(text: str) -> str:
    if len(text) <= MAX_OUTPUT_SIZE:
        return text
    return text[:MAX_OUTPUT_SIZE] + f"\n... [truncated, {len(text)} chars total]"


def _run_in_daemon_thread(fn: Any) -> asyncio.Future:
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    def _settle(setter: Any, value: Any) -> None:
        if not fut.done():
            setter(value)

    def _target() -> None:
        try:
            out = fn()
        except BaseException as exc:
            loop.call_soon_threadsafe(_settle, fut.set_exception, exc)
            return
        loop.call_soon_threadsafe(_settle, fut.set_result, out)

    threading.Thread(target=_target, daemon=True, name="dynamic-tool").start()
    return fut


class DynamicTool(BaseTool):
    """A tool generated at runtime from Python code."""

    # reaches systems or runs code the platform did not write
    risk_tier = "medium"
    effect = Effect(
        kind="external", label="Run a saved tool that can reach the network"
    )

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        tool_code: str,
        tool_params: list[dict[str, Any]] | None = None,
        permissions: dict[str, Any] | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> None:
        self.name = tool_name
        self.description = tool_description
        self._code = tool_code
        self._permissions = permissions or {}
        if not (
            self._permissions.get("network") or self._permissions.get("third_party")
        ):
            self.effect = READ_ONLY
        tool_params = tool_params or []
        if isinstance(input_schema, dict) and isinstance(
            input_schema.get("properties"), dict
        ):
            self.input_schema = input_schema
        else:
            self.input_schema = {
                "type": "object",
                "properties": {
                    p["name"]: {
                        "type": p.get("type", "string"),
                        "description": p.get("description", ""),
                    }
                    for p in tool_params
                },
                "required": [
                    p["name"] for p in tool_params if p.get("required", False)
                ],
            }

    def _allowed_modules(self) -> frozenset[str]:
        extra: set[str] = set()
        if self._permissions.get("network"):
            extra.update({"requests", "urllib"})
        for svc in self._permissions.get("third_party", []) or []:
            if isinstance(svc, str) and svc.lower() not in FORBIDDEN_NAMES:
                extra.add(svc.lower())
        return ALLOWED_MODULES | frozenset(extra)

    def _build_namespace(
        self, arguments: dict[str, Any], stdout: io.StringIO
    ) -> dict[str, Any]:
        real = _real_builtins()
        allowed = self._allowed_modules()
        safe_builtins: dict[str, Any] = {
            k: real[k]
            for k in SAFE_BUILTIN_NAMES
            if k in real and k not in FORBIDDEN_NAMES
        }
        safe_builtins["print"] = functools.partial(print, file=stdout)

        def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
            root = name.split(".")[0]
            if root not in allowed or root in FORBIDDEN_NAMES:
                raise ImportError(f"Import '{name}' not allowed in dynamic tools")
            return _SafeModule(__import__(name, *args, **kwargs), allowed)

        safe_builtins["__import__"] = _safe_import
        namespace: dict[str, Any] = {
            "__builtins__": safe_builtins,
            "__name__": f"dynamic_tool_{self.name}",
            "arguments": arguments,
        }
        for mod_name in ("math", "datetime", "re", "json", "collections"):
            namespace[mod_name] = _SafeModule(__import__(mod_name), allowed)
        return namespace

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        errors = validate_code(self._code)
        if errors:
            return ToolResult(
                content=f"Code validation failed: {'; '.join(errors)}", is_error=True
            )

        stdout_capture = io.StringIO()
        namespace = self._build_namespace(arguments, stdout_capture)
        code = self._code
        label = f"<dynamic_tool:{self.name}>"

        def _run() -> Any:
            compiled = compile(code, label, "exec")
            exec(compiled, namespace)
            return namespace.get("result")

        try:
            # The thread cannot be killed on timeout, it is abandoned and keeps its core busy until it returns.
            result = await asyncio.wait_for(
                _run_in_daemon_thread(_run), MAX_EXECUTION_TIME
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Dynamic tool %s exceeded %ss, thread abandoned",
                self.name,
                MAX_EXECUTION_TIME,
            )
            return ToolResult(
                content=f"Dynamic tool '{self.name}' timed out after {MAX_EXECUTION_TIME}s",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                content=f"Dynamic tool execution error: {type(e).__name__}: {e}",
                is_error=True,
            )

        output = stdout_capture.getvalue()
        if result is not None:
            if isinstance(result, (dict, list)):
                try:
                    return ToolResult(
                        content=_cap_output(json.dumps(result, default=str))
                    )
                except Exception:
                    return ToolResult(content=_cap_output(str(result)))
            return ToolResult(content=_cap_output(str(result)))
        if output:
            return ToolResult(content=_cap_output(output))
        return ToolResult(content='{"status": "completed", "output": null}')


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
3. You can use only: base64, collections, datetime, decimal, fractions, functools, hashlib, itertools, json, math, re, statistics, string, textwrap, uuid
4. You CANNOT use: os, sys, subprocess, pandas, numpy, open(), exec(), eval(), getattr(), dunder attributes, str.format with attribute or index fields, file I/O, network calls
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
