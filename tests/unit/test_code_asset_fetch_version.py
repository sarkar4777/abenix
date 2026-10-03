"""A warm runner fetches the archive of the version it was built for."""

from __future__ import annotations

from types import SimpleNamespace

from app.routers import code_assets as ca


def _asset():
    return SimpleNamespace(
        version=3,
        storage_uri="/data/v3.zip",
        version_history=[
            {"version": 1, "storage_uri": "/data/v1.zip"},
            {"version": 2, "storage_uri": "/data/v2.zip"},
        ],
    )


def test_no_version_or_the_live_one_gives_the_live_archive():
    assert ca._archive_for_version(_asset(), None) == "/data/v3.zip"
    assert ca._archive_for_version(_asset(), 3) == "/data/v3.zip"


def test_an_earlier_version_gives_its_kept_archive():
    assert ca._archive_for_version(_asset(), 2) == "/data/v2.zip"


def test_an_unknown_version_gives_nothing():
    assert ca._archive_for_version(_asset(), 9) is None
