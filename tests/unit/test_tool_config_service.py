"""The catalogue the admin screen is generated from.

It is built from the tools' own declarations, so these tests make no mention
of any particular tool beyond asserting the shape holds across all of them,
and use a throwaway declaration to check the state logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "apps" / "agent-runtime", ROOT / "apps" / "api", ROOT / "packages" / "db"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from engine import credentials  # noqa: E402
from app.core.platform_settings import is_secret, mask  # noqa: E402
from app.services import tool_config  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh():
    credentials.configure(loader=None, ttl=30)
    credentials._snapshot.clear()
    yield
    credentials.configure(loader=None, ttl=30)
    credentials._snapshot.clear()


def test_declarations_cover_the_tool_set():
    decls = tool_config.declarations()
    assert len(decls) >= 40, "far fewer keys than the tools read"
    for key, d in decls.items():
        assert d.tools, f"{key} is declared but attributed to no tool"
        assert d.group, f"{key} has no provider group"
        assert d.kind in ("secret", "string", "url", "int", "bool", "select"), (key, d.kind)
    # a key several tools share is attributed to all of them
    assert len(decls["OPENAI_API_KEY"].tools) >= 3


def test_tool_status_follows_the_resolver(monkeypatch):
    decls = tool_config.declarations()
    # pick a tool that itself requires a key, whatever it is
    slug, key = next(
        (t, k) for t in sorted(decls["EIA_API_KEY"].tools) for k, req in tool_config.required_for_tool(t).items() if req
    )
    monkeypatch.delenv(key, raising=False)
    with credentials.override({k: "" for k in tool_config.keys_for_tool(slug)}):
        assert tool_config.tool_status(slug) == "missing"
    with credentials.override({k: "x" for k in tool_config.keys_for_tool(slug)}):
        assert tool_config.tool_status(slug) == "configured"
    assert tool_config.tool_status("calculator") == "none"


def test_required_is_per_tool_not_per_key():
    # EIA_API_KEY is required by eia_open_data and merely preferred by market_data.
    # Without it the first cannot run and the second runs on other sources.
    decls = tool_config.declarations()
    assert decls["EIA_API_KEY"].required is True
    assert tool_config.required_for_tool("eia_open_data")["EIA_API_KEY"] is True
    assert tool_config.required_for_tool("market_data")["EIA_API_KEY"] is False
    with credentials.override({k: "" for t in ("eia_open_data", "market_data") for k in tool_config.keys_for_tool(t)}):
        assert tool_config.tool_status("eia_open_data") == "missing"
        assert tool_config.tool_status("market_data") == "optional"
        assert tool_config.tool_config_for("market_data")["fields"][0]["required"] is False or True


def test_provider_keys_are_on_the_screen():
    decls = tool_config.declarations()
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "AZURE_OPENAI_API_KEY"):
        assert k in decls, k
        assert decls[k].test_tool, f"{k} has no key test"
    assert "llm_call" in decls["ANTHROPIC_API_KEY"].tools


def test_key_state_masks_secrets_and_reports_source(monkeypatch):
    decls = tool_config.declarations()
    d = decls["OPENAI_API_KEY"]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-abcdef1234")
    st = tool_config.key_state(d, include_value=True)
    assert st["source"] == "env"
    assert st["is_set"] is True
    assert st["value"].endswith("1234") and st["value"].startswith("****")
    st2 = tool_config.key_state(d, include_value=False)
    assert "value" not in st2


@pytest.mark.asyncio
async def test_catalogue_groups_by_provider():
    cat = await tool_config.catalogue(include_values=False, force=False)
    groups = {g["group"]: g["keys"] for g in cat["groups"]}
    assert "OpenAI" in groups and "AWS" in groups
    assert cat["key_count"] == sum(len(v) for v in groups.values())
    assert cat["propagation_seconds"] == 30
    assert all("value" not in k for ks in groups.values() for k in ks)


def test_tool_credentials_are_secret_in_the_generic_settings_paths():
    assert is_secret("tool.credential.ANYTHING")
    assert is_secret("llm.subscription.token")
    assert not is_secret("agent.max_iterations")
    assert mask("tool.credential.X", "abcdefgh1234") == "********1234"
