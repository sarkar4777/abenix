"""Local object storage round trip, streaming and key hygiene."""

from __future__ import annotations

import io
import os

import pytest

from app.core import object_storage as os_mod
from app.core.object_storage import (
    CHUNK_SIZE,
    BadKey,
    LocalObjectStorage,
    ObjectNotFound,
    S3ObjectStorage,
    get_object_storage,
)


async def _collect(stream) -> list[bytes]:
    return [c async for c in stream]


async def test_local_round_trip(tmp_path):
    st = LocalObjectStorage(tmp_path)
    key = "archives/t1/run.jsonl.gz"
    assert not await st.exists(key)
    n = await st.put(key, b"hello world", "application/gzip")
    assert n == 11
    assert await st.exists(key)
    assert b"".join(await _collect(st.get_stream(key))) == b"hello world"
    assert st.url_for(key).startswith("file://")
    assert st.url_for(key).endswith("archives/t1/run.jsonl.gz")
    assert st.path_for(key) == tmp_path / "archives" / "t1" / "run.jsonl.gz"
    assert await st.delete(key) is True
    assert await st.delete(key) is False
    assert not await st.exists(key)


async def test_put_streams_from_async_source_and_get_streams_in_chunks(tmp_path):
    st = LocalObjectStorage(tmp_path)
    piece = os.urandom(1024) * 700  # ~700 KiB per chunk, 4 chunks

    async def gen():
        for _ in range(4):
            yield piece

    n = await st.put("big/blob.bin", gen())
    assert n == len(piece) * 4
    chunks = await _collect(st.get_stream("big/blob.bin"))
    assert len(chunks) > 1
    assert all(len(c) <= CHUNK_SIZE for c in chunks)
    assert b"".join(chunks) == piece * 4


async def test_put_accepts_file_objects_and_sync_iterables(tmp_path):
    st = LocalObjectStorage(tmp_path)
    await st.put("a/file.bin", io.BytesIO(b"abc" * 1000))
    await st.put("a/iter.bin", [b"x", b"y", b"z"])
    assert b"".join(await _collect(st.get_stream("a/file.bin"))) == b"abc" * 1000
    assert b"".join(await _collect(st.get_stream("a/iter.bin"))) == b"xyz"


async def test_put_is_atomic_and_leaves_no_part_file(tmp_path):
    st = LocalObjectStorage(tmp_path)

    async def boom():
        yield b"partial"
        raise RuntimeError("source died")

    with pytest.raises(RuntimeError):
        await st.put("x/y.bin", boom())
    assert not await st.exists("x/y.bin")
    assert list((tmp_path / "x").glob("*")) == []


async def test_missing_key_raises(tmp_path):
    st = LocalObjectStorage(tmp_path)
    with pytest.raises(ObjectNotFound):
        await _collect(st.get_stream("nope/missing.bin"))


@pytest.mark.parametrize("bad", ["", "/abs/path", "../up", "a/../b", "a//b", "a\\b"])
async def test_keys_cannot_escape_the_root(tmp_path, bad):
    st = LocalObjectStorage(tmp_path)
    with pytest.raises(BadKey):
        await st.put(bad, b"x")
    with pytest.raises(BadKey):
        await st.exists(bad)


def test_factory_follows_storage_backend_env(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_ROOT", str(tmp_path))
    st = get_object_storage()
    assert isinstance(st, LocalObjectStorage) and st.root == tmp_path
    st = get_object_storage(local_root=tmp_path / "sub")
    assert st.root == tmp_path / "sub"

    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("STORAGE_S3_BUCKET", "bkt")
    monkeypatch.setenv("STORAGE_S3_ENDPOINT", "http://minio:9000")
    s3 = get_object_storage()
    assert isinstance(s3, S3ObjectStorage)
    assert s3.bucket == "bkt" and s3.endpoint == "http://minio:9000"
    assert s3.url_for("archives/t/r.gz") == "s3://bkt/archives/t/r.gz"

    monkeypatch.setenv("STORAGE_BACKEND", "azure")
    monkeypatch.setenv("STORAGE_AZURE_CONTAINER", "ctr")
    az = get_object_storage()
    assert az.backend == "azure"
    assert az.url_for("archives/t/r.gz") == "az://ctr/archives/t/r.gz"


async def test_regroup_yields_fixed_size_parts():
    async def gen():
        for _ in range(5):
            yield b"a" * 3

    parts = [p async for p in os_mod._regroup(gen(), 4)]
    assert parts == [b"aaaa", b"aaaa", b"aaaa", b"aaa"]
