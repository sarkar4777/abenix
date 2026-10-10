"""A fresh install is built from the ORM and stamped, so bootstrap verify adds what only migrations create."""

from __future__ import annotations

import re
from pathlib import Path

import bootstrap

VERSIONS = Path(bootstrap.ROOT) / "alembic" / "versions"


def test_every_migration_trigger_can_be_rebuilt():
    sql = bootstrap.migration_trigger_sql()
    assert {
        "executions_provenance",
        "executions_emit_event",
        "activity_logs_immutable",
        "source_snapshots_immutable",
    } <= set(sql)
    for name, stmts in sql.items():
        joined = "\n".join(stmts)
        assert re.search(rf"CREATE (OR REPLACE )?FUNCTION {name}\(", joined), name
        assert re.search(rf"CREATE TRIGGER {name}\b", joined), name


def test_each_trigger_is_created_by_one_migration():
    # the rebuild reads one definition per trigger, so a redefinition must update this rule first
    seen: dict[str, list[str]] = {}
    for f in VERSIONS.glob("*.py"):
        up = f.read_text(encoding="utf-8").split("def downgrade")[0]
        for name in re.findall(r"CREATE TRIGGER\s+(\w+)", up):
            seen.setdefault(name, []).append(f.name)
    twice = {n: fs for n, fs in seen.items() if len(fs) > 1}
    assert not twice, f"triggers defined in more than one migration: {twice}"


class FakeConn:
    def __init__(self, present):
        self.present = present
        self.ran: list[str] = []

    def execute(self, stmt):
        sql = str(stmt)
        if "FROM pg_trigger" in sql:
            return [(n,) for n in self.present]
        self.ran.append(sql)
        return []


def test_only_missing_triggers_are_created():
    conn = FakeConn(
        {"executions_provenance", "executions_emit_event", "source_snapshots_immutable"}
    )
    made = bootstrap._heal_missing_triggers_sync(conn)
    assert made == ["activity_logs_immutable"]
    assert any("CREATE TRIGGER activity_logs_immutable" in s for s in conn.ran)
    assert not any("executions_provenance" in s for s in conn.ran)
