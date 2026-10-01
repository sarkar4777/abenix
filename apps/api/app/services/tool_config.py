"""What the platform knows about tool configuration, built from the tools.

Every tool declares the values it needs as `config_fields` on its class. This
module reads those declarations off the runtime classes, the same way the
catalogue reads `input_schema`, and turns them into the shape the admin screen,
the catalogue badges and the Integrations page render. Nothing here names a
tool. A new tool that passes the lint appears everywhere with no change to
this file.

Storage is per key, not per tool. OPENAI_API_KEY is read by eight tools and is
entered once. The screen groups keys by provider and lists the tools each one
unlocks.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any

from engine import credentials

logger = logging.getLogger(__name__)

# Modules the executor builds with context, so they are not in _TOOL_CLASSES.
# Mirrors _LAZY_MODULES in routers/tools.py.
_LAZY_MODULES = [
    ("engine.tools.knowledge_search", ["KnowledgeSearchTool"]),
    ("engine.tools.knowledge_store", ["KnowledgeStoreTool"]),
    ("engine.tools.graph_explorer_tool", ["GraphExplorerTool"]),
    (
        "engine.tools.atlas_tools",
        [
            "AtlasDescribeTool",
            "AtlasQueryTool",
            "AtlasTraverseTool",
            "AtlasSearchGroundedTool",
        ],
    ),
    ("engine.tools.schema_portfolio_tool", ["SchemaPortfolioTool"]),
]

OUT_OF_SCOPE = [
    "MCP tools carry their credentials on the MCP connection, see /mcp.",
    "Code assets keep their own encrypted secrets, see /code-runner.",
    "Tools an agent generates at run time cannot read configuration.",
]


@dataclass
class KeyDecl:
    key: str
    label: str = ""
    kind: str = "secret"
    required: bool = False
    group: str = ""
    description: str = ""
    signup_url: str = ""
    default: str | None = None
    options: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    test_tool: str | None = None  # slug of a declaring tool that can test the value


_DECLS: dict[str, KeyDecl] | None = None
_BY_TOOL: dict[str, dict[str, bool]] | None = None


def _iter_tool_classes():
    from engine.agent_executor import (  # type: ignore
        _CONTEXT_TOOL_FACTORIES,
        _TOOL_CLASSES,
        _ensure_tool_classes,
    )

    _ensure_tool_classes()
    seen: set[str] = set()
    for name, cls in list(_TOOL_CLASSES.items()) + list(
        _CONTEXT_TOOL_FACTORIES.items()
    ):
        if name in seen:
            continue
        seen.add(name)
        yield name, cls
    for mod_path, class_names in _LAZY_MODULES:
        try:
            mod = importlib.import_module(mod_path)
        except Exception as e:  # noqa: BLE001
            logger.debug("tool config: cannot import %s: %s", mod_path, e)
            continue
        for cn in class_names:
            cls = getattr(mod, cn, None)
            name = getattr(cls, "name", None) if cls else None
            if cls is not None and name and name not in seen:
                seen.add(name)
                yield name, cls


def _has_own_test(cls: type) -> bool:
    from engine.tools.base import BaseTool

    return (
        "config_test" in vars(cls)
        and vars(cls)["config_test"] is not vars(BaseTool)["config_test"]
    )


def declarations() -> dict[str, KeyDecl]:
    """Every declared key, merged across the tools that declare it."""
    global _DECLS, _BY_TOOL
    if _DECLS is not None:
        return _DECLS
    decls: dict[str, KeyDecl] = {}
    by_tool: dict[str, dict[str, bool]] = {}
    for slug, cls in _iter_tool_classes():
        fields = getattr(cls, "config_fields", ()) or ()
        # required is per tool: eia_open_data needs EIA_API_KEY, market_data only prefers it
        by_tool[slug] = {f.key: bool(f.required) for f in fields}
        for f in fields:
            d = decls.get(f.key)
            if d is None:
                d = KeyDecl(
                    key=f.key,
                    label=f.label,
                    kind=f.kind,
                    required=f.required,
                    group=f.group,
                    description=f.description,
                    signup_url=f.signup_url,
                    default=f.default,
                    options=list(f.options or ()),
                )
                decls[f.key] = d
            else:
                # Several tools may declare the same key. Required on the screen if
                # any tool needs it, and the fullest description wins.
                d.required = d.required or f.required
                d.label = d.label or f.label
                d.group = d.group or f.group
                if len(f.description or "") > len(d.description or ""):
                    d.description = f.description
                d.signup_url = d.signup_url or f.signup_url
                if d.default is None:
                    d.default = f.default
            if slug not in d.tools:
                d.tools.append(slug)
            if d.test_tool is None and _has_own_test(cls):
                d.test_tool = slug
    for d in decls.values():
        d.group = d.group or "Other"
        d.label = d.label or d.key
    _DECLS, _BY_TOOL = decls, by_tool
    return decls


def keys_for_tool(slug: str) -> list[str]:
    declarations()
    return list((_BY_TOOL or {}).get(slug, {}))


def required_for_tool(slug: str) -> dict[str, bool]:
    declarations()
    return dict((_BY_TOOL or {}).get(slug, {}))


def reset_cache() -> None:
    global _DECLS, _BY_TOOL
    _DECLS, _BY_TOOL = None, None


async def refresh(force: bool = False) -> None:
    await credentials.ensure_fresh(force=force)


def _masked(decl: KeyDecl, value: str) -> str:
    if decl.kind != "secret":
        return value
    v = value.strip()
    if not v:
        return ""
    return f"{'*' * 8}{v[-4:]}" if len(v) > 4 else "*" * 8


def key_state(decl: KeyDecl, include_value: bool) -> dict[str, Any]:
    source = credentials.source(decl.key, default=decl.default)
    value = credentials.get(decl.key, default=decl.default)
    out: dict[str, Any] = {
        "key": decl.key,
        "label": decl.label,
        "kind": decl.kind,
        "required": decl.required,
        "group": decl.group,
        "description": decl.description,
        "signup_url": decl.signup_url,
        "default": decl.default,
        "options": decl.options,
        "tools": sorted(decl.tools),
        "source": source,
        "is_set": bool(value),
        "can_test": decl.test_tool is not None,
    }
    if include_value:
        out["value"] = _masked(decl, value)
    return out


def tool_status(slug: str) -> str:
    """configured | missing | optional | none, for a badge."""
    decls = declarations()
    keys = required_for_tool(slug)
    if not keys:
        return "none"
    required_missing = False
    optional_missing = False
    for k, required in keys.items():
        d = decls[k]
        if credentials.get(k, default=d.default):
            continue
        if required:
            required_missing = True
        else:
            optional_missing = True
    if required_missing:
        return "missing"
    if optional_missing:
        return "optional"
    return "configured"


def tool_config_for(slug: str) -> dict[str, Any]:
    """The per-tool shape /api/tools carries."""
    decls = declarations()
    fields = []
    for k, required in required_for_tool(slug).items():
        st = key_state(decls[k], include_value=False)
        st["required"] = required
        fields.append(st)
    return {"fields": fields, "status": tool_status(slug)}


async def catalogue(include_values: bool = False, force: bool = True) -> dict[str, Any]:
    """Grouped by provider. The admin screen asks for values, the rest do not."""
    await refresh(force=force)
    decls = declarations()
    groups: dict[str, list[dict[str, Any]]] = {}
    for d in sorted(
        decls.values(), key=lambda d: (d.group.lower(), not d.required, d.key)
    ):
        groups.setdefault(d.group, []).append(key_state(d, include_values))
    missing_required = sum(
        1
        for d in decls.values()
        if d.required and not credentials.get(d.key, default=d.default)
    )
    try:
        from app.core.tool_secrets import encrypted_at_rest

        enc = encrypted_at_rest()
    except Exception:  # noqa: BLE001
        enc = False
    return {
        "groups": [
            {"group": g, "keys": ks}
            for g, ks in sorted(groups.items(), key=lambda kv: kv[0].lower())
        ],
        "key_count": len(decls),
        "tool_count": len(_BY_TOOL or {}),
        "missing_required": missing_required,
        "encrypted_at_rest": enc,
        "propagation_seconds": int(credentials._ttl),
        "out_of_scope": OUT_OF_SCOPE,
    }
