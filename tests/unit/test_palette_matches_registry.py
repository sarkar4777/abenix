"""Every tool id the web UI lists must exist in the runtime registry, and every
runtime tool must have a TOOL_DOCS entry."""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PALETTE = ROOT / "apps" / "web" / "src" / "components" / "builder" / "ToolPalette.tsx"
DOCS = ROOT / "apps" / "web" / "src" / "lib" / "tool-docs.ts"
TOOLS_ROUTER = ROOT / "apps" / "api" / "app" / "routers" / "tools.py"
GENERATOR = ROOT / "scripts" / "gen-tool-docs.py"


def _runtime_tool_names() -> set[str]:
    from engine.agent_executor import list_tool_classes

    names = set(list_tool_classes())
    # Tools the API publishes lazily because the executor builds them with context.
    src = TOOLS_ROUTER.read_text(encoding="utf-8")
    block = re.search(r"^LAZY_TOOL_MODULES\s*=\s*\[(.*?)\n\]", src, re.S | re.M)
    assert block, "LAZY_TOOL_MODULES not found in tools.py"
    for mod_path, classes in re.findall(
        r'\(\s*"([\w.]+)",\s*\[(.*?)\]', block.group(1), re.S
    ):
        mod = importlib.import_module(mod_path)
        for cls_name in re.findall(r'"(\w+)"', classes):
            name = getattr(getattr(mod, cls_name), "name", None)
            if isinstance(name, str):
                names.add(name)
    return names


def _palette_ids() -> list[str]:
    src = PALETTE.read_text(encoding="utf-8")
    start = src.index("const BUILT_IN_TOOLS")
    body = src[start : src.index("\n];", start)]
    ids = re.findall(r"\{\s*id:\s*'([\w-]+)'", body)
    assert len(ids) > 20, "BUILT_IN_TOOLS parse looks wrong"
    return ids


def _doc_keys() -> list[str]:
    src = DOCS.read_text(encoding="utf-8")
    start = src.index("export const TOOL_DOCS")
    body = src[start : src.index("\n};", start)]
    keys = re.findall(r"^  (\w+):\s*\{", body, re.M)
    assert len(keys) > 20, "TOOL_DOCS parse looks wrong"
    return keys


def test_palette_ids_exist_in_runtime_registry():
    runtime = _runtime_tool_names()
    missing = sorted(i for i in _palette_ids() if i not in runtime)
    assert not missing, f"ToolPalette lists tools the runtime does not have: {missing}"


def test_tool_docs_keys_exist_in_runtime_registry():
    runtime = _runtime_tool_names()
    missing = sorted(k for k in _doc_keys() if k not in runtime)
    assert (
        not missing
    ), f"TOOL_DOCS documents tools the runtime does not have: {missing}"


def test_palette_has_no_duplicate_ids():
    ids = _palette_ids()
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate palette ids: {dupes}"


def test_every_runtime_tool_has_tool_docs():
    docs = set(_doc_keys())
    missing = sorted(n for n in _runtime_tool_names() if n not in docs)
    assert not missing, (
        "TOOL_DOCS is missing runtime tools, run "
        f"python scripts/gen-tool-docs.py --write: {missing}"
    )


def test_tool_docs_match_the_generator():
    r = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=ROOT,
    )
    assert r.returncode == 0, r.stdout + r.stderr
