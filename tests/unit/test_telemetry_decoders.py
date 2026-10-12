"""Every registered decoder against a real sample of its format, and the plugin lint."""

from __future__ import annotations

import asyncio
import io
import json
import struct
from pathlib import Path

import pytest

from app.telemetry import registry
from app.telemetry.connectors.base import Envelope
from app.telemetry.decoders.base import DecodeError, DecoderState
from app.telemetry.pipeline import run_decode
from app.telemetry.sparkplug import sparkplug_b_pb2 as pb

TESTS = Path(__file__).resolve().parent

DBC = """VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ 2364540158 EEC1: 8 ECU
 SG_ EngineSpeed : 24|16@1+ (0.125,0) [0|8031.875] "rpm" ECU

BO_ 2566844158 ET1: 8 ECU
 SG_ CoolantTemp : 0|8@1+ (1,-40) [-40|210] "degC" ECU
"""

PROTO = """syntax = "proto3";
package acme;
message Reading {
  string machine = 1;
  double temp_c = 2;
  int64 ts = 3;
}
"""

AVRO_SCHEMA = {
    "type": "record",
    "name": "Sensor",
    "fields": [
        {"name": "sensor", "type": "string"},
        {"name": "ts", "type": "long"},
        {"name": "temp_c", "type": "double"},
    ],
}


def _sparkplug() -> bytes:
    p = pb.Payload()
    p.timestamp = 1_791_720_000_000
    p.seq = 0
    m = p.metrics.add()
    m.name, m.datatype, m.long_value = "bdSeq", pb.Int64, 3
    m = p.metrics.add()
    m.name, m.alias, m.datatype, m.double_value = "Engine/Speed_rpm", 1, pb.Double, 900.0
    return p.SerializeToString()


def _protobuf() -> bytes:
    from app.telemetry.decoders.protobuf_doc import message_class

    cls = message_class({"proto": PROTO, "message": "acme.Reading"})
    return cls(machine="pump-7", temp_c=41.5, ts=1_791_720_000_000).SerializeToString()


def _avro() -> bytes:
    import fastavro

    buf = io.BytesIO()
    fastavro.schemaless_writer(
        buf,
        fastavro.parse_schema(AVRO_SCHEMA),
        {"sensor": "s-1", "ts": 1_791_720_000_000, "temp_c": 20.5},
    )
    return b"\x00" + struct.pack(">I", 7) + buf.getvalue()


def _msgpack() -> bytes:
    import msgpack

    return msgpack.packb({"machine": "press-2", "ts": 1_791_720_000, "force_kn": 12.5})


def _cbor() -> bytes:
    import cbor2

    return cbor2.dumps({"machine": "meter-9", "kwh": 1234.5})


