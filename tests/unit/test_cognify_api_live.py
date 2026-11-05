"""The Cognify routes against real Postgres, with the queue replaced."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from atlas_live import _async_url, client, make_user
from fastapi import FastAPI
from kb_pg import make_doc, make_kb, make_tenant


class _Queue:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send_task(self, name, kwargs=None, queue=None):
        if self.fail:
            raise ConnectionError("redis is away")
        self.sent.append((name, kwargs, queue))


@pytest.fixture
def api(kg_conn, kg_db_url, monkeypatch):
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import NullPool

    from app.core.deps import get_current_user, get_db
    from app.routers import knowledge_engine as ke

    cur = kg_conn.cursor()
    tenant = make_tenant(cur)
    user = make_user(cur, tenant)
    kb = make_kb(cur, tenant, created_by=str(user.id))
    engine = create_async_engine(_async_url(kg_db_url), poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def db():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(ke.router)
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: user
    queue = _Queue()
    monkeypatch.setattr(ke, "_dispatcher", lambda: queue)

    class Env:
        pass

    env = Env()
    env.cur, env.kb, env.tenant, env.app, env.queue, env.user = (
        cur,
        kb,
        tenant,
        app,
        queue,
        user,
    )
    return env


def _call(env, method, path, **kw):
    async def go():
        async with client(env.app) as http:
            return await http.request(method, path, **kw)

    return asyncio.run(go())


def test_a_run_goes_to_the_queue_with_a_budget_and_the_cheap_model(api):
    make_doc(api.cur, api.kb, ["a", "b"])
    r = _call(api, "POST", f"/api/knowledge-engines/{api.kb}/cognify", json={})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["documents"] == 1 and data["model"].startswith("claude-haiku")
    assert data["max_cost_usd"] > 0
    name, kwargs, queue = api.queue.sent[0]
    assert name.endswith("run_cognify_job") and queue == "cognify"
    assert (
        kwargs["doc_ids"] is None
    ), "the worker pages the documents, the message stays small"
    api.cur.execute(
        "SELECT status, budget_usd FROM cognify_jobs WHERE id = %s", (data["job_id"],)
    )
    status, budget = api.cur.fetchone()
    assert status == "PENDING" and float(budget) == data["max_cost_usd"]


def test_dry_run_costs_nothing_and_shows_the_sampling_saving(api):
    make_doc(api.cur, api.kb, ["x"] * 1000)
    full = _call(
        api, "POST", f"/api/knowledge-engines/{api.kb}/cognify", json={"dry_run": True}
    ).json()["data"]
    part = _call(
        api,
        "POST",
        f"/api/knowledge-engines/{api.kb}/cognify",
        json={"dry_run": True, "selection": "salient", "sample_rate": 0.1},
    ).json()["data"]
    assert api.queue.sent == []
    api.cur.execute("SELECT count(*) FROM cognify_jobs WHERE kb_id = %s", (api.kb,))
    assert api.cur.fetchone()[0] == 0
    assert full["chunks"] == 1000 and part["chunks"] == 100
    assert part["estimated_usd"] < full["estimated_usd"] and full["estimated_usd"] > 0


def test_a_second_run_on_the_same_collection_is_refused_while_one_is_live(api):
    make_doc(api.cur, api.kb, ["a"])
    first = _call(api, "POST", f"/api/knowledge-engines/{api.kb}/cognify", json={})
    second = _call(api, "POST", f"/api/knowledge-engines/{api.kb}/cognify", json={})
    assert first.status_code == 200 and second.status_code == 409
    assert "already running" in second.text


def test_a_dead_queue_fails_the_job_and_says_so(api, monkeypatch):
    from app.routers import knowledge_engine as ke

    make_doc(api.cur, api.kb, ["a"])
    monkeypatch.setattr(ke, "_dispatcher", lambda: _Queue(fail=True))
    r = _call(api, "POST", f"/api/knowledge-engines/{api.kb}/cognify", json={})
    assert r.status_code == 503 and "queue is not reachable" in r.text
    api.cur.execute("SELECT status FROM cognify_jobs WHERE kb_id = %s", (api.kb,))
    assert api.cur.fetchone()[0] == "FAILED"


def test_stop_marks_the_job_and_the_job_list_shows_progress(api):
    make_doc(api.cur, api.kb, ["a"])
    job = _call(
        api, "POST", f"/api/knowledge-engines/{api.kb}/cognify", json={}
    ).json()["data"]["job_id"]
    r = _call(api, "POST", f"/api/knowledge-engines/{api.kb}/cognify/{job}/stop")
    assert r.status_code == 200
    jobs = _call(api, "GET", f"/api/knowledge-engines/{api.kb}/cognify-jobs").json()[
        "data"
    ]
    assert jobs[0]["stop_requested"] and jobs[0]["stop_reason"] == "user_requested"
    assert {
        "chunks_total",
        "chunks_skipped",
        "relationships_failed",
        "budget_usd",
    } <= set(jobs[0])
    other = _call(
        api, "POST", f"/api/knowledge-engines/{api.kb}/cognify/{uuid.uuid4()}/stop"
    )
    assert other.status_code == 404


def test_a_long_job_with_a_recent_heartbeat_is_not_called_stalled(api):
    make_doc(api.cur, api.kb, ["a"])
    job = _call(
        api, "POST", f"/api/knowledge-engines/{api.kb}/cognify", json={}
    ).json()["data"]["job_id"]
    api.cur.execute(
        "UPDATE cognify_jobs SET status = 'EXTRACTING', started_at = now() - interval '3 days', "
        "heartbeat_at = now() WHERE id = %s",
        (job,),
    )
    jobs = _call(api, "GET", f"/api/knowledge-engines/{api.kb}/cognify-jobs").json()[
        "data"
    ]
    assert jobs[0]["status"] == "extracting"
    api.cur.execute(
        "UPDATE cognify_jobs SET heartbeat_at = now() - interval '7 hours' WHERE id = %s",
        (job,),
    )
    jobs = _call(api, "GET", f"/api/knowledge-engines/{api.kb}/cognify-jobs").json()[
        "data"
    ]
    assert jobs[0]["status"] == "failed"


def test_delete_graph_queues_neo4j_and_clears_the_mirror(api):
    doc = make_doc(api.cur, api.kb, ["a"])
    api.cur.execute("UPDATE documents SET cognified_at = now() WHERE id = %s", (doc,))
    api.cur.execute(
        "INSERT INTO cognify_chunks (kb_id, document_id, chunk_hash) VALUES (%s, %s, 'h')",
        (api.kb, doc),
    )
    api.cur.execute(
        "INSERT INTO graph_entities (id, tenant_id, kb_id, canonical_name, entity_type, mention_count, access_count, confidence) "
        "VALUES (gen_random_uuid(), %s, %s, 'X', 'org', 1, 0, 1)",
        (api.tenant, api.kb),
    )
    r = _call(api, "DELETE", f"/api/knowledge-engines/{api.kb}/graph")
    assert r.status_code == 200, r.text
    assert api.queue.sent[0][0].endswith("delete_kb_graph") and api.queue.sent[0][
        1
    ] == {"kb_id": api.kb}
    for sql in (
        "SELECT count(*) FROM graph_entities WHERE kb_id = %s",
        "SELECT count(*) FROM cognify_chunks WHERE kb_id = %s",
        "SELECT count(*) FROM documents WHERE kb_id = %s AND cognified_at IS NOT NULL",
    ):
        api.cur.execute(sql, (api.kb,))
        assert api.cur.fetchone()[0] == 0
