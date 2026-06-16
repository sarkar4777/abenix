#!/usr/bin/env bash
# Pre-commit / CI guard for the alembic version graph.
#
# Catches the two failure modes that have broken the deploy in the past:
#   1. Two files declaring the same `revision = "..."` (alembic loads both
#      and the graph silently breaks).
#   2. More than one head after walking the down_revision chain (every
#      head must be joined by a merge migration before the next deploy).
#
# Exit 0 = graph is healthy.
# Exit 1 = either fault present, with a one-line diagnosis.

set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
VERS_DIR="$REPO_ROOT/packages/db/alembic/versions"

if [[ ! -d "$VERS_DIR" ]]; then
  echo "verify-alembic-graph: $VERS_DIR not found" >&2
  exit 2
fi

PYTHON_BIN="${PYTHON:-python}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=python3
fi

"$PYTHON_BIN" - "$VERS_DIR" <<'PY'
import importlib.util
import pathlib
import sys

versions = pathlib.Path(sys.argv[1])
revs: dict[str, list[str]] = {}
graph: dict[str, set[str]] = {}

for f in sorted(versions.glob("*.py")):
    if f.name == "__init__.py":
        continue
    spec = importlib.util.spec_from_file_location(f"_mig_{f.stem}", f)
    if spec is None or spec.loader is None:
        continue
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        print(f"verify-alembic-graph: cannot import {f.name}: {e}", file=sys.stderr)
        sys.exit(1)
    rev = getattr(mod, "revision", None)
    down = getattr(mod, "down_revision", None)
    if not isinstance(rev, str):
        continue
    revs.setdefault(rev, []).append(f.name)
    if down is None:
        parents = set()
    elif isinstance(down, str):
        parents = {down}
    elif isinstance(down, (tuple, list)):
        parents = {p for p in down if isinstance(p, str)}
    else:
        parents = set()
    graph[rev] = parents

dupes = {r: files for r, files in revs.items() if len(files) > 1}
if dupes:
    print("verify-alembic-graph: duplicate revision IDs:", file=sys.stderr)
    for r, files in dupes.items():
        print(f"  {r}: {', '.join(files)}", file=sys.stderr)
    sys.exit(1)

children: dict[str, set[str]] = {}
for child, parents in graph.items():
    for p in parents:
        children.setdefault(p, set()).add(child)

heads = sorted(r for r in graph if not children.get(r))
if len(heads) > 1:
    print("verify-alembic-graph: multiple heads — add a merge migration:", file=sys.stderr)
    for h in heads:
        print(f"  {h}", file=sys.stderr)
    sys.exit(1)

print(f"verify-alembic-graph: OK ({len(graph)} revisions, head = {heads[0] if heads else '(none)'})")
PY
