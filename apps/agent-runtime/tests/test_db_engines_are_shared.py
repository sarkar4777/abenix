"""Runtime code must reuse a pooled engine, a new engine per call is a new db login per call."""

from __future__ import annotations

from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "engine"

# each of these keeps its engine in a module cache, or runs once per reaper pass
ALLOWED = {
    "db_pool.py",
    "invocation_log.py",
    "pipeline.py",
    "code_runners.py",
    "tools/code_asset.py",
    "decisions/db.py",
    "sources/db.py",
}


def test_no_per_call_engines() -> None:
    offenders = []
    for f in ENGINE.rglob("*.py"):
        rel = f.relative_to(ENGINE).as_posix()
        if rel in ALLOWED:
            continue
        if "create_async_engine(" in f.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(rel)
    assert not offenders, f"use engine.db_pool.shared_engine in {offenders}"
