"""Duplicate candidates scale by blocks, not by comparing every pair."""

from __future__ import annotations

import asyncio
import random
import time
import tracemalloc

from engine.knowledge import entity_resolver as er
from engine.knowledge.entity_blocking import (
    SKETCH_SIZE,
    WINDOW,
    NameBlocker,
    candidate_groups,
    name_key,
    similar,
)
from engine.knowledge.entity_resolver import ResolvedEntity


def _names(n, seed=1):
    r = random.Random(seed)
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    out = set()
    while len(out) < n:
        word = "".join(r.choice(alphabet) for _ in range(r.randint(5, 10)))
        out.add(
            f"{word.capitalize()} {r.choice(['Energy', 'Capital', 'Metals'])} {r.choice(['Ltd', 'Corp', 'Inc'])}"
        )
    return sorted(out)


def test_name_key_normalizes_case_accents_and_punctuation():
    assert name_key("  ACME,  Corp. ") == "acme corp"
    assert name_key("Crème-Brûlée Ltd") == "creme brulee ltd"
    assert name_key("snake_case_name") == "snake case name"


def test_numbers_keep_different_things_apart():
    assert not similar("project 12 phase", "project 13 phase")
    assert not similar("q3 2024 results", "q4 2024 results")
    assert similar("international business machines", "international busines machines")
    assert similar("acme holdings", "holdings acme")


def test_groups_found_exact_and_fuzzy_and_type_scoped():
    rows = [
        ("ACME Corp.", "organization"),
        ("acme corp", "organization"),
        ("Internationl Business Machines", "organization"),
        ("International Business Machines", "organization"),
        ("Acme Corp", "product"),
        ("Unrelated Thing", "organization"),
    ]
    groups = candidate_groups(rows)
    by_kind = {g.exact: g for g in groups}
    assert set(by_kind[True].names) == {"ACME Corp.", "acme corp"}
    assert set(by_kind[False].names) == {
        "Internationl Business Machines",
        "International Business Machines",
    }
    assert all(g.entity_type == "organization" for g in groups)


def test_work_grows_with_n_not_n_squared():
    n = 8000
    blocker = NameBlocker()
    blocker.add((x, "org") for x in _names(n))
    blocker.groups()
    try:
        # the old scan compared about n squared over two pairs
        assert blocker.stats.comparisons < n * WINDOW * (SKETCH_SIZE + 1)
        assert blocker.stats.comparisons < n * n / 2 / 20
    finally:
        blocker.close()


def test_recall_on_planted_typos():
    r = random.Random(3)
    names = _names(5000)
    typos = {}
    for name in r.sample(names, 200):
        i = r.randrange(2, len(name) - 2)
        typos[name] = name[:i] + name[i + 1 :]
    rows = [(n, "org") for n in names] + [(t, "org") for t in typos.values()]
    groups = candidate_groups(rows)
    together = {frozenset(p) for g in groups for p in _pairs(g.names)}
    found = sum(1 for a, b in typos.items() if frozenset((a, b)) in together)
    assert found / len(typos) >= 0.95


def _pairs(items):
    return [(a, b) for i, a in enumerate(items) for b in items[i + 1 :]]


def test_memory_stays_flat_when_the_corpus_grows_tenfold():
    def peak(n):
        names = _names(n)
        tracemalloc.start()
        b = NameBlocker()
        for i in range(0, n, 2000):
            b.add((x, "org") for x in names[i : i + 2000])
        b.groups()
        _cur, top = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        b.close()
        return top

    assert peak(20000) < peak(2000) * 3


def test_resolver_finds_ambiguous_groups_off_the_event_loop(monkeypatch):
    entities = [
        ResolvedEntity(canonical_name=n, entity_type="org", description="")
        for n in _names(30)
    ] + [
        ResolvedEntity(
            canonical_name="Globex Corporation", entity_type="org", description=""
        ),
        ResolvedEntity(
            canonical_name="Globex Corporatoin", entity_type="org", description=""
        ),
    ]
    groups = er._find_ambiguous_groups(entities)
    assert {e.canonical_name for g in groups for e in g} >= {
        "Globex Corporation",
        "Globex Corporatoin",
    }

    from engine.knowledge.entity_extractor import ExtractedEntity

    seen = {}

    def slow(items):
        import threading

        seen["thread"] = threading.current_thread()
        return []

    monkeypatch.setattr(er, "_find_ambiguous_groups", slow)

    async def main():
        import threading

        raw = [ExtractedEntity(f"Entity {i}", "org", "", 0, "d") for i in range(12)]
        await er.resolve_entities(raw, [])
        return threading.current_thread()

    loop_thread = asyncio.run(main())
    assert seen["thread"] is not loop_thread


def test_ten_thousand_names_finish_in_seconds():
    names = _names(10000)
    started = time.monotonic()
    candidate_groups((n, "org") for n in names)
    assert time.monotonic() - started < 30