# decoder name: (subject, payload, decoder config, mapping, check)
FIXTURES = {
    "sparkplug_b": (
        "spBv1.0/groundwork/NBIRTH/ipc-ex1",
        _sparkplug,
        {},
        None,
        lambda rs: rs[0].kind == "birth" and rs[0].meta["bdseq"] == 3 and rs[0].metrics[1].value == 900.0,
    ),
    "can_frames": (
        "groundwork/ipc-ex1/can/raw",
        lambda: json.dumps(
            [
                {"t": 1791720000100, "id": 0x0CF00400, "data": "F0FF7D401B0000FF", "dlc": 8},
                {"t": 1791720000101, "id": 0x18FEEE00, "data": "7D00000000000000", "dlc": 8},
                {"t": 1791720000102, "id": 0x20000000, "data": "0000000000000000", "dlc": 8},
            ]
        ).encode(),
        {"dbc": DBC, "device": "can"},
        None,
        lambda rs: rs[0].kind == "frame"
        and len(rs[0].frames) == 3
        and {m.name: m.value for m in rs[1].metrics}
        == {"EEC1/EngineSpeed": 0x1B40 * 0.125, "ET1/CoolantTemp": 0x7D - 40},
    ),
    "values": (
        "opcua/plant1/boiler",
        lambda: json.dumps(
            {"ts": 1791720000000, "values": [{"name": "Temp", "value": 81.2, "quality": "uncertain", "unit": "C"}]}
        ).encode(),
        {},
        None,
        lambda rs: rs[0].metrics[0].quality == "uncertain" and rs[0].metrics[0].unit == "C",
    ),
    "json": (
        "plant/line1",
        lambda: json.dumps({"device_id": "pump-7", "ts": 1791720000123, "temp_c": 40.1, "flow": {"in_lph": 3.2}}).encode(),
        {},
        {"node": "$.device_id", "signals": {"exclude": ["device_id"]}},
        lambda rs: rs[0].node == "pump-7"
        and rs[0].ts == 1791720000123
        and {m.name for m in rs[0].metrics} == {"temp_c", "flow/in_lph"},
    ),
    "json_lines": (
        "logs/app",
        lambda: b'{"level": 1}\n{"level": 2}\n',
        {},
        None,
        lambda rs: [r.metrics[0].value for r in rs] == [1, 2],
    ),
    "csv": (
        "meters/site1",
        lambda: b"meter,kwh,ok\nm1,10.5,true\nm2,7,false\n",
        {},
        {"node": "$.meter", "signals": {"exclude": ["meter"]}},
        lambda rs: [r.node for r in rs] == ["m1", "m2"] and rs[0].metrics[0].value == 10.5,
    ),
    "text_number": (
        "home/kitchen/temp",
        lambda: b"21.5",
        {},
        None,
        lambda rs: rs[0].metrics[0].value == 21.5 and rs[0].device == "temp",
    ),
    "influx_line": (
        "telegraf",
        lambda: b"cpu,host=web1,cpu=cpu0 usage_idle=91.5,usage_user=3i 1791720000000000000\n",
        {"device_tag": "cpu"},
        None,
        lambda rs: (rs[0].group, rs[0].node, rs[0].device, rs[0].ts) == ("cpu", "web1", "cpu0", 1791720000000)
        and {m.name: m.value for m in rs[0].metrics} == {"usage_idle": 91.5, "usage_user": 3},
    ),
    "protobuf": (
        "factory/pumps",
        _protobuf,
        {"proto": PROTO, "message": "acme.Reading"},
        {"node": "$.machine", "signals": {"exclude": ["machine"]}},
        lambda rs: rs[0].node == "pump-7" and rs[0].metrics[0].value == 41.5,
    ),
    "avro": (
        "sensors/avro",
        _avro,
        {"schema": json.dumps(AVRO_SCHEMA)},
        {"node": "$.sensor", "signals": {"exclude": ["sensor"]}},
        lambda rs: rs[0].node == "s-1" and rs[0].metrics[0].value == 20.5 and rs[0].ts == 1791720000000,
    ),
    "msgpack": (
        "press/line",
        _msgpack,
        {},
        {"node": "$.machine", "signals": {"exclude": ["machine"]}},
        lambda rs: rs[0].node == "press-2" and rs[0].ts == 1791720000000 and rs[0].metrics[0].value == 12.5,
    ),
    "cbor": (
        "meters/site2",
        _cbor,
        {},
        {"node": "$.machine", "signals": {"exclude": ["machine"]}},
        lambda rs: rs[0].node == "meter-9" and rs[0].metrics[0].value == 1234.5,
    ),
}


async def _lookup(kind, *a):
    return {"online": False, "known": False, "aliases": {}}.get(kind)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_decoder_reads_its_format(name):
    subject, make, cfg, mapping, check = FIXTURES[name]
    dec = registry.decoder(name)
    env = Envelope("c1", "t1", subject, make(), t_recv=1_791_720_000.5)
    recs = asyncio.run(run_decode(dec, env, DecoderState(config=cfg, lookup=_lookup), mapping))
    assert recs and check(recs), recs


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_decoder_refuses_garbage_in_plain_words(name):
    if name == "text_number":
        payload = b"not a number"
    elif name == "csv":
        payload = b"a,b\n1\n"
    else:
        payload = b"\xff\xfe garbage {"
    subject = FIXTURES[name][0]
    dec = registry.decoder(name)
    with pytest.raises(DecodeError) as e:
        asyncio.run(
            run_decode(dec, Envelope("c1", "t1", subject, payload), DecoderState(config=FIXTURES[name][2], lookup=_lookup), FIXTURES[name][3])
        )
    assert str(e.value) and "Traceback" not in str(e.value)


def test_every_plugin_is_registered_declared_and_tested():
    registry.reset()
    cat = registry.catalogue()
    assert not cat["unavailable"], f"plugins that do not import: {cat['unavailable']}"
    decoders = registry.decoders()
    assert set(FIXTURES) == set(decoders), f"decoders without a fixture: {set(decoders) - set(FIXTURES)}"
    for name, cls in decoders.items():
        assert cls.label and cls.description, name
    for transport, cls in registry.connectors().items():
        assert cls.label and cls.description, transport
        assert cls.config_fields, f"{transport} declares no config_fields"
        assert cls.capabilities.get("receive") in ("subscribe", "poll", "push"), transport
        assert cls.scale_mode in ("lease", "shared"), transport
        if cls.default_decoder:
            assert cls.default_decoder in decoders, transport
        test = TESTS / f"test_telemetry_connector_{transport}.py"
        assert test.exists(), f"{transport} has no fixture test at {test.name}"
    assert {"mqtt", "http_push"} <= set(registry.connectors())
