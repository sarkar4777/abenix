"""Seed the `energy_contracts` portfolio schema for every existing tenant."""

from __future__ import annotations

import asyncio
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


def _load_energy_contracts_template() -> dict | None:
    """Pull the `energy_contracts` template from the API router module so"""
    try:
        # Import by file path so we don't drag FastAPI dependencies.

        # __file__ = .../packages/db/seeds/seed_portfolio_schemas.py
        # parents: [0]=seeds, [1]=db, [2]=packages, [3]=abenix root
        router_path = (
            Path(__file__).resolve().parents[3]
            / "apps"
            / "api"
            / "app"
            / "routers"
            / "portfolio_schemas.py"
        )
        if not router_path.exists():
            return None
        import ast

        source = router_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Find the async function `list_templates`, then walk its AST for
        # the first dict literal that has an "id": "energy_contracts" key.
        def _find_energy_dict(node: ast.AST) -> dict | None:
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if (
                        isinstance(k, ast.Constant)
                        and k.value == "id"
                        and isinstance(v, ast.Constant)
                        and v.value == "energy_contracts"
                    ):
                        # Yes, this is the right dict — evaluate it.
                        return ast.literal_eval(node)
            for child in ast.iter_child_nodes(node):
                result = _find_energy_dict(child)
                if result is not None:
                    return result
            return None

        return _find_energy_dict(tree)
    except Exception as e:
        print(f"  ! Could not load template: {e}")
        return None


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
    if not template:
        print("No energy_contracts template found — skipping portfolio schema seed.")
        return

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
    asyncio.run(seed_portfolio_schemas())
