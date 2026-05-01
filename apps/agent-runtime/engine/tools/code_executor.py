"""Safe Python code execution for data transformations, file generation, and comple"""

from __future__ import annotations

import ast
import io
import json
import logging
import os
import traceback
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

MAX_EXECUTION_TIME = 30  # Increased from 10s for complex operations
MAX_OUTPUT_SIZE = 100_000
EXPORT_DIR = os.environ.get("EXPORT_DIR", "/tmp/abenix_exports")

CORE_MODULES = frozenset(
    {
        # Standard library — math & numbers
        "math",
        "statistics",
        "decimal",
        "fractions",
        "cmath",
        # Standard library — date & time
        "datetime",
        "calendar",
        "time",
        "zoneinfo",
        # Standard library — text processing
        "json",
        "csv",
        "re",
        "string",
        "textwrap",
        "html",
        "xml",
        # Standard library — data structures & functional
        "collections",
        "itertools",
        "functools",
        "operator",
        "copy",
        "dataclasses",
        "typing",
        "enum",
        "abc",
        # Standard library — encoding & hashing
        "hashlib",
        "base64",
        "binascii",
        "struct",
        "codecs",
        # Standard library — I/O & formatting
        "io",
        "pprint",
        "difflib",
        # Standard library — misc utilities
        "random",
        "uuid",
        "array",
        "bisect",
        "heapq",
        "contextlib",
        "warnings",
    }
)

EXTENDED_MODULES = frozenset(
    {
        # Data science
        "pandas",
        "numpy",
        "scipy",
        # Excel / spreadsheets
        "openpyxl",
        "xlrd",
        "xlsxwriter",
        # PDF generation
        "reportlab",
        "fpdf",
        # Charting & visualization (non-interactive backends)
        "matplotlib",
        "seaborn",
        "plotly",
        # HTML / XML parsing
        "bs4",
        "lxml",
        # Image processing
        "PIL",
        "pillow",
        # Scientific / ML (read-only, no training)
        "sklearn",
        "scikit_learn",
        # PowerPoint
        "pptx",
        # Tabular display
        "tabulate",
        "prettytable",
        # Compression
        "zipfile",
        "gzip",
        "tarfile",
    }
)

# Combined allowed set for the validator
ALLOWED_MODULES = CORE_MODULES | EXTENDED_MODULES

FORBIDDEN_NAMES = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "input",
        "breakpoint",
        "exit",
        "quit",
        "globals",
        "locals",
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
        "aiohttp",
        "urllib",
        "requests",
        "httpx",
    }
)
# Note: "open" is not forbidden — a sandboxed _safe_open is provided
# that only allows writes to EXPORT_DIR.
# Note: "getattr" allowed for pandas/numpy attribute access.
# Note: "__import__" allowed via safe wrapper that checks ALLOWED_MODULES.


