"""Seed the `energy_contracts` portfolio schema for every existing tenant."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from models.portfolio_schema import PortfolioSchema
from models.tenant import Tenant

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
)


TEMPLATE_PATH = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "api"
    / "app"
    / "core"
    / "portfolio_templates"
    / "energy_contracts.json"
)


def _load_energy_contracts_template() -> dict:
    """Read the template that ships with the API, raise when it is missing or broken."""
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"energy_contracts template not found at {TEMPLATE_PATH}"
        )
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(template.get("schema_json"), dict):
        raise ValueError(f"{TEMPLATE_PATH} has no schema_json object")
    return template


async def _ensure_for_tenant(
    db: AsyncSession,
    tenant: Tenant,
    template: dict,
) -> bool:
    """Insert the energy_contracts schema if this tenant doesn't have one."""
    existing = await db.execute(
        select(PortfolioSchema).where(
            PortfolioSchema.tenant_id == tenant.id,
            PortfolioSchema.domain_name == "energy_contracts",
        )
    )
    if existing.scalar_one_or_none() is not None:
        return False

    schema_json = template.get("schema_json") or {}
    domain = schema_json.get("domain") or {}
    row = PortfolioSchema(
        tenant_id=tenant.id,
        domain_name=domain.get("name", "energy_contracts"),
        label=template.get("label", "Energy Contracts"),
        description=template.get("description") or domain.get("description", ""),
        record_noun=domain.get("record_noun", "contract"),
        record_noun_plural=domain.get("record_noun_plural", "contracts"),
        schema_json=schema_json,
        is_active=True,
    )
    db.add(row)
    return True


async def seed_portfolio_schemas() -> None:
    template = _load_energy_contracts_template()

    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as db:
        tenants = (await db.execute(select(Tenant))).scalars().all()
        if not tenants:
            print("No tenants in DB — run seed_users.py first.")
            await engine.dispose()
            return

        created = 0
        for t in tenants:
            if await _ensure_for_tenant(db, t, template):
                created += 1
        if created:
            await db.commit()
        print(
            f"Seeded {created} energy_contracts schema row(s) across {len(tenants)} tenant(s)."
        )

    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(seed_portfolio_schemas())
    except (OSError, ValueError) as e:
        print(f"Portfolio schema seed FAILED: {e}", file=sys.stderr)
        sys.exit(1)
