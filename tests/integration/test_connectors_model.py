"""Integration test — Connector model write+read against a live Postgres.

Skipped unless ABENIX_INTEGRATION=1. Asserts that the model + migration
shape line up for the v1.1.0 connector framework. Uses the standard
conftest gate so CI without infra silently skips.

Run locally with:
    DATABASE_URL=postgresql+asyncpg://abenix:abenix@localhost:5432/abenix \\
    ABENIX_INTEGRATION=1 pytest tests/integration/test_connectors_model.py
"""

from __future__ import annotations

import os
import uuid

import pytest


@pytest.mark.asyncio
async def test_create_and_read_connector_row():
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
    )

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from models.connector import (
        Connector,
        ConnectorAuthType,
        ConnectorKind,
    )
    from models.tenant import Tenant

    engine = create_async_engine(db_url, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        # Borrow any existing tenant so the FK lands. New install seed
        # always creates at least one (the demo tenant).
        tenant = (await db.execute(select(Tenant).limit(1))).scalars().first()
        if tenant is None:
            pytest.skip("No tenants in DB; run dev-local seed first")

        c = Connector(
            tenant_id=tenant.id,
            name=f"test-cmms-{uuid.uuid4().hex[:8]}",
            kind=ConnectorKind.cmms,
            base_url="https://example.com/api",
            auth_type=ConnectorAuthType.bearer,
            preset_key="sap_pm",
            config={"environment": "sandbox"},
            is_active=True,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)

        assert c.id is not None
        assert c.kind == ConnectorKind.cmms
        assert c.auth_type == ConnectorAuthType.bearer

        # Read-back path — exercises the index + ORM hydration.
        loaded = (
            await db.execute(select(Connector).where(Connector.id == c.id))
        ).scalar_one()
        assert loaded.name == c.name
        assert loaded.config == {"environment": "sandbox"}
        assert loaded.is_active is True

        # Cleanup so re-runs don't pile up rows.
        await db.delete(loaded)
        await db.commit()

    await engine.dispose()
