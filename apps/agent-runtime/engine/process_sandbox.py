"""Run untrusted Python, a pickled model or tool code, in a throwaway process holding no secrets."""

from __future__ import annotations

import ast
import base64
import builtins
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import types
from typing import Any

TIMEOUT_SECONDS = 120
DEFAULT_MEMORY_MB = 2048
PICKLE_FRAMEWORKS = {"sklearn", "xgboost", "pytorch"}
MAX_OUTPUT_CHARS = 100_000
MAX_EXPORT_BYTES = 20 * 1024 * 1024
_ALLOWED_ROOTS = (
    "/usr",
    "/lib",
    "/lib64",
    "/bin",
    "/System",
    "/Library/Fonts",
    "/etc/mime.types",
    "/etc/localtime",
    "/etc/ssl",
    "/etc/fonts",
    "/dev/null",
    "/dev/urandom",
)
_BLOCKED_SUFFIXES = (".pem", ".key", ".env")
_BLOCKED_EVENTS = (
    "os.system",
    "os.exec",
    "os.fork",
    "os.forkpty",
    "os.posix_spawn",
    "os.spawn",
    "os.startfile",
    "os.remove",
    "os.rename",
    "os.rmdir",
    "os.mkdir",
    "os.chmod",
    "subprocess.Popen",
    "pty.spawn",
    "socket.connect",
    "socket.bind",
    "socket.sendto",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "shutil.rmtree",
    "shutil.copyfile",
    "shutil.move",
    "ctypes.dlopen",
    "ctypes.dlsym",
    "ctypes.call_function",
    "ctypes.PyObj_FromPtr",
    "ctypes.string_at",
    "ctypes.wstring_at",
)


class SandboxError(Exception):
    pass


ModelSandboxError = SandboxError


class ModelInputError(SandboxError):
    pass


def load_torch(path: str) -> Any:
    """TorchScript or a weights only checkpoint, never an arbitrary pickle."""
    import torch

    try:
        return torch.jit.load(path, map_location="cpu")
    except RuntimeError:
        return torch.load(path, map_location="cpu", weights_only=True)


def _safe_env(home: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": home,
        "TMPDIR": home,
        "LANG": "C.UTF-8",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "JOBLIB_MULTIPROCESSING": "0",
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": home,
        "SANDBOX_MEMORY_MB": os.environ.get("SANDBOX_MEMORY_MB", ""),
        **(extra or {}),
    }