class _CodeValidator(ast.NodeVisitor):
    def __init__(self, allowed: frozenset[str] | set[str] = ALLOWED_MODULES) -> None:
        self.errors: list[str] = []
        self.imports: list[str] = []
        self._allowed = allowed

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod = alias.name.split(".")[0]
            self.imports.append(mod)
            if mod not in self._allowed:
                self.errors.append(f"Import not allowed: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            mod = node.module.split(".")[0]
            self.imports.append(mod)
            if mod not in self._allowed:
                self.errors.append(f"Import not allowed: {node.module}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in FORBIDDEN_NAMES:
            self.errors.append(f"Access to '{node.id}' is not allowed")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__") and node.attr.endswith("__"):
            safe_dunders = (
                "__init__",
                "__str__",
                "__repr__",
                "__len__",
                "__getitem__",
                "__setitem__",
                "__iter__",
                "__next__",
                "__enter__",
                "__exit__",
                "__contains__",
                "__eq__",
                "__lt__",
                "__gt__",
                "__le__",
                "__ge__",
                "__ne__",
                "__hash__",
                "__bool__",
                "__call__",
                "__name__",
                "__class__",
                "__dict__",
                "__doc__",
                "__module__",
                "__add__",
                "__sub__",
                "__mul__",
                "__truediv__",
                "__floordiv__",
                "__mod__",
                "__pow__",
            )
            if node.attr not in safe_dunders:
                self.errors.append(f"Access to dunder '{node.attr}' is not allowed")
        self.generic_visit(node)


def _validate_code(
    code: str, allowed_modules: frozenset[str] | set[str] = ALLOWED_MODULES
) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"Syntax error: {e}"]

    validator = _CodeValidator(allowed=allowed_modules)
    validator.visit(tree)
    return validator.errors


class CodeExecutorTool(BaseTool):
    name = "code_executor"
    description = (
        "Execute Python code safely in a sandboxed environment. Supports complex data "
        "transformations, statistical computations, file generation (Excel, PDF, charts, "
        "PowerPoint), image processing, and algorithmic operations. "
        "Core libraries always available: pandas, numpy, openpyxl, json, csv, re, math, "
        "datetime, collections, itertools, statistics, uuid, io, base64. "
        "Extended libraries available: scipy, matplotlib, seaborn, reportlab, fpdf, "
        "Pillow (PIL), beautifulsoup4 (bs4), python-pptx (pptx), scikit-learn (sklearn), "
        "plotly, tabulate, xlsxwriter, lxml, zipfile, gzip. "
        "Can save files to the export directory using open('file.ext', 'wb') or "
        "save_export('file.ext', bytes_data). Pipeline data available via context['node_id']. "
        "Does NOT support network calls, system commands, or arbitrary file system access. "
        "Additional modules can be requested via extra_modules — they are LLM-validated for safety."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute. Use print() for output. Last expression is captured as result.",
            },
            "variables": {
                "type": "object",
                "description": "Pre-defined variables available in the execution context as globals",
            },
            "extra_modules": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Additional Python modules to allow for this execution. "
                    "These are validated by an LLM safety review before being permitted. "
                    "Example: ['networkx', 'sympy', 'shapely']. Modules that provide "
                    "network access, system commands, or code execution are rejected."
                ),
            },
        },
        "required": ["code"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        code = arguments.get("code", "")
        variables = arguments.get("variables", {})
        extra_modules = arguments.get("extra_modules", [])
        # Pipeline context injection — upstream node outputs available as 'context'
        pipeline_ctx = arguments.pop("__pipeline_context__", None)
        if pipeline_ctx and isinstance(pipeline_ctx, dict):
            variables["context"] = pipeline_ctx

        if not code.strip():
            return ToolResult(content="Error: code is required", is_error=True)

        # Handle extra_modules — LLM safety validation for user-requested packages
        session_allowed = set(ALLOWED_MODULES)
        if extra_modules and isinstance(extra_modules, list):
            new_modules = [
                m.strip() for m in extra_modules if isinstance(m, str) and m.strip()
            ]
            # Filter out already-allowed and always-forbidden modules
            to_validate = [
                m
                for m in new_modules
                if m not in session_allowed and m not in FORBIDDEN_NAMES
            ]
            if to_validate:
                validated = await self._validate_extra_modules(to_validate, code)
                if validated.get("rejected"):
                    return ToolResult(
                        content="Module safety review failed:\n"
                        + "\n".join(
                            f"  - {m}: {r}"
                            for m, r in zip(to_validate, validated.get("reasons", []))
                        ),
                        is_error=True,
                    )
                session_allowed.update(validated.get("approved", []))

        errors = _validate_code(code, allowed_modules=session_allowed)
        if errors:
            return ToolResult(
                content="Code validation failed:\n"
                + "\n".join(f"  - {e}" for e in errors),
                is_error=True,
            )

        stdout_capture = io.StringIO()
        result_value = None

        safe_globals: dict[str, Any] = {"__builtins__": {}}
        for mod_name in session_allowed:
            try:
                safe_globals[mod_name] = __import__(mod_name)
            except ImportError:
                pass

        def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
            top = name.split(".")[0]
            if top not in session_allowed:
                raise ImportError(
                    f"Import not allowed: {name}. Use extra_modules to request it."
                )
            return __import__(name, *args, **kwargs)

        # Sandboxed file I/O — only allows writing inside EXPORT_DIR
        os.makedirs(EXPORT_DIR, exist_ok=True)
        _export_dir_resolved = os.path.realpath(EXPORT_DIR)

        def _safe_open(filepath: str, mode: str = "r", **kwargs: Any) -> Any:
            resolved = os.path.realpath(
                os.path.join(_export_dir_resolved, os.path.basename(filepath))
            )
            if not resolved.startswith(_export_dir_resolved):
                raise PermissionError(
                    "File access restricted to export directory. Use just a filename, e.g. open('output.xlsx', 'wb')"
                )
            return (
                __builtins__["open"](resolved, mode, **kwargs)
                if isinstance(__builtins__, dict)
                else open(resolved, mode, **kwargs)
            )

        def _save_export(filename: str, data: bytes | str) -> str:
            """Convenience: save binary or text data to the export directory. Returns the full path."""
            resolved = os.path.join(_export_dir_resolved, os.path.basename(filename))
            mode = "wb" if isinstance(data, (bytes, bytearray)) else "w"
            with open(resolved, mode) as f:
                f.write(data)
            return resolved

        safe_builtins = {
            "__import__": _safe_import,
            "print": lambda *args, **kwargs: print(
                *args, file=stdout_capture, **kwargs
            ),
            "open": _safe_open,
            "save_export": _save_export,
            "len": len,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "map": map,
            "filter": filter,
            "sorted": sorted,
            "reversed": reversed,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "round": round,
            "any": any,
            "all": all,
            "isinstance": isinstance,
            "type": type,
            "hasattr": hasattr,
            "repr": repr,
            "format": format,
            "chr": chr,
            "ord": ord,
            "hex": hex,
            "bin": bin,
            "oct": oct,
            "pow": pow,
            "divmod": divmod,
            "complex": complex,
            "bytes": bytes,
            "bytearray": bytearray,
            "memoryview": memoryview,
            "frozenset": frozenset,
            "slice": slice,
            "iter": iter,
            "next": next,
            "id": id,
            "hash": hash,
            "callable": callable,
            "property": property,
            "staticmethod": staticmethod,
            "classmethod": classmethod,
            "super": super,
            "object": object,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "IndexError": IndexError,
            "RuntimeError": RuntimeError,
            "StopIteration": StopIteration,
            "Exception": Exception,
            "getattr": getattr,
            "True": True,
            "False": False,
            "None": None,
            "NotImplementedError": NotImplementedError,
            "AttributeError": AttributeError,
            "ImportError": ImportError,
            "FileNotFoundError": FileNotFoundError,
            "PermissionError": PermissionError,
            "OSError": OSError,
            "IOError": IOError,
            "ZeroDivisionError": ZeroDivisionError,
            "OverflowError": OverflowError,
            "ArithmeticError": ArithmeticError,
        }
        safe_globals["__builtins__"] = safe_builtins
        safe_globals.update(variables)

        import threading

        exec_exception: list[Exception] = []

        def _run_code() -> None:
            nonlocal result_value
            try:
                tree = ast.parse(code)
                last_expr = None
                if tree.body and isinstance(tree.body[-1], ast.Expr):
                    last_expr = tree.body.pop()
                    exec(
                        compile(
                            ast.Module(body=tree.body, type_ignores=[]),
                            "<sandbox>",
                            "exec",
                        ),
                        safe_globals,
                    )
                    result_value = eval(
                        compile(
                            ast.Expression(body=last_expr.value), "<sandbox>", "eval"
                        ),
                        safe_globals,
                    )
                else:
                    exec(compile(tree, "<sandbox>", "exec"), safe_globals)
            except Exception as e:
                exec_exception.append(e)

        thread = threading.Thread(target=_run_code, daemon=True)
        thread.start()
        thread.join(timeout=MAX_EXECUTION_TIME)

        if thread.is_alive():
            return ToolResult(
                content=f"Execution timed out after {MAX_EXECUTION_TIME} seconds",
                is_error=True,
            )

        if exec_exception:
            e = exec_exception[0]
            tb = traceback.format_exception(type(e), e, e.__traceback__)
            lines = "".join(tb).split("\n")
            relevant = [
                ln for ln in lines if not ln.startswith("  File") or "<sandbox>" in ln
            ]
            return ToolResult(
                content=f"Execution error: {type(e).__name__}: {e}\n\n{''.join(relevant[-5:])}",
                is_error=True,
            )

        output = stdout_capture.getvalue()
        if len(output) > MAX_OUTPUT_SIZE:
            output = (
                output[:MAX_OUTPUT_SIZE]
                + f"\n[Truncated at {MAX_OUTPUT_SIZE} characters]"
            )

        parts = []
        if output:
            parts.append(output.rstrip())
        if result_value is not None:
            try:
                val_str = json.dumps(result_value, indent=2, default=str)
            except (TypeError, ValueError):
                val_str = repr(result_value)
            parts.append(f"\nResult: {val_str}")

        content = "\n".join(parts) if parts else "(no output)"

        return ToolResult(
            content=content,
            metadata={
                "has_output": bool(output),
                "has_result": result_value is not None,
            },
        )

    async def _validate_extra_modules(
        self, modules: list[str], code: str
    ) -> dict[str, Any]:
        """Use LLM to validate whether requested extra modules are safe to allow.

        Returns {"approved": [...], "rejected": [...], "reasons": [...]}
        """
        # Hard-reject modules that are always dangerous
        always_reject = {
            "subprocess",
            "os",
            "sys",
            "shutil",
            "pathlib",
            "importlib",
            "ctypes",
            "socket",
            "http",
            "urllib",
            "requests",
            "httpx",
            "aiohttp",
            "asyncio",
            "multiprocessing",
            "threading",
            "signal",
            "pty",
            "fcntl",
            "resource",
            "grp",
            "pwd",
            "pickle",
            "shelve",
            "marshal",  # deserialization attacks
            "code",
            "codeop",
            "compileall",  # code execution
            "webbrowser",
            "antigravity",  # unexpected side effects
        }

        approved: list[str] = []
        rejected: list[str] = []
        reasons: list[str] = []

        # Fast path: reject obviously dangerous, approve obviously safe
        needs_llm_review: list[str] = []
        for mod in modules:
            top = mod.split(".")[0]
            if top in always_reject or top in FORBIDDEN_NAMES:
                rejected.append(mod)
                reasons.append(
                    f"Module '{mod}' provides system/network access and is not permitted"
                )
            else:
                needs_llm_review.append(mod)

        if not needs_llm_review:
            return {"approved": approved, "rejected": rejected, "reasons": reasons}

        # LLM safety review for non-obvious modules
        try:
            from engine.llm_router import LLMRouter

            llm = LLMRouter()

            review_prompt = f"""You are a security reviewer for a sandboxed Python code executor.

A user wants to use these additional Python modules: {needs_llm_review}

Their code:
```python
{code[:2000]}
```

For EACH requested module, determine if it is SAFE to allow in a sandbox.

APPROVE if the module:
- Is a pure computation/data library (e.g., sympy, networkx, shapely, scikit-image)
- Does data transformation, math, or visualization
- Has no ability to access network, filesystem, or system resources

REJECT if the module:
- Can make network requests (requests, urllib, httpx, socket, etc.)
- Can access the filesystem beyond what's sandboxed (os, pathlib, shutil)
- Can execute system commands (subprocess, os.system)
- Can deserialize untrusted data (pickle, marshal, yaml.load)
- Can interfere with the runtime (threading, multiprocessing, signal, ctypes)

Respond with JSON ONLY:
{{"decisions": [{{"module": "name", "safe": true/false, "reason": "brief explanation"}}]}}"""

            resp = await llm.complete(
                messages=[{"role": "user", "content": review_prompt}],
                system="You are a strict security reviewer. When in doubt, reject. Respond with JSON only.",
                model="claude-haiku-3-5-20241022",  # Fast model for validation
                temperature=0.0,
            )

            text = resp.content.strip()
            if "{" in text:
                result = json.loads(text[text.index("{") : text.rindex("}") + 1])
                for decision in result.get("decisions", []):
                    mod = decision.get("module", "")
                    if mod not in needs_llm_review:
                        continue
                    if decision.get("safe", False):
                        approved.append(mod)
                    else:
                        rejected.append(mod)
                        reasons.append(
                            f"{mod}: {decision.get('reason', 'Rejected by safety review')}"
                        )

                # Any modules not in the LLM response default to rejected
                reviewed = {d.get("module") for d in result.get("decisions", [])}
                for mod in needs_llm_review:
                    if mod not in reviewed:
                        rejected.append(mod)
                        reasons.append(
                            f"{mod}: Not reviewed — defaulting to reject for safety"
                        )
            else:
                # LLM didn't return valid JSON — reject all
                for mod in needs_llm_review:
                    rejected.append(mod)
                    reasons.append(
                        f"{mod}: Safety review failed — could not parse LLM response"
                    )

        except Exception as e:
            logger.warning("Extra module LLM validation failed: %s", e)
            # On LLM failure, reject all extra modules for safety
            for mod in needs_llm_review:
                rejected.append(mod)
                reasons.append(
                    f"{mod}: Safety review unavailable — defaulting to reject"
                )

        return {
            "approved": approved,
            "rejected": rejected if rejected else [],
            "reasons": reasons,
        }
