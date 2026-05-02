"""Pytest config for live integration tests.

These tests fire real HTTP requests against a running cluster
(localhost:8000 by default — change with ABENIX_API_URL). They are
gated behind the ABENIX_INTEGRATION env var so they don't run in unit-
test pipelines without a deployed API.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("ABENIX_INTEGRATION", "").lower() in ("1", "true", "yes"):
        return
    skip = pytest.mark.skip(
        reason="Set ABENIX_INTEGRATION=1 to run live agent smoke tests."
    )
    for item in items:
        # The seed-loader tests are pure validation — no HTTP, no DB.
        # They must run unconditionally so a malformed YAML breaks
        # local + CI builds even without the integration flag.
        if "test_seed_loader" in str(item.fspath):
            continue
        item.add_marker(skip)
