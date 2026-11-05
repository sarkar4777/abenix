"""Safe Python code execution for data transformations, file generation, and comple"""

from __future__ import annotations

import ast
import asyncio
import base64
import json
import logging
import os
import re
import tempfile
from typing import Any

from engine.process_sandbox import SandboxError, code_request, run_code
from engine.tenant_access import (
    current_tenant,
    export_dir_for,
    tenant_file_roots,
)
from engine.tools.base import READ_ONLY, BaseTool, ConfigField, ToolResult

logger = logging.getLogger(__name__)

MAX_EXECUTION_TIME = 30  # Increased from 10s for complex operations
MAX_OUTPUT_SIZE = 100_000


def _resolve_export_dir() -> str:
    """Pick a writable export directory.

    Order of preference:
      1. $EXPORT_DIR if set AND writable (k8s prod with PVC mounted).
      2. <cwd>/.data/exports (dev-local.sh — writable + visible to dev).
      3. <tempdir>/abenix_exports (last-resort — works on every OS,
         every container, every fresh install).

    Always creates the directory before returning. The fallback chain
    rescues both broken k8s pods (where /data is set but unwritable)
    and fresh local installs (where the env var is unset).
    """
    candidates = [
        os.environ.get("EXPORT_DIR"),
        os.path.join(os.getcwd(), ".data", "exports"),
        os.path.join(tempfile.gettempdir(), "abenix_exports"),
    ]
    for cand in candidates:
        if not cand:
            continue
        try:
            os.makedirs(cand, exist_ok=True)
            # Probe write — some PVC mounts succeed mkdir but reject writes.
            probe = os.path.join(cand, ".write_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            return cand
        except (OSError, PermissionError) as e:
            logger.warning("EXPORT_DIR candidate %s unwritable: %s", cand, e)
            continue
    # Should never reach here — tempfile.gettempdir() is always writable.
    return tempfile.gettempdir()


EXPORT_DIR = _resolve_export_dir()

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
# allowed modules re-export these, so zipfile.os or random._os reach them without an import
FORBIDDEN_ATTRIBUTES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "pathlib",
        "importlib",
        "ctypes",
        "socket",
        "urllib",
        "requests",
        "httpx",
        "aiohttp",
        "builtins",
        "pickle",
        "marshal",
        "threading",
        "multiprocessing",
        "signal",
        "read_pickle",
        "gi_frame",
        "gi_code",
        "f_globals",
        "f_locals",
        "f_builtins",
        "f_back",
        "tb_frame",
        "cr_frame",
        "ag_frame",
    }
)
_ALLOWED_PRIVATE_ATTRIBUTES = frozenset({"_asdict", "_replace", "_fields", "_make"})
_FORMAT_METHODS = frozenset({"format", "format_map", "vformat", "get_field"})
_SAFE_GETATTR_NAMES = _ALLOWED_PRIVATE_ATTRIBUTES | {"__name__", "__doc__"}
_FORMAT_WALK = re.compile(r"\{[^{}:!]*[.\[]")


