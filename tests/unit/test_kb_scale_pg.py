"""Ingest and search of large collections against real Postgres and pgvector."""

from __future__ import annotations

import asyncio
import os
import random
import re
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import kb_pg
from kb_pg import make_kb, make_tenant
from sqlalchemy import create_engine, text

from engine.knowledge import document_acl
from engine.knowledge import hybrid_search as hs
from worker.tasks import document_processor as dp
from worker.tasks import kb_index

ROOT = Path(__file__).resolve().parents[2]
DIM = 1536


def _vec(seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0, 1) for _ in range(DIM)]


def _literal(values: list[float]) -> str:
    return "[" + ",".join(f"{x:.5f}" for x in values) + "]"


@pytest.fixture(scope="module")
def server_url():
    if os.environ.get("KB_SCALE_TEST_URL"):
        yield os.environ["KB_SCALE_TEST_URL"]
        return
    if not kb_pg.docker_works():
        pytest.skip("docker is not available")
    name = f"abenix-kbscale-test-{uuid.uuid4().hex[:8]}"
    port = kb_pg.free_port()
    kb_pg.run_postgres(name, port)
    url = f"postgresql://postgres:test@127.0.0.1:{port}/abenix"
    try:
        kb_pg.wait_for_postgres(url)
        yield url
    finally:
        subprocess.run([kb_pg.docker(), "rm", "-f", name], capture_output=True)


def _base_schema(server_url: str, prefix: str):
    """A new database through the fresh install path, up to the raw chunks table."""
    import psycopg2

    sys.path.insert(0, str(ROOT / "packages" / "db"))
    import models  # noqa: F401
    from bootstrap import _create_missing_enums_sync
    from models.base import Base

    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    admin = psycopg2.connect(server_url)
    admin.autocommit = True
    admin.cursor().execute(f"CREATE DATABASE {name}")
    admin.close()
    url = server_url.rsplit("/", 1)[0] + f"/{name}"
    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://"))
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        _create_missing_enums_sync(conn)
        Base.metadata.create_all(bind=conn)
    return url, engine


@pytest.fixture(scope="module")
def part_url(server_url):
    sys.path.insert(0, str(ROOT / "packages" / "db"))
    import chunks_store as cs

    url, engine = _base_schema(server_url, "part")
    with engine.begin() as conn:
        for stmt in cs.startup_plan(None, "0.8.0"):
            conn.execute(text(stmt))
        kind = conn.execute(text(cs.STATE_SQL)).first()
        conn.execute(text(cs.hnsw_plan(kind[0], kind[1])))
    engine.dispose()
    return url


@pytest.fixture
def db(part_url, monkeypatch):
    import psycopg2

    monkeypatch.setenv("DATABASE_URL", part_url)
    hs._STORE_FACTS.clear()
    conn = psycopg2.connect(part_url)
    conn.autocommit = True
    yield conn.cursor()
    conn.close()


def _doc(cur, kb, filename="f.txt", current=True) -> str:
    doc = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO documents (id, kb_id, filename, file_type, file_size, chunk_count, "
        "status, storage_url, version_number, is_current) VALUES "
        "(%s, %s, %s, 'txt', 1, 0, 'PROCESSING', '', 1, %s)",
        (doc, kb, filename, current),
    )
    return doc


def _fill(cur, kb, doc, rows: int, seed: int = 0, dedicated: bool = False) -> None:
    import io

    lines = io.StringIO()
    for i in range(rows):
        lines.write(
            f"{uuid.uuid4()}\t{kb}\t{doc}\t{i}\tchunk {i}\t"
            f'{{"filename": "f.txt"}}\t{_literal(_vec(seed + i))}\t'
            f"{'t' if dedicated else 'f'}\t0\n"
        )
    lines.seek(0)
    cur.copy_expert(
        "COPY chunks (id, collection_id, document_id, chunk_index, content, metadata, "
        "embedding, dedicated_index, embedding_generation) FROM STDIN",
        lines,
    )


