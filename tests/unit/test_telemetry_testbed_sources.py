"""The testbed's ready-made connections stay honest and bounded."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.telemetry import mapping as M
from app.telemetry.connectors import opcua as O
from app.telemetry.connectors.base import Envelope

SIM = (
    Path(__file__).resolve().parents[2]
    / "infra"
    / "helm"
    / "testbed"
    / "sim"
    / "sim.py"
)


def sim():
    spec = importlib.util.spec_from_file_location("testbed_sim", SIM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sources():
    return {s["name"]: s for s in sim().testbed_sources()}


def test_opcua_only_gives_physical_units_to_physical_nodes():
    s = sim()
    src = sources()["Testbed · OPC UA PLC"]
    nodes = O.node_list({"nodes": src["config"]["nodes"]})
    units = src["mapping"]["signals"]["units"]
    for nid, name in nodes:
        # a unit from the mapping or one the name implies, such as _C or _bar
        unit = units.get(name) or M.unit_from_name(name)
        if unit is None:
            continue
        assert (
            s.OPC_PHYSICAL.get(nid) == unit
        ), f"{name} carries {unit}, but OPC PLC does not simulate {nid} as that quantity"
    for name in units:
        assert name in {n for _, n in nodes}, f"unit for {name}, which no node maps to"


def test_opc_plc_nodes_that_share_a_generator_are_named_for_it():
    nodes = dict(
        O.node_list({"nodes": sources()["Testbed · OPC UA PLC"]["config"]["nodes"]})
    )
    for nid, name in nodes.items():
        if "SlowDouble" in nid or "FastDouble" in nid:
            assert name.startswith("Random/"), name


def test_logistics_devices_stay_bounded():
    src = sources()["Testbed · RabbitMQ shipments"]
    devices = set()
    for i in range(200):
        doc = {
            "shipment_id": f"SHP{i}",
            "carrier": ["DHL", "DSV"][i % 2],
            "status": "in_transit",
            "location": {
                "city": ["Rotterdam", "Lyon", "Hamburg"][i % 3],
                "lat": 1,
                "lon": 2,
            },
            "weight_kg": 10.0,
            "eta_hours": 8,
            "ts": "2026-10-11T10:00:00+00:00",
        }
        env = Envelope("c", "t", "shipment.in_transit", json.dumps(doc).encode())
        for r in M.apply(doc, env, src["mapping"]):
            devices.add((r.group, r.node, r.device))
    assert len(devices) <= 6
