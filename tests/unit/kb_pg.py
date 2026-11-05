"""A throwaway pgvector container for tests that exercise real persistence."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:pg16"
DOCKER_PATHS = [str(Path.home() / ".docker/bin"), "/opt/homebrew/bin", "/usr/local/bin"]


def docker() -> str | None:
    return shutil.which(
        "docker", path=os.pathsep.join([os.environ["PATH"], *DOCKER_PATHS])
    )


def docker_works() -> bool:
    d = docker()
    if not d:
        return False
    for _ in range(3):
        try:
            if (
                subprocess.run([d, "info"], capture_output=True, timeout=20).returncode
                == 0
            ):
                return True
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2)
    return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_postgres(name: str, port: int) -> None:
    subprocess.run(
        [
            docker(),
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-e",
            "POSTGRES_PASSWORD=test",
            "-e",
            "POSTGRES_DB=abenix",
            "-p",
            f"127.0.0.1:{port}:5432",
            IMAGE,
        ],
        check=True,
        capture_output=True,
    )


def wait_for_postgres(url: str, seconds: int = 60) -> None:
    import psycopg2

    end = time.time() + seconds
    while True:
        try:
            psycopg2.connect(url).close()
            return
        except psycopg2.OperationalError:
            if time.time() > end:
                raise
            time.sleep(0.5)


def fresh_schema(url: str) -> None:
    """The fresh install path, enums and create_all then a partitioned chunks table."""
    from sqlalchemy import create_engine, text

    sys.path.insert(0, str(ROOT / "packages" / "db"))
    import bootstrap
    import models  # noqa: F401
    from chunks_store import partitioned_ddl
    from models.base import Base

    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://"))
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        bootstrap._create_missing_enums_sync(conn)
        Base.metadata.create_all(bind=conn)
        for stmt in partitioned_ddl(partitions=4, column_type="vector"):
            conn.execute(text(stmt))
    engine.dispose()


@pytest.fixture(scope="session")
def kb_db_url():
    if not docker_works():
        pytest.skip("docker is not available")
    name = f"abenix-kbops-test-{uuid.uuid4().hex[:8]}"
    port = free_port()
    run_postgres(name, port)
    url = f"postgresql://postgres:test@127.0.0.1:{port}/abenix"
    try:
        wait_for_postgres(url)
        fresh_schema(url)
        yield url
    finally:
        subprocess.run([docker(), "rm", "-f", name], capture_output=True)


@pytest.fixture
def kb_conn(kb_db_url, monkeypatch):
    import psycopg2

    monkeypatch.setenv("DATABASE_URL", kb_db_url)
    conn = psycopg2.connect(kb_db_url)
    conn.autocommit = True
    yield conn
    conn.close()


def make_tenant(cur) -> str:
    tid = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO tenants (id, name, slug, plan) VALUES (%s, %s, %s, 'FREE')",
        (tid, f"t-{tid[:8]}", f"t-{tid}"),
    )
    return tid


def make_kb(
    cur,
    tenant: str,
    backend: str = "pgvector",
    model: str = "local-hashing-v1",
    created_by: str | None = None,
) -> str:
    kb = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO knowledge_collections (id, tenant_id, name, description, "
        "embedding_model, chunk_size, chunk_overlap, vector_backend, status, doc_count, "
        "graph_enabled, entity_count, relationship_count, default_visibility, created_by) "
        "VALUES (%s, %s, %s, '', %s, 500, 50, %s, 'READY', 0, false, 0, 0, 'project', %s)",
        (kb, tenant, f"kb-{kb[:6]}", model, backend, created_by),
    )
    return kb


def make_doc(
    cur,
    kb: str,
    chunks: list[str],
    *,
    url: str = "",
    filename: str = "a.txt",
    uploaded_by: str | None = None,
    generation: int = 0,
    metadata: dict | None = None,
) -> str:
    import json

    doc = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO documents (id, kb_id, filename, file_type, file_size, chunk_count, "
        "status, storage_url, version_number, is_current, uploaded_by) "
        "VALUES (%s, %s, %s, 'txt', 10, %s, 'READY', %s, 1, true, %s)",
        (doc, kb, filename, len(chunks), url, uploaded_by),
    )
    vec = "[" + ",".join(["0.1"] * 1536) + "]"
    for i, text in enumerate(chunks):
        cur.execute(
            "INSERT INTO chunks (id, collection_id, document_id, chunk_index, content, "
            "metadata, embedding, embedding_generation) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::vector, %s)",
            (
                str(uuid.uuid4()),
                kb,
                doc,
                i,
                text,
                json.dumps({"filename": filename, **(metadata or {})}),
                vec,
                generation,
            ),
        )
    return doc


def _throwaway(prefix: str, *args: str) -> str:
    name = f"abenix-kbops-{prefix}-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [docker(), "run", "-d", "--rm", "--name", name, *args],
        check=True,
        capture_output=True,
    )
    return name


def _wait_until(check, seconds: int, what: str) -> None:
    end = time.time() + seconds
    last = None
    while time.time() < end:
        try:
            if check():
                return
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1)
    raise RuntimeError(f"{what} did not start: {last}")


@pytest.fixture(scope="session")
def minio_endpoint():
    if not docker_works():
        pytest.skip("docker is not available")
    port = free_port()
    name = _throwaway(
        "minio",
        "-e",
        "MINIO_ROOT_USER=testaccess",
        "-e",
        "MINIO_ROOT_PASSWORD=testsecret123",
        "-p",
        f"127.0.0.1:{port}:9000",
        "bitnamilegacy/minio:latest",
    )
    url = f"http://127.0.0.1:{port}"
    try:
        import httpx

        _wait_until(
            lambda: httpx.get(f"{url}/minio/health/live", timeout=2).status_code == 200,
            90,
            "MinIO",
        )
        yield {"url": url, "access": "testaccess", "secret": "testsecret123"}
    finally:
        subprocess.run([docker(), "rm", "-f", name], capture_output=True)


@pytest.fixture(scope="session")
def azurite_port():
    if not docker_works():
        pytest.skip("docker is not available")
    port = free_port()
    name = _throwaway(
        "azurite",
        "-p",
        f"127.0.0.1:{port}:10000",
        "mcr.microsoft.com/azure-storage/azurite:latest",
        "azurite-blob",
        "--blobHost",
        "0.0.0.0",
        "--skipApiVersionCheck",
    )
    try:
        import httpx

        # any answer at all means it is serving, it refuses this request unsigned
        _wait_until(
            lambda: httpx.get(f"http://127.0.0.1:{port}/", timeout=2).status_code > 0,
            60,
            "Azurite",
        )
        yield port
    finally:
        subprocess.run([docker(), "rm", "-f", name], capture_output=True)


@pytest.fixture(scope="session")
def neo4j_bolt():
    if not docker_works():
        pytest.skip("docker is not available")
    port = free_port()
    name = _throwaway(
        "neo4j",
        "-e",
        "NEO4J_AUTH=neo4j/testpassword",
        "-p",
        f"127.0.0.1:{port}:7687",
        "neo4j:5-community",
    )
    uri = f"bolt://127.0.0.1:{port}"
    try:
        from neo4j import GraphDatabase

        def up() -> bool:
            with GraphDatabase.driver(uri, auth=("neo4j", "testpassword")) as d:
                d.verify_connectivity()
            return True

        _wait_until(up, 120, "Neo4j")
        yield uri
    finally:
        subprocess.run([docker(), "rm", "-f", name], capture_output=True)
