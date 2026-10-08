"""GDPR purge: the Neo4j step deletes the person's Cognify entities and logs a true count."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import gdpr_purge
from app.services.gdpr_purge import Subject

TENANT = uuid.uuid4()
USER = uuid.uuid4()
KB1, KB2 = str(uuid.uuid4()), str(uuid.uuid4())


def _subject(**kw) -> Subject:
    base = dict(
        tenant_id=TENANT,
        user_id=USER,
        emails=["jane.doe@acme.com"],
        names=["jane doe"],
        kb_ids=[KB1, KB2],
    )
    base.update(kw)
    return Subject(**base)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def __aiter__(self):
        self._it = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def run(self, cypher, **params):
        self.calls.append((cypher, params))
        return _Result(self.rows)


def _db(scalar=0):
    db = MagicMock()
    res = MagicMock()
    res.scalar.return_value = scalar
    res.rowcount = 0
    db.execute = AsyncMock(return_value=res)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _sql(db) -> list[str]:
    return [str(c.args[0]) for c in db.execute.call_args_list]


@pytest.mark.asyncio
async def test_neo4j_step_deletes_matching_entities_and_counts_them():
    rows = [
        {"kb_id": KB1, "name": "Jane Doe"},
        {"kb_id": KB2, "name": "jane.doe@acme.com"},
    ]
    session = _Session(rows)
    db = _db()
    with patch(
        "engine.knowledge.neo4j_client.is_neo4j_available",
        AsyncMock(return_value=True),
    ), patch(
        "engine.knowledge.neo4j_client.get_neo4j_session",
        AsyncMock(return_value=session),
    ):
        n = await gdpr_purge._purge_neo4j(db, _subject())

    assert n == 2
    cypher, params = session.calls[0]
    assert "MATCH (e:Entity)" in cypher
    assert "e.kb_id IN $kb_ids" in cypher
    assert "DETACH DELETE e" in cypher
    assert params == {
        "kb_ids": [KB1, KB2],
        "emails": ["jane.doe@acme.com"],
        "names": ["jane doe"],
    }
    sql = _sql(db)
    assert any("DELETE FROM graph_relationships" in s for s in sql)
    assert any("DELETE FROM graph_entities" in s for s in sql)
    assert any("UPDATE knowledge_collections" in s for s in sql)


@pytest.mark.asyncio
async def test_neo4j_step_with_nothing_to_match_does_not_touch_the_graph():
    db = _db()
    get_session = AsyncMock()
    with patch("engine.knowledge.neo4j_client.get_neo4j_session", get_session):
        n = await gdpr_purge._purge_neo4j(db, _subject(emails=[], names=[]))
    assert n == 0
    get_session.assert_not_called()


@pytest.mark.asyncio
async def test_unreachable_neo4j_fails_when_entities_are_left():
    db = _db(scalar=3)
    with patch(
        "engine.knowledge.neo4j_client.is_neo4j_available",
        AsyncMock(return_value=False),
    ):
        with pytest.raises(RuntimeError, match="3 graph entities"):
            await gdpr_purge._purge_neo4j(db, _subject())


@pytest.mark.asyncio
async def test_unreachable_neo4j_with_nothing_left_is_zero():
    db = _db(scalar=0)
    with patch(
        "engine.knowledge.neo4j_client.is_neo4j_available",
        AsyncMock(return_value=False),
    ):
        assert await gdpr_purge._purge_neo4j(db, _subject()) == 0


@pytest.mark.asyncio
async def test_purge_user_logs_the_count_each_store_reported():
    db = _db()
    added = []
    db.add = added.append

    async def neo(db_, s):
        return 7

    async def zero(db_, s):
        return 0

    async def boom(db_, s):
        raise RuntimeError("pinecone down")

    purgers = {
        "postgres": zero,
        "pinecone": boom,
        "neo4j": neo,
        "blob": zero,
        "trajectory": zero,
    }
    with patch.object(gdpr_purge, "_PURGERS", purgers), patch.object(
        gdpr_purge, "load_subject", AsyncMock(return_value=_subject())
    ):
        receipt = await gdpr_purge.purge_user(
            db, tenant_id=TENANT, subject_user_id=USER
        )

    assert receipt["neo4j"] == {"status": "completed", "affected": 7}
    assert receipt["pinecone"]["status"] == "failed"
    done = {r.store: r for r in added if r.status != "started"}
    assert done["neo4j"].affected_count == 7
    assert done["neo4j"].status == "completed"
    assert done["pinecone"].affected_count is None
    assert "pinecone down" in done["pinecone"].error


@pytest.mark.asyncio
async def test_load_subject_skips_single_word_names_and_reads_vectors():
    db = MagicMock()
    user_row = MagicMock()
    user_row.first.return_value = ("Jane.Doe@Acme.com", "Admin")
    kbs = MagicMock()
    kbs.all.return_value = [(KB1,)]
    vecs = MagicMock()
    vecs.all.return_value = [("item:0",), ("item:1",)]
    db.execute = AsyncMock(side_effect=[user_row, kbs, vecs])
    s = await gdpr_purge.load_subject(db, TENANT, USER)
    assert s.emails == ["jane.doe@acme.com"]
    assert s.names == []
    assert s.kb_ids == [KB1]
    assert s.persona_vector_ids == ["item:0", "item:1"]


@pytest.mark.asyncio
async def test_pinecone_step_deletes_the_persona_vectors(monkeypatch):
    monkeypatch.setenv("PINECONE_API_KEY", "k")
    seen = {}

    def fake_delete(tenant_id, ids):
        seen["args"] = (tenant_id, ids)
        return len(ids)

    monkeypatch.setattr(gdpr_purge, "_delete_persona_vectors", fake_delete)
    n = await gdpr_purge._purge_pinecone(
        _db(), _subject(persona_vector_ids=["a:0", "a:1"])
    )
    assert n == 2
    assert seen["args"] == (str(TENANT), ["a:0", "a:1"])


@pytest.mark.asyncio
async def test_pinecone_step_without_a_key_fails_loudly(monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PINECONE_API_KEY"):
        await gdpr_purge._purge_pinecone(_db(), _subject(persona_vector_ids=["a:0"]))
    assert await gdpr_purge._purge_pinecone(_db(), _subject()) == 0


@pytest.mark.asyncio
async def test_postgres_step_only_touches_the_subjects_agent_memories():
    db = _db()
    with patch("app.services.audit_chain.maintenance", AsyncMock()):
        await gdpr_purge._purge_postgres(db, _subject())
    memory_sql = next(s for s in _sql(db) if "agent_memories" in s)
    assert "agent_memories.tenant_id" in memory_sql
    assert "agents.creator_id" in memory_sql


def _counting_db(rowcounts: dict[str, int]):
    """rowcount per statement, picked by the first key found in the SQL."""
    db = MagicMock()

    async def execute(stmt, params=None):
        sql = str(stmt)
        res = MagicMock()
        res.rowcount = next((n for k, n in rowcounts.items() if k in sql), 0)
        return res

    db.execute = AsyncMock(side_effect=execute)
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_postgres_step_erases_what_the_person_typed_and_counts_it():
    db = _counting_db(
        {
            "UPDATE messages": 5,
            "UPDATE conversations": 2,
            "UPDATE executions SET input_message": 3,
        }
    )
    with patch("app.services.audit_chain.maintenance", AsyncMock()):
        n = await gdpr_purge._purge_postgres(db, _subject())
    assert n == 10
    calls = {
        str(c.args[0]): c.args[1] for c in db.execute.call_args_list if len(c.args) > 1
    }
    msg_sql = next(s for s in calls if "UPDATE messages" in s)
    # both sides of the person's own conversations go
    assert "role = 'user'" not in msg_sql
    assert "content = :erased" in msg_sql and "blocks = NULL" in msg_sql
    assert "conversations WHERE user_id = :uid AND tenant_id = :t" in msg_sql
    assert calls[msg_sql] == {
        "uid": str(USER),
        "t": str(TENANT),
        "erased": gdpr_purge.ERASED,
    }
    conv_sql = next(s for s in calls if "UPDATE conversations" in s)
    assert "title = :erased" in conv_sql and "share_token = NULL" in conv_sql
    run_sql = next(s for s in calls if "SET input_message = :erased" in s)
    assert "output_message = NULL" in run_sql and "execution_trace = NULL" in run_sql
    assert "node_results = NULL" in run_sql and "tool_calls = NULL" in run_sql


@pytest.mark.asyncio
async def test_postgres_step_keeps_the_not_null_user_links():
    db = _counting_db({})
    with patch("app.services.audit_chain.maintenance", AsyncMock()):
        await gdpr_purge._purge_postgres(db, _subject())
    sql = _sql(db)
    assert not any("SET user_id=NULL" in s or "SET user_id = NULL" in s for s in sql)
    # audit rows keep their digest, only the salt and the raw identifiers go
    audit = next(s for s in sql if "activity_logs" in s)
    assert "pii_salt=NULL" in audit and "pii_digest" not in audit
    assert "details" not in audit


@pytest.mark.asyncio
async def test_erase_skips_rows_already_erased():
    for sql in (
        gdpr_purge._ERASE_MESSAGES,
        gdpr_purge._ERASE_CONVERSATIONS,
        gdpr_purge._ERASE_RUN_INPUTS,
    ):
        assert "<> :erased" in str(sql)


def _write(folder, name, body):
    import json as _json

    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(_json.dumps(body), encoding="utf-8")


@pytest.mark.asyncio
async def test_trajectory_step_deletes_the_persons_records(tmp_path, monkeypatch):
    runtime, wingman = tmp_path / "traj", tmp_path / "wm"
    monkeypatch.setenv("TRAJECTORY_DIR", str(runtime))
    monkeypatch.setenv("WINGMAN_TRAJECTORY_DIR", str(wingman))
    run_a, run_b, other_run = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    other_tenant = str(uuid.uuid4())
    _write(runtime / str(TENANT), "t1", {"execution_id": run_a, "intent": "x"})
    _write(runtime / str(TENANT), "t2", {"execution_id": other_run, "intent": "y"})
    _write(runtime / "shared", "t3", {"user_id": str(USER), "intent": "z"})
    _write(wingman / "shared", "t4", {"execution_id": run_b, "intent": "w"})
    _write(runtime / other_tenant, "t5", {"execution_id": run_a})
    (runtime / str(TENANT) / "broken.json").write_text("{nope", encoding="utf-8")

    db = MagicMock()
    rows = MagicMock()
    rows.all.return_value = [(run_a,), (run_b,)]
    db.execute = AsyncMock(return_value=rows)

    n = await gdpr_purge._purge_trajectory(db, _subject())

    assert n == 3
    assert not (runtime / str(TENANT) / "t1.json").exists()
    assert not (runtime / "shared" / "t3.json").exists()
    assert not (wingman / "shared" / "t4.json").exists()
    assert (runtime / str(TENANT) / "t2.json").exists()
    assert (runtime / other_tenant / "t5.json").exists()
    assert (runtime / str(TENANT) / "broken.json").exists()
    sql, params = str(db.execute.call_args.args[0]), db.execute.call_args.args[1]
    assert "FROM executions WHERE user_id = :uid AND tenant_id = :t" in sql
    assert params == {"uid": str(USER), "t": str(TENANT)}


@pytest.mark.asyncio
async def test_trajectory_step_with_no_store_is_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAJECTORY_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("WINGMAN_TRAJECTORY_DIR", str(tmp_path / "missing2"))
    db = MagicMock()
    rows = MagicMock()
    rows.all.return_value = []
    db.execute = AsyncMock(return_value=rows)
    assert await gdpr_purge._purge_trajectory(db, _subject()) == 0


@pytest.mark.asyncio
async def test_postgres_step_only_sets_user_columns_that_exist():
    import re

    from models.user import User

    db = _counting_db({})
    with patch("app.services.audit_chain.maintenance", AsyncMock()):
        await gdpr_purge._purge_postgres(db, _subject())
    users_sql = next(s for s in _sql(db) if s.lstrip().startswith("UPDATE users SET"))
    set_clause = users_sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
    cols = re.findall(r"(\w+)\s*=", set_clause)
    assert cols and "password_hash" in cols
    missing = [c for c in cols if c not in User.__table__.columns]
    assert not missing, missing
