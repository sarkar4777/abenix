"""Collectors: J1939, OBD-II, DBC, Modbus, NMEA, MQTT payloads, file tail, and a CAN bus end to end."""

from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from abenix_edge.buffer import Reading  # noqa: E402
from abenix_edge.collectors import build  # noqa: E402
from abenix_edge.collectors import j1939 as J  # noqa: E402
from abenix_edge.collectors import modbus as MB  # noqa: E402
from abenix_edge.collectors import nmea, obd2  # noqa: E402
from abenix_edge.collectors.can_bus import CanCollector, parse_parts  # noqa: E402
from abenix_edge.collectors.file_tail import FileTailCollector  # noqa: E402
from abenix_edge.collectors.mqtt_bridge import (
    MqttBridgeCollector,
    readings,
)  # noqa: E402


class Sink:
    def __init__(self) -> None:
        self.rows: list[Reading] = []

    def __call__(self, rows: list[Reading]) -> None:
        self.rows.extend(rows)

    def latest(self) -> dict[tuple[str, str], object]:
        return {(r.subject, r.name): r.value for r in self.rows}


def _can(spec: dict | None = None) -> tuple[CanCollector, Sink]:
    s = Sink()
    c = CanCollector(
        {
            "id": "bus1",
            "name": "Truck bus",
            "type": "can",
            "asset": {"group": "fleet", "node": "truck-12"},
            **(spec or {}),
        },
        s,
        "gw1",
    )
    return c, s


# J1939


def test_identifier_round_trip() -> None:
    arb = J.make_id(61444, 0, prio=3)
    assert arb == 0x0CF00400
    assert J.parse_id(arb) == (3, 61444, 0, J.GLOBAL)
    req = J.make_id(J.REQUEST, 249, 0)
    assert J.parse_id(req) == (6, J.REQUEST, 249, 0)


