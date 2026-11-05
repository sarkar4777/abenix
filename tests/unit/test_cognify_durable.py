"""Cognify against real Postgres and Neo4j with the model call faked."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from kb_pg import make_doc, make_kb, make_tenant
from kg_stack import FakeExtractor, cypher_sync


from engine.knowledge import cognify_pipeline as pipeline
from engine.knowledge import cognify_store as store


@pytest.fixture
def world(kg_conn, kg_db_url, graph):
    cur = kg_conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant)
    yield cur, tenant, kb, kg_db_url
    store.dispose_engines()


def _job(cur, tenant, kb, budget=None):
    jid = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO cognify_jobs (id, tenant_id, kb_id, status, budget_usd, documents_processed, "
        "entities_extracted, entities_merged, relationships_extracted, tokens_used, cost_usd, "
        "anthropic_cost, openai_cost, google_cost, other_cost, documents_total, chunks_total, "
        "chunks_processed, chunks_skipped, chunks_failed, entities_written, entities_failed, "
        "relationships_written, relationships_failed, off_ontology_dropped, stop_requested) "
        "VALUES (%s, %s, %s, 'EXTRACTING', %s, 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,false)",
        (jid, tenant, kb, budget),
    )
    return jid


def _ctx(tenant, kb, job, url, extract, **kw):
    ctx = pipeline.build_context(kb, tenant, job, kw.pop("config", {}), url)
    ctx.extract = extract
    ctx.threshold = 0.0
    ctx.batch_chunks = kw.pop("batch_chunks", 2)
    for k, v in kw.items():
        setattr(ctx, k, v)
    return ctx


def _chunks(n, prefix="Org"):
    return [f"{prefix} {i}|{prefix} {i + 1}|text" for i in range(n)]


def _doc(cur, kb, chunks):
    return {"id": make_doc(cur, kb, chunks), "filename": "a.txt", "chunks": chunks}


def _count(uri, kb):
    return cypher_sync(
        uri, "MATCH (e:Entity {kb_id: $kb}) RETURN count(e) AS n", kb=kb
    )[0]["n"]


def _job_row(cur, job):
    cur.execute(
        "SELECT status, cost_usd, chunks_processed, chunks_skipped, chunks_failed, stop_reason, "
        "entities_written, relationships_written FROM cognify_jobs WHERE id = %s",
        (job,),
    )
    return cur.fetchone()


def test_a_crash_loses_no_spend_and_the_rerun_only_pays_for_the_rest(world, neo4j_uri):
    cur, tenant, kb, url = world
    job = _job(cur, tenant, kb)
    doc = _doc(cur, kb, _chunks(10))
    crashing = FakeExtractor(crash_after=4)

    async def run(extract):
        await pipeline.ensure_schema(force=True)
        return await pipeline.cognify_document(_ctx(tenant, kb, job, url, extract), doc)

    with pytest.raises(RuntimeError):
        asyncio.run(run(crashing))
    # two batches had landed before the crash and are in the graph already
    assert _count(neo4j_uri, kb) > 0
    row = _job_row(cur, job)
    assert row[2] == 4 and float(row[1]) == pytest.approx(0.04)

    second = FakeExtractor()
    outcome = asyncio.run(run(second))
    assert sorted(second.seen) == [4, 5, 6, 7, 8, 9]
    assert outcome.chunks_skipped == 4 and outcome.finished
    assert _count(neo4j_uri, kb) == 11

    third = FakeExtractor()
    again = asyncio.run(run(third))
    assert third.calls == 0 and again.chunks_skipped == 10
    assert _count(neo4j_uri, kb) == 11
    mentions = cypher_sync(
        neo4j_uri,
        "MATCH (e:Entity {kb_id: $kb, canonical_name: 'Org 1'}) RETURN e.mention_count AS m",
        kb=kb,
    )[0]["m"]
    assert mentions == 2


def test_extraction_paid_for_before_a_graph_outage_is_replayed_free(
    world, neo4j_uri, monkeypatch
):
    cur, tenant, kb, url = world
    job = _job(cur, tenant, kb)
    doc = _doc(cur, kb, _chunks(2))
    from engine.knowledge.graph_writer import GraphUnavailable

    async def down(*_a, **_k):
        raise GraphUnavailable("connection refused")

    monkeypatch.setattr(pipeline, "write_entities", down)
    first = FakeExtractor()
    with pytest.raises(GraphUnavailable):
        asyncio.run(pipeline.cognify_document(_ctx(tenant, kb, job, url, first), doc))
    assert first.calls == 2
    monkeypatch.undo()
    from engine.knowledge import neo4j_client

    monkeypatch.setattr(neo4j_client, "_NEO4J_URI", neo4j_uri)
    monkeypatch.setattr(neo4j_client, "_NEO4J_USER", "neo4j")
    import os

    from kg_stack import PASSWORD

    monkeypatch.setattr(
        neo4j_client,
        "_NEO4J_PASSWORD",
        os.environ.get("KG_TEST_NEO4J_PASSWORD", PASSWORD),
    )
    second = FakeExtractor()

    async def rerun():
        await pipeline.ensure_schema(force=True)
        return await pipeline.cognify_document(_ctx(tenant, kb, job, url, second), doc)

    outcome = asyncio.run(rerun())
    assert second.calls == 0 and outcome.chunks_done == 2
    assert _count(neo4j_uri, kb) == 3
    cur.execute(
        "SELECT count(*) FROM cognify_chunks WHERE kb_id = %s AND status = 'done' AND result IS NULL",
        (kb,),
    )
    assert cur.fetchone()[0] == 2


def test_a_job_budget_stops_with_a_clear_reason(world, neo4j_uri):
    cur, tenant, kb, url = world
    job = _job(cur, tenant, kb, budget=0.035)
    doc = _doc(cur, kb, _chunks(20))
    extract = FakeExtractor()

    async def run():
        await pipeline.ensure_schema(force=True)
        ctx = _ctx(tenant, kb, job, url, extract)
        return await pipeline.cognify_document(ctx, doc)

    outcome = asyncio.run(run())
    assert outcome.stop_reason == pipeline.STOP_JOB_BUDGET
    row = _job_row(cur, job)
    assert float(row[1]) <= 0.035 and row[5] == pipeline.STOP_JOB_BUDGET
    assert extract.calls < 20
    assert "job budget" in pipeline.stop_message(row[5], 0.035, float(row[1]))


def test_a_failed_chunk_is_counted_and_retried_on_the_next_run(world, neo4j_uri):
    cur, tenant, kb, url = world
    job = _job(cur, tenant, kb)
    doc = _doc(cur, kb, _chunks(4))

    async def run(extract):
        await pipeline.ensure_schema(force=True)
        return await pipeline.cognify_document(_ctx(tenant, kb, job, url, extract), doc)

    outcome = asyncio.run(run(FakeExtractor(fail_indexes={1})))
    assert outcome.chunks_failed == 1 and not outcome.finished
    assert _job_row(cur, job)[4] == 1
    retry = FakeExtractor()
    asyncio.run(run(retry))
    assert retry.seen == [1]


def test_sampling_is_stable_and_salient_prefers_names_and_numbers():
    chunks = [
        f"chunk number {i} with a few plain words in it today" for i in range(200)
    ]
    chunks[7] = "Acme Corp paid Globex Ltd 4,000,000 USD on 2024-03-01 in New York City"
    hashes = [pipeline.chunk_hash(c) for c in chunks]
    sample = pipeline.ChunkSelection(mode="sample", sample_rate=0.25)
    assert sample.pick(chunks, hashes) == sample.pick(chunks, hashes)
    assert 20 < len(sample.pick(chunks, hashes)) < 90
    salient = pipeline.ChunkSelection(mode="salient", sample_rate=0.05)
    picked = salient.pick(chunks, hashes)
    assert 7 in picked and len(picked) == 10
    capped = pipeline.ChunkSelection(max_chunks_per_doc=3)
    assert len(capped.pick(chunks, hashes)) == 3
    assert not capped.covers_everything and pipeline.ChunkSelection().covers_everything


def test_the_default_model_is_cheap_and_the_estimate_shows_the_saving():
    assert pipeline.DEFAULT_COGNIFY_MODEL.startswith("claude-haiku")
    cheap = pipeline.estimate_cost(1000, pipeline.DEFAULT_COGNIFY_MODEL)
    assert cheap < pipeline.estimate_cost(1000, "claude-sonnet-4-5-20250929") / 2


def _run_tasks_inline(monkeypatch, url, extract):
    """Celery's delay runs the task in process, with the fake extractor in place."""
    from worker.tasks import cognify_task as t

    monkeypatch.setattr(t, "_get_db_url", lambda: url)
    monkeypatch.setattr(
        t.run_cognify_document,
        "delay",
        lambda *a, **k: t.run_cognify_document.apply(args=a, kwargs=k),
    )
    monkeypatch.setattr(
        t.finalize_cognify_job,
        "delay",
        lambda *a, **k: t.finalize_cognify_job.apply(args=a, kwargs=k),
    )
    real = pipeline.build_context

    def with_fake(*a, **k):
        ctx = real(*a, **k)
        ctx.extract = extract
        return ctx

    monkeypatch.setattr(pipeline, "build_context", with_fake)
    return t


