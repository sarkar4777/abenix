"""Alembic revision ids are unique and the history has no cycles."""

from __future__ import annotations

import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "packages" / "db" / "alembic" / "versions"


def _graph() -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    seen: dict[str, str] = {}
    for f in sorted(VERSIONS.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        rev = re.search(r'^revision(?:\s*:[^=]+)?\s*=\s*["\']([^"\']+)', src, re.M)
        if not rev:
            continue
        r = rev.group(1)
        assert r not in seen, f"revision {r} is used by both {seen[r]} and {f.name}"
        seen[r] = f.name
        down = re.search(r"^down_revision(?:\s*:[^=]+)?\s*=\s*(.+)$", src, re.M)
        parents = tuple(re.findall(r'["\']([^"\']+)["\']', down.group(1))) if down else ()
        out[r] = parents
    return out


def test_revision_ids_are_unique_and_parents_exist():
    g = _graph()
    for r, parents in g.items():
        for p in parents:
            assert p in g, f"{r} points at missing parent {p}"


def test_history_has_no_cycles():
    g = _graph()
    state: dict[str, int] = {}

    def visit(n: str, path: list[str]) -> None:
        if state.get(n) == 2:
            return
        assert state.get(n) != 1, f"cycle through {' -> '.join(path + [n])}"
        state[n] = 1
        for p in g.get(n, ()):
            visit(p, path + [n])
        state[n] = 2

    for n in g:
        visit(n, [])
