from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# app.core.config refuses the placeholder SECRET_KEY unless DEBUG is on
os.environ.setdefault("DEBUG", "true")

# the runtime image puts packages/db on PYTHONPATH, tests do the same
_DB = str(Path(__file__).resolve().parents[3] / "packages" / "db")
if _DB not in sys.path:
    sys.path.append(_DB)


@pytest.fixture(autouse=True)
def _fresh_code_asset_cache():
    # the warm path's short cache would otherwise carry rows across tests
    from engine.tools import code_asset

    code_asset._HOT.clear()
    code_asset._HOT_LOCKS.clear()
    code_asset._LAST_TEST_AT.clear()
    yield
    code_asset._HOT.clear()