def _search(monkeypatch, query_vec, kb_ids, top_k=10, hidden=frozenset()):
    async def fake_embed(query, model=None):
        return query_vec

    monkeypatch.setattr(hs, "_embed_query", fake_embed)

    async def go():
        from engine import db_pool

        try:
            return await hs._vector_search_pgvector("q", kb_ids, top_k, None, hidden)
        finally:
            await db_pool.dispose_all() if hasattr(db_pool, "dispose_all") else None

    return asyncio.run(go())


def _ingest_stubs(monkeypatch, tmp_text, embed):
    monkeypatch.setattr(dp, "_embed_chunks", embed)
    monkeypatch.setattr(dp, "_local_path", lambda p, t: (tmp_text, None))
    monkeypatch.setattr(dp, "_quota_refusal", lambda *a: None)
    monkeypatch.setattr(dp, "_record_embedding_spend", lambda *a: None)
    requeued = []
    monkeypatch.setattr(dp.process_document, "update_state", lambda **k: None)
    monkeypatch.setattr(
        dp.process_document, "apply_async", lambda **kw: requeued.append(kw)
    )
    monkeypatch.setattr(dp, "EMBED_CONCURRENCY", 2)
    return requeued


def _run_task(doc, kb, **kw):
    dp.process_document.push_request(retries=0)
    try:
        return dp.process_document.run(doc, kb, "/x", "big.txt", "txt", 200, 20, **kw)
    finally:
        dp.process_document.pop_request()


def _doc_row(cur, doc):
    cur.execute(
        "SELECT status::text, chunk_count, ingest_checkpoint, ingest_attempts, "
        "error_message FROM documents WHERE id = %s",
        (doc,),
    )
    return cur.fetchone()


def test_a_crash_midway_resumes_without_paying_for_stored_batches(
    db, monkeypatch, tmp_path
):
    tenant = make_tenant(db)
    kb = make_kb(db, tenant, model="m")
    doc = _doc(db, kb)
    source = tmp_path / "big.txt"
    source.write_text("\n\n".join(f"paragraph number {i} " * 3 for i in range(2000)))
    embedded: list[str] = []
    blow_after = [3]

    def flaky(chunks, model=None, strict=False):
        if blow_after[0] == 0:
            raise MemoryError("killed")
        blow_after[0] -= 1
        embedded.extend(chunks)
        return [_vec(1)[:DIM] for _ in chunks], True

    _ingest_stubs(monkeypatch, str(source), flaky)
    monkeypatch.setattr(dp.process_document, "retry", lambda exc=None, **k: exc)
    with pytest.raises(MemoryError):
        _run_task(doc, kb)
    status, _count, checkpoint, _a, _e = _doc_row(db, doc)
    assert status == "PROCESSING"
    assert checkpoint >= dp.BATCH_CHUNKS

    first_run = list(embedded)
    embedded.clear()
    blow_after[0] = 10**9
    out = _run_task(doc, kb)
    assert out["status"] == "ready"
    status, count, checkpoint, attempts, error = _doc_row(db, doc)
    assert status == "READY" and error is None
    assert checkpoint == count
    # everything stored before the crash was not embedded again
    assert len(embedded) <= count - dp.BATCH_CHUNKS
    db.execute(
        "SELECT count(*), count(DISTINCT chunk_index), max(chunk_index) FROM chunks "
        "WHERE document_id = %s",
        (doc,),
    )
    rows, distinct, highest = db.fetchone()
    assert rows == distinct == count and highest == count - 1
    db.execute(
        "SELECT content FROM chunks WHERE document_id = %s AND chunk_index = 0", (doc,)
    )
    assert db.fetchone()[0] == first_run[0]


def test_a_worker_killed_every_time_ends_failed_and_says_why(db, monkeypatch, tmp_path):
    tenant = make_tenant(db)
    kb = make_kb(db, tenant, model="m")
    doc = _doc(db, kb)
    source = tmp_path / "big.txt"
    source.write_text("hello world")
    _ingest_stubs(
        monkeypatch,
        str(source),
        lambda c, m=None, strict=False: pytest.fail("no embed"),
    )
    # what a redelivery after the kernel killed the child looks like
    db.execute(
        "UPDATE documents SET ingest_attempts = %s WHERE id = %s",
        (dp.MAX_ATTEMPTS, doc),
    )
    out = _run_task(doc, kb)
    assert out["status"] == "failed"
    status, _c, _k, _a, error = _doc_row(db, doc)
    assert status == "FAILED"
    assert "out of memory" in error
    # and a later redelivery does nothing
    assert _run_task(doc, kb)["status"] == "skipped"


