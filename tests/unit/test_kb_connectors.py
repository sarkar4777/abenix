"""Connector framework and sources. S3, Azure Blob, SQL and filesystem run against real
servers in throwaway containers. Graph, Confluence and Drive run on fake transports only,
none of them has ever been called for real."""

from __future__ import annotations

import base64
import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import boto3
import httpx
import pytest
from kb_pg import make_kb, make_tenant

from engine.kb_connectors import base as conn_base
from engine.kb_connectors import describe
from engine.kb_connectors.azure_blob import parse_connection_string
from engine.kb_connectors.filesystem import FilesystemConnector
from engine.kb_connectors.gdrive import signed_jwt
from engine.kb_connectors.sql_query import check_query
from worker.tasks import kb_connector_sync as sync

AZURITE_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(conn_base, "backoff_delay", lambda attempt, after=None: 0)


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    from engine.storage import service

    monkeypatch.setattr(service, "STORAGE_LOCAL_DIR", str(tmp_path / "store"))
    monkeypatch.setattr(service, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(service, "_storage", None, raising=False)
    (tmp_path / "store").mkdir()
    return tmp_path / "store"


@pytest.fixture
def allow_local(monkeypatch):
    monkeypatch.setenv("KB_CONNECTORS_ALLOWED_HOSTS", "127.0.0.1,localhost")


def _source(cur, tenant, kb, kind, config, secrets=None, cadence=60, created_by=None):
    sid = str(uuid.uuid4())
    key = None
    if secrets:
        key = f"KBCONN_{uuid.UUID(sid).hex}"
        cur.execute(
            "INSERT INTO tenant_tool_credentials (tenant_id, key, value) VALUES (%s, %s, %s)",
            (tenant, key, json.dumps(secrets)),
        )
    cur.execute(
        "INSERT INTO kb_connector_sources (id, tenant_id, kb_id, name, kind, config, "
        "credential_key, cadence_minutes, active, status, confirm_deletes, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, true, 'queued', false, %s)",
        (
            sid,
            tenant,
            kb,
            f"src-{kind}",
            kind,
            json.dumps(config),
            key,
            cadence,
            created_by,
        ),
    )
    return sid


def _run(sid, **kw):
    sent: list[tuple] = []
    requeued: list[str] = []
    out = sync.sync_slice(
        sid,
        requeue=lambda s, countdown=0: requeued.append(s),
        dispatch=lambda *a: sent.append(a),
        **kw,
    )
    return out, sent, requeued


def _docs(cur, kb):
    cur.execute(
        "SELECT filename, status::text, storage_url FROM documents WHERE kb_id = %s ORDER BY 1",
        (kb,),
    )
    return cur.fetchall()


def _items(cur, sid):
    cur.execute(
        "SELECT external_id, status, error FROM kb_connector_items WHERE source_id = %s ORDER BY 1",
        (sid,),
    )
    return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def _state(cur, sid):
    cur.execute(
        "SELECT status, last_error, items_seen, items_ingested, items_updated, items_deleted, "
        "items_failed, items_skipped FROM kb_connector_sources WHERE id = %s",
        (sid,),
    )
    return dict(
        zip(
            (
                "status",
                "error",
                "seen",
                "ingested",
                "updated",
                "deleted",
                "failed",
                "skipped",
            ),
            cur.fetchone(),
        )
    )


def _setup(cur):
    tenant = make_tenant(cur)
    return tenant, make_kb(cur, tenant)


# real S3 compatible server


@pytest.fixture
def bucket(minio_endpoint):
    s3 = boto3.client(
        "s3",
        endpoint_url=minio_endpoint["url"],
        aws_access_key_id=minio_endpoint["access"],
        aws_secret_access_key=minio_endpoint["secret"],
        region_name="us-east-1",
    )
    name = f"src-{uuid.uuid4().hex[:8]}"
    s3.create_bucket(Bucket=name)
    return s3, name


def _s3_config(minio, name, prefix=""):
    return {"bucket": name, "prefix": prefix, "endpoint_url": minio["url"]}


def _s3_secrets(minio):
    return {"access_key": minio["access"], "secret_key": minio["secret"]}


def test_s3_new_changed_deleted_and_unsupported(
    kb_conn, minio_endpoint, bucket, local_storage, allow_local
):
    s3, name = bucket
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    s3.put_object(Bucket=name, Key="docs/a.txt", Body=b"first")
    s3.put_object(Bucket=name, Key="docs/b.md", Body=b"# b")
    s3.put_object(Bucket=name, Key="docs/bundle.zip", Body=b"PK")
    s3.put_object(Bucket=name, Key="docs/raw.bin", Body=b"\x00")
    sid = _source(
        cur,
        tenant,
        kb,
        "s3",
        _s3_config(minio_endpoint, name, "docs/"),
        _s3_secrets(minio_endpoint),
    )

    out, sent, _ = _run(sid)
    assert out["status"] == "idle"
    assert sorted(a[3] for a in sent) == ["a.txt", "b.md"]
    assert [d[0] for d in _docs(cur, kb)] == ["a.txt", "b.md"]
    items = _items(cur, sid)
    assert (
        items["docs/bundle.zip"][0] == "skipped"
        and "Archives" in items["docs/bundle.zip"][1]
    )
    assert items["docs/raw.bin"][0] == "skipped" and ".bin" in items["docs/raw.bin"][1]
    state = _state(cur, sid)
    assert (state["ingested"], state["skipped"]) == (2, 2)
    stored = _docs(cur, kb)[0][2]
    assert stored.startswith("file://") or os.path.exists(stored)

    # nothing changed, nothing fetched or queued again
    out, sent, _ = _run(sid)
    assert out["status"] == "idle" and sent == []
    assert _state(cur, sid)["seen"] == 4

    s3.put_object(Bucket=name, Key="docs/a.txt", Body=b"second")
    s3.delete_object(Bucket=name, Key="docs/b.md")
    out, sent, _ = _run(sid)
    assert out["status"] == "idle"
    assert [a[3] for a in sent] == ["a.txt"]
    state = _state(cur, sid)
    assert (state["updated"], state["deleted"]) == (1, 1)
    assert [d[0] for d in _docs(cur, kb)] == ["a.txt"]
    assert "docs/b.md" not in _items(cur, sid)
    cur.execute("SELECT status::text, file_size FROM documents WHERE kb_id = %s", (kb,))
    assert cur.fetchone() == ("PROCESSING", 6)


def test_s3_endpoint_on_a_private_address_is_refused(
    kb_conn, minio_endpoint, bucket, local_storage, monkeypatch
):
    monkeypatch.delenv("KB_CONNECTORS_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("CONNECTORS_ALLOW_PRIVATE_TARGETS", raising=False)
    _s3, name = bucket
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    sid = _source(
        cur,
        tenant,
        kb,
        "s3",
        _s3_config(minio_endpoint, name),
        _s3_secrets(minio_endpoint),
    )
    out, sent, _ = _run(sid)
    assert out["status"] == "failed" and "private or loopback" in out["error"]
    assert sent == []


def test_s3_wrong_credentials_fail_with_a_clear_message(
    kb_conn, minio_endpoint, bucket, local_storage, allow_local
):
    _s3, name = bucket
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    sid = _source(
        cur,
        tenant,
        kb,
        "s3",
        _s3_config(minio_endpoint, name),
        {"access_key": "nobody", "secret_key": "wrongwrong"},
    )
    out, _sent, _ = _run(sid)
    assert out["status"] == "failed" and "refused these credentials" in out["error"]
    assert _state(cur, sid)["status"] == "failed"


def test_mass_delete_stops_and_asks_then_confirm_removes(
    kb_conn, minio_endpoint, bucket, local_storage, allow_local
):
    s3, name = bucket
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    s3.put_object(Bucket=name, Key="a.txt", Body=b"one")
    sid = _source(
        cur,
        tenant,
        kb,
        "s3",
        _s3_config(minio_endpoint, name),
        _s3_secrets(minio_endpoint),
    )
    _run(sid)
    s3.delete_object(Bucket=name, Key="a.txt")
    out, _sent, _ = _run(sid)
    assert out["status"] == "needs_confirmation"
    assert "nothing was deleted" in out["error"]
    assert len(_docs(cur, kb)) == 1
    cur.execute(
        "UPDATE kb_connector_sources SET confirm_deletes = true WHERE id = %s", (sid,)
    )
    out, _sent, _ = _run(sid)
    assert out["status"] == "idle"
    assert _docs(cur, kb) == []


def test_quota_stops_the_source_with_the_reason(
    kb_conn, minio_endpoint, bucket, local_storage, allow_local
):
    s3, name = bucket
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    cur.execute(
        "INSERT INTO tenant_knowledge_quotas (tenant_id, max_documents) VALUES (%s, 1)",
        (tenant,),
    )
    s3.put_object(Bucket=name, Key="a.txt", Body=b"one")
    s3.put_object(Bucket=name, Key="b.txt", Body=b"two")
    sid = _source(
        cur,
        tenant,
        kb,
        "s3",
        _s3_config(minio_endpoint, name),
        _s3_secrets(minio_endpoint),
    )
    out, sent, _ = _run(sid)
    assert out["status"] == "quota_exceeded"
    assert "limit is 1" in out["error"]
    assert len(sent) == 1


def test_oversized_item_is_skipped(
    kb_conn, minio_endpoint, bucket, local_storage, allow_local, monkeypatch
):
    s3, name = bucket
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    monkeypatch.setattr(sync, "MAX_ITEM_BYTES", 4)
    s3.put_object(Bucket=name, Key="big.txt", Body=b"0123456789")
    sid = _source(
        cur,
        tenant,
        kb,
        "s3",
        _s3_config(minio_endpoint, name),
        _s3_secrets(minio_endpoint),
    )
    _run(sid)
    assert _items(cur, sid)["big.txt"][0] == "skipped"
    assert _docs(cur, kb) == []


def test_docx_zip_bomb_from_a_source_is_skipped(
    kb_conn, minio_endpoint, bucket, local_storage, allow_local, monkeypatch
):
    import io
    import zipfile

    s3, name = bucket
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    monkeypatch.setenv("ARCHIVE_MAX_TOTAL_BYTES", "1000")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"0" * 200_000)
    s3.put_object(Bucket=name, Key="bomb.docx", Body=buf.getvalue())
    sid = _source(
        cur,
        tenant,
        kb,
        "s3",
        _s3_config(minio_endpoint, name),
        _s3_secrets(minio_endpoint),
    )
    _run(sid)
    status, why = _items(cur, sid)["bomb.docx"]
    assert status == "skipped" and "expand" in why
    assert _docs(cur, kb) == []


# real Azure Blob emulator


def test_azure_blob_with_shared_key_against_azurite(
    kb_conn, azurite_port, local_storage, allow_local
):
    account = "devstoreaccount1"
    url = f"http://127.0.0.1:{azurite_port}/{account}"
    conn_string = (
        f"DefaultEndpointsProtocol=http;AccountName={account};AccountKey={AZURITE_KEY};"
        f"BlobEndpoint={url};"
    )
    container = f"c{uuid.uuid4().hex[:8]}"

    from engine.kb_connectors.azure_blob import API_VERSION, AzureBlobConnector

    helper = AzureBlobConnector(
        {"container": container}, {"connection_string": conn_string}
    )

    def write(path, method="PUT", data=b"", extra=None, query=None):
        target = helper._url(path, query or {})
        headers = {
            "x-ms-date": _rfc1123(),
            "x-ms-version": API_VERSION,
            **(extra or {}),
        }
        headers["Authorization"] = _shared_key(
            method, target, headers, account, len(data)
        )
        resp = httpx.request(method, target, content=data, headers=headers, timeout=10)
        assert resp.status_code < 300, resp.text

    write(container, query={"restype": "container"})
    write(f"{container}/one.txt", data=b"hello", extra={"x-ms-blob-type": "BlockBlob"})
    write(f"{container}/two.md", data=b"# two", extra={"x-ms-blob-type": "BlockBlob"})

    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    sid = _source(
        cur,
        tenant,
        kb,
        "azure_blob",
        {"container": container},
        {"connection_string": conn_string},
    )
    out, sent, _ = _run(sid)
    assert out["status"] == "idle", out
    assert sorted(a[3] for a in sent) == ["one.txt", "two.md"]
    cur.execute(
        "SELECT file_size FROM documents WHERE kb_id = %s AND filename = 'one.txt'",
        (kb,),
    )
    assert cur.fetchone()[0] == 5

    write(f"{container}/two.md", method="DELETE")
    write(
        f"{container}/one.txt",
        data=b"hello again",
        extra={"x-ms-blob-type": "BlockBlob"},
    )
    out, sent, _ = _run(sid)
    assert out["status"] == "idle"
    assert [a[3] for a in sent] == ["one.txt"]
    assert [d[0] for d in _docs(cur, kb)] == ["one.txt"]


def _rfc1123() -> str:
    from email.utils import formatdate

    return formatdate(usegmt=True)


def _shared_key(method, url, headers, account, length):
    import hashlib
    import hmac
    from urllib.parse import parse_qsl, urlparse

    u = urlparse(url)
    query = "".join(
        f"\n{k.lower()}:{v}"
        for k, v in sorted(parse_qsl(u.query, keep_blank_values=True))
    )
    ms = "".join(
        f"{k}:{headers[k]}\n"
        for k in sorted(h for h in headers if h.startswith("x-ms-"))
    )
    size = str(length) if length else ""
    to_sign = f"{method}\n\n\n{size}\n\n\n\n\n\n\n\n\n{ms}/{account}{u.path}{query}"
    mac = hmac.new(
        base64.b64decode(AZURITE_KEY), to_sign.encode(), hashlib.sha256
    ).digest()
    return f"SharedKey {account}:{base64.b64encode(mac).decode()}"


def test_connection_string_parsing():
    parsed = parse_connection_string(
        "DefaultEndpointsProtocol=https;AccountName=acme;AccountKey=abc==;EndpointSuffix=core.windows.net"
    )
    assert parsed["account_url"] == "https://acme.blob.core.windows.net"
    assert parsed["account_key"] == "abc=="


# real SQL database, a second database in the throwaway Postgres


@pytest.fixture
def source_db(kb_db_url):
    import psycopg2

    name = f"src_{uuid.uuid4().hex[:8]}"
    admin = psycopg2.connect(kb_db_url)
    admin.autocommit = True
    admin.cursor().execute(f"CREATE DATABASE {name}")
    url = kb_db_url.rsplit("/", 1)[0] + "/" + name
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE policies (id int primary key, title text, body text, "
        "updated timestamptz not null default now(), readers text)"
    )
    cur.execute(
        "INSERT INTO policies VALUES (1, 'Leave', 'Twenty days', now(), 'a@x.example'), "
        "(2, 'Travel', 'Economy only', now(), '')"
    )
    yield url, cur
    conn.close()
    admin.close()


def _sql_config(**extra):
    return {
        "query": "SELECT id, title, body, updated, readers FROM policies",
        "id_column": "id",
        "title_column": "title",
        **extra,
    }


def test_sql_rows_by_hash_detect_change_and_delete(
    kb_conn, source_db, local_storage, allow_local
):
    url, src = source_db
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    sid = _source(
        cur,
        tenant,
        kb,
        "sql",
        {
            "query": "SELECT id, title, body FROM policies",
            "id_column": "id",
            "title_column": "title",
        },
        {"url": url},
    )
    out, sent, _ = _run(sid)
    assert out["status"] == "idle", out
    assert sorted(a[3] for a in sent) == ["Leave.txt", "Travel.txt"]
    with open(_docs(cur, kb)[0][2].replace("file://", ""), encoding="utf-8") as fh:
        assert "body: Twenty days" in fh.read()

    src.execute("UPDATE policies SET body = 'Thirty days' WHERE id = 1")
    src.execute("DELETE FROM policies WHERE id = 2")
    out, sent, _ = _run(sid)
    assert out["status"] == "idle"
    assert [a[3] for a in sent] == ["Leave.txt"]
    assert [d[0] for d in _docs(cur, kb)] == ["Leave.txt"]


def test_sql_watermark_reads_only_changed_rows_and_still_finds_deletes(
    kb_conn, source_db, local_storage, allow_local
):
    url, src = source_db
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    sid = _source(
        cur, tenant, kb, "sql", _sql_config(updated_column="updated"), {"url": url}
    )
    out, sent, _ = _run(sid)
    assert out["status"] == "idle" and len(sent) == 2
    cur.execute("SELECT sync_cursor FROM kb_connector_sources WHERE id = %s", (sid,))
    assert cur.fetchone()[0]["watermark"]

    out, sent, _ = _run(sid)
    assert out["status"] == "idle" and sent == []
    assert _state(cur, sid)["seen"] == 2

    src.execute(
        "UPDATE policies SET body = 'New', updated = now() + interval '1 hour' WHERE id = 1"
    )
    src.execute("DELETE FROM policies WHERE id = 2")
    out, sent, _ = _run(sid)
    assert out["status"] == "idle"
    assert [a[3] for a in sent] == ["Leave.txt"]
    assert [d[0] for d in _docs(cur, kb)] == ["Leave.txt"]


def test_sql_acl_column_becomes_document_grants(
    kb_conn, kb_db_url, source_db, local_storage, allow_local
):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from models.user import User, UserRole

    url, _src = source_db
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    reader = uuid.uuid4()
    engine = create_engine(kb_db_url.replace("postgresql://", "postgresql+psycopg2://"))
    with Session(engine) as session:
        session.add(
            User(
                id=reader,
                tenant_id=uuid.UUID(tenant),
                email="a@x.example",
                full_name="A",
                role=UserRole.USER,
                is_active=True,
            )
        )
        session.commit()
    engine.dispose()
    sid = _source(
        cur, tenant, kb, "sql", _sql_config(acl_column="readers"), {"url": url}
    )
    out, _sent, _ = _run(sid)
    assert out["status"] == "idle"
    cur.execute(
        "SELECT d.filename, g.subject_id::text FROM documents d "
        "LEFT JOIN document_grants g ON g.document_id = d.id WHERE d.kb_id = %s ORDER BY 1",
        (kb,),
    )
    rows = cur.fetchall()
    # an empty allowed list is still restricted, nothing maps so nobody real holds it
    assert rows == [("Leave.txt", str(reader)), ("Travel.txt", str(uuid.UUID(int=0)))]
    with open(_docs(cur, kb)[0][2].replace("file://", ""), encoding="utf-8") as fh:
        assert "readers" not in fh.read()


def test_restricted_item_with_nobody_mapped_stays_closed(
    kb_conn, source_db, local_storage, allow_local
):
    url, src = source_db
    src.execute("UPDATE policies SET readers = 'stranger@elsewhere.example'")
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    creator = str(uuid.uuid4())
    sid = _source(
        cur,
        tenant,
        kb,
        "sql",
        _sql_config(acl_column="readers"),
        {"url": url},
        created_by=creator,
    )
    _run(sid)
    cur.execute(
        "SELECT DISTINCT g.subject_id::text FROM document_grants g JOIN documents d "
        "ON d.id = g.document_id WHERE d.kb_id = %s",
        (kb,),
    )
    assert [r[0] for r in cur.fetchall()] == [creator]


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM policies",
        "SELECT 1; DROP TABLE policies",
        "WITH x AS (DELETE FROM policies RETURNING *) SELECT * FROM x",
        "SELECT * INTO copy_of FROM policies",
    ],
)
def test_sql_query_must_read(query):
    with pytest.raises(conn_base.ConfigError):
        check_query(query)


