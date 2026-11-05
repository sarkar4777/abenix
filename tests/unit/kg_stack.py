"""Throwaway Neo4j for tests that exercise the real graph, and a fake extractor."""

from __future__ import annotations

import os
import subprocess
import time
import uuid

import pytest
from kb_pg import (
    ROOT,
    docker,
    docker_works,
    free_port,
    run_postgres,
    wait_for_postgres,
)

NEO4J_IMAGE = "neo4j:5-community"
PASSWORD = "kg-test-password"


def _wait_for_neo4j(uri: str, seconds: int = 120) -> None:
    from neo4j import GraphDatabase

    end = time.time() + seconds
    while True:
        try:
            with GraphDatabase.driver(uri, auth=("neo4j", PASSWORD)) as d:
                d.verify_connectivity()
            return
        except Exception:
            if time.time() > end:
                raise
            time.sleep(1)


@pytest.fixture(scope="session")
def neo4j_uri():
    uri = os.environ.get("KG_TEST_NEO4J_URI")
    if uri:
        yield uri
        return
    if not docker_works():
        pytest.skip("docker is not available")
    name = f"abenix-kg-test-{uuid.uuid4().hex[:8]}"
    port = free_port()
    subprocess.run(
        [
            docker(),
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-e",
            f"NEO4J_AUTH=neo4j/{PASSWORD}",
            "-p",
            f"127.0.0.1:{port}:7687",
            NEO4J_IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    uri = f"bolt://127.0.0.1:{port}"
    try:
        _wait_for_neo4j(uri)
        yield uri
    finally:
        subprocess.run([docker(), "rm", "-f", name], capture_output=True)


def install_schema(url: str) -> None:
    """The fresh install path, the same one bootstrap takes."""
    import sys

    from sqlalchemy import create_engine, text

    sys.path.insert(0, str(ROOT / "packages" / "db"))
    import bootstrap
    import models  # noqa: F401
    from chunks_schema import startup_statements
    from models.base import Base

    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://"))
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        bootstrap._create_missing_enums_sync(conn)
        Base.metadata.create_all(bind=conn)
        for stmt in startup_statements():
            conn.execute(text(stmt))
    engine.dispose()


@pytest.fixture(scope="session")
def kg_db_url():
    url = os.environ.get("KG_TEST_DATABASE_URL")
    if url:
        install_schema(url)
        yield url
        return
    if not docker_works():
        pytest.skip("docker is not available")
    name = f"abenix-kg-pg-test-{uuid.uuid4().hex[:8]}"
    port = free_port()
    run_postgres(name, port)
    url = f"postgresql://postgres:test@127.0.0.1:{port}/abenix"
    try:
        wait_for_postgres(url)
        install_schema(url)
        yield url
    finally:
        subprocess.run([docker(), "rm", "-f", name], capture_output=True)


@pytest.fixture
def kg_conn(kg_db_url):
    import psycopg2

    conn = psycopg2.connect(kg_db_url)
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def graph(neo4j_uri, monkeypatch):
    from engine.knowledge import neo4j_client

    monkeypatch.setattr(neo4j_client, "_NEO4J_URI", neo4j_uri)
    monkeypatch.setattr(neo4j_client, "_NEO4J_USER", "neo4j")
    monkeypatch.setattr(
        neo4j_client,
        "_NEO4J_PASSWORD",
        os.environ.get("KG_TEST_NEO4J_PASSWORD", PASSWORD),
    )
    neo4j_client.forget_driver()
    neo4j_client._keys_ready.clear()
    yield neo4j_client
    neo4j_client.forget_driver()


def cypher_sync(uri: str, statement: str, **params) -> list[dict]:
    from neo4j import GraphDatabase

    auth = ("neo4j", os.environ.get("KG_TEST_NEO4J_PASSWORD", PASSWORD))
    with GraphDatabase.driver(uri, auth=auth) as d:
        with d.session() as s:
            return [dict(r) for r in s.run(statement, **params)]


class FakeExtractor:
    """Answers like extract_chunks. Each chunk text names its entities, two to a chunk."""

    def __init__(
        self, cost: float = 0.01, fail_indexes=(), crash_after: int | None = None
    ):
        self.cost = cost
        self.calls = 0
        self.seen: list[int] = []
        self.fail_indexes = set(fail_indexes)
        self.crash_after = crash_after

    async def __call__(
        self,
        items,
        doc_id,
        known_entities=None,
        model="",
        ontology=None,
        limiter=None,
        max_parallel=4,
    ):
        from engine.knowledge.entity_extractor import (
            ChunkExtractionResult,
            ExtractedEntity,
            ExtractedRelationship,
        )

        if self.crash_after is not None and self.calls >= self.crash_after:
            raise RuntimeError("worker died")
        out = []
        for index, text in items:
            self.calls += 1
            self.seen.append(index)
            if index in self.fail_indexes:
                out.append(
                    ChunkExtractionResult(
                        [],
                        [],
                        index,
                        doc_id,
                        tokens_used=10,
                        cost=self.cost,
                        error="429",
                    )
                )
                continue
            a, b = text.split("|")[:2]
            out.append(
                ChunkExtractionResult(
                    entities=[
                        ExtractedEntity(a, "organization", f"{a} desc", index, doc_id),
                        ExtractedEntity(b, "organization", f"{b} desc", index, doc_id),
                    ],
                    relationships=[
                        ExtractedRelationship(a, b, "WORKS_WITH", "rel", index, doc_id)
                    ],
                    chunk_index=index,
                    doc_id=doc_id,
                    tokens_used=100,
                    cost=self.cost,
                )
            )
        return out
