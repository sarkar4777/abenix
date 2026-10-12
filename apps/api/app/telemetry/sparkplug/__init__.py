"""Sparkplug B topics and payloads, on top of the Eclipse Tahu protobuf definition."""

from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass
from typing import Any

from app.telemetry.sparkplug import sparkplug_b_pb2 as pb

Payload = pb.Payload
NAMESPACE = "spBv1.0"
MESSAGE_TYPES = (
    "NBIRTH",
    "NDEATH",
    "DBIRTH",
    "DDEATH",
    "NDATA",
    "DDATA",
    "NCMD",
    "DCMD",
)
REBIRTH_METRIC = "Node Control/Rebirth"
BDSEQ_METRIC = "bdSeq"

TYPE_NAMES = {v: k for k, v in pb.DataType.items()}
TYPE_IDS = dict(pb.DataType.items())

_INT_BITS = {1: 8, 2: 16, 3: 32}
_ARRAY_FMT = {
    22: "b",
    23: "h",
    24: "i",
    25: "q",
    26: "B",
    27: "H",
    28: "I",
    29: "Q",
    30: "f",
    31: "d",
    34: "q",
}
NUMERIC_TYPES = frozenset({1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13})


@dataclass(frozen=True)
class Topic:
    group: str
    message_type: str
    node: str
    device: str = ""
    host_id: str = ""

    @property
    def is_state(self) -> bool:
        return self.message_type == "STATE"


def parse_topic(topic: str) -> Topic | None:
    """spBv1.0/{group}/{type}/{node}[/{device}] or spBv1.0/STATE/{host}, None for anything else."""
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != NAMESPACE:
        return None
    if parts[1] == "STATE":
        return Topic(
            group="", message_type="STATE", node="", host_id="/".join(parts[2:])
        )
    if len(parts) < 4 or parts[2] not in MESSAGE_TYPES or not parts[3]:
        return None
    device = "/".join(parts[4:]) if len(parts) > 4 else ""
    if parts[2].startswith("D") and not device:
        return None
    return Topic(group=parts[1], message_type=parts[2], node=parts[3], device=device)


def decode(raw: bytes) -> Any:
    p = Payload()
    p.ParseFromString(raw)
    return p


def _signed(v: int, bits: int) -> int:
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >= 1 << (bits - 1) else v


