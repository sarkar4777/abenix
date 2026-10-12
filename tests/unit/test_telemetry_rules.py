"""Signal rules: the condition state machines, the ingest evaluator, its cross-replica state, and the preview."""

from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.telemetry.decoders.base import Metric, Record
from app.telemetry.rules import model as M
from app.telemetry.rules import preview as P
from app.telemetry.rules.conditions import (
    Sample,
    compile_condition,
    edge_distance,
    norm,
    point_in_polygon,
    step,
)
from app.telemetry.rules.evaluator import Engine, MemoryGuard, MemoryShared
from app.telemetry.rules.index import AssetFacts, compile_rule

T = "11111111-1111-1111-1111-111111111111"


def run(
    cond: dict, values: list, cooldown_ms: int = 0, t0: int = 1_000_000, dt: int = 1000
):
    c = compile_condition(cond)
    st: dict = {}
    out = []
    for i, v in enumerate(values):
        o = step(c, st, Sample(v, t0 + i * dt, cond.get("signal", "")), cooldown_ms)
        out.append(
            "F" if o.fired else "C" if o.cleared else "s" if o.suppressed else "."
        )
    return "".join(out)


# conditions


def test_threshold_with_hysteresis_fires_once_per_excursion():
    c = {"kind": "threshold", "signal": "p", "op": ">", "value": 300, "hysteresis": 10}
    assert run(c, [280, 301, 310, 295, 305, 289, 301]) == ".F...CF"


def test_threshold_without_hysteresis_clears_at_the_limit():
    c = {"kind": "threshold", "signal": "p", "op": ">", "value": 300, "hysteresis": 0}
    assert run(c, [301, 300, 301]) == "FCF"


def test_below_threshold_and_cooldown():
    c = {"kind": "threshold", "signal": "p", "op": "<", "value": 10, "hysteresis": 0}
    # a comeback inside the quiet time is not sent, and neither is its clear
    assert run(c, [5, 20, 5, 20, 5], cooldown_ms=2500) == "FCs.F"


def test_range_outside_and_back_inside_the_margin():
    c = {"kind": "range", "signal": "t", "min": 10, "max": 20, "hysteresis": 1}
    assert run(c, [15, 21, 19.5, 18, 9, 12]) == ".F.CFC"


def test_rate_of_change_over_a_window():
    c = {
        "kind": "rate",
        "signal": "x",
        "limit": 5,
        "per": "s",
        "direction": "up",
        "window_s": 2,
        "hysteresis": 0,
    }
    # +1/s, then +10/s, then flat
    assert run(c, [0, 1, 2, 12, 22, 22, 22, 22]) == "...F.C.."


def test_state_equals_normalises_values():
    assert norm(True) == norm("TRUE") == "true"
    assert norm(1) == norm("1.0") == "1"
    c = {"kind": "state", "signal": "Task/State", "equals": "dig"}
    assert run(c, ["idle", "DIG", "dig", "swing", "dig"]) == ".F.CF"


def test_count_in_a_window():
    c = {
        "kind": "count",
        "signal": "p",
        "count": 3,
        "window_s": 5,
        "when": {"op": ">", "value": 100},
        "hysteresis": 0,
    }
    assert run(c, [101, 50, 102, 103, 50, 50, 50, 50, 50]) == "...F.C..."


DEV = {
    "kind": "deviation",
    "signal": "p",
    "window_s": 60,
    "baseline_s": 600,
    "mode": "ratio",
    "direction": "up",
    "threshold": 1.15,
    "hysteresis": 0.05,
}


def _dev_marks(cond, values, dt=1000):
    c = compile_condition(cond)
    st: dict = {}
    out = []
    for i, v in enumerate(values):
        o = step(c, st, Sample(v, i * dt, "p"), 0)
        out.append((i, "F" if o.fired else "C" if o.cleared else "."))
        if o.fired:
            out[-1] = (i, "F", o.words)
    return out, st


def test_deviation_ratio_fires_when_recent_runs_above_baseline_and_clears():
    # 10 min flat at 100, then 2 min at 130, then back to 100
    vals = [100.0] * 600 + [130.0] * 120 + [100.0] * 180
    marks, st = _dev_marks(DEV, vals)
    fired = [m for m in marks if m[1] == "F"]
    cleared = [m for m in marks if m[1] == "C"]
    assert len(fired) == 1 and 600 < fired[0][0] < 660
    assert "% above its level over the last 10 min" in fired[0][2]
    assert len(cleared) == 1 and cleared[0][0] > 720
    # state stays bounded however long it runs
    assert len(st["b"]) <= 135