def test_sql_word_inside_a_string_is_fine():
    assert (
        check_query("SELECT 'update me' AS a FROM t;")
        == "SELECT 'update me' AS a FROM t"
    )


def test_sql_read_only_transaction_stops_a_writing_function(
    kb_conn, source_db, local_storage, allow_local
):
    url, src = source_db
    src.execute(
        "CREATE FUNCTION wipe() RETURNS int LANGUAGE sql AS 'DELETE FROM policies RETURNING 1'"
    )
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    sid = _source(
        cur,
        tenant,
        kb,
        "sql",
        {"query": "SELECT id, wipe() AS w FROM policies", "id_column": "id"},
        {"url": url},
    )
    out, sent, _ = _run(sid)
    assert out["status"] == "failed" and sent == []
    src.execute("SELECT count(*) FROM policies")
    assert src.fetchone()[0] == 2


# filesystem


def test_filesystem_resumes_mid_listing_and_never_leaves_its_root(
    kb_conn, tmp_path, local_storage, monkeypatch
):
    root = tmp_path / "share"
    (root / "sub").mkdir(parents=True)
    for n in ("a.txt", "b.txt", "sub/c.txt"):
        (root / n).write_text(n)
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    os.symlink(secret, root / "link.txt")
    monkeypatch.setenv("KB_CONNECTOR_FS_ROOTS", str(root))
    monkeypatch.setattr("engine.kb_connectors.filesystem.PAGE", 2)
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    sid = _source(cur, tenant, kb, "filesystem", {"path": str(root)})

    # a zero slice stops after every page, the cursor has to carry the next one over
    seen_cursor = False
    ran = []
    for _ in range(10):
        out, sent, requeued = _run(sid, slice_seconds=0)
        ran.extend(a[3] for a in sent)
        if out["status"] != "continuing":
            break
        assert requeued == [sid]
        cur.execute(
            "SELECT page_cursor FROM kb_connector_sources WHERE id = %s", (sid,)
        )
        seen_cursor = seen_cursor or bool(cur.fetchone()[0])
    assert out["status"] == "idle" and seen_cursor
    assert sorted(ran) == ["a.txt", "b.txt", "c.txt"]
    cur.execute(
        "SELECT acl FROM kb_connector_items WHERE source_id = %s LIMIT 1", (sid,)
    )
    assert "mode" in cur.fetchone()[0]["posix"]

    (root / "a.txt").unlink()
    out, sent, _ = _run(sid)
    assert out["status"] == "idle" and sent == []
    assert [d[0] for d in _docs(cur, kb)] == ["b.txt", "c.txt"]