def _attribute_problem(name: str) -> str | None:
    if name in FORBIDDEN_ATTRIBUTES:
        return f"Access to attribute '{name}' is not allowed"
    if (
        name.startswith("_")
        and not (name.startswith("__") and name.endswith("__"))
        and name not in _ALLOWED_PRIVATE_ATTRIBUTES
    ):
        return f"Access to private attribute '{name}' is not allowed"
    return None


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
        for alias in node.names:
            problem = _attribute_problem(alias.name)
            if problem:
                self.errors.append(problem)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _FORMAT_METHODS:
            literal = isinstance(func.value, ast.Constant) and isinstance(
                func.value.value, str
            )
            if func.attr != "format" or not literal:
                self.errors.append(
                    "str.format is only allowed on a literal string, use an f-string"
                )
            elif _FORMAT_WALK.search(func.value.value):
                self.errors.append(
                    "str.format fields cannot use dots or indexes, use an f-string"
                )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in FORBIDDEN_NAMES:
            self.errors.append(f"Access to '{node.id}' is not allowed")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        owner = node.value.id if isinstance(node.value, ast.Name) else ""
        problem = None if owner in ("self", "cls") else _attribute_problem(node.attr)
        if problem:
            self.errors.append(problem)
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
    config_fields = (
        ConfigField(
            "CODE_EXECUTOR_SANDBOX_IMAGE",
            label="Container image for code runs",
            kind="string",
            group="Code execution",
            description="Runs code_executor in a sandboxed job when the sandbox is on and this image is allowed. It needs Python and the data libraries. Empty means a local process.",
        ),
        ConfigField(
            "SANDBOX_MEMORY_MB",
            label="Memory limit in MB",
            kind="int",
            group="Code execution",
            description="Limit for a code run or a model load. A process honours it where the operating system allows.",
            default="2048",
        ),
    )
    name = "code_executor"
    risk_tier = "medium"
    effect = READ_ONLY
    description = (
        "Execute Python code in a separate process with no secrets, resource limits and no network. Supports complex data "
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
                "description": "Python code to execute. Use print() for output. A last expression, or a variable named result, is captured as the result.",
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

        tenant = current_tenant(self)
        export_dir = export_dir_for(tenant)
        os.makedirs(export_dir, exist_ok=True)
        request = code_request(
            code,
            variables,
            sorted(session_allowed),
            export_dir,
            tenant_file_roots(tenant),
            MAX_EXECUTION_TIME,
        )
        isolation = "process"
        try:
            reply = await self._run_in_job(request, tenant, export_dir)
            if reply is not None:
                isolation = "job"
            else:
                reply = await asyncio.to_thread(run_code, request)
        except ImportError as e:
            return ToolResult(
                content=f"Execution error: ImportError: {e}", is_error=True
            )
        except SandboxError as e:
            if str(e).startswith("Stopped after"):
                return ToolResult(
                    content=f"Execution timed out after {MAX_EXECUTION_TIME} seconds",
                    is_error=True,
                )
            return ToolResult(content=f"Execution error: {e}", is_error=True)

        output = reply.get("stdout") or ""
        if len(output) > MAX_OUTPUT_SIZE:
            output = (
                output[:MAX_OUTPUT_SIZE]
                + f"\n[Truncated at {MAX_OUTPUT_SIZE} characters]"
            )

        parts = []
        if output:
            parts.append(output.rstrip())
        val_str = reply.get("result")
        if val_str is not None:
            # alone it is the step's output, so the next step can read it as JSON
            parts.append(f"\nResult: {val_str}" if output else val_str)

        content = "\n".join(parts) if parts else "(no output)"

        return ToolResult(
            content=content,
            metadata={
                "has_output": bool(output),
                "has_result": val_str is not None,
                "isolation": isolation,
                "network_namespace": bool(reply.get("network_namespace")),
            },
        )

    async def _run_in_job(
        self, request: dict[str, Any], tenant: str, export_dir: str
    ) -> dict[str, Any] | None:
        image = str(self.cfg("CODE_EXECUTOR_SANDBOX_IMAGE") or "").strip()
        if not image:
            return None
        from engine import process_sandbox
        from engine.tools.sandboxed_job import MAX_FILES_BYTES, SandboxedJobTool

        job = SandboxedJobTool(tenant_id=tenant)
        settings = await job._resolve_settings()
        if not settings["enabled"] or image not in settings["allowed_images"]:
            return None
        in_container = {**request, "export_dir": "/tmp/exports", "read_roots": []}
        with open(process_sandbox.__file__, "rb") as f:
            source = f.read()
        body = json.dumps(in_container, default=str).encode()
        if len(source) + len(body) > MAX_FILES_BYTES:
            return None
        result = await job.execute(
            {
                "image": image,
                "command": "python -I /in/sandbox.py /in/request.json",
                "timeout_seconds": MAX_EXECUTION_TIME + 30,
                "memory_mb": int(self.cfg("SANDBOX_MEMORY_MB") or 2048),
                "network": False,
                "files_b64": {
                    "sandbox.py": base64.b64encode(source).decode(),
                    "request.json": base64.b64encode(body).decode(),
                },
            }
        )
        meta = result.metadata or {}
        raw = meta.get("logs") or meta.get("stdout") or ""
        if not raw.strip():
            logger.warning("code_executor job gave no output, running as a process")
            return None
        reply = process_sandbox.parse_reply(raw)
        for item in reply.pop("exports", []):
            with open(
                os.path.join(export_dir, os.path.basename(item["name"])), "wb"
            ) as f:
                f.write(base64.b64decode(item["b64"]))
        return reply

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
