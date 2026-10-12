"""The rules pool: the ingest hands samples over by shard, the pool evaluates them, a shard changes hands."""

from __future__ import annotations

import asyncio
import json
import time

from app.telemetry.rules import pool as Pl
from app.telemetry.rules.evaluator import (
    SHARDS,
    Engine,
    MemoryGuard,
    MemoryShared,
    pack,
    shard_of,
    unpack,
)
from test_telemetry_rules import DEV, THRESH, T, _stream, rec, rule_row


def engine(shared=None, guard=None):
    docs: list = []

    async def emit(d):
        docs.extend(d)

    return Engine(shared or MemoryShared(), guard or MemoryGuard(), emit), docs


def test_shards_spread_and_rendezvous_moves_little():
    tenants = [f"t{i}" for i in range(400)]
    used = {shard_of(t) for t in tenants}
    assert len(used) == SHARDS
    two = ["a", "b"]
    three = ["a", "b", "c"]
    before = {s: Pl.owner_of(s, two) for s in range(SHARDS)}
    after = {s: Pl.owner_of(s, three) for s in range(SHARDS)}
    # adding a replica only moves shards to the new one
    assert all(after[s] in (before[s], "c") for s in range(SHARDS))
    assert {after[s] for s in range(SHARDS)} == {"a", "b", "c"}


def test_pool_mode_forwards_and_inprocess_evaluates():
    e, docs = engine()
    e.load([rule_row("r", THRESH)], [])
    sent: list = []

    async def forward(items):
        sent.extend(items)

    e.default_mode = "pool"
    # no pool alive, so the ingest keeps evaluating itself
    e.observe(T, "c", False, [rec({"p": 400}, 1)], time.time())
    asyncio.run(e.drain(None, forward))
    assert sent == [] and [d["type"] for d in docs] == ["fired"]
    e.pool_alive = True
    e.observe(T, "c", False, [rec({"p": 250}, 2)], time.time())
    asyncio.run(e.drain(None, forward))
    assert len(sent) == 1 and e.forwarded == 1
    # a workspace override wins over the platform default
    e.modes = {T: "inprocess"}
    e.observe(T, "c", False, [rec({"p": 251}, 3)], time.time())
    asyncio.run(e.drain(None, forward))
    assert len(sent) == 1


def test_pack_and_unpack_round_trip():
    e, _ = engine()
    e.load([rule_row("r", THRESH)], [])
    e.observe(T, "conn-1", False, [rec({"p": 400}, 7)], 1791720000.25)
    items = list(e.queue)
    entries = pack(items)
    assert list(entries) == [shard_of(T)]
    back = unpack(entries[shard_of(T)][0], e.by_id())
    assert len(back) == 1
    b = back[0]
    assert (b.rule.id, b.g, b.n, b.d, b.sample.value, b.sample.ts, b.conn_id) == (
        "r",
        "g",
        "n1",
        "hyd",
        400,
        7,
        "conn-1",
    )
    assert b.shared is True
    # a rule deleted since the samples were sent is skipped
    assert unpack(entries[shard_of(T)][0], {}) == []


def _entries(cond, values):
    """What the ingest would append for one asset's stream, one entry per message."""
    src, _ = engine()
    src.load([rule_row("r", cond, cooldown_s=5)], [])
    out = []
    for i, v in enumerate(values):
        src.observe(T, "c", False, [rec({"p": v}, 10_000 + i * 1000)], time.time())
        items = list(src.queue)
        src.queue.clear()
        out.extend(pack(items)[shard_of(T)])
    return out


def _run_pool(e, rules, entries):
    for fields in entries:
        asyncio.run(e.process(unpack(fields, rules)))


def test_a_shard_handed_over_mid_stream_fires_exactly_as_one_engine():
    for cond in (
        THRESH,
        {
            **DEV,
            "window_s": 20,
            "baseline_s": 120,
            "threshold": 1.03,
            "hysteresis": 0.01,
        },
    ):
        values = _stream()
        one, one_docs = engine()
        one.load([rule_row("r", cond, cooldown_s=5)], [])
        for i, v in enumerate(values):
            one.observe(T, "c", False, [rec({"p": v}, 10_000 + i * 1000)], time.time())
        asyncio.run(one.drain())
        want = [(d["type"], d["ts"]) for d in one_docs]
        assert want

        entries = _entries(cond, values)
        store, guard = MemoryShared(), MemoryGuard()
        a, a_docs = engine(store, guard)
        b, b_docs = engine(store, guard)
        for x in (a, b):
            x.load([rule_row("r", cond, cooldown_s=5)], [])
        cut = len(entries) // 2
        # a evaluates the first half and dies before deleting its last 20 entries,
        # so b reads those again before carrying on
        _run_pool(a, a.by_id(), entries[:cut])
        _run_pool(b, b.by_id(), entries[cut - 20 :])
        got = sorted(
            ((d["type"], d["ts"]) for d in a_docs + b_docs), key=lambda x: x[1]
        )
        assert got == want, cond["kind"]


def test_state_is_shared_so_the_new_owner_knows_the_rule_is_already_active():
    store, guard = MemoryShared(), MemoryGuard()
    a, a_docs = engine(store, guard)
    b, b_docs = engine(store, guard)
    for x in (a, b):
        x.load([rule_row("r", THRESH)], [])
    entries = _entries(THRESH, [400, 410, 420])
    _run_pool(a, a.by_id(), entries[:1])
    _run_pool(b, b.by_id(), entries[1:])
    assert [d["type"] for d in a_docs + b_docs] == ["fired"]
    st = json.loads(store.h[(T, "r")]["g/n1/hyd"])
    assert st["a"] is True


def _items(n=500):
    e, _ = engine()
    e.load([rule_row(f"r{i}", THRESH) for i in range(3)], [])
    for i in range(n // 3 + 1):
        e.observe(T, "conn-1", False, [rec({"p": 250.5 + i}, 1000 + i)], time.time())
    return e, list(e.queue)[:n]


def test_msgpack_hand_off_reads_back_from_a_binary_client_and_is_smaller():
    from app.telemetry.rules.evaluator import PACK_V2, _pack_v1

    e, items = _items()
    v2 = pack(items)[shard_of(T)][0]
    v1 = _pack_v1(items)[shard_of(T)][0]
    assert v2["b"][0] == PACK_V2
    assert len(v2["b"]) < len(v1["s"].encode()) / 2
    # a decode_responses=False client hands back bytes keys and values
    raw = {b"t": T.encode(), b"b": v2["b"]}
    back = unpack(raw, e.by_id())
    assert [(b.rule.id, b.sample.value, b.sample.ts) for b in back] == [
        (it.rule.id, it.sample.value, it.sample.ts) for it in items
    ]


def test_older_json_entries_are_still_read_and_newer_ones_are_refused():
    import pytest

    from app.telemetry.rules.evaluator import _pack_v1

    e, items = _items(10)
    v1 = _pack_v1(items)[shard_of(T)][0]
    assert len(unpack({k.encode(): v.encode() for k, v in v1.items()}, e.by_id())) == 10
    with pytest.raises(ValueError, match="newer"):
        unpack({b"t": T.encode(), b"b": bytes([9]) + b"\x90"}, e.by_id())


def test_stream_id_before():
    assert Pl._before("1700-3") == "1700-2"
    assert Pl._before("1700-0") == "1699-18446744073709551615"