def test_eec1_and_et1_decode() -> None:
    eec1 = bytes(
        [0xF0, 0x7D, 165, *(int(1500 / 0.125)).to_bytes(2, "little"), 0, 0xFF, 0xFF]
    )
    sig = dict((n, v) for n, v, _ in J.decode(61444, eec1))
    assert sig["Engine/Speed_rpm"] == 1500 and sig["Engine/Torque_pct"] == 40
    et1 = bytes([126, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
    sig = dict((n, v) for n, v, _ in J.decode(65262, et1))
    # not available bytes are skipped, not reported as 215 C
    assert sig == {"Engine/CoolantTemp_C": 86}


def test_bam_reassembly_of_dm1() -> None:
    dm1 = bytes([0x04, 0xFF, 0x6E, 0x00, 0x03, 0x02, 0x9D, 0x00, 0x12, 0x01])
    tp = J.Transport()
    done = []
    for arb, data in J.bam_frames(65226, 0, dm1):
        _, pgn, sa, da = J.parse_id(arb)
        d, out = tp.feed(pgn, sa, da, data, time.time())
        done += d
        assert out == []
    assert len(done) == 1 and done[0][0] == 65226 and done[0][3] == dm1
    sig = {n: v for n, v, _ in J.decode(65226, done[0][3])}
    assert sig["Diagnostics/ActiveCodes"] == 2
    assert sig["Diagnostics/AmberWarningLamp"] is True
    assert sig["Diagnostics/Codes"][0] == {"spn": 110, "fmi": 3, "count": 2}


def test_rts_to_us_gets_cts_and_end_of_message_ack() -> None:
    tp = J.Transport(lambda: 249)
    payload = bytes(range(17))
    cm = bytes([J.RTS, 17, 0, 3, 0xFF]) + (65260).to_bytes(3, "little")
    done, out = tp.feed(J.TP_CM, 0, 249, cm, 0.0)
    assert out and out[0][1][0] == J.CTS and J.parse_id(out[0][0])[3] == 0
    for i in range(3):
        done, out = tp.feed(
            J.TP_DT,
            0,
            249,
            bytes([i + 1]) + payload[i * 7 : i * 7 + 7].ljust(7, b"\xff"),
            0.01 * i,
        )
    assert done[0][3] == payload
    assert out[0][1][0] == J.EOMA


def test_transport_times_out_a_stalled_session() -> None:
    tp = J.Transport()
    frames = J.bam_frames(65226, 0, bytes(20))
    _, pgn, sa, da = J.parse_id(frames[0][0])
    tp.feed(pgn, sa, da, frames[0][1], 0.0)
    tp.feed(J.TP_DT, 0, J.GLOBAL, frames[1][1], 0.1)
    tp.feed(J.TP_DT, 0, J.GLOBAL, frames[2][1], 2.0)
    assert tp.timeouts == 1 and not tp.sessions


def test_address_claim_contention() -> None:
    low = J.make_name(1, 130)
    me = J.Claimer(J.make_name(99, 130), 249)
    reply = me.on_claim(249, low)
    assert me.address == 128 and reply is not None and J.parse_id(reply[0])[2] == 128
    keep = J.Claimer(low, 249)
    again = keep.on_claim(249, J.make_name(99, 130))
    assert keep.address == 249 and again is not None


def test_can_collector_names_parts_by_claim_and_publishes_latest() -> None:
    c, s = _can({"parts": "3=gearbox"})
    t = time.time()
    c.handle(
        J.make_id(J.ADDRESS_CLAIMED, 0),
        J.make_name(1, 0).to_bytes(8, "little"),
        True,
        t,
    )
    for rpm in (1000, 1200, 1400):
        c.handle(
            J.make_id(61444, 0, prio=3),
            bytes(
                [
                    0xF0,
                    0x7D,
                    150,
                    *int(rpm / 0.125).to_bytes(2, "little"),
                    0,
                    0xFF,
                    0xFF,
                ]
            ),
            True,
            t,
        )
    c.handle(
        J.make_id(61445, 3),
        bytes([128, 0xFF, 0xFF, 128, 0xFF, 0xFF, 0xFF, 0xFF]),
        True,
        t,
    )
    for arb, data in J.bam_frames(
        65226, 0, bytes([0x04, 0xFF, 0x6E, 0x00, 0x03, 0x02, 0x9D, 0x00, 0x12, 0x01])
    ):
        c.handle(arb, data, True, t)
    assert c.publish_latest() > 0
    got = s.latest()
    # only the newest of the three speeds is sent for the interval
    assert got[("fleet/truck-12/engine", "Engine/Speed_rpm")] == 1400
    assert len([r for r in s.rows if r.name == "Engine/Speed_rpm"]) == 1
    assert got[("fleet/truck-12/gearbox", "Transmission/CurrentGear")] == 3
    assert got[("fleet/truck-12/engine", "Diagnostics/ActiveCodes")] == 2
    assert c.extra["ecus"]["0"]["part"] == "engine"


def test_parts_validation() -> None:
    assert parse_parts("0=engine, 3=transmission") == {0: "engine", 3: "transmission"}
    with pytest.raises(ValueError, match="address=part"):
        parse_parts("engine")
    with pytest.raises(ValueError, match="outside"):
        parse_parts("300=x")


# OBD-II


def test_obd2_request_and_decode() -> None:
    arb, data, ext = obd2.request(0x0C)
    assert arb == 0x7DF and data[:3] == bytes([2, 1, 0x0C]) and not ext
    ans = obd2.answer(0x0C, (3000 * 4).to_bytes(2, "big"))
    assert obd2.decode(ans) == (0x0C, "Engine/Speed_rpm", 3000, "rpm")
    assert obd2.decode(obd2.answer(0x05, bytes([126])))[2] == 86
    assert obd2.parse_pids("0c, 0D") == [0x0C, 0x0D]
    with pytest.raises(ValueError, match="Known PIDs"):
        obd2.parse_pids("FF")


def test_can_collector_obd2_mode() -> None:
    c, s = _can({"protocol": "obd2", "obd_pids": "0C,0D"})
    c.handle(0x7E8, obd2.answer(0x0D, bytes([57])), False, time.time())
    c.publish_latest()
    assert s.latest()[("fleet/truck-12/engine", "Vehicle/Speed_kmh")] == 57


DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 2364540158 EEC1: 8 ECU
 SG_ EngineSpeed : 24|16@1+ (0.125,0) [0|8031.875] "rpm" ECU
BO_ 1280 Pump: 8 ECU
 SG_ Pressure : 0|16@1+ (0.1,0) [0|6553.5] "bar" ECU
"""


def test_dbc_decodes_j1939_and_plain_frames() -> None:
    c, s = _can({"dbc": DBC})
    c.handle(
        J.make_id(61444, 0, prio=3),
        bytes([0, 0, 0, *int(800 / 0.125).to_bytes(2, "little"), 0, 0, 0]),
        True,
        time.time(),
    )
    c2, s2 = _can({"dbc": DBC, "protocol": "dbc"})
    c2.handle(1280, (123).to_bytes(2, "little") + bytes(6), False, time.time())
    c.publish_latest()
    c2.publish_latest()
    assert s.latest()[("fleet/truck-12/engine", "EEC1/EngineSpeed")] == 800
    assert s2.latest()[("fleet/truck-12/bus", "Pump/Pressure")] == pytest.approx(12.3)


def test_bad_dbc_is_refused_in_plain_words() -> None:
    with pytest.raises(ValueError, match="DBC file could not be read"):
        _can({"dbc": "BO_ this is not a dbc"})


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_can_bus_end_to_end_over_socketcand() -> None:
    """The simulated bus, real ECUs and the collector, all over the socketcand protocol."""
    import os

    from abenix_edge.sim import canbus, ecu

    port = _free_port()
    loop = asyncio.new_event_loop()
    threading.Thread(
        target=lambda: loop.run_until_complete(canbus.serve("127.0.0.1", port)),
        daemon=True,
    ).start()
    time.sleep(0.3)
    os.environ.update(
        {"CAN_HOST": "127.0.0.1", "CAN_PORT": str(port), "CAN_CHANNEL": "vcan0"}
    )
    stop = threading.Event()
    plant = ecu.Plant()
    for fn in (ecu.engine, ecu.transmission):
        threading.Thread(target=fn, args=(stop, plant), daemon=True).start()
    s = Sink()
    c = CanCollector(
        {
            "id": "bus",
            "type": "can",
            "interface": "socketcand",
            "host": "127.0.0.1",
            "port": port,
            "channel": "vcan0",
            "interval_s": 0.5,
            "request_pgns": "65253, 65260",
            "request_every_s": 0.5,
            "asset": {"group": "fleet", "node": "truck-7"},
        },
        s,
        "gw1",
    )
    ev = asyncio.Event()

    async def go() -> None:
        task = asyncio.create_task(c.run(ev))
        await asyncio.sleep(4.0)
        ev.set()
        await asyncio.wait_for(task, 10)

    asyncio.run(go())
    stop.set()
    got = s.latest()
    assert ("fleet/truck-7/engine", "Engine/Speed_rpm") in got
    assert ("fleet/truck-7/transmission", "Transmission/CurrentGear") in got
    assert ("fleet/truck-7/engine", "Engine/CoolantTemp_C") in got
    # engine hours only come when asked, so this proves our address claim and request went out
    assert got[("fleet/truck-7/engine", "Engine/Hours_h")] > 12000
    # no fault codes on a healthy truck, the VIN comes back over TP.BAM
    assert got[("fleet/truck-7/engine", "Diagnostics/ActiveCodes")] == 0
    assert got[("fleet/truck-7/engine", "Diagnostics/Codes")] == []
    assert got[("fleet/truck-7/engine", "Vehicle/VIN")] == "YS2R4X20005399401"
    assert c.transport.completed >= 1
    assert c.claimer.claimed and c.extra["bus_load_pct"] > 0


# Modbus


def test_register_map_and_decoding() -> None:
    regs = MB.parse_map(
        "voltage_v, holding, 0, float32, 1, V\nenergy_kwh, holding, 6, uint32, 0.1, kWh\n# note\nbreaker, coil, 0"
    )
    assert [r.name for r in regs] == ["voltage_v", "energy_kwh", "breaker"]
    import struct

    hi, lo = struct.unpack(">HH", struct.pack(">f", 231.5))
    assert MB.decode(regs[0], [hi, lo]) == pytest.approx(231.5)
    assert MB.decode(
        MB.Reg("x", "holding", 0, "float32", word_order="little"), [lo, hi]
    ) == pytest.approx(231.5)
    assert MB.decode(regs[1], [0, 1234]) == pytest.approx(123.4)
    assert MB.decode(
        MB.Reg("t", "holding", 0, "int16", 0.1), [0xFFF6]
    ) == pytest.approx(-1.0)
    blocks = MB.blocks(regs)
    assert [(b[0], b[1], b[2]) for b in blocks] == [("holding", 0, 8), ("coil", 0, 1)]
    for bad, why in (
        ("x, holding", "at least name"),
        ("x, nowhere, 1", "holding, input"),
        ("x, holding, 1, float16", "type must"),
        ("x, holding, 1\nx, holding, 2", "Two registers"),
    ):
        with pytest.raises(ValueError, match=why):
            MB.parse_map(bad)


def test_modbus_tcp_poll_against_a_real_server() -> None:
    from pymodbus.datastore import (
        ModbusDeviceContext,
        ModbusSequentialDataBlock,
        ModbusServerContext,
    )
    from pymodbus.server import StartAsyncTcpServer

    import struct

    port = _free_port()
    hi, lo = struct.unpack(">HH", struct.pack(">f", 229.75))
    # block address 1 is protocol address 0
    dev = ModbusDeviceContext(
        hr=ModbusSequentialDataBlock(1, [hi, lo, 0, 0, 0, 0, 0, 4321] + [0] * 24),
        co=ModbusSequentialDataBlock(1, [1] * 8),
    )
    ctx = ModbusServerContext(devices={1: dev}, single=False)
    s = Sink()
    c = MB.ModbusCollector(
        {
            "id": "m",
            "type": "modbus",
            "host": "127.0.0.1",
            "port": port,
            "unit_id": 1,
            "interval_s": 0.2,
            "registers": "voltage_v, holding, 0, float32, 1, V\nenergy_kwh, holding, 6, uint32, 0.1, kWh\nbreaker_closed, coil, 0",
            "asset": {"group": "plant", "node": "meter-1", "device": "main"},
        },
        s,
        "gw1",
    )

    async def go() -> None:
        srv = asyncio.create_task(
            StartAsyncTcpServer(context=ctx, address=("127.0.0.1", port))
        )
        await asyncio.sleep(0.5)
        ev = asyncio.Event()
        task = asyncio.create_task(c.run(ev))
        await asyncio.sleep(1.0)
        ev.set()
        await asyncio.wait_for(task, 5)
        srv.cancel()

    asyncio.run(go())
    got = s.latest()
    assert got[("plant/meter-1/main", "voltage_v")] == pytest.approx(229.75)
    assert got[("plant/meter-1/main", "energy_kwh")] == pytest.approx(432.1)
    assert got[("plant/meter-1/main", "breaker_closed")] is True
    assert c.status == "running" and c.error is None


def test_modbus_unreachable_says_so_plainly() -> None:
    s = Sink()
    c = MB.ModbusCollector(
        {
            "id": "m",
            "type": "modbus",
            "host": "127.0.0.1",
            "port": _free_port(),
            "registers": "a, holding, 0",
        },
        s,
        "gw1",
    )

    async def go() -> None:
        ev = asyncio.Event()
        task = asyncio.create_task(c.run(ev))
        await asyncio.sleep(1.5)
        ev.set()
        await asyncio.wait_for(task, 10)

    asyncio.run(go())
    assert (
        c.status == "error"
        and "Could not reach the Modbus device at 127.0.0.1" in c.error
    )


# NMEA


def test_nmea_sentences() -> None:
    from abenix_edge.sim.ecu import nmea_line

    rmc = nmea_line("GPRMC,123519.00,A,4807.038,N,01131.000,E,22.4,84.4,230394,,")
    got = {n: v for n, v, _ in nmea.parse(rmc)}
    assert got["GNSS/Lat_deg"] == pytest.approx(48.1173)
    assert got["GNSS/Lon_deg"] == pytest.approx(11.516667, rel=1e-6)
    assert got["GNSS/Speed_kmh"] == pytest.approx(41.48, rel=1e-3)
    gga = nmea_line("GNGGA,123519,3352.128,S,15112.558,E,1,08,0.9,545.4,M,46.9,M,,")
    got = {n: v for n, v, _ in nmea.parse(gga)}
    assert (
        got["GNSS/Lat_deg"] < 0
        and got["GNSS/Satellites"] == 8
        and got["GNSS/Altitude_m"] == 545.4
    )
    assert (
        nmea.parse(
            "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*00"
        )
        == []
    )
    assert nmea.parse(nmea_line("GPRMC,123519,V,,,,,,,230394,,")) == [
        ("GNSS/Valid", False, None)
    ]


# MQTT and files


def test_mqtt_payloads_become_readings() -> None:
    rows, ts = readings(
        "site/pump-3/telemetry",
        b'{"ts": 1791720000000, "temp_c": 41.5, "motor": {"amps": 12.1}}',
    )
    assert dict(rows) == {"temp_c": 41.5, "motor/amps": 12.1} and ts == 1791720000000
    assert readings("site/pump-3/pressure_bar", b"4.2")[0] == [("pressure_bar", 4.2)]
    s = Sink()
    c = MqttBridgeCollector(
        {
            "id": "mq",
            "type": "mqtt_bridge",
            "asset": {"group": "site", "node": "{topic.1}", "device": "sensors"},
        },
        s,
        "gw1",
    )
    c.on_message("site/pump-3/pressure_bar", b"4.2")
    assert s.rows[0].subject == "site/pump-3/sensors" and s.rows[0].value == 4.2


def test_file_tail_reads_new_rows_and_survives_restart(tmp_path: Path) -> None:
    f = tmp_path / "log.csv"
    f.write_text("time,temp_c,state\n2026-10-11T10:00:00Z,20.5,run\n")
    s = Sink()
    spec = {
        "id": "ft",
        "type": "file_tail",
        "path": str(f),
        "format": "csv",
        "from_start": True,
        "_data_dir": str(tmp_path),
    }
    c = FileTailCollector(spec, s, "gw1")
    assert c.read_new() == 2
    with f.open("a") as fh:
        fh.write("2026-10-11T10:00:01Z,20.7,run\n")
    c2 = FileTailCollector(spec, s, "gw1")
    assert c2.read_new() == 2
    temps = [r.value for r in s.rows if r.name == "temp_c"]
    assert temps == [20.5, 20.7]
    assert s.rows[-1].ts == 1791712801000


def test_build_refuses_unknown_types() -> None:
    with pytest.raises(ValueError, match="no collector of type"):
        build({"type": "zigbee"}, Sink(), "gw1")


def test_opcua_subscribe_against_a_real_server() -> None:
    from asyncua import Server, ua

    from abenix_edge.collectors.opcua import OpcuaCollector, parse_nodes

    assert parse_nodes("ns=2;s=Temp, Boiler/Temp_C, C\ni=2258") == [
        ("ns=2;s=Temp", "Boiler/Temp_C", "C"),
        ("i=2258", "2258", None),
    ]
    with pytest.raises(ValueError, match="not an OPC UA node id"):
        parse_nodes("Temperature")
    port = _free_port()
    s = Sink()

    async def go() -> None:
        srv = Server()
        await srv.init()
        srv.set_endpoint(f"opc.tcp://127.0.0.1:{port}/edge/")
        idx = await srv.register_namespace("urn:edge-test")
        obj = await srv.nodes.objects.add_object(idx, "Boiler")
        temp = await obj.add_variable(ua.NodeId("Temp", idx), "Temp", 20.0)
        press = await obj.add_variable(ua.NodeId("Press", idx), "Press", 4.0)
        async with srv:
            c = OpcuaCollector(
                {
                    "id": "o",
                    "type": "opcua",
                    "endpoint": f"opc.tcp://127.0.0.1:{port}/edge/",
                    "interval_s": 0.2,
                    "nodes": f"ns={idx};s=Temp, Boiler/Temp_C, C\n"
                    f"ns={idx};s=Press, Boiler/Pressure_bar, bar",
                    "asset": {"group": "plant", "node": "boiler-1", "device": "plc"},
                },
                s,
                "gw1",
            )
            ev = asyncio.Event()
            task = asyncio.create_task(c.run(ev))
            for v in (21.5, 22.25):
                await asyncio.sleep(1.0)
                await temp.write_value(v)
                await press.write_value(v / 5)
            await asyncio.sleep(1.0)
            ev.set()
            await asyncio.wait_for(task, 15)

    asyncio.run(go())
    temps = [r for r in s.rows if r.name == "Boiler/Temp_C"]
    press = [r for r in s.rows if r.name == "Boiler/Pressure_bar"]
    # each node keeps its own value and unit, nothing is shared across a batch
    assert temps[-1].value == 22.25 and 21.5 in [r.value for r in temps]
    assert press[-1].value == 4.45 and 4.3 in [r.value for r in press]
    assert {r.unit for r in temps} == {"C"} and {r.unit for r in press} == {"bar"}
    assert temps[-1].subject == "plant/boiler-1/plc" and temps[-1].quality == "good"


def test_opcua_unreachable_says_so_plainly() -> None:
    from abenix_edge.collectors.opcua import OpcuaCollector

    c = OpcuaCollector(
        {
            "id": "o",
            "type": "opcua",
            "endpoint": f"opc.tcp://127.0.0.1:{_free_port()}",
            "nodes": "i=2258",
        },
        Sink(),
        "gw1",
    )

    async def go() -> None:
        ev = asyncio.Event()
        task = asyncio.create_task(c.run(ev))
        await asyncio.sleep(2.0)
        ev.set()
        await asyncio.wait_for(task, 15)

    asyncio.run(go())
    assert c.status == "error" and c.error.startswith(
        "Could not reach the OPC UA server"
    )


def test_truck_drives_a_duty_cycle_not_a_sine() -> None:
    from abenix_edge.sim.ecu import dm1
    from abenix_edge.sim.truck import DT, Truck

    a, b = Truck(seed=3, start=False), Truck(seed=3, start=False)
    rows = []
    for _ in range(int(20 * 60 / DT)):
        a.step()
        b.step()
        s = a.s
        rows.append(
            (
                s.t,
                s.speed * 3.6,
                s.rpm,
                s.gear,
                s.torque_pct,
                s.fuel_lph,
                s.coolant_c,
                s.phase,
                s.def_warning,
                s.lat,
                s.lon,
            )
        )
    # the same seed gives the same run
    assert (a.s.rpm, a.s.lat, a.s.def_level_pct) == (
        b.s.rpm,
        b.s.lat,
        b.s.def_level_pct,
    )
    phases = {r[7] for r in rows}
    assert {
        "stopped at the gate",
        "pulling away",
        "shifting",
        "cruise",
        "hill climb",
        "braking",
    } <= phases
    gears = {r[3] for r in rows}
    assert 0 in gears and max(gears) >= 9
    assert 570 < min(r[2] for r in rows) and max(r[2] for r in rows) < 2000
    warm = [r[6] for r in rows if r[0] > 400]
    assert 84 < min(warm) and max(warm) < 93
    # torque and fuel move together, heavy pulls burn more
    heavy = [r[5] for r in rows if r[4] > 70]
    light = [r[5] for r in rows if 0 < r[4] < 10]
    assert heavy and light and min(heavy) > max(light)
    # laps differ in length, so the chart never repeats
    starts = [
        r[0]
        for p, r in zip(rows, rows[1:])
        if p[7] == "stopped at the gate" and r[7] != p[7]
    ]
    laps = [round(y - x) for x, y in zip(starts, starts[1:])]
    assert len(laps) >= 2 and len(set(laps)) == len(laps)
    # the route stays on site, a few hundred metres either way
    assert (
        max(abs(r[9] - rows[0][9]) for r in rows) < 0.02
        and max(abs(r[10] - rows[0][10]) for r in rows) < 0.02
    )
    assert any(r[8] for r in rows), "the DEF warning shows within 20 minutes"
    assert len(dm1([(1761, 18, 1), (5246, 15, 1)])) == 10 and dm1([])[:2] == bytes(
        [0, 0xFF]
    )


def test_demo_opcua_nodes_are_named_for_what_opc_plc_serves() -> None:
    sys.path.insert(0, str(ROOT / "demo"))
    import edge_demo

    from abenix_edge.collectors.opcua import parse_nodes

    nodes = parse_nodes(edge_demo.OPC_NODES)
    assert len({n for _, n, _ in nodes}) == len(nodes)
    # opc-plc's Slow and Fast doubles are one counter in lockstep, never a temperature or pressure
    for nid, name, unit in nodes:
        assert "SlowDouble" not in nid and "FastDouble" not in nid, (nid, name)
        assert (
            unit is None
        ), f"{name} has a unit, but opc-plc serves no physical quantity"
    ids = {nid for nid, _, _ in nodes}
    assert ids >= {"ns=3;s=SpikeData", "ns=3;s=DipData", "ns=3;s=StepUp"}
