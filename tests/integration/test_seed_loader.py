"""Integration tests for the agent seed loader.

These tests exercise the strict-validation gate added in response to
the ClaimsIQ Phase A4 incident, where ``pipeline_config:`` was silently
nested under ``model_config:`` in two YAMLs and the loader registered
the agent as a single-step LLM agent. Every execution returned
status=failed in 2-5s with a cryptic 4xx.

Run:
    python -m pytest tests/integration/test_seed_loader.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SEEDS_DIR = ROOT / "packages" / "db" / "seeds" / "agents"

sys.path.insert(0, str(ROOT / "packages" / "db" / "seeds"))

from agent_seed_schema import (  # noqa: E402
    AgentSeedSchema,
    validate_agent_yaml,
)


# --- Happy paths ---------------------------------------------------------


def test_every_shipped_agent_yaml_validates() -> None:
    """All YAMLs under packages/db/seeds/agents/ must satisfy the schema.

    This is the exact same check scripts/lint-agent-seeds.py performs,
    surfaced here so a developer running pytest catches a malformed
    seed without needing to remember the lint command.
    """
    failures: list[str] = []
    yamls = sorted(SEEDS_DIR.glob("*.yaml"))
    assert yamls, "no agent seeds found — fixture path wrong?"
    for f in yamls:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        try:
            validate_agent_yaml(f.name, data)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{f.name}: {e}")
    assert not failures, "malformed agent seeds:\n" + "\n".join(failures)


def test_pipeline_yamls_have_top_level_pipeline_config() -> None:
    """Every mode=pipeline YAML must have pipeline_config at the top
    level, NOT nested inside model_config.

    Direct regression test for the ClaimsIQ Phase A4 incident.
    """
    offenders: list[str] = []
    for f in sorted(SEEDS_DIR.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        if data.get("mode") != "pipeline":
            continue
        nested = (data.get("model_config") or {}).get("pipeline_config")
        top = data.get("pipeline_config")
        if nested or not top:
            offenders.append(f.name)
    assert not offenders, (
        "pipeline_config nested under model_config (or missing): " + ", ".join(offenders)
    )


# --- Failing-YAML fixtures ----------------------------------------------


def _base_yaml() -> dict:
    return {
        "name": "Test Agent",
        "slug": "test-agent",
        "agent_type": "oob",
        "version": "1.0.0",
        "status": "active",
        "system_prompt": "test",
        "model_config": {
            "model": "claude-sonnet-4-5-20250929",
            "temperature": 0.5,
            "tools": [],
        },
    }


def test_nested_pipeline_config_is_rejected() -> None:
    """The exact bug class that bit ClaimsIQ: pipeline_config under
    model_config must raise ValueError — NOT be silently accepted.
    """
    bad = _base_yaml()
    bad["mode"] = "pipeline"
    bad["model_config"]["pipeline_config"] = {
        "nodes": [{"id": "n1", "type": "agent"}],
    }
    with pytest.raises(ValueError) as exc_info:
        validate_agent_yaml("bad.yaml", bad)
    assert "pipeline_config" in str(exc_info.value).lower()
    assert "top level" in str(exc_info.value).lower()


def test_pipeline_mode_without_pipeline_config_is_rejected() -> None:
    bad = _base_yaml()
    bad["mode"] = "pipeline"
    # No top-level pipeline_config at all.
    with pytest.raises(ValueError) as exc_info:
        validate_agent_yaml("bad.yaml", bad)
    assert "pipeline" in str(exc_info.value).lower()


def test_pipeline_with_empty_nodes_is_rejected() -> None:
    bad = _base_yaml()
    bad["mode"] = "pipeline"
    bad["pipeline_config"] = {"nodes": []}
    with pytest.raises(ValueError):
        validate_agent_yaml("bad.yaml", bad)


def test_pipeline_node_missing_id_or_kind_is_rejected() -> None:
    bad = _base_yaml()
    bad["mode"] = "pipeline"
    # node has neither type nor tool_name
    bad["pipeline_config"] = {"nodes": [{"id": "n1"}]}
    with pytest.raises(ValueError) as exc_info:
        validate_agent_yaml("bad.yaml", bad)
    msg = str(exc_info.value).lower()
    assert "type" in msg or "tool_name" in msg


def test_invalid_slug_is_rejected() -> None:
    bad = _base_yaml()
    bad["slug"] = "Invalid Slug With Spaces"
    with pytest.raises(ValueError):
        validate_agent_yaml("bad.yaml", bad)


def test_node_with_tool_name_only_is_accepted() -> None:
    """The legacy DSL form (tool_name in lieu of explicit type) must
    still validate — many shipped pipelines use it.
    """
    good = _base_yaml()
    good["mode"] = "pipeline"
    good["pipeline_config"] = {
        "nodes": [{"id": "step1", "tool_name": "llm_call"}]
    }
    parsed = validate_agent_yaml("good.yaml", good)
    assert isinstance(parsed, AgentSeedSchema)
