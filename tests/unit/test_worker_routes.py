"""The Celery worker has no agent task, queued agent runs go over NATS."""

from __future__ import annotations

import importlib

import pytest

pytest.importorskip("celery")


def test_every_included_task_module_exists_and_none_runs_agents():
    from worker.celery_app import celery_app

    include = list(celery_app.conf.include)
    assert include
    assert not any("agent_tasks" in m for m in include)
    for mod in include:
        assert importlib.util.find_spec(mod) is not None, mod


def test_no_route_sends_work_to_an_agents_queue():
    from worker.celery_app import celery_app

    routes = celery_app.conf.task_routes
    assert not any("agent_tasks" in k for k in routes)
    assert "agents" not in {v["queue"] for v in routes.values()}
