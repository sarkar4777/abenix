"""Erasure reaches knowledge: chunks, files, vectors and Neo4j provenance, on real stores."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from kb_pg import make_doc, make_kb, make_tenant

from app.services import gdpr_purge
from app.services.gdpr_purge import Subject

JANE = "jane.doe@acme.example"


@pytest_asyncio.fixture
async def db(kb_db_url):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine(
        kb_db_url.replace("postgresql://", "postgresql+asyncpg://")
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest.fixture
def graph(neo4j_bolt, monkeypatch):
    from neo4j import GraphDatabase

    from engine.knowledge import neo4j_client

    monkeypatch.setattr(neo4j_client, "_NEO4J_URI", neo4j_bolt)
    monkeypatch.setattr(neo4j_client, "_NEO4J_USER", "neo4j")
    monkeypatch.setattr(neo4j_client, "_NEO4J_PASSWORD", "testpassword")
    monkeypatch.setattr(neo4j_client, "_driver", None)
    monkeypatch.setattr(neo4j_client, "_driver_loop", None)
    with GraphDatabase.driver(neo4j_bolt, auth=("neo4j", "testpassword")) as d:
        with d.session() as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            yield s


def _add(url, *rows):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://"))
    with Session(engine) as session:
        session.add_all(rows)
        session.commit()
    engine.dispose()


def _user(url, tenant):
    from models.user import User, UserRole

    uid = uuid.uuid4()
    _add(
        url,
        User(
            id=uid,
            tenant_id=uuid.UUID(tenant),
            email=f"{uid.hex[:8]}-{JANE}",
            full_name="Jane Doe",
            role=UserRole.USER,
            is_active=True,
        ),
    )
    return str(uid)


def _subject(tenant, uid, kbs):
    return Subject(
        tenant_id=uuid.UUID(tenant),
        user_id=uuid.UUID(uid),
        emails=[JANE],
        names=["jane doe"],
        kb_ids=kbs,
    )


def _entity(cur, tenant, kb, name, docs):
    eid = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO graph_entities (id, tenant_id, kb_id, canonical_name, entity_type, "
        "source_doc_ids, mention_count, access_count, confidence) "
        "VALUES (%s, %s, %s, %s, 'thing', %s::jsonb, 1, 0, 1)",
        (eid, tenant, kb, name, json.dumps(docs)),
    )
    return eid


@pytest.mark.asyncio
async def test_own_documents_go_with_vectors_files_and_provenance(
    kb_conn, kb_db_url, db, graph, tmp_path
):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    jane = _user(kb_db_url, tenant)
    other = _user(kb_db_url, tenant)
    kb = make_kb(cur, tenant, created_by=other)
    file1 = tmp_path / "mine.txt"
    file1.write_text("mine")
    mine = make_doc(
        cur, kb, ["my salary notes"], url=f"file://{file1}", uploaded_by=jane
    )
    theirs = make_doc(cur, kb, ["unrelated budget"], uploaded_by=other)
    cur.execute("UPDATE documents SET cognified_at = now() WHERE id = %s", (mine,))
    cur.execute(
        "INSERT INTO cognify_chunks (kb_id, document_id, chunk_hash, chunk_index, status, "
        "tokens_used, cost_usd, result) VALUES (%s, %s, 'h', 0, 'done', 0, 0, '{\"e\": \"x\"}')",
        (kb, mine),
    )
    only = _entity(cur, tenant, kb, "OnlyMine", [mine])
    shared = _entity(cur, tenant, kb, "Shared", [mine, theirs])
    cur.execute(
        "INSERT INTO graph_relationships (id, kb_id, source_entity_id, target_entity_id, "
        "relationship_type, weight, source_doc_ids, access_count, confidence) "
        "VALUES (%s, %s, %s, %s, 'REL', 1, %s::jsonb, 0, 1)",
        (str(uuid.uuid4()), kb, only, shared, json.dumps([mine])),
    )
    graph.run(
        "CREATE (a:Entity {kb_id: $kb, canonical_name: 'OnlyMine', source_doc_ids: [$m]}) "
        "CREATE (b:Entity {kb_id: $kb, canonical_name: 'Shared', source_doc_ids: [$m, $t]}) "
        "CREATE (c:Entity {kb_id: $kb, canonical_name: 'Theirs', source_doc_ids: [$t]}) "
        "CREATE (b)-[:REL {source_doc_ids: [$m]}]->(c) "
        "CREATE (b)-[:REL2 {source_doc_ids: [$m, $t]}]->(c)",
        kb=kb,
        m=mine,
        t=theirs,
    ).consume()

    affected = await gdpr_purge._purge_knowledge(db, _subject(tenant, jane, [kb]))
    assert affected >= 3

    cur.execute("SELECT count(*) FROM documents WHERE id = %s", (mine,))
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT count(*) FROM chunks WHERE document_id = %s", (mine,))
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT count(*) FROM cognify_chunks WHERE document_id = %s", (mine,))
    assert cur.fetchone()[0] == 0
    assert not file1.exists()
    cur.execute("SELECT count(*) FROM chunks WHERE document_id = %s", (theirs,))
    assert cur.fetchone()[0] == 1

    names = {
        r["n"]: r["d"]
        for r in graph.run(
            "MATCH (e:Entity {kb_id: $kb}) RETURN e.canonical_name AS n, e.source_doc_ids AS d",
            kb=kb,
        )
    }
    assert "OnlyMine" not in names
    assert names["Shared"] == [theirs]
    assert names["Theirs"] == [theirs]
    rels = {
        r["t"]: r["d"]
        for r in graph.run(
            "MATCH (:Entity {kb_id: $kb})-[r]->() RETURN type(r) AS t, r.source_doc_ids AS d",
            kb=kb,
        )
    }
    assert rels == {"REL2": [theirs]}

    cur.execute(
        "SELECT canonical_name, source_doc_ids FROM graph_entities WHERE kb_id = %s",
        (kb,),
    )
    assert dict(cur.fetchall()) == {"Shared": [theirs]}
    cur.execute("SELECT count(*) FROM graph_relationships WHERE kb_id = %s", (kb,))
    assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_a_legacy_document_counts_in_a_collection_they_created(
    kb_conn, kb_db_url, db, graph
):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    jane = _user(kb_db_url, tenant)
    kb = make_kb(cur, tenant, created_by=jane)
    legacy = make_doc(cur, kb, ["no uploader recorded"])
    await gdpr_purge._purge_knowledge(db, _subject(tenant, jane, [kb]))
    cur.execute("SELECT count(*) FROM documents WHERE id = %s", (legacy,))
    assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_mentions_in_other_peoples_documents_lose_those_chunks_and_the_file(
    kb_conn, kb_db_url, db, graph, tmp_path
):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    jane = _user(kb_db_url, tenant)
    other = _user(kb_db_url, tenant)
    kb = make_kb(cur, tenant, created_by=other)
    f = tmp_path / "report.txt"
    f.write_text("x")
    doc = make_doc(
        cur,
        kb,
        [f"contact {JANE.upper()} for this", "nothing here", "signed by Jane Doe"],
        url=str(f),
        uploaded_by=other,
    )
    await gdpr_purge._purge_knowledge(db, _subject(tenant, jane, [kb]))
    cur.execute("SELECT content FROM chunks WHERE document_id = %s", (doc,))
    assert [r[0] for r in cur.fetchall()] == ["nothing here"]
    assert not f.exists()
    cur.execute(
        "SELECT storage_url, error_message FROM documents WHERE id = %s", (doc,)
    )
    url, note = cur.fetchone()
    assert url == "" and "erased" in note


@pytest.mark.asyncio
async def test_a_graph_outage_fails_the_store_and_keeps_the_documents(
    kb_conn, kb_db_url, db
):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    jane = _user(kb_db_url, tenant)
    kb = make_kb(cur, tenant)
    mine = make_doc(cur, kb, ["mine"], uploaded_by=jane)
    cur.execute("UPDATE documents SET cognified_at = now() WHERE id = %s", (mine,))
    _entity(cur, tenant, kb, "OnlyMine", [mine])
    with patch(
        "engine.knowledge.neo4j_client.is_neo4j_available",
        AsyncMock(return_value=False),
    ), pytest.raises(RuntimeError, match="Neo4j is unreachable"):
        await gdpr_purge._purge_knowledge(db, _subject(tenant, jane, [kb]))
    await db.rollback()
    cur.execute("SELECT count(*) FROM documents WHERE id = %s", (mine,))
    assert cur.fetchone()[0] == 1


@pytest.mark.asyncio
async def test_pinecone_vectors_of_own_documents_are_deleted_in_every_store(
    kb_conn, kb_db_url, db, graph, monkeypatch
):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    jane = _user(kb_db_url, tenant)
    kb = make_kb(cur, tenant, backend="pinecone")
    cur.execute(
        "UPDATE knowledge_collections SET embedding_generation = 2 WHERE id = %s", (kb,)
    )
    mine = make_doc(cur, kb, ["fallback row"], uploaded_by=jane)
    theirs = make_doc(cur, kb, [])
    cur.execute("UPDATE documents SET chunk_count = 1 WHERE id = %s", (theirs,))

    class Index:
        deleted: list = []

        def list(self, prefix, namespace):
            yield [f"{mine}_0", f"{mine}_1"]

        def fetch(self, ids, namespace):
            return {
                "vectors": {
                    i: {"metadata": {"text": f"written by {JANE}"}}
                    for i in ids
                    if i.startswith(theirs)
                }
            }

        def delete(self, ids, namespace):
            Index.deleted.append((namespace, sorted(ids)))

    class PC:
        def __init__(self, api_key):
            pass

        def Index(self, name):
            return Index()

    monkeypatch.setenv("PINECONE_API_KEY", "k")
    monkeypatch.setattr("pinecone.Pinecone", PC)
    await gdpr_purge._purge_knowledge(db, _subject(tenant, jane, [kb]))
    assert (f"{kb}.g2", [f"{mine}_0", f"{mine}_1"]) in Index.deleted
    assert (f"{kb}.g2", [f"{theirs}_0"]) in Index.deleted


@pytest.mark.asyncio
async def test_what_they_searched_for_is_erased(kb_conn, kb_db_url, db, graph):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    jane = _user(kb_db_url, tenant)
    kb = make_kb(cur, tenant)
    from models.agent import Agent, AgentStatus
    from models.execution import Execution, ExecutionStatus

    aid, run = uuid.uuid4(), uuid.uuid4()
    _add(
        kb_db_url,
        Agent(
            id=aid,
            tenant_id=uuid.UUID(tenant),
            name="a",
            slug=str(aid),
            status=AgentStatus.ACTIVE,
            creator_id=uuid.UUID(jane),
        ),
    )
    _add(
        kb_db_url,
        Execution(
            id=run,
            tenant_id=uuid.UUID(tenant),
            agent_id=aid,
            user_id=uuid.UUID(jane),
            input_message="q",
            status=ExecutionStatus.COMPLETED,
        ),
    )
    run = str(run)
    cur.execute(
        "INSERT INTO kb_query_invocations (id, tenant_id, kb_collection_id, execution_id, "
        "query_text, is_error) VALUES (%s, %s, %s, %s, 'jane salary', false)",
        (str(uuid.uuid4()), tenant, kb, run),
    )
    await gdpr_purge._purge_knowledge(db, _subject(tenant, jane, [kb]))
    cur.execute(
        "SELECT query_text FROM kb_query_invocations WHERE execution_id = %s", (run,)
    )
    assert cur.fetchone()[0] == gdpr_purge.ERASED
