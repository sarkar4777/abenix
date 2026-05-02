#!/usr/bin/env python3
"""Lint every YAML under packages/db/seeds/agents/ against AgentSeedSchema.

Exits 0 only if every file passes strict validation. Hook this into CI
and pre-commit. Born from the ClaimsIQ Phase A4 incident where
pipeline_config was silently nested inside model_config and seed_agents.py
swallowed it without warning.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SEEDS_DIR = ROOT / "packages" / "db" / "seeds" / "agents"

sys.path.insert(0, str(ROOT / "packages" / "db" / "seeds"))

from agent_seed_schema import validate_agent_yaml  # noqa: E402


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

    if failures:
        print(f"[lint-agent-seeds] FAIL: {len(failures)}/{len(yaml_files)} broken")
        for name, err in failures:
            print(f"  - {name}: {err}")
        return 1

    print(f"[lint-agent-seeds] OK: {len(yaml_files)} agent YAMLs validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
