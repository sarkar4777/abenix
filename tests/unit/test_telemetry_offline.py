"""Sources without births go offline after silence, learnt from their own pace, announced without a flood."""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from app.telemetry import ingest as I
from app.telemetry import keys as K
from app.telemetry import store as ST
from app.telemetry.store import Batch, ConnInfo, Store
from telemetry_fakes import FakeRedis

T = str(uuid.uuid4())


def conn(offline_after_s=0, cid="c1"):
    return ConnInfo(id=cid, tenant=T, name="Shipments", offline_after_s=offline_after_s)


def test_the_silence_limit_is_learnt_from_the_device_and_can_be_set():
    s = Store(lambda *a: None)
    key = (T, "g", "n", "d")
    assert s.offline_after(conn(), s.interval_s(key)) == ST.OFFLINE_UNKNOWN_S
    for i in range(6):
        s._arrival(key, 1000.0 + i * 2)
    assert s.interval_s(key) == 2
    assert s.offline_after(conn(), s.interval_s(key)) == ST.OFFLINE_FLOOR_S
    slow = (T, "g", "n", "slow")
    for i in range(6):
        s._arrival(slow, 1000.0 + i * 20)
    assert s.offline_after(conn(), s.interval_s(slow)) == 200
    rare = (T, "g", "n", "rare")
    for i in range(6):
        s._arrival(rare, 1000.0 + i * 600)
    assert s.offline_after(conn(), s.interval_s(rare)) == ST.OFFLINE_CAP_S
    assert s.offline_after(conn(45), s.interval_s(key)) == 45
    s.default_offline_s = 300
    assert s.offline_after(conn(), s.interval_s(key)) == 300
    assert s.offline_after(conn(45), s.interval_s(key)) == 45


def test_a_quiet_fleet_raises_a_few_alerts_then_one_grouped():
    s = Store(lambda *a: None)
    c = conn()
    now = time.time()
    for i in range(12):
        s.last_data[(T, "logistics", "DHL", f"SHP{i}")] = (now - 2000, c)
    b = Batch()
    s.sweep(now, b)
    assert len(b.index) == 12
    want = int((now - 2000 + ST.OFFLINE_UNKNOWN_S) * 1000)
    assert all(x[2]["offline_at"] == want for x in b.index)
    single = [e for e in b.events if not e[2].get("grouped")]
    assert len(single) == ST.OFFLINE_EACH and len(b.alerts) == ST.OFFLINE_EACH
    b = Batch()
    s.flush_offline(now + ST.OFFLINE_WINDOW_S + 1, b)
    assert len(b.events) == 1 and b.events[0][2]["count"] == 7
    assert b.events[0][2]["grouped"] is True
    firing, alert = b.alerts[0]
    assert firing and alert["once"] and "7 devices" in alert["annotations"]["summary"]


def test_a_steady_device_stays_online():
    s = Store(lambda *a: None)
    c = conn()
    key = (T, "g", "n", "d")
    now = time.time()
    for i in range(6):
        s._arrival(key, now - 50 + i * 10)
    s.last_data[key] = (now - 5, c)
    b = Batch()
    s.sweep(now, b)
    assert not b.index and not b.events


def _row(cid, decoder):
    return {
        "id": cid,
        "tenant": T,
        "name": cid,
        "transport": "amqp" if decoder != "sparkplug_b" else "mqtt",
        "decoder": decoder,
        "mapping": {},
        "enabled": True,
        "shared": False,
        "team_id": None,
    }


def test_after_a_restart_devices_left_online_are_checked_at_once():
    async def go():
        ing = I.Ingest()
        ing.r = FakeRedis()
        ing._scripts()
        ing.rows = {"amqp1": _row("amqp1", "json"), "spb": _row("spb", "sparkplug_b")}
        old = int(time.time() * 1000) - 3 * 3600 * 1000
        fresh = int(time.time() * 1000) - 5000
        docs = {
            "logistics/DHL/SHP1": ("logistics", "DHL", "SHP1", "amqp1", old),
            "logistics/DHL/SHP2": ("logistics", "DHL", "SHP2", "amqp1", fresh),
            "site/pc1/": ("site", "pc1", "", "spb", old),
        }
        for field, (g, n, d, cid, seen) in docs.items():
            doc = {
                "group": g,
                "node": n,
                "device": d,
                "online": True,
                "last_seen": seen,
                "connection_id": cid,
            }
            await ing.r.hset(K.index(T), field, json.dumps(doc))
        await ing.offline_scan()
        idx = {f: json.loads(v) for f, v in (await ing.r.hgetall(K.index(T))).items()}
        assert idx["logistics/DHL/SHP1"]["online"] is False
        # offline from when it went quiet, not from the scan
        assert (
            idx["logistics/DHL/SHP1"]["offline_at"] == old + ST.OFFLINE_UNKNOWN_S * 1000
        )
        assert idx["logistics/DHL/SHP2"]["online"] is True
        assert idx["site/pc1/"]["online"] is True
        offline = [e for e in ing.events if e[1] == "telemetry.device_offline"]
        assert len(offline) == 1 and offline[0][2]["device"] == "SHP1"

    asyncio.run(go())


