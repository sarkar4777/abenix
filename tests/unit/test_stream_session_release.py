"""Streaming routes must not hold the request DB session open (issue #124)."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ROUTER_DIRS = (
    ROOT / "apps" / "api" / "app" / "routers",
    ROOT / "contractiq" / "api" / "app" / "routers",
)

# dependencies that run a query on the request session
SESSION_DEPS = {
    "get_db",
    "get_current_user",
    "get_current_tenant",
    "get_contractiq_user",
    "require_role",
    "require_scope",
}

# single in-memory chunk, nothing to wait on
IN_MEMORY_BODIES = {"iter", "BytesIO"}

ROUTE_VERBS = {"get", "post", "put", "patch", "delete", "api_route"}

ALLOWLIST: dict[tuple[str, str], str] = {
    (
        "apps/api/app/routers/agents.py",
        "execute_agent",
    ): "closes the session before streaming, the generators reopen it only for short writes",
}


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _name(node.func)
    return None


def _is_route(fn: ast.AST) -> bool:
    for dec in getattr(fn, "decorator_list", []):
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            if dec.func.attr in ROUTE_VERBS:
                return True
    return False


def _depends_target(default: ast.AST | None) -> str | None:
    if isinstance(default, ast.Call) and _name(default.func) == "Depends":
        if default.args:
            return _name(default.args[0])
    return None


def _params(fn: ast.AsyncFunctionDef) -> list[tuple[str, str | None]]:
    args = fn.args
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    out = [(a.arg, _depends_target(d)) for a, d in zip(positional, defaults)]
    out += [
        (a.arg, _depends_target(d)) for a, d in zip(args.kwonlyargs, args.kw_defaults)
    ]
    return out


def _own_nodes(fn: ast.AST):
    """Walk a function body without descending into nested defs."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _nested_defs(fn: ast.AST):
    for node in ast.walk(fn):
        if node is not fn and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _uses(node: ast.AST, name: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def _long_stream_returns(fn: ast.AST) -> list[ast.Return]:
    out = []
    for node in _own_nodes(fn):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
            continue
        if _name(node.value.func) != "StreamingResponse":
            continue
        body = node.value.args[0] if node.value.args else None
        if isinstance(body, ast.Call) and _name(body.func) in IN_MEMORY_BODIES:
            continue
        out.append(node)
    return out


def _close_lines(fn: ast.AST, db: str) -> list[int]:
    lines = []
    for node in _own_nodes(fn):
        if (
            isinstance(node, ast.Await)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "close"
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == db
        ):
            lines.append(node.lineno)
    return lines


def _streaming_routes():
    for d in ROUTER_DIRS:
        for path in sorted(d.glob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for fn in tree.body:
                if not isinstance(fn, ast.AsyncFunctionDef) or not _is_route(fn):
                    continue
                returns = _long_stream_returns(fn)
                if returns:
                    yield rel, fn, returns


def _problems(fn: ast.AsyncFunctionDef, returns: list[ast.Return]) -> list[str]:
    params = _params(fn)
    deps = {target for _, target in params if target}
    if not deps & SESSION_DEPS:
        return []
    db = next((p for p, target in params if target == "get_db"), None)
    if db is None:
        return ["session from the auth dependency stays open, take db and close it"]
    out = []
    closes = _close_lines(fn, db)
    for ret in returns:
        if not any(line < ret.lineno for line in closes):
            out.append(f"line {ret.lineno}: no `await {db}.close()` before the stream")
        if _uses(ret.value, db):
            out.append(f"line {ret.lineno}: `{db}` passed into the stream")
    for inner in _nested_defs(fn):
        if _uses(inner, db):
            out.append(f"nested `{inner.name}` uses `{db}` after the handler returns")
    return out


def test_scanner_finds_streaming_routes():
    found = list(_streaming_routes())
    assert len(found) >= 15, [f"{r}:{fn.name}" for r, fn, _ in found]


def test_streaming_routes_release_the_request_session():
    failures = []
    for rel, fn, returns in _streaming_routes():
        if (rel, fn.name) in ALLOWLIST:
            continue
        for problem in _problems(fn, returns):
            failures.append(f"{rel}:{fn.lineno} {fn.name}: {problem}")
    assert not failures, "\n".join(failures)


def test_allowlist_entries_still_exist():
    seen = {(rel, fn.name) for rel, fn, _ in _streaming_routes()}
    stale = [key for key in ALLOWLIST if key not in seen]
    assert not stale, stale