@pytest.mark.asyncio
async def test_filesystem_path_outside_the_roots_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_CONNECTOR_FS_ROOTS", str(tmp_path / "allowed"))
    with pytest.raises(conn_base.ConfigError, match="outside the allowed"):
        await FilesystemConnector({"path": "/etc"}, {}).validate()
    monkeypatch.delenv("KB_CONNECTOR_FS_ROOTS")
    with pytest.raises(conn_base.ConfigError, match="allows no folders"):
        await FilesystemConnector({"path": "/etc"}, {}).validate()


# fake transports only, these three have never been called for real


GRAPH_HOSTS = "graph.microsoft.com,login.microsoftonline.com"


def _graph_transport(state):
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        state["calls"].append(url)
        if "oauth2/v2.0/token" in url:
            assert b"client_credentials" in request.content
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer tok"
        if url.endswith("/sites/site1/drive"):
            return httpx.Response(200, json={"id": "drive1"})
        if "/root/delta" in url and "token=" not in url and "skip=" not in url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"id": "fold", "name": "Folder", "folder": {}},
                        {
                            "id": "f1",
                            "name": "one.txt",
                            "file": {},
                            "cTag": "c1",
                            "size": 5,
                            "lastModifiedDateTime": "2026-01-01T00:00:00Z",
                        },
                    ],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/drives/drive1/root/delta?skip=2",
                },
            )
        if "skip=2" in url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "f2",
                            "name": "two.txt",
                            "file": {},
                            "cTag": "c2",
                            "size": 5,
                        }
                    ],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/drives/drive1/root/delta?token=T1",
                },
            )
        if "token=T1" in url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "f1",
                            "name": "one.txt",
                            "deleted": {"state": "deleted"},
                        },
                        {
                            "id": "f2",
                            "name": "two.txt",
                            "file": {},
                            "cTag": "c3",
                            "size": 7,
                        },
                    ],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/drives/drive1/root/delta?token=T2",
                },
            )
        if "token=T2" in url:
            return httpx.Response(410, json={"error": {"code": "resyncRequired"}})
        if url.endswith("/permissions"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "roles": ["read"],
                            "grantedToV2": {
                                "user": {"id": "u1", "email": "reader@x.example"}
                            },
                        }
                    ]
                },
            )
        if url.endswith("/f2/content") and state.get("fail_f2"):
            return httpx.Response(503)
        if url.endswith("/content"):
            return httpx.Response(200, content=b"hello")
        return httpx.Response(404)

    return httpx.MockTransport(handle)