def test_a_grouped_alert_is_posted_once_and_not_kept_firing():
    async def go():
        ing = I.Ingest()
        ing.r = FakeRedis()
        posted = []

        async def post(a, firing):
            posted.append((a, firing))

        ing._post_alert = post
        alert = ST._group_alert(conn(), ["g/n/a", "g/n/b"], 1)
        await ing._alert(True, alert)
        assert posted and not await ing.r.hgetall("tel:alerts:firing")

    asyncio.run(go())


def _ingest():
    ing = I.Ingest()
    ing.r = FakeRedis()
    ing._scripts()
    return ing


def test_a_shared_source_device_another_replica_hears_stays_online():
    async def go():
        ing = _ingest()
        c = ConnInfo(id="k1", tenant=T, name="Plant", shared=True)
        now = time.time()
        heard = (T, "plant", "line-1", "press-1")
        gone = (T, "plant", "line-1", "press-2")
        done = (T, "plant", "line-1", "press-3")
        for key, seen, online in (
            (heard, now - 5, "1"),
            (gone, now - 2000, "1"),
            (done, now - 2000, "0"),
        ):
            ing.store.last_data[key] = (now - 2000, c)
            await ing.r.hset(
                K.device(*key),
                mapping={"_last_seen": str(int(seen * 1000)), "_online": online},
            )
        await ing._sweep()
        assert ing.store.last_data[heard][0] > now - 10
        assert (await ing.r.hget(K.device(*heard), "_online")) == "1"
        assert (await ing.r.hget(K.device(*gone), "_online")) == "0"
        offline = [e for e in ing.events if e[1] == "telemetry.device_offline"]
        assert [e[2]["device"] for e in offline] == ["press-2"]
        assert done not in ing.store.last_data

    asyncio.run(go())


def test_a_moved_connection_stops_being_watched_here():
    s = Store(lambda *a: None)
    s.last_data[(T, "g", "n", "a")] = (time.time() - 5000, conn(cid="c1"))
    s.last_data[(T, "g", "n", "b")] = (time.time() - 5000, conn(cid="c2"))
    s.drop_connection("c1")
    assert [k[3] for k in s.last_data] == ["b"]


def test_a_shared_device_marked_offline_elsewhere_comes_back_online_here():
    async def go():
        state = {"online": True}

        async def lookup(kind, *a):
            return state["online"] if kind == "online" else None

        s = Store(lookup)
        c = ConnInfo(id="k1", tenant=T, name="Plant", shared=True)
        assert await s._is_online(c, T, "g", "n", "d")
        state["online"] = False
        s.devices[(T, "g", "n", "d")].checked -= 5
        assert not await s._is_online(c, T, "g", "n", "d")

    asyncio.run(go())


def test_a_push_device_heard_once_goes_offline_in_minutes_not_a_quarter_hour():
    s = Store(lambda *a: None)
    c = ConnInfo(id="p1", tenant=T, name="Push", transport="http_push", shared=True)
    key = (T, "weather", "WS-1", "")
    now = time.time()
    s._arrival(key, now - 400)
    s.last_data[key] = (now - 400, c)
    assert s.offline_after(c, s.interval_s(key)) == ST.OFFLINE_UNKNOWN_S
    b = Batch()
    s.sweep(now, b)
    assert [x[2]["node"] for x in b.index] == ["WS-1"]
    assert b.index[0][2]["offline_at"] == int((now - 400 + ST.OFFLINE_UNKNOWN_S) * 1000)


def test_two_messages_use_the_gap_seen_so_far():
    s = Store(lambda *a: None)
    key = (T, "g", "n", "")
    s._arrival(key, 1000.0)
    s._arrival(key, 1010.0)
    assert s.interval_s(key) == 10
    assert s.offline_after(conn(), s.interval_s(key)) == 100