def test_a_finished_document_redelivered_is_not_processed_again(
    db, monkeypatch, tmp_path
):
    tenant = make_tenant(db)
    kb = make_kb(db, tenant, model="m")
    doc = _doc(db, kb)
    source = tmp_path / "big.txt"
    source.write_text("hello world, " * 200)
    calls = []

    def embed(chunks, model=None, strict=False):
        calls.append(len(chunks))
        return [_vec(2) for _ in chunks], True

    _ingest_stubs(monkeypatch, str(source), embed)
    assert _run_task(doc, kb)["status"] == "ready"
    done = sum(calls)
    assert _run_task(doc, kb)["status"] == "skipped"
    assert sum(calls) == done


def test_a_flip_mid_ingest_restarts_at_the_new_generation(db, monkeypatch, tmp_path):
    tenant = make_tenant(db)
    kb = make_kb(db, tenant, model="m")
    doc = _doc(db, kb)
    source = tmp_path / "big.txt"
    source.write_text("\n\n".join(f"paragraph number {i} " * 3 for i in range(2000)))

    def embed(chunks, model=None, strict=False):
        db.execute(
            "UPDATE knowledge_collections SET embedding_generation = 1 WHERE id = %s",
            (kb,),
        )
        return [_vec(3) for _ in chunks], True

    requeued = _ingest_stubs(monkeypatch, str(source), embed)
    out = _run_task(doc, kb)
    assert out["status"] == "restarted"
    assert requeued[0]["kwargs"]["strict"] is True

    monkeypatch.setattr(
        dp,
        "_embed_chunks",
        lambda c, m=None, strict=False: ([_vec(4) for _ in c], True),
    )
    assert _run_task(doc, kb, strict=True)["status"] == "ready"
    db.execute(
        "SELECT DISTINCT embedding_generation FROM chunks WHERE document_id = %s",
        (doc,),
    )
    assert [r[0] for r in db.fetchall()] == [1]


def test_copy_survives_tabs_backslashes_newlines_and_nul(db, monkeypatch, tmp_path):
    tenant = make_tenant(db)
    kb = make_kb(db, tenant, model="m")
    doc = _doc(db, kb)
    awkward = "tab\there\\back\nnew\rcr\x00nul 'q' \"d\""
    dp._store_vectors_pgvector(
        kb, doc, 'na"me\\.txt', [awkward], [_vec(5)], [7], generation=0, start=40
    )
    db.execute(
        "SELECT chunk_index, content, metadata FROM chunks WHERE document_id = %s",
        (doc,),
    )
    index, content, meta = db.fetchone()
    assert index == 40
    assert content == awkward.replace("\x00", "")
    assert meta["filename"] == 'na"me\\.txt' and meta["page"] == 7
    assert meta["chunk_index"] == 40
    assert _doc_row(db, doc)[2] == 41


def test_new_install_table_is_hash_partitioned_and_a_query_touches_one_partition(db):
    db.execute(
        "SELECT c.relkind::text, count(i.inhrelid) FROM pg_class c "
        "LEFT JOIN pg_inherits i ON i.inhparent = c.oid "
        "WHERE c.oid = 'chunks'::regclass GROUP BY 1"
    )
    assert db.fetchone() == ("p", 32)
    kb = str(uuid.uuid4())
    db.execute(f"EXPLAIN SELECT 1 FROM chunks WHERE collection_id = '{kb}'")
    plan = " ".join(r[0] for r in db.fetchall())
    assert len(set(re.findall(r"chunks_p\d+", plan))) == 1