def _graph_source(cur, tenant, kb):
    return _source(
        cur,
        tenant,
        kb,
        "sharepoint",
        {"tenant_id": "t1", "client_id": "c1", "site_id": "site1"},
        {"client_secret": "s"},
    )


def test_graph_delta_lists_changes_and_deletes_and_captures_permissions(
    kb_conn, local_storage, monkeypatch
):
    monkeypatch.setenv("KB_CONNECTORS_ALLOWED_HOSTS", GRAPH_HOSTS)
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    sid = _graph_source(cur, tenant, kb)
    state = {"calls": []}
    options = {"transport": _graph_transport(state)}

    out, sent, _ = _run(sid, options=options)
    assert out["status"] == "idle", out
    assert sorted(a[3] for a in sent) == ["one.txt", "two.txt"]
    cur.execute("SELECT sync_cursor FROM kb_connector_sources WHERE id = %s", (sid,))
    assert cur.fetchone()[0]["delta"].endswith("token=T1")
    cur.execute(
        "SELECT acl FROM kb_connector_items WHERE source_id = %s LIMIT 1", (sid,)
    )
    acl = cur.fetchone()[0]
    assert (
        acl["public"] is False and acl["principals"][0]["email"] == "reader@x.example"
    )

    out, sent, _ = _run(sid, options=options)
    assert out["status"] == "idle"
    assert [a[3] for a in sent] == ["two.txt"]
    assert [d[0] for d in _docs(cur, kb)] == ["two.txt"]
    assert _state(cur, sid)["deleted"] == 1


