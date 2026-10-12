"""Ingest: Sparkplug sessions (seq, bdSeq, aliases, rebirth), the Redis stores, frames, feeds, quotas and leases."""

from __future__ import annotations

import asyncio
import json
import time
import uuid

import pytest

from app.telemetry import ingest as I
from app.telemetry import keys as K
from app.telemetry import reads
from app.telemetry import sparkplug as sp
from app.telemetry.sparkplug import sparkplug_b_pb2 as pb
from app.telemetry import pipeline as P
from app.telemetry.connectors.base import Envelope
from app.telemetry.decoders.can_frames import clean_frame
from telemetry_fakes import FakeRedis

T = str(uuid.uuid4())
G, N = "groundwork", "ipc-ex1"


def make_ingest(r: FakeRedis | None = None, replica: str | None = None) -> I.Ingest:
    ing = I.Ingest()
    ing.r = r or FakeRedis()
    if replica:
        ing.replica = replica
    ing._scripts()
    return ing


def make_row(
    cid="c1",
    tenant=None,
    shared=False,
    raw=("+/+/can/raw",),
    transport="mqtt",
    decoder="sparkplug_b",
    mapping=None,
    bindings=None,
):
    if bindings is None:
        bindings = (
            [{"subjects": list(raw), "decoder": "can_frames", "decoder_config": {}}]
            if raw
            else []
        )
    return {
        "id": cid,
        "tenant": tenant or T,
        "name": "Site broker",
        "transport": transport,
        "config": {"broker_url": "mqtt://x:1883", "subjects": ["spBv1.0/#"]},
        "secrets": {},
        "decoder": decoder,
        "decoder_config": {},
        "mapping": mapping or {},
        "bindings": bindings,
        "strict": False,
        "enabled": True,
        "shared": shared,
        "team_id": None,
        "sig": "s",
    }


def runtime(ing, row=None):
    row = row or make_row()
    rt = P.Runtime(
        row, ing.replica, asyncio.get_running_loop(), ing._wake, ing._lookup, 1000
    )
    rt.sent = []

    async def write(cfg, secrets, target, value):
        rt.sent.append((target["topic"], target["payload"]))
        return {"published": True}

    rt.connector.write = write
    ing.runtimes[row["id"]] = rt
    return rt


def birth(seq, bdseq, metrics, node=True):
    p = pb.Payload()
    p.timestamp = int(time.time() * 1000)
    p.seq = seq
    if node:
        m = p.metrics.add()
        m.name, m.datatype, m.long_value = "bdSeq", pb.Int64, bdseq
    for name, alias, dtype, field, value in metrics:
        m = p.metrics.add()
        m.name, m.alias, m.datatype = name, alias, dtype
        setattr(m, field, value)
    return p.SerializeToString()


def data(seq, metrics):
    p = pb.Payload()
    p.timestamp = int(time.time() * 1000)
    p.seq = seq
    for alias, field, value in metrics:
        m = p.metrics.add()
        m.alias = alias
        setattr(m, field, value)
    return p.SerializeToString()


def death(bdseq):
    p = pb.Payload()
    p.timestamp = int(time.time() * 1000)
    m = p.metrics.add()
    m.name, m.datatype, m.long_value = "bdSeq", pb.Int64, bdseq
    return p.SerializeToString()


async def send(ing, topic, payload, rt=None):
    rt = rt or ing.runtimes.get("c1") or runtime(ing)
    env = Envelope(rt.info.id, rt.info.tenant, topic, payload, t_recv=time.time())
    seen = []
    orig = ing.store.apply

    async def spy(conn, records, t_recv, b):
        seen.append(b)
        await orig(conn, records, t_recv, b)

    ing.store.apply = spy
    try:
        await ing.process([(rt, env)])
    finally:
        ing.store.apply = orig
    await asyncio.sleep(0)
    return seen[0] if seen else None


async def boot(ing):
    runtime(ing)
    await send(
        ing,
        f"spBv1.0/{G}/NBIRTH/{N}",
        birth(0, 1, [("Node/Uptime_s", 100, pb.Int64, "long_value", 5)]),
    )
    await send(
        ing,
        f"spBv1.0/{G}/DBIRTH/{N}/engine",
        birth(
            1,
            0,
            [
                ("Engine/Speed_rpm", 1, pb.Double, "double_value", 800.0),
                ("Safety/Hold", 2, pb.Boolean, "boolean_value", False),
            ],
            node=False,
        ),
    )