def test_a_small_collection_behind_a_big_neighbour_still_finds_everything(
    db, monkeypatch
):
    tenant = make_tenant(db)
    # the big collection and the small one share a partition, that is the failure case
    big = make_kb(db, tenant, model="m")
    target = None
    while target is None:
        small = make_kb(db, tenant, model="m")
        db.execute(
            "SELECT satisfies_hash_partition('chunks'::regclass, 32, r, %s::uuid), "
            "satisfies_hash_partition('chunks'::regclass, 32, r, %s::uuid) "
            "FROM generate_series(0, 31) r",
            (big, small),
        )
        if any(a and b for a, b in db.fetchall()):
            target = small
    big_doc = _doc(db, big)
    small_doc = _doc(db, target)
    _fill(db, big, big_doc, 3000, seed=1000)
    _fill(db, target, small_doc, 7, seed=9000)
    db.execute("ANALYZE chunks")
    out = _search(monkeypatch, _vec(9003), [target], top_k=5)
    assert len(out) == 5
    assert out[0].metadata["chunk_index"] == 3
    assert {r.metadata["kb_id"] for r in out} == {target}


def _near(seed: int, center: list[float], spread: float = 0.05) -> list[float]:
    rng = random.Random(seed)
    return [c + rng.gauss(0, spread) for c in center]


def _load(cur, kb, doc, vectors, start=0) -> None:
    import io

    lines = io.StringIO()
    for offset, values in enumerate(vectors):
        lines.write(
            f"{uuid.uuid4()}\t{kb}\t{doc}\t{start + offset}\tchunk\t"
            f'{{"filename": "f"}}\t{_literal(values)}\tf\t0\n'
        )
    lines.seek(0)
    cur.copy_expert(
        "COPY chunks (id, collection_id, document_id, chunk_index, content, metadata, "
        "embedding, dedicated_index, embedding_generation) FROM STDIN",
        lines,
    )


_CROWDED: dict[str, tuple] = {}


def _crowded_shared(cur, url: str) -> tuple:
    """Inserting through HNSW is the slow part, so the partitioned shape is built once."""
    if url not in _CROWDED:
        _CROWDED[url] = _crowded_index(cur, _same_partition_maker(cur))
    return _CROWDED[url]


def _crowded_index(cur, make_same_partition=None):
    """A large collection far from the query and a small one right on top of it."""
    tenant = make_tenant(cur)
    big = make_kb(cur, tenant, model="m")
    small = make_kb(cur, tenant, model="m")
    if make_same_partition:
        small = make_same_partition(tenant, big)
    big_doc, hidden_doc = _doc(cur, big), _doc(cur, big)
    center = _vec(123)
    _load(cur, big, big_doc, [_vec(1000 + i) for i in range(2500)])
    _load(cur, big, hidden_doc, [_vec(5000 + i) for i in range(500)])
    _load(cur, small, _doc(cur, small), [_near(9000 + i, center) for i in range(800)])
    cur.execute("ANALYZE chunks")
    return tenant, big, small, big_doc, hidden_doc, center


def _old_query_count(cur, kb, vector, k=10) -> int:
    """The query this replaced, with the planner held to the index as a large share gets it."""
    cur.execute("BEGIN")
    cur.execute("SET LOCAL enable_sort = off")
    cur.execute("SET LOCAL enable_seqscan = off")
    cur.execute(
        "SELECT id FROM chunks WHERE collection_id = ANY(%s::uuid[]) "
        "AND NOT dedicated_index ORDER BY embedding <=> %s::vector LIMIT %s",
        ([kb], _literal(vector), k),
    )
    count = len(cur.fetchall())
    cur.execute("ROLLBACK")
    return count


def _same_partition_maker(cur):
    def make(tenant, big):
        while True:
            kb = make_kb(cur, tenant, model="m")
            cur.execute(
                "SELECT bool_or(satisfies_hash_partition('chunks'::regclass, 32, r, "
                "%s::uuid) AND satisfies_hash_partition('chunks'::regclass, 32, r, "
                "%s::uuid)) FROM generate_series(0, 31) r",
                (big, kb),
            )
            if cur.fetchone()[0]:
                return kb

    return make