def test_graph_expired_token_starts_over_instead_of_failing(
    kb_conn, local_storage, monkeypatch
):
    monkeypatch.setenv("KB_CONNECTORS_ALLOWED_HOSTS", GRAPH_HOSTS)
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    sid = _graph_source(cur, tenant, kb)
    cur.execute(
        "UPDATE kb_connector_sources SET sync_cursor = %s::jsonb WHERE id = %s",
        (
            json.dumps(
                {
                    "delta": "https://graph.microsoft.com/v1.0/drives/drive1/root/delta?token=T2"
                }
            ),
            sid,
        ),
    )
    out, sent, _ = _run(sid, options={"transport": _graph_transport({"calls": []})})
    assert out["status"] == "idle", out
    assert len(sent) == 2


def test_graph_failed_download_retries_keeps_the_token_and_recovers(
    kb_conn, local_storage, monkeypatch
):
    monkeypatch.setenv("KB_CONNECTORS_ALLOWED_HOSTS", GRAPH_HOSTS)
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    sid = _graph_source(cur, tenant, kb)
    state = {"calls": [], "fail_f2": True}
    options = {"transport": _graph_transport(state)}
    out, sent, _ = _run(sid, options=options)
    assert out["status"] == "idle"
    assert [a[3] for a in sent] == ["one.txt"]
    assert sum(1 for u in state["calls"] if u.endswith("/f2/content")) == 4
    items = _items(cur, sid)
    assert items["f2"][0] == "failed"
    cur.execute("SELECT sync_cursor FROM kb_connector_sources WHERE id = %s", (sid,))
    assert (cur.fetchone()[0] or {}).get("delta") is None

    state["fail_f2"] = False
    out, sent, _ = _run(sid, options=options)
    assert out["status"] == "idle"
    assert [a[3] for a in sent] == ["two.txt"]
    assert _items(cur, sid)["f2"][0] == "ok"
    cur.execute("SELECT sync_cursor FROM kb_connector_sources WHERE id = %s", (sid,))
    assert cur.fetchone()[0]["delta"].endswith("token=T1")