def test_births_and_aliased_data_land_in_the_latest_store():
    async def run():
        ing = make_ingest()
        await boot(ing)
        b = await send(
            ing, f"spBv1.0/{G}/DDATA/{N}/engine", data(2, [(1, "double_value", 1450.5)])
        )
        h = await ing.r.hgetall(K.device(T, G, N, "engine"))
        m = json.loads(h["m:Engine/Speed_rpm"])
        assert m["v"] == 1450.5 and m["t"] == "Double" and m["q"] == "good"
        assert h["_online"] == "1" and h["_conn"] == "c1"
        node = await ing.r.hgetall(K.device(T, G, N, ""))
        assert node["_bdseq"] == "1" and json.loads(node["m:Node/Uptime_s"])["v"] == 5
        assert await ing.r.smembers(K.node_devices(T, G, N)) == {"", "engine"}
        kinds = [e[1] for e in ing.events]
        assert kinds == ["telemetry.device_online", "telemetry.device_online"]
        assert b.latencies and ing.lat[T]
        # the live stream gets device state at once and metrics on the 10 Hz flush
        assert any('"type": "device"' in m for _, m in ing.r.published)
        pubs = ing.store.take_sse()
        eng = [json.loads(m) for _, m in pubs if '"device": "engine"' in m]
        assert eng and eng[0]["metrics"][0]["value"] == 1450.5
        rows = await reads.all_devices(ing.r, T)
        assert [(x["node"], x["device"], x["online"]) for x in rows] == [
            (N, "", True),
            (N, "engine", True),
        ]
        assert rows[1]["metric_count"] == 2 and rows[1]["connection_id"] == "c1"

    asyncio.run(run())


def test_seq_gap_counts_and_asks_for_one_rebirth():
    async def run():
        ing = make_ingest()
        await boot(ing)
        await send(
            ing, f"spBv1.0/{G}/DDATA/{N}/engine", data(5, [(1, "double_value", 1.0)])
        )
        await send(
            ing, f"spBv1.0/{G}/DDATA/{N}/engine", data(9, [(1, "double_value", 2.0)])
        )
        stats = await ing.r.hgetall(K.stats(T))
        assert stats["seq_gaps"] == "2"
        assert (await ing.r.hget(K.device(T, G, N, ""), "_seq_gaps")) == "2"
        sent = ing.runtimes["c1"].sent
        assert len(sent) == 1, "rebirth requests are spaced out"
        topic, payload = sent[0]
        assert topic == f"spBv1.0/{G}/NCMD/{N}"
        m = sp.decode(payload).metrics[0]
        assert m.name == "Node Control/Rebirth" and m.boolean_value is True
        gaps = [e for e in ing.events if e[1] == "telemetry.seq_gap"]
        assert (
            len(gaps) == 1
            and gaps[0][2]["expected"] == 2
            and gaps[0][2]["received"] == 5
        )
        idx = json.loads((await ing.r.hgetall(K.index(T)))[f"{G}/{N}/"])
        assert idx["seq_gaps"] == 2

    asyncio.run(run())


def test_seq_wraps_at_255_without_a_gap():
    async def run():
        ing = make_ingest()
        await boot(ing)
        for s in range(2, 256):
            await send(
                ing,
                f"spBv1.0/{G}/DDATA/{N}/engine",
                data(s, [(1, "double_value", 1.0)]),
            )
        await send(
            ing, f"spBv1.0/{G}/DDATA/{N}/engine", data(0, [(1, "double_value", 1.0)])
        )
        assert "seq_gaps" not in await ing.r.hgetall(K.stats(T))

    asyncio.run(run())


