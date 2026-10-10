"""Smaller fixes found while driving the admin and depth screens."""

from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from types import SimpleNamespace

from models.user import UserRole

T = uuid.uuid4()


def _user(role=UserRole.USER):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=T, role=role, email="u@x.io", full_name="U"
    )


def test_role_matrix_mirrors_the_server_table():
    from app.core.permissions import features_for
    from app.routers.me import role_matrix

    resp = asyncio.run(role_matrix(_user()))
    roles = json.loads(resp.body)["data"]["roles"]
    assert set(roles) == {"admin", "creator", "user"}
    assert roles["creator"] == features_for(SimpleNamespace(role="creator"))
    assert roles["user"]["manage_ontology"] is False
    assert roles["creator"]["manage_ontology"] is True


class _Res:
    def __init__(self, v):
        self.v = v

    def scalar_one_or_none(self):
        return self.v


class _DB:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.deleted = []

    async def execute(self, stmt):
        return _Res(self.answers.pop(0) if self.answers else None)

    async def commit(self):
        pass

    async def delete(self, obj):
        self.deleted.append(obj)


def _comments(monkeypatch, agent):
    from app.routers import agent_comments

    async def load(db, agent_id, user):
        return agent

    monkeypatch.setattr(agent_comments, "_load_agent_for_caller", load)
    return agent_comments


def test_only_the_author_edits_a_comment(monkeypatch):
    owner = _user()
    agent = SimpleNamespace(id=uuid.uuid4(), creator_id=owner.id, tenant_id=T)
    mod = _comments(monkeypatch, agent)
    author = _user()
    c = SimpleNamespace(user_id=author.id, content="x", is_resolved=False)
    resp = asyncio.run(
        mod.update_comment(agent.id, uuid.uuid4(), {"content": "hijack"}, owner, _DB(c))
    )
    assert resp.status_code == 403
    assert c.content == "x"
    # the owner may still resolve it
    resp = asyncio.run(
        mod.update_comment(agent.id, uuid.uuid4(), {"is_resolved": True}, owner, _DB(c))
    )
    assert json.loads(resp.body)["data"]["updated"] is True
    assert c.is_resolved is True


def test_a_bystander_cannot_resolve_or_delete(monkeypatch):
    agent = SimpleNamespace(id=uuid.uuid4(), creator_id=uuid.uuid4(), tenant_id=T)
    mod = _comments(monkeypatch, agent)
    c = SimpleNamespace(user_id=uuid.uuid4(), content="x", is_resolved=False)
    other = _user()
    assert (
        asyncio.run(
            mod.update_comment(
                agent.id, uuid.uuid4(), {"is_resolved": True}, other, _DB(c)
            )
        ).status_code
        == 403
    )
    db = _DB(c)
    assert (
        asyncio.run(mod.delete_comment(agent.id, uuid.uuid4(), other, db)).status_code
        == 403
    )
    assert db.deleted == []
    db = _DB(c)
    assert (
        asyncio.run(
            mod.delete_comment(agent.id, uuid.uuid4(), _user(UserRole.ADMIN), db)
        ).status_code
        == 200
    )
    assert db.deleted == [c]


def test_comments_and_favorites_follow_agent_access():
    from app.routers import agent_comments, agent_favorites

    assert "resolve_agent_access" in inspect.getsource(
        agent_comments._load_agent_for_caller
    )
    assert "resolve_agent_access" in inspect.getsource(agent_favorites.add_favorite)


def test_security_page_activity_is_your_own():
    from app.routers import settings

    assert "ActivityLog.user_id == user.id" in inspect.getsource(settings.get_activity)


def test_audit_events_filters():
    from app.routers import governance

    src = inspect.getsource(governance.list_audit_events)
    for needle in (
        "ActivityLog.user_id == actor_id",
        "ActivityLog.action.ilike",
        "audit_seq < before",
        'require_capability("audit.view")',
    ):
        assert needle in src


def test_a_zero_cognify_budget_reads_back_as_zero():
    from app.routers import knowledge_v2

    src = inspect.getsource(knowledge_v2)
    assert "if cfg.daily_budget_usd is not None" in src