def _communicate(request: dict[str, Any], home: str, timeout: int) -> bytes:
    proc = subprocess.Popen(
        [sys.executable, "-I", os.path.abspath(__file__)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_safe_env(home),
        cwd=home,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(json.dumps(request, default=str).encode(), timeout)
    except subprocess.TimeoutExpired as e:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        proc.communicate()
        raise SandboxError(f"Stopped after {timeout} seconds") from e
    if not out.strip():
        tail = err.decode("utf-8", "replace").strip()[-300:]
        raise SandboxError(tail or f"The process exited with code {proc.returncode}")
    return out


def parse_reply(raw: bytes | str) -> dict[str, Any]:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    try:
        out = json.loads(text.strip().splitlines()[-1])
    except (IndexError, ValueError) as e:
        raise SandboxError(f"The process gave no usable answer ({text[-200:]})") from e
    if out.get("input_error"):
        raise ModelInputError(out["input_error"])
    if out.get("error"):
        raise SandboxError(out["error"])
    if out.get("missing_module"):
        raise ImportError(out["missing_module"])
    return out["result"]


def run_isolated(
    op: str,
    file_path: str,
    framework: str,
    rows: Any = None,
    *,
    names: list[str] | None = None,
    timeout: int = 0,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="model_sandbox_") as home:
        raw = _communicate(
            {
                "op": op,
                "path": file_path,
                "framework": framework,
                "rows": rows,
                "names": names or [],
                "read_roots": [],
                "timeout": timeout or TIMEOUT_SECONDS,
            },
            os.path.realpath(home),
            timeout or TIMEOUT_SECONDS,
        )
    return parse_reply(raw)


def code_request(
    code: str,
    variables: dict[str, Any],
    allowed_modules: list[str],
    export_dir: str,
    read_roots: list[str],
    timeout: int,
) -> dict[str, Any]:
    return {
        "op": "code",
        "code": code,
        "variables": variables,
        "allowed_modules": allowed_modules,
        "export_dir": export_dir,
        "read_roots": read_roots,
        "timeout": timeout,
    }


def run_code(request: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="code_sandbox_") as home:
        raw = _communicate(request, os.path.realpath(home), int(request["timeout"]) + 5)
    return parse_reply(raw)


def _under(path: str, roots: set[str]) -> bool:
    return any(path == r or path.startswith(r + os.sep) for r in roots)


def _guard(
    read_files: list[str], read_roots: list[str], write_roots: list[str], home: str
) -> None:
    readable = {
        os.path.realpath(p)
        for p in (
            sys.prefix,
            sys.base_prefix,
            sys.exec_prefix,
            home,
            *_ALLOWED_ROOTS,
            *read_roots,
            *write_roots,
        )
    }
    readable.update(os.path.realpath(p) for p in sys.path if p)
    writable = {os.path.realpath(p) for p in (home, *write_roots)}
    exact = {os.path.realpath(p) for p in read_files if p}

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event.startswith(_BLOCKED_EVENTS):
            raise PermissionError(f"{event} is not allowed in this sandbox")
        if event != "open" or not args:
            return
        path = args[0]
        if not isinstance(path, (str, bytes, os.PathLike)):
            return
        real = os.path.realpath(os.fsdecode(path))
        mode = args[1] if len(args) > 1 else "r"
        flags = args[2] if len(args) > 2 else 0
        writing = isinstance(mode, str) and any(c in mode for c in "wax+")
        if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            writing = True
        if writing:
            if not _under(real, writable) and real != os.devnull:
                raise PermissionError(f"Writing {real} is not allowed")
            return
        if real in exact:
            return
        if real.endswith(_BLOCKED_SUFFIXES) or not _under(real, readable):
            raise PermissionError(f"Reading {real} is not allowed")

    sys.addaudithook(hook)


def _isolate_process(timeout: int, memory_mb: int) -> bool:
    """Apply what this platform can enforce, and say whether the network namespace took."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout + 5))
        limit = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):
        pass
    if hasattr(os, "unshare") and hasattr(os, "CLONE_NEWNET"):
        try:
            os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNET)
            return True
        except OSError:
            return False
    return False


def _stub_threadpoolctl() -> None:
    # threadpoolctl needs libc through ctypes, the thread count env vars do its job here
    class _Limit:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def __enter__(self) -> "_Limit":
            return self

        def __exit__(self, *_a: Any) -> bool:
            return False

        def restore_original_limits(self) -> None:
            return None

        unregister = restore_original_limits

    class _Controller:
        lib_controllers: list[Any] = []

        def info(self) -> list[Any]:
            return []

        def limit(self, *_a: Any, **_k: Any) -> _Limit:
            return _Limit()

        def select(self, *_a: Any, **_k: Any) -> "_Controller":
            return self

        def wrap(self, *_a: Any, **_k: Any) -> _Limit:
            return _Limit()

    stub = types.ModuleType("threadpoolctl")
    stub.threadpool_limits = _Limit  # type: ignore[attr-defined]
    stub.threadpool_info = lambda: []  # type: ignore[attr-defined]
    stub.ThreadpoolController = _Controller  # type: ignore[attr-defined]
    sys.modules["threadpoolctl"] = stub


def _preimport(names: list[str]) -> None:
    # library start up may load shared objects, the guard goes on after this and before untrusted code
    import ctypes  # noqa: F401

    _stub_threadpoolctl()
    for name in names:
        try:
            __import__(name)
        except Exception:  # noqa: BLE001
            pass


def _load(path: str, framework: str) -> Any:
    if framework == "pytorch":
        return load_torch(path)
    import joblib

    return joblib.load(path)


def _validate(req: dict[str, Any]) -> dict[str, Any]:
    model = _load(req["path"], req["framework"])
    if req["framework"] == "pytorch":
        if not callable(model):
            raise ValueError(
                "the file holds weights only (a state_dict). Save it with "
                "torch.jit.save or export it to ONNX"
            )
        return {"type": type(model).__name__}
    if not hasattr(model, "predict"):
        raise ValueError(
            f"the file holds a {type(model).__name__}, which has no predict() method"
        )
    info: dict[str, Any] = {"type": type(model).__name__}
    if hasattr(model, "n_features_in_"):
        info["n_features"] = int(model.n_features_in_)
    if hasattr(model, "feature_names_in_"):
        info["feature_names"] = [str(f) for f in model.feature_names_in_]
    if hasattr(model, "classes_"):
        info["classes"] = [str(c) for c in model.classes_]
    return info


def _predict(req: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    model = _load(req["path"], req["framework"])
    rows = req["rows"]
    numeric = bool(rows) and not isinstance(rows[0], str)
    X = np.asarray(rows, dtype=float) if numeric else rows
    if req["framework"] == "pytorch":
        import torch

        model.eval()
        with torch.no_grad():
            try:
                return {"predictions": model(torch.FloatTensor(X)).numpy().tolist()}
            except RuntimeError as e:
                raise ModelInputError(f"The model rejected this input: {e}")
    expected = getattr(model, "n_features_in_", None)
    if numeric and expected is not None and int(expected) != int(X.shape[1]):
        wanted = int(expected)
        names = req.get("names") or [
            str(f) for f in getattr(model, "feature_names_in_", [])
        ]
        noun = "feature" if wanted == 1 else "features"
        msg = f"This model expects {wanted} {noun}, you sent {int(X.shape[1])}."
        if names and len(names) == wanted:
            msg += f" Send them in this order: {', '.join(names)}."
        raise ModelInputError(msg)
    try:
        preds = model.predict(X)
    except ValueError as e:
        raise ModelInputError(f"The model rejected this input: {e}")
    out: dict[str, Any] = {"predictions": preds.tolist()}
    if hasattr(model, "predict_proba"):
        try:
            out["probabilities"] = model.predict_proba(X).tolist()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(model, "classes_"):
        out["classes"] = [str(c) for c in model.classes_]
        out["predicted_class"] = str(preds[0]) if len(preds) else None
    return out


# allowed modules re-export these, so getattr must refuse them the way the validator does
_FORBIDDEN_ATTRIBUTES = frozenset(
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
_FORMAT_METHODS = frozenset({"format", "format_map", "vformat", "get_field"})
_PUBLIC_PRIVATE = frozenset(
    {"_asdict", "_replace", "_fields", "_make", "__name__", "__doc__"}
)
_SAFE_BUILTINS = (
    "len range enumerate zip map filter sorted reversed list dict set tuple int float "
    "str bool abs min max sum round any all isinstance type hasattr repr format chr ord "
    "hex bin oct pow divmod complex bytes bytearray memoryview frozenset slice iter next "
    "id hash callable property staticmethod classmethod super object ValueError TypeError "
    "KeyError IndexError RuntimeError StopIteration Exception NotImplementedError "
    "AttributeError ImportError FileNotFoundError PermissionError OSError IOError "
    "ZeroDivisionError OverflowError ArithmeticError __build_class__"
).split()


def _safe_getattr(obj: Any, name: str, *default: Any) -> Any:
    allowed = isinstance(name, str) and (
        name in _PUBLIC_PRIVATE
        or (
            not name.startswith("_")
            and name not in _FORBIDDEN_ATTRIBUTES
            and name not in _FORMAT_METHODS
        )
    )
    if not allowed:
        raise AttributeError(f"Access to attribute {name!r} is not allowed")
    return getattr(obj, name, *default)


def _module_names(tree: ast.AST, allowed: set[str]) -> list[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in allowed:
            found.add(node.id)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return sorted(n for n in found if n.split(".")[0] in allowed)


def _collect_exports(export_dir: str, before: set[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    total = 0
    for name in sorted(os.listdir(export_dir)):
        path = os.path.join(export_dir, name)
        if name in before or not os.path.isfile(path):
            continue
        data = open(path, "rb").read()
        total += len(data)
        if total > MAX_EXPORT_BYTES:
            raise SandboxError("The files this run wrote are over 20 MB")
        out.append({"name": name, "b64": base64.b64encode(data).decode()})
    return out


def _run_code_request(req: dict[str, Any], want_exports: bool) -> dict[str, Any]:
    code = req["code"]
    allowed = set(req.get("allowed_modules") or [])
    export_dir = os.path.realpath(req["export_dir"])
    os.makedirs(export_dir, exist_ok=True)
    before = set(os.listdir(export_dir)) if want_exports else set()
    tree = ast.parse(code)
    names = _module_names(tree, allowed)
    _preimport(names)
    _guard(
        [],
        list(req.get("read_roots") or []),
        [export_dir],
        os.path.realpath(os.environ.get("HOME", tempfile.gettempdir())),
    )

    stdout = io.StringIO()
    real_open = builtins.open

    def safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split(".")[0] not in allowed:
            raise ImportError(
                f"Import not allowed: {name}. Use extra_modules to request it."
            )
        return __import__(name, *args, **kwargs)

    def safe_open(filepath: Any, mode: str = "r", **kwargs: Any) -> Any:
        target = os.path.realpath(
            os.path.join(export_dir, os.path.basename(str(filepath)))
        )
        if not target.startswith(export_dir + os.sep):
            raise PermissionError(
                "File access restricted to export directory. Use just a filename, e.g. open('output.xlsx', 'wb')"
            )
        return real_open(target, mode, **kwargs)

    def save_export(filename: str, data: bytes | str) -> str:
        target = os.path.join(export_dir, os.path.basename(filename))
        mode = "wb" if isinstance(data, (bytes, bytearray)) else "w"
        with real_open(target, mode) as f:
            f.write(data)
        return target

    safe = {n: getattr(builtins, n) for n in _SAFE_BUILTINS}
    safe.update(
        {
            "__import__": safe_import,
            "print": lambda *a, **k: print(*a, **{**k, "file": stdout}),
            "open": safe_open,
            "save_export": save_export,
            "getattr": _safe_getattr,
            "True": True,
            "False": False,
            "None": None,
        }
    )
    variables = req.get("variables") or {}
    env: dict[str, Any] = {"__builtins__": safe, "__name__": "__sandbox__"}
    for name in {n.split(".")[0] for n in names}:
        try:
            env[name] = __import__(name)
        except ImportError:
            pass
    env.update(variables)

    result: Any = None
    last = (
        tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
    )
    exec(compile(tree, "<sandbox>", "exec"), env)  # noqa: S102
    if last is not None:
        result = eval(  # noqa: S307
            compile(ast.Expression(body=last.value), "<sandbox>", "eval"), env
        )
    elif "result" in env and "result" not in variables:
        result = env["result"]

    if result is None:
        rendered = None
    else:
        try:
            rendered = json.dumps(result, indent=2, default=str)
        except (TypeError, ValueError):
            rendered = repr(result)
    reply: dict[str, Any] = {"stdout": stdout.getvalue(), "result": rendered}
    if want_exports:
        reply["exports"] = _collect_exports(export_dir, before)
    return reply


def _main() -> None:
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    in_job = len(sys.argv) > 1
    source = open(sys.argv[1], encoding="utf-8") if in_job else sys.stdin
    req = json.loads(source.read())
    timeout = int(req.get("timeout") or TIMEOUT_SECONDS)
    memory_mb = int(os.environ.get("SANDBOX_MEMORY_MB") or DEFAULT_MEMORY_MB)
    net_isolated = _isolate_process(timeout, memory_mb)
    out: dict[str, Any]
    try:
        if req["op"] == "code":
            reply = _run_code_request(req, want_exports=in_job)
        else:
            modules = ["numpy", "joblib", "sklearn"]
            if req.get("framework") == "pytorch":
                modules.append("torch")
            _preimport(modules)
            _guard(
                [req["path"]],
                list(req.get("read_roots") or []),
                [],
                os.path.realpath(os.environ.get("HOME", "/nonexistent")),
            )
            reply = {"validate": _validate, "predict": _predict}[req["op"]](req)
        if isinstance(reply, dict) and req["op"] == "code":
            reply["network_namespace"] = net_isolated
        out = {"result": reply}
    except ImportError as e:
        out = {"missing_module": str(e.name or e)}
    except ModelInputError as e:
        out = {"input_error": str(e)}
    except BaseException as e:  # noqa: BLE001
        msg = str(e).strip().rstrip(".")
        out = {"error": f"{type(e).__name__}: {msg}" if msg else type(e).__name__}
    real_stdout.write("\n" + json.dumps(out, default=str) + "\n")
    real_stdout.flush()
    # a thread a model started must not keep the process, and the wall clock, alive
    os._exit(0)


if __name__ == "__main__":
    _main()