def test_rebirth_resets_aliases_and_stale_will_is_ignored():
    async def run():
        ing = make_ingest()
        await boot(ing)
        # node reconnects with a new session, alias 1 now means something else
        await send(
            ing,
            f"spBv1.0/{G}/NBIRTH/{N}",
            birth(0, 2, [("Node/Load_pct", 1, pb.Float, "float_value", 0.5)]),
        )
        aliases = await ing.r.hgetall(K.aliases(T, G, N))
        assert json.loads(aliases["1"]) == ["", "Node/Load_pct", pb.Float]
        assert "2" not in aliases
        assert not any(e[1] == "telemetry.device_online" for e in ing.events[2:])
        # the will of the first session arrives late and must not take the node down
        await send(ing, f"spBv1.0/{G}/NDEATH/{N}", death(1))
        assert (await ing.r.hget(K.device(T, G, N, ""), "_online")) == "1"
        assert (await ing.r.hgetall(K.stats(T)))["stale_death"] == "1"

    asyncio.run(run())


def test_node_death_takes_devices_offline_and_raises_an_alert():
    async def run():
        ing = make_ingest()
        await boot(ing)
        await send(ing, f"spBv1.0/{G}/NDEATH/{N}", death(1))
        for d in ("", "engine"):
            h = await ing.r.hgetall(K.device(T, G, N, d))
            assert h["_online"] == "0" and h["_offline_at"]
        off = [e for e in ing.events if e[1] == "telemetry.device_offline"]
        assert len(off) == 1 and off[0][2]["devices"] == ["engine"]
        firing = [a for f, a in ing.alerts if f]
        assert firing and firing[0]["labels"]["alertname"] == "TelemetryDeviceOffline"
        assert firing[0]["labels"]["node"] == N
        doc = await reads.node_detail(ing.r, T, G, N)
        assert doc["online"] is False
        assert all(m["quality"] == "stale" for m in doc["devices"][0]["metrics"])
        # coming back resolves the alert
        await send(ing, f"spBv1.0/{G}/NBIRTH/{N}", birth(0, 2, []))
        assert [f for f, _ in ing.alerts] == [False, False, True, False]

    asyncio.run(run())


def test_device_death():
    async def run():
        ing = make_ingest()
        await boot(ing)
        p = pb.Payload()
        p.seq = 2
        await send(ing, f"spBv1.0/{G}/DDEATH/{N}/engine", p.SerializeToString())
        assert (await ing.r.hget(K.device(T, G, N, "engine"), "_online")) == "0"
        assert (await ing.r.hget(K.device(T, G, N, ""), "_online")) == "1"
        assert ing.events[-1][1] == "telemetry.device_offline"
        assert ing.events[-1][2]["device"] == "engine"

    asyncio.run(run())


def test_a_new_replica_reads_aliases_and_state_from_redis():
    async def run():
        r = FakeRedis()
        first = make_ingest(r)
        await boot(first)
        second = make_ingest(r)
        runtime(second)
        await send(
            second,
            f"spBv1.0/{G}/DDATA/{N}/engine",
            data(7, [(1, "double_value", 99.0)]),
        )
        m = json.loads(await r.hget(K.device(T, G, N, "engine"), "m:Engine/Speed_rpm"))
        assert m["v"] == 99.0
        # the first message after a handover sets the baseline, it is not a gap
        assert "seq_gaps" not in await r.hgetall(K.stats(T))
        assert not second.runtimes["c1"].sent

    asyncio.run(run())


def test_data_before_any_birth_asks_for_a_rebirth():
    async def run():
        ing = make_ingest()
        runtime(ing)
        await send(
            ing, f"spBv1.0/{G}/DDATA/{N}/engine", data(4, [(1, "double_value", 1.0)])
        )
        assert ing.runtimes["c1"].sent[0][0] == f"spBv1.0/{G}/NCMD/{N}"
        assert not await ing.r.hgetall(K.device(T, G, N, "engine"))

    asyncio.run(run())


