"""Tool runtime defaults: insert what is missing, lift an untouched old default, keep an admin's choice."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import seed_tool_runtime as seed
from models.tool_runtime_config import ToolRuntimeConfig

pytestmark = pytest.mark.asyncio


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.added = []

    async def execute(self, _stmt):
        rows = self.rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        pass


def _row(slug, **kw):
    return ToolRuntimeConfig(slug=slug, **kw)


async def test_fresh_install_gets_every_default():
    db = _Session([])
    await seed.seed_tool_runtime_defaults(db)
    assert {r.slug for r in db.added} == set(seed.DEFAULTS)
    ca = next(r for r in db.added if r.slug == "code_asset")
    assert ca.max_inflight_per_tenant == 8


async def test_untouched_old_default_is_lifted():
    old = _row("code_asset", max_inflight_global=6, max_inflight_per_tenant=2)
    db = _Session([old])
    await seed.seed_tool_runtime_defaults(db)
    assert (old.max_inflight_global, old.max_inflight_per_tenant) == (24, 8)


async def test_admin_choice_is_kept():
    mine = _row("code_asset", max_inflight_global=6, max_inflight_per_tenant=3)
    db = _Session([mine])
    await seed.seed_tool_runtime_defaults(db)
    assert (mine.max_inflight_global, mine.max_inflight_per_tenant) == (6, 3)
