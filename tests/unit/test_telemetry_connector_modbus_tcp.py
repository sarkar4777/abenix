"""Modbus TCP connector: register map, byte and word order, polling, quality and writes."""

from __future__ import annotations

import asyncio
import functools
import json
import struct
from types import SimpleNamespace

import pytest

pytest.importorskip("pymodbus")

from app.telemetry.connectors import modbus_tcp as M  # noqa: E402
from app.telemetry.connectors.base import ConnectorError, RunContext  # noqa: E402


def arun(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))

    return wrapper


MAP = """# energy meter
Voltage_V, holding, 0, float32, 1, V
Energy_kWh, holding, 6, uint32, 0.1, kWh
PowerFactor, holding, 9, int16, 0.001
Setpoint_kW, holding, 10, uint16, 0.1, kW
VoltageLE_V, holding, 20, float32, 1, V, little
Temp_C, input, 0x10, int16, 0.1, C
Breaker, coil, 0
Alarm, discrete, 0
"""


def test_declares_plain_fields():
    d = M.ModbusTcpConnector.describe()
    assert d["transport"] == "modbus_tcp" and d["capabilities"]["receive"] == "poll"
    assert M.ModbusTcpConnector.default_decoder == "values"
    keys = {f["key"]: f for f in d["config_fields"]}
    assert keys["registers"]["required"] and keys["port"]["default"] == "502"
    for f in d["config_fields"]:
        assert f["label"] and f["description"], f["key"]


def test_parse_map_lines_and_json():
    regs = M.parse_map(MAP)
    by = {r.name: r for r in regs}
    assert by["Temp_C"].table == "input" and by["Temp_C"].address == 16
    assert by["VoltageLE_V"].word_order == "little" and by["Energy_kWh"].scale == 0.1
    assert by["Breaker"].type == "bool" and by["Setpoint_kW"].writable
    js = M.parse_map(
        '[{"name": "P", "table": "hr", "address": 4, "type": "float32", "unit": "kW"}]'
    )
    assert js[0].table == "holding" and js[0].unit == "kW"


@pytest.mark.parametrize(
    "text,expect",
    [
        ("", "at least one register"),
        ("A, holding", "at least name, table, address"),
        ("A, shelf, 1", "holding, input, coil or discrete"),
        ("A, holding, 70000", "from 0 to 65535"),
        ("A, holding, 1, float16", "type must be one of"),
        ("A, holding, 1\nA, holding, 2", "Two registers are called A"),
        ("A, holding, 1, uint16, 1, V, middle", "big or little"),
    ],
)
def test_parse_map_errors_are_plain(text, expect):
    with pytest.raises(ConnectorError, match=expect):
        M.parse_map(text)


def regs_of(fmt, value, word_little=False, byte_little=False):
    raw = struct.pack(">" + fmt, value)
    if byte_little:
        raw = b"".join(raw[i : i + 2][::-1] for i in range(0, len(raw), 2))
    ws = [struct.unpack(">H", raw[i : i + 2])[0] for i in range(0, len(raw), 2)]
    return ws[::-1] if word_little else ws


@pytest.mark.parametrize("wo", ["big", "little"])
@pytest.mark.parametrize("bo", ["big", "little"])
def test_float32_round_trip_in_every_order(wo, bo):
    r = M.Reg("V", "holding", 0, "float32", word_order=wo, byte_order=bo)
    ws = regs_of("f", 230.25, wo == "little", bo == "little")
    assert M.decode(r, ws) == 230.25
    assert M.encode(r, 230.25) == ws


def test_scaled_and_signed():
    pf = M.Reg("PF", "holding", 9, "int16", scale=0.001)
    assert M.decode(pf, [0xFC18]) == -1.0
    assert M.encode(pf, -1.0) == [0xFC18]
    e = M.Reg("E", "holding", 6, "uint32", scale=0.1)
    assert M.decode(e, [0x0001, 0xE240]) == 12345.6
    with pytest.raises(ConnectorError, match="out of range"):
        M.encode(M.Reg("S", "holding", 10, "uint16", scale=0.1), 7000)


def test_blocks_read_neighbours_together():
    bl = M.blocks(M.parse_map(MAP))
    assert [(t, s, n) for t, s, n, _ in bl] == [
        ("holding", 0, 11),
        ("holding", 20, 2),
        ("input", 16, 1),
        ("coil", 0, 1),
        ("discrete", 0, 1),
    ]