def test_deviation_stays_quiet_until_the_baseline_has_filled():
    marks, _ = _dev_marks(DEV, [100.0] * 200 + [200.0] * 100)
    assert not [m for m in marks if m[1] == "F"]


def test_deviation_zscore_down():
    cond = {
        **DEV,
        "mode": "zscore",
        "direction": "down",
        "threshold": 3,
        "hysteresis": 1,
    }
    vals = [100.0 + (i % 7) for i in range(600)] + [80.0] * 90
    marks, _ = _dev_marks(cond, vals)
    fired = [m for m in marks if m[1] == "F"]
    assert len(fired) == 1 and "standard deviations below" in fired[0][2]


def test_deviation_words_and_checks():
    assert M.describe_condition(M.clean_condition(dict(DEV), {})) == (
        "the last 1 min of p run 15% above the last 10 min"
    )
    err: dict = {}
    M.clean_condition({**DEV, "threshold": 0.9}, err)
    assert "condition.threshold" in err
    err = {}
    M.clean_condition({**DEV, "baseline_s": 30}, err)
    assert "condition.baseline_s" in err


def test_geofence_enter_and_exit_with_margin():
    sq = [[0, 0], [10, 0], [10, 10], [0, 10]]
    c = compile_condition(
        {
            "kind": "geofence",
            "frame": "site",
            "x_signal": "x",
            "y_signal": "y",
            "polygon": sq,
            "on": "enter",
            "hysteresis": 2,
        }
    )
    st: dict = {}
    seq = [(-5, 5), (5, 5), (11, 5), (13, 5), (5, 5)]
    marks = []
    for i, (x, y) in enumerate(seq):
        o = step(c, st, Sample(None, i * 1000, "x", {"x": x, "y": y}), 0)
        marks.append("F" if o.fired else "C" if o.cleared else ".")
    # the first reading only sets where it stands, 1 m outside is inside the margin
    assert "".join(marks) == ".F.CF"


def test_geofence_baseline_inside_does_not_fire_enter():
    sq = [[0, 0], [10, 0], [10, 10], [0, 10]]
    c = compile_condition(
        {
            "kind": "geofence",
            "frame": "site",
            "x_signal": "x",
            "y_signal": "y",
            "polygon": sq,
            "on": "exit",
        }
    )
    st: dict = {}
    marks = []
    for i, (x, y) in enumerate([(5, 5), (20, 5), (5, 5)]):
        o = step(c, st, Sample(None, i, "x", {"x": x, "y": y}), 0)
        marks.append("F" if o.fired else "C" if o.cleared else ".")
    assert "".join(marks) == ".FC"


def test_geometry():
    sq = [[0, 0], [4, 0], [4, 4], [0, 4]]
    assert point_in_polygon(2, 2, sq) and not point_in_polygon(5, 2, sq)
    assert edge_distance(6, 2, sq, gnss=False) == pytest.approx(2)
    # 0.001 deg of longitude at the equator is about 111 m
    fence = [[0, -1], [0.001, -1], [0.001, 1], [0, 1]]
    assert edge_distance(0.002, 0, fence, gnss=True) == pytest.approx(111.2, rel=0.01)


def test_late_samples_never_move_a_rule_back():
    c = compile_condition({"kind": "threshold", "signal": "p", "op": ">", "value": 1})
    st: dict = {}
    assert step(c, st, Sample(5, 2000), 0).fired
    assert not step(c, st, Sample(0, 1000), 0).cleared
    assert st["late"] == 1


def test_stale_from_the_sweep():
    c = compile_condition({"kind": "stale", "seconds": 10})
    st: dict = {}
    assert not step(c, st, Sample(None, 1, "", {"age_ms": 2000}), 0).fired
    o = step(
        c,
        st,
        Sample(
            None,
            2,
            "",
            {"age_ms": 12_000, "offline_words": ", it went offline at 10:00:00 UTC"},
        ),
        0,
    )
    assert o.fired and "12 s" in o.words and "offline" in o.words
    assert step(c, st, Sample(None, 3, "", {"age_ms": 500}), 0).cleared


# validation and words


def test_clean_rejects_with_plain_words_per_field():
    with pytest.raises(M.RuleInvalid) as e:
        M.clean(
            {
                "name": "",
                "scope": {"kind": "asset"},
                "condition": {"kind": "range", "signal": "t", "min": 5, "max": 1},
            }
        )
    f = e.value.fields
    assert f["name"].startswith("Give the rule a name")
    assert "scope.node" in f and "condition.max" in f


