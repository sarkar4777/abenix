"""The in-cluster Abenix Edge demo, driven through the public API as an admin would from the Edge page.

deploy.sh pipes this into python inside the API pod:
    setup                 make or update the gateway "Edge demo yard", print its Kubernetes manifest with the
                          socketcand bus, the simulated ECUs and the uplink relay as sidecars
    wait                  wait for the first heartbeat and the first data, print the assets
    proof <t0> <t1>       check Edge/Seq history over a cut, print loss, repeats and order
    down                  remove the gateway and its source
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx
import yaml

NAME = "Edge demo yard"
GROUP = "edge-demo"
NS = "abenix-edge-demo"
TB = os.environ.get("TESTBED_NS", "abenix-testbed")
API_SVC = os.environ.get("API_SVC", "abenix-api.abenix.svc.cluster.local:8000")
IMAGE = os.environ.get("EDGE_IMAGE", "localhost:5000/abenix/edge-runtime:latest")
METER = """voltage_v, holding, 0, float32, 1, V
current_a, holding, 2, float32, 1, A
active_power_kw, holding, 4, float32, 1, kW
energy_kwh, holding, 6, uint32, 0.1, kWh
frequency_hz, holding, 8, uint16, 0.01, Hz
power_factor, holding, 9, int16, 0.001
setpoint_kw, holding, 10, uint16, 0.1, kW
temperature_c, holding, 11, int16, 0.1, C
breaker_closed, coil, 0"""
# what the testbed's opc-plc really serves: its Slow and Fast doubles all count up in lockstep,
# so they are not named as temperatures or pressures here
OPC_NODES = """ns=3;s=StepUp, Counters/StepUp
ns=3;s=AlternatingBoolean, Line1/Running
ns=3;s=SpikeData, Anomaly/Spike
ns=3;s=DipData, Anomaly/Dip
ns=3;s=PositiveTrendData, Trend/Rising
ns=3;s=NegativeTrendData, Trend/Falling"""


def log(*a: object) -> None:
    print(*a, file=sys.stderr, flush=True)


def client() -> tuple[httpx.Client, dict[str, str]]:
    c = httpx.Client(base_url="http://localhost:8000", timeout=30)
    r = c.post(
        "/api/auth/login",
        json={
            "email": os.environ.get("ADMIN_EMAIL", "admin@abenix.dev"),
            "password": os.environ.get("ADMIN_PASSWORD", "Admin123456"),
        },
    )
    r.raise_for_status()
    return c, {"Authorization": "Bearer " + r.json()["data"]["access_token"]}


def find(c: httpx.Client, h: dict[str, str]) -> dict | None:
    for g in c.get("/api/edge/gateways", headers=h).json()["data"]["gateways"]:
        if g["name"] == NAME:
            return g
    return None


def collectors() -> list[dict]:
    can = {
        "interface": "socketcand",
        "host": "127.0.0.1",
        "port": 29536,
        "channel": "vcan0",
        "bitrate": "250000",
    }
    return [
        {
            "type": "can",
            "name": "Truck 7 J1939 bus",
            **can,
            "protocol": "j1939",
            "request_pgns": "65253, 65260",
            "request_every_s": 10,
            "asset": {"group": GROUP, "node": "truck-7"},
            "interval_s": 2,
        },
        {
            "type": "can",
            "name": "Truck 7 OBD-II port",
            **can,
            "protocol": "obd2",
            "obd_pids": "0C, 0D, 05, 2F, 04",
            "asset": {"group": GROUP, "node": "truck-7-obd"},
            "interval_s": 2,
        },
        {
            "type": "nmea_gps",
            "name": "Truck 7 GPS",
            "port": "tcp://127.0.0.1:10110",
            "asset": {"group": GROUP, "node": "truck-7", "device": "gps"},
            "interval_s": 2,
        },
        {
            "type": "modbus",
            "name": "Yard energy meter",
            "mode": "tcp",
            "host": f"meter.{TB}.svc.cluster.local",
            "port": 502,
            "unit_id": 1,
            "registers": METER,
            "asset": {"group": GROUP, "node": "meter-1", "device": "main"},
            "interval_s": 2,
        },
        {
            "type": "opcua",
            "name": "OPC PLC simulator",
            "endpoint": f"opc.tcp://opc-plc.{TB}.svc.cluster.local:50000",
            "username": "abenix",
            "password": os.environ.get("OPCUA_PASSWORD", ""),
            "nodes": OPC_NODES,
            "read_mode": "subscribe",
            "asset": {"group": GROUP, "node": "opc-plc", "device": "plc"},
            "interval_s": 1,
        },
    ]


def setup() -> None:
    c, h = client()
    body = {
        "name": NAME,
        "roles": ["collect"],
        "collectors": collectors(),
        "settings": {
            "heartbeat_s": 5,
            "self_metrics_s": 2,
            "buffer_max_age_h": 72,
            "buffer_max_mb": 512,
            "gzip": True,
        },
    }
    g = find(c, h)
    if g is None:
        r = c.post("/api/edge/gateways", headers=h, json=body)
    else:
        r = c.patch(f"/api/edge/gateways/{g['id']}", headers=h, json=body)
    if r.status_code >= 300:
        log("gateway not saved:", r.json().get("error", {}).get("message"))
        sys.exit(1)
    g = r.json()["data"]
    log(
        f"gateway {g['gateway_id']} saved with {len(g['collectors'])} collectors, config version {g['config_version']}"
    )
    inst = c.post(
        f"/api/edge/gateways/{g['id']}/install",
        headers=h,
        json={"platform_url": "http://127.0.0.1:18000"},
    )
    if inst.status_code >= 300:
        log("install command refused:", inst.json().get("error", {}).get("message"))
        sys.exit(1)
    d = inst.json()["data"]
    docs = [x for x in yaml.safe_load_all(d["kubernetes"]) if x]
    sts = None
    for doc in docs:
        doc["metadata"]["namespace"] = NS
        if doc["kind"] == "Namespace":
            doc["metadata"] = {"name": NS}
        if doc["kind"] == "Secret":
            doc["metadata"]["name"] = "edge-demo"
        if doc["kind"] == "StatefulSet":
            sts = doc
    pod = sts["spec"]["template"]["spec"]
    sts["metadata"]["name"] = "edge-demo"
    sts["spec"]["serviceName"] = "edge-demo"
    sts["spec"]["selector"]["matchLabels"]["gateway"] = "edge-demo"
    sts["spec"]["template"]["metadata"]["labels"]["gateway"] = "edge-demo"
    edge = pod["containers"][0]
    edge["imagePullPolicy"] = "IfNotPresent"
    edge["envFrom"] = [{"secretRef": {"name": "edge-demo"}}]
    small = {
        "requests": {"cpu": "20m", "memory": "48Mi"},
        "limits": {"cpu": "300m", "memory": "160Mi"},
    }
    sec = {"runAsNonRoot": True, "allowPrivilegeEscalation": False}

    def side(name: str, module: str, env: dict[str, str]) -> dict:
        return {
            "name": name,
            "image": IMAGE,
            "imagePullPolicy": "IfNotPresent",
            "command": ["python", "-m", module],
            "env": [{"name": k, "value": v} for k, v in env.items()],
            "securityContext": sec,
            "resources": small,
        }

    # the machine side of the box: a user-space CAN bus over socketcand, the ECUs on it, and the uplink
    pod["containers"] = [
        side(
            "canbus",
            "abenix_edge.sim.canbus",
            {
                "CANBUS_LISTEN": "127.0.0.1",
                "CAN_CHANNEL": "vcan0",
                "CAN_BITRATE": "250000",
            },
        ),
        side(
            "ecu",
            "abenix_edge.sim.ecu",
            {"CAN_HOST": "127.0.0.1", "CAN_PORT": "29536", "CAN_CHANNEL": "vcan0"},
        ),
        side("uplink", "abenix_edge.sim.uplink", {"UPLINK_TARGET": API_SVC}),
        edge,
    ]
    print(yaml.safe_dump_all(docs, sort_keys=False))
    log(f"install token made, expires {d['expires_at']}")


def wait() -> None:
    c, h = client()
    g = find(c, h)
    if g is None:
        log("no demo gateway, run deploy.sh edge-demo")
        sys.exit(1)
    t0 = time.time()
    while time.time() - t0 < 240:
        d = c.get(f"/api/edge/gateways/{g['id']}", headers=h).json()["data"]
        devs = [a for a in d.get("assets") or [] if a.get("device")]
        if d["status"] == "online" and len(devs) >= 5:
            break
        time.sleep(5)
    log(
        f"status {d['status']}, enrolled {d['enrolled_at']}, version {d['version']} on {d['platform']}, first data {d['first_data_at']}"
    )
    for col in d.get("collector_health") or []:
        log(
            f"  collector {col['name']}: {col['status']}, {col['readings']} readings{', ' + col['error'] if col.get('error') else ''}"
        )
    rows = c.get("/api/telemetry/devices", headers=h, params={"group": GROUP}).json()[
        "data"
    ]
    log(f"/api/telemetry/devices group={GROUP}:")
    for r in rows:
        if r["device"]:
            log(
                f"  {r['group']}/{r['node']}/{r['device']} online={r['online']} signals={r['metric_count']}"
            )
    b = d.get("buffer") or {}
    log(
        f"buffer depth {b.get('depth')} sent {b.get('sent')} written {b.get('written')}"
    )


def history(
    c: httpx.Client,
    h: dict[str, str],
    group: str,
    node: str,
    device: str,
    metric: str,
    t0: float,
    t1: float,
) -> list[dict]:
    r = c.get(
        "/api/telemetry/history",
        headers=h,
        params={
            "group": group,
            "node": node,
            "device": device,
            "metric": metric,
            "from": str(int(t0)),
            "to": str(int(t1)),
            "step": "1s",
        },
    )
    if r.status_code >= 300:
        log("history refused:", r.text[:300])
        return []
    data = r.json()["data"]
    series = data.get("series") or data.get("metrics") or data
    if isinstance(series, dict):
        series = series.get(metric) or next(iter(series.values()), [])
    elif (
        isinstance(series, list)
        and series
        and isinstance(series[0], dict)
        and "points" in series[0]
    ):
        series = next((s["points"] for s in series if s.get("metric") == metric), [])
    return series or []


def proof(t0: float, t1: float) -> None:
    c, h = client()
    g = find(c, h)
    gid = g["gateway_id"]
    pad = 20
    pts = history(c, h, "edge", gid, "gateway", "Edge/Seq", t0 - pad, t1 + pad)
    vals = []
    multi = 0
    for p in pts:
        n = p.get("n") or p.get("count") or 1
        if n > 1:
            multi += 1
        v = (
            p.get("max")
            if p.get("max") is not None
            else p.get("avg") if p.get("avg") is not None else p.get("v")
        )
        if v is not None:
            vals.append(int(round(v)))
    gaps = [(a, b) for a, b in zip(vals, vals[1:]) if b != a + 1]
    inside = [p for p in pts if t0 * 1000 <= p.get("t", 0) <= t1 * 1000]
    out = {
        "window": [int(t0 - pad), int(t1 + pad)],
        "seq_points": len(vals),
        "seq_first": vals[0] if vals else None,
        "seq_last": vals[-1] if vals else None,
        "seq_expected": (vals[-1] - vals[0] + 1) if vals else 0,
        "gaps": gaps[:10],
        "gap_count": len(gaps),
        "buckets_with_repeats": multi,
        "in_order": vals == sorted(vals),
        "points_in_cut": len(inside),
    }
    meter = history(c, h, GROUP, "meter-1", "main", "voltage_v", t0, t1)
    rpm = history(c, h, GROUP, "truck-7", "engine", "Engine/Speed_rpm", t0, t1)
    out["meter_voltage_points_in_cut"] = len(meter)
    out["truck_rpm_points_in_cut"] = len(rpm)
    out["cut_seconds"] = int(t1 - t0)
    print(json.dumps(out))


def down() -> None:
    c, h = client()
    g = find(c, h)
    if g is None:
        log("no demo gateway")
        return
    r = c.delete(
        f"/api/edge/gateways/{g['id']}", headers=h, params={"remove_source": "true"}
    )
    log("removed" if r.status_code < 300 else r.text[:200])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "setup"
    if cmd == "setup":
        setup()
    elif cmd == "wait":
        wait()
    elif cmd == "proof":
        proof(float(sys.argv[2]), float(sys.argv[3]))
    elif cmd == "down":
        down()
