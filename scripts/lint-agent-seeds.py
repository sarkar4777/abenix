#!/usr/bin/env python3
"""Lint every YAML under packages/db/seeds/agents/ against AgentSeedSchema.

Exits 0 only if every file passes strict validation. Hook this into CI
and pre-commit. Born from the ClaimsIQ Phase A4 incident where
pipeline_config was silently nested inside model_config and seed_agents.py
swallowed it without warning.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SEEDS_DIR = ROOT / "packages" / "db" / "seeds" / "agents"

sys.path.insert(0, str(ROOT / "packages" / "db" / "seeds"))

from agent_seed_schema import validate_agent_yaml  # noqa: E402


KB_SEEDS_DIR = ROOT / "packages" / "db" / "seeds" / "kb"


def _granted_slugs() -> set[str]:
    """Every agent slug any kb/*.yaml grants a collection to."""
    granted: set[str] = set()
    if not KB_SEEDS_DIR.is_dir():
        return granted
    for f in sorted(KB_SEEDS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for coll in data.get("collections") or []:
            for slug in coll.get("agent_slugs") or []:
                granted.add(str(slug))
    return granted


def check_knowledge_grants(yaml_files: list[Path]) -> list[tuple[str, str]]:
    """An agent may not declare knowledge_search with nowhere to search.

    Twenty-three agents once did. The tool is only registered when the agent
    has at least one collection, so the model was told in its prompt that it
    could search and then found no such tool at run time — it answered by
    narrating the call as prose. Nothing failed and nothing logged it.

    Either grant the agent a collection in packages/db/seeds/kb/, or take the
    tool out of its config. A pipeline whose nodes never name the tool counts
    as not using it.
    """
    granted = _granted_slugs()
    problems: list[tuple[str, str]] = []
    for f in yaml_files:
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        slug = str(data.get("slug") or "")
        cfg = data.get("model_config") or {}
        # Serialise the whole config, not just `tools`. A pipeline can ask for
        # the tool inside a node's inline agent, as a comma-separated
        # `arguments.tools` string, and a check that only reads the top-level
        # list calls five such pipelines clean. Confined to model_config so a
        # system prompt naming the slug as advice does not trip it.
        if "knowledge_search" not in json.dumps(cfg):
            continue
        if slug in granted:
            continue
        problems.append(
            (
                f.name,
                f"{slug} declares knowledge_search but no kb seed grants it a "
                "collection — grant one under packages/db/seeds/kb/, or drop "
                "the tool",
            )
        )
    return problems


def main() -> int:
    if not SEEDS_DIR.is_dir():
        print(f"[lint-agent-seeds] no seed dir at {SEEDS_DIR}")
        return 1

    yaml_files = sorted(SEEDS_DIR.glob("*.yaml"))
    failures: list[tuple[str, str]] = []
    for f in yaml_files:
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            failures.append((f.name, f"YAML parse error: {e}"))
            continue
        if not isinstance(data, dict):
            failures.append((f.name, "top-level YAML is not a mapping"))
            continue
        try:
            validate_agent_yaml(f.name, data)
        except Exception as e:  # noqa: BLE001
            failures.append((f.name, str(e)))

    failures.extend(check_knowledge_grants(yaml_files))

    if failures:
        print(f"[lint-agent-seeds] FAIL: {len(failures)}/{len(yaml_files)} broken")
        for name, err in failures:
            print(f"  - {name}: {err}")
        return 1

    print(f"[lint-agent-seeds] OK: {len(yaml_files)} agent YAMLs validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