def test_a_redirect_to_an_internal_address_is_blocked(
    kb_conn, local_storage, monkeypatch
):
    monkeypatch.setenv("KB_CONNECTORS_ALLOWED_HOSTS", "wiki.example.com")
    monkeypatch.delenv("CONNECTORS_ALLOW_PRIVATE_TARGETS", raising=False)

    def handle(request):
        return httpx.Response(
            302, headers={"location": "http://169.254.169.254/latest/meta-data"}
        )

    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    sid = _source(
        cur,
        tenant,
        kb,
        "confluence",
        {"base_url": "https://wiki.example.com", "space_key": "ENG"},
        {"api_token": "t"},
    )
    out, sent, _ = _run(sid, options={"transport": httpx.MockTransport(handle)})
    assert out["status"] == "failed" and "private" in out["error"]
    assert sent == []


def test_confluence_versions_restrictions_and_removed_pages(
    kb_conn, local_storage, monkeypatch
):
    monkeypatch.setenv("KB_CONNECTORS_ALLOWED_HOSTS", "wiki.example.com")
    pages = {
        "1": {"title": "Runbook", "v": 1, "body": "<p>Restart it</p>", "users": []},
        "2": {
            "title": "Salaries",
            "v": 1,
            "body": "<p>Private</p>",
            "users": [{"accountId": "a1", "email": "boss@x.example"}],
        },
    }

    def handle(request):
        assert request.headers["authorization"].startswith("Basic ")
        assert request.url.params.get("spaceKey") == "ENG"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": k,
                        "title": p["title"],
                        "version": {
                            "number": p["v"],
                            "when": "2026-01-01T00:00:00.000Z",
                        },
                        "body": {"storage": {"value": p["body"]}},
                        "restrictions": {
                            "read": {"restrictions": {"user": {"results": p["users"]}}}
                        },
                    }
                    for k, p in pages.items()
                ],
                "_links": {},
            },
        )

    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    creator = str(uuid.uuid4())
    sid = _source(
        cur,
        tenant,
        kb,
        "confluence",
        {
            "base_url": "https://wiki.example.com/wiki",
            "space_key": "ENG",
            "email": "me@x.example",
        },
        {"api_token": "t"},
        created_by=creator,
    )
    options = {"transport": httpx.MockTransport(handle)}
    out, sent, _ = _run(sid, options=options)
    assert out["status"] == "idle", out
    assert sorted(a[3] for a in sent) == ["Runbook.md", "Salaries.md"]
    runbook = next(d for d in _docs(cur, kb) if d[0] == "Runbook.md")
    with open(runbook[2].replace("file://", ""), encoding="utf-8") as fh:
        text = fh.read()
    assert "Restart it" in text and "<p>" not in text
    cur.execute(
        "SELECT d.filename FROM document_grants g JOIN documents d ON d.id = g.document_id "
        "WHERE d.kb_id = %s",
        (kb,),
    )
    assert [r[0] for r in cur.fetchall()] == ["Salaries.md"]

    pages["1"]["v"] = 2
    pages["1"]["body"] = "<p>Restart it twice</p>"
    del pages["2"]
    out, sent, _ = _run(sid, options=options)
    assert out["status"] == "idle"
    assert [a[3] for a in sent] == ["Runbook.md"]
    assert [d[0] for d in _docs(cur, kb)] == ["Runbook.md"]


