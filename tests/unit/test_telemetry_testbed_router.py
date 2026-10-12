"""Try the testbed: detection without Kubernetes calls, and one idempotent click to add every source."""

from __future__ import annotations

import asyncio
import functools
import json
import uuid
from types import SimpleNamespace

from fastapi.responses import JSONResponse

from app.routers import telemetry_testbed as TB


def arun(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))

    return wrapper


def ok(data, code=200):
    return JSONResponse({"success": True, "data": data}, status_code=code)


def bad(message, code=422):
    return JSONResponse({"success": False, "error": {"message": message}}, status_code=code)


SOURCES = [
    {"name": "Testbed · Kafka shop orders", "transport": "kafka", "config": {"bootstrap_servers": "redpanda:9092"}, "subjects": ["shop.orders"]},
    {"name": "Testbed · OPC UA PLC", "transport": "opcua", "config": {"endpoint": "opc.tcp://opc-plc:50000"}},
    {"name": "Testbed · HTTP push weather stations", "transport": "http_push", "config": {}},
    {"name": "Someone else's", "transport": "kafka"},
]


class Recorder:
    def __init__(self, fail=()):
        self.created, self.updated, self.rotated, self.pointed = [], [], [], []
        self.fail = set(fail)

    async def create(self, body):
        self.created.append(body)
        if body["name"] in self.fail:
            return bad("Kafka needs Bootstrap servers")
        data = {"id": str(uuid.uuid4()), "name": body["name"], "transport": body["transport"]}
        if body["transport"] == "http_push":
            data["ingest_token"] = "tpk_new"
        return ok(data, 201)

    async def update(self, cid, body):
        self.updated.append((cid, body))
        return ok({"id": cid, "name": body["name"]})

    async def rotate(self, cid):
        self.rotated.append(cid)
        return ok({"ingest_token": "tpk_rotated"})

    async def point(self, cid, token):
        self.pointed.append((cid, token))
        return True


@arun
async def test_first_click_creates_each_testbed_source_and_points_the_pusher():
    r = Recorder()
    out = await TB.connect_all(SOURCES, {}, r.create, r.update, r.rotate, {}, r.point)
    assert [b["name"] for b in r.created] == [s["name"] for s in SOURCES[:3]]
    assert all(b["enabled"] for b in r.created)
    assert [c["action"] for c in out["connections"]] == ["added"] * 3
    assert all("ingest_token" not in c for c in out["connections"])
    push_id = out["connections"][2]["id"]
    assert r.pointed == [(push_id, "tpk_new")] and out["pusher"] == "set"
    assert out["errors"] == [] and r.rotated == []


@arun
async def test_second_click_updates_in_place_and_keeps_the_pusher():
    r = Recorder()
    ids = {s["name"]: str(uuid.uuid4()) for s in SOURCES[:3]}
    push_id = ids["Testbed · HTTP push weather stations"]
    out = await TB.connect_all(SOURCES, ids, r.create, r.update, r.rotate, {"connection_id": push_id, "token": "t"}, r.point)
    assert r.created == [] and len(r.updated) == 3
    assert all("transport" not in body for _, body in r.updated)
    assert out["pusher"] == "kept" and r.rotated == [] and r.pointed == []


@arun
async def test_a_pusher_that_lost_its_target_gets_a_fresh_token():
    r = Recorder()
    ids = {s["name"]: str(uuid.uuid4()) for s in SOURCES[:3]}
    push_id = ids["Testbed · HTTP push weather stations"]
    out = await TB.connect_all(SOURCES, ids, r.create, r.update, r.rotate, {}, r.point)
    assert r.rotated == [push_id] and r.pointed == [(push_id, "tpk_rotated")]
    assert out["pusher"] == "set"


@arun
async def test_a_refused_source_is_reported_in_plain_words():
    r = Recorder(fail={"Testbed · Kafka shop orders"})
    out = await TB.connect_all(SOURCES, {}, r.create, r.update, r.rotate, {}, r.point)
    assert out["errors"] == [{"name": "Testbed · Kafka shop orders", "error": "Kafka needs Bootstrap servers"}]
    assert len(out["connections"]) == 2


@arun
async def test_probe_says_which_services_answer(monkeypatch):
    async def fake(h, port, timeout=1.0):
        return h.startswith("redpanda.") or port == 8080

    monkeypatch.setattr(TB, "reachable", fake)
    monkeypatch.setenv("TELEMETRY_TESTBED_NAMESPACE", "tb")
    services = await TB.probe()
    by = {s["transport"]: s for s in services}
    assert by["kafka"]["reachable"] and by["kafka"]["address"] == "redpanda.tb.svc.cluster.local:9092"
    assert by["http_push"]["reachable"] and not by["opcua"]["reachable"]
    assert len(services) == 7


@arun
async def test_status_endpoint(monkeypatch):
    async def fake_probe():
        return [{"name": "Kafka (Redpanda)", "transport": "kafka", "address": "x", "reachable": True}]

    async def rows(db, user):
        return [{"id": "1", "name": "Testbed · Kafka shop orders", "status": "connected"}]

    async def has(db, user, cap):
        return cap == "telemetry.manage"

    monkeypatch.setattr(TB, "probe", fake_probe)
    monkeypatch.setattr(TB, "_testbed_rows", rows)
    monkeypatch.setattr(TB.access, "has", has)
    resp = await TB.testbed_status(user=SimpleNamespace(), db=None)
    d = json.loads(resp.body)["data"]
    assert d["installed"] and d["can_connect"] and d["connections"][0]["status"] == "connected"


@arun
async def test_connect_needs_manage(monkeypatch):
    async def has(db, user, cap):
        return False

    monkeypatch.setattr(TB.access, "has", has)
    resp = await TB.testbed_connect(request=None, user=SimpleNamespace(), db=None)
    assert resp.status_code == 403


@arun
async def test_connect_without_a_testbed_says_how_to_install_it(monkeypatch):
    async def has(db, user, cap):
        return True

    async def nothing():
        raise OSError("no route")

    monkeypatch.setattr(TB.access, "has", has)
    monkeypatch.setattr(TB, "fetch_sources", nothing)
    resp = await TB.testbed_connect(request=None, user=SimpleNamespace(), db=None)
    assert resp.status_code == 502
    assert "bash scripts/deploy.sh testbed" in resp.body.decode()
