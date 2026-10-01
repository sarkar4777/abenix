"""Scrub agent templates on the way out and validate them on the way in."""

from __future__ import annotations

import copy
import re
import uuid
from typing import Any

_CREDENTIAL_KEY = re.compile(
    r"(api[_-]?key|apikey|secret|token|password|passwd|credential|authorization|"
    r"bearer|private[_-]?key|connection[_-]?string|\bdsn\b|webhook[_-]?url|client[_-]?secret)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"^(sk-[A-Za-z0-9_-]{8,}|sk-ant-[A-Za-z0-9_-]{8,}|xox[abp]-[A-Za-z0-9-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|Bearer\s+\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----.*)$",
    re.DOTALL,
)

# Keys whose values name tenant-owned resources. The importer may not own them.
RESOURCE_ID_KEYS: dict[str, str] = {
    "code_asset_id": "code_asset",
    "code_asset_ids": "code_asset",
    "asset_id": "code_asset",
    "model_id": "ml_model",
    "ml_model_id": "ml_model",
    "ml_model_ids": "ml_model",
    "collection_id": "knowledge_collection",
    "collection_ids": "knowledge_collection",
    "knowledge_collection_ids": "knowledge_collection",
    "knowledge_base_id": "knowledge_collection",
    "knowledge_base_ids": "knowledge_collection",
    "connector_id": "connector",
    "connector_ids": "connector",
    "connection_id": "connector",
    "mcp_connection_id": "connector",
}
# Whole subtrees that only make sense inside the exporting tenant.
TENANT_BOUND_KEYS = ("mcp_extensions",)


def _is_uuid(v: Any) -> bool:
    try:
        uuid.UUID(str(v))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def strip_credentials(cfg: Any, path: str = "") -> tuple[Any, list[str]]:
    """Drop credential-looking keys and values anywhere in the tree."""
    stripped: list[str] = []
    if isinstance(cfg, dict):
        out: dict[str, Any] = {}
        for k, v in cfg.items():
            here = f"{path}.{k}" if path else str(k)
            if _CREDENTIAL_KEY.search(str(k)):
                stripped.append(here)
                continue
            if isinstance(v, str) and _SECRET_VALUE.match(v.strip()):
                stripped.append(here)
                continue
            clean, sub = strip_credentials(v, here)
            stripped.extend(sub)
            out[k] = clean
        return out, stripped
    if isinstance(cfg, list):
        items = []
        for i, v in enumerate(cfg):
            clean, sub = strip_credentials(v, f"{path}[{i}]")
            stripped.extend(sub)
            items.append(clean)
        return items, stripped
    return cfg, stripped


def strip_resource_refs(cfg: Any, path: str = "") -> tuple[Any, list[str]]:
    """Drop ids of KBs, code assets, models and connectors the importer cannot own."""
    stripped: list[str] = []
    if isinstance(cfg, dict):
        out: dict[str, Any] = {}
        for k, v in cfg.items():
            here = f"{path}.{k}" if path else str(k)
            if k in RESOURCE_ID_KEYS or k in TENANT_BOUND_KEYS:
                stripped.append(here)
                continue
            clean, sub = strip_resource_refs(v, here)
            stripped.extend(sub)
            out[k] = clean
        return out, stripped
    if isinstance(cfg, list):
        items = []
        for i, v in enumerate(cfg):
            clean, sub = strip_resource_refs(v, f"{path}[{i}]")
            stripped.extend(sub)
            items.append(clean)
        return items, stripped
    return cfg, stripped


def sanitize_for_export(cfg: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    clean, a = strip_credentials(copy.deepcopy(cfg or {}))
    clean, b = strip_resource_refs(clean)
    return clean, a + b


def referenced_resource_ids(cfg: Any) -> dict[str, set[str]]:
    """Every uuid under a resource-id key, grouped by resource kind."""
    found: dict[str, set[str]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in TENANT_BOUND_KEYS:
                    continue
                kind = RESOURCE_ID_KEYS.get(k)
                if kind:
                    vals = v if isinstance(v, list) else [v]
                    for item in vals:
                        if _is_uuid(item):
                            found.setdefault(kind, set()).add(str(uuid.UUID(str(item))))
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(cfg)
    return found


def drop_unknown_refs(
    cfg: Any, invalid: set[str], path: str = ""
) -> tuple[Any, list[str]]:
    """Remove resource ids not in the importer's tenant, keep the rest."""
    dropped: list[str] = []
    if isinstance(cfg, dict):
        out: dict[str, Any] = {}
        for k, v in cfg.items():
            here = f"{path}.{k}" if path else str(k)
            if k in TENANT_BOUND_KEYS:
                dropped.append(here)
                continue
            if k in RESOURCE_ID_KEYS:
                if isinstance(v, list):
                    keep = [
                        x
                        for x in v
                        if _is_uuid(x) and str(uuid.UUID(str(x))) not in invalid
                    ]
                    if len(keep) != len(v):
                        dropped.append(here)
                    out[k] = keep
                    continue
                if v is None or (_is_uuid(v) and str(uuid.UUID(str(v))) not in invalid):
                    out[k] = v
                else:
                    dropped.append(here)
                continue
            clean, sub = drop_unknown_refs(v, invalid, here)
            dropped.extend(sub)
            out[k] = clean
        return out, dropped
    if isinstance(cfg, list):
        items = []
        for i, v in enumerate(cfg):
            clean, sub = drop_unknown_refs(v, invalid, f"{path}[{i}]")
            dropped.extend(sub)
            items.append(clean)
        return items, dropped
    return cfg, dropped
