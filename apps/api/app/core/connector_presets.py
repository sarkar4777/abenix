"""Loader for connector presets shipped under packages/db/seeds/connector_presets/.

Presets are read-only YAML on disk; we cache them in process memory. Each
preset declares operations -> (method, path template, args, body template,
query params). The ``connector_call`` tool plus the connectors router both
consume this loader so they never drift.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_PRESETS_CACHE: dict[str, dict[str, Any]] | None = None


def _presets_dir() -> Path:
    here = Path(__file__).resolve()
    # apps/api/app/core/connector_presets.py -> repo root is parents[4]
    candidates = [
        here.parents[4] / "packages" / "db" / "seeds" / "connector_presets",
        Path("/app/packages/db/seeds/connector_presets"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def load_presets() -> dict[str, dict[str, Any]]:
    """Return all presets keyed by preset_key. Caches in process memory."""
    global _PRESETS_CACHE
    if _PRESETS_CACHE is not None:
        return _PRESETS_CACHE
    out: dict[str, dict[str, Any]] = {}
    d = _presets_dir()
    if not d.exists():
        _PRESETS_CACHE = out
        return out
    for fp in sorted(d.glob("*.yaml")):
        try:
            data = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        key = data.get("key") or fp.stem
        data["key"] = key
        out[key] = data
    _PRESETS_CACHE = out
    return out


def list_presets_summary() -> list[dict[str, Any]]:
    """Lightweight list shape for the admin UI dropdown."""
    return [
        {
            "key": p.get("key"),
            "label": p.get("label", p.get("key")),
            "kind": p.get("kind", "custom"),
            "auth_type": p.get("auth_type", "none"),
            "base_url_template": p.get("base_url_template", ""),
            "operations": list((p.get("operations") or {}).keys()),
        }
        for p in load_presets().values()
    ]


def get_preset(key: str) -> dict[str, Any] | None:
    return load_presets().get(key)


def reset_cache() -> None:
    """Test hook so unit tests can re-read after edits."""
    global _PRESETS_CACHE
    _PRESETS_CACHE = None