def _ready_doc(cur, kb, name, chunks):
    return make_doc(cur, kb, chunks, filename=name), chunks


def test_one_task_per_document_ends_complete_and_writes_cognified_at(
    world, neo4j_uri, monkeypatch
):
    cur, tenant, kb, url = world
    extract = FakeExtractor()
    t = _run_tasks_inline(monkeypatch, url, extract)
    texts = {}
    for i in range(3):
        doc, chunks = _ready_doc(cur, kb, f"d{i}.txt", _chunks(3, prefix=f"Co{i}"))
        texts[doc] = chunks
    monkeypatch.setattr(
        t,
        "_load_document",
        lambda d, _k, _c: {"id": d, "filename": "x", "chunks": texts[d]},
    )
    job = _job(cur, tenant, kb, budget=10)
    cur.execute("UPDATE cognify_jobs SET status = 'PENDING' WHERE id = %s", (job,))
    out = t.run_cognify_job.apply(
        kwargs={
            "job_id": job,
            "kb_id": kb,
            "tenant_id": tenant,
            "config": {"kb_resolution": False},
        }
    ).get()
    assert out["documents"] == 3
    row = _job_row(cur, job)
    assert row[0] == "COMPLETE" and row[2] == 9
    assert row[6] > 0 and row[7] == 9
    cur.execute(
        "SELECT count(*) FROM documents WHERE kb_id = %s AND cognified_at IS NOT NULL "
        "AND last_cognify_job_id = %s",
        (kb, job),
    )
    assert cur.fetchone()[0] == 3
    cur.execute(
        "SELECT status, count(*) FROM cognify_job_documents WHERE job_id = %s GROUP BY 1",
        (job,),
    )
    assert cur.fetchall() == [("done", 3)]
    cur.execute(
        "SELECT new_relationships, chunks_analyzed FROM cognify_reports WHERE job_id = %s",
        (job,),
    )
    assert cur.fetchone() == (9, 9)
    cur.execute(
        "SELECT entity_count, relationship_count, graph_enabled FROM knowledge_collections WHERE id = %s",
        (kb,),
    )
    assert cur.fetchone() == (12, 9, True)

    # nothing new means no model call and an honest status
    extract.calls = 0
    rerun = _job(cur, tenant, kb, budget=10)
    t.run_cognify_job.apply(
        kwargs={"job_id": rerun, "kb_id": kb, "tenant_id": tenant, "config": {}}
    ).get()
    row = _job_row(cur, rerun)
    assert row[0] == "COMPLETE" and row[5] == "up_to_date" and extract.calls == 0


