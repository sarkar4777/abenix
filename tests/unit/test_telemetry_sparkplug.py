"""Sparkplug B decoding against payloads built with the compiled Eclipse Tahu proto."""

from __future__ import annotations

import struct
from pathlib import Path

from app.telemetry import sparkplug as sp
from app.telemetry.sparkplug import sparkplug_b_pb2 as pb

SP_DIR = Path(sp.__file__).resolve().parent


def _payload(seq=None, ts=1_700_000_000_000):
    p = pb.Payload()
    p.timestamp = ts
    if seq is not None:
        p.seq = seq
    return p


def test_vendored_proto_keeps_its_epl_notice():
    proto = (SP_DIR / "sparkplug_b.proto").read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: EPL-2.0" in proto
    assert "package org.eclipse.tahu.protobuf;" in proto
    notice = (SP_DIR / "NOTICE.md").read_text(encoding="utf-8")
    assert "Eclipse Public License 2.0" in notice and "Eclipse Tahu" in notice


def test_topics():
    t = sp.parse_topic("spBv1.0/groundwork/DDATA/ipc-ex1/engine")
    assert (t.group, t.message_type, t.node, t.device) == (
        "groundwork",
        "DDATA",
        "ipc-ex1",
        "engine",
    )
    assert sp.parse_topic("spBv1.0/groundwork/NBIRTH/ipc-ex1").device == ""
    st = sp.parse_topic("spBv1.0/STATE/abenix-host")
    assert st.is_state and st.host_id == "abenix-host"
    assert sp.parse_topic("spBv1.0/groundwork/DDATA/ipc-ex1") is None
    assert sp.parse_topic("spBv1.0/groundwork/BOGUS/ipc-ex1") is None
    assert sp.parse_topic("groundwork/ipc-ex1/can/raw") is None
    assert sp.command_topic("g", "n", "d") == "spBv1.0/g/DCMD/n/d"
    assert sp.command_topic("g", "n") == "spBv1.0/g/NCMD/n"


def test_decodes_every_scalar_type_from_a_real_birth():
    p = _payload(seq=0)
    m = p.metrics.add()
    m.name, m.datatype, m.long_value = "bdSeq", pb.Int64, 7
    m = p.metrics.add()
    m.name, m.alias, m.datatype, m.double_value = "Engine/Speed_rpm", 1, pb.Double, 1450.5
    m = p.metrics.add()
    m.name, m.alias, m.datatype, m.int_value = "Engine/CoolantDelta_C", 2, pb.Int8, (-5) & 0xFFFFFFFF
    m = p.metrics.add()
    m.name, m.alias, m.datatype, m.long_value = "Offset", 3, pb.Int64, (-42) & 0xFFFFFFFFFFFFFFFF
    m = p.metrics.add()
    m.name, m.alias, m.datatype, m.float_value = "Hydraulics/BoomPressure_bar", 4, pb.Float, 212.25
    m = p.metrics.add()
    m.name, m.alias, m.datatype, m.boolean_value = "Safety/Hold", 5, pb.Boolean, True
    m = p.metrics.add()
    m.name, m.alias, m.datatype, m.string_value = "Task/State", 6, pb.String, "digging"
    m = p.metrics.add()
    m.name, m.datatype, m.int_value = "UInt", pb.UInt32, 4_000_000_000
    m = p.metrics.add()
    m.name, m.datatype, m.is_null = "Nothing", pb.Double, True
    raw = p.SerializeToString()

    d = sp.decode(raw)
    vals = {x.name: sp.metric_value(x) for x in d.metrics}
    assert vals == {
        "bdSeq": 7,
        "Engine/Speed_rpm": 1450.5,
        "Engine/CoolantDelta_C": -5,
        "Offset": -42,
        "Hydraulics/BoomPressure_bar": 212.25,
        "Safety/Hold": True,
        "Task/State": "digging",
        "UInt": 4_000_000_000,
        "Nothing": None,
    }
    assert d.seq == 0 and d.timestamp == 1_700_000_000_000