def test_clean_geofence_checks_corners():
    with pytest.raises(M.RuleInvalid) as e:
        M.clean(
            {
                "name": "fence",
                "scope": {"kind": "type", "type": "vehicle"},
                "condition": {
                    "kind": "geofence",
                    "frame": "gnss",
                    "x_signal": "lon",
                    "y_signal": "lat",
                    "polygon": [[0, 0], [200, 0], [1, 1]],
                },
            }
        )
    assert "condition.polygon" in e.value.fields


def test_describe_reads_as_a_sentence():
    rule = M.clean(
        {
            "name": "EX1 pump",
            "scope": {
                "kind": "asset",
                "group": "groundwork",
                "node": "ipc-ex1",
                "device": "hydraulics",
            },
            "condition": {
                "kind": "threshold",
                "signal": "Hydraulics/Pump1Pressure_bar",
                "op": ">",
                "value": 300,
                "hysteresis": 10,
            },
            "actions": [
                {"kind": "alert"},
                {"kind": "command", "signal": "Safety/Hold", "value": True},
            ],
        }
    )
    s = M.describe(rule, {"groundwork/ipc-ex1/": "Excavator EX1"})
    assert s == (
        "When Hydraulics/Pump1Pressure_bar goes above 300 (clears at or below 290) on Excavator EX1 part hydraulics, "
        "raise an alert and set Safety/Hold to true."
    )


# the evaluator


def rule_row(
    rid: str, cond: dict, scope: dict | None = None, cooldown_s: int = 0
) -> dict:
    return {
        "id": rid,
        "tenant_id": T,
        "name": f"rule {rid}",
        "severity": "warning",
        "cooldown_s": cooldown_s,
        "scope": scope or {"kind": "asset", "group": "g", "node": "n1", "device": "*"},
        "condition": cond,
        "actions": [{"kind": "alert"}],
    }


def rec(values: dict, ts: int, node: str = "n1", device: str = "hyd") -> Record:
    return Record(
        group="g",
        node=node,
        device=device,
        kind="data",
        ts=ts,
        metrics=[Metric(name=k, value=v, ts=ts) for k, v in values.items()],
    )


def make_engine(shared=None, guard=None):
    docs: list = []

    async def emit(d):
        docs.extend(d)

    e = Engine(shared or MemoryShared(), guard or MemoryGuard(), emit)
    return e, docs


THRESH = {"kind": "threshold", "signal": "p", "op": ">", "value": 300, "hysteresis": 10}


def test_observe_ignores_workspaces_without_rules_and_unmatched_assets():
    e, docs = make_engine()
    e.load([rule_row("r1", THRESH)], [])
    assert e.observe("other-tenant", "c", False, [rec({"p": 400}, 1)], time.time()) == 0
    assert e.observe(T, "c", False, [rec({"p": 400}, 1, node="n2")], time.time()) == 0
    assert e.observe(T, "c", False, [rec({"q": 400}, 1)], time.time()) == 0
    assert e.observe(T, "c", False, [rec({"p": 400}, 1)], time.time()) == 1


def test_scope_by_type_and_tag_uses_the_registry_and_inherits_from_the_asset():
    e, docs = make_engine()
    e.load(
        [
            rule_row("rt", THRESH, {"kind": "type", "type": "machine"}),
            rule_row("rg", THRESH, {"kind": "tag", "tag": "north pit"}),
        ],
        [
            {
                "tenant_id": T,
                "grp": "g",
                "node": "n1",
                "device": "",
                "asset_type": "machine",
                "tags": ["north pit"],
                "display_name": "EX1",
            },
            {
                "tenant_id": T,
                "grp": "g",
                "node": "n2",
                "device": "",
                "asset_type": "vehicle",
                "tags": [],
                "display_name": "HT1",
            },
        ],
    )
    assert e.observe(T, "c", False, [rec({"p": 400}, 1, node="n1")], time.time()) == 2
    assert e.observe(T, "c", False, [rec({"p": 400}, 1, node="n2")], time.time()) == 0
    asyncio.run(e.drain())
    assert {d["rule_id"] for d in docs} == {"rt", "rg"}
    assert docs[0]["asset"] == "EX1 hyd"


def test_fires_once_and_the_firing_says_why():
    e, docs = make_engine()
    e.load(
        [rule_row("r1", THRESH)],
        [
            {
                "tenant_id": T,
                "grp": "g",
                "node": "n1",
                "device": "",
                "asset_type": None,
                "tags": [],
                "display_name": "Excavator EX1",
            }
        ],
    )
    for i, v in enumerate([250, 312.4, 320, 280, 310]):
        e.observe(T, "c", False, [rec({"p": v}, 1000 + i)], time.time())
    asyncio.run(e.drain())
    kinds = [d["type"] for d in docs]
    assert kinds == ["fired", "cleared", "fired"]
    assert docs[0]["detail"] == "p on Excavator EX1 hyd is 312.4, above 300."
    assert docs[0]["value"] == 312.4