def test_a_budget_stop_closes_the_job_as_stopped_with_the_message(
    world, neo4j_uri, monkeypatch
):
    cur, tenant, kb, url = world
    extract = FakeExtractor()
    t = _run_tasks_inline(monkeypatch, url, extract)
    texts = {}
    for i in range(3):
        doc, chunks = _ready_doc(cur, kb, f"d{i}.txt", _chunks(10, prefix=f"Co{i}"))
        texts[doc] = chunks
    monkeypatch.setattr(
        t,
        "_load_document",
        lambda d, _k, _c: {"id": d, "filename": "x", "chunks": texts[d]},
    )
    job = _job(cur, tenant, kb, budget=0.25)
    t.run_cognify_job.apply(
        kwargs={
            "job_id": job,
            "kb_id": kb,
            "tenant_id": tenant,
            "config": {"kb_resolution": False},
        }
    ).get()
    cur.execute(
        "SELECT status, stop_reason, error_message, cost_usd FROM cognify_jobs WHERE id = %s",
        (job,),
    )
    status, reason, message, cost = cur.fetchone()
    assert status == "STOPPED" and reason == "job_budget"
    assert "job budget of $0.25" in message and float(cost) <= 0.25
    cur.execute(
        "SELECT count(*) FROM documents WHERE kb_id = %s AND cognified_at IS NOT NULL",
        (kb,),
    )
    assert cur.fetchone()[0] < 3


