"""An agent saved with a model or tool a run cannot use is told so, and the save still works."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.routers import agents as ag
from app.schemas.agents import CreateAgentRequest
from app.services import agent_config_warnings as acw

ROOT = Path(__file__).resolve().parents[2]
LISTED = {"claude-sonnet-5", "gpt-4o"}
KNOWN = {"calculator", "web_search"}


def test_a_valid_config_has_no_warnings():
    assert acw.find_problems("gpt-4o", ["calculator"], LISTED, KNOWN) == []


def test_a_fake_model_is_named():
    out = acw.find_problems("gpt-fake", [], LISTED, KNOWN)
    assert len(out) == 1 and "gpt-fake" in out[0]


def test_unknown_tools_are_named():
    out = acw.find_problems("gpt-4o", ["calculator", "made_up"], LISTED, KNOWN)
    assert len(out) == 1 and "made_up" in out[0] and "calculator" not in out[0]


def test_dynamic_tools_are_not_flagged():
    tools = ["portfolio_loans", "atlas_query", "pipeline:daily", "mcp_github_list"]
    assert acw.find_problems("gpt-4o", tools, LISTED, KNOWN) == []


def test_an_unseeded_catalogue_does_not_condemn_every_model():
    assert acw.find_problems("gpt-4o", [], set(), KNOWN) == []


def test_real_tool_names_are_known_to_the_catalogue():
    from app.routers.tools import TOOL_CATALOG, _load_runtime_schemas

    known = set(_load_runtime_schemas()) | {t["id"] for t in TOOL_CATALOG}
    for name in (
        "calculator",
        "web_search",
        "tavily_search",
        "knowledge_search",
        "knowledge_store",
    ):
        assert name in known


def _create(monkeypatch, warnings, **body_kwargs):
    monkeypatch.setattr(ag, "log_action", AsyncMock())
    monkeypatch.setattr(ag, "_sync_kb_grants", AsyncMock(return_value=[]))
    monkeypatch.setattr(ag, "_apply_scaling", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_serialize_agent", lambda a: dict(a.model_config_))
    monkeypatch.setattr(ag, "config_warnings", AsyncMock(return_value=warnings))
    db = MagicMock()
    no_row = MagicMock()
    no_row.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=no_row)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    user = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=SimpleNamespace(value="user")
    )
    body = CreateAgentRequest(name="T", **body_kwargs)
    resp = asyncio.run(ag.create_agent(body, MagicMock(), user=user, db=db))
    assert resp.status_code == 201
    return json.loads(resp.body)["data"]


def test_create_returns_the_warnings_and_still_saves(monkeypatch):
    data = _create(monkeypatch, ["Model gpt-fake is not listed"], model="gpt-fake")
    assert data["warnings"] == ["Model gpt-fake is not listed"]
    assert data["model"] == "gpt-fake"


def test_create_has_no_warnings_key_when_clean(monkeypatch):
    assert "warnings" not in _create(monkeypatch, [], model="gpt-4o")


def test_a_broken_check_gives_no_warnings():
    with patch("app.core.deps.fresh_session", side_effect=RuntimeError("db down")):
        assert asyncio.run(acw.config_warnings({"model": "x"}, uuid.uuid4())) == []


def test_openapi_version_is_the_product_version():
    from app.main import app

    assert app.version == (ROOT / "VERSION").read_text().strip()
    assert app.openapi()["info"]["version"] == app.version


def test_the_api_image_ships_the_version_file():
    assert "COPY VERSION" in (ROOT / "docker" / "Dockerfile.api").read_text()
