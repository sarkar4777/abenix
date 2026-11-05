"""Bounded memory, rate limits, wider formats and the small rules of large collections."""

from __future__ import annotations

import asyncio
import inspect
import struct
import sys
import time
import tracemalloc
import types
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from engine.knowledge import embed_gate, hybrid_search as hs, reranker
from engine.knowledge.extractors import streaming
from engine.knowledge.extractors.dispatch import extract_document
from worker.tasks import document_processor as dp

ROOT = Path(__file__).resolve().parents[2]


# chunking


def _old_style(text, size=200, overlap=20):
    return dp._chunk_text(text, chunk_size=size, chunk_overlap=overlap)


def test_a_small_file_chunks_the_same_as_the_whole_file_path():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 40 for i in range(50))
    got = [c for c, _p in dp._iter_chunks([(text, None, False)], 200, 20)]
    assert got == _old_style(text)


def test_a_file_cut_into_windows_loses_no_text():
    text = "\n\n".join(f"unique{i} " + "padding " * 30 for i in range(400))
    blocks = [(text[i : i + 1000], 1, i > 0) for i in range(0, len(text), 1000)]
    chunks = list(dp._iter_chunks(blocks, 200, 20, window=2000))
    joined = " ".join(c for c, _p in chunks)
    for i in range(400):
        assert f"unique{i} " in joined
    assert all(len(c) <= 200 for c, _p in chunks)
    assert {p for _c, p in chunks} == {1}


def test_text_with_no_separators_still_makes_progress():
    blocks = [("x" * 500, None, i > 0) for i in range(20)]
    chunks = list(dp._iter_chunks(blocks, 100, 0, window=300))
    assert sum(len(c) for c, _p in chunks) == 10000


def test_pages_stay_separate_and_keep_their_number():
    chunks = list(
        dp._iter_chunks([("one " * 10, 1, False), ("two " * 10, 2, False)], 1000, 0)
    )
    assert [p for _c, p in chunks] == [1, 2]


def test_a_large_text_file_is_streamed_in_bounded_memory(tmp_path):
    source = tmp_path / "big.txt"
    with open(source, "w") as fh:
        for i in range(600):
            fh.write(("sentence number %d. " % i) * 2000)
    size = source.stat().st_size
    assert size > 20_000_000
    dp._splitter(100, 0)
    tracemalloc.start()
    count = 0
    for _ in dp._iter_chunks(streaming.iter_text(str(source)), 1000, 200):
        count += 1
    _now, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert count > 25000
    # the whole file path needed the file plus every chunk, this holds about a window
    assert peak < 8_000_000, f"peak {peak} of {size}"


def test_batches_skip_what_the_checkpoint_holds():
    chunks = iter((f"c{i}", None) for i in range(250))
    batches = list(dp._batches(chunks, 120))
    assert batches[0][0] == 120 and batches[0][1][0] == "c120"
    assert [len(b[1]) for b in batches] == [100, 30]
    assert batches[1][0] == 220


def test_storage_download_does_not_read_the_file_into_memory(monkeypatch, tmp_path):
    src = inspect.getsource(dp._local_path)
    assert "download_to_file" in src and ".download(" not in src


def test_local_files_are_read_in_place(monkeypatch):
    assert dp._local_path("file:///data/x.txt", "txt") == ("/data/x.txt", None)


# wider formats


def test_html_keeps_text_and_drops_script(tmp_path):
    path = tmp_path / "a.html"
    path.write_text(
        "<html><head><title>t</title><style>x{}</style></head><body><h1>Hello</h1>"
        "<script>alert(1)</script><p>World &amp; more</p></body></html>"
    )
    text = "".join(b[0] for b in streaming.iter_html(str(path)))
    assert "Hello" in text and "World & more" in text
    assert "alert" not in text and "x{}" not in text