def test_a_time_slice_hands_the_document_back_and_counts_totals_once(
    world, neo4j_uri, monkeypatch
):
    cur, tenant, kb, url = world
    extract = FakeExtractor()
    t = _run_tasks_inline(monkeypatch, url, extract)
    doc, chunks = _ready_doc(cur, kb, "big.txt", _chunks(6))
    monkeypatch.setattr(
        t,
        "_load_document",
        lambda d, _k, _c: {"id": d, "filename": "x", "chunks": chunks},
    )
    requeued = []
    monkeypatch.setattr(t, "TIME_SLICE_S", -1.0)

    monkeypatch.setattr(t, "_requeue", lambda args, kwargs=None: requeued.append(args))
    job = _job(cur, tenant, kb, budget=10)
    cur.execute(
        "INSERT INTO cognify_job_documents (job_id, document_id, status) VALUES (%s, %s, 'queued')",
        (job, doc),
    )
    out = t.run_cognify_document.apply(args=[job, kb, tenant, doc, {}]).get()
    assert out["status"] == "continuing" and requeued and extract.calls == 0
    cur.execute("SELECT status FROM cognify_job_documents WHERE job_id = %s", (job,))
    assert cur.fetchone()[0] == "queued"
    monkeypatch.setattr(t, "TIME_SLICE_S", 600.0)
    out = t.run_cognify_document.apply(args=[job, kb, tenant, doc, {}]).get()
    assert out["status"] == "done" and extract.calls == 6
    cur.execute("SELECT chunks_total FROM cognify_jobs WHERE id = %s", (job,))
    assert cur.fetchone()[0] == 6


def test_rerun_keeps_source_doc_ids_and_aliases_for_graph_acls(world, neo4j_uri):
    cur, tenant, kb, url = world
    job = _job(cur, tenant, kb)
    doc_a = _doc(cur, kb, ["Shared|Only A|text"])
    doc_b = _doc(cur, kb, ["Shared|Only B|text"])

    async def run():
        await pipeline.ensure_schema(force=True)
        ctx = _ctx(tenant, kb, job, url, FakeExtractor())
        await pipeline.cognify_document(ctx, doc_a)
        await pipeline.cognify_document(ctx, doc_b)

    asyncio.run(run())
    docs = cypher_sync(
        neo4j_uri,
        "MATCH (e:Entity {kb_id: $kb, canonical_name: 'Shared'}) RETURN e.source_doc_ids AS d, e.tenant_id AS t",
        kb=kb,
    )[0]
    assert set(docs["d"]) == {doc_a["id"], doc_b["id"]} and docs["t"] == tenant
    cur.execute(
        "SELECT source_doc_ids FROM graph_entities WHERE kb_id = %s AND canonical_name = 'Shared'",
        (kb,),
    )
    assert set(cur.fetchone()[0]) == {doc_a["id"], doc_b["id"]}


def test_old_job_config_without_a_row_still_runs_inline(world, neo4j_uri, monkeypatch):
    cur, tenant, kb, url = world
    monkeypatch.setattr(pipeline, "extract_chunks", FakeExtractor())
    real = pipeline.build_context

    def fake(*a, **k):
        ctx = real(*a, **k)
        ctx.extract = FakeExtractor()
        ctx.threshold = 0.0
        return ctx

    monkeypatch.setattr(pipeline, "build_context", fake)
    doc = _doc(cur, kb, _chunks(3))
    result = asyncio.run(
        pipeline.run_cognify(kb, tenant, str(uuid.uuid4()), [doc], {}, url)
    )
    assert result.status == "complete"
    assert result.chunks_analyzed == 3 and result.relationships_written == 3
    cur.execute("SELECT cognified_at FROM documents WHERE id = %s", (doc["id"],))
    assert cur.fetchone()[0] is not None


def test_a_namespace_collection_or_a_missing_driver_still_writes_the_graph(monkeypatch):
    assert store.usable_url("postgresql://x/y", "user-123") == ""
    assert store.usable_url("", str(uuid.uuid4())) == ""
    real = "postgresql+asyncpg://u:p@h/d?ssl=disable"
    kb = str(uuid.uuid4())
    assert store.usable_url(real, kb) == real
    assert store.sync_url(real) == "postgresql+psycopg2://u:p@h/d"
    import builtins

    original = builtins.__import__

    def no_driver(name, *a, **k):
        if name == "psycopg2":
            raise ImportError(name)
        return original(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_driver)
    assert store.usable_url(real, kb) == ""
