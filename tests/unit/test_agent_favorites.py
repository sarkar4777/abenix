"""Stars on deleted agents must not link to a 404."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "db"))

from models.agent import AgentStatus, AgentType

from app.routers import agent_favorites
from app.routers.agent_favorites import favorite_is_live


def _agent(status: AgentStatus, kind: AgentType) -> SimpleNamespace:
    return SimpleNamespace(status=status, agent_type=kind)


def test_archived_custom_agent_is_not_live() -> None:
    assert not favorite_is_live(_agent(AgentStatus.ARCHIVED, AgentType.CUSTOM))


def test_active_and_draft_agents_are_live() -> None:
    assert favorite_is_live(_agent(AgentStatus.ACTIVE, AgentType.CUSTOM))
    assert favorite_is_live(_agent(AgentStatus.DRAFT, AgentType.CUSTOM))


def test_archived_oob_agent_still_opens() -> None:
    assert favorite_is_live(_agent(AgentStatus.ARCHIVED, AgentType.OOB))


def test_list_and_add_filter_on_liveness_and_access() -> None:
    listing = inspect.getsource(agent_favorites.list_favorites)
    adding = inspect.getsource(agent_favorites.add_favorite)
    for src in (listing, adding):
        assert "favorite_is_live" in src
        assert "resolve_agent_access" in src