def _service_account():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return {"client_email": "svc@proj.iam.gserviceaccount.com", "private_key": pem}, key


def test_google_jwt_is_a_real_signature():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    account, key = _service_account()
    token = signed_jwt(account, "user@x.example", now=1000)
    head, body, sig = token.split(".")
    pad = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))  # noqa: E731
    claims = json.loads(pad(body))
    assert (
        claims["iss"] == account["client_email"] and claims["sub"] == "user@x.example"
    )
    assert claims["exp"] == 4600
    key.public_key().verify(
        pad(sig), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )


def test_google_drive_first_listing_then_changes(kb_conn, local_storage, monkeypatch):
    monkeypatch.setenv(
        "KB_CONNECTORS_ALLOWED_HOSTS", "www.googleapis.com,oauth2.googleapis.com"
    )
    account, _key = _service_account()
    exports = []

    def handle(request):
        url = str(request.url)
        path = request.url.path
        if path == "/token":
            assert b"jwt-bearer" in request.content
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer tok"
        if path.endswith("/changes/startPageToken"):
            return httpx.Response(200, json={"startPageToken": "S1"})
        if path.endswith("/drive/v3/files"):
            return httpx.Response(
                200,
                json={
                    "files": [
                        {
                            "id": "g1",
                            "name": "Plan",
                            "mimeType": "application/vnd.google-apps.document",
                            "modifiedTime": "2026-01-01T00:00:00Z",
                            "version": "4",
                            "permissions": [
                                {
                                    "type": "user",
                                    "emailAddress": "a@x.example",
                                    "role": "reader",
                                }
                            ],
                        },
                        {
                            "id": "g2",
                            "name": "notes.txt",
                            "mimeType": "text/plain",
                            "size": "5",
                            "md5Checksum": "m1",
                            "permissions": [{"type": "anyone", "role": "reader"}],
                        },
                        {
                            "id": "dir",
                            "name": "d",
                            "mimeType": "application/vnd.google-apps.folder",
                        },
                        {
                            "id": "x",
                            "name": "form",
                            "mimeType": "application/vnd.google-apps.form",
                        },
                    ]
                },
            )
        if path.endswith("/drive/v3/changes"):
            assert request.url.params["pageToken"] == "S1"
            return httpx.Response(
                200,
                json={
                    "newStartPageToken": "S2",
                    "changes": [
                        {"fileId": "g1", "removed": True},
                        {
                            "fileId": "g2",
                            "file": {
                                "id": "g2",
                                "name": "notes.txt",
                                "mimeType": "text/plain",
                                "size": "6",
                                "md5Checksum": "m2",
                                "permissions": [],
                            },
                        },
                    ],
                },
            )
        if path.endswith("/export"):
            exports.append(url)
            return httpx.Response(200, content=b"exported")
        return httpx.Response(200, content=b"bytes")

    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    sid = _source(
        cur,
        tenant,
        kb,
        "google_drive",
        {"folder_id": ""},
        {"service_account_json": json.dumps(account)},
    )
    options = {"transport": httpx.MockTransport(handle)}
    out, sent, _ = _run(sid, options=options)
    assert out["status"] == "idle", out
    assert sorted(a[3] for a in sent) == ["Plan.txt", "notes.txt"]
    assert "mimeType=text%2Fplain" in exports[0]
    cur.execute("SELECT sync_cursor FROM kb_connector_sources WHERE id = %s", (sid,))
    assert cur.fetchone()[0] == {"changes": "S1"}

    out, sent, _ = _run(sid, options=options)
    assert out["status"] == "idle"
    assert [a[3] for a in sent] == ["notes.txt"]
    assert [d[0] for d in _docs(cur, kb)] == ["notes.txt"]
    cur.execute("SELECT sync_cursor FROM kb_connector_sources WHERE id = %s", (sid,))
    assert cur.fetchone()[0] == {"changes": "S2"}


# wiring and the API


def test_saas_kinds_say_they_were_never_called_for_real():
    by_kind = {k["kind"]: k for k in describe()}
    assert set(by_kind) == {
        "s3",
        "azure_blob",
        "sharepoint",
        "confluence",
        "google_drive",
        "sql",
        "filesystem",
    }
    for kind in ("sharepoint", "confluence", "google_drive"):
        assert by_kind[kind]["verified_live"] is False
    for kind in ("s3", "azure_blob", "sql", "filesystem"):
        assert by_kind[kind]["verified_live"] is True


def _user(tenant, role="ADMIN"):
    from models.user import UserRole

    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant),
        role=UserRole[role],
        email="a@example.com",
    )


def _real_user(url, user):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from models.user import User

    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://"))
    with Session(engine) as session:
        session.add(
            User(
                id=user.id,
                tenant_id=user.tenant_id,
                email=f"{user.id.hex}@example.com",
                full_name="A",
                role=user.role,
                is_active=True,
            )
        )
        session.commit()
    engine.dispose()