def test_xlsx_is_read_sheet_by_sheet(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.append(["name", "value"])
    book.active.append(["alpha", 1])
    second = book.create_sheet("two")
    second.append(["beta", 2])
    path = tmp_path / "a.xlsx"
    book.save(path)
    blocks = list(streaming.iter_xlsx(str(path)))
    assert "alpha\t1" in blocks[0][0] and blocks[0][1] == 1
    assert "beta\t2" in blocks[1][0] and blocks[1][1] == 2


def test_pptx_is_read_slide_by_slide(tmp_path):
    pptx = pytest.importorskip("pptx")
    deck = pptx.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[0])
    slide.shapes.title.text = "Revenue grew"
    slide.notes_slide.notes_text_frame.text = "speaker note"
    path = tmp_path / "a.pptx"
    deck.save(path)
    blocks = list(streaming.iter_pptx(str(path)))
    assert blocks[0][1] == 1
    assert "Revenue grew" in blocks[0][0] and "speaker note" in blocks[0][0]


def _minimal_msg(path: Path, streams: dict[str, bytes]) -> None:
    """A real compound file, every stream past the mini stream cutoff to keep it short."""
    sector = 512
    data = b""
    entries = []
    next_sector = 0
    for name, raw in sorted(streams.items(), key=lambda e: (len(e[0]), e[0].upper())):
        body = raw.ljust(4096, b"\x00")
        count = -(-len(body) // sector)
        entries.append((name, next_sector, len(body)))
        data += body.ljust(count * sector, b"\x00")
        next_sector += count
    dir_sectors = -(-(len(entries) + 1) * 128 // sector)
    dir_start = next_sector
    fat_start = dir_start + dir_sectors
    fat = []
    for _name, start, length in entries:
        count = -(-length // sector)
        fat += [start + i + 1 for i in range(count - 1)] + [0xFFFFFFFE]
    fat += [dir_start + i + 1 for i in range(dir_sectors - 1)] + [0xFFFFFFFE]
    fat += [0xFFFFFFFD]
    fat += [0xFFFFFFFF] * (sector // 4 - len(fat))

    def entry(name, kind, child, right, start, size):
        raw = name.encode("utf-16-le")
        return (
            raw.ljust(64, b"\x00")
            + struct.pack("<HBB", len(raw) + 2, kind, 1)
            + struct.pack("<III", 0xFFFFFFFF, right, child)
            + b"\x00" * 16
            + struct.pack("<I", 0)
            + b"\x00" * 16
            + struct.pack("<III", start, size, 0)
        )

    directory = entry("Root Entry", 5, 1, 0xFFFFFFFF, 0xFFFFFFFE, 0)
    # a chain of right siblings is a legal, if unbalanced, directory tree
    for i, (name, start, length) in enumerate(entries):
        right = i + 2 if i + 1 < len(entries) else 0xFFFFFFFF
        directory += entry(name, 2, 0xFFFFFFFF, right, start, length)
    directory = directory.ljust(dir_sectors * sector, b"\x00")
    header = (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        + b"\x00" * 16
        + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6)
        + b"\x00" * 6
        + struct.pack("<II", 0, 1)
        + struct.pack("<II", dir_start, 0)
        + struct.pack("<I", 4096)
        + struct.pack("<II", 0xFFFFFFFE, 0)
        + struct.pack("<II", 0xFFFFFFFE, 0)
        + struct.pack("<I", fat_start)
        + struct.pack("<I", 0xFFFFFFFF) * 108
    )
    path.write_bytes(
        header.ljust(sector, b"\x00")
        + data
        + directory
        + struct.pack(f"<{len(fat)}I", *fat)
    )


def test_outlook_msg_gives_subject_sender_and_body(tmp_path):
    pytest.importorskip("olefile")
    path = tmp_path / "a.msg"
    _minimal_msg(
        path,
        {
            "__substg1.0_0037001F": "Quarterly numbers".encode("utf-16-le"),
            "__substg1.0_0C1A001F": "Ana Silva".encode("utf-16-le"),
            "__substg1.0_1000001F": "The body of the mail.".encode("utf-16-le"),
        },
    )
    text = "".join(b[0] for b in streaming.iter_msg(str(path)))
    assert "Subject: Quarterly numbers" in text
    assert "From: Ana Silva" in text
    assert "The body of the mail." in text


def test_a_binary_msg_no_longer_falls_through_to_utf8_garbage(tmp_path):
    pytest.importorskip("olefile")
    path = tmp_path / "broken.msg"
    path.write_bytes(b"\xff\xfe not a compound file \x00\x01")
    blocks, method, quality = asyncio.run(extract_document(str(path), file_type="msg"))
    assert blocks == [] and method == "msg" and quality == 0.0


def test_office_formats_work_with_unstructured_missing(tmp_path, monkeypatch):
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setitem(sys.modules, "unstructured", None)
    monkeypatch.setitem(sys.modules, "unstructured.partition.auto", None)
    book = openpyxl.Workbook()
    book.active.append(["kept"])
    path = tmp_path / "a.xlsx"
    book.save(path)
    blocks, method, _q = asyncio.run(extract_document(str(path), file_type="xlsx"))
    assert method == "xlsx" and "kept" in blocks[0].text


def test_every_accepted_extension_has_a_reader_in_the_worker_image():
    from app.services import kb_ingest

    declared = (ROOT / "apps/worker/pyproject.toml").read_text()
    for needed in ("openpyxl", "python-pptx", "olefile"):
        assert needed in declared
    for ext in kb_ingest.ALLOWED_EXTENSIONS:
        if ext in ("pdf", "docx"):
            continue
        assert ext in streaming.TEXT_EXTENSIONS or ext in streaming.STREAMED_OFFICE


# rate limits


class _Api(Exception):
    def __init__(self, status_code, message="x", headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = types.SimpleNamespace(headers=headers or {})


def test_retry_after_is_read_from_seconds_ms_and_dates():
    assert embed_gate.retry_after_seconds(_Api(429, headers={"retry-after": "7"})) == 7
    assert (
        embed_gate.retry_after_seconds(_Api(429, headers={"retry-after-ms": "1500"}))
        == 1.5
    )
    from email.utils import formatdate

    soon = formatdate(time.time() + 30, usegmt=True)
    assert (
        20
        < embed_gate.retry_after_seconds(_Api(429, headers={"retry-after": soon}))
        <= 30
    )
    assert embed_gate.retry_after_seconds(Exception("no response")) is None


def test_local_bucket_makes_callers_wait_for_tokens():
    gate = embed_gate.RateGate("t", 60, 600, client=None)
    gate._client_loaded = True
    assert gate.wait_needed(600) == 0
    wait = gate.wait_needed(60)
    assert 5.5 < wait < 6.5


def test_a_budget_refused_many_times_recovers_because_refusals_cost_nothing():
    gate = embed_gate.RateGate("b", 60, 10**9, client=None)
    gate._client_loaded = True
    for _ in range(60):
        assert gate.try_acquire()
    for _ in range(500):
        assert not gate.try_acquire()
    bucket = gate._local["requests"]
    assert bucket.tokens > -1


class _FakeRedis:
    def __init__(self):
        self.keys = {}
        self.evals = []

    def eval(self, script, n, key, rate, cap, need, strict):
        self.evals.append((key, rate, cap, need, strict))
        return b"0"

    def pttl(self, key):
        return self.keys.get(key, -2)

    def set(self, key, value, px):
        self.keys[key] = px


def test_a_pause_is_shared_and_a_shorter_hint_does_not_cut_it():
    redis = _FakeRedis()
    one = embed_gate.RateGate("p", 60, 600, client=redis)
    two = embed_gate.RateGate("p", 60, 600, client=redis)
    one.pause(30)
    assert 29 < two.pause_remaining() <= 30
    two.pause(5)
    assert 29 < one.pause_remaining() <= 30


def test_a_dead_redis_falls_back_to_a_local_limit():
    class Dead:
        def eval(self, *a):
            raise ConnectionError("down")

        def pttl(self, key):
            raise ConnectionError("down")

    gate = embed_gate.RateGate("d", 60, 600, client=Dead())
    assert gate.wait_needed(1) == 0


@pytest.mark.skipif(
    not __import__("os").environ.get("KB_TEST_REDIS_URL"),
    reason="set KB_TEST_REDIS_URL to run the bucket script on a real Redis",
)
def test_two_gates_share_one_bucket_on_real_redis():
    import os

    import redis

    client = redis.Redis.from_url(os.environ["KB_TEST_REDIS_URL"])
    name = f"t{uuid.uuid4().hex}"
    one = embed_gate.RateGate(name, 60, 600, client=client)
    two = embed_gate.RateGate(name, 60, 600, client=client)
    assert one.wait_needed(600) == 0
    # the second process sees what the first one spent
    assert 5 < two.wait_needed(60) < 7
    one.pause(2)
    assert 1 < two.pause_remaining() <= 2


def test_a_429_honours_retry_after_and_holds_every_worker(monkeypatch):
    slept = []
    gate = embed_gate.RateGate("h", 6000, 10**9, client=None)
    gate._client_loaded = True
    monkeypatch.setitem(embed_gate._GATES, "h", gate)
    monkeypatch.setattr(embed_gate, "embed_gate", lambda p: gate)
    monkeypatch.setattr(embed_gate.time, "sleep", lambda s: slept.append(s))
    answers = [_Api(429, "slow down", {"retry-after": "3"}), "ok"]

    def call():
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert dp._call_provider("h", ["a"], call) == "ok"
    assert any(2.5 < s <= 3 for s in slept)


def test_a_long_retry_after_goes_back_to_the_queue_with_the_hint(monkeypatch):
    gate = embed_gate.RateGate("l", 6000, 10**9, client=None)
    gate._client_loaded = True
    monkeypatch.setattr(embed_gate, "embed_gate", lambda p: gate)
    monkeypatch.setattr(embed_gate.time, "sleep", lambda s: None)

    def call():
        raise _Api(429, "slow down", {"retry-after": "120"})

    with pytest.raises(_Api):
        dp._call_provider("l", ["a"], call)
    wrapped = dp.EmbeddingProviderCallFailed(
        "x", _Api(429, "x", {"retry-after": "120"})
    )
    assert wrapped.retry_after == 120 and wrapped.refused is False


def test_a_refused_key_is_not_retried(monkeypatch):
    calls = []

    def call():
        calls.append(1)
        raise _Api(401, "bad key")

    gate = embed_gate.RateGate("r", 6000, 10**9, client=None)
    gate._client_loaded = True
    monkeypatch.setattr(embed_gate, "embed_gate", lambda p: gate)
    with pytest.raises(_Api):
        dp._call_provider("r", ["a"], call)
    assert calls == [1]


def test_the_sdk_does_not_sleep_on_its_own(monkeypatch):
    seen = {}

    class Client:
        def __init__(self, api_key=None):
            self.embeddings = self
            seen["client"] = self

        def create(self, **kw):
            return types.SimpleNamespace(
                data=[types.SimpleNamespace(embedding=[0.1]) for _ in kw["input"]]
            )

    import openai

    gate = embed_gate.RateGate("s", 6000, 10**9, client=None)
    gate._client_loaded = True
    monkeypatch.setattr(embed_gate, "embed_gate", lambda p: gate)
    monkeypatch.setattr(dp, "OPENAI_API_KEY", "sk")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(openai, "OpenAI", Client)
    dp._embed_chunks(["a", "b"], "text-embedding-3-small")
    assert seen["client"].max_retries == 0


# pinecone


def _pinecone(monkeypatch, matches):
    seen = []

    class _Match:
        def __init__(self, doc, score):
            self.score = score
            self.metadata = {
                "doc_id": doc,
                "text": doc,
                "filename": "f",
                "chunk_index": 0,
            }

    class _Index:
        def query(self, **kw):
            seen.append(kw)
            return types.SimpleNamespace(matches=[_Match(d, s) for d, s in matches])

    fake = types.ModuleType("pinecone")
    fake.Pinecone = lambda api_key: types.SimpleNamespace(Index=lambda name: _Index())
    monkeypatch.setitem(sys.modules, "pinecone", fake)
    monkeypatch.setenv("PINECONE_API_KEY", "pc")
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    monkeypatch.setattr(hs, "_embed_query", AsyncMock(return_value=[0.1] * 4))
    from engine.knowledge import kb_state

    monkeypatch.setattr(kb_state, "live_generations", AsyncMock(return_value=None))
    return seen


def test_pinecone_filter_stays_under_the_limit_past_10k_hidden(monkeypatch):
    from engine.knowledge import document_acl

    open_doc, gone = str(uuid.uuid4()), str(uuid.uuid4())
    seen = _pinecone(monkeypatch, [(open_doc, 0.9), (gone, 0.8)])
    checked = {}

    async def among(ids, hidden, kb_ids):
        checked["ids"] = set(ids)
        return {gone}

    monkeypatch.setattr(document_acl, "hidden_among", among)
    hidden = {str(uuid.uuid4()) for _ in range(12000)}
    out = asyncio.run(hs._vector_search_pinecone("q", ["kb"], 5, None, hidden))
    query = seen[0]
    assert "doc_id" not in query["filter"]
    assert query["filter"]["superseded"] == {"$ne": True}
    assert query["top_k"] == 15
    # the check is sized by the results, not by the hidden set
    assert checked["ids"] == {open_doc, gone}
    assert [r.metadata["doc_id"] for r in out] == [open_doc]


def test_pinecone_short_list_is_still_sent(monkeypatch):
    doc = str(uuid.uuid4())
    seen = _pinecone(monkeypatch, [])
    asyncio.run(hs._vector_search_pinecone("q", ["kb"], 5, None, {doc}))
    assert seen[0]["filter"]["doc_id"] == {"$nin": [doc]}
    assert seen[0]["top_k"] == 5


def test_replacing_a_document_stamps_its_vectors(monkeypatch):
    from worker.tasks import pinecone_vacuum

    updates = []
    index = types.SimpleNamespace(update=lambda **kw: updates.append(kw))
    fake = types.ModuleType("pinecone")
    fake.Pinecone = lambda api_key: types.SimpleNamespace(Index=lambda name: index)
    monkeypatch.setitem(sys.modules, "pinecone", fake)
    monkeypatch.setattr(dp, "PINECONE_API_KEY", "pc")
    out = pinecone_vacuum.stamp_superseded("kb", "doc", 3, 2)
    assert out["stamped"] == 3
    assert updates[0]["id"] == "doc_0" and updates[2]["id"] == "doc_2"
    assert updates[0]["set_metadata"] == {"superseded": True}
    assert updates[0]["namespace"] == "kb.g2"


# acl


def test_bounded_hidden_lookup_caps_the_ids_it_sends():
    from engine.knowledge import document_acl

    class _Row:
        def first(self):
            return (5000, "123", ["a", "b"])

    class _Session:
        async def execute(self, stmt):
            self.params = stmt.compile().params
            self.sql = str(stmt)
            return _Row()

    session = _Session()
    out = asyncio.run(
        document_acl._bounded(
            session, document_acl._SUPERSEDED_SQL, kb_ids=[uuid.uuid4()]
        )
    )
    assert "LIMIT :cap" in session.sql and session.params["cap"] == 1000
    assert out == {"a", "b"} and out.total == 5000 and out.overflow
    assert out.digest == "5000:123"


def test_scope_uses_the_digest_and_is_small():
    from engine.knowledge import document_acl

    many = document_acl.HiddenIds({str(i) for i in range(3)})
    many.digest, many.total = "9:abc", 9
    merged = document_acl.merge_hidden(many, set())
    assert len(hs._acl_scope(merged)) == 16


def test_too_many_hidden_documents_leave_the_graph_out_not_open(monkeypatch):
    from engine.knowledge import document_acl

    big = document_acl.HiddenIds()
    big.overflow, big.restricted_overflow, big.total, big.digest = True, True, 5000, "x"
    monkeypatch.setattr(document_acl, "hidden_for_search", AsyncMock(return_value=big))
    monkeypatch.setattr(
        document_acl, "superseded_for_search", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(hs, "_vector_search", AsyncMock(return_value=[]))
    monkeypatch.setattr(hs, "_lexical_index_note", AsyncMock(return_value=""))
    graph = AsyncMock()
    monkeypatch.setattr(hs, "_graph_search", graph)
    monkeypatch.setattr(hs, "is_neo4j_available", AsyncMock(return_value=True))
    res = asyncio.run(hs.hybrid_search("q", [str(uuid.uuid4())], use_cache=False))
    graph.assert_not_called()
    assert "Graph results were left out" in res.degraded
    assert res.hidden_documents == 5000


# rerank


def _hits(n):
    return [
        hs.SearchResult(
            content=f"c{i}", score=1 - i / 100, source="s", source_type="chunk"
        )
        for i in range(n)
    ]


def _rerank_case(monkeypatch, settings):
    monkeypatch.setenv("RERANKER_PROVIDER", "llm")
    from engine.knowledge import document_acl

    monkeypatch.setattr(
        document_acl, "hidden_for_search", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(
        document_acl, "superseded_for_search", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(hs, "_vector_search", AsyncMock(return_value=_hits(60)))
    monkeypatch.setattr(hs, "_lexical_index_note", AsyncMock(return_value=""))
    monkeypatch.setattr(hs, "is_neo4j_available", AsyncMock(return_value=False))
    monkeypatch.setattr(hs, "_kb_search_settings", AsyncMock(return_value=settings))
    calls = []

    async def fake(query, items, top_k=10, text_key="content", language=None):
        calls.append(len(items))
        return items[:top_k]

    monkeypatch.setattr(reranker, "rerank", fake)
    return calls


def test_a_collection_can_switch_the_reranker_off(monkeypatch):
    kb = str(uuid.uuid4())
    calls = _rerank_case(monkeypatch, {kb: {"rerank_mode": "off"}})
    out = asyncio.run(
        hs.hybrid_search("q", [kb], mode=hs.SearchMode.VECTOR, use_cache=False)
    )
    assert calls == [] and len(out.results) == 10


def test_candidates_are_capped_and_the_budget_runs_out(monkeypatch):
    monkeypatch.setenv("KB_RERANK_MAX_CANDIDATES", "20")
    monkeypatch.setenv("KB_RERANK_PER_MINUTE", "2")
    tenant = f"t{uuid.uuid4().hex}"
    monkeypatch.setattr(embed_gate, "_redis_client", lambda: None)
    kb = str(uuid.uuid4())
    calls = _rerank_case(monkeypatch, {kb: {"rerank_mode": "auto"}})
    for _ in range(4):
        asyncio.run(
            hs.hybrid_search(
                "q", [kb], mode=hs.SearchMode.VECTOR, use_cache=False, tenant_id=tenant
            )
        )
    assert calls == [20, 20]


def test_a_slow_reranker_keeps_retrieval_order(monkeypatch):
    monkeypatch.setenv("RERANKER_PROVIDER", "llm")
    monkeypatch.setenv("KB_RERANK_TIMEOUT_SECONDS", "0.01")

    async def slow(query, items, top_k=10, text_key="content"):
        await asyncio.sleep(1)

    monkeypatch.setattr(reranker, "rerank", slow)
    out = asyncio.run(hs._rerank("q", _hits(5), 3))
    assert [r.content for r in out] == ["c0", "c1", "c2"]


def test_cohere_model_follows_the_language():
    assert reranker.cohere_model("english") == "rerank-english-v3.0"
    assert reranker.cohere_model("simple") == "rerank-multilingual-v3.0"
    assert reranker.cohere_model("german") == "rerank-multilingual-v3.0"


def test_keyword_words_are_not_ascii_only():
    assert hs._WORD.findall("Straßen 日本語 привет") == ["Straßen", "日本語", "привет"]


def test_keyword_language_is_checked_against_the_list():
    assert hs._ts_config("german") == "german"
    assert hs._ts_config("x'); DROP TABLE chunks; --") == "simple"


# limits and chart


def test_the_body_limit_lets_a_large_file_through_only_on_knowledge_routes():
    from starlette.testclient import TestClient

    from app.core import middleware as mw

    async def ok(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    client = TestClient(mw.BodySizeLimitMiddleware(ok))
    two_gb = str(2 * 1024**3)

    def post(path):
        return client.post(path, headers={"content-length": two_gb}).status_code

    kb = uuid.uuid4()
    assert post(f"/api/knowledge-bases/{kb}/upload") == 200
    assert post(f"/api/knowledge-bases/{kb}/upload-bulk") == 200
    assert post(f"/api/knowledge-bases/{kb}/uploads/abc/content") == 200
    assert post("/api/ml-models/upload") == 413
    assert post("/api/agents") == 413


def _helm(*args):
    import shutil
    import subprocess

    helm = shutil.which("helm")
    if not helm:
        pytest.skip("helm is not installed")
    run = subprocess.run([helm, "template", "t", *args], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return run.stdout


def test_chart_scales_workers_on_the_documents_queue_with_keda():
    out = _helm(str(ROOT / "infra/helm/worker"), "--set", "autoscaling.kind=keda")
    assert "kind: ScaledObject" in out and "kind: HorizontalPodAutoscaler" not in out
    assert "listName: documents" in out
    assert "kind: TriggerAuthentication" in out


def test_chart_keeps_the_cpu_autoscaler_unless_asked():
    out = _helm(str(ROOT / "infra/helm/worker"))
    assert "kind: HorizontalPodAutoscaler" in out and "ScaledObject" not in out


def test_ingress_lets_a_2gb_upload_through_unbuffered():
    source = (ROOT / "infra/helm/abenix/templates/ingress.yaml").read_text()
    assert '"50m"' not in source
    assert "proxy-request-buffering" in source
    values = (ROOT / "infra/helm/abenix/values.yaml").read_text()
    assert "maxBodySize: 21g" in values


def test_every_overlay_sizes_postgres_for_vector_indexes():
    import yaml

    for name in ("values", "values-local", "values-azure", "values-production"):
        values = yaml.safe_load((ROOT / f"infra/helm/abenix/{name}.yaml").read_text())
        conf = values["postgresql"]["primary"]["extendedConfiguration"]
        settings = dict(
            line.split(" = ", 1) for line in conf.splitlines() if " = " in line
        )
        assert settings["shared_buffers"] not in ("", "128MB"), name
        assert settings["maintenance_work_mem"] != "64MB", name


def test_the_shipped_image_has_iterative_scan():
    source = (ROOT / "infra/docker/Dockerfile.postgres-pgvector").read_text()
    assert "pgvector/pgvector:0.8.7-pg16" in source


def test_embedding_batches_overlap_up_to_the_concurrency(monkeypatch, tmp_path):
    import threading

    source = tmp_path / "a.txt"
    source.write_text("\n\n".join(f"paragraph {i} " * 5 for i in range(3000)))
    running = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def embed(chunks, model=None, strict=False):
        with lock:
            running["now"] += 1
            running["peak"] = max(running["peak"], running["now"])
        time.sleep(0.02)
        with lock:
            running["now"] -= 1
        return [[0.1] for _ in chunks], True

    monkeypatch.setattr(dp, "_local_path", lambda p, t: (str(source), None))
    monkeypatch.setattr(dp, "_kb_settings", lambda kb: ("pgvector", "m"))
    monkeypatch.setattr(dp, "_kb_generation", lambda kb: 0)
    monkeypatch.setattr(
        dp, "_begin_ingest", lambda d: dp._IngestState("PROCESSING", 1, 0, None, None)
    )

    class Lock:
        def __init__(self, d):
            pass

        def acquire(self):
            return True

        def release(self):
            pass

    monkeypatch.setattr(dp, "_IngestLock", Lock)
    for name in (
        "_prepare_resume",
        "_mark_checkpoint",
        "_forget_attempt",
        "_doc_update",
        "_after_store",
        "_quota_refusal",
        "_record_embedding_spend",
        "_update_document_status",
    ):
        monkeypatch.setattr(dp, name, lambda *a, **k: None)
    monkeypatch.setattr(dp, "_store_vectors", lambda *a, **k: 1)
    monkeypatch.setattr(dp, "_embed_chunks", embed)
    monkeypatch.setattr(dp, "EMBED_CONCURRENCY", 4)
    monkeypatch.setattr(dp.process_document, "update_state", lambda **k: None)
    dp.process_document.push_request(retries=0)
    try:
        out = dp.process_document.run("d", "k", "/x", "a.txt", "txt", 200, 20)
    finally:
        dp.process_document.pop_request()
    assert out["status"] == "ready"
    assert 2 <= running["peak"] <= 4


def test_worker_redelivery_setting_is_capped_in_code():
    src = inspect.getsource(dp.process_document)
    assert "MAX_ATTEMPTS" in src


# upload tokens and storage


def test_an_upload_token_can_not_be_edited_and_expires():
    from app.services import kb_ingest

    token = kb_ingest.sign_upload({"kb": "a", "size": 5})
    assert kb_ingest.read_upload(token)["size"] == 5
    raw, mac = token.split(".")
    assert kb_ingest.read_upload(raw[:-2] + "AA." + mac) is None
    assert (
        kb_ingest.read_upload(kb_ingest.sign_upload({"kb": "a"}, ttl_seconds=-1))
        is None
    )


def test_part_size_keeps_a_plan_small_and_inside_s3_limits():
    from engine.storage.service import direct_part_size

    assert direct_part_size(10 * 1024**2) == 64 * 1024**2
    assert direct_part_size(200 * 1024**3) == -(-200 * 1024**3 // 1000)
    assert direct_part_size(5 * 1024**5) <= 5 * 1024**3


def test_upload_stream_writes_nothing_until_complete(tmp_path, monkeypatch):
    from engine.storage import service

    monkeypatch.setattr(service, "STORAGE_LOCAL_DIR", str(tmp_path))
    storage = service.StorageService("local")

    async def chunks():
        for i in range(4):
            yield bytes([65 + i]) * 1024

    uri = asyncio.run(storage.upload_stream("t", "kb/x/a.txt", chunks()))
    assert uri.startswith("file://")
    assert (
        Path(uri[7:]).read_bytes()
        == b"A" * 1024 + b"B" * 1024 + b"C" * 1024 + b"D" * 1024
    )

    async def broken():
        yield b"x" * 1024
        raise RuntimeError("client went away")

    with pytest.raises(RuntimeError):
        asyncio.run(storage.upload_stream("t", "kb/x/b.txt", broken()))
    assert not list(tmp_path.rglob("b.txt*"))


def test_upload_stream_stays_bounded_with_a_slow_store(tmp_path):
    from engine.storage.service import _BoundedReader

    reader = _BoundedReader(depth=2)
    reader.feed(b"a")
    reader.feed(b"b")
    assert reader._queue.full()
    assert reader.read(2) == b"ab"
    reader.feed(None)
    assert reader.read(10) == b""


def test_a_failed_dispatch_does_not_leave_a_document_processing_forever():
    from app.routers import knowledge

    assert "queued is False" in inspect.getsource(knowledge.queue_document)


def test_copy_field_escapes_the_copy_text_format():
    assert dp._copy_field("a\tb\\c\nd\re\x00f") == "a\\tb\\\\c\\nd\\re" + "f"