def _array(dtype: int, raw: bytes) -> list[Any]:
    if dtype == 32:
        if len(raw) < 4:
            return []
        n = struct.unpack_from("<I", raw)[0]
        bits = raw[4:]
        return [
            bool(bits[i // 8] & (0x80 >> (i % 8)))
            for i in range(n)
            if i // 8 < len(bits)
        ]
    if dtype == 33:
        return [s.decode("utf-8", "replace") for s in raw.split(b"\x00") if s]
    fmt = _ARRAY_FMT.get(dtype)
    if not fmt:
        return []
    size = struct.calcsize(fmt)
    usable = len(raw) - len(raw) % size
    return list(struct.unpack("<" + fmt * (usable // size), raw[:usable]))


def _dataset(ds: Any) -> dict[str, Any]:
    rows = []
    for r in ds.rows:
        row = []
        for el in r.elements:
            kind = el.WhichOneof("value")
            row.append(
                getattr(el, kind) if kind and kind != "extension_value" else None
            )
        rows.append(row)
    return {"columns": list(ds.columns), "rows": rows}


def metric_value(m: Any, dtype: int | None = None) -> Any:
    """The plain Python value of a metric. dtype comes from the birth when DATA leaves it out."""
    if m.is_null:
        return None
    dt = m.datatype or dtype or 0
    kind = m.WhichOneof("value")
    if kind is None:
        return None
    if kind == "int_value":
        bits = _INT_BITS.get(dt)
        return _signed(m.int_value, bits) if bits else m.int_value
    if kind == "long_value":
        return _signed(m.long_value, 64) if dt == 4 else m.long_value
    if kind == "float_value":
        return float(m.float_value)
    if kind == "double_value":
        return m.double_value
    if kind == "boolean_value":
        return m.boolean_value
    if kind == "string_value":
        return m.string_value
    if kind == "bytes_value":
        if dt in _ARRAY_FMT or dt in (32, 33):
            return _array(dt, m.bytes_value)
        return m.bytes_value.hex()
    if kind == "dataset_value":
        return _dataset(m.dataset_value)
    if kind == "template_value":
        return {t.name: metric_value(t) for t in m.template_value.metrics if t.name}
    return None


def quality(m: Any) -> str:
    """good, bad or stale, from the metric's Quality property (192 good, 500 stale)."""
    if m.is_null:
        return "bad"
    if m.HasField("properties"):
        props = m.properties
        for i, k in enumerate(props.keys):
            if k.lower() == "quality" and i < len(props.values):
                pv = props.values[i]
                code = (
                    pv.int_value
                    if pv.WhichOneof("value") == "int_value"
                    else pv.long_value
                )
                if code == 192:
                    return "good"
                if code == 500:
                    return "stale"
                return "bad"
    return "good"


def datatype_for(value: Any, hint: str | int | None = None) -> int:
    """A Sparkplug datatype for a value, keeping the birth's type when there is one."""
    if isinstance(hint, int) and not isinstance(hint, bool) and hint:
        return hint
    if isinstance(hint, str) and TYPE_IDS.get(hint):
        return TYPE_IDS[hint]
    if isinstance(value, bool):
        return TYPE_IDS["Boolean"]
    if isinstance(value, int):
        return TYPE_IDS["Int64"]
    if isinstance(value, float):
        return TYPE_IDS["Double"]
    return TYPE_IDS["String"]


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def coerce(value: Any, dtype: int) -> Any:
    """The value as it will be sent. Raises ValueError when it does not fit the type."""
    if value is None:
        return None
    if dtype in (1, 2, 3, 4, 5, 6, 7, 8, 13):
        if isinstance(value, bool):
            return int(value)
        f = float(value)
        if f != int(f):
            raise ValueError("a whole number is needed")
        return int(f)
    if dtype in (9, 10):
        return float(value)
    if dtype == 11:
        return _as_bool(value)
    if dtype == 17:
        return value if isinstance(value, bytes) else bytes.fromhex(str(value))
    return value if isinstance(value, str) else json.dumps(value)


def set_value(m: Any, dtype: int, value: Any) -> None:
    m.datatype = dtype
    if value is None:
        m.is_null = True
        return
    value = coerce(value, dtype)
    if dtype in (1, 2, 3, 5, 6, 7):
        m.int_value = value & 0xFFFFFFFF
    elif dtype in (4, 8, 13):
        m.long_value = value & 0xFFFFFFFFFFFFFFFF
    elif dtype == 9:
        m.float_value = value
    elif dtype == 10:
        m.double_value = value
    elif dtype == 11:
        m.boolean_value = value
    elif dtype == 17:
        m.bytes_value = value
    else:
        m.string_value = value


def encode(
    metrics: list[dict[str, Any]],
    *,
    seq: int | None = None,
    timestamp: int | None = None,
) -> bytes:
    """metrics: [{name?, alias?, value, datatype?, timestamp?}]."""
    p = Payload()
    p.timestamp = timestamp if timestamp is not None else int(time.time() * 1000)
    if seq is not None:
        p.seq = seq
    for spec in metrics:
        m = p.metrics.add()
        if spec.get("name") is not None:
            m.name = spec["name"]
        if spec.get("alias") is not None:
            m.alias = int(spec["alias"])
        m.timestamp = int(spec.get("timestamp") or p.timestamp)
        set_value(
            m, datatype_for(spec.get("value"), spec.get("datatype")), spec.get("value")
        )
    return p.SerializeToString()


def command_topic(group: str, node: str, device: str = "") -> str:
    if device:
        return f"{NAMESPACE}/{group}/DCMD/{node}/{device}"
    return f"{NAMESPACE}/{group}/NCMD/{node}"


def rebirth_payload() -> bytes:
    return encode([{"name": REBIRTH_METRIC, "value": True, "datatype": "Boolean"}])


def to_json(p: Any) -> dict[str, Any]:
    """A readable form of a payload, used for command previews."""
    out: dict[str, Any] = {"timestamp": p.timestamp, "metrics": []}
    if p.HasField("seq"):
        out["seq"] = p.seq
    for m in p.metrics:
        v = metric_value(m)
        out["metrics"].append(
            {
                "name": m.name,
                "timestamp": m.timestamp,
                "datatype": TYPE_NAMES.get(m.datatype, str(m.datatype)),
                "value": v.hex() if isinstance(v, bytes) else v,
            }
        )
    return out