@pytest.fixture
def session_factory(kb_db_url):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(
        kb_db_url.replace("postgresql://", "postgresql+asyncpg://")
    )
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_api_keeps_secrets_out_of_config_and_encrypted(
    kb_conn, kb_db_url, session_factory, monkeypatch, allow_local
):
    from app.routers import knowledge_connectors as api

    monkeypatch.setenv(
        "ABENIX_DATA_KEY_KEK_BASE64", base64.b64encode(b"k" * 32).decode()
    )
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    user = _user(tenant)
    _real_user(kb_db_url, user)
    body = api.ConnectorBody(
        name="Files",
        kind="s3",
        values={
            "bucket": "b",
            "endpoint_url": "http://127.0.0.1:9",
            "secret_key": "supersecretvalue",
            "access_key": "AKIA",
        },
        cadence_minutes=30,
    )

    async def nolog(*a, **k):
        return None

    monkeypatch.setattr(api, "log_action", nolog)
    with patch("app.services.kb_connectors.send_task") as send:
        async with session_factory() as db:
            resp = await api.create_connector(
                uuid.UUID(kb), body, None, user=user, db=db
            )
    assert resp.status_code == 201, resp.body
    data = json.loads(resp.body)["data"]
    assert "supersecretvalue" not in resp.body.decode()
    assert send.call_args[0][0] == sync.TASK_NAME
    cur.execute(
        "SELECT config::text, credential_key FROM kb_connector_sources WHERE id = %s",
        (data["id"],),
    )
    config, key = cur.fetchone()
    assert "supersecretvalue" not in config and "AKIA" not in config
    cur.execute("SELECT value FROM tenant_tool_credentials WHERE key = %s", (key,))
    stored = cur.fetchone()[0]
    assert "supersecretvalue" not in stored

    from engine import credentials

    assert (
        json.loads(credentials.decode_stored(stored))["secret_key"]
        == "supersecretvalue"
    )

    async with session_factory() as db:
        resp = await api.delete_connector(
            uuid.UUID(kb), uuid.UUID(data["id"]), user=user, db=db
        )
    assert resp.status_code == 200
    cur.execute("SELECT count(*) FROM tenant_tool_credentials WHERE key = %s", (key,))
    assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_api_refuses_a_private_target_and_a_non_admin_filesystem(
    kb_conn, session_factory, monkeypatch
):
    from app.routers import knowledge_connectors as api

    monkeypatch.delenv("KB_CONNECTORS_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("CONNECTORS_ALLOW_PRIVATE_TARGETS", raising=False)
    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    user = _user(tenant)
    async with session_factory() as db:
        resp = await api.create_connector(
            uuid.UUID(kb),
            api.ConnectorBody(
                name="x",
                kind="confluence",
                values={
                    "base_url": "http://10.0.0.5/wiki",
                    "space_key": "E",
                    "api_token": "t",
                },
            ),
            None,
            user=user,
            db=db,
        )
    assert resp.status_code == 400 and b"private" in resp.body

    member = _user(tenant, "USER")
    config, secrets, refused = await api._validated(
        "filesystem", {"path": "/mnt"}, member
    )
    assert refused is not None and refused.status_code == 403

    _c, _s, refused = await api._validated("sharepoint", {"tenant_id": "t"}, user)
    assert refused.status_code == 400 and b"required" in refused.body


@pytest.mark.asyncio
async def test_due_sources_are_claimed_once_and_stuck_ones_resent(
    kb_conn, session_factory
):
    from datetime import datetime, timedelta, timezone

    from app.services import kb_connectors as svc

    cur = kb_conn.cursor()
    tenant, kb = _setup(cur)
    due = _source(cur, tenant, kb, "s3", {"bucket": "b"})
    later = _source(cur, tenant, kb, "s3", {"bucket": "b"})
    stuck = _source(cur, tenant, kb, "s3", {"bucket": "b"})
    cur.execute(
        "UPDATE kb_connector_sources SET status = 'idle', next_sync_at = now() - interval '1 minute' "
        "WHERE id = %s",
        (due,),
    )
    cur.execute(
        "UPDATE kb_connector_sources SET status = 'idle', next_sync_at = now() + interval '1 hour' "
        "WHERE id = %s",
        (later,),
    )
    cur.execute(
        "UPDATE kb_connector_sources SET status = 'running', "
        "updated_at = now() - interval '2 hours' WHERE id = %s",
        (stuck,),
    )
    now = datetime.now(timezone.utc)
    async with session_factory() as db:
        async with db.begin():
            claimed = await svc.claim_due(db, now)
            resent = await svc.stuck_sources(db, now)
    assert uuid.UUID(due) in claimed and uuid.UUID(later) not in claimed
    assert uuid.UUID(stuck) in resent
    async with session_factory() as db:
        async with db.begin():
            again = await svc.claim_due(db, now + timedelta(seconds=1))
    assert uuid.UUID(due) not in again


def test_the_job_is_in_the_catalogue_and_the_routes_are_mounted():
    from app.core import job_runs, scheduler
    from app.routers import knowledge_connectors

    assert "knowledge_ops" in set(job_runs.CATALOGUE)
    assert scheduler._knowledge_ops
    paths = {r.path for r in knowledge_connectors.router.routes}
    assert "/api/knowledge-bases/{kb_id}/connectors/{source_id}/sync" in paths
