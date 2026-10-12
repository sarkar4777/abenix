"""Any-stream pipeline: mapping, event time, dedupe, dead letters and replay, device keys, write-back."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routers import telemetry as R
from app.routers import telemetry_streams as RS
from app.telemetry import access
from app.telemetry import ingest as I
from app.telemetry import keys as K
from app.telemetry import mapping as M
from app.telemetry import pipeline as P
from app.telemetry import reads, sources
from app.telemetry.connectors.base import Envelope
from app.telemetry.decoders.base import DecodeError, MappingError, Metric, Record
from models.telemetry import TelemetryConnection
from telemetry_fakes import FakeRedis

T = str(uuid.uuid4())


def env(subject, payload, **kw):
    return Envelope(
        "c1",
        T,
        subject,
        payload if isinstance(payload, bytes) else json.dumps(payload).encode(),
        **kw,
    )


# mapping


def test_templates_from_subject_headers_and_paths():
    e = env("fleet/van-12/obd", {"v": {"id": "VIN9"}}, headers={"X-Site": "north"})
    assert M.render("{subject.1}", {}, e.subject, e.headers) == "van-12"
    assert (
        M.render(
            "{header.x-site}/{$.v.id}", {"v": {"id": "VIN9"}}, e.subject, e.headers
        )
        == "north/VIN9"
    )
    assert M.render("$.v.id", {"v": {"id": "VIN9"}}, e.subject, {}) == "VIN9"
    assert M.path_get({"a": [{"b": 2}]}, "$.a[0].b") == 2
    assert M.default_asset("orders") == ("stream", "orders", "")
    assert M.default_asset("payments.orders.eu") == ("payments", "orders", "eu")


@pytest.mark.parametrize(
    "subject,sep,asset",
    [
        ("edge/site-a/10.0.0.5", None, ("edge", "site-a", "10.0.0.5")),
        ("fleet.van-12.gps", None, ("fleet", "van-12", "gps")),
        ("pump.1", None, ("pump", "1", "")),
        ("pump.1", "none", ("stream", "pump.1", "")),
        ("plant/line.2/temp", "/", ("plant", "line.2", "temp")),
        ("a.b/c", ".", ("a", "b/c", "")),
    ],
)
def test_subject_split_rule(subject, sep, asset):
    assert M.default_asset(subject, sep) == asset
    m = {"subject_separator": sep} if sep else {}
    assert (
        M.render("{subject.1}", {}, subject, {}, sep)
        == (M.segments(subject, m) + ["", ""])[1]
    )
    rec = M.apply({"x": 1}, env(subject, {"x": 1}), m)[0]
    assert (rec.group, rec.node, rec.device) == asset


@pytest.mark.parametrize(
    "value,fmt,ms",
    [
        (1791720000, "auto", 1791720000000),
        (1791720000123, "auto", 1791720000123),
        (1791720000123456789, "auto", 1791720000123),
        ("2026-10-11T12:00:00Z", "auto", 1791720000000),
        (1791720000.5, "epoch_s", 1791720000500),
    ],
)
def test_timestamps(value, fmt, ms):
    assert M.parse_ts(value, fmt) == ms


def test_signals_flatten_filter_rename_units_types():
    doc = {
        "ts": 1791720000000,
        "id": "p7",
        "temp_c": "40.5",
        "flow": {"in": 3, "out": 2},
        "meta": {"fw": "1.2"},
    }
    m = {
        "node": "$.id",
        "signals": {
            "exclude": ["id", "meta"],
            "rename": {"flow/in": "Flow/In_lph"},
            "units": {"flow/in": "L/h"},
            "types": {"temp_c": "number"},
        },
    }
    rec = M.apply(doc, env("plant/l1", doc), m)[0]
    got = {x.name: (x.value, x.unit, x.type) for x in rec.metrics}
    assert got == {
        "temp_c": (40.5, "C", "number"),
        "Flow/In_lph": (3, "L/h", "number"),
        "flow/out": (2, None, "number"),
    }
    assert rec.ts == 1791720000000 and rec.node == "p7"


def test_records_path_event_mode_and_strict():
    doc = {"batch": [{"id": "a", "x": 1}, {"id": "b", "x": 2}]}
    recs = M.apply(
        doc,
        env("s/t", doc),
        {"records": "$.batch", "node": "$.id", "signals": {"exclude": ["id"]}},
    )
    assert [(r.node, r.metrics[0].value) for r in recs] == [("a", 1), ("b", 2)]
    order = {"type": "order.created", "order_id": "o-1", "amount": 99.5}
    ev = M.apply(order, env("payments/orders", order), {"event": {"name": "$.type"}})
    assert (
        ev[0].kind == "event"
        and ev[0].event_name == "order.created"
        and ev[0].event["amount"] == 99.5
    )
    with pytest.raises(MappingError):
        M.apply(
            {"temp": 1, "hum": 2},
            env("a/b", {}),
            {"strict": True, "signals": {"declared": ["temp"]}},
        )
    with pytest.raises(MappingError):
        M.apply({"x": 1}, env("a/b", {}), {"records": "$.missing"})


def test_suggest_finds_id_time_units_and_events():
    s = M.suggest(
        {
            "device_id": "t-9",
            "timestamp": "2026-10-11T12:00:00Z",
            "speed_kmh": 50,
            "type": "trip.started",
        },
        "fleet/vans",
    )
    assert s["node"] == "$.device_id"
    assert s["timestamp"] == {"path": "$.timestamp", "format": "iso"}
    assert s["signals"]["units"] == {"speed_kmh": "km/h"}
    assert s["event"] == {"name": "$.type"}


# ingest pipeline


def make_ingest():
    ing = I.Ingest()
    ing.r = FakeRedis()
    ing._scripts()
    return ing


def runtime(ing, decoder="json", mapping=None, transport="mqtt", shared=False):
    row = {
        "id": "c1",
        "tenant": T,
        "name": "Fleet",
        "transport": transport,
        "config": {"broker_url": "mqtt://x:1883", "subjects": ["#"]},
        "secrets": {},
        "decoder": decoder,
        "decoder_config": {},
        "mapping": mapping or {},
        "bindings": [],
        "strict": False,
        "enabled": True,
        "shared": shared,
        "team_id": None,
        "sig": "s",
    }
    rt = P.Runtime(
        row, ing.replica, asyncio.get_running_loop(), ing._wake, ing._lookup, 100
    )
    ing.runtimes["c1"] = rt
    return rt


def test_generic_source_comes_online_stores_and_counts():
    async def go():
        ing = make_ingest()
        rt = runtime(ing, mapping={"node": "$.id", "signals": {"exclude": ["id"]}})
        await ing.process(
            [
                (
                    rt,
                    env(
                        "fleet/vans",
                        {"id": "van-1", "ts": 1791720000000, "speed_kmh": 52},
                        t_recv=1791720000.2,
                    ),
                )
            ]
        )
        h = await ing.r.hgetall(K.device(T, "fleet", "van-1", ""))
        assert h["_online"] == "1"
        m = json.loads(h["m:speed_kmh"])
        assert m["v"] == 52 and m["u"] == "km/h" and m["ts"] == 1791720000000
        assert rt.counts["decoded"] == rt.counts["mapped"] == rt.counts["stored"] == 1
        assert ing.events[0][1] == "telemetry.device_online"
        sig = await ing.r.hgetall(K.signals(T, "c1"))
        assert "speed_kmh" in sig
        assert abs(ing.store.skew["c1"] - 200) < 1
        insp = await ing.r.lrange(K.inspector(T, "c1"), 0, -1)
        assert json.loads(insp[0])["ok"] is True

    asyncio.run(go())


def test_latest_only_moves_forward_but_late_data_reaches_history():
    async def go():
        ing = make_ingest()
        ing.store.history_interval_ms = 0
        rt = runtime(ing, mapping={"node": "$.id", "signals": {"exclude": ["id"]}})
        await ing.process([(rt, env("f/v", {"id": "a", "ts": 2000, "x": 2}))])
        await ing.process([(rt, env("f/v", {"id": "a", "ts": 1000, "x": 1}))])
        m = json.loads(await ing.r.hget(K.device(T, "f", "a", ""), "m:x"))
        assert m["v"] == 2
        assert [r[6] for r in ing.history if r[5] == "x"] == [2.0, 1.0]
        assert (await ing.r.hgetall(K.stats(T)))["late"] == "1"

    asyncio.run(go())


def test_duplicates_by_message_id_are_dropped():
    async def go():
        ing = make_ingest()
        rt = runtime(ing)
        e1 = env("f/v", {"x": 1}, msg_id="m-1")
        e2 = env("f/v", {"x": 2}, msg_id="m-1")
        await ing.process([(rt, e1)])
        await ing.process([(rt, e2)])
        assert rt.counts["duplicates"] == 1 and rt.counts["stored"] == 1

    asyncio.run(go())


def test_bad_messages_land_in_the_dlq_and_replay_after_a_fix(monkeypatch):
    async def go():
        ing = make_ingest()
        rt = runtime(ing, mapping={"strict": True, "signals": {"declared": ["temp"]}})
        await ing.process([(rt, env("plant/p1", {"temp": 1, "hum": 50}))])
        await ing.process([(rt, env("plant/p1", b"{not json"))])
        dlq = [json.loads(x) for x in await ing.r.lrange(K.dlq(T, "c1"), 0, -1)]
        assert len(dlq) == 2
        reasons = sorted(d["reason"] for d in dlq)
        assert (
            reasons[0].startswith("Mapping: Strict mode") and "not JSON" in reasons[1]
        )
        assert rt.counts["mapping_failed"] == 1 and rt.counts["decode_failed"] == 1
        diag = reads.diagnose(
            True,
            {
                "status": "connected",
                "pipeline": {**rt.counts, "received": 2},
                "last_reasons": rt.reasons,
            },
            [],
        )
        assert diag["state"] in ("decode_failed", "mapping_failed") and diag["fix"]
        return ing.r

    r = asyncio.run(go())
    c = TelemetryConnection(
        id=uuid.UUID(int=1),
        tenant_id=uuid.UUID(T),
        name="Plant",
        broker_url="mqtt://x",
        topics=["#"],
        raw_topics=[],
        transport="mqtt",
        decoder="json",
        decoder_config={},
        config={},
        secrets={},
        enabled=True,
        shared_subscription=False,
        strict=False,
        mapping={"signals": {"declared": ["temp", "hum"]}},
        team_id=None,
    )
    old = K.dlq(T, "c1")
    r.data[K.dlq(T, c.id)] = r.data.pop(old)
    monkeypatch.setattr(RS, "redis", lambda: r)
    monkeypatch.setattr(RS, "log_action", AsyncMock())
    monkeypatch.setattr(RS, "_conn", AsyncMock(return_value=c))
    monkeypatch.setattr(RS, "tsdb", AsyncMock(side_effect=RuntimeError("no tsdb here")))

    async def has(db, user, cap):
        return True

    monkeypatch.setattr(access, "has", has)
    db = SimpleNamespace(commit=AsyncMock(), execute=AsyncMock())
    out = json.loads(
        asyncio.run(
            RS.replay(
                c.id,
                None,
                {},
                SimpleNamespace(id=uuid.uuid4(), tenant_id=c.tenant_id),
                db,
            )
        ).body
    )["data"]
    assert out["replayed"] == 1 and len(out["still_failing"]) == 1
    assert "not JSON" in out["still_failing"][0]["reason"]
    h = asyncio.run(r.hgetall(K.device(T, "plant", "p1", "")))
    assert json.loads(h["m:hum"])["v"] == 50


def test_preview_and_suggest_endpoints(monkeypatch):
    c = TelemetryConnection(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(T),
        name="Payments",
        broker_url="",
        topics=["payments.orders"],
        raw_topics=[],
        transport="http_push",
        decoder="json",
        decoder_config={},
        config={},
        secrets={},
        enabled=True,
        shared_subscription=False,
        strict=False,
        mapping={},
        team_id=None,
    )
    monkeypatch.setattr(RS, "_conn", AsyncMock(return_value=c))
    db = SimpleNamespace(close=AsyncMock())
    sample = {
        "type": "order.created",
        "order_id": "o-1",
        "amount": 12.5,
        "ts": 1791720000000,
    }
    body = {
        "payload": sample,
        "subject": "payments.orders",
        "mapping": {"event": {"name": "$.type"}},
    }
    out = json.loads(asyncio.run(RS.preview(c.id, body, SimpleNamespace(), db)).body)[
        "data"
    ]
    assert out["errors"] == [] and out["records"][0]["kind"] == "event"
    assert out["records"][0]["event_name"] == "order.created"
    bad = json.loads(
        asyncio.run(RS.preview(c.id, {"payload": "{oops"}, SimpleNamespace(), db)).body
    )["data"]
    assert bad["records"] == [] and "not JSON" in bad["errors"][0]
    sug = json.loads(
        asyncio.run(
            RS.suggest(
                {
                    "payload": {"vehicle_id": "v1", "speed_kmh": 40},
                    "subject": "fleet/vans",
                },
                SimpleNamespace(),
            )
        ).body
    )["data"]
    assert (
        sug["mapping"]["node"] == "$.vehicle_id" and sug["records"][0]["node"] == "v1"
    )


# device keys


def test_device_key_writes_only_as_itself_and_gateway_stays_in_its_lane():
    recs = [Record(group="x", node="someone-else", metrics=[Metric("a", 1)])]
    out = sources.enforce(
        {
            sources.H_KIND: "device",
            sources.H_DEVICE: "truck-7",
            sources.H_GROUP: "fleet",
        },
        recs,
    )
    assert (out[0].group, out[0].node) == ("fleet", "truck-7")
    gw = {
        sources.H_KIND: "gateway",
        sources.H_DEVICE: "gw-1",
        sources.H_NODES: json.dumps(["press-*"]),
    }
    assert sources.enforce(gw, [Record(group="g", node="press-2")])[0].node == "press-2"
    with pytest.raises(DecodeError) as e:
        sources.enforce(gw, [Record(group="g", node="crane-1")])
    assert "may not write for crane-1" in str(e.value)


def test_csv_keys_and_ids():
    rows = sources.parse_csv("device_id,label\ntruck-1,North\ntruck-2,\n")
    assert [r["device_id"] for r in rows] == ["truck-1", "truck-2"]
    with pytest.raises(ValueError):
        sources.parse_csv("device_id\na/b\n")
    with pytest.raises(ValueError):
        sources.parse_csv("device_id\nx\nx\n")
    raw, prefix, digest = sources.new_key("gateway")
    assert (
        raw.startswith("tgk_")
        and prefix == raw[:12]
        and digest == sources.hash_key(raw)
    )


def test_edge_source_is_made_once_and_rekeyed():
    class DB:
        def __init__(self):
            self.added = []
            self.results = []

        async def execute(self, stmt):
            return self.results.pop(0)

        def add(self, o):
            self.added.append(o)

        async def flush(self):
            pass

    none = SimpleNamespace(scalar_one_or_none=lambda: None, first=lambda: None)
    db = DB()
    db.results = [none, none]
    src = asyncio.run(
        sources.ensure_edge_source(
            db, uuid.uuid4(), "gw-1", name="Quarry", group="quarry"
        )
    )
    conn, key = db.added
    assert src.created and conn.transport == "http_push" and conn.decoder == "values"
    assert (
        conn.config["edge_gateway_id"] == "gw-1"
        and key.kind == "gateway"
        and key.group == "quarry"
    )
    assert src.key.startswith("tgk_") and key.key_hash == sources.hash_key(src.key)
    old = SimpleNamespace(revoked_at=None)
    db2 = DB()
    db2.results = [
        SimpleNamespace(scalar_one_or_none=lambda: conn),
        SimpleNamespace(scalars=lambda: iter([old])),
    ]
    src2 = asyncio.run(
        sources.ensure_edge_source(db2, conn.tenant_id, "gw-1", name="Quarry")
    )
    assert not src2.created and old.revoked_at is not None and src2.key != src.key


# generic write-back with confirmation


def test_generic_command_renders_the_mapping_target_and_confirms(monkeypatch):
    r = FakeRedis()
    cid = uuid.uuid4()
    tenant = uuid.UUID(T)
    c = TelemetryConnection(
        id=cid,
        tenant_id=tenant,
        name="Plant",
        broker_url="mqtt://b:1883",
        topics=["plant/#"],
        raw_topics=[],
        transport="mqtt",
        decoder="json",
        decoder_config={},
        config={},
        secrets={},
        enabled=True,
        shared_subscription=False,
        strict=False,
        team_id=None,
        mapping={
            "writable": [
                {
                    "signal": "Setpoint",
                    "target": {
                        "topic": "plant/{node}/set",
                        "payload": '{"sp": {value}}',
                    },
                }
            ]
        },
    )

    async def seed():
        await r.hset(
            K.device(tenant, "plant", "pump1", ""),
            mapping={"_online": "1", "_conn": str(cid)},
        )

    asyncio.run(seed())
    monkeypatch.setattr(R, "redis", lambda: r)
    monkeypatch.setattr(R, "log_action", AsyncMock())

    async def has(db, user, cap):
        return True

    async def scope_for(db, u, fresh=False):
        return access.Scope(
            everything=True, visible=set(), commandable=set(), teams={}, connections=[c]
        )

    monkeypatch.setattr(access, "has", has)
    monkeypatch.setattr(access, "scope_for", scope_for)
    sent = []

    async def publish(conn_id, url, user, pw, topic, payload):
        sent.append((topic, payload))

        async def report():
            await asyncio.sleep(0.05)
            await r.hset(
                K.device(tenant, "plant", "pump1", ""),
                "m:Setpoint",
                K.pack_metric(42, "number", int(time.time() * 1000), "good"),
            )

        asyncio.get_running_loop().create_task(report())

    monkeypatch.setattr(R.brokers.publisher, "publish", publish)
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant)
    body = R.CommandIn(
        group="plant",
        node="pump1",
        signal="Setpoint",
        value=42,
        reason="raise flow",
        confirm_timeout_ms=2000,
    )
    out = json.loads(
        asyncio.run(
            R.send_command(body, None, user, SimpleNamespace(commit=AsyncMock()))
        ).body
    )["data"]
    assert sent == [("plant/pump1/set", b'{"sp": 42}')]
    assert (
        out["published"] and out["confirmed"] is True and out["confirm_ms"] is not None
    )
    body = R.CommandIn(
        group="plant", node="pump1", signal="Nope", value=1, reason="test it"
    )
    resp = asyncio.run(
        R.send_command(body, None, user, SimpleNamespace(commit=AsyncMock()))
    )
    assert (
        resp.status_code == 422
        and json.loads(resp.body)["error"]["error_code"] == "NOT_WRITABLE"
    )


def test_config_list_kind_and_checks():
    from app.telemetry.connectors.base import ConfigField, clean_config

    fields = (
        ConfigField(key="subjects", kind="list"),
        ConfigField(key="port", kind="int"),
        ConfigField(key="qos", kind="select", options=("0", "1")),
        ConfigField(key="tls", kind="bool"),
    )
    out, problems = clean_config(
        fields, {"subjects": "a/#, b/+\nc", "port": "1883", "qos": "1", "tls": "yes"}
    )
    assert (
        out == {"subjects": ["a/#", "b/+", "c"], "port": 1883, "qos": "1", "tls": True}
        and not problems
    )
    _, problems = clean_config(fields, {"subjects": 5, "port": "x", "qos": "2"})
    assert problems == [
        "subjects must be a list",
        "port must be a whole number",
        "qos must be one of 0, 1",
    ]


def test_numbered_batches_count_gaps_and_late_ones_fill_them():
    async def go():
        ing = make_ingest()
        rt = runtime(ing, decoder="values")
        for seq in (1, 2, 5, 3):
            doc = {
                "ts": 1791720000000 + seq,
                "seq": seq,
                "values": [{"name": "Temp", "value": seq}],
            }
            await ing.process([(rt, env("edge/site-a/plc-1", doc))])
        stats = await ing.r.hgetall(K.stats(T))
        assert stats["seq_gaps"] == "2"
        st = await ing.r.hgetall(K.seq_state(T, "edge", "site-a"))
        assert st["last"] == "5" and st["missing"] == "1"
        gaps = [e for e in ing.events if e[1] == "telemetry.seq_gap"]
        assert gaps and gaps[0][2]["missing"] == 2

    asyncio.run(go())


def test_filter_skips_control_messages_without_dead_letters():
    m = {
        "node": "$.symbol",
        "filter": {
            "require": ["$.symbol"],
            "match": {"$.type": "tick"},
            "exclude": {"$.type": ["subscribed", "heartbeat"]},
        },
    }
    assert (
        M.filter_reason({"type": "subscribed"}, m["filter"])
        == "Skipped by the filter: $.symbol is missing"
    )
    assert "not 'tick'" in M.filter_reason(
        {"symbol": "X", "type": "trade"}, m["filter"]
    )
    assert M.filter_reason({"symbol": "X", "type": "tick"}, m["filter"]) is None

    async def go():
        ing = make_ingest()
        rt = runtime(ing, mapping=m)
        await ing.process([(rt, env("market/prices", {"type": "subscribed"}))])
        await ing.process(
            [
                (
                    rt,
                    env(
                        "market/prices",
                        [
                            {"type": "heartbeat", "symbol": "X"},
                            {"type": "tick", "symbol": "ACME", "price": 10.5},
                        ],
                    ),
                )
            ]
        )
        assert (
            rt.counts["skipped"] == 1
            and rt.counts["stored"] == 1
            and not rt.counts.get("dlq")
        )
        assert "missing" in rt.reasons["skipped"]["reason"]
        assert not await ing.r.lrange(K.dlq(T, "c1"), 0, -1)
        h = await ing.r.hgetall(K.device(T, "market", "ACME", ""))
        assert json.loads(h["m:price"])["v"] == 10.5
        diag = reads.diagnose(
            True,
            {
                "status": "connected",
                "pipeline": {"received": 3, "skipped": 3},
                "last_reasons": rt.reasons,
            },
            [],
        )
        assert diag["state"] == "filtered"

    asyncio.run(go())


def test_suggest_proposes_a_require_filter_for_a_noisy_batch():
    batch = [
        {"symbol": "A", "price": 1},
        {"symbol": "B", "price": 2},
        {"type": "subscribed"},
    ]
    s = M.suggest(batch, "market/prices")
    assert s["node"] == "$.symbol" and s["filter"] == {"require": ["$.symbol"]}


def test_a_signal_that_stops_goes_stale_on_its_own_age():
    async def go():
        ing = make_ingest()
        rt = runtime(
            ing,
            mapping={
                "node": "$.id",
                "offline_after_s": 60,
                "signals": {"exclude": ["id"]},
            },
        )
        now = int(time.time() * 1000)
        await ing.process(
            [(rt, env("f/v", {"id": "a", "ts": now - 120_000, "door": 1, "x": 1}))]
        )
        await ing.process([(rt, env("f/v", {"id": "a", "ts": now, "x": 2}))])
        doc = await reads.node_detail(ing.r, T, "f", "a")
        q = {m["name"]: m["quality"] for m in doc["metrics"]}
        assert doc["online"] is True
        assert q == {"door": "stale", "x": "good"}

    asyncio.run(go())


def test_batched_sources_show_fractional_rates_and_readings():
    async def go():
        ing = make_ingest()
        rt = runtime(ing, mapping={"node": "$.id", "signals": {"exclude": ["id"]}})
        ago = time.time() - 2
        await ing.process(
            [(rt, env("f/v", {"id": "a", "x": 1, "y": 2, "z": 3}, t_recv=ago))]
        )
        doc = await reads.node_detail(ing.r, T, "f", "a")
        assert doc["msgs_per_sec"] == 0.2 and doc["readings_per_sec"] == 0.6
        rows = await reads.all_devices(ing.r, T)
        assert rows[0]["msgs_per_sec"] == 0.2
        h = await reads.health(
            ing.r,
            T,
            access.Scope(
                everything=True,
                visible=set(),
                commandable=set(),
                teams={},
                connections=[],
            ),
            {},
        )
        assert [x["node"] for x in h["messages_per_second_by_node"]] in ([], ["a"])

    asyncio.run(go())
