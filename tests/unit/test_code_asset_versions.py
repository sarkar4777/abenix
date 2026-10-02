"""Version history stays bounded and old archives are removed from disk."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.routers import code_assets as ca


@pytest.mark.asyncio
async def test_history_is_bounded_and_prunes_archives(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_MAX_VERSIONS", 2)
    files = []
    for i in range(3):
        f = tmp_path / f"v{i}.zip"
        f.write_bytes(b"x")
        files.append(f)
    live = tmp_path / "live.zip"
    live.write_bytes(b"x")
    a = SimpleNamespace(version_history=[], storage_uri=str(live))
    for i, f in enumerate(files):
        await ca._prune(ca._push_history(a, {"version": i + 1, "storage_uri": str(f)}))
    assert [h["version"] for h in a.version_history] == [2, 3]
    assert not files[0].exists()
    assert files[1].exists() and files[2].exists() and live.exists()


def test_archive_still_live_is_not_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_MAX_VERSIONS", 1)
    shared = tmp_path / "same.zip"
    shared.write_bytes(b"x")
    a = SimpleNamespace(version_history=[], storage_uri=str(shared))
    ca._push_history(a, {"version": 1, "storage_uri": str(shared)})
    ca._push_history(a, {"version": 2, "storage_uri": str(tmp_path / "other.zip")})
    assert shared.exists()


def test_analysis_error_uses_the_analyzer_words():
    msg = ca._analysis_error([{"level": "error", "message": "no entrypoint found"}])
    assert msg == "no entrypoint found"
    assert "README" in ca._analysis_error([])
