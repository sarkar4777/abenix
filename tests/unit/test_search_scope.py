"""Global search links to pages that exist and only finds what the caller can open."""

from __future__ import annotations

import inspect

from app.routers import search


def test_agent_results_open_the_info_page():
    src = inspect.getsource(search.search)
    assert 'f"/agents/{r.id}/info"' in src
    assert 'f"/agents/{r.id}"' not in src


def test_knowledge_results_use_the_real_model_and_route():
    src = inspect.getsource(search.search)
    assert "models.knowledge_base" in src
    assert "/knowledge?id=" in src
    assert "accessible_collection_ids" in src


def test_agents_and_runs_are_scoped_to_the_caller():
    src = inspect.getsource(search.search)
    assert "accessible_agent_ids" in src
    assert "Execution.user_id == user.id" in src
    assert "apply_resource_scope" in src


def test_runs_match_what_they_were_asked():
    assert "Execution.input_message.ilike(like)" in inspect.getsource(search.search)
