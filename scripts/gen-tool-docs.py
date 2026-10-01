#!/usr/bin/env python3
"""Generate TOOL_DOCS in apps/web/src/lib/tool-docs.ts from the runtime tools.

Every tool the executor can run gets an entry: the class description, and
one parameter per input_schema property (type, required, description,
default, enum, minimum, maximum, items). The category is the API catalogue's
category for the slug, or the router's prefix guess for an uncatalogued tool,
mapped to the labels the builder palette already shows.

Only the header comment, TOOL_CATEGORIES and TOOL_DOCS are rewritten. The
interfaces and helper functions in the file are kept as they are. A tool whose
class has no description keeps the description already in the file.

    python scripts/gen-tool-docs.py --check   exit 1 when the file is stale
    python scripts/gen-tool-docs.py --write   rewrite the generated blocks
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "apps" / "web" / "src" / "lib" / "tool-docs.ts"
PALETTE = ROOT / "apps" / "web" / "src" / "components" / "builder" / "ToolPalette.tsx"
TOOLS_ROUTER = ROOT / "apps" / "api" / "app" / "routers" / "tools.py"

for sub in ("apps/api", "apps/agent-runtime", "packages/db"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

HEADER = """/**
 * Tool documentation for every Abenix runtime tool.
 * Used by: AI Builder, Builder config panel, Agent info page, Marketplace.
 *
 * TOOL_CATEGORIES and TOOL_DOCS are generated from the runtime tool classes.
 * Do not edit them by hand, run `python scripts/gen-tool-docs.py --write`.
 * CI runs the same script with --check.
 */
"""

# Fields the config panel hides until a sibling takes one of the listed values.
# The runtime schema has no way to say this, so it lives here.
SHOW_WHEN: dict[tuple[str, str], dict[str, Any]] = {
    ("data_exporter", "email_to"): {"field": "destination", "values": ["email"]},
    ("data_exporter", "email_subject"): {"field": "destination", "values": ["email"]},
    ("data_exporter", "email_body"): {"field": "destination", "values": ["email"]},
    ("data_exporter", "s3_bucket"): {"field": "destination", "values": ["s3"]},
    ("data_exporter", "s3_key"): {"field": "destination", "values": ["s3"]},
    ("data_exporter", "webhook_url"): {"field": "destination", "values": ["webhook"]},
    ("data_exporter", "webhook_headers"): {
        "field": "destination",
        "values": ["webhook"],
    },
    ("data_exporter", "db_connection_string"): {
        "field": "destination",
        "values": ["database"],
    },
    ("data_exporter", "db_table"): {"field": "destination", "values": ["database"]},
    ("http_client", "body"): {"field": "method", "values": ["POST", "PUT", "PATCH"]},
}


def _router_constants() -> dict[str, Any]:
    """LAZY_TOOL_MODULES, _CATEGORY_HINTS and TOOL_CATALOG, read as literals."""
    tree = ast.parse(TOOLS_ROUTER.read_text(encoding="utf-8"))
    wanted = {"LAZY_TOOL_MODULES", "_CATEGORY_HINTS", "TOOL_CATALOG"}
    out: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        else:
            continue
        if isinstance(target, ast.Name) and target.id in wanted and node.value:
            out[target.id] = ast.literal_eval(node.value)
    missing = wanted - set(out)
    if missing:
        sys.exit(f"could not read {sorted(missing)} from {TOOLS_ROUTER}")
    return out


def _category_labels() -> dict[str, str]:
    """The palette's API_CATEGORY_LABELS map, slug to display name."""
    src = PALETTE.read_text(encoding="utf-8")
    m = re.search(r"API_CATEGORY_LABELS[^{]*\{(.*?)\n\s*\};", src, re.S)
    if not m:
        sys.exit(f"API_CATEGORY_LABELS not found in {PALETTE}")
    labels = dict(re.findall(r"(\w+):\s*'([^']+)'", m.group(1)))
    if not labels:
        sys.exit("API_CATEGORY_LABELS parsed empty")
    return labels


def _runtime_classes(lazy_modules: list[tuple[str, list[str]]]) -> dict[str, type]:
    """Every slug the executor can run, with the class that carries its schema."""
    from engine.agent_executor import (
        _CONTEXT_TOOL_FACTORIES,
        _TOOL_CLASSES,
        _ensure_tool_classes,
    )

    _ensure_tool_classes()
    candidates: dict[str, list[type]] = {}
    for mapping in (_TOOL_CLASSES, _CONTEXT_TOOL_FACTORIES):
        for slug, cls in mapping.items():
            candidates.setdefault(slug, []).append(cls)
    for mod_path, class_names in lazy_modules:
        mod = importlib.import_module(mod_path)
        for cn in class_names:
            cls = getattr(mod, cn)
            slug = getattr(cls, "name", None)
            if isinstance(slug, str):
                candidates.setdefault(slug, []).append(cls)
    out: dict[str, type] = {}
    for slug, classes in candidates.items():
        with_schema = [
            c for c in classes if isinstance(getattr(c, "input_schema", None), dict)
        ]
        out[slug] = (with_schema or classes)[0]
    return out


def _docs_block(src: str) -> str:
    start = src.index("export const TOOL_DOCS")
    return src[start : src.index("\n};", start) + 3]


def _categories_block(src: str) -> str:
    start = src.index("export const TOOL_CATEGORIES")
    return src[start : src.index("] as const;", start) + len("] as const;")]