def _assert_crowded_shape_returns_pages(
    cur, monkeypatch, big, small, big_doc, hidden_doc, center
):
    # on this few rows the planner would sort instead, at real sizes it takes the index
    cur.execute("SELECT current_database()")
    database = cur.fetchone()[0]
    cur.execute(f"ALTER DATABASE {database} SET enable_seqscan = off")
    cur.execute(f"ALTER DATABASE {database} SET enable_sort = off")
    try:
        _crowded_pages(cur, monkeypatch, big, small, big_doc, hidden_doc, center)
    finally:
        cur.execute(f"ALTER DATABASE {database} RESET enable_seqscan")
        cur.execute(f"ALTER DATABASE {database} RESET enable_sort")


def _crowded_pages(cur, monkeypatch, big, small, big_doc, hidden_doc, center):
    monkeypatch.setenv("KB_EXACT_SCAN_MAX_CHUNKS", "200")
    # the live failure, the index offers only the near neighbours of the other collection
    assert _old_query_count(cur, big, center) < 10
    query = _near(77, center)
    for k in (10, 50):
        found = _search(monkeypatch, query, [big], top_k=k)
        assert len(found) == k
        assert {r.metadata["kb_id"] for r in found} == {big}
    # a full page of the wrong rows would be no better
    cur.execute(
        "WITH c AS MATERIALIZED (SELECT document_id, chunk_index, embedding FROM chunks "
        "WHERE collection_id = %s) SELECT document_id::text, chunk_index FROM c "
        "ORDER BY embedding <=> %s::vector LIMIT 50",
        (big, _literal(query)),
    )
    best = {tuple(r) for r in cur.fetchall()}
    got = {(r.metadata["doc_id"], r.metadata["chunk_index"]) for r in found}
    assert len(best & got) >= 35
    # hidden documents in the mix do not shorten the page
    found = _search(monkeypatch, query, [big], top_k=30, hidden={hidden_doc})
    assert len(found) == 30 and {r.metadata["doc_id"] for r in found} == {big_doc}
    # the small collection is right there, and both together rank properly
    assert len(_search(monkeypatch, query, [small], top_k=10)) == 10
    both = _search(monkeypatch, query, [big, small], top_k=10)
    assert len(both) == 10 and {r.metadata["kb_id"] for r in both} == {small}


def test_crowded_shared_partition_returns_a_full_page(db, part_url, monkeypatch):
    shape = _crowded_shared(db, part_url)
    _tenant, big, small, big_doc, hidden_doc, center = shape
    _assert_crowded_shape_returns_pages(
        db, monkeypatch, big, small, big_doc, hidden_doc, center
    )


def test_crowded_legacy_global_index_returns_a_full_page(server_url, monkeypatch):
    import psycopg2

    from chunks_schema import startup_statements
    import chunks_store as cs

    url, engine = _base_schema(server_url, "crowd")
    with engine.begin() as conn:
        for stmt in [*startup_statements(), cs.DEDICATED_COLUMN]:
            conn.execute(text(stmt))
        conn.execute(
            text(
                "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
                "USING hnsw (embedding vector_cosine_ops)"
            )
        )
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", url)
    hs._STORE_FACTS.clear()
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    _tenant, big, small, big_doc, hidden_doc, center = _crowded_index(cur)
    _assert_crowded_shape_returns_pages(
        cur, monkeypatch, big, small, big_doc, hidden_doc, center
    )
    conn.close()


def test_deep_scan_rescues_a_starved_first_pass(db, part_url, monkeypatch):
    shape = _crowded_shared(db, part_url)
    _tenant, big, _small, _big_doc, _hidden, center = shape
    monkeypatch.setenv("KB_EXACT_SCAN_MAX_CHUNKS", "200")
    monkeypatch.setenv("KB_HNSW_MAX_SCAN_TUPLES", "50")
    real_exact = hs._exact_scan

    async def no_exact(*a, **k):
        if k.get("timeout"):
            raise AssertionError("the deeper index pass should have been enough")
        return await real_exact(*a, **k)

    if hs_version_is_iterative(db):
        monkeypatch.setattr(hs, "_exact_scan", no_exact)
    found = _search(monkeypatch, _near(78, center), [big], top_k=10)
    assert len(found) == 10


