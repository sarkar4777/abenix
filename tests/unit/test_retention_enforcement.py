from __future__ import annotations

import pytest

from app.core import retention


class FakeSession:
    def __init__(self, tenants):
        self.tenants = tenants

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        class Rows:
            def all(inner):
                return self.tenants

        return Rows()


@pytest.mark.asyncio
async def test_only_tenants_with_saved_settings_lose_data(monkeypatch):
    seen = []

    async def fake_enforce(_db, tenant_id, policy):
        seen.append((tenant_id, policy.execution_retention_days))
        return {"executions_deleted": 2, "conversations_deleted": 1}

    monkeypatch.setattr(retention, "enforce_retention", fake_enforce)
    tenants = [
        ("a", {"retention": {"execution_retention_days": 10}}),
        ("b", {"other": 1}),
        ("c", None),
    ]

    totals = await retention.enforce_all_tenants(lambda: FakeSession(tenants))

    assert seen == [("a", 10)]
    assert totals == {"tenants": 1, "rows": 3}
