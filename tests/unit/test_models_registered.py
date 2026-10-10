"""Every table under packages/db/models is on Base.metadata after `import models`.

The API's startup create_all only builds tables whose modules were imported, so
a model missing from models/__init__ silently loses its table on a fresh database.
"""

from __future__ import annotations

import ast
from pathlib import Path

import models
from models.base import Base

MODELS_DIR = Path(models.__file__).resolve().parent


def _declared_tables() -> dict[str, str]:
    found: dict[str, str] = {}
    for py in sorted(MODELS_DIR.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, (ast.Assign, ast.AnnAssign))
                    and any(
                        isinstance(t, ast.Name) and t.id == "__tablename__"
                        for t in (
                            stmt.targets
                            if isinstance(stmt, ast.Assign)
                            else [stmt.target]
                        )
                    )
                    and isinstance(stmt.value, ast.Constant)
                ):
                    found[stmt.value.value] = py.name
    return found


def test_every_model_table_is_registered():
    declared = _declared_tables()
    assert len(declared) > 50
    missing = {t: f for t, f in declared.items() if t not in Base.metadata.tables}
    assert not missing, f"not imported in models/__init__: {missing}"


def test_previously_missing_modules_are_registered():
    for table in (
        "atlas_graphs",
        "atlas_snapshots",
        "edge_gateways",
        "memory_wings",
        "platform_settings",
        "portfolio_schemas",
        "subject_policies",
    ):
        assert table in Base.metadata.tables


# created by a migration but deliberately without an ORM model
MIGRATION_ONLY = {
    "chunks": "pgvector table the API creates at startup in main.py",
    "knowledge_bases": "pre-rename knowledge table, kept for old databases",
    "contractiq_assets": "ContractIQ moved to its own database",
    "contractiq_clauses": "ContractIQ moved to its own database",
    "contractiq_comparisons": "ContractIQ moved to its own database",
    "contractiq_contracts": "ContractIQ moved to its own database",
    "contractiq_events": "ContractIQ moved to its own database",
    "contractiq_extracted_data": "ContractIQ moved to its own database",
    "contractiq_market_alerts": "ContractIQ moved to its own database",
    "contractiq_risk_analyses": "ContractIQ moved to its own database",
    "contractiq_users": "ContractIQ moved to its own database",
}


def _migration_tables() -> set[str]:
    import re

    versions = MODELS_DIR.parent / "alembic" / "versions"
    created: set[str] = set()
    dropped: set[str] = set()
    for f in versions.glob("*.py"):
        up = f.read_text(encoding="utf-8").split("def downgrade")[0]
        created |= set(re.findall(r'op\.create_table\(\s*["\']([a-z0-9_]+)["\']', up))
        dropped |= set(re.findall(r'op\.drop_table\(\s*["\']([a-z0-9_]+)["\']', up))
    return created - dropped


def test_every_migration_table_has_a_model():
    # a fresh install builds tables from the ORM and stamps alembic, so a
    # migration-only table never exists there
    missing = _migration_tables() - set(Base.metadata.tables) - set(MIGRATION_ONLY)
    assert (
        not missing
    ), f"tables created by migrations with no ORM model: {sorted(missing)}"
