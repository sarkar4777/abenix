from __future__ import annotations

import os

import pytest

# app.core.config refuses the placeholder SECRET_KEY unless DEBUG is on
os.environ.setdefault("DEBUG", "true")


@pytest.fixture(autouse=True)
def _fresh_code_asset_cache():
    # the warm path's short cache would otherwise carry rows across tests
    from engine.tools import code_asset

    code_asset._HOT.clear()
    code_asset._HOT_LOCKS.clear()
    code_asset._LAST_TEST_AT.clear()
    yield
    code_asset._HOT.clear()