def test_geofence_reads_both_coordinates_from_one_record():
    sq = [[0, 0], [10, 0], [10, 10], [0, 10]]
    geo = {
        "kind": "geofence",
        "frame": "site",
        "x_signal": "GNSS/X_m",
        "y_signal": "GNSS/Y_m",
        "polygon": sq,
        "on": "enter",
        "zone": "the pit",
    }
    e, docs = make_engine()
    e.load([rule_row("geo", geo)], [])
    e.observe(T, "c", False, [rec({"GNSS/X_m": -3, "GNSS/Y_m": 5}, 1)], time.time())
    e.observe(T, "c", False, [rec({"GNSS/X_m": 4, "GNSS/Y_m": 5}, 2)], time.time())
    # one coordinate alone uses the last seen partner
    e.observe(T, "c", False, [rec({"GNSS/X_m": 30}, 3)], time.time())
    e.observe(T, "c", False, [rec({"GNSS/X_m": 5}, 4)], time.time())
    asyncio.run(e.drain())
    assert [d["type"] for d in docs] == ["fired", "cleared", "fired"]
    assert "entered the pit" in docs[0]["detail"]


def test_flood_cap_and_duplicate_transitions_are_dropped_by_the_guard():
    e, docs = make_engine()
    e.load(
        [rule_row("r1", {"kind": "threshold", "signal": "p", "op": ">", "value": 0})],
        [],
    )
    vals = [1, 0] * 100
    for i, v in enumerate(vals):
        e.observe(T, "c", False, [rec({"p": v}, 10 + i)], time.time())
    asyncio.run(e.drain())
    fired = [d for d in docs if d["type"] == "fired"]
    assert len(fired) == 60
    assert e.stats["flood"] == 40


def _stream(n=400, seed=7):
    rnd = random.Random(seed)
    out = []
    v = 280.0
    for i in range(n):
        v += rnd.uniform(-8, 8)
        v = max(240, min(360, v))
        out.append(round(v, 2))
    return out


def _run_split(values, engines, shared_flag=True):
    """One asset's stream in arrival order, runs of 1 to 5 messages landing on a random replica."""
    rnd = random.Random(3)
    i = 0
    while i < len(values):
        e = engines[rnd.randrange(len(engines))]
        for _ in range(rnd.randint(1, 5)):
            if i >= len(values):
                break
            e.observe(
                T,
                "c",
                shared_flag,
                [rec({"p": values[i]}, 10_000 + i * 1000)],
                time.time(),
            )
            i += 1
        asyncio.run(e.drain())


@pytest.mark.parametrize(
    "cond",
    [
        THRESH,
        {"kind": "range", "signal": "p", "min": 260, "max": 340, "hysteresis": 5},
        {
            "kind": "count",
            "signal": "p",
            "count": 4,
            "window_s": 10,
            "when": {"op": ">", "value": 320},
        },
        {
            "kind": "rate",
            "signal": "p",
            "limit": 4,
            "per": "s",
            "direction": "either",
            "window_s": 3,
            "hysteresis": 1,
        },
        {
            **DEV,
            "window_s": 20,
            "baseline_s": 120,
            "threshold": 1.03,
            "hysteresis": 0.01,
        },
    ],
)
def test_split_across_two_replicas_gives_the_same_firings_as_one(cond):
    values = _stream()
    one, one_docs = make_engine()
    one.load([rule_row("r", cond, cooldown_s=5)], [])
    for i, v in enumerate(values):
        one.observe(T, "c", False, [rec({"p": v}, 10_000 + i * 1000)], time.time())
    asyncio.run(one.drain())

    store, guard = MemoryShared(), MemoryGuard()
    a, a_docs = make_engine(store, guard)
    b, b_docs = make_engine(store, guard)
    for x in (a, b):
        x.load([rule_row("r", cond, cooldown_s=5)], [])
    _run_split(values, [a, b])

    want = [(d["type"], d["ts"]) for d in one_docs]
    got = sorted([(d["type"], d["ts"]) for d in a_docs + b_docs], key=lambda x: x[1])
    assert want, "the stream should make the rule fire at least once"
    assert got == want