def test_memory_search_matches_any_word_best_first():
    from sqlalchemy.dialects import postgresql

    from engine.tools.memory_recall import _search_terms
    from models.agent_memory import AgentMemory

    match, score = _search_terms("favourite color", AgentMemory)
    opts = {"literal_binds": True}
    where = str(match.compile(dialect=postgresql.dialect(), compile_kwargs=opts))
    order = str(score.compile(dialect=postgresql.dialect(), compile_kwargs=opts))
    assert "replace(agent_memories.key, '_', ' ')" in where
    # either word is enough, so American spelling still finds favourite_colour
    assert " OR " in where and "%favourite%" in where and "%color%" in where
    assert order.count("CASE WHEN") == 2


def test_cognify_worker_names_the_sync_driver(monkeypatch):
    from worker.tasks import cognify_task

    monkeypatch.setattr(
        cognify_task,
        "DATABASE_URL",
        "postgresql+asyncpg://u:p@db:5432/abenix?ssl=disable",
    )
    assert cognify_task._get_db_url() == "postgresql+psycopg2://u:p@db:5432/abenix"


def test_an_added_model_is_known_without_waiting_for_the_cache(monkeypatch):
    from engine import llm_router

    monkeypatch.setattr(llm_router, "_DB_PROVIDER_CACHE", {})
    monkeypatch.setattr(llm_router, "_PRICING_MISS_REFRESH_AT", 0.0)

    calls = []

    def fake_load():
        # the first read is the stale cache, the forced one sees the new row
        calls.append(1)
        if len(calls) > 1:
            llm_router._DB_PROVIDER_CACHE["uat-new-model"] = "openai"
        return {}

    monkeypatch.setattr(llm_router, "_load_db_pricing", fake_load)
    router = llm_router.LLMRouter.__new__(llm_router.LLMRouter)
    assert router.is_known_model("uat-new-model") is True
    assert len(calls) == 2


def test_stalled_cognify_jobs_are_closed(monkeypatch):
    from sqlalchemy.dialects import postgresql

    from app.routers import knowledge_engine

    seen = []

    class _R:
        rowcount = 1

    class _Db:
        committed = False

        async def execute(self, stmt):
            seen.append(str(stmt.compile(dialect=postgresql.dialect())))
            return _R()

        async def commit(self):
            _Db.committed = True

    n = asyncio.run(knowledge_engine.fail_stalled_cognify_jobs(_Db(), T))
    assert n == 2 and _Db.committed
    assert all("UPDATE cognify_jobs SET status=" in q for q in seen)
    assert all(
        "coalesce(cognify_jobs.started_at, cognify_jobs.created_at) <" in q
        for q in seen
    )


def test_a_config_failure_is_dead_lettered_by_the_runtime():
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2] / "apps" / "agent-runtime" / "consumer.py"
    ).read_text(encoding="utf-8")
    branch = src.split("elif _rt_error:", 1)[1].split("await _mark_done(", 1)[0]
    assert "_dlq_after = True" in branch
    assert "if _dlq_after:" in src and "_dead_letter_quietly(" in src


def test_a_config_failure_is_dead_lettered_on_the_inline_path():
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "api"
        / "app"
        / "routers"
        / "agents.py"
    ).read_text(encoding="utf-8")
    branch = src.split("elif _runtime_error:", 1)[1].split(
        "elif _grounding_violation:", 1
    )[0]
    assert "_dlq_after = True" in branch
    tail = src.split("if _dlq_after:", 1)[1][:600]
    assert "dead_letter(" in tail and "reason=str(_runtime_error)" in tail


def test_the_runtime_writes_dead_letters_without_the_api_package():
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    # only packages/db on the path, as in the runtime image
    code = "import dead_letters; print(dead_letters.dead_letter.__name__)"
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root / "packages" / "db",
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(root / "packages" / "db")},
    )
    assert out.stdout.strip() == "dead_letter", out.stderr
    src = (root / "apps" / "agent-runtime" / "consumer.py").read_text(encoding="utf-8")
    assert "from app.services.dlq" not in src