def hs_version_is_iterative(cur) -> bool:
    cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    version = cur.fetchone()[0]
    return tuple(int(p) for p in version.split(".")[:2]) >= (0, 8)


def test_a_page_that_stays_short_says_so_and_is_not_cached(db, part_url, monkeypatch):
    shape = _crowded_shared(db, part_url)
    _tenant, big, _small, _big_doc, _hidden, center = shape
    monkeypatch.setenv("KB_EXACT_SCAN_MAX_CHUNKS", "200")

    async def starved(*a, **k):
        return [("i", big, "d", 0, "one row", {"filename": "f"}, 0.5)]

    async def timed_out(*a, **k):
        return None

    monkeypatch.setattr(hs, "_hnsw_scan", starved)
    monkeypatch.setattr(hs, "_exact_scan", timed_out)

    async def fake_embed(query, model=None):
        return center

    monkeypatch.setattr(hs, "_embed_query", fake_embed)
    monkeypatch.setattr(hs, "is_neo4j_available", AsyncMock(return_value=False))
    stored = AsyncMock()
    from engine.knowledge import search_cache

    monkeypatch.setattr(search_cache, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(search_cache, "set", stored)

    answer = asyncio.run(
        hs.hybrid_search("q", [big], mode=hs.SearchMode.VECTOR, tenant_id="t")
    )
    assert len(answer.results) == 1
    assert "Only 1 of" in answer.degraded and "incomplete" in answer.degraded
    stored.assert_not_called()


def test_a_small_collection_is_exact_and_never_asks_hnsw(db, monkeypatch):
    tenant = make_tenant(db)
    kb = make_kb(db, tenant, model="m")
    _fill(db, kb, _doc(db, kb), 30, seed=70000)

    async def no_hnsw(*a, **k):
        raise AssertionError("a small collection went to the index")

    monkeypatch.setattr(hs, "_hnsw_scan", no_hnsw)
    out = _search(monkeypatch, _vec(70004), [kb], top_k=30)
    assert len(out) == 30 and out[0].metadata["chunk_index"] == 4


def test_when_the_index_comes_back_short_the_exact_scan_fills_the_page(db, monkeypatch):
    monkeypatch.setenv("KB_EXACT_SCAN_MAX_CHUNKS", "5")
    tenant = make_tenant(db)
    kb = make_kb(db, tenant, model="m")
    _fill(db, kb, _doc(db, kb), 40, seed=80000)

    async def starved(*a, **k):
        return []

    monkeypatch.setattr(hs, "_hnsw_scan", starved)
    out = _search(monkeypatch, _vec(80007), [kb], top_k=10)
    assert len(out) == 10 and out[0].metadata["chunk_index"] == 7


def test_above_the_exact_limit_a_filtered_scan_still_fills_the_page(db, monkeypatch):
    monkeypatch.setenv("KB_EXACT_SCAN_MAX_CHUNKS", "50")
    tenant = make_tenant(db)
    kb = make_kb(db, tenant, model="m")
    doc = _doc(db, kb)
    hidden_doc = _doc(db, kb)
    _fill(db, kb, doc, 200, seed=20000)
    _fill(db, kb, hidden_doc, 200, seed=20000)
    db.execute("ANALYZE chunks")
    out = _search(monkeypatch, _vec(20010), [kb], top_k=10, hidden={hidden_doc})
    assert len(out) == 10
    assert {r.metadata["doc_id"] for r in out} == {doc}


def test_acl_over_the_cap_sends_a_bounded_list_and_still_hides_everything(
    db, monkeypatch
):
    monkeypatch.setenv("KB_HIDDEN_INLINE_MAX", "5")
    monkeypatch.setenv("KB_EXACT_SCAN_MAX_CHUNKS", "100000")
    tenant = make_tenant(db)
    kb = make_kb(db, tenant, model="m")
    open_doc = _doc(db, kb)
    _fill(db, kb, open_doc, 3, seed=30000)
    subject = uuid.uuid4()
    restricted = []
    for n in range(12):
        d = _doc(db, kb)
        restricted.append(d)
        _fill(db, kb, d, 1, seed=30000)
        db.execute(
            "INSERT INTO document_grants (id, document_id, tenant_id, subject_type, "
            "subject_id, permission) VALUES (%s, %s, %s, 'user', %s, 'read')",
            (str(uuid.uuid4()), d, tenant, str(uuid.uuid4())),
        )

    async def lookups():
        from engine import db_pool

        try:
            r = await document_acl.hidden_for_search(
                [kb], user_id=subject, user_role="user"
            )
            s = await document_acl.superseded_for_search([kb])
            return r, s
        finally:
            await db_pool.dispose_all() if hasattr(db_pool, "dispose_all") else None

    restricted_ids, superseded = asyncio.run(lookups())
    assert len(restricted_ids) == 5
    assert restricted_ids.total == 12 and restricted_ids.overflow
    assert restricted_ids.digest
    hidden = document_acl.merge_hidden(restricted_ids, superseded)
    assert hidden.restricted_overflow
    out = _search(monkeypatch, _vec(30000), [kb], top_k=30, hidden=hidden)
    assert {r.metadata["doc_id"] for r in out} == {open_doc}


def test_acl_digest_moves_when_the_hidden_set_moves(db, monkeypatch):
    tenant = make_tenant(db)
    kb = make_kb(db, tenant, model="m")
    a = _doc(db, kb)
    subject = uuid.uuid4()

    def scope():
        async def go():
            from engine import db_pool

            try:
                return await document_acl.hidden_for_search(
                    [kb], user_id=subject, user_role="user"
                )
            finally:
                await db_pool.dispose_all() if hasattr(db_pool, "dispose_all") else None

        return hs._acl_scope(document_acl.merge_hidden(asyncio.run(go()), set()))

    assert scope() == ""
    db.execute(
        "INSERT INTO document_grants (id, document_id, tenant_id, subject_type, "
        "subject_id, permission) VALUES (%s, %s, %s, 'user', %s, 'read')",
        (str(uuid.uuid4()), a, tenant, str(uuid.uuid4())),
    )
    first = scope()
    assert first
    b = _doc(db, kb)
    db.execute(
        "INSERT INTO document_grants (id, document_id, tenant_id, subject_type, "
        "subject_id, permission) VALUES (%s, %s, %s, 'user', %s, 'read')",
        (str(uuid.uuid4()), b, tenant, str(uuid.uuid4())),
    )
    assert scope() != first


def test_deferred_collection_skips_the_shared_index_then_builds_its_own(
    db, monkeypatch, part_url
):
    import psycopg2

    monkeypatch.setenv("KB_EXACT_SCAN_MAX_CHUNKS", "10")
    tenant = make_tenant(db)
    kb = make_kb(db, tenant, model="m")
    db.execute(
        "UPDATE knowledge_collections SET index_mode = 'deferred' WHERE id = %s", (kb,)
    )
    doc = _doc(db, kb)
    dp._store_vectors_pgvector(
        kb, doc, "f.txt", ["a", "b"], [_vec(40000), _vec(40001)], generation=0
    )
    db.execute(
        "SELECT dedicated_index, tableoid::regclass::text FROM chunks "
        "WHERE collection_id = %s LIMIT 1",
        (kb,),
    )
    dedicated, partition = db.fetchone()
    assert dedicated is True
    # the exact path serves it while it loads
    out = _search(monkeypatch, _vec(40001), [kb], top_k=1)
    assert out[0].content == "b"

    conn = psycopg2.connect(part_url)
    conn.autocommit = True
    assert kb_index.build_index(conn, kb)["status"] == "built"
    conn.close()
    db.execute("SELECT index_mode FROM knowledge_collections WHERE id = %s", (kb,))
    assert db.fetchone()[0] == "dedicated"
    db.execute(
        "SELECT indexdef FROM pg_indexes WHERE tablename = %s AND indexname = %s",
        (partition, "ix_chunks_kb_" + kb.replace("-", "")),
    )
    definition = db.fetchone()[0]
    assert "hnsw" in definition and kb in definition and "dedicated_index" in definition
    out = _search(monkeypatch, _vec(40000), [kb], top_k=1)
    assert out[0].content == "a"


def test_keyword_search_follows_the_collection_language(db, monkeypatch):
    tenant = make_tenant(db)
    english = make_kb(db, tenant, model="m")
    simple = make_kb(db, tenant, model="m")
    db.execute(
        "UPDATE knowledge_collections SET search_language = 'english' WHERE id = %s",
        (english,),
    )
    for kb, text_value in (
        (english, "the runners were running"),
        (simple, "die Läufer laufen schnell durch Straßen"),
    ):
        doc = _doc(db, kb)
        dp._store_vectors_pgvector(
            kb, doc, "f.txt", [text_value], [_vec(1)], generation=0
        )

    async def find(query, ids):
        from engine import db_pool

        try:
            return await hs._keyword_search_pg(query, ids, 5)
        finally:
            await db_pool.dispose_all() if hasattr(db_pool, "dispose_all") else None

    # english stemming on the english collection
    assert asyncio.run(find("run", [english]))
    # the simple collection does no stemming, the same word does not reach another form
    doc = _doc(db, simple)
    dp._store_vectors_pgvector(
        simple, doc, "f.txt", ["the runners were running"], [_vec(2)], generation=0
    )
    assert not asyncio.run(find("run", [simple]))
    assert asyncio.run(find("running", [simple]))
    # simple keeps the word as written, and a non ASCII word reaches the query
    hit = asyncio.run(find("Straßen", [simple]))
    assert hit and "Straßen" in hit[0].content
    assert not asyncio.run(find("Strasse", [simple]))


def test_partition_script_moves_a_live_legacy_table(server_url):
    import psycopg2

    from chunks_schema import startup_statements

    url, engine = _base_schema(server_url, "legacy")
    with engine.begin() as conn:
        for stmt in startup_statements():
            conn.execute(text(stmt))
        conn.execute(
            text(
                "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
                "USING hnsw (embedding vector_cosine_ops)"
            )
        )
    engine.dispose()
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant, model="m")
    doc = _doc(cur, kb)
    cur.execute(
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS "
        "dedicated_index BOOLEAN NOT NULL DEFAULT FALSE"
    )
    _fill(cur, kb, doc, 50)

    import chunks_store as cs

    cur.execute(cs.STATE_SQL)
    # the old shared index would still charge a deferred load, so it is refused until moved
    assert cur.fetchone()[3] is False
    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "kb-chunks-partition.py"),
            "--database-url",
            url,
            "--partitions",
            "4",
            "--batch",
            "7",
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    cur.execute("SELECT relkind::text FROM pg_class WHERE oid = 'chunks'::regclass")
    assert cur.fetchone()[0] == "p"
    cur.execute(cs.STATE_SQL)
    assert cur.fetchone()[3] is True
    cur.execute("SELECT count(*) FROM chunks")
    assert cur.fetchone()[0] == 50
    cur.execute("SELECT count(*) FROM chunks_legacy")
    assert cur.fetchone()[0] == 50
    cur.execute(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_chunks_embedding_hnsw'"
    )
    assert "dedicated_index" in cur.fetchone()[0]
    # writes keep working through the new table
    _doc2 = _doc(cur, kb)
    os.environ["DATABASE_URL"] = url
    try:
        dp._store_vectors_pgvector(kb, _doc2, "n.txt", ["x"], [_vec(1)], generation=0)
    finally:
        os.environ.pop("DATABASE_URL", None)
    cur.execute("SELECT count(*) FROM chunks WHERE document_id = %s", (_doc2,))
    assert cur.fetchone()[0] == 1
    conn.close()
    again = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "kb-chunks-partition.py"),
            "--database-url",
            url,
            "--drop-legacy",
        ],
        capture_output=True,
        text=True,
    )
    assert again.returncode == 0 and "dropped" in again.stdout
