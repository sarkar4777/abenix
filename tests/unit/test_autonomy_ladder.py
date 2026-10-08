"""Earned autonomy scoring and ladder rules, including property-style checks over many random records."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.services import autonomy_ladder as L

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _grant(level=1, ceiling=4, state="active", since_days=30, config="h1"):
    return {
        "id": "g1",
        "agent_id": "a1",
        "level": level,
        "ceiling": ceiling,
        "state": state,
        "level_since": NOW - timedelta(days=since_days),
        "agent_config_hash": config,
    }


def _scored(i, held=True, config="h1", **kw):
    row = {
        "created_at": NOW - timedelta(minutes=i),
        "status": "executed",
        "mode": "auto",
        "outcome_status": "observed",
        "agent_config_hash": config,
        "score": {"within_band": held, "band_ok": True, "agreement": None},
        "harm": False,
    }
    row.update(kw)
    return row


def _review(i, answer="agree"):
    return {
        "created_at": NOW - timedelta(minutes=i),
        "status": "watching",
        "mode": "watching",
        "reviewer_answer": answer,
        "outcome_status": "none",
        "score": {"agreement": L.agreement_for("watching", answer)},
        "harm": False,
    }


def _stats(rows, grant, **kw):
    return L.compute_stats(
        rows,
        now=NOW,
        level_since=grant["level_since"],
        created_at=NOW - timedelta(days=90),
        current_config_hash=kw.pop("current", grant["agent_config_hash"]),
        **kw,
    )


def test_level_labels_are_plain_words():
    assert [L.level_label(i) for i in range(5)] == [
        "Off",
        "Watching",
        "Asks first",
        "Acts within limits",
        "Acts and reports",
    ]
    assert L.level_label(None) == "Unknown"


def test_wilson_lower_bound_punishes_small_samples():
    assert L.wilson_lower_bound(0, 0) == 0.0
    small = L.wilson_lower_bound(5, 5)
    big = L.wilson_lower_bound(95, 100)
    assert small < 0.6 < big
    assert L.wilson_lower_bound(50, 50) > L.wilson_lower_bound(10, 10)
    assert 0.0 <= L.wilson_lower_bound(0, 10) < 0.01


def test_within_band_numeric_and_categorical():
    p = {"value": 4.4, "low": 4.1, "high": 4.6}
    assert L.within_band(p, 4.35) is True
    assert L.within_band(p, 4.7) is False
    assert L.within_band(p, "4.2") is True
    assert L.within_band({"value": "open"}, "OPEN") is True
    assert L.within_band({"value": "open"}, "closed") is False
    assert L.within_band(None, 4) is None
    assert L.within_band(p, None) is None


def test_band_width_rule_counts_wide_bands_as_no_prediction():
    assert L.band_ok({"value": 4.0, "low": 3.8, "high": 4.4}, 0.2) is True
    assert L.band_ok({"value": 4.0, "low": 1.0, "high": 9.0}, 0.2) is False
    assert L.band_ok({"value": 4.0, "low": 3.0, "high": 5.0}, None) is True
    assert L.band_ok(None, 0.5) is False
    assert L.band_ok({"value": 4.0, "low": 5.0, "high": 3.0}, 1.0) is False
    s = L.score_action({"value": 4.0, "low": 0, "high": 100}, 4.0, 0.2)
    assert s["within_band"] is True and s["band_ok"] is False
    assert L.held({"score": s}) is False


def test_agreement_values():
    assert L.agreement_for("watching", "agree") == 1.0
    assert L.agreement_for("watching", "different") == 0.0
    assert L.agreement_for("watching", "unsure") is None
    assert L.agreement_for("approved", None) == 1.0
    assert L.agreement_for("edited", None) == 0.5
    assert L.agreement_for("rejected", None) == 0.0


def test_policy_layers_override_defaults():
    p = L.merge_policy(
        {"to_asks_first": {"min_reviews": 5}}, {"window": 20, "to_asks_first": None}
    )
    assert p["to_asks_first"] == {"min_reviews": 5, "min_agreement_lb": 0.70}
    assert p["window"] == 20
    assert p["to_within_limits"]["min_executed"] == 50


def test_ceiling_by_tier_and_lowered_caps():
    assert L.tier_ceiling("critical") == 2
    assert L.tier_ceiling("high") == 3
    assert L.tier_ceiling("medium") == 4
    assert L.tier_ceiling(None) == 4
    assert L.effective_ceiling("low", 3, None) == 3
    assert L.effective_ceiling("high", 4, 4) == 3
    assert L.effective_ceiling("medium", None, 1) == 1


def test_watching_to_asks_first_needs_reviews_and_agreement():
    g = _grant(level=1)
    rows = [_review(i) for i in range(12)]
    res = L.evaluate(g, _stats(rows, g), None, NOW)
    assert res["next_level"] == 2 and not res["ready"]
    labels = [r["label"] for r in res["requirements"]]
    assert "12 of 20 reviews" in labels
    missing = [r for r in res["requirements"] if not r["met"]]
    assert missing[0]["fix"]["href"].startswith("/approvals")
    rows = [_review(i) for i in range(25)]
    res = L.evaluate(g, _stats(rows, g), None, NOW)
    assert res["ready"] is True
    assert all(r["fix"] is None for r in res["requirements"])


def test_unsure_answers_are_left_out():
    g = _grant(level=1)
    rows = [_review(i, "unsure") for i in range(30)]
    st = _stats(rows, g)
    assert st["reviews"] == 0 and st["agreement_pct"] is None
    assert not L.evaluate(g, st, None, NOW)["ready"]


def test_asks_first_to_within_limits_sentences():
    g = _grant(level=2, since_days=3)
    rows = [_scored(i, held=i % 10 != 0) for i in range(34)]
    res = L.evaluate(g, _stats(rows, g), None, NOW)
    labels = {r["key"]: r["label"] for r in res["requirements"]}
    assert labels["min_executed"] == "34 of 50 scored actions"
    assert labels["min_accuracy_lb"].startswith("Accuracy ")
    assert "(needs 85%)" in labels["min_accuracy_lb"]
    assert labels["min_days_at_level"] == "3 of 14 days at this level"
    assert not res["ready"]


def test_unknown_outcomes_block_promotion_and_name_the_fix():
    g = _grant(level=2)
    rows = [_scored(i) for i in range(60)] + [
        {
            "created_at": NOW - timedelta(minutes=100 + i),
            "status": "executed",
            "outcome_status": "unknown",
            "score": None,
            "harm": False,
        }
        for i in range(20)
    ]
    res = L.evaluate(g, _stats(rows, g), None, NOW)
    req = next(r for r in res["requirements"] if r["key"] == "max_unknown_rate")
    assert req["met"] is False
    assert req["fix"]["href"].endswith("#outcome")
    assert not res["ready"]


def test_high_reject_rate_blocks():
    g = _grant(level=2)
    rows = [_scored(i) for i in range(60)] + [
        {
            "created_at": NOW - timedelta(minutes=200 + i),
            "status": "rejected",
            "mode": "proposed",
            "outcome_status": "none",
            "harm": False,
        }
        for i in range(40)
    ]
    res = L.evaluate(g, _stats(rows, g), None, NOW)
    assert not next(r for r in res["requirements"] if r["key"] == "max_reject_rate")[
        "met"
    ]


def test_ceiling_blocks_the_next_step():
    g = _grant(level=3, ceiling=3)
    rows = [_scored(i) for i in range(300)]
    res = L.evaluate(g, _stats(rows, g), None, NOW, ceiling=3)
    assert res["blocked_by_ceiling"] is True and res["ready"] is False
    assert any(r["key"] == "ceiling" and not r["met"] for r in res["requirements"])


def test_harm_demotes_to_asks_first():
    g = _grant(level=4, since_days=40)
    rows = [_scored(i) for i in range(100)]
    rows[0]["harm"] = True
    res = L.evaluate(g, _stats(rows, g), None, NOW)
    assert res["demote_to"] == 2
    assert "Harm" in res["demote_reason"]
    assert L.harm_demotion(4) == 2 and L.harm_demotion(1) == 1


def test_accuracy_drop_demotes_one_level():
    g = _grant(level=3)
    rows = [_scored(i, held=i % 2 == 0) for i in range(50)]
    res = L.evaluate(g, _stats(rows, g), None, NOW)
    assert res["demote_to"] == 2
    assert "points under" in res["demote_reason"]


def test_config_change_caps_at_asks_first_until_recheck():
    g = _grant(level=3, config="old")
    rows = [_scored(i, config="new") for i in range(4)] + [
        _scored(10 + i, config="old") for i in range(80)
    ]
    st = _stats(rows, g, current="new")
    res = L.evaluate(g, st, None, NOW)
    assert res["demote_to"] == 2
    assert "changed" in res["demote_reason"]
    rows = [_scored(i, config="new") for i in range(12)] + [
        _scored(20 + i, config="old") for i in range(80)
    ]
    res = L.evaluate(g, _stats(rows, g, current="new"), None, NOW)
    assert res["demote_to"] is None


def test_level_above_ceiling_drops_to_ceiling():
    g = _grant(level=4)
    rows = [_scored(i) for i in range(300)]
    res = L.evaluate(g, _stats(rows, g), None, NOW, ceiling=2)
    assert res["demote_to"] == 2


def test_paused_grant_is_never_ready():
    g = _grant(level=1, state="paused")
    res = L.evaluate(g, _stats([_review(i) for i in range(30)], g), None, NOW)
    assert not res["ready"]


def test_top_level_has_no_next_step():
    g = _grant(level=4)
    res = L.evaluate(g, _stats([], g), None, NOW)
    assert res["next_level"] is None and res["ready"] is False


def test_proposal_answers_count_after_the_action_ran():
    rows = [
        _scored(
            i,
            mode="proposed",
            score={"within_band": True, "band_ok": True, "agreement": a},
        )
        for i, a in enumerate([1.0, 1.0, 0.5, 0.0])
    ]
    st = L.compute_stats(rows, now=NOW)
    assert (st["approved"], st["edited"], st["rejected"]) == (2, 1, 1)
    assert st["no_edit_rate"] == pytest.approx(2 / 3)


def _random_rows(rng: random.Random, grant: dict) -> list[dict]:
    rows = []
    for i in range(rng.randint(0, 260)):
        kind = rng.random()
        if kind < 0.3:
            rows.append(_review(i, rng.choice(["agree", "different", "unsure"])))
        elif kind < 0.85:
            rows.append(
                _scored(
                    i,
                    held=rng.random() < 0.9,
                    config=rng.choice(["h1", "h1", "h2"]),
                    harm=rng.random() < 0.02,
                )
            )
        else:
            rows.append(
                {
                    "created_at": NOW - timedelta(minutes=i),
                    "status": rng.choice(["rejected", "executed", "expired"]),
                    "mode": "proposed",
                    "outcome_status": rng.choice(["unknown", "pending", "none"]),
                    "harm": False,
                }
            )
    return rows


@pytest.mark.parametrize("seed", range(300))
def test_ladder_properties_hold_for_random_records(seed):
    rng = random.Random(seed)
    level = rng.randint(0, 4)
    tier = rng.choice(["low", "medium", "high", "critical"])
    g = _grant(
        level=level,
        ceiling=rng.choice([1, 2, 3, 4]),
        state=rng.choice(["active", "active", "paused"]),
        since_days=rng.randint(0, 90),
    )
    rows = _random_rows(rng, g)
    st = _stats(rows, g, current=rng.choice(["h1", "h2"]))
    cap = L.effective_ceiling(tier, rng.choice([None, 2, 3, 4]), g["ceiling"])
    policy = rng.choice([None, {"to_asks_first": {"min_reviews": 5}}])
    res = L.evaluate(g, st, policy, NOW, ceiling=cap)
    # evaluate never moves a level, it only recommends: a person must act
    assert g["level"] == level
    if res["next_level"] is not None:
        assert res["next_level"] == level + 1
    if res["ready"]:
        assert res["next_level"] <= cap
        assert all(r["met"] for r in res["requirements"])
        assert res["demote_to"] is None
        assert g["state"] == "active"
    if res["blocked_by_ceiling"]:
        assert not res["ready"]
    if res["demote_to"] is not None:
        assert res["demote_to"] < level
        assert res["demote_to"] <= cap or level <= cap
    if level > 2 and st["harm_since_level"]:
        assert res["demote_to"] is not None and res["demote_to"] <= 2
    for r in res["requirements"]:
        assert isinstance(r["label"], str) and r["label"]
        assert r["fix"] is None or r["fix"]["href"].startswith("/")
        assert not r["label"][0].islower()