def test_data_without_datatype_takes_the_birth_type():
    p = _payload(seq=3)
    m = p.metrics.add()
    m.alias, m.int_value = 2, 0xFFFFFFFE
    d = sp.decode(p.SerializeToString())
    assert sp.metric_value(d.metrics[0], pb.Int16) == -2
    assert sp.metric_value(d.metrics[0], pb.UInt32) == 0xFFFFFFFE


def test_arrays_datasets_and_quality():
    p = _payload()
    m = p.metrics.add()
    m.name, m.datatype = "Hist", pb.Int16Array
    m.bytes_value = struct.pack("<3h", 1, -2, 300)
    m = p.metrics.add()
    m.name, m.datatype = "Flags", pb.BooleanArray
    m.bytes_value = struct.pack("<I", 3) + bytes([0b10100000])
    m = p.metrics.add()
    m.name, m.datatype = "Names", pb.StringArray
    m.bytes_value = b"EX1\x00TC1\x00"
    m = p.metrics.add()
    m.name, m.datatype = "Table", pb.DataSet
    ds = m.dataset_value
    ds.num_of_columns = 2
    ds.columns.extend(["ecu", "load"])
    ds.types.extend([pb.String, pb.Double])
    row = ds.rows.add()
    row.elements.add().string_value = "engine"
    row.elements.add().double_value = 0.7
    m = p.metrics.add()
    m.name, m.datatype, m.double_value = "Stale", pb.Double, 1.0
    m.properties.keys.append("Quality")
    pv = m.properties.values.add()
    pv.type, pv.int_value = pb.Int32, 500
    d = sp.decode(p.SerializeToString())
    by = {x.name: x for x in d.metrics}
    assert sp.metric_value(by["Hist"]) == [1, -2, 300]
    assert sp.metric_value(by["Flags"]) == [True, False, True]
    assert sp.metric_value(by["Names"]) == ["EX1", "TC1"]
    assert sp.metric_value(by["Table"]) == {
        "columns": ["ecu", "load"],
        "rows": [["engine", 0.7]],
    }
    assert sp.quality(by["Stale"]) == "stale"
    assert sp.quality(by["Hist"]) == "good"


def test_command_encoding_round_trips():
    raw = sp.encode(
        [{"name": "Safety/Hold", "value": "true", "datatype": "Boolean"}],
        timestamp=123,
    )
    p = pb.Payload()
    p.ParseFromString(raw)
    assert p.metrics[0].name == "Safety/Hold"
    assert p.metrics[0].datatype == pb.Boolean and p.metrics[0].boolean_value is True
    doc = sp.to_json(sp.decode(sp.encode([{"name": "Mode/Set", "value": "safe"}], timestamp=1)))
    assert doc["metrics"][0] == {
        "name": "Mode/Set",
        "timestamp": 1,
        "datatype": "String",
        "value": "safe",
    }
    task = sp.decode(sp.encode([{"name": "Task/Assign", "value": {"zone": "A"}}]))
    assert task.metrics[0].string_value == '{"zone": "A"}'
    reb = sp.decode(sp.rebirth_payload())
    assert reb.metrics[0].name == "Node Control/Rebirth" and reb.metrics[0].boolean_value


def test_coerce_refuses_what_does_not_fit():
    assert sp.coerce("3", pb.Int32) == 3
    assert sp.coerce(1.0, pb.Int64) == 1
    assert sp.coerce("off", pb.Boolean) is False
    try:
        sp.coerce(1.5, pb.Int32)
    except ValueError:
        pass
    else:
        raise AssertionError("1.5 is not a whole number")
    assert sp.datatype_for(True) == pb.Boolean
    assert sp.datatype_for(3) == pb.Int64
    assert sp.datatype_for(3.0) == pb.Double
    assert sp.datatype_for("x", "Float") == pb.Float
