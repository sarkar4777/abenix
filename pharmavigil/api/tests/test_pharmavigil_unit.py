"""Unit tests for the PharmaVigil pieces that do not need a cluster.

The code assets and the store are pure functions over data, so they are worth
testing directly rather than only through a nine-node pipeline that takes two
minutes and needs an LLM.

    cd pharmavigil/api && pytest
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CODER = ROOT / "code-assets" / "meddra-coder" / "main.py"
DISPRO = ROOT / "code-assets" / "disproportionality" / "main.py"


def run_asset(script: Path, payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ── meddra-coder ─────────────────────────────────────────────────────────

def test_exact_term_codes_without_review():
    out = run_asset(CODER, {"terms": ["nausea"]})
    r = out["results"][0]
    assert r["match"] == "exact"
    assert r["needs_review"] is False
    assert r["candidates"][0]["pt"] == "Nausea"


def test_reporter_phrasing_maps_to_the_clinical_term():
    out = run_asset(CODER, {"terms": ["heart attack", "yellow eyes", "hives"]})
    pts = [r["candidates"][0]["pt"] for r in out["results"]]
    assert pts == ["Myocardial infarction", "Hepatotoxicity", "Urticaria"]
    assert all(r["needs_review"] is False for r in out["results"])


def test_phrasing_inside_a_sentence_is_still_found():
    out = run_asset(CODER, {"terms": ["I had really bad hives all week"]})
    r = out["results"][0]
    assert r["match"] == "synonym_contained"
    assert r["candidates"][0]["pt"] == "Urticaria"


def test_a_typo_is_flagged_rather_than_silently_coded():
    # "naseua" should surface nausea as a candidate but not be taken as fact.
    out = run_asset(CODER, {"terms": ["naseua"]})
    r = out["results"][0]
    assert r["needs_review"] is True
    assert r["candidates"][0]["pt"] == "Nausea"


def test_nonsense_is_not_forced_onto_a_near_miss():
    out = run_asset(CODER, {"terms": ["xyzzy flurble"]})
    assert out["results"][0]["needs_review"] is True


def test_important_medical_events_are_flagged():
    out = run_asset(CODER, {"terms": ["throat closing up", "yellow eyes", "headache"]})
    assert "Anaphylactic reaction" in out["ime_hits"]
    assert "Hepatotoxicity" in out["ime_hits"]
    # A headache is not an IME and must not appear.
    assert not any("Headache" in h for h in out["ime_hits"])


def test_intake_reaction_objects_are_accepted_not_just_strings():
    # The pipeline hands over the intake node's objects, not bare strings.
    out = run_asset(CODER, {"terms": [{"verbatim": "nausea"}, {"verbatim": "rash"}]})
    assert [r["candidates"][0]["pt"] for r in out["results"]] == ["Nausea", "Rash"]


def test_empty_input_is_not_an_error():
    out = run_asset(CODER, {"terms": []})
    assert out["results"] == []
    assert out["coded"] == 0


# ── disproportionality ───────────────────────────────────────────────────

def test_a_real_association_clears_the_threshold():
    out = run_asset(DISPRO, {"a": 12, "b": 3400, "c": 480, "d": 295000})
    assert out["crosses_threshold"] is True
    assert out["prr"] > 2
    assert out["prr_lower_ci"] > 1
    assert "Evans" in out["rule"] or "EB05" in out["rule"]


def test_a_thin_count_is_rejected_however_large_the_ratio():
    # Two reports against a tiny expectation gives an enormous PRR and means
    # nothing. This is the single most important rule in the asset.
    out = run_asset(DISPRO, {"a": 2, "b": 40, "c": 90, "d": 295000})
    assert out["prr"] > 50
    assert out["crosses_threshold"] is False
    assert "a < 3" in out["rule"]


def test_no_association_scores_around_one():
    out = run_asset(DISPRO, {"a": 50, "b": 10000, "c": 1500, "d": 295000})
    assert 0.7 < out["prr"] < 1.4
    assert out["crosses_threshold"] is False


def test_a_zero_cell_does_not_divide_by_zero():
    out = run_asset(DISPRO, {"a": 4, "b": 0, "c": 10, "d": 9000})
    assert isinstance(out["ror"], (int, float))
    assert out["ror"] > 0


def test_every_response_carries_the_causality_caveat():
    out = run_asset(DISPRO, {"a": 12, "b": 3400, "c": 480, "d": 295000})
    assert "not" in out["caveat"].lower()
    assert "causality" in out["caveat"].lower()


def test_bad_input_returns_an_error_not_a_crash():
    proc = subprocess.run(
        [sys.executable, str(DISPRO)], input='{"a": "x"}',
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0
    assert "error" in json.loads(proc.stdout)


# ── the store ────────────────────────────────────────────────────────────

sys.path.insert(0, str(ROOT / "api"))


@pytest.mark.asyncio
async def test_queue_orders_by_priority_not_arrival():
    from app.core.store import CaseStore

    store = CaseStore()
    for pid, prio in [("a", "P4"), ("b", "P1"), ("c", "P3"), ("d", "P2")]:
        row = await store.create({"id": pid, "suspect_drug": "X"})
        await store.update(row["id"], priority=prio)
    assert [c["id"] for c in await store.list()] == ["b", "d", "c", "a"]


@pytest.mark.asyncio
async def test_frequency_snapshot_labels_its_background_counts():
    from app.core.store import CaseStore

    store = CaseStore()
    await store.create({"id": "x", "suspect_drug": "Atorvastatin"})
    snap = await store.frequency_snapshot()
    # A reviewer has to be able to tell shipped reference data from reports
    # this instance actually received.
    assert snap["live_cases"] == 1
    assert snap["background_reports"] > 0
    assert snap["total_reports"] == snap["live_cases"] + snap["background_reports"]
    assert "not reports received here" in snap["note"]


@pytest.mark.asyncio
async def test_review_moves_the_case_to_a_terminal_status():
    from app.core.store import CaseStore

    store = CaseStore()
    row = await store.create({"id": "r1", "suspect_drug": "X"})
    await store.update(row["id"], status="assessed")
    after = await store.record_review(row["id"], "approve", "dr.who", "")
    assert after["status"] == "submitted"
    assert after["reviewed_by"] == "dr.who"


@pytest.mark.asyncio
async def test_signal_board_ranks_signals_first():
    from app.core.store import CaseStore

    store = CaseStore()
    await store.create({"id": "1", "suspect_drug": "A"})
    await store.update("1", primary_pt="Rash", signal=False, prr=1.1)
    await store.create({"id": "2", "suspect_drug": "B"})
    await store.update("2", primary_pt="Rhabdomyolysis", signal=True, prr=7.1)
    board = await store.signal_board()
    assert board[0]["pt"] == "Rhabdomyolysis"
    assert board[0]["signal"] is True