def test_compare_and_set_retries_when_another_replica_wrote_first():
    store, guard = MemoryShared(), MemoryGuard()
    e, docs = make_engine(store, guard)
    e.load([rule_row("r", THRESH)], [])
    e.observe(T, "c", True, [rec({"p": 400}, 5000)], time.time())

    def other_replica_writes():
        store.h.setdefault((T, "r"), {})["g/n1/hyd"] = json.dumps(
            {"a": True, "lt": 4000, "lf": 4000}
        )

    store.before_cas = other_replica_writes
    asyncio.run(e.drain())
    # the other replica already fired for this excursion, so this one must not
    assert docs == []
    assert e.stats["cas_retry"] == 1


def test_the_same_transition_seen_twice_is_sent_once():
    guard = MemoryGuard()
    a, a_docs = make_engine(MemoryShared(), guard)
    b, b_docs = make_engine(MemoryShared(), guard)
    for x in (a, b):
        x.load([rule_row("r", THRESH)], [])
        # a lease handover: both replicas briefly read the same messages
        x.observe(T, "c", False, [rec({"p": 400}, 7000)], time.time())
        asyncio.run(x.drain())
    assert len(a_docs) + len(b_docs) == 1


def test_stale_sweep_reads_ages_and_fires_once():
    e, docs = make_engine()
    e.load(
        [
            rule_row(
                "st",
                {"kind": "stale", "seconds": 10},
                {"kind": "asset", "group": "g", "node": "n1", "device": "*"},
            )
        ],
        [],
    )
    ages = {"v": (3000, None)}

    async def read(asks):
        assert asks == [(T, "g", "n1", "", "")]
        return [ages["v"]]

    asyncio.run(e.sweep(read))
    ages["v"] = (15_000, int(time.time() * 1000))
    asyncio.run(e.sweep(read))
    asyncio.run(e.sweep(read))
    ages["v"] = (200, None)
    asyncio.run(e.sweep(read))
    assert [d["type"] for d in docs] == ["fired", "cleared"]
    assert "has sent no data for 15 s, it went offline at" in docs[0]["detail"]


def test_observe_is_cheap():
    e, _ = make_engine()
    e.load([rule_row(f"r{i}", {**THRESH, "signal": f"s{i}"}) for i in range(200)], [])
    records = [rec({f"m{j}": j for j in range(40)} | {"s1": 1, "s2": 2}, 1)]
    n = 5000
    t0 = time.perf_counter()
    for _ in range(n):
        e.observe(T, "c", False, records, time.time())
    per_us = (time.perf_counter() - t0) / n * 1e6
    e.queue.clear()
    assert per_us < 200, per_us


# preview


def _rows(values, metric="p", device="hyd", t0=None):
    t0 = t0 or datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)
    return [
        {
            "time": t0 + timedelta(seconds=i),
            "grp": "g",
            "node": "n1",
            "device": device,
            "metric": metric,
            "num": v,
            "txt": None,
        }
        for i, v in enumerate(values)
    ]


def test_preview_replays_the_same_machine_and_explains():
    rule = {
        "scope": {"kind": "asset", "group": "g", "node": "n1", "device": "*"},
        "condition": THRESH,
        "cooldown_s": 0,
    }
    assets = P.replay(
        rule, _rows([250, 310, 320, 280, 305, 250, 301]), names={"g/n1/": "EX1"}
    )
    assert len(assets) == 1 and len(assets[0]["firings"]) == 3
    assert assets[0]["name"] == "EX1 hyd"
    assert (
        P.summary(rule, assets, 1)
        == "This rule would have fired 3 times in the last hour, on EX1 hyd (3)."
    )
    quiet = P.replay(rule, _rows([250, 260]), names={})
    assert (
        P.summary(rule, quiet, 1)
        == "This rule would not have fired in the last hour. p ranged from 250 to 260."
    )


def test_preview_stale_finds_gaps():
    rule = {"condition": {"kind": "stale", "seconds": 5}, "cooldown_s": 0}
    t0 = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)
    times = [("g", "n1", "", t0 + timedelta(seconds=s)) for s in (0, 1, 2, 20, 21, 22)]
    assets = P.replay_stale(rule, times, t0 + timedelta(seconds=40))
    assert [
        round((f["t"] - t0.timestamp() * 1000) / 1000) for f in assets[0]["firings"]
    ] == [7, 27]
    assert len(assets[0]["clears"]) == 1


def test_compiled_rule_matches_any_part_or_one_part():
    r = compile_rule(
        rule_row(
            "x", THRESH, {"kind": "asset", "group": "g", "node": "n1", "device": "hyd"}
        )
    )
    f = AssetFacts()
    assert r.matches("g", "n1", "hyd", f) and not r.matches("g", "n1", "engine", f)
