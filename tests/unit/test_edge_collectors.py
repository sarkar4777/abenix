"""Abenix Edge collectors on the platform side: catalog, validation, secrets, install commands, status."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from app.services import edge_collectors as EC

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "apps" / "edge-runtime"


def _ok(c: dict) -> dict:
    clean, problems = EC.validate(c)
    assert problems == {}, problems
    return clean


def test_catalog_matches_the_gateway_collectors() -> None:
    sys.path.insert(0, str(EDGE))
    from abenix_edge.collectors import types

    assert {t["type"] for t in EC.CATALOG} == set(types())
    # every field the platform offers is read by the collector on the gateway
    for t in EC.CATALOG:
        src = (
            EDGE
            / "abenix_edge"
            / "collectors"
            / f"{ {'can': 'can_bus', 'nmea_gps': 'nmea'}.get(t['type'], t['type']) }.py"
        ).read_text()
        for f in t["fields"]:
            assert (
                f'"{f["key"]}"' in src
            ), f"{t['type']}.{f['key']} is offered but never read on the gateway"


def test_every_field_has_help_or_an_example() -> None:
    for t in EC.CATALOG:
        assert t["description"] and t["asset_hint"]
        for f in t["fields"]:
            assert (
                f.get("help")
                or f.get("example")
                or f.get("options")
                or f["kind"] == "secret"
                or f.get("default") is not None
            ), f"{t['type']}.{f['key']} has no help, example or default"


def test_can_collector_validation() -> None:
    c = _ok(
        {
            "type": "can",
            "name": "Truck 12 bus",
            "asset": {"group": "fleet", "node": "truck-12"},
            "channel": "can0",
        }
    )
    assert (
        c["protocol"] == "j1939"
        and c["bitrate"] == "250000"
        and c["interface"] == "socketcan"
    )
    assert c["id"].startswith("truck-12-bus-")
    _, p = EC.validate(
        {
            "type": "can",
            "name": "x",
            "asset": {"group": "fleet", "node": "t.12"},
            "interface": "socketcand",
            "parts": "engine",
        }
    )
    assert "asset.node" in p and "letters, digits" in p["asset.node"]
    assert p["host"].startswith("socketcand address is needed, such as 10.0.4.20")
    assert "address=part" in p["parts"]
    _, p = EC.validate(
        {
            "type": "can",
            "name": "x",
            "asset": {"group": "g", "node": "n"},
            "protocol": "dbc",
        }
    )
    assert p["dbc"].startswith("DBC file is needed")
    _, p = EC.validate(
        {
            "type": "can",
            "name": "x",
            "asset": {"group": "g", "node": "n"},
            "protocol": "obd2",
            "obd_pids": "0C, ZZ",
        }
    )
    assert "not a PID Edge reads" in p["obd_pids"]
    _, p = EC.validate(
        {
            "type": "can",
            "name": "x",
            "asset": {"group": "g", "node": "n"},
            "dbc": "BO_ nonsense",
        }
    )
    assert (
        p["dbc"].startswith("The DBC file could not be read")
        or p["dbc"] == "The DBC file has no messages in it"
    )


DBC = 'VERSION ""\nNS_ :\nBS_:\nBU_: ECU\nBO_ 2364540158 EEC1: 8 ECU\n SG_ EngineSpeed : 24|16@1+ (0.125,0) [0|8031.875] "rpm" ECU\n'


def test_dbc_summary_names_the_pgn() -> None:
    assert EC.dbc_problem(DBC) is None
    s = EC.dbc_summary(DBC)
    assert s["count"] == 1 and s["messages"][0]["pgn"] == 61444
    assert s["messages"][0]["signals"] == [{"name": "EngineSpeed", "unit": "rpm"}]


def test_modbus_opcua_gps_mqtt_file_validation() -> None:
    _ok(
        {
            "type": "modbus",
            "name": "Meter",
            "asset": {"group": "plant", "node": "meter-1"},
            "host": "10.0.0.5",
            "registers": "v, holding, 0, float32, 1, V",
        }
    )
    _, p = EC.validate(
        {
            "type": "modbus",
            "name": "Meter",
            "asset": {"group": "plant", "node": "m"},
            "mode": "rtu",
            "registers": "v, nowhere, 0",
        }
    )
    assert (
        p["serial_port"].startswith("Serial port is needed")
        and "holding, input" in p["registers"]
    )
    _, p = EC.validate(
        {
            "type": "modbus",
            "name": "M",
            "asset": {"group": "p", "node": "m"},
            "host": "h",
            "port": "99999",
            "registers": "v, holding, 0",
        }
    )
    assert p["port"] == "Port must be from 1 to 65535"
    _ok(
        {
            "type": "opcua",
            "name": "Line PLC",
            "asset": {"group": "plant", "node": "line-2"},
            "endpoint": "opc.tcp://plc:4840",
            "nodes": "ns=3;s=SlowDouble1, Boiler/Temp_C, C",
        }
    )
    _, p = EC.validate(
        {
            "type": "opcua",
            "name": "x",
            "asset": {"group": "p", "node": "n"},
            "endpoint": "http://plc",
            "nodes": "Temp",
        }
    )
    assert (
        "should look like opc.tcp://" in p["endpoint"]
        and "not an OPC UA node id" in p["nodes"]
    )
    _, p = EC.validate(
        {
            "type": "opcua",
            "name": "x",
            "asset": {"group": "p", "node": "n"},
            "endpoint": "opc.tcp://p:1",
            "nodes": "i=85",
            "security_policy": "Basic256Sha256",
        }
    )
    assert "Sign" in p["security_mode"]
    _ok(
        {
            "type": "nmea_gps",
            "name": "GPS",
            "asset": {"group": "fleet", "node": "van-3"},
            "port": "tcp://10.0.0.1:10110",
        }
    )
    _, p = EC.validate(
        {
            "type": "nmea_gps",
            "name": "GPS",
            "asset": {"group": "fleet", "node": "van-3"},
            "port": "COM3",
        }
    )
    assert "/dev/ttyUSB0" in p["port"]
    _ok(
        {
            "type": "mqtt_bridge",
            "name": "Zigbee",
            "asset": {"group": "site", "node": "{topic.1}"},
            "broker": "mqtt://10.0.0.2:1883",
        }
    )
    _, p = EC.validate(
        {
            "type": "file_tail",
            "name": "Log",
            "asset": {"group": "p", "node": "n"},
            "path": "logs/*.csv",
        }
    )
    assert p["path"].startswith("Use the full path")
    _, p = EC.validate({"type": "zigbee"})
    assert "Pick what this collector reads" in p["type"]


def test_secrets_are_kept_masked_and_reached_the_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import crypto

    monkeypatch.setattr(crypto, "encrypt", lambda t, v: f"enc:{v}")
    monkeypatch.setattr(
        crypto, "decrypt", lambda t, v: v[4:] if v.startswith("enc:") else v
    )
    c = _ok(
        {
            "type": "opcua",
            "name": "PLC",
            "asset": {"group": "p", "node": "n"},
            "endpoint": "opc.tcp://p:4840",
            "nodes": "i=85",
            "password": "s3cret",
        }
    )
    stored = EC.merge_secrets(dict(c), None, "t1")
    assert stored["password"] == "enc:s3cret"
    assert EC.masked(stored)["password"] == EC.MASK
    again = EC.merge_secrets({**c, "password": EC.MASK}, stored, "t1")
    assert again["password"] == "enc:s3cret"
    assert EC.for_gateway(again, "t1")["password"] == "s3cret"


def test_settings() -> None:
    s, p = EC.clean_settings({})
    assert p == {} and s == {
        "buffer_max_mb": 1024,
        "buffer_max_age_h": 72,
        "gzip": True,
        "heartbeat_s": 15,
        "self_metrics_s": 10,
    }
    _, p = EC.clean_settings({"buffer_max_age_h": 9999})
    assert p["buffer_max_age_h"] == "Keep readings for (hours) must be from 1 to 720"


def test_install_commands_follow_what_is_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "EDGE_COLLECTOR_IMAGE", "registry.example/abenix/edge-runtime:2.5.8"
    )
    can = _ok(
        {
            "type": "can",
            "name": "Bus",
            "asset": {"group": "fleet", "node": "truck-12"},
            "channel": "can0",
            "bitrate": "500000",
        }
    )
    rtu = _ok(
        {
            "type": "modbus",
            "name": "Genset",
            "asset": {"group": "site", "node": "genset"},
            "mode": "rtu",
            "serial_port": "/dev/ttyUSB0",
            "registers": "v, holding, 0",
        }
    )
    tail = _ok(
        {
            "type": "file_tail",
            "name": "Log",
            "asset": {"group": "p", "node": "n"},
            "path": "/data/plc/*.csv",
        }
    )
    out = EC.install(
        "truck-12-ab12", "https://abenix.example.com", "etk_abc", [can, rtu, tail]
    )
    d = out["docker_run"]
    assert (
        "ABENIX_ENROLL_TOKEN=etk_abc" in d
        and "--network host" in d
        and "--device /dev/ttyUSB0" in d
    )
    assert "-v /data/plc:/data/plc:ro" in d and d.rstrip().endswith(
        "registry.example/abenix/edge-runtime:2.5.8"
    )
    compose = yaml.safe_load(out["compose"])
    svc = compose["services"]["abenix-edge"]
    assert (
        svc["network_mode"] == "host"
        and svc["environment"]["ABENIX_URL"] == "https://abenix.example.com"
    )
    docs = list(yaml.safe_load_all(out["kubernetes"]))
    kinds = [x["kind"] for x in docs]
    assert kinds == ["Namespace", "Secret", "StatefulSet"]
    pod = docs[2]["spec"]["template"]["spec"]
    assert pod["hostNetwork"] is True
    assert docs[1]["stringData"]["ABENIX_ENROLL_TOKEN"] == "etk_abc"
    assert {v["name"] for v in pod["volumes"]} == {"files0", "dev0"}
    assert (
        "systemctl enable --now abenix-edge" in out["systemd"]
        and "--network host" in out["systemd"]
    )
    assert out["can_setup"] == "sudo ip link set can0 up type can bitrate 500000"
    plain = EC.install("yard-1", "http://abenix-api:8000", "etk_x", [])
    k = list(yaml.safe_load_all(plain["kubernetes"]))[2]["spec"]["template"]["spec"]
    assert "hostNetwork" not in k and "volumes" not in k
    assert k["containers"][0]["securityContext"]["runAsNonRoot"] is True
    assert k["securityContext"] == {"fsGroup": 1001}


def test_image_follows_the_cluster_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EDGE_COLLECTOR_IMAGE", raising=False)
    monkeypatch.setenv(
        "ML_MODEL_SERVING_IMAGE", "localhost:5000/abenix/model-serving:latest"
    )
    assert EC.image() == "localhost:5000/abenix/edge-runtime:latest"
    assert EC.url_problem("abenix.example.com")
    assert EC.url_problem("https://abenix.example.com") is None


def test_status_from_heartbeats() -> None:
    from app.routers.edge import _live_status, _serialize_gateway
    from models.edge_gateway import EdgeGateway

    now = datetime.now(timezone.utc)
    g = EdgeGateway(
        gateway_id="g",
        name="G",
        roles=["collect"],
        collectors=[],
        settings={},
        health={},
        deployed_agents=[],
        config_version=2,
        applied_version=0,
        registered_at=now,
        last_seen_at=now,
    )
    g.enroll_expires_at = now + timedelta(hours=1)
    assert _live_status(g) == "waiting"
    g.enroll_expires_at = now - timedelta(seconds=1)
    assert _live_status(g) == "expired"
    g.enrolled_at = now
    assert _live_status(g) == "online"
    g.last_seen_at = now - timedelta(seconds=120)
    assert _live_status(g) == "offline"
    g.revoked_at = now
    assert _live_status(g) == "revoked"
    row = _serialize_gateway(g, full=True)
    assert row["config_pending"] is True and row["settings"]["buffer_max_age_h"] == 72
    legacy = EdgeGateway(
        gateway_id="old",
        name="old",
        roles=["agents"],
        deployed_agents=[],
        registered_at=now,
        last_seen_at=now - timedelta(seconds=200),
    )
    assert _live_status(legacy) == "online"


def test_new_ids_have_no_dots() -> None:
    from app.routers.edge import _new_gateway_id

    gid = _new_gateway_id("Yard gateway 2.0")
    assert re.fullmatch(r"yard-gateway-2-0-[0-9a-f]{4}", gid)
