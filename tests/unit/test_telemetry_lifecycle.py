"""Forgetting devices: live state goes, history stays, quota frees, and a device that reports comes back."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.routers import telemetry as R
from app.telemetry import access, lifecycle, reads
from app.telemetry import ingest as I
from app.telemetry import keys as K
from app.telemetry import pipeline as P
from app.telemetry.connectors.base import Envelope
from telemetry_fakes import FakeRedis

T = str(uuid.uuid4())
EVERYONE = access.Scope(
    everything=True, visible=set(), commandable=set(), teams={}, connections=[]
)


def make_ingest():
    ing = I.Ingest()
    ing.r = FakeRedis()
    ing._scripts()
    return ing


def runtime(ing):
    row = {
        "id": "c1",
        "tenant": T,
        "name": "Fleet",
        "transport": "mqtt",
        "config": {"broker_url": "mqtt://x:1883", "subjects": ["#"]},
        "secrets": {},
        "decoder": "json",
        "decoder_config": {},
        "mapping": {
            "group": "fleet",
            "node": "$.id",
            "device": "$.part",
            "signals": {"exclude": ["id", "part"]},
        },
        "bindings": [],
        "strict": False,
        "enabled": True,
        "shared": False,
        "team_id": None,
        "sig": "s",
    }
    rt = P.Runtime(
        row, ing.replica, asyncio.get_running_loop(), ing._wake, ing._lookup, 100
    )
    ing.runtimes["c1"] = rt
    return rt


async def send(ing, rt, node, part, **values):
    env = Envelope(
        "c1",
        T,
        "fleet/x",
        json.dumps({"id": node, "part": part, **values}).encode(),
        t_recv=time.time(),
    )
    await ing.process([(rt, env)])


async def mark_offline(r, g, n, d, ago_s):
    at = int(time.time() * 1000) - ago_s * 1000
    raw = await r.hget(K.index(T), K.index_field(g, n, d))
    doc = json.loads(raw)
    doc.update({"online": False, "offline_at": at})
    await r.hset(K.index(T), K.index_field(g, n, d), json.dumps(doc))


def test_forgetting_a_part_keeps_history_and_it_comes_back_when_it_reports():
    async def go():
        ing = make_ingest()
        ing.store.history_interval_ms = 0
        rt = runtime(ing)
        await send(ing, rt, "ship-1", "gps", lat=1.5)
        await send(ing, rt, "ship-1", "door", open=1)
        assert await ing.r.hexists(K.index(T), "fleet/ship-1/gps")
        hist = len(ing.history)
        done = await lifecycle.forget(ing.r, T, [("fleet", "ship-1", "gps")])
        assert done == [{"group": "fleet", "node": "ship-1", "device": "gps"}]
        assert not await ing.r.hexists(K.index(T), "fleet/ship-1/gps")
        assert not await ing.r.hgetall(K.device(T, "fleet", "ship-1", "gps"))
        assert "gps" not in await ing.r.smembers(K.node_devices(T, "fleet", "ship-1"))
        assert await ing.r.hexists(K.index(T), "fleet/ship-1/door")
        assert len(ing.history) == hist
        channel, raw = ing.r.published[-1]
        assert channel == K.FORGOTTEN
        ing._forgotten(raw)
        await send(ing, rt, "ship-1", "gps", lat=2.5)
        doc = json.loads(await ing.r.hget(K.index(T), "fleet/ship-1/gps"))
        assert doc["online"] and doc["node"] == "ship-1" and doc["device"] == "gps"
        m = await ing.r.hget(K.device(T, "fleet", "ship-1", "gps"), "m:lat")
        assert json.loads(m)["v"] == 2.5

    asyncio.run(go())


def test_forgetting_an_asset_takes_its_parts_aliases_and_rings():
    async def go():
        r = FakeRedis()
        for d in ("", "engine", "safety"):
            await r.hset(
                K.index(T),
                K.index_field("g", "n", d),
                json.dumps({"group": "g", "node": "n", "device": d}),
            )
            await r.hset(K.device(T, "g", "n", d), "_conn", "c1")
        await r.sadd(K.node_devices(T, "g", "n"), "", "engine", "safety")
        await r.hset(K.aliases(T, "g", "n"), "1", json.dumps(["engine", "x", 9]))
        await r.lpush(K.frames(T, "g", "n"), "f")
        await r.hset(K.retired(T, "c1"), "g/n/engine/Old", "1")
        await r.hset(K.retired(T, "c1"), "g/m/engine/Old", "1")
        done = await lifecycle.forget(r, T, [("g", "n", "")])
        assert {x["device"] for x in done} == {"", "engine", "safety"}
        assert await r.hlen(K.index(T)) == 0
        assert not await r.hgetall(K.aliases(T, "g", "n"))
        assert not await r.smembers(K.node_devices(T, "g", "n"))
        assert await r.lrange(K.frames(T, "g", "n"), 0, -1) == []
        assert list(await r.hkeys(K.retired(T, "c1"))) == ["g/m/engine/Old"]

    asyncio.run(go())


def test_a_part_drops_only_its_own_aliases():
    async def go():
        r = FakeRedis()
        await r.hset(K.index(T), "g/n/a", json.dumps({"group": "g"}))
        await r.hset(K.aliases(T, "g", "n"), "1", json.dumps(["a", "x", 9]))
        await r.hset(K.aliases(T, "g", "n"), "2", json.dumps(["b", "y", 9]))
        await lifecycle.forget(r, T, [("g", "n", "a")])
        assert list(await r.hkeys(K.aliases(T, "g", "n"))) == ["2"]

    asyncio.run(go())


def test_bulk_forget_matches_offline_age_and_glob_and_frees_quota():
    async def go():
        ing = make_ingest()
        rt = runtime(ing)
        for i in range(5):
            await send(ing, rt, f"ship-{i}", "gps", lat=i)
        await send(ing, rt, "truck-1", "gps", lat=9)
        for i in range(4):
            await mark_offline(ing.r, "fleet", f"ship-{i}", "gps", 7200)
        await mark_offline(ing.r, "fleet", "truck-1", "gps", 7200)
        before = await ing.r.hlen(K.index(T))
        dry = await lifecycle.forget_matching(
            ing.r, T, EVERYONE, offline_for_s=3600, node_glob="ship-*", dry_run=True
        )
        assert dry["matched"] == 4 and dry["forgotten"] == 0
        assert len(dry["sample"]) == 4 and await ing.r.hlen(K.index(T)) == before
        out = await lifecycle.forget_matching(
            ing.r, T, EVERYONE, offline_for_s=3600, node_glob="ship-*", limit=3
        )
        assert out["forgotten"] == 3 and out["remaining"] == 1
        out = await lifecycle.forget_matching(
            ing.r, T, EVERYONE, offline_for_s=3600, node_glob="ship-*"
        )
        assert out["forgotten"] == 1 and out["remaining"] == 0
        assert await ing.r.hlen(K.index(T)) == before - 4
        rows = await reads.all_devices(ing.r, T)
        assert {(x["node"], x["device"]) for x in rows if x["device"]} == {
            ("ship-4", "gps"),
            ("truck-1", "gps"),
        }
        recent = await lifecycle.forget_matching(
            ing.r, T, EVERYONE, offline_for_s=3 * 3600
        )
        assert recent["matched"] == 0

    asyncio.run(go())


def test_candidates_respect_scope_and_connection():
    def row(node, online, cid):
        return {
            "group": "g",
            "node": node,
            "device": "",
            "online": online,
            "offline_at": 1,
            "connection_id": cid,
        }

    rows = [row("a", False, "c1"), row("b", False, "c2"), row("c", True, "c1")]
    only_c1 = access.Scope(
        everything=False, visible={"c1"}, commandable=set(), teams={}, connections=[]
    )
    got = lifecycle.candidates(rows, only_c1, offline_for_s=60)
    assert [x["node"] for x in got] == ["a"]
    got = lifecycle.candidates(rows, EVERYONE, offline_for_s=60, connection_id="c2")
    assert [x["node"] for x in got] == ["b"]


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=T, role="admin")


def test_delete_refuses_an_online_device_without_force(monkeypatch):
    async def go():
        r = FakeRedis()
        await r.hset(
            K.index(T),
            "g/n/a",
            json.dumps({"group": "g", "node": "n", "device": "a", "online": True}),
        )
        monkeypatch.setattr(R, "redis", lambda: r)

        async def has(db, user, cap):
            return True

        async def scope_for(db, user, fresh=False):
            return EVERYONE

        monkeypatch.setattr(access, "has", has)
        monkeypatch.setattr(access, "scope_for", scope_for)
        monkeypatch.setattr(R, "log_action", AsyncMock())
        db = AsyncMock()
        res = await R.forget_device("g", "n", None, "a", False, _user(), db)
        assert res.status_code == 409 and b"DEVICE_ONLINE" in res.body
        res = await R.forget_device("g", "n", None, "a", True, _user(), db)
        assert res.status_code == 200
        assert json.loads(res.body)["data"]["forgotten"] == 1
        res = await R.forget_device("g", "n", None, "a", True, _user(), db)
        assert res.status_code == 404

        async def no(db, user, cap):
            return False

        monkeypatch.setattr(access, "has", no)
        res = await R.forget_devices(R.ForgetIn(offline_for_s=3600), None, _user(), db)
        assert res.status_code == 403

    asyncio.run(go())


def test_the_device_limit_message_names_the_way_out():
    from app.telemetry import quota as Q

    words = Q.throttle_words("devices", 5000)
    assert "Forget devices offline" in words and "raise the limit" in words


def test_the_device_limit_banner_clears_once_devices_are_forgotten():
    async def go():
        ing = make_ingest()
        await ing.r.hset(K.throttle(T), "kind", "devices")
        ing.throttle_reason[T] = ("devices", 10, time.time())
        ing.store.device_count[T] = 3
        await ing._write_health()
        assert T not in ing.throttle_reason
        assert not await ing.r.hgetall(K.throttle(T))

    asyncio.run(go())


def test_offline_age_counts_from_the_last_message():
    now = int(time.time() * 1000)
    row = {
        "group": "g",
        "node": "n",
        "device": "",
        "online": False,
        "last_seen": now - 3 * 3600 * 1000,
        "offline_at": now - 1000,
        "connection_id": "c1",
    }
    got = lifecycle.candidates([row], EVERYONE, offline_for_s=3600, now_ms=now)
    assert len(got) == 1