def test_raw_frames_ring_keeps_the_newest_2000():
    async def run():
        ing = make_ingest()
        topic = f"{G}/{N}/can/raw"
        for batch in range(21):
            frames = [
                {
                    "t": 1_700_000_000_000 + batch * 100 + i,
                    "id": 0x0CF00400,
                    "data": "F0FF7D401B0000FF",
                    "dlc": 8,
                }
                for i in range(100)
            ]
            await send(ing, topic, json.dumps(frames).encode())
        ring = await ing.r.lrange(K.frames(T, G, N), 0, -1)
        assert len(ring) == 2000
        newest = json.loads(ring[0])
        assert newest == {
            "t": 1_700_000_002_099,
            "id": 0x0CF00400,
            "data": "f0ff7d401b0000ff",
            "dlc": 8,
        }
        got = await reads.frames(ing.r, T, G, N, limit=5, since=1_700_000_002_096)
        assert [f["t"] for f in got] == [
            1_700_000_002_099,
            1_700_000_002_098,
            1_700_000_002_097,
        ]
        assert (await ing.r.hgetall(K.stats(T)))["frames"] == "2100"
        # a single frame object and a seconds timestamp are read too
        await send(
            ing,
            topic,
            json.dumps(
                {"t": 1_700_000_100.5, "id": "18FEEE00", "data": [1, 2]}
            ).encode(),
        )
        f = json.loads((await ing.r.lrange(K.frames(T, G, N), 0, 0))[0])
        assert f == {"t": 1_700_000_100_500, "id": 0x18FEEE00, "data": "0102", "dlc": 2}

    asyncio.run(run())


def test_clean_frame_refuses_garbage():
    assert clean_frame({"id": "zz"}, 1) is None
    assert clean_frame({"id": 1, "data": "xyz"}, 1) is None
    assert clean_frame("nope", 1) is None
    assert clean_frame({"id": 5}, 42) == {"t": 42, "id": 5, "data": "", "dlc": 0}


def test_feed_cache_and_history_sampling():
    async def run():
        ing = make_ingest()
        ing.store.history_interval_ms = 1000
        await boot(ing)
        hist_before = len(ing.history)
        for s, v in ((2, 10.0), (3, 11.0), (4, 12.0)):
            await send(
                ing, f"spBv1.0/{G}/DDATA/{N}/engine", data(s, [(1, "double_value", v)])
            )
        # births wrote each metric once, the burst within a second adds nothing more
        assert len(ing.history) == hist_before
        await ing._flush_seen_and_feeds()
        raw = await ing.r.get(K.feed(T, G, N, "engine", "Engine/Speed_rpm"))
        doc = json.loads(raw)
        assert doc["value"] == 12.0 and doc["fetched_at"] > 1e9
        assert (
            K.feed_id(G, N, "engine", "Engine/Speed_rpm")
            == "groundwork/ipc-ex1/engine/Engine/Speed_rpm"
        )
        rows = [r for r in ing.history if r[5] == "Safety/Hold"]
        assert rows and rows[0][6] == 0.0 and rows[0][7] is None

    asyncio.run(run())


def test_message_quota_throttles_the_noisy_workspace_only():
    async def run():
        ing = make_ingest()
        await boot(ing)
        ing.quotas[T] = {"max_msgs_per_sec": 3, "max_devices": 100}
        other = runtime(ing, make_row("c2", tenant=str(uuid.uuid4())))
        for s in range(2, 8):
            await send(
                ing,
                f"spBv1.0/{G}/DDATA/{N}/engine",
                data(s, [(1, "double_value", 1.0)]),
            )
        await send(ing, f"spBv1.0/{G}/NBIRTH/x", birth(0, 0, []), rt=other)
        assert int((await ing.r.hgetall(K.stats(T))).get("throttled", 0)) >= 1
        assert "throttled" not in await ing.r.hgetall(K.stats(other.info.tenant))
        await ing._write_health()
        thr = await ing.r.hgetall(K.throttle(T))
        assert thr["kind"] == "messages" and "skipped" in thr["reason"]

    asyncio.run(run())


def test_device_cap_refuses_new_devices():
    async def run():
        ing = make_ingest()
        await boot(ing)
        ing.store.device_cap[T] = 2
        ing.store.device_count[T] = 2
        await send(
            ing,
            f"spBv1.0/{G}/DBIRTH/{N}/safety",
            birth(
                2,
                0,
                [("Safety/Hold", 9, pb.Boolean, "boolean_value", True)],
                node=False,
            ),
        )
        assert not await ing.r.hgetall(K.device(T, G, N, "safety"))
        assert (await ing.r.hgetall(K.stats(T)))["devices_refused"] == "1"
        assert ing.throttle_reason[T][0] == "devices"

    asyncio.run(run())