class FakeClient:
    def __init__(self, fail_table=None):
        self.hr = [0] * 64
        self.hr[0:2] = regs_of("f", 231.5)
        self.hr[6:8] = [0, 1000]
        self.hr[10] = 500
        self.fail_table = fail_table
        self.connected = True
        self.writes = []

    def _resp(self, regs=None, bits=None, error=None):
        return SimpleNamespace(
            isError=lambda: error is not None,
            exception_code=error,
            registers=regs or [],
            bits=bits or [],
        )

    async def read_holding_registers(self, address, count=1, device_id=1):
        if self.fail_table == "holding":
            return self._resp(error=2)
        return self._resp(regs=self.hr[address : address + count])

    async def read_input_registers(self, address, count=1, device_id=1):
        return self._resp(regs=[0xFF38] * count)

    async def read_coils(self, address, count=1, device_id=1):
        return self._resp(bits=[True] * 8)

    async def read_discrete_inputs(self, address, count=1, device_id=1):
        return self._resp(bits=[False] * 8)

    async def write_register(self, address, value, device_id=1):
        self.writes.append(("reg", address, value, device_id))
        return self._resp()

    async def write_registers(self, address, values, device_id=1):
        self.writes.append(("regs", address, values, device_id))
        return self._resp()

    async def write_coil(self, address, value, device_id=1):
        self.writes.append(("coil", address, value, device_id))
        return self._resp()

    async def connect(self):
        return True

    def close(self):
        self.connected = False


@arun
async def test_poll_values_and_bad_quality_for_a_failed_block():
    values, problems = await M.poll(FakeClient(), M.parse_map(MAP), 1)
    by = {v["name"]: v for v in values}
    assert by["Voltage_V"]["value"] == 231.5 and by["Voltage_V"]["unit"] == "V"
    assert by["Energy_kWh"]["value"] == 100.0 and by["Setpoint_kW"]["value"] == 50.0
    assert by["Temp_C"]["value"] == -20.0 and by["Breaker"]["value"] is True
    assert problems == []
    values, problems = await M.poll(
        FakeClient(fail_table="holding"), M.parse_map(MAP), 1
    )
    by = {v["name"]: v for v in values}
    assert by["Voltage_V"]["quality"] == "bad" and by["Temp_C"]["quality"] == "good"
    assert "that address is not on the device" in problems[0]


@arun
async def test_run_emits_typed_values_on_the_asset_subject(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(M, "make_client", lambda cfg, timeout=None: fake)
    ctx = RunContext(
        connection_id="c1",
        tenant="t1",
        name="Meter",
        config={
            "host": "meter",
            "registers": MAP,
            "poll_interval_ms": "50",
            "asset": "energy/meter-1",
        },
        secrets={},
        replica="r1",
        shared=False,
    )
    task = asyncio.create_task(M.ModbusTcpConnector().run(ctx))
    for _ in range(200):
        if len(ctx.queue) >= 2:
            break
        await asyncio.sleep(0.01)
    env = ctx.queue[0]
    assert (
        env.subject == "energy/meter-1"
        and env.headers["content-type"] == M.CONTENT_TYPE
    )
    assert {v["name"] for v in json.loads(env.payload)["values"]} >= {
        "Voltage_V",
        "Breaker",
    }
    ctx.stopping.set()
    await asyncio.wait_for(task, 3)
    assert not fake.connected and ctx.status == "disabled"


@arun
async def test_write_by_name_by_address_and_coil(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(M, "make_client", lambda cfg, timeout=None: fake)
    cfg = {"host": "meter", "registers": MAP, "unit_id": "3"}
    c = M.ModbusTcpConnector()
    await c.write(cfg, {}, {"register": "Setpoint_kW"}, 42.5)
    await c.write(cfg, {}, {"register": "Voltage_V"}, 230.0)
    await c.write(cfg, {}, {"coil": "Breaker"}, "off")
    await c.write(cfg, {}, {"register": 30, "type": "int16"}, -5)
    assert fake.writes == [
        ("reg", 10, 425, 3),
        ("regs", 0, regs_of("f", 230.0), 3),
        ("coil", 0, False, 3),
        ("reg", 30, 0xFFFB, 3),
    ]
    with pytest.raises(ConnectorError, match="read only"):
        await c.write(cfg, {}, {"register": "Temp_C"}, 1)
    with pytest.raises(ConnectorError, match="true or false"):
        await c.write(cfg, {}, {"coil": "Breaker"}, "maybe")


def test_default_asset_path():
    assert (
        M.asset_of({"host": "meter.abenix-testbed.svc.cluster.local", "unit_id": 2})
        == "modbus/meter-unit2"
    )
    assert M.asset_of({"host": "10.0.0.7"}) == "modbus/10-0-0-7-unit1"