def _header_block(src: str) -> str:
    if not src.startswith("/**"):
        sys.exit("tool-docs.ts no longer starts with a header comment")
    return src[: src.index("*/\n") + 3]


def _existing_descriptions(src: str) -> dict[str, str]:
    """Descriptions already in the file, keyed by slug."""
    pattern = re.compile(
        r'^  "?(\w+)"?: \{\n(?:    .*\n)*?    description: ("(?:[^"\\]|\\.)*"),',
        re.M,
    )
    return {
        m.group(1): json.loads(m.group(2)) for m in pattern.finditer(_docs_block(src))
    }


def _ts(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(", ", ": "))


def _ts_key(slug: str) -> str:
    return slug if re.fullmatch(r"[A-Za-z_]\w*", slug) else _ts(slug)


def _type_name(prop: dict[str, Any]) -> str:
    t = prop.get("type")
    if isinstance(t, list):
        return " | ".join(str(x) for x in t)
    if isinstance(t, str):
        return t
    for key in ("anyOf", "oneOf"):
        alts = [a.get("type") for a in prop.get(key, []) if isinstance(a, dict)]
        if alts and all(isinstance(a, str) for a in alts):
            return " | ".join(alts)
    return "any"


def _param(slug: str, name: str, prop: dict[str, Any], required: bool) -> str:
    parts = [
        f"name: {_ts(name)}",
        f"type: {_ts(_type_name(prop))}",
        f"required: {'true' if required else 'false'}",
        f"description: {_ts(str(prop.get('description') or ''))}",
    ]
    enum = prop.get("enum")
    if isinstance(enum, list) and enum:
        parts.append(
            f"enum: {_ts([x if isinstance(x, str) else str(x) for x in enum])}"
        )
    items = prop.get("items")
    if isinstance(items, dict):
        parts.append(f"items: {{ type: {_ts(_type_name(items))} }}")
    if "default" in prop:
        parts.append(f"default: {_ts(prop['default'])}")
    for bound in ("minimum", "maximum"):
        v = prop.get(bound)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            parts.append(f"{bound}: {_ts(v)}")
    show_when = SHOW_WHEN.get((slug, name))
    if show_when:
        parts.append(
            f"showWhen: {{ field: {_ts(show_when['field'])}, "
            f"values: {_ts(show_when['values'])} }}"
        )
    return "      { " + ", ".join(parts) + " },\n"


def _entry(slug: str, cls: type, category: str, name: str, description: str) -> str:
    schema = getattr(cls, "input_schema", None)
    schema = schema if isinstance(schema, dict) else {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    lines = [
        f"  {_ts_key(slug)}: {{\n",
        f"    category: {_ts(category)},\n",
        f"    name: {_ts(name)},\n",
        f"    description: {_ts(description)},\n",
    ]
    if props:
        lines.append("    parameters: [\n")
        for pname, prop in props.items():
            prop = prop if isinstance(prop, dict) else {}
            lines.append(_param(slug, pname, prop, pname in required))
        lines.append("    ],\n")
    else:
        lines.append("    parameters: [],\n")
    lines.append("  },\n")
    return "".join(lines)


def _description(cls: type, slug: str, existing: dict[str, str], entry: dict) -> str:
    runtime = (getattr(cls, "description", None) or "").strip()
    if runtime:
        return runtime
    if existing.get(slug):
        return existing[slug]
    if (entry.get("description") or "").strip():
        return entry["description"].strip()
    return (cls.__doc__ or "").strip().split("\n")[0]


def generate(current: str) -> str:
    consts = _router_constants()
    labels = _category_labels()
    classes = _runtime_classes(consts["LAZY_TOOL_MODULES"])
    catalog = {e["id"]: e for e in consts["TOOL_CATALOG"] if isinstance(e, dict)}
    hints = consts["_CATEGORY_HINTS"]
    existing = _existing_descriptions(current)

    def category_for(slug: str) -> str:
        cat = catalog.get(slug, {}).get("category")
        if not cat:
            cat = next(
                (c for prefixes, c in hints if slug.startswith(prefixes)), "core"
            )
        return labels.get(cat) or cat.capitalize()

    entries: list[str] = []
    for slug in sorted(classes):
        cls = classes[slug]
        entry = catalog.get(slug, {})
        name = entry.get("name") or slug.replace("_", " ").title()
        description = _description(cls, slug, existing, entry)
        entries.append(_entry(slug, cls, category_for(slug), name, description))

    docs = (
        "export const TOOL_DOCS: Record<string, ToolDoc> = {\n"
        + "".join(entries)
        + "};"
    )
    categories = (
        "export const TOOL_CATEGORIES = [\n"
        + "".join(f"  '{label}',\n" for label in labels.values())
        + "] as const;"
    )

    out = current.replace(_header_block(current), HEADER, 1)
    out = out.replace(_categories_block(out), categories, 1)
    return out.replace(_docs_block(out), docs, 1)


def main(argv: list[str]) -> int:
    if argv not in (["--check"], ["--write"]):
        print(__doc__)
        return 2
    current = DOCS.read_text(encoding="utf-8")
    fresh = generate(current)
    if argv == ["--write"]:
        if fresh != current:
            DOCS.write_text(fresh, encoding="utf-8", newline="\n")
            print(f"wrote {DOCS.relative_to(ROOT).as_posix()}")
        else:
            print("tool-docs.ts already up to date")
        return 0
    if fresh != current:
        print(
            "tool-docs.ts is stale, run: python scripts/gen-tool-docs.py --write",
            file=sys.stderr,
        )
        return 1
    print("tool-docs.ts is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