def test_health_doc_has_what_the_page_shows():
    async def run():
        ing = make_ingest()
        await boot(ing)
        await ing._write_health()
        scope = type(
            "S",
            (),
            {
                "everything": True,
                "visible": set(),
                "connections": [],
                "sees": lambda self, c: True,
            },
        )()
        doc = await reads.health(
            ing.r,
            T,
            scope,
            {
                "max_connections": 20,
                "max_devices": 5000,
                "max_msgs_per_sec": 20000,
                "retention_days": 7,
            },
        )
        for key in (
            "ingest_up",
            "messages_per_second",
            "messages_per_second_by_node",
            "ingest_latency_ms_p50",
            "ingest_latency_ms_p99",
            "seq_gaps",
            "dropped",
            "throttled",
            "throttle_reason",
            "nodes_online",
            "nodes_total",
            "connections",
            "quota",
        ):
            assert key in doc, key
        assert doc["ingest_up"] is True
        assert doc["nodes_total"] == 1 and doc["nodes_online"] == 1
        assert doc["ingest_latency_ms_p99"] is not None
        assert doc["quota"]["used"]["devices"] == 2

    asyncio.run(run())


def test_rendezvous_moves_only_a_share_when_a_replica_joins():
    conns = [str(uuid.uuid4()) for _ in range(300)]
    two = {c: I.owner_of(c, ["a", "b"]) for c in conns}
    three = {c: I.owner_of(c, ["a", "b", "c"]) for c in conns}
    moved = [c for c in conns if two[c] != three[c]]
    assert all(three[c] == "c" for c in moved)
    assert 60 < len(moved) < 140


@pytest.fixture
def no_mqtt(monkeypatch):
    started: list[str] = []

    def fake_start(self):
        started.append(self.info.id)
        self.ctx.set_status("connected")

    async def fake_stop(self):
        return None

    monkeypatch.setattr(P.Runtime, "start", fake_start)
    monkeypatch.setattr(P.Runtime, "stop", fake_stop)
    return started


def _rows(n):
    out = {}
    for i in range(n):
        cid = str(uuid.UUID(int=i + 1))
        row = make_row(cid, raw=())
        row["name"] = f"b{i}"
        out[cid] = row
    return out


def test_leases_split_connections_and_move_when_a_replica_dies(no_mqtt):
    async def run():
        r = FakeRedis()
        a, b = make_ingest(r, "rep-a"), make_ingest(r, "rep-b")
        loop = asyncio.get_running_loop()
        for ing in (a, b):
            ing.loop = loop
            ing.rows = _rows(12)
            await r.zadd(K.REPLICAS, {ing.replica: int(time.time() * 1000)})
        await a.reconcile()
        await b.reconcile()
        assert set(a.runtimes) | set(b.runtimes) == set(a.rows)
        assert not set(a.runtimes) & set(b.runtimes)
        assert a.runtimes and b.runtimes
        # b dies without a goodbye: its heartbeat and leases lapse
        await r.zrem(K.REPLICAS, "rep-b")
        for cid in list(b.runtimes):
            await r.delete(K.lease(cid))
        await a.reconcile()
        assert set(a.runtimes) == set(a.rows)

    asyncio.run(run())


def test_a_joining_replica_takes_its_share(no_mqtt):
    async def run():
        r = FakeRedis()
        a = make_ingest(r, "rep-a")
        a.loop = asyncio.get_running_loop()
        a.rows = _rows(12)
        await r.zadd(K.REPLICAS, {"rep-a": int(time.time() * 1000)})
        await a.reconcile()
        assert len(a.runtimes) == 12
        b = make_ingest(r, "rep-b")
        b.loop = a.loop
        b.rows = _rows(12)
        await r.zadd(K.REPLICAS, {"rep-b": int(time.time() * 1000)})
        await b.reconcile()
        assert not b.runtimes, "b waits while a still holds the leases"
        await a.reconcile()
        await b.reconcile()
        assert len(a.runtimes) + len(b.runtimes) == 12 and b.runtimes

    asyncio.run(run())


def test_shared_subscription_runs_on_every_replica(no_mqtt):
    async def run():
        r = FakeRedis()
        reps = [make_ingest(r, f"rep-{i}") for i in range(3)]
        rows = _rows(1)
        for row in rows.values():
            row["shared"] = True
        for ing in reps:
            ing.loop = asyncio.get_running_loop()
            ing.rows = rows
            await r.zadd(K.REPLICAS, {ing.replica: int(time.time() * 1000)})
        for ing in reps:
            await ing.reconcile()
        assert all(len(ing.runtimes) == 1 for ing in reps)
        rt = next(iter(reps[0].runtimes.values()))
        assert rt.ctx.shared and rt.info.shared

    asyncio.run(run())


