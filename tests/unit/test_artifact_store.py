"""Uploaded files survive on pods that do not hold them, through object storage."""

from __future__ import annotations

import pytest

from app.core import artifact_store
from app.core.object_storage import LocalObjectStorage


@pytest.fixture
def remote(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    bucket = LocalObjectStorage(tmp_path / "bucket")
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_ROOT", str(data))
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setattr(artifact_store, "get_object_storage", lambda: bucket)
    return data


@pytest.mark.asyncio
async def test_mirror_then_restore_on_another_pod(remote):
    f = remote / "ml-models" / "t1" / "abc_model.pkl"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"weights")
    await artifact_store.mirror(f)
    f.unlink()  # the pod that serves the next request never had it
    assert await artifact_store.ensure_local(f)
    assert f.read_bytes() == b"weights"


@pytest.mark.asyncio
async def test_missing_everywhere_is_false(remote):
    assert not await artifact_store.ensure_local(remote / "code-assets" / "gone.zip")


@pytest.mark.asyncio
async def test_remove_deletes_both(remote):
    f = remote / "code-assets" / "a.zip"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"zip")
    await artifact_store.mirror(f)
    await artifact_store.remove(f)
    assert not f.exists()
    assert not await artifact_store.ensure_local(f)


@pytest.mark.asyncio
async def test_local_backend_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    f = tmp_path / "x.zip"
    await artifact_store.mirror(f)  # nothing to do, no error for a missing file
    assert not await artifact_store.ensure_local(f)


def test_keys_follow_the_data_path(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_ROOT", str(tmp_path))
    assert (
        artifact_store.key_for(tmp_path / "ml-models" / "t" / "m.pkl")
        == "artifacts/ml-models/t/m.pkl"
    )