def test_pools_take_only_their_transports(no_mqtt, monkeypatch):
    assert I.takes("mqtt", {"mqtt", "kafka"}, set()) and not I.takes(
        "opcua", {"mqtt"}, set()
    )
    assert I.takes("opcua", set(), set()) and not I.takes("opcua", set(), {"opcua"})

    async def run():
        r = FakeRedis()
        a = make_ingest(r, "rep-default")
        b = make_ingest(r, "rep-industrial")
        rows = _rows(2)
        rows = {k: dict(v) for k, v in rows.items()}
        ids = list(rows)
        rows[ids[1]]["transport"] = "modbus_tcp"
        for ing in (a, b):
            ing.loop = asyncio.get_running_loop()
            ing.rows = rows
            await r.zadd(K.REPLICAS, {ing.replica: int(time.time() * 1000)})
        await r.hset(
            K.replica("rep-default"), mapping={"transports": json.dumps(["mqtt"])}
        )
        await r.hset(
            K.replica("rep-industrial"),
            mapping={"transports": json.dumps(["modbus_tcp"])},
        )
        monkeypatch.setattr(I, "TRANSPORTS", frozenset({"mqtt"}))
        await a.reconcile()
        monkeypatch.setattr(I, "TRANSPORTS", frozenset({"modbus_tcp"}))
        await b.reconcile()
        assert set(a.runtimes) == {ids[0]} and set(b.runtimes) == {ids[1]}

    asyncio.run(run())


def test_a_transport_no_pool_takes_says_so():
    from types import SimpleNamespace

    async def run():
        r = FakeRedis()
        now = int(time.time() * 1000)
        await r.zadd(K.REPLICAS, {"rep": now})
        await r.hset(
            K.replica("rep"),
            mapping={"at": now, "transports": json.dumps(["mqtt"]), "pool": "default"},
        )
        conn = SimpleNamespace(id="c9", enabled=True, transport="opcua")
        st = (await reads.connection_status(r, [conn]))["c9"]
        assert (
            st["status"] == "error"
            and "No ingest pool takes OPC UA" in st["last_error"]
        )
        reps = await reads.live_replicas(r)
        assert reads.pools(reps)[0]["name"] == "default"

    asyncio.run(run())


def test_a_rebirth_retires_metrics_it_no_longer_declares():
    async def run():
        ing = make_ingest()
        await boot(ing)
        before = len([r for r in ing.history if r[5] == "Safety/Hold"])
        assert before >= 1
        # the engine is born again without Safety/Hold
        await send(
            ing,
            f"spBv1.0/{G}/DBIRTH/{N}/engine",
            birth(
                5,
                0,
                [("Engine/Speed_rpm", 1, pb.Double, "double_value", 900.0)],
                node=False,
            ),
        )
        h = await ing.r.hgetall(K.device(T, G, N, "engine"))
        assert "m:Safety/Hold" not in h and "m:Engine/Speed_rpm" in h
        assert "2" not in await ing.r.hgetall(K.aliases(T, G, N))
        retired = await ing.r.hgetall(K.retired(T, "c1"))
        assert f"{G}/{N}/engine/Safety/Hold" in retired
        assert len([r for r in ing.history if r[5] == "Safety/Hold"]) == before
        assert not any(e[1] == "telemetry.device_offline" for e in ing.events)

    asyncio.run(run())


def test_offline_time_is_when_the_will_arrived_not_when_it_was_set():
    async def run():
        ing = make_ingest()
        await boot(ing)
        p = pb.Payload()
        p.timestamp = int(time.time() * 1000) - 20 * 60_000
        m = p.metrics.add()
        m.name, m.datatype, m.long_value = "bdSeq", pb.Int64, 1
        before = int(time.time() * 1000)
        await send(ing, f"spBv1.0/{G}/NDEATH/{N}", p.SerializeToString())
        h = await ing.r.hgetall(K.device(T, G, N, ""))
        assert h["_online"] == "0" and int(h["_offline_at"]) >= before - 1000
        assert abs(ing.store.skew.get("c1", 0)) < 60_000

    asyncio.run(run())
